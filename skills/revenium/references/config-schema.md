# config.json Schema

## Overview

`config.json` is the runtime configuration file for the Revenium skill. It is written
during setup and read by the cron pipeline on every tick. Location:
`~/.hermes/state/revenium/config.json` (declared as `CONFIG_FILE` in `common.sh`).
Its schema defines the interface between the setup flow and the cron pipeline.

## Fields

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `ruleIds` | array of strings | Active (v1.3) | IDs of Revenium guardrail rules to enforce. Written by `/revenium setup` (Phase 18); consumed by `guardrail-check.sh` (Phase 19). |
| `alertId` | string | Deprecated (v1.2) — orphaned by auto-migration; legacy alert preserved server-side; clean up manually in Revenium UI | Legacy budget-alert ID from v1.2 and earlier. No longer written or read by v1.3+ scripts; preserved in `config.json` after migration. |
| `autonomousMode` | boolean | Active | When `true`, a budget breach automatically halts the agent and triggers a notification. |
| `notifyChannel` | string | Active (required when `autonomousMode` is `true`) | Messaging channel for halt notifications (e.g., `slack`, `discord`). |
| `notifyTarget` | string | Active (required when `autonomousMode` is `true`) | Channel-specific target for halt notifications (e.g., `channel:<id>`, `user:<id>`, `@username`). |
| `organizationName` | string | Active (optional) | Used as `--organization-name` on metered transactions for Revenium attribution. |

## ruleIds

`ruleIds` is the active v1.3 replacement for the legacy `alertId` field. It holds an
array of Revenium guardrail rule IDs that the skill enforces on every cron tick. An
empty array or absent key means no guardrail rules are active; the cron pipeline
treats this as a no-op for enforcement and continues metering normally.

## alertId (Deprecated v1.2)

`alertId` was the budget-alert identifier used by v1.2 and earlier. It is orphaned by
the v1.3 auto-migration: the migration writes `ruleIds` and no longer touches `alertId`.
The corresponding budget alert is preserved server-side on Revenium and is never
auto-deleted; operators who no longer need it should clean it up manually in the
Revenium UI.

## autonomousMode

When `autonomousMode` is `true`, a budget breach detected by the cron pipeline
automatically sets `halted: true` in the guardrail status file and triggers a
notification via the configured channel and target. When absent or `false`, the cron
records the breach but does not halt the agent.

## notifyChannel and notifyTarget

These two fields work together and are only meaningful when `autonomousMode` is `true`.
`notifyChannel` identifies the messaging platform (e.g., `slack`, `discord`);
`notifyTarget` identifies the recipient within that platform using the channel-specific
format (e.g., `channel:C0123456789`, `user:<id>`, `@username`).

## organizationName

A human-readable label for the Revenium organization. When present, it is passed as
`--organization-name` on every metered transaction. It is optional; omitting it
skips the flag entirely on the `revenium meter completion` call.

---

# guardrail-status.json Schema

## Overview

`guardrail-status.json` is the runtime enforcement-status file written by `guardrail-check.sh`
on every cron tick. Location: `~/.hermes/state/revenium/guardrail-status.json` (declared as
`GUARDRAIL_STATUS_FILE` in `common.sh`). It is the coupling point between the cron pipeline
(writer) and the shell hooks (`pre_llm_call.sh`, `pre_tool_call.sh`) and the SKILL.md backstop
(readers). The cron pipeline writes this file; the hooks and the SKILL.md procedural block read
it on every Hermes turn.

## Top-Level Fields

