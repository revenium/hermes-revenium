---
phase: 08-job-declaration-prompt-block
plan: "01"
subsystem: seed-data
tags: [job-taxonomy, seed-file, setup, tests]
dependency_graph:
  requires: []
  provides: [skills/revenium/job-taxonomy.json, setup-local.sh job-taxonomy copy, test_job_taxonomy_file_schema]
  affects: [Phase 8 Wave 2 SKILL.md JOB DECLARATION block, revenium-classifier halt-path]
tech_stack:
  added: []
  patterns: [no-clobber seed copy, JSON seed mirroring task-taxonomy.json schema, floor-count test assertion]
key_files:
  created:
    - skills/revenium/job-taxonomy.json
  modified:
    - examples/setup-local.sh
    - tests/test_repository.py
decisions:
  - "Seeded exactly 11 entries: 10 business labels (feature_development, bug_fix, code_review, refactoring, research, debugging, testing, documentation, devops, planning) + interrupted for budget-halt path"
  - "test_job_taxonomy_file_schema asserts len >= 8 floor, NOT exact ordered list (D-04: planner discretion)"
  - "setup-local.sh seed copy uses REVENIUM_JOB_TAXONOMY_FILE env override matching common.sh:25 declaration"
metrics:
  duration: "~8 minutes"
  completed: "2026-05-15"
  tasks: 3
  files: 3
---

# Phase 8 Plan 01: Seed-Data Substrate Summary

**One-liner:** 11-entry `job-taxonomy.json` seed with `interrupted` for halt-path, no-clobber install copy in `setup-local.sh`, and schema-pinning test invariants — the Wave 1 foundation the Wave 2 JOB DECLARATION block reads.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create job-taxonomy.json seed file | ea80b8f | skills/revenium/job-taxonomy.json (created) |
| 2 | Wire seed->live copy in setup-local.sh | 8d93668 | examples/setup-local.sh (modified) |
| 3 | Add presence + schema invariants to test_repository.py | 5d59837 | tests/test_repository.py (modified) |

## What Was Built

### skills/revenium/job-taxonomy.json

New seed file mirroring the `task-taxonomy.json` schema exactly: a single top-level `labels` object mapping job_type labels to descriptors with `description` (string) and `examples` (list). Ships exactly 11 entries:

- 10 business labels: `feature_development`, `bug_fix`, `code_review`, `refactoring`, `research`, `debugging`, `testing`, `documentation`, `devops`, `planning`
- 1 mandatory terminal label: `interrupted` — consumed by the Wave 2 halt-path marker so `job_type:"interrupted"` never triggers a taxonomy mint

All labels match `^[a-z][a-z0-9_]{1,47}$`; none are blocklisted.

### examples/setup-local.sh

Added a parallel no-clobber seed-copy block immediately after the existing `task-taxonomy.json` block:

```bash
JOB_TAXONOMY_DEST="${REVENIUM_JOB_TAXONOMY_FILE:-${STATE_DIR_DEFAULT}/job-taxonomy.json}"
if [[ ! -f "${JOB_TAXONOMY_DEST}" ]]; then
  cp "${REPO_ROOT}/skills/revenium/job-taxonomy.json" "${JOB_TAXONOMY_DEST}"
  echo "Seeded ${JOB_TAXONOMY_DEST}"
else
  echo "Job taxonomy already exists at ${JOB_TAXONOMY_DEST}, not overwriting"
fi
```

Reuses already-defined `REPO_ROOT` and `STATE_DIR_DEFAULT`. Env override `REVENIUM_JOB_TAXONOMY_FILE` matches `common.sh:25` declaration. Bash 3.2-safe (only `cp` and `[[ ! -f ]]`).

### tests/test_repository.py

Two additions:

1. `SKILL / 'job-taxonomy.json'` added to `test_expected_files_exist` list (beside `task-taxonomy.json`)
2. New `test_job_taxonomy_file_schema` method after `test_taxonomy_file_schema`: asserts labels dict, label regex, blocklist, descriptor keys (description str + examples list), and `len(labels) >= 8` floor count — does NOT pin an exact ordered label list (D-04)

Test suite grew from 47 to 48 tests; all pass.

## Verification

- `python3 -m unittest discover -s tests -p 'test_*.py' -v` — 48 tests, all OK
- `bash -n examples/setup-local.sh` — exits 0
- `python3 -c "import json,re; ..."` verify command — prints `ok`
- Branding guard check: clean (no legacy names in new files)

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. All 11 taxonomy entries have concrete descriptions and realistic examples. The `interrupted` entry is intentional and complete — it is the designed value for the halt path.

## Threat Flags

No new threat surface beyond what the plan's threat model covers (T-08-01, T-08-02, T-08-03). The seed copy is no-clobber (T-08-02 mitigated). No network, credentials, or privilege boundaries introduced.

## Self-Check: PASSED

- [x] `skills/revenium/job-taxonomy.json` exists: FOUND
- [x] `examples/setup-local.sh` contains `JOB_TAXONOMY_DEST`: FOUND
- [x] `tests/test_repository.py` contains `test_job_taxonomy_file_schema`: FOUND
- [x] Commit ea80b8f exists: FOUND
- [x] Commit 8d93668 exists: FOUND
- [x] Commit 5d59837 exists: FOUND
