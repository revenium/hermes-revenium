"""Hermes agent:end event hook — mechanical task-type classifier.

Fires once per agent turn yielding back to the user. Writes a marker pair
(one GUARDRAIL classification span + one CHAT work span) into
~/.hermes/state/revenium/markers/<sid>.jsonl, matching the Phase 2 marker
schema the Phase 3 cron pipeline already consumes.

Invariant D-04: this handler MUST NEVER raise out of handle(). Every error
path is caught and logged with logger.warning. Hermes' HookRegistry.emit()
catches but does not retry; an uncaught exception silently drops one turn's
classification — same failure mode as the agent skipping FINAL ACTION.

Module-level path constants mirror skills/revenium/scripts/common.sh. They
are evaluated at import time; tests redirect via env vars + importlib.reload.
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

# Lazy import — keeps the module importable in the test environment where
# Hermes' venv is not available. Tests patch handler.call_llm directly.
try:
    from agent.auxiliary_client import call_llm  # type: ignore
except ImportError:
    call_llm = None  # type: ignore[assignment]

# Path constants — mirror scripts/common.sh. Env vars override defaults so
# tests redirect cleanly via tempfile.mkdtemp + os.environ + importlib.reload.
HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
STATE_DIR = Path(os.environ.get("REVENIUM_STATE_DIR", str(HERMES_HOME / "state" / "revenium")))
MARKERS_DIR = Path(os.environ.get("REVENIUM_MARKERS_DIR", str(STATE_DIR / "markers")))
TAXONOMY_FILE = Path(os.environ.get("REVENIUM_TAXONOMY_FILE", str(STATE_DIR / "task-taxonomy.json")))
BUDGET_STATUS_FILE = STATE_DIR / "budget-status.json"
STATE_DB = HERMES_HOME / "state.db"
SESSIONS_DIR = HERMES_HOME / "sessions"

# Label validation: lowercase snake_case, length 2..48 (regex enforces a
# leading lowercase letter, then 1..47 more chars from [a-z0-9_]).
LABEL_RE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")

# D-09 trivial-label blocklist — these are forbidden classifier outputs even
# if they match LABEL_RE. The validator falls through to "unclassified".
TRIVIAL_BLOCKLIST = {"ack", "acknowledgment", "greeting", "confirmation", "hello", "thanks"}

logger = logging.getLogger("revenium_classifier")


def _walk_to_root_session(sid: str, max_depth: int = 10) -> str:
    """Walk state.db.sessions.parent_session_id chain. Returns input sid if it has
    no parent. Read-only URI mode prevents WAL lock contention with Hermes writer.
    Depth-capped to defeat pathological corrupted parent chains."""
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
    except sqlite3.OperationalError:
        return sid  # locked, missing, or any sqlite error → treat as root
    except Exception:
        return sid  # belt: D-04 invariant


def _count_tools_in_current_turn(sid: str) -> int:
    """Return the count of role:tool entries in ~/.hermes/sessions/<sid>.jsonl
    between the most recent role:user line and EOF. Returns 0 if the file is
    missing, unreadable, or has no user line. Used by D-07 heuristic skip."""
    path = SESSIONS_DIR / f"{sid}.jsonl"
    if not path.is_file():
        return 0
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


def _read_latest_task_type(sid: str) -> "str | None":
    """Return the task_type of the most recent valid marker record for `sid`, or None
    if the file is missing or has no valid records. Used by D-05 subagent inheritance."""
    marker_path = MARKERS_DIR / f"{sid}.jsonl"
    if not marker_path.is_file():
        return None
    try:
        lines = marker_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        tt = rec.get("task_type")
        if isinstance(tt, str) and LABEL_RE.match(tt):
            return tt
    return None


def _recent_marker_pair_exists(sid: str, within_seconds: float = 30.0) -> bool:
    """Stub — T10 implements. Returns False (no recent pair)."""
    return False


def _budget_halted() -> bool:
    """Read budget-status.json and return True if halted. Fail-open on any
    filesystem or JSON error per D-08."""
    try:
        data = json.loads(BUDGET_STATUS_FILE.read_text(encoding="utf-8"))
        return bool(data.get("halted", False))
    except Exception:
        return False


def _read_taxonomy_labels() -> list:
    """Read TAXONOMY_FILE and return the sorted list of existing label keys. The
    live taxonomy is at ~/.hermes/state/revenium/task-taxonomy.json (managed by
    Phase 2). Returns [] on any failure — the LLM will mint a new label."""
    try:
        data = json.loads(TAXONOMY_FILE.read_text(encoding="utf-8"))
        labels = data.get("labels", {})
        if isinstance(labels, dict):
            return sorted(labels.keys())
    except Exception:
        pass
    return []


def _build_classification_prompt(user_msg: str, assistant_resp: str, labels: list) -> str:
    """Build the compact lookup-first classification prompt per D-06 + D-09."""
    labels_block = ", ".join(labels) if labels else "(no existing labels yet)"
    # Cap the labels block at ~1 KB so the taxonomy growing to dozens of labels
    # does not blow out the prompt size.
    if len(labels_block) > 1024:
        labels_block = labels_block[:1024] + " ... [truncated]"
    # Bound the previews to ~1 KB each so the whole prompt fits ~2 KB per D-06.
    user_preview = (user_msg or "")[:800]
    asst_preview = (assistant_resp or "")[:800]
    return (
        "You are classifying a Hermes session turn for spend attribution. "
        "Output ONLY a single snake_case label, no explanation, no quotes, no punctuation.\n\n"
        f"Existing labels: {labels_block}\n\n"
        "Pick the single best-fitting existing label by exact match. "
        "If NONE fit, mint a new label matching ^[a-z][a-z0-9_]{1,47}$. "
        "Forbidden labels (do NOT emit): ack, acknowledgment, greeting, confirmation, hello, thanks.\n\n"
        f"User message preview:\n{user_preview}\n\n"
        f"Assistant response preview:\n{asst_preview}\n\n"
        "Label:"
    )


async def _classify_via_llm(context: dict, response_preview: str) -> str:
    """Invoke the user's main budgeted LLM via agent.auxiliary_client.call_llm.
    Per Pitfall 8 + A3 + D-06: NO `task=` argument so the call uses the user's
    main provider+model from config.yaml. Returns the LLM-emitted raw string;
    caller validates against LABEL_RE + TRIVIAL_BLOCKLIST via _validate_label."""
    if call_llm is None:
        return "unclassified"
    labels = _read_taxonomy_labels()
    prompt = _build_classification_prompt(
        context.get("message", "") or "",
        response_preview,
        labels,
    )
    try:
        response = await asyncio.to_thread(
            call_llm,
            messages=[
                {"role": "system", "content": "You classify Hermes turns into task_type labels. Output only the label."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=64,
            timeout=10.0,
        )
        # Extract content; tolerate openai SDK response shape variations.
        try:
            raw = response.choices[0].message.content
        except AttributeError:
            # Older SDK form: dict-like
            raw = response["choices"][0]["message"]["content"]
        return (raw or "").strip()
    except Exception as exc:
        logger.warning("revenium-classifier LLM call failed: %s", exc)
        return "unclassified"


def _validate_label(label: str) -> str:
    """Returns label if it matches LABEL_RE AND is not in TRIVIAL_BLOCKLIST,
    else returns 'unclassified'. D-09 enforcement at the handler boundary."""
    if not label:
        return "unclassified"
    cleaned = label.strip().lower()
    if cleaned in TRIVIAL_BLOCKLIST:
        return "unclassified"
    if not LABEL_RE.match(cleaned):
        return "unclassified"
    return cleaned


def _muid() -> str:
    """13-char ms-timestamp prefix + 20-char random hex = 33 char lowercase hex."""
    return f"{int(time.time_ns() // 1_000_000):013x}" + secrets.token_hex(10)


def _write_marker_pair(sid: str, task_type: str) -> Path:
    """Atomic O_APPEND + fcntl.LOCK_EX write of a GUARDRAIL + CHAT marker pair.

    Per D-14 + HOOK-06: < 1024 bytes per line, exactly two records, single lock.
    Per Phase 2 marker schema: {muid, ts, sid, task_type, operation_type}.
    """
    MARKERS_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker_path = MARKERS_DIR / f"{sid}.jsonl"

    def _record(op: str) -> dict:
        return {
            "muid": _muid(),
            "ts": time.time(),
            "sid": sid,
            "task_type": task_type,
            "operation_type": op,
        }

    line_g = json.dumps(_record("GUARDRAIL"), separators=(",", ":"), ensure_ascii=True) + "\n"
    line_c = json.dumps(_record("CHAT"), separators=(",", ":"), ensure_ascii=True) + "\n"
    with open(marker_path, "ab", buffering=0) as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line_g.encode("utf-8"))
        f.write(line_c.encode("utf-8"))
    return marker_path


async def handle(event_type: str, context: dict) -> None:
    """Hermes agent:end event handler. D-04: never raises out of handle()."""
    if event_type != "agent:end":
        return
    sid = context.get("session_id")
    if not sid:
        return
    try:
        # Step 1 — subagent inheritance (D-05). Stub returns input sid until T07
        # fills in _walk_to_root_session + _read_latest_task_type.
        root_sid = _walk_to_root_session(sid)
        if root_sid != sid:
            parent_task = _read_latest_task_type(root_sid)
            if parent_task:
                await asyncio.to_thread(_write_marker_pair, sid, parent_task)
                return
            # Parent has no marker yet — fall through to classify as if root.

        # Step 2 — heuristic skip-fast-path (D-07 / HOOK-02).
        response_preview = context.get("response", "") or ""
        tool_count = _count_tools_in_current_turn(sid)
        if tool_count == 0 and len(response_preview) < 200:
            return  # trivial — skip marker entirely

        # Step 3 — D-13 belt: did the agent already self-classify? (T10)
        # if _recent_marker_pair_exists(sid, within_seconds=30):
        #     return

        # Step 4 — budget gate (D-08 / HOOK-04).
        if _budget_halted():
            await asyncio.to_thread(_write_marker_pair, sid, "unclassified")
            logger.warning(
                "revenium-classifier: budget halted, wrote unclassified for sid=%s", sid
            )
            return

        # Step 5 — LLM classification (D-06 / HOOK-05).
        raw_label = await _classify_via_llm(context, response_preview)
        task_type = _validate_label(raw_label)

        # Step 6 — atomic write of GUARDRAIL + CHAT pair (D-10, D-14 / HOOK-06).
        await asyncio.to_thread(_write_marker_pair, sid, task_type)
    except Exception as exc:
        logger.warning(
            "revenium-classifier hook failed for sid=%s: %s",
            context.get("session_id", "?"),
            exc,
        )
