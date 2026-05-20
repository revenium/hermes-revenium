#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

# Argument parsing.
# --interval-seconds N : run the metering pipeline every N seconds within
#                        each cron tick (1..60). N=60 (or omitted) preserves
#                        once-per-minute behavior. Smaller N shortens demo
#                        feedback at the cost of more revenium-CLI calls.
# --dry-run            : print the crontab line that would be installed and
#                        exit 0 without touching crontab. Useful for tests
#                        and for previewing what the installer will do.
# --force              : replace any existing hermes-revenium-metering line
#                        instead of leaving it untouched. Required when
#                        changing --interval-seconds on a host that already
#                        has the cron installed.
INTERVAL_SECONDS=""
DRY_RUN=false
FORCE=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --interval-seconds)
      INTERVAL_SECONDS="${2:-}"; shift 2 ;;
    --interval-seconds=*)
      INTERVAL_SECONDS="${1#--interval-seconds=}"; shift ;;
    --dry-run)
      DRY_RUN=true; shift ;;
    --force)
      FORCE=true; shift ;;
    -h|--help)
      cat <<USAGE
Usage: install-cron.sh [--interval-seconds N] [--force] [--dry-run]

Installs the per-minute Revenium metering cron entry that drains markers,
ships token usage / tool-events to Revenium, and refreshes budget-status.json.

  --interval-seconds N   Run the metering pipeline every N seconds within
                         each cron tick (1..60). Defaults to 60. Set to 15
                         for a four-times-per-minute "demo" cadence so spend
                         appears in Revenium faster.
  --force                Replace any existing hermes-revenium-metering line
                         (required to change --interval-seconds on a host
                         that already has the cron installed).
  --dry-run              Print the crontab line that would be installed and
                         exit without modifying crontab.

USAGE
      exit 0 ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      echo "Run with --help for usage." >&2
      exit 1 ;;
  esac
done

ensure_path
mkdir -p "${STATE_DIR}"
chmod 700 "${MARKERS_DIR}"
chmod +x "${SKILL_DIR}/scripts/"*.sh

CRON_SCRIPT="${SKILL_DIR}/scripts/cron.sh"
CRON_COMMENT="# hermes-revenium-metering"
CRON_SCHEDULE="* * * * *"
CRON_PATH="/usr/local/bin:/usr/bin:/bin"

for p in   /home/linuxbrew/.linuxbrew/bin   /opt/homebrew/bin   "${HOME}/go/bin"   "${HOME}/.local/bin"; do
  [[ -d "${p}" ]] && CRON_PATH="${p}:${CRON_PATH}"
done

if command -v brew >/dev/null 2>&1; then
  BREW_BIN="$(brew --prefix 2>/dev/null)/bin"
  [[ -d "${BREW_BIN}" ]] && CRON_PATH="${BREW_BIN}:${CRON_PATH}"
fi

# Translate --interval-seconds N into the two loop knobs that cron.sh reads.
# Validation here is fail-loud (exit 1) because misconfigured cron lines are
# silent killers — cron just runs the bad line every minute until you notice.
LOOP_ENV=""
INTERVAL_DESCRIPTION="every minute"
if [[ -n "${INTERVAL_SECONDS}" ]]; then
  if ! [[ "${INTERVAL_SECONDS}" =~ ^[0-9]+$ ]] \
      || (( INTERVAL_SECONDS < 1 )) || (( INTERVAL_SECONDS > 60 )); then
    echo "ERROR: --interval-seconds must be an integer in 1..60 (got: ${INTERVAL_SECONDS})" >&2
    exit 1
  fi
  if (( INTERVAL_SECONDS < 60 )); then
    LOOP_COUNT=$(( 60 / INTERVAL_SECONDS ))
    LOOP_ENV="REVENIUM_CRON_LOOP_COUNT=${LOOP_COUNT} REVENIUM_CRON_LOOP_SLEEP_SECONDS=${INTERVAL_SECONDS} "
    INTERVAL_DESCRIPTION="${LOOP_COUNT}x per minute (every ${INTERVAL_SECONDS}s)"
  fi
fi

CRON_LINE="${CRON_SCHEDULE} HERMES_HOME=${HERMES_HOME} REVENIUM_STATE_DIR=${STATE_DIR} ${LOOP_ENV}PATH=${CRON_PATH} bash ${CRON_SCRIPT} >> ${LOG_FILE} 2>&1 ${CRON_COMMENT}"

if ${DRY_RUN}; then
  echo "${CRON_LINE}"
  exit 0
fi

EXISTING_LINE=""
if EXISTING_LINE=$(crontab -l 2>/dev/null | grep "hermes-revenium-metering" || true); [[ -n "${EXISTING_LINE}" ]]; then
  if ! ${FORCE}; then
    echo "✓ Revenium cron already installed."
    echo "${EXISTING_LINE}"
    if [[ -n "${INTERVAL_SECONDS}" ]]; then
      echo ""
      echo "ℹ --interval-seconds was supplied but the existing entry was left in place."
      echo "  Re-run with --force to replace it:"
      echo "    bash ${SKILL_DIR}/scripts/install-cron.sh --interval-seconds ${INTERVAL_SECONDS} --force"
    fi
    exit 0
  fi
  # --force: strip the existing line and append the new one.
  ( crontab -l 2>/dev/null | grep -v "hermes-revenium-metering" || true; echo "${CRON_LINE}" ) | crontab -
  echo "✅ Revenium metering cron replaced (${INTERVAL_DESCRIPTION})"
else
  ( crontab -l 2>/dev/null || true; echo "${CRON_LINE}" ) | crontab -
  echo "✅ Revenium metering cron installed (${INTERVAL_DESCRIPTION})"
fi

echo "   Log: ${LOG_FILE}"
echo ""
echo "To view logs:    tail -f ${LOG_FILE}"
echo "To run manually: bash ${CRON_SCRIPT}"
echo "To uninstall:    bash ${SKILL_DIR}/scripts/uninstall-cron.sh"
