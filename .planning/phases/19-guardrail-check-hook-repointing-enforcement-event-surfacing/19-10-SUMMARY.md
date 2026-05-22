---
phase: 19-guardrail-check-hook-repointing-enforcement-event-surfacing
plan: 10
subsystem: skill-prompt
tags: [SKILL.md, halt-check, guardrail-status, prompt-rewrite, v1.3]
dependency_graph:
  requires: [19-05, 19-07, 19-08, 19-09]
  provides: [HOOK-03]
  affects: [skills/revenium/SKILL.md]
tech_stack:
  added: []
  patterns: [guardrail-status.json-halt-check, D-01-halt-string, haltedRule-substitution]
key_files:
  created: []
  modified:
    - skills/revenium/SKILL.md
decisions:
  - "SKILL.md HALT CHECK + Budget Check Procedure block replaced with v1.3 Guardrail Check Procedure reading guardrail-status.json"
  - "D-01 halt string updated to include haltedRule fields (name, metricType, windowType, currentValue, hardLimit)"
  - "exceeded-branch interactive prompt (D-14) removed — no exceeded field in v1.3 schema"
  - "All 7 budget-status.json references in SKILL.md replaced with guardrail-status.json"
metrics:
  duration: "~10 minutes"
  completed: "2026-05-21T18:24:09Z"
  tasks_completed: 1
  files_modified: 1
---

# Phase 19 Plan 10: SKILL.md HALT CHECK + Procedure Rewrite Summary

SKILL.md lines 24-95 rewritten from v1.2 Budget Check Procedure to v1.3 Guardrail Check Procedure reading guardrail-status.json with D-01 halt string citing haltedRule fields.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Rewrite SKILL.md HALT CHECK + Procedure block + frontmatter + Runtime/Verification/Last-Word references | 153171e | skills/revenium/SKILL.md |

## What Was Built

Seven targeted edits to `skills/revenium/SKILL.md`:

1. **Frontmatter description (line 3):** Repointed from `budget-status.json` to `guardrail-status.json`; "budget check" → "guardrail check"; "token spend limits" → "guardrails-native budget rules"; "budget overrun" → "guardrail block".

2. **Lines 24-95 — HALT CHECK + Procedure block (full rewrite per D-12..D-15):**
   - `## HALT CHECK — DEFENSE-IN-DEPTH BACKSTOP` heading preserved (test_prompt_ordering_invariant anchor)
   - Description updated from "Budget-halt enforcement" to "Guardrail enforcement"
   - Halt condition reads `guardrail-status.json` and `haltedRule` block; D-01 halt string in blockquote: `Guardrail halt active — rule '[haltedRule.name]' ([haltedRule.metricType], [haltedRule.windowType]) at [haltedRule.currentValue] of [haltedRule.hardLimit] hard-limit. To resume: \`bash ~/.hermes/skills/revenium/scripts/clear-halt.sh\``
   - `## Budget Check Procedure` renamed to `## Guardrail Check Procedure`
   - Procedure simplified: read guardrail-status.json, extract `halted`, evaluate halted-yes-or-no (no exceeded branch, no autonomousMode check — D-14 dropped)
   - Missing-file section renamed `### If guardrail-status.json is missing or unreadable`

3. **Runtime State block (line 102):** `budget-status.json` → `guardrail-status.json`.

4. **`/revenium` command behavior (line 169):** Removed `(read from guardrail-status.json when Phase 19 ships it; until then, fall back to reading budget-status.json if present)` → `(read from guardrail-status.json)`.

5. **Verification block (line 207):** `cron.sh updates budget-status.json` → `cron.sh updates guardrail-status.json`.

6. **Verification last bullet (line 209):** "When over budget with autonomous mode on, budget-status.json..." → "When a guardrail rule is blocked with autonomous mode on, guardrail-status.json flips to halted: true and Hermes sends the halt notification (including the most recent enforcement-events list entry)..."

7. **LAST WORD checklist item 1 (line 242):** `budget-status.json` → `guardrail-status.json`.

## Verification Results

```
grep -c "budget-status.json" skills/revenium/SKILL.md  → 0
grep -c "guardrail-status.json" skills/revenium/SKILL.md  → 12
grep -c "Guardrail halt active" skills/revenium/SKILL.md  → 1
grep -c "HALT CHECK" skills/revenium/SKILL.md  → 3
grep -c "haltedRule" skills/revenium/SKILL.md  → 5

test_prompt_ordering_invariant  → PASS
test_no_legacy_branding_left  → PASS
test_job_marker_snippets_resolve_session_id_from_session_files  → PASS
test_skill_frontmatter_has_hermes_metadata  → PASS
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Extra budget-status.json reference in Setup Flow section**
- **Found during:** Task 1 verification
- **Issue:** Line 148 in the Setup Flow section ("This adds a per-minute cron entry that ships token deltas from ~/.hermes/state.db to Revenium and refreshes `budget-status.json`.") was not listed in the plan's change list (plan listed lines 102, 169, 207, 209, 242)
- **Fix:** Updated to `guardrail-status.json` so the install-cron.sh description accurately reflects the v1.3 cron output
- **Files modified:** skills/revenium/SKILL.md
- **Commit:** 153171e (included in task commit)

## Known Stubs

None — SKILL.md is a prompt file with no data sourcing.

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes introduced. The only changes are to prose and the status-file references in the agent prompt.

## Self-Check: PASSED

- [x] `skills/revenium/SKILL.md` modified: FOUND
- [x] Commit 153171e: FOUND (`git log --oneline | grep 153171e`)
- [x] `budget-status.json` grep returns 0: CONFIRMED
- [x] `guardrail-status.json` grep returns ≥4: CONFIRMED (12)
- [x] `Guardrail halt active` grep returns ≥1: CONFIRMED (1)
- [x] `HALT CHECK` grep returns ≥1: CONFIRMED (3)
- [x] `haltedRule` grep returns ≥1: CONFIRMED (5)
- [x] All 4 named tests pass: CONFIRMED
