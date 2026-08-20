# Fleet Cutover Convergence and Read-Side Proof — Observed Unforced, Diagnosed Where Pending

## Verdict

**CUT-01: 7 of 10 fleet profiles converged unforced as of 2026-08-20T03:57:51Z
(marketing, devops, qa, coder, playtester, cfo, pm). The remaining 3 (gtm,
community, lorekeeper) have not converged, and each carries a named,
source-grounded cause — never a forced open.**

No profile was written to, restarted, or otherwise touched to produce this
result. All ten `env` files carry an identical modification time inside the
documented 2026-08-19T21:12–21:40Z cutover flip window, and none is later.
Every converged profile's verdict is corroborated by both its
`drain-status.json` `drained: true` reading AND a matching
`hermes-report.sh:187` log line — neither alone was treated as sufficient.
Every reading was confirmed stable across three samples spaced 5m59s and
9m46s apart (both exceeding the required five-minute floor), with zero
disagreement in this observation window.

The three pending profiles are not stalled without explanation: all eleven
of their pending sessions are OPEN per Hermes' own `state.db`
(`ended_at` NULL) and sit on `drain-status.sh`'s staleness route, bounded
by the observed `staleSecondsEffective = 87000.0` seconds (~24.17h,
computed as `max(86400, 600 + 86400)`, not the nominally-configured 24h).
Their earliest-possible full convergence times, computed from the slowest
pending session in each profile: **lorekeeper ≈ 2026-08-20T05:01:59Z**
(~1 hour out at the time of the Round 3 sample), **gtm ≈
2026-08-20T16:59:11Z** (~13 hours out), **community ≈ 2026-08-20T21:33:13Z**
(~17.6 hours out) — each of these bounds assumes no earlier natural session
end, which would instead route that session through the much faster
600-second settle window. If CUT-01 is re-checked after any of these
times, expect that profile (or, if all its pending sessions closed first,
possibly sooner) to have converged on its own, with no action taken by
this phase or any other.

Date this section was last written: 2026-08-20 (Task 3 of this plan).

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

Every command issued on the host was one of: `ssh`, `cat`, `head`, `tail`,
`grep`, `stat`, `ls`, `python3` (reading JSON), `sqlite3` in read-only URI
mode, and the `revenium` CLI's read subcommands. No `revenium meter`, no
`jobs create`/`outcome`, no `guardrails ... create`/`update`/`delete`, no
write to any profile's `env`/`config.json`/`drain-status.json`/ledger, no
`clear-halt.sh`, no gateway restart, no `rsync` to the host. A profile was
never touched to make it converge.

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

**7 of 10 converged, unforced, with zero disagreement across all three
rounds of this observation window.** No profile flipped `drained` state
between rounds here — contrast with `33-RESEARCH.md`'s earlier observation
of `coder` flapping drained→un-drained→drained across a *different, wider*
window on 2026-08-19/20, which is why this task samples repeatedly rather
than trusting one reading (the gate is known to flap in general; it simply
did not flap during these particular three rounds).

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
run, a gateway restart, a direct ledger edit) occurred — no evidence of any
of those was found either, but absence of evidence for an unlogged action
is not the same class of proof as a file timestamp.

### CUT-02 — read-side dimension confirmation (task type, operation type, trace id/type, agentic job id, squad, per-call, multi-model)

*Filled by plan 33-02.*

## Findings

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

**No undetermined causes.** All eleven pending sessions across the three
profiles fit cleanly into the single applicable bucket (open per
`state.db`, on the staleness route, not yet past the floor) — none needed
the fourth "data does not distinguish" fallback this task's own guidance
allows for.

### CUT-02 — `agenticJobId` and multi-model resolutions

*Filled by plan 33-02.*

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

**CUT-02:** not yet performed — see plan 33-02.

## Verified against

Date: 2026-08-20 (Task 1 of this plan). Method: read-only SSH access to
the fleet host plus the `revenium` CLI's read verbs against the live
Revenium dev tenant. Host address, SSH key filename, remote login string,
and every raw session/trace identifier are deliberately omitted from this
file and live only in this repository's local, gitignored evidence
artifact (`.planning/phases/33-convergence-and-read-side-proof/33-EVIDENCE.md`),
resolved via the stable placeholders used above (`<sid-A>`, `<hash-A>`,
`<profile-state-dir>`). Profile role labels (`playtester`, etc.) are
retained because the per-profile reading in this document depends on them.
