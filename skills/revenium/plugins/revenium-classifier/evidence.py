"""evidence.py — the evidence resolution and reportability boundary (EGV-01).

Phase 45: kept as its own module, for the same reason evaluators.py,
impact_study.py, cohort_impact.py, reporting.py, classification.py and
valuation.py are — the boundary is a FILE boundary, not merely a naming
convention. This is the SIXTH and last boundary this phase carves out of
`classifier.py`, and it owns TWO halves that are related but distinct: the
rule that decides which evidence label a registered implementation may
CLAIM, and the policy that decides whether an accepted estimate is
REPORTABLE.

THE CONTRACT
------------
A reportability implementation is any callable with this signature:

    reportability(request: dict, config: dict) -> dict | None

  request  CALLER-CONSTRUCTED plain data. Every key: `abstained` (bool --
           whether the assessment this request describes has already
           abstained from a value), `agentic_job_id` (str), `job_type`
           (str). The UNTRUSTED evaluator response never crosses this
           boundary as `request` -- only caller-resolved job identity does.

  config   the llmOutcomeEvaluation object from config.json, the same
           object evaluators.py's and valuation.py's own contracts already
           thread through. Every key is absent-able. The shipped fixture
           reads its confirmations from `config["confirmations"]`.

  returns  {"reportability_status": <one of the two known literals,
           REPORTABILITY_REPORTABLE or REPORTABILITY_CANDIDATE>} or None to
           ABSTAIN (decline to resolve; the caller keeps its own default).

An implementation MUST be synchronous: reportability is a policy decision
over already-validated data, and there is nothing to await.

THE CALLER-SIDE INVARIANT, stated plainly because it is the reason this
boundary is safe to make pluggable at all: the caller checks D-05's
abstention rule FIRST, UNCONDITIONALLY, before any implementation is
consulted -- an abstained assessment is never reportable, whatever a
registered implementation returns, and that check cannot be reached
around. The caller then validates whatever a resolved implementation
returns against the two known literals, defaulting to the candidate
status for anything else. A confirmation workflow can decide that a REAL
estimate is reportable; it cannot decide that an ABSENT estimate is
(PA-18). This is a deliberate distrust of registered code on the money
path, matching valuation.py's own ceiling re-assertion: registration is
trusted to declare an identity, never to unlock money reporting on its
own say-so.

ABSTENTION IS NOT AN ERROR. An implementation with nothing to say about a
request returns None, and the caller keeps its existing default (today,
the inline config-opt-in rule) -- the same idiom every other boundary in
this phase shares.

WHAT THIS IS NOT. There is no discovery mechanism, no entry points, and no
plugin packages here -- Phase 36's decision stands, restated for this
boundary. And, stated explicitly because it is the one property that most
needs saying out loud: this module does NOT decide an implementation's
evidence class. The class is DECLARED at `register()` time by trusted code
(D-06 AMENDED, the same mechanism every other boundary in this phase
uses) -- this module only supplies the pure allow-list rule the host
applies to that declaration (`resolve_declared_class`, below), and the
host still passes only the caller-supplied implementation NAME to that
rule, never any implementation OUTPUT. Evidence-class resolution and
reportability resolution are two different moments over two different
kinds of data, sharing one file because they are one governing concern:
what may a registered implementation honestly CLAIM about the evidence
behind an estimate, and MAY that estimate ship as money.

DEPENDENCY DIRECTION. This module must not import classifier.py, for the
same reason evaluators.py, impact_study.py, cohort_impact.py, reporting.py,
classification.py and valuation.py must not: the dependency runs one way
so this module stays importable where Hermes' venv is absent -- proven by
loading it from its own file path with no package parent (D-09's
host-agnosticism rule; see also EGV-03). Host data crosses this boundary
as plain data only -- dicts, strings, numbers -- never a `Path`, a sqlite3
connection, or a file handle (no test enforces this half; this module
obeys the rule by example, stated as a documented rule per D-09). This
module therefore duplicates its own byte-clamp helper rather than
importing classifier.py's or impact_study.py's -- the duplication is
deliberate and required by the dependency rule, not an oversight.

THE NINE LABELS ARE FLAT AND UNORDERED, ON PURPOSE (from
classifier.EVIDENCE_CLASSES' own comment, restated here because
`resolve_declared_class` below is the one function in this whole phase
whose entire job is to respect that shape): customer confirmation may be
commercially authoritative yet causally weak; observation proves
occurrence, not cause; configuration establishes an approved rate, not
actual hours worked -- so no two of the nine labels are comparable, and
none may be sorted, ranked, indexed, or compared as an ordering key.
`resolve_declared_class` performs a MEMBERSHIP test and nothing else -- it
must never sort, rank, index or order-compare two labels, and adding such
a comparison would break the vocabulary's stated contract, not merely
change this function.
"""

