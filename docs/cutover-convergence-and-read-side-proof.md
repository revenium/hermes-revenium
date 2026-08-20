# Fleet Cutover Convergence and Read-Side Proof — 8/10 Converged, Attestation Not Given, Read-Side Confirmed

## Verdict

**Both requirements close, with two honest shortfalls stated up front, not
one: CUT-01 closes at 8 of 10 profiles converged, not 10 of 10 — gtm and
community have NOT converged as of this document's close, each carrying the
same named, source-grounded cause diagnosed at scope time. SEPARATELY, and
more consequentially: the "unforced" half of CUT-01's claim is qualified,
not proven. At this plan's Task 4 blocking checkpoint the operator was
asked to attest that no profile was manually touched during the observation
window; the operator did NOT give that attestation — verbatim: "It may have
been touched but doesnt matter if so" — and declined to name a profile. The
mechanical evidence below is real and stands on its own, but it does not
cover the full span between the 2026-08-19 cutover flip and this phase's
first observation, and this document therefore reports CUT-01 as CLOSED AT
8/10 WITH AN UNATTESTED QUALIFIER, not as a clean unforced pass. CUT-02
closes: every non-cost dimension ROADMAP success criterion 3 names is
confirmed read-side, and both clauses left open at scope time
(`agenticJobId`, multi-model attribution) are resolved either way with
evidence, per ROADMAP success criterion 4 — with one scope limit stated here
rather than buried: `agenticJobId`'s resolution is structural for ROOT
sessions and merely OBSERVATIONAL for SUBAGENT sessions, where the mechanism
in fact favours presence. That half is labelled UNVERIFIED throughout and is
the one item this phase hands forward.**

