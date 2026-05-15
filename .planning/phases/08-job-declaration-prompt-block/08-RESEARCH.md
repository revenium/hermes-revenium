# Phase 8: Job Declaration Prompt Block - Research

**Researched:** 2026-05-15
**Domain:** Prompt engineering — extending `SKILL.md` with an agent-side job-declaration contract; one shipped seed data file; one reference-doc amendment
**Confidence:** HIGH (all findings verified by direct read of in-repo files; this is an internal-codebase phase with no external dependency surface)

## Summary

Phase 8 is a pure prompt-engineering phase. It adds a new `## FINAL ACTION — JOB DECLARATION`
section to `skills/revenium/SKILL.md` that instructs the Hermes agent to declare exactly one
`kind:"job"` JSONL marker per completed task arc, ships a new `skills/revenium/job-taxonomy.json`
seed file, and amends `skills/revenium/references/halt-survivability.md`. No cron-side code changes
— `hermes-report.sh`, `budget-check.sh`, `common.sh`, and the classifier plugin are untouched.

The phase's hard substrate is already frozen: Phase 7 D-03 fixed the `kind:"job"` marker shape
verbatim, Phase 7 D-13 already declared `JOB_TAXONOMY_FILE` in `common.sh` (verified present at
`common.sh:25`), and the v1.0 `## FINAL ACTION — TASK CLASSIFICATION` block (`SKILL.md:279-398`)
supplies a near-complete structural and `execute_code` precedent — the session-id resolution
ladder, the `muid()` helper, and the `fcntl.flock` append-only `write_marker()` pattern are all
directly reusable. The job marker appends to the *same* `markers/<sid>.jsonl` file as task markers
(Phase 7 D-01), so the snippet's file-path machinery is identical.

The two genuine risks are: (1) **taxonomy collapse** — a broader ~8-10 entry `job-taxonomy.json`
re-creates the lookup-collapse failure the v1.0 quick-task `260514-nfb` had to undo (12/16 markers
collapsed onto `generation`); the JOB DECLARATION block needs *strong* mint-first anti-collapse
framing with concrete good/bad examples. (2) **halt-anchor dilution** — every byte added to
`SKILL.md` is delivered via a compressible `skill_view()` tool result; the halt-survivability
runbook is the release gate and its pass criterion changes from "call no tools" to "exactly one
tool call permitted" (D-14). The runbook amendment must land in lockstep with the `SKILL.md` edit.

**Primary recommendation:** Add `## FINAL ACTION — JOB DECLARATION` as a sibling section
immediately after `## FINAL ACTION — TASK CLASSIFICATION`, reusing that block's `execute_code`
scaffolding verbatim and adding a `write_job_marker()` helper. Rewrite the HALT CHECK block to a
*mandated single first-step* — one `execute_code` call writing a degraded-deterministic CANCELLED
job marker, then the verbatim halt string, nothing else. Ship `job-taxonomy.json` mirroring the
v1.0 `task-taxonomy.json` schema and seed→live-copy machinery, and amend `halt-survivability.md`
in the same plan.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Job-Type Vocabulary & Taxonomy**

- **D-01** — `job_type` is LLM-minted free-form, NOT a closed seed enum. This DEVIATES from
  DECLARE-04 and ROADMAP Phase 8 SC2 ("closed seed vocabulary"). User explicitly chose LLM-first
  minting (parity with v1.0 `task_type`). Planner action: treat DECLARE-04 and ROADMAP SC2 as
  amended — reword "selects from a closed seed vocabulary" to "mints LLM-first, reuse-first
  against a live job-taxonomy." Flag this deviation in the plan so REQUIREMENTS.md / ROADMAP.md
  get updated at phase transition.
- **D-02** — `job_type` gets full v1.0 `task_type` parity. A seed `job-taxonomy.json` ships with
  the skill; it is copied to a live mutable `JOB_TAXONOMY_FILE`
  (`~/.hermes/state/revenium/job-taxonomy.json`). The JOB DECLARATION block instructs the agent
  to read the live taxonomy, reuse the closest-fitting existing `job_type` or mint a new one,
  and persist a newly-minted `job_type` back. Mirror the v1.0 `task-taxonomy` machinery and
  `references/task-taxonomy.md` schema/normalization rules.
- **D-03** — Phase 8 activates `JOB_TAXONOMY_FILE` in v1.1 (Phase 7 D-15 said "unused in v1.1").
  Planner action: amend Phase 7 D-15's "unused in v1.1" note and pull v2 `JOBTAX-01` into v1.1
  scope as a Phase 8 deliverable. Agent-side only — the cron passes `job_type` through unchanged.
- **D-04** — Seed `job-taxonomy.json` ships a broader ~8-10 entry list (e.g. `feature_development`,
  `bug_fix`, `code_review`, `refactoring`, `research`, `debugging`, `testing`, `documentation`,
  `devops`, `planning` — exact list is planner discretion). Tradeoff: a larger seed re-creates the
  `260514-nfb` lookup-collapse. The mint-first anti-collapse framing must be STRONG.
- **D-05** — `agentic_job_id` and `job_name` stay free-form LLM-minted. `agentic_job_id` = LLM
  business label + short hex entropy suffix (e.g. `pr-review-fc7a`), with anti-collapse framing
  and concrete good/bad examples. `job_name` is a short human-readable description. Marker keys
  are snake_case (Phase 7 D-02/D-03).

**Arc-Boundary Detection**

- **D-06** — Eager declaration at completion. The agent writes the `kind:"job"` marker in the
  FINAL ACTION of the turn where it believes the arc's goal is met. Accepted risk: a reopened
  arc becomes a separate job.
- **D-07** — Eager declaration on abandonment. When the user pivots to a genuinely new goal
  *before* the current arc was declared, the agent first writes a `CANCELLED` job marker for the
  abandoned arc, then starts the new arc. Prevents positional-attribution leakage (Phase 7 D-08).
- **D-08** — Granularity floor is one job per session. A never-terminated arc simply never becomes
  a job (those task markers meter as v1.0 with no `--task-id`, Phase 7 D-11). Abandoned-arc
  staleness net is explicitly v2 (`STALE-01`).

**Outcome Semantics**

- **D-09** — Status enum is exactly `{SUCCESS, FAILED, CANCELLED}` (uppercase, Phase 7 D-03).
  Business outcome-types are out of scope (v2 `ENRICH-01`).
