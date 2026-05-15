---
phase: 05-housekeeping-compat-hardening
plan: 01
type: execute
executed: 2026-05-15T00:58:02Z
requirements_completed:
  - COMPAT-04
  - TEST-05
files_modified:
  - skills/revenium/scripts/common.sh
  - tests/test_repository.py
files_created:
  - skills/revenium/scripts/prune-markers.sh
  - .planning/phases/05-housekeeping-compat-hardening/05-01-SUMMARY.md
tests_added: 1
tests_modified: 0
tests_total_after: 42
commits:
  - hash: 5ed83a7
    type: feat
    message: "add MARKER_RETENTION_DAYS + PRUNE_LOCK_FILE to common.sh; add prune-markers.sh scaffold + expected_files entry"
  - hash: 93221c7
    type: test
    message: "add test_prune_markers_dry_run_and_live — E2E prune script coverage"
  - hash: (summary commit)
    type: docs
    message: "complete 05-01 plan — prune-markers.sh + common.sh retention knob"
tags:
  - housekeeping
  - prune-markers
  - operator-script
  - common-sh-additions
decisions:
  - "D-26: Ledger-based stale criteria with mtime fallback for orphan markers"
  - "D-27: MARKER_RETENTION_DAYS=30 default, REVENIUM_MARKER_RETENTION_DAYS env override, declared in common.sh"
  - "D-28: Operator-invoked only — no cron.sh integration"
  - "D-29: --dry-run flag + info-helper log per deletion + flock serialization"
dependency_graph:
  requires: []
  provides:
    - skills/revenium/scripts/prune-markers.sh
    - MARKER_RETENTION_DAYS (common.sh)
    - PRUNE_LOCK_FILE (common.sh)
  affects:
    - tests/test_repository.py (test_expected_files_exist now includes prune-markers.sh)
    - skills/revenium/scripts/common.sh (two new path/config declarations)
tech_stack:
  added: []
  patterns:
    - "Bash set -euo pipefail operator script (clear-halt.sh shape)"
    - "Python fcntl flock non-blocking gate (cron.sh pattern)"
    - "info/warn helpers for all log events (CLAUDE.md logging discipline)"
    - "Python heredoc piped to while-read | info for LOG_FILE integration"
key_files:
  created:
    - path: skills/revenium/scripts/prune-markers.sh
      summary: "Operator script that prunes stale marker JSONL files using ledger-based stale check (D-26), with mtime fallback for orphans, flock gate, dry-run flag, and info-helper logging"
  modified:
    - path: skills/revenium/scripts/common.sh
      summary: "Added MARKER_RETENTION_DAYS and PRUNE_LOCK_FILE declarations after LOCK_FILE (D-27)"
    - path: tests/test_repository.py
      summary: "Added prune-markers.sh to expected_files list; added test_prune_markers_dry_run_and_live with three sub-cases"
metrics:
  duration_minutes: ~15
  tasks_completed: 2
  files_changed: 3
---

# Phase 5 Plan 01: Marker File Pruning + common.sh Retention Knob Summary

## Outcome

Shipped `prune-markers.sh` — an operator-invoked script that removes stale marker JSONL files from `${MARKERS_DIR}`. Staleness is determined by reading field 4 of the latest `HERMES:<sid>:…:<unix_ts>:…` ledger row per session (D-26 primary path), falling back to `os.path.getmtime` for orphan markers with no ledger entry. Default retention is 30 days, overridable via `REVENIUM_MARKER_RETENTION_DAYS`. Two new declarations added to `common.sh` (`MARKER_RETENTION_DAYS`, `PRUNE_LOCK_FILE`) following the existing `:-` fallback discipline. One new E2E test verifies all three D-29 sub-cases (dry-run, live, idempotent re-run). Full suite remains green at 42 tests.

## Decisions Honored

### D-26 — Ledger-based stale criteria
Stale check reads the ledger via `grep "^HERMES:<sid>:" | tail -1 | cut -d: -f4` logic (Python implementation) and compares the unix timestamp to `now - retention_days * 86400`. For orphan markers (no ledger row), `os.path.getmtime` is used as the fallback age source. The prune script never writes to the ledger.

### D-27 — Default retention = 30 days, env override
`MARKER_RETENTION_DAYS="${REVENIUM_MARKER_RETENTION_DAYS:-30}"` declared in `common.sh` adjacent to `LOCK_FILE`. Test passes `REVENIUM_MARKER_RETENTION_DAYS=30` explicitly to pin behavior regardless of operator env.

### D-28 — Operator-invoked only
No change to `cron.sh`. The script is a one-shot operator CLI with `set -euo pipefail` (hard-fail mode, matching `clear-halt.sh`). Not wired into any scheduler.

### D-29 — Safety: `--dry-run` flag + `info`-helper logging + flock gate
- `--dry-run` flag: logs candidates without deleting; unknown flags exit 1 with usage on stderr.
- Every removal and dry-run candidate is logged via `info` from `common.sh` (routed to `${LOG_FILE}`), with format `prune: [action] sid=<sid> marker=<fname> last_ledger_ts=<iso>|mtime=<iso> age_days=<n>`.
- Summary line: `prune: summary, scanned=<n> kept=<n> removed=<n>` emitted at end of every run.
- Lock gate: `exec 9>"${PRUNE_LOCK_FILE}"` + `fcntl.flock(9, LOCK_EX | LOCK_NB)` — same pattern as `cron.sh`. On contention: `warn "prior prune still active, skipping"` + `exit 0`. Lock file is `${PRUNE_LOCK_FILE}` (= `${STATE_DIR}/prune.lock`), NOT shared with `cron.lock`.

