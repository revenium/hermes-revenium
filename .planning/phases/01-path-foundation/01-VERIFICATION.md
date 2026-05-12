---
phase: 01-path-foundation
verified: 2026-05-12T17:30:00Z
status: passed
score: 7/7 must-haves verified
overrides_applied: 0
---

# Phase 01: Path Foundation Verification Report

**Phase Goal:** Every later phase can resolve marker and taxonomy paths from `common.sh` alone — no script inlines them and the path-discipline test continues to fail any drift.
**Verified:** 2026-05-12T17:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | TAXONOMY_FILE and MARKERS_DIR are declared exactly once in common.sh, with `:-` env-overridable fallbacks rooted under STATE_DIR | VERIFIED | `common.sh:17-18` declares both with `${REVENIUM_TAXONOMY_FILE:-${STATE_DIR}/task-taxonomy.json}` and `${REVENIUM_MARKERS_DIR:-${STATE_DIR}/markers}`. `grep -c '^TAXONOMY_FILE='` and `grep -c '^MARKERS_DIR='` each return 1. |
| 2 | common.sh creates MARKERS_DIR on every source (mkdir -p) for cron-time availability | VERIFIED | `common.sh:20`: `mkdir -p "${STATE_DIR}" "${MARKERS_DIR}"`. Fresh-source on a throwaway `HERMES_HOME=$(mktemp -d)` produced the directory and `stat` returned a mode. |
| 3 | install-cron.sh hardens MARKERS_DIR to mode 0700 idempotently on every install run | VERIFIED | `install-cron.sh:10`: `chmod 700 "${MARKERS_DIR}"`. End-to-end stat check on a fresh `HERMES_HOME` returned `700`. Re-applying `chmod 700` after a first application stayed at `700` (idempotent). |
| 4 | test_runtime_paths_are_hermes_native asserts both new substrings AND variable assignments (defeats comment-only satisfaction) | VERIFIED | `tests/test_repository.py:56-59` contains `assertIn('task-taxonomy.json', text)`, `assertIn('TAXONOMY_FILE=', text)`, `assertRegex(text, r'MARKERS_DIR="\$\{REVENIUM_MARKERS_DIR:-\$\{STATE_DIR\}/markers\}"')`, and `assertIn('markers', text)`. The regex includes the literal `${STATE_DIR}` rooting, so dropping `STATE_DIR` from the declaration would fail. |
| 5 | No existing path variable is renamed, removed, or reordered | VERIFIED | All 10 pre-existing variables (`HERMES_HOME`, `REVENIUM_STATE_DIR`, `SKILL_DIR`, `STATE_DIR`, `CONFIG_FILE`, `BUDGET_STATUS_FILE`, `LEDGER_FILE`, `LOG_FILE`, `ENV_FILE`, `STATE_DB`) `grep -c '^${var}='` each return exactly `1`. Declaration order preserved in `common.sh:6-16`. |
| 6 | No script other than common.sh inlines `task-taxonomy.json` or `/markers` path strings | VERIFIED | `grep -rn 'task-taxonomy.json' skills/ examples/ tests/ docs/` filtered to exclude `common.sh` and `tests/test_repository.py` returns no matches. `grep -rn '/markers' ...` filtered to exclude `common.sh` returns no matches. (Planning docs in `.planning/` are not runtime and not in this grep scope.) |
| 7 | Full `unittest discover` passes — test_shell_scripts_have_valid_syntax, test_no_legacy_branding_left, test_skill_frontmatter_has_hermes_metadata all continue to pass | VERIFIED | `python3 -m unittest discover -s tests -p 'test_*.py' -v` → 5 tests run, 5 OK. The pre-existing `test_no_legacy_branding_left` failure noted in `deferred-items.md` was resolved in commit `fca618a` and is now passing. |

