# Phase 4: Wire Enrichment - Context

**Gathered:** 2026-05-14
**Status:** Ready for planning (no SPEC.md; discuss-mode capture only)
**Phase goal (verbatim from ROADMAP.md):** Each split metering call carries the richest `--operation-type`, `--agent`, and `--trace-id` available from the marker, with a documented, conservative fallback to today's hardcoded values; provider inference and cost scaling never regress across any split call.

<domain>
## Phase Boundary

Phase 4 enriches the `revenium meter completion` argv shape with per-marker fields that Phase 2 introduced into the marker schema (`operation_type`, optional `agent`, optional `trace_id`). The wire happens in `skills/revenium/scripts/hermes-report.sh`. No new markers, no new state files, no upstream writer changes — this is purely a downstream pass-through enrichment of the cron's CLI invocation.

The phase ships in two distinct code paths:
1. **Marker-driven split path** (Phase 3) — already emits `--operation-type "${op_type}"` from the marker (line 570). Phase 4 extends this path to also emit `--agent` and `--trace-id` from the marker when present, falling back to today's hardcoded values when absent.
2. **Zero-marker fallthrough path** (D-18 backward-compat) — currently omits `--operation-type` entirely (deferred to Phase 4 per the line 611 comment). Phase 4 adds `--operation-type CHAT` here, gated by a Revenium `manage_metering` research query confirming no cost-calculation shift for existing customers' historical unclassified spend.

WIRE-04 is the regression guard — per-marker argv must preserve provider/model/billing_provider/model-source semantics for every pre-existing provider class (anthropic / openai / google / xai / deepseek / meta + OpenRouter and Bedrock special-cases).

</domain>

<carry_forward>
## Carry-forward from prior phases

- **D-1 (PROJECT.md)** — Granularity is per-turn, not per-session. Phase 4 enforces this end-to-end at the wire by allowing per-marker `--agent` / `--trace-id` (D-25 below).
- **D-6 (PROJECT.md)** — `--operation-type GUARDRAIL` for classification turns. Phase 2 markers already carry this; Phase 3's split path already emits it. Phase 4 does NOT change this; only adds CHAT default for the fallthrough.
- **D-7 (PROJECT.md)** — Default to `--task-type unclassified` on no-marker sessions. Preserves backward compat. Phase 4's fallthrough change ADDS `--operation-type CHAT` alongside the existing unclassified task-type; the task-type behavior is unchanged.
- **D-18 (Phase 3)** — Zero-marker fallthrough path is the documented backward-compat shape. Phase 3 SC3 byte-diff invariant explicitly carved out `--operation-type` to be added by Phase 4 (the only legal argv change to this path).
- **Phase 6 marker writers** — The `hermes_cli` plugin's `classifier.py` and the SKILL.md FINAL ACTION snippet both currently write only the 5 required marker keys (`muid`, `ts`, `sid`, `task_type`, `operation_type`). Optional `agent` and `trace_id` fields are NOT populated by any writer today. Per D-23 below, Phase 4 does NOT extend the writers — pass-through only.
- **Phase 6 marker shape in production** — Marker pairs are always `(GUARDRAIL, CHAT)` per Phase 2 D-6. Phase 4's WIRE-01 default (CHAT) aligns with the work-marker side of that pair.

</carry_forward>

<decisions>
## Implementation Decisions

### D-22: WIRE-01 — Zero-marker fallthrough emits `--operation-type CHAT`, after research gate

The cron's zero-marker fallthrough path (today omitting `--operation-type` entirely per the Phase 3 SC3 byte-diff invariant) will emit `--operation-type CHAT` alongside `--task-type unclassified`. This is gated by a mandatory research query in plan 04-01:

**Research gate (MANDATORY — block plan execution until resolved):**
Run `mcp__revenium__manage_metering` (or equivalent introspection) to confirm that Revenium's cost-calculation pipeline treats `operation_type=null/absent` and `operation_type="CHAT"` identically for cost aggregation in existing customers' historical data. If confirmed, ship D-22 as stated. If NOT confirmed, fall back to permanently omitting `--operation-type` in the fallthrough path and document the constraint in `skills/revenium/references/setup.md`.

