#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${HOME}/.hermes/skills/revenium"

# ---------------------------------------------------------------------------
# Preflight: refuse to install a non-functional skill.
#
# The skill is useless without the `revenium` CLI (every cron tick shells out
# to `revenium meter completion`, `revenium guardrails enforcement-rules get`,
# etc.) and `sqlite3` (the cron reads token counts from ~/.hermes/state.db
# via sqlite3). `python3` is used for stdlib heredocs throughout the scripts.
#
# Without these, `setup-local.sh` previously reported "Installed skill" and
# the operator only discovered the install was broken when nothing showed up
# in Revenium. Fail fast with actionable install instructions instead.
# ---------------------------------------------------------------------------
missing=()
command -v revenium >/dev/null 2>&1 || missing+=("revenium")
command -v sqlite3  >/dev/null 2>&1 || missing+=("sqlite3")
command -v python3  >/dev/null 2>&1 || missing+=("python3")

if (( ${#missing[@]} > 0 )); then
  echo "ERROR: Required dependencies missing: ${missing[*]}" >&2
  echo >&2
  echo "Install the missing tools, then re-run this script:" >&2
  echo >&2
  for tool in "${missing[@]}"; do
    case "${tool}" in
      revenium)
        echo "  revenium CLI:" >&2
        echo "    macOS:          brew install revenium/tap/revenium" >&2
        echo "    Linux:          see https://github.com/revenium/revenium-cli/releases for the binary," >&2
        echo "                    or 'brew install revenium/tap/revenium' under Linuxbrew." >&2
        echo "    After install:  run 'revenium config show' and confirm the API key is non-empty;" >&2
        echo "                    if blank, follow the four 'revenium config set' calls in SKILL.md Setup Flow step 2." >&2
        ;;
      sqlite3)
        echo "  sqlite3:" >&2
        echo "    macOS:          bundled (or 'brew install sqlite3')" >&2
        echo "    Debian/Ubuntu:  sudo apt install sqlite3" >&2
        echo "    RHEL/Fedora:    sudo dnf install sqlite" >&2
        ;;
      python3)
        echo "  python3:" >&2
        echo "    macOS:          bundled (or 'brew install python3')" >&2
        echo "    Debian/Ubuntu:  sudo apt install python3" >&2
        echo "    RHEL/Fedora:    sudo dnf install python3" >&2
        ;;
    esac
    echo >&2
  done
  echo "Setup aborted — no files were written." >&2
  exit 1
fi

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
