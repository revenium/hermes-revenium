#!/usr/bin/env bash
set -uo pipefail
# plugin-status.sh — Phase 28 (D-01): diagnose whether the revenium-classifier
# on_session_end plugin is registered with Hermes' plugin discovery AND
# actually firing, and persist a plugin-health status document that
# hermes-report.sh reads to discriminate a registration outage from an
# unclassified session (D-06/D-07).
#
# Two-stage check (mirrors hooks-status.sh's shape):
#   1. Static: is ${HERMES_HOME}/plugins/revenium-classifier present as a
#      directory AND listed in plugins.enabled in ${HOOKS_CONFIG_FILE}?
#   2. Runtime liveness (Plan 28-03, D-02): cross-check sentinel freshness
#      (MARKERS_READY_DIR) against recently-ended sessions in state.db over
#      the REVENIUM_CRON_SETTLE_SECONDS window. A host with zero recently-
#      ended sessions is `idle` (never broken — nothing for the classifier
#      to have missed). A host with ended sessions AND fresh sentinels is
#      `firing`. A host with ended sessions and NO fresh sentinels is
#      `stalled` (broken) — the classifier is registered but not producing.
#      Liveness NEVER consults job-marker presence: a registration outage
#      must stay distinguishable from a classification failure (TRACE-04).
#
# Exit codes (stable for scripting; human-readable text may change):
#   0  registered, and liveness is idle or firing (healthy)
#   1  NOT registered (plugin dir absent, or not listed in plugins.enabled)
#   2  registered but liveness is stalled (not firing)
#
# Filesystem-and-regex ONLY (D-04): this runs on the per-minute cron path and
# must NEVER shell out to the hermes CLI to compute either verdict — it is
# slow, and on the diagnosis host `hermes` was not even on the bare PATH.
# Alert-only (D-05): this script never repairs anything, never restarts the
# gateway, and never invokes install-plugin.sh itself. The ONE sanctioned use
# of the `hermes` CLI anywhere in this script is the Plan 28-03 Task 2
# not-broken-to-broken transition notification (D-06) below — gated strictly
# behind the transition marker, never part of either verdict stage above,
# and itself fail-open (it never changes this script's exit status).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

PLUGIN_NAME="revenium-classifier"
PLUGIN_DEST_DIR="${HERMES_HOME}/plugins/${PLUGIN_NAME}"

# quick-260813-wnz (LOG-02/D-03): opt-in quiet mode -- ONLY cron.sh passes
# --quiet-unchanged. A manual `bash plugin-status.sh` invocation (no flags)
# stays byte-identical to pre-fix behavior, matching the operator docs that
# instruct a human to run this script and read the banner
# (references/trace-type-uncategorized.md, docs/live-host-verification-v1-2.md)
# and tests/test_phase28_plugin_status.py's assertions on that stdout shape.
# The default branch of this scan is a NO-OP, never an error: cron.sh
# forwards its own positional args through this same invocation and this
# script has always ignored them.
QUIET_UNCHANGED=false
for arg in "$@"; do
  case "${arg}" in
    --quiet-unchanged) QUIET_UNCHANGED=true ;;
    *) ;;
  esac
done

# Capture whether the REAL stdout is a terminal BEFORE any redirection,
# mirroring common.sh's `[[ -t 2 ]]` "a human is watching" idiom.
STDOUT_IS_TTY=false
[[ -t 1 ]] && STDOUT_IS_TTY=true

# quick-260813-wnz (LOG-02): buffer the entire banner into a temp file so a
# quiet, unchanged, healthy cron tick can be suppressed without rewriting any
# of the individual `echo` calls below. Save the real stdout onto fd 3, point
# stdout at the buffer, and install an EXIT trap that always cleans it up
# (holds regardless of which exit path below fires). Everything from here
# through the close of the verdict tree (EXIT_CODE assignment) is buffered,
# INCLUDING `echo "${STATUS_OUTPUT}"` -- command substitutions inside this
# region capture their own stdout via their own pipe and are unaffected by
# this outer redirect.
PLUGIN_STATUS_BUFFER="$(mktemp "${STATE_DIR}/.plugin-status-buffer.XXXXXX" 2>/dev/null || mktemp)"
trap 'rm -f "${PLUGIN_STATUS_BUFFER}"' EXIT
exec 3>&1
exec 1>"${PLUGIN_STATUS_BUFFER}"

