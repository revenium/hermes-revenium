# How it works

[← Documentation index](README.md)

This ships as a Hermes skill bundle, but the skill itself — `SKILL.md` — only carries a
halt-check backstop. The work is done by a plugin, three shell hooks, and a cron. See
[What's actually installed](../README.md#whats-actually-installed) for the split.

Those pieces fall into three parts, and they never call each other. The only coupling is
files under `~/.hermes/state/revenium/`.

1. **In-session.** The `revenium-classifier` **plugin** — Python that Hermes loads from
   `~/.hermes/plugins/` and calls at four lifecycle hooks — labels what each session was
   doing and writes marker files. Three **shell hooks**, registered in `config.yaml`,
   enforce guardrails and capture tool calls. None of this makes a network call.
2. **State files.** `config.json`, `guardrail-status.json`, the markers, the ledgers, the
   taxonomies. Every process re-reads what it needs; there is no shared memory and no IPC.
3. **The cron pipeline.** Once a minute, out of process, under one lock. This is the only
   part that talks to Revenium.

That separation is deliberate. A broken install degrades to "no enforcement, no
classification" — never to "agent blocked".

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
appends a compact record to a per-session spool — no network call, no LLM, no database read
on that path — and the cron's `api-event-report.sh` stage ships each record as its own row,
keyed on the provider's `api_request_id`.

The difference from the reporter above is what gets attributed. `hermes-report.sh` takes a
session's token delta and divides it across that session's markers. The event path reports
what each call actually used.

Two switches control it:

| Variable | Default | Effect |
|---|---|---|
| `REVENIUM_EVENT_METERING_MODE` | `shadow` | `shadow` computes rows without shipping; `live` ships them. |
| `REVENIUM_LEGACY_COMPLETIONS` | `enabled` | `enabled` keeps the delta reporter billing; `disabled` stands it down. |

**Setting `MODE=live` alone does not cut over.** While legacy stays enabled, an ownership
record decides which path bills a given session, and the outcome turns on a race you cannot
predict from the switches. A real cutover needs `REVENIUM_LEGACY_COMPLETIONS=disabled`.
[Event metering](event-metering.md) has the mechanism and the evidence.

Setting that fleet-wide is safe. Profiles whose sessions have drained cut over at once; the
rest keep billing through the legacy path until they drain, then cut over on their own. The
`drain-status.sh` stage maintains that gate.

A session's effective stale threshold is
`max(REVENIUM_DRAIN_STALE_SECONDS, REVENIUM_CRON_SETTLE_SECONDS + 86400)`, and it sets the
floor on how fast a profile can converge. **Check yours before planning a cutover — the
default is not the fast case.** At the stock `REVENIUM_DRAIN_STALE_SECONDS=604800`, a quiet
open session takes seven days to clear. Lower it to `86400` and the `settle + 86400` term
takes over, giving 87,000 seconds, or about 24.17 hours. That is the figure quoted in
[Event metering](event-metering.md), and it reflects one fleet's tuned configuration rather
than the default.

Rollback is the reverse: set `REVENIUM_LEGACY_COMPLETIONS=enabled` again, then
`REVENIUM_EVENT_METERING_MODE=shadow`.

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
  `net_value`, `assumptions`, `supplied_costs`, `cost_coverage`. The economic estimate and
  its inputs.
- **The provenance family** — `evaluator`, `evaluator_version`, `model`, `evidence_class`,
  `reportability_status`, `study_id`, `study_version`, `confidence`, `economic_mechanism`,
  `double_counting_group`, `correction_sequence`, `inference_provider`, and
  `inference_address_class`. Who or what produced the estimate, and where it was configured
  to run.

**A byte ceiling is enforced once, in the reporter, at emit** — the one place the actual
wire bytes exist before the payload leaves the machine. The ceiling's authoritative value
lives in `skills/revenium/scripts/hermes-report.sh` as `_METADATA_CEILING_BYTES`; read it
there rather than trusting a number repeated in prose.

**When a payload exceeds the ceiling**, the value family is dropped first, the provenance
family second, and base metering is never dropped — metering never breaks, only the
enrichment yields. A record whose payload was cut carries `metadata_truncated: true`, so a
consumer can tell "this job had no value" (both value keys and the marker absent) from "the
value did not fit" (`metadata_truncated` present). An unmarked partial record would be the
silent substitution this milestone exists to prevent.

**Transport, not policy.** The ceiling decides only what physically fits on the wire — it
makes no judgment about what is worth reporting. The reportability decision (EGV-18) is made
upstream, by the resolver; the reporter only reads that decision and never computes it.

## LLM outcome-value evaluation (experimental)

Opt-in, off by default. When enabled and a job's arc completes `SUCCESS`, the classifier
makes one separate, bounded LLM call on the user's own configured provider to estimate that
job's economic value. `FAILED` and `CANCELLED` arcs are never evaluated — there is no
economic outcome to estimate for an arc that did not finish successfully. The estimate is
derived from two independently bounded inputs (an assumed hours-saved figure and an assumed
loaded hourly rate, each capped by `maxHoursSaved` / `maxLoadedRate`), never asserted
directly by the model.

**What the number is.** The result is an **unverified model estimate** — not measured, not
observed, not customer-confirmed, and not defensible ROI on its own. Revenium computes the
ROI figure it displays from this reported value **combined with metered cost**; the estimate
is one input to that calculation, not the whole of it. See the assessment contract in
[`references/config-schema.md`](../skills/revenium/references/config-schema.md)
for the full bounds and validation rules.

**Default and upgrade behaviour.** `llmOutcomeEvaluation` is absent from `config.json` by
default, and the read **fails closed**: a missing, unreadable, or malformed config resolves
to disabled, never to estimating money by accident. An existing install upgrading into this
feature meters **byte-identically** to before — this is proven, not asserted by inspection:
the `jobs-outcome.golden.json` wire-shape fixture is unchanged by this feature, and the
fail-closed default is covered by its own tests.

**The log taxonomy spans two log destinations.** Six words describe every outcome an
evaluation attempt can reach, and they are not all written to the same place:

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

**Live verification against a real tenant (2026-08-24).** Every earlier phase of this
feature proved the chain above against fixtures, stubs, and a shell test double. It has
since been run once, end to end, against a real Hermes session and a real Revenium tenant:
a session produced an inferred job, the evaluator produced or correctly withheld an
assessment, the outcome was reported through the normal cron pipeline exactly once across
two ticks, and the result was read back live with `revenium jobs roi <id>`.

The run did not use the dedicated sandbox host this verification was originally scoped
against — that host was unreachable, and the only other available host with a real tenant
was a production fleet host deliberately excluded from this work, because the feature
writes estimated money into whatever tenant it touches. It ran instead on a throwaway
profile on a developer workstation, against an isolated development tenant. The substitution
narrows what the result covers, and the limits below are stated with that in mind.

What it wrote is permanent. The verification job and its reported outcome remain in that
development tenant: `revenium jobs outcome` is labelled immutable by the CLI itself, and
nothing this skill calls can retract a reported outcome. Whether deleting a job also
removes its outcome revisions was not tested. Anyone repeating this procedure should expect
the rows to stay.

The reported outcome carried `evidence_class: MODEL_ESTIMATED_DEMO` in its metadata,
alongside `evaluator`, `evaluator_version`, `confidence`, and both numeric assumptions the
estimate is built from. A reader inspecting the outcome's own metadata can tell this number
apart from a measured one — but `revenium jobs roi <id>` itself, in both its JSON and table
output, surfaced none of that: no `evidence_class`, no `evaluator`, no `confidence`, nothing
distinguishing an estimate from a measurement. The estimated value is shown with the exact
same visual weight a measured value would get. Only the separate `jobs outcome-history`
command echoes the metadata blob at all. **The honesty burden for stating that a value is an
unverified model estimate therefore rests entirely on this skill's own `--metadata` payload
and on documentation like this page — not on anything Revenium's primary read-back
surfaces.**

Both outcomes were observed, not just the successful one. A trivial, low-stakes task
produced a genuine `SUCCESS` job, and the evaluator declined to produce a value — no
assessment, nothing reported. A separate, realistic, bounded engineering task produced a
`SUCCESS` job with a complete, non-inflated assessment (`$250.00` USD, `2.0` hours at
`$125/hr`, confidence `0.9`), which was reported and read back unchanged. Read together, the
pair shows the evaluator discriminating rather than assigning a number to every successful
arc regardless of merit — an evaluator that never abstains would be indistinguishable from
one that always inflates.

**What this run did NOT prove.** One arc reported, on one workstation, against one isolated
dev tenant, with one evaluator model, across two cron ticks. It says nothing about fleet or
multi-profile behavior, nothing about idempotency across more than two ticks or concurrent
ticks, and nothing about evaluator behavior on a different LLM provider.

It also did not exercise the value-against-cost calculation. The verification session ran on
a free-tier model, so its metered cost was genuinely `$0.00` and the read-back returned a
null ROI — the correct answer to a value divided by no cost, but a degenerate one. The
reported value was proven end to end; the ratio Revenium computes from that value and the
metered cost was not.

One provenance limit is worth stating alongside the metadata above. `evaluator` and
`evaluator_version` identify the evaluator *implementation*, not the deciding model — the
evaluator issues an unpinned call and the host routes it, so a provider failover can change
the deciding model without changing either field. A third, separately recorded field closes
that gap: `model` is read directly from the LLM response (`response.model`) and clamped to a
fixed byte budget before persistence, so an estimate's metadata establishes not just that a
model produced it under stated assumptions, but which one served the call.

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

**This limit matches the one stated above for the deciding model.** The class reflects the
CONFIGURED endpoint at the moment it was read, not a verified connection — exactly as
`evaluator`/`evaluator_version` above identify the implementation, not the deciding model.
A mid-flight provider failover is not observed by this field, the same way it is not
observed by `evaluator`/`evaluator_version` — only the separate `model` field, read from the
response itself, can capture it.

**What these two facts are NOT.** They are inputs to an operator's own judgment about their
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

- **View budget status** — current spend, threshold, percent used, halt state.
- **Reset** — recreate the budget rule with the same settings, zeroing current spend.
- **Reconfigure** — change API key, budget amount, or period. This deletes the old rule and
  creates a new one.
