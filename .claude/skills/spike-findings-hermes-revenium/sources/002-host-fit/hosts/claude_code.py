"""Host adapter: Claude Code session transcripts.

Claude Code writes one JSONL per session under
~/.claude/projects/<slug>/<session-uuid>.jsonl. Record shapes observed on this
machine (2026-08-15):

  type=user      -> message.content (str or content-block list), sessionId,
                    isSidechain, uuid, parentUuid, cwd, gitBranch
  type=assistant -> message.content (block list), message.usage{input_tokens,
                    output_tokens, cache_read_input_tokens,
                    cache_creation_input_tokens}, requestId, isSidechain
  plus: ai-title, last-prompt, mode, permission-mode, attachment,
        file-history-snapshot/delta, system

This host is a much closer analogue to Hermes than the guardrail is: it HAS a
session, a subagent flag (`isSidechain`, the analogue of Hermes'
parent_session_id), per-call usage numbers, and a durable file per session. Which
means it re-poses most of the questions Hermes' 76% answers — dedupe, idempotency,
where markers live — just against different primitives.
"""
from __future__ import annotations

import json
from pathlib import Path

TEXT_TYPES = ("user", "assistant")


def load_turns(path) -> list:
    """Return [{role, content, isSidechain, sessionId, usage}] for text-bearing turns."""
    turns = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("type") not in TEXT_TYPES:
            continue
        msg = rec.get("message") or {}
        content = msg.get("content")
        if isinstance(content, list):
            parts = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    parts.append(f"[tool_use:{block.get('name')}]")
            content = "\n".join(p for p in parts if p)
        if not isinstance(content, str) or not content.strip():
            continue
        turns.append({
            "role": msg.get("role") or rec.get("type"),
            "content": content,
            "isSidechain": bool(rec.get("isSidechain")),
            "sessionId": rec.get("sessionId"),
            "usage": msg.get("usage") or {},
        })
    return turns


def first_exchange(turns: list) -> "tuple[str, str]":
    """The (user, next assistant) pair — the turn-level classification input."""
    for i, t in enumerate(turns):
        if t["role"] == "user":
            for nxt in turns[i + 1:]:
                if nxt["role"] == "assistant":
                    return t["content"], nxt["content"]
            return t["content"], ""
    return "", ""


def render_transcript(turns: list, limit: int = 6000) -> str:
    """Flatten to the plain transcript string the job-inference prompt wants."""
    out = []
    for t in turns:
        out.append(f"{t['role']}: {t['content']}")
    return "\n".join(out)[:limit]


def session_tokens(turns: list) -> dict:
    """What this host can attribute spend with — the analogue of Hermes' state.db row."""
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    for t in turns:
        u = t.get("usage") or {}
        totals["input"] += u.get("input_tokens", 0) or 0
        totals["output"] += u.get("output_tokens", 0) or 0
        totals["cache_read"] += u.get("cache_read_input_tokens", 0) or 0
        totals["cache_write"] += u.get("cache_creation_input_tokens", 0) or 0
    return totals


def classify(path, classifier) -> dict:
    turns = load_turns(path)
    user, assistant = first_exchange(turns)
    label = classifier.classify_turn(user, assistant)
    return {
        "task_type": label,
        "session_id": turns[0]["sessionId"] if turns else None,
        "turns": len(turns),
        "subagent_turns": sum(1 for t in turns if t["isSidechain"]),
        "tokens": session_tokens(turns),
    }
