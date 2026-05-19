#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

# Acquire cron.lock non-blocking. Held for the rest of this script's lifetime via fd 9,
# so the lock spans BOTH hermes-report.sh and budget-check.sh invocations below (CRON-08, D-12).
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

bash "${SKILL_DIR}/scripts/hermes-report.sh" "$@" || true
bash "${SKILL_DIR}/scripts/budget-check.sh" "$@" || true
bash "${SKILL_DIR}/scripts/tool-event-report.sh" "$@" || true
