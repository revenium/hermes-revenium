# Requirements: Hermes-Revenium — v1.1 Agentic Job Tracking

**Defined:** 2026-05-14
**Core Value:** Every metered completion that leaves this skill carries an accurate, consistently-spelled `--task-type` so Revenium analytics group spend by what the agent actually did, not just by session. v1.1 extends this with agentic-job tracking: spend rolls up under discrete, goal-directed task arcs that carry a business outcome.

## v1 Requirements

Requirements for milestone v1.1. Each maps to exactly one roadmap phase.

### Marker Schema & State (SCHEMA)

State scaffolding and the agent↔cron contract extension. Pure additive — no behavior change, freezes the schema everything downstream depends on.

- [ ] **SCHEMA-01**: New state paths (`JOBS_LEDGER_FILE` for `revenium-jobs.ledger`, and a job-taxonomy file) are declared in `scripts/common.sh` and nowhere else, following the existing `:-` env-override fallback shape.
- [ ] **SCHEMA-02**: A `kind:"job"` JSONL line schema is defined and documented as an additive extension to the existing `markers/<sid>.jsonl` contract — never a per-turn field, never a separate file.
- [ ] **SCHEMA-03**: The cron marker reader branches on `kind`: absent `kind` is treated as `"task"` (v1.0 path byte-identical), `kind:"job"` is parsed as a job declaration, unknown `kind` is skipped.
- [ ] **SCHEMA-04**: A job-less or marker-less session produces byte-identical `revenium meter completion` argv to v1.0 — backward compatibility is verified, not assumed.
- [ ] **SCHEMA-05**: New job-marker fields are `.get()`-optional; `REQUIRED_KEYS` for task markers is unchanged so an un-modified v1.0 cron skips job lines rather than crashing.

### Job Declaration (DECLARE)

The agent-side contract — `SKILL.md` prompt instructing the Hermes agent to declare jobs.

- [ ] **DECLARE-01**: The agent declares a job for each completed task arc by appending a `kind:"job"` marker in its FINAL ACTION, retrospectively (once, at arc end — never mid-arc, never prospectively).
- [ ] **DECLARE-02**: The agent mints an `agenticJobId` as an LLM business label plus a short hex entropy suffix (e.g. `pr-review-fc7a`), with mint-first anti-collapse prompt framing so labels stay specific.
- [ ] **DECLARE-03**: The agent identifies task-arc boundaries within a single Hermes session so one multi-activity session produces multiple distinct jobs.
- [ ] **DECLARE-04**: The agent selects each job's `type` from a closed seed vocabulary of coding-agent job types shipped with the skill.
- [ ] **DECLARE-05**: The agent self-reports an execution status of `SUCCESS`, `FAILED`, or `CANCELLED` per job, using conservative criteria (report `SUCCESS` only on a confirmed met goal; bias to `CANCELLED` under uncertainty).
- [ ] **DECLARE-06**: The budget-halt path writes a `CANCELLED` terminal job marker before emitting the verbatim halt string, so a budget-interrupted arc still gets an outcome.

### Cron Job Creation & Linkage (CREATE)

The cron-side pipeline that mints jobs server-side and links transactions to them.

- [ ] **CREATE-01**: The cron preflight detects whether the installed `revenium` CLI supports `jobs` and `meter completion --task-id`, and fails open (skips job work, meters as v1.0) with a `warn` when it does not.
- [ ] **CREATE-02**: The cron runs `revenium jobs create` once per `agenticJobId`, idempotently — gated on a local `revenium-jobs.ledger` line so per-minute re-runs never double-create.
- [ ] **CREATE-03**: The cron stamps `--task-id <agenticJobId>` on every `revenium meter completion` call belonging to a declared job.
- [ ] **CREATE-04**: Job creation is best-effort — a failed or unavailable `jobs create` never blocks or fails the token-metering path.

### Cron Outcome Reporting (OUTCOME)

The cron-side terminal stage — reporting each job's immutable outcome exactly once.

- [ ] **OUTCOME-01**: The cron reports `revenium jobs outcome` exactly once per terminated arc, gated on a `revenium-jobs.ledger` outcome line.
- [ ] **OUTCOME-02**: The outcome API call is made first and the ledger line is appended only on exit 0 (as the last statement of the success branch), so a partial failure can never lose an outcome permanently.
- [ ] **OUTCOME-03**: An HTTP 409 ("outcome already reported") is treated as success-equivalent; the CLI exit code is never trusted as the idempotency signal.
- [ ] **OUTCOME-04**: `jobs outcome` is gated on a locally-confirmed `JOB:<id>:created` ledger line and deferred to the next cron tick if the job's create has not yet been confirmed — no hand-rolled retry loop.
- [ ] **OUTCOME-05**: The `--result` value is derived verbatim and deterministically from the job marker; agent-supplied status is normalized to uppercase before the call.

### Hardening — v1.0 Carry-Forward (HARDEN)

