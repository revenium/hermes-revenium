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
#   4. (D-09/D-10, ROI-07) The entry may ALSO carry `attributionFraction`
#      and `attributionBasis`. When both are present and valid, the
#      returned `estimated_value` is `round(gross * fraction, 2)` -- the
#      product, never the gross -- and the return dict carries the
#      validated `attribution_fraction`/`attribution_basis` pair under
#      the SAME snake_case wire names `correct-assessment.sh`'s
#      `--attribution-fraction`/`--attribution-basis` flags already
#      persist, so the configured and CLI paths produce one
#      representation rather than two that can diverge (D-10). See the
#      multiplication itself, below, for why this is a narrow, deliberate
#      reversal of `51-CONTEXT.md` D-05 rather than an oversight.
#
# Its honest limit, stated the way the rate-card fixture's own comment
# states its (valuation.py, above): configuration establishes an approved
# value PER COMPLETED BOOKING -- an operator policy, not this booking's
# actual revenue.
#
# Redaction-safe logging (D-11, ROI-08, T-54-02). The sibling
# _rate_card_valuation_fixture above logs the REJECTED CONFIGURED VALUE
# itself on every one of its five warning call sites (the role, the
# amount, or the whole `assumptions` dict on its outer except) -- that
# habit is deliberately NOT copied here. `revenium-metering.log` is
# PERSISTED, so a logged gross is a persisted gross, which is exactly what
# ROI-08 forbids for a business figure. Every branch below therefore logs
# only a FIXED reason word from a closed vocabulary this module defines
# (_REVENUE_ABSTAIN_REASONS) plus the card key name, formatted with %r --
# never the configured amount, never the entry dict, and never the whole
# `config`. The card key is an operator-authored identifier, not the
# money; logging it keeps the T-28-07 %r-not-%s/no-f-string rule (a
# newline embedded in operator text must not forge a second log record)
# while making the diagnostic useful rather than merely empty.
#
# Internal delegation to the built-in derivation (D-04). `boundaries.valuation`
# is a single GLOBAL selection -- pointing an install at this registrant would
# otherwise silently strip value from every ORDINARY, non-revenue session on
# that host, because a registrant returning None aborts the whole assessment
# (classifier.py's caller re-check). The abstain branches above split into
# two classes, and the split is the composition D-04 requires, visible here
# in one registrant's own code rather than as a caller-side special case:
#
#   - NOTHING REVENUE-SHAPED TO PRICE -- `revenueCard` absent/not a
#     dict/empty, `revenueCardKey` absent/empty/not a string, or a
#     `revenueCardKey` naming an entry the card does not hold. The operator
#     has not asked for THIS job to be priced as revenue at all, so the
#     fixture DELEGATES to `resolve("hours_times_rate")` and returns its
#     result verbatim -- no `economic_mechanism`, no attribution. When that
#     resolves to nothing (a `valuation.py` loaded with no classifier to
#     register the built-in), the delegation itself returns None:
#     abstention keeps meaning abstention, rather than this fixture growing
#     a second, local copy of the built-in's own arithmetic.
#   - ASKED TO PRICE AND CANNOT -- the entry exists but is not a dict, or
#     `grossPerJob` is unusable. This is a configuration error about THIS
#     job specifically, not an absence of revenue configuration, so it
#     abstains outright (returns None) rather than quietly pricing the
#     booking as ordinary labour.
#
# Self-delegation is guarded explicitly: this fixture never resolves and
# calls its OWN registered name, even if an operator has pointed
# `hours_times_rate` at `revenue_card_valuation_fixture` itself. A
# delegation cycle inside a registrant contracted to never raise would
# recurse until the interpreter's stack limit -- there is no try/except
# shallow enough to catch a RecursionError gracefully on a money path.
#
# The composition lives here, visibly, in this registrant's own code; the
# boundary contract itself is untouched -- `boundaries.valuation` remains a
# single global selection and `None` still means abstain.

REVENUE_CARD_FIXTURE_VERSION = "1"

