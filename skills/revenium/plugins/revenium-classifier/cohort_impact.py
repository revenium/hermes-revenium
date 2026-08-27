"""cohort_impact.py — the cohort-impact estimator boundary (EGV-01).

Phase 45 (D-03): kept as its own module, for the same reason evaluators.py
and impact_study.py are — the boundary is a FILE boundary, not merely a
naming convention. This module is deliberately separate from
impact_study.py: impact_study.py is the contract a human-authored study
result must satisfy, while this module is the REGISTRY of cohort-impact
ESTIMATORS that could someday produce a candidate for that contract to
validate. Conflating "the shape a study result must have" with "the
registry of things that estimate one" would put two concerns at very
different maturities in one place — impact_study.py has no registry at
all, by its own design (EGV-12); this boundary is a registry with, today,
nothing registered into it.

THE CONTRACT
------------
A cohort estimator is any callable with this signature:

    estimate(cohort: dict, config: dict) -> dict | None

  cohort  plain data describing the population and observation window under
          study — a treated group, a control (or baseline) group, and
          whatever counts each rests on. UNTRUSTED DATA, never instructions,
          for the same reason evaluators.py's `transcript` parameter is: an
          estimator that embeds any of it in a prompt must say so to the
          model.
  config  the operator's settings object. Every key is absent-able.

  returns an ImpactStudyResult-SHAPED candidate dict (see impact_study.py's
          own declared key set), or None to ABSTAIN.

ABSTENTION IS NOT AN ERROR. Returning None is the correct answer whenever an
estimator cannot responsibly characterise a cohort's effect — a missing
count, a non-finite mean, a reversed interval — and callers must treat it as
an ordinary outcome, not a bug to catch (the same idiom evaluators.py's own
contract and impact_study.validate() both already share).

WHAT THIS IS NOT. There is no discovery mechanism, no entry points, and no
plugin packages here — Phase 36's decision stands, restated for this
boundary. And, stated plainly rather than left to be inferred: ZERO
REGISTRANTS TODAY. The shipped registry below is empty by design (D-03).
Nothing in the skill resolves through it, and that emptiness is the
property this module exists to be TESTED against, not a gap to be
apologetic about — an empty registry nobody has ever registered into is
exactly the facade this phase exists to prove is not one: it still accepts
a registrant, and a registrant's result still cannot smuggle causal
strength into a job's own claim (see the next paragraph).

A registered estimator's result can never be represented as
individually-observed causality. The mechanism is STRUCTURAL, not a check:
this registry is a separate `BoundaryRegistry` instance that
classifier._declared_evidence_class NEVER consults — that function resolves
a registrant's declared evidence_class from the `output_assessment`
boundary (evaluators.py) alone. A cohort registrant's declared label
therefore has no code path into any JobAssessment's own `evidence_class`.
That absent import/consultation edge is the same shape EGV-13's
non-inheritance rule already uses for impact_study.py ("a job referencing a
study never inherits the study's evidence_class") — here it is enforced by
this registry never being consulted at all, rather than by an inherited
value being discarded after the fact.

DEPENDENCY DIRECTION. This module must not import classifier.py, for the
same reason evaluators.py and impact_study.py must not: the dependency
runs one way so this module stays importable where Hermes' venv is
absent. Host data crosses this boundary as plain data only — dicts,
strings, numbers — never a `Path`, a sqlite3 connection, or a file handle
(D-09; no test enforces this half, so this module obeys the rule by
example). And, called out explicitly because it would be the easiest
mistake to make in this file of all six: this module must NOT import
impact_study.py either. impact_study.py's own load-bearing property is
that NOTHING IN THE SHIPPED SKILL IMPORTS IT — a shipped module importing
it would make that module's own docstring false, which is exactly the
stale-reference defect shape Phase 44 found. Consequently this module
duplicates its own byte-clamp and finite-number helpers rather than
importing impact_study.py's (or classifier.py's) — the duplication is
deliberate and required by the dependency rule, not an oversight.
"""

from __future__ import annotations

import logging
import math

try:  # packaged: Hermes imports the plugin as a package
    from . import boundary_registry as _br
except ImportError:  # pragma: no cover - plugin dir on sys.path
    try:
        import boundary_registry as _br  # type: ignore
    except ImportError:
        # Loaded by file path with no package parent and no sys.path entry --
        # exactly what tests/test_phase36_evaluator_seam.py's _load_evaluators()
        # does, and that loader may not be edited. Deliberately avoids os and
        # pathlib: this module is under the D-08 import guard.
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            "revenium_boundary_registry",
            __file__.rsplit("/", 1)[0] + "/boundary_registry.py",
        )
        _br = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_br)

