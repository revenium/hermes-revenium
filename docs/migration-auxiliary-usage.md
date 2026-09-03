# Migrating to Auxiliary Usage Metering (v1.5)

This guide documents the Phase 55 upgrade that meters the auxiliary LLM calls
Hermes makes around its main loop: compression, title generation,
approval, vision, web extraction, and session search. Before this upgrade, none
of that spend was reported to Revenium or counted by any guardrail rule. After
it, every auxiliary call ships as its own metered completion.

Reported spend permanently increases for unchanged traffic because existing
auxiliary spend becomes visible. A guardrail threshold tuned before this
upgrade may trip earlier than it used to. Read this document before upgrading
if you run autonomous-mode guardrails close to their limit.

## What changed

`hermes-report.sh` contained zero references to the Hermes `session_model_usage`
table before this phase. It now reads that table on every cron tick, as a
dedicated post-loop pass (`report_auxiliary_usage`) that runs after the
main-loop completion pass and the agentic-jobs outcome stage. Six auxiliary
call kinds are recognised, each with its own `aux_`-prefixed task-type label:

- `aux_approval`
- `aux_title_generation`
- `aux_compression`
- `aux_vision`
- `aux_web_extract`
- `aux_session_search`

Each row in `session_model_usage` with a non-empty `task` column ships as its
own `revenium meter completion` call, carrying `--operation-type AUX` and
`--task-type aux_<label>`. A `session_model_usage.task` value with no matching
label ships anyway, as `--task-type aux_unclassified`, so a future upstream
addition never silently drops spend — it surfaces as one warn per distinct
unrecognised value per install instead.

The same traffic now produces more rows and a higher reported total because
the reporter includes previously unreported auxiliary spend.

## The step-up, with its caveat

Measured fleet-wide across ten production profiles' whole retained session
history, dated 2026-08-15 (`docs/internal/auxiliary-usage-sizing.md`, which
this section summarizes for the tracked record):

- **Fleet-wide auxiliary cost share: 0.4598%** of total metered spend.
- **Fleet-wide auxiliary token share: 0.1042%** of total metered tokens.
- Two per-profile outliers crossed the fleet figure by a wide margin:
  **`cfo` at 3.0634%** and **`playtester` at 2.0723%**.

Both outliers have near-zero denominators and are not representative.
`cfo`'s total spend across its whole retained history was $3.66; `playtester`'s
was $0.026. On both profiles a handful of `approval` calls dominate the
auxiliary figure, so a 3% or 2% share is an artifact of a tiny total, not a
signal that auxiliary spend is typically that large a fraction of a profile's
budget. Do not read either figure as an expected range for a normal-traffic
install — the fleet-wide 0.4598% is the representative number, and even that
carries the same caveat in miniature (`approval` alone is 95.83% of all
auxiliary cost fleet-wide).

You can rerun this read-only measurement against your own `state.db` with the
following three `sqlite3` `SELECT` statements. They do not write to any session
database.

```sql
-- Total spend and tokens, same population hermes-report.sh already meters.
SELECT COALESCE(SUM(estimated_cost_usd), 0) AS total_cost,
       COALESCE(SUM(input_tokens + output_tokens + cache_read_tokens + cache_write_tokens), 0) AS total_tokens
FROM sessions
WHERE input_tokens > 0 OR output_tokens > 0;

-- Auxiliary aggregate. The non-empty-task filter is load-bearing — see
-- "Which rules count it, and which do not" below for why an empty task is
-- excluded, and "auxiliary ledger growth" for the ledger this pass writes to.
SELECT COALESCE(SUM(estimated_cost_usd), 0) AS aux_cost,
       COALESCE(SUM(input_tokens + output_tokens + cache_read_tokens + cache_write_tokens), 0) AS aux_tokens
FROM session_model_usage
WHERE task != '';

-- Per-native-task breakdown, so you can see which auxiliary work dominates
-- on your own host rather than trusting a fleet average.
SELECT task, COUNT(*) AS rows,
       SUM(input_tokens + output_tokens + cache_read_tokens + cache_write_tokens) AS tokens,
       SUM(estimated_cost_usd) AS cost
FROM session_model_usage
WHERE task != ''
GROUP BY task;
```

Compute your own number rather than assuming the fleet average applies to your
install — a low-traffic install is exactly where an outlier like `cfo` or
`playtester` can appear.

## The first tick is a catch-up, and here is why

`session_model_usage`'s counters are cumulative (they accumulate for the
lifetime of a session/model/provider/URL/mode/task identity), and the new
`revenium-aux.ledger` starts empty on every install upgrading into this
release. That combination means **the first cron tick after upgrading reports
each identity's entire accumulated auxiliary usage — potentially months of
it — into the current guardrail window**, exactly the same way the main-loop
reporter has always behaved on a session it has never seen before (a
zero-previous-total session ships its full cumulative total on first sight).

This is previously unreported spend, not a duplicate. Planning rejected a
ledger baseline that would discard observed spend on the first tick. As a
result, a guardrail threshold near its hard limit may trip on the first tick
after upgrade,
because that tick's figure includes a one-time historical catch-up on top of
ordinary current-window spend. Treat the first post-upgrade tick's auxiliary
total as a one-time historical figure, not a new baseline for future ticks.

The reporter also warns about this directly. The first successful auxiliary
emission on an install fires a once-per-install `warn` line naming both the
permanent step-up and this historical catch-up, and pointing back to this
document and the off switch below.

## Which rules count it, and which do not

A freshly-created guardrail rule (via `setup-guardrails.sh`, with no explicit
`--filter`) default-scopes to `--filter AGENT:IS:${REVENIUM_AGENT_NAME}`. Every
auxiliary row ships with the same `--agent` value as its own session's
main-loop completion, so **the default rule counts auxiliary spend
automatically, with no operator action required.**

