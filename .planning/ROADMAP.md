# Roadmap: Hermes-Revenium Task-Type Metering

**Created:** 2026-05-12
**Granularity:** coarse
**Mode:** standard (Horizontal Layers — strict phase ordering enforced by PITFALLS research)
**Project:** Brownfield extension to the `revenium` Hermes skill adding per-turn task attribution.

Every metered completion that leaves this skill carries an accurate, consistently-spelled `--task-type` so Revenium analytics group spend by what the agent actually did, not just by session.

## Phases

- [x] **Phase 1: Path Foundation** - Declare `TAXONOMY_FILE` and `MARKERS_DIR` in `common.sh`; create directory with `chmod 700`; extend path-discipline test. (2026-05-12)
- [x] **Phase 2: Prompt Design & Marker Contract** - End-load the SKILL.md classification block, seed taxonomy, define marker schema; ship BEFORE any cron behavior changes to bound halt-check regression risk. (2026-05-12)
- [x] **Phase 3: Cron Marker Reader + Equal-Split + Ledger v2** - One coherent migration: marker-aware split path, extended `--transaction-id`, 5-field ledger row, `flock(2)` lockfile, pluggable split strategy. Partial adoption breaks idempotency. (2026-05-13)
- [ ] **Phase 4: Wire Enrichment** - Source `--operation-type` / `--agent` / `--trace-id` from marker fields; preserve provider inference for every split call.
- [ ] **Phase 5: Housekeeping & Compat Hardening** - Marker file pruning, backward-compat regression tests, end-to-end test fixtures. Operational hygiene with no functional dependency.
- [ ] **Phase 6: Mechanical Classification via Hermes agent:end Hook** - Replace soft prompt enforcement of FINAL ACTION with a Hermes lifecycle hook that classifies every turn and writes the marker file mechanically. Subagents inherit parent task_type via state.db `parent_session_id`. LLM-assisted classification using the budgeted model. Surfaced by Phase 3 UAT on the Mac Studio — agent-side adoption of the Phase 2 closing-discipline pattern is unreliable in Hermes' lazy-skill-loading + delegate_task subagent architecture. (G-01 architecturally closed by 06-02-PLAN.md; UAT round 2 surfaced G-02 — substance heuristic mis-classifies CLI turns as trivial when ~/.hermes/sessions/<sid>.jsonl is absent. Phase pending 06-03 gap-closure + re-UAT; gap closure in 06-03-PLAN.md rewrites _count_tools_in_current_turn to use state.db.sessions.tool_call_count)

## Phase Details

### Phase 1: Path Foundation
**Goal**: Every later phase can resolve marker and taxonomy paths from `common.sh` alone — no script inlines them and the path-discipline test continues to fail any drift.
**Depends on**: Nothing (first phase).
**Requirements**: PATH-01, PATH-02, PATH-03
**Success Criteria** (what must be TRUE):
  1. Running any installed script that sources `common.sh` resolves `TAXONOMY_FILE` to `~/.hermes/state/revenium/task-taxonomy.json` and `MARKERS_DIR` to `~/.hermes/state/revenium/markers` without inlining either path elsewhere.
  2. `examples/setup-local.sh` (or the install path it invokes) creates `MARKERS_DIR` with mode 700 on a fresh install; `stat -f %A` (macOS) or `stat -c %a` (Linux) confirms `700` on the directory.
  3. `python3 -m unittest tests.test_repository.RepositoryTests.test_runtime_paths_are_hermes_native` passes with the extended assertions on `task-taxonomy.json` and `markers` substrings in `common.sh`.
  4. No behavior change observable from a Hermes session or a cron run — pre-existing `hermes-report.sh` / `budget-check.sh` flows continue to ship token deltas and write `budget-status.json` exactly as before.
**Plans**: 1 plan

Plans:
- [x] 01-01-PLAN.md — Declare TAXONOMY_FILE and MARKERS_DIR in common.sh, chmod 700 MARKERS_DIR in install-cron.sh, extend test_runtime_paths_are_hermes_native (PATH-01, PATH-02, PATH-03)

