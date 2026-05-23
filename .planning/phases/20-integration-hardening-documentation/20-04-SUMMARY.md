---
phase: 20-integration-hardening-documentation
plan: 04
subsystem: live-host-verification
tags: [live-host, mac-studio, ssh, sc6, audit-01, milestone-close, v1.3]
dependency_graph:
  requires: [20-01, 20-02, 20-03, 19-12]
  provides: [sc6-verification-evidence, milestone-v1.3-gate]
  affects: [phase-20-close-gate]
tech_stack:
  added: []
  patterns: [ssh-driven-verification, synthetic-fixture-injection]
key_files:
  created:
    - .planning/phases/20-integration-hardening-documentation/20-VERIFICATION.md
  modified: []
decisions:
  - "AUDIT-01 live API breach unachievable on demo account: enforcement engine currentValue=0 (shadowMode forced, no subscriber-attributable spend). (no events) fallback is correct. Documented as D-20-04-01, carried to v1.4."
  - "118 tests pass on Python 3.13.2 — Mac Studio upgraded from 3.9.6 since Phase 19."
  - "Scenario #1 git clone substituted with cp -R (no GitHub SSH key on Mac Studio); all README script steps executed end-to-end."
metrics:
  duration: 120m
  completed_date: 2026-05-23
  tasks_completed: 5
  files_changed: 1
---

# Phase 20 Plan 04: Live-Host Verification Summary

**One-liner:** Six of 7 SC #6 scenarios PASS on Mac Studio (bash 3.2.57, Python 3.13.2); AUDIT-01 enforcement-event live breach partial due to demo account shadow-mode constraint.

**Deliverable:** `.planning/phases/20-integration-hardening-documentation/20-VERIFICATION.md` — the primary verification document with all evidence, per D-12.

## Summary

| Metric | Value |
|--------|-------|
| Scenarios passed | 6/7 (Scenario #5 PARTIAL — see D-20-04-01) |
| Tests on Mac Studio | 118/118 |
| AUDIT-01 status | PARTIAL — (no events) fallback confirmed correct; field names unconfirmed live |
| Mac Studio state | clean (halted: false, rule 4vK3Zv operational) |
| Commit | f63a82f |

## Deviations from Plan

### AUDIT-01 (D-20-04-01): Demo account enforcement engine shows currentValue: 0

- **Found during:** Task 3 (Scenario #5 breach attempt)
- **Issue:** The `OpenClaw Demo` Revenium tenant enforces `shadowMode: true` on all rules. The enforcement engine shows `currentValue: 0` regardless of `revenium meter completion` calls. No enforcement events have been produced on this account. A real `HALT_TRANSITION=true` cannot be driven.
- **Fix:** N/A — infrastructure constraint. The `(no events)` fallback in guardrail-check.sh:280 is correct for empty-array API response. Field names `timestamp` and `summary` remain LOW-confidence (unit-tested only).
- **Disposition:** Carried to v1.4. Re-test on a production account with real subscriber spend.

## Self-Check

- VERIFICATION.md exists at planned path: FOUND
- All 7 scenario evidence blocks present: YES (6 PASS, 1 PARTIAL)
- Commit f63a82f exists: YES
- Mac Studio guardrail-status.json shows halted:false: YES
