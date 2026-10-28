#!/usr/bin/env bash
# tool-event-report.sh — reads per-session tool-event JSONL files and ships each
# unledgered record to Revenium via `revenium meter tool-event`.
# Soft-fail: individual event failures are warned and skipped; the script never aborts.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

if ! command -v revenium >/dev/null 2>&1; then
  warn "revenium CLI not found on PATH — skipping tool-event metering."
  exit 0
fi
if ! command -v python3 >/dev/null 2>&1; then
  warn "python3 not found — skipping tool-event metering."
  exit 0
fi
if ! revenium config show >/dev/null 2>&1; then
  warn "revenium not configured — run /revenium to set up."
  exit 0
fi

# quick-261027-fib: serialise runs. cron.lock only covers runs made THROUGH
# cron.sh; an operator running this script directly can overlap a tick, and both
# would read the same unledgered rows and ship them before either ledgers them
# (the ledger line is written AFTER the CLI call, so the per-row grep guard
# narrows that window but cannot close it). Non-blocking: a second run defers to
# the next tick. Same exec-fd + fcntl idiom as outcome-metrics-report.sh; a
# `-c` one-liner, not a `python3 -` heredoc, so the one-pass spool read below
# stays the only heredoc interpreter (test_spool_files_share_one_python_pass).
exec 9>"${TOOL_EVENTS_LOCK_FILE}"
if ! python3 -c 'import fcntl, sys
try:
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
except (OSError, BlockingIOError):
    sys.exit(11)' 2>/dev/null; then
  info "tool-event-report: another run holds the lock, skipping this tick"
  exit 0
fi

touch "${TOOL_EVENTS_LEDGER_FILE}"

ORG_NAME=""
if [[ -f "${CONFIG_FILE}" ]]; then
  ORG_NAME=$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}')).get('organizationName', ''))" 2>/dev/null || true)
fi

# quick-261027-fib: one log line per (key, reason), bounded by
# OUTCOME_WARN_FLAGS_DIR -- the same sentinel directory (and key shape) as
# hermes-report.sh's _job_outcome_log_once, so this is not a new state path and
# prune-markers.sh already garbage-collects it. `level` is info for an
# expected, self-resolving hold and warn for a condition an operator should
# look at. Never returns non-zero: a failed flag write degrades to a noisier
# log, not a crashed reporter.
_tool_event_log_once() {
  local raw_key="$1" reason="$2" level="$3" message="$4"
  local flag_key="${raw_key//[^A-Za-z0-9_:.-]/_}"
  flag_key="${flag_key:0:100}"
  local flag_path="${OUTCOME_WARN_FLAGS_DIR}/${flag_key}__tool-${reason}.flag"
  if [[ ! -e "${flag_path}" ]]; then
    mkdir -p "${OUTCOME_WARN_FLAGS_DIR}" 2>/dev/null && touch "${flag_path}" 2>/dev/null
    "${level}" "${message}"
  fi
  return 0
}

