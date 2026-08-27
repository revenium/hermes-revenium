"""classification.py — the classification boundary (EGV-01).

Phase 45 (D-13): kept as its own module, for the same reason evaluators.py,
impact_study.py and cohort_impact.py are — the boundary is a FILE boundary,
not merely a naming convention. D-13 supersedes 45-RESEARCH.md's Assumption
A1 (which recommended scoping this boundary to `task_type` alone): this ONE
contract covers BOTH turn-level `task_type` labelling AND job/arc inference,
because they share the classification concern even though their call paths
in classifier.py differ (_classify_via_llm vs _infer_jobs_via_llm). A `kind`
discriminator on the request tells one implementation which half of the
concern a given call is asking about, rather than splitting the boundary
into two registries for one concern.

THE CONTRACT
------------
A classifier is any callable with this signature:

    classify(request: dict, config: dict) -> dict | None

  request  plain data, carrying a `kind` discriminator of either
            "task_type" or "jobs":

            kind == "task_type":
              context           the SAME shape _classify_via_llm's own
                                 `context` parameter already uses — a dict
                                 with one key, `message` (the user message
                                 str). Kept as a dict, not flattened to a
                                 bare string, so the built-in `llm`
                                 registrant can pass it straight through to
                                 _classify_via_llm unchanged.
              response_preview  the assistant response preview, a str.
              labels            the existing task_type vocabulary, as a
                                 PLAIN LIST OF STRINGS supplied BY THE
                                 CALLER (PA-13 in 45-01-PLAN.md). Reading
                                 the taxonomy file is host I/O and stays on
                                 the host side of this boundary — this is
                                 what lets the contract be extracted to a
                                 standalone library later.

            kind == "jobs":
              transcript  the session transcript, a str.
              labels      the existing job_type vocabulary, as a plain list
                          of strings, supplied BY THE CALLER for the same
                          reason as above.

  config   the llmOutcomeEvaluation object from config.json (the same
           object evaluators.py's own contract already threads through).
           Every key is absent-able.

  returns  {"task_type": <str>} for a "task_type" request, {"jobs": <list
           of job dicts>} for a "jobs" request, or None to ABSTAIN. An
           implementation MAY return an awaitable of either shape; the
           caller resolves it with inspect.isawaitable — the same idiom
           classifier._attach_assessment already uses for a registered
           evaluator that may be sync or async.

`request["transcript"]`, `request["context"]` and `request["response_preview"]`
are UNTRUSTED DATA, never instructions — the same rule evaluators.py's own
`transcript` parameter states. An implementation that embeds any of them in
a prompt must say so to the model.

ABSTENTION IS NOT AN ERROR. A classifier that cannot responsibly label a
turn, or cannot responsibly infer any job arcs, returns None — and the
caller records `unclassified` (task_type) or an empty job list (jobs)
exactly as it does today when the built-in model call fails. This is the
same idiom evaluators.py's own contract and impact_study.validate() both
already share.

WHAT THIS IS NOT. There is no discovery mechanism, no entry points, and no
plugin packages here — Phase 36's decision stands, restated for this
boundary. And, stated plainly rather than left implicit: this contract does
NOT validate the label or the job dicts it returns. `classifier._validate_label`
and `classifier._validate_job` stay at the CALL SITE and apply the SAME
taxonomy rules to every implementation's output identically (PA-14) — a
registered classifier, whatever produced its answer, cannot write a label or
a job the built-in path would have rejected. Moving that validation behind
this contract would let a registered implementation write an unvalidated
label straight into the taxonomy, which is exactly the promotion risk this
split is designed to avoid.

DEPENDENCY DIRECTION. This module must not import classifier.py, for the
same reason evaluators.py, impact_study.py and cohort_impact.py must not:
the dependency runs one way so this module stays importable where Hermes'
venv is absent — proven by loading it from its own file path with no
package parent (D-09's host-agnosticism rule; see also EGV-03). Host data
crosses this boundary as plain data only — dicts, strings, numbers — never
a `Path`, a sqlite3 connection, or a file handle (no test enforces this
half; this module obeys the rule by example). Consequently this module
duplicates its own byte-clamp helper rather than importing
classifier.py's or impact_study.py's — the duplication is deliberate and
required by the dependency rule, not an oversight.
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

logger = logging.getLogger("revenium_classifier.classification")

# Phase 45 (D-01, D-04, D-13): the shared BoundaryRegistry primitive,
# instantiated for this boundary's own name. Unlike cohort_impact.py and
# reporting.py, this registry does NOT ship empty -- the keyword fixture
# below is registered at import time, because a second, real, non-LLM
# implementation is what makes this boundary provably pluggable rather than
# hypothetical (the same reason evaluators.py has shipped `stub` since
# Phase 36).
_REGISTRY = _br.BoundaryRegistry("classification")


def register(name: str, fn, version: str = "", evidence_class: str = "") -> None:
    """Register a classifier under `name`, with the version and
    evidence_class IT declares.

    Same reasoning as evaluators.py's own register(): a future ONNX
    classifier, or any other implementation, must be able to report its own
    identity and its own evidence class without this registry -- or any
    caller -- knowing its name.

    Last registration wins.
    """
    _REGISTRY.register(name, fn, version, evidence_class)


def resolve(name: str):
    """Return the classifier registered as `name`, or None.

    None means "no such registrant" and is a configuration error the
    caller reports; it is NOT the same as a classifier abstaining.
    """
    return _REGISTRY.resolve(name)


def resolve_version(name: str) -> str:
    """The version the named classifier declared, or "" if unknown."""
    return _REGISTRY.resolve_version(name)


def resolve_evidence_class(name: str) -> str:
    """The evidence class the named classifier DECLARED at registration, or
    "" if unknown -- a trusted-code declaration, never a value read from the
    classifier's output."""
    return _REGISTRY.resolve_evidence_class(name)


