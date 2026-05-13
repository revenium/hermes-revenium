# Phase 6: Mechanical Classification via Hermes agent:end Hook - Research

**Researched:** 2026-05-13
**Domain:** Hermes lifecycle hooks, async Python handler design, in-process LLM dispatch, skill distribution
**Confidence:** HIGH on Gates 1, 3, 4 (read directly from live Hermes source on Mac Studio); HIGH on Gate 2 surface, MEDIUM on Gate 2 trust-gate fit (the only friction is that `agent.plugin_llm.PluginLlm` is wired through `PluginContext`, not `HookRegistry` — the handler must bypass it and call `agent.auxiliary_client.call_llm` directly)

## Summary

Phase 6 adds a Hermes lifecycle event hook (`agent:end`) that classifies every yielded turn and writes the Phase 2/3 marker pair (`GUARDRAIL` + `CHAT`) deterministically, independent of agent compliance. The four research gates are all resolvable from the live Hermes installation at `~/.hermes/hermes-agent/` on the Mac Studio (172.16.1.175); no Gate hits a wall.

Three findings reshape the plan in material ways:

1. **The hook's `context` payload is minimal.** It carries `{platform, user_id, session_id, message[:500], response[:500]}` and nothing else — no tool_calls list, no token counts, no full message history. The heuristic skip-fast-path (D-07: "≤ 2 sentences AND zero tools") therefore CANNOT be evaluated from the context alone; the handler must read `~/.hermes/sessions/<sid>.jsonl` to count tool entries since the most recent `role: user` line. This adds one filesystem read per turn — acceptable, but the planner needs to account for it.

2. **`hermes hooks list` is for SHELL hooks, not event hooks.** This is a name collision in Hermes between two parallel hook subsystems. The Python event-hook system at `~/.hermes/hooks/<name>/HOOK.yaml + handler.py` (the one Phase 6 targets) has **no operator-facing CLI**. Discovery confirmation must come from gateway startup logs (`[hooks] Loaded hook 'revenium-classifier' for events: ['agent:end']`) or a one-liner `python3 -c "from gateway.hooks import HookRegistry; r=HookRegistry(); r.discover_and_load(); print(r.loaded_hooks)"`. This contradicts CONTEXT.md D-02 and ROADMAP.md SC1 as worded — flagged below with MEDIUM severity. Decisions don't need to change, but the operator-verification wording must.

3. **`hermes skills install` does NOT relocate a `hooks/` subdirectory.** The installer (`tools/skills_hub.py::install_from_quarantine`) does a flat `shutil.move(quarantine, ~/.hermes/skills/revenium/)`. A skill that ships `skills/revenium/hooks/revenium-classifier/` ends up at `~/.hermes/skills/revenium/hooks/revenium-classifier/` — wrong path for the event-hook discovery loop, which scans `~/.hermes/hooks/`. **D-15(b) is the path** — `examples/setup-local.sh` (or a new `scripts/install-hook.sh`) must do the copy.

**Primary recommendation:** Adopt the locked decisions as-is. Reword the two operator-verification touchpoints (SC1 in ROADMAP + D-02 in CONTEXT) to use gateway-log inspection instead of `hermes hooks list`. Ship the hook at `skills/revenium/hooks/revenium-classifier/{HOOK.yaml, handler.py}` and extend `examples/setup-local.sh` to copy it into `~/.hermes/hooks/`. The handler imports `agent.auxiliary_client.call_llm` directly and wraps it with `asyncio.to_thread()` to stay async-safe.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Event firing (`agent:end`) | Hermes gateway process | — | Owned by `gateway/run.py:7631`. Not modifiable by this phase. |
| Hook discovery/load | Hermes gateway process | — | `gateway/hooks.py:HookRegistry.discover_and_load()` at startup. Single-shot, no reload. |
| Heuristic skip-fast-path evaluation | Hook handler | Session jsonl filesystem | Context lacks tool_calls list; handler reads `~/.hermes/sessions/<sid>.jsonl`. |
| Subagent parent walk | Hook handler | `~/.hermes/state.db` (read-only) | Parent chain via `SELECT parent_session_id FROM sessions WHERE id = ?` recursion. |
| Budget halt gate | Hook handler | `~/.hermes/state/revenium/budget-status.json` | Read-only consumer; falls open on missing/malformed file. |
| LLM classification call | Hook handler | `agent.auxiliary_client.call_llm` (in-process, sync) wrapped with `asyncio.to_thread()` | Hermes' shared aux LLM client handles provider routing/auth. Bypass the `PluginLlm` trust gate — hooks aren't plugins. |
| Marker write | Hook handler | `~/.hermes/state/revenium/markers/<sid>.jsonl` | Same atomic `O_APPEND + fcntl.LOCK_EX` pattern Phase 2 uses. |
| Marker read | Phase 3 cron pipeline (UNCHANGED) | — | `hermes-report.sh` + `parse_prior_state` already consume the path/format the hook writes. |
| Hook distribution to `~/.hermes/hooks/` | `examples/setup-local.sh` post-install step | (Not `hermes skills install` — see Gate 3) | The skill installer does NOT relocate `hooks/`. |
| Hook reload after upgrade | Operator-issued `hermes gateway restart` | — | No file-watch / auto-reload. One-shot load at gateway startup. |

## User Constraints

This section is intentionally absent — there is no separate "user constraints" block in CONTEXT.md to copy verbatim. CONTEXT.md uses `<decisions>` and `<canonical_refs>` instead. The 18 locked decisions D-01..D-18 below in **Locked Decisions Acknowledged** serve the equivalent role.

## Phase Requirements

Phase 6 will introduce HOOK-* requirement IDs during planning per CONTEXT.md "Claude's Discretion: New requirement IDs (HOOK-01 through HOOK-NN) — the planner picks the breakdown." This research therefore does NOT pre-allocate REQ-IDs; the planner owns that mapping. Below is the suggested coverage shape derived from ROADMAP.md's 6 success criteria — the planner may split or merge as needed:

| Suggested ID | Description | Maps to ROADMAP SC | Research Support |
|--------------|-------------|--------------------|------------------|
| HOOK-01 | Ship `skills/revenium/hooks/revenium-classifier/HOOK.yaml` + `handler.py` with `events: [agent:end]` and `async def handle(event_type, context)` | SC1 | Gate 1 + handler signature (test_hooks.py:158) |
| HOOK-02 | Handler implements heuristic skip-fast-path: if `tool_call_count_in_turn == 0` AND `len(context['response']) <= ~2_sentence_threshold`, skip marker write | SC2, D-07 | Gate 1 finding: tool_calls must come from session jsonl, not context |
| HOOK-03 | Handler walks `state.db.sessions.parent_session_id` to root, inheriting root's task_type for subagents | SC3, D-05 | Schema verified, `idx_sessions_parent` index confirmed |
| HOOK-04 | Handler gates the LLM call on `~/.hermes/state/revenium/budget-status.json::halted`; writes `unclassified` + WARN log if halted or file missing/malformed | SC4, D-08 | Existing budget-status.json contract from Phase 3 |
| HOOK-05 | Handler classifies via `agent.auxiliary_client.call_llm` wrapped in `asyncio.to_thread()` with the lookup-first prompt; validates against `^[a-z][a-z0-9_]{1,47}$` and the trivial-label blocklist (D-09); falls back to `unclassified` on validation failure | SC2, D-06, D-09 | Gate 2 finding: aux client is in-process Python, no fork needed |
| HOOK-06 | Handler writes exactly two markers per substantive turn (GUARDRAIL + CHAT) using `O_APPEND + fcntl.LOCK_EX`, schema `{muid, ts, sid, task_type, operation_type}`, < 1024 bytes per line, muid = 33-char hex per MARK-03 | SC2, D-10..D-14 | Phase 2 marker schema confirmed in test_marker_file_schema |
| HOOK-07 | Handler checks marker file tail for an existing marker with same `(sid, turn_seq)` before writing (D-13 belt) | D-13 | Optimization layer; cron muid dedup is correctness layer |
| HOOK-08 | `examples/setup-local.sh` copies `skills/revenium/hooks/revenium-classifier/` into `~/.hermes/hooks/revenium-classifier/` on install; documents `hermes gateway restart` post-install step | SC6, D-15(b), Gate 4 | Gates 3 + 4 |
| HOOK-09 | `tests/test_repository.py` adds the hook files to `test_expected_files_exist` and adds a hook-handler unit test that imports `handler.handle` and exercises a synthetic `agent:end` payload | SC5 | Test infrastructure already imports skill modules dynamically |
| HOOK-10 | `references/setup.md` gets a "Mechanical classification hook" section after "How attribution works" documenting hook existence + verification via gateway logs + restart procedure | SC6, D-16 | Setup.md section ordering verified |

## Locked Decisions Acknowledged

The following CONTEXT.md decisions are LOCKED. Research informs detail; it does not re-litigate:

- **D-01:** `agent:end` event — VERIFIED present in Hermes' event enum (`gateway/hooks.py:16`).
- **D-02:** `~/.hermes/hooks/revenium-classifier/{HOOK.yaml, handler.py}` — VERIFIED matches discovery contract (`gateway/hooks.py:79-130`). ⚠ **Operator-verification clause needs rewording** — see "Conflict Watchlist" below.
- **D-03:** Async handler; LLM via Hermes-provided helper or direct httpx — RESOLVED via Gate 2: use `agent.auxiliary_client.call_llm` (in-process, sync) wrapped with `asyncio.to_thread()`.
- **D-04:** Catch-and-log; never raise. VERIFIED: `HookRegistry.emit()` catches exceptions and prints, but does NOT retry (`gateway/hooks.py:175-180`).
- **D-05..D-14:** Classification + marker write semantics. All marker-side decisions are compatible with the existing Phase 3 cron reader (verified by reading `parse_prior_state` and `hermes-report.sh:222-355`).
- **D-15:** Distribution shape — RESOLVED via Gate 3: **(b) applies**. The skill installer does not handle a `hooks/` subdir; operator install must copy.
- **D-16:** `references/setup.md` addition. No research finding affects this.
- **D-17:** SKILL.md FINAL ACTION block stays in place. No research finding affects this.
- **D-18:** Phase 3 cron pipeline unchanged. VERIFIED by re-reading the marker reader against the hook's planned output format — they match.

## Standard Stack

### Core (already shipped, unchanged)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python (stdlib only) | 3.11 (Hermes venv) | Hook handler language | Matches existing skill stack constraint. `fcntl`, `json`, `sqlite3`, `secrets`, `time`, `pathlib`, `os`, `asyncio`, `logging` all suffice [VERIFIED: live venv inspected] |
| `pyyaml` | 6.0.3 | HOOK.yaml parsing | Already in Hermes venv; loaded by `HookRegistry.discover_and_load()` itself, not by handler [VERIFIED: live venv] |
| `agent.auxiliary_client.call_llm` | (Hermes-internal) | Shared LLM dispatch with provider routing, auth, retry, payment fallback | Hermes' canonical secondary-LLM client used by context compression, vision, web extraction, etc. [VERIFIED: `~/.hermes/hermes-agent/agent/auxiliary_client.py:3887`] |

### Supporting (available, only-if-needed fallbacks)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `httpx` | 0.28.1 | Direct provider call as fallback if aux client is somehow unsuitable | NOT recommended for v1; only if the aux client's blocking-IO inside `to_thread()` becomes a measured latency issue. [VERIFIED: live venv] |
| `anyio` | 4.13.0 | Structured async (alternative to `asyncio.to_thread`) | Optional; `asyncio.to_thread()` is sufficient. [VERIFIED: live venv] |
| `openai` | 2.32.0 | Direct SDK call as fallback | Only if `call_llm` becomes unavailable. Same reasoning as httpx. [VERIFIED: live venv] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `agent.auxiliary_client.call_llm` | `agent.plugin_llm.PluginLlm.acomplete()` | `PluginLlm` is wired through `PluginContext` (`hermes_cli/plugins.py:287-310`), which is constructed by `PluginManager.discover_and_load`. Hooks are loaded by `HookRegistry`, NOT `PluginManager` — they're different subsystems. The trust-gate `plugins.entries.<id>.llm.*` config keys don't apply. The hook would have to instantiate `PluginLlm(plugin_id="revenium-classifier")` manually, which violates the "constructor binds plugin identity for trust-gate enforcement" comment at `plugin_llm.py:601-606`. Cleaner to use the lower-level `call_llm`. |
| Async (`async def handle`) | Sync (`def handle`) | `HookRegistry.emit()` handles both (`hooks.py:172-178`: `if asyncio.iscoroutine(result): await result`). Async is preferred so the handler can use `asyncio.to_thread()` for the blocking `call_llm` invocation without parking the gateway event loop on a 1-3s LLM call. |
| Reading session jsonl every turn | Asking the agent loop to inject tool_call_count into the hook context | Requires a patch to `gateway/run.py:7631` to broaden the payload. Out of scope — Phase 6 must not modify Hermes. One filesystem read per turn is acceptable. |

**Installation:**
No new packages. The handler imports only stdlib + Hermes-internal modules:
```python
import asyncio, fcntl, json, logging, os, re, secrets, sqlite3, time
from pathlib import Path
from agent.auxiliary_client import call_llm  # in-process, available because hook runs in Hermes process
```

**Version verification:** Already done — checked `~/.hermes/hermes-agent/venv/lib/python3.11/site-packages/`:
- `httpx 0.28.1` (2025-04 release)
- `openai 2.32.0` (2025-09 release)
- `anyio 4.13.0` (2025-10 release)
- `pyyaml 6.0.3` (2025-09 release)

These satisfy any plausible fallback need. [VERIFIED: live venv via `ls ~/.hermes/hermes-agent/venv/lib/python3.11/site-packages/`]

## Architecture Patterns

### System Architecture Diagram

```
              ┌────────────────────────────────────────────────────────────┐
              │  Hermes gateway process (one per host)                     │
              │                                                            │
              │   user msg ──► agent loop ──► tool calls ──► assistant ──► │
              │                                                  yield     │
              │                                                  │         │
              │                                                  ▼         │
              │   HookRegistry.emit("agent:end", {               │         │
              │     platform, user_id, session_id,               │         │
              │     message[:500], response[:500]                │         │
              │   })   ◄── ENTRY POINT FOR PHASE 6 HANDLER       │         │
              │                                                            │
              └─────────────────────────────┬──────────────────────────────┘
                                            │
                                            ▼
              ┌────────────────────────────────────────────────────────────┐
              │  revenium-classifier handler.py (async def handle)         │
              │                                                            │
              │   1. Read context fields ─────► session_id, message,       │
              │                                  response                  │
              │                                                            │
              │   2. Read ~/.hermes/sessions/<sid>.jsonl                   │
              │      └─► count tool entries since last user line           │
              │      └─► evaluate D-07 skip-fast-path                      │
              │                                                            │
              │   3. Read ~/.hermes/state.db (read-only) ──► sessions      │
              │      └─► parent_session_id chain walk (D-05)               │
              │      └─► if non-null: read parent's marker file,           │
              │          inherit task_type, skip LLM (D-05)                │
              │                                                            │
              │   4. Read ~/.hermes/state/revenium/budget-status.json      │
              │      └─► if halted: task_type = "unclassified",            │
              │          WARN log, skip LLM (D-08)                         │
              │                                                            │
              │   5. Read ~/.hermes/state/revenium/task-taxonomy.json      │
              │      └─► existing labels list for the prompt               │
              │                                                            │
              │   6. await asyncio.to_thread(call_llm,                     │
              │             messages=[classification_prompt], ...)         │
              │      └─► parse + validate against regex + blocklist        │
              │      └─► retry once on blocklist hit (D-09), then fall     │
              │          back to "unclassified"                            │
              │                                                            │
              │   7. Read ~/.hermes/state/revenium/markers/<sid>.jsonl     │
              │      └─► tail check: existing marker for this turn?        │
              │          (D-13 belt) — if yes, skip write                  │
              │                                                            │
              │   8. Atomic write of GUARDRAIL + CHAT marker pair          │
              │      └─► O_APPEND + fcntl.LOCK_EX (D-14)                   │
              │                                                            │
              └────────────────────────────────────────────────────────────┘
                                            │
                                            ▼ (filesystem only)
              ┌────────────────────────────────────────────────────────────┐
              │  Phase 3 cron pipeline (UNCHANGED — D-18)                  │
              │  every-minute: hermes-report.sh ─► parse_prior_state ─►    │
              │                                    per-marker emission ─►  │
              │                                    revenium meter completion│
              └────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure

```
skills/revenium/
├── SKILL.md                                  # unchanged (D-17)
├── task-taxonomy.json                        # unchanged
├── hooks/
│   └── revenium-classifier/
│       ├── HOOK.yaml                         # NEW
│       ├── handler.py                        # NEW
│       └── test-payloads/                    # NEW (fixtures for unit test)
│           ├── substantive-turn.json
│           ├── trivial-turn.json
│           └── subagent-turn.json
├── references/
│   ├── setup.md                              # extend with "Mechanical classification hook" section
│   ├── task-taxonomy.md                      # unchanged
│   ├── halt-survivability.md                 # unchanged
│   └── troubleshooting.md                    # extend with hook-load failure modes
└── scripts/                                  # all unchanged
    ├── common.sh
    ├── hermes-report.sh
    ├── split_strategies.py
    └── ...

examples/
└── setup-local.sh                            # extend: add `cp -R hooks/* ~/.hermes/hooks/` step

tests/
└── test_repository.py                        # extend: hook files in expected list, handler unit test
```

### Pattern 1: HOOK.yaml manifest shape

**What:** Minimal manifest declaring event subscription. The discovery loop reads `name`, `description`, `events`.
**When to use:** Always — required by `HookRegistry.discover_and_load()`.
**Example:**
```yaml
# Source: ~/.hermes/hermes-agent/gateway/hooks.py:79-130 (discovery contract)
name: revenium-classifier
description: Classifies each Hermes agent:end turn and writes a marker pair (GUARDRAIL + CHAT) for Revenium task-type attribution. See ~/.hermes/skills/revenium/ for the consumer pipeline.
events:
  - agent:end
```

The `name` field is what shows in the gateway startup log (`[hooks] Loaded hook 'revenium-classifier' for events: ['agent:end']`). No other fields are required by Hermes.

### Pattern 2: handler.py async signature

**What:** Top-level `handle` function called by `HookRegistry.emit()`. May be sync or async — async is the right choice here.
**When to use:** Always — required name and signature.
**Example:**
```python
# Source: ~/.hermes/hermes-agent/tests/gateway/test_hooks.py:144-148 (async handler reference)
# Source: ~/.hermes/hermes-agent/gateway/hooks.py:170-180 (dispatcher contract)
async def handle(event_type: str, context: dict) -> None:
    """Fired by HookRegistry.emit() on every Hermes lifecycle event we subscribed to.

    Errors raised here are caught and logged by HookRegistry; they don't block
    the agent pipeline. Returning early is fine. The handler MUST NOT raise
    out of this function — that's a contract from D-04 and from Hermes' own
    error-isolation guarantee.
    """
    if event_type != "agent:end":
        return  # defensive — HookRegistry only dispatches subscribed events anyway
    try:
        # … steps 1-8 from the architecture diagram
        pass
    except Exception as exc:
        logging.warning("revenium-classifier hook failed for sid=%s: %s",
                        context.get("session_id", "?"), exc)
        # NEVER re-raise.
