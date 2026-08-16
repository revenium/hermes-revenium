#!/usr/bin/env bash
# api-event-report.sh — reads per-session api-event JSONL spool files (written
# by the revenium-classifier plugin's post_api_request hook), enriches each
# event with the task type that was actually in force when the call happened,
# and ships each unledgered record to Revenium via `revenium meter completion`.
#
# Phase 32 Plan 01 (D-01/D-03) proved the pipe end to end with a hardcoded
# "unclassified" task-type and no attribution. Plan 02 (this revision) makes
# what flows through it correct:
#
#   - D-09 partition (checked BEFORE the settle gate, session-level, not
#     per-record): a session already present in the frozen legacy HERMES:
#     ledger is skipped ENTIRELY by this path, so the two paths can never
#     double-report the same session.
#   - C-6 settle gate: a session's events are held until markers/.ready/<sid>
#     lands (resolved through the OWNING profile's directory — the same
#     per-session resolution hermes-report.sh already uses), or shipped as
#     unclassified once the session ages past REVENIUM_CRON_SETTLE_SECONDS
#     with no sentinel ever arriving (C-5b — preserves the standing
#     backward-compatibility guarantee for installs with no classifier).
#   - C-5/C-5a/D-14 temporal join: each event is attributed to the marker
#     whose window [marker_i.ts, marker_{i+1}.ts) contains the event's own
#     timestamp; events before the first window-owning marker extend that
#     marker's window backward — the deterministic shape of every session's
#     opening turn (classification fires strictly after turn 1's API calls
#     have already spooled), not a rare edge case. GUARDRAIL records are
#     excluded from the window-boundary list (they are classification
#     bookkeeping, always paired with a CHAT record carrying the identical
#     task_type, written microseconds apart) so a real API call — which is
#     always chat completion work on this event path — lands on the CHAT
#     window, matching contract C-5a's stated outcome: one row per API call,
#     `--operation-type CHAT`. No split_strategies import anywhere on this
#     path (D-05 retires the split here only — the legacy path is untouched).
#   - C-7 provider resolution: the event's native `provider` field, UNLESS it
#     names a routing layer (openrouter/litellm-substring/bedrock/custom/
#     empty/none/unknown), in which case derive the model provider from
#     response_model via the same mapping hermes-report.sh's retired heredoc
#     used — a strictly better input, since response_model is the model that
#     actually served rather than one column per session.
#   - C-8: no --total-cost. The event carries no cost field; Revenium prices
#     the row server-side from model/provider/tokens.
#   - Task 3: the new api_request_id ledger is a real idempotency domain —
#     presence-checked in memory (rebuilt from disk once per run, no grep
#     spawn per record), appended only after a successful call.
#
# Soft-fail: individual event/session failures are warned and skipped; the
# script never aborts (matches tool-event-report.sh's posture).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

if ! command -v revenium >/dev/null 2>&1; then
  warn "revenium CLI not found on PATH — skipping api-event metering."
  exit 0
fi
if ! command -v python3 >/dev/null 2>&1; then
  warn "python3 not found — skipping api-event metering."
  exit 0
fi
if ! revenium config show >/dev/null 2>&1; then
  warn "revenium not configured — run /revenium to set up."
  exit 0
fi
if [[ ! -d "${EVENT_SPOOL_DIR}" ]]; then
  warn "api-events spool directory does not exist — skipping api-event metering."
  exit 0
fi

touch "${EVENT_LEDGER_FILE}"

# --- Capability probes (once per run; fail open — a negative probe simply
# omits the flag, metering exactly as an older CLI always has). ---

JOBS_CLI_CAPABLE=false
if revenium jobs --help >/dev/null 2>&1 && \
   revenium meter completion --help 2>&1 | grep -q -- '--agentic-job-id'; then
  JOBS_CLI_CAPABLE=true
fi

TRACE_TYPE_CLI_CAPABLE=false
if revenium meter completion --help 2>&1 | grep -q -- '--trace-type'; then
  TRACE_TYPE_CLI_CAPABLE=true
