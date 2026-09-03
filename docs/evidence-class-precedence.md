# Evidence-class precedence and declaration authority

[← Back to the docs index](README.md)

This page records two Phase 48 (Reconciliation) results: the verdict on
whether a registration-time `evidence_class` declaration by trusted code is the same threat
model as untrusted model output (RECON-03), and the single cross-boundary precedence rule for
which `evidence_class` wins when the evaluator, valuation, and evidence boundaries each declare
one (RECON-04). It owns neither the nine evidence-class labels' own semantics nor the
assessment schema — those stay owned by
[`references/job-declaration.md`](../skills/revenium/references/job-declaration.md) and
[Claim distinctions and evidence boundaries](claim-distinctions-and-evidence-boundaries.md).
This page implements nothing. Its claims cite existing code, and its rule is a contract for a
later phase rather than a description of current behaviour.

## Scope

The document covers RECON-03's reconciliation verdict and correction, RECON-04's precedence
rule, promotion safety, boundary cases, four falsification conditions, the won't-fix trigger,
and a restatement-site appendix. It changes no shipped runtime behaviour. Phase 50 implements
the design in `classifier.py`, `evaluators.py`, and `evidence.py`.

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

No step in this chain can raise. `evidence.resolve_declared_class`'s entire body runs
inside its own `try/except Exception: return default` (`evidence.py:250-263`).
`BoundaryRegistry.resolve_evidence_class` has no code path that raises at all — a non-string
`name` short-circuits to `""`, a missing entry falls through a dict `.get()` to `""`. And the
whole body of `_declared_evidence_class` itself — both nested import attempts, the call into
`evaluators.resolve_evidence_class`, and the call into `evidence.resolve_declared_class` — is
wrapped in one outer `try/except Exception: return _forced_evidence_class()`
(`classifier.py:1197-1220`). Every branch returns a string; nothing propagates past this
function.

### The structural guarantee, stated precisely

The signature provides the guarantee. `_forced_evidence_class()`
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
time by code the operator installed, not to `config.json`'s `boundaries` object.
`_boundary_impl_name(key, default)` (`classifier.py:2860`) reads `config.json` to select
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

## The precedence rule

**Chosen shape: fixed boundary priority, `evidence` > `valuation` > `evaluator`.** When more
than one of the three boundaries has an active, non-empty declared `evidence_class` for a given
assessment, the rule walks the boundaries in that fixed order and returns the first non-empty
declaration it finds. If none of the three has a non-empty declaration, the rule returns
`_forced_evidence_class()`, unchanged from today. A Phase 50 implementer can build directly from
this paragraph without re-deriving anything.

### Amendment (2026-08-30, Phase 50 Task 1 checkpoint "option-b"): the walk widens to four legs, and a vote must be non-forced, not merely non-empty

**This paragraph amends, and does not replace, the rule stated immediately above.** The original
text is Phase 48's own record and is left in place; this dated block is the correction Phase 50's
Task 1 checkpoint produced against it, per the same append-only discipline this document already
uses elsewhere (see `## Appendix: restatement-site sweep`, D-10). Phase 48 itself said its four
named falsifiers "are not a claim that no fifth exists" (`:339-340` above) — the two facts below
are that fifth consideration, discovered while building, not while falsifying.

**Fact 1 — the built-in default registrant would win on every install under a literal
"first-non-empty" reading.** `classifier.py:943-944` registers the evidence boundary's fail-open
default registrant, `config_opt_in`, with `evidence_class=_LLM_EVIDENCE_CLASS_LITERAL`
(`MODEL_ESTIMATED_DEMO`) — a non-empty string. A walk that stops at the first *non-empty*
declaration, exactly as originally written above, would therefore stop at the `evidence` boundary
on 100% of installs, because its built-in default always has something non-empty to say. Neither
`CUSTOMER_CONFIGURED` (declared on `valuation`) nor `OUTCOME_OBSERVED` (declared on the evaluator)
could ever reach a record, regardless of configuration — the walk's own default arm would mask
every lower-priority boundary unconditionally.

**Fact 2 — `ACTIVITY_MEASURED` is declared on a boundary the three-boundary rule never
consults.** `ACTIVITY_MEASURED` is declared in exactly one place in the tree,
`classification.py:367-371`'s `keyword_classification_fixture`, on the **`classification`**
boundary. The rule as originally written above walks only `evidence`, `valuation`, and
`evaluator` — `classification` is not one of the three named boundaries, so this class was
structurally unreachable no matter how `classification` was configured. DECL-04 requires all four
fixture-declared classes to reach the record; under the original three-boundary text, one of the
four could not.

**The refined rule, stated as one paragraph an implementer can build from.** Walk four boundaries
in the fixed order `evidence > valuation > classification > evaluator`. A boundary's declaration
"counts as a vote" only when it is a non-empty string **and** is not equal to
`EVIDENCE_CLASS_MODEL_ESTIMATED` — the forced constant carries no information distinguishing "this
boundary deliberately declared the demo class" from "this boundary cast no vote at all," so
treating it as a vote is indistinguishable from Fact 1's masking failure. The first boundary in
that order whose declaration counts as a vote wins outright; no later boundary is consulted once
one has won. When no boundary casts a vote, the rule returns `_forced_evidence_class()` with
authority `evaluator`, unchanged from today's behaviour. The winning declaration still passes
through the existing allow-list membership test (see "The causal-label refusal" below) before it
is accepted.