| Field | Type | Present when | Description |
|-------|------|--------------|-------------|
| `halted` | boolean | Always | `true` when `autonomousMode` is on and at least one rule is in `block` state. |
| `haltedAt` | string (ISO-8601) | `halted: true` only | Timestamp of the first halt transition for the current halt epoch. Carried forward on subsequent cron ticks while halt persists; removed on clear. |
| `haltedRule` | object | `halted: true` only | Pre-computed tiebreaker rule (first blocked rule in `ruleIds[]` declaration order, D-04). See haltedRule Extension below. |
| `autonomousMode` | boolean | Always | Mirrors `config.json::autonomousMode` at time of last cron tick. |
| `lastChecked` | string (ISO-8601) | Always | Timestamp of the most recent `guardrail-check.sh` run. |
| `rules` | array | Always | Per-rule state array; see `rules[]` Fields below. |

## `rules[]` Fields

| Field | Type | Description |
|-------|------|-------------|
| `ruleId` | string | Revenium-hashed rule ID; same format as `config.json::ruleIds`. |
| `name` | string | Rule name as declared in Revenium. |
| `metricType` | string | Metric being enforced (e.g., `TOTAL_COST`). |
| `windowType` | string | Billing window (e.g., `MONTHLY`). Mapped from API `periodType`. |
| `groupBy` | string | Grouping dimension (e.g., `ORGANIZATION`). |
| `currentValue` | number | Current value of the metric. |
| `warnThreshold` | number | Warn-band threshold. |
| `hardLimit` | number | Hard-limit threshold. Mapped from API `threshold`. |
| `state` | string | Derived state: `ok`, `warn`, or `block`. `block`: metric has breached the hard limit. `warn`: metric has breached the warn threshold but not the hard limit. `ok`: neither threshold breached. |
| `shadowMode` | boolean | `true` when the rule is in shadow mode — its breaches are recorded (`state: "block"`) but excluded from the top-level `halted` decision, so agent traffic flows unimpeded. Defaults to `false`. |
| `lastChecked` | string (ISO-8601) | Timestamp of this rule's last update. |

### shadowMode

When `shadowMode` is `true`, the rule's evaluations are recorded but it cannot cause
the top-level `halted` flag to flip to `true`; agent traffic flows unimpeded. A
shadow-mode rule that breaches its `hardLimit` still shows `state: "block"` in this
file so dashboards and analytics show the breach. Only the agent-halt decision
is suppressed. Use this mode to validate a new rule's enforcement behavior
against real traffic before flipping the server-side `shadowMode` flag off
(`revenium guardrails budget-rules update <id> --shadow-mode=false`).

When a shadow-mode rule transitions from `state: "ok"` or `state: "warn"` into
`state: "block"`, `guardrail-check.sh` emits a one-shot `[shadow]`-prefixed
operator notification via the same Hermes messaging path used for hard halts.
Re-runs while the rule remains in shadow-block state are silent.

## `haltedRule` Extension (D-04)

When `halted` is `true`, the top-level `haltedRule` block is pre-computed by
`guardrail-check.sh` from the first blocked rule in `config.json::ruleIds` declaration
order. Hook scripts and the SKILL.md backstop read this pre-resolved block instead of
implementing separate tiebreaker logic. When `halted` is `false`,
`haltedRule` is absent entirely.

The `haltedRule` block contains a subset of `rules[]` fields: `ruleId`, `name`,
`metricType`, `windowType`, `currentValue`, and `hardLimit`. The fields `groupBy`,
`warnThreshold`, `state`, and `lastChecked` are intentionally omitted. Hooks only
need the static rule identity and current breach values to render the halt message.

## `llmOutcomeEvaluation` (v1.5, opt-in, experimental)

Opt-in LLM estimation of a job's economic outcome value. **Disabled by default.**
Absent from `config.json` is the same as disabled.

```json
{
  "llmOutcomeEvaluation": {
    "enabled": false,
    "evaluator": "llm",
    "currency": "USD",
    "maxHoursSaved": 40,
    "maxLoadedRate": 500,
    "costs": {
      "bug_fix": {
        "human_review": 25,
        "handoff": 0
      }
    },
    "rateCard": {
      "backend_engineer": 150,
      "support_specialist": 45
    }
  }
}
```

