#!/usr/bin/env bash
# Prune stale marker JSONL files from MARKERS_DIR.
# Staleness is determined by the latest ledger row timestamp for the session
# (field 4 of HERMES:<sid>:<total_tokens>:<unix_ts>:<muid> lines). If no
# ledger entry exists for a sid (orphan marker), file mtime is used instead.
# Safe to run manually at any time; NOT wired into cron (D-28).
#
# Phase 32 (D-15): also prunes the two per-session JSONL spool directories —
# the new event spool (EVENT_SPOOL_DIR) and the pre-existing tool-event spool
# (TOOL_EVENTS_DIR, which this script had NEVER referenced before this
# change) — and the new api_request_id-keyed ledger (EVENT_LEDGER_FILE). All
# four passes share the same lock, the same MARKER_RETENTION_DAYS preflight,
# and the same --dry-run semantics. The frozen legacy HERMES: ledger
# (LEDGER_FILE) is never touched by any of the new passes.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

# ---------------------------------------------------------------------------
# Flag parsing
# ---------------------------------------------------------------------------
DRY_RUN=false
for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=true ;;
    *) echo "Unknown flag: ${arg}" >&2; echo "Usage: $(basename "${BASH_SOURCE[0]}") [--dry-run]" >&2; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Preflight: validate MARKER_RETENTION_DAYS is an integer >= 1 (HARDEN-03).
# A value of 0 (or non-integer) would make every marker stale and trigger a
# mass-delete.  Warn loudly and exit 0 (no error mail from cron) instead of
# deleting anything.  Mirrors the lock-contention exit-0 branch below.
# ---------------------------------------------------------------------------
if ! [[ "${MARKER_RETENTION_DAYS}" =~ ^[0-9]+$ ]]; then
  warn "prune-markers: REVENIUM_MARKER_RETENTION_DAYS=${MARKER_RETENTION_DAYS} is invalid (must be an integer >= 1); refusing to prune"
  exit 0
fi
if [[ "${MARKER_RETENTION_DAYS}" -lt 1 ]]; then
  warn "prune-markers: REVENIUM_MARKER_RETENTION_DAYS=${MARKER_RETENTION_DAYS} is invalid (must be an integer >= 1); refusing to prune"
  exit 0
fi

# ---------------------------------------------------------------------------
# Acquire prune.lock (non-blocking) so two concurrent operator invocations
# cannot race on the same file set (D-29 / T-05-01).  Uses the same
# exec-fd + Python fcntl pattern as cron.sh (CRON-08 / D-12).
# ---------------------------------------------------------------------------
exec 9>"${PRUNE_LOCK_FILE}"
if ! python3 - <<'PY'
import fcntl, sys
try:
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
except (OSError, BlockingIOError):
    sys.exit(11)
PY
then
  warn "prior prune still active, skipping"
  exit 0
fi

# ---------------------------------------------------------------------------
# Main pruning logic: run Python, capture its stdout to a temp file so the
# child's exit code is observable, then feed each output line through info()
# so every log event lands in ${LOG_FILE} with the standard timestamp format.
# Never use bare echo for logged events.
#
# Previously used a process-substitution form which discards the child's exit
# code (pipefail does not apply to that form); a temp-file + prune_rc=$?
# pattern is used instead so a failed os.unlink propagates as a non-zero exit.
# ---------------------------------------------------------------------------
prune_out="$(mktemp)"
# Pass paths via env (bash 3.2 compatible — `${VAR@Q}` requires bash 4.4+;
# per project bash 3.2 convention for macOS stock /bin/bash). Single-
# quoted heredoc keeps the Python source verbatim.
# set +e so set -euo pipefail does not abort before prune_rc=$? is captured.
set +e
MARKERS_DIR_PY="${MARKERS_DIR}" \
LEDGER_FILE_PY="${LEDGER_FILE}" \
MARKER_RETENTION_DAYS_PY="${MARKER_RETENTION_DAYS}" \
DRY_RUN_PY="${DRY_RUN}" \
FLAG_DIRS_PY="${WARN_FLAGS_DIR}
${FALLBACK_WARN_FLAGS_DIR}
${OUTCOME_WARN_FLAGS_DIR}
${PROBE_WARN_FLAGS_DIR}" \
EVENT_SPOOL_DIR_PY="${EVENT_SPOOL_DIR}" \
TOOL_EVENTS_DIR_PY="${TOOL_EVENTS_DIR}" \
EVENT_LEDGER_FILE_PY="${EVENT_LEDGER_FILE}" \
TOOL_EVENTS_LEDGER_FILE_PY="${TOOL_EVENTS_LEDGER_FILE}" \
OWNERS_DIR_PY="${OWNERS_DIR}" \
STATE_DB_PY="${STATE_DB}" \
python3 - <<'PY' >"${prune_out}"
import os
import re
import sqlite3
import sys
import time

