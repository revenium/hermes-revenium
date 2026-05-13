#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${HOME}/.hermes/skills/revenium"

mkdir -p "${HOME}/.hermes/skills"
rm -rf "${TARGET_DIR}"
cp -R "${REPO_ROOT}/skills/revenium" "${TARGET_DIR}"
chmod +x "${TARGET_DIR}/scripts/"*.sh

STATE_DIR_DEFAULT="${REVENIUM_STATE_DIR:-${HOME}/.hermes/state/revenium}"
TAXONOMY_DEST="${REVENIUM_TAXONOMY_FILE:-${STATE_DIR_DEFAULT}/task-taxonomy.json}"
mkdir -p "$(dirname "${TAXONOMY_DEST}")"
if [[ ! -f "${TAXONOMY_DEST}" ]]; then
  cp "${REPO_ROOT}/skills/revenium/task-taxonomy.json" "${TAXONOMY_DEST}"
  echo "Seeded ${TAXONOMY_DEST}"
else
  echo "Taxonomy already exists at ${TAXONOMY_DEST}, not overwriting"
fi

# Phase 6: install the agent:end classifier hook into ~/.hermes/hooks/
# (skills/ tree does NOT auto-relocate hooks/ subdirs — confirmed via 06-RESEARCH.md Gate 3)
# The bulk `cp -R skills/revenium → ${TARGET_DIR}` above just deposited a STALE
# DUPLICATE at ${TARGET_DIR}/hooks/. Prune it so the hook lives in exactly one
# place under ~/.hermes/ (06-RESEARCH.md Pitfall 7).
rm -rf "${TARGET_DIR}/hooks"
HOOKS_DIR="${HOME}/.hermes/hooks"
HOOK_TARGET="${HOOKS_DIR}/revenium-classifier"
mkdir -p "${HOOKS_DIR}"
rm -rf "${HOOK_TARGET}"
cp -R "${REPO_ROOT}/skills/revenium/hooks/revenium-classifier" "${HOOK_TARGET}"
echo "Installed hook to ${HOOK_TARGET}"

echo "Installed skill to ${TARGET_DIR}"
echo ""
echo "Next steps:"
echo "  1. Verify Revenium CLI: revenium config show"
echo "  2. Install cron: bash ~/.hermes/skills/revenium/scripts/install-cron.sh"
echo "  3. Restart Hermes gateway to load the classifier hook: hermes gateway restart"
echo "  4. Start Hermes and load /revenium"