```

### Pattern 3: In-process LLM call via aux client (async-safe)

**What:** Hermes ships a synchronous `agent.auxiliary_client.call_llm` that handles provider resolution (OpenRouter, Anthropic, OpenAI, etc.), auth, retry, and payment-fallback. Hooks run in the gateway event loop, so the call must not block — wrap with `asyncio.to_thread()`.
**When to use:** Every substantive non-subagent turn that passes the budget halt gate.
**Example:**
```python
# Source: ~/.hermes/hermes-agent/agent/auxiliary_client.py:3887 (call_llm signature)
# Source: ~/.hermes/hermes-agent/agent/plugin_llm.py:1-50 (rationale: hook-like callers use the aux client)
import asyncio
from agent.auxiliary_client import call_llm

async def classify_turn(user_msg: str, assistant_resp: str, existing_labels: list[str]) -> str:
    prompt = _build_classification_prompt(user_msg, assistant_resp, existing_labels)
    response = await asyncio.to_thread(
        call_llm,
        task="title_generation",   # or omit task and use main config — see D-06 design choice
        messages=[
            {"role": "system", "content": "You classify Hermes turns into task_type labels."},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.0,
        max_tokens=64,
        timeout=10.0,
    )
    raw = response.choices[0].message.content.strip()
    return _validate_label(raw)  # regex + blocklist (D-09)
```

**Key design call for the planner:** `call_llm`'s `task=` argument lets it pick provider/model from `config.yaml::auxiliary.<task>` overrides. The candidates per `agent/auxiliary_client.py:1-30`:
- `"title_generation"` — cheap, short. Best fit for label classification.
- `"compression"` — sized for context, might overspec.
- `"session_search"` — semantic, also potentially overspec.
- Omit `task=` — falls through to the user's main provider+model (D-06's "Revenium-budgeted model"). **This is what D-06 says to do.**

Recommended for v1: omit `task=` so the classifier uses the same model Revenium is already budgeting. This is the literal reading of D-06: "ask the budgeted model to pick a `task_type` label."

### Pattern 4: state.db read-only subagent walk

**What:** Subagents are sessions whose `parent_session_id IS NOT NULL`. Walk to the root, then read the root's marker file to inherit the task_type. Read-only connection to avoid lock contention with Hermes' writer.
**When to use:** Every turn whose `context['session_id']`'s state.db row has a parent. Subagent classification is purely inherited per D-05 — no LLM call.
**Example:**
```python
# Source: live ~/.hermes/state.db schema (verified 2026-05-13 via sqlite3 -readonly)
# columns include: id TEXT PRIMARY KEY, parent_session_id TEXT, FOREIGN KEY (parent_session_id) REFERENCES sessions(id)
# index: CREATE INDEX idx_sessions_parent ON sessions(parent_session_id)
import sqlite3
from pathlib import Path

def find_root_session_id(state_db: Path, sid: str, max_depth: int = 10) -> str:
    """Walk parent_session_id chain. Returns the input sid if it has no parent.
    Capped at max_depth to defeat any pathological corrupted parent loop."""
    uri = f"file:{state_db}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        current = sid
        for _ in range(max_depth):
            row = conn.execute(
                "SELECT parent_session_id FROM sessions WHERE id = ?", (current,)
            ).fetchone()
            if row is None or row[0] is None:
                return current
            current = row[0]
        return current  # depth exceeded — return the deepest we found
```

The depth cap is the only defense against corrupted parent chains. State.db is a shared SQLite file with WAL — read-only mode (`?mode=ro`) prevents any write contention. The hook should `pass` on `sqlite3.OperationalError` (database locked, file missing) — fall through to treating the session as a root.

### Pattern 5: Tool-call count from session jsonl

**What:** The hook context doesn't include the tool_call list. To evaluate D-07's "zero tools" condition, the handler reads the session jsonl from the most recent `role: user` line forward and counts `role: tool` entries.
**When to use:** Every turn that isn't a subagent (subagents skip the LLM anyway).
**Example:**
```python
# Source: live ~/.hermes/sessions/*.jsonl format inspected 2026-05-13
# Each line is a JSON object with keys: role, content, name (tool only), tool_call_id (tool only),
# reasoning (assistant only), timestamp, finish_reason (assistant final only)
def count_tools_in_current_turn(sessions_dir: Path, sid: str) -> int:
    """Return the number of role:tool entries in the most recent user → assistant turn.
    Returns 0 if the file is missing or no user line found in the tail."""
    path = sessions_dir / f"{sid}.jsonl"
    if not path.is_file():
        return 0
    # Read the file as a sequence of records; find the LAST role:user and count tools after it.
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    last_user_idx = None
    for i in range(len(lines) - 1, -1, -1):
        try:
            obj = json.loads(lines[i])
        except json.JSONDecodeError:
            continue
        if obj.get("role") == "user":
            last_user_idx = i
            break
    if last_user_idx is None:
        return 0
    tool_count = 0
    for line in lines[last_user_idx + 1:]:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("role") == "tool":
            tool_count += 1
    return tool_count
```

For very long session files this is O(file size); the planner may optionally use `os.path.getsize()` + tail-read to bound it. For v1 a full read is acceptable — typical session files are under 1 MB, and `agent:end` only fires a handful of times per minute even under load.

### Pattern 6: Atomic marker write (already locked by Phase 2)

**What:** Same `O_APPEND + fcntl.LOCK_EX` pattern from `SKILL.md:316-365`. The handler reuses this verbatim.
**When to use:** After classification yields a valid label.
**Example:**
```python
# Source: skills/revenium/SKILL.md:353-365 (Phase 2 canonical snippet)
def _write_marker_pair(markers_dir: Path, sid: str, task_type: str) -> Path:
    markers_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker_path = markers_dir / f"{sid}.jsonl"
    def _muid():
        return f"{int(time.time_ns() // 1_000_000):013x}" + secrets.token_hex(10)
    def _record(op):
        return {"muid": _muid(), "ts": time.time(), "sid": sid,
                "task_type": task_type, "operation_type": op}
    line_g = json.dumps(_record("GUARDRAIL"), separators=(",", ":"), ensure_ascii=True) + "\n"
    line_c = json.dumps(_record("CHAT"),      separators=(",", ":"), ensure_ascii=True) + "\n"
    with open(marker_path, "ab", buffering=0) as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line_g.encode("utf-8"))
        f.write(line_c.encode("utf-8"))
    return marker_path
