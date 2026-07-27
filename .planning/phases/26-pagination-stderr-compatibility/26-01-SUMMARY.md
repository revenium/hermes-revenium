---
phase: 26-pagination-stderr-compatibility
plan: 01
subsystem: infra
tags: [bash, capability-probe, pagination, revenium-cli, guardrails, test-harness]

# Dependency graph
requires: []
provides:
  - "supports_flag() generic capability-probe helper in common.sh"
  - "PAGE_FLAG_SUPPORTED once-per-run resolution in guardrail-check.sh"
  - "Capability-gated EVENT_CMD at the halt-path enforcement-events fetch"
  - "Argv-recording, --help-parameterized _make_revenium_stub test harness"
  - "COMPAT-02 discharged by construction (D-01)"
affects: [26-02-stderr-hardening, 26-03-hot-path-pagination, 26-04-invariant-tests]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Generic --help capability probe (supports_flag) with a trailing word-boundary regex to prevent flag-name substring collisions (--page vs --page-size)"
    - "Once-per-script-run capability resolution into a shell variable (no disk cache, no state path) — D-03"
    - "Array-built CLI invocation (EVENT_CMD=(...); EVENT_CMD+=(...)) gated by an if/then/fi, never VAR=$(supports_flag ...)"
    - "Test-stub argv recording (printf '%s\\n' \"$*\" >> argv_log) plus a --help pre-guard checked before the 3-word case dispatch"

key-files:
  created: []
  modified:
    - skills/revenium/scripts/common.sh
    - skills/revenium/scripts/guardrail-check.sh
    - tests/test_repository.py

key-decisions:
  - "supports_flag() lives in common.sh only; the two existing inline probes in hermes-report.sh are left untouched (D-02 scope fence), verified by git diff --quiet main -- hermes-report.sh"
  - "PAGE_FLAG_SUPPORTED resolves exactly once per script run with no disk cache — the PAGE-01 concurrency edge is closed by construction, not by locking"
  - "Fallback branch reproduces today's exact --page-size 1 --output json argv byte-for-byte (D-04) — no new failure mode on CLI v1.2.1"
  - "COMPAT-02 is discharged by construction: the skill never depends on whether v1.2.1 accepts --page 0, because --page is only ever sent when the probe confirms support"

patterns-established:
  - "Capability-gated array-built CLI invocation: base cmd array, conditional cmd+=(...) inside an explicit if/then/fi, final cmd+=(...) for unconditional flags"
  - "Test stub argv log + --help pre-guard: every future _make_revenium_stub caller can now assert exact flags per call site instead of relying on 3-word case dispatch"

requirements-completed: [PAGE-01, PAGE-04, COMPAT-02]

coverage:
  - id: D1
    description: "Halt-path enforcement-events fetch sends --page 0 --page-size 1 when the CLI advertises --page, and exactly today's --page-size 1 shape when it does not — proven on three distinct --help fixtures via recorded argv, including the --page-size-only collision fixture"
    requirement: "PAGE-01"
    verification:
      - kind: unit
        ref: "tests/test_repository.py#test_enforcement_events_fetch_gated_page_flag"
        status: pass
    human_judgment: false
  - id: D2
    description: "The capability probe writes no state — after a full guardrail-check.sh run, only config.json, guardrail-status.json, and revenium-metering.log are regular files under STATE_DIR"
    requirement: "PAGE-01"
    verification:
      - kind: unit
        ref: "tests/test_repository.py#test_capability_probe_writes_no_state"
        status: pass
    human_judgment: false
  - id: D3
    description: "PAGE-04's docstring/code drift check is mechanical: _make_revenium_stub's docstring and guardrail-check.sh's EVENT_CMD construction are asserted to name the same two argv shapes, verified to go red on injected drift"
    requirement: "PAGE-04"
    verification:
      - kind: unit
        ref: "tests/test_repository.py#test_stub_docstring_matches_gated_event_invocation"
        status: pass
    human_judgment: false
  - id: D4
    description: "COMPAT-02 discharged by construction — the skill's behavior never depends on whether CLI v1.2.1 accepts --page 0, because --page is only sent when the probe confirms support"
    requirement: "COMPAT-02"
    verification: []
    human_judgment: true
    rationale: "This is an architectural claim (D-01: gate unconditionally) rather than a directly-testable runtime behavior — it is substantiated by the passing gated-fetch test (D1) plus code inspection of the if/then/fi gate, but the literal factual answer for v1.2.1 stays unverified until Phase 30's live-host run."

# Metrics
duration: 30min
completed: 2026-07-27
status: complete
---

# Phase 26 Plan 01: Capability-Gated Halt-Path Pagination Summary

**Halt-path `enforcement-events list` fetch is now capability-gated on `--page`, proven end-to-end by recorded argv on three `--help` fixtures, discharging COMPAT-02 by construction rather than experiment.**