**Consequence for DECL-04 and ROADMAP criterion 1.** All four fixture-declared classes
(`CUSTOMER_CONFIRMED`, `CUSTOMER_CONFIGURED`, `ACTIVITY_MEASURED`, `OUTCOME_OBSERVED`) are reachable
under the refined rule — proven by `tests/test_phase45_boundary_fixtures.py::FixtureMatrixTests`'
reachability matrix (plan 50-03). DECL-04 closes in **full**. ROADMAP Phase 50 success criterion 1
is **met**, not superseded or narrowed — there is no supersession line to write for it.

### Why the other two candidates were rejected

**Weakest-declared floor** (`MODEL_ESTIMATED_DEMO` as an absolute floor, with a separate
selection rule above it) is not a complete rule on its own. It answers "is the declaration the
forced constant or not," but says nothing about which of two *different*, non-forced
declarations wins — the shape RESEARCH.md §4 shows the registrant set already produces today
(e.g. `valuation.py:315-319` declares `CUSTOMER_CONFIGURED`, `evidence.py:320-324` declares
`CUSTOMER_CONFIRMED`; both are non-forced and different). Answering that case requires pairing
the floor with a secondary tiebreak, which collapses the candidate into fixed boundary priority
anyway — so it is not a separate shape, it is this shape with an extra step.

**Per-aspect authority** (each field family owned by its own boundary, no cross-boundary
override) most closely matches the code's *existing* shape — `evidence_class` is already
effectively owned by whichever single registry `_declared_evidence_class` resolves (today, only
`evaluators`), the same way `estimated_value` is independently owned by the valuation boundary
(`classifier.py:1467`) and `reportability_status` by the evidence boundary
(`classifier.py:2017`). But taken literally for `evidence_class` specifically, it does not
answer RECON-04's stated question at all: if `evidence_class` stays singularly owned by one
registry, there is no genuine three-way conflict for it to resolve, and D-03's "conflicting
declarations in the same assessment" scenario has nothing to apply to. Per-aspect authority
sidesteps RECON-04 rather than answering it.

### One rule site, not one record site

**DECL-02's "exactly one call site" means one *rule* site, not one *record* site.** There are
two places a record is written — `_validate_assessment`'s return dict at `classifier.py:1553`
and `_build_job_assessment`'s record literal at `classifier.py:2389` — and both already call
`_declared_evidence_class(evaluator)` today. This is existing, favorable structure that Phase 50
must not throw away: siting the priority-walk logic inside that one function reaches both
records without duplicating the walk. Whichever shape were chosen, this structural fact would
hold; it happens to make fixed boundary priority easy to implement without violating DECL-02.

### The causal-label refusal (D-02), carried into this rule

The three causal-impact labels — `ASSOCIATIONAL`, `QUASI_EXPERIMENTAL_IMPACT`, and
`EXPERIMENTAL_IMPACT` — are refused at the allow-list even when a trusted registrant declares
one, while `ACTIVITY_MEASURED`, `OUTCOME_OBSERVED`, `CUSTOMER_CONFIGURED`, `CUSTOMER_CONFIRMED`,
`OUTPUT_OBSERVED`, and `MODEL_ESTIMATED_DEMO` stay declarable. The exact insertion point for
this refusal is the `allowed` argument at `classifier.py:1218`, narrowed from the full
`EVIDENCE_CLASSES` frozenset, inside the existing `evidence.resolve_declared_class(declared,
allowed, default)` call (`evidence.py:226`) — not a new gate, a narrower argument to the one
that exists. The rationale: a config-installed boundary must not be able to mark an individual
record with a causal-impact label when no experiment backs it — the boundary between a cohort
estimate and an individually-observed one (EGV-13).

### Conflicting declarations, recorded (D-03)

When two active boundaries declare **different**, non-empty classes for the same assessment,
the rule picks one by the fixed order above, and the persisted record notes both that a
conflict occurred and which authority (boundary) won. This costs one additional field in the
record. A silent pick was rejected: without it, an auditor could not distinguish "exactly one
boundary declared a class" from "two boundaries disagreed and one was chosen over the other."
Recording both facts satisfies DECL-04 (determinism, provable by test) and DECL-05 (an auditor
can tell which authority applied) with one mechanism rather than two.

**Amendment (2026-08-30) — the mechanism is one key naming the winner, not a separate conflict
flag.** What shipped is `evidence_class_authority`, a string field carrying which boundary's
declaration produced the recorded `evidence_class` on **every** record, including the all-absent
fallback arm — not only on records where a conflict occurred. This still satisfies DECL-05 (which
authority applied is always legible) without a second boolean field: "was there a conflict" is
answerable by an auditor as "did a higher-priority boundary in the fixed order also have a
non-empty, non-forced declaration" — information the four-leg walk itself makes reconstructable,
because a lower-priority boundary only ever wins when every higher-priority leg cast no vote.

