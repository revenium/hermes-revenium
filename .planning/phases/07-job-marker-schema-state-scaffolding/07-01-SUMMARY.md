---
phase: 07-job-marker-schema-state-scaffolding
plan: "01"
subsystem: cron-pipeline
tags: [schema, state-paths, job-tracking, backward-compat, tests]
dependency_graph:
  requires: []
  provides:
    - JOBS_LEDGER_FILE path declaration in common.sh
    - JOB_TAXONOMY_FILE path declaration in common.sh
    - kind:"job" reader branch in hermes-report.sh marker reader
    - JOBS_JSON output from marker reader heredoc
    - revenium-jobs.ledger touch-created on cron startup
    - TEST-01 (test_job_marker_schema) schema pin
    - TEST-02 (test_job_marker_does_not_alter_task_completion_argv) regression
  affects:
    - skills/revenium/scripts/common.sh
    - skills/revenium/scripts/hermes-report.sh
    - tests/test_repository.py
tech_stack:
  added: []
  patterns:
    - "VAR=${ENV_OVERRIDE:-${STATE_DIR}/file} path declaration (common.sh)"
    - "kind branch before REQUIRED_KEYS check in Python heredoc"
    - "JOBS_JSON= output + bash sed capture"
key_files:
  created: []
  modified:
    - skills/revenium/scripts/common.sh
    - skills/revenium/scripts/hermes-report.sh
    - tests/test_repository.py
decisions:
  - "D-13: JOBS_LEDGER_FILE and JOB_TAXONOMY_FILE declared in common.sh only with :- env-override shape"
  - "D-14: revenium-jobs.ledger is a separate file from revenium-hermes.ledger"
  - "D-15: revenium-jobs.ledger touch-created in hermes-report.sh startup block; JOB_TAXONOMY_FILE unused in v1.1"
  - "D-06: kind branch before REQUIRED_KEYS check preserves v1.0 byte-identical task-marker path"
  - "D-12: jobs_by_id collector uses last-line-wins per agentic_job_id"
  - "Pitfall 2 guard: jobs_by_id initialized before is_file() check so JOBS_JSON= print is always safe"
metrics:
  duration: "~5 minutes"
  completed: "2026-05-15T05:19:20Z"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 3
  tests_added: 2
  tests_total: 47
---

# Phase 7 Plan 01: Job Marker Schema & State Scaffolding Summary

## One-Liner

Additive v1.1 scaffolding: `JOBS_LEDGER_FILE` and `JOB_TAXONOMY_FILE` in `common.sh`, `kind:"job"` reader branch in `hermes-report.sh` with last-wins deduplication and `JOBS_JSON` output, `revenium-jobs.ledger` touch-created on startup, plus TEST-01 (schema pin) and TEST-02 (byte-identical-argv regression) — all 47 tests pass, v1.0 behavior unchanged.

## Tasks Completed

| Task | Name | Commit | Files Modified |
|------|------|--------|----------------|
| 1 | Declare JOBS_LEDGER_FILE and JOB_TAXONOMY_FILE in common.sh | 5817d47 | `common.sh`, `test_repository.py` |
| 2 | Add kind branch to hermes-report.sh marker reader + jobs ledger touch | c329d95 | `hermes-report.sh` |
| 3 | Add TEST-01 (job marker schema pin) and TEST-02 (byte-identical argv regression) | 6171fbf | `test_repository.py` |

## What Was Built

### Task 1: common.sh path declarations (SCHEMA-01, D-13)

Added two new path declarations immediately after `PRUNE_LOCK_FILE` and before `mkdir -p`:

```bash
# v1.1 job-tracking scaffolding (D-13)
JOBS_LEDGER_FILE="${REVENIUM_JOBS_LEDGER_FILE:-${STATE_DIR}/revenium-jobs.ledger}"
JOB_TAXONOMY_FILE="${REVENIUM_JOB_TAXONOMY_FILE:-${STATE_DIR}/job-taxonomy.json}"
```

