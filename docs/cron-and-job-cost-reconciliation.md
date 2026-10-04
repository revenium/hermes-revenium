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

### The three candidates

Verbatim from
`.planning/todos/pending/2026-10-01-classify-cron-sessions-so-they-stop-metering-as-unclassified.md`:

1. **The plugin never runs for cron-shaped sessions.** The classifier
   registers `on_session_end` / `on_session_finalize` / `post_llm_call` /
   `post_api_request`. If a cron session's lifecycle fires none of them (or
   ends by a path that skips them), no classification is ever attempted and
   no sentinel is written.
2. **Classification is attempted and refused.** `LABEL_RE` validation or
   `TRIVIAL_BLOCKLIST` may reject the label for short, repetitive cron
   transcripts.
3. **It is intentional and simply undocumented** — cron work may have been
   judged not worth an auxiliary-LLM call per tick.

### The probe

Every command below is a read verb. None writes under `~/.hermes`, calls
`revenium meter`, runs `cron.sh` / `hermes-report.sh` / `prune-markers.sh` /
`clear-halt.sh` by hand, or deploys/rsyncs the skill tree.

- `revenium config show` — tenant/agent re-confirmation, same as plan 01.
- `ls -la "${STATE_DIR}"` (resolved: `ls -la ~/.hermes/state/revenium/`) —
  state-dir inventory.
- `wc -l`, `grep -oE '^HERMES:cron_[^:]+:'`, `sort -u` on `LEDGER_FILE`
  (`${STATE_DIR}/revenium-hermes.ledger`) — enumerate every distinct
  `cron_*` session id this host's own ledger has ever shipped (102 ids).
- For each id: `[ -f "${MARKERS_DIR}/<sid>.jsonl" ]` and
  `[ -e "${MARKERS_READY_DIR}/<sid>" ]` — existence checks only, partitioning
  into markers-present / sentinel-only / neither.
- `grep "^HERMES:<sid>:" "${LEDGER_FILE}" | tail -1 | cut -d: -f4` per id —
  read the session's own last-ledger-line timestamp (read-only; this is the
  skill's own append-only idempotency ledger, never written to).
- `python3 -c "... json.loads(...) ..."` over each markers-present
  `<sid>.jsonl` — read the literal `task_type` values out of the marker
  records (file read only).
- `grep -i "prune" "${LOG_FILE}"` (resolved:
  `~/.hermes/state/revenium/revenium-metering.log`) — read the skill's own
  cron log for the most recent `prune-markers.sh` run's output (log read
  only; this plan did not invoke `prune-markers.sh`).
- `export PATH=...`; `hermes cron --help`; `hermes cron list`; `hermes cron
  status`; `hermes cron runs --limit 50` — Hermes' own native cron-listing
  and execution-history verbs (`~/.local/bin/hermes`, not on the bare
  non-login `PATH`), to confirm what actually produces `cron_<job>_<ts>`
  session ids.
- `sqlite3 "${STATE_DB}" "SELECT id, source, started_at, ended_at,
  end_reason, message_count, tool_call_count, input_tokens, output_tokens,
  handoff_state, archived FROM sessions WHERE id = '<sid>'"` — read-only
  `SELECT` against Hermes' own session table, for the specific session this
  section names below and one comparison sibling.
- `systemctl status hermes-gateway --no-pager` — confirm this host's gateway
  is a **system-level** unit (not `--user`), per the reference-host note.
- `bash ${SKILL_DIR}/scripts/plugin-status.sh` and
  `bash ${SKILL_DIR}/scripts/hooks-status.sh` — the skill's own shipped,
  read-only diagnostics, confirming the plugin is registered and the hooks
  are wired before trusting any log-absence finding.
- `journalctl -u hermes-gateway --no-pager --since <ts> --until <ts>` (and
  unbounded, for `--disk-usage` and oldest-entry checks) — read the system
  unit's own log, established below as the classifier's real log channel.

### The evidence — host state

**Partition, measured 2026-10-04, this host's own agent, all 102 distinct
`cron_*` ids ever present in `revenium-hermes.ledger`:**

| State | Count (2026-10-04) | Count in the pending todo (2026-10-01, pre-prune) |
|---|---|---|
| Markers present | 11 | 10 |
| No markers, sentinel present | 0 | 58 (flagged in the todo itself as "all outside the 30d window — pruned") |
| Neither | 91 | 31 |

