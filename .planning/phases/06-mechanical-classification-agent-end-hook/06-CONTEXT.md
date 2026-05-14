# Phase 6: Mechanical Classification via Hermes agent:end Hook - Context

**Gathered:** 2026-05-13
**Status:** Ready for planning
**Source:** Phase 3 UAT findings on Mac Studio + Hermes hook discovery + user-locked decisions

<domain>
## Phase Boundary

Phase 6 replaces soft prompt enforcement of the FINAL ACTION classification protocol (Phase 2) with mechanical enforcement via a Hermes lifecycle hook. The cron pipeline shipped in Phase 3 already reads markers correctly; this phase makes sure the markers exist regardless of whether the agent self-classifies.

Concretely:

1. **Install a Hermes hook** at `~/.hermes/hooks/revenium-classifier/` with `HOOK.yaml` and `handler.py`, registered for the `agent:end` event so it fires once per agent turn yielding back to the user.
2. **Classify the just-completed turn** inside the handler. Use a heuristic fast-path for trivial turns (skip if ≤ 2 sentences AND zero tools called). For substantive turns, call the Revenium-budgeted model to pick a `task_type` label from the live taxonomy (`~/.hermes/state/revenium/task-taxonomy.json`), lookup-first reuse, mint a new snake_case label only if no existing label fits.
3. **Write the marker file** at `~/.hermes/state/revenium/markers/<sid>.jsonl` in the schema Phase 3's `parse_prior_state` consumes — two records per substantive turn (GUARDRAIL classification span + CHAT work span), one marker file per session_id.
4. **Inherit task_type for subagents.** When the hook fires for a session whose state.db row has `parent_session_id IS NOT NULL`, walk to the root user-facing parent and use the parent's task_type instead of re-classifying. This ensures every token spent in a `delegate_task` lineage rolls up under the user's original request.
5. **Gate LLM calls on the budget halt.** If `~/.hermes/state/revenium/budget-status.json` shows `halted: true`, the hook skips the LLM call and writes `task_type: unclassified` plus a `WARN` log line. The classifier itself must not cause budget overrun.
6. **Distribute the hook via the skill package.** `hermes skills install revenium/hermes-revenium/skills/revenium` either installs the hook directly OR `examples/setup-local.sh` (or a documented post-install step) copies it to `~/.hermes/hooks/`. Operator can discover the installation step from `references/setup.md`.
7. **Keep the SKILL.md FINAL ACTION block in place as belt-and-suspenders.** If the agent self-classifies, the hook detects the existing marker for the turn (by tail-comparison or muid presence) and skips. No double-writes.

Out of scope this phase:
- Cron-side classifier fallback (if the hook is uninstalled or fails). Cron-side classification belongs to a hypothetical v2.
- Heuristic-only mode (no LLM dependency). Deferred — adds branching complexity without obvious near-term need.
- Per-tool-call attribution / sub-turn granularity. Deferred — turn-level is sufficient for Revenium's analytics.
- Removing the SKILL.md FINAL ACTION block. Deferred — it's compatible with the hook (no double-write per above) and provides agent-side telemetry for sessions where Hermes isn't running.

The load-bearing invariant: **on every Hermes session turn yield-back, exactly two marker records (GUARDRAIL + CHAT) appear in `~/.hermes/state/revenium/markers/<sid>.jsonl` for every substantive turn — regardless of whether the agent loaded the revenium skill, regardless of whether the session is a primary or a subagent, regardless of context pressure.**
</domain>

<decisions>
## Implementation Decisions

### Hook architecture

- **D-01:** Hook event = `agent:end`. Fires when the agent finishes processing a message (after all tool-call loops and assistant content land). Sufficient granularity — one classification per turn yielded to the user. `agent:step` was considered but rejected: fires per inner loop iteration, would produce N markers per turn instead of 2.
- **D-02:** Hook lives at `~/.hermes/hooks/revenium-classifier/` with `HOOK.yaml` declaring `events: [agent:end]` and `handler.py` exposing `async def handle(event_type, context)`. Matches Hermes' discovery convention at `gateway/hooks.py:HookRegistry.discover_and_load()`.
- **D-03:** Hook handler is async (per Hermes contract) and stdlib-only Python where practical. LLM calls use whatever async HTTP client Hermes provides to its hook context. If `context` doesn't expose an LLM helper, the handler falls back to direct `httpx` against the Revenium-budgeted base URL (resolved from `~/.hermes/config.yaml`). Open research item — answer locks D-03 sub-design.
- **D-04:** Hook errors are caught and logged; the handler must NEVER raise out of `handle()` because Hermes' main pipeline catches but does not retry. A handler crash silently drops one turn's classification — same failure mode as the agent skipping FINAL ACTION today. Acceptable.

### Classification semantics

