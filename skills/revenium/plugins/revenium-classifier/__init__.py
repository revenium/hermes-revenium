"""revenium-classifier plugin entrypoint.

Hermes' plugin manager imports this package and calls register(ctx) at
agent startup; we wire on_session_end → _on_session_end which dispatches
into the shared classifier.run_classification for the actual classification
+ marker write.

Invariant D-04: _on_session_end MUST NEVER raise — exceptions are logged
via logger.warning and swallowed so the plugin manager does not mark the
plugin unhealthy.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .classifier import run_classification, MARKERS_READY_DIR

logger = logging.getLogger("revenium_classifier")


def _write_sentinel(session_id) -> None:
    """D-21 sentinel write: emits an empty file at MARKERS_READY_DIR / session_id
    to signal to the cron pipeline that the plugin has completed processing for
    this session. Cron's session-SELECT filter at hermes-report.sh treats sentinel
    presence as 'plugin signalled ready' and reports the session this tick;
    sentinel absence defers reporting until the session's started_at ages past
    REVENIUM_CRON_SETTLE_SECONDS (default 120s).

    D-04 belt: any IOError / OSError / PermissionError on the sentinel write is
    logged and swallowed — the sentinel is best-effort, and the cron's
    aged-safety-net handles silent failures. This helper NEVER raises.
    """
    if not session_id:
        return
    try:
        MARKERS_READY_DIR.mkdir(parents=True, exist_ok=True)
        sentinel_path = MARKERS_READY_DIR / session_id
        sentinel_path.touch(exist_ok=True)
    except Exception as exc:
        logger.warning(
            "revenium-classifier sentinel write failed for sid=%s: %s",
            session_id,
            exc,
        )


def _on_session_end(
    *,
    session_id,
    completed,
    interrupted,
    model=None,
    platform=None,
    **kwargs,
) -> None:
    """Synchronous on_session_end callback per the Hermes plugin contract.

    Hermes' plugin bus invokes this after run_conversation() has returned.
    We dispatch into the shared classifier.run_classification which itself
    runs the async pipeline under asyncio.run().

    D-04 belt: any exception raised by the underlying pipeline is caught and
    logged here. The plugin manager only marks plugins unhealthy when their
    callbacks raise — we never propagate.

    D-21: after run_classification completes (every outcome — substantive
    marker write, trivial-skip, inheritance, halt-unclassified), AND in the
    outer except handler (D-04 belt extension), we write a per-session
    sentinel at MARKERS_READY_DIR / session_id so the cron pipeline can
    proceed without racing the LLM classifier.

    **kwargs absorbs any additional fields a future Hermes version may add
    to the on_session_end payload, keeping the plugin forward-compatible.
    """
    try:
        if not session_id:
            return
        run_classification(
            session_id=session_id,
            model=model,
            platform=platform,
            message=None,
            response=None,
        )
        _write_sentinel(session_id)
    except Exception as exc:
        logger.warning(
            "revenium-classifier on_session_end failed for sid=%s completed=%s interrupted=%s: %s",
            session_id,
            completed,
            interrupted,
            exc,
        )
        _write_sentinel(session_id)


def register(ctx) -> None:
    """Plugin registration entry point per the Hermes plugin contract.

    Hermes' plugin manager imports this package at agent startup and calls
    register(ctx) exactly once. We register the _on_session_end callback
    against the on_session_end event so it fires for every run_conversation()
    exit (gateway-served + CLI + interactive + ACP + cron-spawned).

    No try/except — registration failure must surface to the plugin manager
    so operators see the unhealthy-plugin state at gateway-restart time.
    """
    ctx.register_hook("on_session_end", _on_session_end)
