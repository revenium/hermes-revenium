"""impact_study.py — the ImpactStudyResult contract (EGV-12).

Phase 43 (EGV-12): kept as its own module, following evaluators.py's own
precedent for the same reason -- a seam that stays visible as a FILE
boundary, not merely a naming convention. EGV-12 exists so that a real
impact study, performed elsewhere by a human analyst outside this codebase,
can be EXPRESSED here without the representation silently mangling its
meaning -- and so that this system never appears to have computed one
itself.

THE CONTRACT
------------
`validate(candidate: dict) -> dict | None` is the whole of this module's
real behaviour.

  candidate  a study record authored by a human analyst (or, later, a
             fixture implementation) OUTSIDE this codebase. UNTRUSTED DATA:
             it may be malformed, hostile, or simply wrong, and validate()
             must survive all three without raising.

  returns    the normalised study dict, with every declared key present and
             narrative fields byte-clamped, or None to ABSTAIN.

Exact key set (D-07, grounded field-by-field against 43-RESEARCH.md's
term-of-art table -- see the per-field comments below the TypedDict for
each field's source and legitimate values):

    study_id, study_version, unit, population, intervention, comparator,
    estimand, identification_method, outcome, observation_window_start,
    observation_window_end, value_low, value_base, value_high, assumptions,
    diagnostics, validity_scope

ABSTENTION IS NOT AN ERROR. Returning None is the correct answer whenever a
supplied candidate does not conform to this contract, and callers must
treat it as an ordinary outcome, not a bug to catch -- the same idiom
classifier._validate_assessment and evaluators.py's own contract already
share (D-10).

WHAT THIS IS NOT. There is no estimator here: nothing in this module
computes an effect, a p-value, a standard error, or a confidence interval
from data. There is no experiment orchestration -- nothing schedules,
randomizes, or runs a study. There is no study registry and no storage --
a validated study dict is handed back to its caller and this module keeps
no memory of it. EGV-12 asks for a contract a study can be POURED INTO; all
of the above is explicitly out of scope for that, not a deferred feature.

DEPENDENCY DIRECTION. This module must not import classifier.py, for the
same reason evaluators.py must not (evaluators.py's own DEPENDENCY
DIRECTION paragraph): the dependency runs one way so this module stays
importable where Hermes' venv is absent. Consequently this module
duplicates its own byte-clamp and finite-number helpers rather than
importing classifier.py's -- the duplication is deliberate and required by
the dependency rule, not an oversight.

NOTHING IN THE SHIPPED SKILL IMPORTS THIS MODULE, and that is deliberate --
this is the property that makes this module's contract load-bearing rather
than merely descriptive. A study's strength (its identification_method, its
validity_scope, its effect estimate) has no code path into a job's own
evidence_class or claim label. That absent import edge is how EGV-13's
non-inheritance rule ("a job referencing a study never inherits the
study's evidence_class") is enforced STRUCTURALLY rather than merely
asserted -- plan 43-04 proves the reverse edge (classifier.py does not
import this module) on the classifier side; this module's own ast-guard
(see tests/test_phase43_impact_study.py) proves this module does not import
classifier.py, closing the loop from this side.
"""

from __future__ import annotations

import logging
import math
from typing import TypedDict

logger = logging.getLogger("revenium_classifier.impact_study")

# Mirrors classifier.py's NARRATIVE_CLAMP_BYTES (classifier.py:1095) exactly.
# Duplicated, not imported -- see DEPENDENCY DIRECTION above.
NARRATIVE_CLAMP_BYTES = 500

# The identification-strategy vocabulary (43-RESEARCH.md's field-by-field
# grounding table, "identification method" row): which design licenses the
# causal claim -- randomization (RCT), parallel-trends (difference-in-
# differences), exclusion+relevance (instrumental variables), continuity-at-
# cutoff (regression discontinuity), selection-on-observables (matching),
# donor-pool comparability (synthetic control). An explicit allow-list,
# matching SUPPORTED_CURRENCIES' (classifier.py:61) and EVIDENCE_CLASSES'
# (classifier.py:799) declaration shape, not a pattern.
#
# OTHER is an explicit escape hatch (43-RESEARCH.md's Assumption A2,
# resolved by 43-CONTEXT.md D-07): it is what makes locking this vocabulary
# now SAFE. A legitimate study using an identification method not named
# here (e.g. an event-study design, a synthetic-DiD hybrid) is
# REPRESENTABLE via OTHER rather than rejected outright. Widening this set
# beyond routing more methods through OTHER is a deliberate edit, never
# silent drift.
IDENTIFICATION_METHODS = frozenset({
    "RCT",
    "DID",
    "IV",
    "RDD",
    "MATCHING",
    "SYNTHETIC_CONTROL",
    "OTHER",
})

# Narrative (free-text, clamped) fields, other than study_id which is
# clamped and validated separately below for non-emptiness.
_NARRATIVE_KEYS = (
    "unit",
    "population",
    "intervention",
    "comparator",
    "estimand",
    "outcome",
    "validity_scope",
)

