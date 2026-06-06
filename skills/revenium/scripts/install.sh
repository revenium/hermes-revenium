#!/usr/bin/env bash
# install.sh — one-command setup for the Hermes Revenium skill.
#
# Orchestrates the full wiring once the skill is present at
# ~/.hermes/skills/revenium/ (via `hermes skills tap add`, an external_dirs
# entry, or a manual copy):
#
#   1. Preflight required tools (revenium, sqlite3, python3).
#   2. Configure ALL FOUR Revenium credentials (key, team-id, tenant-id,
#      owner-id) — prompting for any that are missing. This is the step the
#      manual flow skipped: a config with only an API key meters fine but
#      fails every guardrails/jobs create with "teamId is required".
#   3. Install the on_session_end classifier plugin.
#   4. Register the pre/post hooks in config.yaml.
#   5. Create the Revenium guardrails budget rules.
#   6. Install the per-minute metering cron.
#   7. Restart the Hermes gateway so the plugin reloads.
#
# Idempotent: re-running is safe (each sub-step no-ops when already done).
#
# Usage:
#   bash ~/.hermes/skills/revenium/scripts/install.sh
#   bash ~/.hermes/skills/revenium/scripts/install.sh --hard-limit 50 --period MONTHLY
#   REVENIUM_TEAM_ID=... REVENIUM_TENANT_ID=... REVENIUM_OWNER_ID=... \
#     bash .../install.sh --non-interactive --hard-limit 5 --period DAILY
#
# Flags:
#   --hard-limit <N>   Budget hard limit; with --period, runs guardrails setup
#                      non-interactively (else setup-guardrails prompts).
#   --period <P>       DAILY | WEEKLY | MONTHLY | QUARTERLY.
#   --shadow-mode      Create guardrail rules in observe-only shadow mode.
#   --skip-guardrails  Skip budget-rule creation (creds + plumbing only).
#   --skip-cron        Skip installing the metering cron.
#   --non-interactive  Never prompt; take creds from REVENIUM_* env vars and
#                      fail if any required value is missing.
#   --no-restart       Do not restart the Hermes gateway at the end.
#   --help             Show this help and exit.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------
HARD_LIMIT=""
PERIOD=""
SHADOW_MODE="false"
SKIP_GUARDRAILS="false"
SKIP_CRON="false"
NON_INTERACTIVE="false"
NO_RESTART="false"

usage() { sed -n '2,46p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hard-limit) HARD_LIMIT="${2:-}"; shift 2 ;;
    --period) PERIOD="${2:-}"; shift 2 ;;
    --shadow-mode) SHADOW_MODE="true"; shift ;;
    --skip-guardrails) SKIP_GUARDRAILS="true"; shift ;;
    --skip-cron) SKIP_CRON="true"; shift ;;
    --non-interactive) NON_INTERACTIVE="true"; shift ;;
    --no-restart) NO_RESTART="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown flag: $1 (try --help)" >&2; exit 2 ;;
  esac
done

