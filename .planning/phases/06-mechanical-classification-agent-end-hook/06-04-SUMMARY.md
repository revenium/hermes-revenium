---
phase: 06-mechanical-classification-agent-end-hook
plan: 04
subsystem: cron+plugins
tags: [plugins, hermes-cli, on-session-end, cron, sentinel, settle-window, race-fix, gap-closure]

# Dependency graph
requires:
  - plan: 06-03-PLAN.md
    provides: Tool-count source-of-truth swap (state.db.sessions.tool_call_count primary, JSONL fallback) — the classifier correctly identifies substantive CLI turns. Sentinel-write contract in this plan layers on top — the classifier produces a marker; the plugin then signals readiness via sentinel so the cron does not race the LLM.
provides:
  - "Plugin sentinel write — per-session empty file at MARKERS_READY_DIR/<sid> written from _on_session_end after run_classification returns (every outcome) AND in the outer except handler (D-04 belt extension). Classifier crash no longer freezes a session in the cron's race window."
  - "Cron settle-window filter — hermes-report.sh session SELECT filters by (sentinel exists for sid) OR (started_at < now - REVENIUM_CRON_SETTLE_SECONDS, default 120s). Sentinel-driven primary path; aged-safety-net for plugin-failure cases."
  - "Closes G-03 in code: cron-race ship-unclassified-before-marker no longer happens. CLI sessions whose final turn straddles a minute boundary are deferred to the next tick after the plugin's sentinel lands."
  - "Six new HOOK-13 tests pin the regression guard: sentinel write happy + error paths, cron filter skip-recent-no-sentinel + include-aged-no-sentinel + include-any-age-with-sentinel, end-to-end cron+sentinel ships marker's task_type."
  - "ROADMAP Phase 6 SC5 explicitly calls out the cron sentinel-or-aged synchronization invariant via the new MARKERS_READY_DIR + REVENIUM_CRON_SETTLE_SECONDS clauses."
affects: [phase-04-wire-enrichment, phase-05-housekeeping, hermes-uat]

# Tech tracking
tech-stack:
  added:
    - "Empty-file sentinel signalling pattern at ${MARKERS_READY_DIR}/<sid> — zero-byte touch-style file; existence is the signal. Owner-only directory mode inherited from STATE_DIR (0o700)."
    - "Cron-side settle-window filter via env var REVENIUM_CRON_SETTLE_SECONDS (default 120s). Stdlib-only Python heredoc reads MARKERS_READY_DIR for sentinel existence; falls through to age check on absence."
  removed:
    - "Cron-race window — cron no longer ships task_type=unclassified ~6s before the plugin writes the marker for CLI sessions straddling a minute boundary."
  patterns:
    - "Empty-file sentinel signalling: the plugin writes a zero-byte file in a path-discipline-managed directory; the cron-side filter checks existence to gate downstream behavior. No payload, no parsing, no schema — pure existence semantics. Reusable for future cron/plugin synchronization needs."
    - "Settle-window safety net: a sentinel-driven primary path layered on an age-based fallback. The sentinel is the deterministic happy-path signal; the age check handles plugin-absent / plugin-crashed / plugin-uninstalled cases. Cron eventually reports every session (no infinite deferral) while honoring the explicit signal when present."

key-files:
  created:
    - ".planning/phases/06-mechanical-classification-agent-end-hook/06-04-SUMMARY.md"
  modified:
    - "skills/revenium/scripts/common.sh"
    - "skills/revenium/scripts/hermes-report.sh"
    - "skills/revenium/plugins/revenium-classifier/__init__.py"
    - "skills/revenium/plugins/revenium-classifier/classifier.py"
    - "tests/test_repository.py"
    - ".planning/REQUIREMENTS.md"
    - ".planning/ROADMAP.md"
    - ".planning/phases/06-mechanical-classification-agent-end-hook/06-VERIFICATION.md"
  deleted: []

