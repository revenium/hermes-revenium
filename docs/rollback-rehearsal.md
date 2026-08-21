# Rollback Rehearsal on `devops` — One Falsified, Root-Caused Prediction and One Confirmed Prediction; Restoration Proof Finds a Fourth, Benign Difference Category (ROADMAP Criterion 7 Not Met As Written)

## Verdict

**MIXED RESULT — MECHANISM DEMONSTRATED, RESTORATION NOT CLEAN, READ THIS PARAGRAPH IN
FULL BEFORE ANY OTHER SECTION.** This rehearsal ran one round trip on one profile
(`devops`, one of the fleet's ten) with two inductions, each testing its own committed
prediction. **Prediction A was FALSIFIED**: the induced session was claimed by the event
path, not legacy — root-caused, by reading the deployed `hermes-report.sh` source, to an
ownership guard (`session_event_owned`) rather than the stage-order mechanism
`docs/event-metering.md`'s own "The switches" paragraph previously claimed; that paragraph
has been rewritten in this phase to state the real mechanism, because this rehearsal's own
evidence falsified the shipped-product-doc's prior explanation. **Prediction B was
CONFIRMED**, cleanly and exactly as written — but its confirmation carries a sharp
qualifier stated nowhere as clearly as here: **leg A and leg B produced identical
observable artifacts** (same ledger-line shapes, same log-line shapes, same one-line
`owners/` record), so `devops`, specifically, **cannot discriminate its two env states
from a freshly-induced session's own output** — only reading source code could tell the
two mechanisms apart. **The restoration proof — the criterion this phase can fail on its
own — is NOT MET AS WRITTEN**: `env` returned byte-for-byte to its pre-rehearsal content
and the pre-existing legacy ledger is byte-identical, but the enumerated pre-versus-post
comparison found a **fourth difference category** G-7 does not permit — 1,939 durable
`owners/` "legacy" backfill records, a side effect of the ~17 minutes `env` spent at
`legacy=enabled` on a profile carrying an unusually large legacy backlog. That fourth
category is investigated at length in this document and found benign (the legacy ledger
did not move; every one of the 1,939 records backfills a session this ledger already
billed; zero double-bill signatures exist anywhere) with a forward effect this document's
own read-only method finds to be null — but benign is not the same as permitted, and this
document does not redefine criterion 7 to make the count come out clean.

**Every shortfall this document's body records, enumerated here, checked in both
directions against `## Results`, `## Findings`, and `## Known limitations and
exclusions`:**

1. **The mechanism half of this proof rests entirely on two induced sessions on an
   otherwise-idle profile.** `devops` had zero organic sessions since the 2026-08-19
   cutover flip; every claim this document makes about which path claims a session rests
   on artificial traffic this rehearsal itself created, not on anything that happened on
   its own.
2. **The pre-existing-safety half of the proof is strong for the opposite reason**: a
   profile with zero `owners/` records and zero event-ledger lines before this rehearsal
   had nothing pre-existing to accidentally re-bill or drop, so the byte-identical legacy
   ledger and the clean per-sid enumeration are strong guarantees precisely because there
   was nothing at risk. The two halves of this proof have opposite dependencies on the
   same fact (idleness), and this document states both rather than only the flattering
   one.
3. **One profile of ten.** A rollback mechanism proven — and falsified, and root-caused —
   on `devops` is evidence about the mechanism, not a fleet-wide guarantee. The other nine
   profiles were never rolled back and are not claimed to have been.
4. **`devops`'s own large legacy backlog (886+ tracked sessions, ~5-6 minute legacy
   cycles) is precisely what made this profile behave differently from a smaller-backlog
   profile like `community`** (whose own earlier post-flip probe went entirely to legacy,
   as the original mechanism claim predicted). A profile whose legacy cycle completes
   faster than a session can be induced mid-cycle would very plausibly show Prediction A
   confirmed, not falsified — this rehearsal's finding is a real, source-confirmed
   mechanism (ownership, not stage order, decides), but the RACE that made it visible on
   `devops` specifically is a backlog-size artifact, not something every profile shares.
5. **One round trip. Not repeated, not sampled.** Leg A ran once; leg B ran once. Neither
   leg was re-run to check whether the observed outcome is the profile's consistent
   behaviour or one instance of a race whose result could differ on a re-run.
