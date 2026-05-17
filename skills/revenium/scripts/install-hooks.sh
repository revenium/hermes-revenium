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

# Idempotency check — re-run is a no-op (D-01, CR-01).
# Key the fast-path on whether BOTH revenium command paths are already present,
# NOT on a bare HOOK_TAG grep — a stale HOOK_TAG without the commands must NOT
# short-circuit the install.
if grep -qF "${PRE_LLM_SCRIPT}" "${HOOKS_CONFIG_FILE}" 2>/dev/null \
   && grep -qF "${PRE_TOOL_SCRIPT}" "${HOOKS_CONFIG_FILE}" 2>/dev/null; then
  echo "Revenium hooks already registered in ${HOOKS_CONFIG_FILE}"
  exit 0
fi

# Create parent directory if needed (first-time install on a bare system).
mkdir -p "${HERMES_HOME}"

# Backup before modifying (T-12-07 mitigation — Pitfall 3).
if [[ -f "${HOOKS_CONFIG_FILE}" ]]; then
  cp "${HOOKS_CONFIG_FILE}" "${HOOKS_CONFIG_FILE}.bak.$(date +%s)"
fi

# Patch config.yaml with a stdlib-only re-based Python heredoc (no PyYAML).
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


def hooks_block_extent(text):
    """Locate the hooks: block. Returns (match, start, end) or None."""
    m = re.search(r"^hooks:\s*$", text, re.MULTILINE)
    if not m:
        return None
    after = text[m.end():]
    next_top = re.search(r"^[^\s#]", after, re.MULTILINE)
    end = (m.end() + next_top.start()) if next_top else len(text)
    return (m, m.end(), end)


def insert_command_under_key(hooks_text, event_key, command_path):
    """Insert a revenium `- command:` list item under an existing event key.

    Indentation: list-item indent = key indent + 2 spaces; command:/timeout:
    nested another 2 spaces. The foreign hook's existing entries are left
    untouched — we insert immediately after the event-key line, never replace.
    Returns the modified hooks_text, or None if the event key is absent.
    """
    # Anchor the indent capture to horizontal whitespace only ([^\S\n] =
    # whitespace except newline) so group(1) cannot swallow the leading
    # newline of the hooks-block slice. With a bare \s*, the MULTILINE ^
    # at offset 0 of `existing_hooks` (which always starts with the \n
    # after `hooks:`) would capture "\n  " and inject stray blank lines
    # into the rewritten YAML (CR-01).
    km = re.search(r"^([^\S\n]*)" + re.escape(event_key) + r":[^\S\n]*$",
                   hooks_text, re.MULTILINE)
    if not km:
        return None
    key_indent = km.group(1)
    item_indent = key_indent + "  "
    entry = (
        item_indent + "- command: " + command_path + "\n"
        + item_indent + "  timeout: 5\n"
    )
    insert_at = km.end() + 1  # just past the event-key line's newline
    return hooks_text[:insert_at] + entry + hooks_text[insert_at:]


def full_event_key(event_key, command_path):
    """A complete `  pre_*_call:` key plus its revenium command entry."""
    return (
        "  " + event_key + ":\n"
        "    - command: " + command_path + "\n"
        "      timeout: 5\n"
    )


extent = hooks_block_extent(content)
if extent is None:
    # No hooks: key present — append the entire block at end of file.
    if not content.endswith("\n"):
        content += "\n"
    content += "\n" + hooks_block
    config_path.write_text(content, encoding="utf-8")
    print("Appended hooks block to " + str(config_path))
    raise SystemExit(0)

# hooks: key is present — patch revenium commands into the existing block.
_, hooks_start, hooks_end = extent
existing_hooks = content[hooks_start:hooks_end]

# Determine presence of each revenium command INDEPENDENTLY by command path,
# never by branching on the pre_llm_call: / pre_tool_call: event-key names.
pre_llm_present = bool(re.search(re.escape(pre_llm), existing_hooks))
pre_tool_present = bool(re.search(re.escape(pre_tool), existing_hooks))

new_hooks = existing_hooks
status = []

if not pre_llm_present:
    patched = insert_command_under_key(new_hooks, "pre_llm_call", pre_llm)
    if patched is not None:
        new_hooks = patched
        status.append("Added pre_llm_call revenium command under existing pre_llm_call key")
    else:
        new_hooks = new_hooks + full_event_key("pre_llm_call", pre_llm)
        status.append("Added pre_llm_call key and revenium command to hooks block")

if not pre_tool_present:
    patched = insert_command_under_key(new_hooks, "pre_tool_call", pre_tool)
    if patched is not None:
        new_hooks = patched
        status.append("Added pre_tool_call revenium command under existing pre_tool_call key")
    else:
        new_hooks = new_hooks + full_event_key("pre_tool_call", pre_tool)
        status.append("Added pre_tool_call key and revenium command to hooks block")

new_content = content[:hooks_start] + new_hooks + content[hooks_end:]

# Write the HOOK_TAG ONLY when both revenium commands are now present in the
# resulting hooks block, and never a second copy if one already exists.
final_extent = hooks_block_extent(new_content)
final_hooks = new_content[final_extent[1]:final_extent[2]]
both_present = (
    bool(re.search(re.escape(pre_llm), final_hooks))
    and bool(re.search(re.escape(pre_tool), final_hooks))
)
if both_present and not re.search(
        r"^" + re.escape(hook_tag) + r"\s*$", new_content, re.MULTILINE):
    if not new_content.endswith("\n"):
        new_content += "\n"
    new_content += hook_tag + "\n"

config_path.write_text(new_content, encoding="utf-8")
if status:
    for line in status:
        print(line)
else:
    print("Revenium hooks already present in " + str(config_path))
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
