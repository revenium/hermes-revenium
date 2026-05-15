---
phase: 08-job-declaration-prompt-block
plan: "02"
subsystem: prompt-engineering
tags: [skill-md, job-declaration, halt-check, job-taxonomy, markers, prompt]

dependency_graph:
  requires:
    - phase: 08-01
      provides: skills/revenium/job-taxonomy.json seed with interrupted entry
    - phase: 07-job-marker-schema-state-scaffolding
      provides: frozen kind:"job" marker schema (D-03), reader-required keys (D-04), JOB_TAXONOMY_FILE path declared
  provides:
    - SKILL.md FINAL ACTION — JOB DECLARATION section (DECLARE-01..05)
    - Reconciled HALT CHECK block with mandated CANCELLED marker write (DECLARE-06)
    - halt-survivability.md amended pass criterion (exactly one mandated tool call)
    - test_prompt_ordering_invariant extended to pin halt < classify < job-declaration
  affects:
    - Phase 9 (cron jobs create) — agent now writes kind:"job" markers for cron to consume
    - Phase 10 (cron jobs outcome) — job markers carry status field cron needs
    - halt-survivability manual test matrix (Task 4 checkpoint gate)

tech-stack:
  added: []
  patterns:
    - "Goal-continuity arc-boundary rule: same arc = same goal including follow-up fixes; new arc = unrelated goal"
    - "Degraded-deterministic halt marker: fixed shape (budget-halt-<hex>, interrupted, CANCELLED) — no taxonomy read on halt path (D-15)"
    - "Fail-open taxonomy read: os.path.exists guard + try/except so absent job-taxonomy.json yields empty taxonomy, mints freely"
    - "Atomic job_type mint-persist: flock + tmp-in-same-dir + fsync + rename (mirrors task-taxonomy.md atomic write)"
    - "Mint-first anti-collapse framing: concrete good/bad examples for both agentic_job_id and job_type"

key-files:
  created: []
  modified:
    - skills/revenium/SKILL.md
    - skills/revenium/references/halt-survivability.md
    - tests/test_repository.py

key-decisions:
  - "D-14: Mandated single first-step halt contract — rewrite halt block so halted turn does exactly: (1) one execute_code CANCELLED marker write if arc in progress, (2) verbatim halt string — nothing else"
  - "D-15: Degraded-deterministic halt marker — budget-halt-<hex> agentic_job_id, interrupted job_type (bare literal), no taxonomy read on halt path"
  - "D-16: Arc-in-progress guard — halt marker written only if an undeclared arc was active; idle sessions skip the marker write (no phantom jobs)"
  - "Comment reference to job anchor anchor string in HALT CHECK snippet caused test ordering failure (classify idx > job idx); fixed by rewording comment to avoid the anchor literal"

patterns-established:
  - "Job marker section mirrors TASK CLASSIFICATION 5-part structure: framing, trigger, required sequence, execute_code snippet, self-check, examples"
  - "HALT CHECK + halt-survivability.md amended in lockstep — stale runbook is a release blocker (Pitfall 5)"

requirements-completed: [DECLARE-01, DECLARE-02, DECLARE-03, DECLARE-04, DECLARE-05, DECLARE-06]

duration: ~6min
completed: "2026-05-15"
---

# Phase 8 Plan 02: Job Declaration Prompt Block Summary

**`SKILL.md` gains a complete `## FINAL ACTION — JOB DECLARATION` section with goal-continuity arc rules, write_job_marker() snippet, fail-open taxonomy reuse-or-mint, conservative SUCCESS/FAILED/CANCELLED outcome criteria, and a reconciled HALT CHECK block that writes exactly one degraded-deterministic CANCELLED marker before the verbatim halt string**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-05-15T17:59:31Z
- **Completed:** 2026-05-15T18:05:20Z
- **Tasks:** 3 (Tasks 1-3; Task 4 is a checkpoint gate awaiting human verification)
- **Files modified:** 3

## Accomplishments

- Added `## FINAL ACTION — JOB DECLARATION` as a sibling section after `## FINAL ACTION — TASK CLASSIFICATION` — covers DECLARE-01..05: retrospective once-at-arc-end declaration, mint-first agentic_job_id, reuse-or-mint job_type against live taxonomy, goal-continuity arc boundaries, conservative outcome criteria
- Rewrote `## ABSOLUTE FIRST — HALT CHECK` to the mandated-single-first-step contract (D-14/D-15/D-16): exactly one execute_code CANCELLED marker write when arc in progress, then verbatim halt string — nothing else; verbatim halt string template byte-identical
- Amended `halt-survivability.md` in lockstep: "Call no tools" → "exactly one mandated tool call"; updated both Scenario 1 and Scenario 2 per-scenario PASS/FAIL steps
- Extended `test_prompt_ordering_invariant` to assert halt < classify < job-declaration ordering (Pitfall 2 guard)
- All 48 tests passing; full suite green

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add FINAL ACTION — JOB DECLARATION section | 0a65bdd | skills/revenium/SKILL.md |
| 2 | Rewrite HALT CHECK + amend halt-survivability.md | 401ded8 | skills/revenium/SKILL.md, skills/revenium/references/halt-survivability.md |
| 3 | Extend test_prompt_ordering_invariant | 079d75c | tests/test_repository.py, skills/revenium/SKILL.md (comment fix) |
| 4 | Checkpoint: halt-survivability 4-run matrix | — | Awaiting human verification |