# The full, closed key set (D-10 / C-05): an unknown key is a rejection, not
# a silently-ignored extra -- matching api_event_spool.py's closed-allowlist
# posture.
_REQUIRED_KEYS = frozenset(_NARRATIVE_KEYS) | frozenset({
    "study_id",
    "study_version",
    "identification_method",
    "observation_window_start",
    "observation_window_end",
    "value_low",
    "value_base",
    "value_high",
    "assumptions",
    "diagnostics",
})


class ImpactStudyResult(TypedDict):
    """The declared shape of a validated impact study (EGV-12, D-07).

    This repo has no type checker wired up (CLAUDE.md), so at RUNTIME a
    TypedDict instance is a plain dict and this declaration enforces
    NOTHING by itself -- validate() below does 100% of the real checking.
    The declaration's value is documentation plus future-checker value; do
    not mistake it for a guard.
    """

    # study_id / study_version -- software convention, not causal-inference:
    # mirrors this repo's own assessment_id/sequence identity pattern.
    # study_version is a plain, monotonically increasing int -- matching
    # every other *_VERSION constant in this codebase (
    # ASSESSMENT_SCHEMA_VERSION, TAXONOMY_VERSION, PROMPT_VERSION,
    # POLICY_VERSION), not a string and not semver.
    study_id: str
    study_version: int

    # unit -- Rubin Causal Model / potential-outcomes framework: the entity
    # potential outcomes are defined FOR ("what would this SAME entity's
    # outcome have been under the alternative condition").
    unit: str

    # population / intervention / comparator / outcome -- ICH E9(R1)
    # estimand attributes, named individually rather than nested.
    population: str
    intervention: str
    comparator: str
    outcome: str

    # estimand -- ICH E9(R1)'s own term of art: "a precise description of
    # the treatment effect reflecting the clinical question posed by the
    # trial objective," bundling population + intervention/comparator +
    # endpoint + population-level summary into ONE causal quantity.
    # Deliberately a clamped free-text field, NOT a nested five-attribute
    # sub-object -- a deep structured estimand model is estimator-adjacent
    # complexity a contract module must not carry (D-07).
    estimand: str

    # identification_method -- see IDENTIFICATION_METHODS above for the
    # vocabulary and the OTHER escape hatch's rationale.
    identification_method: str

    # observation_window_start / observation_window_end -- mirrors
    # _build_job_assessment's existing observation_window_start/end pair
    # (classifier.py:1233-1234) exactly, for the period over which the
    # outcome was measured.
    observation_window_start: float
    observation_window_end: float

    # value_low / value_base / value_high -- the effect estimate and its
    # uncertainty interval, reusing the SAME low/base/high triple shape
    # already shipped for the economic-value bounds (Phase 42, EGV-06:
    # classifier.py's value_low/value_base/value_high) rather than
    # inventing a second interval representation.
    value_low: float
    value_base: float
    value_high: float

    # assumptions -- the identifying assumptions the causal claim rests on
    # (SUTVA, parallel trends, exclusion restriction + instrument
    # relevance, no manipulation at the cutoff, donor-pool comparability --
    # named per identification method), stated so a human reviewer can
    # judge plausibility.
    assumptions: "list[str]"

    # diagnostics -- the checks that SUPPORT the assumptions above (placebo
    # tests, pre-trend plots, balance tables, first-stage F-statistics,
    # donor-pool fit). Diagnostics support; they never PROVE -- that
    # distinction is the whole reason both fields exist separately rather
    # than being folded into one.
    diagnostics: "list[str]"

    # validity_scope -- internal vs. external validity. This is the field
    # EGV-13 is actually load-bearing on: a study's validity_scope is
    # inherently a COHORT-level claim, and D-08's non-inheritance guard (a
    # job referencing a study never inherits the study's evidence_class) is
    # the structural mechanism that keeps an individual job from borrowing
    # a cohort-level validity claim as if it were individually observed.
    validity_scope: str


def _clamp_text(value, limit: int = NARRATIVE_CLAMP_BYTES) -> str:
    """Coerce to str and clamp to `limit` SERIALIZED BYTES -- not characters.

    Duplicated from classifier._clamp_assessment_text (classifier.py:722),
    not imported -- see the module docstring's DEPENDENCY DIRECTION
    paragraph. Same reasoning as the original: json.dumps with
    ensure_ascii=True escapes every non-ASCII code point, so a character
    clamp under-counts by up to 12x for emoji.
    """
    if not isinstance(value, str):
        value = "" if value is None else str(value)
    for _bad in ("|", "\n", "\r"):
        value = value.replace(_bad, " ")
    value = value.strip()

    def _serialized_len(s: str) -> int:
        import json
        return len(json.dumps(s, ensure_ascii=True).encode("utf-8")) - 2

    if _serialized_len(value) <= limit:
        return value
    lo, hi = 0, len(value)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _serialized_len(value[:mid]) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return value[:lo]


