---
phase: 18-setup-auto-migration-to-ruleids
plan: "04"
subsystem: skill-setup-flow
tags: [SKILL.md, setup-guardrails.sh, ruleIds, alertId-deprecated, references, setup.md]
dependency_graph:
  requires:
    - 18-02 (setup-guardrails.sh with --interactive mode)
  provides:
    - skills/revenium/SKILL.md: Setup section delegates to setup-guardrails.sh --interactive (D-05)
    - skills/revenium/references/setup.md: v1.2 walkthrough retired; pointers to setup-guardrails.sh and docs/migration-guardrails.md
  affects:
    - skills/revenium/SKILL.md
    - skills/revenium/references/setup.md
tech_stack:
  added: []
  patterns:
    - script-delegation (agent invokes script, captures exit code only, writes nothing itself)
    - ruleIds-presence setup-detection gate (Phase 17 config-schema.md contract)
key_files:
  created: []
  modified:
    - skills/revenium/SKILL.md
    - skills/revenium/references/setup.md
decisions:
  - "D-05: SKILL.md Setup section delegates entirely to setup-guardrails.sh --interactive; agent never writes ruleIds or alertId"
  - "Setup detection gate keys on non-empty ruleIds array, not alertId (per Phase 17 config-schema.md contract)"
  - "Legacy alertId disclaimer added to detection gate prose: deprecated, orphaned by auto-migration, ignored for setup gate"
  - "references/setup.md legacy Reset flow dropped (v1.2 semantics do not map to v1.3 two-stage rule model)"
  - "references/setup.md Reconfigure flow rewritten to point at setup-guardrails.sh --interactive re-run UX"
  - "Auto-migration section added to references/setup.md pointing at docs/migration-guardrails.md (plan 18-05)"
metrics:
  duration: "~15 minutes"
  completed: "2026-05-21"
  tasks: 2
  files: 2
requirements: [SETUP-01, SETUP-02, SETUP-03, SETUP-04]
---

# Phase 18 Plan 04: SKILL.md Setup Section Rewrite Summary

Rewrote `skills/revenium/SKILL.md` Setup section and `skills/revenium/references/setup.md` to delegate all rule-creation logic to `setup-guardrails.sh --interactive`. The agent's role in the Setup Flow collapses from 13 steps (direct `alerts budget create` → `alertId` write) to 4 steps (verify CLI credentials, run script, capture exit code, install cron+hooks).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Rewrite SKILL.md Setup section + /revenium block + Script Entry Points | 86111ff | skills/revenium/SKILL.md |
| 2 | Rewrite references/setup.md Initial-setup + Reset + Reconfigure sections | 4cef5d2 | skills/revenium/references/setup.md |

## SKILL.md Line Count Delta

| | Lines |
|-|-------|
| Before | 318 |
| After | 246 |
| Delta | **-72 lines** |

The Setup Flow shrank from the 13-step, 125-line block to a 4-step, ~50-line block. The target was ~-100 lines; the actual reduction is -72 because the new Step 3 includes explicit exit-code handling prose (three exit-code branches) that is not merely a pointer.

## Halt-String Preservation Proof

The verbatim halt string at line 35 (pre-edit) is byte-identical post-edit:

```
> Budget enforcement halt is active. $[currentValue] of $[threshold] used ([percentUsed]%). To resume: `bash ~/.hermes/skills/revenium/scripts/clear-halt.sh`
```

Grep proof: `grep -cF 'Budget enforcement halt is active. ...' skills/revenium/SKILL.md` returns **1**.

Post-edit, the halt string appears at line 35 (unchanged position — the Setup section begins at line 108 which is after line 35, so no content above it shifted).

## Preserved Section Headings (with line numbers in new file)

| Section | Line (new file) | Status |
|---------|----------------|--------|
| `## HALT CHECK — DEFENSE-IN-DEPTH BACKSTOP` | 24 | unchanged |
| `## Budget Check Procedure` | 41 | unchanged |
| `## Runtime State` | 97 | unchanged |
| `## Verification` | 203 | unchanged |
| `## FINAL ACTION — TASK CLASSIFICATION` | 211 | unchanged |
| `## FINAL ACTION — JOB DECLARATION` | 219 | unchanged |
| `## LAST WORD — PRE-RESPONSE CHECKLIST (EVERY TURN)` | 238 | unchanged |

