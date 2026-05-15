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

  # G-03 sentinel-or-aged filter (D-21): drop sessions younger than SETTLE_SECONDS
  # that have no plugin sentinel at MARKERS_READY_DIR/<sid>. Sessions WITH a sentinel
  # OR older than the settle window pass through unchanged. The downstream while-loop
  # below is byte-identical to pre-edit. Soft-fail: on heredoc error, the original
  # ${sessions} flows through unfiltered (legacy behavior).
  local sentinel_skipped
  sentinel_skipped=$(mktemp 2>/dev/null || echo "/tmp/hermes-sentinel-skipped.$$")
  local filtered_sessions
  filtered_sessions=$(
    SESSIONS="${sessions}" \
    MARKERS_READY_DIR="${MARKERS_READY_DIR}" \
    REVENIUM_CRON_SETTLE_SECONDS="${REVENIUM_CRON_SETTLE_SECONDS:-120}" \
    SKIPPED_LOG="${sentinel_skipped}" \
    python3 - <<'PY' 2>/dev/null
import os
import sys
import time
from pathlib import Path

try:
    settle_seconds = int(os.environ.get('REVENIUM_CRON_SETTLE_SECONDS', '120'))
except (TypeError, ValueError):
    settle_seconds = 120

markers_ready_dir = Path(os.environ.get('MARKERS_READY_DIR', ''))
skipped_log = os.environ.get('SKIPPED_LOG', '')
sessions_data = os.environ.get('SESSIONS', '')

now = int(time.time())

try:
    skip_out = open(skipped_log, 'w', encoding='utf-8') if skipped_log else None
except OSError:
    skip_out = None

for raw_line in sessions_data.split('\n'):
    line = raw_line.rstrip('\n').rstrip('\r')
    if not line:
        continue
    try:
        parts = line.split('|')
        # Columns: id|model|source|input|output|cache_read|cache_write|reasoning|
        #          estimated_cost|api_calls|started_at|ended_at|billing_provider
        # started_at is index 10 (the 11th column).
        if len(parts) < 11:
            # Malformed row — pass through unchanged (soft-fail).
            print(line)
            continue
        sid = parts[0]
        try:
            started_at_int = int(float(parts[10]))
        except (TypeError, ValueError):
            # Pass through unparseable started_at (soft-fail).
            print(line)
            continue
        age = now - started_at_int
        try:
            has_sentinel = (markers_ready_dir / sid).exists() if str(markers_ready_dir) else False
        except OSError:
            has_sentinel = False
        if has_sentinel or age >= settle_seconds:
            print(line)
        else:
            if skip_out is not None:
                try:
                    skip_out.write(f"{sid}\t{age}\t{settle_seconds}\n")
                except OSError:
                    pass
    except Exception:
        # Belt: any unexpected error → pass the row through unmodified.
        print(line)
        continue

if skip_out is not None:
    try:
        skip_out.close()
    except OSError:
        pass
PY
  ) || filtered_sessions="${sessions}"

  # Emit one info log line per skipped session via the existing info helper
  # so the cron log captures the proper timestamp + [INFO ] [revenium] prefix.
  if [[ -s "${sentinel_skipped}" ]]; then
    while IFS=$'\t' read -r skip_sid skip_age skip_settle; do
      [[ -z "${skip_sid}" ]] && continue
      info "skipping ${skip_sid} — awaiting plugin sentinel (age=${skip_age}s < settle=${skip_settle}s)"
    done < "${sentinel_skipped}"
  fi
  rm -f "${sentinel_skipped}" 2>/dev/null || true

  sessions="${filtered_sessions}"

  if [[ -z "${sessions}" ]]; then
    info "All candidate sessions deferred — awaiting plugin sentinels."
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

    # Phase 3 (CRON-01 / MARK-04 / TAX-05 / D-14 / D-15 / D-18): per-session marker reader.
    # Reads ${MARKERS_DIR}/${sid}.jsonl filtered by the prior ledger row's cutoff (ts,
    # muids) via the shared parse_prior_state helper (B6). Emits the S2 telemetry log
    # lines locked by D-18. This commit (T04) does NOT yet change wire behavior — the
    # legacy single-call cmd array below is still emitted unchanged. T05 introduces the
    # per-marker cutover wrapped in 'if n_markers > 0' / else.
    local marker_rows=()
    local n_markers=0
    local prior_muids_count=0
    local s2_info_line=""
    local s2_warn_line=""
    local read_ok="true"
    local marker_output=""
    marker_output=$(
      MARKERS_DIR="${MARKERS_DIR}" \
      SID="${sid}" \
      TOTAL_TOKENS="${total_tokens}" \
      DELTA_TOTAL="${delta_total}" \
      SCRIPT_DIR="${SCRIPT_DIR}" \
      LEDGER_PATH="${LEDGER_FILE}" \
      python3 - <<'PY' 2>&1
import json
import os
import sys
from pathlib import Path

try:
    sys.path.insert(0, os.environ['SCRIPT_DIR'])
    from split_strategies import parse_prior_state
except Exception as exc:
    # B6 / Pitfall A defense: if the helper can't be imported, fall through to
    # the legacy single-call path. The bash side sees READ_OK=false.
    print(f"READ_OK=false")
    print(f"READ_ERR=import: {exc}")
    sys.exit(0)

markers_dir = os.environ['MARKERS_DIR']
sid = os.environ['SID']
try:
    total_tokens = int(os.environ['TOTAL_TOKENS'])
except (TypeError, ValueError):
    total_tokens = 0
try:
    delta_total = int(os.environ['DELTA_TOTAL'])
except (TypeError, ValueError):
    delta_total = 0
ledger_path = os.environ['LEDGER_PATH']

# A2 defense lives inside parse_prior_state (asserts ':' not in sid). Catch the
# AssertionError here and fall through to the legacy path with a warn log.
try:
    prior_ts, prior_muids = parse_prior_state(ledger_path, sid, total_tokens)
except AssertionError as exc:
    print("READ_OK=false")
    print(f"READ_ERR=sid-format: {exc}")
    sys.exit(0)
except Exception as exc:
    print("READ_OK=false")
    print(f"READ_ERR=parse: {exc}")
    sys.exit(0)

# TAX-05 (D-14) trivial-label blocklist enforced cron-side as defense-in-depth.
FORBIDDEN = {'ack', 'acknowledgment', 'greeting', 'confirmation', 'hello', 'thanks'}
REQUIRED_KEYS = ('muid', 'ts', 'sid', 'task_type', 'operation_type')

marker_path = Path(markers_dir) / f"{sid}.jsonl"
markers = []
read_ok = True
read_err = ""
if marker_path.is_file():
    try:
        with marker_path.open() as f:
            for line in f:
                line = line.rstrip('\n')
                if not line:
                    continue
                # T-03-04 defense: cap per-line memory at 4 KB.
                if len(line) > 4096:
                    continue
                # MARK-04 / D-15: per-line try/except. A torn last line or any
                # malformed line is skipped; loop continues.
                try:
                    m = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not all(k in m for k in REQUIRED_KEYS):
                    continue
                # Primary dedup: global muid set. parse_prior_state returns
                # every muid ever ledger'd for this sid across all total_tokens
                # windows, so a muid that already shipped will be in this set
                # regardless of which tick reported it. Partial-failure recovery
                # (COMPAT-03 / SC2) relies on this: muids 4-5 of a 5-marker batch
                # whose tick crashed between calls 3 and 5 stay OUT of the set
                # and are correctly re-emitted on the next tick.
                if m['muid'] in prior_muids:
                    continue
                # Secondary (v1-only) fallback: when no v2 muids exist yet for
                # this sid (fresh upgrade, ledger has only v1 rows), use the
                # ts cutoff to avoid mass-emitting any marker history that
                # predates the upgrade. Once any v2 row exists, prior_muids is
                # the complete record and the ts filter is harmful (it would
                # skip un-emitted markers whose ts predates the latest v2 row).
                if not prior_muids:
                    try:
                        if float(m['ts']) <= prior_ts:
                            continue
                    except (TypeError, ValueError):
                        continue
                if m.get('task_type') in FORBIDDEN:
                    continue
                markers.append(m)
    except OSError as exc:
        # D-14 / D-15: any other file-read OSError falls through.
        read_ok = False
        read_err = f"oserror: {exc}"

n = len(markers)
# D-18 telemetry log lines — locked text, do NOT paraphrase. mean_per_marker
# uses floor-division of the CURRENT-TICK delta (W2). Only emitted when n>0;
# the zero-marker fallthrough has no S2 telemetry per D-18.
if read_ok and n > 0:
    mean_per_marker = delta_total // n if n > 0 else 0
    print(f"S2_INFO=window={n}, mean_per_marker={mean_per_marker}")
    if n == 2 and any(m.get('operation_type') == 'GUARDRAIL' for m in markers):
        print("S2_WARN=classification-dominated window, attribution may be lossy")

print(f"READ_OK={'true' if read_ok else 'false'}")
if read_err:
    print(f"READ_ERR={read_err}")
print(f"N_MARKERS={n}")
print(f"PRIOR_MUIDS_COUNT={len(prior_muids)}")
print(f"MARKERS_JSON={json.dumps(markers, separators=(',', ':'))}")
PY
    ) || marker_output=""

    if [[ -n "${marker_output}" ]]; then
      read_ok=$(echo "${marker_output}" | sed -n 's/^READ_OK=//p' | head -1)
      read_ok="${read_ok:-false}"
      n_markers=$(echo "${marker_output}" | sed -n 's/^N_MARKERS=//p' | head -1)
      n_markers="${n_markers:-0}"
      prior_muids_count=$(echo "${marker_output}" | sed -n 's/^PRIOR_MUIDS_COUNT=//p' | head -1)
      prior_muids_count="${prior_muids_count:-0}"
      s2_info_line=$(echo "${marker_output}" | sed -n 's/^S2_INFO=//p' | head -1)
      s2_warn_line=$(echo "${marker_output}" | sed -n 's/^S2_WARN=//p' | head -1)
      local read_err
      read_err=$(echo "${marker_output}" | sed -n 's/^READ_ERR=//p' | head -1)
      if [[ "${read_ok}" != "true" ]]; then
        warn "marker-read fall-through: session=${sid} reason=${read_err:-unknown}"
        n_markers=0
      fi
    else
      warn "marker-read fall-through: session=${sid} reason=empty-output"
      n_markers=0
    fi

    if [[ -n "${s2_info_line}" ]]; then
      info "S2: ${s2_info_line}"
    fi
    if [[ -n "${s2_warn_line}" ]]; then
      warn "S2: ${s2_warn_line}"
    fi

    # Phase 3 cutover (T05 / B3 / B4): if markers exist for this window, emit
    # per-marker Revenium calls with extended transaction-id and per-call v2
    # ledger writes. Else fall through to the legacy single-call path (T06
    # finalizes that branch with --task-type unclassified + synthetic muid).
    # The per-session idempotency pre-filter on line 71 already short-circuits
    # sessions whose (sid, total_tokens) already has any v2 row — the precise
    # per-muid dedupe happens INSIDE the T04 marker reader via parse_prior_state.
    if [[ "${n_markers}" -gt 0 ]]; then
      # === Per-marker emission (CRON-01..06) ===
      local markers_json
      markers_json=$(echo "${marker_output}" | sed -n 's/^MARKERS_JSON=//p' | head -1)
      local delta_fields_json
      delta_fields_json=$(
        DELTA_INPUT="${delta_input}" \
        DELTA_OUTPUT="${delta_output}" \
        DELTA_CACHE_READ="${delta_cache_read}" \
        DELTA_CACHE_WRITE="${delta_cache_write}" \
        DELTA_TOTAL="${delta_total}" \
        DELTA_COST="${delta_cost}" \
        python3 - <<'PY' 2>/dev/null || echo '{}'
import json, os
print(json.dumps({
    "input": int(os.environ.get('DELTA_INPUT', '0') or '0'),
    "output": int(os.environ.get('DELTA_OUTPUT', '0') or '0'),
    "cache_read": int(os.environ.get('DELTA_CACHE_READ', '0') or '0'),
    "cache_write": int(os.environ.get('DELTA_CACHE_WRITE', '0') or '0'),
    "total": int(os.environ.get('DELTA_TOTAL', '0') or '0'),
    "cost": os.environ.get('DELTA_COST', '0') or '0',
}, separators=(',', ':')))
PY
      )

      # B5: second heredoc — merge markers with equal_split outputs into one
      # pipe-delimited row per marker for bash consumption. Cost is serialized
      # as a STRING so Decimal precision round-trips across the bash boundary.
      local split_rows
      split_rows=$(
        MARKERS_JSON="${markers_json}" \
        DELTA_FIELDS_JSON="${delta_fields_json}" \
        N_MARKERS="${n_markers}" \
        SCRIPT_DIR="${SCRIPT_DIR}" \
        python3 - <<'PY' 2>&1
import json, os, sys
try:
    sys.path.insert(0, os.environ['SCRIPT_DIR'])
    from split_strategies import equal_split
    markers = json.loads(os.environ['MARKERS_JSON'])
    delta = json.loads(os.environ['DELTA_FIELDS_JSON'])
    n = int(os.environ['N_MARKERS'])
    splits = equal_split(delta, n)
    for marker, split in zip(markers, splits):
        m_agent = marker.get('agent', '')
        m_trace = marker.get('trace_id', '')
        # WR-01: sanitize pipe-delimiters and control chars so future upstream writers
        # cannot corrupt the bash while-read IFS='|' parsing (D-34).
        for _bad in ('|', '\n', '\r'):
            m_agent = m_agent.replace(_bad, '_')
            m_trace = m_trace.replace(_bad, '_')
        print(f"{marker['muid']}|{marker['task_type']}|{marker['operation_type']}|"
              f"{split['input']}|{split['output']}|{split['cache_read']}|"
              f"{split['cache_write']}|{split['total']}|{split['cost']}|{m_agent}|{m_trace}")
except Exception as exc:
    print(f"SPLIT_ERROR={exc}", file=sys.stderr)
    sys.exit(3)
PY
      ) || split_rows=""

      if [[ -z "${split_rows}" ]]; then
        warn "split-emit fall-through: session=${sid} reason=empty-split-rows"
        # If the split fails, do NOT silently re-emit as legacy — the markers
        # were valid (n_markers > 0) but the splitter or json round-trip
        # broke. Skip this session entirely; the next tick retries.
        ((skipped_count++)) || true
        continue
      fi

      local row muid t_type op_type d_in d_out d_cr d_cw d_tot d_cost m_agent m_trace
      while IFS='|' read -r muid t_type op_type d_in d_out d_cr d_cw d_tot d_cost m_agent m_trace; do
        [[ -z "${muid}" ]] && continue

        local cmd=(
          revenium meter completion
          --model "${clean_model}"
          --provider "${provider}"
          --input-tokens "${d_in}"
          --output-tokens "${d_out}"
          --cache-read-tokens "${d_cr}"
          --cache-creation-tokens "${d_cw}"
          --total-tokens "${d_tot}"
          --stop-reason "END"
          --request-time "${request_time}"
          --completion-start-time "${request_time}"
          --response-time "${response_time}"
          --request-duration "${duration_ms}"
          --agent "${m_agent:-Hermes}"
          --transaction-id "${sid}-${total_tokens}-${muid}"
          --trace-id "${m_trace:-${sid}}"
          --is-streamed
          --quiet
          --task-type "${t_type}"
          --operation-type "${op_type}"
        )

        if [[ -n "${billing_provider}" ]]; then
          cmd+=(--model-source "${billing_provider}")
        fi
        if [[ "${d_cost}" != "0" && "${d_cost}" != "0.000000" && "${d_cost}" != "0.0" ]]; then
          cmd+=(--total-cost "${d_cost}")
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
          # CRON-06 / D-07 / B1 / Pitfall 8: write the v2 ledger row IMMEDIATELY
          # after each successful call (ONE row per muid; NEVER batched). Field
          # 5 carries EXACTLY ONE muid — never a CSV.
          local now_ts
          now_ts=$(python3 -c "import time; print(f'{time.time():.3f}')" 2>/dev/null || date +%s)
          echo "HERMES:${sid}:${total_tokens}:${now_ts}:${muid}" >> "${LEDGER_FILE}"
          ((reported_count++)) || true
          info "Reported: session=${sid} muid=${muid} task_type=${t_type} op_type=${op_type} in=${d_in} out=${d_out}"
        else
          # Pitfall 8: on failure, do NOT append a ledger row. The next tick
          # re-reads the marker (still absent from prior_muids) and retries.
          warn "Failed: session=${sid} muid=${muid} exit=${cmd_exit} output=${cmd_output}"
          warn "Command: ${cmd[*]}"
        fi
      done <<< "${split_rows}"
    else
      # === Zero-marker fallthrough (CRON-07 / D-11 / D-14 / D-15 / B4) ===
      # No markers in this window. Reasons: older install with no agent classification,
      # missing/empty marker file, all marker lines unparseable, or this session's
      # marker file was unreadable (TAX-05 / MARK-04 tolerance — see T04 reader heredoc).
      # WIRE-01 / D-22: emit --operation-type CHAT — gate discharged in 04-RESEARCH.md (Revenium server-side default; cost parity verified across 50+ historical records).
      # B4: --transaction-id stays as ${sid}-${total_tokens} — the synthetic muid that
      # appears in the v2 ledger row's field 5 is a LEDGER-SIDE identifier only, NEVER
      # in the wire transaction-id. Extending --transaction-id here would break SC3.
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
        --task-type "unclassified"
        --operation-type "CHAT"
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
        # CRON-06 / D-07 / D-09 / D-11 / B1: write v2 ledger row with synthetic
        # placeholder muid. Field 5 holds EXACTLY one value (not a CSV) per B1
        # one-row-per-muid lock. The `unclassified-` prefix marks this row as
        # the zero-marker path so the field-count discrimination remains reliable
        # (v2 = 5 fields, never empty tail).
        local now_ts synthetic_muid
        now_ts=$(python3 -c "import time; print(f'{time.time():.3f}')" 2>/dev/null || date +%s)
        synthetic_muid="unclassified-${now_ts//./}"
        echo "HERMES:${sid}:${total_tokens}:${now_ts}:${synthetic_muid}" >> "${LEDGER_FILE}"
        ((reported_count++)) || true
        info "Reported: session=${sid} task_type=unclassified model=${clean_model} provider=${provider} in=${delta_input} out=${delta_output} cost=${delta_cost}"
      else
        warn "Failed: session=${sid} exit=${cmd_exit} output=${cmd_output}"
        warn "Command: ${cmd[*]}"
      fi
    fi
  done <<< "${sessions}"

  info "=== Done. Reported ${reported_count}, skipped ${skipped_count}. ==="
}

main "$@"