markers_dir    = os.environ['MARKERS_DIR_PY']
ledger_file    = os.environ['LEDGER_FILE_PY']
retention_days = int(os.environ['MARKER_RETENTION_DAYS_PY'])
dry_run        = os.environ['DRY_RUN_PY'] == "true"

cutoff_secs = retention_days * 86400


def ledger_last_ts(sid, ledger_path):
    """Return the unix timestamp (float) from the latest matching ledger row,
    or None if no row exists for this sid. Reads field 4 (0-indexed) from
    lines matching HERMES:<sid>: (D-26 primary path)."""
    try:
        with open(ledger_path, 'r', encoding='utf-8') as f:
            prefix = 'HERMES:' + sid + ':'
            last_ts = None
            for line in f:
                line = line.rstrip('\n')
                if not line.startswith(prefix):
                    continue
                parts = line.split(':')
                # v2: HERMES:<sid>:<total_tokens>:<unix_ts>:<muid>  (5 fields)
                # v1: HERMES:<sid>:<total_tokens>:<unix_ts>          (4 fields)
                if len(parts) >= 4:
                    try:
                        ts = float(parts[3])
                        if last_ts is None or ts > last_ts:
                            last_ts = ts
                    except ValueError:
                        pass
            return last_ts
    except FileNotFoundError:
        return None


def iso(ts):
    """Format a unix timestamp as ISO-8601 UTC for log lines."""
    import datetime
    return datetime.datetime.utcfromtimestamp(ts).strftime('%Y-%m-%dT%H:%M:%SZ')


scanned = 0
kept = 0
removed = 0

try:
    entries = sorted(os.listdir(markers_dir))
except FileNotFoundError:
    entries = []

for fname in entries:
    if not fname.endswith('.jsonl'):
        continue
    fpath = os.path.join(markers_dir, fname)
    if not os.path.isfile(fpath):
        continue

    scanned += 1
    sid = fname[:-len('.jsonl')]  # strip .jsonl suffix

    last_ts = ledger_last_ts(sid, ledger_file)
    if last_ts is not None:
        # Ledger-based stale check (D-26 primary path)
        age_secs  = time.time() - last_ts
        age_days  = age_secs / 86400
        ts_label  = iso(last_ts)
        ts_source = 'last_ledger_ts'
    else:
        # Orphan fallback: no ledger row — use file mtime (D-26 fallback)
        mtime     = os.path.getmtime(fpath)
        age_secs  = time.time() - mtime
        age_days  = age_secs / 86400
        ts_label  = iso(mtime)
        ts_source = 'mtime'

    if age_secs < cutoff_secs:
        kept += 1
        continue

    # File is stale — remove or report
    action = 'dry-run, would remove' if dry_run else 'removed'
    print(
        'prune: ' + action +
        ' sid=' + sid +
        ' marker=' + fname +
        ' ' + ts_source + '=' + ts_label +
        ' age_days=' + str(round(age_days, 1)),
        flush=True,
    )

    if not dry_run:
        try:
            os.unlink(fpath)
            removed += 1
        except OSError as exc:
            print('prune: ERROR removing ' + fname + ': ' + str(exc), flush=True)
            sys.exit(1)
    else:
        removed += 1  # count for dry-run summary