All section headings listed as "DO NOT TOUCH" in the plan are present at their expected relative positions.

## references/setup.md Untouched Sections — SHA256 Spot-Check

Lines 36+ in the new file (`## How attribution works` onward) are byte-identical to lines 73+ in the original:

```
SHA256: d5d4a6059255bb1591b48d7232df1e17bf84973a533551a5639ad500025ccd11
```

Sections verified byte-identical:
- `## How attribution works` (was line 73, now line 36)
- `## Mechanical classification hook` (was further on, now at correct offset)
- `## Marker file pruning` (ditto)

## Acceptance Criteria Results

| Criterion | Result |
|-----------|--------|
| `grep -c "setup-guardrails.sh --interactive" SKILL.md` ≥ 2 | **4** (Step 3, shadow-mode mention, /revenium block, Script Entry Points) |
| `grep -c "ruleIds" SKILL.md` ≥ 2 | **5** |
| `grep -c "revenium alerts budget create" SKILL.md` = 0 | **0** |
| `grep -c "revenium alerts budget delete" SKILL.md` = 0 | **0** |
| `grep -c "Extract the alert ID" SKILL.md` = 0 | **0** |
| `grep -cE 'ALERT_ID\b' SKILL.md` = 0 | **0** |
| `grep -c "alertId" SKILL.md` ≤ 1 | **1** (detection gate disclaimer only) |
| Halt-string grep matches exactly once | **1** |
| `grep -c "setup-guardrails.sh --interactive" setup.md` ≥ 2 | **3** |
| `grep -c "docs/migration-guardrails.md" setup.md` = 1 | **1** |
| `grep -c "revenium alerts budget create" setup.md` = 0 | **0** |
| `grep -c "revenium alerts budget delete" setup.md` = 0 | **0** |
| `grep -c "^## Reset flow" setup.md` = 0 | **0** |
| `test_skill_frontmatter_has_hermes_metadata` passes | PASS |
| `test_no_legacy_branding_left` passes | PASS |
| Full test suite (96 tests) passes | PASS (OK) |

## Deviations from Plan

None — plan executed exactly as written.

One note on line count: the target was approximately -100 lines for SKILL.md; actual reduction was -72 lines. The new step 3 includes explicit exit-code prose (exit 0 success, exit 0 cancel, non-zero failure — three branches spelled out) that is essential for the agent to correctly handle the script's three outcomes. This is not a deviation from the plan's functional requirements — the plan specifies these three exit-code handling branches explicitly.

## Known Stubs

None. The Setup Flow in SKILL.md is fully wired to `setup-guardrails.sh --interactive` (plan 18-02). The references/setup.md pointer to `docs/migration-guardrails.md` refers to a file that plan 18-05 ships.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. This plan is documentation-only (SKILL.md + references/setup.md). The T-18-LOG-INJECT threat (halt-string at line 35 preserved byte-identical) is verified as mitigated.

## Downstream Pointers

- **Plan 18-05:** Creates `docs/migration-guardrails.md` — the file referenced in references/setup.md's new Auto-migration section.
- **Plan 18-06:** Replaces behavioral test stubs with full `tmpdir + fake-revenium` fixtures.
- **Phase 19 HOOK-03:** Owns the halt-string rewrite in SKILL.md naming the offending rule (line 35 is deliberately untouched here).
- **Phase 20 DOCS-02/03:** Owns the SKILL.md Verification block rewrite and halt-survivability runbook re-validation.

## Self-Check: PASSED

- FOUND: skills/revenium/SKILL.md (246 lines, modified)
- FOUND: skills/revenium/references/setup.md (modified)
- FOUND: commit 86111ff (Task 1 — SKILL.md)
- FOUND: commit 4cef5d2 (Task 2 — references/setup.md)
- CONFIRMED: halt-string at line 35 byte-identical (grep match count = 1)
- CONFIRMED: `grep -c "alertId" SKILL.md` = 1 (detection gate disclaimer only)
- CONFIRMED: `grep -c "revenium alerts budget create" SKILL.md` = 0
- CONFIRMED: SHA256 of setup.md lines 36+ = SHA256 of original lines 73+ (byte-identical)
- CONFIRMED: 96 tests pass (OK)
