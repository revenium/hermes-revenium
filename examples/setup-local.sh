#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${HOME}/.hermes/skills/revenium"

mkdir -p "${HOME}/.hermes/skills"
rm -rf "${TARGET_DIR}"
cp -R "${REPO_ROOT}/skills/revenium" "${TARGET_DIR}"
# Prune the stale hooks/ tree from the bulk skill copy — superseded by plugins/ (06-02 / G-01 closure).
rm -rf "${TARGET_DIR}/hooks"
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
# `hermes skills install` does NOT relocate plugins/ subdirs; setup-local does the copy.
PLUGINS_DIR="${HOME}/.hermes/plugins"
PLUGIN_TARGET="${PLUGINS_DIR}/revenium-classifier"
mkdir -p "${PLUGINS_DIR}"
rm -rf "${PLUGIN_TARGET}"
cp -R "${REPO_ROOT}/skills/revenium/plugins/revenium-classifier" "${PLUGIN_TARGET}"
echo "Installed plugin to ${PLUGIN_TARGET}"

# Idempotently enable the plugin in ~/.hermes/config.yaml using a stdlib-only Python
# heredoc (CLAUDE.md: no PyYAML; `re`-based regex manipulation only). If config.yaml
# does NOT exist, create a minimal one with the plugins.enabled block. If it exists,
# patch the existing block in place; if `plugins:` or `enabled:` are missing, append
# the block at end of file. Idempotent on second run (no-op when already present).
CONFIG_YAML="${HOME}/.hermes/config.yaml"
mkdir -p "${HOME}/.hermes"
CONFIG_YAML="${CONFIG_YAML}" python3 - <<'PY'
import os
import re
from pathlib import Path

path = Path(os.environ['CONFIG_YAML'])
plugin_name = "revenium-classifier"

if not path.exists():
    # Pattern B: create a minimal config with the plugins block. Operator can extend.
    path.write_text(
        "plugins:\n"
        "  enabled:\n"
        f"    - {plugin_name}\n",
        encoding="utf-8",
    )
    print(f"Created {path} with plugins.enabled containing {plugin_name}")
    raise SystemExit(0)

content = path.read_text(encoding="utf-8")

# Detect whether plugin is already enabled — look for a list item under plugins.enabled.
# Be lenient: accept any "- revenium-classifier" line with any leading indentation.
if re.search(r"^\s*-\s*" + re.escape(plugin_name) + r"\s*$", content, re.MULTILINE):
    print(f"{plugin_name} already enabled in {path}")
    raise SystemExit(0)

# Find the plugins: block — top-level key only (no leading whitespace).
plugins_match = re.search(r"^plugins:\s*$", content, re.MULTILINE)
if not plugins_match:
    # plugins: block absent — append a new block at end of file.
    if not content.endswith("\n"):
        content += "\n"
    content += f"plugins:\n  enabled:\n    - {plugin_name}\n"
    path.write_text(content, encoding="utf-8")
    print(f"Added plugins.enabled block to {path}")
    raise SystemExit(0)

# plugins: block present — find an enabled: child within it.
# Scope: lines from plugins_match.end() until the next top-level key (^[^\s]) or EOF.
after_plugins = content[plugins_match.end():]
# Find next top-level key (line with no leading whitespace, not blank, not comment).
next_top_match = re.search(r"^[^\s#]", after_plugins, re.MULTILINE)
plugins_block_end = (plugins_match.end() + next_top_match.start()) if next_top_match else len(content)
plugins_block = content[plugins_match.end():plugins_block_end]

# Look for "  enabled:" or "  enabled: []" inside the plugins block.
enabled_match = re.search(r"^(\s+)enabled:(.*)$", plugins_block, re.MULTILINE)
if not enabled_match:
    # plugins: block has no enabled: child — append one before the next top-level key.
    insert = f"  enabled:\n    - {plugin_name}\n"
    new_content = content[:plugins_block_end] + insert + content[plugins_block_end:]
    path.write_text(new_content, encoding="utf-8")
    print(f"Added enabled: list under plugins: in {path}")
    raise SystemExit(0)

# enabled: present — append the plugin to its list.
indent = enabled_match.group(1)  # leading whitespace of the enabled: line (e.g., "  ")
list_item_indent = indent + "  "  # one level deeper for list items
# Insert position: end of the enabled: line's segment within plugins_block.
enabled_line_end_in_block = enabled_match.end()
# Translate to absolute position in `content`.
enabled_line_end_abs = plugins_match.end() + enabled_line_end_in_block
new_content = (
    content[:enabled_line_end_abs]
    + f"\n{list_item_indent}- {plugin_name}"
    + content[enabled_line_end_abs:]
)
path.write_text(new_content, encoding="utf-8")
print(f"Added {plugin_name} to plugins.enabled in {path}")
PY

# Phase 12 (D-02): register pre_llm_call / pre_tool_call shell hooks in config.yaml.
# Guard with || true so a hooks-install hiccup does not abort the whole local setup.
bash "${TARGET_DIR}/scripts/install-hooks.sh" || true

echo "Installed skill to ${TARGET_DIR}"
echo ""
echo "Next steps:"
echo "  1. Verify Revenium CLI: revenium config show"
echo "  2. Install cron: bash ~/.hermes/skills/revenium/scripts/install-cron.sh"
echo "  3. Restart Hermes gateway to load the classifier plugin: hermes gateway restart"
echo "  4. Start Hermes ('hermes chat') and approve the revenium hooks when prompted."
echo "     The hooks are registered but inert until you approve them on first use (D-03)."