## Files Created/Modified

- `skills/revenium/SKILL.md` — Added `## FINAL ACTION — JOB DECLARATION` section (169 lines); rewrote `## ABSOLUTE FIRST — HALT CHECK` block with mandated CANCELLED marker write; fixed comment that accidentally referenced the job anchor before the classify anchor
- `skills/revenium/references/halt-survivability.md` — Amended pass criterion from "Call no tools" to "exactly one mandated tool call"; updated Scenario 1 and 2 PASS/FAIL steps to match
- `tests/test_repository.py` — Extended `test_prompt_ordering_invariant` with job_anchor assertion and classify < job ordering check

## Decisions Made

- **D-14 enacted:** Mandated single first-step approach for halt block — agent's halted turn does exactly two things: (1) one execute_code CANCELLED marker write (arc-in-progress only), (2) verbatim halt string. The halt string remains the dominant step-2 anchor.
- **D-15 enacted:** Degraded-deterministic halt marker uses fixed-shape snippet (budget-halt-<hex>, interrupted, CANCELLED) — no taxonomy read on halt path, minimal reasoning load.
- **D-16 enacted:** Arc-in-progress guard in halt block — idle sessions and already-declared arcs skip the marker write; no phantom job markers.
- **Comment ordering fix:** The HALT CHECK snippet originally contained `# Session id resolution (same ladder as FINAL ACTION — JOB DECLARATION above)`. This made the first occurrence of the "FINAL ACTION — JOB DECLARATION" string appear before "FINAL ACTION — TASK CLASSIFICATION" in the file, causing `test_prompt_ordering_invariant` to fail with classify_idx (15488) > job_idx (2143). Fixed by rewording comment to "same 3-tier ladder as the job-declaration section below".

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed HALT CHECK comment containing job anchor string ahead of TASK CLASSIFICATION section**
- **Found during:** Task 3 (extending test_prompt_ordering_invariant)
- **Issue:** The HALT CHECK block's snippet comment said "same ladder as FINAL ACTION — JOB DECLARATION above" — the anchor string appeared at position 2143 in the file (inside the HALT CHECK block), while "FINAL ACTION — TASK CLASSIFICATION" appears at 15488. The new test assertion `classify_idx < job_idx` failed: 15488 is not less than 2143.
- **Fix:** Rewrote comment to "same 3-tier ladder as the job-declaration section below" — avoids the anchor literal in the HALT CHECK context
- **Files modified:** skills/revenium/SKILL.md
- **Verification:** `python3 -c "t=open(...); print(t.index('FINAL ACTION — TASK CLASSIFICATION') < t.index('FINAL ACTION — JOB DECLARATION'))"` → True
- **Committed in:** 079d75c (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug in anchor ordering caused by comment text)
**Impact on plan:** Required fix; without it the TDD RED→GREEN cycle would have silently shipped a broken test. No scope creep.

## Deviations to reconcile at phase transition

**D-01 — `job_type` is LLM-minted reuse-first, NOT a closed seed enum:**
DECLARE-04 ("selects each job's type from a closed seed vocabulary") and ROADMAP Phase 8 Success Criterion 2 ("closed seed vocabulary") were superseded by the user-explicit choice to mirror v1.0 task_type's LLM-first minting approach. These must be reworded at `/gsd-transition`:
- DECLARE-04: reword to "mints job_type LLM-first, reuse-first against a live job-taxonomy"
- ROADMAP Phase 8 SC2: reword "closed seed vocabulary" → "live reuse-or-mint taxonomy"

**D-03 — Phase 7 D-15's "JOB_TAXONOMY_FILE unused in v1.1" note is superseded:**
Phase 7 D-15 declared `JOB_TAXONOMY_FILE` but said "unused in v1.1 — no reader or writer until v2 JOBTAX-01." Phase 8 activates it: the JOB DECLARATION block reads the live taxonomy and atomically persists newly-minted job_types back. At `/gsd-transition`:
- Amend Phase 7 D-15's note to: "activated by Phase 8 agent-side reader/writer"
- Pull v2 `JOBTAX-01` (job-type taxonomy file) into v1.1 scope as a Phase 8 deliverable

## Issues Encountered