def _finite_number(value) -> "float | None":
    """Return value as a float if it is a real, finite, non-bool number.

    Duplicated from classifier._finite_number (classifier.py:853), not
    imported -- see DEPENDENCY DIRECTION above. bool is rejected explicitly
    because isinstance(True, int) is True in Python, and NaN/infinity are
    rejected explicitly because a bare `value > 0` comparison is FALSE for
    NaN, letting it slip any naive bound check.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def validate(candidate) -> "dict | None":
    """Validate a supplied ImpactStudyResult candidate (EGV-12, D-10).

    Mirror of classifier._validate_assessment's own idiom: reject by
    returning None, NEVER raise, and log a rejected value with %r -- never
    %s and never an f-string, because the candidate may be operator- or
    model-derived text, and a newline inside it must not be able to forge
    a second log record.

    The whole body runs inside one try/except so an internal failure
    (a subtly wrong type deep in a nested structure, for instance) resolves
    to None rather than propagating -- validate() is a pure function of its
    one argument with no I/O, so an internal exception is this module's own
    bug, not the caller's, and must not crash the caller either way.
    """
    try:
        return _validate(candidate)
    except Exception:
        logger.warning(
            "impact_study: validate() raised internally, rejecting candidate: %r",
            candidate,
        )
        return None


def _validate(candidate) -> "dict | None":
    if not isinstance(candidate, dict):
        logger.warning("impact_study: rejected non-dict candidate: %r", candidate)
        return None

    keys = set(candidate)
    unknown = keys - _REQUIRED_KEYS
    if unknown:
        logger.warning(
            "impact_study: rejected candidate with unrecognized key(s): %r",
            unknown,
        )
        return None
    missing = _REQUIRED_KEYS - keys
    if missing:
        logger.warning(
            "impact_study: rejected candidate missing required key(s): %r",
            missing,
        )
        return None

    study_id = candidate["study_id"]
    if not isinstance(study_id, str) or not study_id.strip():
        logger.warning("impact_study: rejected non-empty-string study_id: %r", study_id)
        return None
    study_id = _clamp_text(study_id)

    study_version = candidate["study_version"]
    if (
        isinstance(study_version, bool)
        or not isinstance(study_version, int)
        or study_version < 1
    ):
        logger.warning(
            "impact_study: rejected study_version (must be a plain int >= 1): %r",
            study_version,
        )
        return None

    identification_method = candidate["identification_method"]
    if identification_method not in IDENTIFICATION_METHODS:
        logger.warning(
            "impact_study: rejected identification_method outside the "
            "controlled vocabulary: %r",
            identification_method,
        )
        return None

    narrative: dict = {}
    for key in _NARRATIVE_KEYS:
        value = candidate[key]
        if not isinstance(value, str):
            logger.warning(
                "impact_study: rejected non-string narrative field %r: %r",
                key, value,
            )
            return None
        narrative[key] = _clamp_text(value)

    obs_start = _finite_number(candidate["observation_window_start"])
    obs_end = _finite_number(candidate["observation_window_end"])
    if obs_start is None or obs_end is None:
        logger.warning(
            "impact_study: rejected non-finite observation window: %r",
            (candidate["observation_window_start"], candidate["observation_window_end"]),
        )
        return None
    if obs_end < obs_start:
        logger.warning(
            "impact_study: rejected observation window whose end precedes "
            "its start: %r",
            (obs_start, obs_end),
        )
        return None

    value_low = _finite_number(candidate["value_low"])
    value_base = _finite_number(candidate["value_base"])
    value_high = _finite_number(candidate["value_high"])
    if value_low is None or value_base is None or value_high is None:
        logger.warning(
            "impact_study: rejected non-finite effect estimate/interval: %r",
            (candidate["value_low"], candidate["value_base"], candidate["value_high"]),
        )
        return None
    if not (value_low <= value_base <= value_high):
        logger.warning(
            "impact_study: rejected reversed effect interval: %r",
            (value_low, value_base, value_high),
        )
        return None

    assumptions = candidate["assumptions"]
    diagnostics = candidate["diagnostics"]
    for name, value in (("assumptions", assumptions), ("diagnostics", diagnostics)):
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            logger.warning(
                "impact_study: rejected %s (must be a list of strings): %r",
                name, value,
            )
            return None

    return {
        "study_id": study_id,
        "study_version": study_version,
        "unit": narrative["unit"],
        "population": narrative["population"],
        "intervention": narrative["intervention"],
        "comparator": narrative["comparator"],
        "estimand": narrative["estimand"],
        "identification_method": identification_method,
        "outcome": narrative["outcome"],
        "observation_window_start": obs_start,
        "observation_window_end": obs_end,
        "value_low": value_low,
        "value_base": value_base,
        "value_high": value_high,
        "assumptions": [_clamp_text(v) for v in assumptions],
        "diagnostics": [_clamp_text(v) for v in diagnostics],
        "validity_scope": narrative["validity_scope"],
    }
