# Job Declaration — Inference Criteria

As of Phase 13, job markers (`kind:"job"`) are written automatically by the
`revenium-classifier` plugin at session end — it infers the job arc(s) from
session data without agent involvement. This document describes the criteria
the plugin's inference uses. Refer here only in the rare backstop case where
the SKILL.md `## FINAL ACTION — JOB DECLARATION` section applies.

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

## Status criteria

Exactly one of: `SUCCESS`, `FAILED`, `CANCELLED` (uppercase).

- `SUCCESS` requires positive, checkable evidence established in the session: tests run and passed, build green, diff demonstrably correct, question fully answered. "I made the change but did not or could not verify it" is `CANCELLED`, not `SUCCESS`. No user sign-off required — self-verification is the bar.
- `FAILED` is narrow: a definitive negative terminal state — the fix didn't fix, the build cannot pass, the goal is objectively unachievable. For a `FAILED` arc, also set `failure_reason` to a brief plain-text cause (e.g. "tests failed: 3 assertion errors in auth module"). The cron forwards it to Revenium as `--metadata` on the job outcome. Omit `failure_reason` for `SUCCESS` and `CANCELLED`.
- `CANCELLED` is the catch-all and the uncertainty-bias target: abandoned, interrupted, superseded, or outcome genuinely uncertain. When in doubt, use `CANCELLED`.

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
- `failure_reason`: "upstream library bug blocks CI; no workaround after 3 attempts"

**Example 4 — User pivot before arc declared (CANCELLED for abandoned arc):**
User asked you to refactor the auth module (arc in progress, not yet declared). Mid-arc, user says "actually forget that — help me write a release announcement."
- First: write a `CANCELLED` job marker for the abandoned refactor arc (`job_type`: `refactoring`, `status`: `CANCELLED`).
- Then: begin the new arc (release announcement writing).
- Reason: prevents the refactor's task markers from leaking attribution into the announcement arc.

---

## Outcome-value assessment (v1.5, opt-in, experimental)

When LLM outcome evaluation is enabled and an evaluator returns an accepted
assessment, a `SUCCESS` job marker carries one extra key: `assessment`.

**This is a frozen contract.** Marker readers written before v1.5 must keep
parsing, so every reader uses `.get("assessment", {})` and the key is simply
**absent** whenever evaluation is off, the arc is not `SUCCESS`, or the evaluator
abstained. A disabled-path marker is therefore byte-identical to a pre-v1.5 one.

```json
{"kind":"job","ts":1756...,"sid":"...","agentic_job_id":"fix_auth_a1b2",
 "job_name":"Fix auth regression","job_type":"bug_fix","status":"SUCCESS",
 "assessment":{
   "estimated_value":375.00,
   "currency":"USD",
   "basis":"engineer time avoided on a repro and fix cycle",
   "assumptions":{
     "inferred_role":"backend engineer",
     "estimated_hours_saved":2.5,
     "assumed_loaded_rate":150.00
   },
   "confidence":0.6,
   "evaluator":"llm",
   "evaluator_version":"1",
   "evidence_class":"MODEL_ESTIMATED_DEMO"
 }}
```

| key | type | constraint |
|---|---|---|
| `estimated_value` | number | **Derived** as `estimated_hours_saved x assumed_loaded_rate`, rounded to 2dp. A value supplied by an evaluator is discarded. |
| `currency` | string | ISO 4217, from an explicit supported set, and must match the configured currency. |
| `basis` | string | Clamped to 200 chars. |
| `assumptions.inferred_role` | string | Clamped to 60 chars. |
| `assumptions.estimated_hours_saved` | number | Finite, `0 < h <= maxHoursSaved` (default 40). |
| `assumptions.assumed_loaded_rate` | number | Finite, `0 < r <= maxLoadedRate` (default 500). |
| `confidence` | number | `[0, 1]`. |
| `evaluator`, `evaluator_version` | string | Recorded from the resolved evaluator, never read from its output. |
| `evidence_class` | string | Always `MODEL_ESTIMATED_DEMO` on this path. Forced, never read from output. |

Every string field has `|`, newline, and carriage return replaced with a space
before persistence. The cron's job-outcome queue is `IFS='|'`-parsed, and one
pipe reaching that tuple shifts every following field.

### What `MODEL_ESTIMATED_DEMO` means

**An unverified model estimate.** Not measured, not observed, not
customer-confirmed, and not defensible ROI. Revenium computes a displayed ROI
from this reported value and the metered cost; the value's quality is the
model's, and the feature is labelled experimental for that reason.

**A future non-LLM evaluator must report a different evidence class.** ONNX
classifiers, deterministic customer policies, vertical models, and
system-of-record adapters each carry their own. Do not widen this one to cover
measured value — the whole point of the field is that the two are
distinguishable after the fact.

### The nine evidence-class labels (EGV-10)

`evidence_class` is one of nine flat, unordered labels, never a confidence
ladder: `ACTIVITY_MEASURED`, `OUTPUT_OBSERVED`, `OUTCOME_OBSERVED`,
`MODEL_ESTIMATED_DEMO`, `CUSTOMER_CONFIGURED`, `CUSTOMER_CONFIRMED`,
`ASSOCIATIONAL`, `QUASI_EXPERIMENTAL_IMPACT`, `EXPERIMENTAL_IMPACT`. The
naked-LLM path documented above always emits `MODEL_ESTIMATED_DEMO`; no label
is ranked above or below another.

### Failed and cancelled arcs

`FAILED` and `CANCELLED` arcs are never evaluated: no evaluator call, no
`assessment` key, no value. They keep their metered cost and so remain eligible
to show zero or negative ROI. Success is never inferred from a transcript that
merely sounds productive.
