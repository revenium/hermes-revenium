---
phase: 26-pagination-stderr-compatibility
plan: 04
subsystem: infra
tags: [bash, stderr, mktemp, trap, pagination, revenium-cli, guardrails, test-harness]

# Dependency graph
requires:
  - phase: 26-pagination-stderr-compatibility (plan 01)
    provides: "supports_flag() capability probe, argv-recording _make_revenium_stub test harness"
  - phase: 26-pagination-stderr-compatibility (plan 02)
    provides: "CLI_STDERR_TMP_TEMPLATE state-path constant, stream-split-then-relocate idiom"
  - phase: 26-pagination-stderr-compatibility (plan 03)
    provides: "REVENIUM_PAGE_BATCH_SIZE tunable, gated array-cmd list pattern"
provides:
  - "PAGE_FLAG_SUPPORTED once-per-run resolution in setup-guardrails.sh (probed against budget-rules list)"
  - "Trapped, top-level CLI_STDERR_TMP reused across every create_rule() invocation in one script run"
  - "Stream-split budget-rules create call — rule_json is pure stdout, rule_stderr captured separately, truncated failure diagnostic rebuilt from both"
  - "Three gated, wants-all-pages list sites in setup-guardrails.sh: dedup lookup, operator display, legacy-alert migration fetch"
  - "_make_setup_revenium_stub test helper (setup-guardrails.sh-specific fake revenium dispatcher, $HOME/.local/bin placement contract)"
  - "test_every_json_list_call_site_declares_pagination_classification — cross-file assumption-delta invariant"
  - "STDERR-01 and PAGE-02 fully closed across all six in-scope call sites plus the one pulled-in site (D-07)"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single trapped stderr temp file created ONCE at top level (before any function that may run more than once), never per-call — avoids the EXIT-trap-replaces-prior-trap leak that a per-call mktemp+trap would cause"
    - "Contiguous-comment-block lookback scan for source-invariant tests: walk backward from a matched code line through contiguous '#'-prefixed lines (tolerating a single bare 'local <var>' declaration line), rather than a fixed N-line window — handles multi-line comment blocks and local-declaration-before-array-construction without over- or under-matching"

key-files:
  created: []
  modified:
    - skills/revenium/scripts/setup-guardrails.sh
    - tests/test_repository.py

key-decisions:
  - "Followed D-01 through D-17 from 26-CONTEXT.md exactly — no plan-level decisions required deviation from what was specified."
  - "The invariant test's first draft (fixed N-line lookback) went RED against unmodified post-Task-2 code because setup-guardrails.sh's convention is comment-block -> 'local list_cmd' -> array-construction line, with the local declaration breaking a naive backward walk at the first non-comment line. Fixed by tolerating a single bare 'local <var>' line in the walk without treating it as a wall — a test-authoring correction, not a scope change; guardrail-check.sh's two sites (no local declaration, top-level script) were unaffected."

patterns-established:
  - "Contiguous-comment-block lookback (vs. fixed-window lookback) for any future source-scanning invariant test whose target lines may be preceded by a bare declaration statement between the comment and the code it documents."

requirements-completed: [PAGE-02, STDERR-01]

