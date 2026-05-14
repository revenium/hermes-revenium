---
phase: 04-wire-enrichment
plan: 01
type: execute
executed: 2026-05-14
requirements_completed: [WIRE-01, WIRE-02, WIRE-03, WIRE-04, COMPAT-01]
files_modified:
  - skills/revenium/scripts/hermes-report.sh
  - tests/test_repository.py
  - skills/revenium/references/setup.md
  - .planning/REQUIREMENTS.md
  - .planning/ROADMAP.md
files_created:
  - .planning/phases/04-wire-enrichment/04-01-SUMMARY.md
tests_added: 2
tests_modified: 1
tests_total_after: 39
commits:
  - dc02d69 feat(04-01): WIRE-01 + COMPAT-01 — zero-marker fallthrough emits --operation-type CHAT
  - 2c19c98 feat(04-01): WIRE-02 + WIRE-03 — split_rows pipe extension (fields 10-11) + colon-dash fallbacks
  - b25e435 test(04-01): WIRE-02 + WIRE-03 passthrough regression — test_wire_agent_trace_passthrough
  - 179622a test(04-01): WIRE-04 8-provider regression — test_wire_no_provider_regression_per_class
  - (T05 docs + SUMMARY — committed atomically)
tags: [wire-enrichment, argv-passthrough, operation-type-default, provider-regression]
---

# Plan 04-01 Summary — Wire Enrichment

## Outcome

Phase 4 enriches `revenium meter completion` argv on two code paths in `hermes-report.sh`:

1. **Zero-marker fallthrough** (WIRE-01 / D-22): adds `--operation-type "CHAT"` immediately after `--task-type "unclassified"`. The D-22 gate was DISCHARGED in 04-RESEARCH.md — three independent evidence paths confirmed the Revenium server-side default is CHAT and that switching from absent to explicit CHAT is idempotent for cost calculations. The pre-existing block comment ("Do NOT emit --operation-type: Phase 4 owns…") was replaced with a single D-22 gate-discharged note.

2. **Marker-driven split path** (WIRE-02 + WIRE-03 / D-23): `split_rows` Python heredoc now reads `marker.get('agent', '')` and `marker.get('trace_id', '')` and appends them as pipe fields 10-11. The bash `while IFS='|' read -r` loop was extended to consume `m_agent m_trace`. The cmd array uses `${m_agent:-Hermes}` and `${m_trace:-${sid}}` colon-dash fallbacks — empty-string-from-pipe correctly triggers the fallback so today's universal production case (no upstream writer populates these fields per D-23) continues to ship `--agent Hermes` and `--trace-id ${sid}` byte-identically to pre-Phase-4 behavior.

Both atomic-commit invariants were honored: (1) Python pipe extension AND bash while-read extension landed in the same commit (mismatched field count would silently corrupt `d_cost`); (2) `--operation-type CHAT` production change AND the COMPAT-01 test assertion flip landed in the same commit.

Two new tests were added (WIRE-02/03 passthrough and WIRE-04 8-provider regression), one test assertion was flipped (COMPAT-01). 37 pre-existing tests preserved byte-unchanged (the COMPAT-01 test method itself had one assertion line replaced). Post-Phase-4 suite: 39/39 OK.

REQUIREMENTS.md CRON-07 description prose updated in place (`no explicit --operation-type` → `--operation-type CHAT (WIRE-01 / D-22 discharged in Phase 4)`) for internal consistency.

## Decisions Honored

### D-22 (WIRE-01) — Gate DISCHARGED; ship --operation-type CHAT default

Three independent evidence paths confirmed that the Revenium server-side default for absent `operationType` is `CHAT`:

1. **CLI dry-run**: `revenium meter completion --dry-run --json` with no `--operation-type` flag confirmed the API body emits `{operationType: ABSENT}` — the server maps absent to CHAT server-side.
2. **Historical records**: `revenium metrics completions` over 2026-04-01..2026-05-12 returned 50 records, ALL showing `operationType: CHAT` — every prior call that omitted the flag was recorded as CHAT.
3. **Cost parity**: GUARDRAIL vs CHAT pairs from the same session (28,733-token pair) showed only a $0.000001 floating-point delta — `operationType` is an analytics dimension only, not a cost multiplier.

The D-22 fallback option (permanently omit `--operation-type`) was NOT exercised. Gate DISCHARGED: explicit `--operation-type CHAT` is idempotent for existing customers' dashboards and budgets.

### D-23 (WIRE-02 + WIRE-03) — Cron pass-through ONLY; no upstream writer changes

`classifier.py` and `SKILL.md` FINAL ACTION are byte-unchanged. Phase 4 built the wire to carry `agent`/`trace_id` the moment a future writer chooses to populate them. In production today, every marker hits the colon-dash fallback (`${m_agent:-Hermes}`, `${m_trace:-${sid}}`) because no upstream writer emits these optional fields (per D-23 decision). The test `test_wire_agent_trace_passthrough` sub-case B (fallback) verifies this universal production path; sub-case A (positive) verifies the wire works correctly when a future writer does populate them.

