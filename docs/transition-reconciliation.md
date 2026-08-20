# Cutover Transition Reconciliation — Sole Overlap Confirmed Fleet-Wide; Arithmetic Closes for 5/10 Profiles (Residual 2 Corrected / 112,603 Literal), 50,731 Tokens Confirmed Write-Loss

## Verdict

**RECONCILED, WITH NAMED AND QUANTIFIED SHORTFALLS — read this paragraph in full before
any other section.** Across three independent signals swept over the full ledger history
of all ten fleet profiles, the known 12,608-token canary is confirmed the ONLY session
ever billed by both paths — no second overlap exists anywhere in the fleet — and where the
reconciliation arithmetic runs, it closes to within 2 tokens. Stated without softening,
alongside that result: **(1)** that arithmetic covers only 5 of the fleet's 10 profiles
(gtm, marketing, coder, playtester, cfo) — the other five (devops, qa, pm, community,
lorekeeper) have no reconciliation at all because none has reached a cutover boundary yet,
and two of those five (devops, pm) have an absence of `owners/` overlap evidence that is
NON-PROBATIVE, not clean: neither has had a single new session since the flip for the
detector to evaluate, so "no record" there means "nothing was there to check yet," never
"no overlap found." **(2)** 50,731 tokens (marketing 37,066 + playtester 13,665) are
Revenium's OWN confirmed write-loss inside the cutover's write-loss window — each verified
live via a `404` against locally-reported, spool-corroborated activity that Revenium's
tenant silently discarded; real, permanent, and by design excluded from the residual
rather than chased as a metering gap. **(3)** the residual is **112,603 tokens under the
literal, as-defined bulk-walk measurement** — the number a reader gets by running this
document's own method exactly as written, before any correction. **(4)** that literal
residual shrinks to **2 tokens only once corrected** for one confirmed `metrics ai`
date-filter behavior (it keys off `requestTime`, the start of a legacy delta period, not
`created`, when Revenium actually recorded the row) — and this correction's scope is
**UNDETERMINED beyond the single gtm instance it was confirmed on**: whether the same gap
recurs on any other profile's future legacy delta report was not determined, so 2 tokens
is a corrected result for one confirmed case, not a fleet-wide guarantee. **(5)** one
transient Revenium API error (HTTP 502) occurred on the bulk walk's first attempt,
resolved by an identical retry ~30 seconds later. **(6)** two of the five
boundary-established profiles, gtm and community, had not fully converged (fully drained)
as of this document's own last live read — gtm's already-reached boundary is unaffected,
since the ownership protocol operates per-session, not per-profile, but neither profile's
drain is complete. **(7)** the pruned-spool bucket is empty (0 sessions, 0 tokens) by
direct check today, but remains a live risk for any later phase: `prune-markers.sh`'s
manual-only prune pass could remove a session's spool file before that session's tokens
are confirmed on the read side. **(8)** this document's own redaction-proof sweep found
and fixed one genuine identifier leak that the file-wide regex gate alone did not catch —
the fleet host's own hostname, quoted raw twice in `## Verified against` — now redacted;
closed, but it is direct evidence that the regex gate is a floor for this document's
redaction discipline, not a guarantee, the same lesson Phase 33's own review drew on this
document's sibling.

**Headline, stated up front rather than buried: this plan's own integrity sweep
(Task 2) incidentally found THREE two-line, dual-ledger `owners/` records beyond the
known canary — two on `qa`, one on `cfo`, all dated 2026-08-18 (the same pre-cutover era
as the canary itself). This plan does NOT enumerate, read-side-confirm, or diagnose them —
that is 34-02's explicit charter — but their raw existence means CUT-03 criterion 3 ("the
canary is the only permitted pre-existing overlap") is an OPEN QUESTION for 34-02 to
resolve, not a settled fact this document can currently affirm. See `## Results` →
"Overlap-detector integrity" for the finding and `34-EVIDENCE.md` for their identifiers.**