**The enum, corrected from this section's earlier three-value framing.** `evidence_class_authority`
is one of `_EVIDENCE_CLASS_AUTHORITIES = ("evidence", "valuation", "classification", "evaluator")`
(`classifier.py:1174`) — **four** words, not the three this document's pre-implementation text
assumed, because the walk itself widened to four legs (see the amendment above). The value is
validated against this exact set at the forwarder in `hermes-report.sh` before being placed on the
`--metadata` envelope, and clamped to 16 bytes — `classification` is the longest member at 14
bytes, leaving 2 bytes of headroom that a future fifth authority word must re-check rather than
assume. The forwarder's allow-list check runs **before** truncation, so a legal value is never
silently cut, and an out-of-set value is dropped rather than forwarded — a correctness discipline,
not a cosmetic one, because misnaming who set an evidence label on a billing-adjacent record would
itself be a false audit trail.

### The plumbing consequence

Neither existing record-site function currently has all three boundaries' declared classes in
local scope. `_validate_assessment` (containing record site 1) resolves the active **valuation**
impl name locally at `classifier.py:1467` and never resolves the evidence-boundary impl name
anywhere in its own body. `_resolve_reportability_status` — a **different function** — resolves
the active **evidence** impl name at `classifier.py:2017`. `_build_job_assessment` (containing
record site 2) receives `evaluator` as a parameter but resolves neither the valuation nor the
evidence impl name itself. So under this rule, `_declared_evidence_class`'s signature must grow
beyond its current single `evaluator: str` parameter to also receive the active valuation and
evidence boundaries' declared classes as caller-supplied string arguments. Those values come
from the same two primitives already in the tree — `_boundary_impl_name(key, default)`
(`classifier.py:2860`) to find the active implementation name, then that boundary's own
`resolve_evidence_class(name)` (the `BoundaryRegistry` method at `boundary_registry.py:169-176`)
to read its declared class — without prescribing here what Phase 50's exact parameter list
looks like.

**Amendment (2026-08-30) — what actually shipped.** The rule site is `_evidence_class_precedence(
evaluator, valuation_declared, evidence_declared, classification_declared) -> tuple[str, str]`
(`classifier.py:1275`), one parameter longer than this paragraph anticipated because the walk grew
a fourth leg (see the amendment under "The precedence rule" above). `_declared_evidence_class`
(`classifier.py:1210`) survives unchanged in name and in its existing single-argument call
contract — its three new parameters default to `""` — but its body is now a one-line delegator
returning element 0 of `_evidence_class_precedence`'s 2-tuple, so DECL-02's "exactly one rule
site" holds structurally: there is one function that walks, and one function every existing
caller already called. Both record sites (`_validate_assessment`, `classifier.py:1548`, calling
`_evidence_class_precedence` at `:1756`; and `_build_job_assessment`, `classifier.py:2431`,
calling it at `:2575`) call `_evidence_class_precedence` directly and unpack both elements of its
return tuple, rather than calling the delegator and losing the second element. This is exactly Falsifier 2's own prescribed
narrowing — see `## Phase 50 outcome` below.

### Fail-open, preserved

Every resolution path in the existing chain — an unregistered name, an empty declaration, a
non-string declaration, an import failure, or any raised exception — falls back to
`_forced_evidence_class()` and never raises. The rule inherits this without change: a priority
walk over three fail-open lookups is itself fail-open, and its own worst-case outcome is the
same forced constant the chain already returns today.

### Promotion safety

This subsection states explicitly why the chosen rule opens no promotion path — the binding
constraint an untrusted model output stays structurally unable to raise its own claim
(DECL-03).

**The signature-shaped guarantee, after this rule exists.** `_declared_evidence_class` grows to
accept two additional string arguments — the active valuation-boundary and evidence-boundary
declared classes — but neither may be, nor be derived from, `raw`. Each additional parameter is
itself the *result* of a registry lookup the caller performs via `_boundary_impl_name` (reading
`config.json`) and `BoundaryRegistry.resolve_evidence_class` (reading a registry entry set at
`register()` time) — never a value read out of an evaluator's response. The function's
guarantee class is preserved, not weakened: every parameter it takes still traces back either
to a caller-supplied name or to a registration-time declaration, never to model output.

**What a model output still cannot do.** `raw` never crosses into `_declared_evidence_class` or
its priority walk at all, under any of the additional parameters this rule adds. No parameter
in the widened signature can be traced back to `raw` through the call chain: `_boundary_impl_name`
reads `config.json`, not `raw`; `resolve_evidence_class` reads an import-time registry entry, not
`raw`. A future edit that derived one of the new parameters from `raw` *in the obvious place* —
directly inside one of the three functions `tests/test_phase43_evidence_grading.py`'s ast guard
statically scopes — would be caught the same way A1-A8 are caught today, because `evidence_class`
is already a member of `_PROMOTION_FORBIDDEN_KEYS`
(`tests/test_phase43_evidence_grading.py:484-493`).