### D-24 (WIRE-04) — 8-provider regression test landed

`test_wire_no_provider_regression_per_class` loops over all 8 provider classes:

| Label | billing_provider | expected_provider | expected_model_source |
|-------|-----------------|-------------------|----------------------|
| anthropic | anthropic | anthropic | anthropic |
| openai | openai | openai | openai |
| google | google | google | google |
| xai | xai | xai | xai |
| deepseek | deepseek | deepseek | deepseek |
| meta | (empty) | meta | ABSENT |
| openrouter-special | openrouter | anthropic | openrouter |
| bedrock-special | bedrock | anthropic | bedrock |

The `meta` case is the only case asserting `--model-source` ABSENCE (empty `billing_provider` → conditional flag not emitted). The `openrouter-special` and `bedrock-special` cases verify the existing prefix-stripping behavior (`anthropic/` and `anthropic.` respectively) produces the correct clean model. Each case forces the marker-driven split path (GUARDRAIL+CHAT pair) so N=2 invocations per case are asserted.

### D-25 — Per-marker attribution semantics documented

The following paragraph was appended to the end of the `## How attribution works` section in `skills/revenium/references/setup.md` (before `## Mechanical classification hook`):

> When markers carry different `agent` or `trace_id` values across a session, each Revenium meter call records the per-turn attribution; per-session aggregation happens dashboard-side.

No new section header was added; the paragraph attaches to the existing section's end as plain prose.

## Key Files

- **`skills/revenium/scripts/hermes-report.sh`**: Two atomic changes — (1) zero-marker fallthrough cmd array adds `--operation-type "CHAT"` after `--task-type "unclassified"` and replaces old comment with D-22 gate-discharged note; (2) marker-driven split path: Python heredoc emits 11 pipe fields (agent/trace as fields 10-11), bash while-read consumes 11 variables, cmd array uses colon-dash fallbacks for `--agent` and `--trace-id`.
- **`tests/test_repository.py`**: COMPAT-01 assertion flip in `test_cron_marker_split_end_to_end` (line 614); new `test_wire_agent_trace_passthrough` (WIRE-02/03 positive+fallback sub-cases); new `test_wire_no_provider_regression_per_class` (WIRE-04 DRY 8-case loop).
- **`skills/revenium/references/setup.md`**: D-25 attribution-semantics paragraph appended to `## How attribution works`.
- **`.planning/REQUIREMENTS.md`**: 5 checkbox flips (WIRE-01..04 + COMPAT-01); CRON-07 description prose updated; 5 traceability rows updated to `Verified (Phase 4)`; last-updated date updated.
- **`.planning/ROADMAP.md`**: Phase 4 Plans count finalized (1 plan); 04-01-PLAN.md entry added to Plans list; Progress Table row updated to `1/1 / Executed / 2026-05-14`.

## Verification

- `python3 -m unittest discover -s tests -p 'test_*.py' -v` → **39/39 OK** (37 pre-existing + 2 new: `test_wire_agent_trace_passthrough`, `test_wire_no_provider_regression_per_class`; 1 test method has one assertion flipped but counts as 1 test).
- `bash -n skills/revenium/scripts/hermes-report.sh` → **exit 0** (no syntax regression; `set -uo pipefail` discipline preserved).
- `test_no_legacy_branding_left` passes against all edited files — no legacy product names introduced.
- `test_setup_md_has_mechanical_classification_hook_section` passes — `## Mechanical classification hook` heading byte-unchanged after D-25 paragraph append.

## Operator Verification

Operator action: run a CLI substantive turn against the deployed Phase 4 wire and confirm the Revenium dashboard shows agent + trace_id columns populated when markers carry them (today: Hermes / ${sid} fallback) and operationType=CHAT for the zero-marker case. Record session id and completion timestamp here once verified.

Session id: _pending_
Verified at: _pending_

## Out of Scope Carried Forward

Phase 4 deliberately did NOT touch:
- `skills/revenium/plugins/revenium-classifier/classifier.py` — no upstream agent/trace_id population (D-23 locked)
- `skills/revenium/SKILL.md` FINAL ACTION snippet — D-23 deferred to a future phase
- `skills/revenium/plugins/revenium-classifier/__init__.py`
- `skills/revenium/scripts/split_strategies.py`
- `skills/revenium/scripts/common.sh`
- Ledger format or marker schema
- HOOK-01..HOOK-13 entry strings
- `examples/setup-local.sh`
- Any of the existing 35 non-touched test methods

Phase 5 (Housekeeping) inherits any deferred D-23 ideas (upstream agent/trace_id population in classifier.py). When a future writer phase chooses to populate these optional marker fields, the wire is already ready — the colon-dash fallback will be displaced by the writer's values automatically.