| field | default | purpose |
|---|---|---|
| `enabled` | `false` | Must be a **literal JSON boolean** `true`. The string `"true"`, the integer `1`, and `"yes"` all leave the feature off. |
| `evaluator` | `"llm"` | Which registered evaluator to use. |
| `currency` | `"USD"` | ISO 4217. An assessment naming a different currency is rejected. |
| `maxHoursSaved` | `40` | Upper bound on the estimated hours saved. |
| `maxLoadedRate` | `500` | Upper bound on the assumed loaded hourly rate. |
| `rateCard` | absent | Object keyed by the evaluator's inferred role; a matching role's amount replaces the `hours x rate` derivation. Selected via `boundaries.valuation = "rate_card_valuation_fixture"`. Nests **inside** `llmOutcomeEvaluation` — see "The placement trap" below. |
| `revenueCard` | absent | Object keyed by an operator-bound identity; each entry prices a completed booking. Selected via `boundaries.valuation = "revenue_card_valuation_fixture"` together with `revenueCardKey`. Nests **inside** `llmOutcomeEvaluation` — see "The placement trap" and "`revenueCard`" below. |
| `revenueCardKey` | `""` | The non-empty string naming which `revenueCard` entry applies on this host, read from configuration only. |
| `maxRevenueValue` | absent | Optional ceiling on a configured revenue amount, consulted only when the producing registrant declared and had accepted an operator-only mechanism for the call. See "`maxRevenueValue`" below. |
| `experimentalReportEstimates` | `false` | Must be a **literal JSON boolean** `true`, same discipline as `enabled`. Governs EGV-18's `reportability_status`, not whether an estimate is computed. **As of Phase 53 this flag alone is necessary but no longer sufficient** — see "Reporting the estimate's value" below for the record's evidence-class gate this flag now composes with. |
| `studyId` | `""` | A non-empty string naming an `ImpactStudyResult` this install's job assessments reference. Recorded on every assessment this install produces; never changes an assessment's own `evidence_class` (EGV-13, D-08). |
| `studyVersion` | `0` | A plain integer >= 1, paired with `studyId`. The pair is **all-or-none in both directions**: if either field is missing or malformed (a blank `studyId`, a non-integer or `< 1` `studyVersion`), both resolve to their absent defaults. A half-reference could never name a real `ImpactStudyResult`, so none is recorded. |
| `costs` | `{}` | An object keyed by job type (EGV-14). Each job type's value is an object whose keys are drawn from the four `COST_CATEGORIES` names — `human_review`, `rework_or_error`, `handoff`, `training_or_change`. There is **no fleet-wide default bucket**: an absent job-type key means every category is unknown for that job type, exactly as if `costs` were absent entirely. A supplied `0` is knowledge and participates in the subtraction as a known zero; an absent category is unknown and does not participate (D-10) — these are different and both explicit. A malformed, non-numeric, boolean, or negative value resolves that category to unknown, never to zero. |

### Rate card and revenue card (ROI-05, ROI-06, ROI-07, ROI-08)

Two config-driven, non-model alternatives to the `hours x rate` derivation, each
selected through `boundaries` (documented further below). Both nest **inside**
`llmOutcomeEvaluation` — the same place `costs` and `maxHoursSaved` already live.

**The placement trap.** `rateCard`, `revenueCard`, `revenueCardKey` and
`maxRevenueValue` all nest inside `llmOutcomeEvaluation`. `boundaries` is read
from the **TOP LEVEL** of `config.json`, as a **sibling** of
`llmOutcomeEvaluation`, not from inside it — a different placement rule for an
adjacent surface. That is the exact shape that made a production host's
`rateCard` structurally invisible: the host nested it as a top-level sibling of
`llmOutcomeEvaluation`, following `boundaries`' placement rule instead of
`rateCard`'s own, and 85 sessions went unpriced with no error anywhere (Phase
53). **A wrongly-nested card is not an error** — resolution fails open, so the
resolver simply never sees a misplaced card and the boundary silently keeps its
built-in derivation, with no log line to say so. That silence is exactly why
this note exists: read it before configuring either card.