main() {
  info "=== Tool Event Reporter starting ==="

  if [[ ! -d "${TOOL_EVENTS_DIR}" ]]; then
    info "No tool-events directory — nothing to report."
    return
  fi

  local reported_count=0
  local skipped_count=0
  local held_count=0
  local attributed_count=0
  local unassigned_count=0
  local roots_resolved=0
  local probe_needed=0
  # Set true only by a positive `--workflow-id` capability probe. The probe is
  # lazy: it is paid once per run, and only when some row has an owner (or,
  # later, a hold), so a tick with nothing to attribute costs nothing.
  local workflow_capable=false

  # One python3 pass over EVERY spool file, not one per file. Each per-file
  # pass re-read the whole TOOL ledger to build its pre-filter set: measured
  # on a live profile (2026-10-12), 676 spool files x a 3.2 MB ledger was 55s
  # of a tick that shipped nothing. Files are visited in sorted order, the
  # order the shell glob used; the rows and the per-row guard below are
  # unchanged.
  #
  # quick-261027-fib: the same pass now also decides, per UNLEDGERED row, which
  # job owns the event (see split_strategies.assign_tool_event_job). Job
  # 'revenium_x_intelligence_scan_8e88' received 153 tool events with no job
  # association because `--workflow-id`, the field the application joins on,
  # was never sent. Everything that costs a state.db or marker read is done at
  # most once per distinct ROOT per tick, and only when an unledgered row
  # exists, so a fully pre-ledgered tick still resolves zero roots.
  local rows
  rows=$(
    TOOL_EVENTS_DIR="${TOOL_EVENTS_DIR}" LEDGER_FILE="${TOOL_EVENTS_LEDGER_FILE}" \
    SCRIPT_DIR="${SCRIPT_DIR}" STATE_DB="${STATE_DB}" MARKERS_DIR="${MARKERS_DIR}" \
    MARKERS_READY_DIR="${MARKERS_READY_DIR}" JOBS_LEDGER_FILE="${JOBS_LEDGER_FILE}" \
    PLUGIN_STATUS_FILE="${PLUGIN_STATUS_FILE}" \
    SETTLE_SECONDS="${REVENIUM_CRON_SETTLE_SECONDS:-600}" \
    MAX_HOLD_SECONDS="${REVENIUM_UNCLASSIFIED_MAX_HOLD_SECONDS:-7200}" \
    STALE_SECONDS="${REVENIUM_JOBS_STALE_SECONDS:-600}" \
    python3 - <<'PY' 2>/dev/null || true
import glob
import importlib.util
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote

event_files = sorted(
    p for p in glob.glob(os.path.join(glob.escape(os.environ.get("TOOL_EVENTS_DIR", "")), "*.jsonl"))
    if os.path.isfile(p)
)

# Ledger pre-filter. Measured on a live profile (2026-10-10): ~40k ledgered
# records and one get_root_session_id python+state.db spawn per row before the
# per-row grep, so a tick that shipped nothing took 52 minutes and starved
# every later cron stage. Loading the (sid, tcid) keys once here drops already
# ledgered rows before bash sees them. Fail-open: an unreadable ledger yields
# an empty set and every row falls through to the per-row grep guard below,
# which stays authoritative (it also catches same-run duplicates, since this
# snapshot cannot see lines appended during the run).
ledgered = set()
try:
    with open(os.environ.get("LEDGER_FILE", ""), "r", encoding="utf-8", errors="replace") as lf:
        for lline in lf:
            parts = lline.split(":", 3)
            if len(parts) >= 3 and parts[0] == "TOOL":
                ledgered.add((parts[1], parts[2]))
except OSError:
    pass
skipped = 0
pending = []

for event_file in event_files:
    try:
        with open(event_file, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line:
                    continue
                # 4 KB cap — mirrors marker reader (T-15-03 defense)
                if len(line) > 4096:
                    continue
                try:
                    r = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(r, dict):
                    continue
                sid = r.get("sid") or ""
                tool_call_id = r.get("tool_call_id") or ""
                tool = r.get("tool") or "unknown"
                if not sid or not tool_call_id:
                    continue
                ts_float = r.get("ts") or 0.0
                duration_ms = int(r.get("duration_ms") or 0)
                success = r.get("success")
                # D-03 parity: None treated as True (default success)
                if success is None:
                    success = True
                error = r.get("error") or ""
                sid_source = r.get("sid_source")
                if not isinstance(sid_source, str):
                    sid_source = ""
                try:
                    ts_iso = datetime.fromtimestamp(float(ts_float), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    ts_iso = ""
                if not ts_iso:
                    continue
                # Pipe-sanitize all string fields (WR-01 mirror; T-15-01/T-15-02 tamper mitigations)
                # Colon included to protect ledger key integrity (Pitfall 2 / T-15-02)
                for _bad in ("|", "\n", "\r", ":"):
                    sid = sid.replace(_bad, "_")
                    tool = tool.replace(_bad, "_")
                    tool_call_id = tool_call_id.replace(_bad, "_")
                    error = error.replace(_bad, "_")
                if (sid, tool_call_id) in ledgered:
                    skipped += 1
                    continue
                success_flag = "1" if success else "0"
                pending.append({
                    "sid": sid, "tcid": tool_call_id, "tool": tool, "ts_iso": ts_iso,
                    "ts": float(ts_float), "dur": duration_ms, "success": success_flag,
                    "error": error, "sid_source": sid_source,
                })
    except Exception:
        # Not just OSError: a line that raises (a non-numeric duration_ms)
        # used to end only its own file's interpreter, keeping the rows already
        # printed. One interpreter now serves every file, so the same failure
        # is contained to the same file here. `pending` keeps the rows built
        # before the bad line, exactly as the old print-as-you-go did.
        pass

# ---------------------------------------------------------------------------
# quick-261027-fib: ownership. Nothing below runs unless an unledgered row exists.
# ---------------------------------------------------------------------------
now = time.time()
_SID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")   # post_tool_call.sh _SID_RE: the only sids that may build a path

_ss = None
_resolver = None
if pending:
    # Both imports fail open: a copied tree without the sidecars (the
    # test_tool_event_subagent_trace_inheritance fixture) loses attribution
    # and ships exactly as before; root-trace resolution below needs neither.
    try:
        sys.path.insert(0, os.environ.get("SCRIPT_DIR", ""))
        import split_strategies as _ss
    except Exception:
        _ss = None
    try:
        _spec = importlib.util.spec_from_file_location(
            "fib_markers_dir_sidecar",
            os.path.join(os.environ.get("SCRIPT_DIR", ""), "resolve-markers-dir.py"))
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _resolver = getattr(_mod, "resolve_markers" + "_dir", None)
    except Exception:
        _resolver = None

# One read-only state.db connection per tick, opened only for a tick that has
# something to resolve. Ancestry comes from ONE query (the _parent_map idiom in
# hermes-report.sh) instead of a python spawn per row. A missing database, or
# one without parent_session_id, makes every sid its own root: today's
# fail-open. A locked one is "contended" -- we cannot tell root from child.
parents = {}
db_contended = False
conn = None
state_db = os.environ.get("STATE_DB", "")
if pending and state_db:
    try:
        conn = sqlite3.connect("file:" + quote(state_db, safe="/") + "?mode=ro", uri=True, timeout=1.5)
    except Exception:
        conn = None
if conn is not None:
    try:
        for rid, rparent in conn.execute(
                "SELECT id, parent_session_id FROM sessions WHERE parent_session_id IS NOT NULL"):
            if rid is not None and rparent is not None:
                parents[str(rid)] = str(rparent)
    except sqlite3.OperationalError as exc:
        msg = str(exc).lower()
        parents = {}
        if "locked" in msg or "busy" in msg:
            db_contended = True
    except Exception:
        parents = {}


def _root_of(row_sid):
    """The root delegator, at most ten hops: the get-root-session-id.py walk."""
    current = row_sid
    for _ in range(10):
        parent = parents.get(current)
        if parent is None:
            return current
        current = parent
    return current


process_markers_dir = os.environ.get("MARKERS_DIR", "")
process_ready_dir = os.environ.get("MARKERS_READY_DIR", "")


def _seconds_env(name, default):
    """A tunable the sibling reporters already read; malformed takes its default."""
    raw = os.environ.get(name, "")
    return int(raw) if re.fullmatch(r"[0-9]{1,9}", raw or "") else default


# Reused, none added (zero-config): hermes-report.sh's settle window, the
# unclassified-hold cap (0 switches EVERY hold here off) and the job staleness
# bound that _child_job_link_hold uses.
settle_seconds = _seconds_env("SETTLE_SECONDS", 600)
max_hold_seconds = _seconds_env("MAX_HOLD_SECONDS", 7200)
stale_seconds = _seconds_env("STALE_SECONDS", 600)

created = None
root_info = {}
_classifier_registered = None


def _classifier_expected():
    """True only on POSITIVE evidence that a healthy classifier is registered
    (hermes-report.sh's _classifier_expected). Absent, unreadable or unhealthy
    mean nothing is coming, so there is nothing to hold an event for."""
    global _classifier_registered
    if _classifier_registered is None:
        try:
            with open(os.environ.get("PLUGIN_STATUS_FILE", ""), encoding="utf-8") as pf:
                doc = json.load(pf)
            _classifier_registered = (
                isinstance(doc, dict) and doc.get("healthy") is True and doc.get("registered") is not False)
        except Exception:
            _classifier_registered = False
    return _classifier_registered


def _created_ids():
    """Ids whose `JOB:<id>:created:` is ledgered, read once per tick. A job id
    that is not live in Revenium would be CREATED nameless by a link to it, so
    only these may be sent. Unreadable ledger: empty set, nothing is sent."""
    global created
    if created is None:
        created = set()
        try:
            with open(os.environ.get("JOBS_LEDGER_FILE", ""), "r", encoding="utf-8", errors="replace") as jf:
                for jline in jf:
                    jparts = jline.rstrip("\n").split(":", 3)
                    if len(jparts) >= 3 and jparts[0] == "JOB" and jparts[2] == "created":
                        created.add(jparts[1])
        except OSError:
            pass
    return created


_activity_column_absent = False


def _session_facts(root):
    """(started_at, ended_at, last_activity_at, contended) of the ROOT's row, or
    (None, None, None, contended) when it has no usable row. last_activity_at
    degrades to None on an older Hermes (no column), as in hermes-report.sh.
    contended is True only when state.db was momentarily locked."""
    global _activity_column_absent
    if conn is None:
        return (None, None, None, False)
    row = None
    try:
        if _activity_column_absent:
            raise sqlite3.OperationalError("no such column: last_activity_at")
        row = conn.execute(
            "SELECT started_at, ended_at, last_activity_at FROM sessions WHERE id = ? LIMIT 1",
            (root,)).fetchone()
    except sqlite3.OperationalError as exc:
        msg = str(exc).lower()
        if "locked" in msg or "busy" in msg:
            return (None, None, None, True)
        if "no such column" in msg:
            _activity_column_absent = True
            try:
                row = conn.execute(
                    "SELECT started_at, ended_at, NULL FROM sessions WHERE id = ? LIMIT 1",
                    (root,)).fetchone()
            except sqlite3.OperationalError as exc2:
                m2 = str(exc2).lower()
                return (None, None, None, "locked" in m2 or "busy" in m2)
            except Exception:
                return (None, None, None, False)
    except Exception:
        return (None, None, None, False)

    def _stamp(value):
        if value is None or isinstance(value, bool):
            return None
        try:
            f = float(value)
        except (TypeError, ValueError):
            return None
        return f if f == f and f not in (float("inf"), float("-inf")) and f > 0 else None

    if not row:
        return (None, None, None, False)
    started = _stamp(row[0])
    if started is None:
        return (None, None, None, False)
    return (started, _stamp(row[1]), _stamp(row[2]), False)


def _info_for(root):
    """Per-root facts, computed once per tick: only the ROOT's marker file is
    read (a subagent never ships its own job id), in the directory of the
    profile that OWNS the root."""
    if root in root_info:
        return root_info[root]
    d = {"bad_sid": False, "arcs": None, "ready": False, "facts": None}
    if not _SID_RE.match(root):
        # A parent value from state.db or the spool is untrusted: never build
        # a path from anything that is not a plain session id.
        d["bad_sid"] = True
    else:
        mdir = process_markers_dir
        if _resolver is not None:
            try:
                mdir = _resolver(root, process_markers_dir or None) or process_markers_dir
            except Exception:
                mdir = process_markers_dir
        ready_dir = (process_ready_dir if (mdir == process_markers_dir and process_ready_dir)
                     else os.path.join(mdir, ".ready"))
        d["arcs"] = _ss.tool_event_job_arcs(os.path.join(mdir, root + ".jsonl"))
        try:
            d["ready"] = os.path.exists(os.path.join(ready_dir, root))
        except OSError:
            d["ready"] = False
    root_info[root] = d
    return d


def _sanitize(value):
    for _bad in ("|", "\n", "\r"):
        value = value.replace(_bad, "_")
    return value


def _no_job_decision(root, d, event_ts):
    """(hold, basis) for an event whose root has NO job record.

    Hold (job-pending) exactly when hermes-report.sh's _root_pending_uncached
    would hold a subagent for this root: a healthy classifier is expected, the
    cap is on, the root has a row younger than the cap, no sentinel (the plugin
    has not finished with it, job inference included) and it is live (or the
    database is contended). The classifier writes at most ONE job per root and
    only at a turn boundary, so "live and unfinished" is the one state in which
    a marker may still arrive.

    Released: `hold-expired` when the cap is the ONLY reason it is no longer
    held (a marker that never came), else `no-job` (there is no classifier, the
    sentinel was written, the root is idle, or it has no row: the classifier had
    its chance and wrote no job, so the work is intentionally unassigned)."""
    if max_hold_seconds <= 0 or not _classifier_expected() or d["ready"]:
        return ("", "no-job")
    # Once per root per tick: a root with hundreds of held events would
    # otherwise repeat the same sessions read for each one. A contended
    # result is cached too, so a locked database costs one attempt per root.
    if d["facts"] is None:
        d["facts"] = _session_facts(root)
    started, ended, activity, contended = d["facts"]
    if contended:
        # Cannot tell how old or live the root is: hold one more tick, bounded
        # by the event's own age so a database that stays locked cannot hold
        # an event past the cap.
        if 0 <= now - event_ts < max_hold_seconds:
            return ("job-pending", "")
        return ("", "hold-expired")
    if started is None:
        return ("", "no-job")
    latest = started
    if activity is not None and activity <= now + 300:
        latest = max(latest, activity)
    if ended is not None and ended <= now + 300:
        latest = max(latest, ended)
    if now - latest >= settle_seconds:
        return ("", "no-job")
    if now - started < max_hold_seconds:
        return ("job-pending", "")
    return ("", "hold-expired")


def _decide(row):
    """(root, workflow_id, basis, hold, notice) for one unledgered row.

    A held row carries a `hold` reason and an empty basis; every other row
    carries a basis. Every hold has a bound: the cap on the root's (or the
    event's) age, root liveness, the sentinel, or the create bound below."""
    sid = row["sid"]
    root = sid if db_contended else (_root_of(sid) or sid)
    ts = row["ts"]
    if row["sid_source"] != "payload":
        # Tier-2/3 session ids are guesses (and records from before the hook
        # stamped provenance have none): a guess must never pick a job.
        return (root, "", "sid-unverified", "", sid)
    if db_contended:
        # Ancestry unknown: shipping now would put a subagent's event under the
        # wrong trace and, worse, the wrong job. Hold, bounded by the event's age.
        age = now - ts
        if max_hold_seconds > 0 and 0 <= age < max_hold_seconds:
            return (root, "", "", "db-busy", "state.db")
        return (root, "", "ancestry-unavailable", "", "")
    if _ss is None:
        return (root, "", "attribution-unavailable", "", "")
    d = _info_for(root)
    if d["bad_sid"]:
        return (root, "", "bad-sid", "", root)
    if ts > now + 300:
        return (root, "", "bad-ts", "", "")
    job_id, basis, arc = _ss.assign_tool_event_job(d["arcs"], ts)
    if job_id is None:
        if basis == "no-job":
            hold, released = _no_job_decision(root, d, ts)
            if hold:
                return (root, "", "", hold, root)
            return (root, "", released, "", root if released == "hold-expired" else "")
        if basis in ("ambiguous-arcs", "invalid-job-id", "unplaceable-job", "markers-unreadable"):
            return (root, "", basis, "", root)
        # after-job, bad-ts: intentionally unassigned, ship at once. Under
        # first-record-only no later record can bring the event into an arc,
        # and the classifier mints no second job for a root, so holding would
        # only delay.
        return (root, "", basis, "", "")
    if job_id in _created_ids():
        return (root, job_id, "first-after", "", "")
    # Owner found, create not ledgered: a link now would make Revenium create
    # the job nameless. Wait for the root's create (hermes-report.sh runs it
    # earlier in the same tick) for the bound _child_job_link_hold uses when the
    # root is not in the tick's set; past it the event ships unattributed.
    age = now - arc["first_ts"]
    if max_hold_seconds > 0 and 0 <= age < max(stale_seconds, settle_seconds):
        return (root, "", "", "create-pending", job_id)
    return (root, "", "create-missing", "", job_id)


out = []
probe_needed = 0
for row in pending:
    root, workflow_id, basis, hold, notice = _decide(row)
    if workflow_id or hold:
        probe_needed = 1
    out.append("|".join([
        row["sid"], row["tcid"], row["tool"], row["ts_iso"], str(row["dur"]), row["success"],
        _sanitize(root), workflow_id, basis, hold, _sanitize(notice), row["error"],
    ]))

# Sentinel rows. `__stats__` is FIRST so the bash loop knows whether to pay the
# capability probe before it ships anything; `__skipped__` stays LAST, carrying
# the pre-filtered count. Hermes session ids never take either form, so the
# bash loop treats those sids as sentinels rather than as events.
print("__stats__|%d|%d" % (len(root_info), probe_needed))
for line in out:
    print(line)
print(f"__skipped__|{skipped}")
PY
  )

  if [[ -n "${rows}" ]]; then
    local sid tcid tool ts_iso dur success_flag root_sid workflow_id basis hold notice error_msg
    while IFS='|' read -r sid tcid tool ts_iso dur success_flag root_sid workflow_id basis hold notice error_msg; do
      [[ -z "${sid}" || -z "${tcid}" ]] && continue

      if [[ "${sid}" == "__skipped__" ]]; then
        if [[ "${tcid}" =~ ^[0-9]+$ ]]; then
          skipped_count=$((skipped_count + tcid))
        fi
        continue
      fi
      if [[ "${sid}" == "__stats__" ]]; then
        if [[ "${tcid}" =~ ^[0-9]+$ ]]; then
          roots_resolved="${tcid}"
        fi
        # quick-261027-fib: the lazy `--workflow-id` capability probe. Fail-open:
        # a negative or indeterminate probe leaves workflow_capable=false and
        # every row of this run ships exactly as it did before the flag existed.
        if [[ "${tool}" == "1" ]]; then
          probe_needed=1
          if supports_flag "meter tool-event" "--workflow-id"; then workflow_capable=true; fi
        fi
        continue
      fi

      if [[ "${probe_needed}" -eq 1 && "${workflow_capable}" != "true" ]]; then
        workflow_id=""
        hold=""
        notice=""
        basis="cli-unsupported"
      fi

      # quick-261027-fib: a held row is counted and skipped BEFORE the per-row
      # grep, writes nothing to the ledger and is retried next tick. Each hold
      # was bounded in the heredoc (cap, liveness, sentinel or create bound), so
      # none can wait forever; the notice is logged once per (key, reason).
      if [[ -n "${hold}" ]]; then
        ((held_count++)) || true
        case "${hold}" in
          job-pending)
            _tool_event_log_once "${notice}" "job-pending" info \
              "Tool events held (job-pending): root=${notice} has no job marker yet and is still live; retried next tick, nothing ledgered"
            ;;
          create-pending)
            _tool_event_log_once "${notice}" "create-pending" info \
              "Tool events held (create-pending): job=${notice} has no confirmed create yet; retried next tick"
            ;;
          db-busy)
            _tool_event_log_once "${notice}" "db-busy" info \
              "Tool events held (db-busy): state.db locked while resolving ancestry; retried next tick"
            ;;
        esac
        continue
      fi

      # Idempotency guard: skip if this (sid, tool_call_id) pair is already ledgered.
      # Fixed-string match (-F): sid/tcid are untrusted and may carry regex
      # metacharacters; the heredoc strips ':' from both, so the "TOOL:<sid>:<tcid>:"
      # substring can only occur at the start of a ledger line. Runs BEFORE any
      # per-row work: the root-session lookup used to spawn python and read
      # state.db here, and paying it for a row about to be skipped is what made
      # ticks take an hour.
      if grep -qF "TOOL:${sid}:${tcid}:" "${TOOL_EVENTS_LEDGER_FILE}" 2>/dev/null; then
        ((skipped_count++)) || true
        continue
      fi

      # Phase 22 (TRACE-04 / D-01): root_sid is resolved in the heredoc above,
      # ONCE per root per tick, for subagent trace inheritance. The walk is the
      # get-root-session-id.py one (max_depth=10, fail-open on a missing db).
      # Top-level sessions get root_sid == sid -> byte-identical wire output (TRACE-05).
      # The TOOL ledger key below intentionally stays sid-scoped — the trace-id is
      # the analytics rollup key; the ledger key is per-subagent idempotency.
      [[ -z "${root_sid}" ]] && root_sid="${sid}"

      # Build CLI invocation as indexed array (Bash 3.2 portability — indexed arrays only)
      local cmd=(
        revenium meter tool-event
        --tool-id "${tool}"
        --duration-ms "${dur}"
        --timestamp "${ts_iso}"
        --trace-id "${root_sid}"
        --quiet
      )

      # --success defaults to false when omitted — must be explicit for successful events
      if [[ "${success_flag}" == "1" ]]; then
        cmd+=(--success)
      else
        cmd+=(--success=false)
        if [[ -n "${error_msg}" ]]; then
          cmd+=(--error-message "${error_msg}")
        fi
      fi

      if [[ -n "${ORG_NAME}" ]]; then
        cmd+=(--organization-name "${ORG_NAME}")
      fi

      # quick-261027-fib: the owning job. Appended AFTER every pre-existing flag,
      # so a row with no owner has the byte-identical argv it always had. The id
      # was validated and its create confirmed in the heredoc above; it travels
      # as one array element, never through a shell string.
      if [[ -n "${workflow_id}" ]]; then
        cmd+=(--workflow-id "${workflow_id}")
      fi

      # Invoke and capture exit code; never abort on failure (soft-fail mode)
      local cmd_output cmd_exit
      cmd_output=$("${cmd[@]}" 2>&1) && cmd_exit=0 || cmd_exit=$?

      if [[ "${cmd_exit}" -eq 0 ]]; then
        # D-07 / Pitfall 8: ledger write is the LAST statement of the success branch only.
        # A failed call must never produce a ledger entry — it would permanently suppress retry.
        local now_ts
        now_ts=$(python3 -c "import time; print(f'{time.time():.3f}')" 2>/dev/null || date +%s)
        echo "TOOL:${sid}:${tcid}:${now_ts}" >> "${TOOL_EVENTS_LEDGER_FILE}"
        ((reported_count++)) || true
        if [[ -n "${workflow_id}" ]]; then
          ((attributed_count++)) || true
        else
          ((unassigned_count++)) || true
          case "${basis}" in
            create-missing)
              _tool_event_log_once "${notice}" "create-missing" warn \
                "Tool events shipping WITHOUT --workflow-id (create-missing): job=${notice} has no confirmed create; linking now would make Revenium create it nameless"
              ;;
            hold-expired|ambiguous-arcs|invalid-job-id|unplaceable-job|markers-unreadable|bad-sid)
              _tool_event_log_once "${notice}" "${basis}" warn \
                "Tool events shipping WITHOUT --workflow-id (${basis}): root=${notice} ownership could not be established; events keep the root trace"
              ;;
            sid-unverified)
              _tool_event_log_once "${notice}" "sid-unverified" info \
                "Tool events unattributed (sid-unverified): sid=${notice} session id was not supplied by Hermes"
              ;;
          esac
        fi
        info "Reported: sid=${sid} tool=${tool} tool_call_id=${tcid} success=${success_flag} job=${workflow_id:-none} basis=${basis}"
      else
        warn "Failed: sid=${sid} tcid=${tcid} exit=${cmd_exit} output=${cmd_output}"
      fi
    done <<< "${rows}"
  fi

  info "=== Done. Reported ${reported_count}, skipped ${skipped_count}. Held ${held_count}; attributed ${attributed_count}, unassigned ${unassigned_count}; roots resolved ${roots_resolved}. ==="
}

main "$@"
