---
phase: 06-mechanical-classification-agent-end-hook
plan: 02
subsystem: plugins
tags: [plugins, hermes-cli, on-session-end, universal-coverage, classification, gap-closure, refactor]

# Dependency graph
requires:
  - plan: 06-01-PLAN.md
    provides: Gateway-hook implementation (HOOK.yaml + handler.py + setup-local.sh hook copy + setup.md + 12 HOOK-* tests) that this plan supersedes via D-19 gap closure.
  - phase: 01-path-foundation
    provides: MARKERS_DIR / STATE_DIR / TAXONOMY_FILE path discipline carried through into classifier.py module-level constants.
  - phase: 02-prompt-design-marker-contract
    provides: Marker schema {muid, ts, sid, task_type, operation_type}, LABEL_RE, TRIVIAL_BLOCKLIST, 33-char hex muid recipe — preserved verbatim through the refactor.
  - phase: 03-cron-marker-reader-equal-split-ledger-v2
    provides: parse_prior_state + S2 equal-split cron pipeline — consumes plugin-written markers identically to hook-written markers.
provides:
  - "Universal session coverage — on_session_end fires for every run_conversation() exit (gateway-served + CLI + interactive + ACP + cron-spawned)"
  - "Shared classifier module factored from handler.py — single source of truth for D-04..D-14 + D-05..D-09 invariants"
  - "Plugin distribution via setup-local.sh: cp -R + idempotent plugins.enabled YAML edit using a stdlib-only Python heredoc"
  - "ROADMAP Phase 6 SC1/SC2/SC6 wording updated to plugin paths, on_session_end event, and register(ctx) entry point"
  - "HOOK-11 requirement establishing the universal-coverage invariant"
affects: [phase-04-wire-enrichment, phase-05-housekeeping, hermes-uat]

# Tech tracking
tech-stack:
  added:
    - "Hermes hermes_cli plugin bus (on_session_end event from run_agent.py:15164)"
    - "Plugin manifest format (plugin.yaml: name, version, description, hooks) per hermes-agent/plugins/disk-cleanup/ reference"
  removed:
    - "Hermes gateway event-hook bus binding for revenium-classifier specifically (the bus itself remains in Hermes for other consumers; we just no longer register against it)"
  patterns:
    - "Plugin entrypoint: __init__.py exports register(ctx) calling ctx.register_hook(name, sync_callback); sync callback uses asyncio.run() internally to drive the shared async pipeline"
    - "Shared-module-for-tests refactor: factor handler.py → classifier.py BEFORE deleting the gateway-hook tree to keep every per-task commit green"
    - "Idempotent YAML edit via stdlib-only Python heredoc (regex-based; no PyYAML) per CLAUDE.md Python Heredocs Inside Bash"
    - "Alias-import test migration: `import classifier as handler` lets 12 HOOK-* test methods migrate with one-line-per-method edits"

key-files:
  created:
    - "skills/revenium/plugins/revenium-classifier/plugin.yaml"
    - "skills/revenium/plugins/revenium-classifier/__init__.py"
    - "skills/revenium/plugins/revenium-classifier/classifier.py"
    - "skills/revenium/plugins/revenium-classifier/test-payloads/trivial-turn.json"
    - "skills/revenium/plugins/revenium-classifier/test-payloads/substantive-turn.json"
    - "skills/revenium/plugins/revenium-classifier/test-payloads/subagent-turn.json"
    - ".planning/phases/06-mechanical-classification-agent-end-hook/06-02-SUMMARY.md"
  modified:
    - ".planning/REQUIREMENTS.md"
    - ".planning/ROADMAP.md"
    - ".planning/phases/06-mechanical-classification-agent-end-hook/06-VERIFICATION.md"
    - "examples/setup-local.sh"
    - "skills/revenium/references/setup.md"
    - "tests/test_repository.py"
  deleted:
    - "skills/revenium/hooks/revenium-classifier/HOOK.yaml"
    - "skills/revenium/hooks/revenium-classifier/handler.py"
    - "skills/revenium/hooks/revenium-classifier/test-payloads/trivial-turn.json"
    - "skills/revenium/hooks/revenium-classifier/test-payloads/substantive-turn.json"
    - "skills/revenium/hooks/revenium-classifier/test-payloads/subagent-turn.json"

