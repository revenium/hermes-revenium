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
JOB_TAXONOMY_FILE = Path(os.environ.get("REVENIUM_JOB_TAXONOMY_FILE", str(STATE_DIR / "job-taxonomy.json")))
GUARDRAIL_STATUS_FILE = STATE_DIR / "guardrail-status.json"  # Phase 19 (ENF-03): renamed from BUDGET_STATUS_FILE, repointed to guardrail-status.json
STATE_DB = HERMES_HOME / "state.db"

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


def _read_session_messages(sid: str) -> "tuple[str, str]":
    """Return (last_user_content, last_assistant_content) for `sid` from state.db.messages.

    The production plugin entrypoint (_on_session_end in __init__.py) always passes
    message=None and response=None to run_classification. This helper fills the gap by
    querying state.db.messages so the LLM prompt contains real session content instead of
    empty strings. Tests that pass content explicitly bypass this via the else branch in
    run_classification_async Step 5 — this helper is NOT consulted when message and response
    are already provided.

    Read-only URI mode (`file:...?mode=ro`) prevents WAL lock contention with the Hermes
    writer, matching the pattern used by _walk_to_root_session.
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


# ---------------------------------------------------------------------------
# Phase 13 job-path helpers — mirror the task-path above, don't merge (D-01).
# ---------------------------------------------------------------------------

def _read_session_transcript(
    sid: str,
    max_chars: int = 8000,
    per_msg_cap: int = 500,
) -> str:
    """Return a chronologically-ordered (timestamp ASC) transcript for `sid`.

    Mirrors _read_session_messages with two deliberate deviations:
    - ORDER BY timestamp ASC (arc progression for the LLM, not latest-pair-first)
    - Per-message content capped to `per_msg_cap` chars.

    When the full transcript fits within `max_chars` it is returned whole. When it
    exceeds the budget, return a HEAD + TAIL sample joined by an explicit elision
    marker — NOT a head-only prefix. The opening request lives at the head and the
    completed-arc evidence (final result / summary) lives at the tail; a head-only
    window silently drops the conclusion, so job inference on a long session sees an
    unfinished arc and mis-infers CANCELLED or nothing.

    Returns "" on any failure (D-04 fail-open).
    """
    if not sid:
        return ""
    if not STATE_DB.exists():
        return ""
    try:
        conn = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=2.0)
        try:
            cursor = conn.execute(
                "SELECT role, content FROM messages"
                " WHERE session_id = ? AND content IS NOT NULL AND content != ''"
                " ORDER BY timestamp ASC",
                (sid,),
            )
            lines = [f"{row[0]}: {(row[1] or '')[:per_msg_cap]}" for row in cursor]
        finally:
            conn.close()
        if not lines:
            return ""
        full = "\n".join(lines)
        if len(full) <= max_chars:
            return full
        # Over budget: keep the head (opening request/context) AND the tail
        # (closing outcome) so the job-inference LLM sees the completed arc.
        marker = "\n... [transcript truncated — middle omitted] ...\n"
        budget = max(0, max_chars - len(marker))
        head_budget = budget // 2
        head_parts = []
        head_len = 0
        head_idx = 0
        for i, line in enumerate(lines):
            if head_len + len(line) + 1 > head_budget:
                break
            head_parts.append(line)
            head_len += len(line) + 1
            head_idx = i + 1
        tail_parts = []
        tail_len = 0
        for i in range(len(lines) - 1, head_idx - 1, -1):
            line = lines[i]
            if tail_len + len(line) + 1 > budget - head_len:
                break
            tail_parts.append(line)
            tail_len += len(line) + 1
        tail_parts.reverse()
        if not tail_parts:
            return "\n".join(head_parts)
        return "\n".join(head_parts) + marker + "\n".join(tail_parts)
    except Exception:
        return ""


def _build_job_inference_prompt(transcript: str, job_labels: list) -> str:
    """Build the job-inference prompt — mirror of _build_classification_prompt.

    Deviations from the task-path analog:
    - Output is a JSON array of job objects (agentic_job_id, job_name, job_type, status).
    - Includes arc-boundary guidance (same goal incl. follow-up fixes = one arc).
    - Conservative status criteria (SUCCESS only on checkable evidence, CANCELLED
      is the uncertainty-bias catch-all per Phase 8 DECLARE-05).
    - LLM emits the business label; code appends secrets.token_hex(2) suffix in
      Plan 02's _validate_job step (documented here; not applied in this helper).
    """
    labels_block = ", ".join(job_labels) if job_labels else "(no existing labels yet)"
    if len(labels_block) > 1024:
        labels_block = labels_block[:1024] + " ... [truncated]"
    transcript_preview = (transcript or "")[:6000]
    return (
        "You are analyzing a Hermes AI agent session to identify the discrete task arcs "
        "completed by the agent. A task arc is a goal-directed sequence of turns with a "
        "single objective; follow-up fixes to the same goal are part of the same arc.\n\n"
        "Output ONLY a JSON array of job objects. Each object must have:\n"
        "  - agentic_job_id: a SPECIFIC, DESCRIPTIVE snake_case business label "
        "(e.g. fix_auth_regression, prod_log_triage, weekly_pr_review)\n"
        "  - job_name: a short human-readable name (sentence case, max 60 chars)\n"
        "  - job_type: a snake_case category label matching ^[a-z][a-z0-9_]{1,47}$\n"
        "  - status: one of SUCCESS, FAILED, or CANCELLED\n"
        "  - failure_reason: ONLY when status is FAILED, a brief (max ~200 char) "
        "plain-text explanation of what went wrong (e.g. 'tests failed: 3 assertion "
        "errors in auth module'). OMIT this field for SUCCESS and CANCELLED.\n\n"
        "Status guidance:\n"
        "  SUCCESS: only when there is clear evidence the goal was achieved.\n"
        "  FAILED: only when there is explicit evidence of failure. Always include "
        "failure_reason.\n"
        "  CANCELLED: use when uncertain — this is the uncertainty-bias catch-all.\n\n"
        "Mint a SPECIFIC agentic_job_id. "
        "You MAY reuse one of the existing job_type labels, but only if it is an exact match. "
        "If no existing label fits, mint a new one.\n\n"
        f"Existing job_type labels (for reference): {labels_block}\n\n"
        f"Session transcript:\n{transcript_preview}\n\n"
        "JSON array:"
    )


def _parse_job_array(raw: str) -> list:
    """Parse an LLM response into a list of job dicts. Fail-open: returns [] on any error.

    - Strips leading/trailing ```json ... ``` markdown fences (single-line or multi-line).
    - json.loads the result; on JSONDecodeError returns [].
    - Coerces a lone dict (single-job session) to [dict].
    - Drops any non-dict elements (defensive against LLM adding strings/ints).
    - Returns [] on any error.

    Uses a regex strip to handle both single-line (```json[...]```) and multi-line
    (```json\\n[...]\\n```) fenced responses without splitting into lines first.
    """
    try:
        text = (raw or "").strip()
        # Strip markdown fence: ``` optionally followed by a language tag, then
        # the JSON payload, then a closing ```. Works for both single-line and
        # multi-line fenced output. re is already imported at module scope.
        text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            return []
        return [item for item in parsed if isinstance(item, dict)]
    except Exception:
        return []


async def _infer_jobs_via_llm(transcript: str, job_labels: list) -> list:
    """Invoke the user's main LLM to infer jobs from the session transcript.

    Mirror of _classify_via_llm with deviations:
    - Returns [] (not "unclassified") when call_llm is None.
    - max_tokens=512, timeout=20.0 (larger: array output, bigger prompt).
    - Passes raw response through _parse_job_array instead of .strip().
    - CRITICALLY: NO `task=` kwarg (uses user's main provider+model from config.yaml).
    """
    if call_llm is None:
        return []
    prompt = _build_job_inference_prompt(transcript, job_labels)
    try:
        response = await asyncio.to_thread(
            call_llm,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You analyze Hermes agent session transcripts to identify "
                        "completed task arcs. Output only a JSON array."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=512,
            timeout=20.0,
        )
        # Extract content; tolerate openai SDK response shape variations.
        try:
            raw = response.choices[0].message.content
        except AttributeError:
            raw = response["choices"][0]["message"]["content"]
        return _parse_job_array(raw or "")
    except Exception as exc:
        logger.warning("revenium-classifier job inference LLM call failed: %s", exc)
        return []


def _validate_job(job: dict) -> "dict | None":
    """Validate and normalize a job dict from the LLM response.

    Mirror of _validate_label but for a dict (D-03 reader-required keys).
    Required keys: agentic_job_id (non-empty str), job_type (LABEL_RE match),
    status (in {SUCCESS, FAILED, CANCELLED}). job_name is optional.

    Reuses LABEL_RE for job_type — same snake_case grammar as task labels;
    defense-in-depth against pipe/colon/newline injection that would corrupt
    the cron's IFS='|' parse and JOB:<id>: ledger grammar (T-13-01).

    Returns the normalized dict on success, None for any invalid job (caller skips).
    """
    if not isinstance(job, dict):
        return None
    agentic_job_id = job.get("agentic_job_id", "")
    if not isinstance(agentic_job_id, str) or not agentic_job_id.strip():
        return None
    job_type = job.get("job_type", "")
    if not isinstance(job_type, str):
        return None
    job_type = job_type.strip().lower()
    if not LABEL_RE.match(job_type):
        return None
    status_raw = job.get("status", "")
    if not isinstance(status_raw, str):
        return None
    status = status_raw.strip().upper()
    if status not in {"SUCCESS", "FAILED", "CANCELLED"}:
        return None
    # DECLARE-02 contract: always append a secrets.token_hex(2) entropy suffix to
    # the LLM-supplied agentic_job_id. The LLM is instructed to emit a business
    # label (e.g. fix_auth_regression) and this step deterministically appends the
    # 4-hex token to ensure uniqueness. Unconditional append is correct here because:
    #  1. The LLM prompt never instructs the LLM to mint the suffix itself.
    #  2. A conditional suffix check (r"_[0-9a-f]{4}$") falsely matches ordinary
    #     English words ending in 4 hex chars (_face, _beef, _cafe, _dead, _feed,
    #     _deed, _fade), allowing colliding ids to slip through. (WR-01)
    #  3. Using re at module scope removes the redundant inline import. (IN-01)
    aid = agentic_job_id.strip() + "_" + secrets.token_hex(2)
    # failure_reason is meaningful only for FAILED arcs. Coerce non-str / wrong-status
    # values to empty so SUCCESS/CANCELLED markers stay byte-identical to pre-change
    # output (the writer omits the key when empty). Cap length defensively so a runaway
    # LLM response cannot bloat the marker line or the downstream --metadata CLI arg.
    failure_reason = job.get("failure_reason", "")
    if not isinstance(failure_reason, str) or status != "FAILED":
        failure_reason = ""
    failure_reason = failure_reason.strip()
    if len(failure_reason) > 500:
        failure_reason = failure_reason[:500]
    return {
        "agentic_job_id": aid,
        "job_name": (job.get("job_name") or ""),
        "job_type": job_type,
        "status": status,
        "failure_reason": failure_reason,
    }


def _write_job_marker(sid: str, job: dict) -> Path:
    """Atomic O_APPEND + fcntl.LOCK_EX write of a single kind:"job" marker line.

    Mirror of _write_marker_pair but writes ONE line using the frozen Phase 7 D-03
    record shape. Reader-required keys: kind, agentic_job_id, job_type, status.
    Same compact serialization, same markers/<sid>.jsonl file.
    """
    MARKERS_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker_path = MARKERS_DIR / f"{sid}.jsonl"
    record = {
        "kind": "job",
        "ts": time.time(),
        "sid": sid,
        "agentic_job_id": job["agentic_job_id"],
        "job_name": job.get("job_name", ""),
        "job_type": job["job_type"],
        "status": job["status"],
    }
    # Only emit failure_reason when present (FAILED arcs). Omitting it for
    # SUCCESS/CANCELLED keeps those marker lines byte-identical to the frozen
    # Phase 7 D-03 shape — readers use .get('failure_reason', '') so the absent
    # key is a no-op for the metering pipeline.
    failure_reason = job.get("failure_reason", "")
    if failure_reason:
        record["failure_reason"] = failure_reason
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n"
    with open(marker_path, "ab", buffering=0) as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line.encode("utf-8"))
    return marker_path


def _read_job_taxonomy_labels() -> list:
    """Read JOB_TAXONOMY_FILE and return job_type labels sorted recent-first, alpha within ties.

    Copy of _read_taxonomy_labels with TAXONOMY_FILE → JOB_TAXONOMY_FILE.
    Seed entries with no last_seen_at fall into the 'older' alpha bucket — handled
    by the analog without special-casing. Returns [] on any failure (D-04 fail-open).
    """
    try:
        data = json.loads(JOB_TAXONOMY_FILE.read_text(encoding="utf-8"))
        labels = data.get("labels", {})
        if not isinstance(labels, dict):
            return []
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        recent_cutoff = now - datetime.timedelta(days=7)
        recent, older = [], []
        for key, meta in sorted(labels.items()):  # alpha pre-sort for stable tie-break
            raw_ts = meta.get("last_seen_at") if isinstance(meta, dict) else None
            if raw_ts:
                try:
                    ts = datetime.datetime.fromisoformat(raw_ts.rstrip("Z")).replace(
                        tzinfo=datetime.timezone.utc
                    )
                    if ts >= recent_cutoff:
                        recent.append((ts, key))
                        continue
                except Exception:
                    pass
            older.append(key)
        recent.sort(key=lambda x: x[0], reverse=True)
        return [k for _, k in recent] + older
    except Exception:
        pass
    return []


def _persist_job_type_to_taxonomy(job_type: str) -> None:
    """Append job_type to job-taxonomy.json if not already present, updating
    last_seen_at on every call (D-32 mint-back pattern).

    Copy of _persist_label_to_taxonomy with TAXONOMY_FILE → JOB_TAXONOMY_FILE.
    Keeps the sidecar .lock + non-blocking LOCK_EX|LOCK_NB + temp-file .replace()
    + last_seen_at mint-back; same concurrent on_session_end race resolution as
    HARDEN-01 (T-13-04). Skips empty/invalid job_type instead of "unclassified".
    """
    if not job_type:
        return
    import datetime
    try:
        JOB_TAXONOMY_FILE.parent.mkdir(parents=True, exist_ok=True)
        lock_path = JOB_TAXONOMY_FILE.parent / (JOB_TAXONOMY_FILE.name + ".lock")
        try:
            with open(lock_path, "a") as lockfd:
                try:
                    fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    logger.warning(
                        "revenium-classifier: job taxonomy persist skipped, lock contention "
                        "for job_type=%s: %s",
                        job_type,
                        exc,
                    )
                    return
                try:
                    data = json.loads(JOB_TAXONOMY_FILE.read_text(encoding="utf-8"))
                except Exception:
                    data = {"labels": {}}
                labels = data.get("labels", {})
                if not isinstance(labels, dict):
                    labels = {}
                now_iso = datetime.datetime.now(datetime.timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                if job_type not in labels:
                    labels[job_type] = {
                        "description": None,
                        "examples": [],
                        "last_seen_at": now_iso,
                    }
                else:
                    # Update last_seen_at on every successful write (recency ordering D-33).
                    if not isinstance(labels[job_type], dict):
                        labels[job_type] = {}
                    labels[job_type]["last_seen_at"] = now_iso
                data["labels"] = labels
                tmp = JOB_TAXONOMY_FILE.parent / (JOB_TAXONOMY_FILE.name + ".tmp")
                tmp.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                tmp.replace(JOB_TAXONOMY_FILE)
        except OSError as exc:
            logger.warning(
                "revenium-classifier: job taxonomy persist skipped, lock contention "
                "for job_type=%s: %s",
                job_type,
                exc,
            )
            return
    except Exception as exc:
        logger.warning(
            "revenium-classifier: job taxonomy mint-back failed for job_type=%s: %s",
            job_type,
            exc,
        )


def _job_marker_exists(sid: str) -> bool:
    """Return True if a kind:"job" marker line already exists for sid, False otherwise.

    Mirror of _read_latest_task_type line-by-line tolerant parse, but scans for
    any rec.get("kind") == "job" line and returns True on first hit. Fail-open
    returns False (proceed to write) — the cron's JOB:<id>:created ledger gate is
    the ultimate idempotency backstop (D-08). Do NOT mirror _recent_marker_pair_exists;
    D-08 chose presence-scan over wall-clock proximity (PATTERNS.md §_job_marker_exists).
    """
    marker_path = MARKERS_DIR / f"{sid}.jsonl"
    if not marker_path.is_file():
        return False
    try:
        lines = marker_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("kind") == "job":
            return True
    return False


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


def _guardrail_halted() -> bool:
    """Read guardrail-status.json and return True if halted. Fail-open on any
    filesystem or JSON error per D-08."""
    try:
        data = json.loads(GUARDRAIL_STATUS_FILE.read_text(encoding="utf-8"))
        return bool(data.get("halted", False))
    except Exception:
        return False


def _read_taxonomy_labels() -> list:
    """Read TAXONOMY_FILE and return labels sorted recent-first, alpha within ties.

    Labels with a `last_seen_at` ISO timestamp within the last 7 days appear
    first (recent bucket); older labels and labels without `last_seen_at` (seed
    entries) follow alphabetically. Returns [] on any failure (D-04 fail-open)."""
    try:
        data = json.loads(TAXONOMY_FILE.read_text(encoding="utf-8"))
        labels = data.get("labels", {})
        if not isinstance(labels, dict):
            return []
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        recent_cutoff = now - datetime.timedelta(days=7)
        recent, older = [], []
        for key, meta in sorted(labels.items()):  # alpha pre-sort for stable tie-break
            raw_ts = meta.get("last_seen_at") if isinstance(meta, dict) else None
            if raw_ts:
                try:
                    ts = datetime.datetime.fromisoformat(raw_ts.rstrip("Z")).replace(
                        tzinfo=datetime.timezone.utc
                    )
                    if ts >= recent_cutoff:
                        recent.append((ts, key))
                        continue
                except Exception:
                    pass
            older.append(key)
        recent.sort(key=lambda x: x[0], reverse=True)
        return [k for _, k in recent] + older
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
    taxonomy entry.

    Concurrency: a sidecar lock file (TAXONOMY_FILE + ".lock") is held with a
    non-blocking LOCK_EX during the read-modify-write (HARDEN-01). On lock
    contention (BlockingIOError) or any OSError from flock itself the persist is
    skipped and the function returns without raising (D-01, D-02)."""
    if label == "unclassified":
        return
    import datetime
    try:
        TAXONOMY_FILE.parent.mkdir(parents=True, exist_ok=True)
        lock_path = TAXONOMY_FILE.parent / (TAXONOMY_FILE.name + ".lock")
        try:
            with open(lock_path, "a") as lockfd:
                try:
                    fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    logger.warning(
                        "revenium-classifier: taxonomy persist skipped, lock contention for label=%s: %s",
                        label,
                        exc,
                    )
                    return
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
                tmp = TAXONOMY_FILE.parent / (TAXONOMY_FILE.name + ".tmp")
                tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                tmp.replace(TAXONOMY_FILE)
        except OSError as exc:
            logger.warning(
                "revenium-classifier: taxonomy persist skipped, lock contention for label=%s: %s",
                label,
                exc,
            )
            return
    except Exception as exc:
        logger.warning("revenium-classifier: mint-back failed for label=%s: %s", label, exc)


def _muid() -> str:
    """13-char ms-timestamp prefix + 20-char random hex = 33 char lowercase hex."""
    return f"{int(time.time_ns() // 1_000_000):013x}" + secrets.token_hex(10)


def _root_agentic_job_id_for(root_sid: str) -> str:
    """Resolve the root's agentic_job_id by scanning markers/<root_sid>.jsonl
    for the most recent kind:"job" line. Returns "" on missing file, no job
    marker, JSON decode failure, or any OSError. D-05 fail-open.

    Mirrors the cron-side heredoc in hermes-report.sh (plan 22-03 Task 1) so
    the classifier and the cron resolve the same value for the same session.
    Both read the same append-only file with the same latest-wins semantic, so
    the two values agree by construction (Option A per 22-CONTEXT D-02 — this
    field is forward-looking observability in the marker; the cron does NOT
    consume it, it re-resolves independently).

    Pipe/colon/newline sanitization (WR-01 mirror) defends downstream consumers
    against future upstream writers corrupting the bash IFS='|' parse or the
    Revenium CLI's argv handling.
    """
    if not root_sid:
        return ""
    marker_path = MARKERS_DIR / f"{root_sid}.jsonl"
    if not marker_path.exists():
        return ""
    latest_aid = ""
    try:
        with open(marker_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(rec, dict):
                    continue
                if rec.get("kind") == "job":
                    aid = rec.get("agentic_job_id") or ""
                    if isinstance(aid, str) and aid:
                        for _bad in ("|", "\n", "\r", ":"):
                            aid = aid.replace(_bad, "_")
                        latest_aid = aid
    except OSError:
        return ""
    return latest_aid


def _write_marker_pair(sid: str, task_type: str) -> Path:
    """Atomic O_APPEND + fcntl.LOCK_EX write of a GUARDRAIL + CHAT marker pair.

    Per D-14 + HOOK-06: < 1024 bytes per line, exactly two records, single lock.
    Per Phase 2 marker schema: {muid, ts, sid, task_type, operation_type}.

    Phase 22 (MARKER-01): also emits trace_id resolved to the root delegator;
    for subagent sessions also emits agentic_job_id resolved to the root's
    agentic-job (read from markers/<root_sid>.jsonl). Top-level sessions emit
    trace_id == sid (byte-identical to v1.3's behavior on the cron side via the
    `marker.get('trace_id', '')` heredoc fallback) and OMIT agentic_job_id.

    Per 22-CONTEXT D-03: the existing module-level _walk_to_root_session helper
    is reused here (NOT refactored to call the Phase 21 sidecar). The classifier
    and the cron use independent walk implementations with identical semantics.
    """
    MARKERS_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker_path = MARKERS_DIR / f"{sid}.jsonl"

    # Phase 22 (MARKER-01 / D-02 / D-05): resolve root_sid + root_aid ONCE per
    # call, not per record. The two records (GUARDRAIL + CHAT) share the same
    # inheritance state — resolving twice would waste a sqlite walk + file read.
    root_sid = _walk_to_root_session(sid)
    root_aid = _root_agentic_job_id_for(root_sid) if root_sid != sid else ""

    def _record(op: str) -> dict:
        rec = {
            "muid": _muid(),
            "ts": time.time(),
            "sid": sid,
            "task_type": task_type,
            "operation_type": op,
            "trace_id": root_sid,
        }
        if root_aid:
            rec["agentic_job_id"] = root_aid
        return rec

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
    D-13 dedupe (gates task re-write only, not job inference) → budget gate →
    LLM classification → validated label → atomic marker pair write →
    code-side job inference. Invoked from the plugin entrypoint's sync
    wrapper run_classification() via asyncio.run().

    Step 3 (D-13 dedupe) captures agent_self_classified and gates only Steps
    4-6 (task write path) behind 'if not agent_self_classified:'. Step 7
    (job inference) runs unconditionally afterward so that job markers are
    produced on the dominant self-classify code path. Step 7 carries its own
    three idempotency gates (root_sid, _guardrail_halted, _job_marker_exists).
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
        # Capture as a boolean instead of returning early so Step 7 still runs.
        # Steps 4-6 (task write path) are skipped when the agent already wrote
        # markers; Step 7 (job inference) is always attempted afterward.
        agent_self_classified = _recent_marker_pair_exists(session_id, within_seconds=30.0)

        if not agent_self_classified:
            # Step 4 — budget gate (D-08 / HOOK-04).
            if _guardrail_halted():
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

        # Step 7 — code-side job-inference (D-01 / Phase 13).
        # Runs unconditionally on every reachable path (self-classified or not).
        # Three early skip gates: root-session only, not guardrail-halted, no existing job marker.
        # Wrapped in its own try/except so a job-path failure never disturbs the task marker
        # already written above (D-04 never-raise invariant, T-13-08).
        try:
            if (
                root_sid == session_id  # skip subagent sessions (T-13-06)
                and not _guardrail_halted()  # skip when halted (T-13-09)
                and not _job_marker_exists(session_id)  # skip if job already written (T-13-07 / D-08)
            ):
                transcript = _read_session_transcript(session_id)
                if transcript:
                    job_labels = _read_job_taxonomy_labels()
                    jobs = await _infer_jobs_via_llm(transcript, job_labels)
                    for job in jobs:
                        try:
                            valid = _validate_job(job)
                            if valid:
                                await asyncio.to_thread(_write_job_marker, session_id, valid)
                                _persist_job_type_to_taxonomy(valid["job_type"])
                        except Exception as exc:
                            logger.warning(
                                "revenium-classifier: dropping one job for sid=%s: %s",
                                session_id,
                                exc,
                            )
        except Exception as exc:
            logger.warning(
                "revenium-classifier job inference failed for sid=%s: %s",
                session_id,
                exc,
            )
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