- **D-10** — `FAILED` is narrow: a definitive negative terminal state (the fix didn't fix, the
  build can't pass, the goal is unachievable).
- **D-11** — `CANCELLED` is the catch-all and uncertainty-bias target. Arc abandoned, interrupted,
  superseded, or outcome genuinely uncertain. Budget-halt (D-12) and user-pivot abandonment (D-07)
  both produce `CANCELLED`.
- **D-12-OUT** — `SUCCESS` requires agent self-verification: positive, checkable evidence the
  agent itself established that turn (tests pass, build green, diff demonstrably correct, question
  fully answered). No user sign-off. "I made the change but did not / could not verify it" →
  `CANCELLED`.

**Budget-Halt Path**

- **D-13** — A `CANCELLED` job marker ships on the budget-halt path (DECLARE-06). The
  "drop / defer to v2" option was rejected.
- **D-14** — Reconciliation: Claude's discretion, **strong recommendation = the mandated single
  first-step approach** — rewrite the halt block so a halted turn's response is exactly two things
  in order: (1) one `execute_code` call writing the `CANCELLED` job marker, (2) the verbatim halt
  string — nothing else. **The halt-survivability runbook MUST be amended in lockstep:** pass
  criterion changes from "Call no tools" to "exactly one tool call permitted (the mandated
  CANCELLED marker write); the verbatim halt string still fires; no other tools, no data fetch,
  no answering the question." Updating `references/halt-survivability.md` is a Phase 8 deliverable.
- **D-15** — Halt-marker fidelity: Claude's discretion, **strong recommendation = degraded-
  deterministic** — the halt path runs a near-fixed snippet (`agentic_job_id` like
  `budget-halt-<hex>`, `job_type` `interrupted`, minimal `job_name`) so the halted turn carries
  almost no reasoning load. Full LLM-minting on the halted turn is NOT recommended.
- **D-16** — Write the halt marker only if an arc is in progress. If the session has no undeclared
  in-progress arc, the agent just halts — no phantom `CANCELLED` job. Lightweight "was I
  mid-work?" check, kept minimal.

### Claude's Discretion

- **Arc definition (same-arc vs new-arc).** Recommendation for the planner: use the
  *goal-continuity rule* — same arc = same goal including follow-up fixes, refinements, and
  corrections of that goal (e.g. "the tests fail" after "implement X" stays in arc X); a new arc =
  a goal that is not a continuation. Reject the finer-grained "topic-shift" rule.
- **Halt-block reconciliation wording and halt-marker fidelity** — see D-14, D-15; discretion is
  bounded by the recommendations there.
- Exact seed `job-taxonomy.json` entry list and descriptions (D-04).
- How the seed `job-taxonomy.json` is copied to the live `JOB_TAXONOMY_FILE` (install-cron /
  setup / first-run copy) — mirror whatever mechanism v1.0 uses for `task-taxonomy.json`.
- The internal structure of the JOB DECLARATION `execute_code` snippet (session-id resolution,
  `muid`/marker-write helpers may be reused from the existing TASK CLASSIFICATION snippet).
- Whether `## FINAL ACTION — JOB DECLARATION` is a sibling section after `## FINAL ACTION — TASK
  CLASSIFICATION` or interleaved — planner's call, subject to the halt-survivability gate.

### Deferred Ideas (OUT OF SCOPE)

- **Abandoned-arc staleness sweeper** — cron-side recovery of arcs that end without a terminal
  marker. v2 `STALE-01`, explicitly out of Phase 8 scope (D-08).
- **Business outcome-types** (`DEFLECTED` / `ESCALATED` / `outcome_type` / `outcome_value` on the
  job marker) — v2 `ENRICH-01/02`; the Phase 7 D-03 frozen shape does not carry them.
- **Re-declaration correction of a prematurely-declared arc** — Phase 7 D-12's last-wins dedup
  technically allows it, but it is unreliable against the 60s cron tick and immutable outcomes
  (D-06). Not built into the Phase 8 prompt.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DECLARE-01 | Agent declares a job per completed arc by appending a `kind:"job"` marker in FINAL ACTION, retrospectively (once, at arc end). | New `## FINAL ACTION — JOB DECLARATION` section; mirrors the trigger/required-action-sequence/self-check structure of the v1.0 TASK CLASSIFICATION block (`SKILL.md:279-398`). Marker appends to the same `markers/<sid>.jsonl` file. |
| DECLARE-02 | Agent mints an `agentic_job_id` = LLM business label + short hex entropy suffix (`pr-review-fc7a`), with mint-first anti-collapse framing. | `secrets.token_hex(2)` gives a 4-char hex suffix; reuse the v1.0 mint-first prose pattern + good/bad examples from `task-taxonomy.md` "Mint policy". D-05. |
| DECLARE-03 | Agent identifies task-arc boundaries within a session so one multi-activity session produces multiple jobs. | Goal-continuity arc definition (CONTEXT discretion recommendation); eager declaration at completion (D-06) and at abandonment (D-07). Granularity floor: one job/session (D-08). |
| DECLARE-04 | Agent selects each job's `type` from a vocabulary. **AMENDED by D-01** — `job_type` is LLM-minted reuse-first against a live `job-taxonomy.json`, NOT a closed enum. | New `skills/revenium/job-taxonomy.json` seed (~8-10 entries, D-04); JOB DECLARATION block reads live `JOB_TAXONOMY_FILE`, reuses-or-mints, persists minted types back via the atomic write pattern (`task-taxonomy.md` "Atomic write pattern"). |
| DECLARE-05 | Agent self-reports `SUCCESS`/`FAILED`/`CANCELLED` with conservative criteria — bias to `CANCELLED` under uncertainty. | D-09/D-10/D-11/D-12-OUT outcome semantics; explicit `SUCCESS`-requires-self-verification bar so eager declaration ≠ eager over-claiming. |
| DECLARE-06 | Budget-halt path writes a `CANCELLED` terminal job marker before the verbatim halt string. | D-13 (ships regardless); D-14 mandated-single-first-step halt-block rewrite; D-15 degraded-deterministic marker; D-16 arc-in-progress guard. Lockstep `halt-survivability.md` amendment. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Job arc-boundary recognition | Agent prompt (`SKILL.md`) | — | Only the agent knows when a goal arc is complete; the cron sees a flat marker file. |
| `agentic_job_id` / `job_name` minting | Agent prompt (`SKILL.md`) | — | LLM business labeling — D-05; no deterministic source for "what business work was this". |
| `job_type` reuse-or-mint | Agent prompt (`SKILL.md`) | Live `JOB_TAXONOMY_FILE` (state) | Agent reads + writes the live taxonomy file; mirrors v1.0 `task_type` (D-01/D-02). |
| Job marker write (`kind:"job"` JSONL line) | Agent `execute_code` snippet | `markers/<sid>.jsonl` (state) | Appends to the same per-session marker file as task markers (Phase 7 D-01). |
| Outcome self-report (`SUCCESS`/`FAILED`/`CANCELLED`) | Agent prompt (`SKILL.md`) | — | Conservative self-verification judgement — D-09..D-12-OUT. |
| Budget-halt CANCELLED marker | Agent prompt (HALT CHECK block) | `markers/<sid>.jsonl` (state) | Halt turn writes one degraded-deterministic marker before the halt string (D-13..D-16). |
| Seed taxonomy → live-file copy | Install machinery (`setup-local.sh`) | — | First-run copy of the shipped seed into mutable state — mirrors v1.0 `task-taxonomy.json`. |
| Job creation / `--task-id` / outcomes | Cron (`hermes-report.sh`) — **Phase 9/10** | — | OUT OF SCOPE for Phase 8. The cron is a pure consumer of the marker the agent writes. |

