---
status: diagnosed
phase: 06-mechanical-classification-agent-end-hook
source: [06-VERIFICATION.md]
started: 2026-05-13T19:02:08Z
updated: 2026-05-13T22:55:00Z
uat_rounds:
  - round: 1
    against: gsd/phase-6-uat @ f3f4efa (plan 06-01 only)
    outcome: G-01 surfaced — agent:end hook gateway-platform-scoped, CLI uncovered
  - round: 2
    against: gsd/phase-6-uat @ 5f493c0 (plans 06-01 + 06-02 — on_session_end plugin)
    outcome: G-02 surfaced — plugin loads + callback fires, but substance heuristic misclassifies CLI turns as trivial because ~/.hermes/sessions/<sid>.jsonl is absent for hermes chat -q sessions
---

## Current Test

[complete — 1 failed, 1 blocked]

## Tests

### 1. Gateway startup + substantive turn UAT (ROADMAP SC1, SC2, SC6)
expected: |
  (1) `bash examples/setup-local.sh` succeeds and reports `Installed hook to ~/.hermes/hooks/revenium-classifier`.
  (2) `hermes gateway restart` succeeds.
  (3) Gateway startup log emits: `[hooks] Loaded hook 'revenium-classifier' for events: ['agent:end']`.
  (4) After a substantive turn in a fresh Hermes session (no skill_view("revenium"), no manual classification), `~/.hermes/state/revenium/markers/<sid>.jsonl` contains a GUARDRAIL+CHAT marker pair with a meaningful (non-`unclassified`) `task_type`.
  (5) On the next cron tick, `revenium meter completion` is invoked with `--task-type <meaningful-label>` (not `unclassified`).
why_human: |
  Requires a running Hermes gateway process, a real substantive turn through an LLM, and Revenium CLI configuration — cannot be exercised in CI.
result: failed
executed_on: 2026-05-13T19:30:00Z (Mac Studio, 172.16.1.175, gsd/phase-6-uat @ f3f4efa)
sub_results:
  - step: "(1) setup-local.sh installs hook"
    status: pass
    evidence: "stdout: 'Installed hook to /Users/johndemic/.hermes/hooks/revenium-classifier'; on-disk: ~/.hermes/hooks/revenium-classifier/{HOOK.yaml, handler.py, test-payloads/}"
  - step: "(2) hermes gateway restart"
    status: pass
    evidence: "'✓ Service restarted' at 2026-05-13 15:31:11 local"
  - step: "(3) Gateway log emits load line"
    status: pass
    evidence: "~/.hermes/logs/gateway.log: '[hooks] Loaded hook ''revenium-classifier'' for events: [''agent:end'']' AND '1 hook(s) loaded'"
  - step: "(4) Substantive turn → marker file with non-unclassified task_type"
    status: fail
    evidence: |
      Two CLI substantive turns driven via `hermes chat -q`:
        sid=20260513_153205_0f85c8 (8 tool calls, 3 API calls, 25s, model=qwen/qwen3.6-plus)
        sid=20260513_153349_72147c (2 tool calls, 2 API calls, 10s)
      Both completed cleanly per ~/.hermes/logs/agent.log: 'Turn ended: reason=text_response(finish_reason=stop)'.
      Marker file at ~/.hermes/state/revenium/markers/<sid>.jsonl was NOT created for either session.
      No `revenium-classifier` activity in ~/.hermes/logs/gateway.log or gateway.error.log for either session.
      ~/.hermes/state/revenium/markers/ contains only the pre-hook-deployment file from 12:52 (which was written by SKILL.md FINAL ACTION, not the hook — sid="pseudo-1778691137" pattern).
  - step: "(5) Next cron tick ships --task-type to Revenium"
    status: blocked
    evidence: "Cannot reach this step — no marker file from step (4) for the cron-side reader to consume."
root_cause: |
  `agent:end` is emitted exclusively by `hermes-agent/gateway/run.py:7631`, which runs only inside platform-served gateway sessions (Telegram / Discord / Slack / WhatsApp / Webhook). `hermes chat -q` and the gateway's own cron-ticker invocations use separate runners that do NOT emit `agent:end`. The hook is correctly loaded at gateway startup but has no upstream emitter for CLI / cron sessions.

  Phase 6's design assumed `agent:end` fires for every Hermes agent turn regardless of session origin. In practice the event is gateway-platform-scoped only.

### 2. Subagent inheritance UAT (ROADMAP SC3)
expected: |
  A subagent session whose `state.db.sessions.parent_session_id` points at a root session with task_type=research produces a marker file at `~/.hermes/state/revenium/markers/<child-sid>.jsonl` carrying `task_type: research` on both records, with NO LLM call recorded against the subagent budget.