**What that guard does not cover.** The guard is not a general promotion detector, and Phase 50
must not treat it as one. Its own docstring
(`tests/test_phase43_evidence_grading.py:550-575`) records the scoping as deliberate:
"Deliberately scoped to the `raw` NAME within these three functions, and to a NAMED forbidden-key
set." Three edits would therefore pass it:

1. **A new helper.** `_find_forbidden_raw_reads` walks only the bodies returned by
   `_scoped_function_defs`. A read of `raw['evidence_class']` inside a helper *called from* one of
   those functions is never visited.
2. **A different key.** The match is against `_PROMOTION_FORBIDDEN_KEYS` by name. A precedence
   input derived from some other response field, and only then mapped to a class, is not a
   forbidden-key read.
3. **A different name.** The match is against the literal identifier `raw`
   (`_UNTRUSTED_PARAM_NAME`). Any rebinding before the read is out of scope.

**Which existing test would catch a regression.** `tests/test_phase43_evidence_grading.py`'s
`PromotionTests` (`:626`) running `_hostile_evaluator_response()` through the real construction
path, plus the ast guard over `_PROMOTION_FORBIDDEN_KEYS`. Both remain **necessary and continue
to hold** — they prove the untrusted-input half of the threat model regardless of how many
boundaries the trusted-declaration half consults. They are **not sufficient**: if Phase 50's
priority walk lands in a new helper rather than inline in the three scoped functions, extending
`_scoped_function_defs` to cover that helper is part of Phase 50's work, not an optional extra.
Structural safety here rests on the widened signature carrying no `raw`-derived parameter — the
argument above — with the ast guard as a regression net over the inline case only.

### Boundary cases

**Identical declarations.** Two active boundaries declare the *same* `evidence_class`. This is
not a conflict: the priority walk stops at the first non-empty declaration it encounters in
fixed order, and that value happens to equal what a lower-priority boundary would also have
said. No conflict is recorded, because none occurred — the record only needs a conflict field
when two boundaries would have produced *different* answers (see Conflicting declarations
above).

**Absent declarations.** Two distinct shapes exist, and they must not be conflated. Shape (a):
a boundary's *configured* implementation name is **unregistered** —
`BoundaryRegistry.resolve_evidence_class` misses on `self._entries.get(name)` and returns `""`
(`boundary_registry.py:169-176`). Shape (b): a boundary is registered but its entry declares a
literal `""`. Today, `reporting.py:78-81` and `cohort_impact.py:104-106` ship with zero
registrants — but neither is one of the three boundaries this rule consults (`evaluator`,
`valuation`, `evidence`), so shape (a) is theoretical for this rule's inputs unless an operator
configures an unregistered impl name for one of those three. No fixture in this tree registers
anything with a literal `""` declaration, so shape (b) has no fixture at all. Both shapes
resolve to the same string, `""`, and the priority walk treats `""` as "this boundary cast no
vote" and moves to the next boundary in order. **All-absent case:** if all three boundaries
resolve to `""`, the rule returns `_forced_evidence_class()`, unchanged from today's behaviour.
**Exactly-one-declares case:** that boundary's declaration wins outright, with no conflict
recorded, because only one boundary cast a vote.

**Tied declarations.** No tie is structurally possible under this shape. `evidence` >
`valuation` > `evaluator` is a strict total order over exactly three named boundaries, so no two
boundaries ever share a priority rank — the walk always has exactly one first non-empty match
among any nonempty subset. What might look like a tie at first glance — two boundaries declaring
the *same* class — is the Identical declarations case above, not a priority conflict: the
tiebreak in this rule is over which **boundary** is consulted first, never over which **label**
is "stronger" than another. `classifier.py:1078-1097` states the nine labels are flat and
unordered by design and forbids sorting, ranking, or comparing them as an ordering key; this
rule never compares two label strings against each other at all, so that constraint is never at
stake.

## Falsification conditions

RECON-04 (ROADMAP criterion 3) requires recording these conditions before Phase 50 or Phase 51
evaluates them. Each condition states both the observation that would
falsify the rule and what happens when it fires (D-11) — "the condition fired and we proceeded
anyway" is the failure a pre-committed gate prevents. The four are D-12's
locked set. No test can prove a falsifier set exhaustive; this section states the four that were
named, not a claim that no fifth exists.

### Falsifier 1 — an adversarial fixture obtains a boundary-declared class

**The observation.** A hostile evaluator response, run through the real
`_validate_assessment`/`_build_job_assessment` construction path under Phase 50's implementation
of this rule, produces a persisted `evidence_class` equal to a value the response itself
asserted — through any of the rule's new inputs, not only the fields already guarded today —
rather than a value traced to a `register()`-time declaration.

