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

## Results

*Filled by 35-03 (the round trip itself, step by step) and finalized by 35-04 (the
restoration proof).*

## Findings

*Filled by 35-03 — one named subsection per induced session, with its exact log line and
ledger line.*

## Reproducing this measurement

*Filled below, by this plan's own Task 2, before either induction runs.*

## Independent confirmation

*Filled by 35-04 — the byte-identical `diff` between the pre-rehearsal snapshot and the
finally-restored `env`, plus the full pre-versus-post state comparison G-7 requires.*

## Verified against

*Filled by 35-04 — a consolidated date, method, and redaction-proof statement covering
all of 35-02, 35-03 and 35-04's own live work, following the same pattern
`docs/transition-reconciliation.md`'s own closing section used.*
