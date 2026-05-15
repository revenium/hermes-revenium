"""Shared classifier module for the revenium-classifier hermes_cli plugin.

Invoked from skills/revenium/plugins/revenium-classifier/__init__.py via
on_session_end. Carries the full D-04..D-14 + D-05..D-09 pipeline factored
out so the plugin entrypoint and tests both import it.

Invariant D-04: this module's async entry point MUST NEVER raise out of
run_classification_async(). Every error path is caught and logged with
logger.warning. An uncaught exception silently drops one turn's
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
# Hermes' venv is not available. Tests patch classifier.call_llm directly.
try:
    from agent.auxiliary_client import call_llm  # type: ignore
except ImportError:
    call_llm = None  # type: ignore[assignment]

# Path constants — mirror scripts/common.sh. Env vars override defaults so
# tests redirect cleanly via tempfile.mkdtemp + os.environ + importlib.reload.
HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
STATE_DIR = Path(os.environ.get("REVENIUM_STATE_DIR", str(HERMES_HOME / "state" / "revenium")))
MARKERS_DIR = Path(os.environ.get("REVENIUM_MARKERS_DIR", str(STATE_DIR / "markers")))
MARKERS_READY_DIR = Path(os.environ.get("REVENIUM_MARKERS_READY_DIR", str(MARKERS_DIR / ".ready")))
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
    """Return the count of tool calls in the just-completed turn for session `sid`.
    Primary source: `state.db.sessions.tool_call_count` (universal — populated for
    every session source: gateway-served, CLI one-shot, interactive, ACP, cron).
    Fallback source: `~/.hermes/sessions/<sid>.jsonl` (scan backward for the last
    role:user line, count role:tool entries after it). Returns 0 if neither source
    has the signal. Used by D-07 heuristic skip.

    D-04 invariant: never raises. All sqlite errors fall through to JSONL; all
    OSError/JSONDecodeError in JSONL fall through to 0. D-20 closes G-02: the
    gateway-style JSONL is absent for CLI one-shot sessions (`hermes_cli/oneshot.py::_create_session_db_for_oneshot`
    writes only state.db), so JSONL alone caused every CLI substantive turn to be
    mis-classified as trivial."""
    # PRIMARY PATH — state.db.sessions.tool_call_count. Mirrors the same read-only
    # URI pattern used by _walk_to_root_session above. On any sqlite error, on a
    # missing row, or on a NULL value, fall through to the JSONL fallback.
    try:
        uri = f"file:{STATE_DB}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            row = conn.execute(
                "SELECT tool_call_count FROM sessions WHERE id = ?", (sid,)
            ).fetchone()
            if row is not None and row[0] is not None:
                # int() coercion is defensive — sqlite columns are INTEGER affinity
                # but guard against schema drift where the column might be stored as TEXT.
                return int(row[0])
            # row missing or value NULL → fall through to JSONL fallback
    except sqlite3.OperationalError:
        pass  # db locked, missing, or schema mismatch → JSONL fallback
    except Exception:
        pass  # belt: D-04 invariant — never raise from this helper

    # FALLBACK PATH — read JSONL (preserved verbatim from prior implementation).
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


def _read_session_messages(sid: str) -> "tuple[str, str]":
    """Return (last_user_content, last_assistant_content) for `sid` from state.db.messages.

    The production plugin entrypoint (_on_session_end in __init__.py) always passes
    message=None and response=None to run_classification. This helper fills the gap by
    querying state.db.messages so the LLM prompt contains real session content instead of
    empty strings. Tests that pass content explicitly bypass this via the else branch in
    run_classification_async Step 5 — this helper is NOT consulted when message and response
    are already provided.

    Read-only URI mode (`file:...?mode=ro`) prevents WAL lock contention with the Hermes
    writer, matching the pattern used by _walk_to_root_session and _count_tools_in_current_turn.
    A try/finally with conn.close() is used rather than a with-block so that the
    enclosing except can catch and swallow any error at any point in the helper body,
    preserving the D-04 fail-open invariant: this helper MUST NEVER raise.

    Returns ("", "") if sid is falsy, if state.db does not exist, or on any sqlite,
    filesystem, or schema error.
    """
    if not sid:
        return ("", "")
    if not STATE_DB.exists():
        return ("", "")
    try:
        conn = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=2.0)
        try:
            cursor = conn.execute(
                "SELECT role, content FROM messages"
                " WHERE session_id = ? AND content IS NOT NULL AND content != ''"
                " ORDER BY timestamp DESC",
                (sid,),
            )
            user_msg = ""
            asst_msg = ""
            for row in cursor:
                role, content = row[0], row[1]
                if role == "user" and not user_msg:
                    user_msg = content
                elif role == "assistant" and not asst_msg:
                    asst_msg = content
                if user_msg and asst_msg:
                    break
        finally:
            conn.close()
        return (user_msg, asst_msg)
    except Exception:
        return ("", "")


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
    """D-13: return True if the marker file's tail carries a GUARDRAIL+CHAT pair
    whose most recent ts is within `within_seconds` of time.time(). Used to skip
    the plugin write when the agent's SKILL.md FINAL ACTION snippet already wrote
    markers for this turn. Per Pitfall 6 option (a) — wall-clock proximity."""
    marker_path = MARKERS_DIR / f"{sid}.jsonl"
    if not marker_path.is_file():
        return False
    try:
        lines = marker_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    # Walk backward, collect GUARDRAIL+CHAT pair within the window.
    now = time.time()
    seen_ops = set()
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = rec.get("ts")
        op = rec.get("operation_type")
        if not isinstance(ts, (int, float)) or not isinstance(op, str):
            continue
        if (now - ts) > within_seconds:
            break  # records are timestamp-ordered (append-only); no point continuing
        if op in ("GUARDRAIL", "CHAT"):
            seen_ops.add(op)
            if seen_ops >= {"GUARDRAIL", "CHAT"}:
                return True
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
    """Build the mint-first classification prompt per D-06 + D-09.

    Framing: mint a SPECIFIC, DESCRIPTIVE label first; reuse an existing label
    only if it describes the SAME specific work (not 'close enough').
    """
    labels_block = ", ".join(labels) if labels else "(no existing labels yet)"
    # Cap the labels block at ~1 KB so the taxonomy growing to dozens of labels
    # does not blow out the prompt size.
    if len(labels_block) > 1024:
        labels_block = labels_block[:1024] + " ... [truncated]"
    # Bound the previews to ~800 chars each so the whole prompt fits ~2 KB per D-06.
    user_preview = (user_msg or "")[:800]
    asst_preview = (assistant_resp or "")[:800]
    return (
        "You are classifying a Hermes session turn for spend attribution. "
        "Output ONLY a single snake_case label, no explanation, no quotes, no punctuation.\n\n"
        "Mint a SPECIFIC, DESCRIPTIVE label that captures what the agent actually did. "
        "Use 2-4 words joined by underscores. "
        "Good examples: weekly_pr_review, prod_log_triage, news_summary, sql_query_debug, release_notes_draft.\n\n"
        "AVOID bland catch-all labels like generation, analysis, review, task when a more specific label fits.\n\n"
        f"Existing labels (for reference): {labels_block}\n\n"
        "You MAY reuse one of the existing labels, but only if it describes the SAME specific work — "
        "not 'close enough'. If no existing label is an exact match for this work, mint a new one.\n\n"
        "Label format: ^[a-z][a-z0-9_]{1,47}$\n"
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
    else returns 'unclassified'. D-09 enforcement at the classifier boundary."""
    if not label:
        return "unclassified"
    cleaned = label.strip().lower()
    if cleaned in TRIVIAL_BLOCKLIST:
        return "unclassified"
    if not LABEL_RE.match(cleaned):
        return "unclassified"
    return cleaned


