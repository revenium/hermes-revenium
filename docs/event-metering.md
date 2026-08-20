# Event-Driven Completion Metering

This is the document to have open while running the shadow, canary, and
fleet stages of the Phase 32 rollout — and the one a future reader finds
when the planning tree that designed it is gone. It covers what changed,
how to tell the two metering paths apart on a Revenium row, the switches
that control the rollout, the drain gate that protects it, the known
differences between the two paths, and what rollback can and cannot undo.

## What changed

Completion metering can now be produced by the API call that incurred it —
`post_api_request`, a hook fired once per model call — rather than
reconstructed a minute later from `state.db`'s per-session summary
counters. A new `revenium-classifier` plugin hook spools one record per
call to disk; a new cron stage (`api-event-report.sh`) enriches and ships
those records via `revenium meter completion`.

**Only completion metering moved.** Everything else about the cron
pipeline is unchanged:

- **Agentic jobs stay marker-driven, on the cron.** `post_api_request`
  carries no job lifecycle signal — nothing to move them onto. The
  `revenium-jobs.ledger` and its created-before-outcome gate are untouched.
- **Tool-event metering is untouched.** It was already event-shaped
  (`post_tool_call.sh` → `tool-event-report.sh`); this phase copied that
  pattern, not changed it.
- **Guardrail polling keeps its job.** `guardrail-check.sh` was not
  modified by any plan in this phase.

**This is not "delete the cron."** `cron.sh` grew a fifth metering stage
and a sixth gate stage; the four stages that existed before this phase all
still run, every tick, unchanged.

## The two paths, and how to tell them apart on a Revenium row

The fastest way to tell which path produced a given metered row is its
`--transaction-id`, which becomes the row's transaction identifier in
Revenium:

| Path | Transaction identifier shape | Granularity |
|------|------------------------------|-------------|
| Legacy (cron-reconstructed) | `<session_id>-<cumulative_total_tokens>-<muid>` (or `<session_id>-<cumulative_total_tokens>` for a markerless session) | One row per session-delta split, computed from `state.db` counters roughly a cron tick after the call |
| Event-driven (this phase) | `event:<api_request_id>` | One row per API call, computed from the call that incurred it |

If you are debugging a row and want to know which path shipped it, look at
the transaction identifier first — that is the question every operator
asks before anything else.

## The switches

**`REVENIUM_EVENT_METERING_MODE=live` alone does not cut over.** With
`REVENIUM_LEGACY_COMPLETIONS` still `enabled` (the default), the legacy path's
own D-09 partition check claims every session before the event path gets a
chance to — logging `skipping <sid> — already owned by the legacy HERMES:
ledger (D-09 partition)` for each one — and the event path defers
indefinitely. Legacy wins because `cron.sh` runs the legacy stage before the
event stage inside a single tick under one `cron.lock`, and both paths gate a
session's readiness on the same settle/sentinel condition, so they become
ready on the same tick and ordering decides. **`REVENIUM_LEGACY_COMPLETIONS=disabled`
is required** for the event path to actually bill anything. This was proven by
inducing a session on a profile at `mode=live, legacy=enabled` post-flip: it
went entirely to legacy, 0 event rows.

Two independent, reversible settings control the rollout. Both are
readable from the environment (highest precedence) or from
`config.json` (checked when the environment variable is unset), with an
unrecognised value falling back to the safe default and warning exactly
once per run — a typo must never silently change what gets billed.

**Independence is what makes one sequence unsupported (quick-260818-jbl,
AX-Q16).** Do not set `REVENIUM_LEGACY_COMPLETIONS=disabled` while
`REVENIUM_EVENT_METERING_MODE` is `shadow` (the default). With legacy
suppressed and the event path not shipping, every brand-new session created
while that combination holds is billed by **neither** path for as long as
it holds — legacy correctly declines to claim a session it will never bill
(see "Session ownership and the legacy-claim abstention" under Rollback
below), but nothing is claiming it on the event side either, because
`shadow` ships nothing. The drain gate cannot catch this: its refusal
predicate reads `drained` only and has no view of the event metering mode.
This is the same rule "Interaction with the legacy-disable switch" (below)
already states for the **revert** direction — re-enable legacy before
reverting the event-metering mode — generalised here to the **forward**
direction: do not disable legacy before advancing the event-metering mode
to `live`. A reader who lands on either paragraph should find both.