#### `rateCard`

An object keyed by the evaluator's inferred role (`assumptions.inferred_role`
— model-produced text, e.g. `"backend_engineer"`); each value is the approved
hourly rate for that role. When `boundaries.valuation` selects
`"rate_card_valuation_fixture"` and the inferred role matches a key in the
card, the matching amount **displaces the `hours x rate` derivation entirely**
— the hours side of the arithmetic is not consulted for the amount, though it
still rides the record as an evaluator assumption. Declares
`CUSTOMER_CONFIGURED`.

Its honest limit, in the code's own words: **configuration establishes an
approved RATE, not actual hours worked.**

#### `revenueCard`

An object keyed by an **operator-bound** identity — the agent, profile, or
squad name the operator chooses, never a value read from the model. Selected
via `boundaries.valuation = "revenue_card_valuation_fixture"` together with
`revenueCardKey` below. Each entry is an object:

| entry field | required | notes |
|---|---|---|
| `grossPerJob` | yes | A finite number greater than zero — the approved value per completed booking. |
| `attributionFraction` | no | A finite number from 0 through 1, both endpoints legal — but see the note on `0.0` below. |
| `attributionBasis` | required whenever `attributionFraction` is present | The stated basis the fraction rests on, clamped to 500 serialized bytes. |

`attributionFraction` and `attributionBasis` **travel as a set in both
directions** — the same rule `correct-assessment.sh --attribution-fraction`
already enforces on its own CLI flag pair (documented below). One present
without the other abstains the whole entry.

When both are configured, the skill **multiplies `grossPerJob` by
`attributionFraction` and records only the product** — `estimated_value`. The
gross figure itself reaches no persisted record, no `meter` argv, no
`--metadata` envelope, and no log line. See `docs/value-and-roi.md`'s
Attribution section for the full reasoning behind this narrow reversal of a
prior decision (D-09).

**A fraction of exactly `0.0` validates but produces no record.** It is legal
input and the multiplication yields `0.00`, but a configured valuation is held
to a strictly-positive lower bound, so the assessment then abstains. Nothing is
misreported and no error is raised — the job simply reports its outcome with no
value. If you mean "this work is attributed nothing", omitting the entry says
so more clearly than a zero fraction does.

Its honest limit, in the rate card's own sentence shape: **configuration
establishes an approved value per completed booking, an operator policy, not
this booking's actual revenue.**

```json
{
  "llmOutcomeEvaluation": {
    "revenueCard": {
      "front-desk-agent": {
        "grossPerJob": 320,
        "attributionFraction": 0.15,
        "attributionBasis": "15% per policy REV-2024-03; agent-initiated chat, no prior web session"
      }
    },
    "revenueCardKey": "front-desk-agent"
  }
}
```

#### `revenueCardKey`

The non-empty string naming which `revenueCard` entry applies on this host,
read from configuration only — never inferred. This exists rather than being
inferred because the shipped rate card keys on the evaluator's inferred role,
which is model output, and handing a model the selector for a revenue figure
would create a gradient that rewards pointing agents at high-margin
transactions. A `revenueCard` with several entries and no configured
`revenueCardKey` (or a key naming an entry the card does not hold) selects
nothing: the resolver does not guess or fall back to the card's sole entry —
it delegates internally to the ordinary `hours x rate` derivation instead, so
an ordinary, non-revenue session on the same host still gets its value.

#### `maxRevenueValue`

Optional. Consulted only when the producing registrant declared, and had
accepted for this call, an operator-only economic mechanism. Absent or
malformed, the existing `round(maxHoursSaved x maxLoadedRate, 2)` ceiling
applies unchanged — a malformed `maxRevenueValue` never widens a bound, it
only falls back to the ceiling every other job on the host is already held to.