# (C) read_config_field helper — reads a scalar key from CONFIG_FILE via
# Python. Mirrors guardrail-check.sh's helper of the same name (D-06 reuse),
# but fails open to an empty string on a missing/corrupt CONFIG_FILE — unlike
# guardrail-check.sh, this script must run even when config.json has never
# been created (metering-only installs, fresh hosts).
read_config_field() {
  CONFIG_FILE="${CONFIG_FILE}" KEY="$1" python3 - <<'PY'
import json, os
try:
    val = json.load(open(os.environ['CONFIG_FILE'])).get(os.environ['KEY'], '')
except Exception:
    val = ''
if isinstance(val, bool):
    print('true' if val else 'false')
else:
    print(val if val is not None else '')
PY
}

echo "Revenium plugin registration status"
echo "────────────────────────────────────"

# --- 1. Static registration check ------------------------------------------
echo
echo "[1] Registration check"
registered=true

if [[ ! -d "${PLUGIN_DEST_DIR}" ]]; then
  echo "    ✗ plugin directory NOT found at ${PLUGIN_DEST_DIR}"
  registered=false
else
  echo "    ✓ plugin directory present at ${PLUGIN_DEST_DIR}"
fi

if ${registered}; then
  # Reuse install-plugin.sh's exact anchored list-item regex (read-only) so
  # this check and the writer agree on what "listed" means.
  if HOOKS_CONFIG_FILE="${HOOKS_CONFIG_FILE}" PLUGIN_NAME="${PLUGIN_NAME}" python3 - <<'PY' 2>/dev/null
import os
import re
import sys

path = os.environ['HOOKS_CONFIG_FILE']
plugin_name = os.environ['PLUGIN_NAME']
try:
    content = open(path, encoding='utf-8').read()
except Exception:
    sys.exit(1)
if re.search(r"^\s*-\s*" + re.escape(plugin_name) + r"\s*$", content, re.MULTILINE):
    sys.exit(0)
sys.exit(1)
PY
  then
    echo "    ✓ ${PLUGIN_NAME} listed in plugins.enabled (${HOOKS_CONFIG_FILE})"
  else
    echo "    ✗ ${PLUGIN_NAME} NOT listed in plugins.enabled (${HOOKS_CONFIG_FILE})"
    registered=false
  fi
fi

# --- 2. Runtime liveness ----------------------------------------------------
# D-02: the liveness window is REVENIUM_CRON_SETTLE_SECONDS itself, not a
# second independently-tunable constant — that is the exact bar at which
# hermes-report.sh gives up waiting for a sentinel, so "not firing" fires the
# same tick the fallback trace-type starts happening.
window_seconds="${REVENIUM_CRON_SETTLE_SECONDS:-600}"
window_minutes=$(( (window_seconds + 59) / 60 ))
[[ "${window_minutes}" -lt 1 ]] && window_minutes=1

liveness="unknown"
recent_ended=0
fresh_sentinels=0

