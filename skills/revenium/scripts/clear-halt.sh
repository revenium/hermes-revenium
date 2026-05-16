#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

if [[ ! -f "${BUDGET_STATUS_FILE}" ]]; then
  echo "No budget-status.json found — nothing to clear."
  exit 0
fi

# Pass paths via env (bash 3.2 compatible — `${VAR@Q}` requires bash 4.4+;
# CLAUDE.md mandates bash 3.2 compat for macOS stock /bin/bash). Single-
# quoted heredoc keeps the Python source verbatim.
BUDGET_STATUS_FILE_PY="${BUDGET_STATUS_FILE}" python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ['BUDGET_STATUS_FILE_PY'])
data = json.loads(path.read_text())
if not data.get('halted', False):
    print('No halt is currently active.')
else:
    data['halted'] = False
    data.pop('haltedAt', None)
    path.write_text(json.dumps(data, indent=2) + "\n")
    print('Budget halt cleared. The agent may now resume operations.')
PY
