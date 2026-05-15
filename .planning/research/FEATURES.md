# Feature Research — v1.1 Agentic Job Tracking

**Domain:** Agentic-job tracking for a CLI coding/devops agent (Hermes), layered above the v1.0 `revenium` task-type skill
**Researched:** 2026-05-14
**Confidence:** HIGH for the Revenium wire surface (verified live against `revenium jobs --help` and `meter completion --help`); MEDIUM for coding-agent semantics (interpretation of a sales/support-oriented model applied to a devops agent)

## Scope

This research covers ONLY the new v1.1 agentic-jobs feature surface. The v1.0
task-type classification machinery (markers, classifier plugin, taxonomy, cron
delta-split, idempotency ledger, budget halt) is assumed shipped and is not
re-researched. Jobs sit *above* task-types: many task-type markers roll up into
one agentic job.

## How Agentic-Job Tracking Works (Revenium model)

Revenium models an *agentic job* as a discrete, goal-directed unit of work with a
business outcome, sitting above raw metered completions. Verified lifecycle (from
`revenium jobs --help` per-subcommand help and docs.revenium.io/instrument-your-agents/agent-outcomes):

1. **Create** — `revenium jobs create --agentic-job-id <id> [--name] [--type] [--environment] [--version]`.
   `--agentic-job-id` is the only **required** flag and is a *user-supplied external
   identifier* — the client mints it. There is no server "give me an id" call.
2. **Meter** — every `revenium meter completion` belonging to the job carries
   `--task-id <id>`, value **equal to the `agenticJobId`**. The CLI help is explicit:
   *"Task identifier — correlates the completion with an agentic job (use the same
   value as agenticJobId)."* This is the tx→job wire link; no SDK, no HTTP shim.
3. **Outcome** — `revenium jobs outcome <agenticJobId> --result {SUCCESS|FAILED|CANCELLED}`
   plus optional `--outcome-type`, `--outcome-value`, `--outcome-currency`, `--metadata`,
   `--reported-by`. **Outcomes are immutable** — a second post to the same job returns
   HTTP 409 Conflict.

Two **orthogonal** dimensions describe a finished job:

- **Execution status** (technical, the `--result` flag): `SUCCESS` / `FAILED` /
  `CANCELLED` — did the workflow run to completion without error.
- **Outcome type** (business, `--outcome-type`): `CONVERTED` / `ESCALATED` /
  `DEFLECTED` / `UNSUCCESSFUL` / `CUSTOM` — what business value the job produced
  (`PENDING` is UI-only, not API-postable). The dimensions are independent: a job can
  be `SUCCESS`/`UNSUCCESSFUL` (ran clean, no business win) or `FAILED`/`ESCALATED`
  (broke technically, human took over).

Verified facts that directly shape v1.1 scope:

- `revenium jobs types --json` returns `[]` on this host — **job `--type` is an open
  free-text vocabulary**, NOT a server-enforced enum. It will fragment exactly like
  raw task-types did before the v1.0 taxonomy unless the skill governs it locally.
  This is the single most important finding for v1.1 scope.
- `--agentic-job-id` is **client-minted**, confirming the entropy-suffix design
  (`pr-review-fc7a`) is the collision defense — it must be carried verbatim through
  the marker into both `jobs create` and every `--task-id`.
- `jobs update` only changes `--name`. There is no `jobs update --outcome`; outcome
  reporting is strictly one-shot via `jobs outcome`, server-enforced (409).
- `--dry-run` exists on every `jobs` subcommand — useful for a no-op idempotency probe.
- `revenium jobs` also exposes `get`, `list`, `delete`, `transactions`, `roi`,
  `conversion-funnel` — read/analytics surface. None are needed for v1.1 instrumentation.

## Feature Landscape

### Table Stakes (Required for v1.1 to Be Credible)