## Key Files

- `skills/revenium/scripts/prune-markers.sh` — New operator script. Sources `common.sh`, calls `ensure_path`, acquires `${PRUNE_LOCK_FILE}` via Python fcntl, runs pruning logic in a Python heredoc (stdlib-only: `os`, `sys`, `time`, `datetime`), routes each output line through `info()` via `while IFS= read -r`.
- `skills/revenium/scripts/common.sh` — Two new lines after `LOCK_FILE`: `MARKER_RETENTION_DAYS` and `PRUNE_LOCK_FILE`. No other changes. `test_runtime_paths_are_hermes_native` continues to pass.
- `tests/test_repository.py` — `prune-markers.sh` added to `test_expected_files_exist` expected list; `test_prune_markers_dry_run_and_live` appended to `RepositoryTests` with three sub-cases (dry-run / live / idempotent).

## Verification

```
python3 -m unittest discover -s tests -p 'test_*.py' -v
Ran 42 tests in 12.9s
OK
```

`bash -n skills/revenium/scripts/prune-markers.sh` exits 0.
`test_runtime_paths_are_hermes_native` passes (MARKERS_DIR, MARKERS_READY_DIR, LOCK_FILE lines unchanged; .hermes and state/revenium literals preserved).
`test_no_legacy_branding_left` passes (prune-markers.sh contains no forbidden token matches).

## Operator Verification (Manual UAT Triple-Case)

To verify the script by hand after install:

```bash
# 1. Seed fixture (adjust dates with date -d on Linux, or date -v on macOS)
STATE_DIR=~/.hermes/state/revenium
mkdir -p "${STATE_DIR}/markers"

# Create an "old" session marker (31 days ago)
OLD_TS=$(python3 -c "import time; print(int(time.time()) - 31*86400)")
echo '{"muid":"aaa","ts":'"${OLD_TS}"',"sid":"old-test","task_type":"research","operation_type":"CHAT"}' \
  > "${STATE_DIR}/markers/old-test.jsonl"
echo "HERMES:old-test:1000:${OLD_TS}:aaa" >> "${STATE_DIR}/revenium-hermes.ledger"

# Create a "fresh" session marker (today)
FRESH_TS=$(python3 -c "import time; print(int(time.time()))")
echo '{"muid":"bbb","ts":'"${FRESH_TS}"',"sid":"fresh-test","task_type":"generation","operation_type":"CHAT"}' \
  > "${STATE_DIR}/markers/fresh-test.jsonl"
echo "HERMES:fresh-test:500:${FRESH_TS}:bbb" >> "${STATE_DIR}/revenium-hermes.ledger"

# Create an "orphan" marker (no ledger entry, mtime 31d ago)
echo '{"muid":"ccc","ts":'"${OLD_TS}"',"sid":"orphan-test","task_type":"review","operation_type":"CHAT"}' \
  > "${STATE_DIR}/markers/orphan-test.jsonl"
touch -t "$(python3 -c "import datetime; dt=datetime.datetime.utcnow()-datetime.timedelta(days=31); print(dt.strftime('%Y%m%d%H%M.%S'))")" \
  "${STATE_DIR}/markers/orphan-test.jsonl"

# 2. Dry-run: confirm old-test + orphan-test appear in output, fresh-test absent
bash ~/.hermes/skills/revenium/scripts/prune-markers.sh --dry-run
# Expect: two "dry-run, would remove" lines, one for old-test and one for orphan-test

# 3. Live run: confirm old-test + orphan-test deleted, fresh-test kept
bash ~/.hermes/skills/revenium/scripts/prune-markers.sh
ls "${STATE_DIR}/markers/"
# Expect: only fresh-test.jsonl and .ready/ present

# 4. Idempotent re-run
bash ~/.hermes/skills/revenium/scripts/prune-markers.sh
# Expect: "prune: summary, scanned=1 kept=1 removed=0"
```

## Out of Scope Carried Forward

Per the plan scope locks (D-37, D-38):

- No changes to `classifier.py` (Plans 05-02 owns mint-back + recency sort)
- No changes to `hermes-report.sh` (Plan 05-03 owns WR-01/WR-02)
- No doc changes to README.md, setup.md, task-taxonomy.md (Plan 05-04 owns docs pass)
- `_count_tools_in_current_turn` helper and its 4 tests kept as-is (D-37 explicit KEEP)

## Deviations from Plan

None — plan executed exactly as written. The Python heredoc output is routed through `while IFS= read -r log_line; do info "${log_line}"; done < <(python3 ...)` to satisfy the `info`-helper-only logging discipline while keeping the logic inside a single Python subprocess.

## Self-Check: PASSED

| Item | Result |
|------|--------|
| `skills/revenium/scripts/prune-markers.sh` exists | FOUND |
| `skills/revenium/scripts/common.sh` has MARKER_RETENTION_DAYS | FOUND |
| `skills/revenium/scripts/common.sh` has PRUNE_LOCK_FILE | FOUND |
| `tests/test_repository.py` has test_prune_markers_dry_run_and_live | FOUND |
| `05-01-SUMMARY.md` exists | FOUND |
| T01 commit 5ed83a7 exists | FOUND |
| T02 commit 93221c7 exists | FOUND |
| Test suite: 42 tests, OK | PASSED |
| `bash -n prune-markers.sh` | PASSED |
| `test_no_legacy_branding_left` | PASSED |
