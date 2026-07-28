---
phase: 26-pagination-stderr-compatibility
plan: 03
subsystem: infra
tags: [bash, pagination, revenium-cli, guardrails, cron, test-harness]

# Dependency graph
requires:
  - phase: 26-pagination-stderr-compatibility (plan 01)
    provides: "supports_flag() capability probe, PAGE_FLAG_SUPPORTED once-per-run resolution, argv-recording _make_revenium_stub test harness"
  - phase: 26-pagination-stderr-compatibility (plan 02)
    provides: "CLI_STDERR_TMP_TEMPLATE, stream-split enforcement-rules fetch, stderr_note/enforcement_stderr stub kwargs"
provides:
  - "REVENIUM_PAGE_BATCH_SIZE tunable in common.sh (default 500)"
  - "Capability-gated, array-built BUDGET_RULES_CMD at guardrail-check.sh's per-minute hot-path list call"
  - "guardrail-check.sh file-header statement of the per-tick HTTP request bound (2 steady-state / 3 on halt)"
  - "_revenium_api_calls() test helper — argv-log filter isolating HTTP-backed API calls"
  - "test_cron_tick_request_bound — exact-equality enforcement of the per-tick bound"
  - "test_budget_rules_list_gated_batch_size, test_duplicate_rule_names_resolve_to_last_listed_id, test_zero_rule_install_writes_empty_status"
affects: [26-04-invariant-tests]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Capability-gated array-built CLI invocation reused verbatim from plan 26-01's EVENT_CMD shape: base cmd array, conditional cmd+=(--flag value) inside an explicit if/then/fi, gated on the SAME PAGE_FLAG_SUPPORTED variable resolved once per script run"
    - "Call-count-as-test-oracle: argv log filtered to HTTP-backed verbs only, then asserted with assertEqual (never assertLessEqual) so a bound claim in a file-header comment cannot silently drift without a test going red"

key-files:
  created: []
  modified:
    - skills/revenium/scripts/common.sh
    - skills/revenium/scripts/guardrail-check.sh
    - tests/test_repository.py

key-decisions:
  - "Followed the plan's read_first/action instructions exactly — the wants-bounded marker for EVENT_CMD (halt path) already existed from plan 26-01's commit 34c9b1b, so this plan added only the wants-all-pages marker for BUDGET_RULES_CMD, keeping the acceptance criterion's exactly-one-of-each count intact rather than adding a duplicate"
  - "Reused PAGE_FLAG_SUPPORTED (resolved once per run against enforcement-events list --help) to gate the hot-path budget-rules list call rather than introducing a second probe — per the plan's explicit instruction and D-03's once-per-run-reuse decision"

patterns-established:
  - "_revenium_api_calls() as the canonical way any future test in this file counts HTTP-backed CLI calls: filters out --help lines (local process, no network) and config-show lines (local config-file read), keeping only guardrails/alerts verb lines"

requirements-completed: [PAGE-02, PAGE-03]

coverage:
  - id: D1
    description: "The hot-path budget-rules list call is classified wants-all-pages inline, gated on the same PAGE_FLAG_SUPPORTED probe result the halt path uses, and sources its batch size from the single REVENIUM_PAGE_BATCH_SIZE constant"
    requirement: "PAGE-02"
    verification:
      - kind: unit
        ref: "tests/test_repository.py#test_budget_rules_list_gated_batch_size"
        status: pass
    human_judgment: false
  - id: D2
    description: "guardrail-status.json's rules[] array order follows enforcement-rules get's response order exactly, identical on both probe branches, never reordered by budget-rules list content or pagination flags"
    requirement: "PAGE-02"
    verification:
      - kind: unit
        ref: "tests/test_repository.py#test_budget_rules_list_gated_batch_size"
        status: pass
    human_judgment: false
  - id: D3
    description: "Duplicate budget-rule names resolve to the LAST-listed entry's string id — today's silent last-write-wins behavior, pinned (not changed) so a pagination change cannot flip the collision outcome unnoticed"
    requirement: "PAGE-02"
    verification:
      - kind: unit
        ref: "tests/test_repository.py#test_duplicate_rule_names_resolve_to_last_listed_id"
        status: pass
    human_judgment: false
  - id: D4
    description: "A zero-rule install (empty enforcement-rules and budget-rules responses, empty config.json ruleIds) writes guardrail-status.json with rules:[], halted:false, haltedRule absent, and exits 0 on both probe branches"
    requirement: "PAGE-02"
    verification:
      - kind: unit
        ref: "tests/test_repository.py#test_zero_rule_install_writes_empty_status"
        status: pass
    human_judgment: false
  - id: D5
    description: "The per-tick HTTP request bound is stated in guardrail-check.sh's file header and enforced by exact equality: a steady-state tick issues exactly 2 API calls, a halt-transition tick exactly 3"
    requirement: "PAGE-03"
    verification:
      - kind: unit
        ref: "tests/test_repository.py#test_cron_tick_request_bound"
        status: pass
    human_judgment: false

