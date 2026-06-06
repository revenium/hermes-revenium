#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

# Acquire cron.lock non-blocking. Held for the rest of this script's lifetime via fd 9,
# so the lock spans all inner-pipeline invocations below (CRON-08, D-12).
# `exec 9>"${LOCK_FILE}"` opens fd 9 in this bash process; the python3 subprocess inherits
# fd 9 automatically and calls fcntl.flock(9, ...) on it. No stdin redirection is used so
# the heredoc script body remains the Python program (NOT the empty lock file).
# The `if ! python3 ... ; then ... fi` form neutralizes `-e` for the contention branch so
# `warn + exit 0` is reached on EAGAIN (do NOT add `|| true`; do NOT change cron.sh's flag mode).
# flock(2) works on the underlying open file description regardless of access mode, so a
# write-opened fd 9 is fine for exclusive locking.
exec 9>"${LOCK_FILE}"
if ! python3 - <<'PY'
import fcntl, sys
try:
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
except (OSError, BlockingIOError):
    sys.exit(11)
PY
then
  warn "prior tick still active, skipping this minute"
  exit 0
fi

if [[ -f "${ENV_FILE}" ]]; then
  set -o allexport
  # shellcheck source=/dev/null
  source "${ENV_FILE}"
  set +o allexport
fi

# Optional sub-minute looping. Default REVENIUM_CRON_LOOP_COUNT=1 preserves
# the historical "fire once per cron tick" behavior; demos / dashboards that
# want metrics in Revenium faster than 60s set both knobs (install-cron.sh
# `--interval-seconds N` does this for them). The cron.lock acquired above
# is held for the full loop, so the next minute's cron tick warns + skips
# if this loop overruns — the lock-skip path is the safety net.
loop_count="${REVENIUM_CRON_LOOP_COUNT:-1}"
loop_sleep="${REVENIUM_CRON_LOOP_SLEEP_SECONDS:-0}"

# Validate: positive integers; clamp invalid input to safe defaults rather
# than aborting the tick (matches the rest of the cron's fail-open posture).
if ! [[ "${loop_count}" =~ ^[0-9]+$ ]] || (( loop_count < 1 )); then
  warn "invalid REVENIUM_CRON_LOOP_COUNT=${loop_count}, using 1"
  loop_count=1
fi
if ! [[ "${loop_sleep}" =~ ^[0-9]+$ ]]; then
  warn "invalid REVENIUM_CRON_LOOP_SLEEP_SECONDS=${loop_sleep}, using 0"
  loop_sleep=0
fi

for ((i=1; i<=loop_count; i++)); do
  # Phase 18 (D-06, MIGR-01..04): auto-migration from legacy alertId to ruleIds.
  # Reads alertId inline (Pitfall 5 — no dependency on read_config_field from the
  # second-stage checker; the legacy alert checker was removed in Phase 19). Missing
  # config.json or no alertId means there is nothing to migrate.
  ALERT_ID_FOR_MIGRATION=$(CONFIG_FILE="${CONFIG_FILE}" python3 - <<'PY' 2>/dev/null || true
import json, os
try:
    print(json.load(open(os.environ['CONFIG_FILE'])).get('alertId', ''))
except Exception:
    print('')
PY
)
  # quick-260606: only invoke the migration when there is actually a legacy alertId.
  # setup-guardrails' arg parser rejects an empty --from-alert with exit 2 + an
  # ERROR log (written directly to LOG_FILE, so `2>/dev/null` does not hide it) —
  # which spammed a spurious "--from-alert requires an alertId argument" every tick
  # on guardrails-native installs (ruleIds, no alertId) and read like a metering
  # failure. Guarding here makes the no-op case a true no-op. The `|| true` keeps a
  # real migration failure from ever blocking metering.
  if [[ -n "${ALERT_ID_FOR_MIGRATION}" ]]; then
    bash "${SKILL_DIR}/scripts/setup-guardrails.sh" --from-alert "${ALERT_ID_FOR_MIGRATION}" --auto 2>/dev/null || true
  fi
  bash "${SKILL_DIR}/scripts/hermes-report.sh" "$@" || true
  bash "${SKILL_DIR}/scripts/guardrail-check.sh" "$@" || true
  bash "${SKILL_DIR}/scripts/tool-event-report.sh" "$@" || true
  # Sleep between iterations only; never after the last one (the next cron
  # tick lands within ~60s anyway, so a trailing sleep is wasted).
  if (( i < loop_count && loop_sleep > 0 )); then
    sleep "${loop_sleep}"
  fi
done
