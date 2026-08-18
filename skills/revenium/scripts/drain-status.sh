#!/usr/bin/env bash
# drain-status.sh — Phase 32 Plan 03 (C-11/D-13): the machine-readable
# answer to "has the legacy completions path finished with every session it
# owns". This is the gate hermes-report.sh reads before honouring a request
# to disable the legacy completions stage — see that script's own comment on
# why the composition of D-09 (new path skips sessions already in the legacy
# ledger) and D-11 (legacy path retained, disabled only at cutover) silently
# under-bills a straddling session without this check.
#
# set -euo pipefail (matches guardrail-check.sh's own reasoning, restated
# here): this script's output decides whether billing responsibility can
# transfer between two code paths. Writing a stale or inconsistent status
# file is worse than writing none.
#
# Reads exactly two LOCAL sources and makes ZERO HTTP requests: the frozen
# legacy ledger (LEDGER_FILE) and state.db (read-only URI mode). No
# `revenium` CLI invocation appears anywhere in this script — the per-tick
# request bound this stage adds to cron.sh is exactly zero.
#
# Exit codes (stable for scripting):
#   0   drained — every session id in the ledger has reached a terminal
#       boundary AND gone quiet for REVENIUM_DRAIN_QUIET_TICKS consecutive
#       checks (C-11).
#   10  not yet drained — at least one tracked session has not (either
#       still open, still within the settle window, or not yet quiet long
#       enough).
#   1   could not determine — state.db could not be read. UNKNOWN always
#       resolves to NOT drained (this script never exits 0 on doubt); the
#       distinct exit code exists so a caller can tell "still draining"
#       apart from "the check itself is broken".

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

QUIET_UNCHANGED=false
JSON_MODE=false
for arg in "$@"; do
  case "${arg}" in
    --quiet-unchanged) QUIET_UNCHANGED=true ;;
    --json) JSON_MODE=true ;;
    *) ;;
  esac
done

# Capture the PREVIOUS document's `drained` verdict before recomputing, so
# the --quiet-unchanged gate below can compare against it once the fresh
# computation has landed. Fail-open to "" (treated as "unknown", so the
# first-ever run is never silently suppressed).
PREV_DRAINED=""
if [[ -f "${DRAIN_STATUS_FILE}" ]]; then
  PREV_DRAINED=$(DRAIN_STATUS_FILE="${DRAIN_STATUS_FILE}" python3 - <<'PY' 2>/dev/null || true
import json, os
try:
    d = json.load(open(os.environ['DRAIN_STATUS_FILE']))
    print('true' if d.get('drained') is True else 'false')
except Exception:
    print('')
PY
)
fi

