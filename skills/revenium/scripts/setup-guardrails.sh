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
  --filter <dim:op:val>  Scope the rule's evaluation to traffic matching this filter.
                         Repeatable. Dims: AGENT, MODEL, PROVIDER, ORGANIZATION,
                         CREDENTIAL, PRODUCT, SUBSCRIBER, TASK_TYPE. Ops: IS, IS_NOT.
                         Mutually exclusive with --filters-json.
  --filters-json <json>  Inline JSON filter expression (advanced; passed through verbatim).
                         Mutually exclusive with --filter.
  --interactive          Collect all args from operator prompts.
  --from-alert <id>      Source the limit and period from a legacy alertId.
  --auto                 Suppress interactive prompts (required with --from-alert).
  --help                 Show this usage block and exit.

DEFAULT FILTER SCOPING:
  When neither --filter nor --filters-json is supplied, freshly-created rules
  default-scope to `--filter AGENT:IS:${REVENIUM_AGENT_NAME:-Hermes}` so the
  rule evaluates against the meter completions this skill ships (which all
  carry --agent "${REVENIUM_AGENT_NAME:-Hermes}"). Override by passing one or
  more --filter args (e.g. --filter MODEL:IS:claude-3-opus) or by passing
  --filters-json with a full filter expression.

EXAMPLES:
  # Fresh install — default mode (rule scoped to AGENT:IS:Hermes):
  setup-guardrails.sh --hard-limit 100 --period MONTHLY

  # Fresh install — interactive mode:
  setup-guardrails.sh --interactive

  # Default mode with an explicit per-model filter (overrides AGENT default):
  setup-guardrails.sh --hard-limit 50 --period MONTHLY --filter MODEL:IS:claude-3-opus

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
# v1.3 hotfix (quick-task 260524-lpu): operator-overridable filter scoping for
# the created rule. FILTERS is a repeatable list of `dim:op:val` triples;
# FILTERS_JSON is a single inline JSON expression. They are mutually exclusive
# (enforced after the parse loop). When both are empty, create_rule defaults
# to `--filter AGENT:IS:${REVENIUM_AGENT_NAME}` (see create_rule helper).
FILTERS=()
FILTERS_JSON=""

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
    --filter)
      if [[ -z "${2:-}" ]]; then
        error "--filter requires a dim:op:val argument"; exit 2
      fi
      FILTERS+=("$2")
      shift 2
      ;;
    --filters-json)
      if [[ -z "${2:-}" ]]; then
        error "--filters-json requires a JSON argument"; exit 2
      fi
      FILTERS_JSON="$2"
      shift 2
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