# ---------------------------------------------------------------------------
# quick-260813-wnz (LOG-01/D-05): second pass -- bound the once-per-
# (key, reason) flag directories (WARN_FLAGS_DIR, FALLBACK_WARN_FLAGS_DIR,
# OUTCOME_WARN_FLAGS_DIR, and PROBE_WARN_FLAGS_DIR, passed in
# newline-separated via FLAG_DIRS_PY) so the fix for each re-warn spam
# cannot itself become a new unbounded-growth path. Filtered to files ending
# in '.flag'; staleness is the flag's own mtime (a flag's mtime IS the
# moment we last warned, so it needs no ledger correlation, unlike a
# marker's mtime). Gated by the SAME MARKER_RETENTION_DAYS preflight and
# cutoff_secs the marker pass above uses; --dry-run honored identically.
#
# OUTCOME_WARN_FLAGS_DIR is Phase 39 D-02 (the deferred/wedged job-outcome
# gate). PROBE_WARN_FLAGS_DIR is a pre-existing omission from this list --
# not this phase's defect, but the identical leak, closed alongside here
# since this pass is already generic over the directory list and needs no
# other change to cover it.
# ---------------------------------------------------------------------------
flag_dirs = [d for d in os.environ.get('FLAG_DIRS_PY', '').split('\n') if d]

flags_scanned = 0
flags_kept = 0
flags_removed = 0

for flag_dir in flag_dirs:
    try:
        flag_entries = sorted(os.listdir(flag_dir))
    except FileNotFoundError:
        continue

    for fname in flag_entries:
        if not fname.endswith('.flag'):
            continue
        fpath = os.path.join(flag_dir, fname)
        if not os.path.isfile(fpath):
            continue

        flags_scanned += 1
        mtime = os.path.getmtime(fpath)
        age_secs = time.time() - mtime
        age_days = age_secs / 86400

        if age_secs < cutoff_secs:
            flags_kept += 1
            continue

        action = 'dry-run, would remove' if dry_run else 'removed'
        print(
            'prune: ' + action +
            ' dir=' + flag_dir +
            ' flag=' + fname +
            ' mtime=' + iso(mtime) +
            ' age_days=' + str(round(age_days, 1)),
            flush=True,
        )

        if not dry_run:
            try:
                os.unlink(fpath)
                flags_removed += 1
            except OSError as exc:
                print('prune: ERROR removing ' + fname + ': ' + str(exc), flush=True)
                sys.exit(1)
        else:
            flags_removed += 1  # count for dry-run summary

print(
    'prune: flags summary, scanned=' + str(flags_scanned) +
    ' kept=' + str(flags_kept) +
    ' removed=' + str(flags_removed),
    flush=True,
)

print(
    'prune: summary, scanned=' + str(scanned) +
    ' kept=' + str(kept) +
    ' removed=' + str(removed),
    flush=True,
)

# ---------------------------------------------------------------------------
# Phase 32 (D-15): third pass -- the two per-session JSONL spool directories,
# the new event spool (EVENT_SPOOL_DIR) and the pre-existing tool-event spool
# (TOOL_EVENTS_DIR). TOOL_EVENTS_DIR is in scope DELIBERATELY: this script has
# never referenced it before, so the spool-then-ship pattern D-01/D-03 copy
# has had NO retention at all until now -- the new event spool would have
# silently inherited that same unbounded-growth gap. Structure mirrors the
# marker pass above (ledger-timestamp staleness, mtime fallback for an
# orphan, the same cutoff_secs, the same --dry-run semantics) so the file
# reads as one idea repeated rather than three separate designs.
# ---------------------------------------------------------------------------

_NS_PREFIX_RE = re.compile(r'^agent:([^:]+):')


def _strip_ns_prefix(sid):
    """Strip a leading `agent:<profile>:` namespace prefix, if present.
    Mirrors api_event_spool.py's _NS_RE -- deliberately not shared code (see
    that module's own docstring on why the duplication is intentional)."""
    m = _NS_PREFIX_RE.match(sid)
    if m:
        return sid[m.end():]
    return sid