logger = logging.getLogger("revenium_classifier.cohort_impact")

# Phase 45 (D-03/D-04): the shared BoundaryRegistry primitive, instantiated
# for this boundary's own name. D-03 requires this registry to ship with
# ZERO registrants -- nothing below calls register() at import time.
_REGISTRY = _br.BoundaryRegistry("cohort_impact")


def register(name: str, fn, version: str = "", evidence_class: str = "") -> None:
    """Register a cohort estimator under `name`, with the version and
    evidence_class IT declares.

    Same reasoning as evaluators.py's own register(): a future cohort
    estimator must be able to report its own identity and its own evidence
    class without this registry -- or any caller -- knowing its name.

    Last registration wins.
    """
    _REGISTRY.register(name, fn, version, evidence_class)


def resolve(name: str):
    """Return the estimator registered as `name`, or None.

    None means "no such registrant" and is a configuration error the caller
    reports; it is NOT the same as an estimator abstaining.
    """
    return _REGISTRY.resolve(name)


def resolve_version(name: str) -> str:
    """The version the named estimator declared, or "" if unknown."""
    return _REGISTRY.resolve_version(name)


def resolve_evidence_class(name: str) -> str:
    """The evidence class the named estimator DECLARED at registration, or
    "" if unknown -- a trusted-code declaration, never a value read from the
    estimator's output."""
    return _REGISTRY.resolve_evidence_class(name)


def registered() -> list:
    """Names of every registered cohort estimator, sorted. For diagnostics.

    D-03: this returns [] in the shipped state -- nothing registers at
    import time in this module.
    """
    return _REGISTRY.registered()


# --- shared duplicated helpers ------------------------------------------
#
# Duplicated from impact_study.py's own _clamp_text / _finite_number
# (themselves duplicated from classifier.py), not imported -- see the
# module docstring's DEPENDENCY DIRECTION paragraph. The duplication is
# deliberate and required by the dependency rule, not an oversight.

NARRATIVE_CLAMP_BYTES = 500

# The six two-character JSON escapes (\" \\ \b \f \n \r \t is seven bytes
# of source but \r is folded into the strip pass above before this ever
# runs -- listed here as the full canonical set anyway, so this constant
# reads the same as the escape table it stands in for). Used by
# _serialized_len below instead of importing json for one length
# computation -- this module's DEPENDENCY DIRECTION paragraph keeps its
# import graph to importlib/logging/math, and json is neither.
_JSON_TWO_BYTE_ESCAPES = frozenset('"\\\b\f\n\r\t')


def _serialized_len(s: str) -> int:
    """The length, in bytes, `s` would occupy inside a JSON string encoded
    with ensure_ascii=True -- WITHOUT importing json. Mirrors
    json.dumps(s, ensure_ascii=True) minus its two surrounding quote bytes:
    the six standard two-character escapes cost 2 bytes, every other C0
    control character costs 6 (\\u00XX), every non-ASCII code point in the
    Basic Multilingual Plane costs 6, every code point above it (needing a
    UTF-16 surrogate pair) costs 12, and everything else costs 1 -- the
    same "up to 12x for emoji" undercount classifier._clamp_assessment_text
    and impact_study._clamp_text's own docstrings warn a character clamp
    would miss.
    """
    total = 0
    for ch in s:
        cp = ord(ch)
        if ch in _JSON_TWO_BYTE_ESCAPES:
            total += 2
        elif cp < 0x20:
            total += 6
        elif cp < 0x80:
            total += 1
        elif cp <= 0xFFFF:
            total += 6
        else:
            total += 12
    return total


def _clamp_text(value, limit: int = NARRATIVE_CLAMP_BYTES) -> str:
    """Coerce to str and clamp to `limit` SERIALIZED BYTES -- not characters.

    json.dumps with ensure_ascii=True escapes every non-ASCII code point, so
    a character clamp under-counts by up to 12x for emoji.
    """
    if not isinstance(value, str):
        value = "" if value is None else str(value)
    for _bad in ("|", "\n", "\r"):
        value = value.replace(_bad, " ")
    value = value.strip()

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

    bool is rejected explicitly because isinstance(True, int) is True in
    Python, and NaN/infinity are rejected explicitly because a bare
    `value > 0` comparison is FALSE for NaN, letting it slip any naive
    bound check.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    if math.isnan(f) or math.isinf(f):
        return None
    return f