# Mutex: --filter and --filters-json cannot both be set.
if [[ -n "${FILTERS_JSON}" && ${#FILTERS[@]} -gt 0 ]]; then
  error "--filter and --filters-json are mutually exclusive"
  exit 2
fi

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
# teamId precheck (quick-260605)
# ---------------------------------------------------------------------------
# guardrails budget-rules create — like jobs create — requires a teamId. Without
# one the API returns HTTP 400 and rule creation fails opaquely. Fail loudly here
# so the operator fixes the config before we attempt (and partially apply) rules.
# Auto mode warns + exits 0 to preserve the fail-open automation contract above.
if [[ -z "$(resolve_team_id)" ]]; then
  if [[ "${AUTO}" == "true" ]]; then
    warn "teamId not configured — skipping setup-guardrails (run 'revenium config set team-id <id>')."
    exit 0
  else
    echo "No Revenium Team ID is configured. Budget-rule creation requires it."
    echo "Set it with: revenium config set team-id <TEAM_ID>   (then re-run /revenium)"
    exit 2
  fi
fi

# ---------------------------------------------------------------------------
# Helpers: read_config_field (shared helper, with list branch)
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
# --auto (cron) keeps its fail-open posture: a missing config.json on the
# cron path means "no install yet" — exit 0 so cron doesn't email errors.
# Interactive / default modes self-bootstrap: create STATE_DIR + seed an
# empty config.json so the operator can run setup-guardrails.sh on a
# fresh host without manually preparing state first (closes SC-1 fresh-
# host gap; supersedes Pitfall 6's exit-1 guard for power-user invocations).
if [[ ! -f "${CONFIG_FILE}" ]]; then
  if [[ "${AUTO}" == "true" ]]; then
    warn "no config.json — skipping migration; run /revenium setup"
    exit 0
  else
    info "no config.json at ${CONFIG_FILE} — bootstrapping fresh state"
    mkdir -p "${STATE_DIR}" || { error "could not create ${STATE_DIR}"; exit 1; }
    printf '{}\n' > "${CONFIG_FILE}" || { error "could not seed ${CONFIG_FILE}"; exit 1; }
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
    --group-by AGENT
    --warn-threshold "${warn_threshold}"
    --hard-limit "${hard_limit}"
  )

  # v1.3 hotfix (quick-task 260524-lpu): default-scope created rules to the
  # current install's agent name so the rule actually evaluates against the
  # meter completions we ship (which all carry --agent "${REVENIUM_AGENT_NAME}").
  # Pairs with --group-by AGENT above: filter narrows to agent=Hermes events,
  # group-by AGENT puts all matching spend in one self-contained bucket keyed
  # on the agent name (no dependency on org/subscription resolution).
  # ORGANIZATION grouping was the original default but produced currentValue: 0
  # on tenants whose orgs have no subscriptions (events fall through to the
  # auto-discovery UNCLASSIFIED subscription). Operator can override the
  # filter via --filter (one or more) or --filters-json.
  if [[ -n "${FILTERS_JSON}" ]]; then
    cmd+=(--filters-json "${FILTERS_JSON}")
  elif [[ ${#FILTERS[@]} -gt 0 ]]; then
    local f
    for f in "${FILTERS[@]}"; do
      cmd+=(--filter "${f}")
    done
  else
    cmd+=(--filter "AGENT:IS:${REVENIUM_AGENT_NAME}")
  fi

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
# Helper: compute warn threshold = 80% of hard limit (env-passing, bash 3.2)
# ---------------------------------------------------------------------------
compute_warn_threshold() {
  local hard_limit="$1"
  HARD_LIMIT_ENV="${hard_limit}" python3 - <<'PY'
import os
hard = float(os.environ['HARD_LIMIT_ENV'])
warn = hard * 0.8
# Print with up to 2 decimal places, strip trailing zeros
result = f"{warn:.2f}".rstrip('0').rstrip('.')
print(result if result else '0')
PY
}

# Helper: title-case a period string (MONTHLY -> Monthly, etc.)
period_titled() {
  local period="$1"
  case "${period}" in
    DAILY) echo "Daily" ;;
    WEEKLY) echo "Weekly" ;;
    MONTHLY) echo "Monthly" ;;
    QUARTERLY) echo "Quarterly" ;;
    *) echo "${period}" ;;
  esac
}

# ---------------------------------------------------------------------------
# Mode A: run_default — all args from CLI flags
# ---------------------------------------------------------------------------
run_default() {
  # Validate args (mode resolution already confirmed they're present)
  if ! validate_hard_limit "${HARD_LIMIT}"; then
    error "--hard-limit '${HARD_LIMIT}' must be a positive number"
    exit 2
  fi
  if ! validate_period "${PERIOD}"; then
    error "--period '${PERIOD}' must be DAILY, WEEKLY, MONTHLY, or QUARTERLY"
    exit 2
  fi

  local warn_threshold
  warn_threshold=$(compute_warn_threshold "${HARD_LIMIT}")

  local period_title
  period_title=$(period_titled "${PERIOD}")
  local rule_name="Hermes ${period_title} Budget"

  create_rule "${rule_name}" "${HARD_LIMIT}" "${warn_threshold}" "${PERIOD}"

  if [[ "${RULE_EXIT}" -ne 0 || -z "${RULE_ID}" ]]; then
    migration_notify_once "default_create_failed" "Revenium rule creation failed for ${rule_name}. Check ${LOG_FILE} for details."
    exit 1
  fi

  local new_rule_ids_json
  new_rule_ids_json="[\"${RULE_ID}\"]"
  write_rule_ids_to_config "${new_rule_ids_json}"

  info "config.json now contains ruleIds=[${RULE_ID}]"
  migration_notify_reset
  echo "Created rule ${RULE_ID}. config.json updated."
}