def tool_ledger_last_ts(sid, ledger_path):
    """Newest timestamp for sid in the TOOL: ledger. Colon-delimited
    (TOOL:<sid>:<tool_call_id>:<ts>) and safe to fixed-position-split on ':'
    because post_tool_call.sh strips structural colons from sid before ever
    ledgering it -- unlike the marker pass's HERMES: ledger, whose sid can be
    a colon-bearing agent:<profile>:... identifier."""
    try:
        with open(ledger_path, 'r', encoding='utf-8') as f:
            prefix = 'TOOL:' + sid + ':'
            last_ts = None
            for line in f:
                line = line.rstrip('\n')
                if not line.startswith(prefix):
                    continue
                parts = line.split(':')
                if len(parts) >= 4:
                    try:
                        ts = float(parts[3])
                        if last_ts is None or ts > last_ts:
                            last_ts = ts
                    except ValueError:
                        pass
            return last_ts
    except FileNotFoundError:
        return None


def event_ledger_last_ts(sid, ledger_path):
    """Newest timestamp for sid in the API: ledger
    (API:<api_request_id>|<sid>|<unix_ts>). Deliberately NOT the marker
    pass's colon-splitting parser: api_request_id preserves structural
    colons (contract C-4), so a colon-based split would misparse it -- pipe
    is this ledger's real delimiter. The ledger's sid field is the RAW
    session id (Phase 32 Plan 01 decision); the spool FILENAME is already
    the namespace-stripped component, so both sides are normalized through
    _strip_ns_prefix before comparing."""
    target = _strip_ns_prefix(sid)
    try:
        with open(ledger_path, 'r', encoding='utf-8') as f:
            last_ts = None
            for line in f:
                line = line.rstrip('\n')
                if not line.startswith('API:'):
                    continue
                parts = line.split('|')
                if len(parts) != 3:
                    continue
                _arid_field, ledger_sid, ts_field = parts
                if _strip_ns_prefix(ledger_sid) != target:
                    continue
                try:
                    ts = float(ts_field)
                    if last_ts is None or ts > last_ts:
                        last_ts = ts
                except ValueError:
                    pass
            return last_ts
    except FileNotFoundError:
        return None


def prune_spool_dir(spool_dir, ledger_fn, ledger_path, label):
    s_scanned = s_kept = s_removed = 0
    try:
        entries = sorted(os.listdir(spool_dir))
    except FileNotFoundError:
        entries = []

    for fname in entries:
        if not fname.endswith('.jsonl'):
            continue
        fpath = os.path.join(spool_dir, fname)
        if not os.path.isfile(fpath):
            continue

        s_scanned += 1
        sid = fname[:-len('.jsonl')]

        # Age a spool from the NEWER of its last successful shipment and its
        # own mtime. The ledger timestamp alone is not safe here: every line
        # in a spool file is a billable record, and mtime advances whenever a
        # fresh event is appended. A session that shipped long ago and then
        # resumed carries an ancient ledger entry alongside brand-new
        # unshipped events in the same file -- ageing that file from the
        # ledger alone deletes revenue before it is ever reported.
        #
        # Markers can age from the ledger alone because a marker is a
        # classification record that has already served its purpose once its
        # session is reported. A spool line has not.
        last_ts = ledger_fn(sid, ledger_path)
        mtime = os.path.getmtime(fpath)
        if last_ts is not None and last_ts >= mtime:
            age_secs = time.time() - last_ts
            ts_label = iso(last_ts)
            ts_source = 'last_ledger_ts'
        else:
            age_secs = time.time() - mtime
            ts_label = iso(mtime)
            ts_source = 'mtime'
        age_days = age_secs / 86400

        if age_secs < cutoff_secs:
            s_kept += 1
            continue

        action = 'dry-run, would remove' if dry_run else 'removed'
        print(
            'prune: ' + action +
            ' dir=' + label +
            ' sid=' + sid +
            ' spool=' + fname +
            ' ' + ts_source + '=' + ts_label +
            ' age_days=' + str(round(age_days, 1)),
            flush=True,
        )

        if not dry_run:
            try:
                os.unlink(fpath)
                s_removed += 1
            except OSError as exc:
                print('prune: ERROR removing ' + fname + ': ' + str(exc), flush=True)
                sys.exit(1)
        else:
            s_removed += 1

    print(
        'prune: ' + label + ' summary, scanned=' + str(s_scanned) +
        ' kept=' + str(s_kept) +
        ' removed=' + str(s_removed),
        flush=True,
    )
    return s_scanned, s_kept, s_removed


