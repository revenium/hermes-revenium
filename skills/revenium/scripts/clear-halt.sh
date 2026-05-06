#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

if [[ ! -f "${BUDGET_STATUS_FILE}" ]]; then
  echo "No budget-status.json found — nothing to clear."
  exit 0
fi

python3 - <<PY
import json
from pathlib import Path

path = Path(${BUDGET_STATUS_FILE@Q})
data = json.loads(path.read_text())
if not data.get('halted', False):
    print('No halt is currently active.')
else:
    data['halted'] = False
    data.pop('haltedAt', None)
    path.write_text(json.dumps(data, indent=2) + '
')
    print('Budget halt cleared. The agent may now resume operations.')
PY
