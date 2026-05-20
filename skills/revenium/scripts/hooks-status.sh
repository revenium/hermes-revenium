#!/usr/bin/env bash
set -uo pipefail
# hooks-status.sh — diagnose whether the revenium hooks are registered AND firing.
#
# Two-stage check:
#   1. Static: are the three hook commands listed in ~/.hermes/config.yaml?
#   2. Runtime: is tool-events/<sid>.jsonl actually growing? Cross-check
#      against state.db's recent tool messages — if Hermes has been running
#      tools but tool-events/ stays empty, the hooks are registered but
#      not approved/firing (the silent-failure mode that bit Ubuntu).
#
# Exit codes:
#   0  hooks registered AND firing within the last hour
#   1  hooks NOT registered  (operator hasn't run install-hooks.sh yet)
#   2  hooks registered but NOT firing (approval pending, hermes not restarted, etc.)
# These are stable for scripting; the human-readable text may change.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

PRE_LLM_SCRIPT="${SKILL_DIR}/scripts/pre_llm_call.sh"
PRE_TOOL_SCRIPT="${SKILL_DIR}/scripts/pre_tool_call.sh"
POST_TOOL_SCRIPT="${SKILL_DIR}/scripts/post_tool_call.sh"

echo "Revenium hooks status"
echo "─────────────────────"

# --- 1. Static registration check ------------------------------------------
echo
echo "[1] Registration in ${HOOKS_CONFIG_FILE}"
registered_ok=true
for entry in \
  "pre_llm_call:${PRE_LLM_SCRIPT}" \
  "pre_tool_call:${PRE_TOOL_SCRIPT}" \
  "post_tool_call:${POST_TOOL_SCRIPT}"; do
  hook="${entry%%:*}"
  cmd="${entry#*:}"
  if grep -qF "${cmd}" "${HOOKS_CONFIG_FILE}" 2>/dev/null; then
    echo "    ✓ ${hook} → ${cmd}"
  else
    echo "    ✗ ${hook} NOT registered"
    registered_ok=false
  fi
done

if ! ${registered_ok}; then
  echo
  echo "Hooks are not (fully) registered yet. Run:"
  echo "  bash ${SCRIPT_DIR}/install-hooks.sh"
  exit 1
fi

# --- 2. Approval-mode check ------------------------------------------------
echo
echo "[2] Hermes approval mode"
# Read approvals.mode and hooks_auto_accept via a stdlib Python helper —
# common.sh forbids new runtime deps, so no PyYAML. Lenient against blank
# lines or inline-empty maps; absent keys default to documented Hermes
# defaults (manual, false).
read -r approvals_mode auto_accept <<EOF_MODE
$(HOOKS_CONFIG_FILE="${HOOKS_CONFIG_FILE}" python3 - <<'PY' 2>/dev/null || echo "unknown unknown"
import os, re
try:
    content = open(os.environ["HOOKS_CONFIG_FILE"]).read()
except Exception:
    print("unknown unknown"); raise SystemExit(0)

m = re.search(r"^approvals:\s*$", content, re.MULTILINE)
mode = "default"
if m:
    after = content[m.end():]
    nxt = re.search(r"^[^\s#]", after, re.MULTILINE)
    block = after[:nxt.start()] if nxt else after
    mode_m = re.search(r"^\s*mode:\s*(\S+)", block, re.MULTILINE)
    mode = mode_m.group(1) if mode_m else "default"

aa_m = re.search(r"^hooks_auto_accept:\s*(\S+)", content, re.MULTILINE)
aa = aa_m.group(1) if aa_m else "false"
print(f"{mode} {aa}")
PY
)
EOF_MODE
echo "    approvals.mode    = ${approvals_mode}"
echo "    hooks_auto_accept = ${auto_accept}"

approval_warning=""
if [[ "${approvals_mode}" == "manual" ]] && [[ "${auto_accept}" != "true" ]]; then
  approval_warning="manual approval required"
  echo "    ⚠ manual mode + auto-accept off → hooks fire only after you approve them in 'hermes chat'"
fi

# --- 3. Runtime evidence: did the hook actually write any JSONL? ----------
echo
echo "[3] Recent tool-event capture activity"
# find -mmin works on Linux + macOS coreutils; fall back to 0 on any error.
recent_jsonl=$(find "${TOOL_EVENTS_DIR}" -maxdepth 1 -name '*.jsonl' -mmin -60 2>/dev/null | wc -l | tr -d ' ')
echo "    ${recent_jsonl} tool-events/*.jsonl modified in the last 60 minutes"

# --- 4. Cross-check against state.db so we can distinguish "no agent  -----
#       activity at all" from "agent activity but hooks not firing".
echo
echo "[4] state.db cross-check (last 60 min)"
tool_msgs=0
if [[ -f "${STATE_DB}" ]]; then
  tool_msgs=$(sqlite3 "${STATE_DB}" \
    "SELECT COUNT(*) FROM messages WHERE role='tool' AND timestamp >= strftime('%s','now') - 3600;" \
    2>/dev/null || echo 0)
  echo "    ${tool_msgs} tool message(s) recorded by Hermes"
else
  echo "    (no state.db yet — Hermes hasn't run on this host)"
fi

# --- 5. Ledger snapshot ---------------------------------------------------
echo
echo "[5] Tool-event ledger"
if [[ -f "${TOOL_EVENTS_LEDGER_FILE}" ]]; then
  count=$(wc -l < "${TOOL_EVENTS_LEDGER_FILE}" 2>/dev/null | tr -d ' ')
  echo "    ${count} record(s) in ${TOOL_EVENTS_LEDGER_FILE}"
else
  echo "    ledger missing — the cron has not run successfully yet"
fi

# --- 6. Verdict + actionable guidance -------------------------------------
echo

if (( recent_jsonl > 0 )); then
  echo "✓ Hooks are firing — at least one tool-event was captured in the last hour."
  exit 0
fi

if (( tool_msgs > 0 )); then
  echo "⚠ Hooks are registered, Hermes has been running tools, but no tool-events"
  echo "  have been captured in the last hour. The post_tool_call hook is registered"
  echo "  but not firing. Most likely cause:"
  if [[ -n "${approval_warning}" ]]; then
    echo "    → ${approval_warning} — start 'hermes chat' and accept the approval"
    echo "      prompts for each revenium hook. If hermes was already running when"
    echo "      install-hooks.sh ran, restart it so the updated config.yaml is loaded."
    echo "      To skip approvals entirely, set 'hooks_auto_accept: true' in"
    echo "      ${HOOKS_CONFIG_FILE}."
  else
    echo "    → restart Hermes so it re-reads ${HOOKS_CONFIG_FILE}, and verify"
    echo "      the hooks haven't been disabled per-tool via 'security.acked_advisories'."
  fi
  exit 2
fi

echo "ℹ Hooks are registered but no tool activity has occurred yet (or in the"
echo "  last hour). Start a Hermes session that exercises a tool, then re-run"
echo "  this script to verify capture."
exit 2
