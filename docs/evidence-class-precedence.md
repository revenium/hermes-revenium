# Evidence-class precedence and declaration authority

[← Back to the docs index](README.md)

This page owns two things Phase 48 (Reconciliation) produced: the resolved verdict on
whether a registration-time `evidence_class` declaration by trusted code is the same threat
model as untrusted model output (RECON-03), and the single cross-boundary precedence rule for
which `evidence_class` wins when the evaluator, valuation, and evidence boundaries each declare
one (RECON-04). It owns neither the nine evidence-class labels' own semantics nor the
assessment schema — those stay owned by
[`references/job-declaration.md`](../skills/revenium/references/job-declaration.md) and
[Claim distinctions and evidence boundaries](claim-distinctions-and-evidence-boundaries.md).
This page implements nothing: every claim below is a citation into code that exists today, and
the rule it states is a contract for a later phase to build, not a description of current
behaviour.

## Scope

The rest of this document is organized as: **The reconciliation verdict** (RECON-03's
re-derivation and correction), **The precedence rule** with its **Promotion safety** and
**Boundary cases** subsections (RECON-04, this plan), then two sections a later plan in this
phase adds — **Falsification conditions** (with `### Falsifier 1` through `### Falsifier 4`),
**The won't-fix trigger**, and an **Appendix: restatement-site sweep**. This document is paper
only: it changes no shipped runtime behaviour. Phase 50 is the phase that touches
`classifier.py`, `evaluators.py`, and `evidence.py` to build what is described here.

## The reconciliation verdict

**`classifier.py:1160`'s threat-model argument is the record that stands.
`docs/internal-milestones.md:110`'s EGV-02 deferral note is the record that is corrected.** A
registration-time declaration by trusted code MAY raise the recorded `evidence_class` above
`MODEL_ESTIMATED_DEMO`, because it is a different threat model from the untrusted model output
`_forced_evidence_class()` defends against — not, as the EGV-02 note argued, "the same
mechanism" reached from a different source.

### The call chain, re-derived from the code

`_declared_evidence_class(evaluator: str) -> str` (`classifier.py:1160`) is the whole of the
resolution path a caller reaches today. It is a four-step chain, one citation per step:

1. `_declared_evidence_class` (`classifier.py:1160`) — the entry point, taking exactly one
   parameter, the caller-supplied evaluator **name**.
2. `evaluators.resolve_evidence_class(name)` (`evaluators.py:130-134`) — delegates to the
   `output_assessment` boundary's own registry.
3. `BoundaryRegistry.resolve_evidence_class(name)` (`boundary_registry.py:169-176`) — looks the
   name up in `self._entries`, returning the `evidence_class` string a `register()` call
   declared at import time, or `""` if the name is not a key in that dict.
4. `evidence.resolve_declared_class(declared, allowed, default)` (`evidence.py:226-262`,
   called from `classifier.py:1218`) — the allow-list membership test: returns `declared` only
   when it is a non-empty string present in `allowed`, else `default`.

**No step in this chain can raise.** `evidence.resolve_declared_class`'s entire body runs
inside its own `try/except Exception: return default` (`evidence.py:212-226`).
`BoundaryRegistry.resolve_evidence_class` has no code path that raises at all — a non-string
`name` short-circuits to `""`, a missing entry falls through a dict `.get()` to `""`. And the
whole body of `_declared_evidence_class` itself — both nested import attempts, the call into
`evaluators.resolve_evidence_class`, and the call into `evidence.resolve_declared_class` — is
wrapped in one outer `try/except Exception: return _forced_evidence_class()`
(`classifier.py:1197-1220`). Every branch returns a string; nothing propagates past this
function.

### The structural guarantee, stated precisely

The guarantee is the **signature**, not a comment. `_forced_evidence_class()`
(`classifier.py:1141-1157`) takes zero parameters, so it structurally cannot read evaluator
output no matter how the read is spelled. `_declared_evidence_class(evaluator: str)`
(`classifier.py:1160`) takes exactly one parameter — the evaluator **name** — and no parameter
carrying evaluator **output**, so the same class of guarantee holds: there is no `raw` or
model-response variable in scope inside this function's body for it to read.

Two things would break it, and both must be named because a future rule site inherits this
same exposure: (1) widening the signature to accept a second parameter carrying evaluator
output — e.g. a `raw` argument — and (2) a caller passing a value **derived from** `raw` as the
`evaluator` argument itself. The second is call-site discipline, not something this function's
own signature can prevent; it is not a hypothetical Phase 48 can dismiss, because Phase 50's
rule site inherits it verbatim.

### The trust boundary, named exactly

Trust attaches to the registrant's own in-repo top-level `register(...)` call, made at import
time by code the operator installed — **not** to `config.json`'s `boundaries` object.
`_boundary_impl_name(key, default)` (`classifier.py:2854`) reads `config.json` to select
**which** already-registered implementation is active for a boundary; it never supplies a
class itself, and it cannot author one that was not already declared by a `register()` call in
the tree. An operator editing `config.json` can choose **among** declarations already written
in the repo. It cannot **write** one. This distinction is the load-bearing half of the
verdict and is stated here, not left implied: conflating "which registrant is selected" with
"what that registrant is trusted to declare" is exactly how the EGV-02 note's "same mechanism"
reasoning went wrong.

