# Phase 7: Job Marker Schema & State Scaffolding - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-15
**Phase:** 7-job-marker-schema-state-scaffolding
**Areas discussed:** Job marker field schema, Task-to-job attribution, Job-taxonomy path scaffolding, Reader dedup for job lines

---

## Job Marker Field Schema

### Key naming convention

| Option | Description | Selected |
|--------|-------------|----------|
| snake_case (match v1.0 markers) | kind, ts, sid, agentic_job_id, job_name, job_type, status — consistent with the v1.0 task marker keys in the same file | ✓ |
| camelCase (match config files) | agenticJobId, jobName, jobType — matches PROJECT.md prose and config.json/budget-status.json, but those are different files | |

### Reader-required field set

| Option | Description | Selected |
|--------|-------------|----------|
| id + type + status | agentic_job_id, job_type, status all required; job_name/ts optional | ✓ |
| id only | only agentic_job_id required; type and status defaulted | |
| id + status | id and status required; job_type defaulted | |

**User's choice:** snake_case keys; reader requires `agentic_job_id` + `job_type` + `status`.
**Notes:** A job line missing any of the three required fields is not actionable (cannot be created or have an outcome reported), so the reader skips it. Required-set is a job-only validation gate, distinct from the unchanged task-marker `REQUIRED_KEYS`.

---

## Task-to-Job Attribution

| Option | Description | Selected |
|--------|-------------|----------|
| Positional delimiter | Job marker claims all task markers above it in file order, back to the prior job marker or file start; no linkage fields | ✓ |
| Explicit muid manifest | Job marker carries an array of the task-marker muids in its arc; agent re-reads its own file at arc end | |

**User's choice:** Positional delimiter (Claude's recommendation, accepted — user said "do whatever you think is best for this one").
**Notes:** Explicit per-task back-references were already ruled out: retrospective declaration (DECLARE-01) means a task marker cannot carry a job id at write time. Positional keeps v1.0 task markers byte-identical (SCHEMA-04). Caveat carried to Phase 9: `--task-id` only lands on `meter completion` calls in a tick where the job marker is already in the file.

---

## Job-Taxonomy Path Scaffolding

| Option | Description | Selected |
|--------|-------------|----------|
| Declare both, mirror conventions | common.sh declares JOBS_LEDGER_FILE and JOB_TAXONOMY_FILE with the :- env-override shape; JOB_TAXONOMY_FILE unused until v2 | ✓ |
| Ledger only, defer taxonomy | Declare only JOBS_LEDGER_FILE now; add the taxonomy path in v2 (YAGNI) | |

**User's choice:** Declare both, mirroring `LEDGER_FILE` / `TAXONOMY_FILE` conventions.
**Notes:** Honors roadmap SC-1 literally. `JOB_TAXONOMY_FILE` is forward-compat scaffolding — no reader/writer in v1.1; Phase 8 job types come from a closed seed vocab shipped with the skill.

---

## Reader Dedup for Job Lines

| Option | Description | Selected |
|--------|-------------|----------|
| Last-wins dedup by id | Reader collapses collected job lines to one per agentic_job_id, last line in file order winning | ✓ |
| Collect all, no dedup | Reader returns every valid job line; dedup left entirely to Phase 9/10 ledgers | |

**User's choice:** Last-wins dedup by `agentic_job_id` in the reader.
**Notes:** The marker file is append-only and re-read every cron tick, so a job line is seen repeatedly. Last-wins gives downstream phases a clean unique list and resolves a self-corrected re-declaration deterministically.

## Claude's Discretion

- Exact env-var names (`REVENIUM_JOBS_LEDGER_FILE`, etc.) and the insertion point in `common.sh`.
- Internal Python structure of the reader `kind` branch.
- Whether the `revenium-jobs.ledger` line grammar is pinned in Phase 7 or deferred to Phase 9 planning (Phase 7 must at minimum declare and `touch`-create the file).

## Deferred Ideas

- Host-grown job taxonomy — `JOB_TAXONOMY_FILE` declared now but no reader/writer until v2 `JOBTAX-01`.
- `revenium-jobs.ledger` line grammar — Phase 9/10 planning if not pinned in Phase 7.
- Outcome enrichment fields (`outcome_type` / `outcome_value`) on the job marker — v2 `ENRICH-01/02`.
