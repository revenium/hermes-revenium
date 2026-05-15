# Project Research Summary

**Project:** Hermes-Revenium — v1.1 Agentic Job Tracking
**Domain:** Cron-driven AI-usage-metering skill — adding agentic-job lifecycle (create / attribute / outcome) on top of shipped v1.0 task-type metering
**Researched:** 2026-05-14
**Confidence:** HIGH

## Executive Summary

v1.1 layers Revenium *agentic-job* tracking on top of the shipped v1.0 task-type
metering skill. An agentic job is a discrete, goal-directed task arc with a
business outcome that sits *above* raw metered completions — many v1.0 task-type
markers roll up under one job. The wire surface is three `revenium` CLI calls:
`jobs create` (mint the job server-side), `meter completion --task-id` (the
*only* transaction→job linkage, value == `agenticJobId`), and `jobs outcome`
(report `SUCCESS`/`FAILED`/`CANCELLED`, **immutable, one-shot**). All four
researchers independently verified the CLI surface against the live
authenticated `revenium` binary on this host and **agree with HIGH confidence**
that the entire feature is buildable with the existing stack — Bash + stdlib
Python heredocs + sqlite3 + the `revenium` CLI. **No new runtime dependency, no
SDK, no HTTP client.** The only "stack change" is a mandatory CLI capability
probe: the user just patched the CLI to add `--task-id`, so a meaningful
population of installs will lack `jobs` / `--task-id` and the cron must fail
open.

The recommended approach is **strictly additive** and the researchers converge
unanimously on its shape. Job declaration is a single new `kind:"job"` JSONL line
appended to the *existing* `markers/<sid>.jsonl` at arc end (Architecture Option
B — chosen over both a per-turn field and a separate file). The agent mints the
`agenticJobId` once, retrospectively, in the FINAL ACTION marker — never
mid-arc, never prospectively. The cron grows three named seams in
`hermes-report.sh`: a pre-loop `jobs create` stage, an in-loop conditional
`--task-id` stamp, and a post-loop `jobs outcome` stage. A **separate
`revenium-jobs.ledger`** carries idempotency for the two one-shot job calls. Job
`--type` is governed by a **closed seed vocabulary** of ~8 coding-agent values
(`code-review`, `feature-development`, `bug-fix`, `refactor`, `research`,
`planning`, `devops-task`, `documentation`). Backward compatibility is free: a
job-less marker meters byte-identically to v1.0; a v1.1 marker read by an
un-modified v1.0 cron silently degrades (the job line fails `REQUIRED_KEYS` and
is skipped, not crashed on).