key-decisions:
  - "D-19 (locked in 06-CONTEXT.md gap-closure addendum): replace agent:end gateway hook with hermes_cli on_session_end plugin — the event bus that covers every run_conversation() exit, not just platform-served sessions."
  - "Single-fire invariant: do NOT keep both mechanisms (would require dedup). on_session_end fires for gateway-served sessions through run_conversation() as well, so deleting the gateway hook does NOT lose coverage."
  - "Shared module refactor before deletion: classifier.py is added first (T01), tests migrate (T05), then the gateway-hook tree is deleted (T08). Every per-task commit leaves the full test suite green."
  - "examples/setup-local.sh adds revenium-classifier to plugins.enabled idempotently via a stdlib-only Python heredoc; PyYAML is forbidden by CLAUDE.md so we use regex-based YAML manipulation handling all five edge cases (file missing, plugin already enabled, plugins: missing, enabled: missing, both present)."

patterns-established:
  - "Plugin entrypoint pattern: relative import `from .classifier import run_classification`, sync `_on_session_end(**kwargs)` with D-04 try/except belt, `register(ctx)` with no try/except so registration failure surfaces to the plugin manager."
  - "Shared module + alias-import test migration: `import classifier as handler` lets the existing 12 HOOK-* test methods migrate with one-line-per-method edits to the import + a body edit only at handler.handle() call sites."
  - "Patching the dynamically-loaded plugin's classifier submodule (sys.modules[f'{mod_name}.classifier']) rather than the bare classifier module — necessary because the plugin's `from .classifier import` creates a fresh submodule under the plugin package namespace."

requirements-completed: [HOOK-01, HOOK-02, HOOK-03, HOOK-04, HOOK-05, HOOK-06, HOOK-07, HOOK-08, HOOK-09, HOOK-10, HOOK-11]

# Metrics
duration: ~15min
completed: 2026-05-14
---

# Phase 06 Plan 02: Gap-closure — on_session_end plugin Summary

**In-process hermes_cli plugin registered on `on_session_end` that writes the GUARDRAIL+CHAT marker pair for every `run_conversation()` exit — universal session coverage closing G-01 from the Mac Studio UAT.**

## Performance

- **Duration:** ~15 min
- **Tasks:** 10 (T01–T10)
- **Commits:** 10 (one per task)
- **Files created:** 7 (plugin.yaml + __init__.py + classifier.py + 3 fixtures + this SUMMARY.md)
- **Files modified:** 6 (REQUIREMENTS.md, ROADMAP.md, 06-VERIFICATION.md, setup-local.sh, setup.md, test_repository.py)
- **Files deleted:** 5 (gateway hook tree — HOOK.yaml + handler.py + 3 test-payloads)

## Accomplishments

