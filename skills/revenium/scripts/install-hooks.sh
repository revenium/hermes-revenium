#!/usr/bin/env bash
set -euo pipefail
# install-hooks.sh — idempotently register revenium shell hooks in ${HOOKS_CONFIG_FILE}.
# Mirrors install-cron.sh: backs up config first, patches with a stdlib-only Python
# re-based heredoc (no PyYAML), and is a no-op on re-run (D-01, D-02).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

# Argument parsing.
#   --auto-accept    BUG-6: set `hooks_auto_accept: true` at the top level of the
#                    target profile's config.yaml. REQUIRED for gateway-served
#                    profiles: headless gateways never show the interactive
#                    approval prompt, so registered hooks stay INERT (and
#                    tool-event capture silently never happens) until this is set.
#   --metering-only  BUG-6: install ONLY the post_tool_call hook (tool-event
#                    capture). In shadow/metering-only mode the two pre_* hooks
#                    are inert overhead that still fire on every LLM/tool call.
#   --all-profiles   Register hooks in the default home AND every
#                    ~/.hermes/profiles/<name>/ config.yaml.
#   --profile <name> Register hooks for the named profile only (repeatable).
AUTO_ACCEPT=false
METERING_ONLY=false
ALL_PROFILES=false
SELECTED_PROFILES=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --auto-accept) AUTO_ACCEPT=true; shift ;;
    --metering-only) METERING_ONLY=true; shift ;;
    --all-profiles) ALL_PROFILES=true; shift ;;
    --profile) SELECTED_PROFILES+=("${2:?--profile requires a name}"); shift 2 ;;
    --profile=*) SELECTED_PROFILES+=("${1#--profile=}"); shift ;;
    -h|--help)
      cat <<USAGE
Usage: install-hooks.sh [--auto-accept] [--metering-only]
                        [--all-profiles | --profile <name> ...]

Registers the revenium pre_llm_call / pre_tool_call / post_tool_call shell hooks
in the target profile's config.yaml. Idempotent.

  --auto-accept    Set hooks_auto_accept: true (REQUIRED for headless gateways —
                   they never show the approval prompt, so hooks stay inert).
  --metering-only  Install only post_tool_call (tool-event capture); skip the two
                   pre_* enforcement hooks (inert overhead in metering-only mode).
  --all-profiles   Apply to the default home and every ~/.hermes/profiles/<name>/.
  --profile <name> Apply to the named profile only (repeatable).
USAGE
      exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; echo "Run with --help for usage." >&2; exit 1 ;;
  esac
done

