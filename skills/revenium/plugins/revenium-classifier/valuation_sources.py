"""valuation_sources.py — the valuation SOURCE boundary (SSE-04, D-01).

Phase 59: the fetch layer `valuation.py` structurally cannot host. That
module's own contract requires every registrant to be synchronous and
requires host data to cross its boundary as plain data only -- a dict,
a string, a number, never a `Path`, a sqlite3 connection, or a file
handle. A value drawn from the server's `economics` / `baselines`
surfaces must be FETCHED before it can become plain data, and fetching
is I/O -- exactly what a valuation registrant is forbidden to do. This
module exists so that permission has a home separate from the registry
it feeds.

THE CONTRACT
------------
A valuation source is any callable with this signature:

    fetch(config: dict) -> dict | None

  config   the SAME `llmOutcomeEvaluation` object every other boundary in
           this plugin already threads through (evaluators.py,
           valuation.py, classification.py, evidence.py all share this
           object). Every key is absent-able.

  returns  a plain dict of figures, or None to supply nothing. `None` is
           NOT an error -- exactly as valuation.py's own "ABSTENTION IS
           NOT AN ERROR" rule reads one layer down. A source that has
           nothing to fetch, or fetched something unusable, returns None
           and the caller (classifier._resolve_valuation_source_figures)
           falls back to no `source_figures` at all.

WHAT IS PERMITTED HERE THAT IS NOT PERMITTED IN A REGISTRANT. A source MAY
read a file, and a future source MAY call out to a CLI or the network.
That is the entire reason this module exists as a separate file rather
than as another `valuation.py` registrant: valuation.py's own module
docstring states an implementation "MUST be synchronous" and that host
data crosses its boundary "as plain data only ... never a Path, a
sqlite3 connection, or a file handle" -- this module is where that I/O
is permitted to happen, so that rule in valuation.py never has to bend.

NEVER RAISES. A source is called from `classifier._validate_assessment`'s
own assessment-derivation path, which itself must never raise (see
classifier.py's own top-level invariant). A source's failure must cost
the call its figures, never the assessment. Every source wraps its own
body in try/except and returns None on any exception.

DEPENDENCY DIRECTION. This module must not import classifier.py, for the
same reason valuation.py must not: the dependency runs one way so this
module stays importable where Hermes' venv is absent -- proven by
loading it from its own file path with no package parent, exactly as
valuation.py already is. Consequently this module duplicates its own
`_clamp_text` and `_finite_number` rather than importing either of
valuation.py's copies (which would itself require importing valuation.py,
widening this module's own dependency surface for no gain) or
classifier.py's originals (forbidden outright) -- the duplication is
deliberate and required by the dependency rule, not an oversight, exactly
as valuation.py's own module docstring already argues for its copies.

WHAT THIS IS NOT. Not a discovery mechanism, no entry points, no plugin
packages -- Phase 36's decision restated for a third boundary file. And,
explicitly: this module does NOT decide provenance. D-02 (59-CONTEXT.md)
settled that `boundaries.valuation` plus `valuation.resolve_evidence_class
(name)` already answer where a value came from; nothing here records a
source's identity into any field a caller persists.

The provenance-adjacent server fields Phase 58's D-12 NAMED but
deliberately did not map -- `declaredBy`, `evidenceUrl`, `recordedBy`,
`source`, `reason` -- exist, and this seam must know they exist. This
module does not decide them; see docs/provenance-mapping.md. Naming them
here is not mapping them.
"""

from __future__ import annotations

import json
import logging
import math

try:  # packaged: Hermes imports the plugin as a package
    from . import boundary_registry as _br
except ImportError:  # pragma: no cover - plugin dir on sys.path
    try:
        import boundary_registry as _br  # type: ignore
    except ImportError:
        # Loaded by file path with no package parent and no sys.path entry --
        # exactly what tests/test_phase36_evaluator_seam.py's
        # _load_evaluators() and valuation.py's own equivalent fallback do.
        # Deliberately avoids os and pathlib: this module is under the same
        # import guard valuation.py documents above its own copy of this
        # dance.
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            "revenium_boundary_registry",
            __file__.rsplit("/", 1)[0] + "/boundary_registry.py",
        )
        _br = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_br)

logger = logging.getLogger("revenium_classifier.valuation_sources")

# Phase 59 (D-01, D-04): the shared BoundaryRegistry primitive, instantiated
# under its own boundary name -- "valuation_source", distinct from
# valuation.py's "valuation" -- so the two registries never collide. Like
# valuation.py and classification.py, this registry does NOT ship empty:
# `baselines_file_source` below is registered at import time, because a
# second, real implementation is what makes this boundary provably
# pluggable rather than hypothetical.
_REGISTRY = _br.BoundaryRegistry("valuation_source")


def register(name: str, fn, version: str = "") -> None:
    """Register a valuation source under `name`, with the version it
    declares for itself.

    Deliberately narrower than valuation.py's own register(): a source has
    no `evidence_class` and no `economic_mechanisms` parameter, because a
    source supplies figures, and the evidence class describing a derived
    value stays the REGISTRANT's declaration (valuation.py), per D-02.

    Last registration wins, same as every other BoundaryRegistry-backed
    boundary in this plugin.
    """
    _REGISTRY.register(name, fn, version)