## Standard Stack

This is an internal prompt-engineering phase. There is no library stack — the "stack" is the
existing repo idiom, locked by `CLAUDE.md`.

### Core (already present — reuse, do not add)
| Component | Where | Purpose | Why Standard |
|-----------|-------|---------|--------------|
| `execute_code` Python snippet | `SKILL.md:315-365` (TASK CLASSIFICATION) | Marker writer the agent runs as its FINAL ACTION | Stdlib-only; proven; the JOB DECLARATION snippet is a near-clone. |
| `fcntl.flock` append-only `write_marker()` | `SKILL.md:353-359` | Atomic JSONL append to `markers/<sid>.jsonl` | Phase 7 D-01: job markers append to the same file. Directly reusable — add a `write_job_marker()` variant. |
| `muid()` helper | `SKILL.md:348-351` | 33-char sortable hex id | Reusable for entropy generation; `secrets.token_hex` is the entropy primitive for the `agentic_job_id` suffix. |
| Session-id resolution ladder | `SKILL.md:328-342` | Resolve the active session jsonl name → marker filename | Identical requirement for the job marker. Copy verbatim. |
| Atomic taxonomy write (`flock` + tmp + `os.rename`) | `references/task-taxonomy.md:100-126` | Persist a newly-minted label back to the live taxonomy without partial reads | The template for persisting a minted `job_type` back to `JOB_TAXONOMY_FILE`. |
| Seed→live-copy idiom | `examples/setup-local.sh:14-22` | Copy shipped seed into mutable state on fresh install, no-clobber | The exact pattern `job-taxonomy.json` must mirror. |

### Supporting
| Component | Where | Purpose |
|-----------|-------|---------|
| `JOB_TAXONOMY_FILE` var | `common.sh:25` (already declared, Phase 7 D-13) | Live mutable taxonomy path — `~/.hermes/state/revenium/job-taxonomy.json`. **No new path declaration needed.** |
| `references/task-taxonomy.md` | reference doc | Schema + normalization + mint-policy precedent the new `job-taxonomy.json` mirrors. A parallel `references/job-taxonomy.md` is planner discretion (not strictly required; D-04 says "mirror the v1.0 machinery"). |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Mandated-single-first-step halt block (D-14 rec) | Keep halt block tool-free, drop the CANCELLED marker | Rejected by D-13 — contradicts STATE.md's "ships regardless" commitment. |
| Degraded-deterministic halt marker (D-15 rec) | Full LLM-minting on the halt turn | Rejected by D-15 — loads real reasoning onto the most safety-critical turn; dilution risk. |
| Sibling `## FINAL ACTION — JOB DECLARATION` section | Interleave job logic into the TASK CLASSIFICATION block | Planner discretion. Sibling keeps the v1.0 block byte-stable (backward-compat invariant) and is easier to halt-survivability-test in isolation. Recommend sibling. |
| Closed seed enum for `job_type` (DECLARE-04 literal) | LLM-minted reuse-first (D-01) | D-01 overrides — parity with v1.0 `task_type`; flag the deviation for REQUIREMENTS.md/ROADMAP.md update. |

**Installation:** No `npm`/`pip` install. The seed file ships in the skill tree and is copied to
state by `setup-local.sh` (and any first-run/install path the planner chooses to mirror).

## Architecture Patterns

### System Architecture Diagram

```
  Hermes session (in-process)                         Cron pipeline (out-of-process, Phase 9/10)
  ──────────────────────────                          ───────────────────────────────────────────
  user turn
     │
     ▼
  [skill_view() delivers SKILL.md]
     │
     ▼
  ## ABSOLUTE FIRST — HALT CHECK ──── halted:true ──▶ (D-16) arc in progress?
     │ halted:false                                      │ yes        │ no
     ▼                                                   ▼            ▼
  ...do the work...                            execute_code:    just emit
     │                                         write degraded   verbatim
     ▼                                         CANCELLED job     halt string
  arc goal met? ──no──▶ (continues, no marker)  marker, then
     │ yes                                      verbatim halt
     ▼                                          string
  ## FINAL ACTION — JOB DECLARATION                  │
     │  1. read live JOB_TAXONOMY_FILE                │
     │  2. reuse-or-mint job_type                     │
     │  3. mint agentic_job_id (label+hex)            │
     │  4. pick SUCCESS/FAILED/CANCELLED              │
     │  5. execute_code → write_job_marker()          │
     ▼                                                ▼
  markers/<sid>.jsonl  ◀── {"kind":"job",...} appended ───────────▶  hermes-report.sh
  (also holds kind-absent task markers)                              kind-aware reader
                                                                     (Phase 7 D-06):
                                                                     collects job lines,
                                                                     positional attribution
                                                                     (Phase 7 D-08)
```

The agent writes; the cron reads. The only Phase 8 wire artifact is the `kind:"job"` line. The
seed→live copy of `job-taxonomy.json` is a one-time install-side flow.

