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

Phase 29 (HOOK-02): on_session_finalize still waits for a session boundary
(shutdown, expiry, or reset) that may be minutes or hours away. post_llm_call
fires once per COMPLETED turn from agent/turn_finalizer.py, so we ALSO wire
post_llm_call → a dedicated _on_post_llm_call callback, making an ordinary
session produce a classified job on its first turn. Because run_classification
now invokes an auxiliary LLM on a per-turn hook, Phase 29 also promotes
classifier._session_already_classified to the single authoritative gate at
run_classification_async's Step 3 (HOOK-03/HOOK-04) — every registered
trigger inherits that one guard, so "exactly one classification per session"
holds regardless of which hook fires first.

Invariant D-04: none of _on_session_end, _on_session_finalize,
_on_post_llm_call, or _on_post_api_request MUST EVER raise — exceptions are
logged via logger.warning and swallowed so the plugin manager does not mark
the plugin unhealthy.

Phase 32 (D-01/D-02/EVT-01): a fourth hook, post_api_request, is registered
here for event-driven completion metering. Unlike the three hooks above it
carries no classification concern at all -- it delegates straight to
api_event_spool.spool_api_request, which appends a JSONL record to a
per-session spool file and makes NO network call (D-01). It fires ONCE PER
API CALL rather than once per turn (RESEARCH.md Pitfall 2), so it must never
inherit the other callbacks' accepted turn-1 LLM-call latency.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .classifier import run_classification, MARKERS_READY_DIR, _paths_for_session
from .api_event_spool import spool_api_request

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


def _on_post_llm_call(
    *,
    session_id,
    task_id=None,
    turn_id=None,
    user_message=None,
    assistant_response=None,
    conversation_history=None,
    model=None,
    platform=None,
    **kwargs,
) -> None:
    """Synchronous post_llm_call callback per the Hermes plugin contract.

    post_llm_call fires from agent/turn_finalizer.py's finalize_turn, guarded
    upstream by 'if final_response and not interrupted:' — so it fires once
    per COMPLETED turn (an interrupted turn fires nothing at all; the
    on_session_finalize boundary hook is what classifies that session
    instead, per CONTEXT.md D-06). Confirmed kwargs (RESEARCH.md /
    <hook_signature_contract>): session_id, task_id, turn_id, user_message,
    assistant_response, conversation_history, model, platform. This hook
    carries NO `completed` and NO `interrupted` kwarg of its own — it must
    NOT reuse _on_session_end's or _on_session_finalize's signature.

    D-05: classifying on the first completed turn is what makes an ordinary
    prompt produce a job without waiting for a session boundary. Passing the
    turn's own user_message/assistant_response through as message/response
    (rather than None, the way _on_session_end does) matters, not merely for
    symmetry: post_llm_call fires from finalize_turn, so at turn 1 the
    exchange may not yet be persisted to state.db, and Step 5's
    _read_session_messages fallback would then classify an empty
    conversation. Handing this callback's own turn content to Step 5 makes
    turn-1 classification independent of persistence timing.

    No guard here. Task 1 (Phase 29 / HOOK-03) placed the authoritative
    already-classified latch inside run_classification_async's Step 3, where
    the per-session _Paths are already resolved by _paths_for_session. A
    second guard in this file would need to resolve those paths again, which
    is exactly where a multiplexed-profile session would get the wrong
    markers directory. One gate, one path resolution — every registered
    trigger inherits it.

    No sentinel here, deliberately. _write_sentinel means "the plugin has
    finished with this session", and the cron's sentinel-or-aged filter
    (hermes-report.sh) reports a session immediately once the sentinel
    appears. Writing it mid-session (post_llm_call fires on every turn, not
    just the last one) would change WHEN live sessions are metered — a
    metering-timing change no requirement in this phase asks for, and one
    that would interact with Phase 28's liveness/sentinel-or-aged logic in
    ways this plan does not analyze. D-05's goal — the session's first
    metered delta carries a real trace type — is already achieved by the
    turn-1 marker landing before the reporter picks the session up at the
    settle boundary; the sentinel stays the job of a genuine session
    boundary (_on_session_end / _on_session_finalize).

    Accepted latency cost: run_classification blocks on asyncio.run and
    makes a real auxiliary-LLM call, so the FIRST turn of a session pays
    that latency on the user-visible completion path — unlike
    on_session_end/on_session_finalize, which fire after the user already
    has their response. D-05 accepts this by choosing turn 1. Every
    subsequent turn in the same session short-circuits on Task 1's
    permanent latch and costs only a marker-file read.

    D-04 belt: any exception raised by the underlying pipeline is caught and
    logged here; we never propagate so the plugin manager does not mark the
    plugin unhealthy.

    **kwargs absorbs any additional fields a future Hermes version may add
    to the post_llm_call payload, keeping the plugin forward-compatible.
    """
    try:
        if not session_id:
            return
        run_classification(
            session_id=session_id,
            model=model,
            platform=platform,
            message=user_message,
            response=assistant_response,
        )
    except Exception as exc:
        logger.warning(
            "revenium-classifier post_llm_call failed for sid=%s turn_id=%s: %s",
            session_id,
            turn_id,
            exc,
        )