if ${registered}; then
  echo
  echo "[2] Runtime liveness (window=${window_seconds}s / ${window_minutes}m)"

  # CR-02 (Phase 28 review): a single aggregate recent_ended count against a
  # single fresh_sentinels count — both scoped to the default-profile
  # STATE_DB / MARKERS_READY_DIR — misreports under gateway.multiplex_profiles:
  # every profile's sessions live in the ONE shared state.db, but each named
  # profile's classifier sentinels land under its OWN
  # ~/.hermes/profiles/<profile>/state/revenium/markers/.ready/ directory.
  # Group recently-ended sessions by their OWNING profile's ready directory
  # (via the SAME resolve-markers-dir.py sidecar hermes-report.sh's own
  # per-session resolution already uses — parity, not a third reimplementation
  # of the agent:<profile>: namespace pattern) and check freshness
  # independently per group. This is what stops an idle default profile from
  # masking a firing named profile, and stops a genuinely broken named
  # profile from hiding behind a healthy default (both directions of the
  # misdiagnosis TRACE-04 exists to prevent). Fail-open: any import or lookup
  # failure (e.g. an isolated scratch tree that never shipped
  # resolve-markers-dir.py alongside this script) resolves every sid to the
  # single default ready dir, reproducing this script's pre-fix behavior
  # exactly — never a new failure mode.
  LIVENESS_OUTPUT=$(
    STATE_DB="${STATE_DB}" \
    MARKERS_READY_DIR="${MARKERS_READY_DIR}" \
    MARKERS_DIR="${MARKERS_DIR}" \
    SCRIPT_DIR="${SCRIPT_DIR}" \
    WINDOW_SECONDS="${window_seconds}" \
    WINDOW_MINUTES="${window_minutes}" \
    python3 - <<'PY' 2>/dev/null
import importlib.util
import os
import sqlite3
import time
from pathlib import Path

state_db = os.environ.get('STATE_DB', '')
default_ready_dir = os.environ.get('MARKERS_READY_DIR', '')
process_markers_dir = os.environ.get('MARKERS_DIR', '')
script_dir = os.environ.get('SCRIPT_DIR', '')
try:
    window_seconds = int(os.environ.get('WINDOW_SECONDS', '600'))
except (TypeError, ValueError):
    window_seconds = 600
# D-02 keeps the stall bar at REVENIUM_CRON_SETTLE_SECONDS (== window_seconds):
# the exact age at which hermes-report.sh stops waiting for a sentinel, so
# "not firing" is reported the same tick the fallback trace-type starts.
#
# The SELECT horizon must therefore be strictly wider than that bar. Selecting
# only sessions younger than the bar would make `age >= bar` unsatisfiable by
# construction and liveness could never leave 'firing' — the detector would be
# silently inert. Look back twice the bar so a session that ages out stays
# visible for one further window and can be counted exactly once.
settle_seconds = window_seconds
lookback_seconds = window_seconds * 2

_resolver = None
try:
    spec = importlib.util.spec_from_file_location(
        'phase28_markers_dir_sidecar_status',
        os.path.join(script_dir, 'resolve-markers-dir.py'),
    )
    _mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_mod)
    _resolver = getattr(_mod, 'resolve_markers_dir', None)
except Exception:
    _resolver = None


def ready_dir_for(sid):
    """The .ready directory for sid's OWNING profile, or the process-level
    default when resolution is unavailable or sid is not namespaced."""
    if _resolver is None:
        return default_ready_dir
    try:
        resolved = _resolver(sid, process_markers_dir or None)
    except Exception:
        return default_ready_dir
    if resolved == process_markers_dir:
        return default_ready_dir
    return str(Path(resolved) / '.ready')


