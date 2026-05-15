# Phase 8: Job Declaration Prompt Block - Context

**Gathered:** 2026-05-15
**Status:** Ready for planning

<domain>
## Phase Boundary

`SKILL.md` gains a new `## FINAL ACTION — JOB DECLARATION` section instructing
the Hermes agent to declare one well-formed, business-meaningful job per
completed task arc — minting an `agentic_job_id`, choosing a `job_type`,
self-reporting a conservative outcome — and to write a `CANCELLED` terminal job
marker on the budget-halt path. Pure prompt-engineering plus one shipped seed
data file (`job-taxonomy.json`); no cron-side code (Phases 9–10) and no marker
schema changes (the `kind:"job"` shape is frozen by Phase 7 D-03).

Requirements covered: DECLARE-01..06.

**Backward-compat invariant carried in:** the new section must not weaken the
v1.0 `## ABSOLUTE FIRST — HALT CHECK` anchor or the v1.0 `## FINAL ACTION —
TASK CLASSIFICATION` block; a job-less / marker-less session still meters
byte-identically to v1.0.

</domain>

<decisions>
## Implementation Decisions

### Job-Type Vocabulary & Taxonomy

- **D-01 — `job_type` is LLM-minted free-form, NOT a closed seed enum.**
  *This DEVIATES from DECLARE-04 and ROADMAP Phase 8 Success Criterion 2*, both
  of which say "selects each job's `type` from a **closed** seed vocabulary."
  The user explicitly chose LLM-first minting (parity with how v1.0 `task_type`
  works). **Planner action:** treat DECLARE-04 and ROADMAP SC2 as amended —
  reword "selects from a closed seed vocabulary" to "mints LLM-first,
  reuse-first against a live job-taxonomy." Flag this deviation in the plan so
  REQUIREMENTS.md / ROADMAP.md get updated at phase transition.

- **D-02 — `job_type` gets full v1.0 `task_type` parity.** A seed
  `job-taxonomy.json` ships with the skill; it is copied to a live mutable
  `JOB_TAXONOMY_FILE` (`~/.hermes/state/revenium/job-taxonomy.json`, the path
  Phase 7 D-13 already declared in `common.sh`). The JOB DECLARATION block
  instructs the agent to read the live taxonomy, **reuse the closest-fitting
  existing `job_type` or mint a new one**, and **persist a newly-minted
  `job_type` back** to the live taxonomy. Mirror the v1.0 `task-taxonomy`
  machinery and `references/task-taxonomy.md` schema/normalization rules.

- **D-03 — This activates `JOB_TAXONOMY_FILE` in v1.1.** Phase 7 D-15 declared
  the path but stated it is "unused in v1.1 — no reader or writer until v2
  `JOBTAX-01`." D-01/D-02 supersede that: Phase 8 gives it an agent-side
  reader/writer. **Planner action:** amend Phase 7 D-15's "unused in v1.1"
  note and pull v2 `JOBTAX-01` (job-type taxonomy file) into v1.1 scope as a
  Phase 8 deliverable. Note: this is agent-side only — the cron passes
  `job_type` through unchanged, so Phases 9–10 are unaffected.

- **D-04 — Seed `job-taxonomy.json` ships a broader ~8–10 entry list** for
  day-one Revenium coverage (e.g. `feature_development`, `bug_fix`,
  `code_review`, `refactoring`, `research`, `debugging`, `testing`,
  `documentation`, `devops`, `planning` — exact list is planner discretion).
  **Tradeoff the planner must mitigate:** a larger seed re-creates the
  lookup-collapse the v1.0 mint-first quick task `260514-nfb` had to undo (12
  of 16 markers collapsed onto `generation`). The JOB DECLARATION block's
  mint-first anti-collapse framing must be **strong** — concrete good/bad
  `job_type` examples, explicit "mint a specific type when nothing fits well"
  pressure — to counter the broader seed.

- **D-05 — `agentic_job_id` and `job_name` stay free-form LLM-minted** per
  DECLARE-02. `agentic_job_id` = LLM business label + short hex entropy suffix
  (e.g. `pr-review-fc7a`), with mint-first anti-collapse framing and concrete
  good/bad examples so labels stay specific. `job_name` is a short
  human-readable description. Marker keys are snake_case per Phase 7 D-02/D-03.

