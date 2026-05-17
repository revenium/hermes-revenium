#!/usr/bin/env bash
set -euo pipefail
# install-hooks.sh — idempotently register revenium shell hooks in ~/.hermes/config.yaml.
# Mirrors install-cron.sh: backs up config first, patches with a stdlib-only Python
# re-based heredoc (no PyYAML), and is a no-op on re-run (D-01, D-02).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

HOOK_TAG="# hermes-revenium-hooks"
PRE_LLM_SCRIPT="${SKILL_DIR}/scripts/pre_llm_call.sh"
PRE_TOOL_SCRIPT="${SKILL_DIR}/scripts/pre_tool_call.sh"

# Idempotency check — re-run is a no-op (D-01).
if grep -q "${HOOK_TAG}" "${HOOKS_CONFIG_FILE}" 2>/dev/null; then
  echo "Revenium hooks already registered in ${HOOKS_CONFIG_FILE}"
  exit 0
fi

# Create parent directory if needed (first-time install on a bare system).
mkdir -p "${HERMES_HOME}"

# Backup before modifying (T-12-07 mitigation — Pitfall 3).
if [[ -f "${HOOKS_CONFIG_FILE}" ]]; then
  cp "${HOOKS_CONFIG_FILE}" "${HOOKS_CONFIG_FILE}.bak.$(date +%s)"
fi

# Patch config.yaml with a stdlib-only re-based Python heredoc — do NOT import yaml.
# Mirrors the proven approach in setup-local.sh lines 49-119.
# Receives config path, pre_llm script path, pre_tool script path, and HOOK_TAG via argv.
HOOKS_CONFIG_FILE="${HOOKS_CONFIG_FILE}" \
PRE_LLM_SCRIPT="${PRE_LLM_SCRIPT}" \
PRE_TOOL_SCRIPT="${PRE_TOOL_SCRIPT}" \
HOOK_TAG="${HOOK_TAG}" \
python3 - <<'PYEOF'
import os
import re
from pathlib import Path

config_path = Path(os.environ['HOOKS_CONFIG_FILE'])
pre_llm = os.environ['PRE_LLM_SCRIPT']
pre_tool = os.environ['PRE_TOOL_SCRIPT']
hook_tag = os.environ['HOOK_TAG']

# The hooks block to insert — two entries, no matcher: field (fires for ALL tools).
hooks_block = (
    "hooks:\n"
    "  pre_llm_call:\n"
    "    - command: " + pre_llm + "\n"
    "      timeout: 5\n"
    "  pre_tool_call:\n"
    "    - command: " + pre_tool + "\n"
    "      timeout: 5\n"
    + hook_tag + "\n"
)

if not config_path.exists():
    # No config.yaml yet — create a minimal one with just the hooks block.
    config_path.write_text(hooks_block, encoding="utf-8")
    print("Created " + str(config_path) + " with hooks block")
    raise SystemExit(0)

content = config_path.read_text(encoding="utf-8")

# Detect whether a hooks: block is already present.
hooks_match = re.search(r"^hooks:\s*$", content, re.MULTILINE)
if not hooks_match:
    # No hooks: key present — append the entire block at end of file (format-preserving).
    if not content.endswith("\n"):
        content += "\n"
    content += "\n" + hooks_block
    config_path.write_text(content, encoding="utf-8")
    print("Appended hooks block to " + str(config_path))
    raise SystemExit(0)

# hooks: key is present — find its extent (until next top-level key or EOF).
after_hooks = content[hooks_match.end():]
next_top_match = re.search(r"^[^\s#]", after_hooks, re.MULTILINE)
hooks_block_end = (hooks_match.end() + next_top_match.start()) if next_top_match else len(content)
existing_hooks = content[hooks_match.end():hooks_block_end]

# Check if pre_llm_call already present under hooks.
if re.search(r"^\s*pre_llm_call:", existing_hooks, re.MULTILINE):
    # pre_llm_call already present — append pre_tool_call only if absent.
    if not re.search(r"^\s*pre_tool_call:", existing_hooks, re.MULTILINE):
        insert = (
            "  pre_tool_call:\n"
            "    - command: " + pre_tool + "\n"
            "      timeout: 5\n"
        )
        new_content = content[:hooks_block_end] + insert + content[hooks_block_end:]
        if not new_content.endswith("\n"):
            new_content += "\n"
        new_content += hook_tag + "\n"
        config_path.write_text(new_content, encoding="utf-8")
        print("Added pre_tool_call hook to existing hooks block in " + str(config_path))
    else:
        # Both present — just append the tag.
        if not content.endswith("\n"):
            content += "\n"
        content += hook_tag + "\n"
        config_path.write_text(content, encoding="utf-8")
        print("Annotated existing hooks block in " + str(config_path))
    raise SystemExit(0)

# hooks: present but no pre_llm_call — insert our two entries into the hooks block.
pre_llm_entry = (
    "  pre_llm_call:\n"
    "    - command: " + pre_llm + "\n"
    "      timeout: 5\n"
)
pre_tool_entry = (
    "  pre_tool_call:\n"
    "    - command: " + pre_tool + "\n"
    "      timeout: 5\n"
)
insert = pre_llm_entry + pre_tool_entry
new_content = content[:hooks_block_end] + insert + content[hooks_block_end:]
if not new_content.endswith("\n"):
    new_content += "\n"
new_content += hook_tag + "\n"
config_path.write_text(new_content, encoding="utf-8")
print("Added pre_llm_call and pre_tool_call hooks to " + str(config_path))
PYEOF

chmod +x "${PRE_LLM_SCRIPT}" "${PRE_TOOL_SCRIPT}"

echo "Revenium hooks installed in ${HOOKS_CONFIG_FILE}"
echo "   pre_llm_call:  ${PRE_LLM_SCRIPT}"
echo "   pre_tool_call: ${PRE_TOOL_SCRIPT}"
echo ""
echo "Next step: run 'hermes chat' and approve the revenium hooks when prompted (D-03)."
echo "   Hooks are registered but inert until the user approves them on first use."
echo ""
echo "To uninstall: bash ${SKILL_DIR}/scripts/uninstall-hooks.sh"
