# How an undetermined CANCELLED job renders: the Phase 66 render probe

[← Back to the docs index](README.md)

This record resolves one question for the Trustworthy ROI Numbers milestone
(TRU-04): when the reporter ships a `CANCELLED` job whose outcome it could not
determine, does the reason Phase 66 added to `--metadata` reach the server, and
does the ROI page show it in place? Two probe jobs were shipped through the
real Phase 66 reporter to a development tenant and read back through the real
`revenium` CLI. One is an undetermined `CANCELLED` job. The other has the shape
the `pre_tool_call.sh` halt hook writes, as the contrast.

It does not own the reference-host proof. That is TRU-07, which belongs to
Phase 70 and runs after deployment on the reference host. This record is not
that proof; it hands Phase 70 a recipe (see `## For Phase 70`). The probe
changed no shipped behaviour: no file under `skills/` was touched to produce
it, and the only writes that left the scratch directory were two job
creations and two outcome reports on the development tenant.

## Verdict, up front — every criterion, in one table

| # | Criterion | Source | Verdict |
|---|-----------|--------|---------|
| 1 | The server persisted `failure_reason` and `outcome_basis: undetermined` in `outcomeMetadata` for an undetermined `CANCELLED` job shipped by the real Phase 66 reporter, with `executionStatus` `CANCELLED` and `outcomeType` `UNSUCCESSFUL` | TRU-04 / SC1 (wire) | CONFIRMED |
| 2 | The ROI page shows that reason in place for the undetermined job, and not for the halt-shaped job | TRU-04 / SC1 (page) | PENDING HUMAN CHECK |
| 3 | A halt-shaped job (`guardrail-halt-*`, type `interrupted`) persisted `source` alone: no `failure_reason`, no `outcome_basis` | SC3 | CONFIRMED |

*The TRU-04 status line is written after the page check (plan 66-02 Task 3).*

## The environment

- Working tree: commit `14439a1667b79c93dec6d281bc199dbb1f7b8b59`, on the
  `phase-66-undetermined-outcome-label` branch. Plan 01's three commits
  (`3b0d6e5`, `4bd7cba`, `14439a1`) are in it, and `git status --short --
  skills/` printed nothing before the run, so the probe ran committed code.
- CLI: `revenium 1.7.0 (dd64c11)`, resolved to `/opt/homebrew/bin/revenium`.
  This is a newer build than the 1.5.0 the earlier envelope record used.
- Tenant: the operator's own development tenant, not the milestone's
  reference tenant. No tenant, team or owner identifier appears in this
  document.
- Run time: the server stamped both job creations at `2026-10-06T14:26:22Z`
  and both outcome reports at `2026-10-06T14:26:23Z`. The read-back followed
  within about a minute.

**The instrument check.** The test-double trap from
[Live envelope verification](live-envelope-verification.md) was checked first.
`command -v revenium`, run with `$HOME/.local/bin` deliberately first on
`PATH` (the worst case `ensure_path` creates), resolved to
`/opt/homebrew/bin/revenium`, outside `$HOME/.local/bin`. `revenium jobs --help`
listed `outcome-history` and `delete`, which no test double in this repo
advertises. So the arms below were answered by the real API, not a stub.

**A second trap, in the shell rather than the PATH.** The first attempt at
this probe failed before any write: every `revenium jobs` call returned 403.
The shell exported `REVENIUM_API_KEY`, which overrides the `api-key` in the
CLI's own config file, and the exported value was a different, unauthorized
key. Every command in this record, including the `hermes-report.sh` run (which
shells out to `revenium`), ran with `REVENIUM_API_KEY` removed from the
environment, so the CLI used the configured key. Neither key is printed here.
The generalizable lesson: an exported credential variable silently beats the
config file, and a 403 on a tenant you believe you are authorized for is the
first thing to check it against.

## How each arm was scored

CLI read-back is the only admissible tenant evidence. Each arm was read back
with `revenium jobs get <id> --output json`, `revenium jobs roi <id>` and
`revenium jobs outcome-history <id> --output json`.

Exit status is never evidence. On 2026-08-19 this API accepted writes and
persisted nothing for roughly seven hours while returning success, so a zero
exit, a `created` or `outcome` line in the scratch ledger, or an absence of
warnings proves nothing about whether a row exists. A row counted only when the
server returned it.

The wire row is `CONFIRMED` only if the undetermined arm's `outcomeMetadata`
(an escaped JSON string) carries `outcome_basis` `undetermined` and a
`failure_reason` equal to the constant Plan 01 shipped, with `executionStatus`
`CANCELLED` and `outcomeType` `UNSUCCESSFUL`. The SC3 row is `CONFIRMED` only
if the halt-shaped arm's `outcomeMetadata` holds `source` alone. The page row
comes from a human's direct observation of the page and never from this
read-back.

## The probe

