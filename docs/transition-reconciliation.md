# Cutover Transition Reconciliation — Method Proven End-to-End on One Session, Fleet-Wide Enumeration Pending

## Verdict

**Provisional — this section is finalized by 34-04.** This document's structural shape is
now final (all nine sections below) and its underlying method is proven end-to-end on one
profile and one session, but the fleet-wide claims CUT-03 asks for — every dual-billed
session enumerated, all ten profiles' boundaries and arithmetic, the closing verdict — are
not yet written. What follows is what this plan's tracer task (34-01 Task 1) closes:

**The reconciliation method works as designed, on real data, in both directions of the
write-loss partition.** One profile (`playtester`) had its cutover boundary derived from
its own local evidence — its first post-flip event-path report — and separately, the
read-side visibility of that boundary was shown to lag it by over four hours, exactly the
shape `## Known limitations and exclusions` predicts. One session that ran entirely after
the write-loss window closed reconciled EXACTLY: its local evidence (event-path report,
no legacy ledger line) and Revenium's read-side total (13,634 tokens) agree with zero
residual. A second session — the profile's actual first post-flip event, timestamped
inside the write-loss window — was shown local evidence of a successful 13,665-token
report (ledger idempotency line, spool file, log line) against a `404 Resource not
found` on Revenium's read side, demonstrating the write-loss branch of the partition on a
real casualty, not a hypothetical one.

**Not yet answered by this document:** the overlap-detector integrity checks (34-01
Task 2), the fleet-wide overlap enumeration (34-02), the ten-profile boundary-plus-
arithmetic reconciliation (34-03), and the final verdict with its independent-confirmation
re-runs (34-04). Every section below that those plans/tasks own carries a single italic
placeholder line naming the plan that fills it.

## Why this document exists

The planning directory that captured this measurement is excluded from version control,
so this file is the committed mirror of the headline findings and the replayable method.
Deleting it turns a later phase's own repository pin red (Phase 35 / CUT-07 registers
this file in `tests/test_repository.py::test_expected_files_exist`), which is the whole
point: a verdict that only exists in an untracked directory is a verdict that did not
happen.

## What was measured

Population: the ten fleet profiles that cut over on 2026-08-19 (`gtm, marketing, devops,
qa, coder, playtester, cfo, pm, community, lorekeeper`) on the fleet host named in
`.planning/STATE.md`, and the Revenium dev tenant those profiles report to.

**The two token sources are asymmetric — stated once, here, so no later section
re-derives or contradicts it.**

The legacy ledger line shape is `HERMES:<sid>:<total_tokens>:<ts>:<muid>`, where the third
field is the session's **cumulative** total at report time, never a delta — the delta
computation at `hermes-report.sh:1708-1741` reads the PREVIOUS ledger line's tokens field
as the next delta's baseline, which is what makes the semantics cumulative. A session's
correct legacy total is therefore that sid's **last** line, and summing every line for a
sid multiply-counts its early growth. This document never sums legacy ledger lines.

