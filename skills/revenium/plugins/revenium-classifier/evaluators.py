"""evaluators.py — the outcome-value evaluator seam.

Phase 36 (ROI-03): kept as its own module, separate from classifier.py, for the
same reason api_event_spool.py is — the evaluation seam stays visible, and the
boundary between *inferring what a job was* and *estimating what it was worth*
is a file boundary rather than a naming convention.

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
currency, basis, confidence. The validator forces `evidence_class` and records
`evaluator` / `evaluator_version` from the resolved evaluator rather than from
model output — provenance must not be self-asserted.

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

logger = logging.getLogger("revenium_classifier.evaluators")

# name -> (callable, version). Populated by register() at import time.
_REGISTRY: dict = {}


def register(name: str, fn, version: str = "") -> None:
    """Register an evaluator under `name`, with the version IT declares.

    The version belongs to the evaluator, not to the caller. An earlier draft
    resolved it at the call site with `LLM_EVALUATOR_VERSION if name == "llm"
    else ""`, which silently dropped the version of every other evaluator --
    including the stub, which declares one. That is precisely the coupling this
    seam exists to prevent: a future ONNX or policy evaluator must be able to
    report its own identity without the classifier knowing its name.

    Last registration wins.
    """
    _REGISTRY[name] = (fn, str(version or ""))


def resolve(name: str):
    """Return the evaluator registered as `name`, or None.

    None means "no such evaluator" and is a configuration error the caller
    reports; it is NOT the same as an evaluator abstaining.
    """
    if not isinstance(name, str):
        return None
    entry = _REGISTRY.get(name)
    return entry[0] if entry else None


def resolve_version(name: str) -> str:
    """The version the named evaluator declared, or "" if unknown."""
    if not isinstance(name, str):
        return ""
    entry = _REGISTRY.get(name)
    return entry[1] if entry else ""


def registered() -> list:
    """Names of every registered evaluator, sorted. For diagnostics (ROI-14)."""
    return sorted(_REGISTRY)


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


register("stub", _stub_evaluate, STUB_VERSION)


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
