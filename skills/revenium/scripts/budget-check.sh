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

read_config_field() {
  CONFIG_FILE="${CONFIG_FILE}" KEY="$1" python3 - <<'PY'
import json, os
val = json.load(open(os.environ['CONFIG_FILE'])).get(os.environ['KEY'], '')
if isinstance(val, bool):
    print('true' if val else 'false')
else:
    print(val if val is not None else '')
PY
}

ALERT_ID=$(read_config_field alertId)
if [[ -z "${ALERT_ID}" ]]; then
  echo "No alertId in config"
  exit 1
fi

BUDGET_JSON=$(revenium alerts budget get "${ALERT_ID}" --json 2>/dev/null)
if [[ -z "${BUDGET_JSON}" ]]; then
  echo "Failed to fetch budget"
  exit 1
fi

AUTONOMOUS=$(read_config_field autonomousMode)
NOTIFY_CHANNEL=$(read_config_field notifyChannel)
NOTIFY_TARGET=$(read_config_field notifyTarget)

# Update budget-status.json and decide if we just transitioned into halt.
HALT_OUTPUT=$(
  BUDGET_STATUS_FILE="${BUDGET_STATUS_FILE}" \
  BUDGET_JSON="${BUDGET_JSON}" \
  AUTONOMOUS="${AUTONOMOUS}" \
  python3 - <<'PY'
import json, os
from datetime import datetime, timezone
from pathlib import Path

status_file = Path(os.environ['BUDGET_STATUS_FILE'])
budget_json = os.environ['BUDGET_JSON']
autonomous = os.environ['AUTONOMOUS'] == 'true'

data = json.loads(budget_json)
data['lastChecked'] = datetime.now(timezone.utc).isoformat()
current = float(data.get('currentValue', 0))
threshold = float(data.get('threshold', 0))
exceeded = current > threshold if threshold > 0 else False
data['exceeded'] = exceeded
data.pop('note', None)

prev = {}
prev_halted = False
try:
    prev = json.loads(status_file.read_text())
    prev_halted = bool(prev.get('halted', False))
except Exception:
    pass

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

status_file.write_text(json.dumps(data, indent=2) + '\n')

percent = (current / threshold * 100) if threshold > 0 else 0
status = 'EXCEEDED' if exceeded else 'OK'
halted_tag = ' [HALTED]' if data.get('halted') else ''
print(f"HALT_TRANSITION={'true' if halt_transition else 'false'}")
print(f"CURRENT={current:.2f}")
print(f"THRESHOLD={threshold:.2f}")
print(f"PERCENT={percent:.0f}")
print(f"SUMMARY=Budget: ${current:.2f} / ${threshold:.2f} ({status}){halted_tag}")
PY
)

echo "${HALT_OUTPUT}" | sed -n 's/^SUMMARY=//p'

if echo "${HALT_OUTPUT}" | grep -q '^HALT_TRANSITION=true$'; then
  if [[ -n "${NOTIFY_CHANNEL}" && -n "${NOTIFY_TARGET}" ]]; then
    CURRENT_VALUE=$(echo "${HALT_OUTPUT}" | sed -n 's/^CURRENT=//p')
    THRESHOLD_VALUE=$(echo "${HALT_OUTPUT}" | sed -n 's/^THRESHOLD=//p')
    PERCENT=$(echo "${HALT_OUTPUT}" | sed -n 's/^PERCENT=//p')
    MSG="Budget halt active. Spent \$${CURRENT_VALUE} of \$${THRESHOLD_VALUE} (${PERCENT}%). All autonomous operations are now stopped. To resume: bash ~/.hermes/skills/revenium/scripts/clear-halt.sh"

    if command -v hermes >/dev/null 2>&1; then
      if hermes chat --toolsets messaging -q "Use the send_message tool to send this exact message to ${NOTIFY_CHANNEL}:${NOTIFY_TARGET}: ${MSG}" >/dev/null 2>&1; then
        echo "Halt notification sent via Hermes ${NOTIFY_CHANNEL}"
      else
        echo "Failed to send halt notification via Hermes ${NOTIFY_CHANNEL}"
      fi
    else
      echo "hermes CLI not available — halt notification not sent"
    fi
  else
    echo "Budget halted but no notification channel configured"
  fi
fi