**This is itself a finding, not a restatement.** Between the todo's
measurement (2026-10-01T14:46:41Z) and this one, the host's own
`revenium-metering.log` shows a `prune-markers.sh` run at
**2026-10-01T19:00:39-44Z** — about four hours later, same day — whose output
includes `prune: ready summary, scanned=2843 kept=916 removed=1927
kept_marker_present=2 kept_session_pending=0` and dozens of individual
`prune: removed dir=ready sid=cron_...` lines for sessions 40-80+ days old.
This is PR #139 ("Prune the `.ready` sentinel dir alongside marker files"),
already merged into the commit plan 01 confirmed this host's tree matches
(`ed1fa952c4e7d87dbc63e647ae0a1c81519ae900`) — **before** PR #139, only
markers were pruned by age, so a sentinel, once written, persisted
indefinitely; after it, stale sentinels are pruned too. The todo's 58
"no-marker/has-sentinel" sessions were old sentinel orphans from markers
pruned under the pre-#139 behavior; that same-day prune run pruned their
sentinels too, moving all 58 into the "neither" bucket here. **This matches
this project's own standing finding that a sentinel with no marker is
usually a pruning artifact, not a silent drop** — and it means the "31"
figure, not "31 or 89", is the one comparable across both measurements,
because those 31 already had no sentinel *before* that prune run touched
anything, when no mechanism existed yet that could have removed one.

**Nearly the entire "neither" population is explained by age, not by a live
defect.** `REVENIUM_MARKER_RETENTION_DAYS` defaults to 30
(`common.sh` line 60); the 30-day cutoff from this measurement's run time is
**2026-09-04**. Of the 91 "neither" ids, **90 have a last-ledger timestamp
older than that cutoff** (oldest: 2026-07-13; newest of the 90:
2026-08-21) — every one of them is explained by the same pruning mechanism,
not a live classification failure, because the ledger-timestamp age at scan
time already exceeds the retention window that governs both marker and (now)
sentinel pruning.

**Exactly one "neither" id is NOT explained by age:
`cron_138a635e0812_20260926_070034`** (last-ledger ts `1790408524.383` =
2026-09-26T07:42:04Z by that ledger line, session-start per `state.db`
`1790406034.307` = 2026-09-26T07:00:34Z — 12 days old at measurement time,
well inside the 30-day retention window). This is the single live,
unpruned, unexplained-by-retention defect this partition surfaces, and it is
the session the rest of this section investigates.

**Open Question 1 — do markers that exist carry real labels, or
`unclassified`?** Read directly from each of the 11 markers-present
`<sid>.jsonl` files:

| Session id | `task_type` |
|---|---|
| `cron_138a635e0812_20260925_034013` | `jupiter_signalraven_queue_delivery` |
| `cron_138a635e0812_20260925_070019` | `jupiter_single_event_pipeline_run` |
| `cron_138a635e0812_20260927_070049` | `jupiter_single_event_pipeline_run` |
| `cron_138a635e0812_20260928_070008` | `jupiter_daily_pipeline_run` |
| `cron_138a635e0812_20260929_070024` | `jupiter_daily_pipeline_run` |
| `cron_138a635e0812_20260930_070034` | `jupiter_daily_pipeline_run` |
| `cron_138a635e0812_20261001_070058` | `jupiter_daily_pipeline_empty_queue` |
| `cron_138a635e0812_20261002_070002` | `jupiter_single_event_queue_delivery` |
| `cron_138a635e0812_20261003_070011` | `jupiter_daily_pipeline_run` |
| `cron_138a635e0812_20261004_070016` | `jupiter_daily_pipeline_empty_queue` |
| `cron_23f4c476fc5c_20260928_130044` | `competitive_intelligence_digest_compile` |

**Every single one carries a real, specific label — none is
`unclassified`.** This directly settles Open Question 1 in the direction the
plan's own objective flagged as possible: classification is **not** refused
for cron sessions that reach a classifying hook. Candidate 2
(`LABEL_RE`/`TRIVIAL_BLOCKLIST` refusal) is ruled out as an explanation for
every recent cron session this host has a marker for — the marker-present
population's problem, if any, is not label rejection.

**Open Question 2 / assumption A1 — what actually produces `cron_<job>_<ts>`
ids?** `hermes cron list` (via `~/.local/bin/hermes`, exported onto `PATH`
alongside the linuxbrew prefix) shows an **active** scheduled job:

