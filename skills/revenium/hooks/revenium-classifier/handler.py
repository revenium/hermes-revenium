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
    """Stub — T07 implements. Returns input sid (treat as root)."""
    return sid


def _count_tools_in_current_turn(sid: str) -> int:
    """Stub — T06 implements. Returns 0 (no tools detected)."""
    return 0


def _read_latest_task_type(sid: str) -> "str | None":
    """Stub — T07 implements. Returns None (no inherited task_type)."""
    return None


def _recent_marker_pair_exists(sid: str, within_seconds: float = 30.0) -> bool:
    """Stub — T10 implements. Returns False (no recent pair)."""
    return False


def _budget_halted() -> bool:
    """Stub — T08 implements. Returns False (fail-open)."""
    return False


def _read_taxonomy_labels() -> list:
    """Stub — T09 implements. Returns empty label list."""
    return []


async def _classify_via_llm(context: dict, response_preview: str) -> str:
    """Stub — T09 implements. Returns 'unclassified'."""
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
        # T04-T11 fill in the body. Scaffold stops here so the test suite
        # passes during partial implementation.
        pass
    except Exception as exc:
        logger.warning(
            "revenium-classifier hook failed for sid=%s: %s",
            context.get("session_id", "?"),
            exc,
        )
