# Phase 4: Wire Enrichment - Discussion Log

**Date:** 2026-05-14
**Workflow:** `/gsd-discuss-phase 4` (default mode)
**Output:** `04-CONTEXT.md` (4 decisions locked: D-22, D-23, D-24, D-25)

---

## Areas Selected for Discussion

User selected all 4 surfaced gray areas (via multiSelect AskUserQuestion):

1. WIRE-01 default for zero-marker fallthrough
2. WIRE-02/03 marker agent + trace_id population policy
3. WIRE-04 regression test shape
4. Backward-compat for inconsistent markers within a session

---

## Area 1 — WIRE-01: zero-marker `--operation-type` default

**Question:** What's the right behavior for the zero-marker fallthrough path?

**Options presented:**
1. Emit `--operation-type CHAT`, after the research gate confirms no cost shift *(Recommended)*
2. Always emit `--operation-type CHAT` — skip the research gate
3. Permanently omit `--operation-type` in the fallthrough

**User selection:** Option 1 — emit CHAT after research gate.

**Resulting decision:** D-22 (see `04-CONTEXT.md`).

**Notes:**
- The Phase 3 code at `hermes-report.sh:611` explicitly defers this decision to Phase 4 with a code comment: "Phase 4 owns the WIRE-01 default decision per CONTEXT.md research_gates."
- The research gate language comes directly from `REQUIREMENTS.md::WIRE-01`: "only after verifying via the Revenium manage_metering tool that this does not change cost calculations for existing users."
- Fallback path defined: if the gate fails, permanently omit `--operation-type` and document in `setup.md`.

---

## Area 2 — WIRE-02/03: marker agent + trace_id population policy

**Question:** What's the scope for WIRE-02/03?

**Options presented:**
1. Cron pass-through only *(Recommended)*
2. Cron pass-through + plugin populates `agent` from session context
3. Cron pass-through + plugin populates both `agent` AND `trace_id`

**User selection:** Option 1 — cron pass-through only.

**Resulting decision:** D-23 (see `04-CONTEXT.md`).

**Notes:**
- This narrows scope significantly. The cron is wire-ready but the optional fields are never populated by any current writer (`classifier.py` or SKILL.md FINAL ACTION).
- Effect: `--agent` always falls back to `"Hermes"`, `--trace-id` always falls back to `${sid}` until a future phase ships upstream population.
- Captured 3 specific upstream-population ideas as deferred items in `04-CONTEXT.md::<deferred>`.

---

## Area 3 — WIRE-04: regression test shape

**Question:** How do we prove no provider regression?

**Options presented:**
1. Add 1 argv-comparison test (per provider class) *(Recommended)*
2. Extend the existing end-to-end test with one more provider
3. Mac Studio smoke + visual Revenium dashboard check

**User selection:** Option 1 — argv-comparison test per provider class.

**Resulting decision:** D-24 (see `04-CONTEXT.md`).

**Notes:**
- 8 provider classes to cover: anthropic, openai, google, xai, deepseek, meta, openrouter (special-case), bedrock (special-case).
- Test pattern mirrors the existing `test_cron_marker_split_end_to_end` scaffolding (stubbed `revenium` binary captures argv to a file, assertions on captured argv).
- Planner chooses between 1 looped test method (DRY) vs 8 small methods (clearer CI output) — both acceptable.

---

## Area 4 — Inconsistent markers within a session

**Question:** How should the cron treat inconsistent agent/trace_id values across a session's markers?

**Options presented:**
1. Per-marker as-is — each marker's `--agent` / `--trace-id` wins for its call *(Recommended)*
2. First-marker-wins for the whole session window
3. Defer the question — today's writers don't populate the optional fields anyway

**User selection:** Option 1 — per-marker as-is.

**Resulting decision:** D-25 (see `04-CONTEXT.md`).

**Notes:**
- Aligns with PROJECT.md D-1 (per-turn granularity, not per-session).
- Practical impact today is zero (D-23 means no upstream writer populates these fields yet) — the decision documents intent so when upstream writers DO ship, behavior is predictable.
- Documentation location: `skills/revenium/references/setup.md`, attribution-semantics paragraph.

---

## Canonical References Accumulated

Built throughout the discussion as the user referenced files / specs / patterns. Final list in `04-CONTEXT.md::<canonical_refs>`. Top hits:
- `.planning/ROADMAP.md` (Phase 4 SC + Requirements)
- `.planning/REQUIREMENTS.md` (WIRE-01..04 verbatim language including research gate)
- `.planning/PROJECT.md` (carry-forward D-1, D-6, D-7)
- `skills/revenium/scripts/hermes-report.sh` (the only file Phase 4 modifies in production code)
- `mcp__revenium__manage_metering` (D-22 research gate tool)
- `tests/test_repository.py::test_cron_marker_split_end_to_end` (D-24 test pattern)

---

## Deferred Items

Recorded in `04-CONTEXT.md::<deferred>`:
- Plugin extends to populate `agent` from session context
- Plugin extends to populate `trace_id` from Hermes trace propagation
- SKILL.md FINAL ACTION extends to write `agent` / `trace_id`
- Per-session dashboard aggregation operator docs

---

## Scope Creep Redirected

None — all 4 areas fell within the WIRE-01..04 phase boundary.