# Key decisions honored
key-decisions:
  - "D-21 (locked in CONTEXT.md addendum #3): plugin writes per-session sentinel at MARKERS_READY_DIR/<sid> after every on_session_end outcome; cron filters session SELECT by sentinel-or-aged with default 120s settle window. Sentinel is the deterministic primary path; the age check is the safety net for plugin-failure cases. Alternatives considered: (a) settle-delay-only — fails for long-running sessions; (b) sentinel — CHOSEN; (c) plugin writes ended_at to state.db — violates no-writes-to-state.db invariant; (d) re-shipping with --cost 0 rows — doubles row count, complicates analytics."
  - "D-04 (extended to sentinel write): _on_session_end MUST NEVER raise out. Sentinel write is wrapped in its own try/except Exception inside the new _write_sentinel helper; a permission error, filesystem-full, or any unexpected OSError logs a warning and swallows. The safety-net (started_at age) covers any case where the sentinel fails to land."
  - "Scope discipline (CONTEXT.md addendum #3 'Out of scope (deliberately)'): NO logic changes to classifier.py (only one-line MARKERS_READY_DIR constant addition); NO changes to heuristic-skip threshold or shape; NO changes to response-text signal handling; NO addressing of CR-01/CR-02/CR-03 from 06-02-REVIEW.md; NO migration of the existing 12 HOOK-* tests or 4 HOOK-12 tests; NO changes to setup-local.sh, references/setup.md, SKILL.md, or HOOK-01..HOOK-12 entry strings."

# Patterns established
patterns-established:
  - "Empty-file sentinel signalling pattern: the plugin writes a zero-byte file in a path-discipline-managed directory; the cron-side filter checks existence to gate downstream behavior. No payload, no parsing, no schema — pure existence semantics. Reusable for future cron/plugin synchronization needs without re-litigating the IPC shape."
  - "Settle-window safety net pattern: a sentinel-driven primary path layered on an age-based fallback. The sentinel is the deterministic happy-path signal; the age check handles plugin-absent / plugin-crashed / plugin-uninstalled cases. Cron eventually reports every session (no infinite deferral) while honoring the explicit signal when present."

requirements-completed: [HOOK-01, HOOK-02, HOOK-03, HOOK-04, HOOK-05, HOOK-06, HOOK-07, HOOK-08, HOOK-09, HOOK-10, HOOK-11, HOOK-12, HOOK-13]

duration: ~15min
completed: 2026-05-14
---

# Phase 06 Plan 04: Gap-closure — Plugin sentinel + cron settle-window filter (closes G-03)

Added a per-session sentinel file at `${MARKERS_READY_DIR}/<sid>` written by the plugin's `on_session_end` after every classification outcome; `hermes-report.sh` now filters its session SELECT by sentinel-or-aged with a 120s default settle window, closing G-03 (cron-ticker racing the LLM classifier) surfaced by Mac Studio UAT round 3.

## Performance

- **Tasks:** 8 (T01..T08) — all complete
- **Commits:** 8 atomic commits (one per task)
- **Files modified:** 8 (common.sh, hermes-report.sh, __init__.py, classifier.py, test_repository.py, REQUIREMENTS.md, ROADMAP.md, 06-VERIFICATION.md)
- **Files created:** 1 (this SUMMARY.md)
- **Files deleted:** 0
- **Tests:** 31 → 37 (5 new HOOK-13 unit tests + 1 new HOOK-13 end-to-end test); all green at every commit
- **Production code diff:** common.sh +1 line (MARKERS_READY_DIR declaration + mkdir extension); classifier.py +1 line (MARKERS_READY_DIR constant); __init__.py +36 lines (_write_sentinel helper + two call sites + import line); hermes-report.sh +98 lines (Python heredoc filter + skip-log emission). No logic changes to existing classifier helpers.

## Accomplishments

