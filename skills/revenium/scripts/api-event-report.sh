#!/usr/bin/env bash
# api-event-report.sh — reads per-session api-event JSONL spool files (written
# by the revenium-classifier plugin's post_api_request hook) and ships each
# unledgered record to Revenium via `revenium meter completion`.
#
# Phase 32 tracer (D-01/D-03): one spool record in, one `meter completion`
# call out, one API: ledger line. No enrichment (task-type is hardcoded
# "unclassified" here -- plan 32-02 joins against markers/<sid>.jsonl at ship
# time per D-04), no delta scaling (each event IS the delta already), no
# split_strategies import (D-05 retires the split on the event path).
# Full attribution (root trace, squad flags, job id, organization,
# environment, model source) is deliberately NOT stubbed here -- their
# absence is the visible, correct state for this tracer; plan 32-02 adds
# them.
#
# Soft-fail: individual event failures are warned and skipped; the script
# never aborts (matches tool-event-report.sh's posture).

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

main() {
  info "=== API Event Reporter starting ==="

  local reported_count=0
  local skipped_count=0

  for event_file in "${EVENT_SPOOL_DIR}"/*.jsonl; do
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
            # 4 KB cap -- mirrors tool-event-report.sh's reader (T-15-03 defense)
            if len(line) > 4096:
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
            # Contract C-2 / Task 1e: --model is the record's response_model,
            # falling back to model.
            response_model = r.get("response_model") or model
            provider = r.get("provider") or ""
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
                total_tokens = int(r.get("total_tokens") or 0)
            except (TypeError, ValueError):
                continue
            try:
                request_time = datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                request_time = ""
            try:
                response_time = datetime.fromtimestamp(float(ended_at), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                response_time = ""
            if not request_time or not response_time:
                continue
            # Contract C-4: strip |, \n, \r (colons in api_request_id are
            # structural and preserved -- the ledger delimiter is | precisely
            # so they never collide). Mirrors WR-01 across the string fields
            # that could otherwise corrupt the pipe-delimited row below.
            for _bad in ("|", "\n", "\r"):
                sid = sid.replace(_bad, "_")
                arid = arid.replace(_bad, "_")
                model = model.replace(_bad, "_")
                response_model = response_model.replace(_bad, "_")
                provider = provider.replace(_bad, "_")
            print(f"{sid}|{arid}|{model}|{response_model}|{provider}|{input_tokens}|{output_tokens}|"
                  f"{cache_read_tokens}|{cache_write_tokens}|{total_tokens}|{request_time}|{response_time}|{duration_ms}")
except OSError:
    pass
PY
    )

    if [[ -z "${rows}" ]]; then
      continue
    fi

    local sid arid model response_model provider input_tokens output_tokens
    local cache_read_tokens cache_write_tokens total_tokens request_time response_time duration_ms
    while IFS='|' read -r sid arid model response_model provider input_tokens output_tokens \
      cache_read_tokens cache_write_tokens total_tokens request_time response_time duration_ms; do
      [[ -z "${sid}" || -z "${arid}" ]] && continue

      # Contract C-4: presence check before shipping, fixed-string match.
      # Safe unanchored for the same reason tool-event-report.sh's own check
      # is: "|" cannot appear inside field 1 (stripped above) and no field
      # contains the literal "API:" prefix, so this substring can only occur
      # at the start of a line.
      if grep -qF "API:${arid}|" "${EVENT_LEDGER_FILE}" 2>/dev/null; then
        ((skipped_count++)) || true
        continue
      fi

      local cmd=(
        revenium meter completion
        --model "${response_model}"
        --provider "${provider}"
        --input-tokens "${input_tokens}"
        --output-tokens "${output_tokens}"
        --cache-read-tokens "${cache_read_tokens}"
        --cache-creation-tokens "${cache_write_tokens}"
        --total-tokens "${total_tokens}"
        --stop-reason "END"
        --request-time "${request_time}"
        --completion-start-time "${request_time}"
        --response-time "${response_time}"
        --request-duration "${duration_ms}"
        --agent "${REVENIUM_AGENT_NAME}"
        --transaction-id "event:${arid}"
        --trace-id "${sid}"
        --is-streamed
        --quiet
        --task-type "unclassified"
        --operation-type "CHAT"
      )

      local cmd_output cmd_exit
      cmd_output=$("${cmd[@]}" 2>&1) && cmd_exit=0 || cmd_exit=$?

      if [[ "${cmd_exit}" -eq 0 ]]; then
        # Contract C-4 / D-07 parity: ledger line is the LAST statement of
        # the success branch only. A failed call must never produce a ledger
        # entry — it would permanently suppress retry.
        local now_ts
        now_ts=$(python3 -c "import time; print(f'{time.time():.3f}')" 2>/dev/null || date +%s)
        echo "API:${arid}|${sid}|${now_ts}" >> "${EVENT_LEDGER_FILE}"
        ((reported_count++)) || true
        info "Reported: sid=${sid} api_request_id=${arid} model=${response_model}"
      else
        warn "Failed: sid=${sid} api_request_id=${arid} exit=${cmd_exit} output=${cmd_output}"
      fi
    done <<< "${rows}"
  done

  info "=== Done. Reported ${reported_count}, skipped ${skipped_count}. ==="
}

main "$@"
