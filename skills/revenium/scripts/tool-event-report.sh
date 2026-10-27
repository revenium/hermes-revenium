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

created = None
root_info = {}


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


def _info_for(root):
    """Per-root facts, computed once per tick: only the ROOT's marker file is
    read (a subagent never ships its own job id), in the directory of the
    profile that OWNS the root."""
    if root in root_info:
        return root_info[root]
    d = {"bad_sid": False, "arcs": None}
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
        d["arcs"] = _ss.tool_event_job_arcs(os.path.join(mdir, root + ".jsonl"))
    root_info[root] = d
    return d


def _sanitize(value):
    for _bad in ("|", "\n", "\r"):
        value = value.replace(_bad, "_")
    return value


def _decide(row):
    """(root, workflow_id, basis, hold, notice) for one unledgered row."""
    sid = row["sid"]
    root = _root_of(sid) or sid
    if _ss is None:
        return (root, "", "attribution-unavailable", "", "")
    d = _info_for(root)
    if d["bad_sid"]:
        return (root, "", "bad-sid", "", root)
    ts = row["ts"]
    if ts > now + 300:
        return (root, "", "bad-ts", "", "")
    job_id, basis, arc = _ss.assign_tool_event_job(d["arcs"], ts)
    if job_id is None:
        if basis in ("ambiguous-arcs", "invalid-job-id", "unplaceable-job", "markers-unreadable"):
            return (root, "", basis, "", root)
        return (root, "", basis, "", "")
    if job_id in _created_ids():
        return (root, job_id, "first-after", "", "")
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
            ambiguous-arcs|invalid-job-id|unplaceable-job|markers-unreadable|bad-sid)
              _tool_event_log_once "${notice}" "${basis}" warn \
                "Tool events shipping WITHOUT --workflow-id (${basis}): root=${notice} ownership could not be established; events keep the root trace"
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