# Phase 54 (D-08, D-09): the fixed prefix every producer-authored `basis`
# starts from -- states the provenance and the honest limit the SAME way
# the sibling rate-card fixture's own module comment states its: an
# APPROVED VALUE PER COMPLETED BOOKING, not this booking's actual
# revenue. The fraction is safe to name after this prefix (see below);
# the gross never is, on any branch, under any name.
_REVENUE_CARD_BASIS_PREFIX = (
    "revenue card: an approved value per completed booking, not this "
    "booking's actual revenue"
)


def _delegate_to_builtin_hours_times_rate(assumptions: dict, config: dict) -> "dict | None":
    """D-04: delegate to the `hours_times_rate` registrant when this
    fixture has nothing revenue-shaped to price.

    Returns the built-in's result VERBATIM (which may itself be None, on
    the built-in's own abstain path), or None when `hours_times_rate` is
    unresolved -- a `valuation.py` loaded standalone with no classifier to
    register it, in which case abstention keeps meaning abstention rather
    than this fixture inventing a local copy of the built-in's own
    arithmetic.

    Guards against self-delegation: if the name `hours_times_rate` has
    been registered to THIS very function (an operator pointing the
    built-in's own name at the revenue fixture), resolving and calling it
    here would recurse into itself forever, inside a function contracted
    to never raise. The identity check refuses that call and returns None
    instead -- a self-referential configuration is itself a reason to
    abstain, not a delegation.
    """
    builtin = resolve("hours_times_rate")
    if builtin is None or builtin is _revenue_card_valuation_fixture:
        return None
    return builtin(assumptions, config)

# Phase 54 (D-11, ROI-08, T-54-02): the closed set of reason words this
# fixture's diagnostics may ever emit. A branch names exactly one of these
# plus the card key -- never the offending value, never the configured
# amount. Keeping the vocabulary closed (rather than free-text) is what
# makes "never leaks the value" provable rather than merely intended: a
# reviewer or a future edit can grep this frozenset for the complete list
# of things this fixture is allowed to say when it abstains.
_REVENUE_ABSTAIN_REASONS = frozenset({
    "malformed_assumptions",
    "malformed_config",
    "no_configured_card",
    "unmatched_key",
    "malformed_entry",
    "malformed_gross",
    "malformed_attribution",
    "internal_error",
})