coverage:
  - id: D1
    description: "rule_json at the budget-rules create call holds CLI stdout only — a stderr note can no longer poison the JSON parsed for RULE_ID; on failure the truncated diagnostic is rebuilt from stdout+stderr concatenated and capped at 200 chars"
    requirement: "STDERR-01"
    verification:
      - kind: unit
        ref: "tests/test_repository.py#test_setup_guardrails_rule_create_failure_surfaces_truncated_error"
        status: pass
    human_judgment: false
  - id: D2
    description: "Exactly one top-level EXIT trap cleans up one per-process CLI_STDERR_TMP file, created once before create_rule() can run (which may execute more than once per invocation)"
    requirement: "STDERR-01"
    verification:
      - kind: unit
        ref: "grep -c \"trap 'rm -f\" skills/revenium/scripts/setup-guardrails.sh (equals 1, positioned before usage())"
        status: pass
    human_judgment: false
  - id: D3
    description: "All three setup-guardrails.sh list sites (dedup, display, legacy-migration) are classified wants-all-pages, gated on PAGE_FLAG_SUPPORTED, and proven on the argv shapes D-15 requires — dedup and migration on both probe branches, display on the probe-supported branch"
    requirement: "PAGE-02"
    verification:
      - kind: unit
        ref: "tests/test_repository.py#test_setup_guardrails_list_sites_send_gated_batch_size"
        status: pass
    human_judgment: false
  - id: D4
    description: "Every --output json list-family invocation across guardrail-check.sh and setup-guardrails.sh declares a wants-all-pages/wants-bounded classification marker — 4 wants-all-pages + 1 wants-bounded total, enforced as a source-scanning invariant that goes RED on either a removed marker or a newly added unmarked call site (verified both directions manually, reverted before commit)"
    requirement: "PAGE-02"
    verification:
      - kind: unit
        ref: "tests/test_repository.py#test_every_json_list_call_site_declares_pagination_classification"
        status: pass
    human_judgment: false
  - id: D5
    description: "COMPAT-02 is discharged by construction across the whole phase (D-01, closed in plan 26-01) — no call site in setup-guardrails.sh sends --page unless the local PAGE_FLAG_SUPPORTED probe confirms support, so the skill's behavior never depends on whether CLI v1.2.1 accepts --page 0"
    requirement: "COMPAT-02"
    verification: []
    human_judgment: true
    rationale: "Architectural claim substantiated by code inspection of the if/then/fi gate plus the passing argv tests (D3), not a directly-testable runtime fact — the literal answer for v1.2.1 stays unverified until Phase 30's live-host run (already true as of plan 26-01; this plan extends the same discharged posture to setup-guardrails.sh's three additional sites)."

# Metrics
duration: 20min
completed: 2026-07-27
status: complete
---

# Phase 26 Plan 04: Setup-Path Stream Split and List-Site Classification Summary

**setup-guardrails.sh's rule-create call no longer folds CLI stderr into the JSON parsed for RULE_ID, and all three of its `--output json` list sites (dedup, operator display, legacy-alert migration) are capability-gated on `--page-size 500` — closing STDERR-01 and PAGE-02 across every in-scope call site in the phase, backed by a new cross-file invariant test that fails the moment a future list call skips classification.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-07-27T19:58:53Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments
- Resolved `PAGE_FLAG_SUPPORTED` once per `setup-guardrails.sh` run (D-01/D-03), probed against `budget-rules list` — the verb this script's own list sites use — immediately after `ensure_path`, ahead of every function that could consume it.
- Created a single trapped `CLI_STDERR_TMP` at top level, before any function that might invoke it more than once, avoiding the EXIT-trap-replaces-prior-trap leak a per-call `mktemp`+`trap` would cause. This is the first `trap` in `setup-guardrails.sh`.
- Split the `budget-rules create` call (D-07): `rule_json` is now pure stdout; `rule_stderr` is captured into the shared temp file. On failure, `truncated_err` is rebuilt from both streams concatenated and capped at 200 chars (T-18-LOG-INJECT convention) — the existing truncated-error UX and message wording survive byte-for-byte.
- Classified and gated all three setup-guardrails.sh list sites (D-11/D-12): the dedup lookup in `find_existing_rules()`, the operator display in `run_interactive()`'s re-run gate, and the legacy-alert fetch in `run_migration()`. Each carries a `# wants-all-pages:` marker stating its specific correctness reason (duplicate-rule risk, misleading display, broken migration) and sources its batch size from `REVENIUM_PAGE_BATCH_SIZE`; each preserves its original fallback value and `2>/dev/null` redirect exactly.
- Added `_make_setup_revenium_stub`, a `setup-guardrails.sh`-specific fake `revenium` dispatcher (distinct from `_make_revenium_stub`) that honors the `$HOME/.local/bin` + `env['HOME']` placement contract (D-16) `ensure_path`'s bare-call, no-`_PATH_HEAD` shape requires.
- Proved the three list sites' argv on both probe branches where applicable: `test_setup_guardrails_list_sites_send_gated_batch_size` covers the dedup and legacy-alert sites on both the probe-supported and fallback branches (same migration run), and the operator-display site on the probe-supported branch (interactive re-run gate, stdin closed, non-zero exit tolerated by design).
- Added first-ever coverage of the rule-create failure path: `test_setup_guardrails_rule_create_failure_surfaces_truncated_error` proves the metering log carries the failure prefix, exit code, and a 200-char-capped prefix of a >200-char stderr fixture, with the beyond-cap tail provably absent.
- Landed `test_every_json_list_call_site_declares_pagination_classification`, the assumption-delta invariant named in 26-01's decision: scans both edited scripts for every `--output json` list-family call and requires a wants-all-pages/wants-bounded marker in its immediately-preceding contiguous comment block (tolerating a single bare `local <var>` line between the block and the array-construction line). Asserts exactly 4 wants-all-pages + 1 wants-bounded sites total. Verified RED in both directions (marker removed; unmarked call added) by temporary edit, restore.