### Recommended Structure (files this phase touches)

```
skills/revenium/
├── SKILL.md                          # EDIT: rewrite HALT CHECK block; add JOB DECLARATION section
├── job-taxonomy.json                 # NEW: ~8-10 entry seed, mirrors task-taxonomy.json schema
└── references/
    ├── halt-survivability.md         # EDIT: pass criterion "no tools" → "exactly one tool call"
    └── job-taxonomy.md               # OPTIONAL NEW: parallel reference doc (planner discretion)

examples/setup-local.sh               # EDIT: add job-taxonomy.json seed→live copy block
tests/test_repository.py              # EDIT: add job-taxonomy.json to expected files; optional job-taxonomy schema test
```

### Pattern 1: Sibling FINAL ACTION section reusing the TASK CLASSIFICATION scaffold
**What:** Add `## FINAL ACTION — JOB DECLARATION` after `## FINAL ACTION — TASK CLASSIFICATION`,
structured the same way: a binary Trigger, a Required action sequence, an `execute_code` snippet,
a self-check, and worked Examples.
**When to use:** Always — it preserves the v1.0 block byte-identically (backward-compat invariant)
and isolates the new content for halt-survivability testing.
**Example — the reusable marker-write core (from `SKILL.md:344-365`, adapt for `kind:"job"`):**
```python
# Source: skills/revenium/SKILL.md:344-365 — adapt write_marker -> write_job_marker
import fcntl, json, os, secrets, time
# ... session_id resolution ladder copied verbatim from SKILL.md:328-342 ...
markers_dir = os.path.expanduser("~/.hermes/state/revenium/markers")
os.makedirs(markers_dir, mode=0o700, exist_ok=True)
marker_path = os.path.join(markers_dir, f"{session_id}.jsonl")

def write_job_marker(agentic_job_id, job_name, job_type, status):
    # Phase 7 D-03 frozen shape — reader-required keys: kind, agentic_job_id, job_type, status
    record = {"kind": "job", "ts": time.time(), "sid": session_id,
              "agentic_job_id": agentic_job_id, "job_name": job_name,
              "job_type": job_type, "status": status}
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n"
    with open(marker_path, "ab", buffering=0) as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line.encode("utf-8"))
```

### Pattern 2: `agentic_job_id` = business label + hex entropy suffix
**What:** `f"{business_label}-{secrets.token_hex(2)}"` → e.g. `pr-review-fc7a`. The business
label is LLM-minted; the suffix is 4 hex chars (`token_hex(2)`).
**When to use:** Every job declaration. The halt path uses the degraded form `budget-halt-<hex>`.
**Note:** `token_hex(2)` = 4 chars, matching the `fc7a` example in Phase 7 D-03 and CONTEXT D-05.

### Pattern 3: Reuse-or-mint against the live job taxonomy
**What:** Read `~/.hermes/state/revenium/job-taxonomy.json`, reuse the closest-fitting existing
`job_type`, mint a new `^[a-z][a-z0-9_]{1,47}$` snake_case label only if none fits, persist a
minted label back via the atomic write pattern.
**When to use:** Every non-halt job declaration. Mirrors `task-taxonomy.md` mint policy verbatim.

### Pattern 4: Mandated single first-step halt block (D-14)
**What:** Rewrite `## ABSOLUTE FIRST — HALT CHECK` so a `halted:true` turn does exactly two things
in order: (1) one `execute_code` call writing a degraded-deterministic `CANCELLED` job marker
*only if an arc is in progress* (D-16), (2) emit the verbatim halt string. Nothing else.
**When to use:** This is the D-14 recommended reconciliation. Today's block says "Do NOT make any
tool calls" (`SKILL.md:37`) and "YOUR ENTIRE RESPONSE MUST BE EXACTLY THIS AND NOTHING ELSE"
(`SKILL.md:33`) — both must be reworded to permit exactly the one mandated marker-write call.

### Anti-Patterns to Avoid
- **Bland-catch-all `job_type` collapse:** the `260514-nfb` failure. A larger seed (D-04) makes
  this worse — the prompt MUST push "mint a specific type when nothing fits well" with concrete
  good/bad examples. Catch-alls to call out as bad: `generation`, `task`, `work`, `coding`.
- **Eager declaration becoming eager over-claiming:** D-06 + D-12-OUT interaction — an unverified
  "probably done" arc must declare `CANCELLED`, never `SUCCESS`. Make the SUCCESS self-verification
  bar explicit and example-backed.
- **Weakening the halt anchor:** do not soften "verbatim halt string" or reorder so the marker
  write can swallow the halt string. The marker write is step 1; the halt string is step 2; the
  agent answers nothing.
- **Touching the v1.0 TASK CLASSIFICATION block:** Phase 7 D-09/SCHEMA-04 require v1.0 task
  markers stay byte-identical. The JOB DECLARATION section is additive; do not edit lines 279-398
  except where strictly necessary.
- **Declaring a job mid-arc / prospectively:** DECLARE-01 — retrospective, once, at arc end only.
- **Phantom halt jobs:** D-16 — no `CANCELLED` marker if no arc was in progress.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Session-id resolution | A new resolution scheme | Copy the 3-tier ladder from `SKILL.md:328-342` verbatim | The cron's marker reader expects the marker FILENAME to equal the session jsonl basename; deviating breaks attribution. |
| Atomic JSONL append | A read-modify-write or a lockfile dance | `open(...,"ab")` + `fcntl.flock(LOCK_EX)` from `SKILL.md:353-359` | Already proven; POSIX `O_APPEND` + advisory flock is the repo idiom. |
| Persisting a minted `job_type` | An in-place `json.dump` over the live file | The `flock` + tmp + `os.rename` pattern in `task-taxonomy.md:100-126` | In-place writes risk partial reads by the agent on a later turn; `os.rename` is the atomicity mechanism. |
| Entropy suffix | `random.randint` / time-based | `secrets.token_hex(2)` | Stdlib, collision-safe enough for a 4-char business id; matches the v1.0 `muid` precedent. |
| Seed→live copy | A bespoke first-run hook | The no-clobber `cp` block in `setup-local.sh:14-22` | Identical requirement; mirror it for `job-taxonomy.json`. |
| New state path | Inline `~/.hermes/...` literal | `JOB_TAXONOMY_FILE` — already in `common.sh:25` | Phase 7 D-13 already declared it; `test_runtime_paths_are_hermes_native` enforces single-source. |

