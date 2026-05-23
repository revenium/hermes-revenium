---
phase: 20-integration-hardening-documentation
plan: "02"
subsystem: documentation
tags: [phase-20, docs, rewrite, guardrails-native, two-halves-model]
dependency_graph:
  requires: [20-01, 20-03]
  provides: [DOCS-01, DOCS-02, DOCS-03, DOCS-05]
  affects: [README.md, skills/revenium/SKILL.md, CLAUDE.md, skills/revenium/references/halt-survivability.md, skills/revenium/references/setup.md, skills/revenium/references/troubleshooting.md]
tech_stack:
  added: []
  patterns: [hybrid-structural-surgical-rewrite, D-06-two-halves-model, D-08-numbered-step-setup]
key_files:
  modified:
    - README.md
    - skills/revenium/SKILL.md
    - CLAUDE.md
    - skills/revenium/references/halt-survivability.md
    - skills/revenium/references/setup.md
    - skills/revenium/references/troubleshooting.md
decisions:
  - "D-05 hybrid posture: structural rewrite of README Quick Start/Setup/Verification/Guardrail Enforcement; Setup Flow in SKILL.md; Architecture/Halt-transitions/Common-commands/State-separation in CLAUDE.md; surgical sub for references/*.md"
  - "D-06 canonical mental model 'two halves through guardrail-status.json' with warn/block + audit-on-transition overlay; SKILL.md procedural backstop preserved as defense-in-depth"
  - "D-07 halt-survivability runbook prose-only refresh — no matrix re-run; Phase 19 D-16 already validated; explicit no-re-run note added"
  - "D-08 SKILL.md Setup Flow: 5-step numbered list ending at hook approval; Verification block leads with grep commands then wait-and-cat"
  - "Phase 19 D-12 HALT CHECK + Procedure block (SKILL.md lines 24-95) PRESERVED verbatim — not touched by this plan"
  - "CLAUDE.md edits confined to lines 5-76 (un-managed regions); GSD-managed blocks (lines 129+) completely untouched per Pitfall 5"
  - "CLAUDE.md force-added via git add -f (gitignored file; precedent from .planning/ SUMMARY.md pattern)"
metrics:
  duration: "9m"
  completed: "2026-05-23"
  tasks_completed: 6
  files_modified: 6
---

# Phase 20 Plan 02: Docs Rewrite (Guardrails-Native) Summary