The dominant risk is **data integrity around immutable outcomes**. `jobs
outcome` returns HTTP 409 on any second post and cannot be amended — a
double-report is permanent noise, a wrong outcome is permanently wrong, and a
lost outcome is permanently lost. Compounding this, the CLI **exits 0 even on
409**, so exit code is useless for idempotency. The mitigations all four
researchers agree on: (1) a separate append-only `revenium-jobs.ledger`
(`JOB:<id>:created:<ts>` / `JOB:<id>:outcome:<result>:<ts>`) is the primary
idempotency guard, gating every call with `grep -q` before it fires; (2) the API
call happens **first**, the ledger line is appended **only on exit 0** — making
a phantom "lost outcome" impossible; (3) 409 is treated as success-equivalent
(the belt to the ledger's suspenders); (4) a hard phase-ordering constraint —
the job ledger and `jobs create` path must land *before* any `jobs outcome` call
exists. The second-tier risk is the v1.0 lesson repeating: `agenticJobId`
taxonomy collapse and arc-boundary mis-identification, prevented with the
mint-first anti-collapse prompt framing and cron-side blocklist that already
worked in v1.0.

## Key Findings

### Recommended Stack

The v1.1 stack is a **strict subset of the working v1.0 host** — there is
nothing to install. All four researchers verified the `revenium jobs`
subcommand tree and `meter completion --task-id` directly against the live CLI
(`/opt/homebrew/bin/revenium`, 2026-05-14), including `--dry-run` request shapes
and the 409/exit-0 behavior. The one new requirement is a **preflight capability
probe** (the CLI has no `--version` flag, so detect by capability:
`revenium jobs --help` and `grep -- --task-id` on `meter completion --help`),
failing open with a `warn` + `exit 0` per the existing preflight idiom. See
`STACK.md` for the full verified CLI surface.

**Core technologies:**
- `revenium` CLI (build exposing `jobs` + `meter completion --task-id`) — the *only* sanctioned wire path for `jobs create` / `meter completion --task-id` / `jobs outcome`; no SDK, no HTTP shim, no `curl`/`jq`
- Bash 4+ written **bash-3.2-safe** — orchestrates the new create/stamp/outcome calls via the existing `cmd=( ... )` array idiom in `hermes-report.sh`; bash 3.2 is a hard floor (Mac Studio host)
- Python 3 stdlib heredocs (`json`, `os`, `sys`, `time`, `fcntl`, `pathlib`) — parse job markers, group by `agenticJobId`, build `--metadata` JSON via `json.dumps`; identical pattern to the v1.0 marker reader
- sqlite3 CLI — unchanged read-only session query; jobs add no DB usage (job identity comes from markers, not `state.db`)

### Expected Features

`FEATURES.md` separates a credible v1.1 launch from post-validation
enrichment. Execution status (`--result`) is table stakes — it is the only
required `jobs outcome` flag and the agent always knows it. The business
`outcome-type` is a differentiator, and even then only `DEFLECTED` /
`UNSUCCESSFUL` / `ESCALATED` are honestly agent-reportable for a coding agent;
`CONVERTED` and any monetary `--outcome-value` are operator-supplied opt-in,
**never agent-inferred** (a coding agent has no honest dollar figure).

**Must have (table stakes):**
- Agent declares one job per task arc in a FINAL ACTION marker — without a declared job there is nothing to track
- `agenticJobId` = LLM business label + 4-hex entropy suffix — human-readable, collision-proof
- Cron idempotently runs `jobs create` once per `agenticJobId` — gated on a local ledger line
- Cron stamps `--task-id <agenticJobId>` on every `meter completion` in the job — the *only* tx→job linkage
- Cron reports `jobs outcome` exactly once per terminated arc — gated on a local ledger line
- Self-reported execution status `SUCCESS`/`FAILED`/`CANCELLED` — the required outcome flag
- Closed job-`--type` seed vocabulary (~8 values) — `jobs types` is an empty open enum; uncontrolled `--type` fragments analytics
- Backward compatibility: job-less / marker-less sessions meter exactly as v1.0

**Should have (competitive):**
- Business `outcome-type` (`DEFLECTED`/`UNSUCCESSFUL`/`ESCALATED`) self-reported — turns "spent $X" into "spent $X and shipped/escalated"
- `--metadata` JSON enrichment (PR url, branch, test status, files-changed)
- `--environment` / `--version` / `--reported-by` static config passthrough — `--reported-by` also flags outcomes as agent-self-reported
- Multi-arc-per-session boundary detection — the *target* granularity (one-arc-per-session is the acceptable floor)

**Defer (v2+):**
- Operator-supplied monetary `--outcome-value` — no honest valuation model exists yet
- Job-type taxonomy file with descriptions — only if the closed seed list proves too rigid in practice

### Architecture Approach

`ARCHITECTURE.md` confirms v1.1 needs **no redesign** of the v1.0 two-half
architecture (in-session skill prompt ↔ filesystem state ↔ per-minute cron). It
is additive at three named seams in one file (`hermes-report.sh`) plus one new
`SKILL.md` section, one new state path, and an extended marker schema. The job
marker is a new `kind:"job"` discriminator line in the *existing*
`markers/<sid>.jsonl` (Option B) — chosen unanimously over a per-turn
`agentic_job_id` field (mutates the contractual v1.0 marker shape) and a
separate `jobs/<sid>.jsonl` file (no upside, doubles the prune/sentinel
surface). Arc→turns grouping is recovered cron-side positionally by `ts` window,
needing no per-turn field. The load-bearing CLI fact: `revenium` **exits 0 on
409 and on "outcome already reported"**, so idempotency must be enforced locally
by a ledger, never by `$?`.

**Major components:**
1. Job-declaration prompt block (NEW, `SKILL.md`) — agent appends one `kind:"job"` marker at arc end with id, name, type, `result`, optional outcome fields
2. Marker reader (MODIFIED, `hermes-report.sh` T04 heredoc) — branch on `kind`; absent `kind` → `"task"` (v1.0 path untouched); unknown `kind` → skip
3. Job create stage (NEW, pre-loop function) — scan markers, `jobs create` each un-created `agenticJobId`, append `JOB:<id>:created` ledger row
4. `--task-id` stamping (MODIFIED, in-loop `cmd=(...)` block) — conditional `cmd+=(--task-id "<id>")` when a marker has an owning job
5. Job outcome stage (NEW, post-loop function) — `jobs get` probe + `jobs outcome` for terminated arcs, append `JOB:<id>:outcome` row
6. `revenium-jobs.ledger` (NEW, declared in `common.sh`) — separate append-only idempotency ledger for the two one-shot job calls

### Critical Pitfalls

`PITFALLS.md` flags four P0 (data-integrity / unrecoverable) pitfalls — the
stakes are raised because immutable outcomes cannot be undone.

1. **Double-reporting an immutable outcome (P0)** — the per-minute cron re-sees the FINAL ACTION marker and re-posts `jobs outcome` → 409 storm or, worse, infinite retry. *Avoid:* separate `revenium-jobs.ledger`, `grep -q "^JOB:<id>:outcome:"` gate before posting, treat 409 as terminal success-equivalent, derive `result` verbatim from the marker (deterministic).
2. **Ledger / API divergence on partial failure (P0)** — a crash between the API call and the ledger append either loses the outcome forever (phantom ledger line) or re-posts it. *Avoid:* strict ordering — call the API **first**, append the ledger line **only on exit 0**, as the last statement in the success branch; this makes "lost outcome" impossible and 409-as-success recovers a lost ledger line.
3. **`meter completion --task-id` / `jobs outcome` racing ahead of `jobs create` (P0)** — within and across ticks, ordering is not guaranteed; a too-early `jobs outcome` 404s. *Avoid:* `jobs create` is a pre-loop stage (precedes meter within a tick); gate `jobs outcome` on a *locally confirmed* `JOB:<id>:created` ledger line, deferring to the next tick if absent. **Never block metering on create — it is enrichment, not a gate.** No hand-rolled retry loop; the 60s cron cadence *is* the retry.
4. **Wrong self-reported outcome (P0, unrecoverable)** — LLM self-assessment is optimistic; a wrong `SUCCESS` is a permanent ROI lie. *Avoid:* conservative SKILL.md criteria — report `SUCCESS` only on a confirmed met goal, bias to `CANCELLED` under uncertainty; `--reported-by` flags outcomes as agent-self-reported; accept residual risk explicitly.
5. **`agenticJobId` taxonomy collapse (P1, the v1.0 lesson repeated)** — the LLM picks bland labels (`work-a3f9`, `task-c812`); the entropy suffix *masks* collapse, making it harder to detect than v1.0's. *Avoid:* mint-first anti-collapse prompt framing (the fix that already worked), cron-side forbidden-stem blocklist, strip-and-count distinct-stem detection check.

## Implications for Roadmap

Based on combined research, the suggested phase structure is the
dependency-ordered build sequence from `ARCHITECTURE.md` §10, cross-checked
against the `PITFALLS.md` phase mapping. The **load-bearing ordering constraint
all four researchers surface**: the `revenium-jobs.ledger` and the `jobs create`
path must exist before any `jobs outcome` call — outcome idempotency has nowhere
to live otherwise, and a job must exist server-side before an outcome can
attach to it.

### Phase 1: State Paths + Marker Schema + Reader Branching
**Rationale:** Pure scaffolding with no behavior change; the marker schema is
the single synchronization point everything downstream depends on, so it must be
frozen first. Combines Architecture build-order steps 1-2.
**Delivers:** `JOBS_LEDGER_FILE` (and optional `JOB_TAXONOMY_FILE`) declared in
`common.sh`; `touch`-ed in `hermes-report.sh`; the `kind:"job"` marker schema
frozen; the T04 marker reader branches on `kind` (absent → `"task"`, v1.0 path
byte-identical; unknown → skip).
**Addresses:** Job-marker schema extension; backward compatibility.
**Avoids:** Pitfall 9 (marker schema breaks v1.0 reader — new fields stay
`.get()`-optional, `REQUIRED_KEYS` unchanged); Pitfall 1/2 groundwork (the
separate jobs ledger exists before any job call).

### Phase 2: Job Declaration Prompt Block (`SKILL.md`)
**Rationale:** Pure prompt change once the schema is frozen (depends on Phase 1).
This is where the v1.0 taxonomy-collapse lesson and the conservative-outcome
discipline must be baked in.
**Delivers:** New `## FINAL ACTION — JOB DECLARATION` section — `agenticJobId`
slug rule, mint-first anti-collapse framing with good/bad examples, operational
arc-boundary definition, conservative `SUCCESS`/`CANCELLED` criteria, closed
job-type seed list, and a budget-halt path that writes a `CANCELLED` terminal
marker.
**Addresses:** Agent job declaration; execution-status self-report.
**Avoids:** Pitfall 5 (taxonomy collapse), 6 (arc-boundary mis-identification),
8 (wrong outcome). Re-triggers the halt-survivability runbook (any `SKILL.md`
edit).

### Phase 3: Job Create Stage + `--task-id` Stamping
**Rationale:** The pre-loop `jobs create` stage and the in-loop `--task-id`
stamp ship together — the stamp references a job that create must have minted.
Depends on Phases 1-2.
**Delivers:** New pre-loop function scanning markers and calling `jobs create`
idempotently (`JOB:<id>:created` ledger row, 409-as-success, best-effort failure
posture); conditional `cmd+=(--task-id "<id>")` in the per-marker loop using the
positional ts-window grouping rule.
**Uses:** `revenium jobs create`, `revenium meter completion --task-id`.
**Implements:** Architecture components 3 and 4.
**Avoids:** Pitfall 2 (double-create), 3 (ordering — create precedes meter
within a tick), 4 (best-effort, never gates metering — graceful v1.0
degradation).

### Phase 4: Job Outcome Stage + Arc Termination
**Rationale:** The post-loop `jobs outcome` stage must land last among the
cron-pipeline phases — it depends on a created job and on transactions having
been metered first so the Revenium rollup is complete. Depends on Phases 1-3.
**Delivers:** New post-loop function — `jobs get` reconciliation probe +
`jobs outcome` for terminated arcs, gated on `JOB:<id>:outcome` ledger row,
API-call-first / ledger-on-exit-0 ordering; abandoned-arc staleness net posting
`CANCELLED` once for never-terminated jobs.
**Uses:** `revenium jobs outcome`, `revenium jobs get --output json`.
**Implements:** Architecture component 5.
**Avoids:** Pitfall 1 (double-report), 4 (ledger/API divergence), 7 (abandoned
arc — staleness net + `CANCELLED` default), 11 (dead-predicate — log predicate
inputs, dual-branch tests).

### Phase 5: Hardening Carry-Forward (parallel track)
**Rationale:** v1.0 tech-debt discharge; depends on nothing and can run in
parallel with Phases 1-4 or as a final phase.
**Delivers:** `fcntl.flock` on `_persist_label_to_taxonomy`; `clear-halt.sh`
bash-3.2 `${VAR@Q}` fix; `prune-markers.sh` retention `>= 1` guard; dead-helper
(`_count_tools_in_current_turn`) cleanup.
**Avoids:** Pitfall 10 (bash 3.2 portability — though the discipline applies to
*every* phase that adds a script, not just this one).

### Phase Ordering Rationale

- **Critical path: 1 → 2 → 3 → 4.** The marker schema (frozen at end of Phase 1)
  is the single synchronization point. `jobs create` (Phase 3) must precede
  `jobs outcome` (Phase 4) because outcome idempotency has nowhere to live
  without the jobs ledger and a job must exist server-side before its outcome
  can attach — this is the load-bearing constraint all four researchers
  independently surface.
- **The jobs ledger lands in Phase 1, before any job call exists.** P0 Pitfalls
  1, 2, and 4 all depend on it; building a `jobs outcome` call before its
  idempotency ledger is the single most dangerous sequencing error possible
  given immutable outcomes.
- **`--task-id` stamping groups with `jobs create` (Phase 3), not metering.** It
  is a pure additive flag; isolating it from create would let a marker reference
  a job that does not yet exist.
- **Hardening (Phase 5) is fully parallel** — no functional dependency on the
  job work, but the bash-3.2 floor it enforces is a success criterion for every
  script-adding phase.
- **Every cron-pipeline phase ships behind the v1.0 backward-compat guarantee** —
  a job-less marker must produce byte-identical `meter completion` argv, verified
  by regression test, not eyeballing.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2:** Arc-boundary detection and conservative-outcome prompt framing are
  the milestone-specific judgment problems. The v1.0 taxonomy-collapse fix is a
  proven template, but the multi-arc-per-session vs one-arc-per-session decision
  and the budget-halt terminal-marker mechanics warrant a `/gsd-research-phase`
  pass.
- **Phase 4:** The abandoned-arc staleness net (window length, `CANCELLED`
  default, sweeper cadence) and the `jobs get` reconciliation semantics are the
  least-pinned area — `FEATURES.md` and `ARCHITECTURE.md` differ slightly on
  whether the staleness net is v1.1-MVP or deferrable; resolve during planning.

Phases with standard patterns (skip research-phase):
- **Phase 1:** State-path discipline and additive marker-schema extension are
  well-established v1.0 patterns; the CLI surface is fully verified.
- **Phase 3:** `jobs create` + `--task-id` map 1:1 onto the verified CLI and the
  existing `cmd=(...)` array idiom; the ledger-gate pattern is v1.0-proven.
- **Phase 5:** Pure tech-debt discharge with known fixes already scoped in
  PROJECT.md.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Entire `jobs` subcommand tree, `--task-id`, exit codes, and `--dry-run` request shapes verified directly against the live authenticated CLI on this host. |
| Features | HIGH (wire) / MEDIUM (semantics) | Revenium wire surface verified live; the coding-agent interpretation of a sales/support-oriented outcome model (which `outcome-type`s a coding agent can honestly report) is reasoned, not empirically validated. |
| Architecture | HIGH | Integration seams verified against shipped v1.0 source; the load-bearing 409/exit-0 CLI behavior probed directly. |
| Pitfalls | HIGH | CLI behavior (409, async-create→404) verified live; v1.0 failure modes (taxonomy collapse, dead-predicate drop, bash 3.2 break) are documented live-environment lessons, not speculation. |

**Overall confidence:** HIGH

**Strong cross-researcher agreement (treat as decided):**
- Separate `revenium-jobs.ledger` — never reuse `revenium-hermes.ledger` (its
  4-vs-5 colon-field-count discrimination would break). *All four agree.*
- Additive `kind:"job"` marker line in the existing `markers/<sid>.jsonl` —
  never a per-turn field, never a separate file. *Architecture, Features, Pitfalls agree.*
- Closed job-`--type` seed vocabulary (~8 coding-agent values), not free-mint.
  *Features, Architecture, Stack agree.*
- Phase ordering: jobs ledger + `jobs create` before any `jobs outcome` call.
  *All four agree.*
- Local ledger is the idempotency source of truth; CLI exit code is useless
  (exits 0 on 409); 409 is success-equivalent. *All four agree.*

### Gaps to Address

- **Abandoned-arc / staleness-net scope:** `FEATURES.md` lists the staleness net
  as part of the v1.1 MVP cut while treating multi-arc detection as deferrable;
  `PITFALLS.md` calls skipping it "acceptable for an MVP only if explicitly
  documented." *Handle:* roadmapper decides MVP vs deferred in Phase 4 planning;
  the budget-halt `CANCELLED` terminal marker should ship regardless (cleanest
  fix for the most common abandonment cause).
- **Multi-arc vs one-arc-per-session granularity:** the *target* is multiple
  jobs per session; the *acceptable floor* is one job per session. *Handle:* ship
  the one-arc floor in v1.1 if reliable mid-session boundary prompting proves
  hard; treat multi-arc as a v1.x add. Roadmapper should make this an explicit
  Phase 2 decision point.
- **`revenium schema` is stale for `meter completion`** — the subcommand is
  absent from the schema dump though `--help` shows `--task-id`. *Handle:* pin
  any `meter completion` flag tests to `--help` output, not `schema`; documented
  in STACK.md.
- **`outcome-type` honest-signal boundary:** which business outcomes a coding
  agent can truthfully report is reasoned, not validated. *Handle:* ship v1.1
  with execution-status only (the recommended MVP cut); add `outcome-type` after
  live validation shows clean execution-status data.

## Sources

### Primary (HIGH confidence)
- Live `revenium` CLI probes (`/opt/homebrew/bin/revenium`, 2026-05-14) — `jobs --help` / `jobs create --help` / `jobs outcome --help` / `jobs get` / `meter completion --help`, `revenium schema`, `--dry-run` request shapes, duplicate-id (409, exit 0) and double-outcome (immutability, exit 0) behavior — verified by all four researchers
- `revenium jobs types --json` → `[]` — confirms job `--type` is an open, non-enforced vocabulary
- https://docs.revenium.io/instrument-your-agents/agent-outcomes — job lifecycle, outcome dimensions, 409 immutability, async create→404 race, explicit "do not add a second retry layer" warning
- Shipped v1.0 source — `skills/revenium/scripts/hermes-report.sh`, `common.sh`, `cron.sh`, `split_strategies.py`, `SKILL.md`, `plugins/revenium-classifier/classifier.py` — integration seams, `REQUIRED_KEYS` contract, `set -uo pipefail` posture, `cmd=(...)` idiom
- `.planning/PROJECT.md` — v1.1 milestone scope, Constraints, Key Decisions D
- `.planning/MILESTONES.md` — v1.0 live-environment lessons (taxonomy collapse 260514-nfb, dead-predicate drop 260514-n8e, bash 3.2 `${VAR@Q}` break)

### Secondary (MEDIUM confidence)
- Revenium SDK reference examples (Sales / Support / AI Coding Workflow agents) — comparative outcome-dimension patterns; the doc is SDK-oriented, CLI flag names verified separately
- Coding-agent job-type and outcome-type semantics — reasoned interpretation of the Revenium model applied to a devops agent, not empirically validated

### Tertiary (LOW confidence)
- None — all findings trace to direct CLI verification, shipped source, or documented v1.0 lessons.

### Detailed research files
- `.planning/research/STACK.md` — verified CLI surface, version-compatibility probe, what-not-to-use
- `.planning/research/FEATURES.md` — table-stakes vs differentiator cut, coding-agent semantics, MVP definition
- `.planning/research/ARCHITECTURE.md` — integration seams, marker-schema options, cron-flow staging, build order
- `.planning/research/PITFALLS.md` — 11 pitfalls, P0/P1/P2 severity, pitfall-to-phase mapping, "looks done but isn't" checklist

---
*Research completed: 2026-05-14*
*Ready for roadmap: yes*
