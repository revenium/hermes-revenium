# Claim distinctions and evidence boundaries

[← Back to the docs index](README.md)

This page is repo-only — it is not part of the skill bundle and a tap-installed host never
sees it. It owns the conceptual frame this milestone needs and that no shipped file owns:
the distinctions between output, outcome, valuation, impact, and ROI; the chain that connects
them; the product-truth boundary; the vocabulary this project uses; and what this milestone
deliberately does not ship. Every contract term — the nine evidence labels, the config keys,
the assessment schema — stays owned by the shipped references this page links to. This page
never duplicates a contract; it only explains the frame the contracts sit inside.

Once the frame is clear, [Job value and ROI](value-and-roi.md) is the mechanism: how the
number is produced, bounded, recorded, and reported.

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

## The vocabulary this project uses

Five phrases are the allowed vocabulary for describing what this skill's numbers are, drawn
directly from this project's requirements. Each is right for a specific claim:

- **"model-estimated value"** — the right term for the naked-LLM path's output: a number a
  model derived, not one anyone observed.
- **"configured value estimate"** — the right term when describing a valuation produced by an
  operator-configured, non-LLM boundary (a rate-card fixture, for example) rather than the
  naked-LLM evaluator.
- **"observed outcome"** — the right term only when this skill (or a system-of-record adapter
  it does not yet ship) has actually seen the outcome occur, not merely inferred or assumed it.
- **"associational result"** — the right term for a correlation-shaped finding that stops short
  of a causal claim — an `ASSOCIATIONAL` evidence-class record, for example.
- **"estimated ROI under stated assumptions"** — the right term for a ratio derived from a
  model-estimated value, when the assumptions the estimate rests on are stated alongside it.

A second, prohibited set of phrases also exists, and it is machine-enforced across every
shipped text file in this repository — not just documentation. Rather than quote the five
prohibited phrases here (which would defeat the guard's own purpose the moment this page
shipped), this page describes what each one asserts: a claim of measurement where none was
taken, a claim of realized saving where only an estimate exists, a claim of agent causation
where no identification strategy ran, a claim of established business value where only a
hypothesis exists, and a claim of causal effect where at most an association was observed.
For the exact literal strings, read
[`tests/test_repository.py::test_no_prohibited_claim_language_left`](../tests/test_repository.py)
— the disallowed strings live in that test's own pattern list, exactly as `CLAUDE.md`'s
"Legacy naming guards" section already instructs for this repository's legacy-branding list.

The allowed vocabulary above is guidance only — no test asserts that any of the five allowed
phrases appears anywhere in shipped text, and that is deliberate. A presence assertion would
either pass vacuously (nothing requires prose to use these exact words to be honest) or force
stilted, repetitive writing every time a number is mentioned. The prohibited list is a floor;
the allowed list is a suggestion for clearing it comfortably.

## Configuration and privacy modes

The whole `llmOutcomeEvaluation` feature is opt-in and off by default, and every read of its
configuration fails closed: a missing, unreadable, or malformed config resolves to disabled,
never to estimating money by accident. A second, separate switch decides whether a computed
value may be reported to Revenium at all — a value can be computed and retained locally while
its number is withheld from the wire, which is a different question from whether evaluation
runs in the first place. Cost inputs (a `costs` block, keyed by job type and cost category)
are entirely operator-supplied and net against the computed estimate; this skill invents no
cost figure of its own. The exact key names, defaults, and validation rules for all of this
are owned by [`docs/configuration.md`](configuration.md) and
[`references/config-schema.md`](../skills/revenium/references/config-schema.md) — this page
links to them rather than restating them.

Separately, every job assessment records two observable facts about the configured LLM: the
resolved inference provider name, and a derived address class describing where inference was
**configured** to run. Both describe the CONFIGURED endpoint, not anything this skill actually
watched happen along the way. The skill can observe only where inference was configured to go;
it cannot observe the preprocessing, logging, or retention parts of that path, so it records
only the part it can see and draws no conclusion from the rest. Nothing on this page, or
anywhere else this skill ships, should be read as a statement about where data went, was kept,
was logged, or was retained — in either a stated or a negated form. The two configured-locality
facts are inputs to an operator's own judgment about their own deployment, not a conclusion
this skill draws on the operator's behalf.