Extended `test_runtime_paths_are_hermes_native` with 4 new `assertIn` calls for both variable names and file paths.

Key invariants:
- `revenium-jobs.ledger` is a distinct file from `revenium-hermes.ledger` (D-14)
- `JOB_TAXONOMY_FILE` is declared for forward-compat only — no file created in Phase 7 (D-15)
- Env-var names appear only in `common.sh` (enforced by test)

### Task 2: hermes-report.sh kind branch + jobs ledger touch (SCHEMA-03, SCHEMA-05, D-15)

Three edits:

**Edit A (D-15):** Added `touch "${JOBS_LEDGER_FILE}"` immediately after the existing `touch "${LEDGER_FILE}"` in the startup block.

**Edit B (D-06, D-12):** Inserted the `kind` branch in the Python heredoc marker reader BEFORE the `REQUIRED_KEYS` check (critical ordering per Pitfall 1). Initialized `jobs_by_id = {}` and `JOB_REQUIRED = ("agentic_job_id", "job_type", "status")` after `REQUIRED_KEYS` and before `if marker_path.is_file():` (Pitfall 2 guard). Branch logic:
- `kind == "job"` → validate D-04 keys, store `jobs_by_id[agentic_job_id] = m` (last wins), `continue`
- `kind is not None` → forward-compat skip, `continue`
- `kind` absent → fall through to v1.0 `REQUIRED_KEYS` check (byte-identical)

**Edit C:** Added `JOBS_JSON=` print at end of heredoc; bash captures with `sed` into `local jobs_json` (intentionally unused in Phase 7, reserved for Phase 9).

`REQUIRED_KEYS` tuple unchanged: `('muid', 'ts', 'sid', 'task_type', 'operation_type')` (D-05).

### Task 3: TEST-01 and TEST-02 (TEST-01, TEST-02)

**test_job_marker_schema (TEST-01):**
- Instantiates canonical D-03 fixture with all required and optional keys
- Asserts all four D-04 reader-required keys present (`kind`, `agentic_job_id`, `job_type`, `status`)
- Asserts all keys are `snake_case` via `assertNotRegex(k, r'[A-Z]')` (D-02)
- Asserts `kind == "job"` (D-01)
- Asserts compact JSONL serialization < 1024 bytes (D-03)
- Asserts minimal fixture (no `job_name`, `ts`, `sid`) is valid (D-04 optional keys)

**test_job_marker_does_not_alter_task_completion_argv (TEST-02):**
- Uses same shim + tmpdir + subprocess harness as `test_cron_marker_split_end_to_end`
- Sub-case A: Run hermes-report.sh with task markers only → capture argv; Run again with same task markers + D-03 job line → assert argv lists are byte-identical (SCHEMA-04)
- Sub-case B: Marker-less session → assert exactly 1 call with `--task-type unclassified` and `--operation-type CHAT` (v1.0 zero-marker fallthrough preserved)

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. This plan is pure scaffolding: no data is written to the new ledger, no job taxonomy file is created, and `JOBS_JSON` is captured but explicitly not consumed. The scaffolding is intentional and documented; Phase 9 will add the ledger write logic and Phase 10 will add outcome reporting.

## Threat Flags

None. Phase 7 introduces no new network calls, credentials, file permissions, or user-controlled input surfaces beyond what already existed in the marker reader. The threat register in the plan (`T-07-01`, `T-07-02`, `T-07-03`) all map to existing mitigations inherited from the v1.0 reader.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| `skills/revenium/scripts/common.sh` exists | FOUND |
| `skills/revenium/scripts/hermes-report.sh` exists | FOUND |
| `tests/test_repository.py` exists | FOUND |
| `07-01-SUMMARY.md` exists | FOUND |
| Commit 5817d47 (Task 1) exists | FOUND |
| Commit c329d95 (Task 2) exists | FOUND |
| Commit 6171fbf (Task 3) exists | FOUND |
| No `job-taxonomy.json` created on disk | PASS |