# --- _cohort_estimator_impact_fixture ------------------------------------
#
# Phase 45 (EGV-02, D-05): the non-LLM fixture proving this boundary
# accepts a registrant. Modelled on EGV-02's "cohort impact evaluator": a
# deterministic, arithmetic-only comparison across a treated group and a
# control group -- no model call, no network call, no clock. It is
# deliberately NOT registered at import time (D-03's zero-registrant
# property is the point); the test registers it.

COHORT_FIXTURE_VERSION = "1"


def _cohort_estimator_impact_fixture(cohort: dict, config: dict) -> "dict | None":
    """A deterministic cohort-comparison estimate. No model, no network, no
    clock.

    Reads a treated-group mean, a control-group mean, and a population size
    off `cohort` through _finite_number, and abstains -- returns None,
    never raises -- when any is missing, non-finite, or when the resulting
    effect interval would be reversed. Otherwise returns an
    ImpactStudyResult-SHAPED dict (see impact_study.py's declared key set)
    with every narrative field passed through _clamp_text.

    This function declares QUASI_EXPERIMENTAL_IMPACT at registration, not
    MODEL_ESTIMATED_DEMO: the estimate rests on a comparison across a
    cohort's treated and control groups, not on a model's guess, but it
    also does not establish individual causality for any ONE job -- that is
    exactly the property EGV-13's non-inheritance rule (see the module
    docstring above) keeps this label from ever reaching.

    It must not import impact_study to check its own output -- see the
    module docstring's DEPENDENCY DIRECTION paragraph.
    """
    if not isinstance(cohort, dict):
        logger.warning(
            "cohort_impact: fixture rejected non-dict cohort: %r", cohort
        )
        return None

    population = _finite_number(cohort.get("population"))
    treated_mean = _finite_number(cohort.get("treated_mean"))
    control_mean = _finite_number(cohort.get("control_mean"))
    if population is None or treated_mean is None or control_mean is None:
        logger.warning(
            "cohort_impact: fixture rejected cohort with missing or "
            "non-finite population/treated_mean/control_mean: %r", cohort
        )
        return None
    if population <= 0:
        logger.warning(
            "cohort_impact: fixture rejected non-positive population: %r",
            population,
        )
        return None

    effect = treated_mean - control_mean
    # A deliberately simple, symmetric margin -- this fixture's point is to
    # prove the registry accepts a registrant, not to model real
    # uncertainty. Defaults to +/-10% of the magnitude of the effect when
    # `cohort` supplies no margin of its own. A CALLER-SUPPLIED margin is
    # read verbatim, sign included -- a malformed or hostile cohort
    # dict can supply a NEGATIVE margin, which reverses value_low/value_high
    # below and is exactly the reversed-interval input this function's own
    # abstention guard exists to reject.
    margin = _finite_number(cohort.get("interval_margin"))
    if margin is None:
        margin = abs(effect) * 0.1
    value_low = effect - margin
    value_high = effect + margin
    if value_high < value_low:
        logger.warning(
            "cohort_impact: fixture computed a reversed effect interval: %r",
            (value_low, effect, value_high),
        )
        return None

    cfg = config if isinstance(config, dict) else {}

    return {
        "study_id": _clamp_text(cohort.get("study_id", "cohort_estimator_impact_fixture")),
        "study_version": 1,
        "unit": _clamp_text(cohort.get("unit", "job")),
        "population": _clamp_text(str(population)),
        "intervention": _clamp_text(cohort.get("intervention", "treated cohort")),
        "comparator": _clamp_text(cohort.get("comparator", "control cohort")),
        "estimand": _clamp_text(
            cohort.get("estimand", "mean outcome difference, treated vs control")
        ),
        "identification_method": "MATCHING",
        "outcome": _clamp_text(cohort.get("outcome", "outcome measure")),
        "observation_window_start": _finite_number(cohort.get("window_start")) or 0.0,
        "observation_window_end": _finite_number(cohort.get("window_end")) or 0.0,
        "value_low": value_low,
        "value_base": effect,
        "value_high": value_high,
        "assumptions": [_clamp_text(a) for a in cohort.get("assumptions", []) if isinstance(a, str)],
        "diagnostics": [_clamp_text(d) for d in cohort.get("diagnostics", []) if isinstance(d, str)],
        "validity_scope": _clamp_text(
            cfg.get("validity_scope", "internal validity for this cohort only")
        ),
    }
