---
phase: 19-guardrail-check-hook-repointing-enforcement-event-surfacing
plan: 01
subsystem: tests
tags: [wave-0, nyquist, tdd, test-scaffolding, guardrails]
dependency_graph:
  requires: []
  provides: [wave-0-test-stubs, sc7-gate]
  affects: [tests/test_repository.py]
tech_stack:
  added: []
  patterns: [subprocess-run-stub-on-path, tempfile-isolation, stub-cli-bash]
key_files:
  created: []
  modified:
    - tests/test_repository.py
decisions:
  - SC-7 gate scans only .sh/.py/.yml/.yaml/.json (not .md); halt-survivability.md prose excluded per D-16/19-11
  - test_no_legacy_budget_status_references added adjacent to test_no_legacy_branding_left
  - _make_revenium_stub helper centralizes stub-CLI construction for tests 1-5
  - Existing halted tests (E/F) repointed in-place (renamed via docstring only; no method rename)
  - test_revenium_classifier_job_step7_single_goal edit I makes it error on AttributeError (Wave 0 RED, acceptable)
metrics:
  duration: ~8m
  completed: 2026-05-21
  tasks_completed: 2
  files_modified: 1
---

# Phase 19 Plan 01: Wave 0 Test Scaffolding Summary

## One-liner

Added 12 new Phase 19 behavioral test stubs and repointed 9 legacy budget-status tests to guardrail-status fixtures; all red until implementation waves 19-02 through 19-11 land.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add Phase 19 new behavioral test method stubs | 9a34ad7 | tests/test_repository.py |
| 2 | Repoint legacy budget-status tests and add SC-7 grep test | 6cb6a18 | tests/test_repository.py |

## What Was Built

### Task 1: 12 New Test Methods (Wave 0 RED stubs)

Added to `tests/test_repository.py` after `test_pre_tool_call_halted_blocks`:

1. `_make_revenium_stub` — shared helper that writes a stub `revenium` binary into a tempdir, handling all 4 Phase 19 subcommands (config show, enforcement-rules get, budget-rules list, enforcement-events list). Accepts `events_fail=True` for AUDIT-02 graceful-degradation tests.

2. `test_guardrail_check_writes_status_file` — ENF-02, ENF-03, ENF-04: runs `guardrail-check.sh` with a non-breached stub; asserts `guardrail-status.json` written with 10-key ENF-04 rule schema and string-hash `ruleId` from budget-rules join.

3. `test_guardrail_check_halt_transition` — ENF-05, AUDIT-01: breached stub; asserts `halted:true`, `haltedRule`, `HALT_TRANSITION=true` in stdout, and `EVENT_TS`/`EVENT_SUMMARY` embedding from enforcement-events list (revised 19-05 contract).

4. `test_guardrail_check_halt_carry_forward` — ENF-05: pre-seeds `halted:true` with a known `haltedAt`; asserts it's byte-identical after re-run; asserts `HALT_TRANSITION=true` absent.

5. `test_guardrail_check_no_rules_empty` — ENF-02: empty `ruleIds`; asserts `rules:[]`, `halted:false`.

6. `test_guardrail_check_audit_api_fallback` — AUDIT-02: enforcement-events stub exits 1; asserts status file still written with `halted:true`, and stdout contains `EVENT_TS=(unavailable)` / `EVENT_SUMMARY=(unavailable)`.

7. `test_pre_llm_call_halted_emits_guardrail_halt_string` — HOOK-01, HOOK-03: D-04 `haltedRule` fixture; asserts D-01 halt string template with `Guardrail halt active — rule 'Engineering Budget'`, TOTAL_COST, MONTHLY, 102.5, 100.0.

8. `test_pre_tool_call_halted_blocks_guardrail` — HOOK-01: same fixture; asserts `action:block` and D-01 halt string in message.

9. `test_pre_llm_call_warn_band_emits_stderr` — HOOK-02: warn-state rule; asserts `{}` stdout, `Guardrail warn:` in stderr, flag file at `WARN_FLAGS_DIR/<sid>__<ruleId>.flag`.

10. `test_pre_llm_call_warn_rate_limit` — HOOK-02: two consecutive runs; asserts first run emits warn, second run suppressed by sentinel.

11. `test_clear_halt_bare` — ENF-06: two blocked rules; asserts all cleared, `halted:false`, `haltedAt`/`haltedRule` absent.

12. `test_clear_halt_rule_id` — ENF-06: `--rule-id ruleId-A`; asserts ruleId-A cleared, ruleId-B still blocked, `halted:true`, `haltedRule` repoints to ruleId-B.

13. `test_clear_halt_rule_id_not_blocked` — ENF-06: non-blocked rule; asserts exit 0 with info message, file unchanged.

