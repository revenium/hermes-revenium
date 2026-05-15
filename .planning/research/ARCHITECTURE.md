# Architecture Research — v1.1 Agentic Job Tracking

**Domain:** Cron-driven usage-metering skill (Bash + Python heredocs + sqlite3 + `revenium` CLI)
**Researched:** 2026-05-14
**Confidence:** HIGH — verified against live `revenium` CLI behavior and the shipped v1.0 source.

This document answers a single integration question: **how do v1.1 agentic-job
features attach to the existing v1.0 two-half architecture without redesigning
it?** It is scoped for the roadmapper and phase planners. It names integration
points, marks NEW vs MODIFIED, and gives a dependency-ordered build sequence.

---

## 1. CLI Ground Truth (verified, not assumed)

These behaviors were probed against the live `revenium` CLI on 2026-05-14 and
**shape every design decision below**. Confidence: HIGH.

| Probe | Observed behavior | Design consequence |
|-------|-------------------|--------------------|
| `revenium jobs create --agentic-job-id <new>` | Exit 0, job created (`id`, `agenticJobId`, `hasOutcome:false`). | Create works. |
| `revenium jobs create --agentic-job-id <dup>` | **`HTTP 409 ... already exists`** printed to stderr, **exit code still 0**. | **Exit code is useless for idempotency.** Cron MUST NOT trust `$?`. |
| `revenium jobs get <missing>` | `Error: Resource not found.`, exit 0. | `get` is the reliable existence probe — parse JSON, not exit code. |
| `revenium jobs get <exists> --output json` | Full JSON: `agenticJobId`, `id`, `hasOutcome` (bool), `executionStatus` (null until outcome), `environment`, `name`, `label`. | `hasOutcome` is the authoritative "outcome already reported" flag. |
| `revenium jobs outcome <id> --result SUCCESS` | Exit 0, posts `{executionStatus: SUCCESS}` to `/v2/api/jobs/<id>/outcome`. | Outcome works. |
| `revenium jobs outcome <id> --result FAILED` (2nd call) | **`outcome already reported ... outcomes are immutable`**, **exit code still 0**. | Server enforces one-shot immutability — but cron still must not double-fire (analytics noise, log spam). |
| `revenium meter completion --task-id <v>` | Flag accepted: *"correlates the completion with an agentic job (use the same value as agenticJobId)"*. | `--task-id` value == `agenticJobId`. Pure pass-through, same shape as v1.0's `--task-type` passthrough. |
| `revenium jobs create` flags | `--agentic-job-id` (required), `--name`, `--type`, `--environment`, `--version`. | These five map directly onto the marker schema. |
| `revenium jobs outcome` flags | `--result` (required: SUCCESS/FAILED/CANCELLED), `--outcome-type`, `--outcome-value`, `--outcome-currency`, `--metadata`, `--reported-by`. | `result` is mandatory; the business fields are optional. |

**The load-bearing fact:** the `revenium` CLI exits 0 on `409 already exists`
and on `outcome already reported`. **The cron cannot use exit code to decide
whether a create/outcome succeeded, failed, or was a duplicate.** Idempotency
must therefore be enforced *locally* by a ledger (the v1.0 discipline), with
`jobs get --output json` as a secondary server-side reconciliation probe.

---

## 2. Standard Architecture — Where v1.1 Fits

### System Overview (v1.1 — NEW marked with ★)

