---
phase: 26-pagination-stderr-compatibility
plan: 02
subsystem: infra
tags: [bash, stderr, mktemp, trap, revenium-cli, guardrails, test-harness]

# Dependency graph
requires:
  - phase: 26-pagination-stderr-compatibility (plan 01)
    provides: "supports_flag() capability probe, argv-recording _make_revenium_stub test harness"
provides:
  - "CLI_STDERR_TMP_TEMPLATE state-path constant in common.sh (D-06)"
  - "Stream-split enforcement-rules fetch in guardrail-check.sh — ENFORCEMENT_JSON is stdout-only"
  - "Relocated (not deleted) empty-team EOF soft-fail, now reading both streams (D-05)"
  - "stderr_note / enforcement_stderr kwargs on _make_revenium_stub"
  - "_normalize_guardrail_status test helper (timestamp-blanking dict comparator)"
  - "First-ever test coverage for the empty-team EOF soft-fail"
affects: [26-03-hot-path-pagination, 26-04-invariant-tests]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "STATE_DIR-based mktemp + EXIT trap for splitting a CLI call's stdout from stderr without losing either stream (D-06) — first trap in guardrail-check.sh, disqualified the SHADOW_TMP lookalike as a model (wrong directory, no trap, different purpose)"
    - "Grep-both-streams-concatenated soft-fail relocation: printf '%s\\n%s\\n' \"$stdout\" \"$stderr\" | grep -q pattern — reproduces a pre-split 2>&1 grep's input set exactly, so a stream split cannot narrow a soft-fail's trigger set"
    - "Stub-level stderr injection: an unconditional per-invocation stderr_note plus a case-specific enforcement_stderr kwarg, both defaulted None so every prior _make_revenium_stub caller is unaffected"
    - "Timestamp-normalizing dict comparator (_normalize_guardrail_status) for cross-run byte/dict equality assertions on a file that stamps datetime.now() into three fields"

key-files:
  created: []
  modified:
    - skills/revenium/scripts/common.sh
    - skills/revenium/scripts/guardrail-check.sh
    - tests/test_repository.py

key-decisions:
  - "Followed D-05 through D-08 from 26-CONTEXT.md exactly: split streams via a common.sh-declared mktemp template, relocate (never delete) the EOF soft-fail, and grep the concatenation of both streams rather than either alone — Claude's-discretion item resolved in favor of stderr-plus-stdout because that is provably the pre-split code's exact input set."
  - "Task 1's test_enforcement_stderr_never_enters_parsed_json needed a stronger assertion than the plan's literal 'substring absent from output file' wording to actually go RED against unmodified guardrail-check.sh: a stderr note merged via the old 2>&1 capture corrupts json.loads() and is silently swallowed by the existing try/except, dropping the fixture's rule data to an empty list rather than leaking the note's literal text into the output. Added a positive assertion (the healthy fixture's one rule must survive) alongside the substring-absence check, so the test is RED for the right reason (silent data corruption) and GREEN after the split for the right reason (clean stream separation), not merely coincidentally green both ways."

patterns-established:
  - "Stream-split-then-relocate-not-delete idiom for any future CLI call site whose stderr currently rides inside a JSON-parsed variable (setup-guardrails.sh:455 in plan 26-04 will reuse this exact shape per D-07)."

requirements-completed: [STDERR-01, STDERR-02]

coverage:
  - id: D1
    description: "ENFORCEMENT_JSON at guardrail-check.sh's enforcement-rules fetch contains CLI stdout only — a stderr note is captured into a separate variable (ENFORCEMENT_STDERR) via a per-process-unique mktemp+trap temp file and never enters ENFORCEMENT_JSON"
    requirement: "STDERR-01"
    verification:
      - kind: unit
        ref: "tests/test_repository.py#test_enforcement_stderr_never_enters_parsed_json"
        status: pass
    human_judgment: false
  - id: D2
    description: "The empty/fresh-team EOF soft-fail keeps firing after the stream split, for the error body arriving on either stdout or stderr — first-ever test coverage for behavior that previously had zero tests"
    requirement: "STDERR-01"
    verification:
      - kind: unit
        ref: "tests/test_repository.py#test_empty_team_eof_soft_fail_survives_stream_split"
        status: pass
    human_judgment: false
  - id: D3
    description: "A stderr pagination note changes neither guardrail-status.json's content (proven via timestamp-normalized dict equality) nor the halt/no-halt decision, across a breaching-halt run, an identical breaching-halt run with a note, and a non-breaching run with a note (the false-clear direction)"
    requirement: "STDERR-02"
    verification:
      - kind: unit
        ref: "tests/test_repository.py#test_stderr_pagination_note_does_not_affect_status_or_halt"
        status: pass
    human_judgment: false
  - id: D4
    description: "The stderr temp file is per-process unique and EXIT-trapped — two overlapping guardrail-check.sh runs against the same STATE_DIR never share or leak one, each exits 0, and no .cli-stderr.* file survives either run"
    requirement: "STDERR-01"
    verification:
      - kind: unit
        ref: "tests/test_repository.py#test_concurrent_guardrail_check_runs_do_not_share_stderr_tmp"
        status: pass
    human_judgment: false

