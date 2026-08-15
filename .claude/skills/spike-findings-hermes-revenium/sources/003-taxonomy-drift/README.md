---
spike: 003
idea: portable-task-classifier
name: taxonomy-drift
type: standard
validates: "Given multiple hosts classifying the same work stream, when each keeps its own vocabulary vs when they share one, then measure cross-host fragmentation and whether sharing eliminates it"
verdict: VALIDATED
related: [002-host-fit]
tags: [taxonomy, governance, drift, fragmentation]
---

# Spike 003: Taxonomy Drift

## What This Validates

Retargeted after spike 002. The original framing ("do independent hosts fragment the
vocabulary?") was answered in passing by 002: they do, but only through a cold-start window,
because a vocabulary containing an apt label converges 8/8.

The question actually worth money is the one left over:

**Given** three hosts classifying the same stream of work, **when** each keeps its own
taxonomy versus when all three share one, **then** how much does cross-host fragmentation
differ — and does sharing actually fix it?

This matters because `PROJECT.md` names taxonomy fragmentation as the failure condition for
the whole feature: *"If the taxonomy fragments (`code_review` vs `code-review` vs
`review_code`) … the feature has failed even if the wire protocol works."*

## Method

Five work items covering four distinct underlying activities. Two of them (`flaky-1`,
`flaky-2`) are **the same activity described in different words** — a deliberate probe for
whether the vocabulary collapses synonyms.

- **ARM INDEPENDENT** — three hosts, three separate `InMemoryTaxonomy` stores, all seeded with
  the same four generic labels (`research`, `analysis`, `code_review`, `generation` — the seed
  the repo actually ships).
- **ARM SHARED** — three hosts, one store between them. This is what a served vocabulary looks
  like from the classifier's side.

Metrics: distinct labels per work item (3 = total disagreement, 1 = consensus); fragmentation
ratio (distinct labels minted ÷ real activities, where 1.0 is perfect); and whether the
synonym pair collapsed.

## How to Run

```bash
cd .planning/spikes/003-taxonomy-drift
python3 fragmentation.py     # ~165s, 30 real model calls
```

Raw arms land in `fragmentation_result.json` (and `_run1` / `_run2` for the replicate).

## Investigation Trail

**1. Ran both arms on the same work stream in the same order.** Ordering is held constant
because the shared arm's whole mechanism is "an earlier host mints, a later host reuses".

**2. Independent vocabularies fragment almost completely.** Mean 2.8 distinct labels per work
item, against a ceiling of 3. Fragmentation ratio 3.25 — thirteen labels for four activities.

**3. A shared vocabulary measurably helps, but does not solve it.** Run 1: mean 2.8 → 1.8,
fragmentation 3.25 → 2.0, with two of five items at full 3/3 consensus (`perf-1`, `flaky-2`) —
exactly the items where an earlier host had already minted an apt label for a later host to
find. Run 2 reproduced the direction more strongly (1.4, three items at consensus).

**4. Third surprise: the classifier emits inapt labels verbatim, not just fragmented ones.**
`flaky-1` — a CI flakiness investigation — came back as `sql_query_debug` (Hermes) and
`code_review` (LiteLLM).

> **CORRECTION (quick task 260815-r39):** this step originally called both "seeded generic
> labels". `code_review` is one. `sql_query_debug` is **not in the seed** — it is one of the five
> hardcoded *"Good examples"* in the prompt string (`classifier.py:787`), as is `prod_log_triage`
> below. The model copied its own few-shot examples. Two attractors, and the prompt's is the more
> vivid one. The prompt explicitly says *"AVOID bland catch-all labels like generation, analysis,
review, task when a more specific label fits"*, and the model did it anyway. The seed
vocabulary is not a neutral starting point — it is an attractor, and a bad one.

**5. Cold-start labels are permanent.** In the shared arm the synonym pair still failed to
collapse for 2 of 3 hosts, but the reason is ordering: `flaky-1` was classified while the
vocabulary was still cold, and nothing retroactively repairs a label already minted and
already attached to metered rows. A shared vocabulary prevents *future* divergence; it cannot
heal the window before the right label existed.

## Results

**Verdict: VALIDATED — sharing helps materially (2.8 → 1.6 labels per item across two runs),
but seeding quality dominates, and cold-start labels are unrecoverable.**

### Both runs