```
┌──────────────────────────────────────────────────────────────────────┐
│  IN-SESSION HALF  (skill prompt, runs every Hermes turn)              │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ SKILL.md                                                       │  │
│  │  ├─ HALT CHECK / Budget Check        (v1.0, UNCHANGED)          │  │
│  │  ├─ FINAL ACTION — TASK CLASSIFICATION (v1.0, UNCHANGED)        │  │
│  │  │    writes task-type marker pairs to markers/<sid>.jsonl      │  │
│  │  └─ FINAL ACTION — JOB DECLARATION  (NEW ★)                     │  │
│  │       at task-arc end, appends ONE job marker line             │  │
│  └────────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ revenium-classifier plugin (on_session_end) — v1.0, UNCHANGED  │  │
│  │   writes task-type markers only; does NOT mint jobs            │  │
│  └────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ (filesystem only — no direct calls)
                ┌───────────────▼────────────────────────────┐
                │  SHARED STATE  ~/.hermes/state/revenium/    │
                │   config.json            (v1.0)            │
                │   budget-status.json     (v1.0)            │
                │   task-taxonomy.json     (v1.0)            │
                │   markers/<sid>.jsonl    (v1.0, schema ★)  │
                │   markers/.ready/<sid>   (v1.0)            │
                │   revenium-hermes.ledger (v1.0, 5-field)   │
                │   job-taxonomy.json      (NEW ★, optional) │
                │   revenium-jobs.ledger   (NEW ★)           │
                └───────────────┬────────────────────────────┘
                                │ (filesystem only)
┌───────────────────────────────▼──────────────────────────────────────┐
│  CRON HALF  (cron.sh, every minute, outside any Hermes session)       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ cron.sh — orchestrator (UNCHANGED: flock, env, child invokes)  │  │
│  │   └─ hermes-report.sh   (MODIFIED ★)                           │  │
│  │   └─ budget-check.sh    (UNCHANGED)                            │  │
│  └────────────────────────────────────────────────────────────────┘  │
│  hermes-report.sh new responsibilities (★):                          │
│   A. read job markers from markers/<sid>.jsonl alongside task markers │
│   B. PRE-LOOP: `jobs create` for every NEW agenticJobId (jobs ledger) │
│   C. IN-LOOP: stamp `--task-id <agenticJobId>` on meter completion    │
│   D. POST-LOOP: `jobs outcome` for every NEWLY-TERMINATED arc         │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                    revenium CLI → Revenium platform
                    (jobs create / meter completion --task-id / jobs outcome)
```

### Component Responsibilities (v1.1 delta only)

| Component | v1.1 Responsibility | NEW / MODIFIED | File |
|-----------|---------------------|----------------|------|
| Job-declaration prompt block | At task-arc end, agent appends one `kind:"job"` marker line (id, name, type, environment, result, optional outcome) | **NEW** | `SKILL.md` (new `## FINAL ACTION — JOB DECLARATION` section) |
| Marker reader | Parse both task-type lines and job lines from the same `<sid>.jsonl`; ignore unknown `kind` values | **MODIFIED** | `hermes-report.sh` (T04 marker-read heredoc) |
| Job create stage | Pre-loop pass: for each distinct un-created `agenticJobId` across all markers this tick, call `jobs create`, append jobs-ledger row on success-or-409 | **NEW** | `hermes-report.sh` (new function before the session `while` loop) |
| Task-id stamping | When a marker carries an owning `agentic_job_id`, append `--task-id <id>` to that marker's `meter completion` cmd array | **MODIFIED** | `hermes-report.sh` (per-marker `cmd=(...)` block) |
| Job outcome stage | Post-loop pass: for each `agenticJobId` whose arc is terminated and not yet outcome-reported, call `jobs outcome`, append jobs-ledger outcome row | **NEW** | `hermes-report.sh` (new function after the session `while` loop) |
| Jobs ledger | Append-only idempotency ledger for create + outcome, mirroring `revenium-hermes.ledger` discipline | **NEW** | `common.sh` declares `JOBS_LEDGER_FILE`; written by `hermes-report.sh` |
| Job taxonomy | Optional vocabulary file for job `type` values, mirroring `task-taxonomy.json` | **NEW (optional — see §6)** | `common.sh` declares `JOB_TAXONOMY_FILE` |
| Classifier plugin | UNCHANGED — keeps writing task-type markers only; jobs are agent-declared, not plugin-derived | unchanged | `plugins/revenium-classifier/classifier.py` |
| `cron.sh`, `budget-check.sh`, `clear-halt.sh` | UNCHANGED by job tracking (clear-halt gets a *separate* bash-3.2 hardening fix) | unchanged | — |

---

## 3. Marker Schema Evolution (Question 1)

### The grouping problem

Jobs sit **above** task-types: one task arc (= one `agenticJobId`) spans many
turns, each of which already emits a task-type marker pair. The schema must
model "many task-types roll up under one job" without forcing the agent to
restate the job on every turn.

### Three options considered

