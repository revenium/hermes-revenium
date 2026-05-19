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
      EVENT_FILE="${event_file}" python3 - <<'PY' 2>/dev/null || true
import json
import os
import sys
from datetime import datetime, timezone

event_file = os.environ.get("EVENT_FILE", "")
if not event_file:
    sys.exit(0)

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
            success_flag = "1" if success else "0"
            print(f"{sid}|{tool_call_id}|{tool}|{ts_iso}|{duration_ms}|{success_flag}|{error}")
except OSError:
    pass
PY
    )

    if [[ -z "${rows}" ]]; then
      continue
    fi

    local sid tcid tool ts_iso dur success_flag error_msg
    while IFS='|' read -r sid tcid tool ts_iso dur success_flag error_msg; do
      [[ -z "${sid}" || -z "${tcid}" ]] && continue

      # Idempotency guard: skip if this (sid, tool_call_id) pair is already ledgered.
      # Fixed-string match (-F): sid/tcid are untrusted and may carry regex
      # metacharacters; the heredoc strips ':' from both, so the "TOOL:<sid>:<tcid>:"
      # substring can only occur at the start of a ledger line.
      if grep -qF "TOOL:${sid}:${tcid}:" "${TOOL_EVENTS_LEDGER_FILE}" 2>/dev/null; then
        ((skipped_count++)) || true
        continue
      fi

      # Build CLI invocation as indexed array (Bash 3.2 portability — indexed arrays only)
      local cmd=(
        revenium meter tool-event
        --tool-id "${tool}"
        --duration-ms "${dur}"
        --timestamp "${ts_iso}"
        --trace-id "${sid}"
        --transaction-id "${sid}:${tcid}"
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