The milestone fails its Core Value ("spend ties to units of business work") without
these. Users penalize their absence; they get no credit for their presence.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Agent declares one job per task arc in a FINAL ACTION marker | Without a declared job there is nothing to create, attribute, or close — this *is* the feature | MEDIUM | New fields on the existing marker record; mirrors the v1.0 classify-at-end pattern. Extend the schema, do not add a second agent↔cron channel |
| `agenticJobId` = LLM business label + entropy suffix | Human-readable in the Revenium UI; entropy suffix prevents the `code_review`/`code-review` fragmentation v1.0 hit | LOW | Suffix is `secrets.token_hex(2)` (4 hex chars) — same primitive as the v1.0 `muid()`. Label normalization reuses the task-taxonomy regex |
| Cron idempotently runs `revenium jobs create` once per `agenticJobId` | Re-running cron must never double-create — load-bearing v1.0 invariant, extended | MEDIUM | Gate on a local ledger line (`JOB:<agenticJobId>:created:<ts>`), the same way completions are gated. Do NOT rely on server 409/no-op as the primary guard |
| Cron stamps `--task-id <agenticJobId>` on every `meter completion` in the job | This is the *only* tx→job linkage; without it the created job has zero attributed spend | LOW | Pure pass-through, identical shape to the v1.0 `--operation-type`/`--agent` passthrough (D-23). The id rides in the marker; cron forwards it on every split call |
| Cron reports `jobs outcome` exactly once per terminated arc | Outcome is immutable (409 on retry); a double-report on partial-failure retry is a hard error | MEDIUM | Extend the ledger with `JOB:<id>:outcome:<ts>`; check before posting. The 409 is a backstop, not the guard — a 409 in logs is noise that masks real bugs |
| Self-reported **execution status** `SUCCESS`/`FAILED`/`CANCELLED` | `--result` is the only *required* flag on `jobs outcome`; a job with no outcome stays `PENDING` forever | LOW | The agent always knows this — see coding-agent semantics below |
| Closed job-`--type` seed vocabulary | `jobs types` is empty (open enum); uncontrolled `--type` fragments analytics exactly like raw task-types pre-taxonomy | MEDIUM | This is the v1.1 equivalent of the task-taxonomy problem. A small **closed seed list** is recommended over free-mint (see Anti-Features) |
| Backward compatibility: job-less markers and marker-less sessions meter exactly as v1.0 | Existing installs must not regress — hard PROJECT.md constraint | LOW | If a marker carries no job fields, omit `--task-id` and skip create/outcome. The v1.0 path is byte-untouched |

### Differentiators (Valuable, Not Required for Launch)

Features that make v1.1 genuinely useful rather than merely wire-correct. They align
with the Core Value but can ship incrementally in v1.x.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Business `outcome-type` when the agent has honest signal | Turns "we spent $X" into "we spent $X and shipped a merged PR / escalated to a human" | MEDIUM | For a coding agent, only `DEFLECTED` / `UNSUCCESSFUL` / `ESCALATED` are honestly agent-reportable. `CONVERTED` is not (see semantics) |
| `--metadata` JSON: PR url, branch, test pass/fail, files-changed count | Cheap context that makes a Revenium row diagnostically useful without claiming a dollar value | LOW | `--metadata` accepts an arbitrary JSON string; the agent knows these facts at arc end. Low risk, high readability |
| `--environment` from a static config field (`production` / `dev`) | Separates spend on a CI/autonomous host from a developer's laptop | LOW | One `config.json` field, forwarded by cron; set once at install, not per-arc |
| `--version` = skill version or project git SHA | Lets Revenium ROI views compare job cost across skill releases | LOW | Static; pull from `SKILL.md` frontmatter `version` |
| `--reported-by` = stable agent/operator identifier | Audit trail of who/what closed the job | LOW | Static config field; trivial passthrough |
| Job-type taxonomy file with descriptions (mirror of `task-taxonomy.json`) | Keeps `--type` consistent across hosts; gives the classifier a recency-ordered prompt | MEDIUM | Only worth building if `--type` is free-mint. If v1.1 ships a closed seed list, this is unnecessary — prefer the closed list for v1.1 |

### Anti-Features (Do NOT Build)