| Option | Shape | Verdict |
|--------|-------|---------|
| **A. New field on every task marker** | Add `agentic_job_id` to each `{muid,ts,sid,task_type,operation_type}` line | **Rejected.** Forces the agent to know the job id *during* each turn and restate it on every marker write — but the decided design (PROJECT.md D "declare once, at arc end") is exactly the opposite. The agent doesn't have a stable id mid-arc. Also bloats every line and re-opens the v1.0 `REQUIRED_KEYS` contract. |
| **B. New marker `kind`, same file** | Job declaration is one extra JSONL line in `markers/<sid>.jsonl` with `"kind":"job"`; task markers stay exactly as v1.0 (implicitly `kind:"task"`) | **RECOMMENDED.** One file = one reader, one prune path, one `.ready` sentinel. The arc→turns grouping is recovered cron-side from `(sid, ts-window)`, not from a per-turn field. Backward-compatible: v1.0 task markers have no `kind` key and the reader treats absent `kind` as `"task"`. |
| **C. Separate `jobs/<sid>.jsonl` file** | Job markers in a parallel directory | Workable but adds a second marker dir, a second `.ready` sentinel question, a second prune target, a second path family in `common.sh`. No upside over B — the two marker kinds share a session id and a lifecycle. |

**Recommendation: Option B — a new `kind` discriminator in the existing
`markers/<sid>.jsonl`.**

### Recommended schema

**Task-type marker (v1.0 — UNCHANGED, shown for contrast):**

```json
{"muid":"...","ts":1715...,"sid":"abc","task_type":"code_review","operation_type":"CHAT"}
```

