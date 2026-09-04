# A CLI-verb ask for the Revenium CLI team

[← Back to the project README](../README.md)

This repo-only page records a standing request for the owners of the
`revenium` CLI's verb surface. It is not part of the skill bundle and is
unavailable on a tap-installed host.

It is a companion to
[`docs/roi-read-surface-ask.md`](roi-read-surface-ask.md), an earlier ask to
the same team about the same CLI, and the two are deliberately separate
documents: that page requests fields on a display verb that already
exists (`jobs roi`); this page requests verbs and flags that do not exist
at all. Folding them together would blur "add a field to an existing
command" with "add a command that isn't there," which is a different kind
of ask with a different kind of fix.

## What is true today

Verified live against the installed CLI on 2026-09-04, by running the
probes below and reading exactly what they printed — not transcribed from
any planning document.

```
$ revenium version
revenium 1.5.0 (0f5f3a7)
```

`revenium jobs --help` lists twelve subcommands, no more and no fewer:
`conversion-funnel`, `create`, `delete`, `get`, `list`, `outcome`,
`outcome-history`, `outcome-update`, `roi`, `transactions`, `types`,
`update`.

`revenium jobs types --help` shows a leaf command that takes only flags
(`-h`/`--help` plus the global flags) and has **no subcommands**. Running
`revenium jobs types` lists the available job types; there is no
`economics`, `baselines`, or `facts` verb anywhere under `jobs types`, and
no other command in the twelve-item list above fronts them either. All
three surfaces are unreachable from this CLI today.

`revenium jobs outcome-update --help` advertises exactly six flags —
`--execution-status`, `--metadata`, `--outcome-currency`,
`--outcome-type`, `--outcome-value`, `--reason` — and no version flag
under any spelling.

`revenium metrics --help` lists ten subcommands — `ai`, `api`, `audio`,
`completions`, `dimensions`, `image`, `squads`, `tool-events`, `traces`,
`video` — and none of them covers job outcomes.

One thing already present narrows the ask: `revenium jobs get --help`'s
own example (`revenium jobs get loan-app-12345 --json`) and the root
`revenium --help`'s documented `--json` global flag confirm that reading a
job back as JSON needs nothing new. The read half of optimistic
concurrency — fetching a job's current version — already works; only the
write-side version flag on `jobs outcome-update` is missing (see below).

## Why the CLI-only boundary makes this blocking, not optional