# Metrics
duration: 25min
completed: 2026-07-27
status: complete
---

# Phase 26 Plan 02: Pagination & stderr Compatibility — stderr Hardening Summary

**guardrail-check.sh's enforcement-rules fetch now captures stdout and stderr into separate variables via a per-process mktemp+trap temp file declared in common.sh, with the empty-team EOF soft-fail relocated (not deleted) to grep both streams concatenated — proven by four new tests, three of which cover behavior that had zero prior coverage.**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-07-27T19:23:28Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added `CLI_STDERR_TMP_TEMPLATE` to `common.sh` (D-06) — a `mktemp` template under `STATE_DIR`, declared once, following the `MIGRATION_NOTIFY_FILE` comment-prefixed constant shape exactly; deliberately excluded from the `mkdir -p` list since it names a file, not a directory.
- Split `guardrail-check.sh`'s enforcement-rules fetch (D-05): `ENFORCEMENT_JSON` now captures stdout only (`2>"${CLI_STDERR_TMP}"` instead of `2>&1`); a new `ENFORCEMENT_STDERR` variable holds the separately-captured stderr text. This is the first `trap` in the file (`trap 'rm -f "${CLI_STDERR_TMP}"' EXIT`), confirmed via repo-wide grep to not collide with any prior trap registration.
- Relocated — never deleted — the `"error".*EOF` soft-fail: it now greps `printf '%s\n%s\n' "${ENFORCEMENT_JSON}" "${ENFORCEMENT_STDERR}"`, reproducing exactly the input set the pre-split `2>&1`-merged grep saw, so the relocation cannot narrow which stream a fresh/empty team's error can arrive on. Left an inline comment explaining what silently breaks if a future edit narrows the pattern (a fresh/empty team hard-fails every cron tick) or widens it (enforcement stops halting during a real outage).
- Extended `_make_revenium_stub` with two new defaulted kwargs (`stderr_note`, `enforcement_stderr`) so every one of the 10 pre-existing callers (7 original + 3 from plan 26-01) works unchanged: `stderr_note` emits text on stderr from every non-`--help` invocation; `enforcement_stderr` emits text on stderr from the `enforcement-rules get` arm specifically, letting a caller reproduce an error body arriving on stderr while stdout carries an empty JSON object.
- Added `_normalize_guardrail_status`, a test helper that blanks the three wall-clock timestamp fields (`lastChecked` top-level, per-rule `lastChecked`, `haltedAt`) so two runs' output documents can be compared as equal dicts despite `datetime.now()` stamps.
- Pinned the previously-untested empty-team EOF soft-fail with `test_empty_team_eof_soft_fail_survives_stream_split` — green against unmodified `guardrail-check.sh` (characterization test, written before the Task 2 edit per the plan's atomic-unit requirement) and still green after the split, for the error body arriving on either stream.
- Proved STDERR-01 with `test_enforcement_stderr_never_enters_parsed_json` — RED against unmodified `guardrail-check.sh` (a stderr note corrupts the enforcement-rules JSON parse and silently drops the fixture's real rule data to an empty list), GREEN after Task 2's split.
- Proved STDERR-02 with `test_stderr_pagination_note_does_not_affect_status_or_halt` — three runs (breaching-no-note, breaching-with-note, non-breaching-with-note) show a stderr note changes neither the normalized status document nor `HALT_TRANSITION`/`HALTED_RULE_*`/`EVENT_TS`/`EVENT_SUMMARY` output, in either direction (no false halt, no false clear).
- Proved the per-process-uniqueness/trap claim with `test_concurrent_guardrail_check_runs_do_not_share_stderr_tmp` — two `guardrail-check.sh` processes launched concurrently against the same `STATE_DIR` both exit 0, `guardrail-status.json` parses afterward, and no `.cli-stderr.*` file survives either run.

## Task Commits

Each task was committed atomically:

1. **Task 1: Teach the stub to speak on stderr, and pin the empty-team soft-fail that has never been tested** - `b1cfd55` (test)
2. **Task 2: Split the streams at the enforcement-rules fetch and relocate the EOF soft-fail** - `77f7866` (feat)

**Plan metadata:** commit pending (this SUMMARY + STATE/ROADMAP update)

## Files Created/Modified
- `skills/revenium/scripts/common.sh` - Added `CLI_STDERR_TMP_TEMPLATE` (D-06), declared between `MIGRATION_NOTIFY_FILE` and the `mkdir -p` line.
- `skills/revenium/scripts/guardrail-check.sh` - Split the enforcement-rules fetch into separate stdout/stderr captures via a trapped `mktemp` temp file; relocated the EOF soft-fail grep to read both streams concatenated.
- `tests/test_repository.py` - Extended `_make_revenium_stub` (`stderr_note`, `enforcement_stderr` kwargs); added `_normalize_guardrail_status`, `test_empty_team_eof_soft_fail_survives_stream_split`, `test_enforcement_stderr_never_enters_parsed_json`, `test_stderr_pagination_note_does_not_affect_status_or_halt`, `test_concurrent_guardrail_check_runs_do_not_share_stderr_tmp`.

## Decisions Made
- Followed D-05 through D-08 from `26-CONTEXT.md` exactly as specified — the discretionary call ("stderr only or stderr-plus-stdout" for the EOF grep) was resolved as stderr-plus-stdout per the plan's own reasoning: that set is provably identical to what the pre-split `2>&1` grep saw, so it cannot narrow the soft-fail's trigger set regardless of which stream the CLI actually uses.
- Strengthened Task 1's `test_enforcement_stderr_never_enters_parsed_json` beyond the plan's literal wording (a substring-absence check alone). Verified empirically that the literal check passes against BOTH unmodified and fixed `guardrail-check.sh` — under the old `2>&1` merge, a stderr note doesn't literally leak into the output file; instead it corrupts `json.loads()`, the exception is silently swallowed by existing `try/except` handling, and the fixture's real rule data is dropped to an empty list. Added a positive assertion (the healthy fixture's one rule must survive intact) alongside the substring check, so the test is genuinely RED before Task 2 (with a specific, informative failure message naming the mechanism) and genuinely GREEN after — this is a test-authoring detail, not a scope change; the plan's underlying intent ("no JSON-parsed variable captures stderr", "a note appears nowhere in guardrail-status.json") is honored by both assertions together.

## Deviations from Plan

None (Rule 1/2/3 sense) — the one adjustment above (strengthening a test assertion) is a test-authoring correction to make the plan's stated RED/GREEN requirement actually hold, not a scope or architecture change, and stays within the plan's own "Claude's discretion" latitude for exact temp-file naming, trap placement, and stream-grep direction (D-06/D-05's discretionary clauses).

## Issues Encountered

None. All acceptance-criteria greps (constant declaration shape, absence from `mkdir -p`, no remaining `2>&1` at the enforcement-rules fetch, exactly one `trap ... EXIT`, EOF pattern unchanged, `SHADOW_TMP` untouched) passed on first check.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The stream-split-then-relocate idiom (`CLI_STDERR_TMP_TEMPLATE` → `mktemp` + `trap` → separate stdout/stderr capture → concatenated-grep soft-fail) is ready to be replicated by plan 26-04 for `setup-guardrails.sh:455` (D-07's `budget-rules create` site), which needs the same shape plus preserving the truncated-error-on-failure UX.
- `_make_revenium_stub`'s `stderr_note`/`enforcement_stderr` kwargs and `_normalize_guardrail_status` are now available to every subsequent test in this phase without further harness work.
- No blockers. Full suite green at 161/161 (baseline 157 + 4 new tests from this plan).

## Self-Check: PASSED

- FOUND: skills/revenium/scripts/common.sh
- FOUND: skills/revenium/scripts/guardrail-check.sh
- FOUND: tests/test_repository.py
- FOUND: .planning/phases/26-pagination-stderr-compatibility/26-02-SUMMARY.md
- FOUND commit: b1cfd55 (test: extend revenium stub for stderr emission, pin untested EOF soft-fail)
- FOUND commit: 77f7866 (feat: split stdout/stderr at enforcement-rules fetch, relocate EOF soft-fail)

---
*Phase: 26-pagination-stderr-compatibility*
*Completed: 2026-07-27*