6. **The two induced sessions' metered rows (A and B) are permanent** and cannot be
   un-sent (the same D-08 constraint that made Phase 30's probe rows permanent) — the
   profile was returned to its pre-rehearsal `env` configuration, not to a state in which
   the rehearsal never happened.
7. **A fourth, unpermitted difference category exists** — the 1,939-record `owners/`
   backfill, investigated above and found benign with a null forward effect by read-only
   source inspection, but ROADMAP criterion 7 is not met as written because of it. See
   `## Independent confirmation`'s own disposition paragraph.
8. **Cost is `$0` throughout, by operator decision (G-5/CUT-08), not a defect** — no
   dollar figure in this document supports any claim about billing correctness; `BACK-2676`
   remains the prerequisite for a production tenant to show non-zero cost for either path.

**None of the above changes the phase's headline result: the round trip did happen, live,
on the real fleet, with real induced traffic — and it found something the plan did not
anticipate finding (the ownership-race mechanism, and the `owners/` backfill) rather than
merely confirming what was already assumed. A rehearsal that falsifies its own prediction,
root-causes the falsification against deployed source, corrects a shipped operator
document as a direct result, and then finds and fully investigates an unplanned side
effect is a stronger outcome than a rehearsal that quietly confirmed two predictions and
stopped looking. This document states the shortfalls above precisely so that strength is
not mistaken for an unqualified pass.**

## Why this document exists

The planning directory that captured this measurement is excluded from version control,
so this file is the committed mirror of the headline findings and the replayable method.
Once 35-04 registers this document in `tests/test_repository.py::test_expected_files_exist`
(D-4 — that pin is deliberately added last, after this file exists), deleting it turns the
repository's own test suite red, which is the whole point: a verdict that only exists in
an untracked directory is a verdict that did not happen.

## What was measured

**This rehearsal was the milestone's first deliberate write to the live fleet.** What
follows is the setup that made the round trip provable — which profile, from which exact
backup, and the planned sequence — followed, in `## Results` and `## Findings` below, by
what the round trip actually found once it ran (35-03's rollback leg, this plan's leg B).
Both inductions' predicted outcomes were committed here, ahead of either induction
actually running (see below), exactly as this section originally described.

**Profile: `devops`** (D-2). Chosen from the converged-and-idle candidate set {`qa`,
`lorekeeper`, `devops`, `pm`} after live reconnaissance in `35-RESEARCH.md`, and
**live-reconfirmed for this plan on 2026-08-20**: `drained=true`, `pendingCount=0`,
`owners/` absent (the directory does not exist), `revenium-api-events.ledger` at 0 lines,
and 0 sessions since the 2026-08-19 cutover flip — unchanged from `35-RESEARCH.md`'s
earlier snapshot. `qa` and `lorekeeper`, the approved fallbacks, were re-verified
identically and remain acceptable but less clean (22 and 33 pre-cutover `owners/` records
respectively; both idle since the flip). Full per-profile figures are in `35-EVIDENCE.md`.

**Exact rollback target: `env.bak2-20260819-213357`.** Read live this plan:
`REVENIUM_EVENT_METERING_MODE=live`, `REVENIUM_LEGACY_COMPLETIONS=enabled` — confirmed
byte-for-byte against the content `35-RESEARCH.md` recorded. This is deliberately **not**
`env.bak-20260819-211250` — see `## Reproducing this measurement`'s own preamble for why.

**Only one switch moves across the whole round trip.** `REVENIUM_LEGACY_COMPLETIONS` flips
`disabled -> enabled -> disabled`; `REVENIUM_EVENT_METERING_MODE` stays `live` throughout,
both during the rollback leg and the restore leg. This is what keeps
`_takeover_session_owner` out of scope for this rehearsal by construction (see the
ownership prediction below).

**The four-step sequence, as planned and as actually run** (`## Results` has the full
step-by-step outcome; this is the plan the round trip followed):
1. Snapshot the live `env` to `env.pre-rehearsal-<stamp>` — the literal first command,
   before any other write. Ran 35-03.
2. Restore `env.bak2-20260819-213357` over `env` — the rollback leg (`legacy=enabled`,
   `mode=live`). Ran 35-03.
3. Induce one session; observe which path claims it. Ran 35-03 (induction A) — the event
   path claimed it, falsifying Prediction A (see `## Findings`).
4. Restore `env` from the step-1 snapshot — the cutover leg — and induce a second
   session; observe the event path resume. The restore ran 35-03, as an emergency-recovery
   action rather than this step's own scripted completion (see `## Results`); the second
   induction ran this plan (35-04), against the already-restored state, and confirmed
   Prediction B.

**No gateway restart is part of this sequence.** `cron.sh:32-36` sources `ENV_FILE` fresh
under `set -o allexport` on every invocation, and the fleet's crontab runs the per-profile
cron wrapper every minute (D-5) — an `env` edit takes effect on the very next tick, with no
`systemctl` step anywhere in the sequence.

**Both inductions' predicted outcomes, committed here ahead of either induction actually
running (D-3's prediction-before-induction discipline, Phase 30's own D-12 pattern reused
verbatim).** This ordering is the mechanism, not a formality: a prediction that landed in
the same commit as its result would not be a prediction, and this phase's likeliest
failure mode is a surprise retrofitted into one after the fact. 35-03's own `<verify>`
re-asserts that this block already exists at `HEAD` before its first induction runs.

### Prediction A — the rollback leg (`legacy=enabled`, `mode=live`)

Once `env` is rolled back to `env.bak2-20260819-213357` and the first induced session
lands, the legacy path claims it — because `cron.sh` runs the legacy stage before the
event stage inside one tick, and the D-09 partition check (`api-event-report.sh:744-812`)
is session-level and runs before the settle gate, so legacy always gets first refusal on
every session while it is enabled.

- **Positive evidence:** a new `HERMES:<induced-sid-legacy>:...` line appended to
  `revenium-hermes.ledger`, and a `Reported: session=` log line from one of
  `hermes-report.sh`'s two emit paths (`hermes-report.sh:2518` marker path or `:2615`
  markerless path) naming that sid.
- **Corroborating evidence:** the event path's own D-09 skip line for the same sid —
  `skipping <sid> — already owned by the legacy HERMES: ledger (D-09 partition)`
  (`api-event-report.sh:812`).
- **What should NOT appear:** any `API:` line in `revenium-api-events.ledger` for that
  sid, and any `Reported: sid=` (`api-event-report.sh:1301`) log line for it.
- **Falsifier:** if the induced session instead produces an `API:` ledger line, a
  `Reported: sid=` log line, or no D-09 skip line at all, Prediction A is wrong — the
  ordering/partition mechanism this rehearsal is meant to demonstrate does not hold as
  described, and that is a defect finding for `## Findings`, not something to smooth over.

### Prediction B — the restore leg (`legacy=disabled`, `mode=live`)

Once `env` is restored to its pre-rehearsal snapshot and the second induced session
lands, the event path claims it.

- **Positive evidence:** a new `API:<api_request_id>|<induced-sid-event>|...` line
  appended to `revenium-api-events.ledger`, and a `Reported: sid=` log line
  (`api-event-report.sh:1301`) naming that sid and its `api_request_id`.
- **What should NOT appear:** any `HERMES:` line for that sid, and no D-09 skip line
  (`skipping <sid> — already owned by the legacy HERMES: ledger (D-09 partition)`) for it.
- **A precondition worth stating, not routing around:** `hermes-report.sh:184-190`'s
  legacy-suppression path only engages (logging `legacy completions path disabled — drain
  gate reports drained; skipping legacy completion emission this run.`) when the drain
  gate reports drained. The profile's own pre-state (`35-EVIDENCE.md`) already shows
  `drained=true`, so this is expected to hold — but if induction #1 somehow leaves the
  profile un-drained at the moment of the restore, that is itself a
  predicted-and-observable outcome to record in `## Findings`, not a blocker to route
  around.
