# config.json Schema

## Overview

`config.json` is the runtime configuration file for the Revenium skill. It is written
during setup and read by the cron pipeline on every tick. Location:
`~/.hermes/state/revenium/config.json` (declared as `CONFIG_FILE` in `common.sh`).
The file is the sole coupling point between the setup flow and the cron pipeline; its
schema is the public interface between those two halves.

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
file so dashboards and analytics see the would-be-block — only the agent-halt
decision is suppressed. Useful for validating a new rule's enforcement signal
against real traffic before flipping the server-side `shadowMode` flag off
(`revenium guardrails budget-rules update <id> --shadow-mode=false`).

When a shadow-mode rule transitions from `state: "ok"` or `state: "warn"` into
`state: "block"`, `guardrail-check.sh` emits a one-shot `[shadow]`-prefixed
operator notification via the same Hermes messaging path used for hard halts.
Re-runs while the rule remains in shadow-block state are silent.

## `haltedRule` Extension (D-04)

When `halted` is `true`, the top-level `haltedRule` block is pre-computed by
`guardrail-check.sh` from the first blocked rule in `config.json::ruleIds` declaration
order. This eliminates tiebreaker logic from hook scripts and the SKILL.md backstop —
all three become trivial readers of one pre-resolved block. When `halted` is `false`,
`haltedRule` is absent entirely.

The `haltedRule` block contains a subset of `rules[]` fields: `ruleId`, `name`,
`metricType`, `windowType`, `currentValue`, and `hardLimit`. The fields `groupBy`,
`warnThreshold`, `state`, and `lastChecked` are intentionally omitted — hooks only
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
        "integration": 0
      }
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
| `experimentalReportEstimates` | `false` | Must be a **literal JSON boolean** `true`, same discipline as `enabled`. Governs EGV-18's `reportability_status`, not whether an estimate is computed. |
| `studyId` | `""` | A non-empty string naming an `ImpactStudyResult` this install's job assessments reference. Recorded on every assessment this install produces; never changes an assessment's own `evidence_class` (EGV-13, D-08). |
| `studyVersion` | `0` | A plain integer >= 1, paired with `studyId`. The pair is **all-or-none in both directions**: if either field is missing or malformed (a blank `studyId`, a non-integer or `< 1` `studyVersion`), both resolve to their absent defaults. A half-reference could never name a real `ImpactStudyResult`, so none is recorded. |
| `costs` | `{}` | An object keyed by job type (EGV-14). Each job type's value is an object whose keys are drawn from the four `COST_CATEGORIES` names — `human_review`, `rework_or_error`, `integration`, `training_or_change`. There is **no fleet-wide default bucket**: an absent job-type key means every category is unknown for that job type, exactly as if `costs` were absent entirely. A supplied `0` is knowledge and participates in the subtraction as a known zero; an absent category is unknown and does not participate (D-10) — these are different and both explicit. A malformed, non-numeric, boolean, or negative value resolves that category to unknown, never to zero. |

### Economic mechanisms (EGV-05)

Every job assessment names an `economic_mechanism` — a claim about *how* the
work produced its value, not just how much. Six mechanisms exist:

- `labor_substitution`
- `augmentation_capacity_expansion`
- `newly_enabled_work`
- `quality_decision_improvement`
- `risk_avoidance`
- `incremental_revenue`

The evaluator may select only the first three. A mechanism is a claim about
the work, which the session transcript evidences, so the model may choose
among the three it can evidence from what it actually observed. The remaining
three — `quality_decision_improvement`, `risk_avoidance`, and
`incremental_revenue` — are claims the transcript cannot support, so they are
never reachable from evaluator output. An unrecognised value, or one of these
three operator-only mechanisms, appearing in an evaluator response resolves to
the `unknown` abstain sentinel — the job's mechanism is absent from the
assessment rather than clamped to a working default.

**These three are reserved, not yet assignable.** As of Phase 44 they are
declared, accepted by the reporter's allow-list, and would forward on the wire
if a record carried one — but no producer exists: there is no configuration key
and no CLI flag that sets a job's mechanism, and `correct-assessment.sh` does
not carry one either. The record can *represent* all six (EGV-05); an operator
cannot yet *assert* the operator-only three. The intended path is a study
reference (`studyId`/`studyVersion`), which is Phase 45 work. Do not configure
against this today — nothing reads it.

### Net value and cost coverage (EGV-14, EGV-15)

`estimated_value` remains the GROSS figure and keeps its existing meaning.
`net_value` is a new sibling field, not a redefinition of `estimated_value` —
the assessment schema version is unchanged. It subtracts every cost category
supplied via the `costs` block above from `estimated_value`.

The record names, in a fixed order, which cost categories were included
(supplied and non-negative), which of those were supplied as a known zero,
which are unknown (never configured for this job type, or malformed), and
which are deliberately excluded. A partial net is honest as long as its
partiality is legible — an unnamed partial net is the silent substitution
EGV-15 forbids.

Metered AI cost is deliberately excluded and is named as such in the
coverage list (`metered_ai_cost`). Revenium already holds the metered cost
for a job and completes that half of the subtraction on its side; this
skill never nets AI cost itself.

No ROI ratio is emitted anywhere in the record. The skill ships the
operands — value, costs and coverage — and Revenium derives ratios from
figures it already holds. There is therefore no denominator here to divide
by zero, which is how a genuinely `$0.00`-cost job is represented by its
operands rather than papered over by a null ratio — see
[`job-declaration.md`](job-declaration.md) for the standing regression test
built from that real run.

The read **fails closed**: a missing, unreadable, or malformed `config.json`
resolves to disabled. This is the deliberate inverse of `guardrail-status.json`,
which fails *open* so a never-installed cron never blocks work — failing open
here would estimate money by accident.

