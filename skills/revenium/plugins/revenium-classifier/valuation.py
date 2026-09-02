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

# Phase 54 (D-01, D-03): the three operator-only economic mechanisms a
# valuation registrant may ever declare it can assert -- the ground the
# evaluator structurally cannot reach (classifier.py's
# OPERATOR_ONLY_MECHANISMS). Duplicated here as plain string literals,
# NOT imported from classifier.py -- this module's own DEPENDENCY
# DIRECTION paragraph above forbids importing classifier.py, and
# _clamp_text/_finite_number below already set the precedent for this
# kind of deliberate duplication. What keeps this copy honest:
# tests/test_phase54_revenue_valuation_boundary.py's
# MechanismDeclarationTests's cross-module sync test, which loads both
# modules standalone and asserts the two frozensets are member-for-member
# equal.
VALUATION_DECLARABLE_MECHANISMS = frozenset({
    "risk_avoidance",
    "incremental_revenue",
    "quality_decision_improvement",
})

# Phase 54 (D-01): name -> the frozenset of economic mechanisms THAT
# registrant declared at registration time. This is a CEILING on what the
# registrant may EVER assert across every call it makes, NOT the value
# written to any one record it produces -- that per-call value rides the
# registrant's own return dict (see resolve_declared_mechanisms's own
# docstring for the asymmetry with resolve_evidence_class, which IS the
# per-registrant value). Populated only by register() below, via
# _REGISTRY-adjacent module state rather than widening
# BoundaryRegistry.register()'s own shared four-argument signature, which
# boundary_registry.py's own module docstring calls a five-boundary blast
# radius.
_MECHANISM_DECLARATIONS: dict = {}


def register(name: str, fn, version: str = "", evidence_class: str = "",
             *, economic_mechanisms=None) -> None:
    """Register a valuation implementation under `name`, with the version,
    evidence_class, and economic_mechanisms IT declares.

    Same reasoning as evaluators.py's own register(): a future ONNX,
    deterministic-policy, or vertical valuation must be able to report its
    own identity and its own evidence class without this registry -- or any
    caller -- knowing its name.

    `economic_mechanisms` (Phase 54, D-01/D-03) is keyword-only -- chosen
    over a fifth positional parameter so no existing or future positional
    call site (including every registrant already shipped) can break. It
    declares the CEILING of economic mechanisms this registrant may EVER
    assert: every member must belong to VALUATION_DECLARABLE_MECHANISMS,
    the three mechanisms an evaluator structurally cannot select. `None` or
    an empty collection both declare nothing -- what the shipped
    `hours_times_rate` and `rate_card_valuation_fixture` registrants do,
    which is what keeps a default install byte-identical (D-14): a
    registrant that declares nothing defers to the evaluator's own
    mechanism, unconditionally.

    Raises `ValueError` -- never a bare `assert` -- on any member outside
    VALUATION_DECLARABLE_MECHANISMS, on a non-`str` or empty-string member,
    on a bare `str` passed where a collection was expected (Phase 54 Task 2:
    a bare `"incremental_revenue"` is REJECTED rather than silently iterated
    into individual characters -- a decision, not an oversight), and on any
    non-iterable value. `python3 -O` strips asserts, and this is an
    access-control gate on a money path that must not be optimisable away.
    The declaration is stored only AFTER validation passes, so a refused
    registration leaves no half-state for resolve_declared_mechanisms to
    read.

    Last registration wins.
    """
    if not economic_mechanisms:
        declared = frozenset()
    else:
        if isinstance(economic_mechanisms, str):
            raise ValueError(
                f"register({name!r}): economic_mechanisms must be a "
                "collection of strings, not a single string -- a bare "
                f"{economic_mechanisms!r} would iterate into individual "
                "characters rather than declaring one mechanism"
            )
        try:
            declared = frozenset(economic_mechanisms)
        except TypeError:
            raise ValueError(
                f"register({name!r}): economic_mechanisms must be an "
                f"iterable collection, got {type(economic_mechanisms).__name__}"
            ) from None
        for _mechanism in declared:
            if (
                not isinstance(_mechanism, str)
                or not _mechanism
                or _mechanism not in VALUATION_DECLARABLE_MECHANISMS
            ):
                raise ValueError(
                    f"register({name!r}): economic_mechanisms member "
                    f"{_mechanism!r} is not a member of "
                    f"VALUATION_DECLARABLE_MECHANISMS "
                    f"{sorted(VALUATION_DECLARABLE_MECHANISMS)!r}"
                )
    _MECHANISM_DECLARATIONS[name] = declared
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


def resolve_declared_mechanisms(name: str) -> frozenset:
    """The economic mechanisms the named implementation DECLARED at
    registration, or an empty frozenset if unknown. Never raises.

    Modelled on resolve_evidence_class's exact shape, but states what that
    function cannot: THIS is a CEILING on what the registrant may EVER
    assert, not the value written to every record it produces. A
    registrant declaring {"incremental_revenue"} may still return no
    mechanism on any given call where it has nothing revenue-shaped to
    price -- see _revenue_card_valuation_fixture's own delegation
    behaviour. The per-call value that actually reaches a record rides
    that call's own return dict, re-checked by the caller against this
    ceiling; this function only answers "is X ever ALLOWED to be asserted
    by this registrant".
    """
    if not isinstance(name, str):
        return frozenset()
    return _MECHANISM_DECLARATIONS.get(name, frozenset())


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


