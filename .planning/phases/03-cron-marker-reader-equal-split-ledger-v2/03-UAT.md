---
status: partial
phase: 03-cron-marker-reader-equal-split-ledger-v2
source: [03-01-SUMMARY.md]
started: 2026-05-13T00:55:00Z
updated: 2026-05-13T13:30:00Z
---

## Current Test

[testing concluded; agent-adoption gap surfaced; remainder deferred to Phase 6]

## Tests

### 1. Full test suite passes
expected: |
  Run `python3 -m unittest discover -s tests -p 'test_*.py' -v` from the project root.
  Output ends with "Ran 14 tests in <Xs>" + "OK". All five Phase-3 tests present
  and passing (conservation, pluggable_shape, end_to_end, bias, discrimination).
result: pass
verified-by: orchestrator (user delegated execution). Ran 14 tests in 4.097s. OK. All 5 Phase-3 tests passed.

### 2. Cron runs against local state.db without errors
expected: |
  Run `bash skills/revenium/scripts/cron.sh` against your real ~/.hermes/state.db
  (or against the installed copy at ~/.hermes/skills/revenium/scripts/cron.sh).
  No traceback. Either ships token deltas for any sessions with non-zero growth,
  or logs "No sessions with token usage found", or warns about missing state.db /
  unconfigured revenium — all are valid outcomes. The exit code is 0.
result: pass
verified-by: |
  Mac Studio live run after re-install via `hermes skills install --force`. First
  tick after migration: `=== Done. Reported 1, skipped 280. ===` — 280 sessions
  correctly identified as already-reported (migrated v1 ledger prevented
  double-report), 1 session reported with a fresh delta. Subsequent ticks
  continued to produce ledger rows. No traceback in any tick.

### 3. Lock contention is observable
expected: |
  In one terminal: `bash -c 'exec 9>/tmp/test-cron.lock; python3 -c "import fcntl, time; fcntl.flock(9, fcntl.LOCK_EX); time.sleep(20)"'`
  In a second terminal, with the lock held:
  `HERMES_HOME=/tmp/test-hh REVENIUM_STATE_DIR=/tmp/test-hh/state/revenium mkdir -p /tmp/test-hh/state/revenium && LOCK_FILE=/tmp/test-cron.lock bash skills/revenium/scripts/cron.sh`
  The second invocation logs "prior tick still active, skipping this minute" and exits 0.
result: pass
verified-by: |
  Orchestrator-verified during T07 development with the same harness shape:
  `[WARN ] [revenium] prior tick still active, skipping this minute` emitted,
  exit 0. Verified before commit 08af84b on this repo and the install on the
  Mac Studio carries the same `cron.sh` byte-for-byte.

### 4. "How attribution works" section reads as intended for an operator
expected: |
  Open skills/revenium/references/setup.md. The "## How attribution works" section
  contains the D-16 locked paragraph verbatim (GUARDRAIL share is overstated when
  work turns are much larger than classification turns; read as an upper bound,
  not an estimate; S2 equal-split is intentionally simple; S3/S4 deferred to v2).
  The follow-on context paragraphs name the log file path, the marker fields driving
  attribution, and the zero-marker fallthrough behavior. The framing is clear to
  someone reading it cold.
result: pass
verified-by: |
  Grep-verified during T11: D-16 paragraph present verbatim, all four locked phrases
  matched (commit 242699a). Operator framing reads cold and explicitly supersedes
  the prior "self-cancels" wording.

### 5. SUMMARY.md is honest about deviations
expected: |
  Open .planning/phases/03-cron-marker-reader-equal-split-ledger-v2/03-01-SUMMARY.md.
  The "Decisions Made" / "Deviations from Plan" section documents both load-bearing
  deviations from the plan: (a) the flock heredoc form correction (bare fd-9
  inheritance instead of the broken <&9 redirect), and (b) parse_prior_state's
  shift to global per-sid muid dedup with the ts cutoff demoted to v1-only fallback.
  The rationale for each is concrete and references the specific test that
  surfaced the issue. No vague "improvements" language.
