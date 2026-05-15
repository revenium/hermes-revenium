# Phase 8: Job Declaration Prompt Block - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-15
**Phase:** 8-job-declaration-prompt-block
**Areas discussed:** Seed job-type vocabulary, Arc-boundary detection, Outcome semantics, Budget-halt CANCELLED marker

---

## Seed job-type vocabulary

The phase opened with a question about how granular the *closed* seed list
should be. The user interrupted to ask whether the LLM still decides the job
type — surfacing that the phase-as-scoped (closed seed vocabulary, DECLARE-04)
did not match their mental model. The question was reframed.

### Question 1 — closed seed list vs LLM-minted free-form

| Option | Description | Selected |
|--------|-------------|----------|
| Closed seed list | LLM selects nearest from a fixed enum; matches DECLARE-04 as written | |
| LLM-minted free-form | Agent mints job_type like task_type; deviates from DECLARE-04 | ✓ |
| Closed list + escape hatch | Closed list with a single 'general' catch-all fallback | |

**User's choice:** LLM-minted free-form.
**Notes:** Flagged as a deviation from DECLARE-04 and ROADMAP Phase 8 SC2.

### Question 2 — how minted job_type stays consistent

| Option | Description | Selected |
|--------|-------------|----------|
| Full task_type parity | Live job-taxonomy.json, reuse-first-or-mint, persist back | ✓ |
| Seed list shown, mint allowed | Inline seed examples, no taxonomy file, no persistence | |
| Pure free-form, accept drift | No seed, no taxonomy; accept fragmentation | |

**User's choice:** Full task_type parity.
**Notes:** Activates Phase 7's JOB_TAXONOMY_FILE (amends Phase 7 D-15); pulls
v2 JOBTAX-01 into v1.1 scope.

### Question 3 — seed job-taxonomy.json size

| Option | Description | Selected |
|--------|-------------|----------|
| Small anchor (~4) | Minimal seed; minimizes collapse-onto-seed pressure | |
| Empty seed | 100% agent-grown taxonomy | |
| Broader seed (~8-10) | Fuller starter list; better day-one coverage | ✓ |

**User's choice:** Broader seed (~8-10).
**Notes:** Reintroduces lookup-collapse risk (v1.0 quick task 260514-nfb) —
mint-first framing in SKILL.md must be strong to counter it.

---

## Arc-boundary detection

### Question 1 — when the agent writes a job marker

| Option | Description | Selected |
|--------|-------------|----------|
| Eager — at completion | Marker written the turn the agent believes the goal is met | ✓ |
| Conservative — when provably closed | Carry the arc forward; declare only on clear evidence it is over | |
| You decide | Claude's discretion | |

**User's choice:** Eager — at completion.
**Notes:** Accepted risk — a later reopen becomes a separate job.

### Question 2 — user pivots before the prior arc was declared

| Option | Description | Selected |
|--------|-------------|----------|
| Declare abandoned arc first | Write a CANCELLED marker for the abandoned arc, then start the new one | ✓ |
| Let it fold into next job | Abandoned task markers fold into the next job — accepts attribution leak | |
| You decide | Claude's discretion | |

**User's choice:** Declare abandoned arc first.

### Question 3 — same arc vs new arc definition

| Option | Description | Selected |
|--------|-------------|----------|
| Goal-continuity rule | Same goal incl. follow-up fixes/refinements = same arc | |
| Topic-shift rule | New arc on every activity-type shift | |
| You decide | Claude's discretion | ✓ |

**User's choice:** You decide.
**Notes:** Recommendation captured in CONTEXT.md — planner should adopt the
goal-continuity rule.

---

## Outcome semantics

### Question 1 — FAILED vs CANCELLED distinction

| Option | Description | Selected |
|--------|-------------|----------|
| FAILED = definitive negative | FAILED narrow; CANCELLED catches abandoned/interrupted/uncertain | ✓ |
| FAILED = any non-success | FAILED covers uncertainty; CANCELLED only explicit interruption | |
| You decide | Claude's discretion | |

**User's choice:** FAILED = definitive negative.

### Question 2 — what counts as a confirmed met goal for SUCCESS

| Option | Description | Selected |
|--------|-------------|----------|
| Agent self-verification | Positive checkable evidence the agent established this turn | ✓ |
| User acknowledgment | SUCCESS only after explicit user confirmation | |
| You decide | Claude's discretion | |

**User's choice:** Agent self-verification.
**Notes:** Only bar compatible with eager declaration; unverified "probably
done" → CANCELLED.

---

## Budget-halt CANCELLED marker

### Question 1 — reconciling the marker-write with the halt contract

| Option | Description | Selected |
|--------|-------------|----------|
| Mandated single first-step | One marker-write then verbatim halt string; amend the runbook criterion | |
| Drop from halt path | Leave halt block untouched; defer to v2 STALE-01; drops DECLARE-06 | |
| You decide | Claude's discretion | ✓ |

**User's choice:** You decide.
**Notes:** CONTEXT.md captures a strong recommendation for the mandated
single first-step; "drop from halt path" contradicts STATE.md's "ships
regardless" commitment and is not viable.

### Question 2 — fidelity of the halt-path CANCELLED marker

| Option | Description | Selected |
|--------|-------------|----------|
| Degraded deterministic | Near-fixed snippet; generic id/type; minimal reasoning on the halted turn | |
| Full LLM-minted label | Meaningful id/type minted on the halted turn | |
| You decide | Claude's discretion | ✓ |

**User's choice:** You decide.
**Notes:** CONTEXT.md recommends degraded-deterministic to keep the halt
anchor dominant under context dilution.

---

## Claude's Discretion

- Same-arc vs new-arc definition (recommendation: goal-continuity rule).
- Budget-halt reconciliation wording (recommendation: mandated single
  first-step + amend the halt-survivability runbook pass criterion).
- Budget-halt marker fidelity (recommendation: degraded-deterministic).
- Exact seed job-taxonomy.json entries; seed→live copy mechanism; internal
  structure of the JOB DECLARATION execute_code snippet; section placement
  relative to FINAL ACTION — TASK CLASSIFICATION.

## Deferred Ideas

- Abandoned-arc staleness sweeper — v2 STALE-01.
- Business outcome-types (DEFLECTED/ESCALATED, outcome_type/outcome_value) — v2 ENRICH-01/02.
- Re-declaration correction of a prematurely-declared arc — not built into the Phase 8 prompt.