The instrument is `skills/revenium/scripts/hermes-report.sh` from the working
tree, run once. It is never a hand-built argv: this project has shipped
fixture-fidelity defects five times, and driving the committed reporter is
what makes the probe measure what ships.

A synthetic Hermes home was built in a fresh scratch directory outside the
repo and outside the operator's real `~/.hermes`, with `HERMES_HOME` and
`REVENIUM_STATE_DIR` pointed at it. Its `state.db` has the production schema
and one session, `phase66-probe-20261006-142611`, with 100 input and 50 output
tokens, ended an hour earlier. Its `revenium-hermes.ledger` was pre-seeded with
one line at the session's current total (150 tokens), which makes the session
token-stable, so the reporter ships no completion and takes the arc-close path
that creates both jobs and ships both outcomes in one run. A settle sentinel
and one marker file carry two `kind: job` markers, both `status: CANCELLED`:

- the undetermined arm: id `phase66-undetermined-20261006-142611`, type
  `code_review`;
- the halt arm: id `guardrail-halt-p66-20261006-142611`, type `interrupted`,
  named `Arc interrupted by guardrail halt` as the halt hook names its own
  job.

Auxiliary metering was disabled for the run. No id, name or source contains a
person's name: Phase 65's CR-01 leak came from an operator-named job id that a
shape-only audit could not catch.

**Why not the reference host.** Phase 70 owns the reference-host proof, and
deploying here would pre-empt it and ship unreleased changes beyond Phase 66 to
that host. Probe rows written into the reference tenant would sit in the slice
Phase 70 measures. Rendering is a property of the Revenium web app, not of a
tenant, so the operator's own development tenant answers the question. And an
organic undetermined job on the reference host arrives nondeterministically,
behind a cron pass that takes over an hour.

**What the run left behind.** After the run the scratch `revenium-jobs.ledger`
held a `created` and an `outcome` line for both ids. The scratch
`revenium-hermes.ledger` still held only its one pre-seeded line, so no
completion shipped. The operator's real `revenium-hermes.ledger` and
`revenium-metering.log` kept the modification times they had before the run,
and the real `revenium-jobs.ledger` did not exist before and does not exist
now. None of this is evidence that a row exists; the read-back below is.

## The evidence

Tenant, team, owner and account identifiers, and any email, are replaced with
bracketed placeholders; the field name stays. The probe job ids and session id
stay raw because this plan minted them.

### The undetermined arm

`revenium jobs get phase66-undetermined-20261006-142611 --output json`

```
{
  "_links": {
    "collection": {
      "href": "/profitstream/v2/api/jobs?teamId=<redacted-team-id>"
    },
    "self": {
      "href": "/profitstream/v2/api/jobs/phase66-undetermined-20261006-142611?teamId=<redacted-team-id>"
    }
  },
  "agenticJobId": "phase66-undetermined-20261006-142611",
  "created": "2026-10-06T14:26:22.529Z",
  "entityVersion": 1,
  "environment": "phase66-probe",
  "executionStatus": "CANCELLED",
  "hasOutcome": true,
  "id": "5jRYN7",
  "label": "Phase 66 render probe - undetermined outcome",
  "name": "Phase 66 render probe - undetermined outcome",
  "outcomeCurrency": null,
  "outcomeMetadata": "{\"source\":\"phase66-probe\",\"failure_reason\":\"Outcome not determined: the arc ended without checkable evidence of success or failure, so it was reported as CANCELLED by default. No guardrail halt was recorded for this job.\",\"outcome_basis\":\"undetermined\"}",
  "outcomeReason": null,
  "outcomeReportedAt": "2026-10-06T14:26:23.207Z",
  "outcomeType": "UNSUCCESSFUL",
  "outcomeUpdateCount": 0,
  "outcomeUpdatedAt": null,
  "outcomeUpdatedBy": null,
  "outcomeValue": null,
  "resourceType": "job",
  "source": "UI",
  "type": "code_review",
  "updated": "2026-10-06T14:26:23.207Z",
  "version": null
}
```

`revenium jobs roi phase66-undetermined-20261006-142611`

```
╭───────────────────┬──────────────────────────────────────────────╮
│ Metric            │ Value                                        │
├───────────────────┼──────────────────────────────────────────────┤
│ Job ID            │ phase66-undetermined-20261006-142611         │
│ Name              │ Phase 66 render probe - undetermined outcome │
│ Type              │ code_review                                  │
│ Execution Status  │ CANCELLED                                    │
│ Outcome Type      │ UNSUCCESSFUL                                 │
│ Has Outcome       │ true                                         │
│ Total Cost        │ $0.00                                        │
│ Outcome Value     │ $0.00                                        │
│ ROI %             │ 0.00%                                        │
│ Transaction Count │ 0                                            │
│ Input Tokens      │ 0                                            │
│ Output Tokens     │ 0                                            │
│ Total Tokens      │ 0                                            │
╰───────────────────┴──────────────────────────────────────────────╯
```

