"""reporting.py — the Revenium reporting boundary (EGV-01).

Phase 45 (D-02 AMENDED): kept as its own module, for the same reason every
other boundary in this phase is — the boundary is a FILE boundary, not
merely a naming convention. This is the one boundary CONTEXT and RESEARCH
agree has no runnable Python↔bash bridge to stand behind: read the WHAT
THIS IS NOT section below before assuming a live adapter exists, because
it does not.

THE CONTRACT
------------
A reporter is any callable with this signature:

    report(record: dict, cfg: dict) -> list | None

  record  one JobAssessment sidecar record as plain data (the same shape
          _build_job_assessment in classifier.py constructs and
          hermes-report.sh re-reads off disk).
  cfg     the operator's settings object. Every key is absent-able.

  returns the argv a conformant reporter would invoke the Revenium CLI
          with -- a flat list of strings, verb first -- or None to DECLINE
          to report this record.

ABSTENTION IS NOT AN ERROR. Declining to report is a correct outcome, not a
failure, for the same reason every other boundary's abstention is: a
record with no usable job id has nothing to report, and a caller that
retries or logs an error on that path is treating a normal case as a bug.

WHAT THIS IS NOT. There is NO live adapter, and nothing in the shipped
skill calls through this module at runtime -- state that plainly, because
it is the one property this boundary must not be allowed to blur. The
production reporter is `skills/revenium/scripts/hermes-report.sh`, a
single `main()` spanning roughly lines 742-3957 with no per-record
function seam; extracting one out of the billing hot path was explicitly
rejected as scope this phase cannot absorb (D-02 AMENDED). This module
states what ANY reporter must emit for a record; the conformance proof is
a test asserting that a SECOND reporter, written blind against only this
docstring and the golden's own declared field set (never against
hermes-report.sh's source), produces argv the existing pinned
`jobs-outcome.golden.json` wire shape already accepts (D-07). Moving argv
construction into Python is a recorded Deferred Idea for a later phase,
not this one.

DEPENDENCY DIRECTION. This module must not import classifier.py, must stay
importable with no Hermes venv present, and host data crosses this
boundary as plain data only -- dicts, strings, numbers -- never a `Path`,
a sqlite3 connection, or a file handle (D-09; no test enforces this half,
so this module obeys the rule by example, per every other boundary in
this phase).
"""

from __future__ import annotations

import json
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

logger = logging.getLogger("revenium_classifier.reporting")

# Phase 45 (D-02 AMENDED/D-04): the shared BoundaryRegistry primitive,
# instantiated for this boundary's own name. Ships with ZERO registrants --
# nothing below calls register() at import time.
_REGISTRY = _br.BoundaryRegistry("reporting")


def register(name: str, fn, version: str = "", evidence_class: str = "") -> None:
    """Register a reporter under `name`, with the version and evidence_class
    IT declares.

    D-07: this boundary has no evidence_class of its own -- the property
    that actually matters here is byte-identical argv, not a claim label --
    so a reporter registering here typically declares evidence_class="".
    The parameter still exists, for the same reason every boundary's
    register() keeps the same four-argument shape (D-04, D-06 AMENDED):
    one pattern to learn across all six boundaries.

    Last registration wins.
    """
    _REGISTRY.register(name, fn, version, evidence_class)


def resolve(name: str):
    """Return the reporter registered as `name`, or None.

    None means "no such registrant" and is a configuration error the
    caller reports; it is NOT the same as a reporter declining to report a
    given record.
    """
    return _REGISTRY.resolve(name)


def resolve_version(name: str) -> str:
    """The version the named reporter declared, or "" if unknown."""
    return _REGISTRY.resolve_version(name)


def resolve_evidence_class(name: str) -> str:
    """The evidence class the named reporter DECLARED at registration, or
    "" if unknown. Almost always "" for this boundary -- see register()'s
    own docstring for why."""
    return _REGISTRY.resolve_evidence_class(name)


def registered() -> list:
    """Names of every registered reporter, sorted. For diagnostics.

    Ships as [] in the shipped state -- nothing registers at import time
    in this module.
    """
    return _REGISTRY.registered()