- **T01 path declaration** — `skills/revenium/scripts/common.sh` declares `MARKERS_READY_DIR="${REVENIUM_MARKERS_READY_DIR:-${STATE_DIR}/markers/.ready}"` with env-override-with-fallback shape immediately after `MARKERS_DIR`; the existing `mkdir -p` line is extended to include the new directory so it is created on first source. `skills/revenium/plugins/revenium-classifier/classifier.py` mirrors the constant as a `Path` object alongside the existing `MARKERS_DIR`. `tests/test_repository.py::test_runtime_paths_are_hermes_native` extended with the regex assertion for the new path. Path-discipline single-source-of-truth invariant preserved end-to-end.
- **T01 collateral fix (Rule 1 deviation)** — two existing cleanup loops in `test_cron_marker_split_end_to_end` did `os.unlink(os.path.join(markers_dir, f_))` for every entry in `markers_dir`; the new `.ready/` subdirectory caused `PermissionError` on macOS. Fixed both cleanup loops to skip subdirectories with `if os.path.isdir(full_path): continue` before the unlink — preserves the test's intent (clear marker files between fixture runs) while tolerating the new sentinel directory.
- **T02 plugin sentinel write** — `skills/revenium/plugins/revenium-classifier/__init__.py` gains a `_write_sentinel(session_id)` private helper that builds `MARKERS_READY_DIR / session_id`, calls `Path(...).touch(exist_ok=True)`, and wraps the entire body in `try/except Exception` (`logger.warning` + swallow). `_on_session_end` calls `_write_sentinel(session_id)` AFTER `run_classification` returns inside the existing try-block (happy path covers substantive, trivial-skip, inheritance, and halt outcomes) AND AFTER the existing `logger.warning(...)` call in the outer `except Exception` handler (D-04 belt extension — classifier crash must not freeze a session). D-04 invariant END-TO-END preserved: `_on_session_end` returns None on every code path; `_write_sentinel` never raises.
- **T03 cron sentinel-or-aged filter** — `skills/revenium/scripts/hermes-report.sh` gains a stdlib-only Python heredoc inserted BETWEEN the existing sqlite SELECT and the existing `while IFS='|' read` loop. The heredoc consumes `${sessions}` via env var (because `python3 - <<PY` displaces pipe stdin), keeps rows iff `(MARKERS_READY_DIR / sid).exists() OR (now - started_at >= SETTLE_SECONDS)`, and emits one tab-separated skip log line per dropped session to a tmp file. Bash then iterates the skip log and emits one `info` line per skipped sid through the existing log helper so formatting matches `[INFO ] [revenium] skipping <sid> — awaiting plugin sentinel (age=Ns < settle=120s)`. `SETTLE_SECONDS = int(os.environ['REVENIUM_CRON_SETTLE_SECONDS'] or '120')` with try/except fallback to 120 (operator-typo protection). Soft-fail discipline preserved: malformed rows pass through unchanged; heredoc-level error falls back to legacy unfiltered behavior via `|| filtered_sessions="${sessions}"`. The downstream while-loop is byte-identical to pre-edit.
- **T04 planning artifacts** — `.planning/REQUIREMENTS.md` gains HOOK-13 entry under "Mechanical Classification Hook (Phase 6)" subsection + traceability row; Coverage block bumps `v1 requirements: 49 → 50` and `Mapped to phases: 49 → 50`. `.planning/ROADMAP.md` Phase 6 Requirements line appends `, HOOK-13`; SC5 wording adds the cron sentinel-or-aged synchronization invariant referencing `MARKERS_READY_DIR` and `REVENIUM_CRON_SETTLE_SECONDS`; Plans count `3 → 4` and the 06-04 entry is appended; Categories `HOOK (12) → HOOK (13)`; Progress Table row updates from `3/3 ... G-03 surfaced` to `3/4 In progress — G-03 gap closure planned in 06-04-PLAN.md`. Top-of-file Phase 6 bullet appends the gap-closure summary.
- **T05 five unit tests** — `tests/test_repository.py` gains:
  - `test_revenium_classifier_sentinel_written_on_happy_path` — sentinel written when run_classification completes normally.
  - `test_revenium_classifier_sentinel_written_on_error_path` — sentinel STILL written when run_classification raises (D-04 belt extension).
  - `test_revenium_classifier_cron_filter_skips_recent_no_sentinel` — 30s-old session with NO sentinel is SKIPPED.
  - `test_revenium_classifier_cron_filter_includes_aged_no_sentinel` — 200s-old session with NO sentinel is INCLUDED with D-18 default `--task-type unclassified`.
  - `test_revenium_classifier_cron_filter_includes_any_age_with_sentinel` — 5s-old session WITH a sentinel is INCLUDED (sentinel-wins).
- **T06 end-to-end test** — `tests/test_repository.py::test_revenium_classifier_cron_filter_end_to_end_ships_marker_task_type` seeds state.db row + marker file at MARKERS_DIR/cli-sid.jsonl with task_type=generation + sentinel at MARKERS_READY_DIR/cli-sid; stubs revenium CLI at `$HOME/.local/bin`; invokes `hermes-report.sh`; asserts the recorded argv contains `--task-type generation` AND does NOT contain `--task-type unclassified`. CI regression guard that would have caught G-03 on 2026-05-14 before operator UAT had to surface it.
- **T07 VERIFICATION.md** — `06-VERIFICATION.md` G-03 entry transitions `gap_closure: pending → executed`; `gap_closure_plan: TBD → 06-04-PLAN.md`; new `gap_closure_outcome` field documents the sentinel + cron-filter code-side closure; `relates_to: [HOOK-12, SC2, SC5, Phase-3-cron-pipeline] → [HOOK-13, SC5, Phase-3-cron-pipeline]`. `re_verification.gaps_closed: [G-01, G-02] → [G-01, G-02, G-03]` reflects code-side closure. Frontmatter `status: requires_rerun_uat` PRESERVED verbatim; `re_verification.gaps_remaining: [G-03]` PRESERVED verbatim — G-03 retires operationally only after UAT round 4.

