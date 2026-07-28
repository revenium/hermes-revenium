#!/usr/bin/env bash
set -uo pipefail
# plugin-status.sh — Phase 28 (D-01): diagnose whether the revenium-classifier
# on_session_end plugin is registered with Hermes' plugin discovery, and
# persist a plugin-health status document that hermes-report.sh reads to
# discriminate a registration outage from an unclassified session (D-06/D-07).
#
# Two-stage check (mirrors hooks-status.sh's shape):
#   1. Static: is ${HERMES_HOME}/plugins/revenium-classifier present as a
#      directory AND listed in plugins.enabled in ${HOOKS_CONFIG_FILE}?
#   2. Runtime liveness: STUBBED to "unknown" in this plan. Plan 28-03 fills
#      in the sentinel-freshness cross-check against recently-ended sessions
#      in state.db (D-02). "unknown" is a safe stub — it means "not yet
#      judged", never "broken" — so a registered-but-not-yet-evaluated plugin
#      is never misreported as failing.
#
# Exit codes (stable for scripting; human-readable text may change):
#   0  registered, and liveness is healthy or not-yet-judgeable (unknown/idle/firing)
#   1  NOT registered (plugin dir absent, or not listed in plugins.enabled)
#   2  registered but liveness is "stalled" (not firing) — reserved for 28-03
#
# Filesystem-and-regex ONLY (D-04): this runs on the per-minute cron path and
# must NEVER shell out to the hermes CLI — it is slow, and on the diagnosis
# host `hermes` was not even on the bare PATH. Alert-only (D-05): this script
# never repairs anything and never invokes install-plugin.sh itself.

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

# --- 2. Runtime liveness (STUBBED — completed in Plan 28-03) --------------
echo
echo "[2] Runtime liveness"
echo "    (not yet evaluated in this build — liveness reports 'unknown')"

# --- 3. Persist plugin-status.json atomically (D-06 status file contract) -
STATUS_OUTPUT=$(
  REGISTERED="${registered}" \
  PLUGIN_STATUS_FILE="${PLUGIN_STATUS_FILE}" \
  python3 - <<'PY'
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

status_file = Path(os.environ['PLUGIN_STATUS_FILE'])
registered = os.environ['REGISTERED'] == 'true'

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

# Stage 2 is stubbed to 'unknown' in this plan (Task 1). D-02: 'unknown'
# means "not yet judged", NOT "broken" — healthy tracks registration alone
# until 28-03 fills in the sentinel-freshness rows.
liveness = 'unknown'
healthy = registered

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

if [[ "${PLUGIN_HEALTHY}" != "true" ]]; then
  echo "✗ Plugin is NOT registered. Run:"
  echo "  bash ${SCRIPT_DIR}/install-plugin.sh"
  exit 1
fi

echo "✓ Plugin is registered. Liveness has not been evaluated in this build."
exit 0
