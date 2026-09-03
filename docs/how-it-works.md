# How it works

[← Documentation index](README.md)

This Hermes skill bundle uses `SKILL.md` only as a halt-check backstop. A
plugin, three shell hooks, and a cron perform the runtime work. See
[What's actually installed](../README.md#whats-actually-installed) for the split.

The components do not call each other. They communicate through files under
`~/.hermes/state/revenium/`.

1. In-session: Hermes loads the Python `revenium-classifier` plugin from
   `~/.hermes/plugins/` and calls it at four lifecycle hooks. It labels each session and
   writes marker files. Three shell hooks registered in `config.yaml`
   enforce guardrails and capture tool calls. None of this makes a network call.
2. State files: `config.json`, `guardrail-status.json`, markers, ledgers, and
   taxonomies. Every process re-reads what it needs; there is no shared memory and no IPC.
3. The cron pipeline: runs once a minute, out of process, under one lock. Only this
   component talks to Revenium.

This separation makes a broken install fail open with no enforcement or classification
instead of blocking the agent.

## Token metering with task-type classification

The cron runs six stages under one lock: `plugin-status.sh`, `hermes-report.sh`,
`guardrail-check.sh`, `tool-event-report.sh`, `api-event-report.sh`, and `drain-status.sh`.

`hermes-report.sh` is the token reporter. It reads token deltas from `~/.hermes/state.db`
and ships one `revenium meter completion` per marker. Each completion carries
`--task-type` and `--operation-type` from the task taxonomy; markers that own a job also
carry `--agentic-job-id`.

It reports deltas, not totals. Ledger lines look like
`HERMES:<session_id>:<total_tokens>:<unix_ts>:<muid>`, and a session whose
`(sid, total_tokens)` pair is already present is skipped, so re-running the cron never
double-reports.

The labels come from the `revenium-classifier` plugin, which reads session data directly
rather than asking the agent to classify its own turns. A session with no markers falls
back to `--task-type unclassified`.

The plugin registers four hooks, because no single one covers every session shape:

| Hook | Why it exists |
|---|---|
| `on_session_end` | Fires only from the session-expiry watcher, so it alone would never see a gateway-served session. |
| `on_session_finalize` | Covers shutdown, expiry, and reset boundaries. |
| `post_llm_call` | Fires once per completed turn, so an ordinary prompt is classified on its first turn instead of waiting for a session boundary. |
| `post_api_request` | Carries no classification concern — it is the event-metering seam described below. |

One guard, `_session_already_classified`, makes "exactly one classification per session"
hold no matter which hook fires first.

## Event-driven metering (the v1.5 path)

A second path meters each API call individually. `post_api_request` fires once per call and
appends a compact record to a per-session spool without a network call, LLM call, or database
read. The cron's `api-event-report.sh` stage ships each record as its own row,
keyed on the provider's `api_request_id`.

The difference from the reporter above is what gets attributed. `hermes-report.sh` takes a
session's token delta and divides it across that session's markers. The event path reports
what each call actually used.

Two switches control it:

| Variable | Default | Effect |
|---|---|---|
| `REVENIUM_EVENT_METERING_MODE` | `shadow` | `shadow` computes rows without shipping; `live` ships them. |
| `REVENIUM_LEGACY_COMPLETIONS` | `enabled` | `enabled` keeps the delta reporter billing; `disabled` stands it down. |

Setting `MODE=live` alone does not cut over. While legacy stays enabled, an ownership
record decides which path bills a given session, and the outcome turns on a race you cannot
predict from the switches. A real cutover needs `REVENIUM_LEGACY_COMPLETIONS=disabled`.
[Event metering](event-metering.md) has the mechanism and the evidence.

Setting that fleet-wide is safe. Profiles whose sessions have drained cut over at once; the
rest keep billing through the legacy path until they drain, then cut over on their own. The
`drain-status.sh` stage maintains that gate.

A session's effective stale threshold is
`max(REVENIUM_DRAIN_STALE_SECONDS, REVENIUM_CRON_SETTLE_SECONDS + 86400)`, and it sets the
floor on how fast a profile can converge. Check it before planning a cutover. At the
default `REVENIUM_DRAIN_STALE_SECONDS=604800`, a quiet
open session takes seven days to clear. Lower it to `86400` and the `settle + 86400` term
takes over, giving 87,000 seconds, or about 24.17 hours. That is the figure quoted in
[Event metering](event-metering.md), and it reflects one fleet's tuned configuration rather
than the default.

Rollback is the reverse: set `REVENIUM_LEGACY_COMPLETIONS=enabled` again, then
`REVENIUM_EVENT_METERING_MODE=shadow`.

## Auxiliary usage metering

This pass meters the auxiliary LLM calls Hermes makes around its main loop:
compression, title generation, approval, vision, web extraction, and session search.
None of it was reported before this feature shipped.

It runs as `report_auxiliary_usage`, a post-loop pass inside `hermes-report.sh`, after the
agentic-jobs outcome stage. It is not a seventh cron stage; the cron still runs
six.

It reads `session_model_usage` in `state.db`, read-only, and considers only rows whose
`task` column is non-empty. An empty-`task` row mirrors the `sessions` row's own totals
and is excluded — shipping it would double-count the main loop.

Each qualifying row ships as its own `revenium meter completion`, with
`--operation-type AUX` and `--task-type` drawn from a fixed six-label `aux_*` vocabulary.
An unrecognised value ships as `aux_unclassified` so spend is never dropped, only its
label.

Idempotency is `revenium-aux.ledger`, its own key domain, using per-column cumulative
subtraction — re-running the cron never double-reports.

The switch is `REVENIUM_AUX_METERING` (env) or `auxMetering` (`config.json`), env wins.
`disabled` — or a Hermes build with no `session_model_usage` table — meters
byte-identically to before.

Auxiliary rows carry the session's `--agent`, so default `AGENT:IS:` rules include them.
`MODEL` and `PROVIDER` rules evaluate the auxiliary call's own model and provider, which
may differ from the main loop. `TASK_TYPE` rules must explicitly include the `aux_*`
labels.

Whether Revenium's server-side guardrail counter advances for an auxiliary row has not
yet been verified against a live tenant.

See [Auxiliary usage migration](migration-auxiliary-usage.md) for the measured step-up,
the re-runnable sizing SQL, and the off switch.

## Agentic job tracking

Discrete task arcs become Revenium agentic jobs through `revenium jobs create` and
`revenium jobs outcome`. Each arc's business outcome is recorded exactly once — outcomes
are immutable and never re-sent — with idempotency held in
`~/.hermes/state/revenium/revenium-jobs.ledger`. The AI transactions belonging to a job are
linked back through `--agentic-job-id`.

Every outcome also carries a `--metadata` blob holding the deployment `source`, taken from
the session's source column. `FAILED` arcs add a `failure_reason`: a short plain-text cause
inferred by the classifier. `SUCCESS` and `CANCELLED` arcs carry source alone.

### The bounded `--metadata` envelope (D-01/D-02/D-03, EGV-19)

`--metadata` is not a new transport — it is the existing, real `jobs outcome` CLI flag
above, carrying one flat JSON object. This section formalizes what already ships; no API
capability is invented here.

**Key inventory.** Three groups of keys can appear in the object:

- **Base keys** — `source` (the deployment source) and `failure_reason` (a `FAILED` arc's
  short cause). These are base metering and are never dropped.
- **The value family** — `value_low`, `value_base`, `value_high`, `bounds_source`,
  `net_value`, `assumptions`, `supplied_costs`, `cost_coverage`, `attribution_fraction`,
  `attribution_basis`. The economic estimate and its inputs. The attribution pair is in
  this family rather than the provenance one on purpose: the value family sheds first, so
  an attribution recorded here can never outlive the value it documents.
- **The provenance family** — `evaluator`, `evaluator_version`, `model`, `evidence_class`,
  `evidence_class_authority`, `reportability_status`, `study_id`, `study_version`,
  `confidence`, `economic_mechanism`, `double_counting_group`, `correction_sequence`,
  `inference_provider`, and `inference_address_class`. Who or what produced the estimate,
  and where it was configured to run. `evidence_class_authority` names which of the four
  boundaries in the cross-boundary precedence walk (evidence, valuation, classification, or
  evaluator) decided `evidence_class` — see
  [Evidence-class precedence and declaration authority](evidence-class-precedence.md).

**A byte ceiling is enforced once, in the reporter, at emit.** The ceiling is **4096 bytes**
and is pinned by test to `_METADATA_CEILING_BYTES` in
`skills/revenium/scripts/hermes-report.sh`.

The figure is a **defensive** choice, not a measured server bound: there is no observed
Revenium server-side `--metadata` limit to derive a ceiling from. What DOES stand behind it
is a measurement of this skill's own output — the ASCII baseline for the whole Phase 42-45
field set (every provenance, value, and cost key this envelope can emit) measures under
1,000 bytes, below the 4096-byte ceiling. The number is bounded by measurement
of what this skill actually sends, even though it is not bounded by any documented Revenium
contract.

The source constant remains the authoritative place the value lives; the number here is a
convenience for the reader, with the guard preventing drift. It is not a second source of truth.

When a payload exceeds the ceiling, the value family is dropped first, the provenance
family second, and base metering is never dropped — metering never breaks, only the
enrichment yields. A record whose payload was cut carries `metadata_truncated: true`, so a
consumer can tell "this job had no value" (both value keys and the marker absent) from "the
value did not fit" (`metadata_truncated` present). An unmarked partial record would be the
silent substitution this milestone exists to prevent.

The ceiling decides only what fits on the wire. It
does not decide what is worth reporting. The reportability decision (EGV-18) is made
upstream, by the resolver; the reporter only reads that decision and never computes it.

## LLM outcome-value evaluation (experimental)

> This section is the summary. **[Job value and ROI](value-and-roi.md)** is the complete
> reference — configuration, the evaluator's own bounds, the abstention vocabulary, the
> value derivation, costs and `net_value`, reportability, the sidecar record, the full wire
> shape, corrections, operations, and troubleshooting.

Opt-in, off by default. When enabled and a job's arc completes `SUCCESS`, the classifier
makes one separate, bounded LLM call on the user's own configured provider to estimate that
job's economic value. `FAILED` and `CANCELLED` arcs are never evaluated — there is no
economic outcome to estimate for an arc that did not finish successfully. The estimate is
derived from two independently bounded inputs (an assumed hours-saved figure and an assumed
loaded hourly rate, each capped by `maxHoursSaved` / `maxLoadedRate`), never asserted
directly by the model.

The result is an unverified model estimate: not measured,
observed, not customer-confirmed, and not defensible ROI on its own. Revenium computes the
ROI figure it displays from this reported value **combined with metered cost**; the estimate
is one input to that calculation, not the whole of it. See the assessment contract in
[`references/config-schema.md`](../skills/revenium/references/config-schema.md)
for the full bounds and validation rules.

`llmOutcomeEvaluation` is absent from `config.json` by
default, and the read **fails closed**: a missing, unreadable, or malformed config resolves
to disabled, never to estimating money by accident. An existing install upgrading into this
feature meters **byte-identically** to before — this is proven, not asserted by inspection:
the `jobs-outcome.golden.json` wire-shape fixture is unchanged by this feature, and the
fail-closed default is covered by its own tests.

Six terms describe evaluation outcomes across two log destinations:

- `evaluated`, `abstained`, `invalid`, and `timed-out` are written **in-process** by the
  classifier plugin, on the Python logger `revenium_classifier`, and land wherever Hermes'
  own logging is configured — not in `revenium-metering.log`. The exact lines:
  - `revenium-classifier: outcome evaluated job=%s value=%s %s`
  - `revenium-classifier: outcome evaluation abstained for job=%s`
  - `revenium-classifier: outcome evaluation invalid for job=%s`
  - `revenium-classifier: outcome evaluation timed-out for job=%s`
- `deferred` and `reported` are written by the **cron**, into `revenium-metering.log`. The
  exact line prefixes:
  - `outcome deferred: id=` (its aged form logs as `wedged job (no create confirmed after`)
  - `Outcome reported: agentic_job_id=`

No single file or command shows all six. `diagnose.sh`'s "LLM OUTCOME EVALUATION" section
reports, per profile, whether the switch is enabled, which evaluator is selected, and the
two cron-side counts (`deferred`/`wedged`, `reported`) from that profile's own log — and
names where the other four are written, rather than attempting to show them.

**Live verification against a real tenant (2026-08-24).** A real Hermes session against an
isolated development tenant produced an inferred job and reported its outcome exactly once
across two cron ticks. `revenium jobs roi <id>` returned the value but omitted
`evidence_class: MODEL_ESTIMATED_DEMO`, evaluator, confidence, and other provenance. That
metadata was visible through `jobs outcome-history` only. The primary ROI view therefore
does not distinguish this model estimate from a measured value.

The evaluator declined to produce a value for a trivial task. For a separate engineering
task, it produced a bounded `$250.00` estimate (`2.0` hours at `$125/hr`, confidence `0.9`).
The outcome is immutable and remains in the development tenant.

**What this run did NOT prove.** It covered one workstation, one development tenant, one
evaluator model, and two ticks. It did not test fleet behavior, concurrent ticks, another
provider, or value divided by non-zero metered cost. The free-tier model produced `$0.00`
metered cost and a null ROI.

Evaluator metadata identifies the implementation. The separately recorded `model` field,
read from `response.model`, identifies the model returned by the provider response.

### Inference locality facts (D-06, AMEND-D-07, EGV-21)

Every job assessment records two observable facts about the configured LLM: the resolved
inference provider name, and a derived address class taking exactly one of four values —
`loopback`, `private`, `public`, or `unset`. Both are read from a profile-scoped
`config.yaml`.

The address class is **derived from the configured endpoint, and the endpoint itself is
then discarded** — never stored, never transmitted. A `base_url` can embed an internal
hostname, a port, a path, or credentials, so the raw endpoint never crosses the wire. What
does cross is the derived address class together with the resolved provider name — the same
`inference_provider` key named in the provenance-family bullet above — never the raw string.
The class is derived without any name resolution, so an endpoint named by a hostname the
skill cannot verify is recorded in the conservative direction (`public`), never guessed as
`private` or `loopback`.

As with the deciding model, the class reflects the
CONFIGURED endpoint at the moment it was read, not a verified connection — exactly as
`evaluator`/`evaluator_version` above identify the implementation, not the deciding model.
A mid-flight provider failover is not observed by this field, the same way it is not
observed by `evaluator`/`evaluator_version` — only the separate `model` field, read from the
response itself, can capture it.

These two facts support an operator's judgment about their
deployment, not a conclusion about it. The skill can observe only where inference was
configured to go; it cannot observe the preprocessing, logging, or retention halves of the
path, so it records the part it can see and draws no conclusion from it. No statement here
should be read as saying where data went, was kept, was logged, or was retained — in either
a stated or a negated form.

## Tool-event metering

`post_tool_call` captures each Hermes tool call — name, duration in milliseconds,
success or failure, `tool_call_id`, session ID, error message — into
`~/.hermes/state/revenium/tool-events/<sid>.jsonl`.

The hook is a pure local observer. It makes no network call and exits 0 on any internal
failure, so it can never block the agent. The cron's `tool-event-report.sh` stage reads
those files and ships each unledgered record through `revenium meter tool-event`, keyed on
`<sid>:<tool_call_id>` in `revenium-tool-events.ledger`.

## Guardrail enforcement

Enforcement is structural. The `pre_llm_call` and `pre_tool_call` hooks read
`guardrail-status.json` on every turn and act on the warn/block band, which blocks the
agent deterministically no matter how long the session has run. The halt block in
`SKILL.md` is a procedural backstop; the hooks are the load-bearing path.

Before every operation the state resolves to one of four cases:

| State | What happens |
|---|---|
| All rules ok | Proceed silently. |
| A rule in the warn band | `pre_llm_call` emits one stderr line per (session, ruleId); the agent continues. |
| A rule in the block band, autonomous mode | `pre_tool_call` blocks every tool call with an `action: block` response, `pre_llm_call` injects the halt directive verbatim, and a notification carrying the latest enforcement event goes out through the configured Hermes messaging channel. |
| Status file missing | Proceed. Every in-session path fails open. |

`install-hooks.sh` registers the three hooks and `uninstall-hooks.sh` removes them. They
stay inert until approved on first `hermes chat`.

`guardrail-check.sh` refreshes `guardrail-status.json` each tick and detects new halt
transitions. Only a new transition notifies, and only `clear-halt.sh` can clear a halt —
nothing auto-clears.

The full halt contract, including the exact string the agent must emit verbatim, is in
[`SKILL.md`](../skills/revenium/SKILL.md).

## The `/revenium` command

Run `/revenium` inside a Hermes session to:

- View budget status: current spend, threshold, percent used, and halt state.
- Reset: recreate the budget rule with the same settings and zero current spend.
- Reconfigure: change the API key, budget amount, or period. This deletes the old rule and
  creates a new one.