- **D-05:** Subagent inheritance (LOCKED by user 2026-05-13): when state.db `sessions.parent_session_id IS NOT NULL`, the handler walks the chain via `SELECT parent_session_id FROM sessions WHERE id = ?` recursion until `parent_session_id IS NULL` (the root user-facing session) and uses that root session's most-recent marker `task_type`. Subagent task_type is purely inherited; no LLM call for subagents. Single classification per user request lineage.
- **D-06:** LLM-assisted classification (LOCKED by user 2026-05-13): for substantive turns on root sessions, the handler builds a compact prompt summarizing the turn (user message + tool call names + assistant content preview, capped at ~2KB to keep classifier cost trivial) and asks the budgeted model to pick a `task_type` label from the existing taxonomy or mint a new one matching `^[a-z][a-z0-9_]{1,47}$`. Lookup-first reuse — the prompt explicitly lists existing labels.
- **D-07:** Heuristic skip-fast-path: if the turn produced ≤ 2 sentences of assistant content AND called zero tools, skip the marker write entirely. No LLM call. Matches Phase 2's binary skip rule and Phase 3's expectation that the cron falls through to `unclassified` for skip-turns.
- **D-08:** Budget halt gating: before the LLM call, the handler reads `~/.hermes/state/revenium/budget-status.json`. If `halted: true`, skip the LLM call entirely and write the marker with `task_type: unclassified` plus a `WARN` log line. The classifier itself must never trip the halt. If `budget-status.json` is missing or unreadable, default to writing `unclassified` (fail-open same as the cron pipeline).
- **D-09:** Trivial-label blocklist (carries over from Phase 2 SKILL.md): the LLM may not pick `ack`, `acknowledgment`, `greeting`, `confirmation`, `hello`, `thanks`. The handler validates the LLM's output against this list and re-prompts once if violated; second violation falls back to `unclassified`.
- **D-10:** Two marker records per substantive turn — one with `operation_type = "GUARDRAIL"` (the classification span; tokens spent BY THE HOOK on the LLM call) and one with `operation_type = "CHAT"` (the work span; tokens spent BY THE AGENT on the actual turn). This matches Phase 2's PROMPT-04 convention and Phase 3's S2 equal-split telemetry expectations.

### Marker write semantics

- **D-11:** Marker file path = `~/.hermes/state/revenium/markers/<sid>.jsonl` where `sid` is the current Hermes session_id (NOT `pseudo-<ts>`). The hook context provides `session_id` directly so the `HERMES_SESSION_ID`-resolution dance from SKILL.md is unnecessary — primary OR subagent.
- **D-12:** Marker record format matches Phase 2's MARK-* schema exactly — `{muid, ts, sid, task_type, operation_type}` required; `{turn_seq, agent, trace_id, model}` optional. `muid` is 33-char lowercase hex per MARK-03 (13-char ms-timestamp prefix + 20-char random hex). Phase 3's `parse_prior_state` reads these without modification.
- **D-13:** Double-write avoidance: before writing, the handler reads the marker file's tail and checks if a marker with the same `(sid, turn_seq)` already exists. If yes, the agent self-classified via the SKILL.md FINAL ACTION pathway — the hook skips. Idempotency belt: the cron's per-muid dedup already prevents double-reporting at the wire level, so this check is optimization not correctness.
- **D-14:** Atomic write via `O_APPEND` + `fcntl.flock`. Same pattern as Phase 2's task-taxonomy.md mint pattern and Phase 3's per-call ledger write. < 1024 bytes per line.

### Distribution

- **D-15:** Hook ships INSIDE the skill at `skills/revenium/hooks/revenium-classifier/`. Either:
  - (a) `hermes skills install` honors a `hooks/` subdirectory in the skill and installs hooks alongside the skill content, OR
  - (b) `examples/setup-local.sh` and the documented operator install flow include a step to `cp -R` the hooks dir into `~/.hermes/hooks/`.
  Choice between (a) and (b) is a research item (depends on `hermes skills install` behavior on a skill that contains a `hooks/` subdir).
- **D-16:** `references/setup.md` gets a new "Mechanical classification hook" section after Phase 3's "How attribution works", documenting the hook's existence, where it lives, and how to verify it's loaded via `hermes hooks list`. The "How attribution works" framing stays put — Phase 6 doesn't change S2 bias semantics, only the mechanism that produces markers.

### Backward compatibility