Six documentation files rewritten or surgically updated to teach the v1.3 guardrails-native model. Structural rewrites for README Quick Start/Setup/Verification/Enforcement sections, SKILL.md Setup Flow/Verification, and CLAUDE.md un-managed regions (lines 5-76). Surgical find-and-replace for three references/*.md files. Zero `budget-status` / `budget-check` mentions remain in any of the six files in lines 1-128 (un-managed regions).

## What Was Built

### Task 1 — README.md rewrite (commit 19e429c)

Structural rewrite of Quick Start (5-step flow with `setup-guardrails.sh --interactive` as step 2), Required section (adds guardrail setup step), First-time setup (rewritten for `ruleIds`/`setup-guardrails.sh` flow), Guardrail enforcement section (replaces Budget enforcement), Configuration (JSON example: `alertId` → `ruleIds`; table row updated; migration callout), Manual commands (`budget-check.sh` → `guardrail-check.sh`), Status & diagnostics (`budget-status.json` → `guardrail-status.json`), Troubleshooting paragraph, Uninstalling (`alerts budget` → `guardrails budget-rules`). New Verification section added with grep commands + wait-and-cat step. Migration callout linking to `docs/migration-guardrails.md`.

### Task 2 — SKILL.md Setup Flow + Verification (commit 6f2129f)

Added explicit step 5 ("approve hooks on first hermes chat") to the Setup Flow, making it a clean 5-step numbered list per D-08. Added legacy `alertId` auto-migrate callout. Prepended D-08 grep block to Verification section (crontab, grep hermes-revenium-hooks, post_tool_call, jq .ruleIds) followed by wait-and-cat step. Phase 19 D-12 HALT CHECK + Procedure block (lines 24-95) and frontmatter (lines 1-23) completely untouched.

### Task 3 — CLAUDE.md un-managed region rewrite (commit 20bfd6b)

Five surgical edits in lines 5-76 per D-06: (1) "guardrails-based" qualifier in What this repo is; (2) `budget-check.sh` → `guardrail-check.sh` in Common commands; (3) Architecture two-halves description fully rewritten — `guardrail-check.sh`, `guardrail-status.json`, warn/block bands, enforcement-event embedding, hooks as load-bearing path; (4) `BUDGET_STATUS_FILE` → `GUARDRAIL_STATUS_FILE` in State separation; (5) `budget-check.sh` → `guardrail-check.sh` + ok→block framing + enforcement-events embedding in Halt transitions. GSD-managed blocks (lines 129+) completely untouched. File force-added via `git add -f` (gitignored).

### Task 4 — halt-survivability.md refresh (commit 0695a78)

No-re-run note inserted (cites Phase 19 D-16). Nine `budget-status.json` → `guardrail-status.json` substitutions. `budget-check output` → `guardrail-check output`. Halt-string template: legacy form replaced with D-01 verbatim form. Two fixture python3 blocks replaced with D-04 v1.3 schema (`halted`, `autonomousMode`, `lastChecked`, `haltedAt`, `haltedRule{ruleId,name,metricType,windowType,currentValue,hardLimit,warnThreshold,state}`, `rules[...]`). 4-cell matrix structure and methodology preserved verbatim per D-07.

### Task 5 — setup.md + troubleshooting.md surgical sub (commit ac9ddc4)

Three substitutions: setup.md line 55 (`budget-status.json::halted` → `guardrail-status.json::halted`); troubleshooting.md heading (`## \`budget-status.json\` missing` → `## \`guardrail-status.json\` missing`); troubleshooting.md cat command (`budget-status.json` → `guardrail-status.json`). No broken in-doc anchors (grep confirmed no old anchor links).

### Task 6 — Plan-wide grep gate (verification-only)

SC-7-style grep gate: `budget-status|budget-check` returns 0 across all 5 non-CLAUDE files. CLAUDE.md lines 1-128: 0 matches. Full suite: 118/118 OK. Three invariant tests all pass individually.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 19e429c | docs(20-02): rewrite README.md for guardrails-native v1.3 model |
| 2 | 6f2129f | docs(20-02): rewrite SKILL.md Setup Flow + Verification for v1.3 D-08 |
| 3 | 20bfd6b | docs(20-02): rewrite CLAUDE.md un-managed regions (lines 5-76) for v1.3 D-06 |
| 4 | 0695a78 | docs(20-02): refresh halt-survivability.md per D-07 (prose subs + v1.3 fixtures) |
| 5 | ac9ddc4 | docs(20-02): surgical sub in references/setup.md and troubleshooting.md per D-05 |

## Deviations from Plan

None — plan executed exactly as written. The CLAUDE.md force-add pattern (gitignored file) was anticipated by the parallel execution instructions and is consistent with the `.planning/` SUMMARY.md precedent.

## Preserved Invariants

- **Phase 19 D-12 HALT CHECK + Procedure block**: SKILL.md lines 24-95 completely untouched. `grep -c 'Guardrail halt active' skills/revenium/SKILL.md` = 1.
- **SKILL.md frontmatter**: lines 1-23 unchanged. `test_skill_frontmatter_has_hermes_metadata` passes.
- **CLAUDE.md GSD-managed blocks**: lines 129+ unchanged. `head -77 CLAUDE.md | grep -E '<!-- GSD:' | wc -l` = 0.
- **COMPAT-04**: `test_no_legacy_branding_left` passes against all rewritten files.
- **test_runtime_paths_are_hermes_native**: passes (no path changes in code).
- **Full suite**: 118/118 tests pass.

## Known Stubs

None — all six files deliver complete v1.3 prose. No placeholder or TODO text introduced.

## Threat Flags

None — documentation-only plan. No new code paths, network endpoints, credential handling, or trust boundaries introduced.

## Self-Check: PASSED

All 6 modified files exist in the worktree. All 5 per-task commits exist in git log. SUMMARY.md created at `.planning/phases/20-integration-hardening-documentation/20-02-SUMMARY.md`. Full test suite 118/118 OK.
