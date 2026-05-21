---
phase: 19-guardrail-check-hook-repointing-enforcement-event-surfacing
plan: "04"
subsystem: revenium-classifier-plugin
tags: [classifier, guardrail-repoint, sc7, enf-03, phase-19]
dependency_graph:
  requires: [19-01]
  provides: [classifier-guardrail-repoint]
  affects: [skills/revenium/plugins/revenium-classifier/classifier.py]
tech_stack:
  added: []
  patterns: [fail-open-exception-guard, path-constant-rename]
key_files:
  created: []
  modified:
    - skills/revenium/plugins/revenium-classifier/classifier.py
decisions:
  - "Renamed BUDGET_STATUS_FILE to GUARDRAIL_STATUS_FILE pointing at guardrail-status.json (ENF-03)"
  - "Renamed _budget_halted() to _guardrail_halted() preserving identical fail-open semantics"
  - "Comment on line 43 retains 'renamed from BUDGET_STATUS_FILE' for traceability; does not trigger SC-7 grep (regex: budget-check|budget-status)"
metrics:
  duration: "5 minutes"
  completed: "2026-05-21"
  tasks_completed: 1
  tasks_total: 1
---

# Phase 19 Plan 04: Repoint classifier.py to guardrail-status.json Summary

Renamed `BUDGET_STATUS_FILE` constant and `_budget_halted()` function in classifier.py to `GUARDRAIL_STATUS_FILE` / `_guardrail_halted()`, repointing from `budget-status.json` to `guardrail-status.json` with identical fail-open semantics, closing the SC-7 clean-break gate for the classifier plugin.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Repoint classifier.py constant and function name to guardrail-status | 0bc6f7d | skills/revenium/plugins/revenium-classifier/classifier.py |

## Changes Made

### Task 1: Repoint classifier.py constant and function to guardrail-status

**Constant rename (line 43):**
- `BUDGET_STATUS_FILE = STATE_DIR / "budget-status.json"` → `GUARDRAIL_STATUS_FILE = STATE_DIR / "guardrail-status.json"`
- Comment added: `# Phase 19 (ENF-03): renamed from BUDGET_STATUS_FILE, repointed to guardrail-status.json`

**Function rename (lines 571-578):**
- `def _budget_halted()` → `def _guardrail_halted()`
- Docstring updated: "Read guardrail-status.json and return True if halted."
- Body: `BUDGET_STATUS_FILE.read_text(...)` → `GUARDRAIL_STATUS_FILE.read_text(...)`
- Fail-open `try/except Exception: return False` preserved exactly (D-08 invariant)

**Docstring update (line 812):**
- `_budget_halted` → `_guardrail_halted` in the `run_classification_async` docstring

**Call site 1 (line 835 — budget gate, Step 4):**
- `if _budget_halted():` → `if _guardrail_halted():`

**Call site 2 (line 870 — job-inference gate, Step 7):**
- `and not _budget_halted()` → `and not _guardrail_halted()`

**Inline comment (line 864):**
- "not budget-halted" → "not guardrail-halted"

## Verification Results

```
grep -c '_guardrail_halted' classifier.py  # returns 5 (def + docstring + 2 call sites + constant usage)
grep 'budget-check|budget-status' classifier.py  # returns 0 matches (SC-7 gate clean)
python3 -m unittest test_revenium_classifier_halt_unclassified  # OK
python3 -m unittest test_revenium_classifier_halt_failopen_on_missing_file  # OK
```

Both target tests pass. `classifier.py` is not in the `test_no_legacy_budget_status_references` offenders list (pre-existing failures in that test are from other scripts out of scope for this plan).

## Deviations from Plan

None — plan executed exactly as written.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. The change is a pure rename of an in-process constant and function; the file it reads (`guardrail-status.json`) was already declared in the threat model for this plan (T-19-04-01, T-19-04-02).

## Known Stubs

None.

## Self-Check: PASSED

- File exists: `skills/revenium/plugins/revenium-classifier/classifier.py` — FOUND
- Commit `0bc6f7d` exists — FOUND
- `GUARDRAIL_STATUS_FILE` in classifier.py — FOUND
- `_guardrail_halted` in classifier.py (def + 2 call sites) — FOUND
- No `budget-check|budget-status` in classifier.py — CONFIRMED
