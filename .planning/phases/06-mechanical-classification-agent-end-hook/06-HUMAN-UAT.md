---
status: partial
phase: 06-mechanical-classification-agent-end-hook
source: [06-VERIFICATION.md]
started: 2026-05-13T19:02:08Z
updated: 2026-05-13T19:02:08Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Gateway startup + substantive turn UAT (ROADMAP SC1, SC2, SC6)
expected: |
  (1) `bash examples/setup-local.sh` succeeds and reports `Installed hook to ~/.hermes/hooks/revenium-classifier`.
  (2) `hermes gateway restart` succeeds.
  (3) Gateway startup log emits: `[hooks] Loaded hook 'revenium-classifier' for events: ['agent:end']`.
  (4) After a substantive turn in a fresh Hermes session (no skill_view("revenium"), no manual classification), `~/.hermes/state/revenium/markers/<sid>.jsonl` contains a GUARDRAIL+CHAT marker pair with a meaningful (non-`unclassified`) `task_type`.
  (5) On the next cron tick, `revenium meter completion` is invoked with `--task-type <meaningful-label>` (not `unclassified`).
why_human: |
  Requires a running Hermes gateway process, a real substantive turn through an LLM, and Revenium CLI configuration — cannot be exercised in CI. This is the manual UAT gate the SUMMARY.md flags before Phase 6 is marked Verified.
result: [pending]

### 2. Subagent inheritance UAT (ROADMAP SC3)
expected: |
  A subagent session whose `state.db.sessions.parent_session_id` points at a root session with task_type=research produces a marker file at `~/.hermes/state/revenium/markers/<child-sid>.jsonl` carrying `task_type: research` on both records, with NO LLM call recorded against the subagent budget.
why_human: |
  Hermes' subagent dispatch (delegate_task lineage, real state.db.sessions parent chain) cannot be exercised without running Hermes end-to-end. Synthetic test (`test_revenium_classifier_subagent_inherits`) proves the helpers correctly, but operator confirmation of real-world `parent_session_id` shape is required (ROADMAP SC3).
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