# BUG-6 fleet dispatch: re-exec per profile home with HERMES_HOME set so each
# profile's own config.yaml is patched (and, with --auto-accept, gets the flag).
if { [[ "${ALL_PROFILES}" == "true" ]] || (( ${#SELECTED_PROFILES[@]} > 0 )); } \
   && [[ "${REVENIUM_HOOKS_FLEET_CHILD:-}" != "1" ]]; then
  child_flags=()
  ${AUTO_ACCEPT} && child_flags+=(--auto-accept)
  ${METERING_ONLY} && child_flags+=(--metering-only)
  rc=0
  matched=0
  while IFS=$'\t' read -r pname phome; do
    [[ -z "${pname}" ]] && continue
    if (( ${#SELECTED_PROFILES[@]} > 0 )); then
      want=false
      for w in "${SELECTED_PROFILES[@]}"; do [[ "${w}" == "${pname}" ]] && want=true; done
      ${want} || continue
    fi
    echo "▸ Hooks for profile '${pname}' → ${phome}"
    REVENIUM_HOOKS_FLEET_CHILD=1 \
    HERMES_HOME="${phome}" \
    REVENIUM_STATE_DIR="${phome}/state/revenium" \
    REVENIUM_HOOKS_CONFIG_FILE="${phome}/config.yaml" \
      bash "${BASH_SOURCE[0]}" "${child_flags[@]}" || rc=1
    matched=$((matched + 1))
  done < <(hermes_profile_homes)
  (( matched == 0 )) && { echo "ERROR: no matching profiles found." >&2; exit 1; }
  exit "${rc}"
fi

# BUG-6: set hooks_auto_accept: true at the top level of config.yaml. Idempotent,
# stdlib-only (no PyYAML). Headless/gateway-served profiles never show the
# interactive approval prompt, so without this the registered hooks stay inert.
apply_auto_accept() {
  mkdir -p "$(dirname "${HOOKS_CONFIG_FILE}")"
  CONFIG_YAML="${HOOKS_CONFIG_FILE}" python3 - <<'PYEOF'
import os
import re
from pathlib import Path

path = Path(os.environ['CONFIG_YAML'])
if not path.exists():
    path.write_text("hooks_auto_accept: true\n", encoding="utf-8")
    print("✓ Created " + str(path) + " with hooks_auto_accept: true")
    raise SystemExit(0)

content = path.read_text(encoding="utf-8")
m = re.search(r"^(hooks_auto_accept:).*$", content, re.MULTILINE)
if m:
    new = content[:m.start()] + "hooks_auto_accept: true" + content[m.end():]
    if new != content:
        path.write_text(new, encoding="utf-8")
        print("✓ Set hooks_auto_accept: true in " + str(path))
    else:
        print("✓ hooks_auto_accept already true in " + str(path))
    raise SystemExit(0)
if not content.endswith("\n"):
    content += "\n"
content += "hooks_auto_accept: true\n"
path.write_text(content, encoding="utf-8")
print("✓ Added hooks_auto_accept: true to " + str(path))
PYEOF
}

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

# BUG-6: apply hooks_auto_accept BEFORE the fast-path so an already-registered
# install still gets the flag set (headless gateways need it regardless of
# whether the hook commands are already present).
if ${AUTO_ACCEPT}; then
  mkdir -p "${HERMES_HOME}"
  apply_auto_accept
fi

# Idempotency check — re-run is a no-op (D-01, CR-01).
# Key the fast-path on whether the required revenium command paths are already
# present, NOT on a bare HOOK_TAG grep — a stale HOOK_TAG without the commands
# must NOT short-circuit the install. In --metering-only mode only post_tool_call
# is required (the two pre_* hooks are intentionally not installed).
present=true
if ! grep -qF "${POST_TOOL_SCRIPT}" "${HOOKS_CONFIG_FILE}" 2>/dev/null; then present=false; fi
if ! ${METERING_ONLY}; then
  grep -qF "${PRE_LLM_SCRIPT}" "${HOOKS_CONFIG_FILE}" 2>/dev/null || present=false
  grep -qF "${PRE_TOOL_SCRIPT}" "${HOOKS_CONFIG_FILE}" 2>/dev/null || present=false
fi
if ${present}; then
  echo "Revenium hooks already registered in ${HOOKS_CONFIG_FILE}"
  if ${AUTO_ACCEPT}; then
    echo "✓ hooks_auto_accept enabled — hooks fire without an approval prompt (gateway-ready)."
  else
    # Print the banner even on the no-op fast-path. Most operators run
    # install-hooks.sh expecting the loud reminder; suppressing it because
    # the registration is already done was misleading.
    sed -e "s|SCRIPT_DIR|${SCRIPT_DIR}|g" < <(print_approval_banner)
  fi
  exit 0
fi

# Create parent directory if needed (first-time install on a bare system).
mkdir -p "${HERMES_HOME}"

# Backup before modifying (T-12-07 mitigation — Pitfall 3).
if [[ -f "${HOOKS_CONFIG_FILE}" ]]; then
  cp "${HOOKS_CONFIG_FILE}" "${HOOKS_CONFIG_FILE}.bak.$(date +%s)"
fi

# Patch config.yaml with a stdlib-only re-based Python heredoc (no PyYAML).
# Mirrors the proven approach in install.sh lines 49-119.
# Receives config path, hook script paths, and HOOK_TAG via argv.
HOOKS_CONFIG_FILE="${HOOKS_CONFIG_FILE}" \
PRE_LLM_SCRIPT="${PRE_LLM_SCRIPT}" \
PRE_TOOL_SCRIPT="${PRE_TOOL_SCRIPT}" \
POST_TOOL_SCRIPT="${POST_TOOL_SCRIPT}" \
HOOK_TAG="${HOOK_TAG}" \
METERING_ONLY="${METERING_ONLY}" \
python3 - <<'PYEOF'
import os
import re
from pathlib import Path

config_path = Path(os.environ['HOOKS_CONFIG_FILE'])
pre_llm = os.environ['PRE_LLM_SCRIPT']
pre_tool = os.environ['PRE_TOOL_SCRIPT']
post_tool = os.environ['POST_TOOL_SCRIPT']
hook_tag = os.environ['HOOK_TAG']
# BUG-6: metering-only installs register ONLY post_tool_call (tool-event capture).
metering_only = os.environ.get('METERING_ONLY', 'false') == 'true'

# The hooks block to insert — no matcher: field (fires for ALL tools). In
# metering-only mode only post_tool_call is written.
_pre_block = "" if metering_only else (
    "  pre_llm_call:\n"
    "    - command: " + pre_llm + "\n"
    "      timeout: 5\n"
    "  pre_tool_call:\n"
    "    - command: " + pre_tool + "\n"
    "      timeout: 5\n"
)
hooks_block = (
    "hooks:\n"
    + _pre_block +
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

if not metering_only and not pre_llm_present:
    patched = insert_command_under_key(new_hooks, "pre_llm_call", pre_llm)
    if patched is not None:
        new_hooks = patched
        status.append("Added pre_llm_call revenium command under existing pre_llm_call key")
    else:
        new_hooks = new_hooks + full_event_key("pre_llm_call", pre_llm)
        status.append("Added pre_llm_call key and revenium command to hooks block")

if not metering_only and not pre_tool_present:
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
both_present = bool(re.search(re.escape(post_tool), final_hooks)) and (
    metering_only or (
        bool(re.search(re.escape(pre_llm), final_hooks))
        and bool(re.search(re.escape(pre_tool), final_hooks))
    )
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

if ${METERING_ONLY}; then
  chmod +x "${POST_TOOL_SCRIPT}"
  echo "Revenium hooks installed in ${HOOKS_CONFIG_FILE} (metering-only)"
  echo "   post_tool_call: ${POST_TOOL_SCRIPT}"
else
  chmod +x "${PRE_LLM_SCRIPT}" "${PRE_TOOL_SCRIPT}" "${POST_TOOL_SCRIPT}"
  echo "Revenium hooks installed in ${HOOKS_CONFIG_FILE}"
  echo "   pre_llm_call:   ${PRE_LLM_SCRIPT}"
  echo "   pre_tool_call:  ${PRE_TOOL_SCRIPT}"
  echo "   post_tool_call: ${POST_TOOL_SCRIPT}"
fi

# BUG-6: when auto-accept is set the hooks fire without an approval prompt, so the
# "inert until approved" banner does not apply. Otherwise print it loud and last.
if ${AUTO_ACCEPT}; then
  echo "✓ hooks_auto_accept enabled — hooks fire without an approval prompt (gateway-ready)."
else
  sed -e "s|SCRIPT_DIR|${SCRIPT_DIR}|g" < <(print_approval_banner)
fi

echo "To uninstall: bash ${SKILL_DIR}/scripts/uninstall-hooks.sh"
