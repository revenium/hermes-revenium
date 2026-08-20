# Rollback Rehearsal on `devops` — Setup Complete, Both Predictions Committed; Round Trip Not Yet Performed (PROVISIONAL — disposition finalized by 35-04)

## Verdict

*This section is filled by 35-04, once the round trip (35-03) has run and the restoration
proof is complete. As of this plan (35-02), no fleet mutation has occurred — this document
currently records only the rehearsal's setup: live candidacy re-verification, the
pre-rehearsal state capture, this document's own skeleton, and both inductions'
predictions, committed ahead of either induction actually running.*

## Why this document exists

The planning directory that captured this measurement is excluded from version control,
so this file is the committed mirror of the headline findings and the replayable method.
Once 35-04 registers this document in `tests/test_repository.py::test_expected_files_exist`
(D-4 — that pin is deliberately added last, after this file exists), deleting it turns the
repository's own test suite red, which is the whole point: a verdict that only exists in
an untracked directory is a verdict that did not happen.

## What was measured

**This rehearsal is the milestone's first deliberate write to the live fleet, and as of
this plan (35-02) it has not yet been performed.** What follows is the setup that makes
the eventual round trip provable: which profile, from which exact backup, and what the
four-step sequence will be — plus, added by this plan's Task 2 below, both inductions'
predicted outcomes, committed before either induction runs.

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

**The four-step sequence, planned but not yet executed:**
1. Snapshot the live `env` to `env.pre-rehearsal-<stamp>` — the literal first command,
   before any other write.
2. Restore `env.bak2-20260819-213357` over `env` — the rollback leg (`legacy=enabled`,
   `mode=live`).
3. Induce one session; observe legacy resume and the event path defer.
4. Restore `env` from the step-1 snapshot — the cutover leg — and induce a second
   session; observe the event path resume.

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
at both ends. This rehearsal's own live work in this plan executed no earlier than
2026-08-20T21:00Z, and the round trip itself (35-03) runs later still — well after the
window closed. Any pre-existing ledger or read-side figure this document draws on that
falls inside that window is labelled suspect, exactly as Phase 34 did, and never chased as
a metering defect caused by this rehearsal.

**Cost is `$0` by operator decision — not a metering defect.** Every `$0` /
`totalCost: 0` figure this rehearsal's evidence shows carries this caption: cost is `$0`
by operator decision in this pre-prod tenant (CUT-08); **BACK-2676** (Revenium-side
provider-slug drift) remains the prerequisite before a production tenant would show
non-zero cost for these completions. The two induced sessions this rehearsal creates will
themselves produce `$0` rows; that is expected and captioned, not a finding.

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
"legacy resumed" and "the event path deferred" are claims about behaviour on new activity,
and an idle profile has none of its own. Without the two induced sessions above, this
rehearsal would prove only that nothing happened on `devops`, which is equally true
whether or not the rollback mechanism actually works — this is why D-3 authorizes real
traffic rather than passive observation, and why the "zero owners records" fact must not
be read as unqualified good news on its own.

## Results

**The round trip did not complete both legs.** Leg 1 (the rollback leg, `env.bak2-*`
restored + induction A) ran to completion and produced a result — but that result
**falsified Prediction A**, and the falsification's own evidence made Task 3's own
precondition (a confirmed `HERMES:` ledger line for induction A) impossible to satisfy by
further waiting. Per the plan's own halt discipline, Task 3 (the restore leg + induction
B) was **not started**; `env` was nonetheless returned to the cutover state as an
emergency-recovery action, which `<halt_and_recover>` requires independent of which task
performs it.