**What already covers it, and what does not.** Partially covered today. `PromotionTests`
(`tests/test_phase43_evidence_grading.py:626`) runs `_hostile_evaluator_response()`'s eight
attacks through the real construction path, and `test_a1_direct_label_promotion_is_ignored`
(`:668`) asserts the direct label-promotion attack fails to obtain `EXPERIMENTAL_IMPACT`; the
ast walk over `_PROMOTION_FORBIDDEN_KEYS` (`tests/test_phase43_evidence_grading.py:484-493`, walk
at `:560-621`) proves no future edit can start reading the class off `raw` without turning the
suite red. That covers the untrusted-model-output half. It does not cover the trusted-registrant
half — a different threat model — which is what D-02 addresses and what falsifier 3 below is
about.

**Disposition:** Fatal, and it routes to the won't-fix trigger below, not to a narrowing. This
document's D-01 premise is that a registration-time declaration by trusted code is structurally
unable to read evaluator output — a different threat model from the one
`_forced_evidence_class()` defends against, which is what makes EGV-02 closeable at all. If this
falsifier fires despite that premise, the premise was wrong in practice: implementing the
priority walk reopened, by some path this document did not anticipate, the promotion path Phase
43 structurally closed. That is not a bug to patch inside Phase 50 — it is the ROADMAP's own
anticipated Phase 50 outcome (see `## The won't-fix trigger` below), and EGV-02 closes as a
recorded won't-fix rather than shipping a rule that reopens what Phase 43 shut.

### Falsifier 2 — the rule cannot be sited once

**The observation.** Building the priority walk forces the same resolve-and-compare logic to be
written independently at more than one place — for example, inlined separately inside
`_validate_assessment` and again inside `_build_job_assessment`, rather than both calling one
shared function — so that a future change to the rule requires touching more than one call site
to stay consistent.

