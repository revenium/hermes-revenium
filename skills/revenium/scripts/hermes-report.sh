#!/usr/bin/env bash
# Hermes-native Revenium reporter. Reads token usage from ~/.hermes/state.db
# and ships deltas to Revenium via `revenium meter completion`.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

if ! command -v revenium >/dev/null 2>&1; then
  warn "revenium CLI not found on PATH — skipping metering."
  exit 0
fi
if ! command -v sqlite3 >/dev/null 2>&1; then
  warn "sqlite3 not found — skipping metering."
  exit 0
fi
if ! command -v python3 >/dev/null 2>&1; then
  warn "python3 not found — skipping metering."
  exit 0
fi
if [[ ! -f "${STATE_DB}" ]]; then
  warn "Hermes state.db not found at ${STATE_DB} — skipping."
  exit 0
fi
if ! revenium config show >/dev/null 2>&1; then
  warn "revenium not configured — run /revenium to set up."
  exit 0
fi

touch "${LEDGER_FILE}"

ORG_NAME=""
if [[ -f "${CONFIG_FILE}" ]]; then
  ORG_NAME=$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}')).get('organizationName', ''))" 2>/dev/null || true)
fi

main() {
  info "=== Hermes Metering Reporter starting ==="

  local sessions
  sessions=$(sqlite3 "${STATE_DB}" "
    SELECT id, model, source, input_tokens, output_tokens,
           cache_read_tokens, cache_write_tokens, reasoning_tokens,
           estimated_cost_usd, api_call_count, started_at, ended_at,
           billing_provider
    FROM sessions
    WHERE (input_tokens > 0 OR output_tokens > 0)
    ORDER BY started_at DESC;
  " 2>/dev/null) || { warn "Failed to query state.db"; exit 0; }

  if [[ -z "${sessions}" ]]; then
    info "No sessions with token usage found."
    return
  fi

  local reported_count=0
  local skipped_count=0

  while IFS='|' read -r sid model source input_tokens output_tokens       cache_read cache_write reasoning_tokens estimated_cost       api_calls started_at ended_at billing_provider; do

    local total_tokens=$((input_tokens + output_tokens))
    if [[ "${total_tokens}" -eq 0 ]]; then
      continue
    fi

    local ledger_key="HERMES:${sid}:${total_tokens}"
    if grep -q "^HERMES:${sid}:${total_tokens}:" "${LEDGER_FILE}" 2>/dev/null; then
      ((skipped_count++)) || true
      continue
    fi

    local prev_reported_tokens=0
    local prev_line
    prev_line=$(grep "^HERMES:${sid}:" "${LEDGER_FILE}" 2>/dev/null | tail -1 || true)
    if [[ -n "${prev_line}" ]]; then
      prev_reported_tokens=$(echo "${prev_line}" | cut -d: -f3)
      if [[ "${total_tokens}" -le "${prev_reported_tokens}" ]]; then
        ((skipped_count++)) || true
        continue
      fi
    fi

    local delta_input delta_output delta_cache_read delta_cache_write delta_total
    if [[ "${prev_reported_tokens}" -gt 0 ]]; then
      local ratio
      ratio=$(python3 -c "
prev = ${prev_reported_tokens}
curr = ${total_tokens}
if prev > 0 and curr > prev:
    print(f'{(curr - prev) / curr:.6f}')
else:
    print('1.0')
" 2>/dev/null || echo "1.0")
      delta_input=$(python3 -c "print(max(0, int(${input_tokens} * ${ratio})))" 2>/dev/null)
      delta_output=$(python3 -c "print(max(0, int(${output_tokens} * ${ratio})))" 2>/dev/null)
      delta_cache_read=$(python3 -c "print(max(0, int(${cache_read} * ${ratio})))" 2>/dev/null)
      delta_cache_write=$(python3 -c "print(max(0, int(${cache_write} * ${ratio})))" 2>/dev/null)
    else
      delta_input="${input_tokens}"
      delta_output="${output_tokens}"
      delta_cache_read="${cache_read}"
      delta_cache_write="${cache_write}"
    fi
    delta_total=$((delta_input + delta_output))

    if [[ "${delta_total}" -eq 0 ]]; then
      ((skipped_count++)) || true
      continue
    fi

    local clean_model provider
    clean_model=$(python3 -c "
model = '${model}'
if '/' in model:
    model = model.split('/', 1)[1]
for prefix in ('global.', 'anthropic.', 'openai.', 'google.', 'x-ai.'):
    if model.startswith(prefix):
        model = model[len(prefix):]
print(model)
" 2>/dev/null || echo "${model}")

    provider=$(python3 -c "
model = '${model}'.lower()
billing = '${billing_provider}'.lower()
if billing and billing not in ('', 'none', 'unknown'):
    if billing == 'openrouter':
        if 'claude' in model or 'anthropic' in model:
            print('anthropic')
        elif 'gpt' in model or 'o1' in model or 'o3' in model:
            print('openai')
        elif 'gemini' in model:
            print('google')
        elif 'grok' in model or 'x-ai' in model:
            print('xai')
        elif 'deepseek' in model:
            print('deepseek')
        else:
            print(billing)
    elif billing == 'bedrock':
        if 'claude' in model:
            print('anthropic')
        else:
            print('aws')
    else:
        print(billing)
else:
    if 'claude' in model or 'anthropic' in model:
        print('anthropic')
    elif 'gpt' in model or 'o1-' in model or 'o3-' in model:
        print('openai')
    elif 'gemini' in model:
        print('google')
    elif 'grok' in model or 'x-ai' in model:
        print('xai')
    elif 'deepseek' in model:
        print('deepseek')
    elif 'llama' in model or 'mistral' in model:
        print('meta')
    else:
        print('unknown')
" 2>/dev/null || echo "unknown")

    local request_time response_time duration_ms
    local last_report_ts=""
    if [[ "${prev_reported_tokens}" -gt 0 ]]; then
      last_report_ts=$(grep "^HERMES:${sid}:" "${LEDGER_FILE}" 2>/dev/null | tail -1 | cut -d: -f4 || true)
    fi

    request_time=$(python3 -c "
from datetime import datetime, timezone
last_ts = '${last_report_ts}'
started = float('${started_at}')
ts = float(last_ts) if last_ts else started
print(datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
" 2>/dev/null || date -u +%Y-%m-%dT%H:%M:%SZ)

    response_time=$(python3 -c "
from datetime import datetime, timezone
import time
ended = '${ended_at}'
ts = float(ended) if ended else time.time()
print(datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
" 2>/dev/null || date -u +%Y-%m-%dT%H:%M:%SZ)

    duration_ms=$(python3 -c "
import time
last_ts = '${last_report_ts}'
started = float('${started_at}')
ended = '${ended_at}'
start = float(last_ts) if last_ts else started
end = float(ended) if ended else time.time()
print(max(0, int((end - start) * 1000)))
" 2>/dev/null || echo "0")

    local delta_cost="0"
    if [[ -n "${estimated_cost}" && "${estimated_cost}" != "0" && "${estimated_cost}" != "0.0" ]]; then
      if [[ "${prev_reported_tokens}" -gt 0 ]]; then
        delta_cost=$(python3 -c "
prev = ${prev_reported_tokens}
curr = ${total_tokens}
cost = float('${estimated_cost}')
if prev > 0 and curr > prev:
    print(f'{cost * (curr - prev) / curr:.6f}')
else:
    print(f'{cost:.6f}')
" 2>/dev/null || echo "0")
      else
        delta_cost="${estimated_cost}"
      fi
    fi

    local cmd=(
      revenium meter completion
      --model "${clean_model}"
      --provider "${provider}"
      --input-tokens "${delta_input}"
      --output-tokens "${delta_output}"
      --cache-read-tokens "${delta_cache_read}"
      --cache-creation-tokens "${delta_cache_write}"
      --total-tokens "${delta_total}"
      --stop-reason "END"
      --request-time "${request_time}"
      --completion-start-time "${request_time}"
      --response-time "${response_time}"
      --request-duration "${duration_ms}"
      --agent "Hermes"
      --transaction-id "${sid}-${total_tokens}"
      --trace-id "${sid}"
      --is-streamed
      --quiet
    )

    if [[ -n "${billing_provider}" ]]; then
      cmd+=(--model-source "${billing_provider}")
    fi
    if [[ "${delta_cost}" != "0" && "${delta_cost}" != "0.0" ]]; then
      cmd+=(--total-cost "${delta_cost}")
    fi
    if [[ -n "${ORG_NAME}" ]]; then
      cmd+=(--organization-name "${ORG_NAME}")
    fi
    if [[ -n "${source}" ]]; then
      cmd+=(--environment "${source}")
    fi

    local cmd_output cmd_exit
    cmd_output=$("${cmd[@]}" 2>&1) && cmd_exit=0 || cmd_exit=$?

    if [[ "${cmd_exit}" -eq 0 ]]; then
      local now_ts
      now_ts=$(python3 -c "import time; print(f'{time.time():.3f}')" 2>/dev/null || date +%s)
      echo "${ledger_key}:${now_ts}" >> "${LEDGER_FILE}"
      ((reported_count++)) || true
      info "Reported: session=${sid} model=${clean_model} provider=${provider} in=${delta_input} out=${delta_output} cost=${delta_cost}"
    else
      warn "Failed: session=${sid} exit=${cmd_exit} output=${cmd_output}"
      warn "Command: ${cmd[*]}"
    fi
  done <<< "${sessions}"

  info "=== Done. Reported ${reported_count}, skipped ${skipped_count}. ==="
}

main "$@"
