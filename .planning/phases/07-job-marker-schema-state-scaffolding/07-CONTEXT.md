# Phase 7: Job Marker Schema & State Scaffolding - Context

**Gathered:** 2026-05-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Freeze the agent↔cron contract for agentic jobs and add the idempotency
ledger before any job call exists. Pure additive scaffolding: a new
`kind:"job"` JSONL line shape, a new `revenium-jobs.ledger` state file, a new
job-taxonomy path, and a `kind`-aware branch in the cron marker reader.

**No behavior change, no new wire output.** A job-less or marker-less session
must produce byte-identical `revenium meter completion` argv to v1.0. This
phase ships the schema and scaffolding that Phases 8–10 build on; it does not
itself call `revenium jobs create`, stamp `--task-id`, or report outcomes.

Requirements covered: SCHEMA-01, SCHEMA-02, SCHEMA-03, SCHEMA-04, SCHEMA-05,
TEST-01, TEST-02.

</domain>

<decisions>
## Implementation Decisions

### Job Marker Line Schema (SCHEMA-02, TEST-01)
- **D-01:** The `kind:"job"` marker is an additive JSONL line in the existing
  per-session `markers/<sid>.jsonl` file — never a per-turn field on a task
  marker, never a separate file. It is discriminated solely by the `kind` key.
- **D-02:** Job marker keys are **snake_case**, consistent with the v1.0 task
  marker keys (`muid`, `ts`, `sid`, `task_type`, `operation_type`) that live in
  the same file. The conceptual `agenticJobId` term from PROJECT.md becomes the
  key `agentic_job_id`. config.json / budget-status.json camelCase is a
  different contract and does not apply here.
- **D-03:** Canonical job marker shape:
  ```json
  {"kind":"job","ts":1747300000.12,"sid":"abc123",
   "agentic_job_id":"pr-review-fc7a","job_name":"Review PR #42",
   "job_type":"code_review","status":"SUCCESS"}
  ```
- **D-04:** Reader-required keys for a `kind:"job"` line to be **accepted** as a
  valid job declaration: `kind`, `agentic_job_id`, `job_type`, `status`. A job
  line missing any of these is skipped (it cannot be created or have an outcome
  reported, so it is not actionable). `job_name`, `ts`, `sid` are optional.
- **D-05:** "Reader-required" (D-04) is a separate, job-only validation gate —
  it is NOT the task-marker `REQUIRED_KEYS` tuple. `REQUIRED_KEYS` for task
  markers stays exactly `('muid', 'ts', 'sid', 'task_type', 'operation_type')`,
  unchanged. All job-marker fields are read with `.get()` so a missing field
  never raises (SCHEMA-05).

### Cron Reader `kind` Branching (SCHEMA-03, SCHEMA-05)
- **D-06:** The marker reader in `hermes-report.sh` branches on `kind`:
  - **absent `kind`** → parsed as a v1.0 task marker (`"task"` path),
    byte-identical behavior.
  - **`kind:"job"`** → collected as a job declaration.
  - **any other `kind` value** → skipped (unknown-kind forward-compat).
- **D-07:** Because the existing v1.0 reader already drops any line failing the
  task-marker `REQUIRED_KEYS` check, an *un-modified* v1.0 cron naturally skips
  `kind:"job"` lines rather than crashing — SCHEMA-05 backward-compat is
  preserved without a separate guard.

### Task-to-Job Attribution Model
- **D-08:** Attribution is **positional (delimiter-based)**. A `kind:"job"`
  marker — appended as the agent's FINAL ACTION at arc end — claims all task
  markers *above it in file order*, back to the previous `kind:"job"` marker
  or the start of the file. A multi-arc session file is therefore a sequence
  of delimited segments.
- **D-09:** The job marker carries **no per-task linkage fields** (no muid
  list, no ranges). v1.0 task markers are written unchanged and stay
  byte-identical — this is required by SCHEMA-04 and avoids touching the v1.0
  `SKILL.md` snippet and the Phase 6 classifier plugin.
- **D-10:** Explicit per-task back-references were rejected: jobs are declared
  retrospectively (DECLARE-01), so a task marker cannot carry a job id at
  write time — the id does not yet exist.
- **D-11:** Task markers appearing *after* the last `kind:"job"` marker in a
  file belong to an undeclared arc; they meter exactly as v1.0 (no `--task-id`).

### Reader Job-Line Deduplication
- **D-12:** The reader collects all valid `kind:"job"` lines, then collapses to
  **one declaration per `agentic_job_id`, last line in file order winning**.
  The marker file is append-only and re-read every cron tick, so a job line is
  observed repeatedly; last-wins gives downstream phases a clean, deterministic
  unique list and resolves a self-corrected re-declaration predictably.

### State Path Scaffolding (SCHEMA-01)
- **D-13:** `scripts/common.sh` declares **both** new paths, and only there,
  using the existing `:-` env-override fallback shape:
  - `JOBS_LEDGER_FILE="${REVENIUM_JOBS_LEDGER_FILE:-${STATE_DIR}/revenium-jobs.ledger}"`
    — mirrors `LEDGER_FILE`.
  - `JOB_TAXONOMY_FILE="${REVENIUM_JOB_TAXONOMY_FILE:-${STATE_DIR}/job-taxonomy.json}"`
    — mirrors `TAXONOMY_FILE`.
  (Exact env-var spelling is a planner detail; the `:-` shape and
  `common.sh`-only declaration are locked.)
- **D-14:** `revenium-jobs.ledger` is a **separate file** from
  `revenium-hermes.ledger` — never reuse the metering ledger; its 4-vs-5
  colon-field discrimination would break.
