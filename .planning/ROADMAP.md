# Roadmap: Hermes-Revenium Task-Type Metering

**Project:** Brownfield extension to the `revenium` Hermes skill adding per-turn task attribution and agentic-job tracking.

Every metered completion that leaves this skill carries an accurate, consistently-spelled `--task-type` so Revenium analytics group spend by what the agent actually did, not just by session. v1.1 extends this with agentic-job tracking: spend rolls up under discrete, goal-directed task arcs that carry a business outcome.

## Milestones

- ✅ **v1.0 — Task-Type Metering** (shipped 2026-05-15) — see [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)
- 🚧 **v1.1 — Agentic Job Tracking** (in progress) — Phases 7-11

## Phases

<details>
<summary>✅ v1.0 Task-Type Metering (Phases 1-6) — SHIPPED 2026-05-15</summary>

- [x] Phase 1: Path Foundation (1/1 plans) — completed 2026-05-12
- [x] Phase 2: Prompt Design & Marker Contract (3/3 plans) — completed 2026-05-12
- [x] Phase 3: Cron Marker Reader + Equal-Split + Ledger v2 (1/1 plans) — completed 2026-05-13
- [x] Phase 4: Wire Enrichment (1/1 plans) — completed 2026-05-14, verified via UAT 5/5
- [x] Phase 5: Housekeeping & Compat Hardening (4/4 plans) — completed 2026-05-15, verified via live Mac Studio operator UAT
- [x] Phase 6: Mechanical Classification via Hermes agent:end Hook (4/4 plans) — completed 2026-05-14, verified via UAT round 4

Plus 3 quick tasks shipped 2026-05-14 in response to live Mac Studio diagnostic chain (D-07 removal, mint-first prompt rewrite, state.db content lookup). See `.planning/STATE.md` Quick Tasks Completed section + `.planning/quick/` for details.

Full detail: [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)
Requirements: [milestones/v1.0-REQUIREMENTS.md](./milestones/v1.0-REQUIREMENTS.md)
Summary: [MILESTONES.md](./MILESTONES.md)

</details>

### 🚧 v1.1 Agentic Job Tracking (In Progress)

**Milestone Goal:** The skill identifies discrete task arcs as Revenium *agentic jobs* — creating each, attributing its AI transactions via `--task-id`, and reporting its immutable outcome — so spend ties to units of business work, not just sessions or turn-level task-types. Every cron-pipeline phase ships behind the v1.0 backward-compat guarantee: a job-less or marker-less session meters byte-identically to v1.0.

- [ ] **Phase 7: Job Marker Schema & State Scaffolding** - Freeze the `kind:"job"` marker contract, declare `revenium-jobs.ledger`, teach the cron reader to branch on `kind` — pure additive, no behavior change.
- [ ] **Phase 8: Job Declaration Prompt Block** - `SKILL.md` instructs the agent to declare one job per task arc at arc end, with anti-collapse `agenticJobId` minting and conservative outcome criteria.
- [ ] **Phase 9: Cron Job Creation & `--task-id` Linkage** - Pre-loop `jobs create` stage and in-loop conditional `--task-id` stamping, both idempotent and best-effort.
- [ ] **Phase 10: Cron Outcome Reporting & Idempotency** - Post-loop `jobs outcome` stage with API-first / ledger-on-exit-0 ordering, 409-as-success, and the double-report idempotency test.
- [ ] **Phase 11: v1.0 Carry-Forward Hardening** - Discharge v1.0 tech debt: taxonomy `flock`, `clear-halt.sh` bash 3.2 fix, retention guard, dead-helper removal.

## Phase Details

