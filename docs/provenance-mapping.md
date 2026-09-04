# Local evidence classes and server provenance

[← Back to the docs index](README.md)

## Scope

This page records the decided mapping from each of the nine local
`evidence_class` labels (`skills/revenium/plugins/revenium-classifier/classifier.py`'s
`EVIDENCE_CLASSES`) onto the two server `provenance` vocabularies exposed by
the Revenium Platform API, and the resolution of the one label that maps to
neither. It was derived against spec build `2.20.0-SNAPSHOT`
(`.planning/research/revenium-oas-v2.20.0-SNAPSHOT.json`); that vendored OAS
is itself gitignored and therefore not re-checkable from a fresh clone, which
is why the server value cells below are transcribed here rather than left to
be re-derived from a file a clone will not have.

It does not own the nine local labels' own semantics — that stays owned by
[`references/job-declaration.md`](../skills/revenium/references/job-declaration.md)
— and it does not own Phase 53's reportability gate, which stays owned by
`classifier.py`'s `_REPORTABLE_EVIDENCE_CLASSES`. It follows the shape
[`docs/evidence-class-precedence.md`](evidence-class-precedence.md)
established: a scope line, then a verdict, stated once and cited from
wherever it applies. This page does not edit that file, and the reference
runs one way, from here to there.

**This page implements nothing.** No code path under `skills/` reads,
imports, or hardcodes any value in the tables below. The `revenium` CLI at
`1.5.0` — the latest on the brew tap, and the only interface this project is
permitted to call — exposes none of the `economics`, `baselines`, or `facts`
verbs the server vocabularies below belong to, so there is nothing for a
local path to consume yet even if this document invited it to. Phase 59's
valuation seam is the first plausible consumer, if and when a future CLI
release exposes those verbs.

**The `[ASSUMED]` marker**, used on six rows below, marks a row whose
rationale rests on inference from the generic output/outcome/impact
taxonomy in
[`docs/claim-distinctions-and-evidence-boundaries.md`](claim-distinctions-and-evidence-boundaries.md)
rather than on an on-point code registrant comment — three of the nine local
labels (`OUTPUT_OBSERVED`, `ASSOCIATIONAL`, `EXPERIMENTAL_IMPACT`) have
neither a registrant nor defining prose anywhere in the tree, so their rows
on both tables rest on thinner evidentiary ground than a label like
`CUSTOMER_CONFIGURED`, which has a direct on-point comment at
`valuation.py:324-336`.

## The mapping

D-06: two surface-scoped tables, because a class can legitimately land on
both surfaces with a different value and one table would have to misstate
one of them. D-07: each table is keyed by `evidence_class` alone — folding
in `reportability_status` would suggest a `candidate` row has a provenance
value waiting for it, and would restate Phase 53's gate in a second,
drift-prone place.

Every row carries three cells beyond the key: the server provenance value
this local class maps to (or `not applicable` / `unmappable` with a reason),
a one-line claim-kind rationale, and a lossiness cell naming what the
mapping loses or over-asserts. A per-row confidence column was considered
and rejected — these nine labels are a flat, unordered set (EGV-10), and a
confidence column would invite ranking them against each other, which D-08
forbids.

The eight non-hard rows below are resolved by matching **claim kind** — is
this an observation, a configuration, a confirmation, or a causal
inference? — to the server value naming that same kind. None is resolved by
asking which class is "stronger" or "more trustworthy" than another.

### Table A — baselines surface

Targets `BaselineRequest.provenance` / `BaselineResource.provenance`, enum
`CUSTOMER_DECLARED` / `MEASURED` / `SIGNED_OFF`; the request schema defaults
to `CUSTOMER_DECLARED` when the field is omitted.

