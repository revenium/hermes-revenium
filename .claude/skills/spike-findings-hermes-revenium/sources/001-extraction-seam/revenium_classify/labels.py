"""Pure label/job grammar. No I/O, no host coupling, no third-party imports.

Extracted verbatim (modulo names) from
skills/revenium/plugins/revenium-classifier/classifier.py so the differential
test can assert byte-identical behavior against the original.
"""
from __future__ import annotations

import json
import logging
import re
import secrets

# Lowercase snake_case, length 2..48.
LABEL_RE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")

# Forbidden classifier outputs even when they match LABEL_RE.
TRIVIAL_BLOCKLIST = {"ack", "acknowledgment", "greeting", "confirmation", "hello", "thanks"}

VALID_JOB_STATUSES = {"SUCCESS", "FAILED", "CANCELLED"}

logger = logging.getLogger("revenium_classify")


def validate_label(label: str) -> str:
    """Return the cleaned label, or the 'unclassified' sentinel."""
    if not label:
        return "unclassified"
    cleaned = label.strip().lower()
    if cleaned in TRIVIAL_BLOCKLIST:
        return "unclassified"
    if not LABEL_RE.match(cleaned):
        return "unclassified"
    return cleaned


def parse_job_array(raw: str) -> list:
    """Parse an LLM response into a list of job dicts. Fail-open: [] on any error."""
    try:
        text = (raw or "").strip()
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


def validate_job(
    job: dict,
    entropy: "callable | None" = None,
    logger: "logging.Logger | None" = None,
) -> "dict | None":
    """Validate and normalize a job dict from the LLM response.

    `entropy` is injected only so the differential test can pin the random
    suffix; production callers leave it None and get secrets.token_hex(2).

    `logger` is injected because the LOG CHANNEL IS PART OF THE HOST CONTRACT.
    tests/test_phase28_classifier_reject_log.py asserts this rejection lands on
    the `revenium_classifier` logger specifically (D-09), and that the value is
    rendered with lazy %r so a newline in the raw LLM response cannot forge a
    second record (T-28-07). A library that logs to its own channel silently
    breaks that guarantee — return-value equivalence is NOT sufficient here.
    """
    gen = entropy or (lambda: secrets.token_hex(2))
    log = logger if logger is not None else globals()["logger"]
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
        # %r (lazy), never %s or an f-string — job_type is still-unvalidated
        # LLM output at this branch (T-28-07).
        log.warning(
            "revenium-classifier: rejected job classification, job_type failed "
            "label validation: %r",
            job_type,
        )
        return None
    status_raw = job.get("status", "")
    if not isinstance(status_raw, str):
        return None
    status = status_raw.strip().upper()
    if status not in VALID_JOB_STATUSES:
        return None
    aid = agentic_job_id.strip() + "_" + gen()
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