**Key insight:** Phase 8 should write almost no new mechanism. Every primitive it needs — marker
write, session-id resolution, atomic taxonomy mutation, seed-copy — already exists and is
test-pinned. The phase's real work is *prose*: arc-boundary definition, conservative-outcome
criteria, and anti-collapse framing.

## Common Pitfalls

### Pitfall 1: Taxonomy collapse from a broad seed
**What goes wrong:** With a ~8-10 entry seed (D-04), the agent reuses a "close enough" `job_type`
instead of minting a specific one — 12/16 markers collapsed onto `generation` in `260514-nfb`.
**Why it happens:** Lookup-heavy prompt framing makes the model treat the seed as an enum.
**How to avoid:** Strong mint-first framing — "mint a specific type when nothing fits *well*",
concrete good (`weekly_dependency_upgrade`) vs bad (`generation`) examples, and explicit
"fragmentation is recoverable; a bland label is permanent attribution loss" pressure. The v1.0
fix is documented in `task-taxonomy.md:74-87` ("Mint policy") — reuse that prose shape.
**Warning signs:** A Revenium dashboard where most spend lands under 2-3 generic `job_type`s.

### Pitfall 2: Halt-anchor dilution
**What goes wrong:** Adding a JOB DECLARATION section grows `SKILL.md` (already ~21KB); under
context compression the halt anchor gets summarized and the agent answers the user instead of
halting.
**Why it happens:** `SKILL.md` is delivered via a compressible `skill_view()` tool result, not a
system prompt (`halt-survivability.md:9-12`).
**How to avoid:** Keep the JOB DECLARATION section as a *sibling* after TASK CLASSIFICATION (not
above the halt block); keep the rewritten halt block tight; run the 4-run halt-survivability
matrix as the release gate. `test_prompt_ordering_invariant` already pins halt-anchor < classify-
anchor ordering — keep the new section below both.
**Warning signs:** Any halt-survivability run FAILs.

### Pitfall 3: Eager over-claiming SUCCESS
**What goes wrong:** D-06 eager declaration + a weak SUCCESS bar → the agent declares `SUCCESS`
on "I made the change" without verification.
**Why it happens:** Eager declaration fires at the turn the agent *believes* the goal is met;
belief ≠ verified evidence.
**How to avoid:** D-12-OUT — `SUCCESS` requires positive checkable evidence the agent itself
established that turn. Spell the bar out with examples: "wrote the fix but didn't run the tests"
→ `CANCELLED`, not `SUCCESS`.
**Warning signs:** Jobs marked `SUCCESS` whose marker arc shows no test/build activity.

### Pitfall 4: Positional-attribution leakage across abandoned arcs
**What goes wrong:** User pivots to a new goal before the old arc was declared; the old arc's task
markers get swallowed into the next job by positional attribution (Phase 7 D-08).
**Why it happens:** Phase 7 attribution is delimiter-based — a job marker claims everything above
it back to the previous job marker.
**How to avoid:** D-07 — on a genuine pivot, write a `CANCELLED` job marker for the abandoned arc
*before* starting the new one. This is the same CANCELLED-marker mechanism as the halt path.
**Warning signs:** A job's token total dwarfs its declared scope.

### Pitfall 5: Halt marker breaking the halt-survivability gate silently
**What goes wrong:** The halt block now makes one tool call; if the runbook isn't amended in the
same plan, the gate's "Call no tools" criterion will FAIL every run and block the release.
**Why it happens:** D-14 changes the contract; the runbook is the contract's test.
**How to avoid:** Make the `halt-survivability.md` amendment a non-optional task in the same plan
as the `SKILL.md` halt-block rewrite. Pass criterion → "exactly one tool call permitted (the
mandated CANCELLED marker write); verbatim halt string still fires; no other tools, no data
fetch, no answering the question."
**Warning signs:** Runbook still says "Call no tools" after the `SKILL.md` edit.

### Pitfall 6: bash 3.2 on the live host (carry-forward)
**What goes wrong:** Not a direct Phase 8 risk (no new bash), but `setup-local.sh` edits run on
the Mac Studio at bash 3.2.57. Any new shell in the seed-copy block must be 3.2-safe.
**How to avoid:** The existing `setup-local.sh` copy idiom (`cp` + `[[ ! -f ]]`) is already 3.2-
safe — mirror it exactly; do not introduce bash 4 syntax. STATE.md mandates live-host validation.

## Code Examples

### Job marker JSONL line (Phase 7 D-03 frozen shape — emit verbatim)
```json
{"kind":"job","ts":1747300000.12,"sid":"abc123","agentic_job_id":"pr-review-fc7a","job_name":"Review PR #42","job_type":"code_review","status":"SUCCESS"}
```
Reader-required keys (Phase 7 D-04): `kind`, `agentic_job_id`, `job_type`, `status`. A line missing
any of these is dropped by the cron — the snippet must always emit all four. `job_name`, `ts`,
`sid` are optional but should be emitted (the v1.0 task snippet always emits `ts`/`sid`).

### Degraded-deterministic halt marker (D-15)
```json
{"kind":"job","ts":1747300000.12,"sid":"abc123","agentic_job_id":"budget-halt-9c3e","job_name":"Arc interrupted by budget halt","job_type":"interrupted","status":"CANCELLED"}
```
`agentic_job_id` = `budget-halt-` + `secrets.token_hex(2)`; `job_type` = `interrupted` (consider
seeding this entry in `job-taxonomy.json` so it is not a fresh mint); `status` = `CANCELLED` fixed.

### Seed `job-taxonomy.json` shape (mirrors `task-taxonomy.json`)
```json
{
  "labels": {
    "feature_development": {
      "description": "Building a new capability or feature end to end",
      "examples": ["add OAuth login", "implement the export endpoint"]
    },
    "bug_fix": {
      "description": "Diagnosing and correcting a defect in existing behavior",
      "examples": ["fix the crash on empty input", "the totals are wrong"]
    }
  }
}
```
Same `{"labels": {label: {description, examples}}}` schema as `task-taxonomy.json`; same
`^[a-z][a-z0-9_]{1,47}$` label regex; same blocklist discipline (no `ack`/`greeting`/etc.).
~8-10 entries per D-04 — exact list is planner discretion.

