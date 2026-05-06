#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path
mkdir -p "${STATE_DIR}"
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

CRON_LINE="${CRON_SCHEDULE} HERMES_HOME=${HERMES_HOME} REVENIUM_STATE_DIR=${STATE_DIR} PATH=${CRON_PATH} bash ${CRON_SCRIPT} >> ${LOG_FILE} 2>&1 ${CRON_COMMENT}"

if crontab -l 2>/dev/null | grep -q "hermes-revenium-metering"; then
  echo "✓ Revenium cron already installed."
  crontab -l | grep "hermes-revenium-metering"
  exit 0
fi

( crontab -l 2>/dev/null || true; echo "${CRON_LINE}" ) | crontab -

echo "✅ Revenium metering cron installed (every minute)"
echo "   Log: ${LOG_FILE}"
echo ""
echo "To view logs:    tail -f ${LOG_FILE}"
echo "To run manually: bash ${CRON_SCRIPT}"
echo "To uninstall:    bash ${SKILL_DIR}/scripts/uninstall-cron.sh"
