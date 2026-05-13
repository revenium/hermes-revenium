---
phase: 06-mechanical-classification-agent-end-hook
plan: 01
subsystem: hooks
tags: [hooks, agent-end, classification, llm, subagent-inheritance, mechanical-enforcement, sqlite, asyncio, fcntl, python]

# Dependency graph
requires:
  - phase: 01-path-foundation
    provides: MARKERS_DIR + STATE_DIR path discipline in common.sh; hook reuses the exact same env-var-overridable path shape.
  - phase: 02-prompt-design-marker-contract
    provides: marker schema {muid, ts, sid, task_type, operation_type}, LABEL_RE, TRIVIAL_BLOCKLIST, GUARDRAIL+CHAT pair convention, 33-char hex muid recipe. The hook produces markers in this exact schema.
  - phase: 03-cron-marker-reader-equal-split-ledger-v2
    provides: per-muid cron-side dedup + parse_prior_state + S2 equal-split. The hook produces input that flows straight through this pipeline with zero changes.
provides:
  - Mechanical floor for marker writes — every agent:end turn produces a GUARDRAIL+CHAT marker pair regardless of whether the agent self-classifies
  - Subagent task_type inheritance via state.db.sessions.parent_session_id chain walk (read-only, depth-capped)
  - Budget-halt gating before the classifier LLM call — classifier never trips its own halt
  - D-13 double-write avoidance via 30s wall-clock tail-check, compatible with SKILL.md FINAL ACTION block
  - Heuristic skip-fast-path for trivial turns (no tools + response < 200 chars)
  - End-to-end test suite covering every error path; D-04 never-raises invariant pinned
affects: [phase-04-wire-enrichment, phase-05-housekeeping, hermes-uat]

# Tech tracking
tech-stack:
  added:
    - "Python stdlib only: asyncio, fcntl, json, logging, os, re, secrets, sqlite3, time, pathlib"
    - "Optional in-process import: agent.auxiliary_client.call_llm (lazy try/except ImportError → call_llm=None)"
    - "Hermes event-hook subsystem: agent:end event via gateway/hooks.py::HookRegistry.discover_and_load()"
  patterns:
    - "Module-level env-var-overridable path constants mirroring scripts/common.sh"
    - "Async handler with outer try/except (D-04 never-raises invariant)"
    - "Read-only SQLite URI mode (file:?mode=ro) for state.db access — no WAL lock contention with Hermes writer"
    - "fcntl.LOCK_EX + O_APPEND atomic marker pair write under a single lock"
    - "Wall-clock-proximity dedupe (D-13 30s tail-check) belt-and-suspenders for the agent FINAL ACTION code path"
    - "asyncio.to_thread wrapping for blocking calls (call_llm, _write_marker_pair) to keep the event loop unblocked"
    - "Lookup-first LLM prompt with regex + blocklist validation at the handler boundary (no trust in LLM output)"

key-files:
  created:
    - "skills/revenium/hooks/revenium-classifier/HOOK.yaml"
    - "skills/revenium/hooks/revenium-classifier/handler.py"
    - "skills/revenium/hooks/revenium-classifier/test-payloads/trivial-turn.json"
    - "skills/revenium/hooks/revenium-classifier/test-payloads/substantive-turn.json"
    - "skills/revenium/hooks/revenium-classifier/test-payloads/subagent-turn.json"
    - ".planning/phases/06-mechanical-classification-agent-end-hook/06-01-SUMMARY.md"
  modified:
    - ".planning/REQUIREMENTS.md"
    - ".planning/ROADMAP.md"
    - ".planning/phases/06-mechanical-classification-agent-end-hook/06-CONTEXT.md"
    - "examples/setup-local.sh"
    - "skills/revenium/references/setup.md"
    - "tests/test_repository.py"

key-decisions:
  - "D-03 resolved: classifier uses agent.auxiliary_client.call_llm (in-process sync) wrapped with asyncio.to_thread — no direct httpx fallback in v1"
  - "D-13 implemented as wall-clock-proximity check (30s window) per Pitfall 6 option (a) — cheaper than tracking turn_seq and sufficient for the SKILL.md FINAL ACTION belt-and-suspenders use case"
  - "D-15 resolved via (b): examples/setup-local.sh copies hook into ~/.hermes/hooks/; hermes skills install does NOT relocate hooks/ subdirs (RESEARCH.md Gate 3)"
  - "Conflict C1/C2 wording fix: hermes hooks list / hermes hooks test are for SHELL hooks; event-hook verification uses gateway startup log + direct handler.handle() invocation"
  - "B1 fix: examples/setup-local.sh now prunes the stale ${TARGET_DIR}/hooks duplicate created by the bulk skill copy before installing the canonical hook (RESEARCH.md Pitfall 7)"
  - "B3 fix: T08 landed a stub call_llm invocation so the halt-gate test (mock_llm.assert_not_called) meaningfully pinned the gate's semantic effect; T09 replaced the stub with the full prompt-building + validation pipeline"