fi

SQUAD_CLI_CAPABLE=false
if supports_flag "meter completion" "--squad-id"; then
  SQUAD_CLI_CAPABLE=true
fi

# Task 1c: native per-record reasoning-token breakout, gated behind its own
# probe (resolved once into a shell variable via `if supports_flag; then`,
# never `VAR=$(supports_flag ...)` — the latter swallows the exit status).
REASONING_TOKENS_CLI_CAPABLE=false
if supports_flag "meter completion" "--reasoning-tokens"; then
  REASONING_TOKENS_CLI_CAPABLE=true
fi

ORG_NAME=""
if [[ -f "${CONFIG_FILE}" ]]; then
  ORG_NAME=$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}')).get('organizationName', ''))" 2>/dev/null || true)
fi

# Phase 32 (EVT-03): resolve the set of spool directories to sweep — the
# process-level one plus each OTHER Hermes profile's own api-events
# directory, so a multiplexed gateway's per-profile records are not
# stranded (BUG-4's read-side gap, mirrored onto the spool). Directories
# are resolved ONCE here, before any file or record is read — never
# per-record — matching the cost discipline hermes-report.sh's own
# per-session resolvers document. Dedup by realpath (bash 3.2 has no
# associative arrays) so a directory reachable via more than one profile
# entry is never swept twice in one run.
_spool_dirs=()
_seen_spool_dirs=$'\n'

_add_spool_dir() {
  local d="$1"
  [[ -d "${d}" ]] || return 0
  local real
  real="$(cd "${d}" 2>/dev/null && pwd -P)" || return 0
  case "${_seen_spool_dirs}" in
    *$'\n'"${real}"$'\n'*) return 0 ;;
  esac
  _seen_spool_dirs="${_seen_spool_dirs}${real}"$'\n'
  _spool_dirs+=("${d}")
}

_add_spool_dir "${EVENT_SPOOL_DIR}"
while IFS=$'\t' read -r _profile_name _profile_home; do
  [[ -z "${_profile_home}" ]] && continue
  _add_spool_dir "${_profile_home}/state/revenium/api-events"
done < <(hermes_profile_homes)

# C-6: the .ready directory that owns a resolved per-session markers
# directory — mirrors hermes-report.sh's own belt: when the resolved
# directory equals the process-level MARKERS_DIR, use the (possibly
# independently overridden) MARKERS_READY_DIR; otherwise the resolved
# directory's own .ready subdirectory. Pure string function — no python3
# spawn needed.
_ready_dir_for_markers_dir() {
  local mdir="$1"
  if [[ "${mdir}" == "${MARKERS_DIR}" ]]; then
    printf '%s\n' "${MARKERS_READY_DIR}"
  else
    printf '%s\n' "${mdir}/.ready"
  fi
}