Tech debt acknowledged at v1.0 close, discharged in this milestone.

- [ ] **HARDEN-01**: `_persist_label_to_taxonomy` uses `fcntl.flock` so two concurrent `on_session_end` events cannot race on the taxonomy file.
- [ ] **HARDEN-02**: `clear-halt.sh` no longer uses bash 4.4+ `${VAR@Q}` syntax and runs correctly on bash 3.2.
- [ ] **HARDEN-03**: `prune-markers.sh` validates `REVENIUM_MARKER_RETENTION_DAYS >= 1`, refusing to run (rather than silently deleting everything) when set to 0.
- [ ] **HARDEN-04**: The dead `_count_tools_in_current_turn` helper is removed once confirmed to have no callers post-v1.0.

### Test Coverage (TEST)

Invariant tests that pin the v1.1 contracts — this repo's contracts are test-enforced.

- [ ] **TEST-01**: A test pins the `kind:"job"` marker schema shape.
- [ ] **TEST-02**: A regression test asserts a job-less marker produces byte-identical `meter completion` argv to v1.0.
- [ ] **TEST-03**: A test asserts re-running the cron never double-creates a job or double-reports an outcome (idempotency).

## v2 Requirements

Deferred to a future milestone. Tracked but not in the v1.1 roadmap.

### Outcome Enrichment

- **ENRICH-01**: The agent self-reports a business `outcome-type` (`DEFLECTED` / `UNSUCCESSFUL` / `ESCALATED`) when it has honest signal.
- **ENRICH-02**: The cron passes a `--metadata` JSON payload (PR url, branch, test status, files-changed) on `jobs outcome`.
- **ENRICH-03**: `--environment`, `--version`, and `--reported-by` static config values are passed through on job calls.

### Abandoned-Arc Recovery

- **STALE-01**: A cron-side staleness sweeper posts `CANCELLED` for jobs whose arc never wrote a terminal marker after a configurable window.

### Job Taxonomy Management

- **JOBTAX-01**: A job-type taxonomy file with descriptions, parallel to `task-taxonomy.json`, replaces the closed seed list if it proves too rigid.

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Monetary `--outcome-value` reporting | A coding agent has no honest dollar valuation model; agent-inferred revenue figures would be fiction. Operator-supplied values are a v2+ opt-in. |
| `CONVERTED` business outcome-type | Not honestly agent-reportable for a devops/coding agent; belongs to operator-supplied outcomes. |
| Server-side job-type curation on Revenium | Job types live locally in the skill's seed vocabulary; how Revenium surfaces them is its concern. |
| Hand-rolled retry/backoff loop for the async create→outcome race | The Revenium docs explicitly warn against it; the 60s cron cadence is the retry. |
| Polling `jobs get` until a job exists | Would fight the `cron.lock` and block the per-minute tick; correlation-by-`task-id` absorbs the race. |
| Retroactive job assignment to historical sessions | Only sessions the agent declares jobs for going forward get tracked — consistent with the v1.0 no-backfill stance. |
| Cross-session job threading | Jobs are scoped to a single Hermes session, as markers are. |

## Traceability

Which phases cover which requirements. Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SCHEMA-01 | Phase 7 | Pending |
| SCHEMA-02 | Phase 7 | Pending |
| SCHEMA-03 | Phase 7 | Pending |
| SCHEMA-04 | Phase 7 | Pending |
| SCHEMA-05 | Phase 7 | Pending |
| DECLARE-01 | Phase 8 | Pending |
| DECLARE-02 | Phase 8 | Pending |
| DECLARE-03 | Phase 8 | Pending |
| DECLARE-04 | Phase 8 | Pending |
| DECLARE-05 | Phase 8 | Pending |
| DECLARE-06 | Phase 8 | Pending |
| CREATE-01 | Phase 9 | Pending |
| CREATE-02 | Phase 9 | Pending |
| CREATE-03 | Phase 9 | Pending |
| CREATE-04 | Phase 9 | Pending |
| OUTCOME-01 | Phase 10 | Pending |
| OUTCOME-02 | Phase 10 | Pending |
| OUTCOME-03 | Phase 10 | Pending |
| OUTCOME-04 | Phase 10 | Pending |
| OUTCOME-05 | Phase 10 | Pending |
| HARDEN-01 | Phase 11 | Pending |
| HARDEN-02 | Phase 11 | Pending |
| HARDEN-03 | Phase 11 | Pending |
| HARDEN-04 | Phase 11 | Pending |
| TEST-01 | Phase 7 | Pending |
| TEST-02 | Phase 7 | Pending |
| TEST-03 | Phase 10 | Pending |

**Coverage:**
- v1 requirements: 27 total
- Mapped to phases: 27 (100%) ✓
- Unmapped: 0

---
*Requirements defined: 2026-05-14*
*Last updated: 2026-05-15 after v1.1 roadmap creation (Phases 7-11)*