**What already covers it, and what does not.** No existing test, because no precedence rule
exists yet. The concrete code-level reason this risk is real rather than hypothetical:
`_validate_assessment` resolves the active valuation impl name locally at `classifier.py:1467`
and never resolves the evidence-boundary impl name anywhere in its own body;
`_resolve_reportability_status` — a different function — resolves the active evidence impl name
at `classifier.py:2017`; `_build_job_assessment` resolves neither and receives `evaluator` as a
parameter only. The natural first draft of "also check valuation and evidence" is tempted to
inline a resolve-and-compare block separately at each record site, because each has different
information already in local scope. `boundary_registry.py`'s own docstring records a fixed
defect of exactly this shape: an earlier draft of `evaluators.py`'s `version` handling resolved
metadata by comparing the registrant's name at the call site (`LLM_EVALUATOR_VERSION if name ==
"llm" else ""`), which silently dropped the version of every registrant but one — the reason
`boundary_registry.py` declares per-registrant metadata once, at registration, and never
re-derives it at a call site.

**Disposition:** Narrow, not fatal. If the rule cannot be sited once against
`_validate_assessment` and `_build_job_assessment` as they are shaped today, the fix is
architectural, not a reversal of D-01's chosen shape: extract the priority walk into one function
inside `classifier.py` — mirroring `_declared_evidence_class`'s own existing shape — that both
record sites call, supplying their locally-resolved valuation/evidence declarations as
arguments, rather than re-deriving the walk at each site. Fixed boundary priority survives; only
the plumbing narrows to enforce DECL-02 the way `boundary_registry.py` already enforces it for
`version`.

### Falsifier 3 — a causal label becomes reachable from config

**The observation.** Any path — direct or indirect — by which a trusted registrant's declared
class reaches a persisted `evidence_class` record carrying one of the three reserved
causal-impact labels: `ASSOCIATIONAL`, `QUASI_EXPERIMENTAL_IMPACT`, or `EXPERIMENTAL_IMPACT`.

**What already covers it, and what does not.** No existing coverage at all. `classifier.py:1218`
passes the full nine-label `EVIDENCE_CLASSES` frozenset as `allowed`, so the membership test
alone does not refuse the three labels D-02 reserves. Nothing reaches a record today only
because `_declared_evidence_class` resolves the `output_assessment` registry alone. Closing this
is Phase 50's narrowing of the `allowed` argument at that one site.

**Disposition:** Revise before shipping — not fatal to the rule, and not a won't-fix trigger.
This falsifier guards D-02 specifically, not D-01: if it fires, Phase 50's allow-list narrowing
at `classifier.py:1218` was incomplete or wrong, and the fix is to correct that one narrowing
(refuse exactly the three reserved labels, verified by test against every boundary this rule can
reach) before the rule ships. D-02 is rated costly, not one-way, reversibility precisely because
this kind of revision is expected to be possible without reopening D-01's own premise.

### Falsifier 4 — feature-off behaviour shifts

**The observation.** A feature-off install records or meters anything differently than it does
today — any change to what `hermes-report.sh` ships in `--metadata`, any new job-assessment
sidecar file, any ledger-line shape change — once Phase 50's priority walk exists in the tree.

**Two independent configuration surfaces, not one.** Getting this falsifier right requires not
conflating them:

- **`llmOutcomeEvaluation.enabled`** is the feature gate. `_llm_evaluation_enabled` reads it, and
  it is what EGV-22's feature-off contract is written against.
- **`boundaries`** is a *selection* surface only, and it has **no presence gate**.
  `_boundary_impl_name(key, default, …)` (`classifier.py:2860`) fails open by construction: its
  docstring states that "a missing `boundaries` object" — like a typo or a non-string value —
  "returns `default`", and `default` is always the built-in implementation's registered name. An
  install with no `boundaries` object still resolves to a live registrant. The same docstring
  calls `llmOutcomeEvaluation` "the (unrelated) llmOutcomeEvaluation object".

**What already covers it, and what does not.** Partial coverage.
`tests/test_phase46_feature_off.py` (EGV-22, D-08) asserts byte-identity across two cron ticks
with `llmOutcomeEvaluation.enabled=false` (`:219`). It does not need to be built; it needs to be
re-run once Phase 50 lands. What it does **not** cover is a config that leaves outcome evaluation
enabled and carries boundary selections — there is no "no `boundaries` object" arm, and because
that object's absence is indistinguishable from the registered defaults, such an arm would not
establish feature-off behaviour anyway.

**Disposition:** Revise before shipping — not fatal to the rule, and not a won't-fix trigger.
EGV-22's feature-off contract is a hard constraint independent of whether the precedence rule is
otherwise correct — the rule is unshippable regardless of correctness if this breaks (D-12). The
fix is implementation, not design: gate the priority walk's evaluation behind
`_llm_evaluation_enabled` — the gate that actually exists and that EGV-22 is written against — so
a feature-off install never reaches the new code path at all, and re-run
`tests/test_phase46_feature_off.py` to confirm. Do **not** gate on the presence of the
`boundaries` object; no such check exists in the tree, and adding one would change the fail-open
behaviour `_boundary_impl_name` deliberately guarantees.

## The won't-fix trigger

**The trigger, named exactly.** `### Falsifier 1 — an adversarial fixture obtains a
boundary-declared class` is the falsifier that routes Phase 50 to a recorded won't-fix rather
than an implementation. If a hostile evaluator response reaches a boundary-declared class
through the real construction path once this rule exists, D-01's premise — that a
registration-time declaration by trusted code is a different threat model from untrusted model
output, not the same mechanism reached from a different source — was wrong in practice, and
EGV-02 cannot close without reopening the promotion path Phase 43 structurally shut. That is the
exact scenario Phase 50's own ROADMAP goal text anticipates: "or, if Phase 48 concluded EGV-02
cannot close without reopening a path Phase 43 shut, the phase's honest output is a documented
won't-fix with reasoning recorded, matching how Phase 31 closed unbuilt on its own pre-committed
gate." Falsifier 2 (the rule cannot be sited once) narrows the implementation's plumbing rather
than closing the feature — see its disposition above. Falsifier 3 (a causal label becomes
reachable from config) and Falsifier 4 (feature-off behaviour shifts) are revise-before-ship
items, each fixable inside Phase 50 without touching D-01's premise — neither is a trigger.
Falsifier 1 alone is the trigger.

**What a recorded won't-fix looks like here.** Matching how Phase 31 closed unbuilt on its own
pre-committed gate: its durable artifact, `docs/auxiliary-usage-sizing.md`, recorded the gate
verdict with reasoning in a tracked file, with an explicit "Withdrawn (date) — reason. Not
failed." disposition per affected requirement, rather than a silent drop. A Phase 50 won't-fix
follows the same shape: the closure and its reasoning are written down in a tracked file,
DECL-01 and DECL-04 are dispositioned individually as withdrawn rather than silently dropped,
and — by explicit dependency — LIVE-03 (ROADMAP Phase 52 criterion 2, which REQUIREMENTS.md
already marks "Conditional on DECL-01 building — if EGV-02 closes as a recorded won't-fix, this
requirement closes with it, explicitly, not silently") is dispositioned alongside them. Phase
50's own ROADMAP charter already names this outcome, so the successor phase does not silently
re-inherit a refuted assumption.

**Binding Phase 51 to the same rule.** Phase 51's `--mechanism` work consumes this document's
precedence rule rather than deriving a second one. MECH-03's orthogonality constraint holds
against it: an operator-declared mechanism never moves the recorded `evidence_class`, which
follows the precedence rule stated above and never the mechanism. MECH-05's guard test (a study
reference must not set a mechanism) leans on the same allow-list split D-02 establishes — which
is why D-02 is rated costly rather than reversible above. One rule, two consumers, no second
derivation. Even if Falsifier 1 fires and Phase 50 closes DECL-01/DECL-04 as a won't-fix, the
rule itself — and MECH-03's constraint against it — is unaffected: what would be withdrawn is
the multi-registry resolution Phase 50 builds, not the precedence statement Phase 51 binds
against.

**The drift this prevents.** This milestone opened with a reconciliation phase because two
records had drifted apart, each stating one side of the same question in a different place —
`classifier.py:1160`'s threat-model argument and `docs/internal-milestones.md:110`'s EGV-02
deferral note. A rule derived once and cited twice cannot drift; a rule derived twice will. That
is why this trigger lives here, in the one document both Phase 50 and Phase 51 read, rather than
being restated separately inside each phase's own plan.

## Phase 50 outcome (2026-08-30)

**Verdict: SHIP.** Falsifier 1 did not fire. Phase 50 built the precedence rule described above
rather than converting to the won't-fix trigger. This section is the closing record the
falsification-conditions discipline (`## Falsification conditions` above) requires: a written
verdict for each of the four named conditions, fired or not fired, with the evidence that
produced it — none left silently unevaluated.

