#!/usr/bin/env bash
set -euo pipefail
# uninstall-hooks.sh — remove revenium shell hook entries from ~/.hermes/config.yaml.
# Mirrors uninstall-cron.sh: no-op when hooks are absent, backs up before modifying.
# Sources common.sh (unlike uninstall-cron.sh) because it needs HERMES_HOME / HOOKS_CONFIG_FILE.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

HOOK_TAG="# hermes-revenium-hooks"

if ! grep -q "${HOOK_TAG}" "${HOOKS_CONFIG_FILE}" 2>/dev/null; then
  echo "No Revenium hooks found in ${HOOKS_CONFIG_FILE}."
  exit 0
fi

# Backup before modifying.
cp "${HOOKS_CONFIG_FILE}" "${HOOKS_CONFIG_FILE}.bak.$(date +%s)"

# Remove revenium hook entries and the HOOK_TAG comment via stdlib-only Python heredoc.
HOOKS_CONFIG_FILE="${HOOKS_CONFIG_FILE}" \
HOOK_TAG="${HOOK_TAG}" \
python3 - <<'PYEOF'
import os
import re
from pathlib import Path

config_path = Path(os.environ['HOOKS_CONFIG_FILE'])
hook_tag = os.environ['HOOK_TAG']

content = config_path.read_text(encoding="utf-8")

# Remove the HOOK_TAG comment line.
content = re.sub(r"^" + re.escape(hook_tag) + r"\s*\n?", "", content, flags=re.MULTILINE)

# Remove revenium hook entries under pre_llm_call:, pre_tool_call:, post_tool_call:.
# Strategy: remove any list item (  - command: ...) whose command path is one
# of the revenium hook scripts (pre_llm_call.sh / pre_tool_call.sh /
# post_tool_call.sh), and then remove any hook event key (pre_llm_call:,
# pre_tool_call:, post_tool_call:) that ends up empty.
# WR-01: anchor on the hook SCRIPT PATH, not the bare substring 'revenium' — an
# unrelated command containing 'revenium' (e.g. /usr/bin/revenium-other-hook)
# must NOT be removed.
def remove_revenium_list_items(text):
    # Match a hook event key line (e.g., "  pre_llm_call:") followed by list items.
    # Remove list item blocks whose command path is a revenium hook script.
    lines = text.split("\n")
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Check if this is a revenium hook list item opener:
        # "    - command: .../scripts/pre_llm_call.sh" (or pre_tool_call.sh).
        if (re.match(r"^\s+-\s+command:", line)
                and re.search(r"scripts/(pre_llm_call|pre_tool_call|post_tool_call)\.sh\b", line)):
            # Skip this item: consume all continuation lines (deeper indented or empty).
            base_indent = len(line) - len(line.lstrip())
            i += 1
            while i < len(lines):
                next_line = lines[i]
                if next_line.strip() == "":
                    break
                next_indent = len(next_line) - len(next_line.lstrip())
                if next_indent <= base_indent:
                    break
                i += 1
            continue
        result.append(line)
        i += 1
    return "\n".join(result)

content = remove_revenium_list_items(content)

# Remove any now-empty hook event keys under hooks: block.
# An empty key looks like "  pre_llm_call:\n" immediately followed by the next key
# or end of the hooks block (no indented list items below it).
def remove_empty_hook_keys(text):
    lines = text.split("\n")
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Detect a hook event key like "  pre_llm_call:" or "  pre_tool_call:"
        m = re.match(r"^(\s+)(pre_llm_call|pre_tool_call|post_tool_call):\s*$", line)
        if m:
            # Look ahead: if the next non-blank line has the same or less indentation,
            # this key has no children — skip it.
            indent = len(m.group(1))
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j >= len(lines):
                # EOF after this key — skip it
                i += 1
                continue
            next_line = lines[j]
            next_indent = len(next_line) - len(next_line.lstrip())
            if next_indent <= indent:
                # Empty key — skip
                i += 1
                continue
        result.append(line)
        i += 1
    return "\n".join(result)

content = remove_empty_hook_keys(content)

# Clean up any hooks: block that is now completely empty (just "hooks:\n" with nothing).
content = re.sub(r"^hooks:\s*\n(?=\S|\Z)", "", content, flags=re.MULTILINE)

config_path.write_text(content, encoding="utf-8")
print("Revenium hook entries removed from " + str(config_path))
PYEOF

echo "Revenium hooks removed from ${HOOKS_CONFIG_FILE}."
