#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${HOME}/.hermes/skills/revenium"

mkdir -p "${HOME}/.hermes/skills"
rm -rf "${TARGET_DIR}"
cp -R "${REPO_ROOT}/skills/revenium" "${TARGET_DIR}"
chmod +x "${TARGET_DIR}/scripts/"*.sh

echo "Installed skill to ${TARGET_DIR}"
echo ""
echo "Next steps:"
echo "  1. Verify Revenium CLI: revenium config show"
echo "  2. Install cron: bash ~/.hermes/skills/revenium/scripts/install-cron.sh"
echo "  3. Start Hermes and load /revenium"