### Falsifier 1 — an adversarial fixture obtains a boundary-declared class

**Did not fire. Verdict: `ship`** (plan 50-02, Task 3). Ten checks — six behavioral
(`PromotionUnderPrecedenceTests`) plus four static (`SignatureGuardTests`) — all `PASS` against
the real, built implementation, not a paper prediction. The load-bearing case is Test 2: a hostile
response naming five keys after the walk's own new inputs (`valuation_declared`,
`evidence_declared`, `evidence_class_authority`, `boundaries`, `boundary_impl`) produced a record
identical to the unmodified attack, because those keys are never read off `raw` at either call
site — both callers resolve their non-evaluator arguments independently, from config-driven
module lookups. Static property 3 proves this structurally: every call-site argument traces to a
name or a boundary lookup, never to `raw` (ast-verified). Full detail and the ten-check table:
`.planning/phases/50-declaration-authority/50-02-SUMMARY.md`.

### Falsifier 2 — the rule cannot be sited once

**Did not fire.** The shape built is exactly this falsifier's own prescribed narrowing: one
function, `_evidence_class_precedence` (`classifier.py:1275`), inside `classifier.py`, mirroring
`_declared_evidence_class`'s own pre-existing shape, that both record sites call — supplying their
locally-resolved valuation/evidence/classification declarations as arguments rather than
re-deriving the walk at each site. No resolve-and-compare logic was written independently at more
than one place; `_validate_assessment` (`classifier.py:1548`) and `_build_job_assessment`
(`classifier.py:2431`) both call `_evidence_class_precedence` directly (`:1756`, `:2575`) and
unpack its 2-tuple. DECL-02's "exactly one call site" — one rule site, not one record site, per
this document's own earlier framing — holds as built.

### Falsifier 3 — a causal label becomes reachable from config

**Did not fire, closed pre-emptively.** `_DECLARABLE_EVIDENCE_CLASSES` (`classifier.py:1184-1207`)
narrows the `allowed` argument at the walk's allow-list check from the full nine-label
`EVIDENCE_CLASSES` to a strict six-member subset, refusing `ASSOCIATIONAL`,
`QUASI_EXPERIMENTAL_IMPACT`, and `EXPERIMENTAL_IMPACT` even from a trusted registrant, built by
subtraction (never independently listed) with an import-time assert guarding against drift.
Proven adversarially, not just by construction: 50-02 Task 1 Test 3 registers a fixture declaring
`EXPERIMENTAL_IMPACT` via `boundaries.valuation` and confirms it is refused, falling back to the
forced constant with authority `evaluator` — never `valuation`. 50-03's conflict-pairing tests
re-exercise the same gate across the other three legs (evidence, classification, evaluator).

### Falsifier 4 — feature-off behaviour shifts