- **Falsifier:** if the induced session instead produces a `HERMES:` ledger line, a
  `Reported: session=` log line, or the D-09 skip line, Prediction B is wrong — the
  restored cutover is not actually billing through the event path as designed.

### The ownership prediction — the no-double-ship half

Each induced sid is brand new and has never existed before, so each is expected to
receive an ordinary **one-line** `owners/<sid>` record — `legacy` for induction A's sid,
`event` for induction B's sid. A **two-line** record for either induced sid is the
positive signature of a double-bill (`_claim_session_owner`'s dual branch, per
`34-RESEARCH.md`'s already-settled overlap mechanics, reused here rather than re-derived)
and would be a defect finding, not an expected outcome.

`_takeover_session_owner` **cannot fire** during this rehearsal, by construction — it
requires the event-metering mode to have reverted to `shadow`, and this rehearsal never
touches that switch (`REVENIUM_EVENT_METERING_MODE` stays `live` throughout, per above).
This is recorded here as a **designed non-event**, so a reader does not mistake its
absence for an untested code path.

## Known limitations and exclusions

**The write-loss window is history, not live risk, and this rehearsal runs entirely
outside it.** Revenium's own confirmed write-loss window is `2026-08-19T18:25:00Z` through
`2026-08-20T01:24:00Z` (Phase 34, `docs/transition-reconciliation.md`), a closed interval
at both ends. This rehearsal's own live work began no earlier than 2026-08-20T21:00Z, and
the round trip itself (35-03's leg, this plan's leg B) ran later still, into
2026-08-21T00:22Z — well after the window closed. Any pre-existing ledger or read-side
figure this document draws on that
falls inside that window is labelled suspect, exactly as Phase 34 did, and never chased as
a metering defect caused by this rehearsal.

**Cost is `$0` by operator decision — not a metering defect.** Every `$0` /
`totalCost: 0` figure this rehearsal's evidence shows carries this caption: cost is `$0`
by operator decision in this pre-prod tenant (CUT-08); **BACK-2676** (Revenium-side
provider-slug drift) remains the prerequisite before a production tenant would show
non-zero cost for these completions. The two induced sessions this rehearsal created
themselves produced `$0` rows; that is expected and captioned, not a finding.

**Scope boundary.** This document reports what the rehearsal found; it does not fix
anything the rehearsal surfaces. No file under `skills/` is touched by this phase (G-1).
Whether to delete the retained legacy metering path once rollback is no longer needed is a
later, separate operator call — out of scope here.

**`devops`'s idleness is a trade-off, not unqualified good news — state both halves
separately.** Idleness makes the **pre-existing-safety** half of this proof unusually
STRONG: a profile with zero `owners/` records and zero event-ledger lines has nothing to
accidentally re-bill or drop, so a byte-identical ledger prefix across the whole round
trip is a strong guarantee here, not a weak one. Idleness makes the
**mechanism-demonstration** half entirely DEPENDENT on the two induced sessions —
"which path claims a freshly-created session" is a claim about behaviour on new activity,
and an idle profile has none of its own. **This dependency is exactly what played out**:
induction A's own timing (created 38 seconds into an already-running legacy cycle) is what
produced the falsified Prediction A finding — a passive-observation rehearsal on this same
idle profile would have found nothing, neither confirming nor falsifying anything, because
there would have been no fresh session for either path to race over. Without the two
induced sessions, this rehearsal would have proven only that nothing happened on `devops`,
which is equally true whether or not the rollback mechanism actually works — this is why
D-3 authorizes real traffic rather than passive observation, and why the "zero owners
records" fact must not be read as unqualified good news on its own.

## Results

**The round trip ran as two legs, on two different days of execution, with one falsified
prediction and one confirmed prediction.** Leg 1 (the rollback leg, `env.bak2-*` restored
+ induction A, 35-03) ran to completion and produced a result — but that result
**falsified Prediction A**, and the falsification's own evidence made 35-03's Task 3
precondition (a confirmed `HERMES:` ledger line for induction A) impossible to satisfy by
further waiting, so 35-03 restored `env` to the cutover state as an emergency-recovery
action and stopped there. **This plan (35-04) ran leg 2 directly against that
already-restored cutover state** — no further env write was needed, since `env` was
already `legacy=disabled`/`mode=live` when this plan began — and induced a second session
(B) to test Prediction B on its own terms. **Prediction B was CONFIRMED, cleanly.**

| Step | What was attempted | Artifact | Outcome |
|---|---|---|---|
| 1. Snapshot | `cp` live `env` to `env.pre-rehearsal-<stamp>` | sha256 match between snapshot and live `env` (`6ec48b84...9ddd4a`, both) | Done (35-03) |
| 2. Rollback restore | `cp env.bak2-20260819-213357` over `env` | Read-back `env` sha256 `8bef65b2...b997e601`, matching `env.bak2-*`'s own sha256; write timestamped `2026-08-20T23:23:21Z` | Done (35-03) |
| 3. Rollback took effect | Poll `revenium-metering.log` for a post-write tick | Tick at `2026-08-20T23:24:21Z`-`23:24:26Z`, strictly later than the write; the `legacy completions path disabled` line, present at every prior tick, absent from this one (corroboration) | Done (35-03) |
| 4. Induce session A | `hermes chat` on `devops` | New session id (redacted `<induced-sid-legacy>`); `.ready/<induced-sid-legacy>` sentinel present within 30s | Done (35-03) |
| 5. Legacy claims A (Prediction A) | Poll `revenium-hermes.ledger` for `HERMES:<induced-sid-legacy>:` | No such line appeared after 600s of polling, nor at any point afterward (see Findings) | **FALSIFIED** — the event path claimed A instead (35-03) |
| 6. Event path defers on A (Prediction A, corroborating half) | Poll for the D-09 skip line | No D-09 skip line appears anywhere in the post-rollback log | **Also contrary to the predicted shape** — see Findings for why the D-09 mechanism was never the deciding factor here (35-03) |
| 7. Restore leg (env, emergency recovery) | `cp env.pre-rehearsal-<stamp>` back over `env` | Diff empty, sha256 `6ec48b84...9ddd4a` matches both the snapshot and the pre-rehearsal capture; write timestamped `2026-08-20T23:40:38Z` | Done, **as an emergency-recovery action** (35-03), not as a scripted restore-leg step |
| 8. Confirm `env` still at cutover state at the start of this plan | `cat`/`sha256sum` `env` | `6ec48b84...9ddd4a` — identical to 35-02's original capture and the 35-03 snapshot | Done (35-04) |
| 9. Induce session B | `hermes chat` on `devops`, same command as induction A | New session id (redacted `<induced-sid-event>`); `.ready/<induced-sid-event>` sentinel present within seconds | Done (35-04) |
| 10. Event path claims B (Prediction B) | Poll `revenium-api-events.ledger` and the log for `Reported: sid=<induced-sid-event>` | `API:` line and `Reported: sid=` line both appeared ~4 minutes after induction; no `HERMES:` line, no `Reported: session=` line, no D-09 skip line, ever | **CONFIRMED** — exactly as predicted (35-04) |
| 11. Post-restore tick confirms the cutover state stayed in effect throughout | Poll ticks across both this plan's induction and the POST-state capture | Multiple ticks ran, all under `legacy=disabled`/`mode=live`, ending with the same `env` sha256 the round trip started from | Done (35-04) |
| 12. POST-state capture, IDENTICAL command set to 35-02's | Re-ran 35-02's own replayable block verbatim | See `## Independent confirmation` | Done (35-04) |

**A fourth, unplanned finding surfaced during the POST-state capture: `owners/` now holds
1,941 records, not 2.** The 2 induced sessions (A, B) account for 2 of them; the other
1,939 are a backfill side effect of the ~17-minute window `env` spent at `legacy=enabled`
(35-03's rollback leg) on a profile with a large legacy backlog. See `## Findings` →
"The `owners/` backfill — a fourth difference category" for the full investigation; see
`## Independent confirmation` for why this means ROADMAP criterion 7 is **not met as
written**.

Full raw evidence, including the source-level investigation into why the claimed
mechanism did not hold and the `owners/` backfill investigation, is in `35-EVIDENCE.md`.

## Findings

### Induced session `<induced-sid-legacy>` (rollback leg) — Prediction A: **FALSIFIED**

**Prediction (quoted from the committed `47ecabf` block above, unchanged):** "the legacy
path claims it... a new `HERMES:<induced-sid-legacy>:...` line appended to
`revenium-hermes.ledger`, and a `Reported: session=` log line... the event path's own
D-09 skip line for the same sid... no `API:` line... and any `Reported: sid=` log line
for it [should not appear]."

**Observation:** No `HERMES:` line for `<induced-sid-legacy>` ever appeared in
`revenium-hermes.ledger` (fresh full-file `grep`, not a tail sample), and no
`Reported: session=` log line for it ever appeared. Instead, an `API:` line appeared in
`revenium-api-events.ledger`, and the log recorded:
```
[2026-08-20T23:30:39Z] [INFO ] [revenium] Reported: sid=<induced-sid-legacy> api_request_id=<induced-sid-legacy>:<uuid>:<hash>:api:1 model=glm-4.6 task_type=liveness_check operation_type=CHAT
```
`owners/<induced-sid-legacy>` holds exactly one line, `event` — the event path claimed
sole, permanent ownership of this session. No D-09 skip line appears anywhere in the log
for the whole post-rollback window — the D-09 partition check was never the deciding
mechanism, because a different guard resolved the outcome first (below).

**Named cause, confirmed by reading the deployed `hermes-report.sh` source, not merely
inferred from timing:** the completion-emission block that would write a `HERMES:` line
is guarded by `sid_legacy_suppressed != true AND session_event_owned != true`.
`session_event_owned` is read from the `owners/<sid>` file — once either path claims a
sid, the other is permanently locked out, independent of `REVENIUM_LEGACY_COMPLETIONS`.
`devops` carries the fleet's largest legacy-tracked backlog (886 sessions), and its own
per-cycle legacy walk takes roughly 5-6 minutes end to end. The legacy cycle that was
running at the moment of induction had already fixed its own work list ~38 seconds
*before* the induced session existed, so that cycle could not see it. By the time the
*next* legacy cycle reached this session — confirmed by that cycle's own pre-guard jobs
scan, which did create a job for it — the much-faster event-path stage had already
claimed ownership three seconds earlier in the tail of the prior cycle. Legacy's
emission guard therefore deferred permanently, not provisionally.

**This inverts the assumption Prediction A was built on** — that "cron.sh runs the legacy
stage before the event stage inside one tick" gives legacy first refusal on every session
while it is enabled. That ordering claim does not hold for a session created *during* an
already-in-progress legacy cycle on a profile whose legacy walk is slow relative to the
event path's own pass — here, specifically, because `devops`'s legacy backlog size makes
its own cycle duration long enough to create the race. This is a genuine, reproducible
mechanism difference from the documented one, not a timing fluke: a second full legacy
cycle ran, specifically enumerated this session, and still could not bill it, because
ownership rather than stage order governs the outcome.

**No double-bill occurred.** `owners/<induced-sid-legacy>` has exactly one line. A
subsequent event-path run correctly reported `duplicate-skipped-events=1` for this sid,
confirming idempotency held even though the outcome diverged from prediction.

### Induced session `<induced-sid-event>` (leg B, this plan) — Prediction B: **CONFIRMED**

**Prediction (quoted from the committed `47ecabf` block above, unchanged):** "the event
path claims it... a new `API:<api_request_id>|<induced-sid-event>|...` line appended to
`revenium-api-events.ledger`, and a `Reported: sid=` log line... naming that sid and its
`api_request_id`... any `HERMES:` line... [and] no D-09 skip line... [should not appear]."

**Observation:** exactly as predicted, with no falsifier condition triggered. No
`HERMES:` line for `<induced-sid-event>` ever appeared in `revenium-hermes.ledger`
(fresh full-file `grep`), and no `Reported: session=` log line for it ever appeared. The
event path claimed it cleanly, ~4 minutes after induction:
```
[2026-08-21T00:22:25Z] [INFO ] [revenium] Reported: sid=<induced-sid-event> api_request_id=<induced-sid-event>:<uuid>:<hash>:api:1 model=glm-4.6 task_type=liveness_check operation_type=CHAT
```
`owners/<induced-sid-event>` holds exactly one line, `event`. No D-09 skip line appears
anywhere in the log for the whole leg-B window — expected, since legacy's per-session loop
never ran for this sid at all (it is globally short-circuited by the
`legacy completions path disabled` suppression while `env` reads `legacy=disabled`, the
same short-circuit responsible for `owners/` being ABSENT before 35-03's rollback leg ever
began).

**The question this leg was authorised to settle, answered directly: this profile cannot
discriminate its two env states from a freshly-induced session's own artifacts.** Leg A
(under the ownership race, `legacy=enabled` but too slow to win) and leg B (under a clean
`legacy=disabled`) produced **identical output shapes** — `API:` line present, `HERMES:`
line absent, `Reported: sid=` present, `Reported: session=` absent, D-09 skip line absent,
one-line `owners/<sid>=event` record, both claimed within minutes of induction. The only
way to tell the two mechanisms apart was reading the deployed source
(`hermes-report.sh`'s `session_event_owned` guard); nothing in the ledgers or the log
distinguishes "legacy was cleanly disabled" from "legacy was enabled but lost a race
against a slow backlog." See `35-EVIDENCE.md`'s side-by-side comparison table for the full
enumeration. This is the single largest qualifier on what this rehearsal demonstrates: a
smaller-backlog profile (most of the fleet's other nine) would very plausibly show leg A
actually claimed by legacy, as Prediction A originally assumed — `devops`'s own 886+
session legacy backlog is what created the race window this document's mechanism finding
depends on.

**No double-bill.** `owners/<induced-sid-event>` has exactly one line. The confirming
`Reported 0, ... duplicate-skipped-events=1` line in the same tick's summary refers to sid
A being correctly re-recognised as already-ledgered — not sid B, which is the tick's own
`Reported 1`.

### The `owners/` backfill — a fourth difference category (not induced-session traffic)

**`owners/` holds 1,941 records where G-7's three permitted categories account for only
2.** The two induced sessions (A, B) each hold one `event`-content record — squarely
category 2, "the two induced sessions' own consequential records." **The other 1,939
records, all `legacy`-content, are a genuinely new, fourth category — a consequence of
35-03's rollback leg leaving `env` at `legacy=enabled` for ~17 minutes on a profile
carrying a large pre-existing legacy backlog, not a consequence of anything induced.**

**What wrote them, read from the deployed `hermes-report.sh` source, not inferred:**
`hermes-report.sh`'s per-session SESSION OWNERSHIP RESOLUTION (quick-260817-tfe,
OWN-01/OWN-02/OWN-04) runs once per session, on any tick the global
`legacy completions path disabled` short-circuit does NOT engage — i.e. any tick where
`env` reads `legacy` as something other than cleanly disabled-and-drained. During the
~17 minutes `env` read `legacy=enabled` (`23:23:21Z`–`23:40:38Z`), two full legacy cycles
ran, and for every one of the 1,939 sessions already present in `revenium-hermes.ledger`
with no corresponding row in `revenium-api-events.ledger`, the resolution table (the same
table `api-event-report.sh` implements identically) resolved to `legacy` — a durable
one-line backfill record, not a new bill.

**Benign, checked exhaustively rather than assumed:** the legacy ledger's sha256 is
byte-identical before and after (`c56ff946...c359f6815`, both) — no new `HERMES:` line
accompanies any of the 1,939 records. Every one of the 1,939
`legacy`-owner sids has a pre-existing `HERMES:` ledger line (checked by exhaustive set
difference against the ledger's 1,939 distinct sids — the difference is empty); none is a
new, un-backfilled claim. Zero owner records anywhere on the profile hold more than one
line — the double-bill signature is absent everywhere, not just among the 1,939.

**Forward effect, investigated read-only:** for a `legacy`-owned sid whose ledger history
is closed and unchanging (the overwhelming majority of the 1,939), owner=`legacy` changes
nothing going forward, because neither stage's per-session loop evaluates a dormant sid
again regardless (legacy stays globally short-circuited while `env` reads
`legacy=disabled`+drained; the event-side loop only evaluates sids with fresh
`post_api_request` events). For the theoretical case of one of these sids resuming
activity, the practical outcome does not depend on whether this rehearsal ran: both
stages' resolution tables read the SAME unchanged ledger content, so the first evaluation
of that sid's ownership — whenever it happened, rehearsal or no rehearsal — would resolve
to `legacy` identically. The staleness self-healing chain (`docs/event-metering.md`'s
`### Staleness` → "The self-healing chain") that re-admits a resumed session to legacy
billing operates on `drain-status.sh`'s own `legacyRetainedSids` carve-out, independent of
`owners/`. **This is a read-only, source-grounded finding, not an exhaustive proof that no
host-specific edge case exists** — stated at this strength deliberately, per the plan's own
instruction to report "undetermined" rather than overclaim where the read-only method
cannot fully settle a question.

**Disposition: ROADMAP criterion 7 ("post state matches pre state") is NOT MET AS
WRITTEN.** Exactly three difference categories were permitted; a fourth exists, is real,
and is written up here as the criterion's own text requires rather than absorbed into a
caption or explained away. It is benign by every check this document ran, and its forward
effect is null by the same read-only investigation — but "benign" is not "permitted," and
this document does not soften that distinction. See `## Verdict` for how this shortfall is
carried forward.

## Reproducing this measurement

Every command below is generically parameterised — substitute a real profile name,
session id, or timestamp for the placeholder and it runs as written. Placeholders in this
section are single hyphen-free tokens (`<profile>`, `<sid>`, `<stamp>`, `<fleethost>`,
`<from>`, `<to>`), never the hyphenated redaction placeholders used elsewhere in this
document (`<induced-sid-legacy>`, `<profile-state-dir>`, etc.) — those resolve only via
`35-EVIDENCE.md`'s map, per this phase's own naming convention.

**Read this preamble before running any of the commands below.**

- **The restore target for the rollback leg is `env.bak2-<stamp>`, NEVER `env.bak-<stamp>`
  (no "2").** The `bak2` backup keeps `REVENIUM_EVENT_METERING_MODE=live`; the plain
  `bak` backup ALSO reverts `mode` to `shadow`, which would drag in the mode-aware
  takeover and abstention hazard chain `docs/event-metering.md` documents at length —
  none of which this rehearsal has any reason to exercise. Confirm the target file's own
  content before restoring it (`cat`, not `ls`); never restore by filename pattern alone.
- **No gateway restart step exists anywhere below, deliberately.** `cron.sh` sources
  `ENV_FILE` fresh every tick under `set -o allexport`, and the fleet's crontab runs every
  minute (D-5) — an `env` edit takes effect on the very next tick. Adding a `systemctl`
  restart would introduce a real, avoidable disruption this rehearsal did not ask for, and
  a second variable that makes the timing evidence ambiguous (was the effect from the env
  change, or the restart?).

**Step 1 — snapshot the LIVE cutover state. This is the literal first command of the
whole rehearsal, before any other read or write.**
```bash
d="<profile-state-dir>"
ssh <fleethost> "cp \"$d/env\" \"$d/env.pre-rehearsal-<stamp>\""
```

**Step 2 — rollback leg: restore `env.bak2-*` (mode stays `live`, legacy re-enabled).**
```bash
d="<profile-state-dir>"   # set in EVERY block: each is meant to be runnable alone
ssh <fleethost> "cat \"$d/env.bak2-<stamp>\""   # confirm content before restoring
ssh <fleethost> "cp \"$d/env.bak2-<stamp>\" \"$d/env\""
```

**Step 3 — induce one session, wait for a cron tick (up to
`REVENIUM_CRON_SETTLE_SECONDS`=600s worst case if the classifier sentinel lags), then
observe against Prediction A.**
```bash
d="<profile-state-dir>"   # set in EVERY block: each is meant to be runnable alone
ssh <fleethost> "HERMES_HOME=<profile-home-dir> bash -lc \
  'hermes chat -Q --max-turns 2 -q \"Reply with the single word PONG. Do no other work.\"'"
ssh <fleethost> "tail -f \"$d/revenium-metering.log\""   # observe, then interrupt
ssh <fleethost> "grep '^HERMES:<sid>:' \"$d/revenium-hermes.ledger\""
ssh <fleethost> "grep '<sid>' \"$d/revenium-metering.log\" | grep 'D-09 partition'"
ssh <fleethost> "grep '<sid>' \"$d/revenium-api-events.ledger\""   # must be empty
```

**Step 4 — cutover leg: restore `env` from the STEP-1 SNAPSHOT (never by retyping literal
values), confirm the restore, then induce the second session and observe against
Prediction B.**
```bash
d="<profile-state-dir>"   # set in EVERY block: each is meant to be runnable alone
ssh <fleethost> "cp \"$d/env.pre-rehearsal-<stamp>\" \"$d/env\""
ssh <fleethost> "diff \"$d/env\" \"$d/env.pre-rehearsal-<stamp>\""   # must be empty
ssh <fleethost> "HERMES_HOME=<profile-home-dir> bash -lc \
  'hermes chat -Q --max-turns 2 -q \"Reply with the single word PONG. Do no other work.\"'"
ssh <fleethost> "grep 'Reported: sid=<sid>' \"$d/revenium-metering.log\""
ssh <fleethost> "grep '<sid>' \"$d/revenium-api-events.ledger\""
ssh <fleethost> "grep '<sid>' \"$d/revenium-hermes.ledger\""   # must be empty
```

**The confirming `diff`, restated as its own step because G-7 requires it be an explicit,
separately-invoked action rather than assumed:**
```bash
d="<profile-state-dir>"   # set in EVERY block: each is meant to be runnable alone
ssh <fleethost> "diff \"$d/env\" \"$d/env.pre-rehearsal-<stamp>\""
```
An empty `diff` here covers the `env` file only — it is not, by itself, the full
pre-versus-post comparison G-7 requires. `## Independent confirmation` below extends this
to every other state file the rehearsal could plausibly have touched.

**Step 5 — read a session's ownership record**, the single file that decides which path a
given sid will be billed by, going forward, on every subsequent tick.
```bash
d="<profile-state-dir>"   # set in EVERY block: each is meant to be runnable alone
ssh <fleethost> "cat \"$d/owners/<sid>\""            # exactly one line: 'legacy' or 'event'
ssh <fleethost> "wc -l \"$d/owners/<sid>\""           # must be 1 — a 2-line file is the double-bill signature
```

**Step 6 — the full pre/post state-capture set**, run identically before and after any
mutation to produce a comparable pair (this is 35-02's own replayable block, reused
verbatim by this document for the post-state capture above):
```bash
ssh <fleethost> "
  d=<profile-state-dir>
  echo '=== cat env ==='; cat \"\$d/env\"
  echo '=== sha256sum env ==='; sha256sum \"\$d/env\"
  echo '=== env.bak* filenames ==='; ls -la \"\$d\"/env.bak* 2>&1
  echo '=== env.bak* content + sha256 ==='
  for f in \"\$d\"/env.bak*; do echo \"--- \$f ---\"; cat \"\$f\"; sha256sum \"\$f\"; done
  echo '=== full ls -la of state dir ==='; ls -la \"\$d\"
  echo '=== ledger line counts + sha256 ==='
  wc -l \"\$d\"/revenium-hermes.ledger \"\$d\"/revenium-api-events.ledger
  sha256sum \"\$d\"/revenium-hermes.ledger \"\$d\"/revenium-api-events.ledger
  echo '=== owners dir ==='; [ -d \"\$d\"/owners ] && ls -la \"\$d\"/owners || echo ABSENT
  echo '=== drain-status.json full ==='; cat \"\$d\"/drain-status.json
  echo '=== state.db session count ==='
  sqlite3 -readonly <profile-home-dir>/state.db 'select count(*) from sessions;'
  echo '=== tail revenium-metering.log (20 lines) ==='; tail -20 \"\$d\"/revenium-metering.log
"
```
Re-running this exact block, before and after, and diffing the two outputs item by item is
what `## Independent confirmation` below is built from — not a summary, the literal
command pair.

## Independent confirmation

**The post-state was captured by re-running 35-02's own replayable command block
verbatim** — identical commands, identical order, identical profile — reproduced in full
in `35-EVIDENCE.md`. What follows is the itemised pre-versus-post comparison G-7 requires:
every item the pre-state captured, one row per item, marked IDENTICAL or carrying a named
difference and its cause.

| Item | Pre-state (35-02, 2026-08-20) | Post-state (35-04, 2026-08-21) | Comparison |
|---|---|---|---|
| `env` content | `mode=live`, `legacy=disabled`, `stale=86400` | identical | **IDENTICAL** |
| `env` sha256 | `6ec48b84...9ddd4a` | `6ec48b84...9ddd4a` | **IDENTICAL** — compared against 35-02's own originally captured value directly, not only against the 35-03 snapshot file |
| `env.bak-20260819-211250` content + sha256 | `mode=shadow`, `legacy=enabled`; `cf7f9767...30e02ad` | identical | **IDENTICAL** |
| `env.bak2-20260819-213357` content + sha256 | `mode=live`, `legacy=enabled`; `8bef65b2...b997e601` | identical | **IDENTICAL** |
| `env.pre-rehearsal-20260820-232301` | did not exist | present, 106 bytes, matches `env`'s pre-rehearsal sha256 | **Category 1 (permitted)** — the retained snapshot file, kept rather than deleted because nothing reads `env.*` except `env` itself and the host already carries two backups by the same naming convention; a real difference from the pre-state listing, declared rather than omitted |
| `revenium-hermes.ledger` line count | 2285 | 2285 | **IDENTICAL** |
| `revenium-hermes.ledger` sha256 | `c56ff946...c359f6815` | `c56ff946...c359f6815` | **IDENTICAL, byte-for-byte** — the strongest form of "nothing rewritten, reordered, or dropped"; not merely a prefix match, an exact match |
| `revenium-api-events.ledger` line count | 0 | 2 | **Category 2 (permitted)** — the two induced sessions' own ledger lines |
| `revenium-api-events.ledger` sha256 | `e3b0c442...b7852b855` (well-known empty-file hash) | `74fcdae3...c237c05bd20` | **Category 2** — pre-state content (empty) is trivially a complete prefix of post-state content; on a profile with zero pre-existing event-ledger lines this prefix guarantee is total, not merely strong |
| `owners/` directory | ABSENT | EXISTS, 1,941 entries | **Split across categories 2 and 4** — see below |
| `state.db` session count | 1977 | 1979 | **Category 2** — exactly `+2`, the two induced sessions, individually enumerated below |
| `revenium-metering.log` size | 12,134,129 bytes | 12,176,864 bytes | **Category 3 (permitted)** — log growth; the pre-state's last recorded line (`2026-08-20T21:24:36Z`) is the boundary separating pre-existing lines from this phase's own |
| `drain-status.json` (`drainedCount`, `legacyRetainedSids`) | `886`, 8 entries | `857`, 0 entries | **Dynamic recomputed state, not a durable record** — `drain-status.sh` re-derives this file from live inputs every tick regardless of this rehearsal (`docs/event-metering.md`'s own "self-healing chain"); the ~3h elapsed between captures is enough for ordinary session-lifecycle aging to move sessions between the gate's own retained/drained accounting, independent of any switch this rehearsal flipped. Not counted as a fifth category because it is neither retained nor durable — the same reasoning that places `revenium-metering.log`'s own growth outside the three-category count |
| `revenium-jobs.ledger` size | 31,331 bytes | 31,491 bytes | **Category 2** — two new `JOB:` lines for the two induced sessions' own agentic-job records |
| `task-taxonomy.json` / `job-taxonomy.json` size | 1,397 / 399 bytes | 1,522 / 534 bytes | **Category 2** — new task-type/job-type vocabulary entries the classifier minted for the two induced sessions' own classifications |
| All other state-directory files (`config.json`, `guardrail-status.json`, `plugin-status.json`, `revenium-tool-events.ledger`, the three `.lock` files, `cron.lock`) | present | present, unchanged | **IDENTICAL** |

**`owners/` itself, enumerated:** 1,941 total records — 2 hold `event` (the two induced
sessions, category 2) and 1,939 hold `legacy` (a backfill side effect of 35-03's
~17-minute `legacy=enabled` window on a profile with a large pre-existing legacy backlog
— **category 4, permitted by none of the three named categories**). See `## Findings` →
"The `owners/` backfill" for the full investigation (what wrote them, why they are
benign, and why their forward effect is null by read-only source inspection).

**Disposition, stated plainly rather than redefined to fit:** three of the four
differences found are exactly the three G-7 permits, each named with its cause above. The
fourth — 1,939 `legacy`-content `owners/` records — is not one of them, and this document
does not fold it into category 2 to make the count come out clean. **ROADMAP criterion 7
("post state matches pre state") is therefore NOT MET AS WRITTEN.** The profile was
returned to its pre-rehearsal `env` configuration, byte-for-byte, and its pre-existing
billing ledger is byte-identical — but a fourth kind of state (durable ownership
metadata for 1,939 sessions this rehearsal did not touch, did not bill, and did not
double-bill) now exists where none did before. That is a real difference from "the profile
was returned to exactly its pre-rehearsal state," not a technicality.

**No-data-loss / no-double-ship enumeration, to Phase 34's standard — named sessions, not
counts:**

| Sid | `owners/<sid>` | In `revenium-hermes.ledger`? | In `revenium-api-events.ledger`? | Double-ship? |
|---|---|---|---|---|
| `<induced-sid-legacy>` (induction A, 35-03) | 1 line, `event` | No (fresh full-file grep) | Yes — 1 line | **No** — exactly one path shipped it |
| `<induced-sid-event>` (induction B, 35-04) | 1 line, `event` | No (fresh full-file grep) | Yes — 1 line | **No** — exactly one path shipped it |

Both induced sids were checked against BOTH ledgers individually. Neither appears in both.
The pre-existing legacy ledger's byte-identical sha256 (above) additionally confirms that
none of the 2,285 pre-existing lines were rewritten, reordered, or duplicated, and the
1,939-record `owners/` backfill (above) carries no ledger line of its own — a `legacy`
owner record with no accompanying `HERMES:` append cannot be a double-ship signature by
construction, and the direct check (zero owner files anywhere on the profile hold more
than one line) confirms none exists.

**`_takeover_session_owner`'s unreachability, stated with its condition and cited:** this
mechanism fires only when a session's owner already reads `event` AND the event-metering
mode has reverted to `shadow` — the `else` branch at `hermes-report.sh:1644-1645`, reached
only when neither `EVENT_PATH_LIVE` nor `sid_legacy_suppressed` holds (MODE-05, the
condition at `hermes-report.sh:1609-1645`). `REVENIUM_EVENT_METERING_MODE`
stayed `live` throughout every leg of this rehearsal — the rollback leg only ever moved
`REVENIUM_LEGACY_COMPLETIONS`. A live grep of the full post-rehearsal log for `takeover`
and for the dual-ledger warn string returns nothing, confirming the mechanism never fired,
by construction, exactly as `## What was measured`'s ownership prediction stated in
advance. Its absence here is a designed non-event, not an untested code path.

**Token figures, captioned per G-8's own asymmetry rule:** no token total is read out of
or inferred from `revenium-api-events.ledger` anywhere in this document — that ledger's
lines carry no token field. Any token figure this document states for an event-billed
session, where one appears, is sourced from Revenium's own read side or a not-yet-pruned
spool file, named as such.

## Verified against

**Date and method.** Live SSH reconnaissance and read-only state capture on 2026-08-20
(35-02), the live rollback leg and induction A on 2026-08-20 (35-03), and leg B, the
POST-state capture, and the `owners/` backfill investigation on 2026-08-20/21 (this plan).
All read commands were `cat`, `ls`, `wc`, `sha256sum`, `sqlite3 -readonly`, `grep`,
`python3` reading JSON, and `awk`; all write commands were exactly the four G-2-permitted
writes (the snapshot `cp`, the rollback-restore `cp`, the cutover-restore `cp`, and the two
`hermes chat` inductions) — no `systemctl`, no `crontab`, no `rsync`, no mutating
`revenium` verb, anywhere across all three plans.

**Host discipline (redacted).** All live work ran against one fleet host (identity
redacted per G-6/G-3) over SSH with a named private key (redacted), targeting exactly one
profile, `devops`, of the fleet's ten. No other profile was read or written by this phase.

**What is deliberately redacted, and why.** Two induced raw session ids
(`<induced-sid-legacy>`, `<induced-sid-event>`) are redacted throughout, because a raw sid
is directly correlatable to a real, billed Hermes session and its own transcript. The
fleet host's IPv4 address, its SSH key filename, and its login-user prefix in the SSH
target string are redacted per G-3/G-6, because together they are sufficient to connect to
the host. Two
profile filesystem paths (`<profile-state-dir>`, `<profile-home-dir>`) are redacted
because each embeds the host's own directory layout alongside the profile name. Composite
values that embed a raw sid (an `api_request_id`, or the `event:<api_request_id>`
transaction id it would become in Revenium) are never quoted whole; where their SHAPE
matters, generic non-identifying template tokens (`<uuid>`, `<hash>`) stand in for the
non-sid segments, reusing the already-redacted sid placeholder for the sid segment. sha256
hashes of file content (`env`, the two ledgers) are quoted directly, truncated for
brevity, and are NOT treated as identifiers requiring a map entry — a content fingerprint
does not name a session, a host, or a person, and truncating them (rather than redacting
them) follows the same convention 35-02 and 35-03 already established for this document.

**The four-part redaction proof, run now, counts recorded:**

1. **Map completeness.** Every raw identifier this phase's live work touched — both
   induced sids, both `api_request_id` composites, the profile state-directory and
   home-directory paths, the fleet host's address/key/login string, the fleet host's own
   `hostname` output — has a row in `35-EVIDENCE.md`'s placeholder map (10 rows total
   across 35-02's original map and this plan's additions; 2 rows reserved/not-yet-deployed
   for future use, `<induced-sid-event>` moved from reserved to USED by this plan).
2. **Per-entry absence**, each raw value from `35-EVIDENCE.md`'s map searched
   individually against this document, not by one combined pattern: both induced sids,
   the profile home-directory path prefix, the fleet host's own `hostname` output, the
   fleet host's IPv4 address, and the SSH key filename each returned zero hits, checked
   one at a time (six individual `grep -c` invocations, six zero counts — the literal raw
   values are intentionally not reproduced in this section, since quoting them here would
   itself be the leak this check exists to rule out).
3. **Per-entry presence**, each hyphenated placeholder actually appearing in the tracked
   document confirmed to have a map row: `<induced-sid-legacy>`, `<induced-sid-event>`,
   `<profile-state-dir>`, `<profile-home-dir>` — **4 distinct placeholders**, all four
   present in `35-EVIDENCE.md`'s map, checked individually. One further placeholder
   remains reserved in the map for the fleet host's own `hostname` output but is not
   deployed anywhere in this document, by design — nothing in the tracked prose currently
   needs it.
4. **Shape sweep outside the regex gate's four patterns** — UUIDs, long hex runs,
   `<label>_<hex>` job-style strings, bare hostnames — run against the finished document:
   zero UUID-shaped hits; one long-hex-run hit, the legacy ledger's own truncated sha256
   (a content fingerprint, not an identifier, per the redaction convention stated above);
   zero `<label>_<hex>` job-style strings; zero bare hostname hits.

**Placeholder count, derived from the document at the moment of writing, not carried
forward from an earlier wave:** `grep -oE '<[a-z][a-z-]*-[a-z-]*>' docs/rollback-rehearsal.md | sort -u`
finds **4** distinct hyphenated redaction placeholders in the finished document.

**The file-wide regex gate** (an IPv4 shape, the SSH key filename shape, the login-prefix
shape used in the SSH target string, and the raw-sid timestamp shape) produces zero
matches on the finished document — run as a screen, not accepted as the proof; the four
checks above are the proof.
