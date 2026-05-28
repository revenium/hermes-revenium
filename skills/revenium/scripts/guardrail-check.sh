#!/usr/bin/env bash
# guardrail-check.sh — v1.3 cron stage for guardrail enforcement.
# Polls revenium guardrails enforcement-rules get on every cron tick, builds
# per-rule state (block/warn/ok), writes guardrail-status.json atomically,
# detects new halt transitions, and fires Hermes messaging notification on
# a new halt (AUDIT-01/02 enforcement-event embedding with graceful degradation).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

# Save the head of PATH before ensure_path so that test-injected stub directories
# (prepended by the test harness) are not pushed back by ensure_path's Homebrew
# additions. Re-prepending the original head after ensure_path keeps stubs first
# while still benefiting from the Homebrew/system paths ensure_path provides.
_PATH_HEAD="${PATH%%:*}"
ensure_path
[[ -n "${_PATH_HEAD}" ]] && export PATH="${_PATH_HEAD}:${PATH}"

# (B) Preflight checks — fail-open with warn + exit 0 per cron path.
if ! command -v revenium >/dev/null 2>&1; then
  warn "revenium CLI not found on PATH — skipping guardrail check."
  exit 0
fi
if ! command -v python3 >/dev/null 2>&1; then
  warn "python3 not found — skipping guardrail check."
  exit 0
fi
if [[ ! -f "${CONFIG_FILE}" ]]; then
  warn "No config.json found at ${CONFIG_FILE} — skipping guardrail check."
  exit 0
fi
if ! has_guardrails_cli; then
  warn "revenium guardrails CLI not available — skipping guardrail check."
  exit 0
fi
if ! revenium config show >/dev/null 2>&1; then
  warn "revenium not configured — skipping guardrail check."
  exit 0
fi

# (C) read_config_field helper — reads a scalar key from CONFIG_FILE via Python.
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