### Arc-Boundary Detection

- **D-06 — Eager declaration at completion.** The agent writes the
  `kind:"job"` marker in the FINAL ACTION of the turn where it believes the
  arc's goal is met. Accepted risk: if the user later reopens a
  declared-complete arc, the follow-up work becomes a *separate* job (the
  first was declared prematurely). This is accepted — re-declaration
  correction is unreliable because the cron may have already created/outcome'd
  the job within its 60s tick (outcomes are immutable).

- **D-07 — Eager declaration on abandonment, too.** When the user pivots to a
  genuinely new goal *before* the current arc was declared, the agent first
  writes a `CANCELLED` job marker for the abandoned arc, *then* starts the new
  arc. This prevents the abandoned arc's task markers from being swallowed
  into the next job by positional attribution (Phase 7 D-08) — i.e. it
  prevents the "attribution leaks across tasks" failure mode named in
  PROJECT.md's Core Value. Same CANCELLED-marker mechanism as the budget-halt
  path (D-12).

- **D-08 — Granularity floor is one job per session.** A single-goal session
  produces one job; a multi-goal session produces multiple. An arc that is
  never recognized as terminated (e.g. session ends mid-work) simply never
  becomes a job — those task markers meter as v1.0 with no `--task-id` (Phase
  7 D-11). The abandoned-arc staleness net is explicitly v2 (`STALE-01`).

### Outcome Semantics

- **D-09 — Status enum is exactly `{SUCCESS, FAILED, CANCELLED}`** (DECLARE-05;
  uppercase per Phase 7 D-03 / OUTCOME-05). Business outcome-types
  (`DEFLECTED` etc.) are out of scope (v2 `ENRICH-01`).

- **D-10 — `FAILED` is narrow: a definitive negative terminal state.** The
  agent pursued the goal and it definitively did not work / cannot be achieved
  (the fix didn't fix, the build can't pass, the goal is unachievable).

- **D-11 — `CANCELLED` is the catch-all and the uncertainty-bias target.**
  Arc abandoned, interrupted, superseded, **or outcome genuinely uncertain**.
  The DECLARE-05 "bias to CANCELLED under uncertainty" rule routes uncertain
  arcs to `CANCELLED`, never `FAILED`. Budget-halt (D-12) and user-pivot
  abandonment (D-07) both produce `CANCELLED`.

- **D-12-OUT — `SUCCESS` requires agent self-verification.** `SUCCESS` is
  declared only on positive, checkable evidence the agent itself established
  in that turn: tests run and pass, build green, the diff demonstrably does
  what was asked, the question fully answered. No user sign-off is required
  (incompatible with eager declaration anyway). "I made the change but did not
  / could not verify it" is **not** a confirmed met goal → `CANCELLED`.

### Budget-Halt Path

- **D-13 — A `CANCELLED` job marker ships on the budget-halt path** (DECLARE-06;
  STATE.md: "ships regardless"). The "drop from halt path / defer to v2
  STALE-01" option was rejected — it contradicts STATE.md's commitment.