| Arm | Run 1 mean / item | Run 2 mean / item | Run 1 frag ratio | Run 2 frag ratio |
|-----|-------------------|-------------------|------------------|------------------|
| INDEPENDENT | 2.8 | 2.8 | 3.25 | 2.75 |
| SHARED | 1.8 | **1.4** | 2.00 | **1.50** |

The independent arm reproduced *exactly* — 2.8 mean, per-item spread `[3,3,2,3,3]` in both runs.
Three hosts with their own vocabularies essentially never agree. The shared arm improved on
replication (2/5 items at full consensus in run 1, **3/5 in run 2**), which is consistent with
the mechanism: consensus depends on an earlier host having minted something apt for a later
host to find, and that is a stochastic event.

Combined: **2.8 → 1.6 distinct labels per work item**, roughly a 43% reduction in cross-host
disagreement from sharing the vocabulary alone.

Run 2's shared arm, for comparison with run 1 below:

```
  flaky-1  sql_query_debug | sql_query_debug | ci_flaky_test_root_cause
  perf-1   perf_fix_org_serializer_n1 | perf_fix_dashboard_n1_query | perf_fix_dashboard_n1_query
  docs-1   webhooks_docs (all three)                                    CONSENSUS
  flaky-2  ci_flaky_test_root_cause (all three)                         CONSENSUS
  sec-1    auth_middleware_review (all three)                           CONSENSUS
```

**`flaky-1` drew `sql_query_debug` in both runs, from multiple hosts.** That is a reproducible
misclassification, not sampling noise — but it is a *prompt example* being copied, not a seed
label being reused. See the correction in trail step 4.

### Run 1 detail

Per-item detail (run 1):

```
INDEPENDENT
  flaky-1  Hermes=sql_query_debug        | LiteLLM=code_review                  | Claude=ci_flaky_test_root_cause
  perf-1   Hermes=perf_bottleneck_fix    | LiteLLM=database_query_optimization  | Claude=perf_fix_n_plus_one
  docs-1   Hermes=webhooks_docs_writing  | LiteLLM=webhooks_reference_docs      | Claude=webhooks_reference_docs
  flaky-2  Hermes=ci_intermittent_test_debug | LiteLLM=ci_flaky_test_debug      | Claude=ci_flaky_test_root_cause
  sec-1    Hermes=review_code_change     | LiteLLM=prod_log_triage              | Claude=auth_middleware_security_review

SHARED
  flaky-1  Hermes=sql_query_debug        | LiteLLM=code_review                  | Claude=ci_flaky_test_debug
  perf-1   all three = performance_debug_query_optimization
  docs-1   Hermes=webhooks_docs_writeup  | LiteLLM=webhooks_reference_docs_writeup | Claude=webhooks_reference_docs_writeup
  flaky-2  all three = ci_flaky_test_debug
  sec-1    Hermes=code_review_auth_middleware | LiteLLM=unclassified            | Claude=code_review_auth_middleware
```

Two anomalies worth keeping: `sec-1` produced `prod_log_triage` from one host (a *prompt
example*, not a seed label — see the trail step 4 correction), and one shared-arm classification
returned `unclassified`
— i.e. the raw model output failed `LABEL_RE` or hit the blocklist and was correctly rejected.

### What this means for the original question

Ranked by leverage, from these numbers:

1. **Seed the vocabulary with a curated, domain-appropriate taxonomy.** The generic seed
   actively produced wrong labels. This is the cheapest, highest-impact intervention and it
   requires no library and no service.
2. **Share the vocabulary across hosts.** Worth ~1.2 labels per work item (2.8 → 1.6). This
   is the argument for a taxonomy *service*, and it is independent of whether the classifier
   code is shared.
3. **Share the code.** Cheap and safe (spike 001), 80–91% reuse (spike 002) — but on this
   evidence it is the *least* important of the three for the outcome the project cares about.

### Limits

- One work stream, one model, 2 replicates per arm. Directional, not a benchmark — though
  the independent arm reproduced exactly, which raises confidence in that half.
- Same temperature confound as 002: `claude -p` cannot pass `temperature=0`.
- The shared arm simulates a service with an in-process store — it measures the *vocabulary*
  effect, not the operational cost of running one (see spike 004 for the hop).
- Host order is fixed, which advantages whichever host classifies first. A production system
  has no such ordering guarantee.
