---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: planning
last_updated: "2026-05-12T18:30:26.265Z"
progress:
  total_phases: 5
  completed_phases: 1
  total_plans: 1
  completed_plans: 1
  percent: 100
---

# Project State

**Last Updated:** 2026-05-12 (Phase 2 planning complete)
**Project:** Hermes-Revenium Task-Type Metering

## Project Reference

**Core Value:** Every metered completion that leaves this skill carries an accurate, consistently-spelled `--task-type` so Revenium analytics group spend by what the agent actually did, not just by session.

**Current Focus:** Phase 02 — Prompt Design & Marker Contract (plans ready to execute)

**Key Files:**

- `.planning/PROJECT.md` — project context, decisions, constraints
- `.planning/REQUIREMENTS.md` — v1 requirements with REQ-IDs
- `.planning/ROADMAP.md` — 5-phase decomposition with success criteria
- `.planning/research/SUMMARY.md` — synthesized research bundle
- `.planning/research/PITFALLS.md` — HIGH-severity ordering constraints
- `.planning/codebase/ARCHITECTURE.md` — existing two-half design
- `skills/revenium/scripts/common.sh` — single source of truth for state paths
- `skills/revenium/scripts/hermes-report.sh` — cron pipeline reporter (to be extended in Phase 3)
- `skills/revenium/SKILL.md` — in-session skill prompt (to be extended in Phase 2)

## Current Position

**Phase:** 02 (Prompt Design & Marker Contract)
**Plans:** 3 of 3 planned, 0 of 3 executed
**Status:** Ready to execute
**Progress:** 1/5 phases complete

```
[██████████] 100% Phase 1: Path Foundation                              Complete
[░░░░░░░░░░] 0%   Phase 2: Prompt Design & Marker Contract              Ready to execute
[░░░░░░░░░░] 0%   Phase 3: Cron Marker Reader + Equal-Split + Ledger v2 Not started
[░░░░░░░░░░] 0%   Phase 4: Wire Enrichment                              Not started
[░░░░░░░░░░] 0%   Phase 5: Housekeeping & Compat Hardening              Not started
```

## Performance Metrics

| Metric | Value |
|--------|-------|
| v1 requirements | 37 |
| Mapped to phases | 37 (100%) |
| Phases planned | 2/5 |
| Phases complete | 1/5 |
| Granularity | coarse |
| Mode | yolo / standard horizontal-layers |

## Accumulated Context

### Decisions Logged

From `PROJECT.md` Key Decisions (all carry-forward from project initialization):

1. **Granularity = per turn, not per session.** Per-session loses the signal users want.
2. **Agent self-classifies after each substantive turn.** Cron-side LLM classification was rejected (duplicates agent knowledge, adds dep, breaks fail-open).
3. **Controlled-vocabulary taxonomy with strict lookup-first reuse.** Pure free-form labels fragment.
4. **Marker file (JSONL per session) is the agent ↔ cron contract.** No new IPC; mirrors existing `budget-status.json` shape with opposite direction.
5. **Equal split (S2) across markers in a cron window.** S3/S4 deferred to v2.
6. **`--operation-type GUARDRAIL` for the classification turn.** Distinguishes overhead from work.
7. **Default to `--task-type unclassified` on no-marker sessions.** Preserves backward compat.
8. **Classify substantive turns only.** Trivial acks would pollute the taxonomy.
9. **Taxonomy growth is agent-managed; no automatic merge pass in v1.** Dedupe tooling is v2.

### Open Questions / Carry-Forward Items

- **PROJECT.md "bias self-cancels" framing contradicts PITFALLS research.** The S2 equal-split bias is one-directional, not self-cancelling. Worth a re-confirmation with the team and a PROJECT.md Key Decisions update at the next phase transition. Ship the bias warning in `references/setup.md` regardless.
- **`manage_metering` verification of Revenium server-side `--operation-type` default.** Phase 3 research flag. Must happen before WIRE-01 ships in Phase 4.
- **Long-session halt-check survivability test plan.** Phase 2 research flag. Manual E2E test plan must exist before Phase 2 plan execution.

### Blockers

None.

## Session Continuity

**Last Session:** 2026-05-12 (Phase 2 planning: research → plan → checker → revise → checker PASS)

**Next Session:** Run `/gsd-execute-phase 2` to execute the 3 Phase 2 plans in sequence (waves 1 → 2 → 3, sequential due to shared `tests/test_repository.py` ownership):
- 02-01: Seed `task-taxonomy.json` (8 labels), `references/task-taxonomy.md` cold-path doc, install-time copy in `setup-local.sh`, TEST-02 schema invariant, and `test_taxonomy_atomic_write_pattern` round-trip (covers ROADMAP SC5)
- 02-02: `references/halt-survivability.md` operator runbook, surface it in `CLAUDE.md` and `README.md` (per D-04), TEST-01 marker schema invariant
- 02-03: Append `## FINAL ACTION — TASK CLASSIFICATION` section to `SKILL.md` with canonical Python heredoc marker-write snippet (must resolve `HERMES_SESSION_ID` mechanism — env var, `state.db` lookup, or timestamp fallback) and `test_prompt_ordering_invariant` (PROMPT-07)

**Notes for Future Sessions:**

- Phase 2 plans assume Hermes exposes `HERMES_SESSION_ID` as an env var; the executor MUST verify this empirically and pick a fallback if not — `[ASSUMED]` tag must be removed from `SKILL.md` before plan 02-03 Task 1 completes.
- Phase 3 has two research flags — verify Revenium server-side `--operation-type` default via the `manage_metering` MCP tool, and confirm S2 bias documentation framing with the operator. **TAX-05 was reassigned from Phase 2 to Phase 3** (cron-side tolerance to missing/malformed taxonomy is cron behavior); Phase 3 planning should pick this up.
- Phase 3 must ship as one coherent migration (CRON-01 through CRON-09 + COMPAT-02/03 + TEST-03/04 + TAX-05). Splitting it breaks the idempotency invariant.
- Phase 2 must ship BEFORE Phase 3 to bound the halt-check regression risk (PITFALLS HIGH severity).
- The PROMPT-07 test must use U+2014 em dash (`—`), not ASCII hyphen, in the literal `ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)` — PATTERNS.md and the plan-checker both flagged this.

---
*State initialized: 2026-05-12 at roadmap creation*
