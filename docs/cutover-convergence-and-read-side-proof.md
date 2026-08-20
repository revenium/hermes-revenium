# Fleet Cutover Convergence and Read-Side Proof — Observed Unforced, Diagnosed Where Pending

## Verdict

**Status: IN PROGRESS — Task 1 of 3 (this plan) landed.** The tracer proof
below establishes that every layer this phase needs — SSH read, drain-gate
JSON parse, reporter log-line corroboration, a paged read-side Revenium
query, redaction, and the split git-tracked/gitignored write — works
end-to-end on one profile (`playtester`) and one metered event row. The
full ten-profile convergence table (Task 2) and the named-cause diagnosis
for every profile that has not converged (Task 3) are recorded below this
statement as they land, and this section is rewritten once with the final
CUT-01 outcome at the close of Task 3 of this plan.

Date this section was first written: 2026-08-20.

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

| Profile | R1 `drained`/`pendingCount` | R2 | R3 | Status |
|---|---|---|---|---|
| gtm | false / 5 | false / 5 | false / 5 | **PENDING** — see `## Findings` |
| marketing | true / 0 | true / 0 | true / 0 | **CONVERGED** |
| devops | true / 0 | true / 0 | true / 0 | **CONVERGED** |
| qa | true / 0 | true / 0 | true / 0 | **CONVERGED** |
| coder | true / 0 | true / 0 | true / 0 | **CONVERGED** |
| playtester | true / 0 | true / 0 | true / 0 | **CONVERGED** |
| cfo | true / 0 | true / 0 | true / 0 | **CONVERGED** |
| pm | true / 0 | true / 0 | true / 0 | **CONVERGED** |
| community | false / 1 | false / 1 | false / 1 | **PENDING** — see `## Findings` |
| lorekeeper | false / 5 | false / 5 | false / 5 | **PENDING** — see `## Findings` |

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

*Filled in Task 3 of this plan.*

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