patterns-established:
  - "Module-level path constants pattern: env-var-overridable with sensible defaults, evaluated at import time, tests redirect via importlib.reload + env var swap"
  - "Lazy import pattern: from X import Y wrapped in try/except ImportError → Y = None at module load, allowing tests to patch directly without the real dependency installed"
  - "Async hook handler pattern: outer try/except over async body; all error paths fall through to logger.warning + return; D-04 never-raises invariant"
  - "Atomic marker pair write: O_APPEND + fcntl.LOCK_EX + two compact JSONL records under a single lock — < 1024 bytes per line"
  - "_setup_hook_env / _restore_hook_env test helpers: tempdir + env-var redirect + sys.path manipulation + importlib.reload, copy-paste-free across 9 hook tests"

requirements-completed: [HOOK-01, HOOK-02, HOOK-03, HOOK-04, HOOK-05, HOOK-06, HOOK-07, HOOK-08, HOOK-09, HOOK-10]

# Metrics
duration: ~50min
completed: 2026-05-13
---

# Phase 06 Plan 01: Mechanical Classification via Hermes agent:end Hook Summary

**In-process agent:end event hook that writes a GUARDRAIL+CHAT marker pair for every substantive turn — independent of agent self-classification — with state.db subagent inheritance, budget-halt gating, and SKILL.md FINAL ACTION double-write avoidance.**

## Performance

- **Duration:** ~50 min
- **Started:** 2026-05-13T17:46Z (worktree branch base aba6d0c)
- **Completed:** 2026-05-13T18:36Z
- **Tasks:** 15 (T01–T15)
- **Files created:** 6 (HOOK.yaml + handler.py + 3 test payloads + SUMMARY.md)
- **Files modified:** 6 (REQUIREMENTS.md, ROADMAP.md, 06-CONTEXT.md, setup-local.sh, setup.md, test_repository.py)

## Accomplishments