```

Note the difference from Phase 2's `SKILL.md` snippet: the hook receives `context["session_id"]` directly, so there is **no** `HERMES_SESSION_ID`-resolution fallback dance. The Phase 2 snippet had to derive sid from the newest session jsonl filename because `HERMES_SESSION_ID` wasn't propagated to `execute_code` subprocesses (Phase 3 UAT finding). The hook runs in-process — it has the canonical sid.

### Anti-Patterns to Avoid

- **Calling `hermes hooks test agent:end --payload-file <fixture>`** as if it tests the Python event hook. This CLI command is for SHELL hooks declared in `~/.hermes/config.yaml::hooks`, a different subsystem. It will NOT exercise `revenium-classifier/handler.py`. The test approach must invoke `handler.handle(event_type, context)` directly with a synthetic payload — pure Python unit test, no CLI. (Severity: this anti-pattern is currently present in CONTEXT.md's "Specific Ideas" section, and ROADMAP.md SC2.)
- **Instantiating `agent.plugin_llm.PluginLlm("revenium-classifier")`** to access `ctx.llm` semantics. The trust-gate `plugins.entries.<id>.llm.*` config keys would not apply (no `PluginManager` would have parsed them), and the trust-policy loader would return the fail-closed default (no overrides allowed). Use `agent.auxiliary_client.call_llm` directly — simpler and no fictitious plugin identity.
- **Raising an exception out of `handle()`.** `HookRegistry.emit()` catches it and prints, but the agent loop has already yielded — there's no recovery. D-04 makes this explicit: catch-and-log only. Also: re-raising would print to stderr and pollute gateway logs.
- **Writing markers from BOTH the hook AND the SKILL.md FINAL ACTION code path on the same turn.** D-13 prevents this via tail-check — the planner must implement the check, NOT rely on cron muid-dedup. (Cron dedup would still prevent double-billing on the wire, but the marker file would carry duplicate records, polluting the file and complicating debugging.)
- **Reading `state.db` without `?mode=ro`.** The Hermes writer holds a WAL lock. A non-readonly connection from the hook could either block waiting for the lock or trigger a "database is locked" error mid-handler.
- **Hardcoding `~/.hermes/state/revenium/markers/` instead of resolving from `common.sh`.** Even though the handler is Python (not Bash), the path discipline still applies — the test invariant (`test_runtime_paths_are_hermes_native`) will need extending to check that the handler resolves paths the same way `common.sh` does. The cleanest path is to read environment variables (`HERMES_HOME`, `REVENIUM_STATE_DIR`) with sensible defaults, matching `common.sh`'s shape.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| LLM provider routing (OpenRouter / Anthropic / OpenAI / etc.) | Custom httpx client per provider | `agent.auxiliary_client.call_llm` | Handles auth resolution, base_url overrides, model name aliasing, payment-fallback chain, retry. ~2000 LOC of edge cases [VERIFIED: `agent/auxiliary_client.py` is 4k+ LOC] |
| Async-safe blocking call | Custom thread pool | `asyncio.to_thread(call_llm, ...)` | One-liner; preserves cancellation semantics; doesn't fight Hermes' own loop |
| YAML manifest parsing | Custom parser | `pyyaml` (already in venv, used by `HookRegistry`) | Hook discovery already parses HOOK.yaml — no second parser needed |
| Marker file atomicity | flock-then-rename or custom O_EXCL | `O_APPEND + fcntl.LOCK_EX` (Phase 2 canonical pattern) | Phase 2 already shipped and tested this pattern. < 1024 bytes per record means single-`write(2)` atomicity on POSIX |
| Muid generation | UUID4 | `f"{int(time.time_ns()//1_000_000):013x}" + secrets.token_hex(10)` | MARK-03 contract: 13-char ms-timestamp prefix (lex-sortable) + 20-char random hex = 33 chars. Verified by `test_marker_file_schema`. |
| Subagent inheritance via session jsonl | Read jsonl → find delegate_task tool calls → reconcile | `state.db.sessions.parent_session_id` recursive read | The parent_session_id column exists for this exact purpose. `idx_sessions_parent` makes recursion O(depth) |
| Hook reload on file change | inotify / watchdog | `hermes gateway restart` | Hermes does not auto-reload hooks. Document the operator step. |

**Key insight:** Phase 6 is mostly glue. Every load-bearing primitive already exists in Hermes (`call_llm`, `HookRegistry`, `sessions.parent_session_id`) or in Phase 2/3 (`marker schema`, `O_APPEND+flock` pattern, `parse_prior_state`). The hook handler is the connective tissue.

## Runtime State Inventory

Phase 6 is **additive, not a rename or refactor**. It introduces NEW files and an additive write pattern. Pre-existing runtime state is unaffected.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — Phase 6 reads the existing `state.db` (read-only) and reads/writes the existing markers directory (additive only). No schema change, no migration. | None |
| Live service config | None — no n8n / launchd / pm2 service is reconfigured. The cron pipeline shipped in Phase 3 is unchanged (D-18). | None |
| OS-registered state | None — no new launchd plist / systemd unit / cron entry is created for the hook itself. The hook is loaded by the existing `hermes gateway` service at startup. | None |
| Secrets/env vars | The handler reads existing Hermes provider auth via `agent.auxiliary_client.call_llm`, which resolves API keys from `~/.config/revenium/config.yaml` and provider-specific stores Hermes already manages. No new env var introduced. The hook handler MAY also read `HERMES_HOME` and `REVENIUM_STATE_DIR` (with defaults matching `common.sh`) — these are existing vars from Phase 1. | None — verify no new vars are added |
| Build artifacts | None — no compiled or installed package. The `hooks/` subdirectory ships as static files. After `examples/setup-local.sh` extension, the operator must run `hermes gateway restart` once to load the hook — this is documented, not silent. | Document restart step in `references/setup.md` |

**Migration concerns:** None. Existing installs without the hook continue to behave exactly as today (SKILL.md FINAL ACTION still encourages self-classification; cron fallthrough to `unclassified` for sessions with no markers). Upgrading is purely additive — re-run `setup-local.sh`, then `hermes gateway restart`. No data migration.

**Pre-existing markers from Phase 2/3 trial sessions on the Mac Studio:** verified present at `~/.hermes/state/revenium/markers/20260513_125139_f6c9a4b3.jsonl`. The hook's write pattern produces records that are byte-compatible with the existing reader (`parse_prior_state`). [VERIFIED via SSH]

## Common Pitfalls

### Pitfall 1: Confusing the two hook subsystems

**What goes wrong:** Planner or implementer writes a `HOOK.yaml` matching the SHELL-hook schema (`event: pre_tool_call`, `matcher: ...`, `command: ...`) and lists it in `~/.hermes/config.yaml::hooks` expecting it to fire on `agent:end`. It doesn't. Or, conversely, runs `hermes hooks list` and concludes the event-hook isn't loaded.

**Why it happens:** Hermes ships TWO independent hook subsystems both called "hooks":
1. **Shell hooks** — config-driven, declared in `~/.hermes/config.yaml::hooks`, fire on events like `pre_tool_call`, `on_session_start`, `subagent_stop`. Implemented by `agent/shell_hooks.py`. CLI: `hermes hooks {list, test, revoke, doctor}`. Defined event names in `VALID_HOOKS` (`hermes_cli/plugins.py:128`).
2. **Event hooks** (Phase 6 target) — directory-driven, declared at `~/.hermes/hooks/<name>/HOOK.yaml`, fire on events like `agent:start`, `agent:end`, `session:start`, `gateway:startup`. Implemented by `gateway/hooks.py::HookRegistry`. No dedicated CLI. Defined event names in the module docstring (`gateway/hooks.py:13-19`).

**How to avoid:** When the planner writes operator-verification steps, use one of:
- Inspect gateway startup logs for `[hooks] Loaded hook 'revenium-classifier' for events: ['agent:end']` (printed by `gateway/hooks.py:135`).
- One-liner: `cd ~/.hermes/hermes-agent && ./venv/bin/python3 -c "from gateway.hooks import HookRegistry; r=HookRegistry(); r.discover_and_load(); print([h['name'] for h in r.loaded_hooks])"`
- File-presence check: `test -f ~/.hermes/hooks/revenium-classifier/HOOK.yaml && test -f ~/.hermes/hooks/revenium-classifier/handler.py`.

**Warning signs:** Anyone says "use `hermes hooks list` to verify" or "use `hermes hooks test agent:end` to test."

### Pitfall 2: Hook loaded but never fires because gateway wasn't restarted

**What goes wrong:** Operator updates the hook via `hermes skills install --force` or `setup-local.sh`. The new files land in `~/.hermes/hooks/`. The handler never fires because the gateway process loaded the OLD hook (or no hook at all) at its last startup.

**Why it happens:** `HookRegistry.discover_and_load()` is called exactly once during gateway boot (`gateway/run.py:3377`). No file-watch. No reload mechanism. Loaded handlers live in `self._handlers` for the gateway's lifetime.

**How to avoid:** The post-install step MUST include `hermes gateway restart`. Document this in `references/setup.md` and in `examples/setup-local.sh`'s "Next steps" echo block. If the planner can detect whether `hermes gateway status` returns "running," conditional logic to auto-restart is reasonable; otherwise just print the instruction.

**Warning signs:** A turn that should produce a marker doesn't, and `~/.hermes/hooks/revenium-classifier/` exists on disk.

### Pitfall 3: The handler context lacks tool_calls — D-07 cannot be evaluated from context alone

**What goes wrong:** Implementer reads `context['tool_calls']` or `context['message_count']` to evaluate D-07's "zero tools called" condition. Both are `None` / `KeyError` because they don't exist in the payload.

**Why it happens:** The `agent:end` payload (`gateway/run.py:7479-7485` + `:7631-7633`) is a deliberately minimal preview blob — `{platform, user_id, session_id, message[:500], response[:500]}`. Hermes' designers didn't include tool_call history.

**How to avoid:** Read tool count from `~/.hermes/sessions/<sid>.jsonl` (Pattern 5 above). For the "≤ 2 sentences" threshold, the 500-char `response` preview is enough — a substantive turn nearly always exceeds 500 chars, so the preview being truncated is itself a signal of substantiveness. A conservative threshold: skip only if `len(context['response']) < 200` AND tool_count_in_turn == 0.

**Warning signs:** Tests pass for trivial fixtures but production never skips any turn — symptom of a handler that triggers an LLM call on every "good morning" reply because it can't detect triviality.

### Pitfall 4: `call_llm` blocks the event loop

**What goes wrong:** Handler calls `call_llm(...)` directly inside `async def handle`. The LLM round-trip blocks for 1-3 seconds. Other hooks subscribed to `agent:end` (or to subsequent events on the same gateway) wait. In extreme cases the gateway appears hung to the user.

**Why it happens:** `agent.auxiliary_client.call_llm` is a synchronous function that calls `openai.OpenAI(...).chat.completions.create(...)` under the hood. Calling it directly inside async code blocks the event loop.

**How to avoid:** Wrap with `await asyncio.to_thread(call_llm, ...)`. This dispatches the blocking call to the default thread pool and yields back to the event loop. Hermes' own `agent.plugin_llm.PluginLlm.acomplete()` uses an equivalent pattern (a registered `async_caller` or thread-offload, see `plugin_llm.py:777` — `async def acomplete`).

**Warning signs:** Other `agent:end` hooks (if any are added later) experience increased latency, or `agent:start` hooks for the NEXT message fire late.

### Pitfall 5: state.db read-only mode missing

**What goes wrong:** Handler does `sqlite3.connect(state_db_path)` without `?mode=ro`. Mid-handler, Hermes' own writer tries to commit a session-end row, hits a lock conflict with the handler's read transaction, and the handler sees `sqlite3.OperationalError: database is locked`. The handler's outer try/except (D-04) catches it and the turn is silently un-classified.

**Why it happens:** Default `sqlite3.connect` opens the file read-write and acquires journal locks.

**How to avoid:** `sqlite3.connect(f"file:{state_db_path}?mode=ro", uri=True)`. SQLite still supports concurrent reads against a WAL-mode writer this way without lock contention.

**Warning signs:** Markers appear inconsistently — particularly absent on busy sessions where Hermes is writing rapidly.

### Pitfall 6: D-13 tail-check race with self-classifying agent

**What goes wrong:** Agent self-classifies via SKILL.md FINAL ACTION code path, writes its GUARDRAIL+CHAT pair. A few hundred ms later, `agent:end` fires for the same turn. The hook reads the tail of the marker file, sees the agent's records, but doesn't recognize them as "this turn" because the `turn_seq` matching key isn't well-defined (markers don't carry an obvious "this turn" identifier — `muid` is random, `ts` is approximate).

**Why it happens:** Phase 2's marker schema doesn't include a `turn_seq` field by default (it's optional in MARK-02). The current SKILL.md FINAL ACTION snippet doesn't write `turn_seq` either.

**How to avoid:** Two viable approaches:
- (a) Tail-check by **wall-clock proximity** — read the last GUARDRAIL+CHAT pair; if their `ts` is within (e.g.) 30 seconds of `time.time()`, treat as "this turn." Cheap and good enough.
- (b) Coordinate by **process pid** — add a `pid` optional field to the marker schema. The agent's `execute_code` runs in a subprocess with a known pid; the hook runs in the gateway process. If markers in the last 30s carry `pid != os.getpid()`, the agent already wrote them.

For v1, recommend (a). It's simpler, doesn't change the marker schema, and the consequence of a false negative (double-write) is bounded — the cron muid-dedup prevents wire-level double-emission. The consequence of a false positive (hook skips when agent failed silently) is also bounded — that's exactly the failure mode Phase 6 is meant to repair, and the next turn would re-classify.

**Warning signs:** Marker files showing 4 records per turn (2 from agent + 2 from hook) instead of 2.

### Pitfall 7: Hook ships in skill, but `hermes skills install` lands it in the wrong place

**What goes wrong:** A user installs the skill via `hermes skills install revenium/hermes-revenium/skills/revenium --force`. The whole tree, including `hooks/revenium-classifier/`, lands at `~/.hermes/skills/revenium/hooks/revenium-classifier/`. `HookRegistry.discover_and_load()` scans `~/.hermes/hooks/` (NOT `~/.hermes/skills/*/hooks/`). The hook never loads.

**Why it happens:** `tools/skills_hub.py::install_from_quarantine` does a flat `shutil.move(quarantine, ~/.hermes/skills/<name>/)` with no special handling for `hooks/` subdirectories.

**How to avoid:** The operator install path (whether via `examples/setup-local.sh` or via `hermes skills install` + a documented post-install step) must include:
```bash
mkdir -p "${HOME}/.hermes/hooks"
rm -rf "${HOME}/.hermes/hooks/revenium-classifier"
cp -R "${HOME}/.hermes/skills/revenium/hooks/revenium-classifier" "${HOME}/.hermes/hooks/revenium-classifier"
```
For `setup-local.sh` (controlled path): straightforward — extend the script.
For `hermes skills install` (uncontrolled path): document the post-install step in `references/setup.md` and ship a `scripts/install-hook.sh` helper.

**Warning signs:** Skill is installed but no marker files appear for a verified-substantive turn, and gateway logs show no `[hooks] Loaded hook 'revenium-classifier'` line.

### Pitfall 8: `task=...` argument to `call_llm` overriding the user's model

**What goes wrong:** Handler calls `call_llm(task="title_generation", messages=...)`. If the operator has configured `auxiliary.title_generation.provider/model` in `config.yaml` (which is common — title generation often goes to a smaller/cheaper model), the classifier's calls go to THAT model rather than the user's main budgeted model. This breaks D-06's "Revenium-budgeted model" invariant.

**Why it happens:** `call_llm`'s `task=` arg means "use this task's auxiliary override if configured, else fall through to main." If no override is configured, the behavior is identical to omitting `task=`. If an override IS configured, the task arg silently re-routes.

**How to avoid:** Either:
- Omit `task=` entirely so the call uses `model.provider` + `model.default` from `config.yaml`. **This is the literal reading of D-06.**
- Define a new task name (`"classifier"` or `"revenium_classifier"`) that the operator can override but defaults to the main model. Slightly more configurable but adds a knob.

For v1, recommend omitting `task=`. The classifier is meant to be Revenium-budgeted by default; if an operator wants to route it to a cheaper model in the future, that's a v2 enhancement.

**Warning signs:** Revenium analytics show a different model for classifier rows than for work-turn rows. Hard to detect without specifically looking.

### Pitfall 9: Phase 2's pseudo-sid contamination

**What goes wrong:** The hook writes markers to `~/.hermes/state/revenium/markers/<sid>.jsonl` where sid is the canonical state.db session id (e.g., `20260513_130155_88925eaf`). Meanwhile, Phase 2's FINAL ACTION code path on the SAME session writes to `markers/pseudo-<unixts>.jsonl` because `HERMES_SESSION_ID` isn't propagated to `execute_code` subprocesses. The cron sees two marker files for the same logical session and double-reports.

**Why it happens:** Phase 3 partial workaround (`7613c0f`): the agent's FINAL ACTION snippet now derives sid from the newest session jsonl filename, which produces the canonical sid for primary sessions. But subagent FINAL ACTION code (if it ran) would still fall through to `pseudo-<ts>` because the newest session jsonl might be the parent's, not the subagent's. The cron's `parse_prior_state` keys idempotency by sid, not by filename — two files for two different sids both reporting against the same `state.db.sessions` row would be a problem.

**How to avoid:** The hook is the canonical writer for sid `XXX.jsonl`. For subagents, the hook inherits parent task_type and writes to `<subagent_sid>.jsonl` (which the cron will reconcile against `state.db` rows where `id = <subagent_sid>`). The agent-side FINAL ACTION snippet should never run for subagents because they don't load skills (PIT Phase 3 UAT finding #4: "Subagent sessions don't inherit skills"). So the duplicate-write risk only exists for primary sessions where BOTH the hook and the agent self-classified — D-13 tail-check handles this.

**Warning signs:** `pseudo-*.jsonl` files appearing alongside `<canonical_sid>.jsonl` files in `~/.hermes/state/revenium/markers/`.

## Code Examples

### Skeleton: complete handler.py

```python
# Source: derived from gateway/hooks.py contract + agent/auxiliary_client.py API +
# skills/revenium/SKILL.md FINAL ACTION snippet (Phase 2). Verified live on Mac Studio 2026-05-13.
"""Revenium classifier hook for Hermes agent:end events.

Reads the just-completed turn's session_id from the hook context, classifies
substantive turns via the budgeted LLM, and writes the Phase 2 marker pair
(GUARDRAIL + CHAT) at ~/.hermes/state/revenium/markers/<sid>.jsonl.

Skipped paths:
  - Trivial turns (≤ 2 sentences AND zero tools — D-07)
  - Subagents inherit parent's task_type (D-05) — no LLM call
  - Budget halted (D-08) — write 'unclassified' with WARN log
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger("revenium_classifier")

# Path defaults match scripts/common.sh — see Phase 1 path discipline.
HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
STATE_DIR   = Path(os.environ.get("REVENIUM_STATE_DIR", str(HERMES_HOME / "state" / "revenium")))
MARKERS_DIR = Path(os.environ.get("REVENIUM_MARKERS_DIR", str(STATE_DIR / "markers")))
TAXONOMY_FILE = Path(os.environ.get("REVENIUM_TAXONOMY_FILE", str(STATE_DIR / "task-taxonomy.json")))
BUDGET_STATUS_FILE = STATE_DIR / "budget-status.json"
STATE_DB = HERMES_HOME / "state.db"
SESSIONS_DIR = HERMES_HOME / "sessions"

LABEL_RE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
TRIVIAL_BLOCKLIST = {"ack", "acknowledgment", "greeting", "confirmation", "hello", "thanks"}

async def handle(event_type: str, context: dict) -> None:
    if event_type != "agent:end":
        return
    sid = context.get("session_id")
    if not sid:
        return
    try:
        # Step 1 — subagent inheritance (D-05). If this is a subagent, no LLM call.
        root_sid = _walk_to_root_session(sid)
        if root_sid != sid:
            parent_task = _read_latest_task_type(root_sid)
            if parent_task:
                await asyncio.to_thread(_write_marker_pair, sid, parent_task)
                return
            # Parent has no marker yet — fall through to classify as if this were root.

        # Step 2 — heuristic skip-fast-path (D-07).
        response_preview = context.get("response", "") or ""
        tool_count = _count_tools_in_current_turn(sid)
        if tool_count == 0 and len(response_preview) < 200:
            return  # trivial — skip marker entirely

        # Step 3 — D-13 belt: did the agent already self-classify?
        if _recent_marker_pair_exists(sid, within_seconds=30):
            return  # agent's FINAL ACTION ran; don't double-write

        # Step 4 — budget gate (D-08).
        if _budget_halted():
            await asyncio.to_thread(_write_marker_pair, sid, "unclassified")
            logger.warning("revenium-classifier: budget halted, wrote unclassified for sid=%s", sid)
            return

        # Step 5 — LLM classification (D-06).
        task_type = await _classify_via_llm(context, response_preview)
        if not task_type or task_type in TRIVIAL_BLOCKLIST or not LABEL_RE.match(task_type):
            task_type = "unclassified"

        # Step 6 — atomic write of GUARDRAIL + CHAT pair (D-10, D-14).
        await asyncio.to_thread(_write_marker_pair, sid, task_type)

    except Exception as exc:  # D-04: never raise out
        logger.warning("revenium-classifier hook failed for sid=%s: %s", sid, exc)


# … helper implementations (_walk_to_root_session, _count_tools_in_current_turn,
# _read_latest_task_type, _recent_marker_pair_exists, _budget_halted,
# _classify_via_llm, _write_marker_pair, _muid) per the patterns in this RESEARCH.
```

### Test fixture: synthetic agent:end payload

```python
# tests/test_repository.py — new test method, planner refines naming
import asyncio
import sys
from pathlib import Path

def test_revenium_classifier_handler_trivial_skip(self):
    """A turn with no tools and a short response must skip marker write."""
    HOOK_DIR = SKILL / 'hooks' / 'revenium-classifier'
    sys.path.insert(0, str(HOOK_DIR))
    import handler  # imports the hook module
    # The synthetic payload mimics what gateway/run.py:7631 emits.
    context = {
        "platform": "telegram",
        "user_id": "test-user",
        "session_id": "test-sid-trivial",
        "message": "good morning",
        "response": "Good morning!",  # < 200 chars; tool_count == 0 from missing session jsonl
    }
    # Patch out network and DB access — handler must fall through cleanly.
    # (Detail left to planner — could use unittest.mock or env redirection to a tmpdir.)
    asyncio.run(handler.handle("agent:end", context))
    # Assert no marker file was created.
    self.assertFalse((MARKERS_DIR / "test-sid-trivial.jsonl").exists())
```

The planner is expected to design tests with proper tmpdir isolation (matching `test_cron_marker_split_end_to_end`'s pattern of redirecting `HERMES_HOME` and `REVENIUM_STATE_DIR` to a temp tree). At least three cases per SC2/SC3/SC4:
- Trivial turn → skip (no marker file)
- Substantive turn with halted budget → `unclassified` marker pair
- Substantive turn with parent_session_id set → marker pair with parent's task_type

The Phase 2 marker-schema test (`test_marker_file_schema`) and the cron end-to-end test (`test_cron_marker_split_end_to_end`) already cover wire-level correctness — the new tests focus on classifier semantics.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Phase 2's soft prompt enforcement (SKILL.md FINAL ACTION block) was the sole mechanism for marker writes | Phase 6 adds mechanical enforcement via `agent:end` hook; SKILL.md FINAL ACTION stays as belt-and-suspenders (D-17) | 2026-05-13 (Phase 3 UAT findings) | Markers appear deterministically regardless of agent compliance — including for subagent sessions that don't load skills |
| `HERMES_SESSION_ID`-based sid resolution with newest-session-file fallback (Phase 2 commit `7613c0f`) | Hook reads `context["session_id"]` directly | This phase | No more pseudo-sid contamination on the canonical path; FINAL ACTION snippet retained for sessions where the hook didn't load |
| Cron pipeline treats missing markers as a session-wide problem and falls through to `unclassified` for the whole delta | Same cron pipeline (D-18 — unchanged); just less likely to hit the no-marker path now | This phase | More turns get a meaningful task_type; `unclassified` becomes an edge case rather than the default |
| Phase 2 docs prescribe the agent reads taxonomy and mints labels | Phase 6 makes the LLM do this from inside the hook, but using the same taxonomy file and the same regex/blocklist contract | This phase | Taxonomy growth shifts from "whenever the agent classifies" to "whenever a substantive turn yields and the hook can't fit an existing label" — slightly more controlled growth |

**Deprecated / outdated:**
- The "Hermes-natively supports `hermes hooks list` for event-hook discovery" framing from CONTEXT.md D-02 and ROADMAP SC1 is incorrect — see Conflict Watchlist. Use gateway log inspection instead.
- The `hermes hooks test agent:end --payload-file <fixture>` framing from CONTEXT.md "Specific Ideas" and ROADMAP SC2 is incorrect — `hermes hooks test` dispatches to shell hooks only. Test via direct invocation of `handler.handle` in a Python unit test.

## Conflict Watchlist

These items in CONTEXT.md or ROADMAP.md are contradicted by the live Hermes source. Severity is the orchestrator's call; this section labels each finding so the orchestrator can decide whether to halt for a discussion round or proceed with a wording fix during planning.

| # | Conflict | Severity | Recommendation |
|---|----------|----------|----------------|
| C1 | CONTEXT.md D-02 says hook discovery "succeeds under `hermes hooks list`." ROADMAP SC1 repeats this. The `hermes hooks` CLI is for SHELL hooks declared in `config.yaml`, NOT for the Python event hooks in `~/.hermes/hooks/`. | MEDIUM | Reword: use "gateway startup log line `[hooks] Loaded hook 'revenium-classifier' for events: ['agent:end']`" OR a one-liner `python3 -c "from gateway.hooks import HookRegistry; r=HookRegistry(); r.discover_and_load(); print(r.loaded_hooks)"` for operator verification. Locked decision still valid; wording needs revision in the plan. |
| C2 | CONTEXT.md "Specific Ideas" and ROADMAP SC2 say "Verified via `hermes hooks test agent:end --payload-file <fixture>`." This CLI dispatches only to shell hooks. | MEDIUM | Reword: tests invoke `handler.handle(event_type, context)` directly from a Python unit test with a synthetic context dict. Same fixture content (JSON payload), different execution mechanism. |
| C3 | CONTEXT.md D-15(a) suggests `hermes skills install` MAY automatically install the hook by recognizing a `hooks/` subdirectory. The installer's `install_from_quarantine` does a flat `shutil.move` with no such handling. | LOW | (a) is impossible without modifying Hermes. Default to (b). Adopt explicitly in the plan: `examples/setup-local.sh` does the copy; document the same step for `hermes skills install`-based installs. |
| C4 | CONTEXT.md "Deferred Ideas" notes "Hook hot-reload" as a v2. The current state is even stricter: no reload mechanism at all; `hermes gateway restart` is required for any change to take effect. | LOW | No action needed — the deferred note matches reality. Just ensure operator instructions are explicit. |

**Severity rubric:**
- **HIGH:** Locked decision is unimplementable as worded; must halt for re-discussion.
- **MEDIUM:** Wording must change but the underlying design holds. Planner can fix during plan composition.
- **LOW:** Cosmetic / documentation drift.

No HIGH items found. The phase can proceed to planning with wording adjustments captured in the plan.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Hermes gateway runtime | Hook loading (gateway/hooks.py) | ✓ (Mac Studio) | git HEAD as of 2026-05-10 | None — Hermes is the host. |
| Python 3.11 (Hermes venv) | handler.py | ✓ | 3.11 | None |
| `agent.auxiliary_client.call_llm` | LLM classification (D-06) | ✓ | in-tree, ~4k LOC | Direct `httpx` to provider base_url + API key from auth store |
| `~/.hermes/state.db` (sqlite) | Subagent parent walk (D-05) | ✓ | WAL mode, schema verified | None — required by Phase 6; if absent the handler falls through to `unclassified` cleanly via try/except |
| `pyyaml` | HOOK.yaml parsing (done by HookRegistry, not by handler) | ✓ | 6.0.3 | None |
| `httpx` | Fallback if `call_llm` unavailable | ✓ | 0.28.1 | None |
| `openai` SDK | Used by `call_llm` internally | ✓ | 2.32.0 | None |
| `hermes gateway restart` capability | Operator post-install step | ✓ | available as `hermes gateway restart` (launchd service mgmt) | If gateway not installed as service, operator can kill+restart manually; documented |
| Phase 3 cron pipeline | Consumer of marker files | ✓ | shipped in Phase 3, 14/14 tests green | None — required and present |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None.

**Caveat:** This audit reflects the Mac Studio at 172.16.1.175 as of 2026-05-13. Other operator hosts may have older Hermes installs; the plan should include a minimum-Hermes-version note in `references/setup.md` (e.g., "Requires Hermes with `gateway/hooks.py::HookRegistry` — present since [commit hash]"). Verifying the minimum-version cutoff is out of scope for this research; the planner may want to capture it during Wave 0.

## Project Constraints (from CLAUDE.md)

These are LOAD-BEARING directives the planner must honor:

1. **State path discipline:** All runtime paths originate in `scripts/common.sh`. Even though the handler is Python, the values it reads (`HERMES_HOME`, `REVENIUM_STATE_DIR`, `STATE_DIR`, etc.) must match `common.sh`'s defaults. `test_runtime_paths_are_hermes_native` (`tests/test_repository.py:65-77`) is the authoritative check — the planner should extend it if any new state path is introduced (none expected).
2. **No new runtime deps:** Stdlib Python + POSIX shell only. The handler imports Hermes-internal modules (`agent.auxiliary_client`) which are not a runtime dep of THIS repo — they're a dep of Hermes itself, satisfied by the operator already running Hermes.
3. **Idempotency:** Hook's marker writes must not double-emit on retry. The combination of (cron's per-muid global dedup) + (D-13 tail-check belt) covers this.
4. **Backward compatibility:** Existing installs without the hook must continue to meter exactly as today. Verified by D-17 (SKILL.md unchanged) + D-18 (cron unchanged). The hook is additive — its absence yields the current behavior.
5. **Legacy branding guard:** New hook handler / HOOK.yaml / docs MUST NOT contain the forbidden tokens. The regex is in `tests/test_repository.py:61` (do not reproduce here per CLAUDE.md). When porting any text from upstream Hermes docs into our docs, scrub.
6. **Frontmatter contract preserved:** SKILL.md unchanged per D-17. The `name: revenium`, `metadata.hermes`, `category: devops` invariants remain in force.
7. **Bash strictness:** Any new bash code (e.g., extending `setup-local.sh`) follows the existing `set -euo pipefail` convention.
8. **`test_no_legacy_branding_left` scoping fix preserved:** `.planning/` is excluded from the scan (commit `a273c06`). The new hook directory will be scanned because it's outside `.planning/`.
9. **No writes to `state.db`:** Read-only (`?mode=ro`) connection enforced in the handler. This is a project invariant.

## Assumptions Log

> Below is the list of claims in this research that are tagged `[ASSUMED]` or that the planner / discuss-phase may want to confirm. The intent is to surface decisions that need user-confirmation BEFORE plan composition, not after.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The handler should `await asyncio.to_thread(call_llm, ...)` rather than instantiate an httpx client directly | Pattern 3, Pitfall 4 | If `call_llm` is unstable across Hermes versions or its `task=`/no-task behavior shifts, the classifier could route to the wrong model. Lower-risk alternative is direct httpx with config.yaml-resolved base_url+api_key, but ~3x more code. **Tagged [ASSUMED] — planner can confirm or pivot.** |
| A2 | D-13 tail-check should use a 30-second wall-clock proximity heuristic rather than introducing a new `turn_seq` or `pid` marker field | Pitfall 6 | If the agent + hook somehow race outside 30 seconds (extreme system load), the hook may double-write. Cron dedup prevents wire double-emission. **Tagged [ASSUMED]; planner may prefer (b) pid-based approach.** |
| A3 | `task=` argument to `call_llm` should be OMITTED so the classifier uses the main `model.provider`+`model.default` from config.yaml (matches D-06 "Revenium-budgeted model" wording) | Pitfall 8, Pattern 3 | If a future operator has a different model configured for their main provider than they want billed for classification, they'd need a v2 knob. Low risk. **Tagged [ASSUMED]; alternative is `task="classifier"` with a default config block.** |
| A4 | Heuristic skip-fast-path threshold should be "tool_count == 0 AND response_preview < 200 chars" rather than the binary "≤ 2 sentences AND zero tools" from D-07 (which can't be evaluated from the 500-char-truncated context) | Pattern 5, Pitfall 3 | If 200 chars is wrong (some genuinely substantive turns are < 200 chars, e.g. "here's the answer: 42 — calculated as X * Y * Z"), we miss those classifications. Low-impact: classifier just doesn't fire on that turn. **Tagged [ASSUMED]; planner may prefer to also check session jsonl word count.** |
| A5 | The hook does NOT need to read `~/.hermes/config.yaml` for provider/auth resolution — `call_llm` handles it | Pattern 3 | If `call_llm`'s resolution chain fails silently for some operator's config shape, the handler gets no classification. The handler should catch the exception and fall through to `unclassified`. Low risk. |
| A6 | The hook's HOOK.yaml does NOT need a config.yaml-level `hooks:` entry — auto-discovery from `~/.hermes/hooks/` is sufficient | Architecture diagram, Pattern 1 | The empty `hooks: {}` block in config.yaml today (per CONTEXT.md canonical_refs) is for shell hooks, not event hooks. Event hooks are discovered from the filesystem directly. **Confidence HIGH — verified by reading `discover_and_load`.** |
| A7 | The planner should NOT add `--task-type` arg passthrough to the hook handler — the hook writes markers; the cron reads them and emits `--task-type` to Revenium. The wire boundary is unchanged | Locked Decisions Acknowledged (D-18), Architecture diagram | Sanity check — re-confirms the cron is the ONLY caller of `revenium meter completion`. Verified by re-reading `hermes-report.sh`. |

**If items A1-A4 are unconfirmed before planning:** flag the plan as having configurable design points. The plan can ship the recommended choice with a comment block explaining the alternative. None of these are HIGH-risk — all degrade gracefully.

## Open Questions

1. **Minimum supported Hermes version.**
   - **What we know:** `HookRegistry` was present in the Mac Studio build as of git HEAD 2026-05-10. The exact commit that introduced it is not part of this research.
   - **What's unclear:** Operators on older Hermes installs won't have the event-hook system at all — the hook would be installed but never load, with no error message except a missing log line.
   - **Recommendation:** During planning Wave 0, run `cd ~/.hermes/hermes-agent && git log --diff-filter=A --format='%h %ai %s' -- gateway/hooks.py | tail -1` to find the introducing commit, then document the minimum version in `references/setup.md`. If the file is brand new (which it appears to be given the inline test references), document "Hermes ≥ <commit-or-tag> required."

2. **Whether `subagent_stop` (the SHELL-hook event in `VALID_HOOKS`) is an alternative entry point.**
   - **What we know:** The shell-hook system supports a `subagent_stop` event (`hermes_cli/plugins.py:148`). This fires from the same code path that the event-hook system fires `agent:end` from.
   - **What's unclear:** Whether using a shell hook would be simpler than an event hook. Shell hooks have a CLI (`hermes hooks list/test/doctor`) — better operator UX. But they run as subprocesses (not in-process Python), which means no shared `call_llm` access and significantly more overhead per turn.
   - **Recommendation:** Reject for v1. Event hooks are the right tool — in-process, async, full Python access, low latency. The CLI gap is solved by documenting `hermes gateway restart` and gateway log inspection. **No further investigation needed unless the operator UX gap becomes painful in practice.**

3. **Whether subagent classification can leak across delegate_task lineages.**
   - **What we know:** D-05 walks `parent_session_id` to root and inherits the root's task_type. If a parent has multiple children with different semantic activities (rare but possible — e.g., a planning session that spawns one research subagent AND one code-review subagent), all children get the same root task_type.
   - **What's unclear:** Whether this matches what operators want. The decision was locked at "single classification per request lineage," but the corner case of fan-out subagents wasn't explicitly discussed.
   - **Recommendation:** Honor D-05 as locked. The fan-out case is acceptable degradation — the per-activity granularity is at the turn level within a session; subagent fan-out attributes all child spend to the parent's activity bucket. Revenium analytics can drill down by `session_id` if finer breakdown is needed in a future v2.

4. **Whether the hook should write a marker for itself when it makes an LLM call.**
   - **What we know:** D-10 says "two marker records per substantive turn — one with `operation_type = "GUARDRAIL"` (the classification span; tokens spent BY THE HOOK on the LLM call) and one with `operation_type = "CHAT"` (the work span; tokens spent BY THE AGENT on the actual turn)." So yes — the hook attributes its own LLM cost to the GUARDRAIL record. Good.
   - **What's unclear:** Whether the GUARDRAIL record's `task_type` should be the SAME as the CHAT record (current Phase 2 convention) or `classifier` (more semantically accurate). D-10 wording doesn't pin this; the Phase 2 SKILL.md snippet uses the same task_type for both.
   - **Recommendation:** Use the same `task_type` for both records, matching Phase 2's pattern. The `operation_type` field already discriminates between work and classifier overhead. Don't fragment the taxonomy with a "classifier" entry.

## Validation Architecture

> The project's `.planning/config.json` sets `workflow.nyquist_validation: false`. This section is included anyway per the researcher instruction for completeness; the planner may skip it in PLAN.md per Nyquist gate semantics.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Python stdlib `unittest` |
| Config file | None — discovery via `python3 -m unittest discover -s tests -p 'test_*.py' -v` |
| Quick run command | `python3 -m unittest tests.test_repository.RepositoryTests.<test_method> -v` |
| Full suite command | `python3 -m unittest discover -s tests -p 'test_*.py' -v` |

### Phase Requirements → Test Map

| Suggested Req ID | Behavior | Test Type | Automated Command | File Exists? |
|------------------|----------|-----------|-------------------|-------------|
| HOOK-01 | Files exist + frontmatter shape | unit | `python3 -m unittest tests.test_repository.RepositoryTests.test_expected_files_exist -v` | ✓ (extend existing) |
| HOOK-02 | Heuristic skip on trivial turn | unit | `python3 -m unittest tests.test_repository.RepositoryTests.test_revenium_classifier_trivial_skip -v` | ❌ Wave 0 |
| HOOK-03 | Subagent inheritance | unit | `python3 -m unittest tests.test_repository.RepositoryTests.test_revenium_classifier_subagent_inherits -v` | ❌ Wave 0 |
| HOOK-04 | Budget halt gate | unit | `python3 -m unittest tests.test_repository.RepositoryTests.test_revenium_classifier_halt_unclassified -v` | ❌ Wave 0 |
| HOOK-05 | LLM classification + validation | unit (with mocked call_llm) | `python3 -m unittest tests.test_repository.RepositoryTests.test_revenium_classifier_llm_label -v` | ❌ Wave 0 |
| HOOK-06 | Marker pair write + schema | unit | `python3 -m unittest tests.test_repository.RepositoryTests.test_revenium_classifier_marker_pair -v` | ❌ Wave 0 |
| HOOK-07 | D-13 tail-check skip on existing pair | unit | `python3 -m unittest tests.test_repository.RepositoryTests.test_revenium_classifier_dedupe -v` | ❌ Wave 0 |
| HOOK-08 | setup-local.sh copies hook | integration (script invocation) | extend existing if-present check OR run script in tmpdir | ❌ Wave 0 |
| HOOK-09 | Full suite still green | regression | `python3 -m unittest discover -s tests -p 'test_*.py' -v` | ✓ |
| HOOK-10 | references/setup.md content | unit (string presence) | extend `test_expected_files_exist`-style content check | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `python3 -m unittest tests.test_repository.RepositoryTests.test_revenium_classifier_<specific> -v`
- **Per wave merge:** `python3 -m unittest discover -s tests -p 'test_*.py' -v`
- **Phase gate:** Full suite green before `/gsd-verify-work 6`

### Wave 0 Gaps

- [ ] `tests/test_repository.py::test_revenium_classifier_trivial_skip` — covers HOOK-02
- [ ] `tests/test_repository.py::test_revenium_classifier_subagent_inherits` — covers HOOK-03
- [ ] `tests/test_repository.py::test_revenium_classifier_halt_unclassified` — covers HOOK-04
- [ ] `tests/test_repository.py::test_revenium_classifier_llm_label` — covers HOOK-05 (mocks `agent.auxiliary_client.call_llm`)
- [ ] `tests/test_repository.py::test_revenium_classifier_marker_pair` — covers HOOK-06
- [ ] `tests/test_repository.py::test_revenium_classifier_dedupe` — covers HOOK-07
- [ ] `skills/revenium/hooks/revenium-classifier/test-payloads/` — synthetic agent:end payload fixtures
- [ ] Conditional skip mechanism: tests that import `handler` only run if `agent.auxiliary_client` is importable (allow CI without Hermes venv to skip cleanly with `unittest.skipUnless`)

**No framework install needed:** stdlib unittest covers everything. Mocks via `unittest.mock`.

## Security Domain

> Project does not set `security_enforcement: false`. Including per researcher instruction. Phase 6 introduces an in-process LLM call inside the gateway event loop and a new read of `state.db` — both are MEDIUM-impact surface.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | The hook does not authenticate users; it inherits the gateway's already-authenticated session context |
| V3 Session Management | no | The hook reads session_id passively; it does not mint sessions |
| V4 Access Control | partial | The hook reads `state.db` (read-only) and the markers directory; both already have OS-level permissions (`chmod 700` on markers dir from Phase 1 PATH-02). No new access surface |
| V5 Input Validation | yes | The LLM's returned `task_type` is validated against the regex `^[a-z][a-z0-9_]{1,47}$` and the trivial-label blocklist. A malicious or compromised LLM response cannot inject arbitrary characters into the marker file or downstream Revenium API call |
| V6 Cryptography | no | No new crypto. Marker `muid` uses `secrets.token_hex(10)` which is `secrets`-grade randomness — same as Phase 2 |

### Known Threat Patterns for Hermes Hook + In-Process Python

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Hook handler exception crashes gateway | Denial of Service | `HookRegistry.emit()` catches all exceptions (`gateway/hooks.py:175-180`). Handler must NEVER raise (D-04). Defense-in-depth: outer try/except in `handle()` |
| Malformed `task_type` from LLM injects into marker file or downstream `revenium meter completion` argv | Tampering | Regex validation `^[a-z][a-z0-9_]{1,47}$` rejects non-snake_case. Trivial-label blocklist rejects pollution labels. Cron-side validation (already shipped) is defense-in-depth |
| Race on marker file write between hook and SKILL.md FINAL ACTION code path | Tampering / Repudiation | `fcntl.LOCK_EX` serializes writes within a session. Tail-check (D-13) deduplicates. Cron's per-muid global dedup is the wire-level safety net |
| Long-running `call_llm` blocks event loop, starving other hooks or sessions | Denial of Service | `asyncio.to_thread(call_llm, ...)` offloads to thread pool. Configure `timeout=10.0` on the `call_llm` call so worst-case is bounded |
| Information leakage: response preview (500 chars) sent to classifier LLM contains sensitive content | Information Disclosure | The classifier LLM IS the user's main budgeted model — it already received the full response when producing it. Sending a 500-char preview back to the same model is not new disclosure |
| `parent_session_id` chain corruption causes infinite recursion | DoS | `max_depth=10` cap on chain walk |
| Malicious HOOK.yaml in a tap'd skill installs code that runs in-gateway-process | Elevation of Privilege | Out of scope for THIS phase — `hermes skills install` does scan for trust signals via `tools.skills_guard.scan_skill`. The phase doesn't change that surface. For Revenium's own hook, the trust gate is "this is our own repo" |
| `agent.auxiliary_client.call_llm` exception during high-load can leak partial response | Information Disclosure | Handler catches all exceptions and falls through to `unclassified`. No partial state written |

**Mitigation summary:** Every new attack surface in Phase 6 is bounded by an existing project invariant (file permissions, regex validation, exception isolation, fcntl serialization, cron-side double-dedupe). No new crypto, no new auth surface, no new network egress not already authorized by the user's Revenium provider config. The most significant new surface is "LLM output feeds a regex" — handled by Pitfall 8 / Pattern 3 / HOOK-05 / D-09 in concert.

## Sources

### Primary (HIGH confidence)

- **`~/.hermes/hermes-agent/gateway/hooks.py`** (live, read 2026-05-13 via SSH) — Hook registry, discovery, emit semantics, error isolation. Sources for Gate 1 entry-point shape, Gate 4 single-load-at-startup, handler signature contract.
- **`~/.hermes/hermes-agent/gateway/run.py:7479-7633`** (live, read 2026-05-13) — `hook_ctx` construction for `agent:start` (subset) and `agent:end` (extended with `response[:500]`). Sources Gate 1 payload contents.
- **`~/.hermes/hermes-agent/agent/auxiliary_client.py:3887-3960`** (live, read 2026-05-13) — `call_llm` signature, provider resolution, task arg semantics. Sources Gate 2 LLM call mechanism.
- **`~/.hermes/hermes-agent/agent/plugin_llm.py:1-50, 595-700`** (live, read 2026-05-13) — Plugin LLM facade docstring and PluginLlm class — explains why plugin_llm is NOT the right path for hooks. Sources Gate 2 alternative-rejected.
- **`~/.hermes/hermes-agent/tools/skills_hub.py:2750-2820, 326-660`** (live, read 2026-05-13) — `install_from_quarantine`, `GitHubSource._download_directory_via_tree`. Sources Gate 3 distribution behavior.
- **`~/.hermes/hermes-agent/hermes_cli/hooks.py:1-200`** (live, read 2026-05-13) — Confirms `hermes hooks list/test` is for shell hooks only. Sources Conflict Watchlist C1+C2.
- **`~/.hermes/hermes-agent/hermes_cli/plugins.py:128-180, 287-310`** (live, read 2026-05-13) — `VALID_HOOKS` constant (shell-hook event names), `PluginContext.llm`. Sources distinction between hook subsystems.
- **`~/.hermes/state.db` schema** (live SQL inspection 2026-05-13) — `sessions` table with `parent_session_id` foreign key + `idx_sessions_parent` index, 363 rows with 5 having parents confirmed. Sources Pattern 4.
- **`~/.hermes/sessions/*.jsonl`** (live sample inspected 2026-05-13) — Session transcript format with `{role, content, name, tool_call_id, reasoning, timestamp}` shape. Sources Pattern 5.
- **`~/.hermes/state/revenium/markers/20260513_125139_f6c9a4b3.jsonl`** (live sample inspected 2026-05-13) — Real-world marker file produced by the Phase 2 commit `02eadae`. Sources Pitfall 9 (pseudo-sid contamination).
- **`skills/revenium/SKILL.md`** lines 279-398 — FINAL ACTION block; canonical Phase 2 marker snippet (D-17 unchanged invariant).
- **`skills/revenium/scripts/hermes-report.sh:200-360`** — Cron marker reader (D-18 unchanged consumer).
- **`skills/revenium/scripts/split_strategies.py`** — `parse_prior_state` global muid dedup contract.
- **`tests/test_repository.py`** — All current invariants the planner must respect.

### Secondary (MEDIUM confidence)

- **`~/.hermes/hermes-agent/venv/lib/python3.11/site-packages/`** dir listing (live) — package versions for httpx/openai/anyio/pyyaml. Verified by file presence, not by version field parsing.
- Hermes CLI behavior `hermes hooks --help` and `hermes gateway --help` outputs — captured directly from `~/.hermes/hermes-agent/venv/bin/python3 ~/.hermes/hermes-agent/hermes <cmd> --help`. Authoritative for the shipped CLI behavior on this host.

### Tertiary (LOW confidence — none)

No tertiary sources needed. Every load-bearing finding has a verifiable source on the Mac Studio.

## Metadata

**Confidence breakdown:**
- Gate 1 (`agent:end` payload shape): HIGH — read the emitting code directly.
- Gate 2 (LLM call mechanism): HIGH on surface (`call_llm` is importable, verified); MEDIUM on operational details (whether `asyncio.to_thread` is the right async pattern vs. `anyio.to_thread.run_sync` — both work; chose stdlib).
- Gate 3 (`hermes skills install` of `hooks/` subdir): HIGH — read the installer source.
- Gate 4 (hook reload semantics): HIGH — read the single-call site of `discover_and_load`.
- Standard stack: HIGH — every package version verified by live file inspection.
- Architecture: HIGH for the data flow; MEDIUM on the recommended exact `task=` arg shape (judgment call, see A3).
- Pitfalls: HIGH for documented + verified (1-3, 5, 7); MEDIUM for race-condition (6) and config-leak (8) cases that are model-dependent.
- Conflict Watchlist: HIGH on the facts; severity ratings are judgment calls.

**Research date:** 2026-05-13
**Valid until:** 2026-06-12 (30 days — Hermes is fast-moving; the `gateway/hooks.py` API shape could shift)
**Re-verify on:** any time before planning Phase 6's first plan, re-run `ssh 172.16.1.175 'grep -A5 "agent:end" ~/.hermes/hermes-agent/gateway/run.py | head -10'` to confirm the payload shape hasn't drifted.

---

*Phase: 06-mechanical-classification-agent-end-hook*
*Research conducted: 2026-05-13 via SSH inspection of the live Hermes installation at `johndemic@172.16.1.175`, cross-referenced with the existing skill at `skills/revenium/` and the Phase 2/3 deliverables in `.planning/`*