**Job marker (NEW — written once per arc by the agent's FINAL ACTION block):**

```json
{"kind":"job","jmuid":"<hex>","ts":1715...,"sid":"abc",
 "agentic_job_id":"refactor-auth-flow-9f2a1c",
 "name":"Refactor auth flow","type":"refactor","environment":"production",
 "result":"SUCCESS","outcome_type":"CONVERTED","outcome_value":150}
```

Field notes:

- `kind:"job"` — the discriminator. v1.0 task markers have **no `kind` key**;
  the reader maps absent → `"task"`. Unknown `kind` values are skipped (forward
  compat).
- `jmuid` — job-marker unique id, distinct namespace from task `muid` so the
  jobs ledger and the transaction ledger never key-collide. Same minting recipe
  as `muid` (ms-hex timestamp + random hex).
- `agentic_job_id` — the LLM business label + entropy suffix. This is the value
  that goes verbatim into `jobs create --agentic-job-id` **and** every
  `meter completion --task-id`. Must satisfy a slug regex such as
  `^[a-z0-9][a-z0-9-]{2,62}$` — the CLI accepts it as a free string, but the
  skill should pin a regex to avoid fragmentation and (critically) **forbid
  the `:` character** so the jobs ledger's colon-delimited format stays parseable
  (mirrors `parse_prior_state`'s `assert ':' not in sid`).
- `name`, `type`, `environment` — pass through to `jobs create` 1:1.
- `result` — `SUCCESS` | `FAILED` | `CANCELLED`. **Presence of this field is
  what marks the arc terminated** and eligible for the outcome stage. (If a
  future design wants "job declared but not yet done", omit `result`; §5 covers
  that.)
- `outcome_type`, `outcome_value`, `outcome_currency` — optional business
  signal, pass through to `jobs outcome`. Cron omits the flags when absent.

### Arc → turns grouping (how the cron correlates)

The job marker does **not** list its member task markers. Correlation is
positional and cron-side: the job marker's `ts` ends the arc; all task markers
in `<sid>.jsonl` whose `ts` falls in the arc window get `--task-id` stamped.

**Recommended grouping rule (simplest defensible, mirrors S2 equal-split
philosophy):** *one open job per session at a time.* The most-recent job marker
preceding (or at) a task marker's `ts` owns that task marker. A session that
declares jobs J1 (ts=100) then J2 (ts=300) attributes task markers ts∈(—,100]
to J1 and ts∈(100,300] to J2. Task markers with no preceding job marker get no
`--task-id` (they meter exactly as v1.0). This needs **no per-turn job field**
and tolerates the agent forgetting to declare a job (those turns just stay
job-less — the v1.0 backward-compat guarantee).

### What breaks v1.0 backward-compat — and what does not

| Change | Breaks v1.0? | Why |
|--------|--------------|-----|
| Adding `kind:"job"` lines to `<sid>.jsonl` | **No** | The v1.0 reader's `REQUIRED_KEYS = (muid,ts,sid,task_type,operation_type)` check (`hermes-report.sh:399`) silently *skips* any line missing those keys. A job line lacks `muid`/`task_type`, so an **un-modified v1.0 cron simply ignores job markers** — it does not crash. Forward-compat is free; only the v1.1 cron acts on them. |
| Task markers gaining no new keys | **No** | v1.0 task markers are byte-identical. |
| Marker reader learning to branch on `kind` | **No** | New code path; absent `kind` → `"task"` preserves the exact v1.0 path. |
| `prune-markers.sh` pruning a file that contains job lines | **No** | Pruning is whole-file by ledger staleness; line shape is irrelevant. |
| **Renaming/repurposing any of the 5 task-marker keys** | **YES — do not** | The v1.0 `REQUIRED_KEYS` tuple and `tests/test_repository.py` marker-shape tests are contractual. Job data must be *additive* (new keys / new line kind), never a mutation of the task-marker shape. |

**Net:** Option B is strictly additive. A v1.0-era install upgraded to a v1.1
cron keeps metering; a v1.1-era marker file read by a v1.0 cron loses only the
job attribution (graceful degradation). This is the same backward-compat
posture as v1.0's zero-marker fallthrough.

---

## 4. Cron Flow — Where create/outcome Slot In (Question 2)

### Current `hermes-report.sh` shape (v1.0)

```
preflight (tool checks) → query state.db → sentinel/age filter
  → while-read each session:
      ├─ idempotency pre-filter (grep ledger for sid:total_tokens)
      ├─ compute delta + provider inference
      ├─ T04 marker-read heredoc → markers_json, n_markers
      └─ if n_markers>0: per-marker loop → meter completion → ledger row
         else: zero-marker fallthrough → meter completion → ledger row
  → info "Done"
```

### Recommended v1.1 shape (★ = new)

```
preflight → query state.db → sentinel/age filter
  ★ STAGE 1 — JOB SCAN + CREATE  (new function, BEFORE the session loop)
      ├─ scan every markers/<sid>.jsonl for kind:"job" lines
      ├─ build set of distinct agentic_job_id seen this tick
      ├─ for each id NOT in revenium-jobs.ledger as "created":
      │     revenium jobs create --agentic-job-id <id> [--name --type --environment]
      │     on exit 0 → append "JOB:<id>:created:<ts>" to jobs ledger
      │       (exit 0 covers BOTH real-create AND 409-already-exists — both
      │        mean "the job now exists server-side", which is all we need)
      └─ continue past per-job failures (set -uo pipefail discipline)

  → while-read each session:                          (MODIFIED)
      ├─ idempotency pre-filter                        (unchanged)
      ├─ compute delta + provider                      (unchanged)
      ├─ T04 marker-read heredoc                       (MODIFIED: also returns
      │     the job id owning each task marker via the §3 grouping rule)
      └─ per-marker loop:
           cmd=( revenium meter completion ... )
           ★ if marker has owning agentic_job_id:
                cmd+=(--task-id "<agentic_job_id>")
           run cmd → on exit 0 → transaction ledger row  (unchanged shape)

  ★ STAGE 3 — JOB OUTCOME  (new function, AFTER the session loop)
      ├─ for each agentic_job_id whose job marker carries a `result`:
      │     skip if jobs ledger already has "JOB:<id>:outcome:*"
      │     probe: revenium jobs get <id> --output json → if hasOutcome:true,
      │            append the outcome ledger row WITHOUT re-calling (reconcile)
      │     else:  revenium jobs outcome <id> --result <r> [--outcome-* ...]
      │            on exit 0 → append "JOB:<id>:outcome:<result>:<ts>"
      └─ continue past per-job failures
  → info "Done"
```

### Why three stages, not one fused pass

- **Create must precede meter** (see §5 ordering) → create is a *pre-loop*
  stage, not interleaved.
- **Outcome must follow meter** — an arc's transactions should land before its
  outcome is reported, so Revenium's job rollup is complete when the outcome
  posts. Outcome is therefore a *post-loop* stage.
- The session `while` loop stays almost untouched: the only in-loop change is a
  conditional `cmd+=(--task-id ...)`, structurally identical to the v1.0
  conditional `cmd+=(--total-cost ...)` / `cmd+=(--environment ...)` appends
  already at `hermes-report.sh:579-590`.

### The jobs ledger — extending v1.0 ledger discipline

The transaction ledger keys idempotency on `(sid, total_tokens, muid)`. The
jobs ledger applies the **same append-only, grep-before-act discipline** to two
new one-shot operations.

**Recommendation: a parallel file `revenium-jobs.ledger`, not new rows in
`revenium-hermes.ledger`.** Reason: `parse_prior_state` discriminates v1/v2
transaction rows purely by **colon field count** (4 vs 5 — see
`split_strategies.py:94-99`). Adding a third row shape into the same file would
break that discrimination logic. A separate file keeps the transaction ledger's
field-count contract untouched.

**Jobs ledger line format:**

```
JOB:<agentic_job_id>:created:<unix_ts>
JOB:<agentic_job_id>:outcome:<result>:<unix_ts>
```

- Idempotency probe for create: `grep -q "^JOB:<id>:created:" revenium-jobs.ledger`.
- Idempotency probe for outcome: `grep -q "^JOB:<id>:outcome:" revenium-jobs.ledger`.
- Constraint: `agentic_job_id` must not contain `:` — pin the slug regex in the
  job-marker schema (§3) and assert it cron-side, exactly as `parse_prior_state`
  asserts `':' not in sid`.
- **Write-after-success only.** Append the `created` row only after
  `jobs create` exits 0; append the `outcome` row only after `jobs outcome`
  exits 0 (or after a `jobs get` probe confirms `hasOutcome:true`). A tick that
  crashes between the API call and the ledger append re-attempts next tick —
  and the server's own 409 / immutability guard makes the retry harmless. This
  is the **belt-and-suspenders** pattern: local ledger is the fast path, server
  guard is the safety net.

### Idempotency under partial failure (the SC2-equivalent for jobs)

| Scenario | What happens next tick | Safe? |
|----------|------------------------|-------|
| `jobs create` succeeds, ledger append crashes | Next tick re-runs `jobs create` → server 409 → exit 0 → ledger row finally written | ✅ (409 is treated as success) |
| `jobs create` fails (network) | No ledger row → next tick retries cleanly | ✅ |
| `jobs outcome` succeeds, ledger append crashes | Next tick: `jobs get` probe sees `hasOutcome:true` → write ledger row, skip the call | ✅ (probe reconciles) |
| `jobs outcome` fails | No ledger row → next tick retries | ✅ |
| `meter completion --task-id` fails | v1.0 behavior unchanged — no transaction-ledger row, marker re-emitted next tick (now with the same `--task-id`) | ✅ |

**The `jobs get` probe in Stage 3 is what closes the "outcome succeeded but
ledger lost it" gap** — the transaction ledger has no equivalent because
`meter completion` is naturally idempotent on `--transaction-id`, but
`jobs outcome` is not queryable by transaction id, only by job state.

---

## 5. Ordering & Failure Tolerance (Question 3)

### Ordering within one cron cycle

`jobs create` for job X **must** logically precede every
`meter completion --task-id X` for that job. The Stage-1-before-loop design
guarantees this *within a single tick*.

### The async-create race

Revenium's docs note that `jobs create` may be processed asynchronously, so a
`meter completion --task-id X` issued microseconds after `jobs create X`
returns could reference a job the platform hasn't fully materialized yet.

**Posture: tolerate it, don't fight it.** Three reasons this is safe:

1. **`--task-id` is a correlation tag, not a foreign-key constraint.** A
   `meter completion` with a `--task-id` that doesn't yet resolve still records
   the transaction; Revenium back-fills the job association when the job
   appears. The transaction is never lost.
2. **The v1.0 cron already buffers ~60-120s.** The sentinel/age filter
   (`REVENIUM_CRON_SETTLE_SECONDS`, default 120s) means a session's markers are
   typically read a tick or more after they're written. By the time
   `meter completion` runs, a job created in the *same* tick's Stage 1 has had
   the whole session-loop duration to settle; a job created in an *earlier*
   tick is long-settled.
3. **Worst case is self-healing.** If a transaction does land before its job,
   the next arc's transactions and the outcome call still reference the same
   `agentic_job_id`; Revenium reconciles by id. PROJECT.md already accepts
   "~60s attribution lag" as in-scope — a sub-second create race is strictly
   smaller than that accepted envelope.

**Do not** add a polling "wait for job to exist" loop after `jobs create` — it
would block the per-minute tick, fight `cron.lock`, and chase a race that the
correlation-by-id model already absorbs.

### Failure-tolerance posture (consistent with v1.0)

`hermes-report.sh` runs `set -uo pipefail` (**no `-e`**) precisely so a single
failure doesn't abort the tick. v1.1 extends this:

- **Stage 1 (create):** wrap each `jobs create` so a non-zero/network failure
  is logged via `warn` and the loop `continue`s — exactly like the per-session
  `((counter++)) || true; continue` pattern at `hermes-report.sh:548`.
- **Stage 3 (outcome):** same — a failed `jobs get` probe or `jobs outcome`
  call logs `warn` and moves on; the missing ledger row guarantees a retry.
- **In-loop `--task-id`:** stamping is a pure string append to the `cmd` array.
  It cannot fail on its own; if the marker has no owning job, the flag is simply
  not added (the v1.0 `cmd+=(...)` conditional idiom).
- **`cron.sh` is unchanged** — it already calls `hermes-report.sh || true`, so
  even a catastrophic Stage-1/3 failure cannot block `budget-check.sh`.
- **Never let a job failure block metering.** Metering (the v1.0 core value)
  must always run even if `jobs create` is down. Stage 1's only job is to
  *populate the jobs ledger*; if it does nothing, the session loop still meters
  every marker — just without `--task-id` (graceful degradation to v1.0
  behavior). Make Stage 1 a best-effort prelude, never a gate.

---

## 6. New State Paths (Question 4)

All paths declared in `common.sh` **only** — `test_runtime_paths_are_hermes_native`
fails the build otherwise. Add between `MARKER_RETENTION_DAYS`/`PRUNE_LOCK_FILE`
(lines 21-22) and the `mkdir -p` line (24), following the `${REVENIUM_*:-...}`
override idiom.

| Variable | Path | NEW? | Purpose |
|----------|------|------|---------|
| `JOBS_LEDGER_FILE` | `${STATE_DIR}/revenium-jobs.ledger` | **NEW — required** | Append-only create+outcome idempotency ledger (§4). Created via `touch` in `hermes-report.sh`, same as `LEDGER_FILE` at line 34. |
| `JOB_TAXONOMY_FILE` | `${STATE_DIR}/job-taxonomy.json` | **NEW — optional** | Controlled vocabulary for job `type`, mirroring `TAXONOMY_FILE`. See note below. |

**No new directory is needed.** Job markers live inside the existing
`markers/<sid>.jsonl` (Option B), so `MARKERS_DIR` / `MARKERS_READY_DIR` are
reused unchanged. No `jobs/` directory.

**On `job-taxonomy.json` (optional):** the v1.0 `task-taxonomy.json` exists to
fight label *fragmentation* (`code_review` vs `code-review`). The v1.1
`agentic_job_id` already carries an **entropy suffix** (PROJECT.md decision) —
so job *ids* cannot fragment-collide by design. Only the job `type` field
(`refactor`, `loan-processing`, …) is free-text and could fragment. Two stances:

- **Minimal (recommended for the first phase):** ship no job-taxonomy file;
  let `type` be free-text. The entropy suffix already solves the id problem,
  and `revenium jobs types` exists server-side for `type` discovery.
- **Mirror-v1.0 (defer / optional):** add `job-taxonomy.json` only if `type`
  fragmentation is observed in practice. Declaring the *variable* in `common.sh`
  now (pointing at a file that may not exist) costs nothing and avoids a later
  `common.sh` churn — the v1.0 `TAXONOMY_FILE` already tolerates a missing file.

`MARKER_RETENTION_DAYS` / `prune-markers.sh` need **no change** — pruning is
whole-file by ledger staleness; a file containing job lines prunes identically.
(The jobs ledger itself is tiny and append-only — no pruning needed; if it ever
matters, that's a future concern, not a v1.1 one.)

---

## 7. Data Flow Changes

### NEW flow — Job lifecycle

```
[agent finishes a task arc]
      ↓  appends ONE kind:"job" line
markers/<sid>.jsonl
      ↓  (cron tick N, Stage 1)
hermes-report.sh job-scan ──→ revenium jobs create ──→ Revenium /v2/api/jobs
      ↓  on exit 0
revenium-jobs.ledger  ← "JOB:<id>:created:<ts>"
      ↓  (same tick, session loop)
per-marker meter completion --task-id <id> ──→ Revenium (transaction ↔ job link)
      ↓  (same tick, Stage 3 — result present on job marker)
jobs get <id> probe → not hasOutcome → revenium jobs outcome <id> --result ...
      ↓  on exit 0
revenium-jobs.ledger  ← "JOB:<id>:outcome:<result>:<ts>"
```

### MODIFIED flow — Marker read

v1.0: read `<sid>.jsonl` → keep lines passing `REQUIRED_KEYS` → split delta.
v1.1: read `<sid>.jsonl` → **branch on `kind`**:
- `kind` absent or `"task"` → v1.0 task-marker path (REQUIRED_KEYS, dedup by
  `muid`, split).
- `kind == "job"` → collect into the per-session job list; used by Stage 1
  (create), the §3 grouping rule (`--task-id` ownership), and Stage 3 (outcome).
- unknown `kind` → skip (forward compat).

### UNCHANGED flows

Budget check, halt transition, transaction-ledger delta math, provider
inference, S2 equal split, zero-marker fallthrough, `cron.sh` lock + env, the
classifier plugin — **none change**. v1.1 is additive at three named seams in
one file.

---

## 8. Anti-Patterns (v1.1-specific)

### Anti-Pattern 1: Trusting `jobs create` / `jobs outcome` exit codes

**What people do:** `revenium jobs create ... && echo "created"`.
**Why it's wrong:** the CLI exits **0** on `HTTP 409 already exists` and on
`outcome already reported`. Exit code cannot distinguish success / duplicate /
some failures.
**Do this instead:** treat exit 0 as "the desired server state now holds"
(for create, 409 *is* success). For the rare cases where you need certainty
(outcome reconciliation), probe `jobs get --output json` and read `hasOutcome`.
Drive idempotency from the **local jobs ledger**, never from `$?`.

### Anti-Pattern 2: Putting job rows in `revenium-hermes.ledger`

**What people do:** append `JOB:...` lines to the existing ledger to keep "one
ledger".
**Why it's wrong:** `parse_prior_state` discriminates transaction rows by
colon-field-count (4 = v1, 5 = v2). A third shape corrupts that and breaks the
`split_strategies.py` contract + its tests.
**Do this instead:** separate `revenium-jobs.ledger` with its own `JOB:` prefix.

### Anti-Pattern 3: Per-turn `agentic_job_id` on every task marker

**What people do:** add `agentic_job_id` to the task-marker schema so each turn
self-declares its job.
**Why it's wrong:** mutates the contractual v1.0 marker shape; forces the agent
to know a stable job id mid-arc (it doesn't — the decided design is "declare
once at arc end"); re-opens `REQUIRED_KEYS` and the marker-shape tests.
**Do this instead:** one `kind:"job"` line per arc; recover the arc→turns
grouping cron-side by `ts` window (§3).

### Anti-Pattern 4: Gating metering on `jobs create`

**What people do:** `jobs create || exit` before the session loop.
**Why it's wrong:** if the jobs endpoint is down, the v1.0 core value (metering
spend) stops — a regression. Job tracking is an *enrichment*, not a gate.
**Do this instead:** Stage 1 is best-effort; on failure, the session loop still
meters every marker, just without `--task-id`. Graceful degradation to v1.0.

### Anti-Pattern 5: Polling for the async-created job

**What people do:** after `jobs create`, loop `jobs get` until the job appears,
then meter.
**Why it's wrong:** blocks the per-minute tick, fights `cron.lock`, and chases
a race that correlation-by-id already absorbs (§5).
**Do this instead:** fire-and-continue. `--task-id` correlates by id whenever
the job materializes; PROJECT.md already accepts ~60s lag.

---

## 9. Integration Points — Summary Table

| Seam | File:location | NEW / MODIFIED | Change |
|------|---------------|----------------|--------|
| Job declaration prompt | `SKILL.md` — after `## FINAL ACTION — TASK CLASSIFICATION` (after line 397) | **NEW** section | Instruct agent to append one `kind:"job"` marker at arc end; specify schema + `agentic_job_id` slug rule. |
| State paths | `common.sh` — after line 22 (`PRUNE_LOCK_FILE`) | **NEW** | `JOBS_LEDGER_FILE`; optionally `JOB_TAXONOMY_FILE`. |
| Marker reader | `hermes-report.sh` — T04 heredoc (lines 334-446) | **MODIFIED** | Branch on `kind`; return job markers + per-task-marker owning job id. |
| Job create stage | `hermes-report.sh` — new function called before the `while IFS='|'` loop (line 161) | **NEW** | Scan markers, `jobs create` new ids, append jobs-ledger `created` rows. |
| `--task-id` stamping | `hermes-report.sh` — per-marker `cmd=(...)` block (lines 556-577) | **MODIFIED** | Conditional `cmd+=(--task-id "<id>")` when the marker has an owning job. |
| Job outcome stage | `hermes-report.sh` — new function after `done <<< "${sessions}"` (line 676) | **NEW** | `jobs get` probe + `jobs outcome` for terminated arcs; append jobs-ledger `outcome` rows. |
| Ledger init | `hermes-report.sh` — near `touch "${LEDGER_FILE}"` (line 34) | **MODIFIED** | `touch "${JOBS_LEDGER_FILE}"`. |
| Tests | `tests/test_repository.py` | **MODIFIED** | Add job-marker shape test, jobs-ledger format test, `kind`-discrimination backward-compat test. |
| `cron.sh`, `budget-check.sh`, classifier plugin | — | **UNCHANGED** | No job-tracking change. |

---

## 10. Suggested Build Order (dependency-respecting)

Ordered so each phase is independently testable and nothing depends on a
not-yet-built piece. Each phase ships behind the v1.0 backward-compat guarantee.

1. **State paths + jobs ledger plumbing.** Add `JOBS_LEDGER_FILE` (and optional
   `JOB_TAXONOMY_FILE`) to `common.sh`; `touch` it in `hermes-report.sh`. No
   behavior change — pure scaffolding. *Verifies:* `test_runtime_paths_are_hermes_native`
   still passes; ledger file is created.
   *Depends on:* nothing.

2. **Marker schema + reader `kind` branching.** Define the `kind:"job"` schema;
   teach the T04 heredoc to parse job lines and skip them in the task path.
   *Verifies:* v1.0 task markers still meter byte-identically (the critical
   backward-compat test); job lines are collected, not crashed on.
   *Depends on:* nothing functionally — but the schema must be frozen before
   phases 3-6.

3. **Job declaration prompt block in `SKILL.md`.** New `## FINAL ACTION — JOB
   DECLARATION` section; `agentic_job_id` slug rule. Pure prompt — no cron
   change. *Verifies:* halt-survivability runbook still passes (any `SKILL.md`
   edit re-triggers it); a manual arc produces a well-formed job line.
   *Depends on:* phase 2 (schema must be frozen).

4. **Job create stage (Stage 1).** New pre-loop function: scan, `jobs create`,
   jobs-ledger `created` rows; idempotent across ticks; best-effort failure
   posture. *Verifies:* re-running cron never double-creates (409-as-success);
   metering unaffected when jobs endpoint is mocked-down.
   *Depends on:* phases 1 (ledger) + 2 (reader).

5. **`--task-id` stamping (in-loop).** Conditional `cmd+=(--task-id ...)` using
   the §3 grouping rule. *Verifies:* markers with an owning job get `--task-id`;
   job-less markers meter exactly as v1.0; conservation/idempotency tests still
   green. *Depends on:* phases 2 (reader returns owning id) + 4 (the job exists
   before it's referenced).

6. **Job outcome stage (Stage 3).** New post-loop function: `jobs get` probe +
   `jobs outcome`; jobs-ledger `outcome` rows; one-shot. *Verifies:* outcome
   fires exactly once; partial-failure (ledger-append crash) self-heals via the
   probe. *Depends on:* phases 1 (ledger) + 2 (reader) + 4 (job must exist to
   receive an outcome).

7. **Hardening (v1.0 carry-forward — independent track).** `fcntl.flock` on
   `_persist_label_to_taxonomy`; `clear-halt.sh` bash-3.2 `${VAR@Q}` fix;
   `prune-markers.sh` retention `>= 1` guard; dead-helper cleanup. *Depends on:*
   nothing — can run in parallel with phases 1-6 or as a final phase.

**Critical path:** 1 → 2 → 4 → 6, with 3 and 5 hanging off 2/4. Phase 7 is
fully parallel. The schema freeze at the end of phase 2 is the single
synchronization point everything downstream relies on.

---

## Sources

- Live `revenium` CLI probes (2026-05-14): `jobs --help`, `jobs create --help`,
  `jobs outcome --help`, `jobs get`, `meter completion --help`, plus duplicate-id
  (HTTP 409, exit 0) and double-outcome (immutability error, exit 0) behavior
  tests — **HIGH confidence**, direct observation.
- `skills/revenium/scripts/hermes-report.sh`, `cron.sh`, `common.sh`,
  `split_strategies.py`, `SKILL.md` — shipped v1.0 source — **HIGH confidence**.
- `.planning/PROJECT.md` — v1.1 milestone scope, Key Decisions — **HIGH confidence**.
- `skills/revenium/plugins/revenium-classifier/classifier.py` — marker-writing
  plugin (confirmed task-type-only, unchanged by v1.1) — **HIGH confidence**.

---
*Architecture research for: Hermes-Revenium v1.1 Agentic Job Tracking*
*Researched: 2026-05-14*