from __future__ import annotations

import logging

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

logger = logging.getLogger("revenium_classifier.evidence")

# Phase 45 (D-01, D-04): the shared BoundaryRegistry primitive, instantiated
# for this boundary's own name. Like classification.py and valuation.py,
# this registry does NOT ship empty -- the confirmation-workflow fixture
# below is registered at import time, because a second, real, non-model
# implementation is what makes this boundary provably pluggable rather than
# hypothetical (the same reason evaluators.py has shipped `stub` since
# Phase 36).
_REGISTRY = _br.BoundaryRegistry("evidence")


def register(name: str, fn, version: str = "", evidence_class: str = "") -> None:
    """Register a reportability implementation under `name`, with the
    version and evidence_class IT declares.

    Same reasoning as evaluators.py's/valuation.py's own register(): a
    future ONNX, deterministic-policy, or confirmation-workflow
    implementation must be able to report its own identity and its own
    evidence class without this registry -- or any caller -- knowing its
    name.

    Last registration wins.
    """
    _REGISTRY.register(name, fn, version, evidence_class)


def resolve(name: str):
    """Return the reportability implementation registered as `name`, or
    None.

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
    """Names of every registered reportability implementation, sorted. For
    diagnostics."""
    return _REGISTRY.registered()


# --- shared duplicated helper ----------------------------------------------
#
# Duplicated from impact_study.py's own _clamp_text (itself duplicated from
# classifier.py's _clamp_assessment_text), not imported -- see the module
# docstring's DEPENDENCY DIRECTION paragraph. Same reasoning as the
# original: json.dumps with ensure_ascii=True escapes every non-ASCII code
# point, so a character clamp under-counts by up to 12x for emoji.

NARRATIVE_CLAMP_BYTES = 500


def _clamp_text(value, limit: int = NARRATIVE_CLAMP_BYTES) -> str:
    """Coerce to str and clamp to `limit` SERIALIZED BYTES -- not characters.

    Duplicated from impact_study._clamp_text (itself duplicated from
    classifier._clamp_assessment_text, classifier.py:888), not imported --
    see the module docstring's DEPENDENCY DIRECTION paragraph.
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


# Phase 43 (EGV-18, D-05/D-09): DUPLICATES of classifier.py's own
# REPORTABILITY_REPORTABLE/REPORTABILITY_CANDIDATE constants
# (classifier.py:1612-1613), not imported -- the dependency rule forbids
# it, exactly as it forbids importing EVIDENCE_CLASS_MODEL_ESTIMATED
# (boundary_registry.py duplicates that one as MASQUERADE_CLASS). The two
# declarations are hand-synced; this repo already treats the mechanism
# vocabulary shared between classifier.py and the reporter the same way
# (README/CLAUDE.md's "ledger semantics" discipline).
REPORTABILITY_REPORTABLE = "reportable"
REPORTABILITY_CANDIDATE = "candidate"


