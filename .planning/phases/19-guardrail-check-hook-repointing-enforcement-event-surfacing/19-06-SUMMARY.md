---
phase: 19-guardrail-check-hook-repointing-enforcement-event-surfacing
plan: "06"
subsystem: cron-pipeline
tags: [guardrails, enforcement, cron-stage, repointing]
dependency_graph:
  requires: [19-05]
  provides: [cron.sh wired to guardrail-check.sh]
  affects: [skills/revenium/scripts/cron.sh]
tech_stack:
  added: []
  patterns: [fail-open || true passthrough, cron inner-pipeline stage swap]
key_files:
  created: []
  modified:
    - skills/revenium/scripts/cron.sh
decisions:
  - "Comments referencing budget-check.sh updated to avoid grep-count false positives"
metrics:
  duration: ~5min
  completed: "2026-05-21"
  tasks_completed: 1
  files_created: 0
  files_modified: 1
---

# Phase 19 Plan 06: Swap cron.sh second stage to guardrail-check.sh Summary

Single-line swap on cron.sh line 76: `budget-check.sh` replaced with `guardrail-check.sh`, wiring the new Phase 19 status writer into the per-minute cron pipeline with the existing `|| true` fail-open and `"$@"` passthrough preserved.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Swap cron.sh second-stage call from budget-check.sh to guardrail-check.sh | b5c8332 | skills/revenium/scripts/cron.sh |

## Implementation Details

Line 76 of `skills/revenium/scripts/cron.sh` changed from:

```bash
  bash "${SKILL_DIR}/scripts/budget-check.sh" "$@" || true
```

to:

```bash
  bash "${SKILL_DIR}/scripts/guardrail-check.sh" "$@" || true
```

Two comments that previously referenced `budget-check.sh` by name were also updated so that `grep -c "budget-check.sh" skills/revenium/scripts/cron.sh` returns 0 (the plan's verification requirement). The comments now use `guardrail-check.sh` references or generic descriptions:

- Line 11: `"lock spans BOTH hermes-report.sh and budget-check.sh"` → `"lock spans all inner-pipeline invocations"`
- Line 62: comment about `read_config_field` dependency updated to remove `budget-check.sh` reference

All other cron.sh content (flock block, ENV_FILE sourcing, loop-count validation, hermes-report.sh line, setup-guardrails.sh migration stage, tool-event-report.sh line, loop sleep) is byte-identical to the pre-edit file.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Comments contained budget-check.sh references violating grep-count=0 verification**
- **Found during:** Task 1 verification
- **Issue:** Two comment lines in cron.sh retained `budget-check.sh` string, causing `grep -c "budget-check.sh"` to return 2 instead of 0. The plan's verification section requires 0.
- **Fix:** Updated both comments to remove the `budget-check.sh` string. Also updated the guardrail-check.sh reference in the lock comment to a generic description to keep `grep -c "guardrail-check.sh"` at exactly 1 (functional invocation only).
- **Files modified:** `skills/revenium/scripts/cron.sh`
- **Commit:** b5c8332

## Test Results

- `bash -n skills/revenium/scripts/cron.sh` — OK (syntax valid)
- `grep -c "budget-check.sh" skills/revenium/scripts/cron.sh` — 0
- `grep -c "guardrail-check.sh" skills/revenium/scripts/cron.sh` — 1
- `grep -c "tool-event-report.sh" skills/revenium/scripts/cron.sh` — 1 (untouched)
- `grep -c "hermes-report.sh" skills/revenium/scripts/cron.sh` — 1 (untouched)
- `grep -c "setup-guardrails.sh" skills/revenium/scripts/cron.sh` — 1 (Phase 18 stage untouched)
- `test_cron_sh_loops_per_REVENIUM_CRON_LOOP_COUNT` — PASSED (green, was red before this swap)

## Known Stubs

None. This plan makes a single functional change; no placeholder values.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. The swap replaces one subprocess invocation with another in the same trust boundary (same user context, same `|| true` fail-open). No threat flags.

## Self-Check

### Modified files

- `skills/revenium/scripts/cron.sh` — FOUND

### Commits exist

- b5c8332 — FOUND

## Self-Check: PASSED
