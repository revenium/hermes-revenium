# Milestone v1.3 — Metering Completeness

*Closed 2026-08-19. Kept in `docs/` because `.planning/` is gitignored — a
milestone record that lives only there does not survive.*

**Phases 31–32 · 2026-08-15 → 2026-08-19 · 31 commits · 101 files · +21,604/−181**
**Closeout type: `override_closeout`** — shipped with three requirements explicitly
deferred, not silently dropped. See "Deferred" below.

## What this milestone was for

Make every metered row carry the truth about what produced it: close the
auxiliary-usage gap if it proved material, then move metering off cron-polling a
session database and onto in-process `post_api_request` events, so a row is
produced by the API call that incurred it rather than reconstructed from summary
counters up to a minute later.

## Phase 31 — Auxiliary Usage Metering — CLOSED UNBUILT

Closed on its own pre-committed gate. D-02 fixed ≥1% fleet auxiliary cost share
as the build threshold *in advance*; the measurement across all ten metered
profiles' whole retained history returned **0.4598%** cost share (0.1042% token
share). Per the gate's own rule the phase closed without writing the reporter
change, and spike P-D was promoted into its slot as Phase 32.

Evidence: `docs/internal/auxiliary-usage-sizing.md`.

Three facts that outlived the phase and must not be rediscovered:

- `session_model_usage` carries a **main-loop mirror** in its empty-`task`
  bucket; any query omitting `WHERE task != ''` double-meters every already
  reported main-loop token.
- Its identity key is **six** columns, not four.
- The real native `task` vocabulary fleet-wide is **three** values
  (`title_generation`, `approval`, `compression`) — `approval` dominates and was
  not in the originally assumed five-value list; three of those five have zero
  rows ever.

## Phase 32 — Event-Driven Metering on `post_api_request` — WAVES 1–6 SHIPPED

All five phase success criteria MET:

| # | criterion | status |
|---|---|---|
| 1 | rows from `post_api_request` keyed on `api_request_id`, no delta scaling | met |
| 2 | re-delivery produces no second row — **proven live, not by fixtures** | met (PR #59) |
| 3 | gateway turns meter from the usage summary, not a response attribute | met |
| 4 | multi-model sessions attribute per call via `response_model` | met |
| 5 | the guardrail-polling half of the cron keeps running | met (re-verified on the fleet 2026-08-19) |

Six billing-correctness defects were found by the canary and fixed before close —
each one a path where the legacy and event halves could both bill, or neither:

- cross-profile double-ship: the event path shipped one session from all ten
  profiles (idempotency had been tested across ticks, never across profiles)
- durable atomically-claimed session ownership record (#54)
- mode-aware legacy takeover for the event-owned / mode-revert hazard (#56)
- drain gate taught staleness, with a per-session legacy carve-out (#57)
- legacy must not claim a session it will never bill (#58)
- the event path's model-name normalization, **reverted** (#60) once measurement
  showed its premise was wrong — see below

## Deferred — NOT met, recorded deliberately

| req | what it wanted | why deferred |
|---|---|---|
| EVT-12 (part) | the reporter *refuses* a disable request while the drain gate says otherwise | enforcement half lives in 32-07, unbuilt |
| **EVT-15** | canary rows confirmed on Revenium's read side **including non-zero server-side cost** | **definitionally blocked**: the event path deliberately ships no cost, so this cannot pass until the catalog resolver prices those models |
| EVT-16 | the fleet meters completions through the event path | the cutover itself |

**Blocker: [BACK-2676](https://linear.app/revenium/issue/BACK-2676) — provider-slug
drift.** Measured 2026-08-11→08-19 across 12,958 rows: **84.0% of recorded spend
is client-supplied** via the legacy path's `--total-cost`, and the event path
sends none by design (C-8). Cutting over before the resolver is fixed would zero
84% of the dollar figure Revenium reports. The three affected models are all
provider-slug drift with a catalog entry that already exists.

**Consequence, stated plainly: the event path is built, proven, and DEPLOYED —
and inert.** The fleet is uniform at `EVENT_METERING_MODE=shadow` with legacy
enabled, so completions still bill through the legacy path. Nothing about this
milestone changed what bills today.

## Also closed in this milestone

- **Phase 19 SC-8** — the last v1.1 deferral — closed against a **real breached
  rule** (`docs/internal/halt-enforcement-live-verification.md`). 19-12 had recorded it MET
  against *synthetic* fixtures; the live path had never run. Found and fixed two
  pre-existing defects: a warn rate-limit defeated by a per-second sentinel key,
  and `clear-halt.sh` buying only one tick against a still-breached rule (#64, #65).
- **Capability-probe hardening** — all four raw `grep -q` probes moved to
  `supports_flag`, and `supports_flag`'s own SIGPIPE race closed; it no longer
  reports an indeterminate probe as a confirmed absence (#61, #63).
- **Tap-install taxonomy seed** — the bundled installer seeds the runtime
  taxonomy too, with the job destination prepared (#51).
- **Full fleet deploy** — scripts + classifier plugin to all ten profiles;
  10/10 current, 10/10 gateways running, the pre-#49 classifier staleness gone.

## Lessons worth carrying forward

- **A premise recorded in a commit message is not evidence.** PR #55 claimed
  Revenium priced a normalized model name; measurement showed that cost was
  client-supplied and the normalized string prices at **zero**. The fix was
  reverted (#60) and the raw string turned out to be *closer* to the real
  catalog key.
- **Proving a mechanism exists is not proving it caused the failure.** The
  `supports_flag` SIGPIPE race is real and was fixed — but it does not explain
  the probe flake it was blamed for (the shim emits ~150 bytes, far below the
  pipe buffer). Check magnitudes before naming a root cause.
- **Verify a flake rate was ever counted.** "~1 in 4" came from an impression,
  not a trial, and drove an hour of hunting.
- **Synthetic fixtures cannot close a live criterion.** SC-8 passed on fixtures
  for months and failed to surface two real defects the first time a genuine
  breach ran through it.