## Plugin contracts

Six pluggable boundaries exist as named contracts a later implementation can fit behind:
classification (turn-level `task_type` labelling and job/arc inference), output/outcome
assessment (the evaluator that produces or withholds an `assessment`), economic valuation (how
an accepted outcome converts to a number), evidence resolution and reportability (which
`evidence_class` a boundary declares and whether the result may be reported), cohort impact
(a contract only — no estimator ships), and Revenium reporting. Each is a registry: an
implementation registers a name, and an operator selects among registered implementations by
that name.

The rule that gives these contracts their value: **a non-LLM implementation reports its OWN
evidence class rather than masquerading as an LLM evaluator.** A deterministic rate-card
valuation does not borrow the naked-LLM path's evidence class just because it produces a
similar-looking number; it declares its own, honest label. This is what makes "fits without
masquerading" a structural property rather than a promise — a later ONNX classifier,
deterministic policy, vertical model, or system-of-record adapter can be added behind these
contracts without ever pretending to be the model that isn't there.

The selector keys an operator sets to choose among registered implementations — the
`boundaries` object's `classification`/`valuation`/`evidence` fields, and
`llmOutcomeEvaluation.evaluator` for the output/outcome-assessment boundary — are owned by
[`references/config-schema.md`](../skills/revenium/references/config-schema.md); the nine
evidence-class labels and the resolution rule that assigns one to an assessment are owned by
[`references/job-declaration.md`](../skills/revenium/references/job-declaration.md).

## Correction and audit

This section is written from what a real, currently-passing test observes, not from prose —
per D-18, so the worked example cannot drift from what the code actually does. The source is
[`tests/test_phase47_end_to_end.py::test_operator_correction_appends_a_revision_and_ships_its_marker`](../tests/test_phase47_end_to_end.py).
A future reader can check the description below against that test directly; if the two ever
disagree, the test is the one to trust.

An operator corrects a job's assessment through `correct-assessment.sh`, a human-facing
terminal command that requires `--job-id`, `--value`, `--currency`, and `--reason`. The
correction **appends** a revision line to the job's assessment sidecar record; the observed
test confirms the original line is byte-unchanged after the append — a correction is never a
rewrite. Each appended revision carries a `sequence` number that orders it relative to any
earlier corrections, starting at `1` for the first correction against a given job. The
appended revision also carries the record it superseded (`prior_value_low`,
`prior_value_base`, `prior_value_high`, `prior_currency`), so the append is a complete history,
not just a new number replacing an old one.

The corrected bound is what ships: the observed test confirms the wire call's
`--outcome-value` equals the appended record's own corrected low bound, read off the record
that was just written — never a value retyped anywhere else. The wire call's `--metadata`
carries the same `sequence` number and the same prior-value fields the local record carries —
this is the marker a downstream consumer uses to tell a revision from an original, since an
ordinary, uncorrected `jobs outcome` payload never carries a `sequence` key at all.

The correction path is deliberately unreachable from the per-minute cron pipeline —
`correct-assessment.sh` is never named in `cron.sh` or `install-cron.sh`. It exists only as an
action a human operator takes at a terminal, on purpose, never as something the automated
pipeline could trigger on its own.

## Abstention, zero, and negative value

Three distinct "no positive number" outcomes exist, and this skill keeps them visibly distinct
from each other and from an ordinary valued outcome — each is driven and observed by its own
test in `tests/test_phase47_end_to_end.py`.

- **The evaluator declines.** When the evaluator abstains rather than producing an assessment,
  the job's outcome still reports to Revenium, carrying provenance (`evaluator`,
  `evaluator_version`) but no value flags at all — a real, provenance-bearing record, not a
  silently dropped report. Observed by
  `test_abstention_path_ships_outcome_with_provenance_and_no_value`.