def registered() -> list:
    """Names of every registered classifier, sorted. For diagnostics."""
    return _REGISTRY.registered()


# --- shared duplicated helper --------------------------------------------
#
# Duplicated from impact_study.py's own _clamp_text (itself duplicated from
# classifier.py's _clamp_assessment_text), not imported -- see the module
# docstring's DEPENDENCY DIRECTION paragraph. The duplication is deliberate
# and required by the dependency rule, not an oversight.

NARRATIVE_CLAMP_BYTES = 500


def _clamp_text(value, limit: int = NARRATIVE_CLAMP_BYTES) -> str:
    """Coerce to str and clamp to `limit` SERIALIZED BYTES -- not characters.

    Duplicated from impact_study._clamp_text (itself duplicated from
    classifier._clamp_assessment_text), not imported -- see the module
    docstring's DEPENDENCY DIRECTION paragraph. Same reasoning as the
    original: json.dumps with ensure_ascii=True escapes every non-ASCII
    code point, so a character clamp under-counts by up to 12x for emoji.
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


# --- _keyword_classification_fixture -------------------------------------
#
# Phase 45 (EGV-02, D-05): the non-LLM fixture proving this boundary fits
# without masquerading. Modelled on EGV-02's "ONNX classifier" slot, but
# implemented as a deterministic keyword matcher so it needs no dependency
# at all. No model call, no network call, no clock: every decision is made
# from the request's own text and the caller-supplied label list.
#
# It declares ACTIVITY_MEASURED, not MODEL_ESTIMATED_DEMO: it reports
# observed activity in the turn's own text -- which tokens of which
# candidate label actually appear -- with no model estimate anywhere in the
# derivation, so claiming the naked-LLM label would be a lie about where
# the label came from.

KEYWORD_FIXTURE_VERSION = "1"

# A deliberately small declared maximum, matching cohort_impact.py's own
# "deliberately simple, not a real model" posture -- this fixture's point is
# to prove the registry accepts a registrant that displaces the built-in
# end to end, not to be a good classifier.
_MAX_INFERRED_JOBS = 5

_PUNCTUATION = ".,!?;:()[]{}\"'`~@#$%^&*+=|\\/<>\n\t\r"


def _tokenize(text: str) -> "set[str]":
    """Lowercase `text` and split it into a set of alnum/underscore tokens,
    without importing `re` -- this module's DEPENDENCY DIRECTION paragraph
    keeps its import graph to importlib/json/logging (plus the mandatory
    boundary_registry import), and `re` is neither. Punctuation is stripped
    per word, and every word is further split on `-`/`_` so a label's own
    underscore-separated tokens can be compared against it directly.
    """
    tokens: "set[str]" = set()
    for word in (text or "").lower().split():
        word = word.strip(_PUNCTUATION)
        for part in word.replace("-", "_").split("_"):
            if part:
                tokens.add(part)
    return tokens


def _best_label(tokens: "set[str]", labels) -> "str | None":
    """The label from `labels` whose own underscore-separated tokens overlap
    `tokens` the most, or None when nothing scores above zero -- returning
    None rather than an arbitrary first label is what keeps this an honest
    abstention instead of an invented guess."""
    best_label, best_score = None, 0
    for label in labels:
        if not isinstance(label, str) or not label:
            continue
        label_tokens = [t for t in label.lower().split("_") if t]
        score = sum(1 for t in label_tokens if t in tokens)
        if score > best_score:
            best_label, best_score = label, score
    return best_label


def _keyword_task_type(request: dict) -> "dict | None":
    """kind == 'task_type': score every supplied label by how many of its
    own tokens appear in the context message + response preview, and return
    the highest scorer -- or None when nothing scores above zero, because
    inventing a label is exactly the failure mode the taxonomy governs
    against."""
    labels = request.get("labels")
    if not isinstance(labels, list):
        return None
    ctx = request.get("context")
    if isinstance(ctx, dict):
        message = ctx.get("message", "")
    elif isinstance(ctx, str):
        message = ctx
    else:
        message = ""
    preview = request.get("response_preview")
    preview = preview if isinstance(preview, str) else ""
    tokens = _tokenize(f"{message} {preview}")
    if not tokens:
        return None
    best = _best_label(tokens, labels)
    if best is None:
        return None
    return {"task_type": best}


def _keyword_jobs(request: dict) -> "dict | None":
    """kind == 'jobs': derive one job dict per non-empty transcript
    paragraph, capped at _MAX_INFERRED_JOBS, each carrying the keys
    classifier._validate_job requires with a status of SUCCESS. job_type is
    the best-scoring supplied job label for that paragraph, falling back to
    a fixed, LABEL_RE-shaped default when nothing scores -- this fixture
    always classifies an arc it found, unlike the task_type path, which may
    abstain entirely."""
    transcript = request.get("transcript")
    if not isinstance(transcript, str) or not transcript.strip():
        return None
    labels = request.get("labels")
    labels = labels if isinstance(labels, list) else []
    paragraphs = [p.strip() for p in transcript.split("\n\n") if p.strip()]
    if not paragraphs:
        return None
    jobs = []
    for i, para in enumerate(paragraphs[:_MAX_INFERRED_JOBS]):
        tokens = _tokenize(para)
        job_type = _best_label(tokens, labels) or "general_activity"
        first_line = para.splitlines()[0] if para.splitlines() else para
        jobs.append({
            "agentic_job_id": _clamp_text(f"keyword_job_{i + 1}"),
            "job_name": _clamp_text(first_line[:60] or f"Job {i + 1}"),
            "job_type": job_type,
            "status": "SUCCESS",
        })
    return {"jobs": jobs}


def _keyword_classification_fixture(request: dict, config: dict) -> "dict | None":
    """A deterministic keyword-overlap classifier. No model, no network, no
    clock.

    Dispatches on request['kind']. Every other kind, and every malformed
    input (including a non-dict request or a non-dict config), returns
    None rather than raising -- the whole body runs inside one try/except,
    and any rejection is logged with %r on the request, never %s and never
    an f-string, because the request may carry model- or operator-derived
    text and a newline embedded in it must not be able to forge a second
    log record (the T-28-07 rule the rest of this plugin already follows).
    """
    try:
        if not isinstance(request, dict):
            logger.warning(
                "classification: keyword fixture rejected non-dict request: %r",
                request,
            )
            return None
        kind = request.get("kind")
        if kind == "task_type":
            return _keyword_task_type(request)
        if kind == "jobs":
            return _keyword_jobs(request)
        logger.warning(
            "classification: keyword fixture rejected unrecognised kind: %r",
            kind,
        )
        return None
    except Exception:
        logger.warning(
            "classification: keyword fixture raised internally, rejecting "
            "request: %r",
            request,
        )
        return None


# Registered at import time -- unlike cohort_impact.py and reporting.py,
# this boundary is not required to ship empty, and a shipped fixture is
# what makes the second implementation installable rather than
# hypothetical, the same reason evaluators.py's `stub` has stayed in the
# tree since Phase 36.
register(
    "keyword_classification_fixture",
    _keyword_classification_fixture,
    KEYWORD_FIXTURE_VERSION,
    evidence_class="ACTIVITY_MEASURED",
)