**CUT-01, final state as of 2026-08-20T05:12-05:13Z (Task 3 of this
plan, qualifier added at Task 4):** 8 of 10 converged (unforced by this
phase's own hand; NOT independently attested — see below) — marketing,
devops, qa, coder,
playtester, cfo, pm (converged by 33-01's Round 3, `03:57:51Z`, still
converged 1h15m later) plus **lorekeeper**, which fully converged between
Round 3 and this final sample, right on the earliest-possible bound Round 3
itself computed (`≈2026-08-20T05:01:59Z`, observed `05:12:21Z`). **gtm**
(5 pending → 2 pending, partial progress — its two slowest sessions remain,
cause unchanged: open in `state.db`, staleness route, earliest full
convergence `≈2026-08-20T16:59:12Z`) and **community** (1 pending,
unchanged — same session, cause unchanged, earliest convergence
`≈2026-08-20T21:33:13Z`) are the two profiles CUT-01 does not close for.

**PROVEN, mechanically, no attestation needed:** all ten `env` files carry
one identical modification timestamp inside the documented
`2026-08-19T21:12–21:40Z` cutover flip window, and none is later — this
rules out an `env` edit on any profile at any point through this document's
close. Separately, no plan in phase 33 issued any side-effecting command
against the fleet host or the Revenium tenant across this phase's own
1h37m observation window (`03:36Z`–`05:13Z`, from 33-01's Task 1 tracer
through this final sample): no `revenium meter`, no `jobs create`/`outcome`,
no `guardrails ... create`/`update`/`delete`, no write to any profile's
`config.json`/`drain-status.json`/ledger, no `clear-halt.sh`, no gateway
restart, no `rsync` to the host — every command this phase itself issued is
enumerated in the query ledger below.

**NOT ESTABLISHED:** an operator attestation of non-intervention was
requested at this plan's Task 4 blocking checkpoint and was NOT given. The
operator's verbatim response: **"It may have been touched but doesnt matter
if so."** No profile was named as touched, and none was named as clear of
suspicion either. A `clear-halt.sh` run, a gateway restart, or a
`drain-status.json`/ledger edit by a human or an out-of-band process
therefore CANNOT be excluded by anything in this document. Most of the
cutover→convergence span — 2026-08-19 ~21:12Z (the flip) through 33-01's
first observation at `03:36Z` on 2026-08-20, roughly 6.5 hours — predates
any observation by this phase entirely, so the mechanical evidence above
covers only part of the window CUT-01's "without manual intervention"
language spans. This gap is reported, not chased: the phase's observation
window is closed, and this document does not go back to the host to try to
settle it after the fact.

**CUT-02, final state as of 2026-08-20 (Tasks 1–2 of plan 33-02, Tasks 1–2
of this plan):** every dimension ROADMAP success criterion 3 names is
CONFIRMED read-side, quoted verbatim from live `revenium metrics ai` /
`squads get` / `squads timeline` / `squads list` / `squads executions` /
`jobs get` / `jobs transactions` responses: `taskType`, `operationType`,
`traceId`, `traceType`, `agent`, `squadId`, `model`, `provider`,
`transactionId`, `squadName`, and per-call attribution. Both clauses ROADMAP
success criterion 4 named as open are now RESOLVED, one of them with a
narrower scope than an earlier draft claimed: **`agenticJobId`
RESOLVED-ABSENT FOR ROOT SESSIONS, UNVERIFIED FOR SUBAGENT SESSIONS.** For a
root session it can never reach a metered row, by permanent construction
(`classifier.py:999`) — that half is structural and settled. For a subagent
session, absence is only an OBSERVATION over the rows this phase sampled,
confirmed live via two independent `revenium jobs transactions` calls both
returning `totalCount: 0`. It is not a mechanism result: per-turn
classification (Phase 29's `post_llm_call` hook) normally writes the root's
job marker on the root's FIRST completed turn, so a subagent dispatched after
that inherits the field and its row would carry it. See `## Findings` — the
ordering argument an earlier draft rested this half on was backwards, and is
corrected there rather than quietly dropped. **Multi-model attribution RESOLVED as mechanism-verified,
trigger-unfired-within-a-single-trace** — `fallback_providers` is configured
on all ten profiles and demonstrably live for two of them (marketing and
cfo run every sampled trace on their fallback model, never their
configured primary), but a bounded 26-trace search found no trace where two
distinct models co-occur under one `traceId`. This is explicitly NOT
"structurally cannot be recorded" — the mechanism-verified, fleet-wide
evidence refutes that framing, which STATE.md and the ROADMAP both carried
at scope time and this document corrects. `squadName` remains CONFIRMED
present with one still-open, honestly-recorded finding (its value does not
match either sampled profile's own `--squad-name` argv) — CUT-02's own
wording ("confirmed on the read side") does not require that mismatch to be
resolved, only the dimension's presence, which it is.

Every `$0` cost figure quoted anywhere in this document is captioned
**operator decision (BACK-2676 out of scope), not a metering defect** at
the point it is quoted — see `## Known limitations and exclusions`.

Date this section was last written: 2026-08-20 (Task 4 of plan 33-03,
after the blocking checkpoint's operator response).

## Why this document exists

The planning directory that captured this observation is excluded from
version control, so this file is the committed mirror of the headline
findings and the replayable method. Deleting it turns a later phase's own
repository pin red (Phase 35 / CUT-07 registers this file in
`tests/test_repository.py::test_expected_files_exist`), which is the whole
point: a verdict that only exists in an untracked directory is a verdict
that did not happen.

## What was measured

Population: the ten fleet profiles cut over on 2026-08-19
(`gtm, marketing, devops, qa, coder, playtester, cfo, pm, community,
lorekeeper`) on the fleet host, and the Revenium dev tenant those profiles
report to.

Method, for both halves of this phase:

- **Convergence (CUT-01):** read-only inspection of each profile's
  `state/revenium/drain-status.json` and `state/revenium/revenium-metering.log`,
  sampled repeatedly over real wall-clock time. `drain-status.sh` itself
  makes zero HTTP calls — it computes its verdict from two local sources
  (the legacy ledger and `state.db`) — so this phase's job is purely to
  *observe* that local computation, never to influence it.
- **Read-side proof (CUT-02, and the tracer's own read-side slice):**
  `revenium` CLI read verbs only (`metrics ai`, `jobs get`/`transactions`,
  `squads get`/`list`, `config show`) against the live Revenium dev tenant.

Every command issued BY THIS PHASE on the host was one of: `ssh`, `cat`,
`head`, `tail`, `grep`, `stat`, `ls`, `python3` (reading JSON), `sqlite3` in
read-only URI mode, and the `revenium` CLI's read subcommands. No `revenium
meter`, no `jobs create`/`outcome`, no `guardrails ... create`/`update`/
`delete`, no write to any profile's `env`/`config.json`/`drain-status.json`/
ledger, no `clear-halt.sh`, no gateway restart, no `rsync` to the host, was
issued by any of this phase's three plans. **This is a claim about what
this phase itself did, not a claim about the whole cutover→convergence
span.** Whether any profile was touched by a human or an out-of-band
process outside this phase's own commands is NOT established — see
`## Verdict` and `## Findings` for the Task 4 checkpoint's outcome, where
the operator declined to attest to non-intervention.

## Known limitations and exclusions

**The write-loss window is `2026-08-19T18:25:00Z` through
`2026-08-20T01:24:00Z`, closed at both ends.** Revenium's dev tenant
accepted writes and silently discarded them across that span while
returning success (documented in `.planning/STATE.md`'s "Revenium dev
outage" section). A row timestamped at exactly either endpoint is INSIDE
the suspect window. Every read-side query in this document states its
`--from`/`--to` window and confirms it falls entirely outside that
interval. Data absent from that window is Revenium's own data loss, not a
metering defect, and is never chased as one here.

**Cost is `$0` by operator decision (CUT-08 / BACK-2676 out of scope).**
This pre-prod dev tenant's cost figures are $0 by explicit operator choice,
not because nothing was metered — see `docs/auxiliary-usage-sizing.md` and
`.planning/STATE.md` for the full history. Every `totalCost: 0` figure
quoted in this document carries the caption below.

**Scope boundary — other phases' work, not this one's:** CUT-03
reconciliation (no-gap/no-double-count across the cutover boundary), the
`docs/event-metering.md` correction, rollback demonstration, and the
BACK-2676 cost prerequisite are Phase 34/35 work and are not addressed
here.

**The unforced-convergence attestation was requested and NOT given — a
named, first-class limitation on CUT-01, not a footnote.** This plan's
Task 4 was a blocking checkpoint asking the operator to attest that no
fleet profile was manually touched during the observation window. The
operator's verbatim response: **"It may have been touched but doesnt
matter if so."** No profile was named as touched. Offered the choice
between qualifying the claim or failing CUT-01 for an unnamed profile, the
operator chose to qualify: keep CUT-01 closing at 8/10, but stop asserting
an absence nobody confirmed. This document therefore separates what is
mechanically PROVEN (this phase's own commands were all reads; all ten
`env` files share one identical pre-flip modification time) from what is
NOT ESTABLISHED (whether any profile was touched by a human or an
out-of-band process, particularly across the ~6.5 hours between the
2026-08-19 cutover flip and this phase's first observation). See
`## Verdict` and `## Findings` for the full statement.

## Results

### Tracer — one profile, one event row (Task 1 of this plan)

**Convergence half — `playtester`.** Read from
`<profile-state-dir>/drain-status.json` at `2026-08-20T03:36-03:38Z`:

| Field | Value |
|---|---|
| `drained` | `true` |
| `determined` | `true` |
| `pendingCount` | `0` |
| `lastChecked` | `2026-08-20T03:36:28Z` |
| `staleSecondsConfigured` | `86400.0` |
| `staleSecondsEffective` | `87000.0` |
| `staleEnabled` | `true` |

Corroborating log line, `<profile-state-dir>/revenium-metering.log`, most
recent occurrence before the sample above:

```
[2026-08-20T03:36:24Z] [INFO ] [revenium] legacy completions path disabled — drain gate reports drained; skipping legacy completion emission this run.
```

This is the `hermes-report.sh:187` line. The JSON says what the drain gate
decided; this log line proves `hermes-report.sh` actually acted on that
verdict and skipped legacy completion emission on this tick. Neither alone
would be sufficient — a profile with `REVENIUM_LEGACY_COMPLETIONS=disabled`
in its `env` but no corroborating `:187` line would only prove the switch
was *set*, not that the reporter *currently* honors it (the exact
presence-vs-currency error a prior phase made when it reported ten healthy
profiles while nine ran a stale classifier).

**Read-side half — one metered event row.** First query, narrow window
`--from 2026-08-20T02:00:00Z --to 2026-08-20T03:40:00Z --output json
--page-size 200 --page 0`, returned 100 rows (of 2 pages) and **zero**
Hermes-owned rows (filtering client-side on `agent` starting with `Hermes`
or `label` starting with `event:` — there is no server-side filter on this
verb; see Pitfall note below). Per this task's own instruction, that null
result was not retried into a pass — the window was widened once, still
entirely after the write-loss window's close:

```
revenium metrics ai --from 2026-08-20T01:24:01Z --to 2026-08-20T03:41:00Z \
  --output json --page-size 200 --page N   # N = 0..3
```

That window's non-overlap with `2026-08-19T18:25:00Z`–`2026-08-20T01:24:00Z`
is exact: it starts one second after the suspect window's closed upper
bound. Across 400 total rows (pages 0-3 of 5), 4 were Hermes-owned. One is
quoted here, for `playtester`:

| Field | Value |
|---|---|
| `taskType` | `post_fix_probe` |
| `operationType` | `CHAT` |
| `traceId` | `<sid-A>` |
| `traceType` | `smoke_test` |
| `agent` | `Hermes-playtester` |
| `squadId` | `<sid-A>` |
| `model` | `accounts/fireworks/models/glm-5p2` |
| `transactionId` | `event:<sid-A>:<sid-A>:<hash-A>:api:1` |
| `totalCost` | `0` — **$0 by operator decision (BACK-2676 out of scope), not a metering defect** |
| `created` | `2026-08-20T01:48:46.521Z` |

All fields required by this task's acceptance criteria
(`taskType`/`operationType`/`traceId`/`traceType`/`agent`/`squadId`/
`transactionId`) are present and non-empty. The query window
(`2026-08-20T01:24:01Z`–`2026-08-20T03:41:00Z`) falls entirely after the
write-loss interval's close.

### CUT-01 — ten-profile convergence table

Sampled at three rounds, spaced well beyond the five-minute minimum (Round
1→2: 5m59s; Round 2→3: 9m46s — both exceed the five-minute floor this task
requires, and both comfortably exceed one cron tick, so each round reflects
an independently computed drain-gate verdict, not the same tick read
twice):

| Round | Timestamp (UTC) |
|---|---|
| 1 | 2026-08-20T03:42:06Z |
| 2 | 2026-08-20T03:48:05Z |
| 3 | 2026-08-20T03:57:51Z |

| Profile | R1 `drained`/`pendingCount` | R2 | R3 | Status | Cause if pending (see `## Findings`) |
|---|---|---|---|---|---|
| gtm | false / 5 | false / 5 | false / 5 | **PENDING** | 5 open sessions, staleness route; earliest full convergence ≈ 2026-08-20T16:59:11Z |
| marketing | true / 0 | true / 0 | true / 0 | **CONVERGED** | — |
| devops | true / 0 | true / 0 | true / 0 | **CONVERGED** | — |
| qa | true / 0 | true / 0 | true / 0 | **CONVERGED** | — |
| coder | true / 0 | true / 0 | true / 0 | **CONVERGED** | — |
| playtester | true / 0 | true / 0 | true / 0 | **CONVERGED** | — |
| cfo | true / 0 | true / 0 | true / 0 | **CONVERGED** | — |
| pm | true / 0 | true / 0 | true / 0 | **CONVERGED** | — |
| community | false / 1 | false / 1 | false / 1 | **PENDING** | 1 open session, staleness route; earliest full convergence ≈ 2026-08-20T21:33:13Z |
| lorekeeper | false / 5 | false / 5 | false / 5 | **PENDING** | 5 open sessions, staleness route; earliest full convergence ≈ 2026-08-20T05:01:59Z |

**7 of 10 converged, with zero disagreement across all three rounds of
this observation window; no `drained` state flip between rounds.** Contrast
with `33-RESEARCH.md`'s earlier observation of `coder` flapping
drained→un-drained→drained across a *different, wider* window on
2026-08-19/20, which is why this task samples repeatedly rather than
trusting one reading (the gate is known to flap in general; it simply did
not flap during these particular three rounds). The word "unforced" here
describes what this document can mechanically show — this task's own
commands never wrote to any profile — not a settled fact about the whole
cutover→convergence span; see `## Verdict` and `## Known limitations and
exclusions` for why "unforced" carries a qualifier as of Task 4's
checkpoint.

**This table reflects Round 1-3 only (33-01, `03:42-03:57Z`) and is left
unchanged here.** The observation window continued past Round 3; a fourth,
final re-sample closes it in `## Independent confirmation` →
"CUT-01 — final re-sample, closing the observation window" (Task 3 of plan
33-03), which is authoritative for the phase's CUT-01 count (8 of 10 by
that point — lorekeeper converged, gtm partially converged) — **closed WITH
the unattested-intervention qualifier stated in `## Verdict`, not as a
clean unforced pass.** This table is kept exactly as 33-01 wrote it, not
edited to match the later reading, so the progression between rounds stays
visible.

**First-observed-drained, scoped to this cutover.** Every converged
profile's `revenium-metering.log` was searched for its FIRST occurrence of
the `hermes-report.sh:187` line at or after `2026-08-19T21:12:00Z` — the
documented start of the fleet-wide cutover flip — rather than the file's
absolute first occurrence. This scoping matters: two profiles (`qa`, `cfo`)
carry a `:187` line from **2026-08-18**, a full day before this cutover,
almost certainly a residue of earlier per-profile probing (e.g. the SC-8
disposable-rule run, the catalog probes — both recorded in
`.planning/STATE.md` as touching specific profiles' `env`/config before the
fleet-wide flip). Reporting that earlier line as "first observed drained"
would misattribute a different event to this cutover; the cutover-scoped
value is the one that answers CUT-01.

| Profile | First-observed-drained (cutover-scoped, obs.-bounded) | Immediately preceding `refusing to disable` line |
|---|---|---|
| devops | `2026-08-19T21:34:25Z` | none found in the 21:12–22:00Z window — already drained at the first post-flip check |
| qa | `2026-08-19T21:34:24Z` | none found in the 21:12–22:00Z window — already drained at the first post-flip check |
| playtester | `2026-08-19T21:34:48Z` | none found in the 21:12–22:00Z window — already drained at the first post-flip check |
| pm | `2026-08-19T21:35:14Z` | none found in the 21:12–22:00Z window — already drained at the first post-flip check |
| cfo | `2026-08-19T21:36:42Z` | `2026-08-19T21:34:51Z`, pending=2 |
| marketing | `2026-08-19T21:37:27Z` | `2026-08-19T21:35:28Z`, pending=1 |
| coder | `2026-08-19T21:38:33Z` | `2026-08-19T21:34:35Z`, pending=3 |

**These timestamps are a sampling-cadence artifact, not the true
convergence instant** — the cron ticks roughly once a minute, so the true
transition for each profile happened somewhere between its last
`refusing`/absent-refusal check and the quoted `:187` line, an interval on
the order of the tick spacing shown above (under two minutes in every case
here). No claim is made that these exact timestamps would reproduce on a
re-run of this same query.

**Env-mtime evidence for unforced convergence (gathered once, not per
round — an mtime does not change between samples unless the file is
written again).** All ten profiles' `state/revenium/env` files carry the
identical modification timestamp `2026-08-19T21:33:57.9xxxxxxxx +0000`
(sub-second offsets differ, whole-second value identical across all ten) —
squarely inside the documented `21:12–21:40Z` cutover flip window, and nine
of ten register within the same 21:33:57 second. **No profile's `env` file
carries a modification time later than the cutover flip.** This is the
closest thing to positive evidence for the absence of a later manual
write, and its limit is stated plainly: an mtime proves the file was not
*rewritten*, not that no other kind of manual action (a `clear-halt.sh`
run, a gateway restart, a direct ledger edit) occurred. This limit is no
longer merely theoretical: at Task 4's blocking checkpoint the operator was
explicitly asked to attest to the absence of exactly this kind of action
and declined — "It may have been touched but doesnt matter if so" — so the
gap this paragraph flags is not an abstract caveat, it is the specific gap
Task 4 found unfilled. See `## Verdict` and `## Known limitations and
exclusions`.

### CUT-02 — read-side dimension confirmation (task type, operation type, trace id/type, agentic job id, squad, per-call, multi-model)

**Row-level dimensions and per-call attribution (Task 1 of this plan, queried
2026-08-20T04:12Z).** Query:

```
revenium metrics ai --from 2026-08-20T01:24:01Z --to 2026-08-20T04:12:00Z \
  --output json --page-size 200 --page N   # N = 0..6
```

This window starts one second after the write-loss interval's closed upper
bound (`2026-08-19T18:25:00Z`–`2026-08-20T01:24:00Z`) and ends at query time —
entirely outside it. 635 total rows across all 7 pages; 4 Hermes-owned
(filtered client-side on `agent` starting with `Hermes` or `label` starting
with `event:` — there is still no server-side filter on this verb). All 4 are
the same rows the plan 33-01 tracer found in its own, narrower post-outage
window nearly three hours earlier — an independent re-query run for this
plan finds nothing new and nothing missing, which is exactly the stability a
repeat query is meant to demonstrate rather than a copy-forward of the
earlier numbers.

Dimension table, each CONFIRMED against the quoted response above:

| Dimension | Value(s) confirmed |
|---|---|
| `taskType` | `post_fix_probe`, `subagent_ping_test`, `ping_pong_check` |
| `operationType` | `CHAT` |
| `traceId` | `<sid-A>` (playtester), `<sid-B>` (coder root + its subagent share this traceId) |
| `traceType` | `smoke_test`, `canary_probe_check` |
| `agent` | `Hermes-playtester`, `Hermes-coder` |
| `squadId` | equals `traceId` in every row observed |
| `model` | `accounts/fireworks/models/glm-5p2` (all four rows in this narrow sample — NOT the fleet's single primary model: `playtester`/`coder` are configured with `fireworks/glm-5p2` as primary, but `marketing`/`cfo`/`gtm`/etc. are configured with `zai/glm-4.6` as primary; see `## Findings` → "Multi-model attribution" for the fleet-wide `fallback_providers` picture this narrow four-row sample doesn't show) |
| `provider` | `fireworks` |
| `transactionId` | `event:<sid>:<uuid>:<hash>:api:N` shape, quoted below |
| per-call attribution | two rows, one session (`<sid-B>`), `:api:1` and `:api:2` |
| `agenticJobId` | **RESOLVED-ABSENT (root) / UNVERIFIED (subagent)** — structurally impossible for a root session; for a subagent session, absent in every row sampled here but NOT shown impossible, and the mechanism in fact favours presence once the root has completed a turn; see `## Findings` → "agenticJobId — absent for root sessions by construction, unverified for subagents" |
| multi-model attribution | **RESOLVED — mechanism-verified, no intra-session occurrence found in a bounded 26-trace search** (NOT structurally impossible); see `## Findings` → "Multi-model attribution — mechanism verified, trigger unfired within a single trace" |

Quoted row (`<sid-A>`, playtester — re-confirmed live in this plan's own
query, not merely copied from the tracer):

| Field | Value |
|---|---|
| `taskType` | `post_fix_probe` |
| `operationType` | `CHAT` |
| `traceId` | `<sid-A>` |
| `traceType` | `smoke_test` |
| `agent` | `Hermes-playtester` |
| `squadId` | `<sid-A>` |
| `model` | `accounts/fireworks/models/glm-5p2` |
| `provider` | `fireworks` |
| `transactionId` | `event:<sid-A>:<sid-A>:<hash-A>:api:1` |
| `totalTokenCount` | `13634` |
| `totalCost` | `0` — **$0 by operator decision (BACK-2676 out of scope), not a metering defect** |

**Per-call attribution — two rows, one session, quoted in full.** `<sid-B>`
(coder root session) emitted two rows sharing the same session/uuid/hash
prefix and differing only in the `:api:N` ordinal:

Row `:api:1`:

| Field | Value |
|---|---|
| `taskType` | `subagent_ping_test` |
| `operationType` | `CHAT` |
| `traceId` | `<sid-B>` |
| `traceType` | `canary_probe_check` |
| `agent` | `Hermes-coder` |
| `squadId` | `<sid-B>` |
| `model` | `accounts/fireworks/models/glm-5p2` |
| `provider` | `fireworks` |
| `transactionId` / `label` / `spanId` | `event:<sid-B>:<uuid-B>:<hash-B>:api:1` |
| `requestTime` | `2026-08-20T01:52:40Z` |
| `totalTokenCount` | `20879` |
| `totalCost` | `0` — **$0 by operator decision (BACK-2676 out of scope), not a metering defect** |

Row `:api:2`:

| Field | Value |
|---|---|
| `taskType` | `subagent_ping_test` |
| `operationType` | `CHAT` |
| `traceId` | `<sid-B>` |
| `traceType` | `canary_probe_check` |
| `agent` | `Hermes-coder` |
| `squadId` | `<sid-B>` |
| `model` | `accounts/fireworks/models/glm-5p2` |
| `provider` | `fireworks` |
| `transactionId` / `label` / `spanId` | `event:<sid-B>:<uuid-B>:<hash-B>:api:2` |
| `requestTime` | `2026-08-20T01:52:44Z` |
| `totalTokenCount` | `21212` |
| `totalCost` | `0` — **$0 by operator decision (BACK-2676 out of scope), not a metering defect** |

**The `:api:N` ordinal — not response order, not page order — is what
proves the ordering, demonstrated rather than merely asserted.** Within the
single raw response page these two rows both landed on, the `:api:2` row
appears at array index 79 and the `:api:1` row appears LATER, at index 83 —
the API returned the second call before the first. The `created` timestamps
resolve the true order (`:api:1` = `...27.944Z`, `:api:2` = `...28.045Z`,
`:api:1` earlier), but a reader trusting response position alone would get
it backwards. This is the concrete, observed case for why the `:api:N`
ordinal embedded in `transactionId`/`label`/`spanId` — never `metrics ai`
response or page order — is the load-bearing proof of per-call ordering in
this document.

**Subagent row, same trace, different session id.** A third Hermes-owned row
shares `<sid-B>`'s `traceId`/`squadId` but belongs to its own session
(`<sid-C>`, the dispatched subagent): `taskType=ping_pong_check`,
`transactionId=event:<sid-C>:<uuid-C>:<hash-C>:api:1`,
`totalTokenCount=11859`, `totalCost=0` — **$0 by operator decision (BACK-2676
out of scope), not a metering defect**. This reconfirms live, rather than
merely assuming, the subagent-rolls-up-to-the-root-`traceId`-without-
fragmenting behavior REQUIREMENTS.md's "Known open at scope time" section
already credited to pre-Phase-33 work.

**`squadName` — the two-call join (Task 2 of this plan, queried
2026-08-20T04:1xZ).** `metrics ai` rows carry `squadId` only; none of the 635
rows fetched this session carries a `squadName` key at all — that absence is
the correct schema, not missing data. `squadName` lives on the Squad
resource, reached only via `revenium squads get <squadId> --output json`.
Two independent lookups, one per traceId confirmed above:

`revenium squads get <sid-A> --output json` (playtester trace, whole
lifetime `startTime=2026-08-20T01:47:47Z`–`endTime=2026-08-20T01:47:49Z`,
both after the write-loss window's close — clean):

| Field | Value |
|---|---|
| `squadName` | `gtm-fleet` |
| `models` | `["accounts/fireworks/models/glm-5p2"]` |
| `providers` | `["fireworks"]` |
| `agents` | one entry: `agent=Hermes-playtester`, `role=root`, `transactionCount=1` |
| `transactionCount` | `1` |
| `traceCount` | `1` |

`revenium squads get <sid-B> --output json` (coder trace, whole lifetime
`startTime=2026-08-20T01:52:40Z`–`endTime=2026-08-20T01:52:47Z`, both after
the write-loss window's close — clean):

| Field | Value |
|---|---|
| `squadName` | `gtm-fleet` |
| `models` | `["accounts/fireworks/models/glm-5p2"]` |
| `providers` | `["fireworks"]` |
| `agents` | one entry: `agent=Hermes-coder`, `role=root`, `transactionCount=3` |
| `transactionCount` | `3` |
| `traceCount` | `1` |

Both traces resolve `squadName` to the SAME string, `gtm-fleet`, despite
belonging to different profiles (`playtester` vs `coder`) whose own
`--squad-name` argv (per `api-event-report.sh`'s
`--squad-name "${REVENIUM_SQUAD_NAME:-${REVENIUM_AGENT_NAME}}"`, with
`REVENIUM_SQUAD_NAME` confirmed unset in every one of the ten profiles'
`env` files) would differ — `Hermes-playtester` vs `Hermes-coder`.
`squadName` is CONFIRMED present and non-empty on the Squad resource, and the
two-call join works exactly as documented — but the value returned does not
match what either profile's own argv would send, and no local config source
accounts for `gtm-fleet` on either profile. See `## Findings` for this
mismatch, recorded there rather than resolved further, since diagnosing why
Revenium's server assigns this particular label is outside CUT-02's
read-side-confirmation scope.

`revenium squads timeline <sid-B> --output json`: three chronological
events (root `:api:1` at `startTime=01:52:40Z`, subagent `:api:1` at
`startTime=01:52:44Z`, root `:api:2` at `startTime=01:52:44Z`). The
subagent's event and the root's `:api:2` event share the same whole-second
`startTime`, and the timeline lists the subagent's event first despite the
root's `:api:2` ending later — the same ordinal-over-order lesson from a
second, independent angle (a different session's `:api:1` sorts ahead of
this session's own `:api:2` in server-returned order). The timeline's own
chronological ordering of `<sid-B>`'s two ROOT events (`:api:1` then
`:api:2`) agrees with the `:api:N` ordinals quoted above — no disagreement
to report for the ordinals actually being compared.

`revenium squads list --period TWENTY_FOUR_HOURS --output json`: **one**
squad entity in the period, `label=gtm-fleet` (matching both `squads get`
results above), `agentCount=20`, `executionCount=20`, `traceCount=20`,
`firstExecutionTime=2026-08-19T04:08:48Z`,
`lastExecutionTime=2026-08-20T01:52:47Z`. This period is annotated
**partially suspect**: `2026-08-19T04:08:48Z`–`2026-08-20T01:52:47Z` fully
contains the write-loss window `2026-08-19T18:25:00Z`–`2026-08-20T01:24:00Z`,
so the aggregate `executionCount`/`transactionCount`/`totalCost` figures
cannot be trusted as complete — any writes dropped during the outage are
invisible to this rollup, though the two point-lookup `squads get` calls
above are each individually clean (their own trace lifetimes fall entirely
outside the outage). Zero squads in the period carry a label distinguishable
per-profile (a `Hermes-<profile>`-shaped `label`) — every squad this tenant
has produced for the Hermes event path in this period shares the single
`gtm-fleet` value, consistent with (but not proof of) the two-trace mismatch
above.

## Findings

### Task 4 checkpoint outcome — unforced-convergence attestation requested, not given

**This is the audit trail for CUT-01's "unforced" qualifier, for anyone
replaying this evidence later.**

This plan's Task 4 was a blocking `checkpoint:human-verify` (`gate=
"blocking"`) asking the operator to attest, from their own knowledge of
what was done on the fleet host, that no profile was manually touched
across the observation window — or to name the profile that was, in which
case CUT-01 would be recorded as failed for it.

**Attestation requested:** confirm no `env`/`config.json` edit, no
`clear-halt.sh` run, no gateway restart, no `drain-status.json`/ledger edit
occurred on any profile, matching the ten `env` modification times this
document records as the mechanical (but partial) evidence.

**Operator's verbatim response:** *"It may have been touched but doesnt
matter if so."*

**What this response is, precisely:** neither the unforced attestation nor
a named touched profile. The operator explicitly declined to affirm the
absence of manual intervention, and explicitly declined to name a profile
— both of the plan's own two anticipated exits. Offered the choice between
(a) qualifying the claim as unattested while keeping CUT-01 at 8/10, or (b)
recording CUT-01 as failed for an unnamed profile, the operator chose (a):
**qualify it as unattested.**

**Scope of the resulting claim, stated precisely:** CUT-01 closes at 8 of
10 profiles converged as of this document's close. The "without manual
intervention" language in CUT-01's own requirement text is satisfied ONLY
for the portion of the cutover→convergence span this phase itself directly
observed and controlled (`03:36Z`–`05:13Z` on 2026-08-20, 1h37m, during
which this phase's own commands are exhaustively enumerated in the query
ledger and none was side-effecting) — NOT for the roughly 6.5 hours between
the 2026-08-19 ~21:12Z cutover flip and this phase's first observation, and
NOT as an attested fact for any span, since the one party positioned to
attest to it declined. This gap is not chased further: the observation
window is closed, and re-opening it to interrogate the host after the fact
would itself be a new action this phase's own read-only mandate does not
license.

**CUT-01 is NOT recorded as failed.** The operator explicitly rejected that
outcome. CUT-01 closes at 8/10 with this qualifier attached, per the
operator's own choice.

### Tracer read-side query — narrow window returned zero Hermes rows

The first, narrower query (`--from 2026-08-20T02:00:00Z --to
2026-08-20T03:40:00Z`) returned 100 rows total but zero Hermes-owned ones.
Of the three candidate causes named by this task's own action text —
(a) nothing metered in that exact window, (b) window overlaps the
write-loss hole, (c) query mis-scoped — this document does not need to
adjudicate between them for that *specific* narrow window, because the
required widened retry (still entirely post-outage) succeeded and produced
real Hermes rows. The evidence is nonetheless consistent with cause (a):
this Revenium dev tenant is dominated by non-Hermes traffic (agents named
`Memory`, `Detection`, `Game Master`, and others recorded in
`33-RESEARCH.md`'s live sampling), so a 100-minute slice with no fresh
Hermes-owned completion is unsurprising on a shared tenant, not a sign of a
broken query.

### CUT-01 — named cause per non-converged profile

**The staleness boundary, stated once with its citation:** `drain-status.sh:509`
computes `terminal = stale_enabled and not refused and (now - last_seen) >=
stale_seconds_effective` — an inclusive `>=` comparison, so a pending
session whose age exactly equals `staleSecondsEffective` is INSIDE the
stale route (already terminal, not one tick away from it). The same
inclusive rule governs the settle-window terminal test at
`drain-status.sh:485` (`terminal = (now - float(ended_at)) >= settle_seconds`)
for sessions that HAVE ended. `staleSecondsEffective` itself is
`max(staleSecondsConfigured, settleSeconds + 86400)`
(`drain-status.sh:160`): the fleet's configured value is `86400` and its
`REVENIUM_CRON_SETTLE_SECONDS` is the default `600`, so the floor computes
to `max(86400, 600 + 86400) = 87000` — exactly the `87000.0` observed on
every profile's `drain-status.json` across all three rounds. **The
configured `86400` (24h) is not the operative number; the observed
`87000` (24.17h) is**, because the settle-window addend floors it upward.

**A refinement to this task's own anticipated bucket taxonomy, found while
diagnosing, not assumed going in.** `drain-status.sh`'s three textual
buckets for "not yet drained" (its own header comment,
`drain-status.sh:24-26`) are: still open, still within the (600s) settle
window, or terminal-but-not-yet-quiet. Reading the actual terminal-decision
code (`drain-status.sh:475-517`) shows these are not independent
possibilities for the SAME session — they are mutually exclusive branches
selected by whether `state.db`'s `ended_at` is set: a session with
`ended_at` NOT NULL (closed) is governed exclusively by the FAST 600-second
settle window; a session with `ended_at` NULL (still open, in Hermes' own
bookkeeping) is governed exclusively by the slow ~24.17h staleness route.
There is no "closed session waiting on the 24h floor" state in this code —
closed sessions converge in ten minutes. **Every one of the eleven pending
sessions found below is OPEN per `state.db` (`ended_at` NULL), so every one
of them is on the slow staleness route, not the fast settle route** — this
is the honest, source-grounded finding, not a forced fit into the plan's
original three-way guess.

**Cross-reference method:** each pending sid's `ended_at`/`end_reason`/
`started_at` was read from that profile's own `state.db` via a read-only
URI connection (`file:<path>?mode=ro`), once after Round 1 and again after
Round 3 — identical both times, confirming no session closed during this
observation window.

#### gtm — 5 pending, all open, staleness route (earliest full convergence ≈ 2026-08-20T16:59:11Z)

| sid (placeholder) | ageSeconds (R3, `lastChecked=03:57:33Z`) | quietTicks | terminal | stale | `ended_at` | Gap to `staleSecondsEffective` | Earliest-possible convergence |
|---|---|---|---|---|---|---|---|
| `<gtm-sid-1>` | 85109.2 | 1417 | false | false | NULL (open) | 1890.8s (~31.5min) | 2026-08-20T04:29:03Z |
| `<gtm-sid-2>` | 84810.4 | 1412 | false | false | NULL (open) | 2189.6s (~36.5min) | 2026-08-20T04:34:02Z |
| `<gtm-sid-3>` | 84809.5 | 1412 | false | false | NULL (open) | 2190.5s (~36.5min) | 2026-08-20T04:34:03Z |
| `<gtm-sid-4>` | 71660.1 | 1194 | false | false | NULL (open) | 15339.9s (~4.26h) | 2026-08-20T08:13:12Z |
| `<gtm-sid-5>` | 40101.6 | 668 | false | false | NULL (open) | 46898.4s (~13.03h) | **2026-08-20T16:59:11Z** |

Every one of gtm's five pending sids is a session Hermes' own `state.db`
still considers open (`ended_at` NULL, real `started_at` values on
record). Quiet-tick counts (668–1417) are already far past the
`REVENIUM_DRAIN_QUIET_TICKS=15` requirement — meaning once the staleness
threshold is crossed for a sid, that sid converges within the SAME tick, no
further waiting on quietness. The profile's OWN earliest-possible full
convergence is bounded by its SLOWEST pending sid (`<gtm-sid-5>`, gap
~13.03h at the time of the Round 3 sample) — **assuming none of the five
sessions genuinely ends first**, which would instead route that sid through
the fast 600-second settle window and could converge it far sooner.

#### community — 1 pending, open, staleness route (earliest full convergence ≈ 2026-08-20T21:33:13Z)

| sid (placeholder) | ageSeconds (R3, `lastChecked=03:57:36Z`) | quietTicks | terminal | stale | `ended_at` | Gap to `staleSecondsEffective` | Earliest-possible convergence |
|---|---|---|---|---|---|---|---|
| `<community-sid-1>` | 23662.4 | 374 | false | false | NULL (open) | 63337.6s (~17.59h) | **2026-08-20T21:33:13Z** |

community's single pending session is the youngest (by ledger last-seen
age) of all eleven pending sids across the fleet, and consequently has the
longest remaining wait via the staleness route of any single-pending
profile. Same caveat as gtm: this bound assumes the session does not end
first via natural termination.

#### lorekeeper — 5 pending, all open, staleness route (earliest full convergence ≈ 2026-08-20T05:01:59Z)

| sid (placeholder) | ageSeconds (R3, `lastChecked=03:57:42Z`) | quietTicks | terminal | stale | `ended_at` | Gap to `staleSecondsEffective` | Earliest-possible convergence |
|---|---|---|---|---|---|---|---|
| `<lorekeeper-sid-1>` | 83622.7 | 1254 | false | false | NULL (open) | 3377.3s (~56.3min) | 2026-08-20T04:53:59Z |
| `<lorekeeper-sid-2>` | 83622.1 | 1254 | false | false | NULL (open) | 3377.9s (~56.3min) | 2026-08-20T04:53:59Z |
| `<lorekeeper-sid-3>` | 83556.6 | 1252 | false | false | NULL (open) | 3443.4s (~57.4min) | 2026-08-20T04:55:05Z |
| `<lorekeeper-sid-4>` | 83229.8 | 1247 | false | false | NULL (open) | 3770.2s (~62.8min) | 2026-08-20T05:00:32Z |
| `<lorekeeper-sid-5>` | 83142.8 | 1246 | false | false | NULL (open) | 3857.2s (~64.3min) | **2026-08-20T05:01:59Z** |

lorekeeper is the closest of the three pending profiles to full
convergence — its slowest pending sid is roughly one hour out from the
Round 3 sample, versus gtm's ~13 hours and community's ~17.6 hours.

**Update (Task 3 of plan 33-03): lorekeeper fully converged** at the
observation window's close, right on this section's own predicted bound —
see `## Independent confirmation` → "CUT-01 — final re-sample, closing the
observation window" for the final reading. **gtm partially converged**
(its 3 fastest sids above, `<gtm-sid-1..3>`, closed; `<gtm-sid-4>` and
`<gtm-sid-5>` remain, unchanged cause). **community did not converge**
within this window — same sid, same cause, throughout. This subsection's
own per-sid tables are left as 33-01 wrote them (a Round-3 snapshot), not
edited to match the later reading.

**No undetermined causes.** All eleven pending sessions across the three
profiles fit cleanly into the single applicable bucket (open per
`state.db`, on the staleness route, not yet past the floor) — none needed
the fourth "data does not distinguish" fallback this task's own guidance
allows for.

### squadName resolves to a tenant-wide label, not either sampled profile's own `--squad-name` value

Both `<sid-A>` (playtester) and `<sid-B>` (coder) resolve to
`squadName: "gtm-fleet"` via `revenium squads get`, and `revenium squads
list --period TWENTY_FOUR_HOURS` shows exactly one squad label active in the
tenant during that period — also `gtm-fleet`. Per
`skills/revenium/scripts/api-event-report.sh`'s own argv construction
(`--squad-name "${REVENIUM_SQUAD_NAME:-${REVENIUM_AGENT_NAME}}"`) and the
confirmed-unset `REVENIUM_SQUAD_NAME` in all ten profiles' `env` files, the
value each profile's event path actually sends should be
`Hermes-<profile>` (`Hermes-playtester`, `Hermes-coder`) — not `gtm-fleet`.
No local source accounts for `gtm-fleet`: it is absent from every profile's
`env`, `state/revenium/config.json` (`organizationName` reads `None` on
every profile checked), and `config.yaml`. `revenium config show` reports a
Team ID and a Tenant ID, neither of which is `gtm-fleet` either.

This is recorded as an open finding, not resolved further: it is consistent
with (though not proof of) a server-side default squad label the Revenium
API assigns per-team independent of the client's `--squad-name` argument —
a behavior this read-only observation phase has no means to test further
without either a server-side config change (out of scope) or sending a
deliberately different `--squad-name` value to see whether it is echoed (a
mutating write G-2 forbids). The dimension itself is CONFIRMED present,
non-empty, and resolvable via the two-call join documented in `## Results`;
whether the exact string it resolves to matches what was sent is a separate
question CUT-02's own wording ("confirmed on the read side") does not
require answering.

### agenticJobId — absent for root sessions by construction, unverified for subagents

**`agenticJobId` did not appear on any metered row this phase examined. The
two halves of that result are not equally strong and must not be quoted as
one: for a ROOT session, absence is a structural impossibility and settled;
for a SUBAGENT session, absence is an empirical observation over a small
sample, and the mechanism actually favours presence. Stated here at the
weaker of the two strengths, with the subagent half labelled UNVERIFIED.**

**Method 1 — live read-side result.** Two jobs, each with a `created` line
followed by an `outcome` line in their profile's `revenium-jobs.ledger` (one
from `marketing`, `SUCCESS`; one from `coder`, `<job-B>`, `CANCELLED` —
the same induced probe
STATE.md's Probe 2 recorded, re-queried live for this plan rather than
copy-forwarded). `revenium jobs get <id> --output json` confirms both job
resources exist server-side with a real `executionStatus` and `created`
timestamp. `revenium jobs transactions <id> --output json` returns
`{"totalCount": 0, "transactions": []}` for both — zero AI-metric
transactions are linked to either job anywhere in Revenium. Both `created`
timestamps (`2026-08-20T04:46:32.956Z` and `2026-08-20T01:54:39.627Z`) fall
entirely outside the write-loss interval
(`2026-08-19T18:25:00Z`–`2026-08-20T01:24:00Z`, per the convention stated in
`## Known limitations and exclusions` — the second job's creation is 30m39s
after the interval's close) — neither zero is ambiguous between a by-design
absence and Revenium's silent write loss; both are clean.

`revenium jobs transactions <id>` — not `revenium metrics ai` — is the only
verb capable of answering this question. `metrics ai` rows carry no
job-related key anywhere in their 63-key schema (verified this phase, live
JSON dump); `--agentic-job-id` sent at meter time would be invisible on that
endpoint even if present. An absence in a row dump is not evidence in either
direction, and this is the only place in this document that needs to say so.

**Method 2 — source-level mechanism, independently agreeing.** For a root
session, the marker never carries the field. `classifier.py:999` computes
`root_aid = _root_agentic_job_id_for(root_sid, paths=p) if root_sid != sid
else ""` — for a root session `root_sid == sid`, so `root_aid` is
unconditionally `""`, and the conditional assignment at `classifier.py:1010`
(`if root_aid: rec["agentic_job_id"] = root_aid`) never fires.
`_write_marker_pair`'s own docstring (`classifier.py:975`) states this
outcome as a deliberate design choice: "Top-level sessions emit trace_id ==
sid ... and OMIT agentic_job_id." **This is permanent and applies to every
root session, not a timing artifact — no probe sequencing changes it.**

**For a subagent session there is no mechanism argument at all, and an
earlier draft of this document was wrong to offer one.** The field is present
on a subagent's marker whenever the root's own `kind:"job"` marker already
exists at the moment the subagent is classified. A draft reviewed on
2026-08-20 asserted that job inference "runs as the last step of the root's
own classification — typically at the root's end/finalize boundary, which is
after a mid-session subagent has already finished and been classified," and
called that ordering the normal case. **That is backwards.** Job inference is
Step 7 of `run_classification_async` (`classifier.py:1104-1112`) and its own
comment states it "runs unconditionally on every reachable path" — and since
Phase 29 (HOOK-02) one of those paths is `post_llm_call`, which fires once per
COMPLETED turn. The plugin's own module docstring
(`plugins/revenium-classifier/__init__.py`) states the intent plainly: the
hook exists for "making an ordinary session produce a classified job on its
first turn", and "classifying on the first completed turn is what makes an
ordinary prompt produce a job without waiting for a session boundary." So for
any root that completes one turn before dispatching a subagent — the ordinary
shape of agentic work — the root's job marker exists FIRST, and that
subagent's marker inherits `agentic_job_id` via `classifier.py:999-1010`.
Presence is the expected case there, not the exception.

**What that leaves the subagent half resting on: observation, and nothing
else.** Every Hermes-owned row examined in this phase lacked the field, and
both `revenium jobs transactions` calls returned `totalCount: 0`. That is a
real, reproducible read-side result and it is all this document claims. It is
NOT a demonstration that a subagent row cannot carry the field. The most
likely explanation for the observation is the mundane one — the sampled
window contained no subagent session dispatched after its root's first turn —
and this phase's read-only constraint forbids inducing one to find out.
Anyone extending this finding should treat "subagent rows carry no
`agenticJobId`" as UNVERIFIED and design a probe for it: dispatch a subagent
from a root that has already completed a turn, then read that subagent's row.

**What does NOT close the subagent case either, stated so nobody mistakes it
for a closer.** The event path's marker join does exclude `kind:"job"` records
outright: `api-event-report.sh:1006-1022` skips any record where
`m.get("kind") is not None`, then requires `all(k in m for k in REQUIRED)`
where `REQUIRED = ("muid", "ts", "sid", "task_type", "operation_type")`, so a
job marker is never in the join set. True, and irrelevant to this question —
the carrier is not the job marker. It is the subagent's own ordinary
`CHAT`/`GUARDRAIL` marker, which passes that filter, and `_attribution_for`
reads `agentic_job_id` straight off it (`api-event-report.sh:1056`) and
returns it; the reporter then ships `--agentic-job-id` whenever that value is
non-empty and the CLI is capable (`api-event-report.sh:1268-1269`).

**The legacy-versus-event asymmetry, recorded, not fixed.** The legacy path
resolves this differently and CAN attach a root session's own job id:
`hermes-report.sh:2470-2474`'s per-marker `cmd` construction —
`if [[ "${root_sid}" == "${sid}" && -n "${m_owning_job_id}" ]]; then
cmd+=(--agentic-job-id "${m_owning_job_id}") ...` — ships the root's own
`m_owning_job_id`, something the event path structurally cannot do for a
root session (its `root_aid` is unconditionally empty by `classifier.py:999`
above). **The event path has strictly less capability here than the legacy
path for root sessions.** Whether this asymmetry should be closed — by
having the event path resolve a root session's own job id independently of
the marker join, or some other design — is a decision for a later phase, not
this one. This document's job is to make the fact legible, not to propose or
implement a fix.

### Multi-model attribution — mechanism verified, trigger unfired within a single trace

**Resolved: the mechanism to produce two distinct models under one `traceId`
is verified fleet-wide and demonstrably live for two profiles, but a bounded
26-trace search found no trace where it fired within a single trace — this
is mechanism-verified/trigger-unfired, and it is explicitly NOT the same
claim as "structurally cannot be recorded," which the fleet-wide mechanism
evidence below refutes.**

**The mechanism.** All ten profiles' `config.yaml` declare a
`fallback_providers` block (grepped live on the fleet host, 2026-08-20):
every profile names a `provider`/`model` primary plus one or more fallback
`provider`/`model` pairs (`zai/glm-4.6`, `fireworks/...glm-5p2`, one or more
`openrouter/...` entries, varying per profile). If the primary provider
fails mid-session, Hermes serves subsequent calls in the SAME session from a
fallback. `post_api_request` fires per API call carrying the actually-serving
model and forwards it per-call on the event path (`api-event-report.sh`'s
per-marker construction), so a session that experiences a fallback would
legitimately show two distinct `model` values under one `traceId` — this is
a real, falsifiable path, not a hypothetical one. `post_api_request` does
NOT fire for auxiliary calls (compression, title-gen, `approval`), so
auxiliary traffic is excluded as a possible multi-model source on this path.

**The bounded search.** `revenium squads list` returns one row per squad
LABEL (aggregated across every trace sharing that label), not one row per
trace, so it cannot answer a per-trace question directly. `revenium squads
executions` (the flat, no-groupId form) DOES enumerate individual traces.
Two calls: `--period TWENTY_FOUR_HOURS` (8 traces, all Hermes-shaped) and
`--period SEVEN_DAYS` (20 traces returned; the CLI declines `--page` for
this verb — confirmed via `--help` and a live `unknown flag: --page` error —
so only the first of an internally-reported "4 pages" is retrievable; this
is a genuine CLI limitation, not an omitted retry). After removing 2
overlaps, **26 unique traces were examined with `revenium squads get <id>
--output json`**, reading the top-level `models` array on each: **25
succeeded, all with a single-element `models` array — zero of 26 traces
show `len(models) >= 2`.** One trace errored with a reproducible HTTP 500 on
two consecutive attempts; its own listing showed a `duration` of ~5 days
versus every other trace's 20-300 seconds, a genuine outlier plausibly
responsible for a server-side rollup failure — recorded as the finding,
not retried a third time or chased further (T-33-05 budget discipline). The
7-day period's start (`2026-08-14T08:02Z` earliest observed) is well before
the write-loss interval; none of the 26 examined traces' lifetimes overlap
`2026-08-19T18:25:00Z`–`2026-08-20T01:24:00Z` (all either end before it or
start after it, per each trace's own `startTime`/`endTime`).

**The pattern that came closest, and why it still isn't the proof.**
`marketing` and `cfo` are both configured with `zai/glm-4.6` as PRIMARY, yet
every one of their sampled traces (11 for marketing, 6 for cfo, across both
periods examined) used `fireworks/...glm-5p2` — their own first-listed
FALLBACK, never their configured primary. This is real, corroborating
evidence that the fallback trigger is currently live for these two profiles,
not merely configured-and-dormant — it directly refutes a "the trigger has
simply never fired" reading. But every one of those traces still shows only
ONE model; none straddles the primary and a fallback (or two fallbacks)
within the same trace's own transactions. The mechanism has fired at the
session-to-session boundary; it has not yet been caught firing mid-session
in any of the 26 traces this search examined.

**No provider was failed, no session was induced, and no config was changed
to produce or search for this evidence** — every command in this search was
`revenium squads executions`/`squads get`/`squads list` (read verbs) plus a
`grep`/`cat` of each profile's own `config.yaml` on the fleet host.

## Reproducing this measurement

Convergence check, per profile (machine-readable; run on the fleet host,
against `<profile-state-dir>/drain-status.json`):

```bash
python3 -c "import json;d=json.load(open('drain-status.json'));print(d['drained'], d['determined'], d['pendingCount'], d['lastChecked'])"
```

Convergence check, log-line corroboration (run on the fleet host, against
`<profile-state-dir>/revenium-metering.log`):

```bash
tail -n 200 revenium-metering.log | grep -E 'legacy completions path disabled|refusing to disable' | tail -5
```

Read-side row query, time-boxed and paged (avoids the small-page-size
auto-pagination pitfall — a page size under ~100 with no explicit `--page`
makes the CLI issue one HTTP round-trip per row and print nothing until
every page has landed, which looks exactly like a hang):

```bash
revenium metrics ai --from <ISO> --to <ISO> --output json --page-size 200 --page <N>
```

Filter the returned array client-side — there is no server-side filter on
this verb — down to rows whose `agent` starts with `Hermes` or whose
`label` starts with `event:`.

Trace-level rollup and the two-call join (`squadName`, `traceType`, and the
per-trace `models` set). `<sid>` is the raw root session id — resolve it from
the placeholder map in the gitignored evidence artifact:

```bash
revenium squads get <sid> --output json       # squad detail: squadName, traceType, models
revenium squads timeline <sid> --output json  # per-call events within the one trace
```

Job resource and its linked AI-metric transactions (the `agenticJobId`
probe — a job that exists server-side while `totalCount` stays `0` is the
result this document reports):

```bash
revenium jobs get <job-id> --output json
revenium jobs transactions <job-id> --output json
```

Bounded multi-model search. Enumerate trace ids over a period, then read each
trace's own `models` set and count the traces with two or more distinct
models. `--page` is declined by this verb, so the period is the only knob and
the reachable set is capped — state the cap with the result:

```bash
revenium squads executions --period TWENTY_FOUR_HOURS --output json
revenium squads executions --period SEVEN_DAYS --output json
# then, per enumerated id:
revenium squads get <id> --output json   # inspect len(models) >= 2
```

Every call above is a read verb. Reproducing this measurement requires no
write of any kind — no `revenium meter`, no `jobs create`/`outcome`, no
`guardrails` mutation, and no write to any profile's `env`, `config.json`,
`drain-status.json`, or ledger. The convergence result in particular is only
valid if nothing was touched; see `## Known limitations and exclusions` for
what this phase could and could not establish on that point.

### Query ledger (33-01 + 33-02 + 33-03)

Every `revenium` CLI read-verb call issued by either plan in this phase, in
the order issued, so the method — including what returned nothing and what
was never re-issued — is auditable rather than only the queries that
produced a usable result:

| # | Plan/Task | Command | Window / period | Rows returned | Outcome | Window vs. write-loss interval |
|---|---|---|---|---|---|---|
| 1 | 33-01 Task 1 | `revenium metrics ai --from 2026-08-20T02:00:00Z --to 2026-08-20T03:40:00Z --output json --page-size 200 --page 0` | `02:00:00Z`–`03:40:00Z` | 100 total, **0 Hermes-owned** | success, empty Hermes-filtered set | outside (entirely after `01:24:00Z`) |
| 2 | 33-01 Task 1 | `revenium metrics ai --from 2026-08-20T01:24:01Z --to 2026-08-20T03:41:00Z --output json --page-size 200 --page N` (N=0..3) | `01:24:01Z`–`03:41:00Z` | 400 total, 4 Hermes-owned | success | outside (starts 1s after `01:24:00Z`) |
| 3 | 33-02 Task 1 precondition + Task 2 | `revenium squads list --period TWENTY_FOUR_HOURS --output json` (one call, reused for both purposes — not re-issued) | `TWENTY_FOUR_HOURS` period (≈`2026-08-19T04:08Z`–`2026-08-20T04:08Z`) | 1 squad entity | success, HTTP 200 | **overlapping** — period fully contains `18:25:00Z`–`01:24:00Z`; used to confirm API reachability for the precondition gate and for the period-level squad check, never cited as row-level dimension evidence |
| 4 | 33-02 Task 1 | `revenium metrics ai --from 2026-08-20T01:24:01Z --to 2026-08-20T04:12:00Z --output json --page-size 200 --page N` (N=0..6) | `01:24:01Z`–`04:12:00Z` | 635 total, 4 Hermes-owned | success | outside (starts 1s after `01:24:00Z`) |
| 5 | 33-02 Task 2 | `revenium squads get <sid-A> --output json` | trace lifetime `01:47:47Z`–`01:47:49Z` | 1 squad detail | success | outside |
| 6 | 33-02 Task 2 | `revenium squads get <sid-B> --output json` | trace lifetime `01:52:40Z`–`01:52:47Z` | 1 squad detail | success | outside |
| 7 | 33-02 Task 2 | `revenium squads timeline <sid-B> --output json` | trace lifetime `01:52:40Z`–`01:52:47Z` | 3 events | success | outside |
| 8 | 33-03 Task 1 | `revenium jobs get <job-A> --output json` | point lookup, `created=2026-08-20T04:46:32.956Z` | 1 job resource | success | outside (well after `01:24:00Z`) |
| 9 | 33-03 Task 1 | `revenium jobs transactions <job-A> --output json` | point lookup, same job | `{"totalCount": 0}` | success | outside — clean, not ambiguous |
| 10 | 33-03 Task 1 | `revenium jobs get <job-B> --output json` | point lookup, `created=2026-08-20T01:54:39.627Z` | 1 job resource | success | outside (30m39s after `01:24:00Z`) |
| 11 | 33-03 Task 1 | `revenium jobs transactions <job-B> --output json` | point lookup, same job | `{"totalCount": 0}` | success | outside — clean, not ambiguous |
| 12 | 33-03 Task 2 | `revenium squads executions --period TWENTY_FOUR_HOURS --output json` | `TWENTY_FOUR_HOURS` period | 8 executions | success | overlapping (period contains the write-loss window) — used only to enumerate trace ids, never cited as row-level evidence |
| 13 | 33-03 Task 2 | `revenium squads executions --period SEVEN_DAYS --output json` | `SEVEN_DAYS` period, page 1 of an unreachable 4 (CLI declines `--page` for this verb) | 20 executions | success | overlapping — same caveat as row 12 |
| 14 | 33-03 Task 2 | `revenium squads get <id> --output json` × 26 (24h ∪ 7d sets, 2 overlaps removed) | 26 individual trace lifetimes, earliest `2026-08-14T08:02:06Z` | 25 × 1 squad detail | 25 success, 1 HTTP 500 (reproducible, retried once) | each trace's own lifetime checked individually; none overlaps the write-loss window |
| 15 | 33-03 Task 2 | `grep`/`cat` of all ten profiles' `config.yaml` `fallback_providers` block | n/a (local file read, not an API call) | 10 configs | success | n/a — not an HTTP request |

48 total HTTP requests across rows 1-14 (14 distinct CLI invocations; row 2
pages 0–3 = 4 requests, row 4 pages 0–6 = 7 requests, row 14 = 26 requests —
one of which 500'd — rows 8-13 and the rest are single point lookups/calls).
Row 15 is a local file read (`grep`/`cat` on the fleet host), not an HTTP
request, and is excluded from this count. Auditable total request volume,
per T-33-05's mitigation. Row 14 is, by a wide margin, the highest-volume
single operation in this phase, which is exactly why its cap (26 traces) is
stated explicitly here rather than left implicit.

**Zero-row rule, stated once:** a zero-row result (row 1 above) is never
treated as confirmation of anything. It is equally compatible with a
perfectly healthy metering path (nothing Hermes-owned happened to land in
that particular 100-minute slice, on a tenant dominated by non-Hermes
traffic) and with a fully broken one — only corroborating evidence
distinguishes the two. Here, that evidence is row 2: the very next query,
over a window that fully contains row 1's window plus more, returned real
Hermes rows — supporting cause (a) "nothing Hermes-owned was metered in that
specific slice" over causes (b) write-loss overlap (row 1's window is
entirely outside the outage) or (c) mis-scoping (the query and filter are
identical in shape to row 2's, which worked). Full three-cause analysis is
in `## Findings` → "Tracer read-side query — narrow window returned zero
Hermes rows".

**Errors, stated once:** across 33-01 and 33-02's 16 HTTP requests, zero API
errors, timeouts, or non-200 responses were encountered — every call
returned success on its first attempt, none was retried, and no
small-`--page-size` auto-pagination symptom (Pitfall 1) was triggered, since
every `metrics ai` call in both plans passed an explicit `--page` alongside
`--page-size 200`. **One genuine error was hit in 33-03** (ledger row 14):
one of the 26 `squads get` calls in the multi-model search returned a
reproducible HTTP 500 (`"Revenium API error. Try again later or contact
support."`) on two consecutive attempts, against a trace whose own
`duration` (~5 days) was a stark outlier versus every other examined
trace's 20-300 seconds. It was not retried a third time or treated as
resolved — it is recorded here as a genuine, currently-open server-side
anomaly for that one trace, distinct from every other successful call in
this document, and it played no role in the multi-model verdict (the error
prevented reading `models` on that one trace; it did not reveal one).

## Independent confirmation

**CUT-01: performed (Task 2 of this plan).** All ten profiles were sampled
three times, at real wall-clock intervals of 5m59s and 9m46s (both exceed
the five-minute floor and both exceed one cron tick), on 2026-08-20 between
03:42:06Z and 03:57:51Z. Every profile's `drained`/`pendingCount` reading
was identical across all three rounds — zero disagreement, and therefore
nothing to mark as a later-authoritative override in this observation
window (see `## Results` → CUT-01 table for the full per-round data).
CUT-01's own gate is known to flap over a wider window (per
`33-RESEARCH.md`'s live observation of `coder` flipping drained→un-drained→
drained on 2026-08-19/20) — this task's three-round discipline exists
specifically to catch that, and in this window it confirmed stability
rather than instability. A single reading (including this document's own
Task 1 tracer sample on `playtester`) is never, on its own, treated as
sufficient confirmation; the repeated sampling above is what makes the
CUT-01 verdict independently confirmed rather than a lucky snapshot.

**CUT-02: performed (Tasks 1–2 of plan 33-02, extended by Tasks 1–2 of plan
33-03).** The row-level dimension query was independently re-run in plan
33-02 roughly 2.5 hours after the 33-01 tracer's own query, using a wider
window (`2026-08-20T01:24:01Z`–`04:12:00Z` vs. the tracer's `...–03:41:00Z`)
and found the identical four Hermes-owned rows with identical field values —
nothing new landed in the additional window, and nothing earlier
disappeared, which is exactly the stability a second independent query is
meant to confirm rather than a lucky first read. The `squadName` mismatch
finding (`gtm-fleet` returned for two different profiles' traces, neither of
which sent that string per their own argv) is itself corroborated by two
independent `squads get` calls against two different `squadId`s (`<sid-A>`,
`<sid-B>`), not one lookup taken on faith. `agenticJobId`'s ABSENCE was
independently observed via two unrelated jobs (`marketing`, `coder`), not one
— both return `{"totalCount": 0}` from `revenium jobs transactions`. Note
what two agreeing observations do and do not buy: they corroborate that the
field was absent from what was sampled; they do not turn the subagent half
into a mechanism result, and neither job's session is known to be a subagent
dispatched after its root's first turn — the one shape that would actually
test it. Multi-model
attribution's own independent-confirmation device IS its search bound: 26
separate `squads get` calls against 26 different traces spanning two
non-overlapping enumeration periods (`TWENTY_FOUR_HOURS`, `SEVEN_DAYS`) is
itself the repeated-measurement discipline this section otherwise asks a
second query to provide — a single trace's `models` array was never treated
as sufficient on its own.

### CUT-01 — final re-sample, closing the observation window (Task 3 of this plan)

All ten profiles' `drain-status.json` were re-sampled once more, well beyond
the required 30-minute gap: 33-01's Round 3 was `2026-08-20T03:57:51Z`; this
sample was taken at `2026-08-20T05:12-05:13Z`, **1h15m later**.

| Profile | 33-01 Round 3 (`03:57:51Z`) | This re-sample (`~05:12-05:13Z`) | Changed? |
|---|---|---|---|
| gtm | `false` / 5 | `false` / **2** | **Yes — 3 sessions converged** (the three fastest of the original five: gaps ~31-36min at Round 3) |
| marketing | `true` / 0 | `true` / 0 | No |
| devops | `true` / 0 | `true` / 0 | No |
| qa | `true` / 0 | `true` / 0 | No |
| coder | `true` / 0 | `true` / 0 | No |
| playtester | `true` / 0 | `true` / 0 | No |
| cfo | `true` / 0 | `true` / 0 | No |
| pm | `true` / 0 | `true` / 0 | No |
| community | `false` / 1 | `false` / 1 | No — same `sid` (`<community-sid-1>`), `ended_at` still NULL in `state.db` |
| lorekeeper | `false` / 5 | **`true` / 0** | **Yes — fully converged**, right on the Round-3-computed earliest bound (`≈2026-08-20T05:01:59Z`; observed `05:12:21Z`, 10m22s after the lower bound, as expected for a bound that assumes the very next tick after the threshold crosses) |

**No reading was averaged or replaced with a more favourable one — the later
reading is authoritative for the verdict, and the earlier reading stays on
the page above, unchanged.** Two profiles moved: **lorekeeper fully
converged** (its `first-observed-drained` timestamp is now bounded to
somewhere in `(2026-08-20T03:57:51Z, 2026-08-20T05:12:21Z]`, the interval
between the last two samples — no tighter bound is claimable without a
sample in between), and **gtm partially converged** (5 pending → 2 pending,
its two SLOWEST original sessions per the Round-3 gap computation — `<gtm-sid-4>`
and `<gtm-sid-5>`, confirming the original per-sid ordering was correct).
`community` shows zero change: same single pending `sid`, `ended_at` still
`NULL` in `state.db` (re-queried at this sample), consistent with its own
Round-3 earliest-possible bound (`≈2026-08-20T21:33:13Z`) being far outside
this observation window.

**gtm and community re-diagnosis, re-run against current `pending[]`:** both
remaining gtm sids and the sole community sid are confirmed still `ended_at
IS NULL` in their respective `state.db`s (re-queried at this sample,
identical query shape to 33-01 Task 3's) — the cause has NOT changed for
either: both are still open sessions on the staleness route, not sessions
that closed and are now waiting on a different floor. Recomputing each
sid's gap to `staleSecondsEffective` from this sample's own `ageSeconds`
and `lastChecked` reproduces the SAME earliest-possible-convergence
timestamps 33-01 computed from Round 3, within one second
(`<gtm-sid-4>`: `2026-08-20T08:13:12Z` → recomputed `08:13:13Z`;
`<gtm-sid-5>`: `2026-08-20T16:59:11Z` → recomputed `16:59:12Z`;
`<community-sid-1>`: `2026-08-20T21:33:13Z` → recomputed `21:33:13Z`,
exact) — the bound was correct and stable across 1h15m of real elapsed
time, not a one-off estimate. gtm's own earliest-possible FULL convergence
remains bounded by `<gtm-sid-5>` (`≈2026-08-20T16:59:12Z`, unchanged), since
`<gtm-sid-4>` converges first but gtm needs both closed.

**CUT-01 count at close of window: 8 of 10 converged** (the original 7 —
marketing, devops, qa, coder, playtester, cfo, pm — plus lorekeeper,
converged since Round 3). gtm and community remain pending with the same,
unchanged, source-grounded cause as 33-01 diagnosed. This phase's own
commands never touched any profile — but whether any profile was touched
by anything outside this phase's own commands is NOT established; the
operator declined to attest to that at Task 4's checkpoint. See
`## Verdict` and `## Findings` → "Task 4 checkpoint outcome" for the full
statement — CUT-01 closes at 8/10 WITH that qualifier, not as a clean
unforced pass.

## Verified against

Date: 2026-08-20. Method: read-only SSH access to the fleet host (all ten
profiles' `drain-status.json`, `revenium-metering.log`, `state.db` via a
read-only URI connection, and `config.yaml`) plus the `revenium` CLI's read
verbs (`metrics ai`, `jobs get`/`transactions`, `squads
get`/`list`/`timeline`/`executions`, `config show`) against the live
Revenium dev tenant, across three plans (33-01, 33-02, 33-03) and a
1h37m observation window from the first tracer sample (`2026-08-20T03:36Z`)
to the final re-sample (`2026-08-20T05:13Z`). Population: the ten fleet
profiles cut over on 2026-08-19 (`gtm, marketing, devops, qa, coder,
playtester, cfo, pm, community, lorekeeper`).

**Deliberately omitted from this file, on every page, in every task:** the
fleet host's address, the SSH key filename, every remote login string, and
every raw session, trace, and job identifier. These live only in this
repository's local, gitignored evidence artifact
(`.planning/phases/33-convergence-and-read-side-proof/33-EVIDENCE.md`),
resolved via the stable placeholders used above (`<sid-A>`, `<hash-A>`,
`<sid-B>`, `<uuid-B>`, `<hash-B>`, `<sid-C>`, `<uuid-C>`, `<hash-C>`,
`<job-A>`, `<job-B>`, `<profile-state-dir>`). The 26 squad-execution ids
examined in the multi-model search (Task 2 of this plan) are not even
placeholder-mapped, since none of them is quoted — that finding is reported
only in aggregate (`25/26`, `0` with `len(models) >= 2`) directly in
`## Findings`.

**Retained, deliberately:** profile role labels (`playtester`, `coder`,
`marketing`, `cfo`, etc.) and every aggregate figure (counts, timestamps,
gap computations, `totalCount` values) — the per-profile and per-clause
reading throughout this document depends on them. `gtm-fleet` (a squad
label value, not a session/trace/host identifier) is quoted directly rather
than placeholder-redacted — it falls outside every category this document's
redaction gate covers (IPv4 addresses, SSH key filenames, remote login
strings, the session-id shape).