recent_ended = 0
ready_dirs_seen = set()
rows = []
if state_db and os.path.isfile(state_db):
    try:
        conn = sqlite3.connect(state_db)
        try:
            cur = conn.execute(
                "SELECT id, ended_at FROM sessions WHERE ended_at IS NOT NULL "
                "AND ended_at >= strftime('%s','now') - ?",
                (lookback_seconds,),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
    except Exception:
        rows = []

# Per-session sentinel correspondence, NOT directory freshness. Asking only
# "is anything fresh in this profile's .ready dir?" lets one sentinel vouch for
# every session that ended in the window: a classifier that fires for 1 of 3
# sessions still reads as healthy, the broken-state alert never fires, and the
# two missed sessions surface downstream as `no_job_classified` — attributing a
# plugin execution failure to "this session had no job". Match each ended
# session to its OWN sentinel instead, exactly as the reporter does at
# `hermes-report.sh`'s G-03 gate (`(row_ready_dir / sid).exists()`).
fresh_sentinels_total = 0
missing_settled = 0
missing_pending = 0
now = time.time()
for row in rows:
    sid = row[0] if row else None
    if not sid:
        continue
    recent_ended += 1
    rd = ready_dir_for(sid)
    ready_dirs_seen.add(rd)
    try:
        has_sentinel = bool(rd) and (Path(rd) / sid).exists()
    except OSError:
        has_sentinel = False
    if has_sentinel:
        fresh_sentinels_total += 1
        continue
    # No sentinel: only evidence of a stall once the session has aged past the
    # settle window. Younger ones are still legitimately in flight — counting
    # them would alert on every normal session-end race.
    try:
        ended_at = float(row[1]) if row[1] is not None else None
    except (TypeError, ValueError):
        ended_at = None
    if ended_at is None or (now - ended_at) >= settle_seconds:
        missing_settled += 1
    else:
        missing_pending += 1

# The ended_at-keyed scan above is structurally blind to a host whose sessions
# never end. A gateway session stays open for hours, so `recent_ended == 0` does
# NOT mean "nothing happened" — it can equally mean "everything is still
# happening". On such a host a plugin that never loaded reported `idle`, i.e.
# healthy, while classifying nothing: observed live with 310 token-bearing
# sessions, 101 tool calls in the hour, and zero markers on disk.
#
# So corroborate before calling it idle. post_llm_call classifies every
# COMPLETED turn and writes its marker pair, while deliberately NOT writing a
# sentinel (a sentinel means "done with this session" and would change metering
# timing). Marker files are therefore the only proof-of-life on a host with no
# session boundaries — which is exactly why this looks at marker FILES and not
# at the kind:"job" records inside them. Presence of a marker proves the plugin
# RAN; job contents would conflate a registration outage with a classification
# failure, the distinction TRACE-04 exists to preserve.
# Per-session correspondence, NOT marker freshness. The classifier holds a
# permanent already-classified latch per session, so a long-lived session's
# marker is written once at turn 1 and never rewritten — its mtime ages out of
# any window while the session stays perfectly healthy. Keying on freshness
# would report every healthy long-running session as stalled. Ask instead
# whether each session that produced turns has a marker AT ALL.
turn_sessions = {}
if state_db and os.path.isfile(state_db):
    try:
        conn = sqlite3.connect(state_db)
        try:
            cur = conn.execute(
                "SELECT session_id, MIN(timestamp) FROM messages "
                "WHERE role='assistant' AND timestamp >= strftime('%s','now') - ? "
                "GROUP BY session_id",
                (lookback_seconds,),
            )
            for sid_row, first_ts in cur.fetchall():
                if sid_row:
                    try:
                        turn_sessions[sid_row] = float(first_ts)
                    except (TypeError, ValueError):
                        turn_sessions[sid_row] = now
        finally:
            conn.close()
    except Exception:
        turn_sessions = {}

recent_turns = len(turn_sessions)
sessions_with_marker = 0
settled_turn_sessions = 0
for sid_row, first_ts in turn_sessions.items():
    try:
        has_marker = bool(process_markers_dir) and (
            Path(process_markers_dir) / (str(sid_row) + '.jsonl')).exists()
    except OSError:
        has_marker = False
    if has_marker:
        sessions_with_marker += 1
    # Turn-1 classification is not instant, so a session whose first turn only
    # just landed is not yet evidence of anything.
    if (now - first_ts) >= settle_seconds:
        settled_turn_sessions += 1

fresh_markers = sessions_with_marker

if recent_ended == 0:
    # Sessions produced turns, at least one of them long enough ago to have been
    # classified, and NOT ONE of them has a marker: the plugin is not running,
    # whatever the registration check says.
    if settled_turn_sessions > 0 and sessions_with_marker == 0:
        liveness = 'stalled'
    else:
        liveness = 'idle'
elif missing_settled > 0:
    liveness = 'stalled'
else:
    liveness = 'firing'

print(f"RECENT_ENDED={recent_ended}")
print(f"FRESH_SENTINELS={fresh_sentinels_total}")
print(f"MISSING_SETTLED={missing_settled}")
print(f"MISSING_PENDING={missing_pending}")
print(f"RECENT_TURNS={recent_turns}")
print(f"FRESH_MARKERS={fresh_markers}")
print(f"LIVENESS={liveness}")
PY
  ) || LIVENESS_OUTPUT=""

  recent_ended=$(echo "${LIVENESS_OUTPUT}" | sed -n 's/^RECENT_ENDED=//p' | head -1)
  fresh_sentinels=$(echo "${LIVENESS_OUTPUT}" | sed -n 's/^FRESH_SENTINELS=//p' | head -1)
  missing_settled=$(echo "${LIVENESS_OUTPUT}" | sed -n 's/^MISSING_SETTLED=//p' | head -1)
  missing_pending=$(echo "${LIVENESS_OUTPUT}" | sed -n 's/^MISSING_PENDING=//p' | head -1)
  recent_turns=$(echo "${LIVENESS_OUTPUT}" | sed -n 's/^RECENT_TURNS=//p' | head -1)
  fresh_markers=$(echo "${LIVENESS_OUTPUT}" | sed -n 's/^FRESH_MARKERS=//p' | head -1)
  liveness=$(echo "${LIVENESS_OUTPUT}" | sed -n 's/^LIVENESS=//p' | head -1)

  [[ "${recent_ended}" =~ ^[0-9]+$ ]] || recent_ended=0
  [[ "${fresh_sentinels}" =~ ^[0-9]+$ ]] || fresh_sentinels=0
  [[ "${missing_settled}" =~ ^[0-9]+$ ]] || missing_settled=0
  [[ "${missing_pending}" =~ ^[0-9]+$ ]] || missing_pending=0
  [[ "${recent_turns}" =~ ^[0-9]+$ ]] || recent_turns=0
  [[ "${fresh_markers}" =~ ^[0-9]+$ ]] || fresh_markers=0
  case "${liveness}" in
    idle|firing|stalled) ;;
    *) liveness="unknown" ;;
  esac

  echo "    ${recent_ended} session(s) with ended_at inside the last $(( window_seconds * 2 ))s (state.db)"
  echo "    ${fresh_sentinels} of them have their own sentinel"
  echo "    ${missing_settled} aged past ${window_seconds}s with no sentinel; ${missing_pending} still within the grace window"
  echo "    ${recent_turns} session(s) produced turns in the window; ${fresh_markers} of them have a marker"

  case "${liveness}" in
    idle)
      if [[ "${recent_turns}" -gt 0 ]]; then
        echo "    ℹ no sessions ended in the window, but ${fresh_markers}/${recent_turns} active session(s) have markers — classifier is alive"
      else
        echo "    ℹ idle host — no sessions ended in the window, nothing for the classifier to have missed"
      fi
      ;;
    firing)
      echo "    ✓ classifier is firing — every settled session has its own sentinel"
      ;;
    stalled)
      # Two distinct stall shapes reach this verdict and they need different
      # sentences: sessions that ended without a sentinel, and (on a host whose
      # sessions never end) turns that ran without a marker.
      if [[ "${recent_ended}" -gt 0 ]]; then
        echo "    ✗ classifier NOT firing — ${missing_settled} session(s) aged past the settle window with no sentinel of their own"
      else
        echo "    ✗ classifier NOT firing — ${recent_turns} session(s) produced turns and NOT ONE has a marker"
        echo "      (no session ended, so the sentinel check above cannot see this; long-lived"
        echo "       gateway sessions stay open for hours and never reach a session boundary)"
      fi
      ;;
    *)
      echo "    ? liveness computation failed — treating as non-broken (fail-open)"
      ;;
  esac
