# Configuration

[← Documentation index](README.md)

Configuration lives in two places, and they are not interchangeable. The skill's own
settings sit in `~/.hermes/state/revenium/config.json`. Your Revenium credentials sit in
`~/.config/revenium/config.yaml`, written by `revenium config set`; the skill never reads
or writes that file itself.

## `config.json`

```json
{
  "ruleIds": ["d5jng5"],
  "organizationName": "my-org",
  "autonomousMode": false,
  "notifyChannel": "slack",
  "notifyTarget": "channel:C0123456789"
}
```

| Field | Required | Purpose |
|---|---|---|
| `ruleIds` | yes | The `revenium guardrails budget-rules` ruleIds this install owns. Written by `setup-guardrails.sh`, or on the first cron tick when upgrading a legacy install. |
| `organizationName` | no | Passed as `--organization-name` on metered transactions, for Revenium attribution. |
| `autonomousMode` | no | When `true`, a blocked rule halts the agent and sends a notification. |
| `notifyChannel` | autonomous only | Hermes messaging channel for halt notifications — `slack`, `discord`. |
| `notifyTarget` | autonomous only | Channel-specific target — `channel:<id>`, `user:<id>`, `@username`. |

An upgraded host keeps its legacy `alertId` field, but nothing reads it. See
[Guardrails migration](migration-guardrails.md).

### LLM outcome evaluation (experimental)

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

| Field | Required | Purpose |
|---|---|---|
| `enabled` | no | Must be a **literal JSON boolean** `true` — the string `"true"`, the integer `1`, and any other truthy value all leave the feature off. `false` or absent (the default) meters exactly as before. |
| `evaluator` | no | Which registered evaluator to use. Defaults to `"llm"`. |
| `currency`, `maxHoursSaved`, `maxLoadedRate` | no | Bounds on the estimate. See the full schema for defaults and behaviour when exceeded. |
| `experimentalReportEstimates` | no | Must be a **literal JSON boolean** `true`, same discipline as `enabled`. `false` or absent (the default) computes and records an estimate locally but withholds its value from Revenium — the outcome and provenance still report, the number does not (`reportability_status: "candidate"`). `true` ships the value too (`reportability_status: "reportable"`). |
| `studyId`, `studyVersion` | no | Name an impact study (EGV-12/EGV-13) this install's job assessments reference — a non-empty string id paired with an integer version >= 1, all-or-none (configure one without the other and neither is recorded). Recorded on every assessment; referencing a study never changes that assessment's own `evidence_class`. |
| `costs` | no | An object keyed by job type, each value an object of non-AI cost categories (`human_review`, `rework_or_error`, `integration`, `training_or_change`) that subtract from `estimated_value` into a `net_value`. No fleet-wide default — an unconfigured job type nets nothing. A supplied `0` and an absent category are different and both explicit in the record; see the full schema. |

