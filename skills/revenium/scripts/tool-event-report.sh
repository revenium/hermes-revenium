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

main() {
  info "=== Tool Event Reporter starting ==="

  if [[ ! -d "${TOOL_EVENTS_DIR}" ]]; then
    info "No tool-events directory — nothing to report."
    return
  fi

  local reported_count=0
  local skipped_count=0

  for event_file in "${TOOL_EVENTS_DIR}"/*.jsonl; do
    [[ -f "${event_file}" ]] || continue

    local rows
    rows=$(
      EVENT_FILE="${event_file}" LEDGER_FILE="${TOOL_EVENTS_LEDGER_FILE}" python3 - <<'PY' 2>/dev/null || true
import json
import os
import sys
from datetime import datetime, timezone

event_file = os.environ.get("EVENT_FILE", "")
if not event_file:
    sys.exit(0)

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
            print(f"{sid}|{tool_call_id}|{tool}|{ts_iso}|{duration_ms}|{success_flag}|{error}")
except OSError:
    pass
# Sentinel row carrying the pre-filtered count, always the last line. Hermes
# session ids never take the form "__skipped__", so the bash loop treats that
# sid as the sentinel rather than as an event.
print(f"__skipped__|{skipped}")
PY
    )

    if [[ -z "${rows}" ]]; then
      continue
    fi

    local sid tcid tool ts_iso dur success_flag error_msg
    while IFS='|' read -r sid tcid tool ts_iso dur success_flag error_msg; do
      [[ -z "${sid}" || -z "${tcid}" ]] && continue

      if [[ "${sid}" == "__skipped__" ]]; then
        if [[ "${tcid}" =~ ^[0-9]+$ ]]; then
          skipped_count=$((skipped_count + tcid))
        fi
        continue
      fi

      # Idempotency guard: skip if this (sid, tool_call_id) pair is already ledgered.
      # Fixed-string match (-F): sid/tcid are untrusted and may carry regex
      # metacharacters; the heredoc strips ':' from both, so the "TOOL:<sid>:<tcid>:"
      # substring can only occur at the start of a ledger line. Runs BEFORE the
      # root-session lookup: that lookup spawns python and reads state.db, and
      # paying it for a row about to be skipped is what made ticks take an hour.
      if grep -qF "TOOL:${sid}:${tcid}:" "${TOOL_EVENTS_LEDGER_FILE}" 2>/dev/null; then
        ((skipped_count++)) || true
        continue
      fi

      # Phase 22 (TRACE-04 / D-01): resolve root_sid ONCE per row for subagent
      # trace inheritance. Phase 21's helper walks state.db.sessions.parent_session_id
      # to the root delegator (max_depth=10, fail-open on missing/locked db).
      # Top-level sessions get root_sid == sid -> byte-identical wire output (TRACE-05).
      # The TOOL ledger key below intentionally stays sid-scoped — the trace-id is
      # the analytics rollup key; the ledger key is per-subagent idempotency.
      local root_sid
      root_sid="$(get_root_session_id "${sid}")"
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
        info "Reported: sid=${sid} tool=${tool} tool_call_id=${tcid} success=${success_flag}"
      else
        warn "Failed: sid=${sid} tcid=${tcid} exit=${cmd_exit} output=${cmd_output}"
      fi
    done <<< "${rows}"
  done

  info "=== Done. Reported ${reported_count}, skipped ${skipped_count}. ==="
}

main "$@"