## Task Commits

1. `f6adede` feat(06): declare MARKERS_READY_DIR in common.sh + classifier.py; extend path-discipline test (HOOK-13 prep)
2. `581cfbd` feat(06): plugin __init__.py writes sentinel at MARKERS_READY_DIR/sid after run_classification (HOOK-13)
3. `d6a269f` feat(06): hermes-report.sh sentinel-or-aged session filter (D-21, closes G-03 cron-race)
4. `d974928` docs(06): add HOOK-13 requirement and update Phase 6 SC5 for cron sentinel + settle-window
5. `f108a0e` test(06): add 5 unit tests for sentinel write + cron sentinel-or-aged filter (HOOK-13)
6. `8162a93` test(06): add end-to-end cron+sentinel test — ships marker task_type, not unclassified (HOOK-13 / G-03)
7. `8483e6e` docs(06): mark G-03 gap_closure: executed in 06-VERIFICATION.md (status preserved at requires_rerun_uat)
8. (this commit) docs(06): summarize 06-04 — G-03 closure via plugin sentinel + cron settle-window; UAT-4 gate references all 3 gaps

Per the plan's commit_strategy, every commit left `python3 -m unittest discover -s tests -p 'test_*.py' -v` green. Ordering is load-bearing: T01 path constant first, then T02 sentinel-write consumer, then T03 cron-filter consumer; planning artifacts (T04) before tests (T05+T06); VERIFICATION (T07) before SUMMARY (T08).

## Decisions Honored

