---
phase: 20-integration-hardening-documentation
plan: 01
subsystem: tests
tags: [phase-20, compat, goldens, wire-shape, byte-identical, ci-enforcement]
dependency_graph:
  requires: []
  provides:
    - COMPAT-01 golden-argv CI enforcement for meter completion, jobs create, jobs outcome, meter tool-event
    - Shared _compat_helpers.py module for all four COMPAT-01 tests
    - Four golden JSON fixtures under tests/fixtures/compat/
  affects:
    - tests/test_repository.py (test_expected_files_exist extended)
tech_stack:
  added: []
  patterns:
    - No-shift PATH-shim (PATTERNS lines 202-226): captures full argv including verb+subcommand tokens
    - Separate METER_LOG/JOBS_LOG/TOOL_LOG env routing for unambiguous per-verb capture
    - Synthetic state.db + marker file isolation using tempfile.mkdtemp and shutil.rmtree
    - Pre-seeded jobs ledger (JOB:...:created:) to unblock OUTCOME-04 gate without live API
key_files:
  created:
    - tests/fixtures/compat/meter-completion.golden.json
    - tests/fixtures/compat/jobs-create.golden.json
    - tests/fixtures/compat/jobs-outcome.golden.json
    - tests/fixtures/compat/meter-tool-event.golden.json
    - tests/_compat_helpers.py
    - tests/test_compat_meter_completion.py
    - tests/test_compat_jobs_create.py
    - tests/test_compat_jobs_outcome.py
    - tests/test_compat_meter_tool_event.py
  modified:
    - tests/test_repository.py
decisions:
  - "No-shift shim design: build_shim captures full argv starting with verb token so __verb/__subcommand golden assertions are meaningful"
  - "Separate log routing (METER_LOG/JOBS_LOG/TOOL_LOG) via bash env var cascade eliminates cross-verb capture noise"
  - "Task+job marker pair required for --agentic-job-id: task marker gets owning_job_id from job marker appearing after it in file order (D-11/D-12)"
  - "started_at == ended_at = 1715514000.0 (April 2024) for deterministic --request-duration 0 and settle-seconds filter bypass"
  - "Pre-seeded jobs ledger satisfies OUTCOME-04 gate without live API call"
metrics:
  duration: "~25 minutes"
  completed: "2026-05-23"
  tasks_completed: 7
  files_changed: 10
---

# Phase 20 Plan 01: COMPAT-01 Golden-Argv Wire-Shape Fixtures Summary