# Metrics
duration: 30min
completed: 2026-07-27
status: complete
---

# Phase 26 Plan 03: Hot-Path Pagination Bound Summary

**guardrail-check.sh's per-minute `budget-rules list` call is now classified wants-all-pages and capability-gated behind the same probe the halt path uses, sourcing its batch size from a single `REVENIUM_PAGE_BATCH_SIZE` constant, with the per-tick request bound (2 steady-state / 3 on halt) turned from a comment into an exact-equality test.**

## Performance

- **Duration:** ~30 min
- **Completed:** 2026-07-27
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added `REVENIUM_PAGE_BATCH_SIZE` to `common.sh` (default 500, env-overridable), the single source of truth for the per-request batch size on every wants-all-pages list call.
- Replaced the inline `budget-rules list` invocation in `guardrail-check.sh` with an array-built, capability-gated `BUDGET_RULES_CMD`: `--page-size 500` on a `--page`-advertising CLI, today's exact flagless call otherwise — reusing `PAGE_FLAG_SUPPORTED` rather than a second probe.
- Appended a `wants-all-pages:` classification comment directly above the new call site explaining why the name→id map must be complete (a missing rule falls back to the integer `ruleId`, which 422s on `enforcement-events list`), why the flag is gated rather than unconditional (D-01 no-regression rule), and flagging RESEARCH.md Assumption A1 (omitting `--page` triggers aggregation) as unverified until Phase 30.
- Stated the per-tick HTTP request bound in `guardrail-check.sh`'s file header (2 on a steady-state tick, +1 on a halt transition) with a pointer to `test_cron_tick_request_bound` as its enforcement point.
- Added `_revenium_api_calls()` — a test helper that filters the argv log down to HTTP-backed `guardrails`/`alerts` verb lines, excluding `--help` capability probes and local `config show` reads, with a docstring explaining both exclusions so the filter's honesty (and therefore the bound's credibility) is auditable.
- Added `test_cron_tick_request_bound`: asserts exactly 2 API calls on a non-breaching tick and exactly 3 on a genuine halt transition, using `assertEqual` (never an upper bound) so a future edit adding a silent third/fourth request goes red immediately.
- Added `test_budget_rules_list_gated_batch_size`: proves the hot-path list argv on both probe branches (D-15's coverage bar) using a two-rule fixture whose enforcement-rules order and budget-rules order are deliberately different — also pins that `rules[]` output order always follows `enforcement-rules get`, never `budget-rules list`.
- Added `test_duplicate_rule_names_resolve_to_last_listed_id`: pins the existing silent last-write-wins collision behavior for duplicate rule names.
- Added `test_zero_rule_install_writes_empty_status`: covers the fresh/empty-team edge on both probe branches — `rules: []`, `halted: false`, `haltedRule` absent, exit 0.

## Task Commits

Each task was committed atomically:

1. **Task 1: Classify and gate the hot-path list call; state the per-tick bound in the file header** - `f4e1a13` (feat)
2. **Task 2: Enforce the request bound and pin the collision, ordering, and empty-install behaviors** - `a30c9e6` (test)

**Plan metadata:** commit pending (this SUMMARY + STATE/ROADMAP update)

## Files Created/Modified
- `skills/revenium/scripts/common.sh` - Added `REVENIUM_PAGE_BATCH_SIZE="${REVENIUM_PAGE_BATCH_SIZE:-500}"` immediately after `CLI_STDERR_TMP_TEMPLATE`.
- `skills/revenium/scripts/guardrail-check.sh` - Appended the per-tick bound statement to the file header; replaced the bare `budget-rules list` invocation with a gated, array-built `BUDGET_RULES_CMD` carrying the `wants-all-pages:` classification marker.
- `tests/test_repository.py` - Added `_revenium_api_calls()`, `test_cron_tick_request_bound`, `test_budget_rules_list_gated_batch_size`, `test_duplicate_rule_names_resolve_to_last_listed_id`, `test_zero_rule_install_writes_empty_status`.

## Decisions Made
- The plan's acceptance criteria required exactly one `wants-bounded:` marker in `guardrail-check.sh`. That marker already existed (added by plan 26-01's commit `34c9b1b` above the halt-path `EVENT_CMD`), so this plan added only the `wants-all-pages:` marker for `BUDGET_RULES_CMD` rather than a second `wants-bounded:` comment — confirmed via `git blame` before editing so the exactly-one-of-each acceptance grep would hold.
- Worded `test_cron_tick_request_bound`'s docstring to explain the `assertEqual`-not-upper-bound reasoning without using the literal string `assertLessEqual`, since the plan's own acceptance-criteria grep (`grep -A 60 ... | grep ... contains no assertLessEqual`) would otherwise match the explanatory prose itself, not just code usage. This is a test-authoring wording adjustment, not a scope change — the docstring still explains the same reasoning.