else
  echo
  echo "[2] Runtime liveness"
  echo "    (skipped — plugin is not registered; stage 1 short-circuits stage 2)"
fi

# --- 3. Persist plugin-status.json atomically (D-06 status file contract) -
STATUS_OUTPUT=$(
  REGISTERED="${registered}" \
  LIVENESS="${liveness}" \
  PLUGIN_STATUS_FILE="${PLUGIN_STATUS_FILE}" \
  python3 - <<'PY'
import fcntl
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

status_file = Path(os.environ['PLUGIN_STATUS_FILE'])
registered = os.environ['REGISTERED'] == 'true'
liveness = os.environ['LIVENESS']


def _load_prev():
    """Fail-open load of the previous document (matches guardrail-status.json's
    carry-forward idiom). A missing/corrupt file defaults prev_healthy to TRUE
    so a fresh install never alerts on its very first tick.

    quick-260813-wnz (LOG-02): also returns the raw previous mapping (empty
    dict when no document existed or it was corrupt) so callers can compute
    the LOG-02 change decision from the RAW document -- prev_healthy's
    defaulting-to-True semantics above are the fresh-install-never-alerts
    rule and must not be reused for that decision."""
    prev = {}
    try:
        prev = json.loads(status_file.read_text(encoding='utf-8'))
    except Exception:
        pass
    prev_healthy = prev.get('healthy', True)
    if not isinstance(prev_healthy, bool):
        prev_healthy = True
    return prev_healthy, prev.get('brokenAt'), prev


# WR-03 fix: the read-decide-write sequence below has no protection against
# a second concurrent invocation (the operator doc explicitly instructs
# `bash plugin-status.sh` manual runs, which cron.lock never serializes
# against). Two processes racing this window could both observe the same
# prev_healthy=true, both compute transition=true, and both dispatch a
# broken-transition notification. Mirror classifier.py's
# _persist_label_to_taxonomy sidecar-lock pattern: a non-blocking LOCK_EX on
# PLUGIN_STATUS_FILE + ".lock" held for the whole read-decide-write. On lock
# contention (another process mid-decision), skip the write and report the
# PREVIOUS document's healthy/liveness unchanged with transition=false —
# never mutate the file and never double-notify; the process holding the
# lock is the sole authority for this tick.
status_file.parent.mkdir(parents=True, exist_ok=True)
lock_path = status_file.parent / (status_file.name + '.lock')
try:
    lockfd = open(lock_path, 'a')
except OSError:
    lockfd = None

got_lock = False
if lockfd is not None:
    try:
        fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        got_lock = True
    except OSError:
        got_lock = False

if not got_lock:
    prev_healthy, _, _ = _load_prev()
    print(f"PLUGIN_HEALTHY={'true' if prev_healthy else 'false'}", file=sys.stdout)
    print("PLUGIN_BROKEN_TRANSITION=false", file=sys.stdout)
    # quick-260813-wnz (LOG-02): when we did not get to decide (lock
    # contention), we do not suppress -- hardcode changed=true so the
    # bash-side gate below always prints on this branch.
    print("PLUGIN_STATE_CHANGED=true", file=sys.stdout)
    print(
        "revenium-classifier plugin-status: lock contention, skipping this tick's write",
        file=sys.stderr,
    )
    if lockfd is not None:
        try:
            lockfd.close()
        except OSError:
            pass
    sys.exit(0)

try:
    prev_healthy, prev_broken_at, prev_doc = _load_prev()

    # Verdict table (D-06 contract, Plan 28-01): registered AND liveness not
    # 'stalled' is healthy. 'unknown' (stage 1 failed, stage 2 never ran) and
    # 'idle'/'firing' are all non-broken.
    healthy = registered and liveness != 'stalled'

    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    data = {
        'healthy': healthy,
        'registered': registered,
        'liveness': liveness,
        'lastChecked': now,
    }

    # Transition-only debounce (D-06): computed and the atomic write below
    # lands BEFORE the bash tail's notify branch runs, so a repeat tick reads
    # this already-broken document and stays silent. This boolean is the ONLY
    # debounce mechanism — no separate rate-limit file.
    transition = (not healthy) and prev_healthy

    # quick-260813-wnz (LOG-02/D-03): the change decision for the quiet-mode
    # gate, computed HERE where the previous document is loaded (the only
    # place it is read). True when no previous document existed at all
    # (prev_doc == {}), otherwise true when any of healthy/registered/
    # liveness differs from the previous document's value. Deliberately NOT
    # derived from prev_healthy's defaulting-to-True semantics above -- that
    # default exists so a fresh install never ALERTS, which is a different
    # question from whether this tick's output CHANGED.
    changed = (not prev_doc) or any(
        prev_doc.get(k) != data[k] for k in ('healthy', 'registered', 'liveness')
    )

    if not healthy:
        if prev_healthy:
            data['brokenAt'] = now
        else:
            data['brokenAt'] = prev_broken_at or now
    # healthy == True: brokenAt key omitted entirely (contract) — a recovery run
    # clears any carried-forward brokenAt by simply never writing the key.

    # Atomic write: write-tmp-rename, reused verbatim from guardrail-check.sh
    # (T-28-01 mitigation) so a concurrent reader never observes a partial doc.
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(status_file.parent),
        prefix='.plugin-status-',
        suffix='.tmp',
    )
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            f.write(json.dumps(data, indent=2) + '\n')
        os.replace(tmp_path, str(status_file))
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass

    print(f"PLUGIN_HEALTHY={'true' if healthy else 'false'}")
    print(f"PLUGIN_BROKEN_TRANSITION={'true' if transition else 'false'}")
    print(f"PLUGIN_STATE_CHANGED={'true' if changed else 'false'}")