**Did not fire.** Structural reason: both record-site callers of `_evidence_class_precedence` are
gated behind `_llm_evaluation_enabled` (`classifier.py:3753` and `:3772`), so a feature-off
install never reaches the priority walk at all — the gate that actually exists and that EGV-22 is
written against, not a check on the presence of the `boundaries` object (no such check exists in
the tree, per this document's own Falsifier 4 disposition above). Re-confirmed by a fresh run of
`tests/test_phase46_feature_off.py` in this plan (Task 1), asserting byte-identity across two cron
ticks with `llmOutcomeEvaluation.enabled=false`:

```
$ python3 -m unittest tests.test_phase46_feature_off -v
Ran 11 tests in 71.103s
OK
```

### Reachability and conflict determinism (DECL-04)

All four fixture-declared classes reach the persisted record from their own boundary's
configuration, proven against the real `_validate_assessment` → `_build_job_assessment`
construction path (plan 50-03, `FixtureMatrixTests`' reachability matrix):

| Class | Boundary | Reachable? |
|---|---|---|
| `CUSTOMER_CONFIRMED` | `evidence` | YES |
| `CUSTOMER_CONFIGURED` | `valuation` | YES |
| `ACTIVITY_MEASURED` | `classification` | YES (option-b's newly-inserted fourth leg) |
| `OUTCOME_OBSERVED` | evaluator name | YES |

Conflict resolution is deterministic at N=2 (all six pairings across the four-leg walk), N=3 (two
variants), and N=4 (all four boundaries conflicting) — `ConflictDeterminismTests` (plan 50-03),
re-run three times plus once with `config.json`'s `boundaries` dict keys reversed, with an ast
guard confirming the walk never sorts, maxes, mins, or ordinally compares two label strings.

**Consequence:** DECL-04 closes in **full**. ROADMAP Phase 50 success criterion 1 is **met**; its
"or superseded" branch does not apply, and no supersession line was written for it.

### The full-suite verification this outcome rests on

```
$ python3 -m unittest discover -s tests -p 'test_*.py' -v
Ran 1248 tests in 1108.332s
OK (expected failures=1)
```

Zero `FAIL:`/`ERROR:` lines. `expected failures=1` is the module's own documented
`expectedFailure`, not the `test_a27` floor-regression flake (which presents as
`FAILED (failures=1, expected failures=1)` with a `FAIL:` line present — absent here). Neither
known flake (`test_a27`, the `supports_flag` squad capability probe) fired on this run.

Before/after test counts: **1203** (pre-Phase-50, `origin/main`) → **1248** (this HEAD), an
increase of 45 tests across the four plans (14 in 50-01, 10 in 50-02, 21 in 50-03), with zero
tests removed or weakened. Full detail: `.planning/phases/50-declaration-authority/50-VERIFICATION.md`.

## Appendix: restatement-site sweep

D-10's rule, in this document's own voice: every place in the tree that echoes one side of the
RECON-03 tension is enumerated here, and only the sites the decision renders false are edited.
The audit is visible even where no edit follows, so a later reader knows a site was considered
rather than missed.

| Site | file:line | What it asserts | Verdict | Edited? |
|---|---|---|---|---|
| A | `docs/claim-distinctions-and-evidence-boundaries.md:319-333` (post-48-03; the pre-edit sweep found this paragraph at lines 319-331) | Pre-edit: "Not true today: a configured boundary's own declared class does not reach the persisted record ... This was left open rather than patched because closing it needs a cross-boundary precedence rule that no decision covers ... and because letting a boundary declaration raise a recorded class is the same mechanism as the promotion path this product structurally closed elsewhere; patching around that mechanism here would reopen it by a side door." | Splits in two. The factual clause (lines 319-326, "Not true today ... under-claims rather than over-claims") stays literally true after this phase — Phase 48 changes no runtime behaviour, so the fact that a configured boundary's declared class does not yet reach the record is unaffected. The reasoning clause (pre-edit lines 328-331, "the same mechanism as the promotion path ... reopen it by a side door"; post-edit lines 328-333) is exactly the EGV-02 deferral's reasoning D-01 corrects: a registration-time declaration by trusted code is a different threat model, not the same mechanism reached from a different source, now with a pointer to this document. | Yes — reasoning clause only. Performed by plan 48-03, not this plan (this plan touches only `docs/evidence-class-precedence.md`). |
| B | `boundary_registry.py:25-32` (module docstring, the `register()` contract paragraph) | "This is a DIFFERENT threat model from the one classifier._forced_evidence_class() defends ... A registration-time declaration never touches evaluator output either ... Neither pattern subsumes the other." | Confirmed — this already states D-01's upheld position accurately. | No. |
| C | `cohort_impact.py:46-60` (module docstring paragraph) | "A registered estimator's result can never be represented as individually-observed causality. The mechanism is STRUCTURAL, not a check: this registry is a separate BoundaryRegistry instance that classifier._declared_evidence_class NEVER consults ..." | Confirmed — factual, still true. `_declared_evidence_class` resolves the `output_assessment` registry alone, exactly as this paragraph describes. | No. |
| D | `evaluators.py:38-50` (module docstring paragraph) | "The validator derives evidence_class from the resolved evaluator's OWN registration-time declaration (Phase 45, D-06 AMENDED ...)" | Confirmed — accurate description of the mechanism, unaffected by which record RECON-03 corrects. | No. |
| E | `evidence.py:50-66` (module docstring paragraph) | "...this module does NOT decide an implementation's evidence class. The class is DECLARED at register() time by trusted code (D-06 AMENDED, the same mechanism every other boundary in this phase uses) ..." | Considered and distinguished, not false. This "same mechanism" has a different referent from site A's: here it names the shared registration mechanism every boundary in Phase 45 uses (`register()`/`resolve()`), not the EGV-02 deferral's claim that a boundary declaration is the same mechanism as the promotion path. Different referent, not an instance of the reasoning D-01 corrects. | No — recorded here as considered, which is what D-10's "visible even where no edit follows" exists for. |
| F | `docs/internal-milestones.md:187-188` (numbered list, "### Decisions worth carrying forward" closing section) | "5. Record the direction of an error. EGV-02 was deferrable precisely because it under-claims; that fact turned a would-be blocker into a documented gap." | Confirmed — a generic engineering lesson illustrated by EGV-02's history. Its truth does not depend on RECON-03's outcome; the correction lives in the dated superseding block D-08 adds at line 110, not in this lesson. | No. |

Two of these six sites — E and F — were found beyond the four `48-CONTEXT.md` named (A, B, C,
D). Sites B, C, and D are unaffected because they already state, or accurately describe, the
position D-01 upholds; Phase 48 changes no code these sites describe. The sweep itself is
grep-based and best-effort: it searched `docs/` and the plugin tree for the tension's
characteristic language — "same mechanism", "different threat model", "structurally", "promotion
path", "reopen". A restatement phrased in wording this pattern set did not search would not have
surfaced; a later reader broadening the search should start with the next-closest vocabulary this
document itself uses — "masquerad", "trusted registrant", "cross-boundary precedence".