### Phase 2: Prompt Design & Marker Contract
**Goal**: A Hermes session loaded with the updated skill (a) still emits the verbatim halt string in response to a halted budget within long sessions, and (b) appends well-formed marker lines to `~/.hermes/state/revenium/markers/<sid>.jsonl` for substantive turns, with one GUARDRAIL marker per classification turn.
**Depends on**: Phase 1
**Requirements**: TAX-01, TAX-02, TAX-03, TAX-04, MARK-01, MARK-02, MARK-03, MARK-05, PROMPT-01, PROMPT-02, PROMPT-03, PROMPT-04, PROMPT-05, PROMPT-06, PROMPT-07, TEST-01, TEST-02
**Success Criteria** (what must be TRUE):
  1. In a Hermes session at representative long context length (~10K tokens of prior turns) with `budget-status.json` set to `halted: true`, the agent emits the contractual halt string verbatim on the next operation — confirmed by manual end-to-end test plan recorded in `references/halt-survivability.md`.
  2. After a representative substantive turn (e.g., a code-review request with tool calls), running `cat ~/.hermes/state/revenium/markers/<sid>.jsonl` shows exactly two new lines (one GUARDRAIL classification marker, one CHAT work marker), each < 1024 bytes, each parseable as JSON with only the allow-listed keys `{muid, ts, sid, task_type, operation_type}` plus optional `{turn_seq, agent, trace_id, model}`.
  3. The seed `task-taxonomy.json` ships with 6-8 starting labels, every key matches `^[a-z][a-z0-9_]{1,47}$`, and `python3 -m unittest tests.test_repository` invariant tests for taxonomy and marker schema (TEST-01, TEST-02) pass on the checked-in fixtures.
  4. A prompt-invariant test (PROMPT-07) reading the updated `SKILL.md` confirms the existing halt-block phrasing (`ABSOLUTE FIRST — NON-NEGOTIABLE` or the agreed equivalent) still appears before the new classification block.
  5. Concurrent agent writes to the taxonomy file under `fcntl.flock` produce no partial-read states observable to a separate reader process — verified by a synthetic write-while-read fixture.
**Plans**: 3 plans
**Research needed**: Manual long-session halt-check survivability E2E test plan is authored as part of plan 02-02 (`skills/revenium/references/halt-survivability.md`) before plan 02-03 lands the SKILL.md prompt edit.

Plans:
- [x] 02-01-PLAN.md — Seed taxonomy fixture + references/task-taxonomy.md cold-path doc + install-time copy in setup-local.sh + TEST-02 (TAX-01, TAX-02, TAX-03, TAX-04, PROMPT-06, TEST-02)
- [x] 02-02-PLAN.md — Marker schema TEST-01 + references/halt-survivability.md E2E runbook (MARK-01, MARK-02, MARK-03, MARK-05, TEST-01)
- [x] 02-03-PLAN.md — Append `## FINAL ACTION — TASK CLASSIFICATION` to SKILL.md (4 examples + blocklist + canonical marker-write Python snippet) + PROMPT-07 prompt-invariant test + HERMES_SESSION_ID resolution (PROMPT-01, PROMPT-02, PROMPT-03, PROMPT-04, PROMPT-05, PROMPT-07)

### Phase 3: Cron Marker Reader + Equal-Split + Ledger v2
**Goal**: When the cron runs against a session that has N markers since the previous ledger row, it emits N `revenium meter completion` calls whose per-field token splits sum exactly to the session delta, with marker-aware idempotency surviving any partial multi-call failure.
**Depends on**: Phase 2 (must ship after the prompt change so any halt-check regression is unambiguously attributable to the prompt, not to cron behavior changes — load-bearing PITFALLS constraint).
**Requirements**: TAX-05, MARK-04, CRON-01, CRON-02, CRON-03, CRON-04, CRON-05, CRON-06, CRON-07, CRON-08, CRON-09, COMPAT-02, COMPAT-03, TEST-03, TEST-04
**Success Criteria** (what must be TRUE):
  1. Running `hermes-report.sh` against a synthetic `state.db` plus N markers (for N in {1, 2, 5, 10}) emits exactly N `revenium meter completion` calls, each carrying the per-marker `--task-type`, `--operation-type`, and `--transaction-id ${sid}-${total_tokens}-${muid}`; the sum of `input/output/cache_read/cache_write/total/cost` across the N calls equals the input delta byte-for-byte (conservation test TEST-03 / COMPAT-02).
  2. Killing the cron between meter call 3 and call 5 of a 5-marker batch and re-running on the next tick re-emits exactly markers 4 and 5 (using their unique `muid`-extended transaction-ids), never re-emits markers 1-3, and never loses markers 4-5 — confirmed by per-call ledger-line audit fixture (COMPAT-03, Pitfall 8).
  3. Running the cron against a session with zero markers in the window emits exactly one `revenium meter completion` call whose argv differs from the legacy single-call path only by the addition of `--task-type unclassified` — verified by snapshot-diff test (CRON-07).
  4. Overlapping cron ticks: starting a second `cron.sh` while the first is still running causes the second to exit cleanly with a `prior tick still active` log line and never appends to the ledger — confirmed via `flock(2)` lockfile test on `~/.hermes/state/revenium/cron.lock` (CRON-08).
  5. A synthetic S2-bias test fixture (small classification turn + large work turn) shows the documented 50/50 attribution and the cron emits a `classification-dominated window` warning to the log — the bias direction is pinned by the test, not hidden (TEST-04, Pitfall 5).