- **D-15:** `revenium-jobs.ledger` is `touch`-created on cron run (so it always
  exists for Phase 9/10 readers). `JOB_TAXONOMY_FILE` is declared for
  forward-compat / single-source discipline but is **unused in v1.1** — it has
  no reader or writer until v2 `JOBTAX-01`. Phase 8 job types come from a
  closed seed vocabulary shipped with the skill, not from this host path.

### Claude's Discretion
- Exact env-var names (`REVENIUM_JOBS_LEDGER_FILE` etc.), the precise line of
  `common.sh` to insert declarations, and the internal Python structure of the
  reader branch are planner/executor choices.
- Whether `revenium-jobs.ledger` line format is fully specified in Phase 7 or
  deferred to Phase 9 — Phase 7 must at minimum declare and `touch`-create the
  file; the `JOB:<id>:created` / outcome line grammar may be pinned here or in
  Phase 9 planning.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements & decisions
- `.planning/REQUIREMENTS.md` — SCHEMA-01..05, TEST-01, TEST-02 definitions.
- `.planning/ROADMAP.md` §"Phase 7" — goal, success criteria, dependency on
  Phase 6.
- `.planning/PROJECT.md` §"Key Decisions" — the v1.1 job-tracking decision
  rows (`agenticJobId` = LLM label + entropy suffix; `--task-id` wire link;
  immutable one-shot outcomes).
- `.planning/STATE.md` §"Accumulated Context" — phase-ordering rationale and
  the separate-`revenium-jobs.ledger` decision.

### v1.0 marker & state contract (what this phase extends)
- `skills/revenium/scripts/common.sh` — single source of all state paths;
  the *only* file new paths may be declared in. `TAXONOMY_FILE` /
  `LEDGER_FILE` are the shape templates for the new declarations.
- `skills/revenium/scripts/hermes-report.sh` §marker reader (~lines 314–446)
  — the `REQUIRED_KEYS` check and per-line parse loop the `kind` branch is
  added to.
- `skills/revenium/scripts/split_strategies.py` — `parse_prior_state` helper
  used by the reader; do not break its contract.
- `skills/revenium/SKILL.md` §"FINAL ACTION — TASK CLASSIFICATION" — the v1.0
  task marker write snippet and the `{muid,ts,sid,task_type,operation_type}`
  shape the job line sits alongside.
- `skills/revenium/references/task-taxonomy.md` — v1.0 taxonomy schema and
  normalization rules; the `job-taxonomy.json` path mirrors this.

### Test enforcement
- `tests/test_repository.py` — `test_runtime_paths_are_hermes_native`
  (must still pass after new path declarations), `test_shell_scripts_have_valid_syntax`.
  TEST-01 (pin job marker shape) and TEST-02 (byte-identical argv regression)
  are added here.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `common.sh` path-declaration pattern: `VAR="${ENV_OVERRIDE:-${STATE_DIR}/file}"`
  — `LEDGER_FILE`, `TAXONOMY_FILE`, `MARKERS_DIR` are direct templates for
  `JOBS_LEDGER_FILE` and `JOB_TAXONOMY_FILE`.
- The `hermes-report.sh` marker reader is a Python heredoc with a per-line
  `try/except` parse loop, a `REQUIRED_KEYS` membership check, and a
  `markers.append(m)` collector — the `kind` branch slots into this loop.
- `mkdir -p` block at `common.sh:24` is where a `touch` of the jobs ledger /
  ensure-exists logic can live, alongside the existing dir creation.

### Established Patterns
- Marker JSONL: one compact JSON object per line, `json.dumps(...,
  separators=(",",":"))`, snake_case keys.
- Reader resilience: torn/oversized/malformed lines are skipped, never fatal
  (MARK-04 / D-15); the `kind` branch must preserve this — unknown `kind`
  and incomplete job lines are skipped, not raised.
- Idempotency lives in append-only ledgers keyed on a stable id; the cron is
  re-run every minute and must be safe to re-run.

### Integration Points
- New paths: `scripts/common.sh` only.
- Reader branch: the per-line loop inside the marker-reader heredoc in
  `scripts/hermes-report.sh`.
- New tests: `tests/test_repository.py` (or a sibling `test_*.py`) — job
  marker shape pin + v1.0 argv regression.

</code_context>

<specifics>
## Specific Ideas

- Job marker shape is fixed verbatim per D-03 — TEST-01 pins exactly this
  key set and the snake_case spelling.
- Long-arc `--task-id` caveat (carry into Phase 9 planning): under the
  positional model (D-08), `--task-id` can only be stamped on `meter
  completion` calls emitted in a cron tick where the job marker is *already
  present* in the file. Task markers metered in earlier cron windows of a
  long, multi-minute arc ship without `--task-id`. This is an accepted
  approximation, consistent with the S2 equal-split approximation — it is not
  a Phase 7 deliverable but must not surprise the Phase 9 planner.

</specifics>

<deferred>
## Deferred Ideas

- **Host-grown job taxonomy** — `JOB_TAXONOMY_FILE` is declared now (D-13/D-15)
  but has no reader/writer until v2 `JOBTAX-01`. Phase 8 uses a closed seed
  vocabulary shipped with the skill.
- **`revenium-jobs.ledger` line grammar** — if not pinned in Phase 7, it is a
  Phase 9 (`JOB:<id>:created`) / Phase 10 (outcome line) planning decision.
- **Outcome enrichment** (`outcome_type` / `outcome_value` fields on the job
  marker) — v2 `ENRICH-01/02`; not part of the D-03 frozen shape.

None of the above is scope creep into Phase 7 — all are explicitly later
milestone/phase work.

</deferred>

---

*Phase: 7-job-marker-schema-state-scaffolding*
*Context gathered: 2026-05-15*