event_spool_dir_py = os.environ.get('EVENT_SPOOL_DIR_PY', '')
tool_events_dir_py = os.environ.get('TOOL_EVENTS_DIR_PY', '')
event_ledger_file_py = os.environ.get('EVENT_LEDGER_FILE_PY', '')
tool_events_ledger_file_py = os.environ.get('TOOL_EVENTS_LEDGER_FILE_PY', '')

if event_spool_dir_py:
    prune_spool_dir(event_spool_dir_py, event_ledger_last_ts, event_ledger_file_py, 'api-events')

if tool_events_dir_py:
    prune_spool_dir(tool_events_dir_py, tool_ledger_last_ts, tool_events_ledger_file_py, 'tool-events')

# ---------------------------------------------------------------------------
# Phase 32 (D-15/D-08): fourth pass -- the new api_request_id-keyed ledger
# (EVENT_LEDGER_FILE, API: lines). An API: line is dropped only when it is
# BOTH past the cutoff AND its session's spool file no longer exists
# (T-32-20): removing an idempotency record ahead of the data it protects is
# how a pruning change turns into a double-report, so survival of the spool
# file always wins over age. The frozen legacy HERMES: ledger (LEDGER_FILE)
# is NEVER touched by this pass -- it is the rollback record (D-08) and the
# drain gate's own input (contract C-11); this function only ever opens
# EVENT_LEDGER_FILE, a wholly separate file.
# ---------------------------------------------------------------------------

def prune_event_ledger(ledger_path, spool_dir):
    if not ledger_path:
        return 0, 0, 0
    try:
        with open(ledger_path, 'r', encoding='utf-8') as f:
            raw_lines = [ln.rstrip('\n') for ln in f if ln.strip()]
    except FileNotFoundError:
        return 0, 0, 0

    l_scanned = l_kept = l_removed = 0
    out_lines = []
    now_ts = time.time()

    for raw_line in raw_lines:
        if not raw_line.startswith('API:'):
            out_lines.append(raw_line)
            continue
        parts = raw_line.split('|')
        if len(parts) != 3:
            # Unrecognised shape -- keep. Never guess-delete an idempotency
            # record whose fields this pass cannot parse with confidence.
            out_lines.append(raw_line)
            continue

        l_scanned += 1
        _arid_field, ledger_sid, ts_field = parts
        try:
            ts = float(ts_field)
        except ValueError:
            out_lines.append(raw_line)
            l_kept += 1
            continue

        age_secs = now_ts - ts
        if age_secs < cutoff_secs:
            out_lines.append(raw_line)
            l_kept += 1
            continue

        component = _strip_ns_prefix(ledger_sid)
        spool_path = os.path.join(spool_dir, component + '.jsonl') if spool_dir else ''
        if spool_path and os.path.isfile(spool_path):
            # T-32-20: the record this line protects could still be re-read
            # and re-shipped -- keep it regardless of age.
            out_lines.append(raw_line)
            l_kept += 1
            continue

        action = 'dry-run, would remove' if dry_run else 'removed'
        print(
            'prune: ' + action +
            ' dir=api-events-ledger' +
            ' sid=' + ledger_sid +
            ' age_days=' + str(round(age_secs / 86400, 1)),
            flush=True,
        )
        l_removed += 1
        if dry_run:
            # --dry-run must remove nothing -- keep the line in the rewrite
            # buffer too (moot in practice since the write below is also
            # gated on `not dry_run`, but keeps this function's own
            # bookkeeping honest under either gate independently).
            out_lines.append(raw_line)

    if not dry_run and l_removed:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            for ln in out_lines:
                f.write(ln + '\n')

    print(
        'prune: api-events-ledger summary, scanned=' + str(l_scanned) +
        ' kept=' + str(l_kept) +
        ' removed=' + str(l_removed),
        flush=True,
    )
    return l_scanned, l_kept, l_removed


if event_ledger_file_py:
    prune_event_ledger(event_ledger_file_py, event_spool_dir_py)