**Plans**: 1 plan (single fat plan locked by D-01; load-bearing per PITFALLS Pitfall 8)
**Research needed**: Before planning begins, use the `manage_metering` MCP tool to verify Revenium server-side `--operation-type` default behavior. If the absence of `--operation-type` differs in cost from explicit `CHAT`, WIRE-01 will require a release-note migration path (per SUMMARY.md research flag). [RESOLVED in 03-RESEARCH.md Summary point 4 — Phase 3 does NOT add a default; Phase 4 (WIRE-01) owns that decision.]

Plans:
- [x] 03-01-PLAN.md — Single fat plan: split_strategies.py + LOCK_FILE in common.sh + hermes-report.sh marker reader + per-marker emission + v2 ledger writes + extended transaction-id + zero-marker fallthrough + fail-open per-session tolerance + cron.sh fcntl flock + references/setup.md S2 bias framing + TEST-03 conservation + TEST-04 bias pinning + ledger v1/v2 discrimination (TAX-05, MARK-04, CRON-01, CRON-02, CRON-03, CRON-04, CRON-05, CRON-06, CRON-07, CRON-08, CRON-09, COMPAT-02, COMPAT-03, TEST-03, TEST-04)

### Phase 4: Wire Enrichment
**Goal**: Each split metering call carries the richest `--operation-type`, `--agent`, and `--trace-id` available from the marker, with a documented, conservative fallback to today's hardcoded values; provider inference and cost scaling never regress across any split call.
**Depends on**: Phase 3 (markers must be flowing in real cron traffic before adjacent-flag enrichment is observable).
**Requirements**: WIRE-01, WIRE-02, WIRE-03, WIRE-04, COMPAT-01
**Success Criteria** (what must be TRUE):
  1. Running the cron against a marker that includes `{agent: "code-review-skill", trace_id: "<sid>:17"}` produces a `revenium meter completion` invocation whose `--agent` and `--trace-id` flags carry those values; a marker that omits those fields produces a call with `--agent "Hermes"` and `--trace-id "${sid}"` (backward-compatible defaults).
  2. Non-guardrail markers default to `--operation-type CHAT`; this default is shipped only after Phase 3's `manage_metering` verification confirms no server-side cost-calculation change (gate from WIRE-01).
  3. Each split call carries the same provider/model/source values the legacy single-call path would have used — verified by running a multi-provider fixture (Anthropic, OpenRouter→Anthropic, Bedrock→Claude) and asserting the inferred `--provider` and `--model` flags match the legacy argv for every split (WIRE-04).
  4. A byte-by-byte argv diff between the pre-Phase-4 and post-Phase-4 no-marker fallthrough path shows zero differences except the previously-established `--task-type unclassified` addition — backward compat regression test (COMPAT-01).
**Plans**: TBD

### Phase 5: Housekeeping & Compat Hardening
**Goal**: Marker files do not grow unbounded on long-running hosts, the project's compat invariants are pinned by automated tests, and the frontmatter / legacy-branding / runtime-path guards continue to pass.
**Depends on**: Phase 4 (operational hygiene depends on markers being fully wired and flowing).
**Requirements**: COMPAT-04, TEST-05
**Success Criteria** (what must be TRUE):
  1. Running `bash ~/.hermes/skills/revenium/scripts/prune-markers.sh` (added in this phase) against a fixture with marker files whose latest-reported ledger row is older than N days removes those files and leaves files for active sessions untouched; behavior is idempotent across repeated runs.
  2. `python3 -m unittest discover -s tests -p 'test_*.py' -v` passes end-to-end on the repository as shipped at the end of this phase, including `test_skill_frontmatter_has_hermes_metadata`, `test_runtime_paths_are_hermes_native`, `test_no_legacy_branding_left`, and `test_shell_scripts_have_valid_syntax` (COMPAT-04, TEST-05).
  3. `docs/installation.md` and `references/setup.md` describe the new marker / taxonomy contract, the S2 bias direction (GUARDRAIL share is an upper bound), and the `prune-markers.sh` operator invocation; no new docs reintroduce any string forbidden by `test_no_legacy_branding_left`.