**Why the gate matters:** Switching the default from absent to CHAT would silently re-bucket historical unclassified spend in existing customers' dashboards if Revenium treats the two values differently. The research query is the cheapest way to confirm safety.

### D-23: WIRE-02 + WIRE-03 — Cron pass-through ONLY; no upstream writer changes

The cron reads optional `agent` and `trace_id` fields from each marker if present and emits them as `--agent <value>` / `--trace-id <value>`. When absent (the universal case today), the cron falls back to today's hardcoded `--agent "Hermes"` and `--trace-id "${sid}"`.

**Out of scope for Phase 4:**
- Extending `skills/revenium/plugins/revenium-classifier/classifier.py` to populate `agent` from session context (e.g., skill name, slash-command, model name) — defer to a future phase.
- Extending the SKILL.md FINAL ACTION snippet to populate `agent` / `trace_id`.
- Sourcing `trace_id` from Hermes' internal trace propagation — out of scope; we don't fully control upstream behavior here.

**Effect:** Phase 4 ships the wire ready to carry these fields the moment any upstream writer chooses to populate them. The downstream Revenium-side dimension becomes immediately useful as soon as that happens. No coordination required between Phase 4 and the writer-side decision.

### D-24: WIRE-04 — New argv-comparison regression test per provider class

A new test method in `tests/test_repository.py` (suggested name: `test_wire_no_provider_regression_per_class`) stubs the `revenium` binary to capture argv, seeds synthetic state.db rows + markers per provider class, runs `hermes-report.sh`, and asserts the per-marker `revenium meter completion` argv carries the SAME `--provider`, `--model`, `--model-source` flags as the pre-Phase-3 single-call legacy path would have for that provider.

**Cases (8):** anthropic, openai, google, xai, deepseek, meta, openrouter-special-case (resolves underlying provider from model string), bedrock-special-case (same).

**Each case:** seeded state.db row with the provider's identifying `billing_provider` + `model` shape from the inference rules in `hermes-report.sh:115-165`, marker pair (GUARDRAIL + CHAT) so the split path runs, stubbed `revenium` binary capturing argv into a temp file, assertions on the captured argv strings.

**Where this lives:** As a single test method that loops the 8 cases (DRY scaffolding), OR as 8 small methods (clearer test names in CI output). Planner decides — both are acceptable.

### D-25: Per-marker as-is for inconsistent agent/trace_id within a session

When a session's markers have different `agent` or `trace_id` values across multiple markers (legitimately or otherwise), each per-marker `revenium meter completion` call carries THAT marker's values. The cron does NOT normalize / first-marker-wins / collapse to a single per-session value.

**Why:** Aligns with PROJECT.md D-1 (per-turn granularity, not per-session). A session that legitimately spans different skills should produce per-turn attribution.

**Practical impact today:** Zero — no upstream writer populates these fields (per D-23). All markers fall back to `agent="Hermes"` / `trace_id=${sid}`. The decision documents the intent so when upstream writers DO start populating, the behavior is predictable.

**Documentation:** `skills/revenium/references/setup.md` gets a one-paragraph note: "When markers carry different agent or trace_id values across a session, each Revenium meter call records the per-turn attribution; per-session aggregation happens dashboard-side."

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents (researcher + planner) MUST read these before planning or implementing.**

### Phase 4 success criteria
- `.planning/ROADMAP.md` — Phase 4 section (lines 60-78 approx): Goal, Requirements (WIRE-01..04), Success Criteria. The phase boundary comes from this file and is fixed.

### Requirements
- `.planning/REQUIREMENTS.md` — WIRE-01, WIRE-02, WIRE-03, WIRE-04. WIRE-01 contains the explicit research-gate language that D-22 implements.

### Project-level decisions that carry forward
- `.planning/PROJECT.md` — Key Decisions section. D-1 (per-turn granularity), D-6 (GUARDRAIL for classification), D-7 (unclassified default for no-marker).

### Phase 3 cron implementation
- `skills/revenium/scripts/hermes-report.sh` — the only file Phase 4 modifies in production code (plus tests).
  - Lines 555-580 approx: marker-driven `revenium meter completion` argv block. Phase 4 extends this with `--agent` / `--trace-id` marker-lookups.
  - Lines 605-640 approx: zero-marker fallthrough block. Phase 4 adds `--operation-type CHAT` here (D-22, gated).
  - Lines 115-165 approx: provider inference / OpenRouter / Bedrock special-casing. D-24's regression test seeds inputs against this code.
