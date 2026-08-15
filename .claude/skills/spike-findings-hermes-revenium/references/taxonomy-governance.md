# Taxonomy Governance

The measured behavior of the label vocabulary — why it fragments, what actually fixes it, and
in what order to spend effort. This is the highest-leverage finding of the whole spike series.

`PROJECT.md` names taxonomy fragmentation as the failure condition for the feature:
*"If the taxonomy fragments (`code_review` vs `code-review` vs `review_code`) … the feature has
failed even if the wire protocol works."* These are the numbers on that risk.

## Requirements

From the `portable-task-classifier` idea in `.planning/spikes/MANIFEST.md`:

- **The shared artifact that matters is the TAXONOMY, not the code.** Per-host taxonomy files
  re-pay cold-start drift per host and converge on different attractors; a served vocabulary
  does not.
- **Seed the vocabulary with a curated domain taxonomy.** The shipped generic seed acts as an
  attractor that produces reproducibly *wrong* labels, not merely fragmented ones.
- Prompts are host-specific text (all three hardcode "Hermes"), so `host` is a parameter with a
  `"Hermes"` default — non-Hermes hosts run a different prompt and may produce different labels.

## How to Build It

### The three interventions, ranked by measured leverage

**1. Curate the seed vocabulary.** Cheapest, lowest-risk, needs neither library nor service.
(Shipped for the three catch-alls in quick task 260815-r39: the seed offered `generation`,
`analysis` and `review` as reusable vocabulary while the prompt's AVOID line names those exact
words. Seed changes affect fresh installs only, so the blast radius is small — unlike a prompt
change, which takes effect on every install's next classification.)

Measured (`sources/003-taxonomy-drift/fragmentation.py`, 2 runs): with the shipped generic seed
(`research`, `analysis`, `code_review`, `generation`), a CI-flakiness investigation was labelled
`sql_query_debug` in **both** runs by multiple hosts, `code_review` by another, and one security
review drew `prod_log_triage`.

> **CORRECTION (quick task 260815-r39).** Spike 003 called all of those "seeded generic labels".
> That was wrong, and the error is instructive. `code_review` *is* a seed label, so seed reuse is
> real. But `sql_query_debug` and `prod_log_triage` are **not in the seed at all** — they are two
> of the five hardcoded *"Good examples"* inside the prompt string itself
> (`classifier.py:787`: `weekly_pr_review, prod_log_triage, news_summary, sql_query_debug,
> release_notes_draft`). The model was copying its own few-shot examples verbatim onto unrelated
> work. There are **two** attractors, not one, and the more vivid failures came from the prompt.

A follow-up 2×2 (seed present/absent × examples present/absent) confirmed both attractors are
real and added a third finding: removing the examples also raised reuse of an *apt* existing
label from 3/5 to 4/5, because the examples were stealing classifications away from a correct
label already in the vocabulary. But the examples also anchor the 2-4 word granularity they were
added for — deleting them dropped labels in the target range from 14/15 to 8/15, and the *stated*
rule ("Use 2-4 words joined by underscores") did not substitute for the demonstrated pattern.

**The prompt-side fix is therefore NOT settled.** Effect sizes for the same condition ranged
7%–40% across runs, which is the resolution limit of the CLI harness (no `temperature=0`). Ship a
prompt change only against a temperature-0 instrument. The *seed* half was shipped on coherence
grounds instead — see below.

The seed is not a neutral starting point. Ship a vocabulary of specific, domain-shaped labels,
or ship a smaller one.

**2. Share the vocabulary across hosts.**

| Arm | Run 1 mean labels/item | Run 2 | Fragmentation ratio (4 real activities) |
|-----|------------------------|-------|------------------------------------------|
| INDEPENDENT (one taxonomy per host) | 2.8 | 2.8 | 3.25 / 2.75 |
| SHARED (one taxonomy across hosts) | 1.8 | 1.4 | 2.00 / 1.50 |

Combined **2.8 → 1.6 distinct labels per work item, ~43% less cross-host disagreement.**

Note the asymmetry in reproducibility: the *harm* is perfectly stable (independent arm gave
2.8 with per-item spread `[3,3,2,3,3]` in both runs — three hosts with their own vocabularies
essentially never agree), while the *cure* varies (1.8 vs 1.4, consensus items 2/5 → 3/5),
because consensus depends on an earlier host happening to mint something apt. Sharing is a
reliable improvement, not a guarantee.

**3. Share the classifier code.** Safe and cheap (see `classifier-extraction.md`) but on this
evidence the least consequential of the three for the outcome the project cares about.

### Drift is cold-start, not intrinsic

`sources/002-host-fit/reuse_experiment.py`, same work item, three seeds:

| Arm | Seed | Reuse | Distinct labels |
|-----|------|-------|-----------------|
| COLD | 4 generic labels | **0/4** | 4 |
| WARM | + 1 apt label | **4/4** | 1 |
| HOT | + apt label and 4 near-miss variants | **4/4** (chose the apt one) | 1 |

Once an apt label exists the model converges totally — 8/8 across WARM and HOT — and is not
confused by confusable near-misses. The reuse instruction in the prompt works; it just has
nothing to bite on when the vocabulary is cold or generic.

**Implication:** every host that starts from its own cold vocabulary pays its own fragmentation
window, and those windows converge on *different* attractors. That is the argument for a
vocabulary service, and it is independent of whether the code is shared.

### Cold-start labels are permanent

A shared vocabulary prevents *future* divergence; it cannot heal labels already minted and
already attached to metered rows. Whatever gets emitted during the cold window is in the
analytics forever. This is why seeding beats sharing: seeding removes the window.

## What to Avoid

- **Do not attribute label disagreement to a variable without running the control.** Three hosts
  producing three labels looked like a host-framing effect until the same-framing control
  produced three different labels too (11 distinct labels from 12 classifications of one piece
  of work). Framing was not the cause; free-form minting was.
- **Do not seed with bland category words.** They are attractors that cause misclassification,
  which is worse than fragmentation — a wrong label is confidently wrong in the analytics.
- **Do not assume a shared vocabulary is sufficient.** It cut disagreement 43%, not 100%.
- **Do not quote these magnitudes as production figures.** See Constraints.

## Constraints

- **Temperature confound:** the harness drives the local `claude` CLI, which cannot pass
  `temperature=0`. Production Hermes calls the API at temperature 0.0. Expect real COLD drift
  to be lower; the WARM/HOT convergence result (the load-bearing half) is unaffected.
- Sample sizes are directional: one work stream, one model, N=3–6 per arm, 2 replicates for the
  fragmentation experiment. The independent arm reproduced exactly, which raises confidence in
  that half specifically.
- Host order is fixed in the fragmentation experiment, which advantages whichever host
  classifies first. Production has no such ordering guarantee.
- The library caps the labels block at 1024 characters, so vocabulary growth does not grow the
  prompt past ~2.2 KB (see `host-integration.md`). Curating the seed costs nothing at inference
  time.

## Origin

Synthesized from spikes: 002 (host-fit, VALIDATED), 003 (taxonomy-drift, VALIDATED)
Source files: `sources/002-host-fit/`, `sources/003-taxonomy-drift/`
Raw arms: `sources/003-taxonomy-drift/fragmentation_result_run{1,2}.json`,
`sources/002-host-fit/reuse_experiment_result.json`, `sources/002-host-fit/drift_control_result.json`