- Hermes lifecycle PLUGIN at `skills/revenium/plugins/revenium-classifier/` with `plugin.yaml` + `__init__.py` + `classifier.py` matching the `hermes-agent/plugins/disk-cleanup/` reference shape.
- `register(ctx)` exports the plugin's single mandatory entry point; calls `ctx.register_hook("on_session_end", _on_session_end)`.
- `_on_session_end(*, session_id, completed, interrupted, model=None, platform=None, **kwargs)` is synchronous (per Hermes plugin contract), dispatches into the shared `classifier.run_classification(session_id=..., model=..., platform=...)`, and wraps the whole body in a try/except → `logger.warning` (D-04 belt at the plugin boundary).
- Shared `classifier.py` module factored byte-for-byte from `handler.py` carrying every D-04..D-14 + D-05..D-09 helper: `_walk_to_root_session`, `_count_tools_in_current_turn`, `_read_latest_task_type`, `_recent_marker_pair_exists`, `_budget_halted`, `_read_taxonomy_labels`, `_build_classification_prompt`, `_classify_via_llm`, `_validate_label`, `_muid`, `_write_marker_pair`. New public coroutine `run_classification_async(session_id, model, platform, message, response)` carries the D-04 pipeline; sync wrapper `run_classification` drives it via `asyncio.run()` with its own D-04 belt.
- Universal coverage (HOOK-11): `on_session_end` is emitted from `hermes-agent/run_agent.py:15164` for EVERY `run_conversation()` exit — gateway-served (Telegram/Discord/Slack/WhatsApp/Webhook), CLI one-shot (`hermes chat -q`), interactive `hermes chat`, ACP integrations, AND gateway-internal cron-ticker sessions. The previous `agent:end` gateway-hook (only fired for platform-served sessions per `hermes-agent/gateway/run.py:7631`) is superseded.
- `examples/setup-local.sh` installs the plugin into `~/.hermes/plugins/revenium-classifier/` and idempotently adds `revenium-classifier` to `plugins.enabled` in `~/.hermes/config.yaml` using a stdlib-only Python heredoc (no `import yaml`, regex-based YAML manipulation handling 5 edge cases). Old hook-install block is fully removed; bulk-copy `${TARGET_DIR}/hooks` prune is kept so a stale tree from a re-installed skill does not linger.
- `skills/revenium/references/setup.md` `## Mechanical classification hook` section rewritten: plugin path, universal-coverage explanation (gateway + CLI + ACP + interactive + cron), plugin-manager startup log verification, filesystem checks for plugin.yaml + __init__.py + classifier.py, preserved `Do NOT use hermes hooks list` anti-pattern callout, added migration note for operators with stale `~/.hermes/hooks/revenium-classifier/` trees.
- Test suite: 26 → 27 (1 new HOOK-11 test); all 12 pre-existing HOOK-* test methods migrated to `import classifier as handler`; new `test_revenium_classifier_plugin_entrypoint` test pins the universal-coverage invariant by loading the plugin package via `importlib.util.spec_from_file_location` (the same shape Hermes' plugin manager uses), invoking `register(ctx)` against a stub ctx, and asserting that the registered `on_session_end` callback drives the full classification pipeline and writes a GUARDRAIL+CHAT marker pair with `task_type=code_review`.
- `.planning/REQUIREMENTS.md` adds HOOK-11 + traceability row + Coverage 47 → 48. `.planning/ROADMAP.md` Phase 6 Requirements line appends HOOK-11; SC1 / SC2 / SC6 wording updated to plugin paths + plugin-manager log line + `register(ctx)` invocation; Categories HOOK (10) → HOOK (11); Plans list adds `06-02-PLAN.md`; Progress Table row moves from `1/1 Gaps found` → `1/2 In progress — G-01 gap closure planned`.
- `06-VERIFICATION.md` frontmatter status moves from `gaps_found` → `requires_rerun_uat`; `gap_closure_plan: 06-02-PLAN.md` pointer added at top level AND on G-01's entry; `re_verification.gaps_remaining` still lists `[G-01]` (gap is closed only after operator re-UAT moves G-01 result from `failed` to `pass` in `06-HUMAN-UAT.md`); `human_verification[0]` rewritten to plugin shape; new `### Gap closure (added 2026-05-13 post-UAT)` section documents D-19 + the 12-vs-6 test-count note.

## Task Commits

Each task was committed atomically; every commit leaves `python3 -m unittest discover -s tests -p 'test_*.py'` green.

1. **T01: Add shared classifier.py module + 3 test fixtures** — `ea6a1b7` (feat)
2. **T02: Add plugin __init__.py with register(ctx) → on_session_end** — `a4b38ce` (feat)
3. **T03: Add plugin.yaml manifest** — `54d48d0` (feat)
4. **T04: Add HOOK-11 to REQUIREMENTS.md + ROADMAP.md Phase 6 updates** — `5e7d225` (docs)
5. **T05: Migrate 12 HOOK-* tests + add HOOK-11 plugin entrypoint test** — `6f25f13` (test)
6. **T06: Update setup-local.sh — plugin install + plugins.enabled idempotent YAML edit** — `f8f0d6c` (chore)
7. **T07: Rewrite Mechanical classification hook section in setup.md + update test path assert** — `18752ea` (docs)
8. **T08: Delete agent:end gateway hook tree (HOOK.yaml + handler.py + 3 fixtures)** — `7390761` (feat!)
9. **T09: Mark G-01 gap closure planned in 06-VERIFICATION.md** — `c1c007b` (docs)
10. **T10: This SUMMARY.md** — lands with the metadata commit.

## Decisions Honored

- **D-19** (locked, 06-CONTEXT.md gap-closure addendum): replaced `agent:end` gateway hook with `hermes_cli` on_session_end plugin — covers every `run_conversation()` exit.
- **D-04..D-18** (from plan 06-01): every existing invariant is preserved through the refactor. The classifier helpers move file-to-file but their I/O patterns are byte-identical. D-17 (SKILL.md unchanged) and D-18 (Phase 3 cron pipeline unchanged) hold by inspection.
- **Single-fire invariant** (CONTEXT.md addendum): we DELETED the gateway hook rather than keeping both, because keeping both would have required a dedup contract — and `on_session_end` already fires for gateway-served sessions via `run_conversation()` so coverage is preserved.
- **CLAUDE.md compliance**: examples/setup-local.sh uses a stdlib-only Python heredoc (no `import yaml`) for the `plugins.enabled` YAML edit. Path discipline is maintained — classifier.py declares env-var-overridable path constants mirroring scripts/common.sh, same shape as the old handler.py.
- **Legacy branding clean**: every new and edited file passes `test_no_legacy_branding_left`.

## Deviations from Plan

None — the plan executed as written. One small implementation note worth recording for the retro: the HOOK-11 plugin-entrypoint test had to patch `call_llm` on `sys.modules[f'{mod_name}.classifier']` (the plugin's dynamically-loaded classifier submodule) rather than on the bare `classifier` module the rest of the tests use. This is because the plugin's `from .classifier import run_classification` creates a NEW classifier submodule under the plugin package namespace, distinct from the bare classifier module already in `sys.modules`. Both submodules read the same env-var-driven path constants so they write to the same tmp `MARKERS_DIR`, which is why the assertion `handler.MARKERS_DIR / f'{sid}.jsonl'` correctly finds the marker file. The plan flagged this as a "Patching pattern" in the patterns-established frontmatter.

## Issues Encountered

- The legacy-branding test failed before T05 from outside the worktree (running `python3 -m unittest discover` from the main repo cwd resolved `ROOT = Path(__file__).resolve().parents[1]` to the WORKTREE root because the test file lives in the worktree, but `rglob` from that ROOT descended into NESTED worktrees under `.claude/worktrees/`). From inside the worktree's own cwd the test passes correctly. This is a worktree-isolation artifact, not a code bug; per-commit verification ran from the worktree cwd as required.

## Manual UAT gate

**Phase 6 cannot be marked verified until 06-HUMAN-UAT.md G-01 result moves from `failed` to `pass` — operator action required.**

After this plan lands, operator must re-run UAT on Mac Studio (172.16.1.175) against `gsd/phase-6-uat` with the new plugin:

1. `bash examples/setup-local.sh` — confirm it reports `Installed plugin to ~/.hermes/plugins/revenium-classifier` AND idempotently adds `revenium-classifier` to `plugins.enabled` in `~/.hermes/config.yaml` (re-run produces no duplicate entry).
2. `hermes gateway restart` — confirm the plugin-manager startup log shows the plugin loader picking up `revenium-classifier` (exact log-line shape to be captured during re-UAT and recorded into `06-HUMAN-UAT.md`).
3. Drive a substantive turn via CLI (`hermes chat -q "Review src/foo.py for race conditions"`) WITHOUT loading the revenium skill or executing FINAL ACTION. Confirm `~/.hermes/state/revenium/markers/<sid>.jsonl` contains a GUARDRAIL+CHAT marker pair with a non-`unclassified` `task_type`.
4. Also drive a Telegram message (gateway-served path) and confirm the same marker shape lands.
5. Wait for the next cron tick (~60s); confirm `revenium meter completion` is invoked with `--task-type <meaningful-label>` (not `unclassified`).

Until that operator UAT records G-01 result = `pass`:
- `06-VERIFICATION.md` frontmatter remains `status: requires_rerun_uat`.
- `re_verification.gaps_remaining` still lists `[G-01]`.
- The Phase 6 ROADMAP row stays at `1/2 In progress — G-01 gap closure planned in 06-02-PLAN.md` (NOT `Verified`).

The Phase 6 row in the ROADMAP Progress Table transitions to `2/2 Verified` only after the operator UAT moves G-01 from `failed` to `pass`.

## Backward compatibility

- **D-17 (SKILL.md FINAL ACTION block unchanged):** zero-diff invariant preserved — this plan only touches the plugin tree, setup-local.sh, setup.md, tests, REQUIREMENTS.md, ROADMAP.md, VERIFICATION.md, and this SUMMARY.md.
- **D-18 (Phase 3 cron pipeline unchanged):** zero-diff invariant preserved — hermes-report.sh, split_strategies.py, cron.sh, common.sh, task-taxonomy.json are all untouched. The plugin writes markers in the same Phase 2 schema the existing cron consumes.
- **Operator legacy state:** if an operator installed plan 06-01 first and now installs this plan, the stale `~/.hermes/hooks/revenium-classifier/` directory remains on disk after `setup-local.sh` runs. It is harmless under the new plugin (gateway loads it but `agent:end` from the hook bus never dispatches to it once the on_session_end plugin handles the markers). Documented in setup.md migration note; operators may delete manually if they wish.

## Open Questions Surfaced for Retro

- **A1 (re-UAT log-line shape):** the exact Hermes plugin-manager startup log line for `revenium-classifier` is to be captured by the operator during re-UAT. The plan's `human_verification[0].expected` field intentionally leaves this as "exact log-line shape to be confirmed during re-UAT" rather than asserting a specific string we have not observed.
- **A2 (plugin-manager unhealthy-marking semantics):** if a plugin raises during `register(ctx)` or during a callback Hermes may mark it unhealthy on the next restart. The D-04 belts in `_on_session_end` AND in `run_classification` AND in `run_classification_async` should make this impossible in practice; surface to retro if the re-UAT ever shows the plugin in an unhealthy state.

## Next Phase Readiness

- **Phase 4 (Wire Enrichment):** ready — Phase 6 does not block. Phase 4's WIRE-01..WIRE-04 land on the cron side; Phase 6 produces markers the same cron pipeline consumes.
- **Phase 5 (Housekeeping):** ready — Phase 6 produces marker files just like Phase 2 SKILL.md FINAL ACTION did, so prune-markers.sh (the Phase 5 deliverable) will treat plugin-written markers identically.

## Self-Check: PASSED

Verified before write:

- All 9 prior commits present in `git log 3b64064..HEAD`: ea6a1b7, a4b38ce, 54d48d0, 5e7d225, 6f25f13, f8f0d6c, 18752ea, 7390761, c1c007b — FOUND.
- All 6 created files present in worktree: plugin.yaml, __init__.py, classifier.py, trivial-turn.json, substantive-turn.json, subagent-turn.json — FOUND.
- All 6 modified files present and committed: REQUIREMENTS.md, ROADMAP.md, 06-VERIFICATION.md, setup-local.sh, setup.md, test_repository.py — FOUND.
- All 5 deleted files removed: skills/revenium/hooks/revenium-classifier/{HOOK.yaml, handler.py, test-payloads/*.json} — REMOVED.
- Empty parent dir skills/revenium/hooks also removed — REMOVED.
- Test suite green: 27 tests run, OK status — VERIFIED.
- D-17 / D-18 zero-diff invariants: SKILL.md, hermes-report.sh, split_strategies.py, cron.sh, common.sh, task-taxonomy.json — unchanged vs. base 3b64064.

---
*Phase: 06-mechanical-classification-agent-end-hook*
*Completed: 2026-05-14*
