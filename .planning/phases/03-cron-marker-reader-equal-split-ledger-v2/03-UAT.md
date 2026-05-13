---
status: testing
phase: 03-cron-marker-reader-equal-split-ledger-v2
source: [03-01-SUMMARY.md]
started: 2026-05-13T00:55:00Z
updated: 2026-05-13T00:55:00Z
---

## Current Test
<!-- OVERWRITE each test - shows where we are -->

number: 2
name: Cron runs against local state.db without errors
expected: |
  Run `bash skills/revenium/scripts/cron.sh` against your real ~/.hermes/state.db
  (or against the installed copy at ~/.hermes/skills/revenium/scripts/cron.sh).
  No traceback. Either ships token deltas for any sessions with non-zero growth,
  or logs "No sessions with token usage found", or warns about missing state.db /
  unconfigured revenium — all are valid outcomes. The exit code is 0.
awaiting: user response

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
result: [pending]

### 3. Lock contention is observable
expected: |
  In one terminal: `bash -c 'exec 9>/tmp/test-cron.lock; python3 -c "import fcntl, time; fcntl.flock(9, fcntl.LOCK_EX); time.sleep(20)"'`
  In a second terminal, with the lock held:
  `HERMES_HOME=/tmp/test-hh REVENIUM_STATE_DIR=/tmp/test-hh/state/revenium mkdir -p /tmp/test-hh/state/revenium && LOCK_FILE=/tmp/test-cron.lock bash skills/revenium/scripts/cron.sh`
  The second invocation logs "prior tick still active, skipping this minute" and exits 0.
result: [pending]

### 4. "How attribution works" section reads as intended for an operator
expected: |
  Open skills/revenium/references/setup.md. The "## How attribution works" section
  contains the D-16 locked paragraph verbatim (GUARDRAIL share is overstated when
  work turns are much larger than classification turns; read as an upper bound,
  not an estimate; S2 equal-split is intentionally simple; S3/S4 deferred to v2).
  The follow-on context paragraphs name the log file path, the marker fields driving
  attribution, and the zero-marker fallthrough behavior. The framing is clear to
  someone reading it cold.
result: [pending]

### 5. SUMMARY.md is honest about deviations
expected: |
  Open .planning/phases/03-cron-marker-reader-equal-split-ledger-v2/03-01-SUMMARY.md.
  The "Decisions Made" / "Deviations from Plan" section documents both load-bearing
  deviations from the plan: (a) the flock heredoc form correction (bare fd-9
  inheritance instead of the broken <&9 redirect), and (b) parse_prior_state's
  shift to global per-sid muid dedup with the ts cutoff demoted to v1-only fallback.
  The rationale for each is concrete and references the specific test that
  surfaced the issue. No vague "improvements" language.
result: [pending]

## Summary

total: 5
passed: 1
issues: 0
pending: 4
skipped: 0

## Gaps

[none yet]
