"""The classification engine — the piece that is actually generic.

Everything host-specific is injected:
  * `llm`      — a callable(messages=..., temperature=..., max_tokens=..., timeout=...)
                 returning an OpenAI-shaped response. Hermes passes
                 agent.auxiliary_client.call_llm; a guardrail passes its own client.
  * `taxonomy` — a TaxonomyStore.
  * `host`     — the name that appears in the prompt text.

What is deliberately NOT here: where the transcript came from, where the result
goes, session identity, dedupe, idempotency. Those are host concerns and stay
in the host adapter (see README — that split is the finding).
"""
from __future__ import annotations

import asyncio
import logging

from . import prompts
from .labels import parse_job_array, validate_job, validate_label

logger = logging.getLogger("revenium_classify")

UNCLASSIFIED = "unclassified"


def _content_of(response):
    """Tolerate both attribute-style and dict-style OpenAI response shapes."""
    try:
        return response.choices[0].message.content
    except AttributeError:
        return response["choices"][0]["message"]["content"]


class Classifier:
    def __init__(self, llm=None, taxonomy=None, host: str = prompts.DEFAULT_HOST):
        self.llm = llm
        self.taxonomy = taxonomy
        self.host = host

    # ---- turn/task classification -------------------------------------------------

    async def classify_turn_async(self, user_message: str, assistant_response: str) -> str:
        """Return a validated task_type label. Never raises; 'unclassified' on any failure."""
        if self.llm is None:
            return UNCLASSIFIED
        labels = self.taxonomy.labels() if self.taxonomy else []
        prompt = prompts.build_classification_prompt(
            user_message or "", assistant_response or "", labels, host=self.host
        )
        try:
            response = await asyncio.to_thread(
                self.llm,
                messages=[
                    {"role": "system", "content": prompts.turn_system_prompt(self.host)},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=64,
                timeout=10.0,
            )
            raw = (_content_of(response) or "").strip()
        except Exception as exc:
            logger.warning("LLM call failed: %s", exc)
            return UNCLASSIFIED
        label = validate_label(raw)
        if label != UNCLASSIFIED and self.taxonomy:
            self.taxonomy.record(label)
        return label

    def classify_turn(self, user_message: str, assistant_response: str) -> str:
        """Blocking wrapper for hosts that are not async (a guardrail worker thread)."""
        return asyncio.run(self.classify_turn_async(user_message, assistant_response))

    # ---- job/arc inference --------------------------------------------------------

    async def infer_jobs_async(self, transcript: str) -> list:
        """Return a list of validated job dicts. Never raises; [] on any failure."""
        if self.llm is None:
            return []
        labels = self.taxonomy.labels() if self.taxonomy else []
        prompt = prompts.build_job_inference_prompt(transcript, labels, host=self.host)
        try:
            response = await asyncio.to_thread(
                self.llm,
                messages=[
                    {"role": "system", "content": prompts.job_system_prompt(self.host)},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=512,
                timeout=20.0,
            )
            raw = _content_of(response) or ""
        except Exception as exc:
            logger.warning("job inference LLM call failed: %s", exc)
            return []
        jobs = []
        for candidate in parse_job_array(raw):
            validated = validate_job(candidate)
            if validated:
                jobs.append(validated)
                if self.taxonomy:
                    self.taxonomy.record(validated["job_type"])
        return jobs

    def infer_jobs(self, transcript: str) -> list:
        return asyncio.run(self.infer_jobs_async(transcript))
