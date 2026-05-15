---
phase: 07
slug: job-marker-schema-state-scaffolding
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-15
---

# Phase 07 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Reconstructed from phase artifacts (State B) on 2026-05-15.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Python stdlib `unittest` (zero third-party deps) |
| **Config file** | none — discovery via `-s tests -p 'test_*.py'` |
| **Quick run command** | `cd tests && python3 -m unittest test_repository.RepositoryTests.test_job_marker_schema test_repository.RepositoryTests.test_job_marker_does_not_alter_task_completion_argv` |
| **Full suite command** | `python3 -m unittest discover -s tests -p 'test_*.py' -v` |
| **Estimated runtime** | ~19 seconds (full suite, 47 tests) |

---

## Sampling Rate

- **After every task commit:** Run the quick run command
- **After every plan wave:** Run the full suite command
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~20 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 07-01-01 | 01 | 1 | SCHEMA-01 | T-07-03 | `JOBS_LEDGER_FILE`/`JOB_TAXONOMY_FILE` declared only in `common.sh` with `:-` env-override shape | unit | `python3 -m unittest discover -s tests -p 'test_*.py' -k test_runtime_paths_are_hermes_native` | ✅ | ✅ green |
| 07-01-02 | 01 | 1 | SCHEMA-01 | T-07-03 | `revenium-jobs.ledger` touch-created on every cron run (D-15) | integration | `python3 -m unittest discover -s tests -p 'test_*.py' -k test_job_marker_does_not_alter_task_completion_argv` | ✅ | ✅ green |
| 07-01-03 | 01 | 1 | SCHEMA-02 / TEST-01 | T-07-01 | `kind:"job"` JSONL schema shape pinned (D-01/D-02/D-03/D-04) | unit | `python3 -m unittest discover -s tests -p 'test_*.py' -k test_job_marker_schema` | ✅ | ✅ green |
| 07-01-04 | 01 | 1 | SCHEMA-03 | T-07-01 | Reader branch: absent `kind` → v1.0 task path byte-identical (D-06) | integration | `python3 -m unittest discover -s tests -p 'test_*.py' -k test_job_marker_does_not_alter_task_completion_argv` | ✅ | ✅ green |
| 07-01-05 | 01 | 1 | SCHEMA-03 | T-07-01 | Reader branch: unknown `kind` → forward-compat skip (`elif kind is not None: continue`, D-06) | integration | `python3 -m unittest discover -s tests -p 'test_*.py' -k test_job_marker_does_not_alter_task_completion_argv` | ✅ | ✅ green |
| 07-01-06 | 01 | 1 | SCHEMA-04 / TEST-02 | T-07-01 | Job-less / marker-less session → byte-identical `revenium meter completion` argv to v1.0 | integration | `python3 -m unittest discover -s tests -p 'test_*.py' -k test_job_marker_does_not_alter_task_completion_argv` | ✅ | ✅ green |
| 07-01-07 | 01 | 1 | SCHEMA-05 | T-07-01 | `REQUIRED_KEYS` tuple unchanged; job-marker fields read defensively (`.get()`/membership), malformed lines skip self only | integration | `python3 -m unittest discover -s tests -p 'test_*.py' -k test_cron_marker_split_end_to_end` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. Two gaps surfaced during this audit were filled in `tests/test_repository.py` (no new framework or file needed):

- ✅ SCHEMA-01 touch-create assertion — `revenium-jobs.ledger` existence checked after a cron run inside `test_job_marker_does_not_alter_task_completion_argv`.
- ✅ SCHEMA-03 unknown-`kind` skip — Sub-case D added to `test_job_marker_does_not_alter_task_completion_argv`, including a hard adversarial line (`kind:"future_v2"` carrying all 5 `REQUIRED_KEYS`) that would generate a spurious meter call without the `elif kind is not None: continue` branch.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Job-declaration collection into `JOBS_JSON` + D-12 last-line-wins per `agentic_job_id` | SCHEMA-03 | `JOBS_JSON` is captured into an unused bash local (`jobs_json`) and never logged or written — it is not externally observable without modifying `hermes-report.sh`, which the auditor must not do. Reserved for Phase 9 consumption. | Inspect the marker reader heredoc in `skills/revenium/scripts/hermes-report.sh`: confirm `jobs_by_id[m["agentic_job_id"]] = m` (last assignment wins) and `print(f"JOBS_JSON=...")`. When Phase 9 consumes `JOBS_JSON`, add an automated assertion on collection + last-wins then. |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (2 gaps filled in `test_repository.py`)
- [x] No watch-mode flags
- [x] Feedback latency < 20s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-05-15

---

## Validation Audit 2026-05-15

| Metric | Count |
|--------|-------|
| Gaps found | 2 |
| Resolved | 2 |
| Escalated | 0 |
| Manual-only | 1 |

Reconstructed from `07-01-PLAN.md` / `07-01-SUMMARY.md` (State B). Both fillable gaps (SCHEMA-01 touch-create, SCHEMA-03 unknown-`kind` skip) resolved by extending `test_job_marker_does_not_alter_task_completion_argv`. Full suite: 47/47 green.
