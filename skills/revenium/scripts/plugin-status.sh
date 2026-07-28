#!/usr/bin/env bash
set -uo pipefail
# plugin-status.sh — Phase 28 (D-01): diagnose whether the revenium-classifier
# on_session_end plugin is registered with Hermes' plugin discovery AND
# actually firing, and persist a plugin-health status document that
# hermes-report.sh reads to discriminate a registration outage from an
# unclassified session (D-06/D-07).
#
# Two-stage check (mirrors hooks-status.sh's shape):
#   1. Static: is ${HERMES_HOME}/plugins/revenium-classifier present as a
#      directory AND listed in plugins.enabled in ${HOOKS_CONFIG_FILE}?
#   2. Runtime liveness (Plan 28-03, D-02): cross-check sentinel freshness
#      (MARKERS_READY_DIR) against recently-ended sessions in state.db over
#      the REVENIUM_CRON_SETTLE_SECONDS window. A host with zero recently-
#      ended sessions is `idle` (never broken — nothing for the classifier
#      to have missed). A host with ended sessions AND fresh sentinels is
#      `firing`. A host with ended sessions and NO fresh sentinels is
#      `stalled` (broken) — the classifier is registered but not producing.
#      Liveness NEVER consults job-marker presence: a registration outage
#      must stay distinguishable from a classification failure (TRACE-04).
#
# Exit codes (stable for scripting; human-readable text may change):
#   0  registered, and liveness is idle or firing (healthy)
#   1  NOT registered (plugin dir absent, or not listed in plugins.enabled)
#   2  registered but liveness is stalled (not firing)
#
# Filesystem-and-regex ONLY (D-04): this runs on the per-minute cron path and
# must NEVER shell out to the hermes CLI to compute either verdict — it is
# slow, and on the diagnosis host `hermes` was not even on the bare PATH.
# Alert-only (D-05): this script never repairs anything, never restarts the
# gateway, and never invokes install-plugin.sh itself.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

PLUGIN_NAME="revenium-classifier"
PLUGIN_DEST_DIR="${HERMES_HOME}/plugins/${PLUGIN_NAME}"

echo "Revenium plugin registration status"
echo "────────────────────────────────────"

# --- 1. Static registration check ------------------------------------------
echo
echo "[1] Registration check"
registered=true

if [[ ! -d "${PLUGIN_DEST_DIR}" ]]; then
  echo "    ✗ plugin directory NOT found at ${PLUGIN_DEST_DIR}"
  registered=false
else
  echo "    ✓ plugin directory present at ${PLUGIN_DEST_DIR}"
fi

if ${registered}; then
  # Reuse install-plugin.sh's exact anchored list-item regex (read-only) so
  # this check and the writer agree on what "listed" means.
  if HOOKS_CONFIG_FILE="${HOOKS_CONFIG_FILE}" PLUGIN_NAME="${PLUGIN_NAME}" python3 - <<'PY' 2>/dev/null
import os
import re
import sys

path = os.environ['HOOKS_CONFIG_FILE']
plugin_name = os.environ['PLUGIN_NAME']
try:
    content = open(path, encoding='utf-8').read()
except Exception:
    sys.exit(1)
if re.search(r"^\s*-\s*" + re.escape(plugin_name) + r"\s*$", content, re.MULTILINE):
    sys.exit(0)
sys.exit(1)
PY
  then
    echo "    ✓ ${PLUGIN_NAME} listed in plugins.enabled (${HOOKS_CONFIG_FILE})"
  else
    echo "    ✗ ${PLUGIN_NAME} NOT listed in plugins.enabled (${HOOKS_CONFIG_FILE})"
    registered=false
  fi
fi

# --- 2. Runtime liveness ----------------------------------------------------
# D-02: the liveness window is REVENIUM_CRON_SETTLE_SECONDS itself, not a
# second independently-tunable constant — that is the exact bar at which
# hermes-report.sh gives up waiting for a sentinel, so "not firing" fires the
# same tick the fallback trace-type starts happening.
window_seconds="${REVENIUM_CRON_SETTLE_SECONDS:-600}"
window_minutes=$(( (window_seconds + 59) / 60 ))
[[ "${window_minutes}" -lt 1 ]] && window_minutes=1

liveness="unknown"
recent_ended=0
fresh_sentinels=0