# The entire computation lives in one python3 heredoc: parse the ledger,
# query state.db, carry the previous quiet-tick map forward, write the
# status document atomically, and print a small machine-readable summary on
# stdout for the bash side to gate the exit code and banner on. The heredoc
# ALWAYS exits 0 — under `set -euo pipefail` a non-zero exit here would abort
# this script via the `COMPUTE_OUTPUT=$(...)` assignment before the DETERMINED=
# line could even be parsed, which is exactly the "abort instead of writing a
# clear not-determined verdict" failure mode this script exists to avoid.
# Genuine failure (an unreadable state.db) is reported THROUGH the printed
# DETERMINED=false line, not through this heredoc's own exit status.
COMPUTE_OUTPUT=$(
  LEDGER_FILE="${LEDGER_FILE}" \
  STATE_DB="${STATE_DB}" \
  DRAIN_STATUS_FILE="${DRAIN_STATUS_FILE}" \
  REVENIUM_CRON_SETTLE_SECONDS="${REVENIUM_CRON_SETTLE_SECONDS}" \
  REVENIUM_DRAIN_QUIET_TICKS="${REVENIUM_DRAIN_QUIET_TICKS}" \
  REVENIUM_DRAIN_STALE_SECONDS="${REVENIUM_DRAIN_STALE_SECONDS}" \
  MARKER_RETENTION_DAYS="${MARKER_RETENTION_DAYS}" \
  PENDING_CAP="50" \
  python3 - <<'PY'
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone

ledger_file = os.environ.get('LEDGER_FILE', '')
state_db = os.environ.get('STATE_DB', '')
status_file_path = os.environ.get('DRAIN_STATUS_FILE', '')

try:
    settle_seconds = float(os.environ.get('REVENIUM_CRON_SETTLE_SECONDS', '600'))
except (TypeError, ValueError):
    settle_seconds = 600.0
try:
    quiet_ticks_required = int(os.environ.get('REVENIUM_DRAIN_QUIET_TICKS', '15'))
except (TypeError, ValueError):
    quiet_ticks_required = 15
if quiet_ticks_required < 1:
    quiet_ticks_required = 1
try:
    retention_days = int(os.environ.get('MARKER_RETENTION_DAYS', '30'))
except (TypeError, ValueError):
    retention_days = 30
try:
    pending_cap = int(os.environ.get('PENDING_CAP', '50'))
except (TypeError, ValueError):
    pending_cap = 50

# quick-260818-f1g (STALE-01..07): staleness threshold. A configured value
# <= 0 disables the staleness route entirely (pre-change behaviour,
# STALE-05's opt-out); otherwise the EFFECTIVE seconds are floored at
# settle_seconds + 86400 so a session inside the deliberate metering-deferral
# window can never be judged stale (STALE-05/AX-S19). Both the configured
# and effective numbers are reported in the status document -- see
# EXTRA_DOC_FIELDS below.
try:
    stale_seconds_configured = float(os.environ.get('REVENIUM_DRAIN_STALE_SECONDS', '604800'))
except (TypeError, ValueError):
    stale_seconds_configured = 604800.0
if stale_seconds_configured <= 0:
    stale_enabled = False
    stale_seconds_effective = 0.0
else:
    stale_enabled = True
    stale_seconds_effective = max(stale_seconds_configured, settle_seconds + 86400.0)

now = time.time()
retention_cutoff_seconds = retention_days * 86400

# quick-260818-f1g: additive status-document fields, populated progressively
# as facts become known so an early fail-closed _finish() call carries
# whatever was already established at that point -- never a stale/wrong
# value, and the two early fail-closed paths (ledger unreadable, state.db
# unreadable) end up with `legacyRetainedSids` ABSENT, since that key is
# only ever set once the main per-session loop completes below (STALE-07:
# "those paths report drained: false, so there is nothing to carve out of").
# `_finish()` merges this dict in, guarded so it can never overwrite one of
# the pre-existing document keys.
EXTRA_DOC_FIELDS = {
    'staleSecondsConfigured': stale_seconds_configured,
    'staleSecondsEffective': stale_seconds_effective,
    'staleEnabled': stale_enabled,
}

# C-11's muid shapes: a real muid is 13-hex-ms-ts + 20-hex-random = 33
# lowercase hex chars (classifier.py's _muid); the zero-marker fallback
# writes a synthetic "unclassified-<digits>" muid (hermes-report.sh). Either
# can be the LAST field of a v2 ledger line. Recognising both by pattern —
# rather than assuming a fixed field COUNT — is what lets this parser handle
# a colon-bearing (namespaced `agent:<profile>:...`) sid correctly: sid
# itself is never assumed to be colon-free.
_MUID_RE = re.compile(r'^([0-9a-f]{33}|unclassified-\d+)$')


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _write_atomic(path, doc):
    if not path:
        return
    d = os.path.dirname(path) or '.'
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return
    try:
        fd, tmp_path = tempfile.mkstemp(dir=d, prefix='.drain-status-', suffix='.tmp')
    except OSError:
        return
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(json.dumps(doc, indent=2, sort_keys=True) + '\n')
        os.replace(tmp_path, path)
    except OSError:
        pass
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        except NameError:
            pass


def _parse_ledger_line(line):
    """Return (sid, ts) for a HERMES: line, (sid, None) for a HERMES: line
    whose sid split succeeded but whose timestamp field did not parse (route
    1a -- attributable corruption, quick-260818-f1g STALE-06/AX-S26), or None
    for the three UNATTRIBUTABLE rejection shapes (not HERMES:-prefixed, too
    few fields to split a sid at all, or an empty sid) -- those three keep
    resolving to "skip this line", unchanged. Parses from the RIGHT so a
    colon-bearing sid is never mis-split: the last field is either a v2 muid
    (matched by _MUID_RE, in which case the two fields before it are
    total_tokens and ts) or, for a v1 line (no muid) or an unrecognised
    trailing field, the last TWO fields are treated as total_tokens and ts
    and everything before them is the sid."""
    if not line.startswith('HERMES:'):
        return None
    parts = line[len('HERMES:'):].split(':')
    if len(parts) >= 4 and _MUID_RE.match(parts[-1]):
        sid = ':'.join(parts[:-3])
        ts_str = parts[-2]
    elif len(parts) >= 2:
        sid = ':'.join(parts[:-2])
        ts_str = parts[-1]
    else:
        return None
    if not sid:
        return None
    try:
        ts = float(ts_str)
    except ValueError:
        # The sid IS recoverable here -- the split already succeeded. Return
        # it with ts=None so the caller can refuse staleness for exactly
        # this sid (route 1a) rather than treating the line as unattributable.
        return sid, None
    return sid, ts


def _finish(determined, drained, ledger_tracked, drained_count, pending_count,
            pending, quiet_ticks, session_last_seen_ts, reason=None):
    doc = {
        'lastChecked': _iso(now),
        'ledgerSessionsTracked': ledger_tracked,
        'drainedCount': drained_count,
        'pendingCount': pending_count,
        'pending': pending,
        'quietTicks': quiet_ticks,
        'sessionLastSeenTs': session_last_seen_ts,
        'drained': drained,
        'determined': determined,
    }
    if reason:
        doc['reason'] = reason
    # quick-260818-f1g: additive-only merge -- never lets EXTRA_DOC_FIELDS
    # overwrite one of the pre-existing keys above.
    for _k, _v in EXTRA_DOC_FIELDS.items():
        if _k not in doc:
            doc[_k] = _v
    _write_atomic(status_file_path, doc)
    print(f"DETERMINED={'true' if determined else 'false'}")
    print(f"DRAINED={'true' if drained else 'false'}")
    print(f"LEDGER_SESSIONS_TRACKED={ledger_tracked}")
    print(f"DRAINED_COUNT={drained_count}")
    print(f"PENDING_COUNT={pending_count}")
    sys.exit(0)


try:
    # --- 1. Parse the frozen legacy ledger: per-sid MAX ts. ---------------
    # quick-260818-f1g (STALE-06, AX-S11/AX-S26/AX-S27): ledger_unparsed_lines
    # counts every REJECTED non-empty line (both the unattributable None
    # shape and the attributable (sid, None) shape); ledger_ts_unparsed_sids
    # collects only the attributable sids, which REFUSES staleness for
    # exactly those sids in the terminal computation below (route 1a).
    # Route 1b (unattributable corruption) does not refuse anything here --
    # it widens the retention carve-out later, once ledger_unparsed_lines is
    # known to be > 0.
    sid_max_ts = {}
    ledger_unparsed_lines = 0
    ledger_ts_unparsed_sids = set()
    try:
        with open(ledger_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.rstrip('\n')
                if not line:
                    continue
                parsed = _parse_ledger_line(line)
                if parsed is None:
                    ledger_unparsed_lines += 1
                    continue
                sid, ts = parsed
                if ts is None:
                    ledger_unparsed_lines += 1
                    ledger_ts_unparsed_sids.add(sid)
                    continue
                if sid not in sid_max_ts or ts > sid_max_ts[sid]:
                    sid_max_ts[sid] = ts
    except FileNotFoundError:
        sid_max_ts = {}
    except OSError:
        # An existing-but-unreadable ledger is the same "cannot determine"
        # shape as an unreadable state.db -- never assume drained on doubt.
        _finish(False, False, 0, 0, 0, [], {}, {},
                reason='legacy ledger unreadable')

    EXTRA_DOC_FIELDS['ledgerUnparsedLines'] = ledger_unparsed_lines

    # Which legacy-owned sessions are STILL OPEN? This must be answered
    # BEFORE the retention filter below, not after.
    #
    # An earlier revision filtered on ledger age alone, reasoning that a
    # session whose newest ledger line predates the retention window is
    # "drained by definition". That is only true when the session has also
    # ENDED. A long-lived session -- a gateway conversation, or one that
    # resumed after a quiet spell -- can carry an ancient newest-ledger-line
    # and still be open and still be spending. Dropping it here would hide
    # it from the terminal check below, report the gate drained, and let an
    # operator disable legacy completions while it is live. Its subsequent
    # usage would then be skipped by BOTH reporters: the legacy path because
    # it is disabled, the event path because D-09 skips any session already
    # present in the legacy ledger. That is a silent, permanent under-bill --
    # the exact failure D-13 exists to prevent, re-entering through the
    # retention filter.
    #
    # No `IN (...)` clause: open sessions are few while the historical ledger
    # is large, so selecting the open set outright is both cheaper and immune
    # to SQLite's bound-variable limit.
    # quick-260818-f1g (STALE-06/AX-S08): the activity read rides INSIDE this
    # SAME open-session query -- same connection, same read-only URI, no new
    # file/process/query -- so test_drain_status_adds_a_cron_stage_but_no_request
    # and test_cron_tick_request_bound stay untouched. `PRAGMA table_info`
    # answers whether `last_activity_at` exists on THIS state.db; every
    # fixture in this repo's test suite lacks the column (AX-S08's
    # ledger-only branch), while a real Hermes state.db declares it REAL at
    # ordinal 46.
    open_sids = set()
    last_activity_by_sid = {}
    activity_column_present = False
    if state_db and os.path.isfile(state_db):
        try:
            uri = f"file:{state_db}?mode=ro"
            with sqlite3.connect(uri, uri=True) as conn:
                cols = [r[1] for r in conn.execute('PRAGMA table_info(sessions)')]
                activity_column_present = 'last_activity_at' in cols
                if activity_column_present:
                    for row in conn.execute(
                            'SELECT id, last_activity_at FROM sessions WHERE ended_at IS NULL'):
                        row_sid = str(row[0])
                        open_sids.add(row_sid)
                        if row[1] is not None:
                            last_activity_by_sid[row_sid] = row[1]
                else:
                    for row in conn.execute(
                            'SELECT id FROM sessions WHERE ended_at IS NULL'):
                        open_sids.add(str(row[0]))
        except Exception:
            # A db that exists but cannot be queried leaves openness
            # indeterminate for every session. Never assume drained on doubt.
            pending_preview = sorted(sid_max_ts.items(), key=lambda kv: kv[1])[:pending_cap]
            _finish(False, False, len(sid_max_ts), 0, len(sid_max_ts),
                    [{'sid': sid, 'ageSeconds': round(now - ts, 1)}
                     for sid, ts in pending_preview],
                    {}, {}, reason='state.db unreadable')

    EXTRA_DOC_FIELDS['activityColumnPresent'] = activity_column_present

    # C-11: a session whose newest ledger line is older than the retention
    # window is not tracked individually -- that keeps the quiet-tick map
    # bounded on a fleet ledger holding thousands of historical sessions.
    # A still-open session is force-included regardless of its ledger age,
    # per the reasoning above; the bound is preserved because the carve-out
    # is sized by the open-session count, not by ledger history.
    tracked = {
        sid: ts for sid, ts in sid_max_ts.items()
        if (now - ts) < retention_cutoff_seconds or sid in open_sids
    }

    # --- 2. Query state.db (read-only URI, ONE query for every tracked
    # sid) for ended_at. A MISSING db file means every sid is legitimately
    # absent (C-11's OR branch) -- not an error. A db file that EXISTS but
    # cannot be queried (corrupt) is genuinely indeterminate. ---------------
    ended_at_by_sid = {}
    db_readable = True
    if tracked and state_db and os.path.isfile(state_db):
        try:
            uri = f"file:{state_db}?mode=ro"
            with sqlite3.connect(uri, uri=True) as conn:
                placeholders = ','.join('?' for _ in tracked)
                cur = conn.execute(
                    f"SELECT id, ended_at FROM sessions WHERE id IN ({placeholders})",
                    list(tracked.keys()),
                )
                for row_sid, ended_at in cur:
                    ended_at_by_sid[str(row_sid)] = ended_at
        except Exception:
            db_readable = False

    if not db_readable:
        # Cannot determine terminal status for ANY tracked session -- the
        # whole run is indeterminate. Still write a valid, informative
        # document (ledger-only facts are trustworthy; only the DB-derived
        # terminal check is in doubt).
        pending_preview = sorted(tracked.items(), key=lambda kv: kv[1])[:pending_cap]
        pending_list = [
            {'sid': sid, 'ageSeconds': round(now - ts, 1)}
            for sid, ts in pending_preview
        ]
        _finish(False, False, len(tracked), 0, len(tracked), pending_list,
                {}, {}, reason='state.db unreadable')

    # --- 3. Carry the previous run's quiet-tick map forward. ---------------
    prev_quiet_ticks = {}
    prev_last_seen_ts = {}
    try:
        prev_doc = json.load(open(status_file_path, 'r', encoding='utf-8'))
        if isinstance(prev_doc.get('quietTicks'), dict):
            prev_quiet_ticks = prev_doc['quietTicks']
        if isinstance(prev_doc.get('sessionLastSeenTs'), dict):
            prev_last_seen_ts = prev_doc['sessionLastSeenTs']
    except Exception:
        pass

    quiet_ticks = {}
    session_last_seen_ts = {}
    pending = []
    drained_count = 0
    stale_drained_count = 0
    stale_without_activity_signal = 0
    stale_granted_sids = set()
    stale_granted_no_activity_sids = set()

    # --- 4. Precedence: staleness applies to exactly ONE branch -----------
    #   sid not in state.db at all  -> terminal = True             UNCHANGED
    #   ended_at is not None        -> terminal = past settle       UNCHANGED
    #   ended_at IS NULL            -> terminal = stale             THE ONLY
    #                                                                NEW ROUTE
    # (quick-260818-f1g STALE-01..07; the third branch was unconditionally
    # False before this change -- drain-status.sh:350 in the pre-change file.)
    for sid, max_ts in tracked.items():
        prev_ts = prev_last_seen_ts.get(sid)
        prev_count = prev_quiet_ticks.get(sid, 0)
        if not isinstance(prev_count, int):
            prev_count = 0
        try:
            unchanged = prev_ts is not None and float(prev_ts) == max_ts
        except (TypeError, ValueError):
            unchanged = False
        new_count = (prev_count + 1) if unchanged else 0
        quiet_ticks[sid] = new_count
        session_last_seen_ts[sid] = max_ts

        stale_route_hit = False
        if sid not in ended_at_by_sid:
            # Absent from state.db entirely -- terminal by the OR branch.
            terminal = True
        else:
            ended_at = ended_at_by_sid[sid]
            if ended_at is not None:
                # Staleness must NEVER override the settle window
                # (STALE-03/AX-S14): a session that ended recently is
                # governed exclusively by this branch, unchanged.
                terminal = (now - float(ended_at)) >= settle_seconds
            else:
                # THE ONLY NEW ROUTE. last_seen = max(ledger_max_ts,
                # last_activity_at), started_at excluded (see the plan's
                # "Why this is a closure, not a narrowing"). Staleness is
                # REFUSED for this sid when its activity value is present
                # but unparseable (AX-S09), or when its own newest ledger
                # line failed to parse a timestamp (route 1a, AX-S26). A
                # future-dated activity or ledger value simply makes the age
                # negative -- never stale, with no special-casing (AX-S10).
                last_seen = max_ts
                has_activity_signal = False
                refused = sid in ledger_ts_unparsed_sids
                if sid in last_activity_by_sid:
                    try:
                        activity_ts = float(last_activity_by_sid[sid])
                        has_activity_signal = True
                        if activity_ts > last_seen:
                            last_seen = activity_ts
                    except (TypeError, ValueError):
                        refused = True
                terminal = (
                    stale_enabled
                    and not refused
                    and (now - last_seen) >= stale_seconds_effective
                )
                if terminal:
                    stale_route_hit = True
                    stale_granted_sids.add(sid)
                    if not has_activity_signal:
                        stale_without_activity_signal += 1
                        stale_granted_no_activity_sids.add(sid)

        # Quiet-tick composition is UNCHANGED: staleness grants `terminal`,
        # never `drained` (STALE-01, AX-S18).
        is_drained = terminal and new_count >= quiet_ticks_required
        if is_drained:
            drained_count += 1
            if stale_route_hit:
                stale_drained_count += 1
        else:
            pending.append((sid, max_ts, new_count, terminal, stale_route_hit))

    pending.sort(key=lambda t: t[1])
    pending_capped = pending[:pending_cap]
    pending_list = [
        {
            'sid': sid,
            'ageSeconds': round(now - ts, 1),
            'quietTicks': qt,
            'terminal': term,
            'stale': stale_flag,
        }
        for sid, ts, qt, term, stale_flag in pending_capped
    ]

    ledger_tracked = len(tracked)
    pending_count = len(pending)
    drained = (pending_count == 0)

    # --- 5. legacyRetainedSids: the per-session carve-out (STALE-07,
    # AX-S25/S27/S28/S29/S30). Suppression defaults to APPLY; retention is
    # the explicit carve-out -- a sid absent from this list (including one
    # that has never appeared in the ledger at all) is still suppressed.
    # Route 1b (unattributable ledger corruption): when ANY line failed to
    # parse without a recoverable sid, EVERY staleness-granted sid is
    # retained this run, widening the carve-out rather than closing the
    # gate (STALE-06/AX-S27). Otherwise only the sids with no corroborating
    # activity value are retained (AX-S07).
    if ledger_unparsed_lines > 0:
        legacy_retained_sids = sorted(stale_granted_sids)
    else:
        legacy_retained_sids = sorted(stale_granted_no_activity_sids)

    EXTRA_DOC_FIELDS['staleDrainedCount'] = stale_drained_count
    EXTRA_DOC_FIELDS['staleWithoutActivitySignal'] = stale_without_activity_signal
    EXTRA_DOC_FIELDS['legacyRetainedSids'] = legacy_retained_sids

    _finish(True, drained, ledger_tracked, drained_count, pending_count,
            pending_list, quiet_ticks, session_last_seen_ts)
except SystemExit:
    raise
except Exception as exc:
    # Absolute last resort -- never let an unanticipated exception escape
    # with a non-zero exit (which would abort the OUTER bash script under
    # set -e before it could read DETERMINED=). Report not-determined.
    print(f"DETERMINED=false", file=sys.stdout)
    print(f"DRAINED=false", file=sys.stdout)
    print(f"LEDGER_SESSIONS_TRACKED=0", file=sys.stdout)
    print(f"DRAINED_COUNT=0", file=sys.stdout)
    print(f"PENDING_COUNT=0", file=sys.stdout)
    sys.exit(0)
PY
)

DETERMINED=$(echo "${COMPUTE_OUTPUT}" | sed -n 's/^DETERMINED=//p' | head -1)
DRAINED=$(echo "${COMPUTE_OUTPUT}" | sed -n 's/^DRAINED=//p' | head -1)
LEDGER_SESSIONS_TRACKED=$(echo "${COMPUTE_OUTPUT}" | sed -n 's/^LEDGER_SESSIONS_TRACKED=//p' | head -1)
DRAINED_COUNT=$(echo "${COMPUTE_OUTPUT}" | sed -n 's/^DRAINED_COUNT=//p' | head -1)
PENDING_COUNT=$(echo "${COMPUTE_OUTPUT}" | sed -n 's/^PENDING_COUNT=//p' | head -1)

case "${DETERMINED}" in
  true|false) ;;
  *) DETERMINED=false ;;