def resolve_declared_class(declared, allowed, default: str) -> str:
    """Return `declared` when it is a string present in `allowed`, else
    `default`.

    This is the allow-list rule classifier._declared_evidence_class
    delegates its membership test to (PA-19) -- the rule lives with the
    boundary that owns evidence rather than in the host module. Every
    outcome other than "a str member of allowed" -- a non-string
    `declared`, an empty string, a label absent from `allowed`, a
    non-iterable `allowed`, or any internal failure (including `in`
    raising on a malformed `allowed`) -- returns `default`.

    MEMBERSHIP ONLY. This function must never sort, rank, index or
    order-compare two labels -- see the module docstring's closing
    paragraph for why: the nine-label vocabulary is deliberately flat and
    unordered, and adding an ordering comparison here would break that
    contract, not merely change this function.

    The whole body runs inside one try/except returning `default`, logging
    a rejected declaration with %r -- never %s, never an f-string, because
    a declared label can be caller-supplied and a newline embedded in it
    must not be able to forge a second log record (the T-28-07 rule the
    rest of this plugin already follows).
    """
    try:
        if isinstance(declared, str) and declared and declared in allowed:
            return declared
        logger.warning(
            "evidence: resolve_declared_class rejected declaration outside "
            "the allow-list: %r", declared,
        )
        return default
    except Exception:
        logger.warning(
            "evidence: resolve_declared_class raised internally rejecting "
            "declaration: %r", declared,
        )
        return default


# --- _confirmation_workflow_evidence_fixture -------------------------------
#
# Phase 45 (EGV-02, D-05): the non-model fixture proving this boundary fits
# without masquerading. Modelled on EGV-02's "confirmation workflow" slot:
# an operator-recorded customer confirmation makes an estimate reportable,
# with no model call anywhere in the decision.
#
# It declares CUSTOMER_CONFIRMED, not MODEL_ESTIMATED_DEMO: the honest
# claim is that a customer confirmed the outcome, not that a model
# estimated it. The honest limit of that claim, matching the vocabulary's
# own definition: customer confirmation may be commercially authoritative
# yet causally weak, so confirming an outcome is not the same as observing
# that the work caused it.

CONFIRMATION_FIXTURE_VERSION = "1"


def _confirmation_workflow_evidence_fixture(request: dict, config: dict) -> "dict | None":
    """Mark an estimate reportable only when an operator has recorded a
    customer confirmation for this exact job.

    Reads `config["confirmations"]` when that is a list, and returns the
    reportable status only for a request that is NOT abstained AND whose
    `agentic_job_id` appears in that list. Every other case -- an abstained
    request, a job id absent from the list, a missing or non-list
    `confirmations` value -- returns the candidate status. A non-dict
    `request` or `config` returns None (abstain) rather than raising.

    Reads no clock, makes no model call and makes no network call: the
    whole decision is a membership check.
    """
    try:
        if not isinstance(request, dict) or not isinstance(config, dict):
            return None
        if request.get("abstained"):
            return {"reportability_status": REPORTABILITY_CANDIDATE}
        confirmations = config.get("confirmations")
        job_id = request.get("agentic_job_id")
        if isinstance(confirmations, list) and job_id in confirmations:
            return {"reportability_status": REPORTABILITY_REPORTABLE}
        return {"reportability_status": REPORTABILITY_CANDIDATE}
    except Exception:
        logger.warning(
            "evidence: confirmation workflow fixture raised internally, "
            "rejecting request: %r", request,
        )
        return None


# Registered at import time -- like classification.py and valuation.py,
# this boundary is not required to ship empty, and a shipped fixture is
# what makes the second implementation installable rather than
# hypothetical, the same reason evaluators.py's `stub` has stayed in the
# tree since Phase 36.
register(
    "confirmation_workflow_evidence_fixture",
    _confirmation_workflow_evidence_fixture,
    CONFIRMATION_FIXTURE_VERSION,
    evidence_class="CUSTOMER_CONFIRMED",
)