# --- _revenue_card_valuation_fixture --------------------------------------
#
# Phase 54 (ROI-05, D-01/D-02/D-05/D-06): the revenue registrant proving
# EGV-05's deferred producer for `incremental_revenue`. Modelled on
# _rate_card_valuation_fixture immediately above -- same file, same
# try/except-returning-None shape, same CUSTOMER_CONFIGURED evidence class
# -- but keyed and gated differently in three deliberate ways:
#
#   1. (D-06) The card entry is selected by `config["revenueCardKey"]`, an
#      OPERATOR-BOUND identity resolved from config, never from
#      `assumptions["inferred_role"]` -- that field is clamped MODEL
#      output (classifier.py's inferred_role, model-produced), and handing
#      the model the selector on a revenue figure would open exactly the
#      "gaming gradient that rewards pointing agents at high-margin
#      transactions" hazard 51-CONTEXT.md names. A card with several
#      entries and no configured key selects nothing; this fixture never
#      iterates the card or falls back to its sole entry.
#   2. (D-12) `estimated_hours_saved` and `assumed_loaded_rate` are
#      IGNORED entirely -- unlike the rate-card fixture, which still gates
#      on positive finite hours/rate before pricing. Revenue is not
#      derived from effort; a clerk taking a booking may show real saved
#      time, but that time is not what values the booking.
#   3. (D-01/D-02) It declares (and returns) `economic_mechanism:
#      "incremental_revenue"` -- the producing boundary names the
#      mechanism it priced, re-checked by the caller against this
#      registrant's own registration-time declaration below.
#
# Its honest limit, stated the way the rate-card fixture's own comment
# states its (valuation.py, above): configuration establishes an approved
# value PER COMPLETED BOOKING -- an operator policy, not this booking's
# actual revenue.
#
# Redacted logging (D-11) and delegation to the built-in derivation when
# nothing revenue-shaped can be priced (D-04) are explicitly NOT this
# task's job -- 54-03 and 54-02 own them respectively; no placeholder for
# either is written here, per this task's own instruction to leave them
# absent rather than stub them.

REVENUE_CARD_FIXTURE_VERSION = "1"


def _revenue_card_valuation_fixture(assumptions: dict, config: dict) -> "dict | None":
    """Price a completed booking from an operator-approved revenue card,
    keyed by an OPERATOR-BOUND identity -- never by inferred role.

    Reads `config["revenueCard"]` when that is a dict, selects the entry
    named by `config["revenueCardKey"]` (a non-empty str present in the
    card -- a multi-entry card with no configured key, or a key the card
    does not name, abstains rather than guessing), reads that entry's
    `grossPerJob` through `_finite_number`, and returns
    `{"estimated_value": round(gross, 2), "currency": <the assumptions'
    currency>, "economic_mechanism": "incremental_revenue"}` when the
    amount is finite and positive. Every other case -- a non-dict
    `assumptions` or `config`, an absent or non-dict revenue card, a
    missing/non-str/empty/unmatched `revenueCardKey`, a non-dict selected
    entry, or a non-finite/boolean/non-positive `grossPerJob` -- returns
    None. A card that has nothing configured for the operator-bound
    identity is a reason to abstain, not to guess.

    `estimated_hours_saved` and `assumed_loaded_rate` on `assumptions` are
    deliberately never read (D-12): revenue is not derived from effort,
    so those two fields stay on the record as the evaluator's own
    assumptions without determining this fixture's value.

    The whole body runs inside one try/except returning None, logging
    with %r -- never %s, never an f-string, because a card key or amount
    can be operator-supplied text and a newline embedded in it must not
    be able to forge a second log record (the T-28-07 rule the rest of
    this plugin already follows). D-11's redaction requirement for the
    configured gross amount itself is 54-03's job, not this task's.

    Reads no clock, makes no model call and makes no network call: the
    whole derivation is a dict lookup and a bounds check.
    """
    try:
        a = assumptions if isinstance(assumptions, dict) else {}
        cfg = config if isinstance(config, dict) else {}

        revenue_card = cfg.get("revenueCard")
        if not isinstance(revenue_card, dict):
            logger.warning(
                "valuation: revenue card fixture found no configured "
                "revenue card: %r", revenue_card,
            )
            return None

        card_key = cfg.get("revenueCardKey")
        if not isinstance(card_key, str) or not card_key or card_key not in revenue_card:
            logger.warning(
                "valuation: revenue card fixture has no configured "
                "revenueCardKey selecting a configured entry: %r", card_key,
            )
            return None

        entry = revenue_card.get(card_key)
        if not isinstance(entry, dict):
            logger.warning(
                "valuation: revenue card fixture's entry for key %r is "
                "not a dict: %r", card_key, entry,
            )
            return None

        gross = _finite_number(entry.get("grossPerJob"))
        if gross is None or gross <= 0:
            logger.warning(
                "valuation: revenue card fixture rejected non-positive or "
                "non-finite grossPerJob for key %r: %r",
                card_key, entry.get("grossPerJob"),
            )
            return None

        return {
            "estimated_value": round(gross, 2),
            "currency": a.get("currency"),
            "economic_mechanism": "incremental_revenue",
        }
    except Exception:
        logger.warning(
            "valuation: revenue card fixture raised internally, rejecting "
            "assumptions: %r", assumptions,
        )
        return None


# Registered at import time, same reasoning as rate_card_valuation_fixture
# above -- a shipped second CUSTOMER_CONFIGURED fixture, this time
# declaring the one operator-only mechanism it is ever permitted to
# assert (D-01/D-03). CUSTOMER_CONFIGURED is already a member of Phase
# 53's derived reportable set, so no new reportability gate is needed for
# a configured revenue value to report.
register(
    "revenue_card_valuation_fixture",
    _revenue_card_valuation_fixture,
    REVENUE_CARD_FIXTURE_VERSION,
    evidence_class="CUSTOMER_CONFIGURED",
    economic_mechanisms={"incremental_revenue"},
)