- Hermes lifecycle hook at `skills/revenium/hooks/revenium-classifier/` with `HOOK.yaml` + `handler.py` matching the gateway's discover_and_load() contract for `agent:end`.
- `async def handle(event_type, context)` implementing the full D-04 → D-14 pipeline: subagent inheritance → heuristic skip → D-13 dedupe → budget gate → LLM classification → validated label → atomic marker pair write.
- Subagent task_type inheritance via depth-capped read-only `parent_session_id` chain walk on `~/.hermes/state.db`.
- Budget-halt gating reads `~/.hermes/state/revenium/budget-status.json` and writes `task_type: unclassified` + WARN log when halted.
- LLM call via `agent.auxiliary_client.call_llm` wrapped in `asyncio.to_thread` with NO `task=` argument (Pitfall 8 / A3 / D-06 — uses user's main budgeted model).
- Label validation against `^[a-z][a-z0-9_]{1,47}$` + trivial blocklist `{ack, acknowledgment, greeting, confirmation, hello, thanks}`; fall-through to `unclassified` on any validation failure.
- Atomic O_APPEND + fcntl.LOCK_EX write of a GUARDRAIL + CHAT marker pair, < 1024 bytes per line, Phase 2 schema, 33-char hex muid.
- `examples/setup-local.sh` copies the hook into `~/.hermes/hooks/revenium-classifier/` idempotently, prunes the stale `${TARGET_DIR}/hooks` duplicate (B1), and prints a `hermes gateway restart` next step.
- `skills/revenium/references/setup.md` carries a `## Mechanical classification hook` section after `## How attribution works` documenting installation, restart, three verification mechanisms, and the explicit "do NOT use `hermes hooks list`" callout (Conflict C1/C2).
- Test suite: 14 → 26 tests (12 new). Every existing Phase 1-3 test still passes. D-17 + D-18 backward-compat invariants verified via `git diff` (zero lines vs. base for SKILL.md, hermes-report.sh, split_strategies.py, cron.sh, common.sh, task-taxonomy.json).

## Task Commits

Each task was committed atomically; every commit leaves `python3 -m unittest discover -s tests -p 'test_*.py'` green.

1. **T01: Add HOOK-01..HOOK-10 + finalize Phase 6 roadmap placeholders** — `6a61e19` (docs)
2. **T02: Add HOOK.yaml manifest** — `8236cb6` (feat)
3. **T03: Add handler.py scaffold with marker-pair writer and async handle stub** — `5c46293` (feat)
4. **T05: Add synthetic agent:end payload fixtures** — `798ee6e` (test)  *[landed before T04 to keep test_expected_files_exist green]*
5. **T04: Assert hook files exist + test_revenium_classifier_marker_pair** — `4df8579` (test)
6. **T06: Wire heuristic skip-fast-path using session jsonl tool count (HOOK-02)** — `83e082d` (feat)
7. **T07: Walk state.db parent_session_id chain for subagent inheritance (HOOK-03)** — `734028f` (feat)
8. **T08: Gate LLM call on budget-status.json halt flag (HOOK-04)** — `aaa5ec2` (feat)
9. **T09: Wire LLM classification via call_llm with regex + blocklist validation (HOOK-05)** — `b886aee` (feat)
10. **T10: Tail-check 30s marker pair to avoid double-writes (HOOK-07)** — `76eff11` (feat)
11. **T11: Pin D-04 error-isolation invariant — handle() never raises** — `05d2b86` (test)
12. **T12: Install agent:end hook from setup-local.sh + document gateway restart (HOOK-08)** — `bca9a97` (chore)
13. **T13: Add Mechanical classification hook section to references/setup.md (HOOK-10)** — `3188086` (docs)
14. **T14: Assert setup.md carries the Mechanical classification hook section (HOOK-10)** — `63bf925` (test)

**Plan metadata commit (T15):** lands with this SUMMARY.md.

_Note: T04 + T05 were swapped in execution order to keep `test_expected_files_exist` green at every commit, exactly as the plan's `<action>` block permits ("the implementer commits T04+T05 together if the gap window is uncomfortable; alternatively, the implementer reorders to land fixtures first, then the test extension second … the final state is identical")._

## Files Created/Modified

### Created

- `skills/revenium/hooks/revenium-classifier/HOOK.yaml` — Event-hook manifest declaring `name: revenium-classifier`, `events: [agent:end]`, and a description. Matches the `gateway/hooks.py::HookRegistry.discover_and_load()` contract verbatim.
- `skills/revenium/hooks/revenium-classifier/handler.py` — 200-line async handler implementing the full D-04..D-14 pipeline. Module-level path constants mirror `common.sh`. Module-level `LABEL_RE`, `TRIVIAL_BLOCKLIST`, lazy `call_llm` import, and 10 private helpers. `async def handle(event_type, context)` wraps the whole body in a try/except → `logger.warning` (D-04 never-raises).
- `skills/revenium/hooks/revenium-classifier/test-payloads/trivial-turn.json` — Short-response fixture for the HOOK-02 heuristic skip test.
- `skills/revenium/hooks/revenium-classifier/test-payloads/substantive-turn.json` — > 200-char response fixture for HOOK-04/05/07 tests.
- `skills/revenium/hooks/revenium-classifier/test-payloads/subagent-turn.json` — Child-sid fixture used in HOOK-03 inheritance test.
- `.planning/phases/06-mechanical-classification-agent-end-hook/06-01-SUMMARY.md` — This file.

### Modified

- `.planning/REQUIREMENTS.md` — Added 10 new HOOK-01..HOOK-10 entries under `### Mechanical Classification Hook (Phase 6)` + 10 traceability rows + coverage counts (37 → 47).
- `.planning/ROADMAP.md` — Phase 6 Requirements line: `TBD` → `HOOK-01..HOOK-10`. Plans line: `TBD` → `1 plan (single fat plan; load-bearing tight coupling)`. SC1/SC2 wording fixed per Conflict C1/C2 (gateway log + direct handler invocation, not `hermes hooks list/test`). Coverage counts 37 → 47; Categories appended `, HOOK (10)`. Progress Table row updated to `0/1 | Not started`.
- `.planning/phases/06-mechanical-classification-agent-end-hook/06-CONTEXT.md` — Inserted `[SUPERSEDED by Conflict C2 in 06-RESEARCH.md]` marker on the stale `hermes hooks test agent:end --payload-file <fixture>` bullet.
- `examples/setup-local.sh` — Added Phase 6 hook copy block (lines 27-34) with B1 prune of `${TARGET_DIR}/hooks` duplicate. Replaced "Next steps" echo block to include `hermes gateway restart`.
- `skills/revenium/references/setup.md` — Appended `## Mechanical classification hook` section after `## How attribution works` (32 lines covering installation, gateway restart, three verification mechanisms, and the explicit "Do NOT use `hermes hooks list`" callout).
- `tests/test_repository.py` — Added `HOOK_DIR` constant, `_agent_aux_client_available()`, `_setup_hook_env()`, `_restore_hook_env()` module-level helpers. Extended `test_expected_files_exist` with 5 new hook files. Added 9 new test methods: `test_revenium_classifier_marker_pair`, `test_revenium_classifier_trivial_skip`, `test_revenium_classifier_substantive_uses_session_jsonl_tool_count`, `test_revenium_classifier_subagent_inherits`, `test_revenium_classifier_walk_to_root`, `test_revenium_classifier_halt_unclassified`, `test_revenium_classifier_halt_failopen_on_missing_file`, `test_revenium_classifier_llm_label`, `test_revenium_classifier_llm_blocklist_fallthrough`, `test_revenium_classifier_dedupe`, `test_revenium_classifier_never_raises`, `test_setup_md_has_mechanical_classification_hook_section` — 12 in total. (The plan's lower-bound estimate was 6+; we landed 12 because each substantive helper got a focused method to keep `git bisect` precise.)

## Decisions Honored (D-01..D-18 + Conflict C1/C2)

- **D-01** (event = agent:end): HOOK.yaml `events: [agent:end]`.
- **D-02** (file layout): hook at `skills/revenium/hooks/revenium-classifier/`; HOOK.yaml + handler.py.
- **D-03** (in-process call_llm): `from agent.auxiliary_client import call_llm` lazy import + `asyncio.to_thread` wrapper. No httpx fallback.
- **D-04** (never raises): outer try/except + `logger.warning` in handle(). Pinned by `test_revenium_classifier_never_raises`.
- **D-05** (subagent inheritance): `_walk_to_root_session` recurses parent_session_id chain (depth-capped at 10) + `_read_latest_task_type` reads root's marker file. Pinned by `test_revenium_classifier_subagent_inherits`.
- **D-06** (LLM-assisted classification): `_classify_via_llm` calls call_llm with NO `task=` argument so the user's main budgeted model is used. Prompt is lookup-first with the existing taxonomy listed inline.
- **D-07** (heuristic skip): `_count_tools_in_current_turn(sid) == 0 AND len(response) < 200 → return`. Pinned by `test_revenium_classifier_trivial_skip`.
- **D-08** (budget halt gate): `_budget_halted()` reads `BUDGET_STATUS_FILE` with try/except fail-open. Pinned by `test_revenium_classifier_halt_unclassified` + `test_revenium_classifier_halt_failopen_on_missing_file`.
- **D-09** (trivial-label blocklist): `_validate_label` enforces `LABEL_RE` AND TRIVIAL_BLOCKLIST. Pinned by `test_revenium_classifier_llm_blocklist_fallthrough`.
- **D-10** (two marker records per substantive turn): `_write_marker_pair` writes one GUARDRAIL + one CHAT. Pinned by `test_revenium_classifier_marker_pair`.
- **D-11** (marker path): `MARKERS_DIR / f"{sid}.jsonl"` per common.sh.
- **D-12** (marker record format): 5-key required schema; 33-char hex muid (`f"{int(time.time_ns()//1_000_000):013x}" + secrets.token_hex(10)`).
- **D-13** (double-write avoidance): `_recent_marker_pair_exists(sid, within_seconds=30.0)` tail-check. Pinned by `test_revenium_classifier_dedupe`.
- **D-14** (atomic write): `O_APPEND` + `fcntl.LOCK_EX` under a single lock.
- **D-15** (distribution): option (b) — `examples/setup-local.sh` does the copy. `hermes skills install` does NOT relocate `hooks/` subdirs (RESEARCH.md Gate 3).
- **D-16** (setup.md docs): new `## Mechanical classification hook` section AFTER `## How attribution works`. Pinned by `test_setup_md_has_mechanical_classification_hook_section`.
- **D-17** (SKILL.md unchanged): `git diff aba6d0c -- skills/revenium/SKILL.md` is empty. `test_prompt_ordering_invariant` still passes.
- **D-18** (Phase 3 cron unchanged): `git diff aba6d0c` empty for `hermes-report.sh`, `split_strategies.py`, `cron.sh`, `common.sh`, `task-taxonomy.json`. `test_cron_marker_split_end_to_end` still passes.
- **Conflict C1/C2 fix**: ROADMAP SC1/SC2 + setup.md anti-pattern callout both reflect that `hermes hooks list / test` is a SHELL-hook CLI and does not dispatch the Python event hook. Verification mechanism is gateway log line + direct `handler.handle(...)` invocation.

## Deviations from Plan

None - plan executed exactly as written. The only execution-order tweak was swapping T04 ↔ T05 (fixtures landed before the `test_expected_files_exist` extension that asserts they exist) — the plan's `<action>` block explicitly permits this reordering and notes "the final state is identical."

## Issues Encountered

- None. Every task's verify block passed on the first attempt. The test suite stayed green at every commit (14 → 15 → 17 → 19 → 21 → 23 → 24 → 25 → 26 tests as the plan progressed).

## User Setup Required

None - no external service configuration required during plan execution. **Manual operator step before this hook actually fires in production:** run `bash examples/setup-local.sh && hermes gateway restart` on the Mac Studio. The gateway startup log should emit `[hooks] Loaded hook 'revenium-classifier' for events: ['agent:end']`. This is the only step that cannot be automated in CI (RESEARCH.md Gate 2 / SC6).

## Open Questions Surfaced for Retro

From RESEARCH.md A1-A4, all locked at the recommended values; surface to the retro if the Mac Studio UAT shows otherwise:

- **A1** (`agent.auxiliary_client.call_llm` vs direct httpx): Locked on in-process call_llm. If the Hermes venv import shape changes, the lazy `try/except ImportError` keeps the test suite green but the hook will silently fall through to `unclassified` in production.
- **A2** (30s tail-check window): Locked at 30 seconds. If multi-turn sessions produce > 1 substantive turn within a single 30s wall-clock window, the second turn's marker pair would be suppressed. Operator-observable via `WARN` log absence + marker-file line count.
- **A3** (no `task=` argument to call_llm): Locked. If Hermes' aux client adds a required `task=` argument later, the call_llm invocation will start failing — surfacing as `logger.warning("revenium-classifier LLM call failed: %s", ...)` + `task_type: unclassified` markers, which the UAT will catch.
- **A4** (response-length threshold = 200 chars): Locked. If the typical substantive turn's response trends shorter (e.g., quick code-review acknowledgments), the heuristic skip will mark turns as trivial too aggressively. Tunable via the literal `< 200` in handler.py if needed.

## Next Phase Readiness

- **Phase 4 (Wire Enrichment)**: ready — Phase 6 does not block. Phase 4's WIRE-01..WIRE-04 land on the cron side; Phase 6 hooks feed markers into the same pipeline.
- **Phase 5 (Housekeeping)**: ready — Phase 6 produces marker files just like Phase 2 SKILL.md FINAL ACTION did, so prune-markers.sh (the Phase 5 deliverable) will treat hook-written markers identically.
- **Manual UAT gate before Phase 6 is marked Verified**: operator runs `bash examples/setup-local.sh && hermes gateway restart` on the Mac Studio, exercises a fresh substantive Hermes session WITHOUT loading the revenium skill, and confirms (a) gateway log emits the load line, (b) `~/.hermes/state/revenium/markers/<sid>.jsonl` contains a meaningful (non-unclassified) GUARDRAIL+CHAT pair, (c) the next cron tick reports the session to Revenium with a non-unclassified `--task-type`.

## Self-Check: PASSED

Verified before write:

- All 14 commits present in `git log aba6d0c..HEAD`: 6a61e19, 8236cb6, 5c46293, 798ee6e, 4df8579, 83e082d, 734028f, aaa5ec2, b886aee, 76eff11, 05d2b86, bca9a97, 3188086, 63bf925 — FOUND.
- All 5 created files present: HOOK.yaml, handler.py, trivial-turn.json, substantive-turn.json, subagent-turn.json — FOUND.
- All 5 modified files present and committed: REQUIREMENTS.md, ROADMAP.md, 06-CONTEXT.md, setup-local.sh, setup.md, test_repository.py — FOUND.
- Test suite green: 26 tests run, OK status — VERIFIED.
- D-17 / D-18 zero-diff invariants: SKILL.md, hermes-report.sh, split_strategies.py, cron.sh, common.sh, task-taxonomy.json all unchanged vs. base aba6d0c — VERIFIED.

---
*Phase: 06-mechanical-classification-agent-end-hook*
*Completed: 2026-05-13*
