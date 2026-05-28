#!/usr/bin/env bash
set -euo pipefail
# install-hooks.sh — idempotently register revenium shell hooks in ${HOOKS_CONFIG_FILE}.
# Mirrors install-cron.sh: backs up config first, patches with a stdlib-only Python
# re-based heredoc (no PyYAML), and is a no-op on re-run (D-01, D-02).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

HOOK_TAG="# hermes-revenium-hooks"
PRE_LLM_SCRIPT="${SKILL_DIR}/scripts/pre_llm_call.sh"
PRE_TOOL_SCRIPT="${SKILL_DIR}/scripts/pre_tool_call.sh"
POST_TOOL_SCRIPT="${SKILL_DIR}/scripts/post_tool_call.sh"

# Loud, always-printed approval banner. Registered hooks are inert until the
# user accepts them on first `hermes chat` — that footgun has bitten more than
# one operator (Ubuntu sandbox 2026-05-19 had every hook registered but never
# fired, silently zeroing tool-event capture for the entire session). We
# print this on every run (fast-path and slow-path) so the requirement is
# impossible to miss.
print_approval_banner() {
  cat <<'BANNER'

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  IMPORTANT — hooks are INERT until you approve them in a Hermes chat session

  Hermes' default `approvals.mode: manual` + `hooks_auto_accept: false` means
  the three revenium hooks registered here (pre_llm_call, pre_tool_call,
  post_tool_call) are written to config.yaml but DO NOT fire until you start
  `hermes chat` and accept the approval prompt for each one.

  Until that happens:
    • the budget halt is NOT structurally enforced (SKILL.md backstop only)
    • tool-events/ stays empty, so the tool-event ledger never fills, so
      tool-usage analytics never reach Revenium even with the cron running.

  Diagnose anytime with:
    bash SCRIPT_DIR/hooks-status.sh

  If you want to skip the per-install approval prompt entirely, set
  `hooks_auto_accept: true` at the top level of the Hermes hook configuration.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BANNER
}

# Idempotency check — re-run is a no-op (D-01, CR-01).
# Key the fast-path on whether ALL revenium command paths are already present,
# NOT on a bare HOOK_TAG grep — a stale HOOK_TAG without the commands must NOT
# short-circuit the install.
if grep -qF "${PRE_LLM_SCRIPT}" "${HOOKS_CONFIG_FILE}" 2>/dev/null \
   && grep -qF "${PRE_TOOL_SCRIPT}" "${HOOKS_CONFIG_FILE}" 2>/dev/null \
   && grep -qF "${POST_TOOL_SCRIPT}" "${HOOKS_CONFIG_FILE}" 2>/dev/null; then
  echo "Revenium hooks already registered in ${HOOKS_CONFIG_FILE}"
  # Print the banner even on the no-op fast-path. Most operators run
  # install-hooks.sh expecting the loud reminder; suppressing it because
  # the registration is already done was misleading.
  sed -e "s|SCRIPT_DIR|${SCRIPT_DIR}|g" < <(print_approval_banner)
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
# Receives config path, hook script paths, and HOOK_TAG via argv.
HOOKS_CONFIG_FILE="${HOOKS_CONFIG_FILE}" \
PRE_LLM_SCRIPT="${PRE_LLM_SCRIPT}" \
PRE_TOOL_SCRIPT="${PRE_TOOL_SCRIPT}" \
POST_TOOL_SCRIPT="${POST_TOOL_SCRIPT}" \
HOOK_TAG="${HOOK_TAG}" \
python3 - <<'PYEOF'
import os
import re
from pathlib import Path

config_path = Path(os.environ['HOOKS_CONFIG_FILE'])
pre_llm = os.environ['PRE_LLM_SCRIPT']
pre_tool = os.environ['PRE_TOOL_SCRIPT']
post_tool = os.environ['POST_TOOL_SCRIPT']
hook_tag = os.environ['HOOK_TAG']

