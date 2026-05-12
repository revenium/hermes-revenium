---
phase: 01-path-foundation
plan: 01
subsystem: infra
tags: [bash, paths, state-discipline, hermes-skill, common.sh, install-cron, test-invariants]

# Dependency graph
requires: []
provides:
  - TAXONOMY_FILE variable in common.sh (resolves to ${STATE_DIR}/task-taxonomy.json, REVENIUM_TAXONOMY_FILE-overridable)
  - MARKERS_DIR variable in common.sh (resolves to ${STATE_DIR}/markers, REVENIUM_MARKERS_DIR-overridable)
  - common.sh auto-creates MARKERS_DIR on every source via extended mkdir -p
  - install-cron.sh hardens MARKERS_DIR to mode 0700 idempotently
  - test_runtime_paths_are_hermes_native enforces the new substrings AND variable-assignment patterns
affects:
  - 02-prompt-design-and-marker-contract (writes per-session JSONL marker files to ${MARKERS_DIR}, taxonomy to ${TAXONOMY_FILE})
  - 03-cron-marker-reader (reads ${MARKERS_DIR}/<session_id>.jsonl, splits deltas across markers)
  - 04-wire-enrichment (consumes marker task_type/operation_type for --task-type / --operation-type flags)
  - 05-housekeeping (marker retention/rotation policies for ${MARKERS_DIR})

# Tech tracking
tech-stack:
  added: []  # No new runtime dependencies; bash + python heredoc + sqlite3 + revenium CLI unchanged
  patterns:
    - "Every new state path follows the ${REVENIUM_<NAME>:-${STATE_DIR}/<file>} env-fallback shape (mirrors HERMES_HOME / REVENIUM_STATE_DIR)"
    - "Directory creation lives in common.sh's mkdir -p line (multi-target form), not in calling scripts"
    - "Permission hardening (chmod 700) lives in install-cron.sh (operator-invoked, idempotent), not in common.sh (every-cron-tick)"
    - "test_runtime_paths_are_hermes_native asserts BOTH substring presence AND variable-assignment patterns to defeat comment-only satisfaction"

key-files:
  created:
    - .planning/phases/01-path-foundation/deferred-items.md
  modified:
    - skills/revenium/scripts/common.sh
    - skills/revenium/scripts/install-cron.sh
    - tests/test_repository.py

key-decisions:
  - "Permission hardening (chmod 700) belongs in install-cron.sh, not common.sh, so it does not run on every cron tick"
  - "mkdir -p in common.sh is extended to multi-target form, not duplicated, so the dir is created on first source regardless of who sources first"
  - "test_runtime_paths_are_hermes_native is extended in place (PATH-03 names it), not split into a new method, and asserts the canonical :-env-fallback regex on MARKERS_DIR"

patterns-established:
  - "New state-path variable pattern: TAXONOMY_FILE / MARKERS_DIR define both the literal default under ${STATE_DIR} and an env-override hook (REVENIUM_TAXONOMY_FILE / REVENIUM_MARKERS_DIR), so cron and tests can redirect independently"
  - "Path-discipline test pattern: assertIn the literal substring AND assertRegex the variable assignment with full :-env-fallback shape, so future drift (comment-only, missing override, dropped STATE_DIR rooting) fails the test"

requirements-completed: [PATH-01, PATH-02, PATH-03]

# Metrics
duration: 3min
completed: 2026-05-12
---

# Phase 01 Plan 01: Path Foundation Summary

**TAXONOMY_FILE and MARKERS_DIR declared as REVENIUM_*-overridable variables in common.sh, MARKERS_DIR hardened to mode 0700 in install-cron.sh, and the path-discipline invariant test extended to enforce both substring presence and the canonical :-env-fallback regex.**

## Performance

- **Duration:** 3 min (161 s)
- **Started:** 2026-05-12T16:49:40Z
- **Completed:** 2026-05-12T16:52:21Z
- **Tasks:** 3
- **Files modified:** 3 (1 line removed, 8 lines added)

## Accomplishments

- `skills/revenium/scripts/common.sh` declares two new state-path variables under the existing path block using the project's canonical `:-` env-fallback pattern (matches `HERMES_HOME` / `REVENIUM_STATE_DIR` shape).
- `mkdir -p` line extended to multi-target form `mkdir -p "${STATE_DIR}" "${MARKERS_DIR}"` so cron-time availability of the markers directory is guaranteed regardless of who sources `common.sh` first.
- `skills/revenium/scripts/install-cron.sh` runs `chmod 700 "${MARKERS_DIR}"` after sourcing `common.sh` and before the `chmod +x` of script files. Verified end-to-end on a throwaway `HERMES_HOME=$(mktemp -d)`: `stat -f %A ${MARKERS_DIR}` returns `700`.
- `tests/test_repository.py::test_runtime_paths_are_hermes_native` extended in place (no new method, no rename per PATH-03) with four new assertions covering the new substrings and variable-assignment patterns. Negative-fixture sanity confirmed: dropping `${STATE_DIR}` rooting on the `MARKERS_DIR` line causes the regex assertion to fail; restoring it passes.