# Plain echo for the human at the terminal; warn/info go to the cron log helpers.
say()  { echo "$*"; }
step() { echo ""; echo "▸ $*"; }
ok()   { echo "  ✓ $*"; }
die()  { echo "" >&2; echo "  ✗ $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Preflight
# ---------------------------------------------------------------------------
step "Checking prerequisites"
for tool in revenium sqlite3 python3; do
  command -v "${tool}" >/dev/null 2>&1 || die "${tool} not found on PATH. Install it and re-run. (revenium: brew install revenium/tap/revenium)"
  ok "${tool}"
done

# ---------------------------------------------------------------------------
# 2. Credentials — ensure ALL FOUR are configured
# ---------------------------------------------------------------------------
step "Configuring Revenium credentials"

# A config field is "set" when revenium config show prints a value that is
# neither empty nor the literal "(not set)" placeholder. ANSI-stripped.
config_field_set() {
  local label="$1" esc val
  esc=$(printf '\033')
  val=$(revenium config show 2>/dev/null \
        | sed "s/${esc}\[[0-9;]*m//g" \
        | sed -n "s/.*${label}:[[:space:]]*//p" \
        | head -1 \
        | sed 's/[[:space:]]*$//')
  [[ -n "${val}" && "${val}" != "(not set)" ]]
}

# Ensure a single credential is PERSISTED into the revenium config.
# $1 = human label, $2 = `revenium config set` key, $3 = env var name.
#
# Critical: a REVENIUM_* env var must be *persisted*, not merely trusted. The
# cron runs without the operator's install-time environment, so a value that
# lives only in env (and that `revenium config show` reflects) would vanish the
# moment install.sh exits — leaving the cron with no teamId. So when the env var
# is set we always `revenium config set` it. config_field_set is only the
# decision-maker when no env var is present (then `config show` reflects the
# persisted config accurately).
ensure_cred() {
  local label="$1" key="$2" envvar="$3" val=""
  # Indirect read of $envvar with an unset-safe default. `${!envvar:-}` (indirect
  # `!` combined with `:-`) raises "invalid indirect expansion" under set -u when
  # the target is unset; eval of a normal expansion is the bash 3.2-portable form.
  eval "val=\"\${${envvar}:-}\""
  if [[ -n "${val}" ]]; then
    revenium config set "${key}" "${val}" >/dev/null 2>&1 \
      && ok "${label} set (from ${envvar})" \
      || die "Failed to set ${label} via 'revenium config set ${key}'."
    return 0
  fi
  if config_field_set "${label}"; then
    ok "${label} already configured"
    return 0
  fi
  if [[ "${NON_INTERACTIVE}" == "true" ]]; then
    die "${label} not configured and ${envvar} is unset (--non-interactive)."
  fi
  read -r -p "  Revenium ${label}: " val
  [[ -z "${val}" ]] && die "${label} is required."
  revenium config set "${key}" "${val}" >/dev/null 2>&1 \
    && ok "${label} set" \
    || die "Failed to set ${label} via 'revenium config set ${key}'."
}

ensure_cred "API Key"   "key"       "REVENIUM_API_KEY"
ensure_cred "Team ID"   "team-id"   "REVENIUM_TEAM_ID"
ensure_cred "Tenant ID" "tenant-id" "REVENIUM_TENANT_ID"
ensure_cred "Owner ID"  "owner-id"  "REVENIUM_OWNER_ID"

# Hard verify all four before doing any work that depends on them.
for f in "API Key" "Team ID" "Tenant ID" "Owner ID"; do
  config_field_set "${f}" || die "${f} still not configured — aborting."
done
ok "All four credentials present"

# ---------------------------------------------------------------------------
# 3. Classifier plugin
# ---------------------------------------------------------------------------
step "Installing the revenium-classifier plugin"
bash "${SCRIPT_DIR}/install-plugin.sh" --no-restart || die "Plugin install failed."

# ---------------------------------------------------------------------------
# 4. Shell hooks
# ---------------------------------------------------------------------------
step "Registering pre/post hooks in config.yaml"
bash "${SCRIPT_DIR}/install-hooks.sh" || warn "install-hooks.sh returned non-zero — review above; continuing."

# ---------------------------------------------------------------------------
# 5. Guardrail budget rules
# ---------------------------------------------------------------------------
# Idempotent re-run: skip rule creation when config.json already has ruleIds.
# setup-guardrails default mode refuses (exit 1) on existing ruleIds, and
# interactive mode would create duplicates — so install.sh gates here instead,
# keeping a re-run safe. To change limits/period, run setup-guardrails.sh
# --interactive directly.
rules_already_configured() {
  [[ -f "${CONFIG_FILE}" ]] || return 1
  python3 - "${CONFIG_FILE}" <<'PY' 2>/dev/null
import json, sys
try:
    ids = json.load(open(sys.argv[1])).get('ruleIds', [])
    sys.exit(0 if isinstance(ids, list) and ids else 1)
except Exception:
    sys.exit(1)
PY
}

if [[ "${SKIP_GUARDRAILS}" == "true" ]]; then
  step "Skipping guardrail budget rules (--skip-guardrails)"
elif rules_already_configured; then
  step "Guardrail budget rules already configured — skipping"
  ok "config.json already has ruleIds (run setup-guardrails.sh --interactive to change)"
else
  step "Creating Revenium guardrail budget rules"
  gr_cmd=(bash "${SCRIPT_DIR}/setup-guardrails.sh")
  if [[ -n "${HARD_LIMIT}" && -n "${PERIOD}" ]]; then
    gr_cmd+=(--hard-limit "${HARD_LIMIT}" --period "${PERIOD}")
  else
    gr_cmd+=(--interactive)
  fi
  [[ "${SHADOW_MODE}" == "true" ]] && gr_cmd+=(--shadow-mode)
  "${gr_cmd[@]}" || die "Guardrail rule creation failed — see the error above."
fi

# ---------------------------------------------------------------------------
# 6. Metering cron
# ---------------------------------------------------------------------------
if [[ "${SKIP_CRON}" == "true" ]]; then
  step "Skipping metering cron (--skip-cron)"
else
  step "Installing the per-minute metering cron"
  bash "${SCRIPT_DIR}/install-cron.sh" || die "Cron install failed."
fi

# ---------------------------------------------------------------------------
# 7. Gateway restart
# ---------------------------------------------------------------------------
if [[ "${NO_RESTART}" != "true" ]] && command -v hermes >/dev/null 2>&1; then
  step "Restarting the Hermes gateway"
  if hermes gateway restart >/dev/null 2>&1; then
    ok "Gateway restarted (classifier plugin reloaded)"
  else
    say "  NOTE: could not restart the gateway — run 'hermes gateway restart' manually."
  fi
fi

echo ""
echo "✅ Revenium skill installed and wired up."
echo "   Start a Hermes session ('hermes chat'); on first use, approve the revenium hooks when prompted."
echo "   Diagnose anytime: bash ${SCRIPT_DIR}/hooks-status.sh"
