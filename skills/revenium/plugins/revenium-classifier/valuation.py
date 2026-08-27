"""valuation.py — the economic valuation boundary (EGV-01).

Phase 45: kept as its own module, for the same reason evaluators.py,
impact_study.py, cohort_impact.py, reporting.py and classification.py are —
the boundary is a FILE boundary, not merely a naming convention. This
boundary is carved out of the derivation step inside
`classifier._validate_assessment`, which today does the mechanism gate, the
hours/rate bound checks, the confidence check, the value-bounds abstain
gate, the currency check AND the money math all in one function. Only the
money math moves here — the split is drawn as narrowly as it can be while
still being a real boundary, because this is the highest-risk edit in the
phase.

THE CONTRACT
------------
A valuation implementation is any callable with this signature:

    value(assumptions: dict, config: dict) -> dict | None

  assumptions  CALLER-CONSTRUCTED plain data — this is the rule that
               matters most, stated first because getting it wrong is the
               one mistake this contract cannot tolerate. `assumptions` is
               built by `classifier._validate_assessment` from fields it
               has ALREADY VALIDATED AND CLAMPED: `estimated_hours_saved`,
               `assumed_loaded_rate`, `currency`, `economic_mechanism`,
               `inferred_role`. The UNTRUSTED evaluator response
               (`classifier._validate_assessment`'s own `raw` parameter) is
               deliberately NOT passed through — an implementation
               registered here never sees a key the validator did not
               already vet.

  config       the llmOutcomeEvaluation object from config.json (the same
               object evaluators.py's own contract already threads
               through). Every key is absent-able. The shipped fixture
               reads its rate card from `config["rateCard"]`.

  returns      {"estimated_value": <number>, "currency": <str>} or None to
               ABSTAIN.

An implementation MUST be synchronous: economic valuation is arithmetic
over already-validated data, and there is nothing to await.

The caller RE-CHECKS the returned amount against its own configured
ceiling — the maximum hours times the maximum rate — before it can become
a value. An implementation cannot widen the operator's bounds by returning
a larger number. This is a deliberate distrust of registered code on the
money path, not an oversight in the contract: registration is trusted to
declare an identity, never to assert an amount the operator did not
configure and a model did not derive.

ABSTENTION IS NOT AN ERROR. An implementation that cannot responsibly
price the work returns None, and the job reports its execution status
without a value — the same idiom evaluators.py's own contract and
impact_study.validate() both already share.

WHAT THIS IS NOT. There is no discovery mechanism, no entry points, and no
plugin packages here — Phase 36's decision stands, restated for this
boundary. And, stated plainly per D-14 and PA-17: this module is NOT where
Phase 44's deferred EGV-05 producer lands. The three operator-declared
mechanisms (`risk_avoidance`, `incremental_revenue`,
`quality_decision_improvement`) still have no producer, and EGV-05 remains
recorded as partial in REQUIREMENTS.md. A future producer plugging into
this registry is groundwork this phase leaves behind, not a promise this
phase keeps.

DEPENDENCY DIRECTION. This module must not import classifier.py, for the
same reason evaluators.py, impact_study.py, cohort_impact.py, reporting.py
and classification.py must not: the dependency runs one way so this module
stays importable where Hermes' venv is absent — proven by loading it from
its own file path with no package parent (D-09's host-agnosticism rule;
see also EGV-03). Host data crosses this boundary as plain data only —
dicts, strings, numbers — never a `Path`, a sqlite3 connection, or a file
handle (no test enforces this half; this module obeys the rule by
example). Consequently this module duplicates its own byte-clamp and
finite-number helpers rather than importing classifier.py's or
impact_study.py's — the duplication is deliberate and required by the
dependency rule, not an oversight.
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

logger = logging.getLogger("revenium_classifier.valuation")

# Phase 45 (D-01, D-04): the shared BoundaryRegistry primitive, instantiated
# for this boundary's own name. Like classification.py, this registry does
# NOT ship empty -- the rate-card fixture below is registered at import
# time, because a second, real, non-model implementation is what makes this
# boundary provably pluggable rather than hypothetical (the same reason
# evaluators.py has shipped `stub` since Phase 36).
_REGISTRY = _br.BoundaryRegistry("valuation")


def register(name: str, fn, version: str = "", evidence_class: str = "") -> None:
    """Register a valuation implementation under `name`, with the version
    and evidence_class IT declares.

    Same reasoning as evaluators.py's own register(): a future ONNX,
    deterministic-policy, or vertical valuation must be able to report its
    own identity and its own evidence class without this registry -- or any
    caller -- knowing its name.

    Last registration wins.
    """
    _REGISTRY.register(name, fn, version, evidence_class)


def resolve(name: str):
    """Return the valuation implementation registered as `name`, or None.

    None means "no such registrant" and is a configuration error the
    caller reports; it is NOT the same as an implementation abstaining.
    """
    return _REGISTRY.resolve(name)


def resolve_version(name: str) -> str:
    """The version the named implementation declared, or "" if unknown."""
    return _REGISTRY.resolve_version(name)


def resolve_evidence_class(name: str) -> str:
    """The evidence class the named implementation DECLARED at
    registration, or "" if unknown -- a trusted-code declaration, never a
    value read from the implementation's output."""
    return _REGISTRY.resolve_evidence_class(name)


def registered() -> list:
    """Names of every registered valuation implementation, sorted. For
    diagnostics."""
    return _REGISTRY.registered()


