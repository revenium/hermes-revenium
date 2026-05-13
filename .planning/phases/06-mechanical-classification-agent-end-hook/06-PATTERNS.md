# Phase 6: Mechanical Classification via Hermes agent:end Hook - Pattern Map

**Mapped:** 2026-05-13
**Files analyzed:** 7 (2 new, 5 modified/extended)
**Analogs found:** 5 / 7 (two patterns are NEW with no in-repo analog — HOOK.yaml shape and `agent.auxiliary_client.call_llm` import; both have canonical shapes captured inline from RESEARCH.md)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `skills/revenium/hooks/revenium-classifier/HOOK.yaml` | config (event-hook manifest) | event-driven (subscription) | none in-repo | NO ANALOG — use canonical shape from `~/.hermes/hermes-agent/gateway/hooks.py:79-130` |
| `skills/revenium/hooks/revenium-classifier/handler.py` | service (async event handler) | event-driven (LLM + file I/O) | `skills/revenium/scripts/split_strategies.py` (stdlib-only Python module) + SKILL.md FINAL ACTION snippet (lines 315-365) | PARTIAL — divergence: handler is async + imports Hermes-internal `agent.auxiliary_client.call_llm`; split_strategies is sync stdlib-only |
| `skills/revenium/hooks/revenium-classifier/test-payloads/*.json` | test fixture | static data | new — no in-repo analog | NO ANALOG — synthetic `agent:end` context JSON (shape from RESEARCH.md Gate 1) |
| `examples/setup-local.sh` (modified) | utility (install script) | file-I/O (copy) | same file's existing taxonomy-seed block (lines 12-20) | EXACT — same file, parallel idempotent copy step |
| `skills/revenium/references/setup.md` (modified) | docs | static content | same file's "How attribution works" block (lines 73-85) | EXACT — same file, parallel section |
| `tests/test_repository.py` (modified) | test | unit + integration | `test_cron_marker_split_end_to_end` (lines 291-470, tmpdir + env redirect pattern) + `test_taxonomy_atomic_write_pattern` (lines 103-174, fcntl flock pattern) | EXACT — same file, parallel test methods |
| `skills/revenium/SKILL.md` (possibly modified) | docs | static content | FINAL ACTION block (lines 279-397) — only if D-17 belt-suspenders pointer is added | EXACT — leave verbatim per D-17 unless planner adds optional cross-ref |

## Pattern Assignments

### `skills/revenium/hooks/revenium-classifier/HOOK.yaml` (config, event-driven)

**Analog:** NONE in repo. Canonical shape from `~/.hermes/hermes-agent/gateway/hooks.py:79-130` (Hermes discovery contract), captured in RESEARCH.md Pattern 1.

**Canonical content (copy verbatim, adjust description as needed):**

```yaml
name: revenium-classifier
description: Classifies each Hermes agent:end turn and writes a marker pair (GUARDRAIL + CHAT) for Revenium task-type attribution. See ~/.hermes/skills/revenium/ for the consumer pipeline.
events:
  - agent:end
```

**Required fields per `HookRegistry.discover_and_load()`:**
- `name` (string) — must equal the directory name `revenium-classifier`; appears in `[hooks] Loaded hook '<name>' for events: [...]` startup log.
- `events` (list of strings) — must include `agent:end` exactly.
- `description` (string) — optional, free-form.

**No other fields required.** Hermes ignores unknown keys. Parsed via `pyyaml` (already in Hermes venv).

---

### `skills/revenium/hooks/revenium-classifier/handler.py` (service, event-driven)

**Analog A (sync stdlib Python module shape):** `skills/revenium/scripts/split_strategies.py` — for module-level structure, docstring style, stdlib-only imports.

**Analog B (marker write pattern + muid + flock):** `skills/revenium/SKILL.md` lines 315-365 (FINAL ACTION execute_code snippet) — for the load-bearing marker pair write.

**Analog C (read budget-status.json):** `skills/revenium/scripts/budget-check.sh` lines 64-70 (Python heredoc) — for the fail-open read pattern.

**Analog D (LLM call):** NONE in repo. Canonical shape from `~/.hermes/hermes-agent/agent/auxiliary_client.py:3887` per RESEARCH.md Pattern 3.

**Module-level structure pattern** (from `split_strategies.py:1-25`):