main() {
  info "=== API Event Reporter starting ==="

  local reported_count=0
  local held_sessions=0
  local legacy_skipped_sessions=0
  local dup_skipped_events=0

  local now
  now=$(date +%s)

  # Task 3a: build the new ledger's api_request_id presence lookup ONCE, in
  # memory, rather than a grep spawn per record — this path sees strictly
  # more records than the reporter's per-session spawns, which were already
  # the measured dominant fleet cost (quick-task 260814-e7c). Rebuilt from
  # the file at the start of this run; appended to in memory as new lines
  # are written below, so two records with the same id inside one run also
  # deduplicate (not just across runs).
  local _seen_arids=$'\n'
  if [[ -s "${EVENT_LEDGER_FILE}" ]]; then
    while IFS= read -r _arid; do
      [[ -z "${_arid}" ]] && continue
      _seen_arids="${_seen_arids}${_arid}"$'\n'
    done < <(
      EVENT_LEDGER_FILE="${EVENT_LEDGER_FILE}" python3 - <<'PY' 2>/dev/null
import os
p = os.environ.get("EVENT_LEDGER_FILE", "")
try:
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.startswith("API:"):
                continue
            rest = line[4:]
            idx = rest.find("|")
            if idx == -1:
                continue
            print(rest[:idx])
except OSError:
    pass
PY
    )
  fi

  # Enumerate every candidate spool file across every swept directory.
  local -a event_files=()
  local spool_dir event_file
  for spool_dir in "${_spool_dirs[@]}"; do
    for event_file in "${spool_dir}"/*.jsonl; do
      [[ -f "${event_file}" ]] || continue
      event_files+=("${event_file}")
    done
  done

  if [[ "${#event_files[@]}" -eq 0 ]]; then
    info "=== Done. No spool files found. ==="
    return
  fi

  # C-6/attribution: read state.db's sessions.source column ONCE for the
  # whole run (not per session) for the --environment flag. Uses Python's
  # stdlib sqlite3 module directly (no shelling to the sqlite3 CLI, so this
  # script gains no new external-tool precondition), opened read-only via a
  # URI so a missing state.db is never created as a side effect — this is
  # the cron-side shipper, not the in-session hook D-01 restricts.
  local _env_map_file
  _env_map_file=$(mktemp 2>/dev/null || echo "/tmp/revenium-api-event-env-map.$$")
  STATE_DB="${STATE_DB}" ENV_MAP_FILE="${_env_map_file}" python3 - <<'PY' 2>/dev/null || true
import os
import sqlite3

db = os.environ.get("STATE_DB", "")
out = os.environ.get("ENV_MAP_FILE", "")
if db and out and os.path.isfile(db):
    try:
        uri = f"file:{db}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            cur = conn.execute("SELECT id, COALESCE(source, '') FROM sessions")
            with open(out, "w", encoding="utf-8") as f:
                for sid, source in cur:
                    sid = str(sid) if sid is not None else ""
                    source = str(source) if source is not None else ""
                    if not sid:
                        continue
                    for bad in ("\t", "\n", "\r"):
                        sid = sid.replace(bad, "_")
                        source = source.replace(bad, "_")
                    f.write(f"{sid}\t{source}\n")
    except Exception:
        pass
PY

  for event_file in "${event_files[@]}"; do
    # --- Peek: one pass to learn this file's owning sid, event count, and
    # oldest event timestamp — cheap enough to do once per session file and
    # needed before any directory resolution below (which is keyed on sid).
    local peek
    peek=$(EVENT_FILE="${event_file}" python3 - <<'PY' 2>/dev/null
import json
import os

event_file = os.environ.get("EVENT_FILE", "")
sid = ""
count = 0
min_ts = None
try:
    with open(event_file, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or len(line) > 4096:
                continue
            try:
                r = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(r, dict):
                continue
            r_sid = r.get("sid") or ""
            arid = r.get("api_request_id") or ""
            if not r_sid or not arid:
                continue
            if not sid:
                sid = r_sid
            count += 1
            try:
                ts = float(r.get("ts"))
            except (TypeError, ValueError):
                continue
            if min_ts is None or ts < min_ts:
                min_ts = ts
except OSError:
    pass
print(f"SID={sid}")
print(f"COUNT={count}")
print(f"MIN_TS={min_ts if min_ts is not None else ''}")
PY
    )

    local sid count min_ts
    sid=$(echo "${peek}" | sed -n 's/^SID=//p' | head -1)
    count=$(echo "${peek}" | sed -n 's/^COUNT=//p' | head -1)
    min_ts=$(echo "${peek}" | sed -n 's/^MIN_TS=//p' | head -1)

    [[ -z "${sid}" ]] && continue
    [[ -z "${count}" || "${count}" == "0" ]] && continue

    # D-09 partition: session-level skip, checked BEFORE the settle gate —
    # this is the whole of the no-overlap guarantee between the two paths.
    if grep -q "^HERMES:${sid}:" "${LEDGER_FILE}" 2>/dev/null; then
      info "skipping ${sid} — already owned by the legacy HERMES: ledger (D-09 partition)"
      ((legacy_skipped_sessions++)) || true
      continue
    fi

    local session_markers_dir
    session_markers_dir="$(resolve_markers_dir "${sid}")"
    [[ -z "${session_markers_dir}" ]] && session_markers_dir="${MARKERS_DIR}"

    local ready_dir
    ready_dir="$(_ready_dir_for_markers_dir "${session_markers_dir}")"

    local has_sentinel=false
    [[ -e "${ready_dir}/${sid}" ]] && has_sentinel=true

    local join_mode
    if [[ "${has_sentinel}" == "true" ]]; then
      join_mode="join"
    else
      local age=0
      if [[ -n "${min_ts}" ]]; then
        age=$(NOW="${now}" MIN_TS="${min_ts}" python3 -c "
import os
try:
    now = float(os.environ.get('NOW', '0'))
    min_ts = float(os.environ.get('MIN_TS', '0'))
    print(max(0, int(now - min_ts)))
except Exception:
    print(0)
" 2>/dev/null || echo 0)
      fi
      if [[ "${age}" -lt "${REVENIUM_CRON_SETTLE_SECONDS}" ]]; then
        # T-32-10: logged ONCE per session per tick, never per record — the
        # measured precedent (9M lines/27 days from an ungated per-tick warn)
        # is exactly why this line lives here, outside any per-record loop.
        info "holding ${sid} — awaiting plugin sentinel (age=${age}s < settle=${REVENIUM_CRON_SETTLE_SECONDS}s, events=${count})"
        ((held_sessions++)) || true
        continue
      fi
      # C-5b / C-6 point 3: aged out with no sentinel — ship unclassified,
      # exactly the zero-marker fallback backward-compat guarantee. Do NOT
      # read the markers file in this mode even if one happens to exist.
      join_mode="unclassified"
    fi

    # Attribution flags resolved ONCE per session (not per event), mirroring
    # hermes-report.sh's own per-session-loop cost discipline.
    local root_sid
    root_sid="$(get_root_session_id "${sid}")"
    [[ -z "${root_sid}" ]] && root_sid="${sid}"

    local root_trace_type=""
    if [[ "${TRACE_TYPE_CLI_CAPABLE}" == "true" ]]; then
      local root_markers_dir
      if [[ "${root_sid}" == "${sid}" ]]; then
        root_markers_dir="${session_markers_dir}"
      else
        root_markers_dir="$(resolve_markers_dir "${root_sid}")"
        [[ -z "${root_markers_dir}" ]] && root_markers_dir="${MARKERS_DIR}"
      fi
      root_trace_type=$(
        ROOT_SID="${root_sid}" MARKERS_DIR="${root_markers_dir}" python3 - <<'PY' 2>/dev/null
import json, os
from pathlib import Path
root_sid = os.environ.get('ROOT_SID', '')
markers_dir = os.environ.get('MARKERS_DIR', '')
latest_type = ""
if root_sid and markers_dir:
    marker_path = Path(markers_dir) / f"{root_sid}.jsonl"
    if marker_path.exists():
        try:
            with open(marker_path, 'r', encoding='utf-8') as fh:
                for line in fh:
                    line = line.rstrip('\n')
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if not isinstance(rec, dict):
                        continue
                    if rec.get('kind') == 'job':
                        jt = rec.get('job_type')
                        if isinstance(jt, str) and jt:
                            for bad in ('\n', '\r'):
                                jt = jt.replace(bad, '_')
                            latest_type = jt
        except OSError:
            pass
print(latest_type)
PY
      )
      root_trace_type="${root_trace_type//[^A-Za-z0-9_-]/_}"
      root_trace_type="${root_trace_type:0:128}"
      [[ -z "${root_trace_type}" ]] && root_trace_type="uncategorized"
    fi

    local source_env=""
    if [[ -f "${_env_map_file}" ]]; then
      source_env=$(awk -F'\t' -v s="${sid}" '$1==s{print $2; exit}' "${_env_map_file}" 2>/dev/null)
    fi

    local markers_file="${session_markers_dir}/${sid}.jsonl"

    # --- Enrich: read the event file (and, in join mode, the markers file)
    # once each, join per event, and emit one pipe-delimited row per
    # shippable event. Contract C-4/T-32-08: pipe/newline/CR stripped and
    # length-capped on every field before it crosses the row boundary.
    local rows
    rows=$(
      EVENT_FILE="${event_file}" \
      MARKERS_FILE="${markers_file}" \
      JOIN_MODE="${join_mode}" \
      python3 - <<'PY' 2>/dev/null
import bisect
import json
import os
from datetime import datetime, timezone

event_file = os.environ.get("EVENT_FILE", "")
markers_file = os.environ.get("MARKERS_FILE", "")
join_mode = os.environ.get("JOIN_MODE", "unclassified")


def _iso(ts):
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def _clean(s, cap=128):
    s = s or ""
    for bad in ("|", "\n", "\r"):
        s = s.replace(bad, "_")
    return s[:cap]


def _infer_provider(model_lc):
    if "claude" in model_lc or "anthropic" in model_lc:
        return "anthropic"
    if "gpt" in model_lc or "o1" in model_lc or "o3" in model_lc:
        return "openai"
    if "gemini" in model_lc:
        return "google"
    if "grok" in model_lc or "x-ai" in model_lc:
        return "xai"
    if "deepseek" in model_lc:
        return "deepseek"
    if "llama" in model_lc or "mistral" in model_lc:
        return "meta"
    return "unknown"


_ROUTING_LAYER_NAMES = {"openrouter", "bedrock", "custom", "none", "unknown", ""}


def _resolve_provider(provider_raw, response_model):
    # Contract C-7: verbatim, unless the field names a ROUTING layer rather
    # than a model provider — in which case derive the model provider from
    # response_model, the same mapping the retired hermes-report.sh heredoc
    # used, with a strictly better input (the model that actually served).
    p_lc = (provider_raw or "").strip().lower()
    is_routing = p_lc in _ROUTING_LAYER_NAMES or "litellm" in p_lc
    if not is_routing:
        return provider_raw or ""
    return _infer_provider((response_model or "").lower())


_STOP_REASON_MAP = {
    "stop": "END", "end_turn": "END",
    "tool_calls": "TOOL_CALL", "tool_use": "TOOL_CALL",
    "length": "TOKEN_LIMIT", "max_tokens": "TOKEN_LIMIT",
    "content_filter": "CONTENT_FILTER",
}


def _stop_reason(finish_reason):
    # Closed allowlist; anything unrecognised/empty/absent maps to END (the
    # constant the legacy path always shipped) so an unexpected provider
    # value can never strand a record via CLI rejection.
    return _STOP_REASON_MAP.get((finish_reason or "").strip().lower(), "END")


# --- Load markers (task markers only) for the temporal join (C-5). ---
markers = []
if join_mode == "join" and markers_file and os.path.isfile(markers_file):
    REQUIRED = ("muid", "ts", "sid", "task_type", "operation_type")
    try:
        with open(markers_file, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line or len(line) > 4096:
                    continue
                try:
                    m = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(m, dict):
                    continue
                if m.get("kind") is not None:
                    continue
                if not all(k in m for k in REQUIRED):
                    continue
                try:
                    m["ts"] = float(m["ts"])
                except (TypeError, ValueError):
                    continue
                markers.append(m)
    except OSError:
        pass
markers.sort(key=lambda m: m["ts"])

# Contract C-5a: GUARDRAIL records are classification bookkeeping, always
# paired microseconds apart with a CHAT record carrying the IDENTICAL
# task_type. Excluding them from the window-BOUNDARY list (they are still
# read and validated above) means a real API call — which is always chat
# completion work on this event path — lands on the CHAT window, including
# events preceding the pair entirely (D-14's backward extension then reaches
# the CHAT window rather than GUARDRAIL's degenerate one). Falls back to the
# unfiltered list only if that would leave nothing to attribute to.
window_markers = [m for m in markers if m.get("operation_type") != "GUARDRAIL"]
if not window_markers:
    window_markers = markers
marker_ts = [m["ts"] for m in window_markers]


def _attribution_for(ts):
    if not window_markers:
        return "unclassified", "CHAT", "", ""
    idx = bisect.bisect_right(marker_ts, ts) - 1
    if idx < 0:
        idx = 0
    m = window_markers[idx]
    task_type = _clean(m.get("task_type") or "unclassified", 128)
    operation_type = _clean(m.get("operation_type") or "CHAT", 32)
    trace_id = _clean(m.get("trace_id") or "", 256)
    agentic_job_id = _clean(m.get("agentic_job_id") or "", 128)
    return task_type, operation_type, trace_id, agentic_job_id


try:
    with open(event_file, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or len(line) > 4096:
                continue
            try:
                r = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(r, dict):
                continue
            sid = r.get("sid") or ""
            arid = r.get("api_request_id") or ""
            if not sid or not arid:
                continue
            model = r.get("model") or ""
            response_model = r.get("response_model") or model
            provider_raw = r.get("provider") or ""
            ts = r.get("ts")
            ended_at = r.get("ended_at")
            try:
                duration_ms = int(r.get("duration_ms") or 0)
            except (TypeError, ValueError):
                duration_ms = 0
            try:
                input_tokens = int(r.get("input_tokens") or 0)
                output_tokens = int(r.get("output_tokens") or 0)
                cache_read_tokens = int(r.get("cache_read_tokens") or 0)
                cache_write_tokens = int(r.get("cache_write_tokens") or 0)
                reasoning_tokens = int(r.get("reasoning_tokens") or 0)
                total_tokens = int(r.get("total_tokens") or 0)
            except (TypeError, ValueError):
                continue

            try:
                event_ts = float(ts)
            except (TypeError, ValueError):
                continue

            request_time = _iso(ts)
            response_time = _iso(ended_at)
            if not request_time or not response_time:
                continue

            if join_mode == "join":
                task_type, operation_type, trace_id, agentic_job_id = _attribution_for(event_ts)
            else:
                task_type, operation_type, trace_id, agentic_job_id = "unclassified", "CHAT", "", ""

            provider_resolved = _resolve_provider(provider_raw, response_model)
            stop_reason = _stop_reason(r.get("finish_reason"))

            row = [
                _clean(sid, 256), _clean(arid, 256), _clean(response_model, 256),
                _clean(provider_raw, 128), _clean(provider_resolved, 128),
                str(input_tokens), str(output_tokens), str(cache_read_tokens),
                str(cache_write_tokens), str(reasoning_tokens), str(total_tokens),
                request_time, response_time, str(duration_ms), stop_reason,
                task_type, operation_type, trace_id, agentic_job_id,
            ]
            print("|".join(row))
except OSError:
    pass
PY
    )

    [[ -z "${rows}" ]] && continue

    local sid_r arid_r model_r provider_raw_r provider_resolved_r
    local input_r output_r cache_read_r cache_write_r reasoning_r total_r
    local request_time_r response_time_r duration_r stop_reason_r
    local task_type_r operation_type_r trace_id_r agentic_job_id_r

    while IFS='|' read -r sid_r arid_r model_r provider_raw_r provider_resolved_r \
      input_r output_r cache_read_r cache_write_r reasoning_r total_r \
      request_time_r response_time_r duration_r stop_reason_r \
      task_type_r operation_type_r trace_id_r agentic_job_id_r; do
      [[ -z "${sid_r}" || -z "${arid_r}" ]] && continue

      # Task 3a: in-memory presence check — no subprocess per record.
      case "${_seen_arids}" in
        *$'\n'"${arid_r}"$'\n'*)
          ((dup_skipped_events++)) || true
          continue
          ;;
      esac

      local cmd=(
        revenium meter completion
        --model "${model_r}"
        --provider "${provider_resolved_r}"
        --input-tokens "${input_r}"
        --output-tokens "${output_r}"
        --cache-read-tokens "${cache_read_r}"
        --cache-creation-tokens "${cache_write_r}"
        --total-tokens "${total_r}"
        --stop-reason "${stop_reason_r}"
        --request-time "${request_time_r}"
        --completion-start-time "${request_time_r}"
        --response-time "${response_time_r}"
        --request-duration "${duration_r}"
        --agent "${REVENIUM_AGENT_NAME}"
        --transaction-id "event:${arid_r}"
        --trace-id "${trace_id_r:-${root_sid}}"
        --is-streamed
        --quiet
        --task-type "${task_type_r}"
        --operation-type "${operation_type_r}"
      )

      # Task 1c: native per-record reasoning breakout, capability-gated.
      if [[ "${REASONING_TOKENS_CLI_CAPABLE}" == "true" && "${reasoning_r}" -gt 0 ]]; then
        cmd+=(--reasoning-tokens "${reasoning_r}")
      fi
      # C-7: --model-source mirrors the legacy path's use of billing_provider
      # as the routing-info slot — the event's RAW (unresolved) provider.
      if [[ -n "${provider_raw_r}" ]]; then
        cmd+=(--model-source "${provider_raw_r}")
      fi
      # C-8: --total-cost is deliberately never appended on this path — the
      # event carries no cost field; Revenium prices the row server-side.
      if [[ -n "${ORG_NAME}" ]]; then
        cmd+=(--organization-name "${ORG_NAME}")
      fi
      if [[ -n "${source_env}" ]]; then
        cmd+=(--environment "${source_env}")
      fi
      if [[ "${TRACE_TYPE_CLI_CAPABLE}" == "true" ]]; then
        cmd+=(--trace-type "${root_trace_type:-uncategorized}")
      fi
      if [[ "${JOBS_CLI_CAPABLE}" == "true" && -n "${agentic_job_id_r}" ]]; then
        cmd+=(--agentic-job-id "${agentic_job_id_r}")
      fi
      if [[ "${SQUAD_CLI_CAPABLE}" == "true" ]]; then
        cmd+=(--squad-id "${root_sid}")
        cmd+=(--squad-name "${REVENIUM_SQUAD_NAME:-${REVENIUM_AGENT_NAME}}")
        if [[ "${root_sid}" == "${sid_r}" ]]; then
          cmd+=(--squad-role "root")
        else
          cmd+=(--squad-role "subagent")
        fi
      fi

      local cmd_output cmd_exit
      cmd_output=$("${cmd[@]}" 2>&1) && cmd_exit=0 || cmd_exit=$?

      if [[ "${cmd_exit}" -eq 0 ]]; then
        # Task 3b: ledger line is the LAST statement of the success branch
        # only. A failed call must never produce a ledger entry — it would
        # permanently suppress retry.
        local now_ts
        now_ts=$(python3 -c "import time; print(f'{time.time():.3f}')" 2>/dev/null || date +%s)
        echo "API:${arid_r}|${sid_r}|${now_ts}" >> "${EVENT_LEDGER_FILE}"
        _seen_arids="${_seen_arids}${arid_r}"$'\n'
        ((reported_count++)) || true
        info "Reported: sid=${sid_r} api_request_id=${arid_r} model=${model_r} task_type=${task_type_r} operation_type=${operation_type_r}"
      else
        warn "Failed: sid=${sid_r} api_request_id=${arid_r} exit=${cmd_exit} output=${cmd_output}"
      fi
    done <<< "${rows}"
  done

  rm -f "${_env_map_file}" 2>/dev/null || true

  info "=== Done. Reported ${reported_count}, held-sessions=${held_sessions}, legacy-skipped-sessions=${legacy_skipped_sessions}, duplicate-skipped-events=${dup_skipped_events}. ==="
}

main "$@"
