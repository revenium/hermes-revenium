---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: completed
last_updated: "2026-05-12T20:49:20.057Z"
progress:
  total_phases: 5
  completed_phases: 2
  total_plans: 4
  completed_plans: 4
  percent: 40
---

# Project State

**Last Updated:** 2026-05-12 (Phase 2 execution complete — verifier PASSED)
**Project:** Hermes-Revenium Task-Type Metering

## Project Reference

**Core Value:** Every metered completion that leaves this skill carries an accurate, consistently-spelled `--task-type` so Revenium analytics group spend by what the agent actually did, not just by session.

**Current Focus:** Phase 02 complete — ready for Phase 03 planning (Cron Marker Reader + Equal-Split + Ledger v2)

**Key Files:**

- `.planning/PROJECT.md` — project context, decisions, constraints
- `.planning/REQUIREMENTS.md` — v1 requirements with REQ-IDs
- `.planning/ROADMAP.md` — 5-phase decomposition with success criteria
- `.planning/research/SUMMARY.md` — synthesized research bundle
- `.planning/research/PITFALLS.md` — HIGH-severity ordering constraints
- `.planning/codebase/ARCHITECTURE.md` — existing two-half design
- `skills/revenium/scripts/common.sh` — single source of truth for state paths
- `skills/revenium/scripts/hermes-report.sh` — cron pipeline reporter (to be extended in Phase 3)
- `skills/revenium/SKILL.md` — in-session skill prompt (Phase 2 appended classification block)
- `skills/revenium/task-taxonomy.json` — seed taxonomy (Phase 2)
- `skills/revenium/references/task-taxonomy.md` — cold-path agent reference (Phase 2)
- `skills/revenium/references/halt-survivability.md` — manual halt-check survivability operator runbook (Phase 2)

## Current Position

**Phase:** 02 (Prompt Design & Marker Contract) — COMPLETE
**Plans:** 3 of 3 executed; verifier PASSED (5/5 automated SC; SC1 human gate before release)
**Status:** Ready for Phase 03 planning
**Progress:** 2/5 phases complete

```
[██████████] 100% Phase 1: Path Foundation                              Complete
[██████████] 100% Phase 2: Prompt Design & Marker Contract              Complete
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
| Phases complete | 2/5 |
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

### Phase 2 Resolutions

- **HERMES_SESSION_ID mechanism pinned (Option b):** `os.environ.get("HERMES_SESSION_ID") or f"pseudo-{int(time.time())}"`. Phase 3 cron reconciles markers against `state.db` so the pseudo-id fallback is acceptable as a transitional mechanism.
- **D-04 surfacing channel:** README.md is the durable surfacing for `halt-survivability.md` (CLAUDE.md is `.gitignored` by project policy; local edit non-durable, accepted by operator).
- **TAX-05 → Phase 3:** cron-side tolerance to missing/malformed taxonomy is cron work.
- **MARK-04 → Phase 3:** cron-side torn-line reader test is cron work; Phase 2 shipped the schema contract that makes the tolerance trivial.

### Open Questions / Carry-Forward Items

- **PROJECT.md "bias self-cancels" framing contradicts PITFALLS research.** The S2 equal-split bias is one-directional, not self-cancelling. Worth a re-confirmation with the team and a PROJECT.md Key Decisions update at the next phase transition. Ship the bias warning in `references/setup.md` regardless.
- **`manage_metering` verification of Revenium server-side `--operation-type` default.** Phase 3 research flag. Must happen before WIRE-01 ships in Phase 4.

### Blockers

None.

## Session Continuity

**Last Session:** 2026-05-12 (Phase 2 execution: 3 plans in 3 waves, 9/9 unittest tests pass, verifier PASSED)

**Next Session:** Run `/gsd-plan-phase 3` to plan the Cron Marker Reader + Equal-Split + Ledger v2 phase. Phase 3 must ship as ONE coherent migration — partial adoption breaks the load-bearing idempotency invariant. Phase 3 picks up TAX-05 and MARK-04 as carry-forwards from Phase 2 reassignment.

**Phase 2 delivered (across multiple commits on main):**

- `skills/revenium/task-taxonomy.json` — 8-label seed fixture, all keys match `^[a-z][a-z0-9_]{1,47}$`
- `skills/revenium/references/task-taxonomy.md` — cold-path agent reference with atomic-write pattern, blocklist, mint policy
- `skills/revenium/references/halt-survivability.md` — manual E2E operator runbook (2x2 matrix: short/long context × Anthropic/OpenAI), surfaced in README.md
- `skills/revenium/SKILL.md` — `## FINAL ACTION — TASK CLASSIFICATION` section at line 279 with substantive-turn rule, 4 canonical examples, trivial blocklist, canonical Python heredoc marker-write snippet. Halt anchor at line 24 byte-unchanged.
- `examples/setup-local.sh` — install-time guarded copy of seed taxonomy
- `tests/test_repository.py` — 4 new test methods: `test_taxonomy_file_schema`, `test_taxonomy_atomic_write_pattern`, `test_marker_file_schema`, `test_prompt_ordering_invariant`. All 9 tests pass.

**Operator gate before any release that modifies SKILL.md:** Run the halt-survivability runbook at `skills/revenium/references/halt-survivability.md` to confirm the verbatim halt string still fires under context dilution in long sessions. This is the SC1 human-verification gate the gsd-verifier flagged.

**Notes for Future Sessions:**

- Phase 3 must ship as one coherent migration (TAX-05 + MARK-04 + CRON-01..09 + COMPAT-02/03 + TEST-03/04). Splitting it breaks the idempotency invariant.
- Phase 3 research flags: verify Revenium server-side `--operation-type` default via `manage_metering` MCP tool; confirm S2 bias documentation framing with operator.
- CLAUDE.md is `.gitignored` by project policy — durable surfacing happens in README.md.
- PROMPT-07 uses U+2014 em dash literals (bytes E2 80 94) — preserve this when extending the test.

---
*State initialized: 2026-05-12 at roadmap creation*