**Plans**: TBD

### Phase 6: Mechanical Classification via Hermes agent:end Hook
**Goal**: When a Hermes session — primary or subagent — completes a turn, a Hermes lifecycle hook deterministically writes a marker record at `~/.hermes/state/revenium/markers/<sid>.jsonl` with a meaningful `task_type` and `operation_type`, independent of whether the agent loaded the `revenium` skill or executed the FINAL ACTION self-classification code. Token attribution by activity in Revenium becomes observable without depending on agent compliance.
**Depends on**: Phase 3 (cron-side marker reader must exist for hook-written markers to flow to Revenium). Independent of Phase 4 and Phase 5 — can ship in parallel.
**Requirements**: HOOK-01, HOOK-02, HOOK-03, HOOK-04, HOOK-05, HOOK-06, HOOK-07, HOOK-08, HOOK-09, HOOK-10, HOOK-11, HOOK-12
**Success Criteria** (what must be TRUE):
  1. `~/.hermes/plugins/revenium-classifier/` exists with `plugin.yaml` declaring at least `on_session_end` and `__init__.py` exposing `def register(ctx)` — discovery and load succeed under direct filesystem inspection (`test -f`) AND the Hermes plugin-manager startup log shows the plugin-load line (reference shape: `hermes-agent/plugins/disk-cleanup/` at startup).
  2. After a fresh substantive Hermes session that the agent does NOT manually classify, the next cron tick reports the session's tokens to Revenium with a meaningful `--task-type` (not `unclassified`) — proven by an end-to-end fixture that exercises `register(ctx)` and the synchronous `on_session_end` callback with a synthetic context and asserts a marker file appears at the expected path. Covers every session source (gateway-served, CLI one-shot, interactive, ACP, cron) because `on_session_end` is emitted from `run_agent.py` for every `run_conversation()` invocation, not from the gateway-specific `agent:end` emit site. Specifically covers sessions without per-session JSONL (CLI one-shot, ACP, cron) — verified by an end-to-end test that creates a state.db row with `tool_call_count > 0` and NO `~/.hermes/sessions/<sid>.jsonl`, then asserts the classifier writes a marker file with a non-`unclassified` `task_type`.
  3. For a subagent session with `parent_session_id != NULL` in state.db, the marker file's `task_type` matches the parent's `task_type` — verified by a synthetic two-session fixture where the parent is classified first and the child inherits, recorded as an integration test.
  4. The classifier consults the budgeted LLM for substantive turns AND is bounded by Revenium's halt-check: if `budget-status.json` shows `halted: true` the plugin skips the LLM call and writes `task_type: unclassified` with a `WARN` log line. No silent budget overrun from the classifier itself.
  5. `python3 -m unittest discover -s tests -p 'test_*.py' -v` passes including new tests for the classifier (heuristic skip-fast-path on trivial turns, LLM call invocation contract, parent_session_id inheritance via state.db join). No regressions in existing Phase 1-3 tests.
  6. `bash examples/setup-local.sh` installs the plugin into `~/.hermes/plugins/revenium-classifier/` AND adds `revenium-classifier` to `~/.hermes/config.yaml::plugins.enabled` — distribution mechanism is operator-discoverable from `references/setup.md`.
**Plans**: 3 plans (06-01 ships the original gateway-hook implementation, 06-02 closes G-01 with the hermes_cli plugin migration, 06-03 closes G-02 with the state.db tool-count source-of-truth swap)

Plans:
- [x] 06-01-PLAN.md — Single fat plan: HOOK.yaml + handler.py with subagent-inherit + heuristic-skip + budget-halt + LLM-classify + atomic marker pair write + D-13 dedupe + setup-local.sh hook copy + setup.md docs + 6 unittest methods + 3 synthetic agent:end fixtures (HOOK-01..HOOK-10)
- [x] 06-02-PLAN.md — Gap closure: factor classifier into shared module, add on_session_end plugin (plugin.yaml + __init__.py), delete agent:end gateway hook, migrate setup-local.sh + tests + setup.md, add HOOK-11 (HOOK-01..HOOK-10 carried, HOOK-11 added)
- [ ] 06-03-PLAN.md — Gap closure: rewrite _count_tools_in_current_turn to query state.db.sessions.tool_call_count first (universal source — populated for every session source) with JSONL fallback; add 3 unit tests + 1 end-to-end test; add HOOK-12 (HOOK-01..HOOK-11 carried, HOOK-12 added)
**Locked decisions (from UAT discussion 2026-05-13)**:
  - Subagent task_type inheritance: walk `state.db.sessions.parent_session_id` to the root user-facing parent; subagent inherits the root's task_type. Single classification per request lineage.
  - Classifier: LLM-assisted using the Revenium-budgeted model. Heuristic fast-paths for trivial turns (≤ 2 sentences AND zero tools = skip). Budget halt gates the LLM call.
