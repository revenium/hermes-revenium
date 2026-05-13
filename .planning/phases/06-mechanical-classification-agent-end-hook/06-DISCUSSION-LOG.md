# Phase 6 Discussion Log

**Date:** 2026-05-13
**Mode:** Inline discussion during Phase 3 UAT (not run via `/gsd-discuss-phase`)

Phase 6 was surfaced during Phase 3's user acceptance testing on John D'Emic's Mac Studio. The cron half of attribution was proven correct (5/5 UAT tests pass), but agent-side production of markers was empirically unreliable in Hermes' deployment architecture. The full discussion is recorded in the conversation transcript that produced commits `a273c06` through `8b84257`. Key beats:

## Failure observations (Phase 3 UAT, Mac Studio)

1. **Hermes uses lazy skill loading via `skill_view`.** The user's `john-session-bootstrap` skill chain (bootstrap → operating-doctrine) did not always trigger; sessions that opened with a research-style prompt (e.g. "research affordable managed switches") bypassed bootstrap entirely and jumped straight to `delegate_task`. Without bootstrap, the revenium skill never loaded.

2. **Even when revenium IS loaded**, the agent treated the FINAL ACTION block as documentation rather than as a binding action. In one debugging session, the agent loaded revenium, saw the FINAL ACTION text in a `skill_view` tool result, then ran 28 more tool calls and yielded without writing any marker.

3. **`HERMES_SESSION_ID` is not propagated to `execute_code` subprocesses** in the current Hermes build, so when the agent DID execute the marker-write snippet, the fallback fired and produced `pseudo-<unixts>.jsonl` filenames that the cron's `parse_prior_state` couldn't match against state.db session ids. Worked around in commit `7613c0f` by deriving sid from `~/.hermes/sessions/<id>.jsonl` filename, but only fixes primary sessions.

4. **Subagent sessions don't inherit skills.** `delegate_task` spawns child sessions with their own context, and the heaviest token consumers are subagents — none of which load revenium.

## Tactical fixes attempted (all on `main` before Phase 6)

- `a273c06` — scope `test_no_legacy_branding_left` to exclude `.planning/` (legacy-branding test was tripping on planning artifacts that quoted forbidden tokens as anti-patterns).
- `02eadae` — rewrite FINAL ACTION block in SKILL.md with HALT-CHECK-strength enforcement language ("MANDATORY", "NON-NEGOTIABLE", "you MUST call `execute_code`", self-check before yielding). PROVEN to produce marker writes when revenium is loaded — verified in test session `20260513_125139_f6c9a4b3` which produced two well-formed records (`task_type=research`, GUARDRAIL + CHAT).
- `7613c0f` — derive marker sid from session jsonl filename when `HERMES_SESSION_ID` is unset.

These narrow failure modes but cannot make adoption deterministic. Soft prompt enforcement in a lazy-loading runtime is fundamentally fragile.

## Decision point — three options offered to John

- **A:** Accept Phase 3 as passing; capture the agent-adoption gap as a follow-up.
- **B:** Keep iterating tactically (modify `john-operating-doctrine` to unconditionally load revenium).
- **C:** Architectural fix — Hermes hook-based mechanical enforcement.

**John chose (C).**

## Discovery (after C was chosen)

Hermes natively supports lifecycle hooks:

- Hook discovery: `~/.hermes/hooks/<name>/HOOK.yaml + handler.py` with `async def handle(event_type, context)`.
- CLI: `hermes hooks {list, test, revoke, doctor}`.
- Events: `gateway:startup`, `session:start`, `session:end`, `session:reset`, `agent:start`, `agent:step`, **`agent:end`**, `command:*`.
- Source: `~/.hermes/hermes-agent/gateway/hooks.py` — `HookRegistry.discover_and_load()` and `emit()`.
- Subagent → parent traceability: `state.db.sessions.parent_session_id` (foreign key to itself), indexed by `idx_sessions_parent`.

This makes a clean architecture possible: a Python hook on `agent:end` that classifies turns and writes markers, with subagent inheritance via a parent_session_id chain walk.

## Two decision questions asked, both locked

1. **Subagent task_type — inherit from parent or classify independently?**
   - John: **inherit** (single classification per user-request lineage).
2. **Classifier — pure heuristic or LLM-assisted?**
   - John: **LLM-assisted** (uses the Revenium-budgeted model itself; bounded by budget halt check).

These two answers fully determine the high-level shape of Phase 6.

## What's locked vs. open

**Locked decisions:** D-01 through D-18 in `06-CONTEXT.md`. Hook event, file layout, classification semantics, marker write semantics, distribution shape, backward compat — all decided.

**Research gates (informational, not blocking):**
- `agent:end` context payload shape (what fields the hook receives).
- LLM call mechanism from within the hook handler (Hermes-provided helper vs direct httpx).
- Whether `hermes skills install` copies a skill's `hooks/` subdirectory into `~/.hermes/hooks/`.
- Hook reload semantics on file change (gateway restart required?).

The phase researcher will resolve these via code-read of `~/.hermes/hermes-agent/gateway/hooks.py` and adjacent files. None of the gates block plan kickoff — they refine task-level details.

## Next step

Phase 6 directory is scaffolded. Next action: `/gsd-plan-phase 6` — the planner will produce one or more PLAN.md files with concrete task breakdown, dependency analysis, and verification block. Given the locked decisions and rich discovery already in `06-CONTEXT.md`, the planner has unusually low ambiguity to navigate; this should produce a clean plan in one revision pass.