The value this produces is an **unverified model estimate** — see
[How it works](how-it-works.md#llm-outcome-value-evaluation-experimental) for what that
means and how Revenium combines it with metered cost into a displayed ROI, and
**[Job value and ROI](value-and-roi.md)** for the complete reference: the evaluator, the
abstention vocabulary, the derivation, the records, the wire shape, and troubleshooting.
[Job value: a practical overview](value-overview.md) is the short version, with an annotated
worked configuration for a software engineering team.

`net_value`, the cost coverage list, and the six `economic_mechanism` values
(three the evaluator may select, three only an operator can declare) are all
part of this same block's effect and are documented in full — including why
no ROI ratio is ever emitted — in the full schema below.

The full schema is in
[`references/config-schema.md`](../skills/revenium/references/config-schema.md).

### Opt-in surfaces and how they compose (D-09, EGV-23)

Everything under `llmOutcomeEvaluation` is **experimental**, including the
`boundaries` object below, which selects an implementation for one assessment
step. Five settings control separate parts of the opt-in feature:

| Surface | Governs |
|---|---|
| `enabled` | Whether evaluation happens at all. |
| `experimentalReportEstimates` | Whether a computed value is *reportable* to Revenium — independent of `enabled`, because a value can be computed and withheld from the wire. |
| `boundaries` | Which registered implementation serves each pluggable contract (classification, valuation, evidence). |
| `costs` | Operator-supplied inputs that net against a computed estimate. |
| `studyId` / `studyVersion` | Reference an impact study; referencing one never changes an assessment's own evidence class. |

These five are **independent. There is no master flag, and none of them will be
renamed.**

Adding a master flag to the billing path would create a second way to disable
metering and mix fail-open enrichment with deterministic budget enforcement,
which EGV-22 forbids. No setting will be renamed because `enabled` and
`experimentalReportEstimates` are already set in live installs; renaming
either is a breaking config change for exactly the installs this milestone
promises unchanged behaviour to.

### Pluggable boundaries (experimental)

```json
{
  "boundaries": {
    "classification": "llm",
    "valuation": "hours_times_rate",
    "evidence": "config_opt_in"
  }
}
```

`boundaries` is a **top-level key of `config.json`, a sibling of `llmOutcomeEvaluation`** —
the JSON above is the whole file's shape, not a fragment to paste inside the
`llmOutcomeEvaluation` object. It is one of that feature's five opt-in *surfaces*
conceptually, but it is not one of its members structurally. Nesting it is silent: the
resolver reads the top level, and a `boundaries` object it does not find is
indistinguishable from one that was never configured.

Phase 45 (EGV-01) turned six points inside the classifier plugin into named, pluggable
contracts, each backed by its own registry. `boundaries` selects a non-built-in
implementation for one of them, by the name it registered under — `classification` covers
both turn-level task-type labelling and job/arc inference as one contract; `valuation` and
`evidence` are separate boundaries. The object, any one of its members, an empty value, or a
name that resolves to nothing all fall back to the built-in implementation and change
nothing else. A typo here falls back to current behaviour and never stops classification.

`llmOutcomeEvaluation.evaluator` above stays the selector for the output/outcome-assessment
boundary and is deliberately not part of this object, because moving it would be a breaking
config change for every install that already sets it.

The full schema, including the shipped non-LLM classifier fixture, is in
[`references/config-schema.md`](../skills/revenium/references/config-schema.md).

## Environment variables

Every value below has a working default in `scripts/common.sh`. Set one only when you have
a reason to. The cron reads them from an optional env file at
`~/.hermes/state/revenium/env`, sourced at the start of each tick.

### Identity

| Variable | Default | Purpose |
|---|---|---|
| `REVENIUM_AGENT_NAME` | `Hermes` | The AGENT dimension. Fleet installs set `Hermes-<profile>` per profile. |
| `REVENIUM_SQUAD_NAME` | *(empty)* | The SQUAD dimension, meant to span agents. The empty default preserves backward compatibility. |

`organizationName` is neither of these. It names a company or product, and conflating it
with an agent name is a common enough mistake that the installer warns about it.

### Paths

| Variable | Default |
|---|---|
| `HERMES_HOME` | `~/.hermes` |
| `REVENIUM_STATE_DIR` | `${HERMES_HOME}/state/revenium` |

### Timing

| Variable | Default | Purpose |
|---|---|---|
| `REVENIUM_CRON_SETTLE_SECONDS` | `600` | How long to wait for a session's classification before metering it anyway. Must exceed worst-case job-inference latency — metering early orphans the completion from its job permanently. |
| `REVENIUM_JOBS_STALE_SECONDS` | `600` | When an open job arc is considered stale. |
| `REVENIUM_MARKER_RETENTION_DAYS` | `30` | Age at which `prune-markers.sh` will remove a marker file. |
| `REVENIUM_CRON_LOOP_COUNT` | `1` | Iterations per cron tick, for sub-minute cadence. `install-cron.sh --interval-seconds` sets this. |
| `REVENIUM_CRON_LOOP_SLEEP_SECONDS` | `0` | Pause between those iterations. |

### Event metering

| Variable | Default | Purpose |
|---|---|---|
| `REVENIUM_EVENT_METERING_MODE` | `shadow` | `shadow` computes rows without shipping them; `live` ships them. |
| `REVENIUM_LEGACY_COMPLETIONS` | `enabled` | `enabled` keeps the delta reporter billing; `disabled` stands it down. |
| `REVENIUM_DRAIN_STALE_SECONDS` | `604800` | When an open session counts as drained. Sets the floor on cutover convergence — see [How it works](how-it-works.md#event-driven-metering-the-v15-path). |

Setting `MODE=live` by itself does not cut over. [Event metering](event-metering.md)
explains why.

### Housekeeping

| Variable | Default | Purpose |
|---|---|---|
| `REVENIUM_LOG_MAX_BYTES` | `52428800` | Size at which the metering log is truncated in place. |
| `REVENIUM_LOG_KEEP_BYTES` | `2097152` | How much tail to keep when it is. |
| `REVENIUM_PAGE_BATCH_SIZE` | `500` | Page size for paged Revenium CLI reads. |

### Credentials

`REVENIUM_API_KEY`, `REVENIUM_TEAM_ID`, `REVENIUM_TENANT_ID`, and `REVENIUM_OWNER_ID` are
read by `install.sh --non-interactive` and by the `revenium` CLI. They are not a substitute
for `revenium config set` on an interactive host. See
[Credentials](installation.md#credentials-all-four-required).
