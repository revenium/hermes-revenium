# Job Declaration — Operational Detail

This file holds the full operational detail for the `## FINAL ACTION — JOB DECLARATION` step in `SKILL.md`. Refer here for arc-boundary rules, the SUCCESS/FAILED/CANCELLED criteria, the anti-collapse label examples, and worked examples. The `write_job_marker` snippet itself remains in `SKILL.md`.

## Arc definition (goal-continuity rule)

**Same arc:** the same goal, including follow-up fixes, refinements, and corrections of that goal. Example: "the tests fail" sent after "implement X" is still arc X — X is not done until it works. Do NOT declare the job at "implement X" if you know verification is still needed.

**New arc:** a goal that is NOT a continuation of the current one — a genuine topic pivot, a new unrelated request.

**On a genuine pivot before the current arc was declared:** first write a `CANCELLED` job marker for the abandoned arc (prevents attribution leakage into the next job), then treat the new request as a fresh arc.

**Granularity floor:** at minimum, one job per session. A single-goal session produces one job; a multi-goal session produces multiple.

## Trigger (binary — no judgment calls)

Declare a job marker if ANY of these are true:
- You have just completed the goal the arc was working toward and you have self-verified the result (see SUCCESS bar below).
- The arc has definitively failed (the fix didn't fix, the build cannot pass, the goal is unachievable).
- The user has pivoted to a new goal before this arc was declared — write `CANCELLED` for the abandoned arc first.

**Skip the job marker ONLY when ALL of these are true:**
- Your entire turn was a trivial response (≤ 2 sentences, zero tools called).
- No arc was in progress at the start of this turn.

## Required action sequence

Before your final response yields back to the user:

**Step 1 — mint an `agentic_job_id`.** Compose a specific business-readable label describing what the arc actually did, then append `secrets.token_hex(2)` (4 hex chars) as an entropy suffix. Example: `pr-review-fc7a`, `fix-auth-race-3b1e`, `weekly-dep-upgrade-9a2c`.

**Anti-collapse rule (critical):** the label MUST be specific enough to be meaningful in a Revenium analytics dashboard. Bad: `task-a12f`, `work-b3c4`, `coding-9d1a`, `generation-4e5f`. Good: `refactor-db-pool-7c2a`, `add-pagination-endpoint-1f3b`. If you find yourself writing a generic label, stop and pick a more specific one. Fragmentation between `code_review` and `code-review` is permanent harm; a generic label is also permanent attribution loss.

**Step 2 — select a `job_type`.** Read the live taxonomy at `~/.hermes/state/revenium/job-taxonomy.json`. Reuse the closest-fitting existing `job_type`. Mint a new `^[a-z][a-z0-9_]{1,47}$` snake_case label ONLY if none fits well.

**Anti-collapse rule (critical):** same pressure as `agentic_job_id`. Bad `job_type` values: `generation`, `task`, `work`, `coding`, `general`. Good: `weekly_dependency_upgrade`, `database_schema_migration`, `pull_request_review`. Mint a specific type when nothing fits — fragmentation is recoverable, a bland label is permanent attribution loss.

If you mint a new `job_type`, persist it back to the live taxonomy atomically (flock + tmp file in same dir + fsync + rename) before writing the job marker.

**Step 3 — determine `status`.** Exactly one of: `SUCCESS`, `FAILED`, `CANCELLED` (uppercase).

- `SUCCESS` requires positive, checkable evidence YOU established in THIS turn: tests run and passed, build green, diff demonstrably correct, question fully answered. "I made the change but did not or could not verify it" is `CANCELLED`, not `SUCCESS`. No user sign-off required — self-verification is the bar.
- `FAILED` is narrow: a definitive negative terminal state — the fix didn't fix, the build cannot pass, the goal is objectively unachievable.
- `CANCELLED` is the catch-all and the uncertainty-bias target: abandoned, interrupted, superseded, or outcome genuinely uncertain. When in doubt, use `CANCELLED`.

**Step 4 — call `execute_code` with the `write_job_marker` snippet in `SKILL.md`.**

## Self-check before yielding

Immediately before yielding your final response, answer these three questions. If a job marker was required and you have not written it, call `execute_code` with the snippet in `SKILL.md` before sending your response.

1. Did I just complete, fail, or abandon the goal this arc was working toward? → if yes, a job marker is REQUIRED.
2. Did I self-verify the outcome (tests ran, build green, answer complete) before setting `status = "SUCCESS"`? → "I made the change but couldn't verify it" means `status = "CANCELLED"`.
3. Did I just call `execute_code` with `write_job_marker`? → if a marker was REQUIRED, YES is the only acceptable answer.

## Examples

**Example 1 — Arc complete, self-verified (SUCCESS):**
User asked you to add a pagination endpoint. You wrote the code, ran the test suite (all green), and the diff does what was asked.
- `agentic_job_id`: `add-pagination-endpoint-3b1e`
- `job_name`: "Add pagination to /api/users endpoint"
- `job_type`: `feature_development` (or mint `api_endpoint_development` if more specific)
- `status`: `SUCCESS` (tests ran and passed — self-verified)

**Example 2 — Arc complete but NOT verified (CANCELLED, not SUCCESS):**
User asked you to fix a bug. You wrote the fix but did not run the tests (no terminal access, or deferred to user).
- `status`: `CANCELLED` — you made the change but could not verify it. Do NOT set `SUCCESS` here. The user will verify; if they confirm it works, that is a separate arc.

**Example 3 — Arc definitively failed (FAILED):**
User asked you to make the CI pipeline green. After 3 attempts the underlying library has a known unresolved upstream bug that makes the goal objectively unachievable today.
- `agentic_job_id`: `fix-ci-upstream-blocker-9f2a`
- `job_type`: `debugging`
- `status`: `FAILED` (definitive negative terminal state — goal is unachievable)

**Example 4 — User pivot before arc declared (CANCELLED for abandoned arc):**
User asked you to refactor the auth module (arc in progress, not yet declared). Mid-arc, user says "actually forget that — help me write a release announcement."
- First: write a `CANCELLED` job marker for the abandoned refactor arc (`job_type`: `refactoring`, `status`: `CANCELLED`).
- Then: begin the new arc (release announcement writing).
- Reason: prevents the refactor's task markers from leaking attribution into the announcement arc.