def _on_post_api_request(
    *,
    session_id,
    api_request_id=None,
    task_id=None,
    turn_id=None,
    platform=None,
    model=None,
    provider=None,
    base_url=None,
    api_mode=None,
    api_call_count=None,
    api_duration=None,
    started_at=None,
    ended_at=None,
    finish_reason=None,
    message_count=None,
    response_model=None,
    response=None,
    usage=None,
    assistant_message=None,
    assistant_content_chars=None,
    assistant_tool_call_count=None,
    **kwargs,
) -> None:
    """Synchronous post_api_request callback per the Hermes plugin contract.

    Phase 32 (D-01/D-02/EVT-01): fires ONCE PER API CALL, not once per turn
    like the other three callbacks in this file (RESEARCH.md Pitfall 2) —
    often several times within a single turn's tool-call round trips. Does
    exactly one thing: hands its kwargs to api_event_spool.spool_api_request,
    which appends a JSONL record to disk and makes NO network call, NO LLM
    call, and NO database read (D-01).

    `response` and `assistant_message` are deliberately NOT forwarded to the
    spool writer. Contract C-2 forbids prompt/response content from ever
    entering the spool record (T-32-03), and per Contract C-3 (the ported
    langfuse fix, docs/plugin-interface-findings.md § E2), `response` on
    THIS hook is always a sanitized dict with no real `.usage` attribute —
    the writer reads token counts directly from the separate top-level
    `usage` summary kwarg, never from `response`.

    D-04 belt: spool_api_request already wraps its own body in
    try/except + logger.warning, but this callback catches again so a
    defect anywhere in the metering handler can never surface as a broken
    turn — matching the belt-and-suspenders posture of every callback here.

    **kwargs absorbs any additional fields a future Hermes version may add
    to the post_api_request payload, keeping the plugin forward-compatible.
    """
    try:
        if not session_id:
            return
        spool_api_request(
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
            "revenium-classifier post_api_request failed for sid=%s api_request_id=%s: %s",
            session_id,
            api_request_id,
            exc,
        )


def register(ctx) -> None:
    """Plugin registration entry point per the Hermes plugin contract.

    Hermes' plugin manager imports this package at agent startup and calls
    register(ctx) exactly once. We register:

    - _on_session_end against on_session_end, which fires for every
      run_conversation() exit (gateway-served + CLI + interactive + ACP +
      cron-spawned) — but only when _session_expiry_watcher actually runs.
    - _on_session_finalize against on_session_finalize, which fires from
      three production sites and needs no session_reset configuration, so
      it is the one that classifies a session at its boundary (shutdown,
      expiry, or reset) regardless of whether anything classified it
      earlier (Phase 29 / HOOK-01).
    - _on_post_llm_call against post_llm_call, which fires once per
      COMPLETED turn from agent/turn_finalizer.py — the trigger that
      classifies an ordinary session on its FIRST turn, without waiting for
      any boundary (Phase 29 / HOOK-02).
    - _on_post_api_request against post_api_request, which fires once per
      API CALL (Phase 32 / D-02) and spools a per-call metering event —
      unrelated to classification, kept in its own module
      (api_event_spool.py) so the seam stays visible.

    The first three callbacks dispatch into the same run_classification
    pipeline, which gates re-classification behind the single permanent
    latch at run_classification_async's Step 3 (Phase 29 / HOOK-03,
    HOOK-04) — so "exactly one classification per session" is a property of
    the pipeline, not of any one callback or firing order. The fourth
    callback is independent of that pipeline entirely.

    No try/except — registration failure must surface to the plugin manager
    so operators see the unhealthy-plugin state at gateway-restart time.
    """
    ctx.register_hook("on_session_end", _on_session_end)
    ctx.register_hook("on_session_finalize", _on_session_finalize)
    ctx.register_hook("post_llm_call", _on_post_llm_call)
    ctx.register_hook("post_api_request", _on_post_api_request)
