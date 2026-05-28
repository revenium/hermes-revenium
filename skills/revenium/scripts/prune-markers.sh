#!/usr/bin/env bash
# Prune stale marker JSONL files from MARKERS_DIR.
# Staleness is determined by the latest ledger row timestamp for the session
# (field 4 of HERMES:<sid>:<total_tokens>:<unix_ts>:<muid> lines). If no
# ledger entry exists for a sid (orphan marker), file mtime is used instead.
# Safe to run manually at any time; NOT wired into cron (D-28).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

# ---------------------------------------------------------------------------
# Flag parsing
# ---------------------------------------------------------------------------
DRY_RUN=false
for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=true ;;
    *) echo "Unknown flag: ${arg}" >&2; echo "Usage: $(basename "${BASH_SOURCE[0]}") [--dry-run]" >&2; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Preflight: validate MARKER_RETENTION_DAYS is an integer >= 1 (HARDEN-03).
# A value of 0 (or non-integer) would make every marker stale and trigger a
# mass-delete.  Warn loudly and exit 0 (no error mail from cron) instead of
# deleting anything.  Mirrors the lock-contention exit-0 branch below.
# ---------------------------------------------------------------------------
if ! [[ "${MARKER_RETENTION_DAYS}" =~ ^[0-9]+$ ]]; then
  warn "prune-markers: REVENIUM_MARKER_RETENTION_DAYS=${MARKER_RETENTION_DAYS} is invalid (must be an integer >= 1); refusing to prune"
  exit 0
fi
if [[ "${MARKER_RETENTION_DAYS}" -lt 1 ]]; then
  warn "prune-markers: REVENIUM_MARKER_RETENTION_DAYS=${MARKER_RETENTION_DAYS} is invalid (must be an integer >= 1); refusing to prune"
  exit 0
fi

# ---------------------------------------------------------------------------
# Acquire prune.lock (non-blocking) so two concurrent operator invocations
# cannot race on the same file set (D-29 / T-05-01).  Uses the same
# exec-fd + Python fcntl pattern as cron.sh (CRON-08 / D-12).
# ---------------------------------------------------------------------------
exec 9>"${PRUNE_LOCK_FILE}"
if ! python3 - <<'PY'
import fcntl, sys
try:
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
except (OSError, BlockingIOError):
    sys.exit(11)
PY
then
  warn "prior prune still active, skipping"
  exit 0
fi

# ---------------------------------------------------------------------------
# Main pruning logic: run Python, capture its stdout to a temp file so the
# child's exit code is observable, then feed each output line through info()
# so every log event lands in ${LOG_FILE} with the standard timestamp format.
# Never use bare echo for logged events.
#
# Previously used a process-substitution form which discards the child's exit
# code (pipefail does not apply to that form); a temp-file + prune_rc=$?
# pattern is used instead so a failed os.unlink propagates as a non-zero exit.
# ---------------------------------------------------------------------------
prune_out="$(mktemp)"
# Pass paths via env (bash 3.2 compatible — `${VAR@Q}` requires bash 4.4+;
# per project bash 3.2 convention for macOS stock /bin/bash). Single-
# quoted heredoc keeps the Python source verbatim.
# set +e so set -euo pipefail does not abort before prune_rc=$? is captured.
set +e
MARKERS_DIR_PY="${MARKERS_DIR}" \
LEDGER_FILE_PY="${LEDGER_FILE}" \
MARKER_RETENTION_DAYS_PY="${MARKER_RETENTION_DAYS}" \
DRY_RUN_PY="${DRY_RUN}" \
python3 - <<'PY' >"${prune_out}"
import os
import sys
import time

markers_dir    = os.environ['MARKERS_DIR_PY']
ledger_file    = os.environ['LEDGER_FILE_PY']
retention_days = int(os.environ['MARKER_RETENTION_DAYS_PY'])
dry_run        = os.environ['DRY_RUN_PY'] == "true"

cutoff_secs = retention_days * 86400


def ledger_last_ts(sid, ledger_path):
    """Return the unix timestamp (float) from the latest matching ledger row,
    or None if no row exists for this sid. Reads field 4 (0-indexed) from
    lines matching HERMES:<sid>: (D-26 primary path)."""
    try:
        with open(ledger_path, 'r', encoding='utf-8') as f:
            prefix = 'HERMES:' + sid + ':'
            last_ts = None
            for line in f:
                line = line.rstrip('\n')
                if not line.startswith(prefix):
                    continue
                parts = line.split(':')
                # v2: HERMES:<sid>:<total_tokens>:<unix_ts>:<muid>  (5 fields)
                # v1: HERMES:<sid>:<total_tokens>:<unix_ts>          (4 fields)
                if len(parts) >= 4:
                    try:
                        ts = float(parts[3])
                        if last_ts is None or ts > last_ts:
                            last_ts = ts
                    except ValueError:
                        pass
            return last_ts
    except FileNotFoundError:
        return None


def iso(ts):
    """Format a unix timestamp as ISO-8601 UTC for log lines."""
    import datetime
    return datetime.datetime.utcfromtimestamp(ts).strftime('%Y-%m-%dT%H:%M:%SZ')


scanned = 0
kept = 0
removed = 0

try:
    entries = sorted(os.listdir(markers_dir))
except FileNotFoundError:
    entries = []

for fname in entries:
    if not fname.endswith('.jsonl'):
        continue
    fpath = os.path.join(markers_dir, fname)
    if not os.path.isfile(fpath):
        continue

    scanned += 1
    sid = fname[:-len('.jsonl')]  # strip .jsonl suffix

    last_ts = ledger_last_ts(sid, ledger_file)
    if last_ts is not None:
        # Ledger-based stale check (D-26 primary path)
        age_secs  = time.time() - last_ts
        age_days  = age_secs / 86400
        ts_label  = iso(last_ts)
        ts_source = 'last_ledger_ts'
    else:
        # Orphan fallback: no ledger row — use file mtime (D-26 fallback)
        mtime     = os.path.getmtime(fpath)
        age_secs  = time.time() - mtime
        age_days  = age_secs / 86400
        ts_label  = iso(mtime)
        ts_source = 'mtime'

    if age_secs < cutoff_secs:
        kept += 1
        continue

    # File is stale — remove or report
    action = 'dry-run, would remove' if dry_run else 'removed'
    print(
        'prune: ' + action +
        ' sid=' + sid +
        ' marker=' + fname +
        ' ' + ts_source + '=' + ts_label +
        ' age_days=' + str(round(age_days, 1)),
        flush=True,
    )

    if not dry_run:
        try:
            os.unlink(fpath)
            removed += 1
        except OSError as exc:
            print('prune: ERROR removing ' + fname + ': ' + str(exc), flush=True)
            sys.exit(1)
    else:
        removed += 1  # count for dry-run summary

print(
    'prune: summary, scanned=' + str(scanned) +
    ' kept=' + str(kept) +
    ' removed=' + str(removed),
    flush=True,
)
PY
prune_rc=$?
set -e
while IFS= read -r log_line; do
  info "${log_line}"
done < "${prune_out}"
rm -f "${prune_out}"
if [[ "${prune_rc}" -ne 0 ]]; then
  warn "prune-markers: pruning failed (python exit ${prune_rc}); some stale markers may remain"
  exit "${prune_rc}"
fi