**Research needed**:
  - Hermes hook payload schema for `agent:end` (what fields `context` carries — session_id, message history, tool calls). Inspect `hermes-agent/gateway/hooks.py` for HookRegistry.emit() callers.
  - Hook distribution mechanism: does `hermes skills install` already copy hooks from a skill's `hooks/` subdirectory? Or do they need explicit installation?
  - Subagent transcript availability — is `~/.hermes/sessions/<subagent_sid>.jsonl` always written, or only for some subagent types?
  - LLM call from within a hook handler — what async API surface does the hook get? Direct `httpx` to the provider, or a Hermes-internal helper?

## Phase Dependencies

```
Phase 1 (Path Foundation)
   │
   ▼
Phase 2 (Prompt Design & Marker Contract)   ← MUST ship before Phase 3 (halt-check regression risk)
   │
   ▼
Phase 3 (Cron Marker Reader + Equal-Split + Ledger v2)   ← ONE coherent migration
   │
   ├──────────────────────────────────┐
   ▼                                  ▼
Phase 4 (Wire Enrichment)         Phase 6 (Mechanical Classification via agent:end hook)
   │                                  │   ← unblocked by Phase 3; can ship in parallel
   ▼                                  │   with Phase 4 / Phase 5; required for end-user
Phase 5 (Housekeeping)                │   observability of taskType attribution
   │                                  │
   └──────────────────────────────────┘
```

The hard ordering constraint (PITFALLS HIGH severity): Phase 2 ships before Phase 3 so any halt-check regression after the new prompt content is unambiguously attributable to the prompt change rather than to concurrent cron behavior changes. Phase 3 lands as one coherent migration because partial adoption (split path without per-marker ledger lines, or new ledger without conservation test) breaks the load-bearing idempotency invariant.

## Progress Table

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Path Foundation | 1/1 | Complete | 2026-05-12 |
| 2. Prompt Design & Marker Contract | 0/3 | Not started | - |
| 3. Cron Marker Reader + Equal-Split + Ledger v2 | 1/1 | Verified (5/5 UAT pass) — agent-adoption gap deferred to Phase 6 | 2026-05-13 |
| 4. Wire Enrichment | 0/0 | Not started | - |
| 5. Housekeeping & Compat Hardening | 0/0 | Not started | - |
| 6. Mechanical Classification via agent:end Hook | 2/3 | In progress — G-02 gap closure planned in 06-03-PLAN.md | 2026-05-14 |

## Research Flags

| Phase | Research Needed | Tool / Method |
|-------|-----------------|---------------|
| 2 | Long-session halt-check survivability — manual E2E test plan against representative session lengths | Manual Hermes session test plan, recorded in `references/halt-survivability.md` |
| 3 | Revenium server-side `--operation-type` default behavior — does absence differ from explicit `CHAT` in cost calculations? | `manage_metering` MCP tool |
| 3 | S2 bias direction — confirm with operator that the documented bias framing is acceptable before shipping the synthetic-bias test | Team review of the bias documentation in `references/setup.md` |

Phases 1 and 5 use standard repository patterns (path additions, housekeeping mirror of `clear-halt.sh`) and skip phase-research.

## Coverage

- **v1 requirements:** 49
- **Mapped to phases:** 49
- **Unmapped:** 0
- **Categories:** PATH (3), TAX (5), MARK (5), PROMPT (7), CRON (9), WIRE (4), COMPAT (4), TEST (5), HOOK (12)

TEST requirements are distributed across the phases that own the code under test:
- TEST-01 (marker schema) → Phase 2
- TEST-02 (taxonomy schema) → Phase 2
- TEST-03 (cron split conservation, idempotency) → Phase 3
- TEST-04 (S2 synthetic bias) → Phase 3
- TEST-05 (no-legacy-branding continues to pass) → Phase 5

---
*Roadmap created: 2026-05-12*