```python
"""Module-level docstring explaining role + invariants + cross-refs.

Conservation invariant (or in our case: catch-and-log invariant from D-04).
"""
from decimal import Decimal  # one import per line; alphabetical

INT_FIELDS = ("input", "output", ...)  # module-level constants in SCREAMING_SNAKE_CASE
```

**Adapt to handler.py:**

```python
"""Revenium classifier hook for Hermes agent:end events.

Reads the just-completed turn's session_id from the hook context, classifies
substantive turns via the budgeted LLM, and writes the Phase 2 marker pair
(GUARDRAIL + CHAT) at ~/.hermes/state/revenium/markers/<sid>.jsonl.

Invariant (D-04): handle() MUST NOT raise — all exceptions caught + logged.
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

# Path defaults match scripts/common.sh
HERMES_HOME        = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
STATE_DIR          = Path(os.environ.get("REVENIUM_STATE_DIR", str(HERMES_HOME / "state" / "revenium")))
MARKERS_DIR        = Path(os.environ.get("REVENIUM_MARKERS_DIR", str(STATE_DIR / "markers")))
TAXONOMY_FILE      = Path(os.environ.get("REVENIUM_TAXONOMY_FILE", str(STATE_DIR / "task-taxonomy.json")))
BUDGET_STATUS_FILE = STATE_DIR / "budget-status.json"
STATE_DB           = HERMES_HOME / "state.db"
SESSIONS_DIR       = HERMES_HOME / "sessions"

LABEL_RE          = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
TRIVIAL_BLOCKLIST = {"ack", "acknowledgment", "greeting", "confirmation", "hello", "thanks"}

logger = logging.getLogger("revenium_classifier")
```

**Async handler signature pattern** (from RESEARCH.md Pattern 2; verified against `~/.hermes/hermes-agent/tests/gateway/test_hooks.py:144-148`):

```python
async def handle(event_type: str, context: dict) -> None:
    if event_type != "agent:end":
        return
    sid = context.get("session_id")
    if not sid:
        return
    try:
        # ... steps 1-6 per RESEARCH.md architecture diagram
        pass
    except Exception as exc:                                                # D-04 belt: never raise
        logger.warning("revenium-classifier hook failed for sid=%s: %s",
                       context.get("session_id", "?"), exc)
```

**Marker pair write pattern** (copy from `SKILL.md` lines 348-365, drop the sid-resolution dance since context provides sid directly):

```python
def _muid() -> str:
    # MARK-03: 13-char ms-timestamp hex (sortable) + 20-char random hex = 33 chars total
    return f"{int(time.time_ns() // 1_000_000):013x}" + secrets.token_hex(10)

def _write_marker_pair(sid: str, task_type: str) -> Path:
    MARKERS_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker_path = MARKERS_DIR / f"{sid}.jsonl"
    def _record(op: str) -> dict:
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

**Note the divergences from SKILL.md's snippet:**

1. No `HERMES_SESSION_ID`-resolution fallback — the hook receives `context["session_id"]` directly. The whole `sessions_dir` newest-file scan + `pseudo-<ts>` fallback in SKILL.md lines 318-342 is unnecessary in-process.
2. The two records ship in **two `write()` calls under one `flock()`** rather than two separate `write_marker()` invocations. POSIX guarantees `< PIPE_BUF` writes are atomic; `flock` covers the multi-call sequence.

**Budget-status read pattern** (mirrors `budget-check.sh:64-70` shape — try/except → empty default):

```python
def _budget_halted() -> bool:
    try:
        data = json.loads(BUDGET_STATUS_FILE.read_text())
        return bool(data.get("halted", False))
    except Exception:                                                       # fail-open per D-08
        return False
```

**state.db read-only subagent walk pattern** (NEW — no in-repo analog; canonical from RESEARCH.md Pattern 4):

```python
def _walk_to_root_session(sid: str, max_depth: int = 10) -> str:
    """Walk parent_session_id chain. Returns sid if it has no parent. Capped to defeat
    pathological parent loops. Read-only URI prevents WAL lock contention with Hermes writer."""
    try:
        uri = f"file:{STATE_DB}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            current = sid
            for _ in range(max_depth):
                row = conn.execute(
                    "SELECT parent_session_id FROM sessions WHERE id = ?", (current,)
                ).fetchone()
                if row is None or row[0] is None:
                    return current
                current = row[0]
            return current
    except sqlite3.OperationalError:                                        # locked / missing
        return sid                                                          # treat as root
