---
phase: 07-job-marker-schema-state-scaffolding
verified: 2026-05-15T07:00:00Z
status: gaps_found
score: 3/4 must-haves verified
overrides_applied: 0
gaps:
  - truth: "The cron marker reader branches on kind: absent kind is parsed as 'task' (v1.0 path), kind:'job' is collected as a job declaration, unknown kind is skipped — and REQUIRED_KEYS for task markers is unchanged so an un-modified v1.0 cron skips job lines rather than crashing"
    status: partial
    reason: "WR-01: m.get('kind') is called with no isinstance(m, dict) guard. A valid-JSON but non-object line (array/scalar/null/bool) causes AttributeError, which escapes both the inner json.JSONDecodeError handler and the outer OSError handler, triggering marker_output='' at line 469 and discarding attribution for the entire session. Pre-Phase-7 behavior was silent skip (REQUIRED_KEYS membership check on a list returns False, not an exception). WR-03: agentic_job_id is used as a dict key with no type/str validation — a list/dict value raises unhashable TypeError via the same uncaught path."
    artifacts:
      - path: "skills/revenium/scripts/hermes-report.sh"
        issue: "Line 409: kind = m.get('kind') called before isinstance(m, dict) guard. Lines 412-413: jobs_by_id[m['agentic_job_id']] = m with no str/non-empty validation on the key. Both AttributeError and TypeError escape the except json.JSONDecodeError / except OSError handlers."
    missing:
      - "Add 'if not isinstance(m, dict): continue' immediately after the json.loads try/except block (before line 409)"
      - "Validate agentic_job_id is a non-empty string before using it as a dict key: 'job_id = m.get(\"agentic_job_id\"); if not isinstance(job_id, str) or not job_id: continue'"
---

# Phase 7: Job Marker Schema & State Scaffolding Verification Report

**Phase Goal:** Freeze the agent-to-cron contract for jobs — the single synchronization point everything downstream depends on — and add the idempotency ledger before any job call exists. Pure additive scaffolding: no behavior change, no new wire output.
**Verified:** 2026-05-15T07:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | JOBS_LEDGER_FILE and JOB_TAXONOMY_FILE declared only in common.sh with :- env-override shape; revenium-jobs.ledger touch-created on cron run; test_runtime_paths_are_hermes_native still passes | ✓ VERIFIED | Lines 24-25 in common.sh. touch on line 35 of hermes-report.sh. Test passes in the full 47-test suite. |
| 2 | kind:"job" JSONL schema is defined as additive extension of markers/<sid>.jsonl — never a per-turn field, never a separate file — and a test pins its shape | ✓ VERIFIED | test_job_marker_schema (line 3469 in test_repository.py) asserts all four D-04 reader-required keys, snake_case spelling, kind=="job", <1024 bytes, and minimal-fixture validity. Both new tests pass. |
| 3 | Cron marker reader branches on kind: absent kind -> v1.0 path, kind:"job" -> job declaration, unknown kind -> skipped; REQUIRED_KEYS for task markers unchanged so un-modified v1.0 cron skips job lines | ✗ PARTIAL | The branching logic is correctly structured (lines 409-416 in hermes-report.sh) and the REQUIRED_KEYS tuple is unchanged. However, m.get("kind") is called with no isinstance(m, dict) guard. A valid-JSON non-object line causes AttributeError that escapes both error handlers and discards the entire session's attribution — a regression from v1.0 behavior (silent skip). WR-03 (unhashable agentic_job_id key) has the same escape path. |
| 4 | A regression test asserts a job-less / marker-less session produces byte-identical revenium meter completion argv to v1.0 | ✓ VERIFIED | test_job_marker_does_not_alter_task_completion_argv (line 3520) sub-case A asserts argv lists are byte-identical between task-only and task+job runs. Sub-case B asserts the zero-marker fallthrough emits --task-type unclassified and --operation-type CHAT. Both sub-cases pass. |

**Score:** 3/4 truths verified

### Deferred Items

None — all four success criteria are within Phase 7 scope.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `skills/revenium/scripts/common.sh` | JOBS_LEDGER_FILE and JOB_TAXONOMY_FILE path declarations | ✓ VERIFIED | Both declared at lines 24-25 with REVENIUM_JOBS_LEDGER_FILE and REVENIUM_JOB_TAXONOMY_FILE env-override shape. Neither path added to mkdir -p. |
| `skills/revenium/scripts/hermes-report.sh` | kind branch in marker reader + jobs ledger touch + JOBS_JSON output | ✓ WIRED (partial regression) | touch on line 35. jobs_by_id initialized before is_file() at line 383 (Pitfall 2 guard). Kind branch at lines 409-416. JOBS_JSON printed at line 467. Bash capture at line 484. Regression: missing isinstance guard (see gap). |
| `tests/test_repository.py` | test_job_marker_schema (TEST-01) and test_job_marker_does_not_alter_task_completion_argv (TEST-02) | ✓ VERIFIED | Both methods present at lines 3469 and 3520. Both pass individually (confirmed via pytest) and in the full 47-test suite. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| hermes-report.sh | JOBS_LEDGER_FILE in common.sh | touch on startup | ✓ WIRED | `touch "${JOBS_LEDGER_FILE}"` at line 35, directly after `touch "${LEDGER_FILE}"` at line 34 |
| hermes-report.sh marker reader | jobs_by_id collector | kind branch before REQUIRED_KEYS check | ✓ WIRED (partial) | `kind = m.get("kind")` at line 409, before REQUIRED_KEYS at line 418. Missing isinstance guard means non-dict JSON values cause uncaught AttributeError. |

### Data-Flow Trace (Level 4)

