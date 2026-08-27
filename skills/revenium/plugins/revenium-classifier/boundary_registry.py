"""boundary_registry.py — the one shared registry primitive every boundary
in Phase 45 (Pluggable Boundaries) stands on.

Phase 45 (D-01, D-04): all six boundaries in this phase — output/outcome
assessment, classification, economic valuation, evidence resolution and
reportability, cohort impact, and Revenium reporting — expose the SAME
register()/resolve() shape, so there is one pattern to learn and EGV-02's
"fits without masquerading" proof is identical at every boundary. Rather
than hand-copy a registry six times, this module is the ONE primitive every
boundary module (evaluators.py included, per its Phase 45 migration)
instantiates with its own `boundary` name.

THE CONTRACT
------------
`BoundaryRegistry(boundary)` is a named collection of registrants. Each
registrant is added with:

    register(name: str, fn, version: str = "", evidence_class: str = "") -> None

  name           the registrant's identifier, unique within THIS registry.
                 Last registration wins.
  fn             the callable implementing the boundary's contract. This
                 module never calls it -- resolution and invocation are the
                 caller's job.
  version        the identity the registrant declares for itself, exactly
                 as evaluators.py's own register() already does for the
                 `llm`/`stub` evaluators.
  evidence_class one of classifier.EVIDENCE_CLASSES' nine labels (or ""),
                 declared HERE, at registration time, by TRUSTED CODE --
                 the module-level `register(...)` call a boundary module
                 makes at import time. This is a DIFFERENT threat model
                 from the one classifier._forced_evidence_class() defends:
                 _forced_evidence_class() takes no parameter and therefore
                 structurally cannot read UNTRUSTED evaluator OUTPUT, no
                 matter how the read is spelled. A registration-time
                 declaration never touches evaluator output either -- it is
                 written once, by the same in-repo code that defines `fn`,
                 before any evaluator has run even once. Neither pattern
                 subsumes the other; they cover two different moments
                 (import time vs. call time) against two different
                 adversaries (a hostile evaluator response vs. an
                 uncontrolled call site). See D-06 AMENDED (45-CONTEXT.md).

`resolve(name) -> callable | None`, `resolve_version(name) -> str`, and
`resolve_evidence_class(name) -> str` look a registrant up by name. A
non-str name, or a name never registered, resolves to None/""/"" rather
than raising -- the same `isinstance` guard evaluators.py's original
`resolve`/`resolve_version` already applied.

`registered() -> list[str]` returns every registered name, sorted, for
diagnostics (mirrors evaluators.py's `registered()`, ROI-14).

Per-registrant metadata (version, evidence_class) is ALWAYS declared where
the implementation registers, never resolved at the call site by comparing
the registrant's name. evaluators.py's own `register()` docstring already
argues this for `version`: an earlier draft resolved it with
`LLM_EVALUATOR_VERSION if name == "llm" else ""`, which silently dropped
the version of every other evaluator, including the stub, which declares
one. That Greptile P1 is precisely the coupling this seam exists to
prevent, and it applies just as much to `evidence_class` -- a future ONNX,
deterministic-policy, vertical, or system-of-record implementation must be
able to report its OWN version and its OWN evidence class without the
caller knowing its name.

ABSTENTION IS NOT AN ERROR. A `None` from `resolve` means "no such
registrant" -- a configuration error the caller reports. It is NOT the
same thing as a registered implementation choosing to abstain by returning
None from its OWN call; that decision belongs to the registrant, this
module never makes it.

WHAT THIS IS NOT. There is no discovery mechanism, no entry points, and no
plugin packages here -- Phase 36's decision stands, restated for all six
boundaries this phase adds. Registration is explicit: a boundary module's
own top-level `register(...)` call, at import time, exactly like
evaluators.py's `register("stub", _stub_evaluate, STUB_VERSION)`.

DEPENDENCY DIRECTION. This module must not import classifier.py, and must
stay importable with no Hermes venv present -- the same constraint that
keeps `call_llm` behind a lazy import throughout classifier.py. Per D-09:
host data crosses a contract boundary as plain data only -- dicts,
strings, numbers -- never a `Path`, a sqlite3 connection, or a file
handle. No test enforces that second half (45-CONTEXT.md's documented
gap), so this module obeys the rule by example: nothing here accepts or
returns anything but plain data and callables supplied by the caller.

REVERSIBILITY WARNING (D-04, D-06 AMENDED). This helper becomes a
load-bearing shared dependency the moment a second boundary module
instantiates it, and its four-argument `register()` signature is shared by
all six registries. Changing that signature later touches every
registration site and every fixture across the whole phase -- treat it as
settled once `evaluators.py`'s migration (Phase 45 Plan 01) proves it
against a 452-line test suite that may not be edited.
"""