Features that look reasonable but create cost, drift, or false data.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Agent self-guesses a monetary `--outcome-value` | "Show ROI in dollars" is Revenium's headline use case | A coding agent has **no honest basis** for a dollar figure. A merged PR is not worth $4,200; inventing one poisons every ROI aggregate. Revenium's own docs reserve `CONVERTED`+value for sales/support agents with a real deal/ticket value | Emit `--outcome-value` only when an operator supplies it via config/metadata. Default: omit it. Execution status + `DEFLECTED` carry the story |
| Free-mint job `--type` like task-types | Symmetry with the v1.0 task-taxonomy | Jobs are coarser and lower-volume than task-types; ~6–8 closed values cover the space and never fragment. Free-mint reintroduces the `code_review`/`code-review` problem at a layer where it's *more* visible (fewer, bigger rows) | Ship a closed seed list (see semantics below). Treat additions as a release, like the task-type blocklist |
| Start-of-arc + end-of-arc marker pair | "Properly bracket the job lifecycle" | Doubles the marker discipline burden and creates a half-open-job failure mode (start written, end never written). v1.0 explicitly chose classify-at-end to avoid pair discipline | Single retrospective FINAL ACTION marker at arc end — already the decided v1.1 design. Cron does create+meter+outcome from one marker |
| Auto-classify `CONVERTED` from "tests passed" / "PR merged" | Tests-green feels like a "win" | Conflates *execution success* with *business conversion*. `SUCCESS` execution status already captures "it worked"; `CONVERTED` means revenue/cost displacement — a coding agent rarely has that signal | Map green tests / merged PR to `executionStatus: SUCCESS`. Leave `outcomeType` unset unless there's genuine business signal |
| Real-time / mid-arc job creation | "Create the job as soon as the arc starts" | Requires the agent to know arc boundaries *prospectively*, which it cannot do reliably; also breaks the cron-owns-the-wire model | Retrospective declaration at arc end; cron creates the job lazily on first sighting of its id |
| Cron auto-deriving arcs from session timing/heuristics | "Don't make the agent decide boundaries" | The agent is the only component that knows when a goal was achieved. Timing heuristics split mid-task and merge unrelated tasks | The agent declares the boundary explicitly in the marker; cron never infers arcs |
| Mutable / re-postable outcomes | "Let the agent correct a wrong outcome" | The API forbids it (409 Conflict). A correction path fights the platform | Treat the first outcome as final. A wrong outcome is a one-time data-quality issue logged once, not retried |
| Cross-session job threading | "One feature spans many Hermes sessions" | v1.0 already scoped markers to a single session (PROJECT.md Out of Scope). Cross-session correlation needs a join key Hermes does not expose | Job arc is bounded within one session. Multiple jobs per session, but no job spans sessions |
| Using `jobs update`/`get`/`roi`/`conversion-funnel` in the cron | They exist in the CLI, so "use them" | Read/analytics surface — not instrumentation. Pulling them into the cron adds API calls and failure modes for no metering benefit | The cron only writes: `create`, `meter completion --task-id`, `outcome`. Analytics is the operator's job in the Revenium UI |

## Coding-Agent Job Semantics (the milestone-specific question)

**Realistic job `--type` values for Hermes (a CLI coding/devops agent).** A closed
seed list sized to the space — not free-mint:

| Job type | Covers |
|----------|--------|
| `code-review` | Reviewing a PR, diff, or module |
| `feature-development` | Building new functionality end to end |
| `bug-fix` | Reproducing and correcting a defect |
| `refactor` | Behavior-preserving restructuring |
| `research` | Investigation / codebase exploration with no shipped artifact |
| `planning` | Roadmaps, design docs, task breakdowns |
| `devops-task` | Cron, CI, deployment, infra changes |
| `documentation` | Writing or updating docs |

These roll **above** the v1.0 task-types: one `feature-development` job arc may
contain `research`, `generation`, `code_review`, and `debugging` task-type markers.
Job-type is the coarse business unit; task-type is the per-turn activity.

**Execution status semantics for a coding task:**

- `SUCCESS` — the goal the agent set out to achieve was reached: the PR was produced,
  the fix landed, the review was delivered. Green tests / passing build is *evidence*
  of `SUCCESS`, but the criterion is the agent's own judgement that it completed what
  was asked.
