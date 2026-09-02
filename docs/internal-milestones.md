# Internal milestone closeouts

Engineering evidence for shipped planning milestones is tracked here because the
planning tree (`.planning/`) and evidence tree (`docs/internal/`) are both
gitignored. A closeout recorded only there disappears with the working tree, as
the 2026-06-06 roadmap reconstruction showed.

Planning milestones and product git tags share numbers but are separate
namespaces. Milestones from "LLM-Estimated Agentic Job Outcomes and ROI" onward
are name-only and are not tagged, after an earlier "v1.5" label collided with an
unrelated shipped product tag.

---

## Evidence-Graded Agentic Job Value and ROI — shipped 2026-08-28

**Phases:** 41–47 · **Plans:** 40 · **PRs:** #93–#102 · **Range:** `c241a29`..`37fb6f6`
**Closeout type:** `override_closeout` · **Requirements:** 25 of 27 complete, 2 partial
**Not tagged**, by the milestone's own instruction.

### What this milestone was for

The experimental naked-LLM job-value path produced a number that looked like a
return figure and was not one. Prediction, valuation and return were collapsed
together, derived from a single economic mechanism, and carried a single forced
evidence label.

The work separated the claims. Each now has its own representation, evidence
label, and gate:

| Claim | Question it answers |
|---|---|
| Prediction / classification | What kind of job was performed? |
| Output | What artifact or state change was produced? |
| Outcome | Was it accepted, used, sustained, reversed, or followed downstream? |
| Valuation | What is that outcome worth under explicit assumptions? |
| Impact | What changed *because of* agent use, against a counterfactual? |
| Return | Incremental monetized benefit net of incremental cost, over a declared basis |

**The governing rule.** The model may classify jobs, assess outputs and outcomes,
identify economic mechanisms, and propose valuation assumptions. It must never be
*able* to claim it established causation. Where a requirement could be satisfied
by policy or by construction, construction was chosen — the previous milestone's
`evidence_class` was safe only because a single value existed, and that safety
disappears the moment there are nine.

### What shipped

- **Nine evidence labels that do not form a confidence ladder.** Customer
  confirmation may be commercially authoritative yet causally weak; observation
  proves occurrence, not cause; configuration establishes an approved rate, not
  hours actually spent. The naked-LLM path emits `MODEL_ESTIMATED_DEMO` and is
  **structurally unable** to promote past it — proven by adversarial fixture,
  not asserted by convention.

- **Six mechanism-typed economic claims** replacing `estimated_hours_saved ×
  assumed_loaded_rate`, with net value across all supplied costs, explicit
  zero and unknown denominators, double-counting controls, and zero and negative
  work staying visible rather than disappearing.

- **A versioned sidecar carrier.** The assessment moved from the 1024-byte marker
  line, already 70% consumed by six fields, to a job-id-keyed JSONL under
  `${STATE_DIR}/job-assessments/`. The choice used measured sizes, and none of
  the stated falsification conditions occurred.

- **Provenance that survives.** Model, prompt, taxonomy, policy and schema
  versions persist through deferred job creation and retry, proven by two real
  `hermes-report.sh` subprocess ticks across a forced `jobs create` failure
  rather than by mocks.

- **Corrections that append.** `revenium jobs outcome-update` server-side;
  appended `kind:"correction"` sidecar lines as the local complete history. The
  original assessment is never destructively replaced.

- **Six pluggable boundaries as real contracts** — classification, output/outcome
  assessment, economic valuation, evidence resolution and reportability, cohort
  impact (contract only), and Revenium reporting. Host-agnostic, so the core can
  later be extracted to `revenium-task-classifier`. Proven extensible by non-LLM
  fixtures each declaring a distinct, non-masquerading evidence class; no fixture
  makes a model call.

- **`ImpactStudyResult` as a contract only** — fields, no estimators, no
  experiment orchestration, and no import edge toward Hermes.

- **A bounded safety envelope.** A byte-clamped metadata ceiling, a
  dynamically-enumerated canary sweep with a *binding* vacuous-pass guard
  (proven binding by a negative control), honest inference-locality disclosure,
  and byte-identical feature-off behaviour.

- **CI-enforced language.** `tests/test_repository.py::test_no_prohibited_claim_language_left`
  scans the whole shipped tree — not just Markdown — in the shape of the existing
  legacy-name guards. Confirmed non-vacuous by injection probe.

- **An end-to-end harness** driving the real classifier and reporter from
  transcript through segmented job, structured assessment, `MODEL_ESTIMATED_DEMO`
  valuation, reportability resolution, and safe job outcome metadata.

Test code outweighs shipped code roughly 2.6:1 (+17,423 test lines against
+6,662 plugin and shell lines). The tests demonstrate the safety property with
adversarial cases.

### Known gaps