COMPAT-01 byte-identical wire contract enforced: four golden-argv CI tests (one per verb) prove that the v1.3 install emits the same argv shapes for `revenium meter completion`, `revenium jobs create`, `revenium jobs outcome`, and `revenium meter tool-event` as v1.2 did. Test count grows from 114 to 118; full suite stays green.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create four golden JSON fixtures | eaa1b3b | tests/fixtures/compat/*.golden.json |
| 2 | Create _compat_helpers.py shared module | 369a487 | tests/_compat_helpers.py |
| 3 | Create test_compat_meter_completion.py | 8169fba | tests/test_compat_meter_completion.py |
| 4 | Create test_compat_jobs_create.py | e9132de | tests/test_compat_jobs_create.py |
| 5 | Create test_compat_jobs_outcome.py | 5f4cd9d | tests/test_compat_jobs_outcome.py |
| 6 | Create test_compat_meter_tool_event.py | ebdbb6c | tests/test_compat_meter_tool_event.py |
| 7 | Extend test_expected_files_exist with golden fixtures | 9081c4e | tests/test_repository.py |

Note: Tasks 1 and 2 were completed by a prior executor (commits eaa1b3b and 369a487). Tasks 3-7 were completed in this execution wave.

## What Was Built

Four COMPAT-01 golden-argv test files plus a shared helper module assert that the argv shapes emitted by `hermes-report.sh` and `tool-event-report.sh` are byte-identical to the documented v1.2 wire contract.

### Golden Fixtures

Each golden encodes one canonical happy-path invocation per D-03 with three sections:
- `exact_match_fields`: byte-identical field values including `__verb`/`__subcommand` verb-identity assertions
- `pattern_fields`: ISO-8601 regex for timestamps (broad form per Pitfall 3)
- `forbidden_fields`: `--budget-id` and `--alert-id` on every golden (defense-in-depth COMPAT-04 spirit); `--error-message` added to `meter-tool-event.golden.json` (success branch must not carry it)

### Shared Helper Module (`tests/_compat_helpers.py`)

Exports: `argv_to_flags`, `assert_argv_matches_golden`, `load_golden`, `build_shim`, `build_state_db`, `run_script`, `FIXTURES_DIR`, `SCRIPTS_DIR`.

**No-shift shim design:** `build_shim` writes a shim that does NOT shift past verb/subcommand. Every captured argv begins with the verb token (`meter`, `jobs`). This is the critical difference from the analog's shifting shim — `__verb` and `__subcommand` are always populated in `argv_to_flags` output, making verb-identity assertions meaningful.

**Guardrails branch:** The shim includes `guardrails) exit 0 ;;` so `has_guardrails_cli()` probes (`revenium guardrails budget-rules --help` and `revenium guardrails enforcement-events --help`) succeed under the shim per RESEARCH Pitfall 1 extension.

### Test Details

**test_compat_meter_completion.py:**
- Two-line marker file: task marker (gets owning_job_id via D-11 resolution) + job marker (kind="job", agentic_job_id=compat-job-001)
- `started_at == ended_at == 1715514000.0` gives deterministic `--request-duration 0`
- Separate `METER_LOG`/`JOBS_LOG` routing; asserts exactly 1 meter completion invocation

**test_compat_jobs_create.py:**
- Same two-line marker pattern; asserts jobs create argv from `JOBS_LOG`
- `source='test'` column supplies `--environment test` in jobs create

**test_compat_jobs_outcome.py:**
- Pre-seeds `revenium-jobs.ledger` with `JOB:compat-job-001:created:1715516001.000` to unblock OUTCOME-04 gate
- Job marker status=SUCCESS populates outcome queue; asserts `--outcome-type CONVERTED` and `__positional_args=['compat-job-001']`
- Exactly one outcome invocation (idempotency invariant)

**test_compat_meter_tool_event.py:**
- Exercises `tool-event-report.sh` (not hermes-report.sh)
- Asserts bare `--success` stores as `True` (not string `'true'`) proving the bare-flag invariant from tool-event-report.sh:136
- `--error-message` is absent (forbidden_field defense)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test fixture for meter completion: started_at/ended_at discrepancy**
- **Found during:** Task 3 first run
- **Issue:** `started_at: 1715514000.0`, `ended_at: 1715515001.0` gave `--request-duration 1001000` (ms), not `0` as golden expected
- **Fix:** Set `ended_at = started_at = 1715514000.0` so `duration_ms = 0`
- **Files modified:** tests/test_compat_meter_completion.py

**2. [Rule 1 - Bug] Fixed test fixture for meter completion: marker structure for --agentic-job-id**
- **Found during:** Task 3 second run
- **Issue:** Single combined marker with `agentic_job_id` field was treated as a task marker; the script reads `owning_job_id` (set via D-11 deferred resolution from a separate `kind:"job"` marker)
- **Fix:** Split into two JSONL lines: task marker (no kind field) followed by job marker (kind="job")
- **Files modified:** tests/test_compat_meter_completion.py

**3. [Rule 1 - Bug] Fixed test for meter completion: multiple invocations in single log**
- **Found during:** Task 3 third run
- **Issue:** `jobs create` and `meter completion` both captured in same `INVOCATIONS_LOG`, giving `len(invocations) == 2` instead of 1
- **Fix:** Added separate `METER_LOG`, `JOBS_LOG` env vars to env; read `meter_log` directly to count meter invocations
- **Files modified:** tests/test_compat_meter_completion.py

**4. [Rule 3 - Blocker] Resume base mismatch: worktree was forked from wrong HEAD**
- **Found during:** Resume verification
- **Issue:** Worktree HEAD was at `main` (1ee6ab9), but Tasks 1+2 are on `feat/v1.3-guardrails-migration` (fcd9237)
- **Fix:** `git reset --hard fcd9237` to rebase worktree onto the correct resume point
- **Impact:** Safe — no prior commits on the agent branch existed before the reset

## Known Stubs

None. All four compat tests exercise real script invocations with deterministic synthetic data.

## Threat Flags

None. Tests are isolated to per-test tmpdir (tempfile.mkdtemp, cleaned in finally). No new production code changes; no new network surface.

## Self-Check

Files created/modified:

- tests/fixtures/compat/meter-completion.golden.json: present (eaa1b3b)
- tests/fixtures/compat/jobs-create.golden.json: present (eaa1b3b)
- tests/fixtures/compat/jobs-outcome.golden.json: present (eaa1b3b)
- tests/fixtures/compat/meter-tool-event.golden.json: present (eaa1b3b)
- tests/_compat_helpers.py: present (369a487)
- tests/test_compat_meter_completion.py: present (8169fba)
- tests/test_compat_jobs_create.py: present (e9132de)
- tests/test_compat_jobs_outcome.py: present (5f4cd9d)
- tests/test_compat_meter_tool_event.py: present (ebdbb6c)
- tests/test_repository.py: modified (9081c4e)

Full suite: 118 tests, all green.
