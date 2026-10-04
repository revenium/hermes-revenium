# Job cost provenance and cron-session classification: the Phase 65 reconciliation

[← Back to the docs index](README.md)

This page records two Phase 65 (Reconciliation) findings for the Trustworthy
ROI Numbers milestone: TRU-01, whether the ROI view's per-job `Total Cost` is
derived from this skill's own `--agentic-job-id` attribution or from a
different, server-side signal; and TRU-02, why `hermes cron run` sessions
meter as `unclassified`. It owns neither the attribution dimension's own
design (see [Job value and ROI](value-and-roi.md) and
[`references/job-declaration.md`](../skills/revenium/references/job-declaration.md))
nor the classifier's hook mechanics beyond what this diagnosis needed to read
(see [Hermes plugin interface](plugin-interface.md)). This page diagnoses
shipped behaviour against a real reference host and tenant and changes none
of it — no file under `skills/` was touched to produce this record.

One correction while we're here: `ROADMAP.md` names "the way Phase 41's
reconciliation record did" as this record's survival precedent. That citation
is inaccurate — Phase 41's deliverables live entirely in gitignored
`.planning/` and do not survive in git. The actual precedents for a tracked,
pinned, surviving diagnosis record are
[Evidence-class precedence and declaration authority](evidence-class-precedence.md)
(Phase 48) and `docs/auxiliary-usage-sizing.md` (Phase 31) — the latter is
itself a cautionary tale, not a surviving example: an earlier record of its
own existence was never added to `test_expected_files_exist`, and the file is
untracked and gone today. That history is exactly why this page's own pin,
added in this same change, matters.

## Verdict, up front — every criterion, in one table

| # | Criterion | Source | Verdict |
|---|---|---|---|
| 1 | Whether `jobs roi`'s per-job `Total Cost` is derived from this skill's `--agentic-job-id` attribution, or from a server-side signal | TRU-01 | **CONFIRMED** — Total Cost is derived from attributed completions; see below |
| 2 | Why `hermes cron run` sessions classify as `unclassified` | TRU-02 | **NOT YET ANSWERED** — filled by plan 02 of this phase |
| 3 | The record survives the milestone: tracked under `docs/`, pinned in `test_expected_files_exist`, indexed in `docs/README.md` | ROADMAP criterion 3 | **CONFIRMED** — this file, this pin, this index entry |

## What this record decides for later phases

- **TRU-05 / Phase 68:** `TRU-05 is LIVE` — per-job Total Cost is built from
  this skill's `--agentic-job-id` attribution, confirmed two ways (the
  two-job `transactionCount` comparison, and a direct assumption-A2 test
  ruling out a time-window/session-based join), so the measured 3.2%
  attribution rate (78 of 2,424 markers, per `.planning/REQUIREMENTS.md`) is
  the actual denominator and Phase 68 runs on it. See "### The verdict" under
  TRU-01 below for the evidence.
- **TRU-06 / Phase 69:** pending plan 02 of this phase.

## The environment

- **Host:** the reference host used throughout this milestone's measurements
  ("Jupi" by role, per `.planning/REQUIREMENTS.md`). Named by role only — no
  address, hostname, or SSH key name appears in this file.
- **Agent:** `Jupiter` — confirmed on every transaction row read for this
  record's probes (`"agent": "Jupiter"`), so every figure below is this
  host's own agent, not the tenant's other agent (out of scope per
  `.planning/REQUIREMENTS.md` § Out of Scope).
- **Tenant:** confirmed via `revenium config show`'s `Tenant ID` field,
  matching the reference tenant id recorded in `.planning/REQUIREMENTS.md` §
  "The measured starting position." `revenium tenants get` itself takes a
  required positional tenant id — there is no "get the configured tenant"
  form — so `config show` is the correct substitute here, not a weaker
  confirmation. The tenant id itself is not transcribed into this file, per
  this phase's own prohibitions.
