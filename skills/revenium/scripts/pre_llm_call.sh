#!/usr/bin/env bash
set -euo pipefail
# pre_llm_call.sh — inject budget halt directive into every Hermes turn.
# Reads stdin (JSON payload from Hermes hook dispatcher), checks budget-status.json,
# emits {"context":"..."} when halted:true, {} otherwise (fail-open).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

# MUST be the first executable statement after ensure_path — Hermes pipes the JSON
# payload and waits for stdin to be consumed before reading stdout. An early exit
# without reading stdin hangs the hook (RESEARCH.md Pitfall 1).
# The pre_llm_call hook does not parse the payload — drain and discard it.
cat - >/dev/null

# Read budget status — fail open to false if missing or corrupt (V5 Input Validation).
halted="$(BUDGET_STATUS_FILE="${BUDGET_STATUS_FILE}" python3 -c "
import json, os
try:
    d = json.load(open(os.environ['BUDGET_STATUS_FILE']))
    print('true' if d.get('halted') else 'false')
except Exception:
    print('false')
" 2>/dev/null || echo 'false')"

# Fast path: not halted — emit no-op and exit cleanly.
if [[ "${halted}" != "true" ]]; then
  printf '{}\n'
  exit 0
fi

# Extract values for halt string substitution — each with a '?' fallback.
current_value="$(BUDGET_STATUS_FILE="${BUDGET_STATUS_FILE}" python3 -c "
import json, os
d = json.load(open(os.environ['BUDGET_STATUS_FILE']))
print(d.get('currentValue', '?'))
" 2>/dev/null || echo '?')"

threshold="$(BUDGET_STATUS_FILE="${BUDGET_STATUS_FILE}" python3 -c "
import json, os
d = json.load(open(os.environ['BUDGET_STATUS_FILE']))
print(d.get('threshold', '?'))
" 2>/dev/null || echo '?')"

percent_used="$(BUDGET_STATUS_FILE="${BUDGET_STATUS_FILE}" python3 -c "
import json, os
d = json.load(open(os.environ['BUDGET_STATUS_FILE']))
print(d.get('percentUsed', '?'))
" 2>/dev/null || echo '?')"

# Emit halt context injection via json.dumps (handles quoting/escaping safely).
# The context string instructs the agent to emit the verbatim halt string and nothing else.
# The verbatim halt string must be byte-identical to SKILL.md line 35.
CURRENT_VALUE="${current_value}" THRESHOLD="${threshold}" PERCENT_USED="${percent_used}" python3 -c "
import json, os
current_value = os.environ['CURRENT_VALUE']
threshold = os.environ['THRESHOLD']
percent_used = os.environ['PERCENT_USED']
halt_str = (
    'Budget enforcement halt is active. '
    + current_value + ' of ' + threshold + ' used ('
    + percent_used + '%). To resume: \`bash ~/.hermes/skills/revenium/scripts/clear-halt.sh\`'
)
directive = (
    'BUDGET HALT ACTIVE. Your response for this turn MUST be EXACTLY the following '
    'message and nothing else:\n' + halt_str
)
print(json.dumps({'context': directive}))
"