**Why a separate ceiling:** without one, an operator must inflate
`maxLoadedRate` to price a booking above the labor ceiling — corrupting the
labor bound that still guards every other, non-revenue job on the same host.
`maxRevenueValue` lets the two ceilings be sized independently.

#### The multi-profile fence

On a host whose owning profile cannot be attributed with certainty — a
multiplexed gateway serving several profiles, where per-profile config
resolution did not visibly engage — a revenue valuation **abstains** rather
than pricing from the root `config.json`'s card. This is the opposite polarity
from the rest of this config surface, which fails *open* (a missing or
malformed key degrades to the built-in derivation): on this one money path the
skill fails *closed*, deliberately, for the same reason `guardrail-status.json`'s
own fail-closed inversion is called out above — "keep going" and "keep going
with the wrong operator's money" are different outcomes, and only the first is
acceptable here. An ordinary, non-revenue session on the same host is
unaffected by this fence.

### Economic mechanisms (EGV-05)

Every job assessment names an `economic_mechanism`, which states how the work
produced value. Six mechanisms exist:

- `labor_substitution`
- `augmentation_capacity_expansion`
- `newly_enabled_work`
- `quality_decision_improvement`
- `risk_avoidance`
- `incremental_revenue`

The evaluator may select only the first three because the session transcript can
support them. The transcript cannot support `quality_decision_improvement`,
`risk_avoidance`, or `incremental_revenue`, so evaluator output cannot select them.
An unrecognised value or operator-only mechanism in an evaluator response resolves
to the `unknown` abstain sentinel. The mechanism is then absent from the assessment
instead of being replaced with a default.

**Two producers now exist for the operator-only three.**
`correct-assessment.sh --mechanism` (Phase 51) files any of the six directly
as an operator correction. As of this phase, a valuation registrant may also
**declare** one of the three at registration — the shipped
`revenue_card_valuation_fixture` declares `incremental_revenue` — and have it
accepted on any call whose own returned mechanism matches that declaration
(see `skills/revenium/plugins/revenium-classifier/valuation.py`'s `register()`
contract). The evaluator still structurally cannot select any of the three:
`_resolve_economic_mechanism`'s membership test runs only against
`EVALUATOR_MECHANISMS`, never `ECONOMIC_MECHANISMS`, so a value outside that
set — including all three operator-only mechanisms — resolves to the
`unknown` abstain sentinel in an evaluator response. The authority split
(`51-CONTEXT.md` D-01) holds regardless of which producer configured a
mechanism.

### Net value and cost coverage (EGV-14, EGV-15)

`estimated_value` remains the GROSS figure and keeps its existing meaning.
`net_value` is a new sibling field, not a redefinition of `estimated_value`.
The assessment schema version is unchanged. It subtracts every cost category
supplied via the `costs` block above from `estimated_value`.

The record names, in a fixed order, which cost categories were included
(supplied and non-negative), which of those were supplied as a known zero,
which are unknown (never configured for this job type, or malformed), and
which are deliberately excluded. The record must identify a partial net as
partial; EGV-15 forbids an unnamed partial net.

Metered AI cost is deliberately excluded and is named as such in the
coverage list (`metered_ai_cost`). Revenium already holds the metered cost
for a job and completes that half of the subtraction on its side; this
skill never nets AI cost itself.

No ROI ratio is emitted anywhere in the record. The skill ships the
operands (value, costs, and coverage), and Revenium derives ratios from
figures it already holds. This avoids a local zero denominator. The operands
represent a `$0.00`-cost job without substituting a null ratio; see
[`job-declaration.md`](job-declaration.md) for the standing regression test
built from that real run.

The read **fails closed**: a missing, unreadable, or malformed `config.json`
resolves to disabled. `guardrail-status.json` instead fails *open* so a
never-installed cron never blocks work. Failing open here would estimate money
without operator consent.

