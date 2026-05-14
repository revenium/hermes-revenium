---
phase: 06-mechanical-classification-agent-end-hook
plan: 03
subsystem: plugins
tags: [plugins, hermes-cli, on-session-end, state-db, tool-count, cli-coverage, gap-closure]

# Dependency graph
requires:
  - plan: 06-02-PLAN.md
    provides: Plugin tree (plugin.yaml + __init__.py + classifier.py + 3 fixtures); shared classifier module with the original JSONL-only `_count_tools_in_current_turn` that this plan rewrites.
provides:
  - "Universal tool-count signal — state.db.sessions.tool_call_count is the primary source (populated for every session source: CLI, gateway, interactive, ACP, cron); JSONL is the fallback."
  - "Closes G-02 in code: CLI substantive turns no longer mis-classify as trivial because the gateway-style JSONL is absent."
  - "Four new HOOK-12 tests pin the regression guard: state.db hit, JSONL fallback, both absent, and the end-to-end CLI-substantive-turn-without-JSONL behavioral test."
  - "ROADMAP Phase 6 SC2 explicitly calls out the CLI-coverage invariant via the new 'state.db row with tool_call_count > 0 and NO ~/.hermes/sessions/<sid>.jsonl' clause."
affects: [phase-04-wire-enrichment, phase-05-housekeeping, hermes-uat]

# Tech tracking
tech-stack:
  added:
    - "Parameterized state.db SELECT under the existing mode=ro URI form (no new module-level imports — sqlite3 was already imported for _walk_to_root_session)"
  removed:
    - "JSONL-only tool-count source — JSONL remains as fallback, no longer primary"
  patterns:
    - "Source-of-truth swap with minimum-blast-radius: rewrite a single helper's body, preserve the original implementation as a named fallback branch, keep all callers and the function signature untouched"
    - "Reuse-of-established-state.db-read-pattern: mirror `sqlite3.connect(f'file:{STATE_DB}?mode=ro', uri=True)` from `_walk_to_root_session` at classifier.py:60-65 — same URI form, same exception envelope, same D-04 belt"

key-files:
  created:
    - ".planning/phases/06-mechanical-classification-agent-end-hook/06-03-SUMMARY.md"
  modified:
    - "skills/revenium/plugins/revenium-classifier/classifier.py"
    - "tests/test_repository.py"
    - ".planning/REQUIREMENTS.md"
    - ".planning/ROADMAP.md"
    - ".planning/phases/06-mechanical-classification-agent-end-hook/06-VERIFICATION.md"
  deleted: []

# Key decisions honored
key-decisions:
  - "D-20 (locked in CONTEXT.md addendum #2): switch tool-count source from per-session JSONL to state.db.sessions.tool_call_count primary, JSONL fallback. state.db is the universal source — populated for every session source. Classifier already opens state.db mode=ro for the parent-session walk; one additional parameterized SELECT against the same row closes the gap."
  - "D-04 (preserved): _count_tools_in_current_turn returns an int on every code path and NEVER raises out of the helper. Any sqlite3.OperationalError on the new SELECT falls through to the JSONL path; any error in the JSONL path falls through to 0."
  - "Scope discipline (locked in CONTEXT.md addendum #2 'Out of scope (deliberately)'): NO changes to heuristic-skip threshold, response-text signal, CR-01/CR-02/CR-03 from 06-02-REVIEW.md, existing 12 HOOK-* tests, __init__.py signature, setup-local.sh, references/setup.md, HOOK-01..HOOK-11 entry strings, SKILL.md, or the cron pipeline."

# Patterns established
patterns-established:
  - "Parameterized state.db SELECT under existing mode=ro URI — minimum-blast-radius source-of-truth swap pattern that future helpers can mirror. The same file already used this pattern in `_walk_to_root_session` for the parent-session walk; 06-03 extends it to tool-count without introducing a new connection or new pattern."
  - "Test-pair around a source-of-truth swap: one primary-source-wins test + one fallback-source-wins test + one both-absent test + one end-to-end behavioral test that proves the swap fixes the production bug it was meant to fix. This is the CI shape the round-1 plan-checker should have asked for on 06-02."

requirements-completed: [HOOK-01, HOOK-02, HOOK-03, HOOK-04, HOOK-05, HOOK-06, HOOK-07, HOOK-08, HOOK-09, HOOK-10, HOOK-11, HOOK-12]

duration: ~10min (interrupted by transient Cloudflare 522 mid-execution; T01-T04 landed via worktree executor, T05+T06 completed inline after the worktree merged cleanly)
completed: 2026-05-14
---

# Phase 06 Plan 03: Gap-closure — state.db tool-count source-of-truth swap Summary

Rewrote `_count_tools_in_current_turn` to query `state.db.sessions.tool_call_count` first (universal source — populated for every session source) with JSONL as fallback, closing G-02 surfaced by Mac Studio UAT round 2.

## Performance