- **D-14 — Reconciliation approach: Claude's discretion, with a strong
  recommendation.** DECLARE-06's marker-write conflicts with the v1.0 halt
  block ("Do NOT make any tool calls", "YOUR ENTIRE RESPONSE MUST BE EXACTLY
  THIS") *and* with the halt-survivability runbook's pass criterion ("Call no
  tools"). **Recommended:** the *mandated single first-step* approach — rewrite
  the halt block so a halted turn's response is exactly two things in order:
  (1) one `execute_code` call writing the `CANCELLED` job marker, (2) the
  verbatim halt string — nothing else (no data fetch, no answering the user).
  **The halt-survivability runbook MUST be amended in lockstep:** its pass
  criterion changes from "Call no tools" to "exactly one tool call permitted
  (the mandated CANCELLED marker write); the verbatim halt string still fires;
  no other tools, no data fetch, no answering the question." Updating
  `references/halt-survivability.md` is a Phase 8 deliverable.

- **D-15 — Halt-marker fidelity: Claude's discretion, with a strong
  recommendation.** **Recommended:** degraded-deterministic — the halt path
  runs a near-fixed snippet (`agentic_job_id` like `budget-halt-<hex>`,
  `job_type` `interrupted`, minimal `job_name`) so the halted turn carries
  almost no reasoning load and the verbatim halt anchor stays dominant under
  context dilution. Full LLM-minting on the halted turn was weighed and is not
  recommended — it loads real reasoning onto the most safety-critical turn in
  the file. A budget-interrupted arc honestly deserves a generic label.

- **D-16 — Write the halt marker only if an arc is in progress.** If the
  session has no undeclared in-progress arc (the last arc was already
  declared, session idle), the agent just halts — it does not fabricate a
  phantom `CANCELLED` job. This is a lightweight "was I mid-work?" check, kept
  minimal to protect the halt path.

### Claude's Discretion

- **Arc definition (same-arc vs new-arc).** User said "you decide."
  **Recommendation for the planner:** use the *goal-continuity rule* — same
  arc = same goal including follow-up fixes, refinements, and corrections of
  that goal (e.g. "the tests fail" after "implement X" stays in arc X — X is
  not done until it works); a new arc = a goal that is not a continuation of
  the current one. This keeps a job a coherent unit of business work and
  matches PROJECT.md's "goal-directed sequence of turns" wording. Reject the
  finer-grained "topic-shift" rule (it fragments one goal across jobs).
- **Halt-block reconciliation wording and halt-marker fidelity** — see D-14,
  D-15; discretion is bounded by the recommendations there.
- Exact seed `job-taxonomy.json` entry list and descriptions (D-04).
- How the seed `job-taxonomy.json` is copied to the live `JOB_TAXONOMY_FILE`
  (install-cron / setup / first-run copy) — mirror whatever mechanism v1.0
  uses for the `task-taxonomy.json` seed.
- The internal structure of the JOB DECLARATION `execute_code` snippet
  (session-id resolution, `muid`/marker-write helpers may be reused from the
  existing TASK CLASSIFICATION snippet).
- Whether `## FINAL ACTION — JOB DECLARATION` is a sibling section after
  `## FINAL ACTION — TASK CLASSIFICATION` or interleaved — planner's call,
  subject to the halt-survivability gate.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements & decisions
- `.planning/REQUIREMENTS.md` — DECLARE-01..06 definitions. Note D-01/D-03
  flag deviations from DECLARE-04 to be reconciled.
- `.planning/ROADMAP.md` §"Phase 8" — goal, the four success criteria, and
  the dependency on Phase 7. SC2 is amended by D-01.
- `.planning/PROJECT.md` §"Key Decisions" — the v1.1 job-tracking rows
  (`agenticJobId` = LLM label + entropy suffix; declare-once-at-arc-end;
  `--task-id` wire link; immutable one-shot outcomes) and §"Core Value"
  (attribution leak = failure).
- `.planning/STATE.md` §"Research Flags" — Phase 8 arc-boundary + conservative-
  outcome framing flag; "Budget-halt CANCELLED marker ships regardless."
- `.planning/phases/07-job-marker-schema-state-scaffolding/07-CONTEXT.md` —
  **the frozen `kind:"job"` marker schema (D-03), reader-required keys (D-04),
  positional attribution (D-08), last-wins dedup (D-12), `JOB_TAXONOMY_FILE`
  declaration (D-13) and its "unused in v1.1" note (D-15, superseded here).**
  Phase 8's marker writes MUST conform to this shape verbatim.

### v1.0 prompt & taxonomy contract (what this phase extends)
- `skills/revenium/SKILL.md` — the file being edited. §"ABSOLUTE FIRST — HALT
  CHECK" (the block D-13/D-14 amend), §"FINAL ACTION — TASK CLASSIFICATION"
  (the structural and snippet precedent for the new JOB DECLARATION block,
  including the `muid` / session-id-resolution / `fcntl.flock` marker-write
  pattern and the mint-first taxonomy framing).
- `skills/revenium/references/task-taxonomy.md` — v1.0 taxonomy schema,
  normalization rules, and the atomic mint pattern; `job-taxonomy.json` and
  the JOB DECLARATION reuse-first-or-mint logic mirror this.
- `skills/revenium/references/halt-survivability.md` — **the release gate.**
  Its pass criterion ("Call no tools") MUST be amended by Phase 8 per D-14;
  the 4-run test matrix must re-pass after the `SKILL.md` edit.

### Test enforcement
- `tests/test_repository.py` — `test_skill_frontmatter_has_hermes_metadata`,
  `test_no_legacy_branding_left`, `test_runtime_paths_are_hermes_native` (the
  seed `job-taxonomy.json` and live path must not violate path discipline).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `SKILL.md` §"FINAL ACTION — TASK CLASSIFICATION" `execute_code` snippet —
  the session-id resolution ladder, the `muid()` helper, and the
  `fcntl.flock` append-only `write_marker()` pattern are directly reusable for
  the JOB DECLARATION snippet (job markers append to the *same*
  `markers/<sid>.jsonl` file — Phase 7 D-01).
- v1.0 `task-taxonomy.json` seed-file + live-copy + reuse-recency machinery —
  the template for `job-taxonomy.json` (D-02).
- `JOB_TAXONOMY_FILE` path — already declared in `scripts/common.sh` by Phase
  7 D-13; no new path declaration needed in Phase 8 (state-path discipline
  satisfied).

### Established Patterns
- Marker JSONL: one compact JSON object per line, `json.dumps(...,
  separators=(",",":"))`, snake_case keys (Phase 7 D-02).
- Mint-first anti-collapse framing — v1.0 quick task `260514-nfb`: a lookup-
  heavy prompt collapses minted labels; mint-first framing with concrete
  good/bad examples is the proven fix. Applies to both `agentic_job_id` (D-05)
  and `job_type` (D-04).
- The halt-check anchor is delivered via `skill_view()` and can be
  context-compressed in long sessions — every `SKILL.md` addition is a
  dilution risk, which is why the halt-survivability runbook exists.

### Integration Points
- New/edited content is entirely within `skills/revenium/SKILL.md` plus a new
  shipped `skills/revenium/job-taxonomy.json` seed file, plus an amendment to
  `skills/revenium/references/halt-survivability.md`.
- The marker the agent writes is consumed by the Phase 7 `kind`-aware cron
  reader; Phase 8 must emit exactly the Phase 7 D-03 shape.

</code_context>

<specifics>
## Specific Ideas

- Canonical job marker shape is fixed by Phase 7 D-03 — Phase 8 emits exactly:
  `{"kind":"job","ts":...,"sid":...,"agentic_job_id":...,"job_name":...,"job_type":...,"status":...}`.
  Reader-required keys (Phase 7 D-04): `kind`, `agentic_job_id`, `job_type`,
  `status`. A job marker missing any of these is dropped by the cron — the
  JOB DECLARATION snippet must always emit all four.
- `agentic_job_id` example shape: `pr-review-fc7a` (business label + short hex
  suffix). Halt-path degraded form: `budget-halt-<hex>` (D-15).
- The premature-SUCCESS / eager-completion interaction (D-06): the planner
  should make the SUCCESS bar (D-12-OUT, self-verification) explicit enough
  that an unverified "probably done" arc is declared `CANCELLED`, not
  `SUCCESS` — eager declaration must not become eager over-claiming.

</specifics>

<deferred>
## Deferred Ideas

- **Abandoned-arc staleness sweeper** — an arc that ends without any terminal
  job marker (session closed mid-work) never becomes a job. Cron-side
  recovery is v2 `STALE-01`, explicitly out of Phase 8 scope (D-08).
- **Business outcome-types** (`DEFLECTED` / `ESCALATED` / `outcome_type` /
  `outcome_value` on the job marker) — v2 `ENRICH-01/02`; the Phase 7 D-03
  frozen shape does not carry them.
- **Re-declaration correction of a prematurely-declared arc** — Phase 7 D-12's
  last-wins dedup technically allows re-emitting a job marker with the same
  `agentic_job_id`, but it is unreliable against the 60s cron tick and
  immutable outcomes (D-06). Not built into the Phase 8 prompt.

None of the above is scope creep into Phase 8 — all are explicitly later
milestone work.

</deferred>

---

*Phase: 8-job-declaration-prompt-block*
*Context gathered: 2026-05-15*