Not applicable — Phase 7 is pure scaffolding. jobs_json is captured but explicitly unused in Phase 7 (intentional per plan). JOBS_JSON output flows: heredoc print (line 467) -> bash sed capture (line 484) -> local jobs_json (declared, intentionally unused, comment-documented for Phase 9).

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full test suite passes with 47 tests | `python3 -m unittest discover -s tests -p 'test_*.py' -v` | 47 tests OK in 14.502s | ✓ PASS |
| Both scripts parse without syntax errors | `bash -n common.sh && bash -n hermes-report.sh` | Both exit 0 | ✓ PASS |
| TEST-01 and TEST-02 pass individually | pytest on both new methods | 2 passed in 1.30s | ✓ PASS |

### Probe Execution

Step 7c: SKIPPED — no probe scripts declared in plan or found at conventional paths.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|------------|------------|-------------|--------|---------|
| SCHEMA-01 | 07-01-PLAN.md | JOBS_LEDGER_FILE and JOB_TAXONOMY_FILE declared in common.sh with :- shape | ✓ SATISFIED | Lines 24-25 in common.sh; env-var names appear only in common.sh (grep confirmed) |
| SCHEMA-02 | 07-01-PLAN.md | kind:"job" JSONL schema defined as additive extension of markers/<sid>.jsonl | ✓ SATISFIED | Schema pinned by test_job_marker_schema; file co-location in existing markers/<sid>.jsonl |
| SCHEMA-03 | 07-01-PLAN.md | Reader branches on kind; absent -> v1.0, kind:"job" -> collected, unknown -> skipped | ✗ BLOCKED | Branch logic is structurally correct but missing isinstance(m, dict) guard — non-dict JSON lines cause AttributeError that discards entire session (WR-01). WR-03 adds a second uncaught TypeError path. |
| SCHEMA-04 | 07-01-PLAN.md | Job-less / marker-less session produces byte-identical argv to v1.0 | ✓ SATISFIED | TEST-02 sub-case A and B both pass; invocations_a == invocations_b verified |
| SCHEMA-05 | 07-01-PLAN.md | REQUIRED_KEYS unchanged; job-marker fields accessed with .get()/membership | ✓ SATISFIED | REQUIRED_KEYS at line 378 is exactly ('muid', 'ts', 'sid', 'task_type', 'operation_type'); job fields accessed with all(k in m for k in JOB_REQUIRED) |
| TEST-01 | 07-01-PLAN.md | test_job_marker_schema pins kind:"job" shape | ✓ SATISFIED | Method present at line 3469; passes |
| TEST-02 | 07-01-PLAN.md | test_job_marker_does_not_alter_task_completion_argv proves byte-identical argv | ✓ SATISFIED | Method present at line 3520; both sub-cases pass |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| hermes-report.sh | 409 | `m.get("kind")` before isinstance check — AttributeError uncaught | BLOCKER | A single non-object JSON line ([1,2,3], "str", 42, null, true) silently discards attribution for the entire session. Regression from v1.0 behavior. |
| hermes-report.sh | 413 | `jobs_by_id[m["agentic_job_id"]] = m` with no str/non-empty validation | WARNING | list/dict value as agentic_job_id raises unhashable TypeError via same uncaught path as WR-01; null/numeric values accepted as keys and would mis-group in Phase 9 |
| hermes-report.sh | 483-484 | `local jobs_json` assigned but never read | INFO | Acceptable per plan (explicitly unused in Phase 7, documented for Phase 9 consumption); adds one echo|sed per session per cron tick |

No TBD/FIXME/XXX/unresolved debt markers found in modified files.

### Human Verification Required

None. All success criteria are verifiable programmatically.

### Gaps Summary

**1 gap blocking full goal achievement:**

**WR-01 + WR-03: Non-dict JSON line and unhashable agentic_job_id cause uncaught exceptions that discard session attribution (SCHEMA-03 PARTIAL)**

The kind branch is structurally correct and the REQUIRED_KEYS tuple is unchanged. However, `m.get("kind")` is called immediately after `json.loads(line)` with no `isinstance(m, dict)` check. If any line in a session's markers/<sid>.jsonl is valid JSON but not a JSON object — e.g., `[1,2,3]`, `"hello"`, `42`, `null`, `true` — then `m.get()` raises `AttributeError`. This exception is caught by neither `except json.JSONDecodeError:` (line 403) nor `except OSError:` (line 444), so it escapes the entire per-file loop, causing `|| marker_output=""` at line 469 to fire. The session falls through to `unclassified` metering with a `marker-read fall-through` warn, losing all marker attribution.

Pre-Phase-7 behavior was safe: `all(k in m for k in REQUIRED_KEYS)` on a list returns `False` (no exception), so a non-dict JSON line was silently skipped and the remaining valid markers were still processed.

WR-03 adds a second uncaught path: if a `kind:"job"` line has `agentic_job_id` set to a list or dict, `jobs_by_id[m["agentic_job_id"]] = m` raises `unhashable type: TypeError` via the same uncaught route.

**Fixes required:**
1. Add `if not isinstance(m, dict): continue` after the `json.loads` try/except block, before line 409.
2. Validate agentic_job_id: `job_id = m.get("agentic_job_id"); if not isinstance(job_id, str) or not job_id: continue`.

Note: TEST-02 uses only well-formed canonical markers, so it does not exercise these paths. The full suite passes because no test feeds non-object JSONL lines to the reader. The regression is latent but observable and is a strict regression from v1.0 for any marker file containing a valid-JSON non-object line.

---

_Verified: 2026-05-15T07:00:00Z_
_Verifier: Claude (gsd-verifier)_