esac
case "${DRAINED}" in
  true|false) ;;
  *) DRAINED=false ;;
esac
[[ "${LEDGER_SESSIONS_TRACKED}" =~ ^[0-9]+$ ]] || LEDGER_SESSIONS_TRACKED=0
[[ "${DRAINED_COUNT}" =~ ^[0-9]+$ ]] || DRAINED_COUNT=0
[[ "${PENDING_COUNT}" =~ ^[0-9]+$ ]] || PENDING_COUNT=0

EXIT_CODE=10
if [[ "${DETERMINED}" != "true" ]]; then
  EXIT_CODE=1
elif [[ "${DRAINED}" == "true" ]]; then
  EXIT_CODE=0
fi

if [[ "${JSON_MODE}" == "true" ]]; then
  cat "${DRAIN_STATUS_FILE}" 2>/dev/null || echo '{}'
  exit "${EXIT_CODE}"
fi

# quick-260818-f1g: banner-only enrichment, read from the JSON document
# already written above rather than through a new `_finish` KEY=value line
# (that channel's shape is contractual — drain-status.sh:391-407's bash-side
# parsing must not move). Fail-open to zero/empty on any read error; this is
# purely cosmetic and must never affect EXIT_CODE.
STALE_DRAINED_COUNT=0
STALE_RETAINED_COUNT=0
STALE_SECONDS_EFFECTIVE_DAYS=""
if [[ -f "${DRAIN_STATUS_FILE}" ]]; then
  _stale_banner_output=$(DRAIN_STATUS_FILE="${DRAIN_STATUS_FILE}" python3 - <<'PY' 2>/dev/null
import json, os
try:
    d = json.load(open(os.environ['DRAIN_STATUS_FILE']))
except Exception:
    print('SDC=0')
    print('RETAINED=0')
    print('EFF_DAYS=')
else:
    sdc = d.get('staleDrainedCount')
    retained = d.get('legacyRetainedSids')
    eff = d.get('staleSecondsEffective')
    print(f"SDC={sdc if isinstance(sdc, int) else 0}")
    print(f"RETAINED={len(retained) if isinstance(retained, list) else 0}")
    print(f"EFF_DAYS={(eff / 86400.0):.1f}" if isinstance(eff, (int, float)) else "EFF_DAYS=")
PY
) || true
  STALE_DRAINED_COUNT=$(printf '%s' "${_stale_banner_output}" | sed -n 's/^SDC=//p' | head -1)
  STALE_RETAINED_COUNT=$(printf '%s' "${_stale_banner_output}" | sed -n 's/^RETAINED=//p' | head -1)
  STALE_SECONDS_EFFECTIVE_DAYS=$(printf '%s' "${_stale_banner_output}" | sed -n 's/^EFF_DAYS=//p' | head -1)
