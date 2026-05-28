---
phase: 19-guardrail-check-hook-repointing-enforcement-event-surfacing
plan: 11
subsystem: cron-pipeline
tags: [sc-7, enf-01, enf-03, clean-break, budget-check-deletion]
dependency_graph:
  requires: [19-04, 19-05, 19-06, 19-07, 19-08, 19-09, 19-10]
  provides: [sc-7-gate-green, budget-check-deleted, legacy-cleanup-wired]
  affects: [skills/revenium/scripts/guardrail-check.sh, tests/test_repository.py]
tech_stack:
  added: []
  patterns: [git-rm-for-intentional-deletion, idempotent-cleanup-guard]
key_files:
  created: []
  modified:
    - skills/revenium/scripts/guardrail-check.sh
    - skills/revenium/scripts/install-cron.sh
    - skills/revenium/scripts/setup-guardrails.sh
    - tests/test_repository.py
  deleted:
    - skills/revenium/scripts/budget-check.sh
decisions:
  - "SC-7 gate passes by excluding guardrail-check.sh from test scan (the rm -f line is the cleanup mechanism itself, not a legacy consumer)"
  - "test_no_legacy_budget_status_references scope: .sh/.py/.yml/.yaml/.json only (no .md); guardrail-check.sh excluded; halt-survivability.md deferred to Phase 20 DOCS-03"
  - "Probe 2 confirmed: halt-survivability.md has 9 matches, Phase 20 DOCS-03 is still queued"
metrics:
  duration_minutes: 5
  completed: "2026-05-21T18:31:01Z"
  tasks_completed: 1
  tasks_total: 1
  files_changed: 5
---

# Phase 19 Plan 11: ENF-01/ENF-03 Clean Break — Delete budget-check.sh, Wire Legacy Cleanup Summary

Deleted `budget-check.sh` (fully superseded by `guardrail-check.sh`), added idempotent `budget-status.json` cleanup block to `guardrail-check.sh` after atomic write, fixed SC-7 violations in two comment strings, and updated the SC-7 test to exclude `guardrail-check.sh` (the intentional cleanup carrier). All 114 tests pass; SC-7 gate green.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Delete budget-check.sh and add runtime budget-status.json cleanup to guardrail-check.sh | 23debe1 | skills/revenium/scripts/budget-check.sh (deleted), guardrail-check.sh, install-cron.sh, setup-guardrails.sh, tests/test_repository.py |

## What Was Built

- **Deletion (ENF-01):** `skills/revenium/scripts/budget-check.sh` removed via `git rm`. The file had 118 lines implementing the old budget-check cron stage; every function it provided is now handled by `guardrail-check.sh` (wired in Wave 6 plan 19-06).

- **Legacy cleanup (ENF-03):** `guardrail-check.sh` extended with a one-time cleanup block at line 251-253. After the atomic `os.replace` write of `guardrail-status.json` completes (and before the `HALT_TRANSITION` evaluation block), the script checks for and removes any stale `budget-status.json`. The guard `[[ -f ... ]]` makes it idempotent — no log spam on subsequent ticks.

- **SC-7 violations in comments fixed (Rule 1):**
  - `setup-guardrails.sh:148`: comment "verbatim from budget-check.sh" updated to "shared helper"
  - `install-cron.sh:38`: usage text "refreshes budget-status.json" updated to "refreshes guardrail-status.json"

- **Test updated:** `test_no_legacy_budget_status_references` in `tests/test_repository.py` given `excluded_names = {'guardrail-check.sh'}` with an explanatory comment. The cleanup lines in `guardrail-check.sh` are the deletion mechanism, not legacy code; scanning them would defeat the guard's purpose.

## Verification Results

| Check | Result |
|-------|--------|
| `test ! -f skills/revenium/scripts/budget-check.sh` | PASS (file absent) |
| SC-7 grep on code-bearing files (excl. guardrail-check.sh) | PASS - 0 matches |
| Probe 1: SC-7 scope comment in test_repository.py | PASS - line 135 |
| Probe 2: halt-survivability.md has legacy strings (Phase 20 queued) | PASS - 9 matches |
| `test_expected_files_exist` | PASS |
| `test_no_legacy_budget_status_references` | PASS |
| `bash -n` syntax check all modified scripts | PASS |
| Full test suite (114 tests) | PASS |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] SC-7 violations in comment strings (setup-guardrails.sh, install-cron.sh)**
- **Found during:** Task 1, running the SC-7 grep before committing
- **Issue:** `setup-guardrails.sh:148` contained `budget-check.sh` in a comment; `install-cron.sh:38` contained `budget-status.json` in usage text. The `test_no_legacy_budget_status_references` test scans full file text (not stripping comments), so both would have failed.
- **Fix:** Updated `setup-guardrails.sh` comment to "shared helper"; updated `install-cron.sh` usage text to `guardrail-status.json`.
- **Files modified:** `skills/revenium/scripts/setup-guardrails.sh`, `skills/revenium/scripts/install-cron.sh`
- **Commit:** 23debe1

**2. [Rule 1 - Bug] test_no_legacy_budget_status_references would fail on guardrail-check.sh cleanup lines**
- **Found during:** Task 1, after adding the cleanup block and running the test
- **Issue:** The plan required adding `rm -f "${STATE_DIR}/budget-status.json"` to `guardrail-check.sh`, but the SC-7 test scans the full file text of all `.sh` files including `guardrail-check.sh`. The plan's verification grep explicitly excluded `guardrail-check.sh`; the test did not.
- **Fix:** Added `excluded_names = {'guardrail-check.sh'}` with an explanatory comment to the test. The exclusion is correct: the rm -f line is the cleanup mechanism itself (not a legacy consumer), exactly as the plan's verification section documented.
- **Files modified:** `tests/test_repository.py`
- **Commit:** 23debe1

## SC-7 Final State

The SC-7 gate (grep on code-bearing files) now passes cleanly:

```
grep -r 'budget-check|budget-status' skills/ \
  --include="*.sh" --include="*.py" --include="*.yml" \
  --include="*.yaml" --include="*.json" \
  | grep -v guardrail-check.sh
=> 0 matches
```

`guardrail-check.sh` carries the intentional `rm -f budget-status.json` cleanup (3 lines), which are excluded from the gate as documented in the plan and test comment.

`halt-survivability.md` retains 9 legacy string matches — this is the Phase 20 DOCS-03 backlog item; the .md exclusion is deliberate, auditable, and ratified in this plan's action (C).

## Known Stubs

None.

## Threat Flags

None beyond the threat model documented in the plan (T-19-11-01 through T-19-11-04).

## Self-Check: PASSED

- [x] `skills/revenium/scripts/budget-check.sh` does not exist on disk
- [x] `skills/revenium/scripts/guardrail-check.sh` contains `rm -f "${STATE_DIR}/budget-status.json"` at line 252
- [x] Commit 23debe1 exists: `git log --oneline | grep 23debe1`
- [x] All 114 tests pass: `python3 -m unittest discover -s tests -p 'test_*.py'`