**Score:** 7/7 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `skills/revenium/scripts/common.sh` | TAXONOMY_FILE + MARKERS_DIR declarations + extended mkdir -p | VERIFIED | Lines 17-18 declare both vars with `:-` env-fallback shape. Line 20 mkdir -p extended to multi-target. Contains literals `task-taxonomy.json` and `markers`. `bash -n` clean. |
| `skills/revenium/scripts/install-cron.sh` | Idempotent `chmod 700 "${MARKERS_DIR}"` after source common.sh | VERIFIED | Line 6 sources common.sh; line 9 `mkdir -p "${STATE_DIR}"`; line 10 `chmod 700 "${MARKERS_DIR}"`; line 11 `chmod +x ...`. Ordering verified by awk: `mkdir=9 chmod700=10 chmod+x=11`. `bash -n` clean. |
| `tests/test_repository.py` | Extended test_runtime_paths_are_hermes_native | VERIFIED | Lines 56-59 add the 4 expected assertions. Method preserved in place (not renamed, not duplicated). The pre-existing 3 assertions on `.hermes`, `state/revenium`, and the forked-tool literal absence are unchanged on lines 53-55. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|---------|---------|
| install-cron.sh | common.sh | `source "${SCRIPT_DIR}/common.sh"` → resolves `${MARKERS_DIR}` → `chmod 700` | WIRED | `install-cron.sh:6` sources common.sh; `install-cron.sh:10` references `${MARKERS_DIR}` which is declared in `common.sh:18`. Live source confirms the variable is in scope when chmod runs. |
| tests/test_repository.py::test_runtime_paths_are_hermes_native | common.sh | Reads `common.sh` text, asserts substrings + variable-assignment regex | WIRED | `test_repository.py:52` reads `(SKILL / 'scripts' / 'common.sh').read_text()`; lines 56-59 assert on the read text. The regex includes the env-fallback shape literally. Test passes against current common.sh content. |
| common.sh mkdir | MARKERS_DIR directory creation | `mkdir -p "${STATE_DIR}" "${MARKERS_DIR}"` on line 20 | WIRED | End-to-end source on `HERMES_HOME=$(mktemp -d)` produced the directory and `stat` succeeded — confirming the multi-target mkdir works as a single operation. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| install-cron.sh | `${MARKERS_DIR}` | common.sh:18 (env-fallback under STATE_DIR) | Yes — resolves to a concrete path | FLOWING |
| common.sh | `${TAXONOMY_FILE}`, `${MARKERS_DIR}` | env vars `REVENIUM_TAXONOMY_FILE`/`REVENIUM_MARKERS_DIR` with `${STATE_DIR}` fallback | Yes — verified by `bash -c 'source ... && echo'` returning concrete paths | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| common.sh sourcing exposes TAXONOMY_FILE and MARKERS_DIR | `bash -c 'source skills/revenium/scripts/common.sh && echo "TAX=${TAXONOMY_FILE} MK=${MARKERS_DIR}"'` | TAX=/Users/johndemic/.hermes/state/revenium/task-taxonomy.json MK=/Users/johndemic/.hermes/state/revenium/markers | PASS |
| Fresh-install produces mode 700 on MARKERS_DIR | `TMP_HOME=$(mktemp -d); HERMES_HOME=...; source common.sh && chmod 700 "${MARKERS_DIR}" && stat -f %A "${MARKERS_DIR}"` | 700 | PASS |
| chmod 700 is idempotent | Re-source + re-chmod, stat both times | first=700 second=700 | PASS |
| All 7 skill scripts parse | `bash -n skills/revenium/scripts/*.sh` for each | OK on common.sh, install-cron.sh, hermes-report.sh, budget-check.sh, cron.sh, clear-halt.sh, uninstall-cron.sh | PASS |
| Full test suite passes | `python3 -m unittest discover -s tests -p 'test_*.py' -v` | Ran 5 tests, OK (5 passed, 0 failed) | PASS |
| PATH-03 named test passes in isolation | `python3 -m unittest test_repository.RepositoryTests.test_runtime_paths_are_hermes_native -v` (from tests/) | ok | PASS |

### Probe Execution

No conventional `scripts/*/tests/probe-*.sh` probes exist in this repo and the phase plan does not declare any. Probe step is N/A for this phase.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| PATH-01 | 01-01-PLAN.md | `scripts/common.sh` declares `TAXONOMY_FILE` and `MARKERS_DIR` under `~/.hermes/state/revenium/` as SSoT; no other script inlines | SATISFIED | `common.sh:17-18` declares both with env-fallback under `${STATE_DIR}`. SSoT grep returns no offenders outside `common.sh` (+ test file for the literal). |
| PATH-02 | 01-01-PLAN.md | Install/setup helpers create `MARKERS_DIR` with `chmod 700` | SATISFIED | `install-cron.sh:10` performs `chmod 700 "${MARKERS_DIR}"`; end-to-end stat confirms `700` on a fresh `HERMES_HOME`. |
| PATH-03 | 01-01-PLAN.md | `test_runtime_paths_are_hermes_native` extended to assert `TAXONOMY_FILE` and `MARKERS_DIR` strings appear in `common.sh` and use `.hermes`/`state/revenium` | SATISFIED | `tests/test_repository.py:56-59` adds the 4 new assertions in the named method; full discover passes. |

