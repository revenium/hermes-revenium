# Claim distinctions and evidence boundaries

[← Back to the docs index](README.md)

This page is repo-only — it is not part of the skill bundle and a tap-installed host never
sees it. It owns the conceptual frame this milestone needs and that no shipped file owns:
the distinctions between output, outcome, valuation, impact, and ROI; the chain that connects
them; the product-truth boundary; the vocabulary this project uses; and what this milestone
deliberately does not ship. Every contract term — the nine evidence labels, the config keys,
the assessment schema — stays owned by the shipped references this page links to. This page
never duplicates a contract; it only explains the frame the contracts sit inside.

## Output, outcome, valuation, impact, ROI

Five words get used loosely in this space. Here they are held apart.

**Output** is what the work produced — a merged diff, a passed test suite, a shipped
endpoint. It is the thing an agent can self-verify at the moment it finishes. This skill
observes output directly, through the session transcript a job marker is built from.

**Outcome** is what happened as a result of that output being accepted and used — a bug
that stopped recurring, a review that caught a defect, a release that shipped on schedule.
An outcome requires the output to have been adopted by something or someone downstream of
the agent; producing the output is not the same as the output mattering. This skill infers
a `SUCCESS`/`FAILED`/`CANCELLED` status from the transcript, which is closer to output than
to outcome — self-verification is not downstream adoption.

**Valuation** is a monetary figure attached to a claimed outcome, under stated assumptions.
It requires an outcome (or an assumed one) plus a rate or price to convert it to money. This
skill's `llmOutcomeEvaluation` feature produces a valuation — an hours-saved figure times a
loaded rate — but the outcome the valuation is attached to is itself assumed, not observed.
That is the load-bearing gap the rest of this page returns to.

**Impact** is the causal contribution of the intervention, relative to a comparator — what
would have happened without the agent's work. Establishing impact requires an identification
strategy (a control group, a natural experiment, a pre/post design with confounders
addressed) that this product does not run. This skill can name that an impact claim exists as
a contract (see `references/job-declaration.md`'s `ImpactStudyResult`), but it does not
produce one.

**ROI** is a ratio of a valuation to a cost. It inherits every weakness of the valuation it is
built from, plus whatever imprecision the cost side carries. A ROI computed from an unverified
model estimate is not made more certain by the division; it is simply a ratio of one soft
number to one hard one.

**What this skill can produce today:** output (observed), a coarse outcome signal (self-
verified success/failure), and valuation (a model-estimated hypothesis). **What it cannot
produce:** a verified outcome (nothing downstream is observed), impact (no identification
strategy runs), or a ROI grounded in anything stronger than its own valuation input.

## The results chain

The five distinctions above are definitional. This chain is what makes them operational — an
ordered sequence from the moment an agent acts to the moment a business outcome could, in
principle, be monetized. Each link names the evidence that would be needed to assert it, and
whether this skill actually observes that evidence.

1. **Execution** — the agent ran. Observed directly (the session exists).
2. **Output** — the agent produced something. Observed directly (the transcript, self-
   verified per the job-declaration `SUCCESS` bar).
3. **Acceptance** — a human or system accepted the output. Would require a merge event, a
   review approval, or an equivalent downstream signal. Not observed by this skill.
4. **Adoption** — the accepted output was actually used. Would require usage telemetry from
   whatever the output was integrated into. Not observed.
5. **Operational outcome** — using it changed some operational metric (fewer incidents, faster
   cycle time). Would require a system-of-record adapter reading that metric before and after.
   Not observed; see "What this milestone does not ship" below.
6. **Business outcome** — the operational change moved a business metric (revenue, retention,
   cost). Would require attribution work well beyond this skill's scope. Not observed.
7. **Monetized value** — the business outcome was converted to a dollar figure under a
   defensible method. This skill computes a number here, but it computes it from links 1–2
   directly, skipping links 3–6 entirely — an assumed hours-saved figure standing in for
   the whole unobserved middle of the chain.

Read this way, `llmOutcomeEvaluation`'s valuation is not a measurement of link 7 — it is a
model's guess at what link 7 might be, made without evidence for links 3 through 6 ever
existing. That gap between "the number this skill emits" and "the chain that number claims to
summarize" is the single fact the rest of this page exists to keep visible.

## Evidence labels and the product-truth boundary

Every assessment this skill produces carries an `evidence_class` — one of nine labels. They
are a set of **distinct claim kinds**, not a confidence ladder ranking one label above
another. The nine labels, their exact spellings, and the resolution rule that assigns one to
a given assessment are owned by
[`references/job-declaration.md`](../skills/revenium/references/job-declaration.md)'s "The
nine evidence-class labels" section — this page does not re-enumerate them.

Why a ladder is the wrong mental model: customer confirmation may be commercially
authoritative — a customer said the outcome happened — yet causally weak, because a customer
confirming an outcome is not the same as observing that the agent's work caused it.
Observation proves occurrence, not cause — seeing an event happen does not establish what
made it happen. Configuration establishes an approved rate, not actual hours worked — a
rate card tells you what an hour is worth, not how many hours a task actually took. And a
classifier's confidence score is predictive, not causal — it measures how sure a model is
about its own output, not whether that output reflects reality. None of these four is simply
"more" or "less" trustworthy than the others in a single dimension; each fails in a different
way, which is why the labels sit side by side rather than in a rank order.

### The product-truth boundary

This is the boundary that matters most for anyone reading a number this skill reports, so it
gets stated plainly rather than left as a passing remark.

A live verification against a real Revenium tenant found that `revenium jobs roi <id>`
surfaces no `evidence_class`, no `evaluator`, and no `confidence` in either its JSON or its
table output. A model-estimated value is displayed with the exact same visual weight a
measured value would get on that read-back surface. Only the separate `jobs outcome-history`
command echoes the metadata blob at all.

**The honesty burden for stating that a value is an unverified model estimate rests entirely
on this skill's own `--metadata` payload and on documentation like this page — not on
anything Revenium's primary read-back surfaces.** Revenium's product does not draw the
distinction this page draws; nothing downstream of the wire enforces it. If this skill's
`--metadata` payload ever stopped carrying `evidence_class`, or if a reader never opened this
page, an estimate and a measurement would be visually indistinguishable to anyone looking at
`jobs roi`. That is the boundary: the product tells the truth only as far as this skill's own
metadata and documentation carry it, and no further.

## Why a model-estimated value is a hypothesis

The naked-LLM evaluation path always resolves to the `MODEL_ESTIMATED_DEMO` evidence class.
Four reasons that class is a hypothesis rather than an established result:

1. **The figure is derived, not asserted.** `estimated_value` is computed as
   `estimated_hours_saved x assumed_loaded_rate` from two independently capped assumption
   inputs — it is never a number an evaluator states directly and this skill just forwards.
2. **The assumptions are recorded alongside the figure**, not hidden behind it — a reader
   can see the hours and the rate that produced the number, not just the number.
3. **Nothing in the path observes the claimed outcome occurring.** The evaluator reasons over
   the session transcript alone; no downstream system confirms the outcome actually happened.
4. **The reportability resolver, not the evaluator, decides whether the number may leave the
   machine at all.** A computed value and a reportable value are two different gates, and an
   evaluator's opinion about its own estimate never overrides the resolver's decision.

What `MODEL_ESTIMATED_DEMO` means in full, and the rule that a future non-LLM evaluator must
report its own, different evidence class rather than widening this one, is owned by
[`references/job-declaration.md`](../skills/revenium/references/job-declaration.md)'s "What
`MODEL_ESTIMATED_DEMO` means" section — read it there.