why_human: |
  Hermes' subagent dispatch (delegate_task lineage, real state.db.sessions parent chain) cannot be exercised without running Hermes end-to-end.
result: blocked
executed_on: 2026-05-13T19:35:00Z
sub_results:
  - step: "Test premise — parent classified by the hook first"
    status: blocked
    evidence: "Test 1 (above) demonstrates the hook does not fire for CLI sessions, which is the most readily-driven path for synthesizing a parent+child lineage outside production traffic. Cannot establish a parent classification to inherit from until the underlying CLI gap is closed OR the test is rebuilt over the Telegram path."

## Summary

total: 2
passed: 0
issues: 1
pending: 0
skipped: 0
blocked: 1

## Gaps

### G-01: agent:end hook does not fire for non-platform-served sessions (CLI, cron)
severity: high
status: open
discovered: 2026-05-13T19:35:00Z
relates_to: HOOK-01, HOOK-02, HOOK-05, HOOK-06, SC1, SC2, SC6, ROADMAP Phase 6 goal
summary: |
  The Phase 6 phase goal — "When a Hermes session ... completes a turn, a Hermes lifecycle hook deterministically writes a marker record ... independent of whether the agent loaded the revenium skill or executed the FINAL ACTION self-classification code" — is not achieved for CLI sessions (`hermes chat -q`, `hermes acp`, etc.) or for the gateway's internal cron-ticker sessions. `agent:end` is emitted only by `gateway/run.py:7631`, which is the platform-served path (Telegram / Discord / Slack / WhatsApp / Webhook).

  This is the very gap Phase 6 was created to close (per Phase 3 UAT's "agent-side adoption ... unreliable" finding). CLI is the dominant dev-time path and remains uncovered by mechanical classification.
options_for_closure:
  - "(a) Add a second hook-emit integration point in hermes_cli (or wherever CLI agent turns terminate) so CLI sessions also fire agent:end through the same registry."
  - "(b) Add a separate CLI-side hook bus and write a parallel handler that shares the same classification + marker-write helpers from handler.py (factor into a shared module)."
  - "(c) Scope correction — declare Phase 6 as 'platform-served gateway sessions only' in ROADMAP/REQUIREMENTS, and accept that CLI sessions stay on FINAL ACTION self-classification. The Phase 3 UAT gap then remains open for CLI."
recommended_action: |
  Run `/gsd-plan-phase 6 --gaps` to plan a gap-closure increment. Decide (a) vs (b) during the discuss/plan step — likely (a) if hermes_cli already has a hook-loading code path that can be reused, otherwise (b).

  Both options require checking the contributing audience: do CLI users want / need this attribution split, and is there an `agent:end`-equivalent emit site already in `hermes_cli/main.py` we can hook?
status_after_06_02: |
  G-01's root cause was correctly diagnosed and the architectural fix landed (06-02 — `hermes_cli` plugin registering `on_session_end`). UAT round 2 (2026-05-13T22:50Z on Mac Studio 172.16.1.175 against `gsd/phase-6-uat @ 5f493c0`) confirms:

  - setup-local.sh installs the plugin to ~/.hermes/plugins/revenium-classifier/ ✓
  - `~/.hermes/config.yaml::plugins.enabled` correctly contains `revenium-classifier` (idempotent stdlib edit) ✓
  - The Hermes plugin manager loads the plugin: debug log shows `Plugin revenium-classifier registered hook: on_session_end` and `mgr._hooks.get("on_session_end") = [_on_session_end]` ✓
  - `hermes plugins list` reports `revenium-classifier ... enabled ... 1.0.0 ... user` ✓
  - The `_on_session_end` callback fires (verified by direct `invoke_hook(...)` call) ✓

  However, NO marker file is written for CLI substantive turns. The callback silently no-ops because of G-02 (below). G-01 is now scoped to "covered architecturally; blocked behaviorally by G-02".

### G-02: substance heuristic mis-classifies CLI sessions as trivial because `~/.hermes/sessions/<sid>.jsonl` is absent
severity: high
status: open
discovered: 2026-05-13T22:55:00Z
relates_to: HOOK-02, HOOK-11, SC2, SC6, plan 06-02 truth #4 (heuristic skip-fast-path)
summary: |
  `classifier._count_tools_in_current_turn(sid)` reads `~/.hermes/sessions/<sid>.jsonl` to count tool calls in the current turn. For CLI one-shot sessions (`hermes chat -q`), this file does not exist — `hermes_cli/oneshot.py::_create_session_db_for_oneshot` writes session data only to `~/.hermes/state.db`, not to the per-session JSONL the gateway uses.

  With JSONL absent → `_count_tools_in_current_turn` returns 0. The `on_session_end` payload also doesn't include `response` text, so `response_preview = ""` → `len < 200`. Both heuristic-skip conditions match (`tool_count == 0` AND `response < 200 chars`) → the classifier correctly takes the trivial-skip path and writes no marker. Every CLI substantive turn is now silently mis-classified as trivial.

  Evidence:
  - sid `20260513_225231_cf97de` (CLI turn at 22:52, 2 API calls, 1 tool call): no `~/.hermes/sessions/<sid>.jsonl`, no marker file
  - Direct `invoke_hook("on_session_end", session_id="20260513_225231_cf97de", ...)` produces no marker either — the callback runs, takes the trivial-skip branch, returns
  - state.db sessions row HAS the substance signal: `tool_call_count`, `message_count`, `input_tokens`, etc. are all populated for the CLI turn
options_for_closure:
  - "(a) Rewrite `_count_tools_in_current_turn` to read `state.db.sessions.tool_call_count` (and possibly `message_count`) FIRST, with JSONL fallback. state.db is the universal source of truth for every session source (gateway, CLI, interactive, ACP, cron). The classifier already opens state.db for the parent_session_id walk — add one query against the same row."
  - "(b) Make the substance heuristic conditional on JSONL existence: if absent, fall through to LLM classification (no trivial-skip). Risk: every silent CLI turn (e.g., a one-word `/help` query) costs an LLM call. Less defensible than (a)."
  - "(c) Modify Hermes upstream to write JSONL for CLI sessions too. Out of scope (we don't own hermes-agent)."
recommended_action: |
  Run `/gsd-plan-phase 6 --gaps` for plan 06-03. Option (a) is the right call: state.db query is one extra parameterized SELECT, the classifier already opens state.db mode=ro, and the test fixtures can stay (just add the missing JSONL-absent test that this UAT proved was missing). Also add a NEGATIVE test: state.db row with tool_call_count > 0 + missing JSONL must NOT trigger trivial-skip.

  This is the test gap the round-1 code review flagged as "test fixture safety: do tests properly isolate by tmpdir?" — the answer was yes, but the tmpdir always created the JSONL, so the "JSONL absent" branch was untested. Plan 06-03 closes both the code gap and the missing-test gap.

### Test 1 — UAT round 2 sub-results (2026-05-13T22:50Z on Mac Studio against gsd/phase-6-uat @ 5f493c0)

result: failed (still — different root cause)
sub_results:
  - step: "(1) setup-local.sh installs plugin + edits config.yaml"
    status: pass
    evidence: "stdout: 'Installed plugin to /Users/johndemic/.hermes/plugins/revenium-classifier' AND 'Added plugins.enabled block to /Users/johndemic/.hermes/config.yaml'; on-disk plugin tree contains plugin.yaml + __init__.py + classifier.py + test-payloads/; config.yaml ends with `plugins:\\n  enabled:\\n    - revenium-classifier`"
  - step: "(2) hermes gateway restart"
    status: pass
    evidence: "'✓ Service restarted' at 2026-05-13 22:52:01"
  - step: "(3) Gateway startup loads the plugin"
    status: pass
    evidence: "`hermes plugins list` reports revenium-classifier as 'enabled' from 'user' source; direct `mgr.discover_and_load(force=True)` shows `Plugin revenium-classifier registered hook: on_session_end` and `mgr._hooks['on_session_end'] = [_on_session_end]`. Note: the gateway startup log does NOT print a plugin-load line analogous to the old `[hooks] Loaded hook ...` — plugin loading is silent (Hermes only logs at DEBUG level)."
  - step: "(4) CLI substantive turn → marker file with non-unclassified task_type"
    status: fail
    evidence: |
      CLI substantive turn driven via `hermes chat -q "Read /Users/johndemic/.hermes/skills/revenium/scripts/budget-check.sh and tell me in 2-3 sentences what halt transition logic it implements."` (sid=20260513_225231_cf97de, 2 API calls, 1 tool call, "Turn ended: reason=text_response", model=qwen/qwen3.6-plus, platform=cli).
      Marker file at ~/.hermes/state/revenium/markers/20260513_225231_cf97de.jsonl NOT created.
      Direct callback invocation via `invoke_hook("on_session_end", session_id="20260513_225231_cf97de", ...)` ALSO produced no marker file — confirming the callback runs but exits via trivial-skip.
      Root cause: G-02 (above) — `_count_tools_in_current_turn` returns 0 for CLI sessions because the gateway-style JSONL is absent.
  - step: "(5) Next cron tick ships --task-type to Revenium"
    status: blocked
    evidence: "Still blocked — no marker file from step (4)."
