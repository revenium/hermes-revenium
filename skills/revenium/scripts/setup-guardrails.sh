#!/usr/bin/env bash
set -euo pipefail
# setup-guardrails.sh — single rule-creation entry point for the v1.3 guardrails-native
# budget enforcement. Three modes per D-02:
#   default  : --hard-limit N --period P [...] from CLI args; idempotent create.
#   --interactive : operator prompts; called by SKILL.md Setup Flow (plan 18-04).
#   --from-alert <id> --auto : cron migration; called by cron.sh first stage (plan 18-03).
# Idempotent via ruleIds-presence pre-check (D-07); flock-guarded via RULES_LOCK_FILE (D-07);
# --shadow-mode propagates to every create call (D-04).
# Bash 3.2 compatible (Mac Studio gate) — uses env-passing heredoc pattern (no bash 4.4+ operators).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
  cat <<'USAGE'
setup-guardrails.sh — create Revenium guardrails budget rules

MODES:
  Default mode (all args from CLI flags):
    setup-guardrails.sh --hard-limit 100 --period MONTHLY [--shadow-mode]

  Interactive mode (operator prompts; used by SKILL.md Setup Flow):
    setup-guardrails.sh --interactive [--shadow-mode]

  Migration mode (cron auto-migration from legacy alertId):
    setup-guardrails.sh --from-alert <alertId> --auto [--shadow-mode]

OPTIONS:
  --hard-limit <N>       Budget hard limit (numeric, e.g. 50.00). Required in default mode.
  --period <P>           Budget period: DAILY | WEEKLY | MONTHLY | QUARTERLY. Required in default mode.
  --shadow-mode          All created rules run in shadow mode (observe only, do not block).
  --interactive          Collect all args from operator prompts.
  --from-alert <id>      Source the limit and period from a legacy alertId.
  --auto                 Suppress interactive prompts (required with --from-alert).
  --help                 Show this usage block and exit.

EXAMPLES:
  # Fresh install — default mode:
  setup-guardrails.sh --hard-limit 100 --period MONTHLY

  # Fresh install — interactive mode:
  setup-guardrails.sh --interactive

  # Auto-migration from legacy alertId (called by cron.sh):
  setup-guardrails.sh --from-alert abc123 --auto
USAGE
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
MODE="default"
AUTO="false"
FROM_ALERT=""
HARD_LIMIT=""
PERIOD=""
SHADOW_MODE="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interactive)
      MODE="interactive"
      shift
      ;;
    --from-alert)
      MODE="from-alert"
      FROM_ALERT="${2:-}"
      if [[ -z "${FROM_ALERT}" ]]; then
        error "--from-alert requires an alertId argument"; exit 2
      fi
      shift 2
      ;;
    --auto)
      AUTO="true"
      shift
      ;;
    --hard-limit)
      HARD_LIMIT="${2:-}"
      if [[ -z "${HARD_LIMIT}" ]]; then
        error "--hard-limit requires a value"; exit 2
      fi
      shift 2
      ;;
    --period)
      PERIOD="${2:-}"
      if [[ -z "${PERIOD}" ]]; then
        error "--period requires a value"; exit 2
      fi
      shift 2
      ;;
    --shadow-mode)
      SHADOW_MODE="true"
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      error "unknown flag: $1"
      exit 2
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Mode resolution rules
# ---------------------------------------------------------------------------
if [[ "${MODE}" == "interactive" && "${AUTO}" == "true" ]]; then
  error "--interactive and --auto are mutually exclusive"
  exit 2
fi

if [[ "${MODE}" == "from-alert" && "${AUTO}" != "true" ]]; then
  error "--from-alert requires --auto"
  exit 2
fi

if [[ "${MODE}" == "default" ]]; then
  if [[ -z "${HARD_LIMIT}" || -z "${PERIOD}" ]]; then
    error "default mode requires --hard-limit and --period"
    exit 2
  fi
fi

# ---------------------------------------------------------------------------
# Capability precheck (fail-open — mirrors hermes-report.sh:13-32)
# ---------------------------------------------------------------------------
if ! has_guardrails_cli; then
  if [[ "${AUTO}" == "true" ]]; then
    warn "revenium guardrails subcommands not available — skipping setup-guardrails."
    exit 0
  else
    echo "The revenium CLI does not support guardrails budget-rules commands."
    echo "Upgrade with: brew upgrade revenium/tap/revenium"
    exit 0
  fi
fi

# ---------------------------------------------------------------------------
# Helpers: read_config_field (verbatim from budget-check.sh, with list branch)
# ---------------------------------------------------------------------------
read_config_field() {
  CONFIG_FILE="${CONFIG_FILE}" KEY="$1" python3 - <<'PY'
import json, os
val = json.load(open(os.environ['CONFIG_FILE'])).get(os.environ['KEY'], '')
if isinstance(val, list):
    print('nonempty' if val else '')
elif isinstance(val, bool):
    print('true' if val else 'false')
else:
    print(val if val is not None else '')
PY
}