def resolve(name: str):
    """Return the valuation source registered as `name`, or None.

    None means "no such registrant" and is a configuration error the
    caller reports (as "no source configured or resolvable"); it is NOT
    the same as a source abstaining by returning None from a call.
    """
    return _REGISTRY.resolve(name)


def resolve_version(name: str) -> str:
    """The version the named source declared, or "" if unknown."""
    return _REGISTRY.resolve_version(name)


def registered() -> list:
    """Names of every registered valuation source, sorted. For
    diagnostics, and for RegistryRoundTripTests's iteration."""
    return _REGISTRY.registered()


# --- shared duplicated helpers --------------------------------------------
#
# Duplicated from valuation.py's own _clamp_text/_finite_number (themselves
# duplicated from classifier.py's originals), not imported -- see the
# module docstring's DEPENDENCY DIRECTION paragraph. The duplication is
# deliberate and required by the dependency rule, not an oversight.

NARRATIVE_CLAMP_BYTES = 500


def _clamp_text(value, limit: int = NARRATIVE_CLAMP_BYTES) -> str:
    """Coerce to str and clamp to `limit` SERIALIZED BYTES -- not
    characters.

    Duplicated from valuation._clamp_text (itself duplicated from
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

    Duplicated from valuation._finite_number (itself duplicated from
    classifier._finite_number), not imported -- see DEPENDENCY DIRECTION
    above. bool is rejected explicitly because isinstance(True, int) is
    True in Python, so a plain isinstance check would silently accept True
    as the number 1. NaN and infinity are rejected explicitly too: a bare
    `value > 0` comparison is FALSE for NaN, so NaN slips through any
    naive lower-bound guard and lands in a monetary field.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    if math.isnan(f) or math.isinf(f):
        return None
    return f


# --- _baselines_file_source ------------------------------------------------
#
# Phase 59 (D-01, D-06): the one shipped source, shaped after the server's
# `baselines` surface -- hourlyRate / minutesPerUnit / provenance -- per
# D-06's choice of that surface over `economics` as the closest analogue to
# what local valuation already does (hours times rate), so a later swap to
# a real server-backed source is like-for-like.

MAX_SOURCE_DOCUMENT_BYTES = 65536  # a source reading an operator-named path
# must not be able to pull an unbounded file into memory on the assessment
# derivation path.

BASELINES_FILE_SOURCE_VERSION = "1"


def _baselines_file_source(config: dict) -> "dict | None":
    """Read a `baselines`-shaped JSON document from the operator-named
    path `config["valuationSourceFixturePath"]` and return its figures.

    Returns None, and never raises, for every one of these shapes: a
    non-dict `config`; an absent, empty, or non-string
    `valuationSourceFixturePath`; a path that does not exist or cannot be
    opened; a document exceeding MAX_SOURCE_DOCUMENT_BYTES; bytes that do
    not parse as JSON; a top level that is not a dict; a missing,
    non-finite, or non-positive `hourlyRate`; a missing, non-finite, or
    non-positive `minutesPerUnit`.

    `provenance` is read through `_clamp_text` and clamps to the empty
    string on anything unusable rather than failing the fetch --
    `provenance` is descriptive, not load-bearing arithmetic, unlike the
    two numeric fields above.

    On success, returns `{"hourlyRate": <float>, "minutesPerUnit": <float>,
    "provenance": <str>, "source": "baselines_file_source"}`.

    The whole body runs inside one try/except returning None, logging at
    logger.warning with a lazy %r on the exception -- never the document's
    contents, matching this package's redaction-safe logging convention
    (T-28-07 / T-54-02's own reasoning applied here).
    """
    try:
        if not isinstance(config, dict):
            return None

        path = config.get("valuationSourceFixturePath")
        if not isinstance(path, str) or not path:
            return None

        with open(path, "rb") as fh:
            raw = fh.read(MAX_SOURCE_DOCUMENT_BYTES + 1)
        if len(raw) > MAX_SOURCE_DOCUMENT_BYTES:
            logger.warning(
                "valuation_sources: baselines file source rejected an "
                "over-sized document at %r", path,
            )
            return None

        document = json.loads(raw)
        if not isinstance(document, dict):
            return None

        hourly_rate = _finite_number(document.get("hourlyRate"))
        minutes_per_unit = _finite_number(document.get("minutesPerUnit"))
        if hourly_rate is None or hourly_rate <= 0:
            return None
        if minutes_per_unit is None or minutes_per_unit <= 0:
            return None

        provenance = _clamp_text(document.get("provenance"), NARRATIVE_CLAMP_BYTES)

        return {
            "hourlyRate": hourly_rate,
            "minutesPerUnit": minutes_per_unit,
            "provenance": provenance,
            "source": "baselines_file_source",
        }
    except Exception as exc:  # noqa: BLE001 - never raise on this path
        logger.warning(
            "valuation_sources: baselines file source raised: %r", exc,
        )
        return None


# Registered at import time -- like valuation.py and classification.py,
# this registry does not ship empty, because a second real implementation
# is what makes a boundary provably pluggable rather than hypothetical.
register("baselines_file_source", _baselines_file_source, BASELINES_FILE_SOURCE_VERSION)
