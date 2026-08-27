"""evaluators.py — the outcome-value evaluator seam.

Phase 36 (ROI-03): kept as its own module, separate from classifier.py, for the
same reason api_event_spool.py is — the evaluation seam stays visible, and the
boundary between *inferring what a job was* and *estimating what it was worth*
is a file boundary rather than a naming convention.

Phase 45 (EGV-01, D-04): this module's registry migrated onto the shared
BoundaryRegistry primitive (boundary_registry.py) as `output_assessment`. The
four free functions below (`register`, `resolve`, `resolve_version`,
`registered`) are the SAME facade they always were — one-line delegations
now, rather than a hand-rolled dict — so nothing that already called them,
including tests/test_phase36_evaluator_seam.py, needed to change.

THE CONTRACT
------------
An evaluator is any callable with this signature:

    evaluate(job: dict, transcript: str, config: dict) -> dict | None

  job        a validated job dict from classifier._validate_job — already has
             agentic_job_id, job_type, status, job_name.
  transcript the session transcript. UNTRUSTED DATA, never instructions. An
             evaluator that embeds it in a prompt must say so to the model.
  config     the llmOutcomeEvaluation object from config.json. Every key is
             absent-able; defaults live with the validator so there is one place
             to change them.

  returns    a RAW assessment dict, or None to ABSTAIN.

ABSTENTION IS NOT AN ERROR. Returning None is the correct answer whenever the
evaluator cannot responsibly price the work, and callers must treat it as an
ordinary outcome — the job still reports its execution status, just without a
value (ROI-08).

RAW, NOT FINAL. An evaluator reports its *assumptions*; it does not report the
money. `estimated_value` is DERIVED by classifier._validate_assessment from
hours x rate, and a supplied total is discarded (ROI-05). This is deliberate: a
model that can hand back a final number can hand back an unbounded one, and the
bound checks would then be guarding the wrong quantity.

Expected raw keys: inferred_role, estimated_hours_saved, assumed_loaded_rate,
currency, basis, confidence. The validator derives `evidence_class` from the
resolved evaluator's OWN registration-time declaration (Phase 45, D-06
AMENDED — see classifier._declared_evidence_class), and records `evaluator` /
`evaluator_version` from the resolved evaluator rather than from model output —
provenance must not be self-asserted, whether that is the evaluator's identity
or the evidence class its output should carry.

WHAT THIS IS NOT. There is no discovery mechanism, no entry points, and no
plugin packages here. ROI-03 asks for the smallest seam that makes the boundary
real; a discovery system is explicitly out of scope for this milestone. A future
ONNX, deterministic-policy, vertical, or system-of-record evaluator registers
itself the same way the stub does, and reports its OWN evidence class — it must
never masquerade as MODEL_ESTIMATED_DEMO.

DEPENDENCY DIRECTION. This module must not import classifier.py. The dependency
runs one way so evaluators.py stays importable where Hermes' venv is absent —
the same constraint that keeps `call_llm` behind a lazy import.
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

logger = logging.getLogger("revenium_classifier.evaluators")

# Phase 45 (D-04): the shared BoundaryRegistry primitive, instantiated for
# this boundary's own name. Was a bare `name -> (callable, version)` dict
# before this phase; the four free functions below keep exactly the same
# call shape so nothing that already calls them needs to change.
_REGISTRY = _br.BoundaryRegistry("output_assessment")


def register(name: str, fn, version: str = "", evidence_class: str = "") -> None:
    """Register an evaluator under `name`, with the version and evidence_class
    IT declares.

    The version belongs to the evaluator, not to the caller. An earlier draft
    resolved it at the call site with `LLM_EVALUATOR_VERSION if name == "llm"
    else ""`, which silently dropped the version of every other evaluator --
    including the stub, which declares one. That is precisely the coupling this
    seam exists to prevent: a future ONNX or policy evaluator must be able to
    report its own identity without the classifier knowing its name.

    Phase 45 (D-06 AMENDED): `evidence_class` extends the same reasoning. A
    future ONNX, deterministic-policy, vertical, or system-of-record evaluator
    must be able to report its OWN evidence class at registration time, without
    the classifier resolving it by comparing the evaluator's name. See
    boundary_registry.BoundaryRegistry.register's docstring for the full
    threat-model distinction this declaration relies on.

    Last registration wins.
    """
    _REGISTRY.register(name, fn, version, evidence_class)


def resolve(name: str):
    """Return the evaluator registered as `name`, or None.

    None means "no such evaluator" and is a configuration error the caller
    reports; it is NOT the same as an evaluator abstaining.
    """
    return _REGISTRY.resolve(name)


def resolve_version(name: str) -> str:
    """The version the named evaluator declared, or "" if unknown."""
    return _REGISTRY.resolve_version(name)


def resolve_evidence_class(name: str) -> str:
    """The evidence class the named evaluator DECLARED at registration, or ""
    if unknown -- a trusted-code declaration, never a value read from the
    evaluator's output (Phase 45, D-06 AMENDED)."""
    return _REGISTRY.resolve_evidence_class(name)