| Setting | Env var | `config.json` key | Default | Values |
|---|---|---|---|---|
| Event metering mode | `REVENIUM_EVENT_METERING_MODE` | `eventMeteringMode` | `shadow` | `shadow` (ships nothing, writes no ledger line, produces a comparison readout) / `live` (ships for real) |
| Legacy completions | `REVENIUM_LEGACY_COMPLETIONS` | `legacyCompletions` | `enabled` | `enabled` (the old path keeps billing) / `disabled` (request to stop — see the drain gate below) |

A fresh install of this phase's code observes **zero change**: shadow mode
ships nothing and the legacy path keeps billing exactly as it always did.
Flipping either switch is a deliberate, later operator action, not a side
effect of updating the skill.

**Shadow mode's readout.** While `REVENIUM_EVENT_METERING_MODE=shadow`
(the default), `api-event-report.sh` fully constructs every event's
`revenium meter completion` argv and then discards it — no CLI call, no
ledger line — and instead appends one JSON row per session to
`event-shadow-report.jsonl`, including sessions the event path would have
held or skipped entirely, with a per-platform aggregate (session count,
event-row count, database token total, mean coverage ratio) logged once
per run. Read this before authorising a canary: it is also how the
gateway question (does `post_api_request` fire on gateway-served turns at
all) gets answered on real traffic, before any billing changes.

## The drain gate

`drain-status.sh` answers one question: **has the legacy completions path
finished with every session it owns?** It reads exactly two local sources
— the frozen legacy ledger and `state.db` — and makes zero HTTP requests.
A session is **drained** only when both hold:

- **Terminal** — the session has ended and aged past the settle window, it
  is gone from `state.db` entirely, **or** (quick-260818-f1g) it is still
  open but has gone quiet for longer than `REVENIUM_DRAIN_STALE_SECONDS` —
  see "Staleness" below. Staleness applies to exactly one of these three
  branches: an open session with a live activity signal, or one that ended
  recently, is governed by the other two branches unchanged.
- **Quiet** — its legacy ledger timestamp has not moved across
  `REVENIUM_DRAIN_QUIET_TICKS` consecutive checks (default 15).

Exit codes: `0` drained, `10` not yet drained, `1` could not determine
(state.db or the ledger was unreadable). **Unknown never resolves to
drained** — the check is deliberately biased toward "keep waiting" over
"assume it's safe."

`hermes-report.sh` re-reads `drain-status.json`'s `drained` field at
startup, independently of anything else in this document. **A request to
set `REVENIUM_LEGACY_COMPLETIONS=disabled` is refused — with one warning
per run, and completions keep metering — while the gate reports not
drained**, or while the status file is missing or malformed. This refusal
is deliberate: the composition of "the new path skips any session already
in the legacy ledger" and "the legacy path stops when disabled" would
otherwise let a session that had prior legacy ledger lines and kept making
calls after cutover be billed by **neither** path. That is a silent
under-bill, not a crash — nothing errors, nothing halts, a slice of usage
simply never reaches Revenium. If a disable flip appears not to take
effect, run `drain-status.sh` (or `--json`) directly and look at its
`pending` list; that is the authoritative account of which sessions are
still blocking the gate and why.

### Staleness (quick-260818-f1g)