### Seed→live copy block for `setup-local.sh` (mirror lines 14-22)
```bash
# Source: examples/setup-local.sh:14-22 — parallel block for job-taxonomy.json
JOB_TAXONOMY_DEST="${REVENIUM_JOB_TAXONOMY_FILE:-${STATE_DIR_DEFAULT}/job-taxonomy.json}"
if [[ ! -f "${JOB_TAXONOMY_DEST}" ]]; then
  cp "${REPO_ROOT}/skills/revenium/job-taxonomy.json" "${JOB_TAXONOMY_DEST}"
  echo "Seeded ${JOB_TAXONOMY_DEST}"
else
  echo "Job taxonomy already exists at ${JOB_TAXONOMY_DEST}, not overwriting"
fi
```

## State of the Art

| Old (v1.0 / Phase 7) | Current (Phase 8) | When Changed | Impact |
|----------------------|-------------------|--------------|--------|
| `JOB_TAXONOMY_FILE` declared but "unused in v1.1" (Phase 7 D-15) | Activated — agent-side reader/writer added | Phase 8 (D-03) | Pull v2 `JOBTAX-01` into v1.1 scope; amend Phase 7 D-15 note. |
| DECLARE-04: "closed seed vocabulary" | LLM-minted reuse-first against a live taxonomy | Phase 8 (D-01) | Reword DECLARE-04 + ROADMAP SC2 at phase transition. |
| HALT CHECK block: "Do NOT make any tool calls" | Exactly one mandated `execute_code` marker-write permitted | Phase 8 (D-14) | `halt-survivability.md` pass criterion changes in lockstep. |
| Markers were only `kind`-absent task lines | `markers/<sid>.jsonl` now also carries `kind:"job"` lines | Phase 7 D-01 (schema) / Phase 8 (agent emits them) | Cron reader already `kind`-aware (Phase 7 D-06). |

**Deprecated/outdated:** Phase 7 D-15's "no reader or writer until v2 `JOBTAX-01`" — superseded
by D-03. The planner must flag this for the Phase 7 context/REQUIREMENTS update.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | A standalone first-run/install copy of `job-taxonomy.json` outside `setup-local.sh` is not strictly required — `setup-local.sh` is the v1.0 seed-copy mechanism and `task-taxonomy.json` has no other copy path. | Standard Stack / Code Examples | If v1.0 also seeds the taxonomy via `install-cron.sh` or a SKILL.md setup step, the planner must mirror that path too. Verified: `install-cron.sh` does NOT copy `task-taxonomy.json`; only `setup-local.sh:14-22` does. Low risk. |
| A2 | A parallel `references/job-taxonomy.md` reference doc is optional, not mandatory. | Recommended Structure | CONTEXT D-04 says "mirror the v1.0 machinery and `references/task-taxonomy.md` schema" — this can be satisfied by reusing `task-taxonomy.md`'s rules in-prompt without a new doc. Planner discretion; low risk. |
| A3 | `token_hex(2)` (4 hex chars) is the intended suffix length, matching the `fc7a` example. | Pattern 2 | Phase 7 D-03 and CONTEXT D-05 both show 4-char suffixes (`fc7a`). If a longer suffix is wanted the snippet trivially changes. Low risk. |
| A4 | Seeding an `interrupted` entry in `job-taxonomy.json` for the halt path is desirable so D-15's degraded marker does not trigger a fresh mint on the halt turn. | Code Examples | If the planner prefers the halt `job_type` to be a non-taxonomy literal, that is also valid (the cron passes `job_type` through unchanged). Low risk, planner discretion. |

## Open Questions

1. **Does any install path other than `setup-local.sh` need the seed→live copy?**
   - What we know: `setup-local.sh:14-22` is the only place `task-taxonomy.json` is copied to
     state. `install-cron.sh` does not copy it. `SKILL.md` setup flow does not copy it.
   - What's unclear: whether the project intends `install-cron.sh` or a SKILL.md first-run step
     to also seed taxonomies on a non-`setup-local` install.
   - Recommendation: mirror `setup-local.sh` exactly (A1). If the planner wants belt-and-suspenders
     coverage, an idempotent no-clobber copy could also be added to `install-cron.sh` — but that
     would be a new behavior not present for `task-taxonomy.json` and arguably out of scope.

2. **Should the halt-path `job_type` (`interrupted`) be a seeded taxonomy entry or a bare literal?**
   - What we know: the cron passes `job_type` through unchanged; D-15 wants a near-fixed snippet.
   - What's unclear: purely a consistency preference.
   - Recommendation: seed `interrupted` in `job-taxonomy.json` (A4) so the halt snippet never has
     to touch the taxonomy file at all — minimal reasoning load on the halt turn (D-15 intent).

3. **Does Hermes propagate `HERMES_SESSION_ID` to `execute_code` on the halt turn?**
   - What we know: the v1.0 session-id ladder falls back to newest-jsonl then a pseudo-id
     (`SKILL.md:328-342`); a pseudo-id marker is not cron-attributable.
   - What's unclear: nothing new — the job snippet inherits the exact same ladder and the exact
     same caveat. This is not a Phase 8 regression, just an inherited limitation.
   - Recommendation: copy the ladder verbatim; do not attempt to "fix" it in Phase 8.

## Environment Availability

Step 2.6: SKIPPED — Phase 8 is a code/config/docs-only change (edit `SKILL.md`, ship a JSON seed,
amend a reference doc, edit `setup-local.sh` and a test). No external runtime tools, services, or
dependencies are introduced. The runtime tools the *skill* uses (`python3`, `sqlite3`, `revenium`,
`cron`) are unchanged and already covered by v1.0.

## Runtime State Inventory

