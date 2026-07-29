"""revenium-classifier plugin entrypoint.

Hermes' plugin manager imports this package and calls register(ctx) at
agent startup; we wire on_session_end → _on_session_end which dispatches
into the shared classifier.run_classification for the actual classification
+ marker write.

Phase 29 (HOOK-01): on_session_end fires only from _session_expiry_watcher,
which never runs while Hermes' SessionResetPolicy defaults to mode:"none" —
so interactive gateway sessions were never classified. on_session_finalize
fires from three production sites (gateway/run.py shutdown + session_expired,
slash_commands.py user reset) and needs no reset policy, so we ALSO wire
on_session_finalize → a dedicated _on_session_finalize callback. The two
hooks carry different kwargs (see _on_session_finalize's docstring) and are
therefore never signature-compatible — each gets its own callback.

Invariant D-04: neither _on_session_end nor _on_session_finalize MUST EVER
raise — exceptions are logged via logger.warning and swallowed so the
plugin manager does not mark the plugin unhealthy.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .classifier import run_classification, MARKERS_READY_DIR, _paths_for_session

logger = logging.getLogger("revenium_classifier")


def _write_sentinel(session_id) -> None:
    """D-21 sentinel write: emits an empty file at MARKERS_READY_DIR / session_id
    to signal to the cron pipeline that the plugin has completed processing for
    this session. Cron's session-SELECT filter at hermes-report.sh treats sentinel
    presence as 'plugin signalled ready' and reports the session this tick;
    sentinel absence defers reporting until the session's started_at ages past
    REVENIUM_CRON_SETTLE_SECONDS (default 600s per BUG-1).

    BUG-4: the sentinel MUST land under the OWNING profile's markers/.ready dir so
    that profile's per-profile cron picks it up. In the multiplex single-gateway
    process the module MARKERS_READY_DIR points at the default home, which would
    strand a namespaced session's sentinel; _paths_for_session resolves the
    profile's ready dir. Non-multiplex sessions resolve to the module dir
    (byte-identical to before).

    D-04 belt: any IOError / OSError / PermissionError on the sentinel write is
    logged and swallowed — the sentinel is best-effort, and the cron's
    aged-safety-net handles silent failures. This helper NEVER raises.
    """
    if not session_id:
        return
    try:
        ready_dir = _paths_for_session(session_id).markers_ready_dir
        ready_dir.mkdir(parents=True, exist_ok=True)
        sentinel_path = ready_dir / session_id
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


def _on_session_finalize(
    *,
    session_id,
    platform=None,
    reason=None,
    **kwargs,
) -> None:
    """Synchronous on_session_finalize callback per the Hermes plugin contract.

    on_session_finalize fires from three production sites — gateway shutdown
    (reason="shutdown"), session expiry (reason="session_expired"), and a
    user-initiated slash-command reset (reason="new_session") — and requires
    no session_reset configuration, unlike on_session_end which only ever
    fires from _session_expiry_watcher. This hook carries NO `completed` and
    NO `interrupted` kwarg (confirmed by direct source read, see
    29-RESEARCH.md / <hook_signature_contract>); it MUST NOT reuse
    _on_session_end's signature, which would TypeError on every real
    invocation and be silently swallowed by Hermes' invoke_hook.

    On a reset path the payload also carries old_session_id / new_session_id
    (absorbed by **kwargs); this callback always classifies the session_id it
    was handed, never those.

    D-06: this callback does NOT pre-check whether session_id already has a
    marker — that permanent guard is implemented once, authoritatively,
    inside run_classification_async (plan 29-04) so every registered trigger
    inherits it regardless of firing order. Calling run_classification
    unconditionally here is correct both before and after that guard lands.

    D-04 belt: any exception raised by the underlying pipeline is caught and
    logged here; we never propagate so the plugin manager does not mark the
    plugin unhealthy.

    D-21: after run_classification completes (any outcome), AND in the outer
    except handler (D-04 belt extension), we write the same per-session
    sentinel _on_session_end writes — on_session_finalize is a genuine
    session boundary, semantically equivalent for the cron's
    sentinel-or-aged filter, and restoring it here is what makes Phase 28's
    fleet liveness signal meaningful again for interactive gateway traffic.

    **kwargs absorbs any additional fields (old_session_id, new_session_id,
    or fields a future Hermes version may add) so the plugin stays
    forward-compatible.
    """
    try:
        if not session_id:
            return
        run_classification(
            session_id=session_id,
            model=None,
            platform=platform,
            message=None,
            response=None,
        )
        _write_sentinel(session_id)
    except Exception as exc:
        logger.warning(
            "revenium-classifier on_session_finalize failed for sid=%s reason=%s: %s",
            session_id,
            reason,
            exc,
        )
        _write_sentinel(session_id)


def register(ctx) -> None:
    """Plugin registration entry point per the Hermes plugin contract.

    Hermes' plugin manager imports this package at agent startup and calls
    register(ctx) exactly once. We register:

    - _on_session_end against on_session_end, which fires for every
      run_conversation() exit (gateway-served + CLI + interactive + ACP +
      cron-spawned) — but only when _session_expiry_watcher actually runs.
    - _on_session_finalize against on_session_finalize, which fires from
      three production sites and needs no session_reset configuration, so
      it is the one that actually classifies interactive gateway sessions
      today (Phase 29 / HOOK-01).

    No try/except — registration failure must surface to the plugin manager
    so operators see the unhealthy-plugin state at gateway-restart time.
    """
    ctx.register_hook("on_session_end", _on_session_end)
    ctx.register_hook("on_session_finalize", _on_session_finalize)