- **CLI:** `revenium v1.7-5-g8d46ad4 (8d46ad4)`.
- **Deployed code currency:** the host's skill tree is **not** a git
  checkout (`git rev-parse HEAD` inside it fails with "not a git
  repository"), so currency was established by per-file sha256 rather than a
  commit hash, in **both** locations Hermes' plugin discovery can load the
  classifier from: `~/.hermes/skills/revenium/plugins/revenium-classifier/`
  (the shipped skill-tree copy) and `~/.hermes/plugins/revenium-classifier/`
  (the separately loaded copy Hermes' plugin discovery actually imports —
  see [Hermes plugin interface](plugin-interface.md) for why these two
  locations exist and can diverge). `classifier.py` and `__init__.py` (both
  locations) and `scripts/hermes-report.sh` (skill-tree only — it has no
  plugin-discovery counterpart) are byte-identical to this repository's HEAD
  at the time of this probe (`ed1fa952c4e7d87dbc63e647ae0a1c81519ae900`), by
  sha256, 0 mismatches across all five comparisons. This corrects standing
  project memory, which recorded the host's skill tree as "last synced at
  `221b435`, predating phases 61-63" — that record is now stale; the
  deployed tree is current as of this probe.
- **Run date:** 2026-10-04.

## How each answer was scored

CLI read-back against the tenant is the **only** admissible tenant-side
evidence for either finding in this record, matching the bar every prior
live-proof record in this repo (`docs/live-tenant-proof.md`,
`docs/comprehensive-roi-proof.md`, `docs/subscriber-live-proof.md`) already
set. No UI or dashboard observation contributed to any verdict. **Exit status
is never evidence.** Host-side wire evidence — a ledger line, a marker file
— is corroboration only: it establishes that the skill did its job, not that
the platform ingested or attributed the value the way the skill intended.

## TRU-01 — where the ROI view's per-job Total Cost comes from

### The probe

Per `65-RESEARCH.md` Pattern 2, `revenium jobs transactions <id> --output
json` — not `revenium metrics ai` or `metrics completions` — is the verb
capable of answering "did this job receive any attributed spend," because it
returns the server's own literal list of AI-metric transactions linked to
that job id. Two job ids from this host's own agent slice (confirmed
`"agent": "Jupiter"` on every transaction row below) were read: one this
host's own `revenium-jobs.ledger` already showed as having no real
transactions behind it, one with real transactions behind it.

### The evidence

**Zero-attribution job — `revenium jobs roi jupiter_single_event_signalraven_drain_f38e5ce0_f7c3 --output json`:**
```json
{
  "agenticJobId": "jupiter_single_event_signalraven_drain_f38e5ce0_f7c3",
  "agenticJobName": "Jupiter single-event pipeline for SignalRaven signal f38e5ce0",
  "agenticJobType": "single_event_pipeline_execution",
  "executionStatus": "SUCCESS",
  "hasOutcome": true,
  "inputTokens": 0,
  "outcomeCurrency": null,
  "outcomeType": "CONVERTED",
  "outcomeValue": null,
  "outputTokens": 0,
  "roi": null,
  "totalCost": 0,
  "totalTokens": 0,
  "transactionCount": 0
}
```

**Same job — `revenium jobs transactions jupiter_single_event_signalraven_drain_f38e5ce0_f7c3 --output json`:**
```json
{
  "totalCount": 0,
  "transactions": []
}
```

**Attributed job — `revenium jobs roi <redacted-actor-job-id>_d671 --output json`:**
```json
{
  "agenticJobId": "<redacted-actor-job-id>_d671",
  "agenticJobName": "Single-event pipeline execution for <redacted-actor> signal",
  "agenticJobType": "single_event_pipeline_execution",
  "executionStatus": "SUCCESS",
  "hasOutcome": true,
  "inputTokens": 118076,
  "outcomeCurrency": "USD",
  "outcomeType": "CONVERTED",
  "outcomeValue": 59.5,
  "outputTokens": 8417,
  "roi": 15326.18,
  "totalCost": 0.385708,
  "totalTokens": 126493,
  "transactionCount": 2
}
```

