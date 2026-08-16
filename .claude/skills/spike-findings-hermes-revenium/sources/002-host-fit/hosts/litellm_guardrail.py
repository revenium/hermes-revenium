"""Host adapter: LiteLLM custom guardrail.

The constraint that makes this host interesting: a guardrail sees ONE
request/response pair. There is no session database, no prior turns, no durable
per-session filesystem, and the hook runs on the caller's critical path.

Everything Hermes' classifier does to *find* a transcript is therefore
inapplicable — the transcript is simply handed to you. This adapter is the whole
Hermes-side 76% replaced by ~20 lines, because this host's session model is
trivial.

What it does NOT solve: with no session identity, per-arc job inference is
meaningless here (one request is not an arc), and the taxonomy has nowhere local
to live — see spike 003.
"""
from __future__ import annotations


def extract_turn(payload: dict) -> "tuple[str, str]":
    """Pull (user_message, assistant_response) out of a guardrail payload."""
    data = payload.get("data") or {}
    messages = data.get("messages") or []
    user = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            user = m.get("content") or ""
            break
    response = payload.get("response") or {}
    choices = response.get("choices") or []
    assistant = ""
    if choices:
        assistant = ((choices[0] or {}).get("message") or {}).get("content") or ""
    return user, assistant


def attribution_keys(payload: dict) -> dict:
    """The identity a guardrail actually has — API-key metadata, not a session id."""
    meta = ((payload.get("data") or {}).get("metadata")) or {}
    return {
        "team_id": meta.get("user_api_key_team_id"),
        "user_id": meta.get("user_api_key_user_id"),
        "key_alias": meta.get("user_api_key_alias"),
        "model": (payload.get("data") or {}).get("model"),
    }


def classify(payload: dict, classifier) -> dict:
    user, assistant = extract_turn(payload)
    label = classifier.classify_turn(user, assistant)
    return {"task_type": label, **attribution_keys(payload)}