The event ledger line shape is `API:<api_request_id>|<sid>|<ts>` (`common.sh:125`) and
carries **no token field at all** — it is a pure idempotency record. The event path's real
per-call total reaches `revenium meter completion --total-tokens` and, once shipped,
exists nowhere durable on the local side except an ephemeral spool file (subject to
manual-only GC via `prune-markers.sh`). The event side's only DURABLE total source, once a
spool file may have been pruned, is Revenium's own read side (`revenium squads get
<root_sid>` / `revenium squads timeline <root_sid>`). No section of this document reads or
infers a token total from the event ledger.

Every command issued by this phase against the fleet host is one of: `ssh`, `cat`, `head`,
`tail`, `grep`, `stat`, `ls`, `wc`, `comm`, `python3` (JSON parsing only), `sqlite3` in
read-only URI mode, and the `revenium` CLI's read subcommands (`squads
get`/`timeline`/`list`/`executions`, `metrics ai`, `jobs get`/`transactions`, `config
show`). No `revenium meter`, no `jobs create`/`outcome`, no `guardrails ...
create`/`update`/`delete`, no write to any profile's `env`/`config.json`/
`drain-status.json`/any ledger/`owners/` record/any spool file, no `clear-halt.sh`, no
gateway restart, no `rsync` to the host.

## Known limitations and exclusions

**The write-loss window is `2026-08-19T18:25:00Z` through `2026-08-20T01:24:00Z`, closed
at both ends.** Revenium's dev tenant accepted writes and silently discarded them across
that span while returning success (documented in `.planning/STATE.md`'s "Revenium dev
outage" section). A row or local timestamp at exactly either endpoint is INSIDE the
suspect window.

**The fleet's cutover flip window (`2026-08-19T21:12Z`–`21:40Z`) sits ENTIRELY INSIDE the
write-loss window.** This is not a corner case — it is the default expectation for the
first hours of event-path activity on every early-converging profile. This document's own
tracer directly demonstrates the consequence: `playtester`'s TRUE first post-flip
event-path report (`21:38:39Z`) fell inside the outage and is invisible on Revenium's read
side entirely (a live `404` on that exact session, quoted in `## Results`); the earliest
row the read side DOES show for that profile is a later, unrelated session
(`01:48:46.521Z`), over four hours after the true boundary. Any later section that
mistakes a read-side-first-visible-row timestamp for a profile's true cutover instant is
making exactly this error — the read-side timestamp is a visibility LOWER BOUND, never the
boundary itself.

**Cost is `$0` by operator decision (CUT-08 / BACK-2676 out of scope).** This pre-prod dev
tenant's cost figures are `$0` by explicit operator choice, not because nothing was
metered. Every `totalCost: 0` figure quoted in this document carries this caption:
**operator decision (BACK-2676 out of scope), not a metering defect.**

**Scope boundary — other phases' work, not this one's:** the `docs/event-metering.md`
correction, the repository pin for this document (`tests/test_repository.py`), and the
BACK-2676 cost prerequisite are Phase 35 (CUT-04/CUT-07) work and are not addressed here.

*The overlap-detector integrity checks (34-01 Task 2) and their qualifications are filled
in next, in this same plan.*

## Results

### Tracer — one profile, one session, one reconciliation (Task 1 of this plan)

**Boundary — `playtester`, derived from its own local evidence.**

`env` flip (from file mtime): `2026-08-19T21:33:57Z`.

Earliest `api-event-report.sh`-shaped `Reported: sid=... api_request_id=...` line in
`<profile-state-dir>/revenium-metering.log` at or after the flip:
`2026-08-19T21:38:39Z`, session `<sid-B>`. That same sid has **zero** `HERMES:` lines in
`<profile-state-dir>/revenium-hermes.ledger` — confirming the event path, not legacy,
billed it first, with no prior legacy claim to contest.

**Boundary: `2026-08-19T21:38:39Z`.**

**Read-side visibility lower bound — separately recorded, NOT the boundary.** A query
window starting one second after the write-loss window's close
(`2026-08-20T01:24:01Z`–`2026-08-20T02:10:00Z`, all pages) returns exactly one
`Hermes-playtester` row: `created=2026-08-20T01:48:46.521Z`,
`transactionId=event:<sid-T>:<sid-T>:<hash-T>:api:1`. This is a DIFFERENT session (`<sid-T>`,
the tracer session below) — the profile's TRUE first event (`<sid-B>` at `21:38:39Z`) never
becomes read-side-visible at all (see the suspect exemplar below). **Lower bound on
visibility: `2026-08-20T01:48:46.521Z` — 4h10m07s after the true boundary. This is a
visibility floor, not the cutover instant.**