This project has been CLI-only by architecture since it started. Calling
the Revenium Platform API directly over HTTP was considered and declined,
on the record, on 2026-09-03 (`.planning/REQUIREMENTS.md`, "Explicitly out
of scope"), specifically to preserve that boundary. Given that choice, a
server endpoint with no CLI verb in front of it is not merely awkward to
reach from this project — it is unreachable, full stop. No amount of work
on this side substitutes for a verb that doesn't exist; the work that
depends on one of these five gaps cannot be finished by trying harder here.

Say the important distinction plainly: the endpoints themselves already
exist server-side. This is a client-surface gap, not a platform gap. That
is what makes each of the five asks below small — no new capability is
being requested, only a way for this CLI to reach a capability the
platform already has.

## What this project built instead of waiting

Rather than hold this work until the CLI catches up, three things were
built ahead of it, all inert until a verb or flag ships:

- **The valuation seam**
  (`skills/revenium/plugins/revenium-classifier/valuation_sources.py`).
  Its one shipped source is deliberately shaped after the server's
  `baselines` surface — `hourlyRate`, `minutesPerUnit`, `provenance` — so
  that a later server-backed source is a like-for-like swap, not a
  rewrite.
- **An independent capability probe on the correction path**
  (`skills/revenium/scripts/correct-assessment.sh:614-648`). Its whole
  positive branch — reading a job's current version and appending
  `--expected-entity-version` to the correction call — is written and
  tested today, and stays dead code until the probed flag ships under a
  real spelling.
- **A decided local-to-server provenance mapping**
  ([`docs/provenance-mapping.md`](provenance-mapping.md)). Every local
  `evidence_class` this project produces is already mapped onto the two
  server `provenance` vocabularies the `economics`/`baselines` and
  `facts`/outcome-metrics surfaces use, including the one label
  (`MODEL_ESTIMATED_DEMO`) that maps to neither.

None of this is a Revenium commitment or an agreed roadmap item. It is
what this project chose to do on its own side while waiting.

## The concrete ask

Five entries, and only five — everything this milestone actually hit while
building, per its own roadmap instruction. Nothing plausible-but-unhit is
included.

1. **A read verb, `jobs types economics`, for the job-type `economics`
   surface** (the figures a server-computed job-type economics record
   carries — monetization, `overheadPerUnit`, `unitMetricKey` — per
   `.planning/REQUIREMENTS.md`'s summary of the platform's own schema).
   Today only the write side is documented anywhere this project can see;
   read access is the blocking half, since this project has nothing to
   write from yet.

   **What changes here the day this ships:** `valuation_sources.register()`
   gains a server-backed source function, registered exactly as the
   shipped file source already is
   (`valuation_sources.py:206-239`) — a new source function plus a config
   key, no caller changes.

2. **A read verb, `jobs types baselines`, for the job-type `baselines`
   surface.** This is the one with a live consumer already built, so its
   required shape is explicit:
   the read verb must return, at minimum, these three fields, by these
   names:

   - `hourlyRate` — a positive number.
   - `minutesPerUnit` — a positive number.
   - `provenance` — a string.

   A verb returning a differently-named or differently-shaped set of
   fields is one `valuation_sources.py`'s existing seam cannot consume
   without a code change on this side — which defeats the point of having
   built the seam ahead of time.

   **What changes here the day this ships:** `valuation_sources.register()`
   gains a server-backed source function, registered exactly as the
   shipped file source already is
   (`valuation_sources.py:206-239`) — a new source function plus a config
   key, no caller changes.

3. **A read verb, `jobs types facts`, for the job-type `facts` surface**
   (late-arriving, provenance-carrying facts about a job type, per the
   platform's `facts` schema summarized in `.planning/REQUIREMENTS.md`).

   **What changes here the day this ships:** `valuation_sources.register()`
   gains a server-backed source function, registered exactly as the
   shipped file source already is
   (`valuation_sources.py:206-239`) — a new source function plus a config
   key, no caller changes.

4. **A version flag on `jobs outcome-update`.** Its exact spelling is the
   subject of its own section below, because this project has to guess it
   today.

   **What changes here the day this ships:** the capability probe already
   in `correct-assessment.sh` flips positive and the already-shipped
   read-and-append branch (`correct-assessment.sh:614-648`, `:1076-1080`)
   engages with no code change on this side.

5. **A CLI surface for job-outcome metrics**, fronting the platform's
   outcome-metrics surface (`POST /jobs/{id}/outcome/metrics` per
   `.planning/REQUIREMENTS.md`'s summary). Both halves of the gap are
   missing today: no `jobs` verb writes a late-arriving outcome metric,
   and none of `revenium metrics`' ten subcommands reads one back.

   **What changes here the day this ships:** nothing, today — no gate
   exists in this codebase for this one, because there was nothing to
   probe against. Saying so plainly is more useful to the implementer
   than inventing a gate that isn't there. What it would unlock: a way for
   a late-arriving value to carry its own provenance forward, instead of
   the correction path's current append-only overwrite of the original
   outcome value.

No commitment above names a date, a phase number, or who will do the work.
Each one describes a mechanism already sitting in this tree; the mechanism
is checkable today and a schedule is not this project's promise to make.

## The one string we are guessing

`skills/revenium/scripts/correct-assessment.sh:631` probes exactly one
flag spelling:

```
supports_flag "jobs outcome-update" "--expected-entity-version"
```

That spelling was derived, not observed: it is a straight kebab-case
transliteration of the platform's own OAS field name,
`expectedEntityVersion`, following the same kebab-case convention verified
against three flag/field pairs the CLI already ships —
`--outcome-value`/`outcomeValue`, `--outcome-currency`/`outcomeCurrency`,
and `--execution-status`/`executionStatus`.
**`--expected-entity-version` has never been observed on a real `--help`.**

The consequence is precise, and it is the reason this passage exists: if
the shipped flag uses a different spelling, the probe above simply stays
negative forever, the correction path fails open exactly as it does
today, and the entire positive branch — the guarded `jobs get` read plus
the conditional flag append — is silently inert. Working code that never
runs, with no error anywhere to point at it.

If the real spelling is different, tell us. The fix on this side is one
constant — the string literal in the `supports_flag` call at
`correct-assessment.sh:631` — and one fixture,
`tests/fixtures/compat/jobs-outcome-update-versioned.golden.json`, which
pins the version-carrying argv shape. Nothing else in this codebase
depends on the guessed spelling.

## What is NOT being asked

- **No change to what this skill sends today.** Every ask above is about
  reading a new surface or adding a flag this project would opt into; none
  of it changes the record shape or the wire payload this skill already
  ships.
- **Not direct HTTP access, and not an SDK.** The CLI-only boundary is
  this project's own architectural choice, made and re-affirmed on the
  record; it is not up for renegotiation in this document.
- **Not write verbs first.** Read access is what unblocks the seam this
  project has already built; the write side of `economics` / `baselines` /
  `facts` is out of scope here.
- **Not a schedule.** Every commitment above is mechanical — a gate that
  flips — not a date.

## Where the evidence lives

- [`docs/wire-contract-audit-2.20.0.md`](wire-contract-audit-2.20.0.md) —
  where the OAS field `expectedEntityVersion` was read from, and the
  field-by-field audit of every request this skill already sends against
  the `2.20.0-SNAPSHOT` platform API spec.
- [`docs/provenance-mapping.md`](provenance-mapping.md) — the server
  `provenance` vocabulary names for the `baselines` and `facts`/outcome-
  metrics surfaces named above, and the decided mapping from this
  project's own evidence classes onto them.
- [`docs/roi-read-surface-ask.md`](roi-read-surface-ask.md) — the sibling,
  earlier ask to the same team: fields missing from an existing display
  verb, deliberately not part of this page.