## Task Commits

Each task was committed atomically:

1. **Task 1: Resolve the probe once and split the rule-create call's streams (D-07)** - `362a9f0` (feat)
2. **Task 2: Classify and gate the three setup list sites (D-11, D-12)** - `57dfc4b` (feat)
3. **Task 3: Prove the setup argv on both probe branches, cover the create-failure path, and lock the classification invariant** - `be7d96a` (test)

**Plan metadata:** commit pending (this SUMMARY + STATE/ROADMAP update)

## Files Created/Modified
- `skills/revenium/scripts/setup-guardrails.sh` - Added `PAGE_FLAG_SUPPORTED` resolution and trapped `CLI_STDERR_TMP` at top level; split the rule-create call's stdout/stderr; gated all three list sites (dedup, display, legacy-alert migration) behind the probe with `wants-all-pages:` markers.
- `tests/test_repository.py` - Added `_make_setup_revenium_stub`, `test_setup_guardrails_list_sites_send_gated_batch_size`, `test_setup_guardrails_rule_create_failure_surfaces_truncated_error`, `test_every_json_list_call_site_declares_pagination_classification`.

## Decisions Made
- Followed D-01 through D-17 from `26-CONTEXT.md` exactly as specified — no plan-level decisions required deviation.
- Task 3's invariant-test scan needed a small implementation correction beyond the plan's literal "look up to a small fixed number of lines" wording: setup-guardrails.sh's convention places a bare `local list_cmd` declaration between the marker's comment block and the array-construction line it documents, which a naive fixed-window backward walk breaks on (the declaration line is not a comment). Fixed by tolerating a single bare `local <var>`-only line in the walk without treating it as a stopping wall. Verified this doesn't over-match: guardrail-check.sh's two sites (top-level script, no `local` prefix) are unaffected, and both manual RED checks (removed marker, added unmarked call) still correctly fail. This is a test-authoring correction that keeps the invariant's stated intent — no site left undeclared — not a scope or architecture change.

## Deviations from Plan

None (Rule 1/2/3 sense) — the invariant-test walk-tolerance adjustment above is a test-authoring detail needed to make the plan's own stated mechanism (source-scan for markers) actually work against the codebase's real comment-then-local-declaration shape; it does not change what the test verifies or which sites it covers.

## Issues Encountered

None beyond the one documented above (invariant-test lookback tolerance), which was caught and fixed on the first test run before commit.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 26 is now complete: all four plans landed. STDERR-01 (no JSON-parsed variable in either script can be poisoned by CLI stderr) and PAGE-02 (every list-family call site classified and gated) are closed across all six originally-scoped call sites plus the one pulled-in site (`setup-guardrails.sh:455`, D-07).
- COMPAT-02 remains discharged by construction (D-01, closed in plan 26-01) and unchanged by this plan — the literal "does v1.2.1 accept --page 0" question stays open pending Phase 30's live-host run, but the skill's behavior never depends on the answer.
- The `test_every_json_list_call_site_declares_pagination_classification` invariant now guards both edited scripts against a future list call silently reverting to the old first-page default — no further action needed unless a new list-family verb is introduced, in which case the scan's `verb_pattern` must be extended.
- No blockers. Full suite green at 168/168 (baseline 165 + 3 new tests from this plan).

## Self-Check: PASSED

- FOUND: skills/revenium/scripts/setup-guardrails.sh
- FOUND: tests/test_repository.py
- FOUND: .planning/phases/26-pagination-stderr-compatibility/26-04-SUMMARY.md
- FOUND commit: 362a9f0 (feat: split rule-create stdout/stderr, resolve --page probe once)
- FOUND commit: 57dfc4b (feat: classify and gate the three setup-guardrails.sh list sites)
- FOUND commit: be7d96a (test: prove setup argv on both probe branches, cover create-failure, lock invariant)

---
*Phase: 26-pagination-stderr-compatibility*
*Completed: 2026-07-27*