```

**JSONL reader for tool-count + recent-marker check** (analog: `split_strategies.py::parse_prior_state` lines 113-149 — line-by-line read with per-line try/except, file-not-found fallback). Adapt for `~/.hermes/sessions/<sid>.jsonl` per RESEARCH.md Pattern 5.

**LLM call pattern (NEW — no in-repo analog; canonical from RESEARCH.md Pattern 3 + A3):**

```python
# Import is deferred — the hook may load on a system whose Hermes venv differs.
# Wrap import in try/except so test runs without Hermes can mock or skipUnless.
try:
    from agent.auxiliary_client import call_llm
except ImportError:
    call_llm = None  # handler falls through to unclassified if aux client unavailable

async def _classify_via_llm(user_msg: str, assistant_resp: str, labels: list[str]) -> str:
    if call_llm is None:
        return "unclassified"
    prompt = _build_classification_prompt(user_msg, assistant_resp, labels)
    response = await asyncio.to_thread(
        call_llm,
        # NOTE: omit `task=` per D-06 "Revenium-budgeted model" + A3 + Pitfall 8 — falls
        # through to the user's main model.provider/model.default from config.yaml
        messages=[
            {"role": "system", "content": "You classify Hermes turns into task_type labels."},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.0,
        max_tokens=64,
        timeout=10.0,
    )
    raw = response.choices[0].message.content.strip()
    return raw  # caller validates against LABEL_RE + TRIVIAL_BLOCKLIST
```

**Error handling pattern** (from `budget-check.sh:64-70` Python heredoc — bare `except Exception: pass`):

The handler wraps the ENTIRE handle() body in try/except per D-04. Sub-helpers use targeted try/except per failure mode (`sqlite3.OperationalError`, `OSError`, `json.JSONDecodeError`, `ImportError` for the aux client). Every fallthrough goes to `unclassified` rather than raising.

**Validation pattern** (LLM output against label regex + blocklist — same shape as cron-side defense at `hermes-report.sh:278`):

```python
FORBIDDEN = {'ack', 'acknowledgment', 'greeting', 'confirmation', 'hello', 'thanks'}
# After LLM call:
if not task_type or task_type in TRIVIAL_BLOCKLIST or not LABEL_RE.match(task_type):
    task_type = "unclassified"  # D-09: re-prompt once then fall back; planner picks impl
```

---

### `skills/revenium/hooks/revenium-classifier/test-payloads/*.json` (test fixture, static)

**Analog:** NONE in repo. Shape from RESEARCH.md Gate 1 (verified against `~/.hermes/hermes-agent/gateway/run.py:7479-7633`).

**Canonical synthetic `agent:end` context payload (one fixture per scenario):**

```json
{
  "platform": "telegram",
  "user_id": "test-user",
  "session_id": "20260513_120000_testtrivial",
  "message": "good morning",
  "response": "Good morning!"
}
```

**Three fixtures expected per RESEARCH.md "Recommended Project Structure":**

| Fixture file | Scenario | Distinguishing field |
|--------------|----------|----------------------|
| `trivial-turn.json` | `response` < 200 chars, no session jsonl ⇒ skip | `response: "Good morning!"` |
| `substantive-turn.json` | `response` ≥ 200 chars OR tools-in-jsonl > 0 ⇒ classify | `response` is a 500-char preview of a code-review reply |
| `subagent-turn.json` | state.db row has `parent_session_id` set ⇒ inherit | `session_id` matches a subagent row the test seeds in tmpdir state.db |

---

### `examples/setup-local.sh` (utility, file-I/O — MODIFIED)

**Analog:** Same file, existing taxonomy-seed block (lines 12-20).

**Imports pattern** (lines 1-5 — keep verbatim):

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${HOME}/.hermes/skills/revenium"
```

**Existing parallel copy pattern** (lines 12-20 — idempotent seed-only-if-missing):

```bash
STATE_DIR_DEFAULT="${REVENIUM_STATE_DIR:-${HOME}/.hermes/state/revenium}"
TAXONOMY_DEST="${REVENIUM_TAXONOMY_FILE:-${STATE_DIR_DEFAULT}/task-taxonomy.json}"
mkdir -p "$(dirname "${TAXONOMY_DEST}")"
if [[ ! -f "${TAXONOMY_DEST}" ]]; then
  cp "${REPO_ROOT}/skills/revenium/task-taxonomy.json" "${TAXONOMY_DEST}"
  echo "Seeded ${TAXONOMY_DEST}"
else
  echo "Taxonomy already exists at ${TAXONOMY_DEST}, not overwriting"
fi
```

**New section to add (per D-15(b) + Gate 3 + Pitfall 7 — hook is UNCONDITIONALLY replaced, not seed-only):**

```bash
# Phase 6: install the agent:end classifier hook into ~/.hermes/hooks/
# (skills/ tree does NOT auto-relocate hooks/ subdirs — confirmed Gate 3 / RESEARCH.md)
HOOKS_DIR="${HOME}/.hermes/hooks"
HOOK_TARGET="${HOOKS_DIR}/revenium-classifier"
mkdir -p "${HOOKS_DIR}"
rm -rf "${HOOK_TARGET}"
cp -R "${REPO_ROOT}/skills/revenium/hooks/revenium-classifier" "${HOOK_TARGET}"
echo "Installed hook to ${HOOK_TARGET}"
```

**"Next steps" extension (lines 23-27 — append a `hermes gateway restart` reminder per Pitfall 2):**

```bash
echo "Next steps:"
echo "  1. Verify Revenium CLI: revenium config show"
echo "  2. Install cron: bash ~/.hermes/skills/revenium/scripts/install-cron.sh"
echo "  3. Restart Hermes gateway to load the classifier hook: hermes gateway restart"
echo "  4. Start Hermes and load /revenium"
```

**Bash conventions to preserve:**

- `set -euo pipefail` (line 2) — KEEP. Hard-fail mode is correct for this orchestration script.
- Quoted expansions everywhere, `${var}` brace form, `[[ ... ]]` conditionals — KEEP.
- `# Phase 6:` prefix on the comment so future grep-ability ties the block to its requirement.

---

### `skills/revenium/references/setup.md` (docs, static content — MODIFIED)

**Analog:** Same file, "How attribution works" section (lines 73-85).

**Existing parallel section** (lines 73-85 — explanatory prose after the numbered setup steps):

```markdown
## How attribution works

GUARDRAIL share is overstated when work turns are much larger than classification turns. Read GUARDRAIL share as an upper bound, not an estimate. The S2 equal-split is intentionally simple and biases attribution toward classification overhead in mixed windows. Later strategies (S3 weighted, S4 guardrail-estimator) are deferred to v2.

The cron emits two S2 telemetry log lines per session per tick to make this visible to operators. ...
```

**New section to add (D-16 — placement: AFTER "How attribution works", per CONTEXT.md):**

Use the same H2 heading style + paragraph-prose voice. Required content per D-16 + RESEARCH.md Pitfalls 1, 2, 7 + Conflict C1:

```markdown
## Mechanical classification hook

Phase 6 ships an in-process Hermes lifecycle hook at `~/.hermes/hooks/revenium-classifier/` that classifies every `agent:end` turn and writes the GUARDRAIL + CHAT marker pair the cron consumes. This hook is the mechanical floor — it fires regardless of whether the agent self-classifies via the FINAL ACTION block in `SKILL.md`. Both pathways write to the same `~/.hermes/state/revenium/markers/<sid>.jsonl`; the hook tail-checks for a recent agent-written pair (within 30s) before writing to avoid duplicates.

The hook is installed by `examples/setup-local.sh` into `~/.hermes/hooks/revenium-classifier/`. **`hermes skills install` does NOT relocate the `hooks/` subdirectory** — operators installing via that path must additionally copy `~/.hermes/skills/revenium/hooks/revenium-classifier/` to `~/.hermes/hooks/revenium-classifier/` themselves.

After installing or updating the hook, **run `hermes gateway restart`**. Hermes loads hooks once at gateway startup; there is no file-watch reload.

To verify the hook loaded, inspect the gateway startup log for:

    [hooks] Loaded hook 'revenium-classifier' for events: ['agent:end']

Or run a one-shot discovery check:

    cd ~/.hermes/hermes-agent && ./venv/bin/python3 -c \
      "from gateway.hooks import HookRegistry; r=HookRegistry(); r.discover_and_load(); print(r.loaded_hooks)"

**Do NOT** use `hermes hooks list` to verify — that CLI is for shell hooks declared in `config.yaml`, a different subsystem.
```

**Markdown conventions to preserve:**

- H2 (`##`) for top-level sections — matches existing "How attribution works" + "Reset flow" + "Reconfigure flow".
- Triple-backtick fenced code blocks with no language for shell-snippet copy-pasta (existing pattern at lines 26-28, 36-44, 54-56).
- Lowercase `code` for path/identifier references, bold for invariants (existing pattern).

---

### `tests/test_repository.py` (test, unit + integration — MODIFIED)

**Analog A (test_expected_files_exist extension):** lines 11-33 — flat list append.

**Analog B (sys.path import + tmpdir + env-redirect):** `test_cron_marker_split_end_to_end` lines 291-470. This is the canonical "set HERMES_HOME=tmpdir + REVENIUM_STATE_DIR=tmpdir + import module under test" pattern.

**Analog C (atomic-write fcntl pattern in tests):** `test_taxonomy_atomic_write_pattern` lines 103-174 — for marker-write round-trip assertions.

**Extension to `test_expected_files_exist`** (line 31 — add to the `expected` list):

```python
expected = [
    # ... existing entries unchanged ...
    SKILL / 'scripts' / 'split_strategies.py',
    # Phase 6 — agent:end classifier hook (HOOK-01)
    SKILL / 'hooks' / 'revenium-classifier' / 'HOOK.yaml',
    SKILL / 'hooks' / 'revenium-classifier' / 'handler.py',
]
```

**New test method skeleton — tmpdir + env redirect** (mirrors `test_cron_marker_split_end_to_end:383-427`):

```python
def test_revenium_classifier_trivial_skip(self):
    """HOOK-02: A turn with no tools and a short response must skip marker write."""
    import asyncio
    import os
    import sys
    import tempfile
    import shutil

    HOOK_DIR = SKILL / 'hooks' / 'revenium-classifier'

    # Conditional skip if Hermes venv isn't available — handler imports
    # agent.auxiliary_client which only resolves inside the gateway venv.
    sys.path.insert(0, str(HOOK_DIR))
    try:
        import handler  # may ImportError if agent.* unavailable in this venv
    except ImportError as exc:
        self.skipTest(f"hook handler unimportable (no Hermes venv): {exc}")

    tmpdir = tempfile.mkdtemp(prefix='gsd-hook-trivial-')
    try:
        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir   = os.path.join(hermes_home, 'state', 'revenium')
        markers_dir = os.path.join(state_dir, 'markers')
        os.makedirs(markers_dir, mode=0o700)

        # Patch the handler's module-level path constants to point at tmpdir.
        # (Alternative: spawn a subprocess with env vars HERMES_HOME / REVENIUM_STATE_DIR
        # set — same pattern as test_cron_marker_split_end_to_end:419-427.)
        # The planner picks the cleaner approach during implementation.
        ...

        context = {
            "platform": "test", "user_id": "u", "session_id": "test-sid-trivial",
            "message": "good morning", "response": "Good morning!",
        }
        asyncio.run(handler.handle("agent:end", context))

        self.assertFalse(
            os.path.exists(os.path.join(markers_dir, "test-sid-trivial.jsonl")),
            "trivial turn must NOT create marker file (HOOK-02 / D-07)",
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        sys.path.remove(str(HOOK_DIR))
```

**Test method coverage map** (from RESEARCH.md "Test Framework" table):

| Method | Covers | Pattern reuse |
|--------|--------|---------------|
| `test_revenium_classifier_trivial_skip` | HOOK-02, D-07 | tmpdir + env-redirect (cron-e2e) |
| `test_revenium_classifier_subagent_inherits` | HOOK-03, D-05 | tmpdir + seed state.db w/ parent_session_id; reuse `build_state_db()` shape from cron-e2e |
| `test_revenium_classifier_halt_unclassified` | HOOK-04, D-08 | tmpdir + write budget-status.json with `halted: true` |
| `test_revenium_classifier_llm_label` | HOOK-05, D-06, D-09 | `unittest.mock.patch('handler.call_llm')` to return a fixed label |
| `test_revenium_classifier_marker_pair` | HOOK-06, D-10..D-14 | reuse `test_marker_file_schema` assertions on hook output |
| `test_revenium_classifier_dedupe` | HOOK-07, D-13 | seed marker file with a recent record before invoking handler |

**Conditional-skip pattern (HOOK-09 caveat — CI may lack Hermes venv):**

```python
@unittest.skipUnless(
    _hermes_aux_client_available(),
    "agent.auxiliary_client not importable — Hermes venv required",
)
def test_revenium_classifier_llm_label(self):
    ...
```

Where the predicate function lives at module scope:

```python
def _hermes_aux_client_available() -> bool:
    try:
        from agent.auxiliary_client import call_llm  # noqa: F401
        return True
    except ImportError:
        return False
```

**Test conventions to preserve:**

- One `TestCase` subclass (`RepositoryTests`); add methods, don't split into new classes.
- Method docstring first line summarizes the invariant being tested (existing pattern: lines 80, 103, 176, 217).
- `import` statements inside test methods (not top of file) when only that test needs them — established pattern at lines 81, 105, 178, 220, etc.
- `tempfile.mkdtemp(prefix='gsd-...')` for tmp dirs; `shutil.rmtree(..., ignore_errors=True)` in `finally`.

---

### `skills/revenium/SKILL.md` (docs — POSSIBLY MODIFIED, per D-17)

**Analog:** Same file's existing FINAL ACTION block (lines 279-397).

**Per D-17: FILE IS UNCHANGED.** The FINAL ACTION block stays verbatim as belt-and-suspenders. The hook handles cases where the agent doesn't self-classify; SKILL.md handles cases where the hook fails to load. Double-write is avoided by D-13 (tail-check in the hook).

**If the planner decides to add a one-line cross-reference** (optional — not required by any locked decision):

The planner MAY add a single-line "see also" pointer in a non-load-bearing comment-only zone of SKILL.md. Suggested location: after the existing line 297 "DO NOT skip it." paragraph, as a parenthetical note. The text MUST NOT alter:

- The HALT CHECK anchor string (lines 1-50, enforced by `test_prompt_ordering_invariant`).
- The FINAL ACTION anchor string (line 279, enforced by `test_prompt_ordering_invariant`).
- The execute_code snippet in lines 315-365 (the agent-side mechanical contract).
- The MARK-* schema fields in any marker record example.

If unsure, leave SKILL.md untouched. The hook is documented in `references/setup.md` per D-16; cross-linking inside SKILL.md is cosmetic.

---

## Shared Patterns

### Path discipline — single source of truth in `common.sh`

**Source:** `skills/revenium/scripts/common.sh:6-19`
**Apply to:** `handler.py` module-level constants.

The Python handler MUST mirror the shell variables defined in `common.sh`. Use `os.environ.get(NAME, DEFAULT)` with the same defaults:

```bash
HERMES_HOME="${HERMES_HOME:-${HOME}/.hermes}"
REVENIUM_STATE_DIR="${REVENIUM_STATE_DIR:-${HERMES_HOME}/state/revenium}"
TAXONOMY_FILE="${REVENIUM_TAXONOMY_FILE:-${STATE_DIR}/task-taxonomy.json}"
MARKERS_DIR="${REVENIUM_MARKERS_DIR:-${STATE_DIR}/markers}"
```

The Python equivalent (in `handler.py`):

```python
HERMES_HOME   = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
STATE_DIR     = Path(os.environ.get("REVENIUM_STATE_DIR", str(HERMES_HOME / "state" / "revenium")))
TAXONOMY_FILE = Path(os.environ.get("REVENIUM_TAXONOMY_FILE", str(STATE_DIR / "task-taxonomy.json")))
MARKERS_DIR   = Path(os.environ.get("REVENIUM_MARKERS_DIR", str(STATE_DIR / "markers")))
```

**Test enforcement:** `test_runtime_paths_are_hermes_native` (lines 65-77) currently asserts `common.sh` contains the literal strings `.hermes`, `state/revenium`, `TAXONOMY_FILE=`, `MARKERS_DIR=`. The planner should consider whether to extend this test to also scan `handler.py` for the same literals (low value — the handler is single-author and won't get accidentally rewritten with hardcoded paths the way shell scripts could).

### Atomic file write — `fcntl.flock` + `O_APPEND`

**Source A (test fixture-level pattern):** `tests/test_repository.py::test_taxonomy_atomic_write_pattern` lines 147-161
**Source B (production marker write):** `skills/revenium/SKILL.md:357-359` (the canonical execute_code snippet)
**Apply to:** `handler.py::_write_marker_pair`

```python
with open(marker_path, "ab", buffering=0) as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    f.write(line_g.encode("utf-8"))
    f.write(line_c.encode("utf-8"))
# flock auto-released on close
```

**Why this shape:**

- `"ab"` = append-binary; satisfies POSIX `O_APPEND` atomicity for `< PIPE_BUF` (typically 4 KB on Linux/macOS) writes.
- `buffering=0` = unbuffered; each `write()` is one `write(2)` syscall.
- `fcntl.LOCK_EX` serializes the two-record pair so no other writer (e.g., the agent's SKILL.md FINAL ACTION execute_code) can interleave between GUARDRAIL and CHAT.
- Records are `< 1024 bytes` per `test_marker_file_schema` (line 201) — well under PIPE_BUF.

### Read-only state.db access

**Source:** RESEARCH.md Pattern 4 (NEW — no in-repo analog; closest is `hermes-report.sh:45-53` which uses `sqlite3` CLI subprocess, not Python).
**Apply to:** `handler.py::_walk_to_root_session` and any other state.db read.

```python
uri = f"file:{STATE_DB}?mode=ro"
with sqlite3.connect(uri, uri=True) as conn:
    row = conn.execute("SELECT parent_session_id FROM sessions WHERE id = ?", (sid,)).fetchone()
```

**Constraint:** Hermes' writer holds a WAL lock. `?mode=ro` prevents the handler from blocking on or conflicting with the writer. **No SQL writes to state.db ever** — project invariant from CLAUDE.md "Constraints" section.

### Catch-and-log error handling — never raise out of `handle()`

**Source:** D-04 + `budget-check.sh:64-70` (Python heredoc try/except fallback pattern)
**Apply to:** outer `handle()` body and every sub-helper that touches filesystem / network / sqlite.

```python
async def handle(event_type: str, context: dict) -> None:
    # ... preconditions ...
    try:
        # ... full body ...
    except Exception as exc:                                                # bare Exception OK here
        logger.warning("revenium-classifier hook failed for sid=%s: %s",
                       context.get("session_id", "?"), exc)
        # NEVER re-raise
```

**Reasoning (per RESEARCH.md Pitfall 4 + D-04):** `HookRegistry.emit()` catches exceptions and prints them to gateway logs, but the agent loop has already yielded — there's no recovery. Re-raising would pollute logs and gain nothing.

Sub-helpers use targeted try/except per failure mode rather than bare `except Exception`:

- `sqlite3.OperationalError` for state.db read
- `OSError` for filesystem read/write
- `json.JSONDecodeError` for malformed JSONL lines
- `ImportError` for the optional `agent.auxiliary_client` import

Every failure path falls through to `task_type = "unclassified"` per D-08's fail-open philosophy.

### Marker record schema — `{muid, ts, sid, task_type, operation_type}`

**Source:** `skills/revenium/SKILL.md:353-356` (Phase 2 canonical write) + `tests/test_repository.py::test_marker_file_schema` lines 176-215 (schema enforcement).
**Apply to:** `handler.py::_write_marker_pair`.

**Required keys:** `muid` (33-char lowercase hex), `ts` (Unix float seconds), `sid` (Hermes session_id), `task_type` (matches `^[a-z][a-z0-9_]{1,47}$`), `operation_type` (`GUARDRAIL` or `CHAT`).
**Optional keys allowed:** `turn_seq`, `agent`, `trace_id`, `model` (allow-listed at line 180).
**Forbidden:** any field NOT in the allow-list. The schema test enforces `< 1024 bytes` per line.

**muid generator (one-liner contract from MARK-03):**

```python
return f"{int(time.time_ns() // 1_000_000):013x}" + secrets.token_hex(10)
```

**operation_type vocabulary** (line 207-208 in test): `{CHAT, GUARDRAIL, TOOL, AGENT, LLM, CHAIN, RETRIEVER, EMBEDDING, RERANKER, EVALUATOR, UNKNOWN}` (OpenInference span_kind). For Phase 6 the hook writes only `GUARDRAIL` (classification span) and `CHAT` (work span).

### Trivial-label blocklist (defense-in-depth at three layers)

**Source A (taxonomy doc):** `skills/revenium/references/task-taxonomy.md` (per RESEARCH.md "Canonical References")
**Source B (cron defense):** `hermes-report.sh:278` — `FORBIDDEN = {'ack', 'acknowledgment', 'greeting', 'confirmation', 'hello', 'thanks'}`
**Source C (Phase 2 prompt):** `SKILL.md:302-309`
**Apply to:** `handler.py` LLM-output validation after `_classify_via_llm`.

```python
TRIVIAL_BLOCKLIST = {"ack", "acknowledgment", "greeting", "confirmation", "hello", "thanks"}
```

Per D-09: on first blocklist hit, RE-PROMPT once; second hit falls back to `unclassified`. The cron-side check at `hermes-report.sh:324` (`if m.get('task_type') in FORBIDDEN: continue`) is defense-in-depth — even if the hook's validation has a bug, the cron drops the marker.

### Legacy branding guard

**Source:** `tests/test_repository.py::test_no_legacy_branding_left` lines 42-63
**Apply to:** ALL new files (HOOK.yaml, handler.py, test-payloads/*.json, README/docs updates).

The test scans every `.md / .sh / .py / .txt / .json / .yml / .yaml` file under repo root (except `.planning/` and `test_repository.py` itself) for the regex on line 61. New text MUST NOT introduce the forbidden tokens. When porting any pattern text from upstream Hermes docs, scrub.

---

## No Analog Found

Files with no close match in the codebase (planner should use RESEARCH.md patterns inline):

| File | Role | Data Flow | Pattern source |
|------|------|-----------|----------------|
| `skills/revenium/hooks/revenium-classifier/HOOK.yaml` | event-hook manifest | event-driven (subscription) | RESEARCH.md Pattern 1 — canonical shape from `~/.hermes/hermes-agent/gateway/hooks.py:79-130` |
| `agent.auxiliary_client.call_llm` invocation inside handler.py | LLM-call wrapper | request-response (sync wrapped with `asyncio.to_thread`) | RESEARCH.md Pattern 3 — canonical shape from `~/.hermes/hermes-agent/agent/auxiliary_client.py:3887` |

Both patterns are captured **inline above** in the `handler.py` and `HOOK.yaml` sections with full code excerpts — planner does not need to re-derive from research findings.

## Pattern Reuse Quick Reference

For the planner: when writing PLAN.md actions, reference these exact source locations:

| Need | Source | Line range |
|------|--------|------------|
| Marker pair write atomicity | `skills/revenium/SKILL.md` | 348-365 |
| muid generation (MARK-03) | `skills/revenium/SKILL.md` | 348-351 |
| Marker schema test assertions | `tests/test_repository.py` | 176-215 |
| Tmpdir + env-redirect test scaffold | `tests/test_repository.py` | 383-427 |
| Fail-open JSON read of budget-status | `skills/revenium/scripts/budget-check.sh` | 64-70 |
| Ledger / JSONL line-by-line reader | `skills/revenium/scripts/split_strategies.py::parse_prior_state` | 113-159 |
| state.db SQL shape (input columns) | `skills/revenium/scripts/hermes-report.sh` | 45-53 |
| Path-defaults env-var fallback chain | `skills/revenium/scripts/common.sh` | 6-19 |
| Idempotent copy-into-place install step | `examples/setup-local.sh` | 7-10 |
| Seed-only-if-missing install step | `examples/setup-local.sh` | 12-20 |
| Setup doc section heading style | `skills/revenium/references/setup.md` | 73-85 |
| Test method docstring convention | `tests/test_repository.py` | 80, 103, 176, 217 |
| FORBIDDEN blocklist enforcement | `skills/revenium/scripts/hermes-report.sh` | 278, 324 |
| `^[a-z][a-z0-9_]{1,47}$` label regex | `tests/test_repository.py` | 88, 203 |

## Metadata

**Analog search scope:**
- `skills/revenium/scripts/*.{sh,py}` — common.sh, budget-check.sh, hermes-report.sh, split_strategies.py, cron.sh
- `skills/revenium/SKILL.md` — FINAL ACTION block (lines 279-397)
- `skills/revenium/references/*.md` — setup.md, task-taxonomy.md, halt-survivability.md, troubleshooting.md
- `tests/test_repository.py` — all current test methods (946 lines)
- `examples/setup-local.sh` — full file (27 lines)

**Files scanned:** 13 in repo + 2 referenced from live Hermes installation (read via RESEARCH.md verified excerpts; `~/.hermes/hermes-agent/gateway/hooks.py`, `~/.hermes/hermes-agent/agent/auxiliary_client.py`).

**Pattern extraction date:** 2026-05-13
**Phase:** 06-mechanical-classification-agent-end-hook