**Same job — `revenium jobs transactions <redacted-actor-job-id>_d671 --output json`:**
```json
{
  "totalCount": 2,
  "transactions": [
    {
      "agent": "Jupiter",
      "cost": 0.192854,
      "duration": 333648,
      "inputTokens": 59038,
      "model": "glm-5.2",
      "outputTokens": 4209,
      "provider": "openrouter",
      "status": "success",
      "timestamp": "2026-09-23T03:17:40Z",
      "totalTokens": 63247,
      "transactionId": "20260923_031638_b5998f-126493-001a0cc49a440cc6a37e61b50a181196c"
    },
    {
      "agent": "Jupiter",
      "cost": 0.192854,
      "duration": 333648,
      "inputTokens": 59038,
      "model": "glm-5.2",
      "outputTokens": 4208,
      "provider": "openrouter",
      "status": "success",
      "timestamp": "2026-09-23T03:17:40Z",
      "totalTokens": 63246,
      "transactionId": "20260923_031638_b5998f-126493-001a0cc49a440e64def363562142db1dc"
    }
  ]
}
```

`jobs roi`'s `totalCost`/`transactionCount` are zero exactly when `jobs
transactions` returns `totalCount: 0`, and non-zero (2 transactions,
`$0.385708`) exactly when `jobs transactions` returns 2 real rows — the
decisive comparison this phase's own research named as the test, now
confirmed on this host, this tenant, today.

### Assumption A2, tested: does a session-level or time-window join also contribute?

`65-RESEARCH.md`'s Assumptions Log (A2) flags the one gap the two-job
comparison above cannot close on its own: `jobs transactions`'s
`transactionCount` might count every transaction in the job's time window
*for that session*, not only the ones carrying that job's own
`--agentic-job-id`. If true, TRU-01's answer would need a caveat about a
secondary, session-based signal.

A single root cron session on this host, `cron_138a635e0812_20260929_070024`,
settles this directly. Its own marker file carries **two** job-kind records,
written seconds apart — this one session created two separate jobs in
sequence:

```
{"kind":"job", ..., "sid":"cron_138a635e0812_20260929_070024", "agentic_job_id":"jupiter_open_web_signal_capture_992f", ...}
{"kind":"job", ..., "sid":"cron_138a635e0812_20260929_070024", "agentic_job_id":"signalraven_drain_eligibility_check_7f5b", ...}
```

The second of those two job ids is `signalraven_drain_eligibility_check_7f5b`
— a zero-attribution job in its own right (`transactionCount: 0`, confirmed
the same way as the sample job above). The session itself shipped exactly two
completions, read from its own `revenium-hermes.ledger` line:

```
HERMES:cron_138a635e0812_20260929_070024:35563:1790666592.335:001a0ebfa8d449183a960e5897d1018c3
HERMES:cron_138a635e0812_20260929_070024:35563:1790666592.613:001a0ebfa8d4419ee4547706cddcd0bb0
```

Pulling those exact two transactions back from the tenant
(`revenium metrics completions`, matched by `transactionId` against the
ledger tuple above) shows both carry a real, populated `agenticJobId` key —
**not null, and not absent** — but pointing at the *other* job:

```
transactionId: cron_138a635e0812_20260929_070024-35563-001a0ebfa8d449183a960e5897d1018c3
agenticJobId: jupiter_open_web_signal_capture_992f
totalCost: 2.014956 | totalTokenCount: 17781 | environment: cron | squadId: cron_138a635e0812_20260929_070024