- **D-21 (plugin sentinel + cron settle-window primary, aged-safety-net secondary):** delivered fully. The plugin signals readiness via an empty file at `${MARKERS_READY_DIR}/<sid>` after every `on_session_end` outcome; the cron's session SELECT filter checks sentinel existence first and falls through to the age check (`started_at < now - SETTLE_SECONDS`). The age check is the safety net for plugin-failure cases (uninstalled plugin, plugin crash before sentinel write, gateway-hook legacy installs) — eventually every session reports under D-18 default.
- **D-04 (extended to sentinel write):** every code path in `_write_sentinel` and `_on_session_end` returns None and never raises. The sentinel write itself is wrapped in `try/except Exception → logger.warning → swallow` so a permission error or filesystem-full on the sentinel directory cannot escape `_on_session_end`. The cron's aged-safety-net covers any case where the sentinel fails to land.
- **Scope discipline (CONTEXT.md addendum #3):** the diff is bounded. `classifier.py` gains exactly one line (the `MARKERS_READY_DIR` constant); no helper logic is touched. `__init__.py` gains the `_write_sentinel` helper + two call sites + one import line. `hermes-report.sh` gains the Python heredoc filter + skip-log emission block, all between the existing SELECT and the existing while-loop — every line from the `local reported_count=0` declaration onward is byte-identical. `setup-local.sh`, `references/setup.md`, `SKILL.md`, `split_strategies.py`, `cron.sh`, `task-taxonomy.json`, and the existing 16 HOOK-* test methods are all UNTOUCHED.

## Manual UAT gate

Phase 6 cannot be marked verified until 06-HUMAN-UAT.md G-01, G-02, AND G-03 result move from "failed" to "pass"

Operator runbook (UAT round 4, on the Mac Studio against `gsd/phase-6-uat` once it advances past this commit):

1. Pull `gsd/phase-6-uat` to Mac Studio: `git pull origin gsd/phase-6-uat`.
2. Re-run install (idempotent): `bash examples/setup-local.sh`. Confirm `~/.hermes/state/revenium/markers/.ready/` directory exists with mode 0o700 (or owner-only). It is created automatically by sourcing `common.sh` on first cron invocation; no separate install step required.
3. Restart Hermes gateway: `hermes gateway restart` — confirm the `revenium-classifier` plugin still loads.
4. Drive a substantive turn via CLI: `hermes chat -q "Review src/foo.py for race conditions"`. Confirm:
   - `~/.hermes/state/revenium/markers/<sid>.jsonl` contains a GUARDRAIL+CHAT pair with non-`unclassified` task_type (G-01 + G-02 verification, preserved from UAT round 3).
   - `~/.hermes/state/revenium/markers/.ready/<sid>` exists (sentinel written by the plugin after on_session_end completes).
5. Wait for the next cron tick (~60s); confirm `~/.hermes/state/revenium/revenium-metering.log` shows `revenium meter completion` invoked with `--task-type <meaningful-label>` (NOT `--task-type unclassified`). This retires G-03.
6. (Optional) For the long-running-session edge case: drive a substantive turn that takes > 120s (the settle window). Confirm the cron tick that lands DURING the in-flight session DOES skip with `awaiting plugin sentinel (age=Ns < settle=120s)` log line; confirm the next tick AFTER on_session_end fires DOES ship the meaningful task_type.
7. (Optional) For the plugin-failure edge case: temporarily mis-configure the plugin (e.g., remove from `plugins.enabled` in `~/.hermes/config.yaml`), drive a substantive turn, wait for `started_at + 120s`, confirm the cron eventually reports the session with `--task-type unclassified` (D-18 safety-net default).

Until UAT round 4 records G-03 result = `pass` in `06-HUMAN-UAT.md`: `06-VERIFICATION.md` frontmatter remains `status: requires_rerun_uat`; `re_verification.gaps_remaining` still lists `[G-03]`; Phase 6 Progress Table row stays at `3/4 In progress — G-03 gap closure planned in 06-04-PLAN.md` (NOT `Verified`). The Phase 6 row transitions to `4/4 Verified` only after operator UAT round 4 retires G-03. Note that G-01 + G-02 are already operator-confirmed (UAT round 3, recorded in `06-HUMAN-UAT.md`); they appear in the verbatim UAT-4 gate string above for traceability — UAT round 4 confirms the full chain by retiring the remaining gap.

## Backward compatibility

D-17 + D-18 zero-diff invariants preserved for the pieces this plan does NOT touch. The cron pipeline's downstream logic (the per-marker emission loop, the ledger writes, the equal_split conservation, the transaction-id shape, the cron.lock flock, the fail-open per-session tolerance) is byte-identical. `SKILL.md`, `split_strategies.py`, `cron.sh`, `task-taxonomy.json`, `setup-local.sh`, `references/setup.md`, and the existing 16 HOOK-* test methods are all untouched.

D-18 (no-marker fallthrough → `--task-type unclassified`) STILL applies for aged-no-sentinel sessions — that is the safety-net path. The new D-21 invariant (sentinel + settle-window) LAYERS on top of D-18:
- For sessions WITH a sentinel: cron ships on the very next tick (no settle delay).
- For sessions WITHOUT a sentinel and younger than SETTLE_SECONDS: cron defers (new behavior, prevents the cron-race).
- For sessions WITHOUT a sentinel and aged past SETTLE_SECONDS: cron ships with D-18 default unclassified (legacy behavior preserved).

Existing installs without the plugin (or with the plugin uninstalled) eventually report every session at age >= 120s under the unclassified default — no infinite deferral.

## Self-Check

- [x] All 8 modified files have been edited (common.sh, hermes-report.sh, __init__.py, classifier.py, tests/test_repository.py, REQUIREMENTS.md, ROADMAP.md, 06-VERIFICATION.md)
- [x] 1 new file created (this SUMMARY.md)
- [x] 8 atomic commits landed (T01 through T08, one per task; commit hashes recorded in `## Task Commits` above)
- [x] Full test suite green at every commit boundary (37 tests; 31 pre-existing + 5 new HOOK-13 unit tests + 1 new HOOK-13 end-to-end test)
- [x] `06-VERIFICATION.md` frontmatter `status: requires_rerun_uat` is PRESERVED (the load-bearing gate for Phase 6 verification)
- [x] `06-VERIFICATION.md::re_verification.gaps_remaining: [G-03]` is PRESERVED
- [x] `06-VERIFICATION.md::re_verification.gaps_closed` updated to `[G-01, G-02, G-03]` reflecting code-side closure of G-03
- [x] `_on_session_end` returns None on every code path (D-04 invariant); `_write_sentinel` never raises (D-04 belt extension)
- [x] No logic changes to `classifier.py` beyond the one-line `MARKERS_READY_DIR` constant addition
- [x] No edits to `setup-local.sh`, `references/setup.md`, `SKILL.md`, `split_strategies.py`, `cron.sh`, `task-taxonomy.json`, or HOOK-01..HOOK-12 entry strings (scope discipline)
- [x] No edits to the existing 16 HOOK-* test methods (12 from 06-02 + 4 from 06-03); the existing `test_cron_marker_split_end_to_end` cleanup loops were minimally extended to skip the new `.ready/` subdirectory (Rule 1 deviation — direct collateral from T01's path layout choice; documented above)
- [x] `test_no_legacy_branding_left` passes — no forbidden tokens in any new content
- [x] Manual UAT-4 gate language references G-01, G-02, AND G-03 verbatim per the plan's mandatory string