### Phase 7: Job Marker Schema & State Scaffolding
**Goal**: Freeze the agent↔cron contract for jobs — the single synchronization point everything downstream depends on — and add the idempotency ledger before any job call exists. Pure additive scaffolding: no behavior change, no new wire output.
**Depends on**: Phase 6 (v1.0 marker reader / `common.sh` path discipline)
**Requirements**: SCHEMA-01, SCHEMA-02, SCHEMA-03, SCHEMA-04, SCHEMA-05, TEST-01, TEST-02
**Success Criteria** (what must be TRUE):
  1. `JOBS_LEDGER_FILE` (for `revenium-jobs.ledger`) and the optional job-taxonomy path are declared only in `scripts/common.sh` with the `:-` env-override shape, and `revenium-jobs.ledger` is `touch`-created on cron run — `test_runtime_paths_are_hermes_native` still passes.
  2. The `kind:"job"` JSONL line schema is defined and documented as an additive extension of the existing `markers/<sid>.jsonl` contract — never a per-turn field, never a separate file — and a test pins its shape.
  3. The cron marker reader branches on `kind`: absent `kind` is parsed as `"task"` (v1.0 path), `kind:"job"` is collected as a job declaration, unknown `kind` is skipped — and `REQUIRED_KEYS` for task markers is unchanged so an un-modified v1.0 cron skips job lines rather than crashing.
  4. A regression test asserts a job-less / marker-less session produces byte-identical `revenium meter completion` argv to v1.0 — backward compatibility is verified, not assumed.
**Plans**: 1 plan
- [x] 07-01-PLAN.md — common.sh path scaffolding, kind-aware marker reader branch, TEST-01/TEST-02 invariant tests

### Phase 8: Job Declaration Prompt Block
**Goal**: The Hermes agent reliably declares one well-formed, business-meaningful job per completed task arc — minting a specific `agenticJobId`, selecting a seed job type, and self-reporting a conservative outcome — including on the budget-halt path.
**Depends on**: Phase 7 (job-marker schema must be frozen)
**Requirements**: DECLARE-01, DECLARE-02, DECLARE-03, DECLARE-04, DECLARE-05, DECLARE-06
**Success Criteria** (what must be TRUE):
  1. `SKILL.md` has a new `## FINAL ACTION — JOB DECLARATION` section instructing the agent to append exactly one `kind:"job"` marker per completed task arc, retrospectively at arc end — never mid-arc, never prospectively.
  2. The agent mints an `agenticJobId` as an LLM business label plus a short hex entropy suffix, with mint-first anti-collapse prompt framing (concrete good/bad examples) so labels stay specific, and selects each job's `type` from a closed seed vocabulary of coding-agent job types shipped with the skill.
  3. The prompt gives an operational arc-boundary definition so a multi-activity session produces multiple distinct jobs, and gives conservative `SUCCESS`/`FAILED`/`CANCELLED` criteria — `SUCCESS` only on a confirmed met goal, bias to `CANCELLED` under uncertainty.
  4. The budget-halt path writes a `CANCELLED` terminal job marker before emitting the verbatim halt string, so a budget-interrupted arc still gets an outcome — and the halt-survivability runbook still passes after the `SKILL.md` edit.
**Plans**: 2 plans
- [ ] 08-01-PLAN.md — ship the job-taxonomy.json seed, setup-local.sh seed->live copy, and test invariants
- [ ] 08-02-PLAN.md — add the SKILL.md JOB DECLARATION section, reconcile the HALT CHECK block, amend halt-survivability.md
**UI hint**: yes

### Phase 9: Cron Job Creation & `--task-id` Linkage
**Goal**: The cron pipeline mints each declared job server-side exactly once and stamps every owning transaction with `--task-id`, as a best-effort enrichment that never blocks or alters the v1.0 metering path.
**Depends on**: Phase 7 (jobs ledger + reader), Phase 8 (agent declares jobs)
**Requirements**: CREATE-01, CREATE-02, CREATE-03, CREATE-04
**Success Criteria** (what must be TRUE):
  1. A cron preflight detects whether the installed `revenium` CLI supports `jobs` and `meter completion --task-id`, and fails open — skipping job work and metering exactly as v1.0 with a `warn` — when it does not.
  2. The cron runs `revenium jobs create` once per `agenticJobId`, idempotently — gated on a `revenium-jobs.ledger` `created` line so per-minute re-runs never double-create, with HTTP 409 treated as success-equivalent.
  3. Every `revenium meter completion` call belonging to a declared job carries `--task-id <agenticJobId>`; job-less markers and the zero-marker fallthrough stay byte-identical to v1.0.
  4. Job creation is best-effort — a failed or unavailable `jobs create` logs a `warn` and never blocks or fails the token-metering path.