**Three-way reconciliation — session `<sid-T>` (`playtester`, entirely after
`2026-08-20T01:24:00Z`, = Phase 33's own post-fix probe session).**

| Source | Query | Result |
|---|---|---|
| Legacy (last `HERMES:` line) | `grep "^HERMES:<sid-T>:" revenium-hermes.ledger` | **No such line** — event-owned, never legacy-claimed. Absence is the expected finding, not a failed read. |
| Read side, aggregate | `revenium squads get <sid-T> --output json` | `totalTokens: 13634` (query time: 2026-08-20T15:28Z) |
| Read side, row-level | `revenium squads timeline <sid-T> --output json` | One row, ordered by its own `startTime`: `id=event:<sid-T>:<sid-T>:<hash-T>:api:1` (`event:` prefix → EVENT class), `totalTokens: 13634` |

Row-level classification sums: event = 13634, legacy = 0. Equals the aggregate total
exactly — zero residual.

**Clean/suspect partition:** session `<sid-T>` ran entirely `2026-08-20T01:47:47Z`–
`01:47:49Z`, strictly after `2026-08-20T01:24:00Z` → **CLEAN**. Expected result confirmed:
local evidence (one event-path report, no legacy row) and the read side (13,634 tokens)
agree exactly, with no unexplained residual.

**Suspect-bucket exemplar — session `<sid-B>` (`playtester`'s actual first post-flip
event, `2026-08-19T21:38:39Z`, inside the write-loss window).**

Local evidence: an `API:` idempotency ledger line (no token field, as `## What was
measured` states) plus its still-unpruned spool file, `total_tokens: 13665`
(`input_tokens=13629`, `output_tokens=36`) — this is what was locally reported as shipped.

Read side: `revenium squads get <sid-B> --output json` → `{"error": "Resource not found.",
"exit_code": 3, "status": 404}`.

**This is the write-loss branch of the partition, demonstrated on a real casualty:** the
call returned success locally (a ledger line and a spool file are written ONLY on a 0
exit code), but Revenium's tenant retains nothing for this session now. Both branches of
the partition — clean (`<sid-T>`, agrees exactly) and suspect (`<sid-B>`, local evidence
of 13,665 tokens shipped, read side shows nothing) — are demonstrated, not asserted.

*Overlap-detector integrity (34-01 Task 2), fleet-wide overlap enumeration (34-02),
per-profile boundaries and arithmetic (34-03), and independent confirmation re-runs
(34-04) are filled in next, by those tasks/plans.*

## Findings

*Filled in by 34-02 (overlap enumeration) and extended by 34-03/34-04.*

## Reproducing this measurement

**Boundary derivation (per profile):**
```bash
ssh <fleet-host> \
  'grep -n "Reported: sid=.*api_request_id=" \
     /home/ubuntu/.hermes/profiles/<profile>/state/revenium/revenium-metering.log | head -1'
ssh <fleet-host> \
  'grep "^HERMES:<sid>:" \
     /home/ubuntu/.hermes/profiles/<profile>/state/revenium/revenium-hermes.ledger | wc -l'
```

**Legacy per-session total (last line, never a sum):**
```bash
grep "^HERMES:<sid>:" revenium-hermes.ledger | tail -1 | cut -d: -f3
```

**Read-side total and row-level split:**
```bash
revenium squads get <root_sid> --output json      # top-level totalTokens
revenium squads timeline <root_sid> --output json  # per-row; classify id by event: prefix
```

*A replayable template per verb family this whole phase used is 34-04 Task 1's own
acceptance criterion — the above covers only what Task 1 of this plan used.*

## Independent confirmation

*Filled in by 34-04 — re-runs of this plan's own queries, plus the fleet-wide sweeps' own
independent-confirmation rounds.*

## Verified against

Date: 2026-08-20. Method (this task only): read-only SSH access to the fleet host
(`revenium-metering.log`, `revenium-hermes.ledger`, `revenium-api-events.ledger`, the
`api-events/` spool directory, `env` file mtime) plus the `revenium` CLI's read verbs
(`squads get`, `squads timeline`, `metrics ai`) against the live Revenium dev tenant.
Population: one profile (`playtester`) and two of its sessions.

**Deliberately omitted from this file, on every page, in every task:** the fleet host's
address, the SSH key filename, every remote login string, and every raw session, trace,
`api_request_id`, and composite `transactionId`. These live only in this repository's
local, gitignored evidence artifact
(`.planning/phases/34-transition-reconciliation/34-EVIDENCE.md`), resolved via the stable
placeholders used above (`<sid-B>`, `<hash-B>`, `<sid-T>`, `<hash-T>`,
`<profile-state-dir>`).

**Retained, deliberately:** profile role labels (`playtester`, `coder`, `gtm`, etc.),
every aggregate figure (token counts, timestamps), and read-side query results — none of
these are session, trace, or host identifiers, and the per-profile reading throughout this
document depends on them.