def _persist_label_to_taxonomy(label: str) -> None:
    """Append label to task-taxonomy.json if not already present, updating
    last_seen_at on every call (D-32 mint-back).

    Atomic via temp-file + os.replace. Fail-open: any I/O error logs a warning
    and returns without raising (D-32). Only called after _write_marker_pair
    succeeds. The 'unclassified' sentinel is excluded — never persisted as a
    taxonomy entry."""
    if label == "unclassified":
        return
    import datetime
    try:
        try:
            data = json.loads(TAXONOMY_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {"labels": {}}
        labels = data.get("labels", {})
        if not isinstance(labels, dict):
            labels = {}
        now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if label not in labels:
            labels[label] = {
                "description": None,
                "examples": [],
                "last_seen_at": now_iso,
            }
        else:
            # Update last_seen_at on every successful write (recency ordering D-33).
            if not isinstance(labels[label], dict):
                labels[label] = {}
            labels[label]["last_seen_at"] = now_iso
        data["labels"] = labels
        TAXONOMY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = TAXONOMY_FILE.parent / (TAXONOMY_FILE.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(TAXONOMY_FILE)
    except Exception as exc:
        logger.warning("revenium-classifier: mint-back failed for label=%s: %s", label, exc)


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


async def run_classification_async(
    session_id: str,
    model: "str | None" = None,
    platform: "str | None" = None,
    message: "str | None" = None,
    response: "str | None" = None,
) -> None:
    """Async classifier entry point. D-04: never raises out of this function.

    Drives the D-04..D-14 pipeline: subagent inheritance →
    D-13 dedupe → budget gate → LLM classification → validated label →
    atomic marker pair write. Invoked from the plugin entrypoint's sync
    wrapper run_classification() via asyncio.run().
    """
    if not session_id:
        return
    try:
        # Step 1 — subagent inheritance (D-05).
        root_sid = _walk_to_root_session(session_id)
        if root_sid != session_id:
            parent_task = _read_latest_task_type(root_sid)
            if parent_task:
                await asyncio.to_thread(_write_marker_pair, session_id, parent_task)
                _persist_label_to_taxonomy(parent_task)
                return
            # Parent has no marker yet — fall through to classify as if root.

        # Step 3 — D-13 belt: did the agent already self-classify? (HOOK-07)
        if _recent_marker_pair_exists(session_id, within_seconds=30.0):
            return  # agent's FINAL ACTION wrote markers in the last 30s; don't double-write

        # Step 4 — budget gate (D-08 / HOOK-04).
        if _budget_halted():
            await asyncio.to_thread(_write_marker_pair, session_id, "unclassified")
            logger.warning(
                "revenium-classifier: budget halted, wrote unclassified for sid=%s", session_id
            )
            return

        # Step 5 — LLM classification (D-06 / HOOK-05).
        # Resolve message + response from state.db when caller passed None (the
        # production path: __init__.py:_on_session_end always passes None). Tests
        # that pass content explicitly bypass this lookup via the else branch.
        if not message or not response:
            db_user, db_asst = _read_session_messages(session_id)
            user_msg = message or db_user
            asst_resp = response or db_asst
        else:
            user_msg, asst_resp = message, response
        raw_label = await _classify_via_llm(
            {"message": user_msg},
            asst_resp or "",
        )
        task_type = _validate_label(raw_label)

        # Step 6 — atomic write of GUARDRAIL + CHAT pair (D-10, D-14 / HOOK-06).
        await asyncio.to_thread(_write_marker_pair, session_id, task_type)
        _persist_label_to_taxonomy(task_type)
    except Exception as exc:
        logger.warning(
            "revenium-classifier classifier failed for sid=%s: %s",
            session_id,
            exc,
        )


def run_classification(
    session_id: str,
    model: "str | None" = None,
    platform: "str | None" = None,
    message: "str | None" = None,
    response: "str | None" = None,
) -> None:
    """Synchronous convenience wrapper. Drives run_classification_async via
    asyncio.run(). The plugin entrypoint (`_on_session_end`) is synchronous per
    the Hermes plugin contract, so this wrapper bridges the sync→async gap.

    D-04 belt at the sync boundary: any exception escaping asyncio.run is
    caught here and logged via logger.warning. The plugin entrypoint stays
    clean and never sees a propagating exception.
    """
    try:
        asyncio.run(
            run_classification_async(
                session_id=session_id,
                model=model,
                platform=platform,
                message=message,
                response=response,
            )
        )
    except Exception as exc:
        logger.warning(
            "revenium-classifier run_classification failed for sid=%s: %s",
            session_id,
            exc,
        )