- **Tasks:** 6 (T01..T06) — all complete
- **Commits:** 6 atomic commits (4 via worktree executor, 1 worktree-merge commit, 1 inline VERIFICATION.md commit, 1 inline SUMMARY commit — same atomicity as if all 6 had landed via a single executor)
- **Files modified:** 5
- **Files created:** 1 (this SUMMARY.md)
- **Files deleted:** 0
- **Tests:** 27 → 31 (4 new HOOK-12 tests); all green at every commit
- **Production code diff:** +35 / -7 lines in `classifier.py` — contained entirely within `_count_tools_in_current_turn`'s function body

## Accomplishments

- Rewrote `_count_tools_in_current_turn(sid: str) -> int` in `skills/revenium/plugins/revenium-classifier/classifier.py`. New control flow: open `state.db` via the existing `sqlite3.connect(f'file:{STATE_DB}?mode=ro', uri=True)` URI form, run `SELECT tool_call_count FROM sessions WHERE id = ?` parameterized, return that int when present and non-NULL. On `sqlite3.OperationalError` or row miss or NULL value, fall through to the preserved JSONL-reading code path (existing implementation moved inside the fallback branch — not rewritten, not deleted). On JSONL absent or any read error in the fallback, return 0. D-04 invariant: every path returns an int, never raises out of the helper.
- Added 3 new unit tests in `tests/test_repository.py`:
  - `test_revenium_classifier_tool_count_from_state_db_primary` — state.db row with `tool_call_count=3` AND no JSONL file → helper returns 3 (state.db primary path).
  - `test_revenium_classifier_tool_count_jsonl_fallback_when_state_db_missing` — no state.db row for the sid (or `tool_call_count=NULL`) AND a JSONL with 5 `role:"tool"` entries → helper returns 5 (JSONL fallback path).
  - `test_revenium_classifier_tool_count_zero_when_both_absent` — neither state.db row nor JSONL → helper returns 0 (heuristic-skip-on-empty-session contract pinned explicitly).
- Added 1 new end-to-end behavioral test in `tests/test_repository.py`:
  - `test_revenium_classifier_tool_count_end_to_end_cli_substantive` — synthetic state.db with `INSERT INTO sessions (id, source, started_at, tool_call_count) VALUES ('cli-sid', 'cli', 0, 2);` + NO JSONL at `~/.hermes/sessions/cli-sid.jsonl` + mocked `call_llm` returning `code_review` + seeded taxonomy + non-halted budget-status.json → assert the marker file appears with exactly 2 records, both `task_type='code_review'` and `{GUARDRAIL, CHAT}` operation_types. This is the CI regression guard that would have caught G-02 on 2026-05-13.
- Added `HOOK-12` to `.planning/REQUIREMENTS.md` (entry + traceability row + Coverage bump 48→49); updated `.planning/ROADMAP.md` Phase 6 with: HOOK-12 in Requirements line, new SC2 wording explicitly calling out the `state.db row with tool_call_count > 0 and NO ~/.hermes/sessions/<sid>.jsonl` invariant, 06-03-PLAN.md added to Plans list, Categories HOOK (11)→(12), Progress Table row 2/2 → 2/3.
- Updated `06-VERIFICATION.md`: G-02 transitioned to `gap_closure: executed` with `gap_closure_plan: 06-03-PLAN.md` and a new `gap_closure_outcome` field documenting the code-side closure. Frontmatter `status: requires_rerun_uat` PRESERVED verbatim. `re_verification.gaps_remaining: [G-01, G-02]` PRESERVED — both gaps stay until operator UAT round 3 confirms behavioral closure.

## Task Commits

1. `36b6dd5` feat(06): rewrite `_count_tools_in_current_turn` to use `state.db.sessions.tool_call_count` primary with JSONL fallback (closes G-02)
2. `e5c70f9` docs(06): add HOOK-12 requirement and update Phase 6 SC2 for state.db tool-count primary source
3. `d849574` test(06): add 3 unit tests for state.db-primary + JSONL-fallback + both-absent tool-count branches (HOOK-12)
4. `0de55ed` test(06): add end-to-end CLI-without-JSONL test for tool-count source-of-truth swap (HOOK-12 / G-02)
5. `070ceb0` chore: merge executor worktree (worktree-agent-a6b24d74657c8e03e) — Phase 6 06-03 T01-T04 (partial — API timeout; T05+T06 completed inline after merge)
6. `42e8238` docs(06): mark G-02 gap_closure: executed in 06-VERIFICATION.md (status preserved at requires_rerun_uat)
7. (this commit) docs(06): summarize 06-03 — G-02 closure via state.db tool-count + UAT-3 gate references both gaps

Per the plan's commit_strategy, every commit left `python3 -m unittest discover -s tests -p 'test_*.py' -v` green. The worktree executor delivered T01-T04 atomically before a transient Cloudflare 522 cut the connection; T05+T06 were completed inline because both are pure documentation edits with no executor value-add beyond following the plan instructions.

## Decisions Honored

