---
phase: 05-housekeeping-compat-hardening
plan: 03
type: execute
status: complete
requirements_completed:
  - COMPAT-04
  - TEST-05
files_modified:
  - skills/revenium/scripts/hermes-report.sh
  - tests/test_repository.py
files_created:
  - .planning/phases/05-housekeeping-compat-hardening/05-03-SUMMARY.md
tests_added: 1
tests_modified: 2
tests_total_after: 45
commits:
  - T01: eb23d8d feat(05-03): WR-01 / D-34 pipe-safety sanitization in split_rows + regression test
  - T02: ed87520 refactor(05-03): WR-02 / D-35 drop dead local row var in hermes-report.sh main
  - T03: c3be715 test(05-03): WR-03 / D-36 extend base_env env isolation in Phase 4 wire tests
tags:
  - phase-4-cleanup
  - pipe-safety
  - dead-code-removal
  - test-env-isolation
completed_at: "2026-05-15T01:13:48Z"
duration_minutes: 15
---

# Phase 05 Plan 03: WR-01 pipe-sanitization + WR-02 dead-var removal + WR-03 test env isolation

## One-liner

Three Phase 4 review WRs closed: pipe-safety sanitization of `|`/`\n`/`\r` in split_rows heredoc (WR-01), dead `local row` variable removed from while-read declaration (WR-02), and `base_env` extended with three `REVENIUM_*` env overrides in two Phase 4 wire test methods (WR-03).

## Outcome

All three WRs from `04-REVIEW.md` that were folded into Phase 5 are now closed. The marker pipe-row protocol is defense-in-depth: future upstream writers cannot desynchronize the 11-field `IFS='|'` bash parser by embedding control characters in `agent` or `trace_id` fields. The test suite now stands at 45 tests, all green.

## Decisions Honored

### D-34 (WR-01) — Pipe-safety sanitization in split_rows heredoc

The `split_rows` Python heredoc in `hermes-report.sh` previously relied on a social-contract comment (`# NOTE: m_agent / m_trace values MUST NOT contain '|'`). The comment was replaced with a 3-iteration sanitization loop that replaces `|`, `\n`, and `\r` with `_` in both `m_agent` and `m_trace` before the pipe-delimited `print(...)` call. The 9-field print prefix (fields 1-9) is byte-unchanged; only the content of fields 10-11 is now sanitized. The `<<'PY'` heredoc prevents bash interpolation; Python reads the escape sequences with standard Python semantics. Empty strings (the universal case today per D-23) sanitize to empty strings — no behavioral change for current production output.

### D-35 (WR-02) — Dead `local row` variable removed

The `local row` token was declared at line 549 in `hermes-report.sh::main` but never referenced anywhere in the file. It was a relic from a pre-11-pipe iteration where rows were read into `row` first before parsing. The single-token deletion makes the local declaration match the 11-variable `while IFS='|' read -r ...` header exactly. `set -u` now provides defense-in-depth: any future accidental reference to `row` will bark immediately.

### D-36 (WR-03) — Test env isolation via explicit base_env overrides

The two Phase 4 wire test methods (`test_wire_agent_trace_passthrough` and `test_wire_no_provider_regression_per_class`) inherit `os.environ` into their `base_env` dict. A developer with `REVENIUM_MARKERS_DIR`, `REVENIUM_MARKERS_READY_DIR`, or `REVENIUM_TAXONOMY_FILE` exported in their shell could leak those into the cron subprocess, causing it to read/write against the developer's real `~/.hermes/state/revenium/` directory. The fix adds three explicit overrides pointing at tmpdir-isolated paths. The existing `**os.environ` inheritance is preserved for other vars (PATH, HOME, etc.) per `04-REVIEW.md` WR-03 guidance to use the additive-override approach.

## Key Files

| File | Change | Commit |
|------|--------|--------|
| `skills/revenium/scripts/hermes-report.sh` | WR-01 sanitization loop in split_rows heredoc; WR-02 `local row` removal | eb23d8d, ed87520 |
| `tests/test_repository.py` | New `test_hermes_report_pipe_safety_marker_sanitization`; WR-03 base_env extensions in 2 methods (3 constructions) | eb23d8d, c3be715 |

## Verification

All acceptance criteria confirmed at each commit boundary:

- `bash -n skills/revenium/scripts/hermes-report.sh` exits 0 (verified after T01 and T02)
- `grep -c "WR-01: sanitize pipe-delimiters" ...` returns 1
- `grep -c "for _bad in" ...` returns 1
- `grep -c "MUST NOT contain '|'" ...` returns 0 (old comment removed)
- `grep -c "local row muid t_type" ...` returns 0 (dead var removed)
- `grep -wn "row" ...` shows only comments (no variable references)
- `grep -c "'REVENIUM_MARKERS_DIR':" tests/test_repository.py` returns 9 (3 existing tests + 6 other occurrences)
- `python3 -m unittest discover -s tests -p 'test_*.py'` reports 45 tests, OK at every commit boundary

## Operator Verification

No manual steps required. All changes are infrastructure hardening with automated test coverage. The new `test_hermes_report_pipe_safety_marker_sanitization` test exercises the pathological `bad|value` / `bad\nvalue` marker fixture and asserts the sanitized `bad_value` appears in `--agent` and `--trace-id` argv without desynchronizing the 11-field parser.

## Out of Scope Carried Forward

- `_count_tools_in_current_turn` removal (D-37 — explicit KEEP, not touched)
- The `'${model}'` shell interpolation in hermes-report.sh Python heredocs (04-REVIEW.md IN-02 / D-38 — deferred to a future hardening pass; state.db is trusted by this skill's threat model)
- Docs pass: README.md / setup.md / task-taxonomy.md / PROJECT.md / REQUIREMENTS.md / ROADMAP.md (Plan 05-04 owns this)

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| `05-03-SUMMARY.md` exists | FOUND |
| T01 commit eb23d8d exists | FOUND |
| T02 commit ed87520 exists | FOUND |
| T03 commit c3be715 exists | FOUND |