Bounds apply to the two *inputs*, not to the product. An out-of-range assumption
causes the evaluator to abstain, which is legible; an out-of-range total is not.
Abstention falls back to the existing status-only outcome path.

The value produced is an **unverified model estimate** — see the assessment
contract in [`job-declaration.md`](job-declaration.md) for what
`MODEL_ESTIMATED_DEMO` means.

### Reporting the estimate's value (EGV-18)

`experimentalReportEstimates` is a second, independent opt-in on top of `enabled`. With it
absent or not a literal `true`, an estimate is still computed and recorded locally in the
job-assessments sidecar, but its `reportability_status` resolves to `candidate`: the outcome
arc still reports to Revenium, and provenance (`evidence_class`, `evaluator`,
`evaluator_version`, `model`, and the version family) still ships in `--metadata`, but no
bound, no `bounds_source`, and no `assumptions` cross the wire — the number stays on this
machine. Set it to a literal JSON `true` and `reportability_status` resolves to `reportable`,
shipping the estimate exactly as the value flags and `--metadata` describe above. An
abstained assessment is never `reportable`, whatever this key says. An operator-filed
correction (`correct-assessment.sh`) always ships its value, regardless of this key — it is
filed under explicit human authorisation, not naked-LLM estimation.

### Operator visibility (Phase 39, ROI-14)

`diagnose.sh` reports, per profile, whether this switch is enabled and which evaluator is
selected, plus the two cron-side outcomes it can legitimately see from that profile's own
log: `deferred` (and its aged `wedged` restatement) and `reported`. The other four outcomes
— `evaluated`, `abstained`, `invalid`, `timed-out` — are written in-process by the classifier
plugin on the `revenium_classifier` Python logger, not into `revenium-metering.log`, so they
land wherever Hermes' own logging is configured. `diagnose.sh` names where they are; it does
not show them.

## `boundaries` (v1.6, optional)

Phase 45 (EGV-01) generalized six seams inside the classifier plugin into named, pluggable
contracts, each backed by its own registry: `classification` (task_type labelling and job/arc
inference, one contract per D-13), `valuation`, and `evidence`. (The other three phase-45
boundaries — cohort impact and Revenium reporting — ship with zero registrants or no live
adapter and have no operator-selectable name today.) `boundaries` is how an operator selects a
non-built-in implementation for one of these three, by the name it registered under:

```json
{
  "boundaries": {
    "classification": "llm",
    "valuation": "llm",
    "evidence": "llm"
  }
}
```

| field | default | purpose |
|---|---|---|
| `classification` | `"llm"` | Which registered classifier resolves BOTH turn-level `task_type` labelling and job/arc inference (`classification.py`). The built-in `llm` registrant is the naked-LLM classifier this skill has always shipped; `keyword_classification_fixture` is a shipped, deterministic, non-LLM alternative that makes no model call. |
| `valuation` | `"llm"` | Which registered implementation resolves an outcome's economic valuation. |
| `evidence` | `"llm"` | Which registered implementation resolves an assessment's evidence grading. |

**Fail-open, every way.** The `boundaries` object itself, any one of its members, an empty
string value, or a name that does not resolve to a registered implementation — all four fall
back to the built-in implementation and change nothing else about classification. A typo in
`config.json`, or an install with no `boundaries` object at all, degrades to today's behaviour
rather than stopping classification.

`llmOutcomeEvaluation.evaluator` (documented above) remains the selector for the
output/outcome-assessment boundary (`evaluators.py`) and is deliberately NOT moved into this
object — moving it would be a breaking config change for every install that already sets it.

---

# Job Assessment Sidecar (Phase 42)

## Overview

Every accepted `llmOutcomeEvaluation` assessment (see above) is now also written to a
job-id-keyed sidecar file, `${STATE_DIR}/job-assessments/<sanitized_job_id>.jsonl`
(declared as `JOB_ASSESSMENTS_DIR` in `common.sh`) — the record of record for a job's
`JobAssessment`, distinct from the job marker's existing 9-key `assessment` summary
(`markers/<sid>.jsonl`), which stays a pointer-and-summary and is byte-unchanged. The
outcome stage in `hermes-report.sh` reads the sidecar, never the marker's summary, to
resolve `--outcome-value`/`--outcome-currency` and `--metadata` provenance — an absent,
unreadable, oversized, or pruned sidecar record reports the outcome status-only, with no
value flags.

The file holds one JSON line per record, of two kinds: `job_assessment` (the original,
written by the classifier immediately after evaluation, before the job marker itself —
sidecar-first ordering means a crash between the two writes leaves a harmless orphan
sidecar record rather than losing the assessment's value) and `correction` (an
operator-filed revision, appended by `correct-assessment.sh`). A scan-to-end
reader with no early exit means the LAST line matching a job id wins, so a `correction` line
naturally supersedes the original. Each line is capped at 8,192 bytes; an over-length line
is skipped by the reader (never crashes it) and refused outright by the writer.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `REVENIUM_JOB_ASSESSMENTS_DIR` | `${STATE_DIR}/job-assessments` | Overrides the sidecar directory, following the same `REVENIUM_*` override convention as `EVENT_SPOOL_DIR`/`TOOL_EVENTS_DIR`. |
| `REVENIUM_ASSESSMENT_RETENTION_DAYS` | `90` | Retention window for sidecar files, keyed on each file's own last write (mtime) — not the owning session's ledger timestamp, the way `markers/` is pruned. Deliberately well above `MARKER_RETENTION_DAYS`' 30: assessments are the audit record a correction is filed against, and corrections arrive on a human timescale, not a session one. |

Both variables are declared only in `common.sh`, between the existing declarations and
the eager `mkdir -p` line, following the single-source-of-truth rule every other state
path in this document follows.