### Task 2: Repointing and SC-7 Gate

**A. test_expected_files_exist**: Removed `SKILL / 'scripts' / 'budget-check.sh'`; added `SKILL / 'scripts' / 'guardrail-check.sh'` (goes RED: script doesn't exist yet).

**B. test_runtime_paths_are_hermes_native**: Added Phase 19 assertions for `WARN_FLAGS_DIR=`, `markers/.warn`, WARN_FLAGS_DIR regex; plus `assertNotIn('BUDGET_STATUS_FILE=')` and `assertNotIn('budget-status.json')` (goes RED: common.sh still has BUDGET_STATUS_FILE and no WARN_FLAGS_DIR).

**C. test_cron_sh_loops_per_REVENIUM_CRON_LOOP_COUNT**: Stub tuple and ordering assertion both updated from `budget-check.sh` to `guardrail-check.sh` (goes RED: cron.sh still calls budget-check.sh).

**D. test_pre_llm_call_fail_open**: `budget-status.json` → `guardrail-status.json`; `BUDGET_STATUS_FILE` → `GUARDRAIL_STATUS_FILE`. (still PASSES because hook fails-open on missing BUDGET_STATUS_FILE env var — fail-open is the expected behavior in both cases)

**E. test_pre_llm_call_halted_emits_halt_string**: D-04 haltedRule fixture; D-01 halt string assertions replacing legacy `Budget enforcement halt is active.` (goes RED: hook still uses budget-status.json).

**F. test_pre_tool_call_halted_blocks**: guardrail-status.json fixture; D-01 halt string assertion added (goes RED: hook still uses budget-status.json).

**G. test_revenium_classifier_halt_unclassified**: `budget-status.json` fixture → `guardrail-status.json`; `_budget_halted()` → `_guardrail_halted()` (goes RED: classifier.py not yet updated).

**H. test_revenium_classifier_halt_failopen_on_missing_file**: `BUDGET_STATUS_FILE` → `GUARDRAIL_STATUS_FILE`; `_budget_halted` → `_guardrail_halted` (goes RED: classifier.py not yet updated).

**I. test_revenium_classifier_job_step7_single_goal** (line ~8840): `handler.BUDGET_STATUS_FILE` → `handler.GUARDRAIL_STATUS_FILE` (goes RED with AttributeError: classifier.py not yet updated).

**J. Around line 2370**: `budget-status.json` fixture → `guardrail-status.json` in G-02 regression guard test.

**K. NEW: test_no_legacy_budget_status_references**: SC-7 gate scans `skills/` for `.sh/.py/.yml/.yaml/.json` files containing `budget-check|budget-status`; fails against today's code (budget-check.sh and budget-status.json still present).

## Test Suite State

| Metric | Before | After |
|--------|--------|-------|
| Total tests | 101 | 114 |
| Passing | 101 | 93 |
| Failing | 0 | 21 |
| Red tests added by this plan | — | 21 |

**The 21 red tests are intentional Wave 0 behavior.** They will be made green by plans 19-02 through 19-11 as each implementation wave lands.

## Deviations from Plan

**1. [Rule 1 - Bug] Task 2G also updated `_guardrail_halted()` call in test body**

- **Found during:** Task 2, editing test_revenium_classifier_halt_unclassified
- **Issue:** Plan's Edit G specified updating the fixture but the test body also called `handler._budget_halted()` which needed to become `handler._guardrail_halted()`
- **Fix:** Updated `self.assertTrue(handler._budget_halted())` to `self.assertTrue(handler._guardrail_halted())`
- **Files modified:** tests/test_repository.py
- **Commit:** 6cb6a18

**2. [Rule 2 - Auto-add] task_revenium_classifier_job_step7_single_goal becomes RED (AttributeError)**

- **Found during:** Task 2, Edit I
- **Issue:** The edit to `handler.GUARDRAIL_STATUS_FILE` causes an `AttributeError` (not `AssertionError`) when classifier.py still has `BUDGET_STATUS_FILE`. The plan says tests should FAIL ASSERTION not error on import — this is a runtime AttributeError during test body, not an import error, so it satisfies the spirit of the Wave 0 requirement.
- **Fix:** Accepted as expected Wave 0 RED behavior. The test will become green when Phase 19 implementation updates classifier.py.
- **Files modified:** none additional

## Self-Check

- [x] tests/test_repository.py modified with 12 new methods and 9 repoints
- [x] 114 total tests discovered and run (no import errors)
- [x] 21 red tests (intentional Wave 0)
- [x] test_no_legacy_budget_status_references added (SC-7 gate)
- [x] Commits 9a34ad7 and 6cb6a18 exist

## Self-Check: PASSED