The successor phase's context document records and re-defers both gaps.

**EGV-02 — cross-boundary evidence-class precedence is undecided.** A configured
boundary's declared `evidence_class` does not reach the persisted record;
`_declared_evidence_class` resolves against the evaluators registry only. When
`boundaries.valuation` or `boundaries.evidence` names a fixture declaring
`CUSTOMER_CONFIGURED` or `CUSTOMER_CONFIRMED`, the sidecar still records the
evaluator's class. Found by external review on PR #100 and confirmed against
source.

The error is in the **safe** direction. `MODEL_ESTIMATED_DEMO` is the weakest
label, so the record under-claims rather than over-claims, and the
promotion-blocking architecture is not breached. It was deferred rather than
patched because closing it requires a genuinely new precedence rule (which class
wins when evaluator, valuation and evidence each declare one), and because any
rule that lets a boundary declaration *raise* the recorded class is structurally
the promotion path this milestone closed — sourced from trusted configuration
rather than model output, but the same mechanism. That belongs in a design
discussion, not a patch.

**Superseded 2026-08-29 (Phase 48) —** a registration-time declaration by
trusted code and untrusted model output are two different threat models, not
the same mechanism reached from a different source. The paragraph above
concludes that any rule letting a boundary declaration raise the recorded
class is structurally the promotion path this milestone closed — "sourced
from trusted configuration rather than model output, but the same
mechanism." That final clause is what the corrected understanding disagrees
with. Trust attaches to the registrant's own in-repo top-level
`register(...)` call, written by the same code that defines `fn`, at import
time — not to `config.json`'s `boundaries` object, which selects *which*
registrant is active (`_boundary_impl_name`, `classifier.py:2860`) and never
authors a class. `classifier.py:1160`'s threat-model argument is the record
that stands. Phase 48 changes no runtime behaviour: a configured boundary's
declared class still does not reach the persisted record, and
`_declared_evidence_class` still resolves the evaluators registry alone —
the correction is to the *reasoning* that made EGV-02 look unclosable, not
to the *facts* of the gap. See `docs/evidence-class-precedence.md`,
particularly `## The reconciliation verdict` and `## The precedence rule`,
which together make EGV-02 closeable in Phase 50 rather than a permanent
won't-fix; see `## The won't-fix trigger` for the conditions under which it
would still close unbuilt.

**EGV-05 — the operator-declared mechanisms had no producer.** As recorded at
the close of phases 41-47 this was true of all three:
`quality_decision_improvement`, `risk_avoidance` and `incremental_revenue` were
declared and would forward on the wire, but nothing could set them. Two
producers have since landed — `correct-assessment.sh --mechanism` (Phase 51)
and a valuation registrant declaring one at registration (Phase 54, where the
shipped `revenueCard` fixture declares `incremental_revenue`) — so the
statement above stands only for `quality_decision_improvement` and
`risk_avoidance`, whose intended producer remains a study reference
(`studyId`/`studyVersion`). The evaluator still cannot select any of the three,
which is deliberate rather than outstanding.

### Limits of what was demonstrated

- **No live-tenant run.** The end-to-end proof is a produced-artifact harness
  driving the real classifier and reporter around a stubbed model response. The
  previous milestone's live proof stands only for the paths it covered; nothing
  in phases 41–47 was exercised against a real tenant.

- **`revenium jobs roi` still surfaces no provenance.** Server API changes were a
  declared non-goal, so "reportable" means retained in a bounded metadata
  envelope or held locally — never *visible in Revenium's return view*.

- **Whether real sessions cluster near the value bounds is still unmeasured**,
  carried forward from the previous milestone.

### Decisions worth carrying forward

1. **Open a milestone with reconciliation when the specification describes an
   architecture nobody has re-read.** Phase 41 changed no production behaviour
   and reshaped every phase after it, correcting four scoping-time findings and
   surfacing two more.

2. **A safety property that holds because only one value exists is not a safety
   property.** Ask what makes an invariant true before widening its domain.

3. **State falsification conditions before running the measurement** that decides
   a design question.

4. **Prove every new guard non-vacuous** in the same change that adds it, by
   injection probe or negative control.

5. **Record the direction of an error.** EGV-02 was deferrable precisely because
   it under-claims; that fact turned a would-be blocker into a documented gap.

### Archive pointers

The full roadmap, requirements traceability, and phase artifacts are in the
gitignored planning tree:

- `.planning/milestones/ROADMAP-evidence-graded-value.md`
- `.planning/milestones/REQUIREMENTS-evidence-graded-value.md`
- `.planning/milestones/evidence-graded-value-phases/`
- `.planning/RETROSPECTIVE.md`

User-facing documentation for what this milestone shipped lives in
`docs/claim-distinctions-and-evidence-boundaries.md`.
