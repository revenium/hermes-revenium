---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Agentic Job Tracking
status: planning
stopped_at: Phase 8 context gathered
last_updated: "2026-05-15T16:23:25.444Z"
last_activity: 2026-05-15
progress:
  total_phases: 5
  completed_phases: 1
  total_plans: 1
  completed_plans: 1
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-14)

**Core value:** Every metered completion that leaves this skill carries an accurate, consistently-spelled `--task-type` so Revenium analytics group spend by what the agent actually did, not just by session. v1.1 extends this with agentic-job tracking.
**Current focus:** Phase 07 — job-marker-schema-state-scaffolding

## Current Position

Phase: 8
Plan: Not started
Status: Ready to plan
Last activity: 2026-05-15

Progress: [░░░░░░░░░░] 0% (v1.1)

## Performance Metrics

| Metric | Value |
|--------|-------|
| v1.1 requirements | 27 |
| Mapped to phases | 27 (100%) |
| Phases planned | 5 (Phases 7-11) |
| Phases complete | 0/5 |
| Granularity | coarse |
| Mode | yolo |

v1.0 shipped 2026-05-15: 6 phases, 14 plans, 45 tests. See MILESTONES.md.

## Accumulated Context

### Decisions

Full decision log in PROJECT.md Key Decisions table. v1.1 roadmap-shaping decisions:

- **Phase ordering is load-bearing.** All four researchers independently surfaced: the `revenium-jobs.ledger` + `kind:"job"` schema must land first (Phase 7); `jobs create` (Phase 9) must precede any `jobs outcome` call (Phase 10) — outcome idempotency has nowhere to live otherwise, and job outcomes are immutable so double-reporting is unrecoverable.
- **Separate `revenium-jobs.ledger`** — never reuse `revenium-hermes.ledger`; its 4-vs-5 colon-field discrimination would break.
- **Additive `kind:"job"` marker line** in the existing `markers/<sid>.jsonl` — never a per-turn field, never a separate file.
- **Local ledger is the idempotency source of truth** — the CLI exits 0 on HTTP 409, so exit code is useless; 409 is success-equivalent.
- **Hardening (Phase 11)** has no functional dependency on the job work — final phase or parallel track.
- **Backward compat is a hard gate on every cron-pipeline phase** — job-less / marker-less sessions meter byte-identically to v1.0, verified by regression test.

### Pending Todos

None.

### Blockers/Concerns

None.

### Research Flags (carried into planning)

- **Phase 8:** Arc-boundary detection + conservative-outcome prompt framing warrant a `/gsd-research-phase` pass; the multi-arc-per-session vs one-arc-per-session granularity is an explicit Phase 8 decision point (acceptable floor: one job per session).
- **Phase 10:** The abandoned-arc staleness net (window, `CANCELLED` default, cadence) and `jobs get` reconciliation semantics are the least-pinned area — resolve MVP-vs-deferred during Phase 10 planning. Budget-halt `CANCELLED` terminal marker (DECLARE-06, Phase 8) ships regardless.

## Deferred Items

v1.0 carry-forward tech debt — all four items are now in-scope for Phase 11 (HARDEN-01..04):

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| tech_debt | `_persist_label_to_taxonomy` lacks `fcntl.flock` | scheduled — Phase 11 (HARDEN-01) | v1.0 close |
| tech_debt | `clear-halt.sh` `${VAR@Q}` bash 4.4+ syntax | scheduled — Phase 11 (HARDEN-02) | v1.0 close |
| tech_debt | `REVENIUM_MARKER_RETENTION_DAYS=0` not validated | scheduled — Phase 11 (HARDEN-03) | v1.0 close |
| tech_debt | Dead `_count_tools_in_current_turn` helper | scheduled — Phase 11 (HARDEN-04) | v1.0 close |

## Session Continuity

Last session: 2026-05-15T16:23:25.433Z
Stopped at: Phase 8 context gathered
Resume file: .planning/phases/08-job-declaration-prompt-block/08-CONTEXT.md

**Next step:** Run `/gsd-plan-phase 7` to plan Job Marker Schema & State Scaffolding.

**Operator gate before any release that modifies SKILL.md (Phase 8):** Run the halt-survivability runbook at `skills/revenium/references/halt-survivability.md` to confirm the verbatim halt string still fires under context dilution.

**Live-host validation:** Every script-adding phase must be verified on Mac Studio (`ssh 172.16.1.175`, bash 3.2.57) — the dev checkout lies about portability (v1.0 lesson).
