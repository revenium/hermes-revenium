"""api_event_spool.py — the metering handler for the post_api_request hook.

Phase 32 (D-01/D-02/D-03): kept as its own module, separate from
classifier.py, so the metering seam stays visible even though both live
inside the revenium-classifier plugin package (D-02's accepted cost: the
plugin is no longer purely a classifier).

Invariant (RESEARCH.md Pitfall 2): post_api_request fires ONCE PER API CALL,
often several times per turn -- unlike the classification hooks in
__init__.py, which are allowed turn-1 latency as an accepted, bounded cost
(Phase 29 D-05). This module must never inherit that budget: it does exactly
one thing, build a small dict from kwargs and append it to a per-session
JSONL file under a lock. No asyncio, no call_llm, no sqlite3.connect, no
network call of any kind (D-01) -- multiplying any of those by the per-turn
API-call count would violate D-01 directly.

Invariant (D-04 belt, matching every other callback in this plugin):
spool_api_request() must NEVER raise. Every error path is caught and logged
via logger.warning; a raising metering hook degrades the agent from
"no metering" to "broken turn".

Contract C-2 (32-01-PLAN.md <shared_contracts>): a spool record is a closed
19-key allowlist. Content is forbidden -- no prompt text, no response text,
and no field derived from either may ever enter the record (T-32-03). This
is why the hook's `response` and `assistant_message` kwargs are never even
threaded through to this module by __init__.py's _on_post_api_request.

Contract C-3 (the ported langfuse fix, established by live testing against
§ E2): token counts are read from the separate top-level `usage` kwarg,
which on this hook is always a pre-built summary dict -- never from a
`.usage` attribute on `response` (which is always a sanitized plain dict on
this hook and therefore never carries that attribute).
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import re
from pathlib import Path

from .classifier import STATE_DIR, _paths_for_session

logger = logging.getLogger("revenium_classifier")

# T-32-01 (mirrors post_tool_call.sh's CR-01 control byte-for-byte): only
# alphanumeric, underscore, hyphen; max 128 chars. Applied to the SPOOL
# FILENAME COMPONENT only (see _filename_component_for_session below) -- not
# to the raw session_id, which for a namespaced multiplex identifier
# legitimately contains colons that must still resolve.
_SID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

# `agent:<profile>:<rest>` namespace (multiplex). Mirrors classifier.py's
# _NS_RE exactly -- deliberately not shared code (see classifier.py's own
# docstring on why the two implementations stay independent).
_NS_RE = re.compile(r"^agent:([^:]+):")

# Contract C-2: the closed allowlist of keys a spool record may carry, and
# nothing else. A test asserts a written record's key set equals this
# exactly, so a future field addition that leaks prompt/response content
# turns the suite red rather than shipping silently.
_RECORD_KEYS = (
    "v", "sid", "api_request_id", "ts", "ended_at", "duration_ms", "platform",
    "model", "response_model", "provider", "base_url", "api_mode",
    "finish_reason", "input_tokens", "output_tokens", "cache_read_tokens",
    "cache_write_tokens", "reasoning_tokens", "total_tokens",
)


def _spool_dir_for_session(session_id: str) -> Path:
    """Resolve the api-events spool directory that OWNS this session.

    Mirrors classifier._paths_for_session's per-session resolution (C-1):
    for a namespaced session whose profile home exists on disk, the
    profile-scoped state_dir; otherwise the module-level STATE_DIR, at
    which point (and ONLY then) the REVENIUM_EVENT_SPOOL_DIR override (if
    set) takes precedence -- mirroring the classifier's own
    fall-back-to-module-paths semantics exactly. The env var is read live
    (not frozen at import time) so tests can redirect it without a module
    reload.
    """
    paths = _paths_for_session(session_id)
    if paths.state_dir == STATE_DIR:
        override = os.environ.get("REVENIUM_EVENT_SPOOL_DIR")
        if override:
            return Path(override)
        return STATE_DIR / "api-events"
    return paths.state_dir / "api-events"


def _filename_component_for_session(session_id: str) -> str:
    """The portion of session_id that becomes the spool filename.

    For a namespaced `agent:<profile>:<rest>` identifier, per-profile
    resolution (_spool_dir_for_session, above) has already consumed the
    `agent:<profile>:` prefix to choose the owning directory -- the
    remainder is what is validated and used as the filename component. A
    non-namespaced identifier is used as-is. Validation against _SID_RE
    happens in the caller; this function only strips the prefix.
    """
    s = str(session_id)
    m = _NS_RE.match(s)
    if m:
        return s[m.end():]
    return s


def _sanitize_api_request_id(api_request_id) -> str:
    """Contract C-4: strip |, \\n, \\r (colons are structural and preserved);
    cap at 256 chars."""
    s = str(api_request_id) if api_request_id is not None else ""
    for bad in ("|", "\n", "\r"):
        s = s.replace(bad, "")
    return s[:256]


def _extract_usage(usage) -> "dict | None":
    """Contract C-3: read token counts from the top-level `usage` kwarg.

    A usage that is absent, None, empty, or not a dict means the call
    produced no usage -- callers must write no record (not a record of
    zeros). `output_tokens` falls back to `completion_tokens` when the key
    is genuinely absent (not merely zero), mirroring langfuse's own
    fallback verbatim.
    """
    if not isinstance(usage, dict) or not usage:
        return None

    def _int(key: str, fallback_key: "str | None" = None) -> int:
        val = usage.get(key)
        if val is None and fallback_key is not None:
            val = usage.get(fallback_key)
        try:
            return int(val or 0)
        except (TypeError, ValueError):
            return 0

    return {
        "input_tokens": _int("input_tokens"),
        "output_tokens": _int("output_tokens", "completion_tokens"),
        "cache_read_tokens": _int("cache_read_tokens"),
        "cache_write_tokens": _int("cache_write_tokens"),
        "reasoning_tokens": _int("reasoning_tokens"),
        "total_tokens": _int("total_tokens"),
    }


def _spool_api_request_inner(
    *,
    session_id,
    api_request_id,
    started_at,
    ended_at,
    platform,
    model,
    response_model,
    provider,
    base_url,
    api_mode,
    api_duration,
    finish_reason,
    usage,
) -> None:
    if not session_id:
        logger.warning(
            "revenium-classifier spool_api_request: missing session_id, dropping event"
        )
        return

    filename_component = _filename_component_for_session(session_id)
    if not _SID_RE.match(filename_component):
        logger.warning(
            "revenium-classifier spool_api_request: session_id %r failed "
            "filename validation, dropping event",
            session_id,
        )
        return

    arid = _sanitize_api_request_id(api_request_id)
    if not arid:
        logger.warning(
            "revenium-classifier spool_api_request: empty api_request_id "
            "after sanitisation for sid=%s, dropping event",
            session_id,
        )
        return

    usage_fields = _extract_usage(usage)
    if usage_fields is None:
        # No usage means the call produced nothing to meter -- not an error,
        # not logged (a call that legitimately errored before a response is
        # a routine occurrence, not a defect to warn about every time).
        return

    spool_dir = _spool_dir_for_session(str(session_id))
    spool_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Ensure 0o700 even if a prior process (e.g. common.sh's eager mkdir -p)
    # created the dir first with a umask-constrained mode (mirrors
    # post_tool_call.sh's identical belt-and-suspenders chmod).
    try:
        os.chmod(spool_dir, 0o700)
    except OSError:
        pass

    event_path = spool_dir / f"{filename_component}.jsonl"

    # T-32-01: path-confinement assertion -- event_path must resolve inside
    # spool_dir (mirrors post_tool_call.sh's identical CR-01 assertion).
    resolved_dir = os.path.realpath(str(spool_dir))
    resolved_file = os.path.realpath(str(event_path))
    if os.path.commonpath([resolved_file, resolved_dir]) != resolved_dir:
        logger.warning(
            "revenium-classifier spool_api_request: resolved event path "
            "escaped spool dir for sid=%s, dropping event",
            session_id,
        )
        return

    record = {
        "v": 1,
        "sid": str(session_id),
        "api_request_id": arid,
        "ts": float(started_at),
        "ended_at": float(ended_at),
        "duration_ms": int(round(float(api_duration) * 1000)),
        "platform": str(platform or ""),
        "model": str(model or ""),
        "response_model": str(response_model or ""),
        "provider": str(provider or ""),
        "base_url": str(base_url or ""),
        "api_mode": str(api_mode or ""),
        "finish_reason": str(finish_reason or ""),
        "input_tokens": usage_fields["input_tokens"],
        "output_tokens": usage_fields["output_tokens"],
        "cache_read_tokens": usage_fields["cache_read_tokens"],
        "cache_write_tokens": usage_fields["cache_write_tokens"],
        "reasoning_tokens": usage_fields["reasoning_tokens"],
        "total_tokens": usage_fields["total_tokens"],
    }
    # Contract C-2: exactly the 19-key allowlist, nothing more -- catches a
    # future field addition (e.g. a raw response snippet) before it ships.
    assert set(record.keys()) == set(_RECORD_KEYS)

    line = json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n"
    with open(event_path, "ab", buffering=0) as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(line.encode("utf-8"))


def spool_api_request(
    *,
    session_id=None,
    api_request_id=None,
    started_at=None,
    ended_at=None,
    platform=None,
    model=None,
    response_model=None,
    provider=None,
    base_url=None,
    api_mode=None,
    api_duration=None,
    finish_reason=None,
    usage=None,
    **kwargs,
) -> None:
    """Append one contract-C-2 record to this session's api-events spool.

    Never raises (D-04 belt) -- wraps the entire body. Makes no network
    call, no LLM call, no database read (D-01, RESEARCH Pitfall 2).

    **kwargs absorbs any additional fields __init__.py's callback forwards
    (or a future Hermes version adds) that this module does not use.
    """
    try:
        _spool_api_request_inner(
            session_id=session_id,
            api_request_id=api_request_id,
            started_at=started_at,
            ended_at=ended_at,
            platform=platform,
            model=model,
            response_model=response_model,
            provider=provider,
            base_url=base_url,
            api_mode=api_mode,
            api_duration=api_duration,
            finish_reason=finish_reason,
            usage=usage,
        )
    except Exception as exc:
        logger.warning(
            "revenium-classifier spool_api_request failed for sid=%s api_request_id=%s: %s",
            session_id,
            api_request_id,
            exc,
        )