Before this addition, an OPEN session (`ended_at IS NULL`) was
**unconditionally non-terminal** — the drain gate could never report
drained while even one session stayed open, and a fleet with hundreds of
sessions that will never close (a long-lived gateway conversation, or one
Hermes' own retention never garbage-collects) could never disable legacy
completions at all.

An open session is now also judged terminal when it has gone quiet for
longer than `REVENIUM_DRAIN_STALE_SECONDS` (default `604800`, 7 days).
"Quiet" here is `now - last_seen >= threshold`, where `last_seen` is the
**later** of the session's newest legacy-ledger timestamp and its
`last_activity_at` column in `state.db` (when that column exists and is
populated) — `started_at` is deliberately excluded, since a live
long-running session should never be judged by when it began.

**The effective threshold is floored** at
`REVENIUM_CRON_SETTLE_SECONDS + 86400`, so a session still inside the
deliberate metering-deferral window can never be judged stale. That floor
is **not** a general bound on ledger lag — a ledger line is appended only
after a *successful* `revenium` CLI call, so a persistently-failing
per-session metering path withholds ledger progress indefinitely, with no
upper bound at all. Safety therefore does not rest on the threshold being
"big enough"; it rests on the per-session carve-out below. Setting
`REVENIUM_DRAIN_STALE_SECONDS` to `0` or below disables the staleness
route entirely and restores the pre-change behaviour exactly (the
conservative direction — there is no corresponding "go faster than the
floor" escape hatch).

**The self-healing chain.** A stale-drained session's verdict is
re-derived from live inputs on every tick, not decided once: if the
session resumes, its ledger timestamp or `last_activity_at` moves,
`last_seen` moves with it, staleness withdraws, `terminal` goes back to
`false`, and `hermes-report.sh`'s next startup re-read of
`drain-status.json` refuses the disable — legacy resumes billing that
session on the very next cron tick.

**The per-session carve-out — `legacyRetainedSids`.** A stale verdict
being wrong has a real cost: a legacy-owned session is never picked up by
the event path (`api-event-report.sh` only ships when a record's owner is
exactly `event`), so suppressing legacy for a session it still owns bills
that session by **neither** path, and because suppression freezes the
session's own ledger, the wrong verdict **latches** — it never
self-corrects. To make a wrong staleness verdict cost nothing rather than
cost a permanently-unbilled session, `drain-status.sh` emits
`legacyRetainedSids`: every tracked session whose terminality rests on
staleness **alone**, with no corroborating `last_activity_at` value, plus
— when any ledger line failed to parse this run — **every**
staleness-granted session (corruption widens the carve-out; it never
closes the gate). `hermes-report.sh` reads this list at startup and
resolves suppression **per session**:

```
suppress(sid) = REVENIUM_LEGACY_COMPLETIONS=disabled
                AND the drain gate reports drained
                AND sid NOT IN legacyRetainedSids
```

**Polarity is the whole design: the default is suppress, retention is the
carve-out.** A brand-new session that has never appeared in the legacy
ledger is not tracked, so it is not retained, so it **is** suppressed —
which is what lets the event path own it. A status document with no
`legacyRetainedSids` key at all (an older `drain-status.sh`, or an
early fail-closed run) suppresses every session exactly as it did before
this change.

**Retaining a session costs (close to) nothing.** The growth guard and
zero-delta guard in `hermes-report.sh` both `continue` before any
`revenium` invocation is built, so "legacy keeps metering a retained,
quiet session" is a ledger comparison and a `continue` — zero HTTP
requests, zero wire-shape impact. The carve-out changes **which**
sessions emit; it never changes **what** they emit, so every golden argv
fixture in `tests/fixtures/compat/` is unaffected by construction.

**`drained: true` no longer means "legacy is off."** It means "legacy is
off for everything except the sessions named in `legacyRetainedSids`." On
a fleet with many long-lived sessions that structurally cannot be handed
to the event path, the retained list — not the `drained` boolean — is the
real measure of cutover progress. `drain-status.sh`'s own banner states
both facts together whenever any session reached terminal by staleness.

New `drain-status.json` fields (all additive, all optional for a reader
still expecting the pre-this-change shape): `staleSecondsConfigured`,
`staleSecondsEffective`, `staleEnabled`, `activityColumnPresent`,
`ledgerUnparsedLines`, `staleDrainedCount`, `staleWithoutActivitySignal`,
`legacyRetainedSids`. Each `pending` entry also gains a `stale` boolean.

## The known differences from the legacy path

- **One row per API call, not one row per session-delta split.** The
  legacy path splits a session's periodic token delta across its
  unreported markers (a GUARDRAIL/CHAT pair per classification window);
  the event path ships one row per call, carrying that call's own usage
  under a single `CHAT` operation type. Reason: the call itself, not a
  cron-tick reconstruction, is now the unit of metering.
- **No client-supplied cost.** The event path never sends `--total-cost` —
  the spooled record carries no cost field, and Revenium prices the row
  server-side from model, provider, and tokens. The legacy path's
  `--total-cost`, when present, is unaffected.
- **Provider resolution is native, except through a routing layer.** The
  event path reads the call's own `provider` field directly, unless that
  field names a routing layer (OpenRouter, a LiteLLM-substring match,
  Bedrock, `custom`, or empty/`none`/`unknown`), in which case it derives
  the model provider from `response_model` — the model that actually
  served the call, which is a strictly better input than the legacy
  path's session-level `model` column for a session that changed models
  mid-stream.

## Rollback

Setting `REVENIUM_EVENT_METERING_MODE` back to `shadow` (or leaving it at
its default) stops the event path from shipping immediately — it resumes
constructing argv and discarding it.

**What happens to a session the event path already owns.** Ownership is
durable (quick-260817-tfe / PR #54): once a session's `owners/<sid>` record
names `event`, the legacy path used to defer to it forever, regardless of
whether the event path was still actually shipping. That was silently
correct only while the mode stayed `live` — the instant an operator reverts
to `shadow`, the event path stops shipping (by design) but the record still
said `event`, so **before quick-260818-0in** the session's growth would
have been billed by NEITHER path, permanently. This is now closed
(mode-aware legacy takeover): the legacy path takes each event-owned
session over on its NEXT tick after a revert, records a catch-up floor
equal to the session's cumulative total at the takeover instant, and bills
only growth above that floor going forward. The cost is a bounded, one-time
under-bill covering the window between the event path's last shipped row
and the takeover instant — the same direction (under-bill on doubt, never
double-bill) this feature has taken everywhere else, accepted for the same
reason: a double-bill is the worse failure.

**The takeover is one-way.** Once a session's record is flipped to
`legacy`, nothing flips it back. Returning a session to the event path is a
deliberate operator action — delete its `owners/<sid>` record while the
mode is `live` — not something that happens by flipping the mode switch
back and forth. This is what makes a later `shadow`→`live` flip safe: the
event path's own total predicate (`api-event-report.sh`) defers forever
once the record's first line is anything but the exact literal `event`.

**Interaction with the legacy-disable switch.** No takeover fires while
legacy completions are disabled (`REVENIUM_LEGACY_COMPLETIONS=disabled`) —
flipping ownership there would convert a state that heals when the mode
returns to `live` (the event path resumes and bills) into one that cannot
(the record would say `legacy`, the event path would defer forever, and
legacy is disabled). An operator who has already disabled legacy
completions must **re-enable them before reverting the event-metering
mode**, or the affected event-owned sessions simply stay un-taken-over —
and, since the event path is also not shipping in `shadow`, un-billed —
until legacy is re-enabled.

**Session ownership and the legacy-claim abstention (quick-260818-jbl,
CLAIM-01..05).** The claim block above assumes a session already has SOME
ownership history to resolve. A brand-new session — rows in NEITHER the
`HERMES:` nor the `API:` ledger — has none, and the claim's own default was
written when legacy always billed: `claim_side="legacy"`. Since
quick-260818-f1g, legacy completions can be suppressed **per session**
while that claim still runs, so a brand-new session under suppression used
to be claimed `legacy`, written durably, and then never billed by legacy
(suppressed) — and never billed by the event path either, because its own
ship predicate defers to any existing record whose first line is not the
exact literal `event`. That is a silent, permanent under-bill for every new
session created during the exact window CLAIM-01 describes.

The fix is an **abstention**: legacy writes no ownership record at all when
it is suppressed for a session AND neither ledger holds rows for it AND no
record exists yet. With nothing claimed, whichever path is actually live
claims the session atomically on its own next tick — under `cron.sh`'s
fixed legacy-then-event stage order, this resolves inside the SAME tick
whenever `REVENIUM_EVENT_METERING_MODE=live`. Abstaining was chosen over
two rejected alternatives: claiming `event` on the event path's own behalf
(false whenever the event path is not live, and self-locking — the
mode-aware takeover above will not undo it while suppression holds), and
teaching the event path that a zero-row `legacy` record is claimable
(re-derives ownership from the peer's mutable, prunable billing ledger,
exactly the mechanism PR #54 exists to delete).

**The per-tick aggregate, and its two severities.** Exactly like the other
ownership aggregates in this document, a single line fires once per tick
when the count is non-zero and is silent at zero — never a per-session
line. Its severity depends on whether the event path is live for THIS
tick's legacy run:

- **`info`** — the event path is live. Normal cutover flow: the sessions
  named in the count are claimed and billed by the event path this same
  tick.
- **`warn`** — the event path is NOT live. Nobody will claim or bill these
  sessions this tick. The line names both recovery routes (below) and both
  remedies: flip `REVENIUM_EVENT_METERING_MODE=live`, or set
  `REVENIUM_LEGACY_COMPLETIONS=enabled`. Do not wait on this warn — act on
  one of the two remedies.

**The recovery bound — both routes, both bounds (AX-Q16).** An earlier
draft of this fix described abstention as "fully recoverable." That
overstated it. There are two independent recovery routes, with two
different bounds, and permanent loss requires BOTH closed:

- **Route A — flip the event path to `live`.** Recovers from the session's
  spool file (`EVENT_SPOOL_DIR/<sid>.jsonl`). Bounded by
  `REVENIUM_MARKER_RETENTION_DAYS` (default 30) from the session's last
  event, and only reachable when an operator actually runs the manual
  `prune-markers.sh` (never wired into cron).
- **Route B — set `REVENIUM_LEGACY_COMPLETIONS=enabled`.** Recovers from
  the session's row in `state.db`, which this skill never writes and never
  prunes, at a zero baseline (billing the full cumulative total exactly
  once — correct-by-design for a baseline-0 claim, not an over-bill).
  Bounded only by however long Hermes itself retains the session row.

Once a session's sid leaves `state.db`, Route B closes on its own, and
`prune-markers.sh`'s owners pass removes any stray ownership record for
that sid too — the identical terminal state today's durable-`legacy`
default would reach anyway. Abstention is never worse than the pre-fix
behaviour on this axis; it is strictly better inside both recovery windows.

**A pre-fix record left by the defect (AX-Q15).** A `legacy` owner record
with no second line (no baseline) and zero rows in either billing ledger
can only have been written by the defect this fix closes — a migration
state, not something this fix produces going forward. Both paths stay off
such a session (legacy because the record already names it; the event path
because the record's first line is not `event`) until an operator applies
the remedy: delete `owners/<sid>` while the event path is `live`, and the
next event-path tick claims it fresh.

**The liveness predicate's scope limit.** The guard resolves liveness from
the SAME `REVENIUM_EVENT_METERING_MODE` / `eventMeteringMode` switch the
event shipper itself reads. There is deliberately no liveness heuristic —
no "has the event ledger grown recently", no spool freshness, no
cron-registration probe — because inferring liveness from a mutable
artifact would re-import the exact order-dependence PR #54 exists to
eliminate. Consequence: a profile whose config says `live` while
`api-event-report.sh`'s cron stage is not actually scheduled to run is
**not** covered by this guard — the legacy path will see
`EVENT_PATH_LIVE=true` and keep deferring to a path that has, in fact,
stopped shipping. This is the "uninstall the event path" case. Runbook
step: before removing `api-event-report.sh`'s cron stage (or the plugin
that spools its input), either revert `REVENIUM_EVENT_METERING_MODE` to
`shadow` first — letting the next legacy tick take every event-owned
session over normally — or clear the affected sessions' `owners/<sid>`
records directly so the legacy path backfills them fresh.

**A residual straddle exposure, and how to avoid it entirely.** The two
scripts resolve the mode INDEPENDENTLY, at their own process startup — two
sequential reads by two processes, never a shared read. Under cron this can
never bite: `cron.sh` always runs the legacy stage before the event stage,
both inside one `cron.lock`, so no same-tick race is constructible. The
exposure opens only when `api-event-report.sh` is run BY HAND, out of
band, while a revert is in progress: an out-of-band `live` invocation could
invoice tokens for a session in the microseconds around the takeover. The
takeover guards against this by re-reading the session's live `state.db`
total immediately before publishing the floor, so anything the out-of-band
shipment already recorded in `sessions` is floored out rather than
re-billed. The residual — tokens not yet reflected in `sessions` at that
instant, or shipped in the microseconds after the floor is published — is
bounded and accepted, not fixed. The one instruction that removes it
entirely: **do not run `api-event-report.sh` by hand while a revert is in
progress — let the cron stages do it.**

**Rollout ordering is unchanged (from PR #54).** The skew hazard is
directional: an old legacy build racing a new event-aware build can
double-bill. The skill update must reach EVERY profile, verified by
**checksum, not presence** (a stale classifier can sit at a path that
"looks" current — see the trace-type-uncategorized history for exactly
this failure mode), before ANY profile flips `shadow`→`live`.

The legacy ledger was **frozen, never migrated** (a deliberate design
choice — the two ledgers key on per-call `api_request_id` versus
per-session-total identifiers that are not equivalent, so migrating between
them risked retroactive double-metering), so re-enabling the legacy
completions stage for a session the event path never owned runs against an
intact record exactly as before. For a session the event path DID own,
"exactly as before" is no longer literally true — see the takeover
behaviour above.

**What rollback cannot undo:** any row the event path has already shipped
to Revenium exists server-side under the `event:<api_request_id>`
transaction-identifier scheme. The legacy path cannot reproduce that key
from the frozen `HERMES:` ledger, so those specific rows cannot be
re-derived or re-shipped under the legacy shape. This is exactly why the
canary flip (letting the event path ship for real on even one profile) is
gated behind an explicit operator decision rather than happening as a
byproduct of deploying this phase's code.

## Shadow-stage findings (2026-08-17)

The shadow stage ran fleet-wide (all ten metered profiles) for roughly 20 hours
before this readout. `revenium-api-events.ledger` stayed empty on every profile
throughout — shadow mode shipped nothing, as designed.

**The gateway question is answered: `post_api_request` fires on gateway-served
turns.** A live, continuously-open gateway-served conversation (channel-name
platform value, not the literal string `gateway` — matching the caveat this
document's design phase raised) produced spooled events with exact per-call
agreement against `state.db` for the portion of its history inside the shadow
window. Corroborated independently by the owning profile's own gateway-service
and channel-integration configuration. This closes the one open question the
shadow stage existed to resolve before any canary could be authorised.

**Fleet coverage:** of 14 real sessions observed across cron, CLI, and
gateway-served surfaces, 12 showed exact 1.000 event-vs-database token
agreement. The two exceptions were each individually explained rather than
averaged away: one was a multi-week-old session whose database counter
reflects its entire history while the event count only reflects the shadow
window (a scale mismatch, not a missed call); the other was a single
still-in-flight, multi-call session where the event count briefly ran ahead of
a database snapshot taken moments earlier (a measurement-instant race that
resolves on the next tick, confirmed to involve no duplicate event records).

**The three predicted systematic deltas are confirmed on real traffic, with no
surprises beyond them:**

- **Row count and operation type.** The legacy path's session-delta pair
  (one `GUARDRAIL` row, one `CHAT` row, tokens split via `equal_split`) is
  replaced by one `CHAT` row per API call. Observed 1–23 event rows per
  session against the legacy path's fixed two, with exact token conservation
  on every session where a clean comparison was possible.
- **Cost.** The event path never sent `--total-cost` on any observed row, as
  designed — Revenium prices these rows server-side.
- **Provider.** The event path's resolved provider matched the legacy path's
  would-be resolution on every observed row. The routing-layer fallback
  branch (added for installs that route through OpenRouter, LiteLLM, or
  Bedrock) was not exercised on this fleet's traffic in this window — every
  provider value seen was already a direct model-provider name. Kept in place
  rather than removed: this fleet's provider mix is not guaranteed to stay
  that way, and other installs have needed exactly this fallback before.

**One anomaly was observed during the window and is now fully explained.** For
part of the shadow window, a shadow-report-only artifact — never the shipping
path, never the idempotency ledger — showed one profile's session data
appearing in every other profile's comparison report. It cost nothing in
billing terms: the affected surface only ever produces a disposable comparison
file, and `revenium-api-events.ledger` stayed empty on every profile
throughout.

There *was* a real defect, and it was real in production: the build deployed at
the start of the window swept every profile's spool directory instead of only
its own, so each profile's run read every other profile's spooled events. That
is the same cross-profile defect this phase had already fixed once on the
shipping side. Mid-window it was fixed here too, and that single script was
pushed to the fleet roughly a second after the fix was committed. Reports
written before the push carry the sweeping behaviour; those written after do
not.

So two distinct things are true and should not be collapsed. The **anomaly** was
a genuine code defect, briefly live on the fleet. The **disappearance** of the
anomaly was not mysterious — it was that fix landing. What the currently
deployed build contains is the corrected single-profile read. An initial pass
that looked only at the deployed host could see the anomaly stop but not why,
and recorded the cause as unattributed; correlating the host's file timestamps
and authentication log against the repository's commit history closed it.

Why it cost nothing: in shadow mode the swept records only ever reach the
disposable comparison report. Had the same build been running in **live** mode,
each non-owning profile would have found no legacy ledger line for a foreign
session, concluded it was unowned, and shipped it against its own event ledger —
up to 9x duplicate billing. The defect's blast radius was bounded by the mode,
not by the code.

Two lessons worth keeping, both of which cost real investigation time here:

- **A content hash only proves what was true when you sampled it.** Every hash
  check of the shipper happened after the corrective push, so all of them
  agreed — and that agreement was mistaken for evidence that nothing had ever
  differed. The pre-fix build was simply never hashed. Sampling after the fact
  cannot establish what was running before.
- **A single-file push to a fleet leaves almost no trace.** Only one file in a
  49-file deployed tree carried the telltale modification time, and because the
  push was non-interactive it created no login record. Any out-of-band push to
  a deployed tree should take the same timestamped backup the documented deploy
  sequence takes, and record itself, or the next reader has nothing to correlate.

A `profiles`-axis regression test landed alongside the sweep fix: it asserts a
run does not process a sibling profile's spool file, and leaves that file in
place for its owner. Be precise about what it does and does not cover, because
the difference matters at the moment the event path goes live:

- **It asserts in shadow mode**, by checking the foreign session is absent from
  the shadow comparison rows. It does not exercise live shipping.
- **The `ticks`-axis tests** exercise the other half — live shipping and
  event-ledger deduplication across repeated runs.
- **No test yet asserts that a *live-mode* run refuses to ship a sibling
  profile's session.** So "never-double-report is covered on both axes" would
  overstate it: the profiles axis is covered for *reading*, the ticks axis for
  *shipping*, and the live-mode intersection of the two is covered only by
  construction.

That construction argument is real but is not a test: the spool directory list is
resolved to a single entry before any mode branch, so shadow and live share one
discovery path and neither can see a sibling's spool. The isolation is therefore
structural rather than mode-specific. Still, the one axis that produced a 9x
duplicate-billing defect is also the one whose live path has no direct
assertion — closing that gap is worth doing before or alongside the first live
rollout, not after.

## State files added

- `~/.hermes/state/revenium/api-events/<sid>.jsonl` — the per-session
  event spool, one JSON record per API call, written by the
  `post_api_request` plugin hook.
- `~/.hermes/state/revenium/revenium-api-events.ledger` — the event path's
  own idempotency ledger, keyed on `api_request_id` (`API:` lines),
  entirely separate from the legacy `revenium-hermes.ledger`.
- `~/.hermes/state/revenium/event-shadow-report.jsonl` — shadow mode's
  per-session comparison readout, bounded by the same rotation thresholds
  as the metering log.
- `~/.hermes/state/revenium/drain-status.json` — the drain gate's
  atomically-written verdict, including the pending-session list. Since
  quick-260818-f1g also carries the staleness fields
  (`staleSecondsConfigured`, `staleSecondsEffective`, `staleEnabled`,
  `activityColumnPresent`, `ledgerUnparsedLines`, `staleDrainedCount`,
  `staleWithoutActivitySignal`) and the per-session carve-out
  (`legacyRetainedSids`) — see "Staleness" under "The drain gate" above.
- `~/.hermes/state/revenium/owners/<sid>` — the durable, atomically-claimed
  session ownership record (quick-260817-tfe / PR #54): a one-line file
  naming which path bills a session (`legacy` or `event`), or two lines
  when a catch-up baseline is present. Lifetime is keyed on presence in
  `state.db`, not on either billing ledger's own retention —
  `prune-markers.sh` removes a record only once its session is absent from
  `state.db`, however old the record's own mtime is. quick-260818-0in adds
  the mode-aware takeover, which flips this record's first line to
  `legacy` one-way when the event path is not live; see Rollback above.

## Where to look if you build on this

- `skills/revenium/scripts/api-event-report.sh` — the shipper: the settle
  gate, the legacy-ledger partition, the temporal marker join, provider
  resolution, and the shadow/live mode branch.
- `skills/revenium/scripts/drain-status.sh` — the drain gate's own
  implementation and its exit-code contract.
- `skills/revenium/scripts/hermes-report.sh` — the one outer guard around
  the legacy completion-emission block that reads the drain gate.
- `tests/fixtures/compat/meter-completion-event.golden.json` — the event
  path's own pinned argv shape; see `tests/fixtures/compat/README.md` for
  how it relates to (and stays separate from) the legacy v1.x contract.

## Idempotency, proven live

Proven by **forced re-run on a live host** on 2026-08-18, not inferred from the
uniqueness of the idempotency key.

A session was induced on a drained profile with the event path live and legacy
completions disabled. It was claimed by the event path and shipped one row. The
metering stages were then invoked **three times back to back**, each invocation
evidenced by its own log lines rather than assumed — a run silently skipped on
the cron lock would prove nothing.

After three re-runs:

- All **four** ledger surfaces were byte-identical to their pre-run snapshots —
  the event ledger, the legacy completions ledger, the jobs ledger, and the
  tool-events ledger.
- The event shipper reported `duplicate-skipped-events=1` on every run, so the
  record genuinely reached the **presence check** rather than being filtered
  earlier at the ownership gate.
- The spool file still held its record. This is the case the legacy path never
  had: spool records are **not** consumed on ship, so every re-run necessarily
  re-reads what it already shipped, and the ledger is the sole barrier to a
  duplicate.
- Server-side, the session still carried **exactly one** row.

A negative control ruled out an inert shipper: one further session was induced
and re-run once, and both the event ledger and the server gained **exactly one**
row. Without it, a shipper broken so badly it sent nothing at all would have
produced an identical clean result.

Note on ordering: an earlier attempt at this proof was recorded as **not-run**
because every candidate session was skipped at the ownership gate, upstream of
the presence check. A byte-identical ledger is necessary but not sufficient —
confirm the records under test actually reached the logic being tested.