- TDD RED phase was structurally unusual: Task 1 (adding the JOB DECLARATION section) is a prerequisite of Task 3 (the TDD test extension), so the test could not fail "before" the implementation in the classic TDD sense. However, a genuine RED was achieved organically: the initial test extension did fail (ordering invariant violated due to comment anchor text), and the bug was fixed before the GREEN commit. This satisfies the TDD contract.

## User Setup Required

None — all changes are to static skill assets. The halt-survivability 4-run matrix (Task 4 checkpoint) requires manual testing on a live Hermes install.

## Next Phase Readiness

- SKILL.md carries complete JOB DECLARATION section and reconciled HALT CHECK block
- Task 4 (halt-survivability 4-run matrix) is the blocking release gate before proceeding
- After Task 4 passes: Phase 9 (cron jobs create) can begin consuming the kind:"job" markers the agent now writes
- ROADMAP.md and REQUIREMENTS.md need D-01/D-03 reconciliation at phase transition (documented above)

## Threat Surface Scan

No new threat surface beyond the plan's threat model (T-08-04 through T-08-10). No new network endpoints, auth paths, or schema changes introduced. The SKILL.md additions are prompt-only content within the existing `skill_view()` delivery mechanism (T-08-07 mitigated by section placement, ordering test, and Task 4 gate).

## Known Stubs

None. The JOB DECLARATION execute_code snippet uses placeholder variable names (`replace-with-step1-label-`, `replace_with_step2_type`) that agents are instructed to substitute — this is intentional prompt instructional scaffolding, not a data stub affecting functionality.

## Post-checkpoint deviation

**Live validation on Mac Studio host (2026-05-15) found that both job-marker snippets bound the session id via broken auto-detection.**

- **Root cause:** The 3-tier session-id ladder in both the HALT CHECK and JOB DECLARATION `execute_code` snippets was broken in two ways: (1) `execute_code` on the Hermes host does not receive a `HERMES_SESSION_ID` env var, so tier 1 always falls through; (2) the `*.jsonl` glob in `~/.hermes/sessions/` matches only legacy session files — current Hermes writes transcripts as `session_<id>.json`, so the glob always matched stale files from a previous session and silently mis-attributed every job marker to the wrong session. Live proof: a job for session `20260515_162310_593b86` was written into `20260515_141331_1350d1b1.jsonl` (a stale session). This is a Core Value violation (job→session attribution broken).
- **Fix:** Both the HALT CHECK snippet and the JOB DECLARATION snippet were updated to replace the broken 3-tier ladder with a single explicit agent-substituted `session_id = "REPLACE_WITH_YOUR_SESSION_ID"` placeholder and a fail-loud guard (`raise SystemExit(...)`) that prevents execution if the placeholder is left unsubstituted. The agent is directed to copy its session id from the `Session ID:` line in its system prompt. The TASK CLASSIFICATION snippet received the same cleanup (removing the broken env/filesystem fallbacks, replaced with a stable `HERMES_CLASSIFICATION_SESSION_ID` env var read with a timestamp fallback, since that snippet is handled by the mechanical plugin hook and not agent-substituted).
- **Instruction text updated:** Both instruction paragraphs for the HALT CHECK and JOB DECLARATION steps were updated to direct the agent to substitute its session id before calling `execute_code`.
- **Regression test:** `test_job_marker_snippets_bind_explicit_session_id` added to `tests/test_repository.py` — pins that neither `os.environ.get("HERMES_SESSION_ID")` nor `os.listdir(sessions_dir)` appear anywhere in `SKILL.md`, and that exactly 2 occurrences of the explicit `REPLACE_WITH_YOUR_SESSION_ID` placeholder and guard string are present (one in HALT CHECK, one in JOB DECLARATION).
- **Test count:** 48 → 49 (all passing).
- **Commit:** fix(08-02): bind job markers to explicit agent-supplied session id

## Self-Check: PASSED

- [x] `skills/revenium/SKILL.md` contains `## FINAL ACTION — JOB DECLARATION`: FOUND
- [x] `skills/revenium/SKILL.md` TASK CLASSIFICATION index < JOB DECLARATION index: CONFIRMED (15492 < 22693)
- [x] `skills/revenium/SKILL.md` does NOT contain "Do NOT make any tool calls": CONFIRMED
- [x] `skills/revenium/SKILL.md` contains "budget-halt-": CONFIRMED
- [x] `skills/revenium/references/halt-survivability.md` does NOT contain "Call **no tools**": CONFIRMED
- [x] `halt-survivability.md` contains "exactly one": CONFIRMED
- [x] `tests/test_repository.py` contains `job_anchor = 'FINAL ACTION — JOB DECLARATION'`: CONFIRMED
- [x] Commit 0a65bdd exists: CONFIRMED
- [x] Commit 401ded8 exists: CONFIRMED
- [x] Commit 079d75c exists: CONFIRMED
- [x] All 48 tests pass: CONFIRMED