# The hooks block to insert — three entries, no matcher: field (fires for ALL tools).
hooks_block = (
    "hooks:\n"
    "  pre_llm_call:\n"
    "    - command: " + pre_llm + "\n"
    "      timeout: 5\n"
    "  pre_tool_call:\n"
    "    - command: " + pre_tool + "\n"
    "      timeout: 5\n"
    "  post_tool_call:\n"
    "    - command: " + post_tool + "\n"
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
    """Locate the hooks: block. Returns (match, start, end) or None.

    Matches three forms of a present-but-empty or block-style hooks key:
      hooks:            (bare — already-block-style or empty)
      hooks: {}         (empty flow map — the real host case)
      hooks: []         (empty flow seq — handled for completeness)
    A non-empty inline map/seq is NOT matched (out of scope).
    """
    m = re.search(
        r"^hooks:[^\S\n]*(?:\{[^\S\n]*\}|\[[^\S\n]*\])?[^\S\n]*$",
        text, re.MULTILINE,
    )
    if not m:
        return None
    # For inline-empty forms (hooks: {} / hooks: []) the matched span covers
    # the entire `hooks: {}` token on that line.  We normalise the start
    # pointer so that `content[:hooks_start]` always ends just BEFORE the
    # `hooks:` keyword (i.e. at the beginning of that line) and the caller
    # rewrites the whole `hooks:` line as a clean bare `hooks:\n`.
    line_start = text.rfind("\n", 0, m.start()) + 1  # start of the matched line
    after = text[m.end():]
    # Skip any trailing \r or \n that ends the hooks: line so existing_hooks
    # starts cleanly at the first indented line of the block (or is empty).
    eol_skip = len(after) - len(after.lstrip("\r\n"))
    hooks_content_start = m.end() + eol_skip
    next_top = re.search(r"^[^\s#]", after[eol_skip:], re.MULTILINE)
    end = (hooks_content_start + next_top.start()) if next_top else len(text)
    return (m, hooks_content_start, end, line_start)


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
_, hooks_start, hooks_end, line_start = extent
existing_hooks = content[hooks_start:hooks_end]

# Determine presence of each revenium command INDEPENDENTLY by command path,
# never by branching on the pre_llm_call: / pre_tool_call: event-key names.
pre_llm_present = bool(re.search(re.escape(pre_llm), existing_hooks))
pre_tool_present = bool(re.search(re.escape(pre_tool), existing_hooks))
post_tool_present = bool(re.search(re.escape(post_tool), existing_hooks))

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

if not post_tool_present:
    patched = insert_command_under_key(new_hooks, "post_tool_call", post_tool)
    if patched is not None:
        new_hooks = patched
        status.append("Added post_tool_call revenium command under existing post_tool_call key")
    else:
        new_hooks = new_hooks + full_event_key("post_tool_call", post_tool)
        status.append("Added post_tool_call key and revenium command to hooks block")

# Rebuild: replace from the beginning of the `hooks:` line through hooks_end
# so that an inline-empty `hooks: {}` line is rewritten as a bare `hooks:`.
new_content = content[:line_start] + "hooks:\n" + new_hooks + content[hooks_end:]

# Write the HOOK_TAG ONLY when both revenium commands are now present in the
# resulting hooks block, and never a second copy if one already exists.
final_extent = hooks_block_extent(new_content)
final_hooks = new_content[final_extent[1]:final_extent[2]]
both_present = (
    bool(re.search(re.escape(pre_llm), final_hooks))
    and bool(re.search(re.escape(pre_tool), final_hooks))
    and bool(re.search(re.escape(post_tool), final_hooks))
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

chmod +x "${PRE_LLM_SCRIPT}" "${PRE_TOOL_SCRIPT}" "${POST_TOOL_SCRIPT}"

echo "Revenium hooks installed in ${HOOKS_CONFIG_FILE}"
echo "   pre_llm_call:   ${PRE_LLM_SCRIPT}"
echo "   pre_tool_call:  ${PRE_TOOL_SCRIPT}"
echo "   post_tool_call: ${POST_TOOL_SCRIPT}"

# Same banner as the fast-path. Always loud, always last so it stays on screen.
sed -e "s|SCRIPT_DIR|${SCRIPT_DIR}|g" < <(print_approval_banner)

echo "To uninstall: bash ${SKILL_DIR}/scripts/uninstall-hooks.sh"