## Performance

- **Duration:** ~30 min
- **Completed:** 2026-07-27T19:07:24Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added `supports_flag()` to `common.sh` — a generic, fail-open `--help` capability probe with a trailing word-boundary regex (`[^A-Za-z0-9-]|$`) that stops `--page` from matching `--page-size`.
- Resolved `PAGE_FLAG_SUPPORTED` exactly once per `guardrail-check.sh` run (D-03), placed between the preflight block and `read_config_field()`, with no disk cache and no new state path.
- Gated the halt-path `enforcement-events list` fetch: an `EVENT_CMD` array conditionally appends `--page 0` when the probe succeeds, then always appends `--page-size 1 --output json`; the `__FAIL__` sentinel and `2>/dev/null` are unchanged.
- Extended `_make_revenium_stub` with argv recording (every invocation logged verbatim) and a parameterized `--help` pre-guard (`advertise_page` / `advertise_page_size` kwargs) so tests can prove exact CLI flags per call site instead of the flag-blind 3-word case dispatch. All 7 pre-existing call sites work unchanged.
- Proved the probe→argv→assertion loop on three `--help` fixtures: v1.3.0 shape (both flags), realistic pre-v1.3.0 shape (`--page-size` only — the substring-collision fixture), and an ancient shape (neither flag).
- Closed the PAGE-01 concurrency edge with an exact-set inventory test: after a full run, the only regular files under `STATE_DIR` are `config.json`, `guardrail-status.json`, `revenium-metering.log` — no probe cache, no lock, no marker.
- Replaced PAGE-04's reviewer-diligence note with a mechanical co-occurrence assertion between the stub docstring and `guardrail-check.sh`'s `EVENT_CMD` construction; verified red on injected drift (temporarily renamed `--page 0` append, confirmed failure, restored).

## Task Commits

Each task was committed atomically:

1. **Task 1: End-to-end capability-gated halt-path fetch — one call site, both probe branches** - `34c9b1b` (feat)
2. **Task 2: Probe leaves no state, and the harness docstring stops drifting (PAGE-04)** - `e1991d2` (test)

**Plan metadata:** commit pending (this SUMMARY + STATE/ROADMAP update)

## Files Created/Modified
- `skills/revenium/scripts/common.sh` - Added `supports_flag()` capability-probe helper immediately after `has_guardrails_cli()`.
- `skills/revenium/scripts/guardrail-check.sh` - Added `PAGE_FLAG_SUPPORTED` once-per-run resolution; gated the halt-path `EVENT_CMD` array construction.
- `tests/test_repository.py` - Extended `_make_revenium_stub` (argv log, `--help` pre-guard, `advertise_page`/`advertise_page_size` kwargs) plus `_revenium_argv_log_path`, `test_enforcement_events_fetch_gated_page_flag`, `test_capability_probe_writes_no_state`, `test_stub_docstring_matches_gated_event_invocation`.

## Decisions Made
- Followed D-01 through D-04 and D-13 through D-17 from `26-CONTEXT.md` exactly as specified — no plan-level decisions required deviation.
- Task 2's `test_capability_probe_writes_no_state` fixture was authored as a breaching + autonomous + no-notify-channel scenario (matching Task 1's gated-fetch test) rather than a fully quiescent run, because a totally quiet run never calls `info`/`warn` and therefore never creates `revenium-metering.log` — which would make the exact-set assertion unable to distinguish "log never created" from "probe correctly left no extra state." This is a test-authoring detail, not a scope change; the plan's list of expected files (`config.json`, `guardrail-status.json`, `revenium-metering.log`) is honored exactly.

## Deviations from Plan

None - plan executed exactly as written. The docstring correction for PAGE-04 (plan's Task 2 subsection (b)) was completed proactively as part of Task 1's `_make_revenium_stub` docstring rewrite (it already needed to describe the argv log and the two new kwargs, so the two invocation shapes were documented in the same edit) — Task 2's mechanical assertion (`test_stub_docstring_matches_gated_event_invocation`) then verified that description against the code rather than re-editing the docstring a second time. No functional change to plan scope.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The proven vertical slice (`supports_flag()` → `PAGE_FLAG_SUPPORTED` → gated `EVENT_CMD` → argv-log → assertion) is ready to be replicated by plans 26-02 (stderr hardening), 26-03 (hot-path pagination bound), and 26-04 (invariant tests across all list-family call sites), per the plan's stated purpose.
- `_make_revenium_stub`'s argv-log and `--help` pre-guard infrastructure is now available to every subsequent test in this phase without further harness work.
- No blockers. Full suite green at 157/157 (baseline 154 + 3 new tests from this plan).

---
*Phase: 26-pagination-stderr-compatibility*
*Completed: 2026-07-27*