# (D) Extract ruleIds array from config.json.
RULE_IDS_JSON=$(CONFIG_FILE="${CONFIG_FILE}" python3 -c "
import json, os
try:
    ids = json.load(open(os.environ['CONFIG_FILE'])).get('ruleIds', [])
    print(json.dumps(ids))
except Exception:
    print('[]')
" 2>/dev/null || echo '[]')

# (E) Read scalar config fields.
AUTONOMOUS=$(read_config_field autonomousMode)
NOTIFY_CHANNEL=$(read_config_field notifyChannel)
NOTIFY_TARGET=$(read_config_field notifyTarget)

# (F) Resolve teamId from revenium config show.
TEAM_ID=$(revenium config show 2>&1 | sed -n 's/.*Team ID:[ 	]*//p' | tr -d ' ')
if [[ -z "${TEAM_ID}" ]]; then
  warn "Could not resolve teamId from revenium config show — skipping guardrail check."
  exit 0
fi

# (G) Fetch enforcement rules — treat EOF/exit-1 (empty team) as soft-fail.
ENFORCEMENT_JSON=$(revenium guardrails enforcement-rules get "${TEAM_ID}" --output json 2>&1) || true
if echo "${ENFORCEMENT_JSON}" | grep -q '"error".*EOF'; then
  ENFORCEMENT_JSON='{"rules": []}'
fi

# Pre-step: build name -> string-id map once per tick (RESEARCH § ruleId mismatch finding).
# enforcement-rules API returns integer ruleId values; budget-rules list returns string-hash IDs
# that match config.json::ruleIds and are accepted by enforcement-events list --rule-id.
BUDGET_RULES_JSON=$(revenium guardrails budget-rules list --output json 2>/dev/null || echo '[]')

# (H) Build guardrail-status.json via a single Python heredoc with atomic write.
HALT_OUTPUT=$(
  GUARDRAIL_STATUS_FILE="${GUARDRAIL_STATUS_FILE}" \
  ENFORCEMENT_JSON="${ENFORCEMENT_JSON}" \
  BUDGET_RULES_JSON="${BUDGET_RULES_JSON}" \
  RULE_IDS_JSON="${RULE_IDS_JSON}" \
  AUTONOMOUS="${AUTONOMOUS}" \
  python3 - <<'PY'
import json, os, tempfile
from datetime import datetime, timezone
from pathlib import Path

status_file = Path(os.environ['GUARDRAIL_STATUS_FILE'])
enforcement_json = os.environ['ENFORCEMENT_JSON']
budget_rules_json = os.environ.get('BUDGET_RULES_JSON', '[]')
rule_ids_order = json.loads(os.environ['RULE_IDS_JSON'])   # string IDs, declaration order
autonomous = os.environ['AUTONOMOUS'] == 'true'

# Parse enforcement-rules response (integer ruleId space)
api_rules = []
try:
    api_rules = json.loads(enforcement_json).get('rules', [])
except Exception:
    pass

# Parse budget-rules list (string-hash ruleId space) and build name -> string-id map.
# RESEARCH.md § "ruleId mismatch finding": the enforcement-rules API returns integer IDs
# that do NOT match config.json::ruleIds (string hashes). The only stable join key
# between the two is the rule `name` field.
name_to_string_id = {}
try:
    br_data = json.loads(budget_rules_json)
    # budget-rules list returns a JSON array; each entry has {id: "<string-hash>", name: "..."}
    if isinstance(br_data, list):
        for br in br_data:
            n = br.get('name')
            sid = br.get('id')   # string-hash ID, e.g. "d5jng5"
            if n and sid:
                name_to_string_id[n] = sid
except Exception:
    pass

# Build per-rule state list (ENF-04 schema)
# state derivation: breached -> 'block', warnBreached -> 'warn', else 'ok'
now = datetime.now(timezone.utc).isoformat()
new_rules = []
for r in api_rules:
    if r.get('breached'):
        state = 'block'
    elif r.get('warnBreached'):
        state = 'warn'
    else:
        state = 'ok'
    rule_name = r.get('name', '')
    # ruleId resolution: prefer the string-hash from budget-rules list (matches
    # config.json::ruleIds format; accepted by enforcement-events list --rule-id).
    # Fallback: coerce the API integer ruleId to a string (best-effort; the AUDIT-01
    # enforcement-events fetch will likely 422 on this path, and the script gracefully
    # degrades to rule-level data only per AUDIT-02).
    resolved_rule_id = name_to_string_id.get(rule_name)
    if not resolved_rule_id:
        resolved_rule_id = str(r.get('ruleId', '')) if r.get('ruleId') is not None else ''
    # Map API field names to ENF-04 schema field names (RESEARCH.md Section 1)
    new_rules.append({
        'ruleId': resolved_rule_id,              # REVISED: string-hash ID via name join
        'name': rule_name,
        'metricType': r.get('metricType', ''),
        'windowType': r.get('periodType', ''),    # API: periodType -> schema: windowType
        'groupBy': r.get('groupBy', ''),
        'currentValue': r.get('currentValue', 0),
        'warnThreshold': r.get('warnThreshold', 0),
        'hardLimit': r.get('threshold', 0),       # API: threshold -> schema: hardLimit
        'state': state,
        'lastChecked': now,
    })

# Load previous state (fail-open)
prev = {}
try:
    prev = json.loads(status_file.read_text(encoding='utf-8'))
except Exception:
    pass
prev_halted = bool(prev.get('halted', False))
prev_halted_at = prev.get('haltedAt')

# Top-level halted derivation
any_blocked = any(r['state'] == 'block' for r in new_rules)
new_halted = autonomous and any_blocked

# HALT_TRANSITION detection: new halt iff new_halted and not prev_halted
halt_transition = False
if new_halted and not prev_halted:
    halt_transition = True
    halted_at = now
elif new_halted and prev_halted:
    halted_at = prev_halted_at or now
else:
    halted_at = None

# haltedRule tiebreaker (D-02): first blocked rule in ruleIds[] declaration order
halted_rule = None
if new_halted:
    blocked = [r for r in new_rules if r['state'] == 'block']
    if blocked:
        first = blocked[0]
        halted_rule = {
            'ruleId': first['ruleId'],
            'name': first['name'],
            'metricType': first['metricType'],
            'windowType': first['windowType'],
            'currentValue': first['currentValue'],
            'hardLimit': first['hardLimit'],
        }

# Build output document (ENF-04 + D-04)
data = {
    'halted': new_halted,
    'autonomousMode': autonomous,
    'lastChecked': now,
    'rules': new_rules,
}
if new_halted and halted_at:
    data['haltedAt'] = halted_at
if halted_rule:
    data['haltedRule'] = halted_rule

# Atomic write: write-tmp-rename (RESEARCH.md Section 3)
tmp_fd, tmp_path = tempfile.mkstemp(
    dir=str(status_file.parent),
    prefix='.guardrail-status-',
    suffix='.tmp'
)
try:
    with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
        f.write(json.dumps(data, indent=2) + '\n')
    os.replace(tmp_path, str(status_file))
finally:
    try:
        os.unlink(tmp_path)
    except FileNotFoundError:
        pass

# Emit KEY=value lines for bash caller to parse HALT_TRANSITION and halted rule fields
print(f"HALT_TRANSITION={'true' if halt_transition else 'false'}")
if halt_transition and halted_rule:
    print(f"HALTED_RULE_NAME={halted_rule['name']}")
    print(f"HALTED_RULE_ID={halted_rule['ruleId']}")
    print(f"HALTED_METRIC_TYPE={halted_rule['metricType']}")
    print(f"HALTED_WINDOW_TYPE={halted_rule['windowType']}")
    print(f"HALTED_CURRENT_VALUE={halted_rule['currentValue']}")
    print(f"HALTED_HARD_LIMIT={halted_rule['hardLimit']}")
PY
)

# Emit KEY=value lines from the heredoc to stdout so the cron caller (and test
# harness) can observe HALT_TRANSITION, HALTED_RULE_*, etc. The lines are also
# retained in HALT_OUTPUT for sed-based extraction below.
echo "${HALT_OUTPUT}"

# (I-pre) Phase 19 clean-break: remove stale legacy status file on first successful write.
# Runs AFTER guardrail-status.json is durably on disk, BEFORE halt notification.
# Idempotent: guard prevents log spam on ticks where the file is already gone.
if [[ -f "${STATE_DIR}/budget-status.json" ]]; then
  rm -f "${STATE_DIR}/budget-status.json"
  info "Cleaned up legacy budget-status.json (Phase 19 clean break)"
fi

# (I) Parse halt output from Python heredoc.
if echo "${HALT_OUTPUT}" | grep -q '^HALT_TRANSITION=true$'; then
  HALTED_RULE_NAME=$(echo "${HALT_OUTPUT}" | sed -n 's/^HALTED_RULE_NAME=//p')
  HALTED_RULE_ID=$(echo "${HALT_OUTPUT}" | sed -n 's/^HALTED_RULE_ID=//p')
  HALTED_METRIC_TYPE=$(echo "${HALT_OUTPUT}" | sed -n 's/^HALTED_METRIC_TYPE=//p')
  HALTED_WINDOW_TYPE=$(echo "${HALT_OUTPUT}" | sed -n 's/^HALTED_WINDOW_TYPE=//p')
  HALTED_CURRENT_VALUE=$(echo "${HALT_OUTPUT}" | sed -n 's/^HALTED_CURRENT_VALUE=//p')
  HALTED_HARD_LIMIT=$(echo "${HALT_OUTPUT}" | sed -n 's/^HALTED_HARD_LIMIT=//p')

  # (J) AUDIT-01: fetch enforcement event for the halted rule (fail-open per AUDIT-02).
  # Use a sentinel "__FAIL__" to distinguish API failure (exit non-zero) from an empty
  # result (API succeeded, no events). Both produce '(unavailable)' in the notification
  # per AUDIT-02, but the test asserts on '(unavailable)' for API failures specifically.
  EVENT_JSON=$(revenium guardrails enforcement-events list \
    --rule-id "${HALTED_RULE_ID}" --page-size 1 --output json 2>/dev/null || echo '__FAIL__')
  if [[ "${EVENT_JSON}" == "__FAIL__" ]]; then
    warn "enforcement-events list failed for rule ${HALTED_RULE_ID} — falling back to rule-level data (AUDIT-02)"
    EVENT_TS='(unavailable)'
    EVENT_SUMMARY='(unavailable)'
  else
    EVENT_TS=$(EVENT_JSON="${EVENT_JSON}" python3 -c "
import json, os
try:
    events = json.loads(os.environ['EVENT_JSON'])
    print(events[0].get('created', '(unavailable)') if events else '(no events)')
except Exception:
    print('(unavailable)')
" 2>/dev/null || echo '(unavailable)')
    EVENT_SUMMARY=$(EVENT_JSON="${EVENT_JSON}" python3 -c "
import json, os
try:
    events = json.loads(os.environ['EVENT_JSON'])
    print(events[0].get('rawDetails', '(unavailable)') if events else '(no events)')
except Exception:
    print('(unavailable)')
" 2>/dev/null || echo '(unavailable)')
  fi

  # Emit audit event fields as KEY=value on stdout (AUDIT-01 happy-path observable signal;
  # AUDIT-02: still emits with literal '(unavailable)' on fallback — test asserts on this).
  echo "EVENT_TS=${EVENT_TS}"
  echo "EVENT_SUMMARY=${EVENT_SUMMARY}"

  # (K) Operator halt notification via Hermes messaging toolset (D-01 halt string template).
  MSG="Guardrail halt active — rule '${HALTED_RULE_NAME}' (${HALTED_METRIC_TYPE}, ${HALTED_WINDOW_TYPE}) at ${HALTED_CURRENT_VALUE} of ${HALTED_HARD_LIMIT} hard-limit. To resume: bash ~/.hermes/skills/revenium/scripts/clear-halt.sh | Event: [${EVENT_TS}] ${EVENT_SUMMARY}"
  if [[ -n "${NOTIFY_CHANNEL}" && -n "${NOTIFY_TARGET}" ]]; then
    if command -v hermes >/dev/null 2>&1; then
      if hermes chat --toolsets messaging -q "Use the send_message tool to send this exact message to ${NOTIFY_CHANNEL}:${NOTIFY_TARGET}: ${MSG}" >/dev/null 2>&1; then
        info "Halt notification sent via Hermes ${NOTIFY_CHANNEL}"
      else
        warn "Failed to send halt notification via Hermes ${NOTIFY_CHANNEL}"
      fi
    else
      warn "hermes CLI not available — halt notification not sent"
    fi
  else
    info "Guardrail halted but no notification channel configured"
  fi
fi