- **D-20 (state.db primary + JSONL fallback):** delivered fully. The new SELECT lands inside the existing `sqlite3.connect(uri, uri=True)` mode=ro envelope; the JSONL implementation is preserved verbatim as the fallback branch. No new module-level imports; no new connection lifecycle pattern; no change to the function signature or callers.
- **D-04 (helper never raises):** every exception path is caught at the appropriate layer. The new state.db code wraps the SELECT in try/except `sqlite3.OperationalError` (fall through to JSONL); the outer try/except `Exception` (the D-04 belt that was already in place around the JSONL path) covers any remaining surface. Every path returns an int.
- **Scope discipline (CONTEXT.md addendum #2):** the diff is contained entirely within `_count_tools_in_current_turn`'s function body. No other function in `classifier.py` is touched; `__init__.py` is untouched; the existing 12 HOOK-* tests are untouched and still pass (they don't seed state.db, so they fall through to the JSONL fallback and return the same values as before).

## Manual UAT gate

Phase 6 cannot be marked verified until 06-HUMAN-UAT.md G-01 AND G-02 result move from "failed" to "pass"

Operator runbook (UAT round 3, on the Mac Studio against `gsd/phase-6-uat` once it advances past this commit):

1. `hermes gateway restart` — confirm the `revenium-classifier` plugin still loads. (No setup re-run needed; the Mac Studio's config.yaml already has `plugins.enabled: [revenium-classifier]` from UAT round 2.)
2. Drive a substantive turn via CLI: `hermes chat -q "<a multi-step prompt that triggers tool use>"` WITHOUT loading the `revenium` skill and without executing any FINAL ACTION classification code. Confirm `~/.hermes/state/revenium/markers/<sid>.jsonl` contains a GUARDRAIL+CHAT pair with a non-`unclassified` `task_type`. This is the test that retires G-02 (and, by transitivity, retires G-01's behavioral block — G-01 was architecturally closed by 06-02 but stayed behaviorally blocked by G-02).
3. (Optional) Drive a Telegram message through the gateway and confirm the marker shape is unchanged (the on_session_end plugin already fires for gateway-served sessions per UAT round 2's plugin-load confirmation).
4. Wait for the next cron tick (~60s); confirm `revenium meter completion` is invoked with `--task-type <meaningful-label>` (not `unclassified`) by tailing `~/.hermes/state/revenium/revenium-metering.log`.

Until UAT round 3 records BOTH G-01 result = `pass` AND G-02 result = `pass` in `06-HUMAN-UAT.md`: `06-VERIFICATION.md` frontmatter remains `status: requires_rerun_uat`; `re_verification.gaps_remaining` still lists `[G-01, G-02]`; Phase 6 Progress Table row stays at `2/3 In progress — G-02 gap closure planned in 06-03-PLAN.md` (NOT `Verified`). The Phase 6 row transitions to `3/3 Verified` only after operator UAT round 3 retires both gaps.

## Backward compatibility

D-17 + D-18 zero-diff invariants preserved. `git diff` against the pre-06-03 base produces zero lines for: SKILL.md, hermes-report.sh, split_strategies.py, cron.sh, common.sh, task-taxonomy.json, references/task-taxonomy.md, references/halt-survivability.md, references/setup.md, examples/setup-local.sh. Cron-side pipeline behavior unchanged: existing sessions that already have markers continue to ship with their recorded `task_type`; sessions with no marker continue to ship as `task_type=unclassified` per the cron's existing D-18 default; new markers produced by the on_session_end plugin (post-06-03) carry the LLM-classified label.

The existing 12 HOOK-* tests pass unchanged. They synthesize tmpdir JSONL fixtures with no state.db row for the synthetic sid, so the new state.db primary path falls through (`sqlite3.OperationalError` / row miss) into the preserved JSONL fallback, which returns the same values as before the rewrite.

## Self-Check

- [x] All 5 modified files have been edited (classifier.py, tests/test_repository.py, REQUIREMENTS.md, ROADMAP.md, 06-VERIFICATION.md)
- [x] 7 commits landed atomically (one per task plus the worktree-merge boundary)
- [x] 4 new HOOK-12 tests pass: `test_revenium_classifier_tool_count_from_state_db_primary`, `test_revenium_classifier_tool_count_jsonl_fallback_when_state_db_missing`, `test_revenium_classifier_tool_count_zero_when_both_absent`, `test_revenium_classifier_tool_count_end_to_end_cli_substantive`
- [x] Full test suite green (31 tests; 27 pre-existing + 4 new HOOK-12)
- [x] `06-VERIFICATION.md` frontmatter `status: requires_rerun_uat` is PRESERVED (the load-bearing gate for Phase 6 verification)
- [x] `06-VERIFICATION.md::re_verification.gaps_remaining: [G-01, G-02]` is PRESERVED
- [x] `_count_tools_in_current_turn` returns an int on every path, never raises (D-04 invariant)
- [x] No edits to setup-local.sh, references/setup.md, __init__.py, SKILL.md, hermes-report.sh, split_strategies.py, cron.sh, common.sh, task-taxonomy.json, or HOOK-01..HOOK-11 entry strings (scope discipline)
- [x] `test_no_legacy_branding_left` passes — no forbidden tokens in any new content
