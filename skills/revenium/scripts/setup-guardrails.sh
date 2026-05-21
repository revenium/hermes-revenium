#!/usr/bin/env bash
set -euo pipefail
# setup-guardrails.sh — single rule-creation entry point for the v1.3 guardrails-native
# budget enforcement. Three modes per D-02:
#   default  : --hard-limit N --period P [...] from CLI args; idempotent create.
#   --interactive : operator prompts; called by SKILL.md Setup Flow (plan 18-04).
#   --from-alert <id> --auto : cron migration; called by cron.sh first stage (plan 18-03).
# Idempotent via ruleIds-presence pre-check (D-07); flock-guarded via RULES_LOCK_FILE (D-07);
# --shadow-mode propagates to every create call (D-04).
# Bash 3.2 compatible (Mac Studio gate) — uses env-passing heredoc pattern (NEVER ${var@Q}).

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
# Placeholder for mode dispatch (Tasks 2 and 3 fill in the body)
# ---------------------------------------------------------------------------
# Task 2 adds: config.json existence check, three-state pre-check, flock,
#              create_rule(), write_rule_ids_to_config(), migration_notify_once()
# Task 3 adds: run_default(), run_interactive(), run_migration(), mode dispatch