`revenium jobs outcome-history phase66-undetermined-20261006-142611 --output json`

```
[
  {
    "executionStatus": "CANCELLED",
    "outcomeCurrency": null,
    "outcomeMetadata": "{\"source\":\"phase66-probe\",\"failure_reason\":\"Outcome not determined: the arc ended without checkable evidence of success or failure, so it was reported as CANCELLED by default. No guardrail halt was recorded for this job.\",\"outcome_basis\":\"undetermined\"}",
    "outcomeReason": null,
    "outcomeType": "UNSUCCESSFUL",
    "outcomeValue": null,
    "reason": null,
    "reportedAt": "2026-10-06T14:26:23.207Z",
    "reportedBy": "<redacted-email>",
    "sequence": 1
  }
]
```

The server kept the reporter's reason verbatim and the `outcome_basis` key
beside it. `outcomeReason`, the server's own purpose-built field, is `null`:
no released CLI has a flag to set it, so `--metadata` is the only carrier
reachable today. The `jobs roi` table shows the status and the outcome type
and nothing from `outcomeMetadata`.

### The halt arm

`revenium jobs get guardrail-halt-p66-20261006-142611 --output json`

```
{
  "_links": {
    "collection": {
      "href": "/profitstream/v2/api/jobs?teamId=<redacted-team-id>"
    },
    "self": {
      "href": "/profitstream/v2/api/jobs/guardrail-halt-p66-20261006-142611?teamId=<redacted-team-id>"
    }
  },
  "agenticJobId": "guardrail-halt-p66-20261006-142611",
  "created": "2026-10-06T14:26:22.759Z",
  "entityVersion": 1,
  "environment": "phase66-probe",
  "executionStatus": "CANCELLED",
  "hasOutcome": true,
  "id": "l38QM6",
  "label": "Arc interrupted by guardrail halt",
  "name": "Arc interrupted by guardrail halt",
  "outcomeCurrency": null,
  "outcomeMetadata": "{\"source\":\"phase66-probe\"}",
  "outcomeReason": null,
  "outcomeReportedAt": "2026-10-06T14:26:23.553Z",
  "outcomeType": "UNSUCCESSFUL",
  "outcomeUpdateCount": 0,
  "outcomeUpdatedAt": null,
  "outcomeUpdatedBy": null,
  "outcomeValue": null,
  "resourceType": "job",
  "source": "UI",
  "type": "interrupted",
  "updated": "2026-10-06T14:26:23.554Z",
  "version": null
}
```

`revenium jobs roi guardrail-halt-p66-20261006-142611`

```
╭───────────────────┬────────────────────────────────────╮
│ Metric            │ Value                              │
├───────────────────┼────────────────────────────────────┤
│ Job ID            │ guardrail-halt-p66-20261006-142611 │
│ Name              │ Arc interrupted by guardrail halt  │
│ Type              │ interrupted                        │
│ Execution Status  │ CANCELLED                          │
│ Outcome Type      │ UNSUCCESSFUL                       │
│ Has Outcome       │ true                               │
│ Total Cost        │ $0.00                              │
│ Outcome Value     │ $0.00                              │
│ ROI %             │ 0.00%                              │
│ Transaction Count │ 0                                  │
│ Input Tokens      │ 0                                  │
│ Output Tokens     │ 0                                  │
│ Total Tokens      │ 0                                  │
╰───────────────────┴────────────────────────────────────╯
```

`revenium jobs outcome-history guardrail-halt-p66-20261006-142611 --output json`

```
[
  {
    "executionStatus": "CANCELLED",
    "outcomeCurrency": null,
    "outcomeMetadata": "{\"source\":\"phase66-probe\"}",
    "outcomeReason": null,
    "outcomeType": "UNSUCCESSFUL",
    "outcomeValue": null,
    "reason": null,
    "reportedAt": "2026-10-06T14:26:23.553Z",
    "reportedBy": "<redacted-email>",
    "sequence": 1
  }
]
```

The halt-shaped job carries `source` alone. Its `jobs roi` table differs from
the undetermined job's only in id, name and type, which is the point of the
contrast: in the CLI's table the two rows read alike, and only
`outcomeMetadata` tells them apart.

## What the ROI page shows

PENDING HUMAN CHECK

## What this does not establish

Written after the page check (plan 66-02 Task 3).

## For Phase 70

Written after the page check (plan 66-02 Task 3).

## Jobs created

Two throwaway jobs on the development tenant, from one synthetic session:

- `phase66-undetermined-20261006-142611` (undetermined arm)
- `guardrail-halt-p66-20261006-142611` (halt arm)
- session `phase66-probe-20261006-142611`

They are left in place as the evidence behind this record. `revenium jobs
delete` exists should they need removing.
