#!/usr/bin/env bash
set -euo pipefail
# install-plugin.sh — install the revenium-classifier on_session_end plugin into
# Hermes' plugin discovery path and enable it in ${HOOKS_CONFIG_FILE}.
#
# Why this script exists: `hermes skills install`, the GitHub tap install, and
# `external_dirs` all place skill content under ~/.hermes/skills/<name>/, but
# Hermes' plugin manager loads on_session_end plugins from a *separate* root:
# ~/.hermes/plugins/<plugin>/. Without this step the classifier never runs,
# no kind:"job" markers are written, and agentic-job usage never reaches
# Revenium. install.sh does this for local dev installs; this
# script is the equivalent for tap / hermes-skills-install operators.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

# Argument parsing.
#   --dry-run     Print every fs/yaml operation that would be performed without
#                 touching the filesystem. Used by the test suite.
#   --no-restart  Skip `hermes gateway restart` (useful in CI / containers
#                 where the gateway isn't running).
#   -h | --help   Usage.
DRY_RUN=false
NO_RESTART=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true; shift ;;
    --no-restart)
      NO_RESTART=true; shift ;;
    -h|--help)
      cat <<USAGE
Usage: install-plugin.sh [--dry-run] [--no-restart]

Installs the bundled revenium-classifier on_session_end plugin into
\${HERMES_HOME}/plugins/ and enables it in \${HERMES_HOME}/config.yaml's
plugins.enabled list. Idempotent — re-runs are safe.

After this step (and a hermes gateway restart) every session-end emits a
kind:"job" marker so Revenium agentic-job analytics work.

  --dry-run      Print operations without performing them.
  --no-restart   Don't run 'hermes gateway restart' after install.

USAGE
      exit 0 ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      echo "Run with --help for usage." >&2
      exit 1 ;;
  esac
done

ensure_path

PLUGIN_NAME="revenium-classifier"
PLUGIN_SRC="${SKILL_DIR}/plugins/${PLUGIN_NAME}"
PLUGIN_DEST_DIR="${HERMES_HOME}/plugins"
PLUGIN_DEST="${PLUGIN_DEST_DIR}/${PLUGIN_NAME}"

if [[ ! -d "${PLUGIN_SRC}" ]]; then
  echo "ERROR: plugin source missing at ${PLUGIN_SRC}" >&2
  echo "  'hermes skills install' fetches only SKILL.md + references/ — not plugins/" >&2
  echo "  or scripts/. Run the bootstrap to fetch them, then re-run setup:" >&2
  echo "    bash ${SKILL_DIR}/references/bootstrap.sh" >&2
  echo "  (or: git clone --depth 1 https://github.com/revenium/hermes-revenium.git /tmp/hr && bash /tmp/hr/install.sh)" >&2
  exit 1
fi

if ${DRY_RUN}; then
  echo "[dry-run] mkdir -p ${PLUGIN_DEST_DIR}"
  echo "[dry-run] rm -rf ${PLUGIN_DEST}"
  echo "[dry-run] cp -R ${PLUGIN_SRC} ${PLUGIN_DEST}"
  echo "[dry-run] strip __pycache__ from ${PLUGIN_DEST}"
else
  mkdir -p "${PLUGIN_DEST_DIR}"
  # Unconditional overwrite: matches the setup-local pattern. The plugin is
  # source-controlled in the skill bundle and ships as a unit; partial-update
  # races are worse than a clean replace. The next gateway restart picks up
  # whatever lands here.
  rm -rf "${PLUGIN_DEST}"
  cp -R "${PLUGIN_SRC}" "${PLUGIN_DEST}"
  # Drop any __pycache__ carried by cp -R — Hermes loads the plugin from this
  # directory and a stale .pyc would shadow updated classifier.py.
  find "${PLUGIN_DEST}" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
  echo "✓ Plugin installed at ${PLUGIN_DEST}"
fi

# Patch ${HOOKS_CONFIG_FILE} to ensure the plugin appears in plugins.enabled.
# Mirror of install.sh's heredoc — stdlib only, no PyYAML (per
# project constraint), idempotent on re-run, lenient about list-item indentation.
if ${DRY_RUN}; then
  echo "[dry-run] ensure ${PLUGIN_NAME} listed in plugins.enabled of ${HOOKS_CONFIG_FILE}"