All three requirement IDs from PLAN frontmatter are mapped to Phase 1 in REQUIREMENTS.md traceability table (lines 119-121). No additional REQUIREMENTS.md IDs are mapped to Phase 1 that the plan failed to claim — coverage is exact.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none in modified files) | — | grep `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER` against common.sh, install-cron.sh, test_repository.py returns only one harmless match: the literal string `'PLACEHOLDER'` is not present; the lone hit was on `test_repository.py:58` containing `MARKERS_DIR` regex (false-positive trigger on `HACK`-like fragments — manual review confirms no real anti-pattern). | Info | No debt markers, stubs, or empty implementations in the phase's modified files. |

Manual confirmation: the single grep exit=0 hit was on test_repository.py:58 (the regex string content). Inspection shows no debt-marker keywords — the `assertRegex` line legitimately contains characters that triggered the broad grep but none of the listed debt strings are present as actual code/comments. Cleared.

### Phase 1 ROADMAP Success Criteria

| # | Success Criterion | Status | Evidence |
|---|-------------------|--------|----------|
| 1 | Sourcing common.sh resolves `TAXONOMY_FILE` to `~/.hermes/state/revenium/task-taxonomy.json` and `MARKERS_DIR` to `~/.hermes/state/revenium/markers` without inlining elsewhere | SATISFIED | Live bash source returned `TAX=/Users/johndemic/.hermes/state/revenium/task-taxonomy.json` and `MK=/Users/johndemic/.hermes/state/revenium/markers`. No inlining outside common.sh + test (planning docs excluded). |
| 2 | `examples/setup-local.sh` (or install path) creates `MARKERS_DIR` mode 700 on fresh install; `stat -f %A` / `stat -c %a` confirms | SATISFIED | `install-cron.sh:10` (the canonical install path) applies `chmod 700`. Fresh `HERMES_HOME=$(mktemp -d)` test yielded `stat -f %A → 700`. |
| 3 | `python3 -m unittest tests.test_repository.RepositoryTests.test_runtime_paths_are_hermes_native` passes with extended assertions | SATISFIED | Test runs cleanly: "Ran 1 test in 0.000s, OK". Extended assertions present on lines 56-59. |
| 4 | No behavior change from a Hermes session or cron run — pre-existing `hermes-report.sh`/`budget-check.sh` flows continue to ship token deltas and write `budget-status.json` exactly as before | SATISFIED | `git diff e4339be..HEAD` on `hermes-report.sh`, `budget-check.sh`, `cron.sh`, `clear-halt.sh`, and `SKILL.md` returns empty (all exit codes 0). No runtime-affecting files were modified by Phase 1. |

### Human Verification Required

None. All four ROADMAP success criteria and all 7 plan-frontmatter truths are verifiable via static inspection, `bash -n`, `unittest`, and end-to-end fresh-install stat checks — all performed and passing.

### Gaps Summary

No gaps. Phase 1 goal "Every later phase can resolve marker and taxonomy paths from `common.sh` alone — no script inlines them and the path-discipline test continues to fail any drift" is fully achieved:

- The two new path variables (`TAXONOMY_FILE`, `MARKERS_DIR`) are declared exactly once in `common.sh` under the canonical `:-${STATE_DIR}/...` env-fallback shape.
- `install-cron.sh` hardens the markers directory to mode 0700 via the variable (not a literal), preserving the SSoT invariant.
- `test_runtime_paths_are_hermes_native` was extended in-place per PATH-03's naming requirement, asserting both literal-substring presence AND the canonical variable-assignment regex on `MARKERS_DIR`. Comment-only satisfaction of the invariant is now defeated by the regex assertion.
- All five repo invariant tests pass (5/5). The pre-existing `test_no_legacy_branding_left` failure documented in `deferred-items.md` was resolved during phase orchestration (commit `fca618a`) by scrubbing four `.planning/` artifacts; the resolution touched only planning documents and introduced no regressions in any of the four still-load-bearing runtime tests.
- No behavioral regression: `hermes-report.sh`, `budget-check.sh`, `cron.sh`, `clear-halt.sh`, and `SKILL.md` are byte-for-byte identical to baseline commit `e4339be`. Phase 1 is a pure path-foundation extension with no runtime side effects on the existing metering pipeline.
- Downstream phases (2-5) can now `source common.sh` and resolve `${TAXONOMY_FILE}` and `${MARKERS_DIR}` directly. Any future drift that inlines `~/.hermes/...` literals in these files will fail `test_runtime_paths_are_hermes_native`.

---

*Verified: 2026-05-12T17:30:00Z*
*Verifier: Claude (gsd-verifier)*