- `.planning/phases/03-cron-marker-reader-equal-split-ledger-v2/03-CONTEXT.md` — Phase 3's deferral note on WIRE-01 ("research_gates" section).

### Phase 2 marker schema (the contract Phase 4 honors)
- `.planning/phases/02-prompt-design-marker-contract/02-CONTEXT.md` — marker field allow-list: required `{muid, ts, sid, task_type, operation_type}` + optional `{turn_seq, agent, trace_id, model}`.
- `skills/revenium/references/task-taxonomy.md` — operation_type vocabulary (CHAT, GUARDRAIL) and the rationale for treating GUARDRAIL as classification overhead.

### Phase 6 marker writers (read-only; Phase 4 does NOT modify)
- `skills/revenium/plugins/revenium-classifier/classifier.py` — current marker writer; writes only required keys. D-23 confirms Phase 4 does NOT extend this.
- `skills/revenium/SKILL.md` — FINAL ACTION section; current marker writer for agent self-classification. D-23 confirms Phase 4 does NOT extend this.

### Revenium MCP tooling (D-22 research gate)
- `mcp__revenium__manage_metering` — the Revenium MCP tool the planner must consult to discharge the D-22 research gate. The planner's 04-RESEARCH.md must include the query results.

### Test patterns (D-24 reference)
- `tests/test_repository.py::test_cron_marker_split_end_to_end` — the existing end-to-end test scaffolding to mirror for D-24's argv-comparison test (synthetic state.db, marker fixture, stubbed `revenium`, captured-argv assertions).

</canonical_refs>

<specifics>
## Specific References

- **WIRE-04 provider classes to cover:** anthropic, openai, google, xai, deepseek, meta, openrouter (special-case: model-string parsing to underlying provider), bedrock (special-case: model-id parsing). Each has an explicit branch in `hermes-report.sh:115-165`.
- **Stubbed `revenium` binary pattern:** the existing `tests/test_repository.py::test_cron_marker_split_end_to_end` already creates a temp-dir `revenium` stub script that captures argv to a file. D-24's test mirrors this pattern.
- **D-22 fallback if research gate fails:** permanently omit `--operation-type` in the fallthrough. Update `skills/revenium/references/setup.md` with a "Why the fallthrough path omits operation-type" subsection.
- **D-25 documentation location:** `skills/revenium/references/setup.md` — append one paragraph in the existing "Attribution semantics" section (or create one if absent). Same file the Phase 6 "Mechanical classification hook" section lives in.

</specifics>

<deferred>
## Deferred Ideas

- **Upstream `agent` population in classifier.py** — Plugin extracts `agent` from session context (skill name when `skill_view` was called recently, slash-command name when turn was triggered by `/foo`, else model name). Phase 4 D-23 explicitly defers this; a future phase can pick it up.
- **Upstream `trace_id` population from Hermes trace propagation** — If Hermes' `on_session_end` context exposes a span trace-id (or one becomes available via a future plugin hook), the classifier could populate `trace_id`. Defer until upstream support exists.
- **SKILL.md FINAL ACTION extension to write `agent`/`trace_id`** — Could ship symmetrically with the plugin upstream-population. Defer as a single coordinated future phase rather than dribbling in.
- **Per-session dashboard aggregation guidance** — When per-marker agent/trace_id starts varying, customers may want dashboard-side patterns for collapsing. Operator-facing docs, not engineering work. Defer to a future Phase 5+ housekeeping wave.

</deferred>

<scope_creep_redirected>
None. The 4 discussed areas all fall within the WIRE-01..04 phase boundary.

</scope_creep_redirected>

---

*Phase: 04-wire-enrichment*
*Context gathered: 2026-05-14 via /gsd-discuss-phase 4 — 4 areas discussed, 4 decisions locked (D-22, D-23, D-24, D-25). Carry-forward references PROJECT.md D-1/D-6/D-7 and Phase 3 D-18.*
