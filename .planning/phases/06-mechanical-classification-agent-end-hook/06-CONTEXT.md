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

*Phase: 06-mechanical-classification-agent-end-hook*
*Context gathered: 2026-05-13 via Phase 3 UAT findings + Hermes hook discovery + locked design decisions (subagent inheritance, LLM-assisted classification)*