# ---------------------------------------------------------------------------
# quick-260817-tfe (OWN-02): fifth pass -- the session OWNERSHIP records
# (OWNERS_DIR). Same idea as the passes above, with ONE deliberate difference
# that is the entire point of this pass existing:
#
#   STALENESS IS PRESENCE IN state.db, AND NOTHING ELSE. cutoff_secs is NOT
#   used here, and the coupling to MARKER_RETENTION_DAYS is deliberately
#   ABSENT. An ownership record must outlive every billing row it partitions,
#   for as long as the session it names can still accrue tokens. That is
#   exactly P1-2: the ownership signal used to live in the API: ledger, which
#   this script prunes at MARKER_RETENTION_DAYS (default 30), so ~30 days on a
#   STILL-LIVE session erased its only ownership record and let the legacy
#   path re-bill the session's entire cumulative token count from a zero
#   baseline. A future reader "restoring consistency" by keying this pass on
#   age would reintroduce that defect exactly.
#
# FAIL-SAFE, HARD. A missing state.db, an unreadable one, or ANY sqlite error
# removes NOTHING and says why. Deleting an ownership record on doubt is how a
# pruning change becomes a double-bill -- the same reasoning the event-ledger
# pass above already carries for its own idempotency records.
#
# Note this script is MANUAL and deliberately not wired into cron (D-28), so
# owners records accumulate between operator runs exactly as markers do.
# ---------------------------------------------------------------------------

def _owner_record_name(sid):
    """The SAME filename derivation the claim primitive uses in both
    hermes-report.sh and api-event-report.sh (separator and NUL to underscore,
    200-character cap). Applied to every state.db id before comparing, so an
    exotic session id compares against the right key on both sides."""
    return sid.replace('/', '_').replace('\x00', '_')[:200]


def prune_owners(owners_dir, state_db):
    if not owners_dir:
        return 0, 0, 0
    try:
        entries = sorted(os.listdir(owners_dir))
    except FileNotFoundError:
        return 0, 0, 0
    except OSError as exc:
        print('prune: owners pass skipped -- owners dir unreadable: ' + str(exc), flush=True)
        return 0, 0, 0

    if not state_db or not os.path.isfile(state_db):
        print('prune: owners pass skipped -- state.db not found at ' + str(state_db) +
              '; removing NOTHING (an ownership record deleted on doubt is a double-bill)',
              flush=True)
        return 0, 0, 0

    live = set()
    try:
        # Read-only URI connection, the established stdlib-sqlite3 pattern
        # drain-status.sh already uses -- this pass adds no new external-tool
        # precondition, and a missing state.db is never created as a side effect.
        uri = 'file:' + state_db + '?mode=ro'
        with sqlite3.connect(uri, uri=True) as conn:
            for (sid,) in conn.execute('SELECT id FROM sessions'):
                if sid is None:
                    continue
                live.add(_owner_record_name(str(sid)))
    except Exception as exc:
        print('prune: owners pass skipped -- state.db unreadable (' + str(exc) +
              '); removing NOTHING', flush=True)
        return 0, 0, 0

    o_scanned = o_kept = o_removed = 0
    for fname in entries:
        fpath = os.path.join(owners_dir, fname)
        if not os.path.isfile(fpath):
            continue

        o_scanned += 1
        if fname in live:
            o_kept += 1
            continue

        action = 'dry-run, would remove' if dry_run else 'removed'
        print(
            'prune: ' + action +
            ' dir=owners' +
            ' sid=' + fname +
            ' reason=absent_from_state_db',
            flush=True,
        )

        if not dry_run:
            try:
                os.unlink(fpath)
                o_removed += 1
            except OSError as exc:
                print('prune: ERROR removing ' + fname + ': ' + str(exc), flush=True)
                sys.exit(1)
        else:
            o_removed += 1

    print(
        'prune: owners summary, scanned=' + str(o_scanned) +
        ' kept=' + str(o_kept) +
        ' removed=' + str(o_removed),
        flush=True,
    )
    return o_scanned, o_kept, o_removed


prune_owners(os.environ.get('OWNERS_DIR_PY', ''), os.environ.get('STATE_DB_PY', ''))
PY
prune_rc=$?
set -e
while IFS= read -r log_line; do
  info "${log_line}"
done < "${prune_out}"
rm -f "${prune_out}"
if [[ "${prune_rc}" -ne 0 ]]; then
  warn "prune-markers: pruning failed (python exit ${prune_rc}); some stale markers may remain"
  exit "${prune_rc}"
fi
