#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${HOME}/.hermes/skills/revenium"

mkdir -p "${HOME}/.hermes/skills"

# Remove stray duplicate skill dirs (e.g. revenium.bak.*, revenium.predeploy.bak.*).
# Hermes plugin discovery scans every skill's bundled plugins/ subdir, so a leftover
# copy registers a duplicate revenium-classifier and can shadow the fresh install.
# The `revenium.*` glob (note the dot) matches backups but never `revenium` itself.
find "${HOME}/.hermes/skills" -maxdepth 1 -type d -name 'revenium.*' -print -exec rm -rf {} + 2>/dev/null || true

rm -rf "${TARGET_DIR}"
cp -R "${REPO_ROOT}/skills/revenium" "${TARGET_DIR}"
# Prune the stale hooks/ tree from the bulk skill copy — superseded by plugins/ (06-02 / G-01 closure).
rm -rf "${TARGET_DIR}/hooks"
# Drop any __pycache__ carried in by cp -R — stale .pyc can shadow updated source.
find "${TARGET_DIR}" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
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

JOB_TAXONOMY_DEST="${REVENIUM_JOB_TAXONOMY_FILE:-${STATE_DIR_DEFAULT}/job-taxonomy.json}"
if [[ ! -f "${JOB_TAXONOMY_DEST}" ]]; then
  cp "${REPO_ROOT}/skills/revenium/job-taxonomy.json" "${JOB_TAXONOMY_DEST}"
  echo "Seeded ${JOB_TAXONOMY_DEST}"
else
  echo "Job taxonomy already exists at ${JOB_TAXONOMY_DEST}, not overwriting"
fi

# Phase 6 (gap closure): install the on_session_end classifier PLUGIN into ~/.hermes/plugins/
# — covers gateway, CLI, interactive, ACP, and cron sessions (universal coverage per HOOK-11).
# `hermes skills install` does NOT relocate plugins/ subdirs; setup-local + install-plugin.sh
# close the gap. Delegate to install-plugin.sh so the plugin-install + config.yaml-patch
# logic lives in exactly one place (a divergent inline copy here used to drift from the
# script). --no-restart because setup-local performs the gateway restart at the end of
# the run.
bash "${TARGET_DIR}/scripts/install-plugin.sh" --no-restart

# Phase 12 (D-02): register pre_llm_call / pre_tool_call shell hooks in config.yaml.
# Guard with || true so a hooks-install hiccup does not abort the whole local setup.
bash "${TARGET_DIR}/scripts/install-hooks.sh" || true

# Restart the Hermes gateway so the long-lived gateway process reloads the updated
# classifier plugin. A stale gateway keeps running the pre-update plugin and silently
# stops writing job markers for gateway-served (Telegram / Slack) sessions — fresh CLI
# processes pick up the new plugin on their own, but the gateway does not.
if command -v hermes >/dev/null 2>&1; then
  if hermes gateway restart >/dev/null 2>&1; then
    echo "Restarted Hermes gateway (reloaded classifier plugin)"
  else
    echo "NOTE: could not restart Hermes gateway — run 'hermes gateway restart' manually"
  fi
fi

echo "Installed skill to ${TARGET_DIR}"
echo ""
echo "Next steps:"
echo "  1. Verify Revenium CLI: revenium config show"
echo "  2. Install cron: bash ~/.hermes/skills/revenium/scripts/install-cron.sh"
echo "  3. Start Hermes ('hermes chat') and approve the revenium hooks when prompted."
echo "     The hooks are registered but inert until you approve them on first use (D-03)."
