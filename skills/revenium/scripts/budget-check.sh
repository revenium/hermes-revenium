#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "No config.json found"
  exit 1
fi

ALERT_ID=$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}'))['alertId'])" 2>/dev/null)
if [[ -z "${ALERT_ID}" ]]; then
  echo "No alertId in config"
  exit 1
fi

BUDGET_JSON=$(revenium alerts budget get "${ALERT_ID}" --json 2>/dev/null)
if [[ -z "${BUDGET_JSON}" ]]; then
  echo "Failed to fetch budget"
  exit 1
fi

AUTONOMOUS=$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}')).get('autonomousMode', False))" 2>/dev/null || echo "False")
NOTIFY_CHANNEL=$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}')).get('notifyChannel', ''))" 2>/dev/null || true)
NOTIFY_TARGET=$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}')).get('notifyTarget', ''))" 2>/dev/null || true)

HALT_TRANSITION=$(python3 <<PYEOF
import json
from datetime import datetime, timezone
from pathlib import Path

data = json.loads('''${BUDGET_JSON}''')
data['lastChecked'] = datetime.now(timezone.utc).isoformat()
current = float(data.get('currentValue', 0))
threshold = float(data.get('threshold', 0))
exceeded = current > threshold if threshold > 0 else False
data['exceeded'] = exceeded
if 'note' in data:
    del data['note']

path = Path('${BUDGET_STATUS_FILE}')
prev_halted = False
prev = {}
try:
    prev = json.loads(path.read_text())
    prev_halted = prev.get('halted', False)
except Exception:
    prev = {}

autonomous = '${AUTONOMOUS}' == 'True'
halt_transition = False
if autonomous and exceeded and not prev_halted:
    data['halted'] = True
    data['haltedAt'] = datetime.now(timezone.utc).isoformat()
    halt_transition = True
elif prev_halted:
    data['halted'] = True
    data['haltedAt'] = prev.get('haltedAt', datetime.now(timezone.utc).isoformat())
else:
    data['halted'] = False

path.write_text(json.dumps(data, indent=2) + '
')
print(f"HALT_TRANSITION={'true' if halt_transition else 'false'}")
print(f"Budget: ${current:.2f} / ${threshold:.2f} ({'EXCEEDED' if exceeded else 'OK'}){' [HALTED]' if data.get('halted') else ''}")
PYEOF
)

echo "${HALT_TRANSITION}" | tail -1

if echo "${HALT_TRANSITION}" | head -1 | grep -q "HALT_TRANSITION=true"; then
  if [[ -n "${NOTIFY_CHANNEL}" && -n "${NOTIFY_TARGET}" ]]; then
    CURRENT_VALUE=$(python3 -c "import json; print(f"${json.load(open('${BUDGET_STATUS_FILE}')).get('currentValue', 0):.2f}")" 2>/dev/null || echo "?")
    THRESHOLD=$(python3 -c "import json; print(f"${json.load(open('${BUDGET_STATUS_FILE}')).get('threshold', 0):.2f}")" 2>/dev/null || echo "?")
    PERCENT=$(python3 -c "import json; d=json.load(open('${BUDGET_STATUS_FILE}')); print(f"{float(d.get('currentValue',0))/float(d.get('threshold',1))*100:.0f}")" 2>/dev/null || echo "?")
    MSG="Budget halt active. Spent \$${CURRENT_VALUE} of \$${THRESHOLD} (${PERCENT}%). All autonomous operations are now stopped. To resume: bash ~/.hermes/skills/revenium/scripts/clear-halt.sh"

    if command -v hermes >/dev/null 2>&1; then
      hermes chat --toolsets messaging -q "Use the send_message tool to send this exact message to ${NOTIFY_CHANNEL}:${NOTIFY_TARGET}: ${MSG}" >/dev/null 2>&1 &&         echo "Halt notification sent via Hermes ${NOTIFY_CHANNEL}" ||         echo "Failed to send halt notification via Hermes ${NOTIFY_CHANNEL}"
    else
      echo "hermes CLI not available — halt notification not sent"
    fi
  else
    echo "Budget halted but no notification channel configured"
  fi
fi