# ---------------------------------------------------------------------------
# Helpers: input validation
# ---------------------------------------------------------------------------
validate_hard_limit() {
  [[ "$1" =~ ^[0-9]+(\.[0-9]+)?$ ]]
}

validate_period() {
  case "$1" in DAILY|WEEKLY|MONTHLY|QUARTERLY) return 0 ;; *) return 1 ;; esac
}

# ---------------------------------------------------------------------------
# Config.json existence check (mode-agnostic)
# ---------------------------------------------------------------------------
if [[ ! -f "${CONFIG_FILE}" ]]; then
  if [[ "${AUTO}" == "true" ]]; then
    warn "no config.json — skipping migration; run /revenium setup"
    exit 0
  else
    error "config.json not found at ${CONFIG_FILE}"
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Three-state pre-check (D-07 idempotency + Pitfall 6)
# ---------------------------------------------------------------------------
RULE_IDS=$(read_config_field ruleIds)
EXISTING_ALERT_ID=$(read_config_field alertId)

if [[ "${MODE}" == "from-alert" && "${AUTO}" == "true" ]]; then
  if [[ "${RULE_IDS}" == "nonempty" ]]; then
    # ruleIds already populated — this is the post-migration no-op path
    exit 0
  fi
  if [[ -z "${EXISTING_ALERT_ID}" ]]; then
    warn "no alertId and no ruleIds — run /revenium setup"
    exit 0
  fi
elif [[ "${MODE}" == "default" ]]; then
  if [[ "${RULE_IDS}" == "nonempty" ]]; then
    error "ruleIds already populated; refusing to create duplicate. Use --interactive to update/recreate."
    exit 1
  fi
fi
# For interactive mode, re-run gate is handled in run_interactive() after flock acquisition.

# ---------------------------------------------------------------------------
# Acquire RULES_LOCK_FILE flock (D-07 — guards pre-check-and-create window)
# Mirrors cron.sh:19-29 exactly.
# ---------------------------------------------------------------------------
exec 9>"${RULES_LOCK_FILE}"
if ! python3 - <<'PY'
import fcntl, sys
try:
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
except (OSError, BlockingIOError):
    sys.exit(11)
PY
then
  warn "rules.lock held by concurrent setup-guardrails — skipping this run"
  exit 0
fi

# Re-check ruleIds after flock (TOCTOU defense)
RULE_IDS=$(read_config_field ruleIds)
if [[ "${RULE_IDS}" == "nonempty" ]]; then
  info "ruleIds populated by concurrent process — exiting cleanly"
  exit 0
fi

# ---------------------------------------------------------------------------
# Helper: create_rule RULE_NAME HARD_LIMIT WARN_THRESHOLD PERIOD
# The single call site for rule creation in this codebase (D-01).
# Sets RULE_ID (stdout) and RULE_EXIT (global) on return.
# ---------------------------------------------------------------------------
RULE_EXIT=0
RULE_ID=""

create_rule() {
  local rule_name="$1"
  local hard_limit="$2"
  local warn_threshold="$3"
  local period="$4"

  local cmd
  cmd=(revenium guardrails budget-rules create
    --output json
    --name "${rule_name}"
    --description ""
    --metric-type TOTAL_COST
    --window-type "${period}"
    --action BLOCK
    --group-by ORGANIZATION
    --warn-threshold "${warn_threshold}"
    --hard-limit "${hard_limit}"
  )

  if [[ "${SHADOW_MODE}" == "true" ]]; then
    cmd+=(--shadow-mode)
  fi

  local rule_json
  rule_json=$("${cmd[@]}" 2>&1) && RULE_EXIT=0 || RULE_EXIT=$?

  if [[ "${RULE_EXIT}" -ne 0 ]]; then
    local truncated_err
    truncated_err="${rule_json:0:200}"
    error "rule creation failed (exit ${RULE_EXIT}): ${truncated_err}"
    RULE_ID=""
    return
  fi

  RULE_ID=$(RULE_JSON="${rule_json}" python3 - <<'PY'
import json, os, sys
try:
    d = json.loads(os.environ['RULE_JSON'])
    print(d['id'])
except Exception:
    pass
PY
  )

  info "Created rule ${RULE_ID} for ${rule_name} (warn=${warn_threshold} hard=${hard_limit} period=${period})"
}