# --- shared duplicated helpers --------------------------------------------
#
# Duplicated from impact_study.py's own _clamp_text/_finite_number
# (themselves duplicated from classifier.py's _clamp_assessment_text/
# _finite_number), not imported -- see the module docstring's DEPENDENCY
# DIRECTION paragraph. The duplication is deliberate and required by the
# dependency rule, not an oversight.

NARRATIVE_CLAMP_BYTES = 500


def _clamp_text(value, limit: int = NARRATIVE_CLAMP_BYTES) -> str:
    """Coerce to str and clamp to `limit` SERIALIZED BYTES -- not characters.

    Duplicated from impact_study._clamp_text (itself duplicated from
    classifier._clamp_assessment_text, classifier.py:888), not imported --
    see the module docstring's DEPENDENCY DIRECTION paragraph. Same
    reasoning as the original: json.dumps with ensure_ascii=True escapes
    every non-ASCII code point, so a character clamp under-counts by up to
    12x for emoji.
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

    Duplicated from impact_study._finite_number (itself duplicated from
    classifier._finite_number), not imported -- see DEPENDENCY DIRECTION
    above. bool is rejected explicitly because isinstance(True, int) is
    True in Python, so a plain isinstance check would silently accept True
    as the number 1 and price an hour of work off a type error. NaN and
    infinity are rejected explicitly too: a bare `value > 0` comparison is
    FALSE for NaN, so NaN slips through any naive lower-bound guard and
    lands in a monetary field.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    if math.isnan(f) or math.isinf(f):
        return None
    return f


# --- _rate_card_valuation_fixture -----------------------------------------
#
# Phase 45 (EGV-02, D-05): the non-model fixture proving this boundary fits
# without masquerading. Modelled on EGV-02's "customer-configured policy"
# slot: an operator's approved rate card, keyed by inferred role, prices
# the work with no model call anywhere in the derivation.
#
# It declares CUSTOMER_CONFIGURED, not MODEL_ESTIMATED_DEMO: the amount
# comes from a rate card the operator approved, so the honest claim is that
# the value was CONFIGURED, not that a model estimated it. The honest limit
# of that claim, matching the vocabulary's own definition: configuration
# establishes an approved RATE, not actual hours worked -- the hours side
# of the arithmetic still comes from the resolved evaluator's own
# assumptions, unchanged by this fixture.

RATE_CARD_FIXTURE_VERSION = "1"


def _rate_card_valuation_fixture(assumptions: dict, config: dict) -> "dict | None":
    """Price the work from an operator-approved rate card keyed by
    inferred role, rather than from hours times rate.

    Reads `config["rateCard"]` when that is a dict, looks up
    `assumptions["inferred_role"]`, runs the configured amount through
    `_finite_number`, and returns `{"estimated_value": round(amount, 2),
    "currency": <the assumptions' currency>}` when the amount is finite
    and positive. Every other case -- a non-dict `assumptions` or
    `config`, missing or non-finite/boolean/non-positive hours or rate on
    `assumptions` (the fixture still declines to price work it cannot see
    the effort for), an absent or non-dict rate card, a role the card does
    not name, or a non-finite/boolean/non-positive configured amount --
    returns None. An approved rate card that has nothing to say about this
    role is a reason to abstain, not to guess.

    The whole body runs inside one try/except returning None, logging with
    %r on the rejected role or amount -- never %s, never an f-string,
    because a role or amount can be operator-supplied text and a newline
    embedded in it must not be able to forge a second log record (the
    T-28-07 rule the rest of this plugin already follows).

    Reads no clock, makes no model call and makes no network call: the
    whole derivation is a dict lookup and a bounds check.
    """
    try:
        a = assumptions if isinstance(assumptions, dict) else {}
        cfg = config if isinstance(config, dict) else {}

        hours = _finite_number(a.get("estimated_hours_saved"))
        rate = _finite_number(a.get("assumed_loaded_rate"))
        if hours is None or rate is None or hours <= 0 or rate <= 0:
            logger.warning(
                "valuation: rate card fixture rejected non-positive or "
                "non-finite hours/rate: %r",
                (a.get("estimated_hours_saved"), a.get("assumed_loaded_rate")),
            )
            return None

        rate_card = cfg.get("rateCard")
        if not isinstance(rate_card, dict):
            logger.warning(
                "valuation: rate card fixture found no configured rate "
                "card: %r", rate_card,
            )
            return None

        role = a.get("inferred_role")
        if not isinstance(role, str) or role not in rate_card:
            logger.warning(
                "valuation: rate card fixture has no configured rate for "
                "role: %r", role,
            )
            return None

        amount = _finite_number(rate_card.get(role))
        if amount is None or amount <= 0:
            logger.warning(
                "valuation: rate card fixture rejected non-positive or "
                "non-finite amount for role %r: %r", role, rate_card.get(role),
            )
            return None

        return {
            "estimated_value": round(amount, 2),
            "currency": a.get("currency"),
        }
    except Exception:
        logger.warning(
            "valuation: rate card fixture raised internally, rejecting "
            "assumptions: %r", assumptions,
        )
        return None


# Registered at import time -- like classification.py, this boundary is not
# required to ship empty, and a shipped fixture is what makes the second
# implementation installable rather than hypothetical, the same reason
# evaluators.py's `stub` has stayed in the tree since Phase 36.
register(
    "rate_card_valuation_fixture",
    _rate_card_valuation_fixture,
    RATE_CARD_FIXTURE_VERSION,
    evidence_class="CUSTOMER_CONFIGURED",
)