else
  mkdir -p "$(dirname "${HOOKS_CONFIG_FILE}")"
  CONFIG_YAML="${HOOKS_CONFIG_FILE}" PLUGIN_NAME="${PLUGIN_NAME}" python3 - <<'PY'
import os
import re
from pathlib import Path

path = Path(os.environ['CONFIG_YAML'])
plugin_name = os.environ['PLUGIN_NAME']

if not path.exists():
    path.write_text(
        "plugins:\n"
        "  enabled:\n"
        f"    - {plugin_name}\n",
        encoding="utf-8",
    )
    print(f"✓ Created {path} with plugins.enabled containing {plugin_name}")
    raise SystemExit(0)

content = path.read_text(encoding="utf-8")

if re.search(r"^\s*-\s*" + re.escape(plugin_name) + r"\s*$", content, re.MULTILINE):
    print(f"✓ {plugin_name} already enabled in {path}")
    raise SystemExit(0)

plugins_match = re.search(r"^plugins:\s*$", content, re.MULTILINE)
if not plugins_match:
    if not content.endswith("\n"):
        content += "\n"
    content += f"plugins:\n  enabled:\n    - {plugin_name}\n"
    path.write_text(content, encoding="utf-8")
    print(f"✓ Added plugins.enabled block to {path}")
    raise SystemExit(0)

after_plugins = content[plugins_match.end():]
next_top_match = re.search(r"^[^\s#]", after_plugins, re.MULTILINE)
plugins_block_end = (plugins_match.end() + next_top_match.start()) if next_top_match else len(content)
plugins_block = content[plugins_match.end():plugins_block_end]

enabled_match = re.search(r"^(\s+)enabled:(.*)$", plugins_block, re.MULTILINE)
if not enabled_match:
    insert = f"  enabled:\n    - {plugin_name}\n"
    new_content = content[:plugins_block_end] + insert + content[plugins_block_end:]
    path.write_text(new_content, encoding="utf-8")
    print(f"✓ Added enabled: list under plugins: in {path}")
    raise SystemExit(0)

indent = enabled_match.group(1)
list_item_indent = indent + "  "
enabled_line_end_in_block = enabled_match.end()
enabled_line_end_abs = plugins_match.end() + enabled_line_end_in_block
new_content = (
    content[:enabled_line_end_abs]
    + f"\n{list_item_indent}- {plugin_name}"
    + content[enabled_line_end_abs:]
)
path.write_text(new_content, encoding="utf-8")
print(f"✓ Added {plugin_name} to plugins.enabled in {path}")
PY
fi

# Restart the gateway so the long-running gateway process reloads the new
# plugin. Fresh CLI sessions pick up the plugin themselves; the gateway does
# not. Best-effort — missing `hermes` CLI or a non-running gateway is fine,
# we just tell the operator.
if ${DRY_RUN}; then
  echo "[dry-run] hermes gateway restart"
elif ${NO_RESTART}; then
  echo "ℹ Skipped 'hermes gateway restart' (--no-restart). Restart manually for"
  echo "  gateway-served sessions (Telegram, Slack, ACP) to pick up the plugin."
else
  if command -v hermes >/dev/null 2>&1; then
    if hermes gateway restart >/dev/null 2>&1; then
      echo "✓ Restarted Hermes gateway — classifier plugin is live."
    else
      echo "ℹ 'hermes gateway restart' did not succeed (gateway not running?)."
      echo "  Restart it manually for gateway-served sessions to load the plugin:"
      echo "    hermes gateway restart"
    fi
  else
    echo "ℹ 'hermes' CLI not found on PATH; skipped gateway restart."
  fi
fi

if ${DRY_RUN}; then
  echo ""
  echo "(dry-run — nothing was changed)"
else
  echo ""
  echo "✅ revenium-classifier plugin installed and enabled."
  echo "   Source:  ${PLUGIN_SRC}"
  echo "   Target:  ${PLUGIN_DEST}"
  echo "   Config:  ${HOOKS_CONFIG_FILE}"
  echo ""
  echo "Next: start a new Hermes session — every session-end will write a"
  echo "      kind:\"job\" marker, picked up by the next cron tick and shipped"
  echo "      to Revenium as an agentic-job outcome."
fi