# ---------------------------------------------------------------------------
# Mode B: run_interactive — operator prompts (used by SKILL.md Setup Flow)
# ---------------------------------------------------------------------------
run_interactive() {
  echo ""
  echo "Setting up Revenium guardrails budget rules..."
  echo ""

  # Re-run gate (SETUP-05 + D-15): if ruleIds already populated, offer [r]ecreate / [c]ancel
  if [[ "${RULE_IDS}" == "nonempty" ]]; then
    echo "Existing budget rules found:"

    # List current rules from Revenium and display them
    local rules_json
    rules_json=$(revenium guardrails budget-rules list --output json 2>/dev/null) || rules_json="[]"

    # Read current ruleIds from config.json and display matching rules
    CONFIG_FILE="${CONFIG_FILE}" RULES_JSON="${rules_json}" python3 - <<'PY'
import json, os
config = json.loads(open(os.environ['CONFIG_FILE']).read())
rule_ids = config.get('ruleIds', [])
try:
    rules = json.loads(os.environ['RULES_JSON'])
except Exception:
    rules = []
rules_by_id = {r['id']: r for r in rules}
for rid in rule_ids:
    r = rules_by_id.get(rid)
    if r:
        print(f"  {rid}  {r.get('name', '?')}  hard={r.get('hardLimit', '?')}  warn={r.get('warnThreshold', '?')}  window={r.get('windowType', '?')}")
    else:
        print(f"  {rid}  (not found in Revenium)")
PY

    echo ""
    echo "Note: hard-limit cannot be updated in place; choose [r] to delete and recreate."

    local rerun_action=""
    local attempt=0
    while [[ ${attempt} -lt 3 ]]; do
      read -r -p "Action? [r]ecreate / [c]ancel: " rerun_action
      case "${rerun_action}" in
        r|recreate)
          # Delete all existing rules then fall through to fresh-install path
          local cur_rule_ids_raw
          cur_rule_ids_raw=$(CONFIG_FILE="${CONFIG_FILE}" python3 - <<'PY'
import json, os
config = json.loads(open(os.environ['CONFIG_FILE']).read())
for rid in config.get('ruleIds', []):
    print(rid)
PY
          )
          while IFS= read -r rid; do
            if [[ -n "${rid}" ]]; then
              revenium guardrails budget-rules delete "${rid}" --yes >/dev/null 2>&1 || true
              info "Deleted existing rule ${rid}"
            fi
          done <<< "${cur_rule_ids_raw}"
          RULE_IDS=""
          break
          ;;
        c|cancel|"")
          echo "Cancelled."
          exit 0
          ;;
        *)
          echo "Invalid choice. Please enter r or c."
          attempt=$((attempt + 1))
          ;;
      esac
    done

    if [[ ${attempt} -ge 3 ]]; then
      error "Too many invalid responses."
      exit 1
    fi
  fi

  # Operator prompts — fresh-install path
  local hard_limit="" period="" org_name="" autonomous="" notify_channel="" notify_target=""

  # Prompt for hard limit
  local hl_attempt=0
  while [[ ${hl_attempt} -lt 3 ]]; do
    read -r -p "Budget hard limit (numeric, e.g. 50.00): " hard_limit
    if validate_hard_limit "${hard_limit}"; then
      break
    fi
    echo "Invalid input. Must be a positive number (e.g. 50 or 100.00)."
    hl_attempt=$((hl_attempt + 1))
  done
  if ! validate_hard_limit "${hard_limit}"; then
    error "Too many invalid inputs for hard-limit."
    exit 1
  fi

  # Prompt for period
  local period_attempt=0
  while [[ ${period_attempt} -lt 3 ]]; do
    read -r -p "Budget period (DAILY/WEEKLY/MONTHLY/QUARTERLY): " period
    if validate_period "${period}"; then
      break
    fi
    echo "Invalid period. Must be DAILY, WEEKLY, MONTHLY, or QUARTERLY."
    period_attempt=$((period_attempt + 1))
  done
  if ! validate_period "${period}"; then
    error "Too many invalid inputs for period."
    exit 1
  fi

  # Optional org name
  read -r -p "Organization name (optional, press Enter to skip): " org_name || org_name=""

  # Autonomous mode
  local auto_response=""
  read -r -p "Run autonomously (budget halt enforced + notifications fire)? (yes/no, default no): " auto_response || auto_response=""
  case "${auto_response}" in
    yes|y|YES|Y)
      autonomous="true"
      read -r -p "Notify channel (e.g. slack, discord): " notify_channel || notify_channel=""
      read -r -p "Notify target (e.g. channel:C123, @username): " notify_target || notify_target=""
      ;;
    *)
      autonomous="false"
      ;;
  esac

  local warn_threshold
  warn_threshold=$(compute_warn_threshold "${hard_limit}")

  local period_title
  period_title=$(period_titled "${period}")
  local base_rule_name="Hermes ${period_title} Budget"

  # Create base rule
  create_rule "${base_rule_name}" "${hard_limit}" "${warn_threshold}" "${period}"

  if [[ "${RULE_EXIT}" -ne 0 || -z "${RULE_ID}" ]]; then
    error "Failed to create base budget rule."
    exit 1
  fi

  local base_rule_id="${RULE_ID}"
  local rule_ids_list="${base_rule_id}"

  # Task-type picker (SETUP-02 + D-12, D-13, D-14)
  if [[ -f "${TAXONOMY_FILE}" ]]; then
    local labels_json
    labels_json=$(TAXONOMY_FILE="${TAXONOMY_FILE}" python3 - <<'PY'
import json, os, sys
try:
    d = json.load(open(os.environ['TAXONOMY_FILE']))
    labels = list(d.get('labels', {}).keys())
    print(json.dumps(labels))
except Exception:
    print('[]')
PY
    )

    local label_count
    label_count=$(echo "${labels_json}" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

    if [[ "${label_count}" -gt 0 ]]; then
      echo ""
      echo "Available task types (optional per-task budget rules):"
      LABELS_JSON="${labels_json}" python3 - <<'PY'
import json, os
labels = json.loads(os.environ['LABELS_JSON'])
for i, label in enumerate(labels, 1):
    print(f"  {i}) {label}")
PY

      local task_selection=""
      read -r -p 'Which to enforce? (comma-separated indices, or "none"): ' task_selection || task_selection=""

      # Parse selection and create per-task rules
      local selected_labels
      selected_labels=$(LABELS_JSON="${labels_json}" TASK_TYPE_SELECTION="${task_selection}" python3 - <<'PY'
import json, os
labels = json.loads(os.environ['LABELS_JSON'])
sel = os.environ['TASK_TYPE_SELECTION'].strip().lower()
if sel == 'none' or not sel:
    print('[]')
else:
    try:
        indices = [int(x.strip()) for x in sel.split(',') if x.strip().isdigit()]
        selected = [labels[i-1] for i in indices if 1 <= i <= len(labels)]
        print(json.dumps(selected))
    except Exception:
        print('[]')
PY
      )

      local num_selected
      num_selected=$(echo "${selected_labels}" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

      if [[ "${num_selected}" -gt 0 ]]; then
        # Iterate selected labels and create per-task rules
        local label_index=0
        while [[ ${label_index} -lt ${num_selected} ]]; do
          local label
          label=$(LABELS_JSON="${selected_labels}" IDX="${label_index}" python3 - <<'PY'
import json, os
labels = json.loads(os.environ['LABELS_JSON'])
print(labels[int(os.environ['IDX'])])
PY
          )

          local task_hard_limit="" task_hl_attempt=0
          while [[ ${task_hl_attempt} -lt 3 ]]; do
            read -r -p "Hard limit for ${label} (numeric): " task_hard_limit
            if validate_hard_limit "${task_hard_limit}"; then
              break
            fi
            echo "Invalid input. Must be a positive number."
            task_hl_attempt=$((task_hl_attempt + 1))
          done
          if ! validate_hard_limit "${task_hard_limit}"; then
            warn "Skipping task-type rule for ${label} (invalid hard-limit after 3 attempts)."
            label_index=$((label_index + 1))
            continue
          fi

          local task_warn
          task_warn=$(compute_warn_threshold "${task_hard_limit}")

          local label_title
          label_title=$(echo "${label}" | python3 -c "import sys; s=sys.stdin.read().strip(); print(s.replace('_',' ').title().replace(' ','_'))" 2>/dev/null || echo "${label}")
          local task_rule_name="Hermes ${label_title} Budget"

          create_rule "${task_rule_name}" "${task_hard_limit}" "${task_warn}" "${period}"

          if [[ "${RULE_EXIT}" -eq 0 && -n "${RULE_ID}" ]]; then
            rule_ids_list="${rule_ids_list}
${RULE_ID}"
          else
            warn "Failed to create rule for task type ${label} — skipping."
          fi

          label_index=$((label_index + 1))
        done
      fi
    fi
  fi

  # Build JSON array from newline-separated rule IDs
  local new_rule_ids_json
  new_rule_ids_json=$(RULE_IDS_NL="${rule_ids_list}" python3 - <<'PY'
import json, os
lines = [x.strip() for x in os.environ['RULE_IDS_NL'].strip().split('\n') if x.strip()]
print(json.dumps(lines))
PY
  )

  write_rule_ids_and_config "${new_rule_ids_json}" "${org_name}" "${autonomous}" "${notify_channel}" "${notify_target}"

  migration_notify_reset

  local rule_count
  rule_count=$(echo "${new_rule_ids_json}" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "?")
  echo "Created ${rule_count} rule(s). config.json updated. ruleIds=${new_rule_ids_json}"
}

# ---------------------------------------------------------------------------
# Mode C: run_migration — cron auto-migration from legacy alertId (--from-alert --auto)
# ---------------------------------------------------------------------------
run_migration() {
  # D-11: operator-controllable shadow-mode override via cron env
  if [[ "${REVENIUM_MIGRATE_SHADOW_MODE:-false}" == "true" ]]; then
    SHADOW_MODE="true"
  fi

  # Cross-check: --from-alert value must match stored alertId
  if [[ "${FROM_ALERT}" != "${EXISTING_ALERT_ID}" ]]; then
    error "alertId mismatch: --from-alert=${FROM_ALERT} vs config.json alertId=${EXISTING_ALERT_ID}"
    exit 1
  fi

  # Fetch alert list (Pitfall 1: must use list, not get — list has cumulativePeriod + name)
  local alert_list
  alert_list=$(revenium alerts budget list --output json 2>/dev/null) || alert_list="[]"

  # Filter by alertId, emit KEY=value lines
  local alert_data
  alert_data=$(
    FROM_ALERT_ID="${FROM_ALERT}" ALERT_LIST="${alert_list}" python3 - <<'PY'
import json, os
alert_id = os.environ['FROM_ALERT_ID']
try:
    alerts = json.loads(os.environ['ALERT_LIST'])
except Exception:
    alerts = []
match = next((a for a in alerts if a.get('alertId') == alert_id), None)
if match:
    # T-18-LOG-INJECT mitigation: truncate name to 64 chars before logging
    name = (match.get('name') or '')[:64]
    print(f"THRESHOLD={match.get('threshold', '')}")
    print(f"PERIOD={match.get('cumulativePeriod', '')}")
    print(f"NAME={name}")
    print("FOUND=true")
else:
    print("FOUND=false")
PY
  )

  local found
  found=$(echo "${alert_data}" | sed -n 's/^FOUND=//p')

  # D-09: deleted-alert edge case
  if [[ "${found}" != "true" ]]; then
    error "Legacy alertId ${FROM_ALERT} not found in Revenium alerts budget list — it was deleted upstream."
    migration_notify_once "deleted_upstream_alert" "Legacy alertId ${FROM_ALERT} not found in Revenium — it was deleted upstream. Run /revenium setup to create fresh ruleIds."
    exit 0
  fi

  local threshold period mig_name
  threshold=$(echo "${alert_data}" | sed -n 's/^THRESHOLD=//p')
  period=$(echo "${alert_data}" | sed -n 's/^PERIOD=//p')
  mig_name=$(echo "${alert_data}" | sed -n 's/^NAME=//p')

  # Validate threshold
  if ! validate_hard_limit "${threshold}"; then
    error "alert threshold '${threshold}' is not a valid positive number"
    migration_notify_once "bad_threshold" "Legacy alertId ${FROM_ALERT} has non-numeric threshold '${threshold}'. Manual investigation required."
    exit 0
  fi

  # Validate period
  if ! validate_period "${period}"; then
    error "alert period '${period}' is not one of DAILY/WEEKLY/MONTHLY/QUARTERLY"
    migration_notify_once "bad_period" "Legacy alertId ${FROM_ALERT} has unrecognized period '${period}'. Manual investigation required."
    exit 0
  fi

  local warn_threshold
  warn_threshold=$(compute_warn_threshold "${threshold}")

  # Pick rule name: use alert name if available, else derive from period
  local rule_name
  if [[ -n "${mig_name}" ]]; then
    rule_name="${mig_name}"
  else
    local period_title
    period_title=$(period_titled "${period}")
    rule_name="Hermes ${period_title} Budget"
  fi

  # TOCTOU re-check after flock (concurrent process may have completed migration)
  RULE_IDS=$(read_config_field ruleIds)
  if [[ "${RULE_IDS}" == "nonempty" ]]; then
    info "ruleIds populated by concurrent migration — exiting cleanly"
    exit 0
  fi

  create_rule "${rule_name}" "${threshold}" "${warn_threshold}" "${period}"

  if [[ "${RULE_EXIT}" -ne 0 || -z "${RULE_ID}" ]]; then
    local truncated_msg="${rule_name:0:64}"
    error "Migration from legacy alertId ${FROM_ALERT} to guardrails rule failed. Cron will retry next tick."
    migration_notify_once "create_failed" "Migration from legacy alertId ${FROM_ALERT} failed for rule '${truncated_msg}'. Cron will retry next tick. Check logs for details."
    exit 0
  fi

  local new_rule_ids_json="[\"${RULE_ID}\"]"
  write_rule_ids_to_config "${new_rule_ids_json}"

  # MIGR-03: one-time deprecation log line
  info "deprecation: legacy alertId ${FROM_ALERT} orphaned, migrated to ruleId ${RULE_ID}"

  migration_notify_reset
  exit 0
}

# ---------------------------------------------------------------------------
# Top-level mode dispatch
# ---------------------------------------------------------------------------
case "${MODE}" in
  interactive) run_interactive ;;
  from-alert)  run_migration ;;
  default)     run_default ;;
  *)           error "unknown mode ${MODE}"; exit 2 ;;
esac