## Task Commits

Each task was committed atomically on `worktree-agent-aaed5527c529271c5`:

1. **Task 1: Declare TAXONOMY_FILE and MARKERS_DIR in common.sh (PATH-01)** — `4136439` (feat)
2. **Task 2: Harden MARKERS_DIR to mode 0700 in install-cron.sh (PATH-02)** — `f5265fd` (feat)
3. **Task 3: Extend test_runtime_paths_are_hermes_native (PATH-03)** — `da8b9ea` (test)

## Files Created/Modified

- `skills/revenium/scripts/common.sh` — Added `TAXONOMY_FILE` and `MARKERS_DIR` variable declarations (both using `${REVENIUM_*:-${STATE_DIR}/*}` shape); extended `mkdir -p` to create `MARKERS_DIR` on every source. Net +3 / -1 lines.
- `skills/revenium/scripts/install-cron.sh` — Added `chmod 700 "${MARKERS_DIR}"` between the existing `mkdir -p "${STATE_DIR}"` line and the `chmod +x "${SKILL_DIR}/scripts/"*.sh` line. Net +1 line.
- `tests/test_repository.py` — Extended `test_runtime_paths_are_hermes_native` with four new assertions (substring `task-taxonomy.json`, variable `TAXONOMY_FILE=`, regex for `MARKERS_DIR=` with `:-` env-fallback under `${STATE_DIR}`, substring `markers`). Net +4 lines.
- `.planning/phases/01-path-foundation/deferred-items.md` — New scope-boundary deferral note for the pre-existing `test_no_legacy_branding_left` failure (see Issues Encountered).

## Phase-Level Verification Outcomes

- **`python3 -m unittest discover -p 'test_*.py' -v` (run from `tests/`):** 5 tests run, **4 passing**. The one failure is `test_no_legacy_branding_left`, which was failing on the baseline commit (`e4339be`) before any work in this plan began. The offender list is identical pre- and post-work: `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/TESTING.md`, `.planning/codebase/CONCERNS.md`, `.planning/phases/01-path-foundation/01-01-PLAN.md`. See Issues Encountered.
- **`python3 -m unittest tests.test_repository.RepositoryTests.test_runtime_paths_are_hermes_native -v`:** OK.
- **Fresh-install stat check (`stat -f %A "${MARKERS_DIR}"` on a throwaway `HERMES_HOME=$(mktemp -d)`):** outputs `700` ✓.
- **SSoT discipline grep** — `task-taxonomy.json` outside `skills/revenium/scripts/common.sh` and `tests/test_repository.py`: no matches ✓.
- **SSoT discipline grep** — `markers` in `skills/revenium/scripts/` outside `common.sh`: no matches; `install-cron.sh` refers only to `${MARKERS_DIR}` ✓.
- **Backward-compat variable-count check** — all 10 existing path variables (`HERMES_HOME`, `REVENIUM_STATE_DIR`, `SKILL_DIR`, `STATE_DIR`, `CONFIG_FILE`, `BUDGET_STATUS_FILE`, `LEDGER_FILE`, `LOG_FILE`, `ENV_FILE`, `STATE_DB`) declared exactly once each ✓.
- **Shell-strictness check** — `bash -n` clean on all `skills/revenium/scripts/*.sh` ✓.
- **Negative-fixture sanity** — mutating `MARKERS_DIR` to drop `${STATE_DIR}` rooting causes `test_runtime_paths_are_hermes_native` to fail with a clear assertion error; reverting passes. Confirms the new regex is doing real work, not just substring-matching.

## Decisions Made

- **chmod 700 lives in `install-cron.sh`, not `common.sh`.** `common.sh` is sourced on every cron tick (once per minute); running `chmod 700` 1440 times per day on an already-700 directory is wasted I/O. `install-cron.sh` is operator-invoked (rare) and exists precisely as the canonical install entry, making it the right home for one-shot permission hardening. `setup-local.sh` was considered and rejected — it's a developer-staging helper that runs before any `common.sh` source, so `MARKERS_DIR` is not yet resolvable there. Documented inline in the Task 2 plan rationale.
- **`mkdir -p "${STATE_DIR}" "${MARKERS_DIR}"` (multi-target), not a second separate `mkdir -p "${MARKERS_DIR}"`.** Keeps the single line that owns directory creation; avoids duplicating it, which would drift if `STATE_DIR` changes shape later.
- **PATH-03 test extension stays in `test_runtime_paths_are_hermes_native` (no new method).** The requirement names this method specifically. Splitting into a `test_taxonomy_and_markers_paths_in_common_sh` method would also work but would violate the requirement's explicit naming.

## Deviations from Plan

None - plan executed exactly as written. All three tasks (PATH-01, PATH-02, PATH-03) implemented per spec with no auto-fixes, no architectural escalations, and no scope expansion.