fi
[[ "${STALE_DRAINED_COUNT}" =~ ^[0-9]+$ ]] || STALE_DRAINED_COUNT=0
[[ "${STALE_RETAINED_COUNT}" =~ ^[0-9]+$ ]] || STALE_RETAINED_COUNT=0

CHANGED=true
if [[ "${DRAINED}" == "${PREV_DRAINED}" ]]; then
  CHANGED=false
fi

if [[ "${QUIET_UNCHANGED}" == "true" && "${CHANGED}" == "false" ]]; then
  : # suppressed: quiet cron tick, verdict unchanged from disk
else
  echo "Revenium legacy-completions drain status"
  echo "─────────────────────────────────────────"
  if [[ "${DETERMINED}" != "true" ]]; then
    echo "? could not determine — state.db (or the legacy ledger) could not be read."
    echo "  Treating as NOT drained (T-32-14: unknown never resolves to drained)."
  elif [[ "${DRAINED}" == "true" ]]; then
    echo "✓ drained — ${LEDGER_SESSIONS_TRACKED} tracked session(s), all ${DRAINED_COUNT} terminal and quiet."
    echo "  The legacy completions path may now be disabled (REVENIUM_LEGACY_COMPLETIONS=disabled)."
    if [[ "${STALE_DRAINED_COUNT}" -gt 0 ]]; then
      echo "  ${STALE_DRAINED_COUNT} of those reached terminal by staleness (no activity for ~${STALE_SECONDS_EFFECTIVE_DAYS:-?}d) rather than by ending; ${STALE_RETAINED_COUNT} of those stay on legacy."
      echo "  drained means \"legacy is off for everything except the sessions it still owes\" — the retained list, not this verdict, is the real measure of cutover progress."
    fi
  else
    echo "✗ not drained — ${PENDING_COUNT} of ${LEDGER_SESSIONS_TRACKED} tracked session(s) still pending."
    echo "  A disable request will be refused (and completions kept metering) until this reports drained."
  fi
  echo "  Full status: ${DRAIN_STATUS_FILE}"
fi

exit "${EXIT_CODE}"