Phase 8 ships a new seed file and activates a state path. This is not a rename/migration, but the
seed→live activation has a state dimension worth pinning:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `markers/<sid>.jsonl` gains `kind:"job"` lines (append-only; same file as task markers). No existing data is rewritten. | None — purely additive (Phase 7 D-01). |
| Live service config | None — Phase 8 touches no Revenium/cron/OS config. | None — verified by phase boundary (CONTEXT domain). |
| OS-registered state | None — no cron change, no Task Scheduler / launchd touch. | None — `install-cron.sh` is unchanged. |
| Secrets/env vars | `REVENIUM_JOB_TAXONOMY_FILE` override already declared (`common.sh:25`); no new secret. | None. |
| Build artifacts | New seed `skills/revenium/job-taxonomy.json` ships with the skill; copied to `~/.hermes/state/revenium/job-taxonomy.json` on fresh install. Existing installs with no live file get it on next `setup-local.sh`; existing installs that never re-run setup will have the agent read a *missing* live taxonomy. | The JOB DECLARATION snippet must fail-open if `JOB_TAXONOMY_FILE` is absent — treat as an empty taxonomy and mint freely (mirror the classifier's missing-file fail-open). The planner should make this explicit. |

**Backward-compat note:** an install that never gets the seed copied (no re-run of `setup-local.sh`)
still meters byte-identically — the missing taxonomy only affects `job_type` reuse, and a job-less
session is unaffected entirely. The fail-open behavior is the safety net.

## Validation Architecture

`workflow.nyquist_validation` is not disabled in `.planning/config.json` for this repo's GSD
setup, so validation applies. **Important:** this phase has *two* validation surfaces — the
automated `tests/test_repository.py` harness, and the *manual* halt-survivability runbook.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Python stdlib `unittest` |
| Config file | none — discovery-based |
| Quick run command | `python3 -m unittest tests.test_repository.RepositoryTests.test_expected_files_exist tests.test_repository.RepositoryTests.test_prompt_ordering_invariant -v` |
| Full suite command | `python3 -m unittest discover -s tests -p 'test_*.py' -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DECLARE-01 | `## FINAL ACTION — JOB DECLARATION` section exists in `SKILL.md`, after the halt + classify anchors | unit (string presence + ordering) | `python3 -m unittest tests.test_repository.RepositoryTests.test_prompt_ordering_invariant -v` | ⚠️ existing test pins halt<classify; **extend** to also pin the new anchor below classify (Wave 0) |
| DECLARE-02 | `agentic_job_id` minting prose present | manual (prompt review) | — | ❌ prompt-quality, not test-pinnable; review-only |
| DECLARE-03 | arc-boundary definition prose present | manual (prompt review) | — | ❌ prompt-quality; review-only |
| DECLARE-04 | `skills/revenium/job-taxonomy.json` ships with valid schema | unit | `python3 -m unittest tests.test_repository.RepositoryTests.test_expected_files_exist -v` + a new `test_job_taxonomy_file_schema` | ❌ Wave 0 — add `job-taxonomy.json` to the `expected` list (`test_repository.py:56-84`) and add a schema test mirroring `test_taxonomy_file_schema` (`test_repository.py:139-160`) |
| DECLARE-05 | conservative-outcome criteria prose present | manual (prompt review) | — | ❌ prompt-quality; review-only |
| DECLARE-06 | halt block writes a `CANCELLED` marker before the halt string; runbook amended | manual (halt-survivability runbook) | — | ❌ manual 4-run matrix in `halt-survivability.md` |
| (regression) | v1.0 task markers / argv unchanged; no legacy branding; runtime paths native | unit | `python3 -m unittest discover -s tests -p 'test_*.py' -v` | ✅ `test_marker_file_schema`, `test_no_legacy_branding_left`, `test_runtime_paths_are_hermes_native`, `test_shell_scripts_have_valid_syntax` already exist |

### Sampling Rate
- **Per task commit:** `python3 -m unittest tests.test_repository.RepositoryTests.test_expected_files_exist tests.test_repository.RepositoryTests.test_prompt_ordering_invariant -v` (plus the new `test_job_taxonomy_file_schema` once added).
- **Per wave merge:** `python3 -m unittest discover -s tests -p 'test_*.py' -v` — full suite green.
- **Phase gate:** Full suite green **and** the manual halt-survivability runbook re-passes all
  4 runs (2 session lengths × 2 model families) against the amended pass criterion. This is the
  STATE.md-mandated operator gate for any `SKILL.md` change and is non-negotiable for release.

### Wave 0 Gaps
- [ ] `tests/test_repository.py` — add `skills/revenium/job-taxonomy.json` to the `expected` list
  in `test_expected_files_exist` (`test_repository.py:56-84`). Without this, the new file is not
  presence-enforced.
- [ ] `tests/test_repository.py` — add `test_job_taxonomy_file_schema`, mirroring
  `test_taxonomy_file_schema` (`test_repository.py:139-160`): assert `labels` dict, every key
  matches `^[a-z][a-z0-9_]{1,47}$`, no blocklisted labels, each descriptor has `description` +
  `examples`.
- [ ] `tests/test_repository.py` — *consider* extending `test_prompt_ordering_invariant` to also
  assert the `FINAL ACTION — JOB DECLARATION` anchor exists and sits after the classify anchor
  (keeps the halt anchor dominant — Pitfall 2).
- [ ] No framework install needed — stdlib `unittest` is already the harness.
- [ ] The halt-survivability runbook is a *manual* plan — there is no automated test for
  DECLARE-06's runtime behavior. The Wave 0 "gap" is procedural: the plan must schedule the
  4-run matrix and the runbook amendment as explicit tasks.

*Note: DECLARE-02/03/05 are prompt-quality requirements — there is no honest unit test for "the
arc-boundary prose is good". These are verified by review against the CONTEXT decisions and by the
halt-survivability behavioral test for the halt-path subset. The plan should not invent brittle
string-grep tests for prose quality.*

## Security Domain

`security_enforcement` is not disabled in config, so this section is included.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface — agent-side prompt + local file. |
| V3 Session Management | no | "Session" here is a Hermes session jsonl; no credentials. |
| V4 Access Control | no | No access-control surface. |
| V5 Input Validation | yes | The minted `job_type` is normalized to `^[a-z][a-z0-9_]{1,47}$` before being written / persisted (mirror `task-taxonomy.md` `mint_label` regex normalization). `agentic_job_id` / `job_name` are written as JSON strings via `json.dumps` — no injection into the marker file. |
| V6 Cryptography | no (entropy only) | `secrets.token_hex` is used for non-security entropy (id uniqueness), not for a security boundary. Stdlib `secrets` is the correct choice anyway — never `random`. |

### Known Threat Patterns for {Bash + Python heredoc + JSONL marker file}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed `job_type` (hyphens, unicode, overlong) corrupting the live taxonomy | Tampering | Normalize + regex-validate before persist (`task-taxonomy.md:103-108` pattern); reject on failure. |
| Partial read of the live taxonomy by a concurrent agent turn | Tampering / DoS | `flock` + write-to-tmp + `os.rename` atomic-replace (`task-taxonomy.md:100-126`). |
| Torn / oversized JSONL marker line | Tampering | Phase 7 reader already skips malformed/oversized lines; the job snippet writes one compact `json.dumps(...,separators=(",",":"))` line — keep it well under the 1024-byte budget (`test_marker_file_schema`). |
| Path traversal via a crafted session id | Tampering | The session-id ladder derives from a real jsonl basename or a `pseudo-<ts>` literal — no user-controlled path component. Unchanged from v1.0; no new exposure. |
| Marker file permission leak | Information Disclosure | `markers/` is created `mode=0o700` (`SKILL.md:345`); `install-cron.sh` `chmod 700`s it. Job markers inherit this — no new control needed. |

No new threat surface: Phase 8 writes one additional line shape to an already-existing,
already-permission-controlled local file and reads/writes one additional local JSON file using
the already-proven atomic pattern. There is no network, no credential, and no privilege boundary.

## Project Constraints (from CLAUDE.md)

The planner must verify the plan honors every directive below — these have the same authority as
locked CONTEXT decisions.

- **No new runtime dependencies.** Everything must be stdlib Python or POSIX sh. The JOB
  DECLARATION snippet uses only `fcntl, json, os, secrets, time, re, tempfile` — all stdlib.
- **State-path discipline.** New state paths live only in `common.sh`. `JOB_TAXONOMY_FILE` is
  already there (Phase 7 D-13) — Phase 8 declares NO new path. `test_runtime_paths_are_hermes_native`
  enforces this.
- **No writes to `state.db`.** Phase 8 writes only to `markers/<sid>.jsonl` and the live
  `job-taxonomy.json` — both under `~/.hermes/state/revenium/`. Compliant.
- **Tap discoverability.** The skill stays at `skills/revenium/`; the new seed
  `skills/revenium/job-taxonomy.json` sits beside `task-taxonomy.json`. SKILL.md frontmatter
  (`name: revenium`, `metadata.hermes`, `category: devops`) is untouched —
  `test_skill_frontmatter_has_hermes_metadata` stays green.
- **Legacy branding guard.** `test_no_legacy_branding_left` greps every shipped `.md/.json/.sh/.py`
  file (excluding `.planning/`) for forbidden forked-tool names. The new `job-taxonomy.json`,
  `SKILL.md` edits, and `halt-survivability.md` amendment must contain none.
- **Idempotency.** Not a Phase 8 cron concern (no cron change), but the marker write is append-
  only and Phase 7 D-12 last-wins dedup absorbs a re-emitted job line — the prompt should still
  instruct "declare once at arc end", not re-declare.
- **Backward compatibility.** A job-less / marker-less session meters byte-identically to v1.0.
  The JOB DECLARATION section is additive; the v1.0 TASK CLASSIFICATION block (`SKILL.md:279-398`)
  must not be weakened or restructured.
- **Shell strictness.** `setup-local.sh` uses `set -euo pipefail`; the new seed-copy block must
  preserve that and stay bash 3.2-safe (live host is bash 3.2.57, STATE.md).
- **Halt-survivability gate.** Any release modifying `SKILL.md` must re-pass the 4-run
  halt-survivability matrix — and for Phase 8 the runbook itself is amended (D-14).

## Sources

### Primary (HIGH confidence — direct in-repo read, 2026-05-15)
- `skills/revenium/SKILL.md` — HALT CHECK block (lines 24-46), Budget Check Procedure (48-88),
  FINAL ACTION — TASK CLASSIFICATION block including the `execute_code` snippet (279-398).
- `skills/revenium/references/task-taxonomy.md` — taxonomy schema, normalization regex, mint
  policy, atomic write pattern (full file).
- `skills/revenium/references/halt-survivability.md` — pass criterion, 4-run test matrix (full file).
- `skills/revenium/scripts/common.sh` — `JOB_TAXONOMY_FILE` declaration at line 25, path idiom.
- `skills/revenium/task-taxonomy.json` — v1.0 seed file (the schema template).
- `examples/setup-local.sh` — seed→live copy block (lines 14-22).
- `tests/test_repository.py` — `test_expected_files_exist`, `test_skill_frontmatter_has_hermes_metadata`,
  `test_no_legacy_branding_left`, `test_runtime_paths_are_hermes_native`, `test_taxonomy_file_schema`,
  `test_marker_file_schema`, `test_prompt_ordering_invariant` (lines 56-344).
- `.planning/phases/08-job-declaration-prompt-block/08-CONTEXT.md` — D-01..D-16, canonical refs.
- `.planning/phases/07-job-marker-schema-state-scaffolding/07-CONTEXT.md` — frozen `kind:"job"`
  shape (D-03), reader-required keys (D-04), positional attribution (D-08), `JOB_TAXONOMY_FILE`
  declaration (D-13), "unused in v1.1" note (D-15, superseded).
- `.planning/REQUIREMENTS.md` — DECLARE-01..06; `JOBTAX-01` (v2, pulled into v1.1 by D-03).
- `.planning/ROADMAP.md` §Phase 8 — goal + 4 success criteria (SC2 amended by D-01).
- `.planning/STATE.md` — Phase 8 research flags, the SKILL.md operator gate, live-host mandate.
- `CLAUDE.md` — project constraints, state-path discipline, halt gate, branding guard.

### Secondary / Tertiary
- None — this is an internal-codebase phase; no external documentation or web sources were needed.

## Metadata

**Confidence breakdown:**
- Standard stack / reusable assets: HIGH — every primitive verified by direct file read; the
  TASK CLASSIFICATION block is a near-complete template.
- Architecture / patterns: HIGH — Phase 7 froze the marker shape; the v1.0 block supplies the
  structure; CONTEXT D-14/D-15 give explicit recommendations.
- Pitfalls: HIGH — the `260514-nfb` collapse and halt-dilution risks are documented in-repo
  (`task-taxonomy.md`, `halt-survivability.md`).
- Validation: HIGH for the automated harness; the manual halt-survivability runbook is inherently
  a judgement test — flagged as such.

**Research date:** 2026-05-15
**Valid until:** 2026-06-14 (stable — internal codebase; only changes if Phases 9/10 reshape the
marker contract, which the phase boundaries explicitly prevent).