# ---------------------------------------------------------------------------
# Helper: write_rule_ids_to_config RULE_IDS_JSON
# Atomic write via temp-then-rename. Preserves alertId and all other fields.
# ---------------------------------------------------------------------------
write_rule_ids_to_config() {
  local rule_ids_json="$1"
  CONFIG_FILE="${CONFIG_FILE}" NEW_RULE_IDS_JSON="${rule_ids_json}" python3 - <<'PY'
import json, os, tempfile
from pathlib import Path

config_path = Path(os.environ['CONFIG_FILE'])
new_rule_ids = json.loads(os.environ['NEW_RULE_IDS_JSON'])

try:
    config = json.loads(config_path.read_text())
except Exception:
    config = {}

config['ruleIds'] = new_rule_ids
# SETUP-03: never write or strip alertId here. D-09 says leave the legacy
# alertId orphan in place; operator removes it manually in Revenium UI.

tmp_dir = config_path.parent
with tempfile.NamedTemporaryFile('w', dir=tmp_dir, delete=False, suffix='.tmp') as tmp:
    json.dump(config, tmp, indent=2)
    tmp.write('\n')
    tmp.flush()
    os.fsync(tmp.fileno())
    tmp_name = tmp.name

os.rename(tmp_name, str(config_path))
PY
}

# ---------------------------------------------------------------------------
# Helper: write_rule_ids_and_config RULE_IDS_JSON ORG_NAME AUTONOMOUS NOTIFY_CH NOTIFY_TGT
# Extended write-back that also persists org/autonomous/notify fields (--interactive mode).
# ---------------------------------------------------------------------------
write_rule_ids_and_config() {
  local rule_ids_json="$1"
  local org_name="${2:-}"
  local autonomous="${3:-}"
  local notify_channel="${4:-}"
  local notify_target="${5:-}"
  CONFIG_FILE="${CONFIG_FILE}" \
  NEW_RULE_IDS_JSON="${rule_ids_json}" \
  ORG_NAME="${org_name}" \
  AUTONOMOUS="${autonomous}" \
  NOTIFY_CHANNEL="${notify_channel}" \
  NOTIFY_TARGET="${notify_target}" \
  python3 - <<'PY'
import json, os, tempfile
from pathlib import Path

config_path = Path(os.environ['CONFIG_FILE'])
new_rule_ids = json.loads(os.environ['NEW_RULE_IDS_JSON'])
org_name = os.environ.get('ORG_NAME', '')
autonomous = os.environ.get('AUTONOMOUS', '')
notify_channel = os.environ.get('NOTIFY_CHANNEL', '')
notify_target = os.environ.get('NOTIFY_TARGET', '')

try:
    config = json.loads(config_path.read_text())
except Exception:
    config = {}

config['ruleIds'] = new_rule_ids

if org_name:
    config['organizationName'] = org_name
if autonomous in ('true', 'false'):
    config['autonomousMode'] = (autonomous == 'true')
if notify_channel:
    config['notifyChannel'] = notify_channel
if notify_target:
    config['notifyTarget'] = notify_target
# Never write or strip alertId (SETUP-03 + D-09).

tmp_dir = config_path.parent
with tempfile.NamedTemporaryFile('w', dir=tmp_dir, delete=False, suffix='.tmp') as tmp:
    json.dump(config, tmp, indent=2)
    tmp.write('\n')
    tmp.flush()
    os.fsync(tmp.fileno())
    tmp_name = tmp.name

os.rename(tmp_name, str(config_path))
PY
}

# ---------------------------------------------------------------------------
# Helper: migration_notify_once ERROR_CLASS MSG
# D-10: send at most one notification per error class. Hash-gated via MIGRATION_NOTIFY_FILE.
# ---------------------------------------------------------------------------
migration_notify_once() {
  local error_class="$1"
  local msg="$2"
  local new_hash prev_hash=""
  new_hash=$(ERROR_CLASS="${error_class}" python3 - <<'PY'
import hashlib, os
print(hashlib.sha256(os.environ['ERROR_CLASS'].encode()).hexdigest()[:16])
PY
  )
  if [[ -f "${MIGRATION_NOTIFY_FILE}" ]]; then
    prev_hash=$(cat "${MIGRATION_NOTIFY_FILE}" 2>/dev/null || true)
  fi
  if [[ "${new_hash}" != "${prev_hash}" ]]; then
    local notify_channel notify_target
    notify_channel=$(read_config_field notifyChannel)
    notify_target=$(read_config_field notifyTarget)
    if [[ -n "${notify_channel}" && -n "${notify_target}" ]] && command -v hermes >/dev/null 2>&1; then
      if hermes chat --toolsets messaging -q "Use the send_message tool to send this exact message to ${notify_channel}:${notify_target}: ${msg}" >/dev/null 2>&1; then
        info "Migration failure notification sent (class=${error_class})"
      else
        warn "Failed to send migration notification (class=${error_class})"
      fi
    else
      warn "Migration failure notification not sent (channel/target missing or hermes CLI unavailable) — class=${error_class}"
    fi
    echo "${new_hash}" > "${MIGRATION_NOTIFY_FILE}"
  fi
}

# Reset gate after a successful migration so next failure can re-notify.
migration_notify_reset() {
  rm -f "${MIGRATION_NOTIFY_FILE}"
}

# ---------------------------------------------------------------------------
# Placeholder for mode entry points (Task 3 fills in the bodies)
# ---------------------------------------------------------------------------
# Task 3 adds: run_default(), run_interactive(), run_migration(), case dispatch