finally:
    try:
        fcntl.flock(lockfd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        lockfd.close()
    except OSError:
        pass
PY
)

echo "${STATUS_OUTPUT}"
PLUGIN_HEALTHY=$(echo "${STATUS_OUTPUT}" | sed -n 's/^PLUGIN_HEALTHY=//p' | head -1)
PLUGIN_BROKEN_TRANSITION=$(echo "${STATUS_OUTPUT}" | sed -n 's/^PLUGIN_BROKEN_TRANSITION=//p' | head -1)
PLUGIN_STATE_CHANGED=$(echo "${STATUS_OUTPUT}" | sed -n 's/^PLUGIN_STATE_CHANGED=//p' | head -1)
case "${PLUGIN_STATE_CHANGED}" in
  true|false) ;;
  *) PLUGIN_STATE_CHANGED=true ;;  # empty/unrecognized -- never suppress
esac

# --- 4. Verdict + actionable guidance --------------------------------------
echo

if [[ "${registered}" != "true" ]]; then
  echo "✗ Plugin is NOT registered. Run:"
  echo "  bash ${SCRIPT_DIR}/install-plugin.sh"
  EXIT_CODE=1
elif [[ "${liveness}" == "stalled" ]]; then
  echo "✗ Plugin is registered but the classifier is NOT firing (stalled)."
  if [[ "${recent_ended}" -gt 0 ]]; then
    echo "  ${recent_ended} session(s) ended in the last ${window_seconds}s with zero sentinel activity."
  else
    echo "  ${recent_turns} session(s) produced turns in the last $(( window_seconds * 2 ))s and none has a marker."
    echo "  'Registered' means present in config.yaml — it does NOT mean the running"
    echo "  gateway has loaded it. A gateway started before the plugin was installed"
    echo "  reports exactly this."
  fi
  echo "  Human remediation (this script never repairs automatically, D-05):"
  echo "    1. Restart the Hermes gateway so it reloads ${PLUGIN_NAME}."
  echo "    2. Re-run: bash ${SCRIPT_DIR}/install-plugin.sh"
  EXIT_CODE=2
