---
status: complete
phase: 04-wire-enrichment
source:
  - 04-01-SUMMARY.md
started: 2026-05-14T21:35:00Z
updated: 2026-05-14T21:42:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Wire carries --operation-type CHAT on every revenium call
expected: After the Mac Studio cron tick, every `Reported: ...` line in `~/.hermes/state/revenium/revenium-metering.log` shows the corresponding revenium meter call shipped `--operation-type CHAT` on the wire — both for marker-driven rows (op_type=GUARDRAIL or CHAT from the marker) AND for the zero-marker fallthrough path (WIRE-01 / D-22).
result: pass

### 2. Wire carries --agent and --trace-id (fallback values in production)
expected: Marker-driven revenium meter calls ship `--agent Hermes` and `--trace-id <sid>` because no upstream writer populates the marker `agent`/`trace_id` fields yet (D-23 cron pass-through ONLY decision). The wire is built to carry real values when a future writer populates them — verifiable via test_wire_agent_trace_passthrough's positive sub-case.
result: pass

### 3. Provider/model inference preserved across the marker-driven split
expected: For sessions you've run today (e.g. `qwen/qwen3.6-plus` via openrouter), the cron log shows correct `model=qwen3.6-plus provider=openrouter` per Reported line — provider prefix stripped, model-source carried. WIRE-04's 8-provider regression test pins this across anthropic, openai, google, xai, deepseek, meta (empty model-source), openrouter-special, and bedrock-special cases.
result: pass

### 4. D-25 attribution paragraph present in setup.md
expected: `skills/revenium/references/setup.md` contains the one-paragraph addition inside `## How attribution works` documenting per-turn attribution semantics: "When markers carry different `agent` or `trace_id` values across a session, each Revenium meter call records the per-turn attribution; per-session aggregation happens dashboard-side."
result: pass

### 5. Revenium dashboard reflects per-turn task_type for marker-driven rows
expected: In the Revenium dashboard, recent metering rows for your Mac Studio sessions show varied `taskType` values (e.g. `moltbook_heartbeat_check`, `hardware_overview`, etc. — content-driven labels from today's classifier chain) instead of the previously-collapsed `generation`/`unclassified` pattern. (Note: this is the headline outcome of the full work chain — Phase 4 wire + the 3 quick-task classifier fixes — not Phase 4 alone, but the Phase 4 wire is what carries those labels to the Revenium API.)
result: pass

## Summary

total: 5
passed: 5
issues: 0
pending: 0
skipped: 0

## Gaps

[none yet]