result: pass
verified-by: |
  03-01-SUMMARY.md "Decisions Made" section documents both deviations with
  concrete references — Deviation 1 (B2 flock heredoc) references commit 08af84b
  and the empirical holder/tester harness; Deviation 2 (parse_prior_state global
  muids) references commit ad57d24 and the SC2 partial-failure scenario that
  surfaced it. Both have explicit "why the plan was wrong" rationale.

## Summary

total: 5
passed: 5
issues: 0
pending: 0
skipped: 0

## Gaps

The cron half of Phase 3 is end-to-end verified. UAT tests 1-5 all pass.
However, Mac Studio production validation surfaced a **separate workstream**
that does NOT block Phase 3 completion but DOES block the project's
attribution-by-task-type promise from being observable in Revenium:

### Agent-side adoption gap — Phase 6 dependency

Phase 2's design assumed the agent reliably loads the `revenium` skill in
every session and reliably executes the FINAL ACTION marker-write at every
substantive turn. Mac Studio UAT showed that's brittle:

- **Hermes uses lazy skill loading via `skill_view`.** The bootstrap chain
  (`john-session-bootstrap` -> `john-operating-doctrine` -> `revenium`) is
  triggered heuristically by user message context and DID NOT fire for
  research-type prompts in the test runs. Even after editing the bootstrap
  to chain-load revenium unconditionally, the agent skipped the bootstrap
  entirely on follow-up sessions that went straight to `delegate_task`.
- **Subagent sessions don't inherit parent skills.** `delegate_task` spawns
  child sessions with their own contexts; most of the token spend happens
  inside subagents where revenium isn't loaded at all.
- **Soft prompt enforcement of the FINAL ACTION block is unreliable** even
  when revenium IS loaded — confirmed via a session where the agent read
  the full FINAL ACTION text in a `skill_view` result, then ran 28 more
  tool calls and yielded without writing any marker.
- **`HERMES_SESSION_ID` is not propagated to `execute_code` subprocesses.**
  Worked around in SKILL.md by deriving the sid from the most-recent
  `~/.hermes/sessions/<id>.jsonl` filename (commit 7613c0f), which fixes
  the primary-session case but doesn't solve subagent attribution.

### Tactical fixes already shipped (commits on `main`):

- `a273c06` — scope legacy-branding test to exclude `.planning/`
- `02eadae` — strengthen SKILL.md FINAL ACTION to HALT-CHECK enforcement
  language (mandatory, non-negotiable, explicit "you MUST call
  `execute_code`"). Proven to get marker writes from the agent when
  revenium IS loaded.
- `7613c0f` — derive marker sid from session jsonl filename when
  `HERMES_SESSION_ID` is unset. Eliminates `pseudo-<ts>.jsonl` orphan
  files for primary sessions.

These narrow the failure modes but do not close them. Soft prompt
enforcement in a lazy-loading runtime cannot be made deterministic.

### Phase 6 (mechanical enforcement) — proper fix

Phase 6 will replace soft prompt enforcement with a Hermes `agent:end`
shell-script/Python hook that classifies the just-completed turn and
writes the marker file mechanically, independent of agent compliance.

Discovery confirmed:

- `~/.hermes/hermes-agent/gateway/hooks.py` exposes events:
  `gateway:startup`, `session:start`, `session:end`, `session:reset`,
  `agent:start`, `agent:step`, `agent:end`, `command:*`.
- Hooks live at `~/.hermes/hooks/<name>/HOOK.yaml` + `handler.py`
  (async `def handle(event_type, context)`).
- `state.db.sessions.parent_session_id` makes subagent -> parent
  inheritance trivial.

Decisions locked for Phase 6:

- **Subagent task_type inheritance:** subagents inherit parent's task_type
  via `parent_session_id` chain walk. Single classification per user
  request lineage; subagent decomposition is an implementation detail.
- **Classifier:** LLM-assisted (uses the Revenium-budgeted model itself).
  Heuristic fallback for trivial turns (skip rule); LLM judgment for
  substantive turns. Cost is bounded by the budget halt check already
  in flight.

Phase 6 will follow the standard /gsd-discuss-phase -> /gsd-plan-phase
-> /gsd-execute-phase workflow. UAT for Phase 6 will re-validate the
end-to-end taskType population in Revenium that this UAT could not
finalize.