| `evidence_class` | Server provenance value | Claim-kind rationale | Lossiness / caveat |
|---|---|---|---|
| `ACTIVITY_MEASURED` | *not applicable* | No local path uses a keyword/token-overlap classification signal to set a job-type rate; this label characterizes what one session's transcript contained, never a per-type `hourlyRate` / `minutesPerUnit` assumption. | — |
| `OUTPUT_OBSERVED` | *not applicable* | **[ASSUMED]** A self-verified output observation (`SUCCESS` / `FAILED` / `CANCELLED` inferred from the transcript) is a per-job signal, never a job-type rate. | — |
| `OUTCOME_OBSERVED` | *not applicable* (borderline — see below) | The sole producer, `_system_of_record_assessment_fixture`, reads a single global `config["systemOfRecord"]` rate for one job's assessment; it never persists a job-type baseline record. | **Flagged borderline:** a system of record is exactly the kind of source `MEASURED` describes on this surface. If a future baseline-setting path reused this evidence kind to populate a real `POST .../baselines` call, `MEASURED` would be the value then — today no such path exists, so *not applicable* is the honest present-tense answer, not a permanent one. |
| `MODEL_ESTIMATED_DEMO` | **unmappable** | None of `CUSTOMER_DECLARED` / `MEASURED` / `SIGNED_OFF` answers "no rate-obtaining process ran at all — a model invented an hours/rate pair"; each of the three names a real process that produced the rate. See [The hard case](#the-hard-case) (added by plan 58-02) for the full derivation. | This label names no server provenance value on either surface (D-01). |
| `CUSTOMER_CONFIGURED` | **`CUSTOMER_DECLARED`** | The rate/revenue card is an operator-approved figure the operator declared into config, with no model call in the derivation (`valuation.py:324-336`) — a direct kind-match to "customer declared". | `CUSTOMER_DECLARED` cannot distinguish a rate-card entry keyed by evaluator-inferred role from a revenue-card entry keyed strictly by an operator-bound `revenueCardKey` (never model-inferred) — two different exposure profiles to model influence, collapsed into one value. |
| `CUSTOMER_CONFIRMED` | *not applicable* | The sole producer, `_confirmation_workflow_evidence_fixture` (`evidence.py:283-317`), is keyed by `agentic_job_id` membership in a confirmations list — structurally per-*job*, never a job-*type* rate. This is the same structural reason `OUTCOME_OBSERVED` takes *not applicable* on this surface, not a comparison of the two claims' relative weight (D-08 forbids that question). | **`SIGNED_OFF`** is the value this row would take if a baseline-setting path ever consumed this evidence kind — a customer confirming an outcome is, in claim-kind terms, the closest analog to a stakeholder signing off on a baseline value. Note this is a surface-scoping fact, not a strength comparison: `SIGNED_OFF` exists only on the baselines vocabulary and `ATTESTED` (see Table B) only on the facts-and-metrics vocabulary. |
| `ASSOCIATIONAL` | *not applicable* | **[ASSUMED]** A causal-impact estimate — even the weakest, correlational form — is not a job-type rate. | Real mapping supplied on the facts-and-outcome-metrics surface instead (see Table B). |
| `QUASI_EXPERIMENTAL_IMPACT` | *not applicable* | Same reasoning as `ASSOCIATIONAL`: a causal-impact estimate is not a job-type rate. | Real mapping supplied on the facts-and-outcome-metrics surface instead (see Table B). |
| `EXPERIMENTAL_IMPACT` | *not applicable* | **[ASSUMED]** Same reasoning as `ASSOCIATIONAL`: a causal-impact estimate is not a job-type rate. | Real mapping supplied on the facts-and-outcome-metrics surface instead (see Table B). |

### Table B — facts and outcome-metrics surface

Targets `PeriodFactEntry.provenance` / `OutcomeMetricEntry.provenance` /
`OutcomeMetricEntry_Read.provenance`, all three byte-identical: enum
`MEASURED` / `SELF_REPORTED` / `DERIVED` / `ATTESTED`, defaulting to
`SELF_REPORTED` when the field is omitted.

| `evidence_class` | Server provenance value | Claim-kind rationale | Lossiness / caveat |
|---|---|---|---|
| `ACTIVITY_MEASURED` | **`MEASURED`** | A deterministic token-overlap measurement of the transcript (`classification.py:209-221`) — a real quantity was measured, no self-report, no derivation, no attestation. | See "The `MEASURED` collision" below — this row shares its value with `OUTPUT_OBSERVED` and `OUTCOME_OBSERVED` for a reason that is not a claim-kind mismatch. |
| `OUTPUT_OBSERVED` | **`MEASURED`** | **[ASSUMED]** A direct, self-verified observation that the work product exists. | This is D-09's own named example of the `MEASURED` collision, stated in full below. |
| `OUTCOME_OBSERVED` | **`MEASURED`** | An external system of record's recorded observation of the downstream outcome (`evaluators.py:182-188`) — still an observation, not a derivation or a self-report. | Same `MEASURED` collision as `OUTPUT_OBSERVED`, stated once below rather than twice. |
| `MODEL_ESTIMATED_DEMO` | **unmappable** | None of `MEASURED` / `SELF_REPORTED` / `DERIVED` / `ATTESTED` names "a model hypothesized a number with no real observation behind it"; each names a real quantity obtained some way. See [The hard case](#the-hard-case) (added by plan 58-02). | This label names no server provenance value on either surface (D-01). Supporting note: this surface's own schema *omits* the field to `SELF_REPORTED` by default — silence is not neutral, which is part of why an explicit *unmappable* entry matters more here, not less. |
| `CUSTOMER_CONFIGURED` | **`SELF_REPORTED`** | The operator or organization is the "reporter" of a pre-approved rate or amount — a real person's number, not a model's, matching `SELF_REPORTED`'s own definition. | `SELF_REPORTED` cannot distinguish a value fixed once in a rate card and applied mechanically on every subsequent record from an ad hoc figure typed in fresh for this one fact. |
| `CUSTOMER_CONFIRMED` | **`ATTESTED`** | A stakeholder affirms or validates an existing figure after the fact (`evidence.py:266-278`) — a confirmation act, which is exactly what `ATTESTED` names on this surface. Unlike Table A, `ATTESTED` exists here with no competing candidate, so this row is a clean match. | `ATTESTED` does not reveal *what* was attested to — a customer confirming an already-model-estimated figure is recorded identically to a customer confirming an independently-derived one; confirmation establishes agreement, not independent verification of magnitude. |
| `ASSOCIATIONAL` | **`DERIVED`** | An impact estimate — even a bare correlational comparison with no adjustment for confounders — is computed from underlying inputs via a comparison procedure: not directly measured, not self-reported, not merely attested. **[ASSUMED]** **Refused as a declaration today:** `_DECLARABLE_EVIDENCE_CLASSES` (`classifier.py:1250-1273`) excludes this label from every registrant, trusted or not, so no local path can attach it to a record right now — that refusal is not a statement that the label is meaningless or that no server value fits, only that nothing currently emits it. | See "The causal-impact collapse" below — the single largest lossiness in this whole mapping. |
| `QUASI_EXPERIMENTAL_IMPACT` | **`DERIVED`** | Same reasoning as `ASSOCIATIONAL`: a comparison-derived figure, not a raw measurement, self-report, or attestation. **Refused as a declaration today**, same `_DECLARABLE_EVIDENCE_CLASSES` citation. | Same causal-impact collapse, stated once below. |
| `EXPERIMENTAL_IMPACT` | **`DERIVED`** | **[ASSUMED]** Same reasoning: an RCT effect estimate is still a *derived* statistic — computed from randomized treated/control observations via an identification strategy — not a raw measurement, self-report, or attestation. **Refused as a declaration today**, same `_DECLARABLE_EVIDENCE_CLASSES` citation. | Same causal-impact collapse, stated once below. |

## Shared caveats

**The `MEASURED` collision.** `MEASURED` cannot distinguish an observed
output from an observed outcome, and `ACTIVITY_MEASURED` lands on the same
value too. All three share `MEASURED` because the server vocabulary has no
activity/output/outcome axis to place them on — not because they are the
same claim. This is D-09's own named example of a mapping that is honest
about what it loses.

**The causal-impact collapse.** All three causal-impact labels —
`ASSOCIATIONAL`, `QUASI_EXPERIMENTAL_IMPACT`, `EXPERIMENTAL_IMPACT` — land
on the identical value `DERIVED`. This is the mapping's single largest
information loss: the whole reason the local vocabulary splits
correlational, quasi-experimental, and experimental designs into three
labels is to preserve a causal-rigor distinction that `DERIVED` cannot
represent at all. A reader of a facts-and-metrics record can tell that
*some* comparison or calculation produced the figure, and nothing about
whether it came from a randomized trial or a raw group-mean difference.
This is a statement about the server vocabulary's resolution, not a claim
that one of the three labels carries more weight than another — the doc is
not saying `EXPERIMENTAL_IMPACT` is worth more than `ASSOCIATIONAL`; it is
saying the server's own vocabulary cannot see the difference between them.

**Why `DERIVED` is not the answer for the other six.**
`references/job-declaration.md:94` states `estimated_value` is *always* the
product of `estimated_hours_saved` and `assumed_loaded_rate`, for every
evidence class — not just the model-estimated one. The provenance label
describes the *kind of the two inputs* (measured, configured, confirmed, or
model-invented), never the arithmetic that combines them. `DERIVED` is
reserved for the causal-impact labels specifically because *their* figure
comes from a statistical comparison across a treated and control
population, not because a multiplication happened.
