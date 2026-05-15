---
phase: 8
slug: job-declaration-prompt-block
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-15
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Python `unittest` (stdlib) |
| **Config file** | none — discovery via `-s tests -p 'test_*.py'` |
| **Quick run command** | `python3 -m unittest tests.test_repository -v` |
| **Full suite command** | `python3 -m unittest discover -s tests -p 'test_*.py' -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python3 -m unittest tests.test_repository -v`
- **After every plan wave:** Run `python3 -m unittest discover -s tests -p 'test_*.py' -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 8-XX-XX | TBD | TBD | DECLARE-01..06 | — | N/A | unit | `python3 -m unittest discover -s tests -p 'test_*.py'` | ❌ W0 | ⬜ pending |

*Per-task rows are filled in by the planner once PLAN.md files exist. This phase is prompt-engineering: most tasks edit `SKILL.md` / `references/*.md`, whose enforceable assertions are repo-invariant tests (`tests/test_repository.py`).*

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_repository.py` — add `job-taxonomy.json` to expected-file invariants; add `test_job_taxonomy_file_schema` validating the seed taxonomy shape
- [ ] No framework install needed — stdlib `unittest` already present

*The shipped `skills/revenium/job-taxonomy.json` seed file and any new `SKILL.md` anchors must be pinned by repo-invariant tests so regressions fail the build.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Halt-check survivability under context dilution | DECLARE-06 | Requires a long live Hermes session; cannot be exercised by `unittest` | Run the 4-run test matrix in `skills/revenium/references/halt-survivability.md` (amended pass criterion: exactly one mandated `execute_code` CANCELLED-marker write permitted, verbatim halt string still fires) |
| Agent mints specific, non-collapsed `agentic_job_id` / `job_type` per arc | DECLARE-02, DECLARE-04 | Prompt-behavior quality — observable only across real multi-arc sessions | Run a multi-goal Hermes session; inspect `markers/<sid>.jsonl` job markers for label specificity and absence of taxonomy collapse |
| One distinct job per task arc in a multi-activity session | DECLARE-03 | Arc-boundary detection is LLM behavior | Run a session with 2+ distinct goals; confirm 2+ `kind:"job"` markers with distinct `agentic_job_id`s |
| Conservative outcome bias (`CANCELLED` under uncertainty, not `SUCCESS`) | DECLARE-05 | Outcome judgement is LLM behavior | Exercise an unverified-change arc; confirm `status` is `CANCELLED`, not `SUCCESS` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