```
138a635e0812 [active]
  Name:      jupiter-pipeline
  Schedule:  0 7 * * *
  ...
  Last run:  2026-10-04T07:02:14.749565+00:00  ok
```

The job id (`138a635e0812`) matches the first path segment of every
`cron_138a635e0812_<ts>` session id in the ledger, and `hermes cron status`
confirms "Gateway is running — cron jobs will fire automatically." This
confirms assumption A1 directly: these session ids are produced by Hermes'
own native `hermes cron` scheduler, not an operator `at`/systemd-timer
wrapper around a `hermes chat -Q` call. The hook-firing analysis below
targets the correct code path.

### The verdict

**Candidate 1 holds, in a narrower and different shape than either the
pending todo or this plan's own objective anticipated — confirmed live, not
assumed.**

**Locating the right instrument first.** The classifier's own outcomes never
reach `revenium-metering.log` — `scripts/diagnose.sh:346-350` says so
explicitly in the shipped product ("written IN-PROCESS by the classifier
plugin on the Python logger 'revenium_classifier', not into
revenium-metering.log, so they land wherever Hermes' own logging is
configured"), and this record would be answering from the wrong instrument
if it stopped there. This host runs hermes-gateway as a **system-level**
`systemd` unit (confirmed: `systemctl status hermes-gateway` shows
`Loaded: .../etc/systemd/system/hermes-gateway.service`, not a `--user`
unit), so its Python process's stdout/stderr — and with it every
`logging.getLogger("revenium_classifier")` line — lands in
**`journalctl -u hermes-gateway`**, which retains history back to this
host's last `hermes-gateway` package reinstall (oldest entry: 2026-06-09).
This was confirmed as the *correct* channel, not merely *a* channel, by
reading a **working** cron session's log window
(`cron_138a635e0812_20260927_070049`, 2026-09-27 07:04:39Z) and finding
three real `revenium_classifier` lines there, including the exact
`_validate_label`-adjacent valuation warnings this skill's own code emits.

**Reading that channel for the one live defect session named above.**
`cron_138a635e0812_20260926_070034` has neither a marker nor a sentinel, and
its `state.db` row shows it was not a zero-turn, never-completed session —
quite the opposite: `message_count=17`, `tool_call_count=12`,
`input_tokens=102404`, `output_tokens=3569`, `end_reason='cron_complete'`.
`journalctl -u hermes-gateway --since "2026-09-26 06:55:00" --until
"2026-09-26 07:10:00"` and a same-day full-log grep for the literal session
id both return **zero** lines containing `revenium` or
`revenium_classifier`, in either direction. The same window **does** show
the actual cause, from Hermes' own scheduler and conversation loop, not this
skill:

```
07:00:34 WARNING agent.conversation_loop: API call failed (attempt 1/3) ... HTTP 402 ...
07:01:13 WARNING agent.conversation_loop: API call failed (attempt 1/3) ... HTTP 402 ...
07:01:14 ERROR   agent.conversation_loop: Non-retryable client error: Error code: 402 - ...
07:01:14 ERROR   cron.scheduler: Job 'jupiter-pipeline' failed: RuntimeError: HTTP 402: ...
07:01:14            Traceback (most recent call last):
07:01:14              File ".../hermes-agent/cron/scheduler.py", line 5751, in run_job
07:01:14                raise RuntimeError(_err_text)
07:01:14            RuntimeError: HTTP 402: This request requires more credits, ...
```

The run exhausted its provider credits mid-conversation (OpenRouter 402, a
real billing event, not a skill defect) and `cron/scheduler.py`'s own
`run_job` (line 5751 in this host's installed Hermes build) raised a
`RuntimeError` that `cron.scheduler` logged as a job failure. **Zero
classifier log lines, from a channel independently confirmed correct on a
sibling session minutes away in the same ledger, is the positive evidence
for candidate 1**: `_on_session_end` (`__init__.py:86-133`) and
`_on_session_finalize` (`__init__.py:136-200`) were never invoked for this
session at all. The structural argument this phase's `must_haves.key_links`
names applies here precisely: every code path through those two callbacks —
including each one's own `except Exception` handler — calls
`_write_sentinel` (`__init__.py:52-82`) before returning, and
`_write_sentinel` itself swallows every `IOError`/`OSError`/
`PermissionError` with a `logger.warning` (PA-9's fourth candidate). A
sentinel-write failure would still log something; a `LABEL_RE`/
`TRIVIAL_BLOCKLIST` rejection (`classifier.py:58`, `classifier.py:67`,
validated at `_validate_label`, `classifier.py:4713-4737`) would also still
log something (`classifier.py`'s rejection warning fires from inside
`_validate_label`, which only runs once a hook has already dispatched into
`run_classification_async`, `classifier.py:5176-5186`). **No line at all, in
either direction, from an instrument proven to carry this exact logger's
output minutes earlier, rules out every code path that requires the hook to
have started running** — leaving "the hook was never invoked" as the only
candidate the evidence supports.

**The specific shape differs from what the todo and this plan's own
objective guessed.** The todo's candidate 1 reads "the plugin never runs for
cron-shaped sessions" and this plan's objective speculated a narrower form —
"a cron session that never completes a turn and never hits a session
boundary reaches none of the three hooks." **That narrower hypothesis is
wrong, confirmed by this session's own evidence**: 17 messages and 12 tool
calls is not a zero-turn session, and `state.db` records a real, terminal
`end_reason` (`cron_complete`), not an interrupted or still-open one. The
actual mechanism, confirmed by the traceback above: when
`cron/scheduler.py`'s `run_job` raises an uncaught exception after the
conversation itself has already produced real turns — here, because the
underlying provider call's final retry exhausted and raised past Hermes' own
agent-loop retry logic — that exception propagates out of `run_job` and is
caught and logged by `cron.scheduler` itself, a code path distinct from, and
evidently upstream of, whatever normally triggers `on_session_end` /
`on_session_finalize` for a cron run. The 2026-08-13 claim at
`docs/plugin-interface.md:73` ("Cron (`hermes cron run`) — **identical full
lifecycle**, including `on_session_end`") should be read as "identical
dispatch mechanism when the scheduler's own `run_job` returns normally," not
as "cron sessions always complete a turn and hit a boundary" — that probe
used one successful completed exchange and never exercised an error-raising
run.

**Corroborating pattern, not independently re-measured.** The same
`cron.scheduler: Job '...' failed` error signature appears 20 times in this
host's full `journalctl -u hermes-gateway` history back to 2026-06-09,
clustered around provider-credit exhaustion events (several in a row,
2026-08-04 through 2026-08-11) and isolated incidents elsewhere (2026-06-16,
06-17, 06-20, 06-21, 06-24, 07-07, 07-18, 07-19, 07-27, 07-28, 08-11(x2),
2026-09-26). All but the 2026-09-26 occurrence are now outside the 30-day
retention window and cannot be independently re-verified against their own
marker/sentinel state the way the named session was — they are named here as
a consistent pattern across four months, not as an additional measurement.

### What this does not establish

- **Single session, single host, single probe pass.** The verdict rests on
  one named defect session (`cron_138a635e0812_20260926_070034`), read once,
  on this date. The 20-occurrence historical pattern is corroboration by
  error-message shape, not 20 independently re-confirmed marker/sentinel
  absences — those sessions' marker and sentinel state cannot be
  re-established now that they are past the retention window.
- **This does not establish Hermes' native cron scheduling semantics beyond
  what this session's own `state.db` row and the system log show.** Exactly
  why `cron/scheduler.py`'s exception-handling path (upstream of `run_job`'s
  `raise`) does not also invoke `on_session_end` / `on_session_finalize` the
  way a normal-return path does is not established from this repository's
  own code — Hermes' `cron/scheduler.py` is not part of this skill and was
  not read beyond the one traceback frame the log itself printed
  (`cron/scheduler.py:5751`).
- **The deployed-tree currency caveat from `## The environment` applies to
  every `__init__.py` / `classifier.py` citation above.** `git diff --stat
  ed1fa95..HEAD -- skills/` is empty, so every line number cited is read
  against both this repository's HEAD and the tree plan 01 confirmed
  byte-identical to `ed1fa95` on this host, by sha256, in both
  plugin-discovery locations — not against a possibly-stale assumption.
- **A non-error-path trigger for the same "neither" shape is not ruled
  out.** This record found exactly one live example, and its cause was a
  scheduler-level exception. A different cron run that reaches "neither" by
  some other upstream path (unrelated to a `run_job` exception) is not
  demonstrated to be impossible — only unobserved in the one unpruned
  instance this host currently has.
