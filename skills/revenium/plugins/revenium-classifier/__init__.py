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

from .classifier import run_classification

logger = logging.getLogger("revenium_classifier")


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
    except Exception as exc:
        logger.warning(
            "revenium-classifier on_session_end failed for sid=%s completed=%s interrupted=%s: %s",
            session_id,
            completed,
            interrupted,
            exc,
        )


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