**Plans**: TBD

### Phase 10: Cron Outcome Reporting & Idempotency
**Goal**: The cron reports each terminated arc's immutable outcome to Revenium exactly once, with a partial-failure posture that can never lose or double-report an outcome.
**Depends on**: Phase 7 (jobs ledger), Phase 9 (job must exist server-side before its outcome can attach)
**Requirements**: OUTCOME-01, OUTCOME-02, OUTCOME-03, OUTCOME-04, OUTCOME-05, TEST-03
**Success Criteria** (what must be TRUE):
  1. The cron reports `revenium jobs outcome` exactly once per terminated arc — gated on a `revenium-jobs.ledger` outcome line and on a locally-confirmed `JOB:<id>:created` line, deferring to the next cron tick (no hand-rolled retry loop) if the job's create has not yet been confirmed.
  2. The outcome API call is made first and the ledger line is appended only on exit 0 as the last statement of the success branch, so a partial failure can never lose an outcome permanently; an HTTP 409 ("outcome already reported") is treated as success-equivalent and the CLI exit code is never trusted as the idempotency signal.
  3. The `--result` value is derived verbatim and deterministically from the job marker, with agent-supplied status normalized to uppercase before the call.
  4. A test asserts that re-running the cron never double-creates a job or double-reports an outcome.
**Plans**: TBD

### Phase 11: v1.0 Carry-Forward Hardening
**Goal**: Discharge the four tech-debt items acknowledged at v1.0 close — no functional dependency on the job work, runs as the final phase or in parallel.
**Depends on**: Nothing (independent track — can run in parallel with Phases 7-10)
**Requirements**: HARDEN-01, HARDEN-02, HARDEN-03, HARDEN-04
**Success Criteria** (what must be TRUE):
  1. `_persist_label_to_taxonomy` uses `fcntl.flock` so two concurrent `on_session_end` events cannot race on the taxonomy file.
  2. `clear-halt.sh` no longer uses bash 4.4+ `${VAR@Q}` syntax and runs correctly on bash 3.2.
  3. `prune-markers.sh` validates `REVENIUM_MARKER_RETENTION_DAYS >= 1`, refusing to run rather than silently deleting everything when set to 0.
  4. The dead `_count_tools_in_current_turn` helper is removed once confirmed to have no callers post-v1.0.
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 7 → 8 → 9 → 10 → 11. Phase 11 (Hardening) has no functional dependency on 7-10 and may be executed in parallel or pulled earlier.

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Path Foundation | v1.0 | 1/1 | Complete | 2026-05-12 |
| 2. Prompt Design & Marker Contract | v1.0 | 3/3 | Complete | 2026-05-12 |
| 3. Cron Marker Reader + Equal-Split + Ledger v2 | v1.0 | 1/1 | Complete | 2026-05-13 |
| 4. Wire Enrichment | v1.0 | 1/1 | Verified | 2026-05-14 |
| 5. Housekeeping & Compat Hardening | v1.0 | 4/4 | Verified | 2026-05-15 |
| 6. Mechanical Classification via agent:end Hook | v1.0 | 4/4 | Verified | 2026-05-14 |
| 7. Job Marker Schema & State Scaffolding | v1.1 | 0/1 | Planned | - |
| 8. Job Declaration Prompt Block | v1.1 | 0/2 | Planned | - |
| 9. Cron Job Creation & `--task-id` Linkage | v1.1 | 0/TBD | Not started | - |
| 10. Cron Outcome Reporting & Idempotency | v1.1 | 0/TBD | Not started | - |
| 11. v1.0 Carry-Forward Hardening | v1.1 | 0/TBD | Not started | - |
