"""Prompt construction.

SPIKE FINDING (see README Investigation Trail): the original prompts hardcode
the string "Hermes" in three places. That makes them host-specific text, not
generic logic. The seam here is `host` — a parameter defaulting to "Hermes" so
extraction is byte-identical for the existing plugin, while a LiteLLM guardrail
or Claude Code host can pass its own framing.

Any host that passes a different `host` value gets a different prompt and
therefore potentially different labels. That is a behavior change, not a
refactor — it belongs in the taxonomy-governance question (spike 003).
"""
from __future__ import annotations

DEFAULT_HOST = "Hermes"

# The turn-level framing. `{host}` is the only variable text.
_TURN_SYSTEM = "You classify {host} turns into task_type labels. Output only the label."
_JOB_SYSTEM = (
    "You analyze {host} agent session transcripts to identify "
    "completed task arcs. Output only a JSON array."
)


def turn_system_prompt(host: str = DEFAULT_HOST) -> str:
    return _TURN_SYSTEM.format(host=host)


def job_system_prompt(host: str = DEFAULT_HOST) -> str:
    return _JOB_SYSTEM.format(host=host)


def build_classification_prompt(
    user_msg: str,
    assistant_resp: str,
    labels: list,
    host: str = DEFAULT_HOST,
) -> str:
    """Mint-first classification prompt. Byte-identical to the original at host='Hermes'."""
    labels_block = ", ".join(labels) if labels else "(no existing labels yet)"
    if len(labels_block) > 1024:
        labels_block = labels_block[:1024] + " ... [truncated]"
    user_preview = (user_msg or "")[:800]
    asst_preview = (assistant_resp or "")[:800]
    return (
        f"You are classifying a {host} session turn for spend attribution. "
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


def build_job_inference_prompt(
    transcript: str,
    job_labels: list,
    host: str = DEFAULT_HOST,
) -> str:
    """Job-inference prompt. Byte-identical to the original at host='Hermes'."""
    labels_block = ", ".join(job_labels) if job_labels else "(no existing labels yet)"
    if len(labels_block) > 1024:
        labels_block = labels_block[:1024] + " ... [truncated]"
    transcript_preview = (transcript or "")[:6000]
    return (
        f"You are analyzing a {host} AI agent session to identify the discrete task arcs "
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