- **The reportability gate is closed.** When a value is computed but the separate reportability
  switch is off, the estimate is computed and retained locally — the sidecar carries a real
  `value_low` — while the number itself is withheld from the wire; provenance
  (`evidence_class`, `evaluator`, `evaluator_version`, `model`) still ships, and
  `reportability_status` reads `candidate` rather than `reportable`. Observed by
  `test_withheld_candidate_path_withholds_value_and_keeps_provenance`.
- **Supplied costs meet or exceed the estimate.** When an operator-supplied cost is at or above
  the derived value, `net_value` goes to or below zero — and the record stays visible on both
  the sidecar and the wire, rather than being clamped to zero, suppressed, or dropped. Observed
  by `test_negative_net_value_stays_visible_with_the_value_family_intact`.

Why this matters: work that produced no value and work that was never valued must not look the
same in the data. An abstained outcome, a withheld candidate, and a negative net value are each
a different, honest fact about a job — collapsing any of them into a blank or a zero would
erase the distinction between "nothing to report" and "something to report, but not this way."

## What this milestone does not ship

Every item below is stated as an absence, not as something scheduled. Nothing here is a
commitment about what happens next; it is a record of what this tree does not contain today.

**No local classifier model ships here.** Classification and outcome evaluation both run
through an LLM call on the operator's own configured provider. Nothing in this tree runs an
on-device or locally-hosted model of any kind.

**No customer-configured value policy produces a recorded value here.** The pluggable
boundaries exist as contracts and carry non-LLM fixtures proving they fit, but nothing in this
tree turns an operator's own rate card, pricing table, or business rule into the class
actually written to a persisted record.

**No system-of-record outcome adapter ships here.** Nothing in this tree observes a downstream
system — a ticketing tool, an incident tracker, a revenue system — to confirm that a claimed
outcome occurred. Every outcome this skill records is self-reported by the classifier from the
session transcript alone.

**Nothing here produces a causal claim.** The impact-study structure is a contract only — no
estimator, no experiment orchestration, nothing that runs an identification strategy. An
individual job may carry a reference to such a study without that reference letting a cohort
estimate stand in for an individually observed cause. No evaluator anywhere in this tree can
produce either of the two impact-shaped evidence classes; this is enforced structurally, not by
convention or reviewer discipline.

**The relationship between a job assessment and an impact study result is not implemented.**
This is stated as an absence, not a partial feature: an assessment carries a slot that could
reference a study, and nothing in this tree fills that slot and nothing reads it.

### Two requirements recorded as partial rather than closed

**EGV-02 — a later implementation fits without masquerading.** True today: all six pluggable
boundaries exist as registries, and each carries a non-LLM fixture that declares its own,
honest evidence class rather than borrowing the naked-LLM path's `MODEL_ESTIMATED_DEMO`. Not
true today: a configured boundary's own declared class does not reach the persisted record —
resolution runs against the evaluators registry only, so an active valuation or evidence
boundary's declared class is not what ends up on the sidecar. The recorded class therefore
under-claims rather than over-claims, which is the safe direction — no record ever shows more
certainty than it should. This was left open rather than patched because closing it needs a
cross-boundary precedence rule that no decision covers — which class wins when the evaluator,
the valuation boundary, and the evidence boundary each declare one — and because letting a
boundary declaration raise a recorded class is the same mechanism as the promotion path this
product structurally closed elsewhere; patching around that mechanism here would reopen it by
a side door.

**EGV-05 — six economic mechanisms are representable.** True today: all six mechanism values
are representable on the wire and accepted by the reporter's allow-list. Not true today: three
of the six — the operator-declared mechanisms — have no producer anywhere in this tree. No
configuration key sets one, no CLI flag sets one, and the correction path does not set one
either. They are representable and accepted; they are not reachable.

Both gaps are recorded in full, including their re-deferral history, in
`.planning/REQUIREMENTS.md`. That file is the authoritative record of both; this page states
them here so a reader who never opens the gitignored planning tree still sees them.