### The corrected register() inventory: nine, not six

Every `register(...)` call in the plugin tree that declares an `evidence_class` today, verified
against the current tree:

| # | file:line | Registrant name | Registry (boundary) | Declared `evidence_class` |
|---|-----------|------------------|----------------------|----------------------------|
| 1 | `evaluators.py:179` | `stub` | `output_assessment` (evaluators) | `_br.MASQUERADE_CLASS` (`MODEL_ESTIMATED_DEMO`) |
| 2 | `evaluators.py:222-226` | `system_of_record_assessment_fixture` | `output_assessment` | `OUTCOME_OBSERVED` |
| 3 | `classification.py:367-371` | `keyword_classification_fixture` | `classification` | `ACTIVITY_MEASURED` |
| 4 | `valuation.py:315-319` | `rate_card_valuation_fixture` | `valuation` | `CUSTOMER_CONFIGURED` |
| 5 | `evidence.py:320-324` | `confirmation_workflow_evidence_fixture` | `evidence` | `CUSTOMER_CONFIRMED` |
| 6 | `classifier.py:750-751` | `llm` | `output_assessment` (evaluators) | `_LLM_EVIDENCE_CLASS_LITERAL` (`MODEL_ESTIMATED_DEMO`) |
| 7 | `classifier.py:815-816` | `llm` | `classification` | `_LLM_EVIDENCE_CLASS_LITERAL` |
| 8 | `classifier.py:879-880` | `hours_times_rate` | `valuation` | `_LLM_EVIDENCE_CLASS_LITERAL` |
| 9 | `classifier.py:943-944` | `config_opt_in` | `evidence` | `_LLM_EVIDENCE_CLASS_LITERAL` |

Rows 6-9 are `classifier.py` registering the shipped built-ins into the four other boundaries'
registries at its own import time, all forced to `MODEL_ESTIMATED_DEMO`. This is a real
invariant worth stating: **the built-in default registrant for every one of these four
boundaries declares the same class the naked-LLM path already forces, so the built-in default
never conflicts with the forced constant.** A conflict can only arise once an operator
configures a *non*-default registrant for one of these boundaries. This table is listed for
accuracy at all nine rows; the count discrepancy with earlier notes (which said "six") is not
editorialized further here.

`reporting.py:78-81` and `cohort_impact.py:104-106` ship with **zero registrants** — no
`register()` call fires at either module's import time at all. This is a different case from a
registrant that declares a literal `""`: no fixture in this tree has ever registered anything
with an empty `evidence_class` string. It matters because a precedence rule's "absent
declaration" case has to handle "boundary has no entry to resolve" (`reporting`/`cohort_impact`
today) and "boundary's resolved entry declares `""`" (theoretical, unfixtured) as two distinct
shapes — see Boundary cases below.

### D-02's causal-label refusal does not exist in the tree today

`classifier.py:1218` passes the full nine-label `EVIDENCE_CLASSES` frozenset
(`classifier.py:1100-1108`) as `allowed` to `evidence.resolve_declared_class`. A trusted
registrant declaring `EXPERIMENTAL_IMPACT` would pass this membership test today, exactly as
any of the other eight labels would. It does not currently reach a persisted record only
because `_declared_evidence_class` resolves the `output_assessment` (evaluators) registry
alone and never consults `valuation`, `evidence`, `classification`, `cohort_impact`, or
`reporting`. The refusal of the three causal-impact labels for a trusted registrant is
therefore a narrowing of the `allowed` argument at this one existing call site, to be built by
Phase 50 — it must be described as a rule to be built, never as a guard that already holds.

### What Phase 43's promotion architecture proves, and what it does not

`tests/test_phase43_evidence_grading.py:416-479`'s `_hostile_evaluator_response()` layers eight
promotion attempts onto one evaluator response, and `_PROMOTION_FORBIDDEN_KEYS`
(`:484-493`) is the ast guard's forbidden-key set, statically scoped to the functions that
legitimately hold the untrusted `raw` response in scope. This proves the untrusted-model-output
half of the threat model: a model response cannot smuggle an `evidence_class` (or any of the
other ten forbidden keys) through `raw`, today or after any future edit the ast guard would
catch. It does **not** touch the trusted-registrant half — whether a `register()` call, not a
model response, can reach a causal-impact class — because that is a different threat model
entirely, one this document's verdict is about.

**True today:** a registration-time declaration by trusted code is structurally unable to read
evaluator output, by the same class of parameterless/name-only guarantee `_forced_evidence_class()`
provides, and Phase 43's promotion architecture closes the separate untrusted-input path this
guarantee does not need to close. **Not true today:** a configured boundary's own declared
class does not yet reach the persisted record — `_declared_evidence_class` resolves the
evaluators registry only — so this correction changes no observable behaviour by itself
(Phase 45, D-06 AMENDED; Phase 43, EGV-13).