import logging

logger = logging.getLogger("revenium_classifier.boundary_registry")

# Duplicated from classifier.EVIDENCE_CLASS_MODEL_ESTIMATED (classifier.py:859),
# not imported -- see DEPENDENCY DIRECTION above, and impact_study.py's own
# precedent for why a one-way dependency rule requires this kind of small,
# deliberate duplication rather than an import. The two constants are pinned
# equal by tests/test_phase45_boundary_registry.py's SeamMigrationTests via
# `resolve_evidence_class("stub")`, so drift between the two copies is
# caught, not merely hoped against.
MASQUERADE_CLASS = "MODEL_ESTIMATED_DEMO"


class BoundaryRegistry:
    """A named collection of registrants for ONE boundary.

    Two registries never see each other, even when a registrant name is
    reused across them: `BoundaryRegistry("a").register("shared", f1)` and
    `BoundaryRegistry("b").register("shared", f2)` each resolve "shared" to
    their own callable, because each instance owns its own `_entries` dict.
    """

    def __init__(self, boundary: str) -> None:
        self.boundary = str(boundary or "")
        # name -> {"fn": callable, "version": str, "evidence_class": str}
        self._entries: dict = {}

    def register(self, name: str, fn, version: str = "", evidence_class: str = "") -> None:
        """Register `fn` under `name`, with the version and evidence_class
        IT declares.

        Per-registrant metadata is declared HERE, where the implementation
        registers, never resolved at the call site by comparing the
        registrant's name -- see this module's docstring for the Greptile
        P1 this generalizes from evaluators.py's own `version` handling to
        `evidence_class` as well: an earlier draft resolved a per-registrant
        value with `SOME_VALUE if name == "llm" else ""`, which silently
        dropped every other registrant's own declared value. A future
        ONNX, deterministic-policy, vertical, or system-of-record
        implementation must be able to report its own identity and its own
        evidence class without this registry -- or the classifier that
        calls it -- knowing its name.

        Last registration wins: registering the same name twice replaces
        the entry, and `registered()` still holds exactly one copy of that
        name.
        """
        self._entries[name] = {
            "fn": fn,
            "version": str(version or ""),
            "evidence_class": str(evidence_class or ""),
        }

    def resolve(self, name: str):
        """Return the callable registered as `name`, or None.

        None means "no such registrant" and is a configuration error the
        caller reports; it is NOT the same as a registrant abstaining.
        """
        if not isinstance(name, str):
            return None
        entry = self._entries.get(name)
        return entry["fn"] if entry else None

    def resolve_version(self, name: str) -> str:
        """The version the named registrant declared, or "" if unknown."""
        if not isinstance(name, str):
            return ""
        entry = self._entries.get(name)
        return entry["version"] if entry else ""

    def resolve_evidence_class(self, name: str) -> str:
        """The evidence_class the named registrant declared AT REGISTRATION
        TIME, or "" if unknown -- a trusted-code declaration, never a value
        read from the registrant's own output."""
        if not isinstance(name, str):
            return ""
        entry = self._entries.get(name)
        return entry["evidence_class"] if entry else ""

    def registered(self) -> list:
        """Names of every registered registrant, sorted. For diagnostics."""
        return sorted(self._entries)


def is_masquerading(registry: "BoundaryRegistry", name: str) -> bool:
    """True exactly when `name`'s declared evidence_class equals
    MASQUERADE_CLASS -- the executable form of D-06's "must never
    masquerade as MODEL_ESTIMATED_DEMO" rule, so a future fixture that
    dishonestly claims the forced-LLM label can be caught rather than
    trusted on the strength of a docstring alone.

    False for an unregistered name and for any other label, including an
    empty declaration. Never raises: any internal failure is logged with
    %r on `name` -- never %s and never an f-string, because a registrant
    name can be operator- or caller-supplied and a newline embedded in it
    must not be able to forge a second log record (the T-28-07 rule
    evaluators.py and classifier.py both already follow).
    """
    try:
        return registry.resolve_evidence_class(name) == MASQUERADE_CLASS
    except Exception:
        logger.warning(
            "boundary_registry: is_masquerading() raised internally for name: %r",
            name,
        )
        return False