transactionId: cron_138a635e0812_20260929_070024-35563-001a0ebfa8d4419ee4547706cddcd0bb0
agenticJobId: jupiter_open_web_signal_capture_992f
totalCost: 2.014956 | totalTokenCount: 17782 | environment: cron | squadId: cron_138a635e0812_20260929_070024
```

(The `organization`/`team`/`product`/`source`/`subscriberCredential` nested
objects and the `_links` block that `metrics completions` also returns are
omitted here — they carry internal tenant ids this comparison does not
depend on and this phase's redaction convention keeps out of this file.)

Both completions carry the **first** job's id (`jupiter_open_web_...`), and
`revenium jobs roi jupiter_open_web_signal_capture_992f` independently shows
`totalCost: 4.029912, totalTokens: 35563, transactionCount: 2` — exactly this
session's whole spend. The second job, same session, same time window, same
two completions, shows **zero**. If `transactionCount` were satisfied by a
time-window or session-based join rather than the specific `--agentic-job-id`
value on each completion, both jobs would show the spend; only one does.
**Assumption A2 is CONFIRMED**: `jobs roi`'s `transactionCount` counts only
transactions carrying that specific job's own `--agentic-job-id`, not a
broader session- or window-based match — tested directly from this host's own
evidence, not assumed from the two historical cross-host observations alone.

### The verdict

**CONFIRMED.** Two independent legs of evidence agree, both from this host's
own agent slice (`"agent": "Jupiter"` on every transaction row read in this
record):

1. **The two-job comparison** (above): `jobs roi`'s `totalCost`/
   `transactionCount` are zero exactly when `jobs transactions` returns
   `totalCount: 0`, and non-zero exactly when it returns real rows.
2. **The assumption-A2 test** (above): a single session's two completions tag
   one specific job's `--agentic-job-id` and nothing else — a sibling job
   from the identical session and time window gets nothing, ruling out a
   time-window or session-based join as an alternative explanation.

Per-job `Total Cost` is built from the completions this skill tags with that
job's own `--agentic-job-id`, full stop — not from a time-window join, not
from a session-level aggregate, and not from an independent server-side
signal.

**A byproduct worth naming plainly, because it is directly visible in the
evidence above and bears on TRU-05's own denominator:** a session that
creates more than one job in sequence ships its completions to only one of
them. This traces to `api-event-report.sh`'s `_attribution_for`
(`skills/revenium/scripts/api-event-report.sh:1489-1521`), which resolves a
single `owning_job_id` per session-window lookup and falls back to it only
when a marker carries no `agentic_job_id` of its own — a second job created
later in the same session never displaces the first. This is a plausible,
concrete contributor to part of the measured 96.8% non-attributed
population, distinct from "never attributed at all." It is not measured or
sized here, and no fix is proposed; it is recorded as a finding this
diagnosis surfaced, for whichever phase picks up TRU-05.

### What this does not establish

- **Single-host, single-tenant, single probe pass.** Both the two-job
  comparison and the A2 test ran once, on this host (agent `Jupiter`,
  reference tenant), on 2026-10-04. Nothing here establishes the
  relationship holds on a different host, a different tenant, or across
  repeated passes.
- **This is a read-side observation of how `Total Cost` is composed, not a
  measurement of whether `--agentic-job-id` persists correctly server-side
  for every emission path.** Both evidenced sessions (the sample job and the
  A2 test session) were event-path sessions (`environment: "cron"`,
  `api-event-report.sh`'s own `_attribution_for`); the delta-reporter path
  (`hermes-report.sh`'s own `meter completion` call) was not separately
  re-tested here, though it ships the identical `--agentic-job-id` flag
  under the same contract.
- **The deployed-tree currency caveat from `## The environment` applies
  here too.** This finding describes the behaviour of the code confirmed
  byte-identical to this repository's `ed1fa95` on this host, on this date
  — not a timeless property of the wire protocol.
- **The multi-job-per-session attribution byproduct named above is a
  finding, not a measurement.** How many of the 96.8% non-attributed jobs
  are explained by this mechanism, versus some other cause, is not
  established here and is out of this plan's scope.

## TRU-02 — why `hermes cron run` sessions classify as unclassified

NOT YET ANSWERED — filled by plan 02 of this phase.
