"""revenium_classify — host-agnostic task/job classification core.

Hard rule for this spike: this package imports NOTHING outside the stdlib and
knows nothing about Hermes, LiteLLM, or Claude Code. `verify_purity.py` asserts it.
"""
from .engine import UNCLASSIFIED, Classifier
from .labels import (
    LABEL_RE,
    TRIVIAL_BLOCKLIST,
    VALID_JOB_STATUSES,
    parse_job_array,
    validate_job,
    validate_label,
)
from .prompts import (
    DEFAULT_HOST,
    build_classification_prompt,
    build_job_inference_prompt,
    job_system_prompt,
    turn_system_prompt,
)
from .taxonomy import FileTaxonomy, InMemoryTaxonomy, TaxonomyStore

__all__ = [
    "Classifier",
    "UNCLASSIFIED",
    "LABEL_RE",
    "TRIVIAL_BLOCKLIST",
    "VALID_JOB_STATUSES",
    "validate_label",
    "validate_job",
    "parse_job_array",
    "build_classification_prompt",
    "build_job_inference_prompt",
    "turn_system_prompt",
    "job_system_prompt",
    "DEFAULT_HOST",
    "TaxonomyStore",
    "FileTaxonomy",
    "InMemoryTaxonomy",
]