if ${registered}; then
  echo
  echo "[2] Runtime liveness (window=${window_seconds}s / ${window_minutes}m)"

  # Count sessions whose ended_at falls inside the window. A missing or
  # unreadable state.db resolves to zero (idle branch) — same tolerance
  # hooks-status.sh uses for its own state.db cross-check.
  if [[ -f "${STATE_DB}" ]]; then
    recent_ended=$(sqlite3 "${STATE_DB}" \
      "SELECT COUNT(*) FROM sessions WHERE ended_at IS NOT NULL AND ended_at >= strftime('%s','now') - ${window_seconds};" \
      2>/dev/null || echo 0)
  fi
  [[ "${recent_ended}" =~ ^[0-9]+$ ]] || recent_ended=0

  # Count sentinels modified inside the window. Deliberately does NOT consult
  # job-marker presence anywhere — a registration outage must stay
  # distinguishable from a classification failure (TRACE-04).
  fresh_sentinels=$(find "${MARKERS_READY_DIR}" -maxdepth 1 -type f -mmin "-${window_minutes}" 2>/dev/null | wc -l | tr -d ' ')
  [[ "${fresh_sentinels}" =~ ^[0-9]+$ ]] || fresh_sentinels=0

  echo "    ${recent_ended} session(s) with ended_at inside the last ${window_seconds}s (state.db)"
  echo "    ${fresh_sentinels} sentinel(s) modified inside the last ${window_seconds}s (${MARKERS_READY_DIR})"

  if [[ "${recent_ended}" -eq 0 ]]; then
    liveness="idle"
    echo "    ℹ idle host — no sessions ended in the window, nothing for the classifier to have missed"
  elif [[ "${fresh_sentinels}" -gt 0 ]]; then
    liveness="firing"
    echo "    ✓ classifier is firing — sentinel activity matches recently-ended sessions"
  else
    liveness="stalled"
    echo "    ✗ classifier NOT firing — sessions ended but no sentinel activity in the window"
  fi
else
  echo
  echo "[2] Runtime liveness"
  echo "    (skipped — plugin is not registered; stage 1 short-circuits stage 2)"
fi

# --- 3. Persist plugin-status.json atomically (D-06 status file contract) -
STATUS_OUTPUT=$(
  REGISTERED="${registered}" \
  LIVENESS="${liveness}" \
  PLUGIN_STATUS_FILE="${PLUGIN_STATUS_FILE}" \
  python3 - <<'PY'
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

status_file = Path(os.environ['PLUGIN_STATUS_FILE'])
registered = os.environ['REGISTERED'] == 'true'
liveness = os.environ['LIVENESS']

# Fail-open load of the previous document (matches guardrail-status.json's
# carry-forward idiom). A missing/corrupt file defaults prev_healthy to TRUE
# so a fresh install never alerts on its very first tick.
prev = {}
try:
    prev = json.loads(status_file.read_text(encoding='utf-8'))
except Exception:
    pass
prev_healthy = prev.get('healthy', True)
if not isinstance(prev_healthy, bool):
    prev_healthy = True
prev_broken_at = prev.get('brokenAt')

# Verdict table (D-06 contract, Plan 28-01): registered AND liveness not
# 'stalled' is healthy. 'unknown' (stage 1 failed, stage 2 never ran) and
# 'idle'/'firing' are all non-broken.
healthy = registered and liveness != 'stalled'

now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

data = {
    'healthy': healthy,
    'registered': registered,
    'liveness': liveness,
    'lastChecked': now,
}

if not healthy:
    if prev_healthy:
        data['brokenAt'] = now
    else:
        data['brokenAt'] = prev_broken_at or now
# healthy == True: brokenAt key omitted entirely (contract).

# Atomic write: write-tmp-rename, reused verbatim from guardrail-check.sh
# (T-28-01 mitigation) so a concurrent reader never observes a partial doc.
tmp_fd, tmp_path = tempfile.mkstemp(
    dir=str(status_file.parent),
    prefix='.plugin-status-',
    suffix='.tmp',
)
try:
    with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
        f.write(json.dumps(data, indent=2) + '\n')
    os.replace(tmp_path, str(status_file))
finally:
    try:
        os.unlink(tmp_path)
    except FileNotFoundError:
        pass

print(f"PLUGIN_HEALTHY={'true' if healthy else 'false'}")
PY
)

echo "${STATUS_OUTPUT}"
PLUGIN_HEALTHY=$(echo "${STATUS_OUTPUT}" | sed -n 's/^PLUGIN_HEALTHY=//p' | head -1)

# --- 4. Verdict + actionable guidance --------------------------------------
echo

if [[ "${registered}" != "true" ]]; then
  echo "✗ Plugin is NOT registered. Run:"
  echo "  bash ${SCRIPT_DIR}/install-plugin.sh"
  EXIT_CODE=1
elif [[ "${liveness}" == "stalled" ]]; then
  echo "✗ Plugin is registered but the classifier is NOT firing (stalled)."
  echo "  ${recent_ended} session(s) ended in the last ${window_seconds}s with zero sentinel activity."
  echo "  Human remediation (this script never repairs automatically, D-05):"
  echo "    1. Restart the Hermes gateway so it reloads ${PLUGIN_NAME}."
  echo "    2. Re-run: bash ${SCRIPT_DIR}/install-plugin.sh"
  EXIT_CODE=2
else
  echo "✓ Plugin is registered. Liveness: ${liveness}."
  EXIT_CODE=0
fi

exit "${EXIT_CODE}"