## Issues Encountered

**Pre-existing `test_no_legacy_branding_left` failure (out of scope, scope-boundary deferred).**

The baseline commit (`e4339be docs(01): record phase 1 planning complete`) was already failing `test_no_legacy_branding_left` because four `.planning/` documentation files contain case-folded substrings that match the legacy-branding regex. These are meta-references that quote the test's path-discipline behavior for traceability — they are NOT real branding leakage in shipped runtime code under `skills/`, `examples/`, or `tests/`. Plan 01-01's file scope is `skills/revenium/scripts/common.sh`, `skills/revenium/scripts/install-cron.sh`, and `tests/test_repository.py`; the offending files are explicitly out of scope.

Per executor scope-boundary rule (only fix issues directly caused by current task's changes; log out-of-scope discoveries), the failure is documented in `.planning/phases/01-path-foundation/deferred-items.md` and should be addressed by a separate cleanup plan — likely Phase 5 ("Housekeeping & Compat Hardening") or a dedicated meta-file scrub. The `deferred-items.md` file itself was written so as not to extend the offender list (it references the regex abstractly).

No regression caused by this plan: the offender list is byte-for-byte identical pre- and post-work.

## User Setup Required

None - this plan modifies only the skill's runtime scripts and the invariant test. No external service configuration, no environment variables, no manual steps. Re-running `install-cron.sh` on existing installs is the only user-visible side effect; it is idempotent and the `chmod 700` is a no-op on a directory already at 700.

## Next Phase Readiness

**Phase 2 (Prompt Design & Marker Contract) is unblocked.** `${TAXONOMY_FILE}` and `${MARKERS_DIR}` are now resolvable from any script that sources `common.sh`. Phase 2's marker-writing logic (in `SKILL.md` prompt-side bash, or in any helper) MUST write via `${MARKERS_DIR}/<session_id>.jsonl` and `${TAXONOMY_FILE}`, never via the literal `~/.hermes/state/revenium/markers/...` — the extended `test_runtime_paths_are_hermes_native` will catch any drift in `common.sh`, and the no-inlining property elsewhere is enforced socially in Phase 2.

**Hand-off notes for Phase 2:**

- `MARKERS_DIR` is guaranteed to exist (mode 0700 after a fresh install, mode whatever-it-was before that — but `mkdir -p` runs on every source so the directory itself is never missing). Phase 2 marker writers do NOT need to `mkdir -p "${MARKERS_DIR}"` themselves.
- `TAXONOMY_FILE` is NOT auto-created — only the parent `${STATE_DIR}` is. Phase 2's first taxonomy-write site is responsible for `mkdir -p "$(dirname "${TAXONOMY_FILE}")"` (which is just `${STATE_DIR}`, already covered by `common.sh`) and for atomic-create-or-update semantics on the JSON file itself.
- The env-override hooks (`REVENIUM_TAXONOMY_FILE`, `REVENIUM_MARKERS_DIR`) work just like `REVENIUM_STATE_DIR` — Phase 2 test fixtures can redirect these to a `tmpdir` without touching `HERMES_HOME`.
- Phase 5 ("Housekeeping & Compat Hardening") should add the meta-reference scrub for `test_no_legacy_branding_left` so the full discover run goes green; it should also revisit whether `test_no_legacy_branding_left` ought to skip the `.planning/` tree by default (since that tree is design-document scratch space, not shipped code).

**Backward-compat assertion still holds:** no existing variable was renamed, removed, or reordered; `hermes-report.sh`, `budget-check.sh`, `cron.sh`, `clear-halt.sh`, and `uninstall-cron.sh` were not modified; `SKILL.md` frontmatter was not touched. `bash -n` is clean on every script. All four other tests (`test_expected_files_exist`, `test_skill_frontmatter_has_hermes_metadata`, `test_runtime_paths_are_hermes_native`, `test_shell_scripts_have_valid_syntax`) pass.

## Self-Check

Verifying claims in this summary before returning to the orchestrator.

**Created files:**
- `.planning/phases/01-path-foundation/deferred-items.md` — FOUND

**Modified files (all on `worktree-agent-aaed5527c529271c5`):**
- `skills/revenium/scripts/common.sh` — modified in commit 4136439 ✓
- `skills/revenium/scripts/install-cron.sh` — modified in commit f5265fd ✓
- `tests/test_repository.py` — modified in commit da8b9ea ✓

**Commits exist (verified via `git log --oneline`):**
- 4136439 feat(01-01): declare TAXONOMY_FILE and MARKERS_DIR in common.sh ✓
- f5265fd feat(01-01): harden MARKERS_DIR to mode 0700 in install-cron.sh ✓
- da8b9ea test(01-01): extend test_runtime_paths_are_hermes_native for new state paths ✓

## Self-Check: PASSED

---
*Phase: 01-path-foundation*
*Completed: 2026-05-12*