Bounds apply to the two *inputs*, not to the product. An out-of-range assumption
causes the evaluator to abstain, which is legible; an out-of-range total is not.
Abstention falls back to the existing status-only outcome path.

The value produced is an **unverified model estimate**. See the assessment
contract in [`job-declaration.md`](job-declaration.md) for what
`MODEL_ESTIMATED_DEMO` means.

### Reporting the estimate's value (EGV-18)

`experimentalReportEstimates` is a second, independent opt-in on top of `enabled`. With it
absent or not a literal `true`, an estimate is still computed and recorded locally in the
job-assessments sidecar, but its `reportability_status` resolves to `candidate`: the outcome
arc still reports to Revenium, and provenance (`evidence_class`, `evaluator`,
`evaluator_version`, `model`, and the version family) still ships in `--metadata`, but no
bound, no `bounds_source`, and no `assumptions` cross the wire. The number stays on this
machine. Set it to a literal JSON `true` and `reportability_status` resolves to `reportable`
**only if the record's evidence class also clears the gate described below** —
shipping the estimate exactly as the value flags and `--metadata` describe above. An
abstained assessment is never `reportable`, whatever this key says. An operator-filed
correction (`correct-assessment.sh`) always ships its value, regardless of this key,
because a human explicitly authorizes it.

#### The evidence-class gate on top of this flag (Phase 53, ROI-01)

Turning `experimentalReportEstimates` on is **necessary but no longer
sufficient** for a value to reach the wire. As of Phase 53, a record must
also carry one of five permitted evidence classes: `ACTIVITY_MEASURED`,
`OUTPUT_OBSERVED`, `OUTCOME_OBSERVED`, `CUSTOMER_CONFIGURED`,
`CUSTOMER_CONFIRMED`. A record whose evidence class is `MODEL_ESTIMATED_DEMO`
— the class every naked-LLM evaluation produces — is refused, whatever this
flag says.