- **D-17:** SKILL.md FINAL ACTION block stays in place verbatim (commit 02eadae's strengthened text). The hook handles the cases where the agent doesn't self-classify; the SKILL.md handles the cases where the hook fails to install or is disabled. Double-write avoided by D-13.
- **D-18:** Existing Phase 3 cron pipeline is UNCHANGED. Same `parse_prior_state` helper, same per-marker emission loop, same one-row-per-muid ledger format. The hook just produces markers the cron is already designed to read.

### Claude's Discretion

- Exact wording of the LLM classification prompt — the planner picks the shape subject to the constraints (lookup-first reuse, trivial-label blocklist, regex validation, ~2KB cap).
- Exact LLM call mechanism — whether to use a Hermes-provided helper or direct `httpx`. Locked by research finding on `agent:end` context shape.
- Exact threshold for "trivial turn" beyond the binary rule — the planner may add additional heuristics (e.g., turn-duration < 100ms always skip) subject to D-07's binary baseline.
- Exact distribution shape (a vs b in D-15) — the planner picks based on `hermes skills install` discovery.
- New requirement IDs (HOOK-01 through HOOK-NN) — the planner picks the breakdown.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project canonical
- `.planning/PROJECT.md` — Decisions 1-9 (per-turn granularity, controlled vocabulary, marker file IPC, --operation-type GUARDRAIL convention, --task-type unclassified default).
- `.planning/REQUIREMENTS.md` — Phase 6 will add HOOK-01..HOOK-NN; new requirements MUST trace to one or more success criteria in ROADMAP.md Phase 6.
- `.planning/ROADMAP.md` — Phase 6 section with 6 success criteria and locked decisions.

### Phase 2 deliverables (informs hook contract)
- `skills/revenium/SKILL.md` (FINAL ACTION block lines 279-417 in current main) — defines the marker schema and write semantics the hook must match exactly. The hook is the mechanical version of what the FINAL ACTION block instructs the agent to do.
- `skills/revenium/task-taxonomy.json` — seed labels the LLM classification prompt MUST list (lookup-first reuse).
- `skills/revenium/references/task-taxonomy.md` — label regex (`^[a-z][a-z0-9_]{1,47}$`), normalization rules, trivial-label blocklist. The hook MUST enforce these on LLM output.

### Phase 3 deliverables (cron pipeline that consumes hook output)
- `skills/revenium/scripts/hermes-report.sh` — per-session marker reader (lines 222-355 in current main). Reads markers via `parse_prior_state` from `~/.hermes/state/revenium/markers/<sid>.jsonl` — the hook MUST write to this exact path.
- `skills/revenium/scripts/split_strategies.py::parse_prior_state` — global muid dedup. The hook does not need to worry about idempotency at the wire level; the cron handles per-muid dedup.

### Hermes hook infrastructure (reference, not modified by this phase)
- `~/.hermes/hermes-agent/gateway/hooks.py::HookRegistry` — discovery and event dispatch. Read `discover_and_load()` and `emit()` for the contract.
- `~/.hermes/hermes-agent/hermes_cli/hooks.py` — `hermes hooks {list, test, revoke, doctor}` CLI for operator inspection.
- `~/.hermes/config.yaml::hooks` — config block (currently empty `{}`); the new hook may need a config entry or may be auto-discovered.

### state.db schema (for subagent inheritance)
- `~/.hermes/state.db::sessions` — columns include `id`, `parent_session_id` (foreign key to itself), `input_tokens`, `output_tokens`. Index `idx_sessions_parent` makes the recursion fast. The handler queries this for D-05.

### Discovery findings (Mac Studio, 2026-05-13)
- Hermes hook events available: `gateway:startup`, `session:start`, `session:end`, `session:reset`, `agent:start`, `agent:step`, `agent:end`, `command:*`. Source: `gateway/hooks.py:1-25`.
- Subagent sessions exist in `state.db` with `parent_session_id` set (verified by `SELECT parent_session_id FROM sessions LIMIT 1`).
- Subagent transcript files DO land at `~/.hermes/sessions/<subagent_sid>.jsonl` (initially thought missing — confirmed present in second sweep).

### Research gates (informational; NOT blocking for plan kickoff)
- **`agent:end` context payload shape** — what fields the hook's `context` argument carries. Read `gateway/hooks.py::HookRegistry.emit()` callers and recent agent loop code. Determines whether the hook can read the just-completed turn directly OR must re-read the session jsonl file.
- **LLM call mechanism from within a hook** — does the hook context expose a helper for making LLM calls, or must the handler instantiate its own httpx client? If the latter, the handler reads `~/.hermes/config.yaml` for provider base URL + API key resolution.
- **`hermes skills install` behavior on a skill containing a `hooks/` subdirectory** — does it copy the hooks dir into `~/.hermes/hooks/`? If yes, D-15(a). If no, D-15(b) (operator-driven post-install).
- **Hook reload on config change** — does Hermes auto-reload hooks when files change on disk, or is a `hermes gateway restart` required? Affects the operator install instructions.
</canonical_refs>

<specifics>
## Specific Ideas

- **Hook handler skeleton (illustrative — planner will refine):**
  ```python
  async def handle(event_type: str, context: dict) -> None:
      if event_type != "agent:end": return
      sid = context.get("session_id")
      if not sid: return
      try:
          # 1. Heuristic skip-fast-path (D-07)
          if _is_trivial_turn(context): return
          # 2. Subagent inheritance (D-05)
          parent_task_type = _walk_parent_chain(sid)
          if parent_task_type:
              task_type = parent_task_type
          else:
              # 3. Budget gate (D-08)
              if _budget_halted(): task_type = "unclassified"
              else:
                  # 4. LLM classification (D-06)
                  task_type = await _classify_via_llm(context)
                  if task_type in TRIVIAL_BLOCKLIST: task_type = "unclassified"
          # 5. Atomic write (D-11..D-14)
          _write_marker_pair(sid, task_type)
      except Exception as exc:
          logging.warning(f"revenium-classifier hook failed for {sid}: {exc}")
  ```
- **Test fixture for `hermes hooks test agent:end --payload-file <fixture>` [SUPERSEDED by Conflict C2 in 06-RESEARCH.md — the actual test uses direct `handler.handle(...)` invocation; `hermes hooks test` is a SHELL-hook CLI that does not dispatch Python event hooks.]:** synthetic JSON payload with `{event: "agent:end", session_id: "test-sid", message_count: 4, tool_calls: [...], assistant_content: "..."}`. The planner SHOULD ship at least one fixture in `skills/revenium/hooks/revenium-classifier/test-payloads/` and a tests/test_hook_classifier.py that invokes the hook with the fixture.
- **state.db read pattern:** read-only `sqlite3.connect(STATE_DB, mode="ro")` to avoid lock contention with Hermes' writer. `parent_session_id` traversal capped at a sane depth (e.g., 10) to prevent runaway loops on corrupted parent chains.
- **LLM prompt shape (illustrative):** "You are classifying a Hermes session turn for spend attribution. Existing labels: [list from task-taxonomy.json]. Turn summary: [compact 2KB summary]. Pick the single best-fitting existing label, or mint a new one matching `^[a-z][a-z0-9_]{1,47}$` if NONE fit. Forbidden: ack, acknowledgment, greeting, confirmation, hello, thanks. Output ONLY the label, no explanation."
- **Marker write atomicity:** same pattern as Phase 2's task-taxonomy.md atomic-write — single O_APPEND write with `fcntl.LOCK_EX`, < 1024 bytes per line.
</specifics>

<deferred>
## Deferred Ideas

- **Cron-side classifier fallback.** If the hook is uninstalled / disabled / crashes silently, the cron still falls through to `unclassified`. A v2 could add a cron-side post-hoc classifier that reads recent session jsonl files and writes markers for sessions with no marker file. Adds complexity for an edge case; defer.
- **Heuristic-only classification mode.** For air-gapped or LLM-budget-constrained installs, a heuristic-only mode (rules over tool-call signatures) could replace the LLM call. Defer until there's a concrete user with that constraint.
- **Per-tool-call attribution.** Currently a turn = one classification. Could be sub-divided into per-tool-call markers for finer granularity. Defer — Revenium analytics already work fine at turn level.
- **SKILL.md FINAL ACTION block removal.** Once the hook is proven reliable, the SKILL.md text could be removed to reduce maintenance burden. Defer — the text is small and harmless, and keeping it preserves operator-side documentation of the marker contract.
- **Hook hot-reload.** Updates to `handler.py` currently require a `hermes gateway restart`. A v2 could add file-watch hot-reload. Defer — operator restart is a one-time cost.
</deferred>

---

## Gap-closure addendum (2026-05-13 — post-UAT)

Surfaced by operator UAT on the Mac Studio (172.16.1.175) against gsd/phase-6-uat @ f3f4efa. See `06-HUMAN-UAT.md G-01` and `06-VERIFICATION.md` (status: gaps_found) for the evidence trail.

### What broke

`agent:end` is emitted exclusively from `hermes-agent/gateway/run.py:7631` — only platform-served gateway sessions (Telegram / Discord / Slack / WhatsApp / Webhook). CLI sessions (`hermes chat -q`), interactive `hermes chat`, ACP integrations, and gateway-internal cron-ticker sessions complete `run_conversation()` without ever emitting `agent:end`. Two synthetic CLI substantive turns confirmed this: hook loaded at gateway startup, but zero marker files were written for either turn.

The Phase 6 phase goal ("a Hermes lifecycle hook deterministically writes a marker record ... independent of whether the agent loaded the revenium skill or executed the FINAL ACTION self-classification code") is therefore not achieved for the dominant dev-time path.

### Locked decision (D-19)

**Replace the `agent:end` gateway-hook integration with a `hermes_cli` plugin that registers `on_session_end`.**

Why `on_session_end`:
- Emitted from `hermes-agent/run_agent.py:15164` at the end of EVERY `run_conversation()` call
- Fires for ALL session sources: gateway-served (Telegram et al.) AND CLI one-shot AND interactive AND ACP AND cron-spawned
- Payload provided: `session_id`, `completed`, `interrupted`, `model`, `platform` — exactly the fields the existing handler.py expects

Why a plugin and not a hook:
- The two events (`agent:end`, `on_session_end`) belong to two different registration mechanisms in Hermes. Gateway hooks (YAML manifest under `~/.hermes/hooks/`) listen to gateway-bus events. Plugins (Python `register(ctx)` under `~/.hermes/plugins/`) listen to CLI/agent-core bus events. We have to switch registration mechanisms because the event we want lives on the other bus.
- Reference pattern: `hermes-agent/plugins/disk-cleanup/` ships exactly the shape we need — `plugin.yaml` manifest + `__init__.py` with `register(ctx)` that calls `ctx.register_hook("on_session_end", handler)`.

### Out of scope (deliberately)

- Keeping the gateway hook alongside the plugin. `on_session_end` already fires for gateway-served sessions (because gateway/run.py invokes `run_conversation()`), so the gateway hook would double-fire and require dedup. Single-firing is the cleaner invariant — delete the old hook outright.
- Editing upstream `hermes-agent/` source to make `agent:end` fire from `run_agent.py`. We do not own that codebase.

### What the gap-closure plan must do

| Concern | Action |
|---------|--------|
| Plugin manifest | Add `skills/revenium/plugins/revenium-classifier/plugin.yaml` (`name: revenium-classifier`, `hooks: [on_session_end]`, description). |
| Plugin entrypoint | Add `skills/revenium/plugins/revenium-classifier/__init__.py` exporting `def register(ctx)` that registers `on_session_end → handler`. Reuse classification + marker-write helpers from the existing `handler.py`. |
| Shared module refactor | Factor the classification + marker-write logic from `skills/revenium/hooks/revenium-classifier/handler.py` into a shared module (`skills/revenium/plugins/revenium-classifier/classifier.py` or similar). Both the new plugin entrypoint AND tests should import from the shared module so duplicate code does not drift. |
| Remove gateway hook | Delete `skills/revenium/hooks/revenium-classifier/{HOOK.yaml, handler.py, test-payloads/}`. The gateway hook is redundant under the plugin and creates a double-fire / dedup contract that we explicitly do not want. |
| Distribution | Update `examples/setup-local.sh` so it (a) copies `skills/revenium/plugins/revenium-classifier/` to `~/.hermes/plugins/revenium-classifier/` and (b) adds `revenium-classifier` to `plugins.enabled` in `~/.hermes/config.yaml` (with an idempotent yaml-aware insert; if config.yaml is missing, print a one-line manual step). Remove the old hook-copy block. Keep the "Restart Hermes gateway" next-step line. |
| Tests | Migrate the 6 HOOK-* test methods in `tests/test_repository.py` to invoke the plugin entrypoint (or the shared module) instead of `handler.handle`. Keep the underlying classification/marker-pair/inheritance/halt/dedupe assertions. Update `test_revenium_classifier_files_exist` to assert the plugin path (`skills/revenium/plugins/revenium-classifier/`) and remove the hook-path assertion. |
| Docs | Update `skills/revenium/references/setup.md`'s "Mechanical classification hook" section to describe the plugin: new install path, gateway-restart still required (plugin manager loads at agent startup), and a one-line note that the plugin covers gateway + CLI + ACP + interactive + cron — not just gateway. |
| ROADMAP / REQUIREMENTS | Add a `HOOK-11` requirement for "plugin-based universal session coverage" and check it off when the gap is closed. Update Phase 6 ROADMAP success criteria SC1 / SC2 strings to refer to the plugin path + plugin-loader log line instead of `[hooks] Loaded hook ...`. Mark G-01 as resolved in the verification table. |
| UAT re-run on Mac Studio | The new plan should land back on `gsd/phase-6-uat` for a second operator UAT — both a CLI substantive turn AND a Telegram message should produce marker files with non-`unclassified` task_type. The cron tick should then ship `--task-type <label>` to Revenium. |

The renaming from "hook" to "plugin" is **load-bearing** for ROADMAP / SC1 / SC2 phrasing — they currently say `~/.hermes/hooks/revenium-classifier/...` and `[hooks] Loaded hook 'revenium-classifier'`. The gap-closure plan must update those success-criteria strings too, otherwise the verifier will mark the gap unclosed even after the code works.

---

## Gap-closure addendum #2 (2026-05-14 — post-UAT round 2)

UAT round 2 on Mac Studio (172.16.1.175 against `gsd/phase-6-uat @ 5f493c0`, plans 06-01 + 06-02 deployed) confirmed plan 06-02's architectural fix LANDED — the `hermes_cli` plugin loads, `register(ctx)` runs cleanly, `on_session_end` callback fires. But a CLI substantive turn still produced no marker file. See `06-HUMAN-UAT.md::G-02` for the full evidence trail.

### What broke (G-02)

`classifier._count_tools_in_current_turn(sid)` reads `~/.hermes/sessions/<sid>.jsonl` to count tool calls in the current turn. `hermes_cli/oneshot.py::_create_session_db_for_oneshot` writes session data only to `~/.hermes/state.db`, not to the per-session JSONL the gateway uses. The file is **absent** for CLI one-shot sessions.

With JSONL absent → `_count_tools_in_current_turn` returns 0. The `on_session_end` payload also doesn't include `response` text, so `response_preview = ""` → `len < 200`. Both heuristic-skip conditions match (`tool_count == 0` AND `response < 200 chars`) → the classifier correctly takes the trivial-skip path and writes no marker. Every CLI substantive turn is silently mis-classified as trivial.

The unit tests didn't catch this because every test fixture creates a synthetic tmpdir JSONL — the JSONL-absent branch was never exercised. Production CLI hits that branch on every invocation.

### Locked decision (D-20)

**Switch the tool-count source of truth from the per-session JSONL to `state.db.sessions.tool_call_count`. JSONL becomes a fallback.**

Why state.db is the right source:
- `tool_call_count` is populated for **every** session source (CLI, gateway-served, interactive, ACP, cron) — it's a column on the `sessions` table, written by every code path that runs `run_conversation`.
- The classifier already opens `state.db` via `sqlite3.connect(..., mode=ro)` for the parent-session walk in `_walk_to_root_session`. Adding a query against the same row is one extra parameterized SELECT.
- No new privilege boundary — same read-only connection.
- The fallback semantics: if state.db row is missing (very rare — would only happen if the on_session_end fires before the row is committed, which the upstream code at run_agent.py:15164 explicitly orders AFTER the session-DB write), fall back to JSONL. JSONL absent in that fallback → 0 (current behavior). Belt-and-braces; the primary path is state.db.

### Scope discipline (locked)

This plan is **narrowly scoped to G-02 only**. Out of scope for 06-03:
- The "tool-less Telegram turn gets trivial-skipped because response_preview is always 0" concern. Surfaced during diagnosis but operator decision: tool-less + short-response turns are arguably correctly classified as trivial chatter per the Phase 2 intent ("classify substantive turns only"). If it turns out tool-less production turns ARE substantive and need attribution, address in a follow-up — do not bundle here.
- The 3 code-review blockers in `06-02-REVIEW.md` (CR-01 subagent dedup, CR-02 walk-to-root depth-cap, CR-03 flow-style YAML). CR-01 and CR-02 are pre-existing carry-forward bugs from 06-01; CR-03 doesn't fire on the Mac Studio (no flow-style enabled list). Schedule a separate polish pass after Phase 6 closes.

### What the gap-closure plan must do

| Concern | Action |
|---------|--------|
| `_count_tools_in_current_turn` rewrite | In `skills/revenium/plugins/revenium-classifier/classifier.py`, rewrite `_count_tools_in_current_turn(sid)` to query `state.db.sessions.tool_call_count WHERE id = ?` first (using the same `mode=ro` URI pattern already in `_walk_to_root_session`). Return that integer. On `sqlite3.OperationalError` (db locked, missing) OR `None` row OR `None` value → fall back to the existing JSONL-reading path. On JSONL absent → 0 (current end-state for the fallback). D-04 invariant preserved: every exception path returns an integer; never raises. |
| Test: state.db row drives the count (positive) | New unit test: synthetic state.db with `INSERT INTO sessions (id, source, started_at, tool_call_count) VALUES ('test-sid', 'cli', 0, 3);` AND no JSONL file at `~/.hermes/sessions/test-sid.jsonl` — assert `_count_tools_in_current_turn('test-sid') == 3`. This is the test the round-1 plan-checker should have asked for. |
| Test: JSONL fallback (negative) | New unit test: state.db without the sid (or with tool_call_count NULL), JSONL has 5 role:tool entries — assert `_count_tools_in_current_turn('test-sid') == 5`. |
| Test: both absent → 0 | New unit test: neither state.db row nor JSONL — assert `_count_tools_in_current_turn('test-sid') == 0`. (Should already pass, but assert explicitly so the heuristic-skip-on-empty-session contract is pinned.) |
| Test: behavioral — CLI substantive turn writes marker | New end-to-end test that simulates a CLI substantive turn (state.db row with tool_call_count=2, no JSONL) and asserts that `run_classification` produces a marker file with a non-`unclassified` `task_type`. This is the test that would have caught G-02 in CI. Mock `call_llm` to return a valid label. |
| HOOK-12 requirement | Add `HOOK-12` to `.planning/REQUIREMENTS.md`: "Tool-count signal MUST be sourced from `state.db.sessions.tool_call_count` (universal — populated for every session source), with JSONL as fallback. The classifier MUST NOT mis-classify CLI / interactive / ACP / cron sessions as trivial solely because the gateway-style JSONL is absent." |
| ROADMAP success criteria update | Update Phase 6 ROADMAP SC2 to explicitly say "covers every session source including those without per-session JSONL (CLI one-shot, ACP, cron) — verified by an end-to-end test that creates a state.db row with `tool_call_count > 0` and NO JSONL, then asserts the classifier writes a marker file with non-`unclassified` `task_type`". |
| VERIFICATION.md G-02 transition | Update `06-VERIFICATION.md::gaps[G-02].gap_closure` from `pending` to `executed`. Keep `status: requires_rerun_uat` until UAT round 3 confirms a CLI substantive turn produces a marker on Mac Studio. |
| UAT round 3 on Mac Studio | After execution: re-run UAT 3 on `gsd/phase-6-uat`. Confirm: `hermes chat -q "..."` substantive turn → marker file appears with non-`unclassified` task_type → next cron tick ships `--task-type <label>` to Revenium (not `unclassified`). Mac Studio config.yaml already has `plugins.enabled: revenium-classifier` from UAT-2; no setup re-run needed. |

### Out of scope (deliberately)

- Touching anything else in `classifier.py` beyond `_count_tools_in_current_turn`.
- Changing the heuristic-skip threshold or logic shape.
- Adding the response-text signal to the substance heuristic.
- Touching `__init__.py::_on_session_end` callback signature.
- Migrating any of the existing 12 HOOK-* tests (they use synthetic JSONL; preserve as-is).
- Touching setup-local.sh, references/setup.md, REQUIREMENTS HOOK-01..HOOK-11 (carried unchanged from 06-02).

---

## Gap-closure addendum #3 (2026-05-14 — post-UAT round 3)

UAT round 3 on Mac Studio (172.16.1.175 against `gsd/phase-6-uat @ e49611b`, plans 06-01 + 06-02 + 06-03 deployed) confirmed G-01 + G-02 closure: marker file for CLI sid `20260514_031132_a7aa8e` shows `task_type: "generation"` (non-unclassified). But the cron pipeline shipped `task_type=unclassified` to Revenium 6.47 seconds BEFORE the marker was written. See `06-HUMAN-UAT.md::G-03` for the timeline.

### What broke (G-03)

The classifier's `on_session_end` callback does an LLM call to assign the task_type. For qwen3.6-plus this takes ~5-10 seconds. The cron ticker runs every minute against `~/.hermes/state.db`. Sessions whose final turn straddles a minute boundary race the classifier — if the cron ticks AFTER state.db has the token delta but BEFORE on_session_end has written the marker, the cron takes the D-18 default (`--task-type unclassified`). The cron's ledger is idempotent — once a session is reported, future ticks skip it forever even if a marker arrives 6 seconds later.

Concrete UAT round 3 evidence:
- 07:11:32.51 — CLI session row created in state.db
- 07:12:02.08 — cron tick: reads state.db, sees 35,550 tokens, NO marker exists yet, ships `task_type=unclassified`, writes ledger `HERMES:<sid>:35550:1778742722.083:unclassified-1778742722083`
- 07:12:08.55 — on_session_end fires, classifier writes marker with `task_type=generation` (6.47s late)
- Result: Revenium received `unclassified`; marker exists on disk but is unreachable by the ledger-idempotent cron.

state.db's `ended_at` column is NULL for CLI sessions (hermes_cli/oneshot.py doesn't populate it), so the cron can't filter on `ended_at IS NOT NULL` to wait for session completion. The cron's existing SELECT in `hermes-report.sh` has no settle-window or freshness filter.

