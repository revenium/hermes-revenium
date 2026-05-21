#!/usr/bin/env bash
set -euo pipefail
# pre_llm_call.sh — inject guardrail halt directive into every Hermes turn.
# Reads stdin (JSON payload from Hermes hook dispatcher), checks guardrail-status.json,
# emits {"context":"..."} when halted:true (HOOK-01, D-01), emits one rate-limited
# stderr warn line per (session, ruleId) when any rule is in warn state (HOOK-02, D-05..D-07),
# emits {} otherwise. Fail-open on missing or corrupt status file (HOOK-04).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

# MUST be the first executable statement after ensure_path — Hermes pipes the JSON
# payload and waits for stdin to be consumed before reading stdout. An early exit
# without reading stdin hangs the hook (RESEARCH.md Pitfall 1).
# The pre_llm_call hook does not parse the payload — drain and discard it.
# WARNING: Do NOT move this line. Moving it will cause the hook to hang in production
# because Hermes blocks on stdin before reading stdout (Pitfall 1 mitigation).
cat - >/dev/null

# Read guardrail status — multi-value extraction (halted + haltedRule in one call).
# Fail-open: any exception prints HALTED=false (HOOK-04).
HALTED_AND_RULE=$(GUARDRAIL_STATUS_FILE="${GUARDRAIL_STATUS_FILE}" python3 -c "
import json, os
try:
    d = json.load(open(os.environ['GUARDRAIL_STATUS_FILE']))
    halted = d.get('halted', False)
    if halted:
        hr = d.get('haltedRule', {})
        print('HALTED=true')
        print('RULE_NAME=' + str(hr.get('name', '?')))
        print('METRIC_TYPE=' + str(hr.get('metricType', '?')))
        print('WINDOW_TYPE=' + str(hr.get('windowType', '?')))
        print('CURRENT_VALUE=' + str(hr.get('currentValue', '?')))
        print('HARD_LIMIT=' + str(hr.get('hardLimit', '?')))
    else:
        print('HALTED=false')
except Exception:
    print('HALTED=false')
" 2>/dev/null || echo 'HALTED=false')

halted="$(echo "${HALTED_AND_RULE}" | sed -n 's/^HALTED=//p')"

# Fast path: not halted — run warn-band check then emit no-op.
if [[ "${halted}" != "true" ]]; then
  # Warn-band: emit one stderr line per (session, ruleId) for rules in 'warn' state.
  # D-05: stderr only — NOT routed through common.sh::warn (which writes to LOG_FILE).
  # Pitfall 3: do NOT call warn() here — that writes to the cron log.
  WARN_INFO=$(GUARDRAIL_STATUS_FILE="${GUARDRAIL_STATUS_FILE}" python3 -c "
import json, os
try:
    d = json.load(open(os.environ['GUARDRAIL_STATUS_FILE']))
    for r in d.get('rules', []):
        if r.get('state') == 'warn':
            print('WARN_RULE=' + str(r['ruleId']) + ':' + str(r.get('name', '?')) + ':' + str(r.get('metricType', '?')) + ':' + str(r.get('windowType', '?')) + ':' + str(r.get('currentValue', '?')) + ':' + str(r.get('hardLimit', '?')))
except Exception:
    pass
" 2>/dev/null || true)

  if [[ -n "${WARN_INFO}" ]]; then
    # Resolve session_id for rate-limit sentinel (mirrors pre_tool_call.sh:51-64 pattern).
    # Pitfall 4: session_id is often empty in the hook payload; scan newest non-cron session file.
    SESSION_ID=$(HERMES_HOME="${HERMES_HOME}" python3 -c "
import os, time
sessions_dir = os.path.join(os.environ.get('HERMES_HOME', os.path.expanduser('~/.hermes')), 'sessions')
try:
    candidates = [f for f in os.listdir(sessions_dir)
                  if f.startswith('session_') and f.endswith('.json')
                  and not f.startswith('session_cron_')]
    if candidates:
        newest = max(candidates, key=lambda f: os.path.getmtime(os.path.join(sessions_dir, f)))
        sid = newest[len('session_'):-len('.json')]
        # T-19-07-05: reject session_id with path separators
        if '/' not in sid and '..' not in sid:
            print(sid)
        else:
            print('unknown-' + str(int(time.time())))
    else:
        print('unknown-' + str(int(time.time())))
except Exception:
    print('unknown-' + str(int(time.time())))
" 2>/dev/null || echo "unknown-$$")

    while IFS= read -r warn_line; do
      [[ -z "${warn_line}" ]] && continue
      # Extract ruleId from WARN_RULE=<ruleId>:<name>:... format.
      # f1 = WARN_RULE=<ruleId>, so strip the WARN_RULE= prefix for ruleId.
      rule_id="$(echo "${warn_line}" | cut -d: -f1 | sed 's/^WARN_RULE=//')"
      rule_name="$(echo "${warn_line}" | cut -d: -f2)"
      metric_type="$(echo "${warn_line}" | cut -d: -f3)"
      window_type="$(echo "${warn_line}" | cut -d: -f4)"
      current_value="$(echo "${warn_line}" | cut -d: -f5)"
      hard_limit="$(echo "${warn_line}" | cut -d: -f6)"

      # T-19-07-04: validate ruleId character set before constructing flag path.
      # Only allow [A-Za-z0-9_-]; skip and log a warn if malformed.
      if ! echo "${rule_id}" | grep -Eq '^[A-Za-z0-9_-]+$'; then
        warn "pre_llm_call: malformed ruleId '${rule_id}' — skipping warn emit (T-19-07-04)"
        continue
      fi

      warn_flag="${WARN_FLAGS_DIR}/${SESSION_ID}__${rule_id}.flag"
      if [[ ! -f "${warn_flag}" ]]; then
        mkdir -p "${WARN_FLAGS_DIR}"
        touch "${warn_flag}"
        # D-05: stderr ONLY — do NOT route through common.sh::warn (Pitfall 3)
        echo "Guardrail warn: rule '${rule_name}' (${metric_type}, ${window_type}): ${current_value} of ${hard_limit} hard-limit." >&2
      fi
    done < <(echo "${WARN_INFO}" | grep '^WARN_RULE=')
  fi

  printf '{}\n'
  exit 0
fi

# Halted: extract the 5 haltedRule fields from HALTED_AND_RULE.
RULE_NAME="$(echo "${HALTED_AND_RULE}" | sed -n 's/^RULE_NAME=//p')"
METRIC_TYPE="$(echo "${HALTED_AND_RULE}" | sed -n 's/^METRIC_TYPE=//p')"
WINDOW_TYPE="$(echo "${HALTED_AND_RULE}" | sed -n 's/^WINDOW_TYPE=//p')"
CURRENT_VALUE="$(echo "${HALTED_AND_RULE}" | sed -n 's/^CURRENT_VALUE=//p')"
HARD_LIMIT="$(echo "${HALTED_AND_RULE}" | sed -n 's/^HARD_LIMIT=//p')"

# Emit halt context injection via json.dumps (handles quoting/escaping safely).
# The context string instructs the agent to emit the D-01 verbatim halt string and nothing else.
# Pass field values via env vars for bash 3.2 compatibility (no ${VAR@Q}).
RULE_NAME="${RULE_NAME}" METRIC_TYPE="${METRIC_TYPE}" WINDOW_TYPE="${WINDOW_TYPE}" \
CURRENT_VALUE="${CURRENT_VALUE}" HARD_LIMIT="${HARD_LIMIT}" python3 -c "
import json, os
rule_name = os.environ['RULE_NAME']
metric_type = os.environ['METRIC_TYPE']
window_type = os.environ['WINDOW_TYPE']
current_value = os.environ['CURRENT_VALUE']
hard_limit = os.environ['HARD_LIMIT']
halt_str = (
    \"Guardrail halt active — rule '\" + rule_name + \"' (\" + metric_type + ', '
    + window_type + ') at ' + current_value + ' of ' + hard_limit
    + ' hard-limit. To resume: \`bash ~/.hermes/skills/revenium/scripts/clear-halt.sh\`'
)
directive = (
    'GUARDRAIL HALT ACTIVE. Your response for this turn MUST be EXACTLY the following '
    'message and nothing else:\n' + halt_str
)
print(json.dumps({'context': directive}))
"