| Step | What was attempted | Artifact | Outcome |
|---|---|---|---|
| 1. Snapshot | `cp` live `env` to `env.pre-rehearsal-<stamp>` | sha256 match between snapshot and live `env` (`6ec48b84...9ddd4a`, both) | Done |
| 2. Rollback restore | `cp env.bak2-20260819-213357` over `env` | Read-back `env` sha256 `8bef65b2...b997e601`, matching `env.bak2-*`'s own sha256; write timestamped `2026-08-20T23:23:21Z` | Done |
| 3. Rollback took effect | Poll `revenium-metering.log` for a post-write tick | Tick at `2026-08-20T23:24:21Z`-`23:24:26Z`, strictly later than the write; the `legacy completions path disabled` line, present at every prior tick, absent from this one (corroboration) | Done |
| 4. Induce session A | `hermes chat` on `devops` | New session id (redacted `<induced-sid-legacy>`); `.ready/<induced-sid-legacy>` sentinel present within 30s | Done |
| 5. Legacy claims A (Prediction A) | Poll `revenium-hermes.ledger` for `HERMES:<induced-sid-legacy>:` | No such line appeared after 600s of polling, nor at any point afterward (see Findings) | **FALSIFIED** — the event path claimed A instead |
| 6. Event path defers on A (Prediction A, corroborating half) | Poll for the D-09 skip line | No D-09 skip line appears anywhere in the post-rollback log | **Also contrary to the predicted shape** — see Findings for why the D-09 mechanism was never the deciding factor here |
| 7. Restore leg (env, Task 3) | `cp env.pre-rehearsal-<stamp>` back over `env` | Diff empty, sha256 `6ec48b84...9ddd4a` matches both the snapshot and the pre-rehearsal capture; write timestamped `2026-08-20T23:40:38Z` | Done, **as an emergency-recovery action**, not as Task 3's normal completion |
| 8. Induce session B (Task 3) | — | — | **Not performed.** Task 3 was never entered; its own precondition (A's `HERMES:` line) could not be satisfied |
| 9. Post-restore tick confirms restore took effect | — | — | **Deferred to 35-04.** The first tick to run entirely under the restored env had not completed when this plan's execution stopped (a legacy cycle was still mid-run) |

Full raw evidence, including the source-level investigation into why the claimed
mechanism did not hold, is in `35-EVIDENCE.md`.

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

### Induced session B (restore leg) — not performed

Task 3, which would induce and observe a second session under the restored cutover
state, was never started. Its own `<precondition>` requires a confirmed `HERMES:` ledger
line for induction A before Task 3 may begin; per the finding above, that line will never
appear (the guard that determines it resolved, permanently, at `2026-08-20T23:23:21Z` +
~7 minutes, well inside the plan's own 600-second settle budget for a single poll but past
the point where continued waiting could change the outcome). No second `hermes chat`
session was induced. `env` was returned to the cutover state as the `<halt_and_recover>`
block requires regardless of which task performs the restore, and that restoration is
recorded in `## Results` above and confirmed with an empty `diff` and a matching sha256.

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
ssh <fleethost> "cat \"$d/env.bak2-<stamp>\""   # confirm content before restoring
ssh <fleethost> "cp \"$d/env.bak2-<stamp>\" \"$d/env\""
```

**Step 3 — induce one session, wait for a cron tick (up to
`REVENIUM_CRON_SETTLE_SECONDS`=600s worst case if the classifier sentinel lags), then
observe against Prediction A.**
```bash
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
ssh <fleethost> "diff \"$d/env\" \"$d/env.pre-rehearsal-<stamp>\""
```
An empty `diff` here covers the `env` file only — it is not, by itself, the full
pre-versus-post comparison G-7 requires. `## Independent confirmation` (35-04) extends
this to every other state file the rehearsal could plausibly have touched.

## Independent confirmation

*Filled by 35-04 — the byte-identical `diff` between the pre-rehearsal snapshot and the
finally-restored `env`, plus the full pre-versus-post state comparison G-7 requires.*

## Verified against

*Filled by 35-04 — a consolidated date, method, and redaction-proof statement covering
all of 35-02, 35-03 and 35-04's own live work, following the same pattern
`docs/transition-reconciliation.md`'s own closing section used.*