**Why:** `revenium jobs roi <id>`, the surface an operator actually reads a
value on, carries no `evidence_class`, `evaluator`, or `confidence` — a
model-estimated figure would render there with a measurement's visual weight.
See [`docs/claim-distinctions-and-evidence-boundaries.md`](../../../docs/claim-distinctions-and-evidence-boundaries.md#the-product-truth-boundary)
for the live finding, and [`docs/roi-read-surface-ask.md`](../../../docs/roi-read-surface-ask.md)
for the standing ask this gate is a self-imposed substitute for.

**The permitted set is a code constant, not a config key (D-02).** There is
deliberately no field anywhere in `config.json` that widens it — an operator
cannot turn `MODEL_ESTIMATED_DEMO` reportable by any combination of settings
in this file. Widening the set requires a code change and review, not a
configuration edit. This is intentional: a value-reporting gate an operator
can configure away is not a gate.

**If you turn `experimentalReportEstimates` on and see nothing reported,**
this is why. The naked-LLM evaluator (`"evaluator": "llm"`, the default)
always produces `MODEL_ESTIMATED_DEMO`, which this gate always refuses — no
config change in this file makes that evaluator's output reportable. A value
becomes reportable only when it is constituted by something other than a
model — for example a `CUSTOMER_CONFIGURED` boundary — never by turning this
flag on alone.

### Operator visibility (Phase 39, ROI-14)

`diagnose.sh` reports, per profile, whether this switch is enabled and which evaluator is
selected, plus the two cron-side outcomes it can legitimately see from that profile's own
log: `deferred` (and its aged `wedged` restatement) and `reported`. The other four outcomes
(`evaluated`, `abstained`, `invalid`, and `timed-out`) are written in-process by the classifier
plugin on the `revenium_classifier` Python logger, not into `revenium-metering.log`, so they
land wherever Hermes' own logging is configured. `diagnose.sh` names where they are; it does
not show them.

## Opt-in surfaces and how they compose (D-09, EGV-23)

Everything under `llmOutcomeEvaluation`, including the `boundaries` object
below that selects an implementation for an assessment step, is
**experimental**. Five surfaces make up the whole opt-in feature, each
governing a genuinely different thing:

| Surface | Governs |
|---|---|
| `enabled` | Whether evaluation happens at all. |
| `experimentalReportEstimates` | Whether a computed value is *reportable* to Revenium — independent of `enabled`, because a value can be computed and withheld from the wire. |
| `boundaries` | Which registered implementation serves each pluggable contract (classification, valuation, evidence). |
| `costs` | Operator-supplied inputs that net against a computed estimate. |
| `studyId` / `studyVersion` | Reference an impact study; referencing one never changes an assessment's own evidence class. |

These five are **independent. There is no master flag, and none of them will be
renamed.**

No master flag exists because adding a new gate to the billing path risks
becoming a second way to disable metering. It would also conflate fail-open
enrichment with deterministic budget enforcement, which EGV-22 forbids. No
surface will be renamed because `enabled` and
`experimentalReportEstimates` are already set in live installs; renaming
either is a breaking config change for exactly the installs this milestone
promises unchanged behaviour to.

## `boundaries` (v1.6, optional, experimental)

Phase 45 (EGV-01) turned six classifier-plugin boundaries into named, pluggable
contracts, each backed by its own registry: `classification` (task_type labelling and job/arc
inference, one contract per D-13), `valuation`, and `evidence`. (The other three phase-45
boundaries (cohort impact and Revenium reporting) ship with zero registrants or no live
adapter and have no operator-selectable name today.) `boundaries` is how an operator selects a
non-built-in implementation for one of these three, by the name it registered under.

**It is read from the TOP LEVEL of `config.json`, as a sibling of `llmOutcomeEvaluation`**,
not from inside that object. The resolver reads `config["boundaries"]` directly. The
"Opt-in surfaces" table above groups it with `llmOutcomeEvaluation`'s other surfaces because
it governs part of the same opt-in feature; that grouping is conceptual and says nothing
about where the key lives. A nested `boundaries` object resolves to nothing, and because
resolution fails open, every boundary silently keeps its built-in implementation with no
log line to say so.

```json
{
  "boundaries": {
    "classification": "llm",
    "valuation": "hours_times_rate",
    "evidence": "config_opt_in"
  }
}
```

| field | default | purpose |
|---|---|---|
| `classification` | `"llm"` | Which registered classifier resolves BOTH turn-level `task_type` labelling and job/arc inference (`classification.py`). The built-in `llm` registrant is the naked-LLM classifier this skill has always shipped; `keyword_classification_fixture` is a shipped, deterministic, non-LLM alternative that makes no model call. |
| `valuation` | `"hours_times_rate"` | Which registered implementation resolves an outcome's economic valuation. The built-in `hours_times_rate` registrant is the `hours x rate` derivation this skill has always shipped; `rate_card_valuation_fixture` is a shipped, operator-configured alternative that reads a role rate card and makes no model call. |
| `evidence` | `"config_opt_in"` | Which registered implementation resolves an assessment's reportability. The built-in `config_opt_in` registrant is the config-opt-in rule this skill has always applied; `confirmation_workflow_evidence_fixture` is a shipped alternative modelling an explicit customer-confirmation workflow. |

The resolver fails open. The `boundaries` object itself, any one of its members, an empty
string value, or a name that does not resolve to a registered implementation all fall
back to the built-in implementation and change nothing else about classification. A typo in
`config.json`, or an install with no `boundaries` object at all, degrades to today's behaviour
rather than stopping classification.

`llmOutcomeEvaluation.evaluator` (documented above) remains the selector for the
output/outcome-assessment boundary (`evaluators.py`) and is deliberately NOT moved into this
object. Moving it would break every install that already sets it.

---

# Job Assessment Sidecar (Phase 42)

## Overview

Every accepted `llmOutcomeEvaluation` assessment (see above) is now also written to a
job-id-keyed sidecar file, `${STATE_DIR}/job-assessments/<sanitized_job_id>.jsonl`
(declared as `JOB_ASSESSMENTS_DIR` in `common.sh`). It is the system of record for a job's
`JobAssessment`, distinct from the job marker's existing 9-key `assessment` summary
(`markers/<sid>.jsonl`), which stays a pointer-and-summary and is byte-unchanged. The
outcome stage in `hermes-report.sh` reads the sidecar, never the marker's summary, to
resolve `--outcome-value`/`--outcome-currency` and `--metadata` provenance. An absent,
unreadable, oversized, or pruned sidecar record reports the outcome status-only, with no
value flags.

The file holds one JSON line per record, of two kinds: `job_assessment` (the original,
written by the classifier immediately after evaluation, before the job marker itself.
With sidecar-first ordering, a crash between the two writes leaves an orphan
sidecar record rather than losing the assessment's value) and `correction` (an
operator-filed revision, appended by `correct-assessment.sh`). A scan-to-end
reader with no early exit means the LAST line matching a job id wins, so a `correction` line
naturally supersedes the original. Each line is capped at 8,192 bytes; an over-length line
is skipped by the reader (never crashes it) and refused outright by the writer.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `REVENIUM_JOB_ASSESSMENTS_DIR` | `${STATE_DIR}/job-assessments` | Overrides the sidecar directory, following the same `REVENIUM_*` override convention as `EVENT_SPOOL_DIR`/`TOOL_EVENTS_DIR`. |
| `REVENIUM_ASSESSMENT_RETENTION_DAYS` | `90` | Retention window for sidecar files, keyed on each file's own last write (mtime), not the owning session's ledger timestamp used to prune `markers/`. The window exceeds `MARKER_RETENTION_DAYS`' 30 because assessments are the audit record for corrections, which may arrive well after a session ends. |

Both variables are declared only in `common.sh`, between the existing declarations and
the eager `mkdir -p` line, following the single-source-of-truth rule every other state
path in this document follows.

## `correct-assessment.sh` operator flags

Corrections are filed by a human at a terminal; this script is never reachable
from cron. Every flag below is refused loudly on a bad value rather than
degraded to a default — an operator running one command can act on an error,
and a silently-skipped correction is worse than a refused one.

| Flag | Required | Notes |
|------|----------|-------|
| `--job-id` | always | |
| `--reason` | always | Audit-trail text, clamped to 500 serialized bytes. |
| `--value` | unless `--mechanism` is given | The point/base estimate. |
| `--currency` | whenever `--value` is given | One of USD, EUR, GBP, CAD, AUD, JPY, CHF. |
| `--value-low` / `--value-high` | no | Default to `--value` (equal bounds). Refused without `--value`. |
| `--mechanism` | no | One of the six declared economic mechanisms, matched exactly. Case-sensitive; surrounding whitespace is trimmed, nothing else is coerced. `--mechanism ""` is refused rather than treated as absent. |
| `--attribution-fraction` | no | A finite number from 0 through 1, both endpoints legal. Refused if not accompanied by `--attribution-basis`, and refused without `--value` — a fraction with nothing to attribute is not recorded. |
| `--attribution-basis` | whenever `--attribution-fraction` is given | Free text, clamped like `--reason`. Refused on its own. |
| `--dry-run` | no | Performs no writes, local or remote, on any path. |

A mechanism-only correction omits the value family entirely rather than
writing zeros or nulls; `prior_value_*` still records what stood before.

The attribution pair is recorded, never computed. What it does and does not
establish is set out in the project's `docs/value-and-roi.md` — referenced by
name rather than linked, because this file ships into the skill bundle where a
repo-relative path would not resolve.