# --- shared duplicated helper --------------------------------------------
#
# Duplicated from impact_study.py's own _clamp_text (itself duplicated
# from classifier.py), not imported -- see the module docstring's
# DEPENDENCY DIRECTION paragraph. The duplication is deliberate and
# required by the dependency rule, not an oversight.

NARRATIVE_CLAMP_BYTES = 500


def _clamp_text(value, limit: int = NARRATIVE_CLAMP_BYTES) -> str:
    """Coerce to str and clamp to `limit` SERIALIZED BYTES -- not
    characters. json.dumps handles the escaping/quoting for the narrative
    values that enter --metadata below, so this helper's own length check
    reuses the same module already imported for that -- unlike
    cohort_impact.py's sibling helper, which hand-rolls the byte count to
    avoid importing json at all, this module already needs json for
    --metadata and gains nothing by avoiding it here too.
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


# --- _argv_conformance_reporting_fixture ---------------------------------
#
# Phase 45 (EGV-02, D-05, D-07): the second reporter, written ONLY against
# THE CONTRACT above and the golden's own declared field set
# (tests/fixtures/compat/jobs-outcome.golden.json) -- it does NOT read
# hermes-report.sh, because a second implementer reading the bash script
# is not the thing D-07's conformance proof exists to demonstrate. It is
# deliberately NOT registered at import time; the test registers it.
#
# Forbidden flags, per the golden's own forbidden_fields list: --budget-id
# and --alert-id are the pre-guardrails spellings this milestone broke
# with (Phase 19's clean break -- see CLAUDE.md's "Legacy naming guards").
# This fixture never emits either, whatever the record contains.

REPORTING_FIXTURE_VERSION = "1"

_FORBIDDEN_FLAGS = ("--budget-id", "--alert-id")


def _argv_conformance_reporting_fixture(record: dict, cfg: dict) -> "list | None":
    """Build the `revenium jobs outcome` argv for one JobAssessment record.

    Declines -- returns None, never raises -- for a non-dict record, an
    empty record, or a record with no usable job id. Any rejection is
    logged with %r on the record -- never %s and never an f-string,
    because a sidecar record's narrative fields may be operator- or
    model-derived text, and a newline inside one must not be able to forge
    a second log record (the T-28-07 rule every boundary module in this
    phase follows).
    """
    if not isinstance(record, dict) or not record:
        logger.warning(
            "reporting: fixture declined non-dict or empty record: %r", record
        )
        return None

    job_id = record.get("agentic_job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        logger.warning(
            "reporting: fixture declined record with no usable job id: %r",
            record,
        )
        return None
    job_id = job_id.strip()

    status = record.get("execution_status")
    status = status.strip().upper() if isinstance(status, str) else ""

    # Verb first, no program name -- matches THE CONTRACT above and the
    # golden's own captured shape (tests/_compat_helpers.py's no-shift shim
    # captures argv starting at the verb token, never argv[0]).
    argv = ["jobs", "outcome", job_id]
    if status:
        argv += ["--result", status]
    argv += ["--quiet"]

    # A SUCCESS execution maps to a CONVERTED business outcome, mirroring
    # hermes-report.sh's own --result/--outcome-type split (a business
    # outcome is a separate axis from an execution result) -- arrived at
    # independently from THE CONTRACT and the golden's declared fields,
    # not by reading the bash script.
    if status == "SUCCESS":
        argv += ["--outcome-type", "CONVERTED"]

    meta: dict = {}
    source = record.get("source")
    if isinstance(source, str) and source.strip():
        meta["source"] = _clamp_text(source.strip(), 64)
    failure_reason = record.get("failure_reason")
    if status == "FAILED" and isinstance(failure_reason, str) and failure_reason.strip():
        meta["failure_reason"] = _clamp_text(failure_reason.strip())

    if meta:
        argv += [
            "--metadata",
            json.dumps(meta, sort_keys=True, separators=(",", ":")),
        ]

    # _FORBIDDEN_FLAGS are never appended by any branch above -- no
    # construction path in this function can emit either one, so nothing
    # further to strip here. Named explicitly so a future edit that starts
    # forwarding an operator-supplied flag notices this comment before it
    # reintroduces one of Phase 19's retired spellings.
    return argv