else
  echo "✓ Plugin is registered. Liveness: ${liveness}."
  EXIT_CODE=0
fi

# --- Restore stdout and gate the buffered banner (LOG-02/D-03) -------------
# The buffered region closes here, at the close of the verdict tree (EXIT_CODE
# now assigned). Restore the real stdout, then print the buffer UNLESS ALL of:
# the quiet flag was passed, real stdout is not a terminal, the health marker
# is true, the change marker is false, and the transition marker is false.
# Any one of those failing means print everything. The transition-
# notification block below writes only to the log helpers and to `hermes
# chat` (never to this script's stdout), so its position relative to this
# gate does not change its behavior -- it stays AFTER the restore so a future
# stdout-emitting addition there is never silently swallowed by the buffer.
exec 1>&3
exec 3>&-

if [[ "${QUIET_UNCHANGED}" == "true" && "${STDOUT_IS_TTY}" != "true" && \
      "${PLUGIN_HEALTHY}" == "true" && "${PLUGIN_STATE_CHANGED}" != "true" && \
      "${PLUGIN_BROKEN_TRANSITION}" != "true" ]]; then
  : # suppressed: quiet cron tick, healthy, unchanged, no transition
else
  cat "${PLUGIN_STATUS_BUFFER}"
fi

# --- 5. Not-broken-to-broken transition notification (D-06, Task 2) --------
# Reuses guardrail-check.sh's exact Hermes messaging dispatch shape. Fires
# ONLY on the transition (already debounced by the atomic write above having
# landed); every branch here is fail-open and NEVER changes EXIT_CODE. This
# is the one sanctioned Hermes CLI invocation in this script — a
# notification, never a repair action (D-05): no gateway restart, no
# installer invocation, no clearing of a broken verdict from here (the
# verdict tree recomputing it on a later tick is the only path that clears
# brokenAt).
if [[ "${PLUGIN_BROKEN_TRANSITION}" == "true" ]]; then
  NOTIFY_CHANNEL=$(read_config_field notifyChannel)
  NOTIFY_TARGET=$(read_config_field notifyTarget)

  if [[ "${registered}" != "true" ]]; then
    VERDICT_DESC="not registered"
  else
    VERDICT_DESC="registered but not firing (liveness=${liveness})"
  fi
  NOTIFY_MSG="Revenium classifier plugin health check FAILED — ${VERDICT_DESC}. Restart the Hermes gateway, then re-run: bash ${SCRIPT_DIR}/install-plugin.sh"

  if [[ -n "${NOTIFY_CHANNEL}" && -n "${NOTIFY_TARGET}" ]]; then
    if command -v hermes >/dev/null 2>&1; then
      if hermes chat --toolsets messaging -q "Use the send_message tool to send this exact message to ${NOTIFY_CHANNEL}:${NOTIFY_TARGET}: ${NOTIFY_MSG}" >/dev/null 2>&1; then
        info "Plugin-health notification sent via Hermes ${NOTIFY_CHANNEL}"
      else
        warn "Failed to send plugin-health notification via Hermes ${NOTIFY_CHANNEL}"
      fi
    else
      warn "hermes CLI not available — plugin-health notification not sent"
    fi
  else
    info "Plugin health check failed but no notification channel configured"
  fi
fi

exit "${EXIT_CODE}"