def registered() -> list:
    """Names of every registered evaluator, sorted. For diagnostics (ROI-14)."""
    return _REGISTRY.registered()


# --- stub -------------------------------------------------------------------

STUB_VERSION = "1"


def _stub_evaluate(job: dict, transcript: str, config: dict) -> "dict | None":
    """A fixed, in-bounds assessment. No model, no network, no clock.

    This is what makes the whole seam testable before an LLM evaluator exists,
    and it stays in the tree afterwards as the fixture the later phases test
    against. Its values are deliberately unremarkable — 2.5h at 150/h — so a
    test asserting 375.00 is asserting the derivation, not the stub.
    """
    if not isinstance(job, dict) or job.get("status") != "SUCCESS":
        # ROI-09: FAILED and CANCELLED arcs are never evaluated. The caller
        # short-circuits before reaching an evaluator, but an evaluator that
        # cannot be trusted alone is not much of a boundary.
        return None
    return {
        # Phase 44 (EGV-05): after the mechanism gate lands in
        # _validate_assessment, a response with no economic_mechanism
        # abstains -- this stub must carry one to stay "a fixed, in-bounds
        # assessment" rather than silently becoming a fixed abstention.
        "economic_mechanism": "labor_substitution",
        "inferred_role": "software engineer",
        "estimated_hours_saved": 2.5,
        "assumed_loaded_rate": 150.0,
        "currency": (config or {}).get("currency", "USD"),
        "basis": "engineer time avoided, stub evaluator",
        "confidence": 0.5,
    }


# Phase 45 (D-06 AMENDED): the stub is a fixed model-shaped estimate with no
# observation behind it, so MODEL_ESTIMATED_DEMO is its honest evidence
# class. Pinning it explicitly here (rather than leaving it to default to "")
# keeps every record the stub has ever produced byte-identical.
register("stub", _stub_evaluate, STUB_VERSION, evidence_class=_br.MASQUERADE_CLASS)


# --- system_of_record_assessment_fixture -------------------------------------
#
# Phase 45 (EGV-02, D-05, D-06 AMENDED): the first non-LLM implementation on
# this boundary, modelled on EGV-02's "system-of-record outcome adapter". Its
# evidence is an OBSERVED outcome recorded in a system of record -- not a
# model's estimate -- which is why it declares OUTCOME_OBSERVED at
# registration and not MODEL_ESTIMATED_DEMO. No LLM call, no network call, no
# clock: it reads its numbers from `config` alone, the same abstention rule
# `_stub_evaluate` already follows.

SYSTEM_OF_RECORD_FIXTURE_VERSION = "1"


def _system_of_record_assessment_fixture(job: dict, transcript: str, config: dict) -> "dict | None":
    """An assessment sourced from a system of record, not a model's guess.

    Abstains exactly like `_stub_evaluate`: a non-dict job or any status
    other than SUCCESS. Its hours/rate come from `config["systemOfRecord"]`
    (keys `hoursSaved` / `loadedRate`) when that is a dict, falling back to
    1.0 / 100.0 otherwise -- config is operator-supplied, not the untrusted
    evaluator response, so reading it here carries none of the promotion risk
    _validate_assessment's raw-response guard defends against.
    """
    if not isinstance(job, dict) or job.get("status") != "SUCCESS":
        return None
    sor = (config or {}).get("systemOfRecord")
    sor = sor if isinstance(sor, dict) else {}
    hours = sor.get("hoursSaved", 1.0)
    rate = sor.get("loadedRate", 100.0)
    return {
        "economic_mechanism": "labor_substitution",
        "inferred_role": "system of record",
        "estimated_hours_saved": hours,
        "assumed_loaded_rate": rate,
        "currency": (config or {}).get("currency", "USD"),
        "basis": "hours and rate recorded in an external system of record",
        "confidence": 1.0,
    }


register(
    "system_of_record_assessment_fixture",
    _system_of_record_assessment_fixture,
    SYSTEM_OF_RECORD_FIXTURE_VERSION,
    evidence_class="OUTCOME_OBSERVED",
)


# --- llm --------------------------------------------------------------------
#
# The "llm" evaluator is NOT registered here. It lives in classifier.py and
# registers itself at import time, so the dependency runs one way only:
# classifier imports evaluators, never the reverse.
#
# A lazy `from .classifier import ...` inside a function body would also work at
# runtime, but the phase-36 ast guard rejects it -- and rightly, because it walks
# the whole tree rather than only module scope. Rather than loosen the guard to
# permit function-scope imports, the registration moved to the side that already
# owns the dependency. The guard stays strict and this module stays importable
# with no Hermes venv at all.