- `FAILED` — the agent hit a technical wall it could not get past: unrecoverable
  error, blocked tool, the fix did not work and the agent gave up. The arc terminated
  *without* achieving its goal due to a failure.
- `CANCELLED` — the arc was deliberately abandoned: the user changed direction, said
  stop, or the v1.0 budget halt fired mid-arc. Distinct from `FAILED` — nothing broke,
  the work was just called off. (The budget-halt → `CANCELLED` mapping is a clean
  tie-in to existing v1.0 machinery.)

**When can a coding agent honestly know a business `outcome-type`?**

- `DEFLECTED` — **defensible.** "The agent completed this autonomously; doing it
  manually would have cost developer time." This is the natural coding-agent business
  outcome — the value is *displaced developer cost*. Even here, `outcome-value` should
  come from an operator-configured rate, not an agent guess.
- `UNSUCCESSFUL` — **defensible.** Job ran clean (`SUCCESS` execution) but produced
  nothing shippable — e.g. research that concluded "not feasible". `SUCCESS`/`UNSUCCESSFUL`
  is a legitimate, honest pairing.
- `ESCALATED` — **defensible.** The agent handed back to a human ("I need you to
  decide X"). Coding agents do this often.
- `CONVERTED` — **rarely honest.** Implies revenue created or cost meaningfully
  displaced with a known value. A coding agent merging a PR has not "converted"
  anything it can quantify. Reserve for operator-supplied metadata only.
- `CUSTOM` — escape hatch; avoid unless an operator defines a concrete meaning.

**Table-stakes vs differentiator on the business dimension.** **Execution status
(`--result`) is table stakes** — it is the required flag and the agent always knows
it. The **business `outcome-type` is a differentiator**, and even then only
`DEFLECTED` / `UNSUCCESSFUL` / `ESCALATED` should be agent-reportable; `CONVERTED` and
any `--outcome-value` are **operator-supplied opt-in metadata**, never agent-inferred.
Shipping v1.1 with execution status only — `outcome-type` deferred to v1.x — is still
credible and is the recommended MVP cut.

## Task-Arc Boundary Detection (the granularity question)

The agent must identify where one job ends and the next begins *within* a session,
retrospectively, in the FINAL ACTION marker. Guidance for the SKILL.md prompt:

**Signals that mark an arc boundary (a job just ended):**
- The user's stated goal was achieved or explicitly abandoned ("the PR is ready").
- The user introduces a *new, unrelated* goal ("now let's look at the deploy script").
- A natural deliverable was produced and handed back (a merged diff, a doc, a review).
- The user says stop / change direction (→ `CANCELLED`).

**Signals that do NOT mark a boundary (still the same arc):**
- Many tools or many turns — turn/tool count is *not* a boundary. A 30-turn feature
  build is one job.
- The agent paused to research or debug *in service of the same goal* — sub-activities,
  not new jobs.
- The user asked a clarifying question about the in-progress work.

**Anti-fragmentation framing (the dominant failure mode).** The v1.0 taxonomy collapse
showed agents over-produce labels under reuse pressure; the symmetric risk here is
over-splitting under boundary pressure. The prompt must bias toward coarse:

- Default to **continuing the current arc**. A new job is the exception, declared only
  on a clear goal change. "When in doubt, it's the same job."
- Coarser is safer than finer. A job bundling two small related tasks is a minor
  attribution smudge; ten micro-jobs per session is noise that defeats the feature.
- At arc end the agent asks itself one question: "what single goal did these turns
  serve?" If it can name one goal, it is one job.
- Reuse the v1.0 binary-trigger style: give the agent an explicit, judgement-free rule
  for *when* to emit a job marker (a turn that completes/abandons a goal) versus carry
  forward.

**Pragmatic v1.1 floor.** If reliably prompting mid-session arc splitting proves hard,
**one job per session** is a defensible fallback — it still delivers the Core Value
(spend tied to a unit of work) and matches the v1.0 "one marker file per session"
structure. The roadmap should treat multi-arc-per-session as the *target* and
one-arc-per-session as the *acceptable floor*.

## Feature Dependencies

```
[Job declaration marker (FINAL ACTION extension)]
    └──requires──> [v1.0 marker-JSONL contract + classifier plugin]
    └──requires──> [agenticJobId minting: LLM label + entropy suffix]
                       └──reuses──> [v1.0 label-normalization regex + muid() entropy primitive]

[Cron `jobs create` (idempotent)]
    └──requires──> [Job declaration marker]
    └──requires──> [Job ledger extension: JOB:<id>:created line]
                       └──reuses──> [v1.0 append-only ledger + flock idempotency pattern]

[Cron `--task-id` stamp on meter completion]
    └──requires──> [Job declaration marker (supplies the id)]
    └──reuses──> [v1.0 adjacent-flag passthrough (D-23)]

[Cron `jobs outcome` (exactly-once)]
    └──requires──> [Job ledger extension: JOB:<id>:outcome line]
    └──requires──> [execution status in the marker]
    └──requires──> [arc-terminated signal in the marker]

[Closed job-type seed list] ──governs──> [Cron `jobs create` --type]

[outcome-type / outcome-value (DIFFERENTIATOR)]
    └──enhances──> [Cron `jobs outcome`]
    └──requires──> [operator-supplied config for outcome-value — NOT agent-inferred]
```

### Dependency Notes

- **Everything depends on the v1.0 marker machinery.** v1.1 adds *fields* and a record
  type to the marker, plus job-aware logic in `hermes-report.sh`. It adds no new
  agent↔cron channel. The classifier plugin (`on_session_end`) is the natural place the
  job marker gets written, exactly like task-type markers.
- **The ledger is the idempotency backbone for all three job calls.** The v1.0
  `HERMES:<sid>:<total_tokens>:<unix_ts>:<muid>` format must gain job lines
  (`JOB:<agenticJobId>:created` and `JOB:<agenticJobId>:outcome`). Re-running cron
  checks the ledger before `jobs create` and before `jobs outcome`. The 409 is a
  backstop only.
- **The v1.0 mint-back-race hardening item directly de-risks v1.1.** Adding
  `fcntl.flock` to `_persist_label_to_taxonomy` is the same atomic-write discipline a
  job-type taxonomy would need — do that hardening first.
- **`--task-id` stamping conflicts with nothing.** It is an additive flag on
  `meter completion`. The v1.0 S2 marker-split path is unaffected: every split call for
  a job's session window simply carries the same `--task-id`.

## MVP Definition

### Launch With (v1.1)

- [ ] Job declaration marker — extend the FINAL ACTION marker schema with
      `agentic_job_id`, `job_name`, `job_type`, `execution_status`, `arc_terminated`.
- [ ] `agenticJobId` minting — LLM business label + 4-hex entropy suffix, normalized.
- [ ] Closed job-type seed list (`code-review`, `feature-development`, `bug-fix`,
      `refactor`, `research`, `planning`, `devops-task`, `documentation`).
- [ ] Cron `revenium jobs create` — idempotent via a `JOB:<id>:created` ledger line.
- [ ] Cron `--task-id <agenticJobId>` stamped on every `meter completion` for the job.
- [ ] Cron `revenium jobs outcome --result {SUCCESS|FAILED|CANCELLED}` — exactly once,
      gated by a `JOB:<id>:outcome` ledger line.
- [ ] Backward compatibility — job-less markers and marker-less sessions meter as v1.0.
- [ ] v1.0 hardening carry-forward: `fcntl.flock` mint-back fix, `clear-halt.sh` bash
      3.2 compat, retention guard, dead-helper cleanup.

### Add After Validation (v1.x)

- [ ] Business `outcome-type` (`DEFLECTED` / `UNSUCCESSFUL` / `ESCALATED`) self-reported
      by the agent — trigger: execution-status data looks clean and operators ask for
      the business breakdown.
- [ ] `--metadata` JSON enrichment (PR url, branch, test status, files-changed count).
- [ ] `--environment`, `--version`, `--reported-by` static config passthrough.
- [ ] Multi-arc-per-session boundary detection, if v1.1 ships the one-job-per-session
      floor.

### Future Consideration (v2+)

- [ ] Operator-supplied `--outcome-value` (e.g. config hourly-rate × time saved for a
      `DEFLECTED` job) — defer until a concrete operator request and a defensible
      valuation model exist.
- [ ] Job-type taxonomy file with descriptions — only if the closed seed list proves
      too rigid in practice.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Job declaration marker (schema extension) | HIGH | MEDIUM | P1 |
| `agenticJobId` minting (label + entropy) | HIGH | LOW | P1 |
| Cron `jobs create` idempotent | HIGH | MEDIUM | P1 |
| `--task-id` stamp on `meter completion` | HIGH | LOW | P1 |
| Cron `jobs outcome` exactly-once | HIGH | MEDIUM | P1 |
| Execution status (`--result`) self-report | HIGH | LOW | P1 |
| Closed job-type seed list | MEDIUM | LOW | P1 |
| Backward compatibility | HIGH | LOW | P1 |
| v1.0 hardening carry-forward | MEDIUM | LOW | P1 |
| Business `outcome-type` (DEFLECTED/UNSUCCESSFUL/ESCALATED) | MEDIUM | MEDIUM | P2 |
| `--metadata` JSON enrichment | MEDIUM | LOW | P2 |
| `--environment` / `--version` / `--reported-by` | LOW | LOW | P2 |
| Multi-arc-per-session boundary detection | MEDIUM | HIGH | P2 |
| Operator-supplied `--outcome-value` | LOW | MEDIUM | P3 |
| Job-type taxonomy file | LOW | MEDIUM | P3 |

**Priority key:** P1 = must have for v1.1 launch · P2 = should have, add when possible ·
P3 = defer until observed need.

## Competitor Feature Analysis

Revenium provides reference instrumentation patterns rather than competing products.
The three SDK reference examples are the relevant comparison:

| Pattern | Revenium Sales-Agent example | Revenium Support-Agent example | Our Approach (Hermes coding agent) |
|---------|------------------------------|--------------------------------|-------------------------------------|
| Job granularity | Per lead | Per support ticket | Per task arc (multiple per session) |
| Outcome dimension used | `CONVERTED` + dollar `outcomeValue` (deal size) | `DEFLECTED` (avoided call cost) / `ESCALATED` | Execution status always; `DEFLECTED`/`UNSUCCESSFUL`/`ESCALATED` as a v1.x differentiator |
| `outcomeValue` source | Real deal value | Modeled avoided cost | **Omitted by default** — no honest source; operator config only |
| Job creation timing | At lead intake (prospective) | At ticket open (prospective) | Retrospective at arc end (agent declares once) |
| Instrumentation transport | `revenium-python-sdk` middleware | `revenium-python-sdk` middleware | `revenium` CLI only — no SDK, no new runtime dependency (PROJECT.md constraint) |

The "AI Coding Workflow" SDK reference example reports *72% autonomous completion, 10%
escalation, 18% custom outcomes* — note it leans on `CUSTOM`/`DEFLECTED`, not
`CONVERTED`, confirming that a coding agent's honest outcome surface is
autonomous-completion / escalation, not revenue conversion.

## Sources

- `revenium jobs --help` and per-subcommand help (`create`, `outcome`, `types`,
  `update`, `transactions`) — verified live, revenium CLI at `/opt/homebrew/bin/revenium` — HIGH confidence
- `revenium meter completion --help` — confirmed `--task-id` flag semantics ("use the
  same value as agenticJobId") — HIGH confidence
- `revenium jobs types --json` returned `[]` — confirms job-`--type` is an open,
  non-enforced vocabulary — HIGH confidence
- https://docs.revenium.io/instrument-your-agents/agent-outcomes — job lifecycle,
  outcome dimensions, immutability (409), three reference examples — HIGH confidence
  (note: the doc is written for the Python SDK; CLI flag names verified separately)
- `.planning/PROJECT.md` v1.1 milestone section + Key Decisions — project constraints
- `skills/revenium/SKILL.md` FINAL ACTION block + `references/task-taxonomy.md` — the
  v1.0 marker/classifier machinery the job layer extends

---
*Feature research for: agentic-job tracking on a CLI coding agent (v1.1)*
*Researched: 2026-05-14*