**34-02 resolves the open question above: the canary remains the ONLY genuine
pre-existing overlap.** All ten profiles were swept fleet-wide, full ledger history, by
three independent signals (the `owners/` two-line-record sweep, a raw `comm -12`
cross-check of the two ledgers' distinct sid sets, and a grep of every retained
`revenium-metering.log` for the dual-ledger warn string). 626 owner records, 2,577
distinct legacy sids, and 14 distinct event sids were swept; exactly ONE session
(`<canary-sid>`, redacted per this document's own convention) was found in BOTH ledgers by
the independent raw cross-check. **The three additional two-line
`owners/` records this plan's own predecessor flagged (two on `qa`, one on `cfo`) are
confirmed NOT overlaps** — direct per-sid drill-down shows the legacy ledger has ZERO
lines for all three, ever; the second line on their owner files was written by a
structurally different mechanism (`_takeover_session_owner`, a pre-cutover
shadow-mode ownership handoff that explicitly floors legacy's baseline so it "never
re-bills what the event path already shipped") than the canary's own dual-ledger claim
(`_claim_session_owner`'s dual-ledger branch). Both mechanisms happen to write a 2-line
owner file, which is why the durable-record signal alone flagged all four — the raw
ledger cross-check and the exact log-string match are what correctly separate the one
real overlap from the three false positives. See `## Results` → "Overlap enumeration —
three independent signals" and `## Findings` for the full per-session enumeration this
finding rests on.

**A second, independent finding from re-deriving the canary's own numbers live rather
than copying them forward: the canary's total metered footprint is larger than previously
computed.** `32-CANARY-EVIDENCE.md` recorded the legacy-side total (12,608 tokens, 2 rows)
but explicitly marked read-side confirmation of the event side "not-run". Live re-derivation
via `squads get`/`squads timeline` finds the event path's own 4 rows sum to 24,688 tokens —
legitimate cache-inclusive per-call accounting for a 4-turn tool-use loop, not a second
overcount (the underlying real input+output usage, 12,608 tokens, is identical whichever
path's own accounting is read). The trace's true combined total, both paths summed, is
37,296 tokens with zero residual against the read side's own aggregate. This does not
change the overlap COUNT (it is still one session), but it corrects the previously
incomplete magnitude on record for that one session. See `## Findings` → the canary's own
subsection for the full row-level breakdown.

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

**The overlap-detector integrity checks (Task 2, this plan) establish whether an absence
of two-line `owners/` records elsewhere in this phase's later work will mean anything.**
See `## Results` for the per-profile currency, engagement, and prune-history table, and
`## Known limitations and exclusions` for every qualification those checks produced.

**Answered in full, as of this document's current state.** The fleet-wide overlap
enumeration (34-02) is CLOSED — see above and `## Findings`. The ten-profile
boundary-plus-arithmetic reconciliation (34-03) is CLOSED — see `## Results`, five
profiles reconciled, five not yet reached, per the first paragraph above. The final
verdict, with its independent-confirmation re-runs (34-04), is the first paragraph above
— RECONCILED WITH NAMED, QUANTIFIED SHORTFALLS, not a clean unqualified close. No section
of this document carries an unfilled placeholder any longer.

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

**Deployed-versus-checkout drift: none found.** All four scripts this phase's exact-string
greps depend on (`hermes-report.sh`, `api-event-report.sh`, `common.sh`,
`prune-markers.sh`) match the checkout at the fleet's pinned deploy commit `f13bdf6`
byte-for-byte. No qualification carried forward from this check.

**Two profiles' overlap-detector coverage is non-probative, not clean.** `devops` and `pm`
have NOT engaged the ownership protocol as of this observation — their `owners/`
directories do not exist yet (not merely empty), because neither profile has had a single
new session since the 2026-08-19 cutover flip for the event path to claim. Both ARE
genuinely cut over (`drain-status.json: drained=true`). **34-02 and 34-03 must not read
"no owners records on devops/pm" as "no overlap on devops/pm" — it is "nothing was there
to check yet."** If either profile gets its first post-flip session before this phase
closes, this qualification should be re-evaluated against fresh data, not assumed to still
hold.

**Three additional two-line `owners/` records exist beyond the canary, unenumerated by
this plan.** Task 2's per-profile listing (gathered to confirm the canary's own record)
also found two-line records on `qa` (2) and `cfo` (1), all dated 2026-08-18 — the same
pre-cutover era as the canary. This plan does not investigate them further; 34-02 must
treat this as its starting evidence, not discover it independently and not assume the
canary is the only pre-existing overlap without first accounting for these three.
**RESOLVED by 34-02: confirmed NOT overlaps** — see `## Verdict` and `## Findings`.

**A two-line `owners/` record is NOT, by itself, proof of a double-bill (correction to
this document's own earlier framing, landed by 34-02).** Two structurally different
primitives both write a 2-line owner file: `_claim_session_owner`'s dual-ledger branch
(fired when BOTH ledgers already had rows for a session at claim time — genuine evidence
of a past double-bill, the canary's own mechanism) and `_takeover_session_owner` (fired
when legacy takes over an event-owned record during pre-cutover shadow mode, writing a
floor specifically so it will NEVER re-bill what the event path already shipped — a
double-bill PREVENTION mechanism, not evidence one occurred). The two write byte-similar
files and, in the takeover case, a log line with different wording
(`"session ownership taken over from the event path... mode=..."`) than the dual-ledger
claim's (`"dual-ledger session claimed for the legacy path..."`). Any later phase reading
`owners/` two-line records as a pre-computed overlap list must additionally check the
raw ledger `comm -12` intersection or the exact log string — the durable record alone
over-reports.

**Pruned-spool bucket (event-side local evidence unavailable, one-way-checkable only):
`0` sessions, `0` tokens (34-03 Task 2/3).** For every post-boundary event-path session
on the five profiles that had reached a boundary at this document's writing, the
`api-events/<sid>.jsonl` spool file was checked and found present and readable — none had
been garbage-collected by `prune-markers.sh`'s manual-only owners pass. This bucket is
therefore empty by direct check, not by assumption, for this reconciliation's own window.
Had any spool file been pruned, that session's event-side local total would have been
unavailable — checkable only from Revenium's read side, with no local figure to compare
it against — and would have been placed in this bucket with its own session count and
token total (where the read side supplies one) rather than assumed zero or dropped from
the arithmetic. The mechanism remains a live risk for any later phase: `prune-markers.sh`
is manual-only today, but nothing prevents a future run from pruning a spool file whose
session has not yet been read-side-reconciled.

**`metrics ai --from`/`--to` filters by `requestTime`, not `created` — a CLI-behavior
limitation on any date-windowed bulk query against this verb (34-03 Task 2).** For a
legacy delta-report row, `requestTime` is the START of the delta period (the previous
report's own timestamp), which can predate the row's `created` timestamp (when Revenium
actually recorded it) by hours to weeks. A bulk `metrics ai` walk windowed strictly after
the write-loss window will silently exclude such a row even though it was genuinely
reported, and would be counted as CLEAN, safely inside the window. See `## Findings` for
the full live bisection and `## Results` → gtm's own table for the one confirmed
instance and its corrected figures. This is a limitation of the bulk-query aggregation
method, not evidence of a metering gap — every instance found this phase was confirmed
present via a direct, date-window-free `squads get`/`squads timeline` query.

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

### Overlap-detector integrity (Task 2 of this plan)

| Profile | Deployed-vs-checkout hash (4 files) | Event ledger | `owners/` entries | Spool files | Engagement gate | Prune-history |
|---|---|---:|---:|---:|---|---|
| gtm | match (all 4) | 278 B | 57 | 14 | **engaged** (ledger) | no evidence of a run |
| marketing | match (all 4) | 973 B | 235 | 21 | **engaged** (ledger) | no evidence of a run |
| devops | match (all 4) | 0 B | 0 (dir absent) | 0 | **NOT engaged** | no evidence of a run |
| qa | match (all 4) | 206 B | 22 | 2 | **engaged** (ledger) | no evidence of a run |
| coder | match (all 4) | 796 B | 227 | 5 | **engaged** (ledger) | no evidence of a run |
| playtester | match (all 4) | 206 B | 7 | 3 | **engaged** (ledger) | no evidence of a run |
| cfo | match (all 4) | 1076 B | 42 | 7 | **engaged** (ledger) | no evidence of a run |
| pm | match (all 4) | 0 B | 0 (dir absent) | 0 | **NOT engaged** | no evidence of a run |
| community | match (all 4) | 0 B | 3 | 1 | **engaged** (owners/spool) | no evidence of a run |
| lorekeeper | match (all 4) | 0 B | 33 | 2 | **engaged** (owners/spool) | no evidence of a run |

**Currency.** `sha256sum` of the deployed `hermes-report.sh`, `api-event-report.sh`,
`common.sh`, `prune-markers.sh` under `~/.hermes/skills/revenium/scripts/`, compared
against this checkout at the fleet's pinned deploy commit `f13bdf6` — all four files
match byte-for-byte. The scripts are deployed ONCE per host and shared by all ten
profiles (confirmed via `crontab -l`: a single `cron-fleet.sh` invocation carries all ten
profile names and repoints `HERMES_HOME` internally, per profile, at runtime — there is no
per-profile copy of the script files themselves), so one comparison per file covers all
ten profiles' rows above identically. No qualification needed for the exact-string greps
34-02 will run.

**Engagement — NOT uniform, and this matters.** The ownership protocol
(`hermes-report.sh:192-200`'s OWN-03 gate) is active only when SOME event-path artifact
exists: a non-empty `revenium-api-events.ledger`, any entry under `owners/`, or any spool
file. **Eight of ten profiles are engaged. `devops` and `pm` are NOT** — both have a
zero-byte event ledger, an `owners/` directory that does not even EXIST yet (confirmed
with `test -d`, not just "empty"; `OWNERS_DIR` is created lazily by the claim primitive,
so its absence proves no claim has ever been attempted), and zero spool files. Both ARE
genuinely cut over (`drain-status.json`: `drained: true, pendingCount: 0` on both, sampled
2026-08-20T15:4xZ) and both show **zero** `Reported: sid=...api_request_id=...` lines in
their whole retained log — i.e. no new session has occurred on either profile since the
flip for the event path to have anything to claim, not a failure of the mechanism. **An
absent `owners/` directory on devops or pm is therefore non-probative for "no overlap" —
there was nothing for the detector to evaluate yet, and 34-02/34-03 must not read their
silence as a clean result.** Two profiles (`community`, `lorekeeper`) are engaged via the
owners/spool disjuncts despite an empty event ledger — their `owners/` counts (3, 33) and
spool counts (1, 2) are real and non-zero even though the ledger itself reads 0 bytes; the
gate correctly treats any one of the three signals as sufficient.

**Prune history.** `prune-markers.sh`'s owners pass is manual-only (never wired into cron,
per `CLAUDE.md`'s "Metering ledger semantics" and the commands block). No profile's
`revenium-metering.log` shows a `prune:` line (the exact string `prune_owners()` emits),
and no `prune.lock` file exists on any profile. Every profile's log retains data back to
somewhere between 2026-07-18 and 2026-07-28 — before the ownership protocol shipped
(quick-260817-tfe, 2026-08-17) — so this is a real "no evidence of a run" finding for all
ten, not an inconclusive one truncated by log rotation.

**Canary — PRESENT, and its baseline matches exactly.** `owners/<canary-sid>` under
`coder`'s `owners/` directory: found, a genuine two-line record —
`legacy` / `12608`. The baseline (`12608`) matches the independently-documented canary
figure (12,608 tokens; `REQUIREMENTS.md`, `32-CANARY-EVIDENCE.md`) EXACTLY. This is
corroboration, not the primary source — the canary's history is independently documented
regardless — but the exact match is strong additional evidence the record is genuine, not
a coincidence. File mtime: `2026-08-18T03:04Z` (the day after the canary event
`2026-08-17T21:30:57Z`, the same day quick-260817-tfe / PR #54 merged).

**INCIDENTAL FINDING — additional two-line (dual-ledger) owner records exist beyond the
canary.** While confirming the canary's own record, this task's per-profile `owners/`
listing (already gathered for the engagement table above) was also checked for line count
on every engaged profile. Result: **three additional two-line records, all dated
2026-08-18 (pre-cutover, same era as the canary) — two on `qa`, one on `cfo`.** This task
does NOT enumerate, read-side-confirm, or diagnose these — that is 34-02's explicit
charter (S-2: "the overlap ENUMERATION... covers the FULL ledger history on every
profile... the only way to answer 'is the canary the only one'"). Recording their
existence here, with their raw identifiers preserved in `34-EVIDENCE.md`, so 34-02 does
not start its enumeration from an unexamined "canary is the only one" assumption. **This
finding alone means CUT-03 criterion 3 ("the canary is the only permitted pre-existing
overlap") cannot yet be affirmed — it is 34-02's open question, not this plan's.**

### Overlap enumeration — three independent signals, all ten profiles, full ledger history (34-02 Task 1)

Scope: the WHOLE retained history of every profile's `owners/` directory and both
ledgers — not a post-cutover window. Every one of the ten logs' first surviving line
predates `REVENIUM_LOG_MAX_BYTES` (50 MiB) rotation ever triggering (each log is 11.7–26.7
MB, well under the ceiling), so "swept the whole retained history" is not a sampled claim.

| Profile | Owners swept (total) | Owners 2+-line hits | Legacy sid-set size | Event sid-set size | `comm -12` intersection | Dual-ledger warn hits | Earliest surviving log line |
|---|---:|---:|---:|---:|---:|---:|---|
| gtm | 57 | 0 | 56 | 1 | 0 | 0 | 2026-07-18T00:02:36Z |
| marketing | 235 | 0 | 231 | 4 | 0 | 0 | 2026-07-18T00:02:44Z |
| devops | UNDETERMINED (dir absent) | UNDETERMINED | 1939 | 0 | 0 (trivial) | 0 (trivial) | 2026-07-18T00:03:03Z |
| qa | 22 | **2** | 20 | 2 | 0 | 0 | 2026-07-18T00:07:08Z |
| coder | 227 | **1** (the canary) | 225 | 3 | **1** (the canary) | **1** (the canary) | 2026-07-18T00:07:10Z |
| playtester | 7 | 0 | 5 | 2 | 0 | 0 | 2026-07-18T03:41:15Z |
| cfo | 42 | **1** | 40 | 2 | 0 | 0 | 2026-07-19T23:42:30Z |
| pm | UNDETERMINED (dir absent) | UNDETERMINED | 25 | 0 | 0 (trivial) | 0 (trivial) | 2026-07-20T04:39:20Z |
| community | 3 | 0 | 3 | 0 | 0 | 0 | 2026-07-28T22:37:23Z |
| lorekeeper | 33 | 0 | 33 | 0 | 0 | 0 | 2026-07-28T22:37:24Z |
| **Sum (engaged profiles)** | **626** | **4** | **2,577** (all ten) | **14** (all ten) | **1** | **1** | — |

**`devops`/`pm` marked UNDETERMINED for signal 1, and their signal-2/3 zeros are TRIVIAL,
not clean** — carried forward from 34-01's own integrity table: neither profile has ever
engaged the ownership protocol (`owners/` directory does not exist; `test -d` confirmed
absence, not mere emptiness), both show a genuinely non-zero legacy sid history (1,939 and
25 sessions respectively — real pre-cutover legacy-only usage) alongside a genuinely
EMPTY event sid set (0 — no event-path activity has EVER occurred on either profile). A
`comm -12` intersection of 0 against an empty set proves nothing about overlap; it proves
only that nothing has happened yet for the detector to evaluate. If either profile
acquires its first post-flip session before this phase closes, this row must be
re-swept, not assumed to still read UNDETERMINED.

**Every partial detection explained, not merely listed:**

- **`qa` (2 hits) and `cfo` (1 hit): signal 1 (owners two-line record) found them; signal
  2 (raw ledger `comm -12`) and signal 3 (exact dual-ledger warn string) did NOT.**
  Direct per-sid drill-down (not inference) rules out the tidier-sounding explanation —
  pruning of a since-removed event-ledger line — because the event ledger's line for all
  three sids is still present, unpruned, right now. The real cause, confirmed from source
  (`hermes-report.sh:426-471, 1640-1679`) and corroborated by each profile's own
  contemporaneous log line at the owner file's exact mtime: all three two-line records
  were written by `_takeover_session_owner` (quick-260818-0in/MODE-01), a ONE-WAY
  ownership handoff from the event path to legacy that fires only while the fleet ran
  pre-cutover `shadow` mode — structurally different from `_claim_session_owner`'s
  dual-ledger branch (the canary's own mechanism), and NOT evidence of a double-bill: the
  legacy ledger has zero lines for all three sids, confirmed directly, so legacy never
  actually billed anything for them despite "owning" the record. Full per-session detail
  in `## Findings` below.
- **`coder`'s canary: found by all three signals, in full agreement.** This is the one
  genuine cross-signal confirmation in the sweep, and it is the ONLY session the raw,
  assumption-free `comm -12` cross-check independently finds in both ledgers, fleet-wide.
- **All other profiles (gtm, marketing, playtester, community, lorekeeper): zero hits on
  all three signals, in full agreement.** No partial detections to explain.

**Candidate set (union of anything any signal found): 4 sessions — 1 genuine overlap (the
canary) + 3 confirmed non-overlaps (ownership takeovers).** See `## Findings` for the
full per-session enumeration, including the three non-overlaps, so the audit trail is
complete rather than silently dropping the candidates the signals disagreed on.

### Per-profile cutover boundaries, each from its own evidence (34-03 Task 1)

**Env flip re-confirmed uniform across all ten profiles, live, not assumed.** `stat` on
every profile's own `env` file returns the identical mtime **`2026-08-19T21:33:57Z`**
(sub-second offsets `.914`–`.958` only, from a single `install-hooks.sh`-driven write),
matching Phase 33's own finding exactly — re-confirmed rather than carried forward.

Each profile's boundary is the timestamp of its earliest `Reported: sid=...
api_request_id=...` line (`api-event-report.sh:1301`) at or after the flip, paired with
confirmation that the same sid has zero `HERMES:` lines in that profile's own legacy
ledger — the pairing that makes the claim, per this plan's own method, not the fleet-wide
flip instant used as a stand-in. Where no such line exists at all, the profile has not
started billing through the event path and its boundary is recorded as not yet reached,
with its own reason.

| Profile | Boundary | Boundary check (log line + legacy-line absence) | Read-side visibility lower bound | Gap | Attribution |
|---|---|---|---|---|---|
| gtm | **2026-08-20T14:03:28Z** | `<gtm-B-sid>`; `grep "^HERMES:<gtm-B-sid>:"` → 0 lines | 2026-08-20T14:03:28.543Z | ~0.5s | Clean — boundary sits well after W's close; the sub-second gap is ordinary reporting latency, not the outage. |
| marketing | **2026-08-19T22:46:28Z** | `<mkt-B-sid>`; 0 `HERMES:` lines | 2026-08-20T04:47:44.696Z — a **later, different** session, `<mkt-C1-sid>` | **6h01m16.696s** | Write-loss window swallowed the true boundary session. Confirmed live: `revenium squads get <mkt-B-sid>` → `{"error": "Resource not found.", "exit_code": 3, "status": 404}` — the same shape as the tracer's own suspect exemplar (`<sid-B>`), demonstrated on a second, independent casualty. |
| devops | **not yet reached** | 0 `Reported: sid=...api_request_id=` lines in the whole retained log | n/a — 0 `Hermes-devops` rows in the post-`01:24:01Z` read-side query | n/a | Genuinely cut over (`drained=true, pendingCount=0`, live) but zero new sessions since the flip — nothing for the event path to claim yet (carried forward from 34-01's own finding). |
| qa | **not yet reached** | 0 post-flip lines. The log's only 2 `Reported:` lines ever are pre-cutover (`2026-08-18T21:18:58Z` / `21:20:24Z`, sids `<qa-dual-sid-1>` / `<qa-dual-sid-2>` — the SAME two sessions 34-02 already confirmed are ownership takeovers, not overlaps) | n/a — 0 rows | n/a | Drained (`drained=true, pendingCount=0`, live) but zero new sessions since the flip. |
| coder | **2026-08-20T01:53:27Z** | `<coder-B1-sid>` (co-occurring sibling `<coder-B2-sid>`, a subagent-shaped session claimed the same instant); 0 `HERMES:` lines for either | 2026-08-20T01:53:27.944Z | ~0.9s | Clean — this is coder's own **POST-cutover** boundary, distinct from the pre-cutover canary (`<canary-sid>`, `2026-08-17`, 34-02's confirmed sole overlap); the boundary sits 29m27s after W's close. |
| playtester | **2026-08-19T21:38:39Z** — established by 34-01, cited here, not re-derived | `<sid-B>`; 0 `HERMES:` lines | 2026-08-20T01:48:46.521Z — established by 34-01 | **4h10m07s** — established by 34-01 | Write-loss window — established by 34-01; repeated here only so the ten-row table is complete. |
| cfo | **2026-08-20T09:08:00Z** | `<cfo-B-sid>`; 0 `HERMES:` lines | 2026-08-20T09:08:01.016Z | ~1.0s | Clean — boundary sits over 7h after W's close. |
| pm | **not yet reached** | 0 `Reported:` lines, ever | n/a — 0 rows | n/a | Genuinely cut over (`drained=true, pendingCount=0`, live) but zero new sessions since the flip. |
| community | **not yet reached** | 0 `Reported:` lines, ever | n/a — 0 rows | n/a | Still draining — `drained=false, pendingCount=1`, unchanged since Phase 33's close (see live re-read below). |
| lorekeeper | **not yet reached** | 0 `Reported:` lines, ever, in the whole retained log | n/a — 0 rows | n/a | Drained (`drained=true, pendingCount=0`, live) but zero new sessions since the flip; its 33 `owners/` entries and 2 spool files (34-01's own integrity table) are all dated on or before `2026-07-31`/`2026-08-17` — pre-cutover, corroborating "no post-flip activity" independently of the log check. |

**Why a still-pending profile is not a double-bill risk, stated once.** The
mutual-exclusion ownership protocol defers the event path for any sid the ownership
record still assigns to legacy. `gtm`'s own remaining 2 pending sessions (both opened
before the cutover, still billing via legacy under the protocol's per-**session**, not
per-**profile**, claim) are direct proof of this: `gtm` is NOT fully drained, yet it
independently reached its own boundary via `<gtm-B-sid>`, a genuinely new session created
after the flip and claimed by the event path the instant it started. The risk window
closes, rather than opens, once a still-pending session finishes draining — while a
session remains open, the protocol guarantees it stays on whichever path claimed it
first, so no double-bill can occur for gtm's or community's remaining open sessions.

**`gtm` and `community` re-read live, compared against Phase 33's own recorded
estimates — neither carried forward as still current.**

- **`gtm`:** `drained=false, pendingCount=2, lastChecked=2026-08-20T16:28:34Z,
  staleSecondsEffective=87000.0` (live). Phase 33's close recorded 5 pending → 2 pending
  (partial convergence — three of five sessions had closed) with an earliest-full-
  convergence estimate of `≈2026-08-20T16:59:12Z`, bounded by its slowest remaining sid.
  This read (`16:28:34Z`) is BEFORE that estimate and shows the SAME `pendingCount` (2)
  Phase 33's own close already recorded. **Verdict: gtm has NOT fully converged since
  Phase 33's close** — consistent with, not contradicting, the estimate not yet having
  arrived. gtm nonetheless has its own boundary (row above), because the ownership
  protocol operates per-session, not per-profile.
- **`community`:** `drained=false, pendingCount=1, lastChecked=2026-08-20T16:28:41Z,
  staleSecondsEffective=87000.0` (live). Phase 33 recorded 1 pending, unchanged, with an
  earliest-full-convergence estimate of `≈2026-08-20T21:33:13Z`. This read is also BEFORE
  that estimate and shows the SAME `pendingCount` (1). **Verdict: community has NOT
  converged since Phase 33's close** — and, unlike gtm, has ALSO not reached its own
  event-path boundary yet (0 `Reported:` lines ever anywhere in its retained log) — its
  post-boundary reconciliation table below is therefore empty, not zero.

### Per-profile reconciliation — clean against read-side, suspect carved out and counted (34-03 Task 2)

**Local evidence, per profile, following `<reconciliation_arithmetic>` exactly.** For
each of the five profiles with a boundary, every legacy ledger sid with a line
timestamped at or after that boundary was found (`awk` on the ledger's fourth,
Unix-epoch field), and its LAST such line's cumulative total was read — never summed.
Every event-path sid was found the same way from the profile's own `api-events/` spool
directory (every file present; none pruned — see the pruned-spool bucket below), and its
per-record `total_tokens` fields summed. Four of the five profiles (marketing, coder,
cfo, playtester) had **no** post-boundary legacy ledger growth at all — post-cutover
activity on those profiles is 100% event-path. `gtm` is the one exception (below).

**Read side, walked per `<reconciliation_arithmetic>`'s own definition.** `revenium
metrics ai --from 2026-08-20T01:24:01Z --to 2026-08-20T23:59:59Z --output json
--page-size 200 --page N`, `N` = 0 through 14, terminated at page 14's short return (55
rows, after fourteen 100-row pages — the server's actual page size is 100 regardless of
the requested 200; see the CLI-behavior finding below). **1,455 total rows, 1,455 unique
`id`s, zero duplicates** — the walk is exhaustive and non-duplicating for what it
returns. `--from`/`--to` both sit strictly after `2026-08-20T01:24:00Z`, asserted
non-overlapping with the write-loss window `2026-08-19T18:25:00Z`–`2026-08-20T01:24:00Z`
in this same paragraph. Rows are attributed to a profile by `agent == "Hermes-<profile>"`
(client-side; no server-side filter exists on this verb) and to a path by whether
`transactionId` starts with `event:`. One query in this walk (`page=0`, first attempt,
`2026-08-20T16:30:03Z`) returned `{"error": "Revenium API error...", "status": 502}`;
recorded under `## Findings` with its exact call before the retry that succeeded.

**A second, more consequential CLI-behavior finding, load-bearing for `gtm`'s own table:
`--from`/`--to` on `metrics ai` filters by each row's `requestTime`, not its `created`
timestamp.** For an event-path row, `requestTime` and `created` sit seconds to minutes
apart (the CLI ships the call and Revenium ingests it almost immediately), so this never
mattered for any event-path session in this phase. For a LEGACY delta-report row,
`requestTime` is the **start of the delta period** — the previous report's own
timestamp — which can predate the row's `created` (when the delta was actually shipped)
by hours, days, or (for a slow-ticking session) weeks. A profile-wide bulk walk
`--from`'d strictly after the write-loss window therefore silently excludes any legacy
delta row whose delta period began before that cutoff, even though the row's own
`created` timestamp — when Revenium actually recorded it — falls safely inside the
window. This is exactly what happened to `gtm`'s one post-boundary legacy row; see its
own table entry below and `## Findings` for the full evidence trail (bisected live: a
window bracketing only `requestTime` returns the row, a window bracketing only `created`
returns none, even with `--squad-id` narrowing to the exact session).

**Pruned-spool bucket (event-side local evidence unavailable): 0 sessions, 0 tokens.**
Every post-boundary event-path sid's spool file, on all five profiles with a boundary,
was found present and readable — none had been garbage-collected. This bucket is stated
as empty by direct check, not assumed.

#### gtm

| Symbol | Value | Source |
|---|---|---|
| SUSPECT | 0 | No post-boundary local evidence (legacy or event) falls inside W; boundary itself sits >12h after W's close. |
| CLEAN | **126,160** = 112,603 (legacy) + 13,557 (event) | Legacy: last ledger line `1056131` minus the pre-boundary last line `943528` = `112603`, line timestamp `2026-08-20T15:53:10.870Z` (`<gtm-legacy-sid>`). Event: `api-events/<gtm-B-sid>.jsonl`, 2 records, `total_tokens` summed = `13557`. |
| READ | **13,557** (bulk walk, `agent="Hermes-gtm"`, literal `<reconciliation_arithmetic>` definition) | `metrics ai` walk above; 2 rows, both `event:`-prefixed, for `<gtm-B-sid>`. |
| READ_event | 13,557 | Same 2 rows. |
| READ_legacy | **0** (bulk walk) — see below for the read-confirmed true value | The bulk walk returned zero `Hermes-gtm` rows with a legacy-shaped `transactionId` in this window — the CLI-behavior finding above, not a lost row. |
| RESIDUAL | **112,603** against the literal bulk-walk READ; **2** against the read-confirmed true value | See disposition below — NOT attributed to the write-loss window; a named, evidenced, different cause. |

**Residual disposition, gtm.** The literal bulk-walk `RESIDUAL(gtm)` (`126,160 − 13,557 =
112,603`) is fully explained, not unexplained: `revenium squads get <gtm-legacy-sid>` /
`squads timeline <gtm-legacy-sid>` / `metrics ai --squad-id <gtm-legacy-sid>` (no date
window on the first two; a wide window bracketing `requestTime` on the third) all agree
the row exists, with `created: 2026-08-20T15:53:10.878Z` (inside the stated query window)
and `totalTokenCount: 112601`. **The tokens are not lost — Revenium has the row; the
profile-wide bulk walk's date filter, keyed to `requestTime` rather than `created`,
simply does not surface it**, because this row's `requestTime`
(`2026-08-19T16:49:12Z`, the previous report's own timestamp under legacy's cumulative
delta model) predates the walk's `--from`. Once the row is counted via its
read-confirmed value, `126,160 − (112,601 + 13,557) = 2` — a small, separately-named
residual: `112,603` (local, raw cumulative subtraction) vs `112,601` (read side) differs
by 2 tokens, consistent with `hermes-report.sh:1752-1773`'s proportional delta-scaling
across input/output/cache buckets introducing sub-token rounding on each split. Neither
figure (`112,603` local nor `2` residual) is attributed to the write-loss window — both
sit deep in the CLEAN period, nowhere near `W`.

#### marketing

| Symbol | Value | Source |
|---|---|---|
| SUSPECT | **37,066** | `<mkt-B-sid>` spool total (1 record) — the profile's true boundary session, timestamped `2026-08-19T22:46:28Z`, inside W. |
| CLEAN | **91,625** = 37,216 + 17,745 + 36,664 | Three spool totals: `<mkt-C1-sid>` (2 records), `<mkt-C2-sid>` (1 record), `<mkt-C3-sid>` (2 records) — all strictly after W's close (`04:47`, `08:01`, `10:46` on 2026-08-20). No post-boundary legacy ledger growth on marketing. |
| READ | **91,625** | Bulk walk sum for `agent="Hermes-marketing"`, cross-confirmed exactly by `squads get` on each of the three sids (`37216 + 17745 + 36664 = 91625`). |
| READ_event | 91,625 | All three rows carry `event:`-prefixed `transactionId`s. |
| READ_legacy | 0 | No legacy-path rows for marketing in the window. |
| RESIDUAL | **0** | CLEAN and READ agree exactly — the expected shape for a session with no suspect local activity. |

`SUSPECT(marketing)` is reported here, never inside the residual: `37,066` tokens of
locally-reported, spool-corroborated activity for `<mkt-B-sid>` that Revenium's own
tenant discarded during the write-loss window (live-confirmed `404`, above) — the
quantified size of that one casualty, not a metering gap.

#### coder

| Symbol | Value | Source |
|---|---|---|
| SUSPECT | 0 | Boundary sits 29m27s after W's close; no post-boundary local evidence falls inside W. |
| CLEAN | **53,950** = 42,091 + 11,859 | `<coder-B1-sid>` spool (2 records, `total_tokens` `20879 + 21212 = 42091`) + `<coder-B2-sid>` spool (1 record, `11859`). No post-boundary legacy ledger growth on coder. |
| READ | **53,950** | Bulk walk sum for `agent="Hermes-coder"`, cross-confirmed exactly by `squads get <coder-B1-sid>` (`53950`, the combined trace total — `<coder-B2-sid>` is a same-instant subagent dispatch under the same trace). |
| READ_event | 53,950 | Both sessions carry `event:`-prefixed `transactionId`s. |
| READ_legacy | 0 | No legacy-path rows for coder in the window. |
| RESIDUAL | **0** | Agrees exactly — the expected shape for a session with no suspect local activity. |

#### playtester

Carried forward from 34-01's own tracer, not re-derived: CLEAN = READ = **13,634**
(`<sid-T>`), RESIDUAL = **0**. SUSPECT = **13,665** (`<sid-B>`, the profile's own true
boundary session — local evidence of a successfully-shipped call: an `API:` idempotency
ledger line plus its still-unpruned spool file, `total_tokens: 13665`, timestamped inside
W), reported separately, never inside the residual, exactly as 34-01's own tracer
demonstrated with a live `404` on `<sid-B>`.

#### cfo

| Symbol | Value | Source |
|---|---|---|
| SUSPECT | 0 | Boundary sits over 7h after W's close; no post-boundary local evidence falls inside W. |
| CLEAN | **221,231** | `<cfo-B-sid>` spool, 7 records, `total_tokens` summed = `221231`. No post-boundary legacy ledger growth on cfo. |
| READ | **221,231** | Bulk walk sum for `agent="Hermes-cfo"`, cross-confirmed exactly by `squads get <cfo-B-sid>` (`221231`). |
| READ_event | 221,231 | All 7 rows carry `event:`-prefixed `transactionId`s. |
| READ_legacy | 0 | No legacy-path rows for cfo in the window. |
| RESIDUAL | **0** | Agrees exactly. |

#### devops, qa, pm, community, lorekeeper

**No boundary yet (see the boundary table above) → empty by construction, not a row of
zeros.** Each of these five profiles' post-boundary reconciliation table has nothing to
fill: `devops`/`pm`/`qa`/`lorekeeper` because zero new sessions have occurred since the
flip for either path to claim, and `community` because it has not yet finished draining.
None contribute a SUSPECT, CLEAN, READ, or RESIDUAL figure to the fleet sums below — an
absent boundary is not a boundary at time zero, and reporting a zero here would
misrepresent "nothing observed yet" as "reconciled clean."

### Fleet totals — the sum of the ten tables above, and every residual's disposition (34-03 Task 3)

**Fleet totals are the stated sum of the ten per-profile summands above — shown here, not
just the result, so a reader can add the column themselves.** Five profiles contribute a
zero/empty summand (devops, qa, pm, community, lorekeeper — no boundary yet, per the
table above); the other five contribute the figures from their own tables.

| Symbol | gtm | marketing | coder | playtester | cfo | (5 empty) | **Fleet sum** |
|---|---:|---:|---:|---:|---:|---:|---:|
| SUSPECT | 0 | 37,066 | 0 | 13,665 | 0 | 0 | **50,731** |
| CLEAN | 126,160 | 91,625 | 53,950 | 13,634 | 221,231 | 0 | **506,600** |
| READ (literal bulk-walk) | 13,557 | 91,625 | 53,950 | 13,634 | 221,231 | 0 | **393,997** |
| READ_event | 13,557 | 91,625 | 53,950 | 13,634 | 221,231 | 0 | **393,997** |
| READ_legacy (literal bulk-walk) | 0 | 0 | 0 | 0 | 0 | 0 | **0** |
| RESIDUAL (literal bulk-walk) | 112,603 | 0 | 0 | 0 | 0 | 0 | **112,603** |

**Every non-zero residual, disposed one at a time — no third option, no rounding away.**
The fleet's entire literal-bulk-walk residual (`112,603`) is `gtm`'s own residual; every
other profile's residual is exactly `0`. It is given TWO named causes, not left
unexplained, and NEITHER is the write-loss window (`W`) — this delta happened, and was
recorded by Revenium, deep inside the CLEAN period, nowhere near `W`:

1. **`112,601` tokens — the `metrics ai --from`/`--to` requestTime-vs-created filtering
   behavior** (`## Findings` → the dedicated subsection above). The row
   (`<gtm-legacy-sid>-1056131`) is confirmed present on
   Revenium's read side — `squads get`, `squads timeline`, and a `--squad-id`-narrowed
   `metrics ai` call (no date filter, or a window bracketing `requestTime` instead of
   `created`) all return it, in full agreement with the local ledger's own recorded
   growth. **This is not a metering gap — the tokens were never lost, only omitted by
   this one aggregation method's date-filter semantics.** Once counted via its
   read-confirmed value, the corrected fleet `READ = 393,997 + 112,601 = 506,598`, and
   the corrected fleet `RESIDUAL = 506,600 − 506,598 = 2`.
2. **`2` tokens — delta-scaling rounding.** `112,603` (local, raw cumulative
   subtraction: `1,056,131 − 943,528`) vs `112,601` (read side, Revenium's own recorded
   value for the same delta report) differ by 2 tokens, consistent with
   `hermes-report.sh:1752-1773`'s proportional split of one delta across
   input/output/cache buckets introducing sub-token rounding on each split. This 2-token
   residual is what remains once cause 1 above is accounted for, and it is the fleet's
   own genuinely irreducible residual: **`2` tokens, unattributed to any window, named to
   its exact mechanism.**

**Zero tokens are unexplained — across the five profiles a reconciliation exists
for.** That scope qualifier is load-bearing and is not a formality: the other five
profiles (devops, qa, pm, community, lorekeeper) have no reconciliation at all, so they
contribute neither an explained nor an unexplained token, and this claim says nothing
whatever about them. Within the five, every non-zero residual — the full `112,603` under
the literal definition, or the `2` that remains once the CLI-behavior gap is corrected
for — carries a named cause pointing at specific evidence (a transaction ID, a timestamp,
a code citation), not a plausibility argument. No residual
anywhere in this reconciliation is attributed to the write-loss window, because none of
them fall inside it — the window's own effect is captured entirely by SUSPECT, below.

**SUSPECT — Revenium's own quantified data loss for this fleet across the cutover,
`50,731` tokens, reported as a number, not an excluded region.** This is `marketing`'s
`37,066` (`<mkt-B-sid>`, live `404`) plus `playtester`'s `13,665` (`<sid-B>`, live `404`,
established by 34-01). Both are locally-reported, spool-corroborated activity that
Revenium's own tenant discarded during the write-loss window. **This is not a metering
gap and was not chased as one** — it is stated plainly as the size of the outage's own
damage, and it is **explicitly excluded from RESIDUAL**: SUSPECT tokens never appear in
READ (Revenium genuinely has nothing for either session — confirmed by a live `404`, not
inferred), so they cannot create a residual against a total that never counted them.

**The gap claim and the double-count claim, stated separately, each with its own figures
and its own scope:**

- **No-gap claim:** across the five profiles with post-boundary activity, CLEAN local
  evidence (`506,600`) matches Revenium's own read-side total to within `2` tokens
  (`506,598` once the one confirmed CLI-behavior gap is corrected for by direct
  per-session query) — a rounding artifact with a named mechanism, not an unexplained
  shortfall. No tokens billed locally and reported cleanly (outside `W`) are missing from
  Revenium's own records.
- **No-double-count claim:** the `50,731` SUSPECT tokens (write-loss casualties) were
  billed locally exactly once and never landed in Revenium at all — confirmed by a live
  `404` on both sessions, not merely absent from a time-windowed query. They are counted
  in neither READ nor RESIDUAL; the only place they appear in this document's arithmetic
  is as SUSPECT, exactly once, per profile.

`## Verdict` was not rewritten by this task (34-03) beyond what 34-02 left there at the
time — the closing disposition of these figures, and the milestone's own verdict on
CUT-03, was 34-04's own work, and is now written into `## Verdict`'s first paragraph
above.

## Findings

### `<canary-sid>` — the one confirmed pre-existing overlap

**Profile:** `coder`. **Row counts:** 2 legacy, 4 event. **Token totals, re-derived live**
(not copied from `REQUIREMENTS.md`/`32-CANARY-EVIDENCE.md`): legacy-class sum (the two
`squads timeline` rows whose `id` carries no `event:` prefix) = **12,608** — exactly
matches the ledger's last-line value and the previously-recorded figure. Event-class sum
(the four `event:`-prefixed rows) = **24,688** — a figure `32-CANARY-EVIDENCE.md` §7
explicitly marked "not-run" and never previously computed; this document is its first
live confirmation. Combined = **37,296**, matching `squads get`'s own top-level
`totalTokens` exactly, zero residual. **The two figures are not double-counting the same
tokens twice over**: the underlying real input+output usage (12,608) is identical whether
read from the legacy path's `state.db`-derived split or summed from the event path's own
four per-call records; the event side's larger total (24,688) is legitimate
cache-inclusive per-call accounting for a 4-turn tool-use loop (turns 2 and 3 re-process
5,997 and 6,083 cached context tokens respectively — visible in the still-unpruned spool
file, which corroborates the read side byte-for-byte). **Claim timestamp:**
`2026-08-18T03:04:27Z` (dual-ledger warn line; the owner file's own mtime matches to the
sub-second, corroborating rather than substituting). **Confirmed pre-existing:** the
canary's own activity (`2026-08-17T21:31:01Z`–`21:33:28Z`) and its claim
(`2026-08-18T03:04:27Z`) both predate the fleet's cutover flip
(`2026-08-19T21:12Z`–`21:40Z`) by more than a day — this is a date comparison against
live-confirmed timestamps, not an assertion. **Named cause:** the D-09 partition's
ordering-dependent defect (`32-CANARY-EVIDENCE.md` §2) — a session whose first
event-shipper pass preceded its first legacy pass, before the mutual-ownership protocol
existed to prevent it.

### `<qa-dual-sid-1>` — NOT an overlap (ownership takeover)

**Profile:** `qa`. **Row counts:** 0 legacy (no `HERMES:` line, ever — confirmed by
direct grep, not inferred from the `comm -12` miss alone), 1 event
(`squads get` confirms `transactionCount: 1`). **Token totals:** legacy — no such line,
the absence is the expected finding, not a failed read. Event — **13,914** (read side,
matches the still-unpruned spool file's own `total_tokens` exactly: `input_tokens=13843,
output_tokens=21, cache_read_tokens=50`). The owner file's recorded floor (`13864`) is 50
tokens lower than this — exactly the call's `cache_read_tokens` value — a small, separate
finding about `hermes-report.sh`'s `state.db`-derived `total_tokens` not including
cache-read tokens the same way the event path's own shipped total does; it does not
change the "zero legacy rows, not an overlap" conclusion. **Claim/takeover timestamp:**
`2026-08-18T21:21:26Z` (log line, strong provenance). **Named cause:**
`_takeover_session_owner` (quick-260818-0in/MODE-01) — legacy took over ownership from an
event-owned record while the fleet ran pre-cutover `shadow` mode, but its own growth
guard never fired because legacy had nothing new to bill; the session was billed exactly
once, by the event path.

### `<qa-dual-sid-2>` — NOT an overlap (ownership takeover)

**Profile:** `qa`. **Row counts:** 0 legacy, 1 event. **Token totals:** legacy — no such
line. Event — **14,028** (read side; spool: `input_tokens=13893, output_tokens=135,
cache_read_tokens=0` — the owner file's floor, `14028`, matches exactly since this call
has no cache-read component). **Claim/takeover timestamp:** `2026-08-18T21:21:26Z` — the
same cron tick as `<qa-dual-sid-1>`, both takeovers landing together. **Named cause:**
identical to `<qa-dual-sid-1>`.

### `<cfo-dual-sid-1>` — NOT an overlap (ownership takeover)

**Profile:** `cfo`. **Row counts:** 0 legacy, 1 event. **Token totals:** legacy — no such
line. Event — **13,015** (read side; spool: `input_tokens=13009, output_tokens=6,
cache_read_tokens=0` — floor `13015` matches exactly). **Claim/takeover timestamp:**
`2026-08-18T16:51:36Z`. **Named cause:** identical mechanism to the two `qa` sessions,
independently confirmed on a third profile.

### `metrics ai` transient 502, one occurrence (34-03 Task 2)

**Timestamp:** `2026-08-20T16:30:03Z` (first attempt of the fleet-wide bulk walk).
**Exact call:** `revenium metrics ai --from 2026-08-20T01:24:01Z --to
2026-08-20T23:59:59Z --output json --page-size 200 --page 0`. **Result:** `{"error":
"Revenium API error. Try again later or contact support.", "exit_code": 1, "status":
502}`. Retried ~30 seconds later with the identical call — succeeded, returned the same
first page later confirmed against the walk's own cross-checks (`squads get` sums match
the bulk-walk sums exactly for every session verified). Recorded per this phase's own
discipline (the write-loss outage's root cause is unknown and could recur, so any 5xx is
a finding in its own right, not a transient to retry away silently) — no further
occurrence in the remaining 14 pages of the same walk.

### `metrics ai --from`/`--to` filters by `requestTime`, not `created` — a CLI-behavior finding with direct arithmetic consequences (34-03 Task 2)

**What was found.** A profile-wide `metrics ai` walk windowed strictly after the
write-loss window's close (`--from 2026-08-20T01:24:01Z`) silently omitted a legacy
delta-report row (`<gtm-legacy-sid>`, `112,601` tokens) whose own `created` timestamp
(`2026-08-20T15:53:10.878Z` — when Revenium actually recorded it) sits **comfortably
inside** the queried window. The row is not missing from Revenium: `squads get
<gtm-legacy-sid>`, `squads timeline <gtm-legacy-sid>`, and a `--squad-id`-narrowed
`metrics ai` call with a window wide enough to bracket its `requestTime`
(`2026-08-19T16:49:12Z`) all return it, in full agreement on every field.

**Bisection, live, both directions:**
- `--from 2026-08-20T15:50:00Z --to 2026-08-20T15:56:00Z` (brackets `created`, excludes
  `requestTime`), with `--squad-id <gtm-legacy-sid>` narrowing to the exact session: **0
  rows.**
- `--from 2026-08-19T16:45:00Z --to 2026-08-19T16:55:00Z` (brackets `requestTime`,
  excludes `created`), same `--squad-id`: **1 row** — the same row, full detail,
  `created: 2026-08-20T15:53:10.878Z`, `requestTime: 2026-08-19T16:49:12Z`,
  `totalTokenCount: 112601`.

**Why this happens, and why it matters beyond this one row.** For an event-path
completion, `requestTime` and `created` sit seconds to minutes apart — the CLI ships the
call and Revenium ingests it almost immediately — so the choice of filter field never
mattered for any event-path session this phase measured. For a LEGACY delta-report row,
`requestTime` is populated as the **start of the delta period** (the previous report's
own timestamp, per `hermes-report.sh`'s delta computation), which for a slow-ticking or
long-running session can predate the row's `created` by hours, days, or weeks — here,
almost a full day (`2026-08-19T16:49:12Z` vs `2026-08-20T15:53:10.878Z`). **Any
profile-wide bulk walk `--from`'d strictly after the write-loss window will silently
exclude a legacy delta row whose delta period began before that cutoff, even though the
row was actually reported — and would actually be counted as CLEAN local evidence —
safely inside the window.** This is a genuine gap in the bulk-walk aggregation method,
not a token that Revenium lost; it is documented here, quantified (one row, `112,601`
tokens, `gtm` only, among the five profiles this plan established a boundary for) rather
than silently absorbed, per criterion 6. `## Results` → gtm's own table shows both the
literal bulk-walk figure and the read-confirmed corrected figure side by side, with the
residual this finding explains named rather than left as "unexplained."

**Scope of this finding.** Checked directly against all five boundary-established
profiles' local evidence (the only systematic way to find an instance of this): exactly
one row, on one profile (`gtm`), was affected — the only post-boundary legacy delta
report among the five. Whether this is the only such case fleet-wide, or whether other
profiles' own future legacy delta reports (once gtm's remaining 2 pending sessions or
community's 1 pending session eventually report) will exhibit the same gap, was not
determined beyond this one confirmed instance — a single occurrence supports "this is a
real, reproducible CLI/API behavior," not "this is the full extent of its effect."

## Reproducing this measurement

Every command below is read-only and generically parameterised — substitute a real
profile name, session id, or ISO-8601 timestamp for the placeholder and it runs as
written. Placeholders in this section are single hyphen-free tokens (`<profile>`, `<sid>`,
`<from>`, `<to>`, `<N>`), never the hyphenated redaction placeholders used elsewhere in
this document (`<canary-sid>`, `<gtm-B-sid>`, etc.) — those resolve only via
`34-EVIDENCE.md`'s map, per this phase's own naming convention.

**Boundary derivation (per profile):**
```bash
ssh <fleethost> \
  'grep -n "Reported: sid=.*api_request_id=" \
     <profile-state-dir>/revenium-metering.log | head -1'
ssh <fleethost> \
  'grep "^HERMES:<sid>:" \
     <profile-state-dir>/revenium-hermes.ledger | wc -l'
```
(`<profile-state-dir>` is the same redaction placeholder used in `## Results` → "Tracer" —
resolve it via `34-EVIDENCE.md`'s map, not by hand. `<fleethost>` is deliberately
hyphen-free, matching the other generic template parameters above — the hyphen is what the
map-coverage gate uses to decide a token needs its own map row, and a substitutable
template parameter
must never carry one.)

**Verb family — the `owners/` two-line sweep, per profile:**
```bash
d=~/.hermes/profiles/<profile>/state/revenium/owners
for f in "$d"/*; do n=$(wc -l < "$f"); [ "$n" -ge 2 ] && echo "DUAL $(basename "$f") $(tr '\n' '|' < "$f")"; done
```
A `>= 2`-line file is a CANDIDATE, never a confirmed overlap by itself — the two-line shape
is also produced by `_takeover_session_owner`, a double-bill PREVENTION mechanism, not
evidence one occurred. Disambiguate with the ledger `comm -12` intersection below and the
log-line check before concluding anything.

**Verb family — the two-ledger sid extraction and `comm -12` intersection (the check on
the checker; the raw evidence the `owners/` sweep alone cannot supply):**
```bash
grep -oE '^HERMES:[^:]+' revenium-hermes.ledger | sed 's/^HERMES://' | sort -u > /tmp/legacy_sids
awk -F'|' '{print $2}' revenium-api-events.ledger | sort -u > /tmp/event_sids
comm -12 /tmp/legacy_sids /tmp/event_sids
```

**Disambiguating a signal-1-only hit: is it a genuine dual-ledger claim, or an ownership
takeover?**
```bash
grep "<sid>" revenium-metering.log | grep -i "ownership taken over\|dual-ledger"
grep "^HERMES:<sid>:" revenium-hermes.ledger   # empty => never legacy-billed, not an overlap
```

**Verb family — the legacy last-line-per-sid token read:**
```bash
# CUMULATIVE, NOT ADDITIVE: the 3rd colon-delimited field is this sid's RUNNING TOTAL as of
# THIS report, never a delta. Summing every line for a sid multiply-counts its early
# growth — always take the LAST line only, exactly as below. This warning travels with the
# command itself: a reader who copies only the command, not the surrounding prose, must
# still see it.
grep "^HERMES:<sid>:" revenium-hermes.ledger | tail -1 | cut -d: -f3
```

**Verb family — the paged `revenium metrics ai` walk:**
```bash
revenium metrics ai --from <from> --to <to> --output json --page-size 200 --page <N>
```
This verb has **no server-side filter** — request `--page-size 200`, walk `--page 0, 1, 2,
...` (the server's actual page size is 100 regardless of the requested value — a short page,
under 100 rows, is the walk's own termination signal), and filter the returned array
**client-side** on `agent == "Hermes-<profile>"` (or on `transactionId`/`id` starting with
`event:` to isolate the event path from the legacy path). `--from`/`--to` filter on each
row's own `requestTime`, **not** `created` — for a legacy delta-report row, `requestTime` is
the delta period's own start and can predate `created` by hours to weeks, so a bulk walk
windowed strictly after a cutoff can silently omit a row genuinely reported inside that
window (see `## Known limitations and exclusions` and `## Findings`). Cross-confirm any
profile-level sum this walk produces against `squads get` for that profile's own session
ids before trusting it.

**Verb family — the `revenium squads get` / `revenium squads timeline` pair:**
```bash
revenium squads get <sid> --output json       # top-level totalTokens, squadName, agents[]
revenium squads timeline <sid> --output json  # per-row events; classify id by event: prefix
```
Rows returned by `squads timeline` are ordered by their **own** `startTime` field (mirroring
`requestTime`/`created` on `metrics ai`) — **never** by array position. A trace with more
than one event must be re-sorted on its own timestamp field before any "first
event"/"last event" claim is made from it; do not assume the API's return order is
chronological order.

**Overlap-detector integrity, per profile:**
```bash
sha256sum ~/.hermes/skills/revenium/scripts/{hermes-report,api-event-report,common,prune-markers}.sh
ls ~/.hermes/profiles/<profile>/state/revenium/owners/ 2>&1
test -s ~/.hermes/profiles/<profile>/state/revenium/revenium-api-events.ledger && echo non-empty
grep 'prune:' ~/.hermes/profiles/<profile>/state/revenium/revenium-metering.log
```

Every command above is a read verb. Reproducing this measurement requires no write of any
kind — no `revenium meter`, no `jobs create`/`outcome`, no `guardrails` mutation, and no
write to any profile's `env`, `config.json`, `drain-status.json`, `owners/` record, or
ledger.

### Query ledger (34-01 + 34-02 + 34-03 + 34-04)

Every `revenium` CLI read-verb call issued by any plan in this phase, in the order issued,
so the method — including what returned empty and what errored — is auditable rather than
only the queries that produced a usable result. Local `ssh`-only reads (the boundary
derivation, the `owners/` sweeps, the ledger `comm -12` intersections, the `env`/
`drain-status.json` re-reads) are not HTTP requests against Revenium and are excluded from
this table; they are fully logged in `34-EVIDENCE.md` instead.

| # | Plan/Task | Command | Window / scope | Result | Outcome |
|---|---|---|---|---|---|
| 1 | 34-01 Task 1 | `squads get <sid-T>` | point lookup | `totalTokens: 13634` | success |
| 2 | 34-01 Task 1 | `squads timeline <sid-T>` | point lookup | 1 event | success |
| 3 | 34-01 Task 1 | `metrics ai --from 2026-08-20T01:24:01Z --to 2026-08-20T02:10:00Z --page-size 200 --page 0..3` | `01:24:01Z`–`02:10:00Z` | 256 rows total, 1 Hermes-playtester | success |
| 4 | 34-01 Task 1 | `squads get <sid-B>` | point lookup | — | **error — 404 Resource not found** (the write-loss casualty itself, not a query defect) |
| 5 | 34-02 Task 2 | `squads get <canary-sid>` | point lookup | `totalTokens: 37296` | success |
| 6 | 34-02 Task 2 | `squads timeline <canary-sid>` | point lookup | 6 events | success |
| 7 | 34-02 Task 2 | `squads get <qa-dual-sid-1>` | point lookup | `totalTokens: 13914` | success |
| 8 | 34-02 Task 2 | `squads get <qa-dual-sid-2>` | point lookup | `totalTokens: 14028` | success |
| 9 | 34-02 Task 2 | `squads get <cfo-dual-sid-1>` | point lookup | `totalTokens: 13015` | success |
| 10 | 34-03 Task 1 | `squads get <mkt-B-sid>` | point lookup | — | **error — 404 Resource not found** (marketing's own write-loss casualty) |
| 11 | 34-03 Task 2 | `metrics ai --from 2026-08-20T01:24:01Z --to 2026-08-20T23:59:59Z --page-size 200 --page 0` (first attempt) | `01:24:01Z`–`23:59:59Z` | — | **error — HTTP 502**, retried ~30s later |
| 12 | 34-03 Task 2 | `metrics ai --from 2026-08-20T01:24:01Z --to 2026-08-20T23:59:59Z --page-size 200 --page 0..14` (retry, full walk) | `01:24:01Z`–`23:59:59Z` | 1,455 rows total (14×100 + 55), 18 Hermes-owned | success |
| 13 | 34-03 Task 2 | `squads get <gtm-B-sid>` | point lookup | `totalTokens: 13557` | success |
| 14 | 34-03 Task 2 | `squads get <mkt-C1-sid>` | point lookup | `totalTokens: 37216` | success |
| 15 | 34-03 Task 2 | `squads get <mkt-C2-sid>` | point lookup | `totalTokens: 17745` | success |
| 16 | 34-03 Task 2 | `squads get <mkt-C3-sid>` | point lookup | `totalTokens: 36664` | success |
| 17 | 34-03 Task 2 | `squads get <coder-B1-sid>` | point lookup | `totalTokens: 53950` | success |
| 18 | 34-03 Task 2 | `squads get <cfo-B-sid>` | point lookup | `totalTokens: 221231` | success |
| 19 | 34-03 Task 2 | `metrics ai --from 2026-08-20T15:50:00Z --to 2026-08-20T15:56:00Z --page-size 200 --page 0` (broad, no `--squad-id`) | `15:50:00Z`–`15:56:00Z` | 0 rows | success, **empty** |
| 20 | 34-03 Task 2 | `metrics ai --from 2026-08-20T15:50:00Z --to 2026-08-20T15:56:00Z --squad-id <gtm-legacy-sid> --page-size 200 --page 0` | `15:50:00Z`–`15:56:00Z`, narrowed | 0 rows | success, **empty** (brackets `created`, excludes `requestTime`) |
| 21 | 34-03 Task 2 | `metrics ai --from 2026-08-19T16:45:00Z --to 2026-08-19T16:55:00Z --squad-id <gtm-legacy-sid> --page-size 200 --page 0` | `2026-08-19T16:45:00Z`–`16:55:00Z`, narrowed | 1 row, `totalTokenCount: 112601` | success (brackets `requestTime`, resolves the bisection) |
| 22 | 34-03 Task 2 | `squads get <gtm-legacy-sid>` | point lookup, no date window | `totalTokens: 225606` | success (corroboration) |
| 23 | 34-03 Task 2 | `squads timeline <gtm-legacy-sid>` | point lookup, no date window | 2 events | success (corroboration) |
| 24 | 34-04 Task 1 | `squads get <sid-T>` (re-query, independent confirmation) | point lookup | `totalTokens: 13634` — **identical to row 1** | success |

24 distinct `revenium` CLI read-verb invocations across all four plans. Rows 3 and 12 each
fan out into multiple HTTP page requests (row 3 = 4 pages, row 12 = 15 pages) — 41 total
HTTP requests across all 24 rows (24 − 2 single-request-equivalents + 4 + 15). **Two
errors, both recorded rather than retried away silently:** rows 4 and 10 are this phase's
own quantified write-loss evidence (both live `404`s on sessions with local evidence of a
successful ship), not query defects; row 11's 502 was a transient server error that
succeeded on an identical retry ~30 seconds later (`## Findings` → "`metrics ai` transient
502"). **Two empty results, both explained, neither treated as confirmation of anything on
their own:** rows 19 and 20 are the two halves of the `requestTime`-vs-`created` bisection
that produced this phase's own CLI-behavior finding — an empty result from a
`created`-bracketing window is the expected, diagnostic outcome that row 21's
`requestTime`-bracketing window then resolves, not an unexplained gap.

## Independent confirmation

**Second run of the two local signals from 34-02, this document's own re-run of its own
method — 2026-08-20T17:09:51Z, 1h15m02s after the first run's start
(`2026-08-20T15:54:49Z`).** Same two signals (the `owners/` `>=2`-line sweep, the raw
ledger `comm -12` intersection) re-issued verbatim across all ten profiles, over the same
read-only SSH access used throughout this phase.

| Profile | Owners total (1st → 2nd) | 2-line hits (1st → 2nd) | Legacy sid count (1st → 2nd) | Event sid count (1st → 2nd) | `comm -12` intersection (1st → 2nd) |
|---|---|---|---|---|---|
| gtm | 57 → 57 | 0 → 0 | 56 → 56 | 1 → 1 | 0 → 0 |
| marketing | 235 → 236 (+1) | 0 → 0 | 231 → 231 | 4 → 5 (+1) | 0 → 0 |
| devops | UNDETERMINED (dir absent, both runs) | — | 1939 → 1939 | 0 → 0 | 0 → 0 (trivial) |
| qa | 22 → 22 | 2 → 2 (same two sids) | 20 → 20 | 2 → 2 | 0 → 0 |
| coder | 227 → 227 | 1 → 1 (the canary) | 225 → 225 | 3 → 3 | 1 → 1 (the canary) |
| playtester | 7 → 7 | 0 → 0 | 5 → 5 | 2 → 2 | 0 → 0 |
| cfo | 42 → 42 | 1 → 1 | 40 → 40 | 2 → 2 | 0 → 0 |
| pm | UNDETERMINED (dir absent, both runs) | — | 25 → 25 | 0 → 0 | 0 → 0 (trivial) |
| community | 3 → 3 | 0 → 0 | 3 → 3 | 0 → 0 | 0 → 0 |
| lorekeeper | 33 → 33 | 0 → 0 | 33 → 33 | 0 → 0 | 0 → 0 |

**Result: the hit set is IDENTICAL between the two runs, fleet-wide, on every signal.** The
sole nonzero `comm -12` intersection is still exactly one session (the canary, `coder`),
unchanged. The two-line-owner-record count is still exactly four fleet-wide (the canary
plus the three confirmed ownership-takeover non-overlaps), unchanged, on the same four
sids — `qa`'s two and `cfo`'s one are the identical sids re-confirmed, not a new pair.
**Only one profile's swept totals grew at all between the two runs: `marketing` gained one
`owners/` entry and one distinct event sid** (consistent with marketing's own ongoing
post-cutover event-path traffic, the same profile whose post-boundary CLEAN table in
`## Results` already shows multiple sessions), **and that growth produced neither a new
`comm -12` hit nor a new two-line owner record.** A growing corpus with an unchanged hit
set is stronger evidence than an unchanged corpus would have been: the sweep is not
returning the same answer only because nothing happened between runs — new activity
genuinely occurred, and it still did not surface a second overlap. The hit set did not
change, so there is nothing to add to `## Findings` from this re-run.

**One representative session's read-side total, re-queried and compared.** `<sid-T>`
(playtester's own clean tracer session, `## Results` → "Tracer"): first queried
`2026-08-20T15:28Z`, `totalTokens: 13634`. Re-queried this task, `2026-08-20T17:10:10Z`
(1h42m10s later): `totalTokens: 13634` — **identical, no difference to explain.** A
completed, closed session's read-side total does not drift once Revenium has durably
recorded it; this is the expected result for a CLEAN session outside the write-loss
window, not a coincidence.

## Verified against

Date: 2026-08-20. Method (34-01, tracer + integrity): read-only SSH access to the fleet
host (`revenium-metering.log`, `revenium-hermes.ledger`, `revenium-api-events.ledger`, the
`api-events/` spool directory, `env` file mtimes, `owners/` directories, deployed script
`sha256sum`s) plus the `revenium` CLI's read verbs (`squads get`, `squads timeline`,
`metrics ai`) against the live Revenium dev tenant. Population for the tracer: one
profile (`playtester`) and two of its sessions. Population for the integrity checks: all
ten fleet profiles.

**Method (34-02, overlap enumeration), same read-only discipline, re-confirmed
connectivity live (`2026-08-20T15:54:49Z`, same host, `<host-name>`):** the same
SSH/`revenium` read surface, extended with `comm -12` (raw ledger cross-check) and
per-sid `grep` drill-downs. Population: all ten fleet profiles' full ledger/owner-record
history (no time-window restriction — see `## Results` for the swept totals), plus
`squads get`/`squads timeline` re-derivation for all four candidate sessions found by any
signal.

**Method (34-03, boundaries and reconciliation arithmetic), same read-only discipline,
re-confirmed connectivity live (`2026-08-20T16:27:51Z`, same host,
`<host-name>`):** the same SSH/`revenium` read surface, extended with per-profile
`env`-mtime and `drain-status.json` re-reads, an `awk`-filtered legacy-ledger sweep
keyed on each profile's own boundary epoch, per-session spool-file summation, a 15-page
`metrics ai` bulk walk (1,455 rows, `--from`/`--to` both on the local workstation and
cross-confirmed against the fleet host's own CLI installation, same tenant), and a live
bisection of the `metrics ai` date-filter's field semantics (`--squad-id`-narrowed calls
with disjoint windows). Population: the five profiles that had reached their own boundary
at this document's writing (gtm, marketing, coder, playtester, cfo) plus a full
five-profile "not yet reached" determination (devops, qa, pm, community, lorekeeper) —
every ten profiles' `env` flip and `drain-status.json` re-read live, not sampled.

**Method (34-04, independent confirmation, reproduction templates, redaction proof, and
verdict), same read-only discipline, re-confirmed connectivity live
(`2026-08-20T17:09:40Z`, same host, `<host-name>`):** the same SSH/`revenium` read
surface, re-issued rather than extended — a second run of 34-02's own owners/`comm -12`
sweep across all ten profiles, one `squads get` re-query of a representative closed
session, and the three-check redaction audit below. No new command shape was needed for
this plan's own confirmation work. Observation window for this document's own live
queries, earliest precisely-timestamped command to last: `2026-08-20T15:28Z` (34-01's
first `squads get`, its own read-side visibility check a few minutes earlier is recorded
only as `~15:2xZ` in `34-EVIDENCE.md` and is not used here to avoid false precision)
through `2026-08-20T17:10:16Z` (34-04's own last `squads get`) — roughly 1h42m spanning
all four plans' own live queries against the fleet host and the Revenium dev tenant.
Population: all ten fleet profiles, re-swept in full a second time by 34-04 Task 1; one
representative session re-queried.

**Redaction proof (34-04 Task 2) — three independent checks, not one regex.** (1)
Map completeness: every placeholder appearing in this document was enumerated and checked
against `34-EVIDENCE.md`'s map; two gaps were found and closed before this section was
written — a template parameter (`<fleethost>`, this document's `## Reproducing this
measurement` SSH target) was previously spelled with a hyphen, making it indistinguishable
from a redacted identifier awaiting a map row, and was renamed to the hyphen-free form
this phase's own naming convention requires; and that same section quoted the fleet host's
own per-profile state directory in full rather than using the `<profile-state-dir>`
placeholder already defined for exactly that path, and was corrected to use it. Every
other placeholder had exactly one map row; none was dead. (2) The bijection, checked one
entry at a time: for all 18 placeholders mapped AT THE TIME THIS CHECK RAN, the raw
value's verbatim absence and the placeholder's presence were confirmed independently, and
both held for all 18 — recorded per-entry in `34-EVIDENCE.md`. **Why this says 18 while
the closing inventory says 19, which is not a contradiction:** Check 3 below had not yet
run, and it is Check 3 that minted the 19th placeholder (`<host-name>`) by redacting a
leak this check could not have covered, because the leak was still un-redacted and
un-mapped while this check was executing. The 19th was verified separately after Check 3
redacted it — its raw value is verbatim-absent from this document and its placeholder
appears in it — so the bijection now holds 19/19 in both directions, but this check as
executed covered 18, and it is reported at the count it actually covered rather than
back-dated to the final total. (3) The sweep for identifier shapes outside the regex
gate's four patterns found one genuine leak: the fleet host's own hostname, quoted raw,
twice, in this section's own 34-02/34-03 method paragraphs above — not an IPv4 address, an
SSH key filename, a login string, or a session-id shape, so the file-wide regex gate never
saw it, exactly the shape of gap that gate is not sufficient to close on its own. Redacted
behind a new placeholder, `<host-name>`, with its own map row added to `34-EVIDENCE.md`.
Two further hits from the same sweep — `quick-260817-tfe` and
`quick-260818-0in` — were evaluated and retained: both are this project's own internal
change-ticket labels for prior code changes (paired with the public GitHub PR numbers that
cite them), not a fleet session, trace, host, or job identifier; they identify a code
change, not a person, session, or machine, and fall outside every category this document's
redaction covers. No other candidate token — hex strings, `cron_`-prefixed tokens,
UUID-shaped strings, `api_request_id`-shaped strings, standalone squad ids — was found
raw anywhere in this file outside an already-redacted placeholder. Full per-entry results
for all three checks are in `34-EVIDENCE.md`; this paragraph states only that the checks
ran, what they covered, and what they found, per this task's own instruction not to
duplicate the evidence artifact's detail here.

**Deliberately omitted from this file, on every page, in every task:** the fleet host's
address AND its own hostname, the SSH key filename, every remote login string, and every
raw session, trace, `api_request_id`, and composite `transactionId` — including the three
confirmed-non-overlap sessions and the canary's own event-side identifiers, quoted above
only via placeholder or in aggregate (profile + count + date + token figures), never by
raw id. These live only in this repository's local, gitignored evidence artifact
(`.planning/phases/34-transition-reconciliation/34-EVIDENCE.md`), resolved via the stable
placeholders used above (`<sid-B>`, `<hash-B>`, `<sid-T>`, `<hash-T>`, `<canary-sid>`,
`<qa-dual-sid-1>`, `<qa-dual-sid-2>`, `<cfo-dual-sid-1>`, `<profile-state-dir>`,
`<gtm-B-sid>`, `<gtm-legacy-sid>`, `<mkt-B-sid>`, `<mkt-C1-sid>`, `<mkt-C2-sid>`,
`<mkt-C3-sid>`, `<coder-B1-sid>`, `<coder-B2-sid>`, `<cfo-B-sid>`, `<host-name>`) — the
three qa/cfo placeholders 34-01 reserved but did not yet dereference are used throughout
`## Results` and `## Findings` above; the nine 34-03 placeholders and `<host-name>` are new
to this document as of this plan. This list (19 redaction placeholders, all hyphenated per
convention) was itself verified against the document above, not merely asserted — see the
"Redaction proof" paragraph and `34-EVIDENCE.md` for the checked results.

**Retained, deliberately:** profile role labels (`playtester`, `coder`, `qa`, `cfo`,
`gtm`, etc.), every aggregate figure (token counts, timestamps, hash-match verdicts, row
counts, swept totals), the deploy commit `f13bdf6`, and the two internal change-ticket
labels `quick-260817-tfe` / `quick-260818-0in` — none of these are session, trace, host,
or job identifiers (the deploy commit and change-ticket labels identify a code change, not
a machine or a session), and the per-profile reading throughout this document depends on
them.