Three scoping choices change that:

- **A rule scoped on `TASK_TYPE`** does not count auxiliary rows unless the
  operator explicitly adds the six `aux_*` labels (or `aux_unclassified`) to
  that rule's filter. `TASK_TYPE`-scoped rules are opt-in for auxiliary spend
  by construction — the `aux_` prefix exists specifically so this exclusion is
  a deliberate choice rather than an accident.
- **A rule scoped on `MODEL`** counts an auxiliary row only when the
  auxiliary call actually ran on the scoped model. Auxiliary calls frequently
  run on a smaller or cheaper model than the session's main-loop model, so a
  `MODEL`-scoped rule built around your primary model will systematically
  undercount — or miss entirely — the auxiliary spend running alongside it.
- **A rule scoped on `PROVIDER`** now counts rows whose `billing_provider`
  column is the literal string `auto` — this phase resolves `auto` through
  model-name inference on both the main-loop and auxiliary emit paths, from
  one shared function. Before this phase, a `billing_provider` of `auto`
  reached the `PROVIDER` dimension as `auto` and was silently omitted by any
  provider-scoped rule filtering on a real provider name. **This resolution
  is global — it changes provider-scoped counting for main-loop rows too, not
  only auxiliary ones — and rows Revenium already ingested with `auto` are
  not back-filled.**

The only filter operators this repo documents anywhere are `IS` and `IS_NOT`
(`setup-guardrails.sh --help`). There is no supported way to match a whole
label prefix or substring on `TASK_TYPE` — an operator who wants a rule to
count every `aux_*` label must enumerate them.

## The limit on ROI-10, stated with the passes

Guardrail counting occurs server-side: Revenium counts what it
actually ingested, filtered through the rule's own scope, against the
currently-billed window. This phase proves, locally and repeatably, that an
auxiliary row is *emitted* carrying the same scope-bearing dimensions as its
own session's main-loop completion — `--agent`, `--organization-name`,
`--environment`, `--trace-id`, `--trace-type`, the three squad flags, and
`--agentic-job-id` all match; `MODEL` and `PROVIDER` are the row's own facts
(named above); `TASK_TYPE` and `OPERATION_TYPE` diverge by design.

This phase does not observe the Revenium-side counter moving. Confirmation that
a real tenant's guardrail evaluation increases by an
auxiliary row's metered amount once ingested inside a rule's scope — is
Phase 56's, against a real tenant. Stated here, in the same place as the
passes, rather than left as a silent gap: the local proof establishes *scope
match at emission*; the server-side *counting* half is confirmed live later.

## Switching it off

Set `REVENIUM_AUX_METERING=disabled` in `~/.hermes/state/revenium/env`, or set
the `auxMetering` key to `"disabled"` in `config.json`. The environment
variable takes precedence over the config key when both are set.

With auxiliary metering disabled:

- Zero `--operation-type AUX` completions are shipped, on any tick.
- No `revenium-aux.ledger` is written.
- Main-loop metering is byte-identical to what it was before this upgrade.

An install whose Hermes build predates the `session_model_usage` table is
byte-identical by construction — the auxiliary pass detects the table's
absence via a read-only `sqlite_master` probe, logs one `info` line naming
that exact reason, and ships nothing. It needs no `REVENIUM_AUX_METERING`
setting to behave this way.

`REVENIUM_AUX_METERING=disabled` lets an operator hold reported spend steady
during a guardrail cutover while retuning thresholds. It is not the recommended
posture. The default is on because auxiliary spend is part of total spend.

## Auxiliary ledger growth (out of scope, recorded here so it is not a surprise)

`revenium-aux.ledger` grows without bound, the same as the three pre-existing
ledgers it sits alongside (`revenium-hermes.ledger`, `revenium-jobs.ledger`,
`revenium-tool-events.ledger`). None of the four is pruned automatically.
`prune-markers.sh` covers marker files only, and is deliberately not wired
into cron — it is an operator-run, manual GC tool. This is named here
explicitly so an operator who eventually notices ledger file size growth
recognises it as an existing, accepted characteristic of every ledger this
skill maintains, not a new defect introduced by this phase.

## What would invalidate this

If `report_auxiliary_usage` in `skills/revenium/scripts/hermes-report.sh`, or
the shared provider-inference function `_infer_provider` it calls, changes
its query, its scope-dimension resolution, or its ledger key shape, the
figures and guarantees in this document need to be re-verified. The tests
that hold this document's claims honest today are:

- `tests/test_phase55_auxiliary_metering.py` — the end-to-end tracer: one
  `session_model_usage` row to a metered `AUX` completion to an `AUX:`
  ledger line, the off-switch arms, and the absent-table arm.
- `tests/test_phase55_aux_edges.py` — the `auto`-provider resolution, the
  `aux_unclassified` fallback and its once-per-value warn, and the
  once-per-install step-up notice this document describes above.
- `tests/test_phase55_aux_proofs.py` — the adversarial mirror-bucket proof
  (an empty-`task` row must never itself ship as an auxiliary row), the
  cross-tick idempotency proof, and the ROI-10 scope-parity assertion this
  document's "limit on ROI-10" section describes.
- `tests/test_compat_meter_completion_aux.py` — the auxiliary path's own
  pinned argv shape.
- `tests/test_compat_v1_4_meta.py` — the umbrella regression trip-wire
  confirming the four pre-existing v1.x golden fixtures (main-loop
  completions, jobs, tool-events) stay byte-identical; the auxiliary golden
  above is additive to, not part of, that immutability contract.

If any of these goes red, treat the claims in this document as unverified
until it is re-confirmed against the current code.
