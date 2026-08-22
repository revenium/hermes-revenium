# Milestone v1.4 — Cutover Validation & Convergence — closeout

Git-tracked per CUT-07 (`.planning/` is gitignored). Companion to
`docs/cutover-convergence-and-read-side-proof.md`,
`docs/transition-reconciliation.md`, and `docs/rollback-rehearsal.md`, which
carry the phase-level evidence this document closes over.

Scope: phases 33, 34, 35. Phases 31–32 belong to v1.3 and are closed out in
`docs/milestone-v1.3-closeout.md`.

## Convergence re-sample — 2026-08-21T22:5xZ

Phase 33 closed its observation window on 2026-08-20 with 8/10 profiles
converged, recording `gtm` and `community` as the two CUT-01 did not close for.
This is a later reading of the same fleet host, taken without touching any
profile.

| profile | drained | pending / tracked |
|---|---|---|
| cfo | yes | 0 / 34 |
| coder | yes | 0 / 101 |
| community | **yes** | 0 / 3 |
| devops | yes | 0 / 688 |
| **gtm** | **no** | **1 / 56** |
| lorekeeper | yes | 0 / 33 |
| marketing | yes | 0 / 186 |
| playtester | yes | 0 / 5 |
| pm | yes | 0 / 25 |
| qa | yes | 0 / 20 |

**9/10 converged.** `community` converged between phase 33's close and this
sample — unattended, which is the point below.

`gtm`'s single remaining session is `20260724_080054_dcaa580b`, age 14.8h
against an effective stale threshold of 87,000s (24.17h). It is correctly
`stale: false`: it has not yet aged into the staleness route. Computed earliest
convergence ≈ **2026-08-22T08:00Z**. Nothing about it is diagnosed as stuck —
it is a session the drain gate has not yet been allowed to release.

## The "without manual intervention" clause is now evidenced, not merely unattested

Phase 33 could prove only a negative: no `env` file bore an mtime later than the
cutover flip window. That ruled out an edit but did not demonstrate the fleet
converging on its own.

Two things demonstrate it now:

1. **`community` converged with no intervention.** Phase 33 recorded it at 1
   pending, cause unchanged throughout its window, earliest convergence
   ≈2026-08-20T21:33Z. It is drained at this sample. Nothing was run against it
   in between.
2. **The `env` mtimes still hold.** Nine of ten remain at the identical
   `2026-08-19 21:33:57` flip timestamp. `devops` is later
   (`2026-08-20 23:40:38`) and that is the phase-35 rollback rehearsal
   (`docs/rollback-rehearsal.md`), which deliberately restored env from backup
   and back — a documented, intended write, not a stealth manual step. Phase 33's
   flat claim that "none is later" is superseded by this one exception, named
   here rather than left to contradict a reader's own `stat`.

## Measurement hazard found during this re-sample

`drain-status.sh` reads `REVENIUM_DRAIN_STALE_SECONDS` from the environment and
**rewrites `drain-status.json`** as a side effect. Run by hand without sourcing
the profile's `<state>/env` first — which is how an operator naturally runs it —
it falls back to the built-in 604800s (7-day) default instead of the profile's
configured 86400s, and then persists that reading over the cron's.

The first pass of this re-sample did exactly that and produced a false picture:
`gtm` appeared to have regressed from 2 pending to 5, and `community` appeared
still pending. Sourcing the env as `cron.sh` does gave 87,000s effective and the
table above. The wrong numbers were written into `drain-status.json` for both
profiles before the correct run overwrote them.

This is the same class of defect as a diagnostic that mutates the state it is
diagnosing. Recorded here as a finding against the tooling, not the fleet.

## Success criteria at close

| # | Criterion | Disposition |
|---|---|---|
| 1 | 10/10 billing through the event path, converged, no manual step | **9/10 CONVERGED; the tenth has a computed bound, not a diagnosis of failure.** The no-manual-step clause is now positively evidenced (see above), upgraded from UNATTESTED. |
| 2 | Every non-cost dimension confirmed read-side | MET (2026-08-20) |
| 3 | No gap and no double count across the boundary | MET WITH NAMED SHORTFALLS — 5 of 10 profiles; 112,603-token residual before a correction of undetermined scope; 50,731 tokens Revenium's own confirmed write-loss |
| 4 | Rollback demonstrated | MET WITH NAMED SHORTFALLS — one leg falsified and root-caused, one confirmed but output-identical; restoration criterion 7 **NOT MET AS WRITTEN** |
| 5 | Operator doc no longer misleads | MET, corrected twice |

## Still open at close

- `agenticJobId` absent from metered rows while the jobs ledger advances locally
  — unresolved in either direction.
- Multi-model attribution unproven; the sampled profile runs one model.
- The 2026-08-19 Revenium dev outage **accepted writes and discarded them**
  while returning success. Distinct from the 500s, and possibly still latent.
- CUT-05's restoration criterion 7, NOT MET AS WRITTEN, with the `owners/`
  backfill category fully characterised in `docs/rollback-rehearsal.md`.
