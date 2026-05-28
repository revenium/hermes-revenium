#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

# No ensure_path — clear-halt.sh is a human-facing CLI; cron path extension
# is not needed here.

# Pass paths via env (bash 3.2 compatible — `${VAR@Q}` requires bash 4.4+;
# CLAUDE.md mandates bash 3.2 compat for macOS stock /bin/bash). Single-
# quoted heredoc keeps the Python source verbatim.

RULE_ID=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rule-id)
      RULE_ID="${2:-}"
      if [[ -z "${RULE_ID}" ]]; then
        echo "--rule-id requires an ID argument" >&2; exit 2
      fi
      shift 2
      ;;
    --help|-h) echo "Usage: clear-halt.sh [--rule-id <id>]"; exit 0 ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
done

if [[ ! -f "${GUARDRAIL_STATUS_FILE}" ]]; then
  echo "No guardrail-status.json found — nothing to clear."
  exit 0
fi

GUARDRAIL_STATUS_FILE_PY="${GUARDRAIL_STATUS_FILE}" RULE_ID_PY="${RULE_ID}" python3 - <<'PY'
import json, os, tempfile
from pathlib import Path

path = Path(os.environ['GUARDRAIL_STATUS_FILE_PY'])
rule_id = os.environ.get('RULE_ID_PY', '')

data = json.loads(path.read_text())
autonomous = bool(data.get('autonomousMode', False))
rules = data.get('rules', [])

if rule_id:
    target = next((r for r in rules if r.get('ruleId') == rule_id), None)
    if target is None or target.get('state') != 'block':
        print(f'Rule {rule_id} is not in block state — no change.')
        raise SystemExit(0)
    target['state'] = 'ok'
    print(f'Cleared block state for rule {rule_id} ({target.get("name", "?")}).')
else:
    cleared = [r for r in rules if r.get('state') == 'block']
    if not cleared:
        print('No halt is currently active.')
        raise SystemExit(0)
    for r in cleared:
        r['state'] = 'ok'
    print(f'Cleared {len(cleared)} blocked rule(s). The agent may now resume operations.')

# Recompute top-level halted
any_blocked = any(r.get('state') == 'block' for r in rules)
new_halted = autonomous and any_blocked
data['halted'] = new_halted
data['rules'] = rules
if not new_halted:
    data.pop('haltedAt', None)
    data.pop('haltedRule', None)
else:
    blocked = [r for r in rules if r.get('state') == 'block']
    if blocked:
        first = blocked[0]
        data['haltedRule'] = {
            'ruleId': first['ruleId'],
            'name': first['name'],
            'metricType': first['metricType'],
            'windowType': first['windowType'],
            'currentValue': first['currentValue'],
            'hardLimit': first['hardLimit'],
        }

# Atomic write (RESEARCH.md Section 3): mkstemp same-dir + os.replace
tmp_fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix='.clear-halt-', suffix='.tmp')
try:
    import os as _os
    with _os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
        f.write(json.dumps(data, indent=2) + '\n')
    _os.replace(tmp_path, str(path))
finally:
    try:
        _os.unlink(tmp_path)
    except FileNotFoundError:
        pass
PY