def _revenue_card_valuation_fixture(assumptions: dict, config: dict) -> "dict | None":
    """Price a completed booking from an operator-approved revenue card,
    keyed by an OPERATOR-BOUND identity -- never by inferred role.

    Reads `config["revenueCard"]` when that is a non-empty dict, selects
    the entry named by `config["revenueCardKey"]` (a non-empty str present
    in the card), reads that entry's `grossPerJob` through
    `_finite_number`, and returns `{"estimated_value": round(gross, 2),
    "currency": <the assumptions' currency>, "economic_mechanism":
    "incremental_revenue"}` when the amount is finite and positive.

    Two DIFFERENT things happen when this fixture cannot price the job
    (D-04), and they are deliberately not the same outcome:

    - NOTHING REVENUE-SHAPED TO PRICE -- an absent, non-dict, or empty
      `revenueCard`; an absent, empty, non-str, or unmatched
      `revenueCardKey` -- DELEGATES internally to the built-in
      `hours_times_rate` registrant and returns its result verbatim, so
      an ordinary non-revenue session on a revenue-configured host still
      gets its value. A multi-entry card with no configured key, or a
      key the card does not name, is exactly this case: the operator has
      not asked for THIS job to be priced as revenue at all.
    - ASKED TO PRICE AND CANNOT -- the selected entry is not a dict, or
      its `grossPerJob` is non-finite/boolean/non-positive -- ABSTAINS
      outright (returns None). A card that names this job but cannot be
      read is a configuration error about this job, not an absence of
      revenue configuration, and abstaining beats quietly pricing the
      booking as ordinary labour.

    A non-dict `assumptions` or a non-dict `config` also abstains outright
    (also None) -- see `_delegate_to_builtin_hours_times_rate` for the
    delegation itself and its own self-delegation guard.

    Phase 54 (D-09/D-10, ROI-07): the selected entry may ALSO carry
    `attributionFraction` and `attributionBasis`. The two travel as a
    SET -- one present without the other abstains outright, the same
    rule `correct-assessment.sh`'s own `--attribution-fraction`/
    `--attribution-basis` flag pair enforces -- and a present fraction
    must be finite, non-boolean, and within `[0.0, 1.0]` inclusive at
    both endpoints, or the entry abstains. When both validate, the
    returned `estimated_value` is `round(gross * fraction, 2)` -- the
    PRODUCT, computed in one expression at the point of return, never
    the gross under any key or in any diagnostic -- and the return dict
    additionally carries the validated `attribution_fraction` (float)
    and `attribution_basis` (clamped to `NARRATIVE_CLAMP_BYTES`
    serialized bytes, the same limit `correct-assessment.sh`'s own
    `_clamp_reason` uses). With neither key configured, the entry prices
    at `round(gross, 2)` exactly as before this phase, and the return
    dict carries neither attribution key.

    Its honest limit, stated the way the rate-card fixture states its own:
    configuration establishes an approved value PER COMPLETED BOOKING --
    an operator policy, not this booking's actual revenue.

    Phase 54 (D-08): on every branch where THIS fixture actually derives
    a value (never on a delegation branch, never on an abstain), the
    return dict also carries a `basis` string it authored itself --
    `_REVENUE_CARD_BASIS_PREFIX`, plus the applied fraction when one was
    applied. The fraction is safe to name in that string; the gross is
    not, and never appears in it. The caller's own 200-byte clamp on
    `basis` cannot truncate this string mid-sentence -- it is built to
    stay well under that bound by construction, not merely by care.

    `estimated_hours_saved` and `assumed_loaded_rate` on `assumptions` are
    deliberately never read (D-12): revenue is not derived from effort,
    so those two fields stay on the record as the evaluator's own
    assumptions without determining this fixture's value.

    The whole body runs inside one try/except returning None. Every
    abstain branch, including this outer except, logs ONLY a fixed reason
    word from `_REVENUE_ABSTAIN_REASONS` and the card key name (%r,
    never %s, never an f-string -- T-28-07) -- never the configured
    amount, never the entry dict, and never the whole `config` (D-11,
    ROI-08, T-54-02; see the module comment above this function for why
    this deliberately does NOT copy the sibling rate-card fixture's habit
    of logging the rejected value). The happy path emits no log record at
    all.

    Reads no clock, makes no model call and makes no network call: the
    whole derivation is a dict lookup, a bounds check and one
    multiplication-free lookup.
    """
    card_key = None
    try:
        if not isinstance(assumptions, dict):
            logger.warning(
                "valuation: revenue card fixture abstained (%s) for key %r",
                "malformed_assumptions", card_key,
            )
            return None
        if not isinstance(config, dict):
            logger.warning(
                "valuation: revenue card fixture abstained (%s) for key %r",
                "malformed_config", card_key,
            )
            return None

        a = assumptions
        cfg = config
        card_key = cfg.get("revenueCardKey")

        revenue_card = cfg.get("revenueCard")
        if not isinstance(revenue_card, dict) or not revenue_card:
            logger.warning(
                "valuation: revenue card fixture found nothing revenue-shaped "
                "to price (%s), delegating to the built-in derivation for "
                "key %r", "no_configured_card", card_key,
            )
            return _delegate_to_builtin_hours_times_rate(assumptions, config)

        if not isinstance(card_key, str) or not card_key or card_key not in revenue_card:
            logger.warning(
                "valuation: revenue card fixture found nothing revenue-shaped "
                "to price (%s), delegating to the built-in derivation for "
                "key %r", "unmatched_key", card_key,
            )
            return _delegate_to_builtin_hours_times_rate(assumptions, config)

        entry = revenue_card.get(card_key)
        if not isinstance(entry, dict):
            logger.warning(
                "valuation: revenue card fixture abstained (%s) for key %r",
                "malformed_entry", card_key,
            )
            return None

        gross = _finite_number(entry.get("grossPerJob"))
        if gross is None or gross <= 0:
            logger.warning(
                "valuation: revenue card fixture abstained (%s) for key %r",
                "malformed_gross", card_key,
            )
            return None

        # Phase 54 (D-09/D-10, ROI-07): the attribution pair, read and
        # validated ONLY here, after gross itself already validated.
        # `51-CONTEXT.md` D-05 chose "recorded, never computed" for two
        # reasons: (a) keeping gross out of a metering RECORD is the only
        # structural defence against cross-system double counting
        # available at this layer -- the channel, the loyalty programme,
        # the pricing engine and marketing attribution each already claim
        # the same stay -- and (b) it kept this skill from becoming the
        # site where a business-gross figure meets an attribution policy.
        # D-09 narrowly reverses (b), in the open: this skill now IS that
        # site, for the configured path only. (a) survives completely --
        # `gross` above is read, multiplied below, and discarded; it is
        # bound to no other name, returned under no key, and named in no
        # diagnostic. The rejected alternative was letting the operator
        # pre-multiply off-system, which lets a later fraction edit
        # silently desynchronise from an amount nobody recomputed --
        # exactly the drift phase success criterion 5 forbids. Doing the
        # multiplication here, in one expression, makes that criterion
        # true by construction.
        raw_fraction = entry.get("attributionFraction")
        raw_basis = entry.get("attributionBasis")
        has_fraction = raw_fraction is not None
        has_basis_text = isinstance(raw_basis, str) and raw_basis.strip() != ""

        attribution_fraction = None
        attribution_basis_text = None

        if has_fraction and not has_basis_text:
            # Travel-as-a-set, direction 1: a bare fraction carries the
            # appearance of precision with nothing to answer for it --
            # same rule, same reasoning as correct-assessment.sh's own
            # --attribution-fraction/--attribution-basis flag pair.
            logger.warning(
                "valuation: revenue card fixture abstained (%s) for key %r",
                "malformed_attribution", card_key,
            )
            return None
        if not has_fraction and raw_basis is not None:
            # Travel-as-a-set, direction 2: a basis with nothing to
            # attribute.
            logger.warning(
                "valuation: revenue card fixture abstained (%s) for key %r",
                "malformed_attribution", card_key,
            )
            return None
        if has_fraction:
            fraction = _finite_number(raw_fraction)
            if fraction is None or not (0.0 <= fraction <= 1.0):
                # Rejects non-finite, boolean, non-numeric, and anything
                # outside [0.0, 1.0] -- both endpoints are legal, matching
                # the CLI flag's own inclusive bound.
                logger.warning(
                    "valuation: revenue card fixture abstained (%s) for "
                    "key %r", "malformed_attribution", card_key,
                )
                return None
            attribution_fraction = fraction
            attribution_basis_text = _clamp_text(raw_basis, NARRATIVE_CLAMP_BYTES)

        # The multiplication: ONE expression, at this ONE site, bound
        # directly to the value this function returns. `gross` is never
        # rebound to a longer-lived name for this purpose.
        estimated_value = round(
            gross * attribution_fraction if attribution_fraction is not None
            else gross,
            2,
        )

        # Phase 54 (D-08): the producer-authored basis -- present only on
        # this, the branch where this fixture actually derived a value.
        # The fraction is safe to name here; the gross is not, and is
        # never referenced.
        basis_text = _REVENUE_CARD_BASIS_PREFIX
        if attribution_fraction is not None:
            basis_text = (
                f"{_REVENUE_CARD_BASIS_PREFIX} (attribution "
                f"{attribution_fraction} applied; see attribution_basis)"
            )
        basis_text = _clamp_text(basis_text, 200)

        result = {
            "estimated_value": estimated_value,
            "currency": a.get("currency"),
            "economic_mechanism": "incremental_revenue",
            "basis": basis_text,
        }
        if attribution_fraction is not None:
            # Same snake_case wire names Phase 51 shipped for the CLI
            # path (D-10) -- emitted ONLY when both validated, so an
            # unconfigured entry's return dict carries neither key.
            result["attribution_fraction"] = attribution_fraction
            result["attribution_basis"] = attribution_basis_text
        return result
    except Exception:
        logger.warning(
            "valuation: revenue card fixture abstained (%s) for key %r",
            "internal_error", card_key,
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