## Deviations from Plan

None (Rule 1/2/3 sense) - plan executed exactly as written. The two items above are both plan-consistent authoring details (avoiding an accidental duplicate marker; wording a docstring to satisfy the acceptance grep's letter as well as its intent), not deviations from scope or architecture.

## Issues Encountered

None. Both RED-verification checks specified in the plan's acceptance criteria were run manually and reverted before commit:
- Temporarily adding a redundant `revenium guardrails budget-rules list --output json` call to `guardrail-check.sh` made `test_cron_tick_request_bound` fail with `AssertionError: 3 != 2 : steady-state tick must issue exactly 2 API calls: ['guardrails enforcement-rules get 12802 --output json', 'guardrails budget-rules list --output json --page-size 500', 'guardrails budget-rules list --output json']`.
- Temporarily swapping the two fixture entries in `test_duplicate_rule_names_resolve_to_last_listed_id` flipped the expected resolved id from `idLast` to `idFirst` (test failed with `AssertionError: 'idFirst' != 'idLast'`), confirming the test tracks last-write-wins behavior rather than a hardcoded string.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All five call sites CONTEXT.md scoped for this phase have their pagination classification landed except the three `setup-guardrails.sh` list sites and the `budget-rules create` stderr split — both owned by plan 26-04, which also lands `LIST_CMD`, `rule_stderr`, and the cross-site invariant test `test_every_json_list_call_site_declares_pagination_classification`.
- `REVENIUM_PAGE_BATCH_SIZE` is now available for plan 26-04's three `setup-guardrails.sh` list sites to reference directly (D-11 classifies them wants-all-pages too).
- `_revenium_api_calls()` is available for any future test needing an honest HTTP-call count.
- No blockers. Full suite green at 165/165 (baseline 161 + 4 new tests from this plan).

## Self-Check: PASSED

- FOUND: skills/revenium/scripts/common.sh
- FOUND: skills/revenium/scripts/guardrail-check.sh
- FOUND: tests/test_repository.py
- FOUND: .planning/phases/26-pagination-stderr-compatibility/26-03-SUMMARY.md
- FOUND commit: f4e1a13 (feat: classify and gate hot-path budget-rules list on --page probe)
- FOUND commit: a30c9e6 (test: enforce per-tick request bound; pin collision/ordering/empty edges)

---
*Phase: 26-pagination-stderr-compatibility*
*Completed: 2026-07-27*