### Locked decision (D-21)

**Plugin writes a sentinel file after every `on_session_end` invocation completes. Cron only reports sessions whose sentinel exists OR whose `started_at` is older than a settle-window (default: 2 minutes).**

Specifically:
- **Sentinel path:** `~/.hermes/state/revenium/markers/.ready/<sid>` — an empty file (zero bytes), `touch`-style. Module-level constant `MARKERS_READY_DIR` declared in `common.sh` alongside the existing `MARKERS_DIR`.
- **When the plugin writes a sentinel:** at the END of `_on_session_end` (in `__init__.py`), AFTER `run_classification` returns. Write happens unconditionally — for substantive turns (after marker pair written), trivial-skip turns (after the skip), inheritance turns (after parent task_type adopted), halt turns (after unclassified marker written), and even error paths (catch in the outer try/except, log warning, still write sentinel). The sentinel says "the plugin has finished with this session — cron may proceed."
- **Cron filter (in `hermes-report.sh` session SELECT):** `WHERE (input_tokens > 0 OR output_tokens > 0) AND (sentinel exists for sid OR started_at < strftime('%s', 'now') - SETTLE_SECONDS)`. The OR is the safety net for sessions where the plugin never fires (uninstalled plugin, plugin crash before the sentinel write, gateway hooks legacy path, etc.) — eventually they all report with the D-18 default. SETTLE_SECONDS = 120 (2 minutes) by default; configurable via env var `REVENIUM_CRON_SETTLE_SECONDS` for operator tuning.
- **Sentinel lifecycle:** sentinels are append-once, never updated. After a session is reported, the sentinel remains (we don't re-read it; idempotency is in the ledger). Housekeeping (future Phase 5) prunes both the marker file AND the sentinel together when a session is N days old.

Why this approach (not the alternatives):
- **(a) settle-delay only** (skip sessions younger than N seconds): fails for long-running sessions (> N min) — they're still in flight when the cron runs and would race the LAST classification.
- **(b) sentinel — chosen.** Deterministic. The plugin signals readiness explicitly. Long-running sessions still tick correctly as the operator drives turns; only the FINAL turn's classification is in flight and the sentinel handles that.
- **(c) plugin writes ended_at to state.db:** violates the "no writes to state.db" invariant (locked in CLAUDE.md). Out.
- **(d) re-shipping with `--cost 0` rows:** doubles the Revenium row count and complicates analytics math. Out.

### Scope discipline (locked)

This plan is **narrowly scoped to G-03 only**. Out of scope for 06-04:
- Touching the classifier itself (`_count_tools_in_current_turn`, `_walk_to_root_session`, `_classify_via_llm`, `_write_marker_pair`, etc.)
- The 3 code-review issues carried from 06-02-REVIEW.md (CR-01 subagent dedup, CR-02 walk-to-root depth-cap, CR-03 flow-style YAML) — scheduled for a separate polish pass
- The "tool-less Telegram turn" concern (open issue but distinct from G-03)
- Heuristic-skip threshold or logic shape
- Changes to setup-local.sh, references/setup.md, SKILL.md, or HOOK-01..HOOK-12 strings beyond adding HOOK-13

### What the gap-closure plan must do

| Concern | Action |
|---------|--------|
| `common.sh` new path constant | Declare `MARKERS_READY_DIR="${STATE_DIR}/markers/.ready"` between `MARKERS_DIR` and `mkdir -p`. Add to the `mkdir -p ...` line so the directory is created on first source. Update `tests/test_repository.py::test_runtime_paths_are_hermes_native` to assert the new path substring. |
| Plugin sentinel write | In `skills/revenium/plugins/revenium-classifier/__init__.py::_on_session_end`, after `run_classification(...)` returns (in the try block) AND in the outer `except Exception:` handler, write the sentinel: `MARKERS_READY_DIR / sid` — `Path(...).touch(exist_ok=True)`. Sentinel write must NEVER raise (any exception → log + swallow). The point of the sentinel is "the plugin has finished with this session" — fires for every outcome (marker written, trivial-skip, inheritance, halt, error). |
| Classifier shared module exports `MARKERS_READY_DIR` | Add the constant import in `classifier.py` alongside the existing `MARKERS_DIR` (mirror the path-discipline pattern). Plugin `__init__.py` imports from `.classifier`. |
| Cron settle filter | In `skills/revenium/scripts/hermes-report.sh`, modify the session SELECT to add the sentinel-or-aged filter. The simplest shape: Python heredoc that lists session candidates from sqlite, then filters by `os.path.exists(MARKERS_READY_DIR / sid) OR started_at < now - SETTLE_SECONDS`. SETTLE_SECONDS = `os.environ.get('REVENIUM_CRON_SETTLE_SECONDS', '120')`. Skipped sessions log a single `info` line: `"skipping <sid> — awaiting plugin sentinel (age=Ns < settle=120s)"` so operator can debug. |
| HOOK-13 requirement | Add `HOOK-13` to `.planning/REQUIREMENTS.md`: "Cron pipeline MUST synchronize with the plugin via a per-session sentinel file at `${MARKERS_READY_DIR}/<sid>`. Sessions WITHOUT a sentinel AND younger than `REVENIUM_CRON_SETTLE_SECONDS` (default 120s) MUST be skipped this tick to give the plugin time to finish classification. Sessions older than the settle window MAY be reported even without a sentinel (D-18 default) to handle plugin-failure cases." |
| ROADMAP success criteria update | Update Phase 6 SC5 to call out: "the next cron tick after on_session_end ships `--task-type <meaningful-label>` to Revenium — verified by an end-to-end fixture that creates a session, fires on_session_end (writing both the marker AND the sentinel), then invokes `hermes-report.sh` and asserts the resulting `revenium meter completion` call carries the marker's `task_type`, NOT `unclassified`." |
| Tests: sentinel write (positive) | New unit test: invoke `_on_session_end` directly with a synthetic state.db + mocked classifier; assert `MARKERS_READY_DIR / sid` exists after the call. |
| Tests: sentinel write on error path (D-04 belt) | New unit test: patch `run_classification` to raise; assert sentinel STILL gets written (D-04 invariant extends to sentinel: never block a session forever just because classification failed). |
| Tests: cron filter — skip recent-no-sentinel | New unit test: synthetic state.db with a session row whose `started_at` is 30s ago AND no sentinel; assert `hermes-report.sh`'s session-list query SKIPS the sid. |
| Tests: cron filter — report aged-no-sentinel | New unit test: synthetic state.db with a session row whose `started_at` is 200s ago AND no sentinel; assert the query INCLUDES the sid (safety-net path). |
| Tests: cron filter — report any-age-with-sentinel | New unit test: synthetic state.db with a session row whose `started_at` is 5s ago AND a sentinel file at `MARKERS_READY_DIR / sid`; assert the query INCLUDES the sid (sentinel path). |
| Tests: end-to-end (cron + sentinel) | New end-to-end test: synthetic state.db + write a marker file (sid X) + write a sentinel for sid X, invoke `hermes-report.sh` against synthetic HERMES_HOME, assert it ships the markers' `task_type` (not unclassified) to a mocked `revenium meter completion`. This is the CI regression guard for G-03. |
| VERIFICATION.md G-03 transition | Update `06-VERIFICATION.md::gaps[G-03].gap_closure` from `pending` to `executed`. Keep `status: requires_rerun_uat` until UAT round 4 confirms a CLI substantive turn produces a marker AND that marker reaches Revenium with the correct task_type. |
| UAT round 4 on Mac Studio | After execution: re-run UAT 4 on `gsd/phase-6-uat`. The test sequence: install (idempotent), restart gateway, drive a CLI substantive turn straddling a minute boundary, wait one minute, confirm cron ships `--task-type <label>` (NOT unclassified) by tailing `~/.hermes/state/revenium/revenium-metering.log`. |

The plugin → sentinel → cron chain is **the load-bearing primary path** for G-03 closure. The aged-safety-net is for the edge cases where the plugin fails silently — without it, a plugin crash would freeze the cron forever for that session.

### Out of scope (deliberately)

- Touching `classifier.py` beyond importing `MARKERS_READY_DIR` (no logic changes to the helpers).
- Heuristic-skip / response-text / parent-inheritance / budget-halt logic.
- The CR-01/CR-02/CR-03 code-review issues from 06-02-REVIEW.md.
- setup-local.sh changes (the new directory is created by `common.sh` sourcing, not by setup-local.sh — same pattern as `MARKERS_DIR` today).
- HOOK-01..HOOK-12 entry strings (carried unchanged).
- SKILL.md, the existing 12 HOOK-* tests, the 4 HOOK-12 tests.
- The cron pipeline's other logic — splits, ledger writes, etc. ONLY the session-selection SELECT changes.

---

*Phase: 06-mechanical-classification-agent-end-hook*
*Context gathered: 2026-05-13 via Phase 3 UAT findings + Hermes hook discovery + locked design decisions (subagent inheritance, LLM-assisted classification)*
*Gap-closure addendum: 2026-05-13 via Mac Studio UAT — D-19 locked: switch from gateway `agent:end` hook to `hermes_cli` `on_session_end` plugin*
*Gap-closure addendum #2: 2026-05-14 via Mac Studio UAT round 2 — D-20 locked: switch tool-count source from per-session JSONL to state.db.sessions.tool_call_count, JSONL fallback*
*Gap-closure addendum #3: 2026-05-14 via Mac Studio UAT round 3 — D-21 locked: plugin writes per-session sentinel at MARKERS_READY_DIR/<sid> after on_session_end; cron filters sessions by sentinel-or-aged (settle window 120s)*
