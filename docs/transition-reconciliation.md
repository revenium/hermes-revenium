# Cutover Transition Reconciliation — Method Proven End-to-End, THREE Additional Pre-Cutover Overlaps Found Beyond the Canary, Fleet-Wide Enumeration Pending

## Verdict

**Provisional — this section is finalized by 34-04.** This document's structural shape is
now final (all nine sections below) and its underlying method is proven end-to-end on one
profile and one session, but the fleet-wide claims CUT-03 asks for — every dual-billed
session enumerated, all ten profiles' boundaries and arithmetic, the closing verdict — are
not yet written. What follows is what this plan (34-01) actually closes:

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

**Not yet answered by this document:** the ten-profile boundary-plus-arithmetic
reconciliation (34-03), and the final verdict with its independent-confirmation re-runs
(34-04). The fleet-wide overlap enumeration (34-02) is now CLOSED — see above and
`## Findings`. Every section below that 34-03/34-04 own carries a single italic
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

*Per-profile boundaries and reconciliation arithmetic (34-03), and independent
confirmation re-runs (34-04), are filled in by those plans.*

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

**Overlap-detector integrity, per profile:**
```bash
sha256sum ~/.hermes/skills/revenium/scripts/{hermes-report,api-event-report,common,prune-markers}.sh
ls ~/.hermes/profiles/<profile>/state/revenium/owners/ 2>&1
test -s ~/.hermes/profiles/<profile>/state/revenium/revenium-api-events.ledger && echo non-empty
grep 'prune:' ~/.hermes/profiles/<profile>/state/revenium/revenium-metering.log
```

**Overlap enumeration, three independent signals, per profile (34-02):**
```bash
# Signal 1: owners/ two-line sweep
d=~/.hermes/profiles/<profile>/state/revenium/owners
for f in "$d"/*; do n=$(wc -l < "$f"); [ "$n" -ge 2 ] && echo "DUAL $(basename "$f") $(tr '\n' '|' < "$f")"; done

# Signal 2: raw ledger comm -12 cross-check (the check on the checker)
grep -oE '^HERMES:[^:]+' revenium-hermes.ledger | sed 's/^HERMES://' | sort -u > /tmp/legacy_sids
awk -F'|' '{print $2}' revenium-api-events.ledger | sort -u > /tmp/event_sids
comm -12 /tmp/legacy_sids /tmp/event_sids

# Signal 3: the dual-ledger warn line, corroboration only
grep -c "dual-ledger session claimed for the legacy path" revenium-metering.log

# Disambiguating a signal-1-only hit: is it a genuine dual-ledger claim, or a takeover?
grep "<sid>" revenium-metering.log | grep -i "ownership taken over\|dual-ledger"
grep "^HERMES:<sid>:" revenium-hermes.ledger   # empty => never legacy-billed, not an overlap
```

*A replayable template per verb family this whole phase used is 34-04 Task 1's own
acceptance criterion — the above covers only what Task 1/2 of this plan used.*

## Independent confirmation

*Filled in by 34-04 — re-runs of this plan's own queries, plus the fleet-wide sweeps' own
independent-confirmation rounds.*

## Verified against

Date: 2026-08-20. Method (34-01, tracer + integrity): read-only SSH access to the fleet
host (`revenium-metering.log`, `revenium-hermes.ledger`, `revenium-api-events.ledger`, the
`api-events/` spool directory, `env` file mtimes, `owners/` directories, deployed script
`sha256sum`s) plus the `revenium` CLI's read verbs (`squads get`, `squads timeline`,
`metrics ai`) against the live Revenium dev tenant. Population for the tracer: one
profile (`playtester`) and two of its sessions. Population for the integrity checks: all
ten fleet profiles.

**Method (34-02, overlap enumeration), same read-only discipline, re-confirmed
connectivity live (`2026-08-20T15:54:49Z`, same host, `tableforone-agents`):** the same
SSH/`revenium` read surface, extended with `comm -12` (raw ledger cross-check) and
per-sid `grep` drill-downs. Population: all ten fleet profiles' full ledger/owner-record
history (no time-window restriction — see `## Results` for the swept totals), plus
`squads get`/`squads timeline` re-derivation for all four candidate sessions found by any
signal.

**Deliberately omitted from this file, on every page, in every task:** the fleet host's
address, the SSH key filename, every remote login string, and every raw session, trace,
`api_request_id`, and composite `transactionId` — including the three confirmed-non-overlap
sessions and the canary's own event-side identifiers, quoted above only via placeholder or
in aggregate (profile + count + date + token figures), never by raw id. These live only in
this repository's local, gitignored evidence artifact
(`.planning/phases/34-transition-reconciliation/34-EVIDENCE.md`), resolved via the stable
placeholders used above (`<sid-B>`, `<hash-B>`, `<sid-T>`, `<hash-T>`, `<canary-sid>`,
`<qa-dual-sid-1>`, `<qa-dual-sid-2>`, `<cfo-dual-sid-1>`, `<profile-state-dir>`) — the
three qa/cfo placeholders 34-01 reserved but did not yet dereference are now used
throughout `## Results` and `## Findings` above.

**Retained, deliberately:** profile role labels (`playtester`, `coder`, `qa`, `cfo`,
`gtm`, etc.), every aggregate figure (token counts, timestamps, hash-match verdicts, row
counts, swept totals), and the deploy commit `f13bdf6` — none of these are session,
trace, or host identifiers, and the per-profile reading throughout this document depends
on them.
