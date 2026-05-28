---
phase: 19-guardrail-check-hook-repointing-enforcement-event-surfacing
plan: 02
subsystem: common-sh-path-declarations
tags: [wave-2, common-sh, warn-flags-dir, budget-status-removal, enf-03, hook-02]
dependency_graph:
  requires: [19-01]
  provides: [WARN_FLAGS_DIR-path-constant]
  affects:
    - skills/revenium/scripts/common.sh
tech_stack:
  added: []
  patterns: [env-overridable-path-default, single-source-of-truth-common-sh]
key_files:
  created: []
  modified:
    - skills/revenium/scripts/common.sh
decisions:
  - WARN_FLAGS_DIR placed immediately after MARKERS_READY_DIR so MARKERS_DIR is defined before it is referenced in the default value
  - WARN_FLAGS_DIR uses MARKERS_DIR variable (not STATE_DIR) in default to keep warn flags co-located with other marker dirs under markers/
  - Comment includes literal markers/.warn so test_runtime_paths_are_hermes_native assertIn passes
  - mkdir -p left unchanged — hooks create WARN_FLAGS_DIR lazily on first use (RESEARCH.md Section 5)
  - BUDGET_STATUS_FILE removed for clean break per ENF-03/D-12 — subsequent plans handle remaining budget-check/budget-status references in other scripts
metrics:
  duration: ~5m
  completed: 2026-05-21
  tasks_completed: 1
  files_modified: 1
---

# Phase 19 Plan 02: WARN_FLAGS_DIR + BUDGET_STATUS_FILE Removal in common.sh Summary

Single-file change: added `WARN_FLAGS_DIR` path constant to `common.sh` immediately after `MARKERS_READY_DIR`, and removed the `BUDGET_STATUS_FILE` declaration as part of the v1.3 guardrails-native clean break.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add WARN_FLAGS_DIR and remove BUDGET_STATUS_FILE in common.sh | 285fd1a | skills/revenium/scripts/common.sh |

## What Was Built

- `WARN_FLAGS_DIR="${REVENIUM_WARN_FLAGS_DIR:-${MARKERS_DIR}/.warn}"` declared as the single source of truth for the Phase 19 D-06 warn-band rate-limit sentinel directory path
- `BUDGET_STATUS_FILE="${STATE_DIR}/budget-status.json"` line removed from common.sh (ENF-03 clean break)
- `mkdir -p` line left unchanged — WARN_FLAGS_DIR is created lazily by hooks on first use

## Verification Results

- `bash -n skills/revenium/scripts/common.sh` returns 0
- `grep WARN_FLAGS_DIR skills/revenium/scripts/common.sh` matches 1 line
- `grep BUDGET_STATUS_FILE skills/revenium/scripts/common.sh` returns no matches
- `grep 'budget-status.json' skills/revenium/scripts/common.sh` returns no matches
- `test_runtime_paths_are_hermes_native` PASSED (includes Phase 19 WARN_FLAGS_DIR assertions at lines 188-194)
- `test_shell_scripts_have_valid_syntax` PASSED
- `test_no_legacy_branding_left` PASSED

## Deviations from Plan

None — plan executed exactly as written. The comment on the WARN_FLAGS_DIR line includes the literal string `markers/.warn` to satisfy the `assertIn('markers/.warn', text)` assertion in `test_runtime_paths_are_hermes_native` (the regex assertion alone would not cover this check since the default value uses `${MARKERS_DIR}/.warn` variable substitution, not the literal string).

## Known Stubs

None.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced.

## Self-Check: PASSED

- File exists: skills/revenium/scripts/common.sh — FOUND
- Commit 285fd1a exists — FOUND via `git rev-parse --short HEAD`
