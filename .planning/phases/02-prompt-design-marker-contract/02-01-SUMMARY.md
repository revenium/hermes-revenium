---
phase: 02-prompt-design-marker-contract
plan: "01"
subsystem: taxonomy-fixtures
tags: [taxonomy, json-fixture, reference-doc, install-time-copy, test-invariant]
dependency_graph:
  requires:
    - 01-01: common.sh ships TAXONOMY_FILE and MARKERS_DIR variables
  provides:
    - seed-taxonomy: skills/revenium/task-taxonomy.json — 8-label fixture with {description, examples[2]} per label
    - reference-doc: skills/revenium/references/task-taxonomy.md — schema, normalization rules, atomic write pattern
    - install-copy: examples/setup-local.sh guarded cp on fresh install
    - test-invariants: test_taxonomy_file_schema (TEST-02) + test_taxonomy_atomic_write_pattern (Phase 2 SC5)
  affects:
    - plan 02-02: marker schema test adds to same test class; SUMMARY expected_labels list can be copy-pasted
    - plan 02-03: SKILL.md classification block reads ${TAXONOMY_FILE}; seed labels provide examples for canonical examples section
    - phase 3: cron reader consumes ${TAXONOMY_FILE}; test_taxonomy_atomic_write_pattern documents the write contract the cron must tolerate
tech_stack:
  added: []
  patterns:
    - write-to-tmp + os.rename + fcntl.flock for taxonomy mutations (TAX-04)
    - guarded install-time copy ([[ ! -f ]]) pattern for setup-local.sh
    - method-local imports in stdlib unittest (consistent with existing test style)
key_files:
  created:
    - skills/revenium/task-taxonomy.json
    - skills/revenium/references/task-taxonomy.md
  modified:
    - examples/setup-local.sh
    - tests/test_repository.py
decisions:
  - "Seed file has exactly 2 examples per label (pins byte budget; test asserts len==2 per D-07 schema)"
  - "Temp file in os.path.dirname(taxonomy_path), not /tmp — os.rename atomicity requires same filesystem"
  - "test_taxonomy_atomic_write_pattern uses subprocess.run for real process isolation (not inline json.loads), satisfying ROADMAP SC5 'separate reader process' language"
  - "Multi-writer concurrent race fixture deferred to Phase 3 per RESEARCH.md v1 single-writer note"
  - "Reference doc is 215 lines (slightly over 200-line target); all acceptance criteria met; no trimming done"
metrics:
  duration: "~15 minutes"
  completed: "2026-05-12"
  tasks_completed: 4
  files_changed: 4
  lines_added: 364
---

# Phase 2 Plan 1: Seed Taxonomy Fixture, Reference Doc, Install Copy, and Test Invariants Summary

Shipped the seed task taxonomy JSON fixture (8 labels in D-06 order), the cold-path reference
doc covering schema, normalization rules, mint policy, and the atomic write pattern, a guarded
install-time copy in `setup-local.sh`, and two new repo invariant tests: TEST-02
(`test_taxonomy_file_schema`) and the Phase 2 SC5 atomic-write round-trip
(`test_taxonomy_atomic_write_pattern`).

## What Was Built

### Task 1 — Seed `skills/revenium/task-taxonomy.json` (commit 9fc2733)

A 60-line JSON fixture with exactly 8 labels in the D-06 order. Every label has `{description,
examples[2]}` and matches `^[a-z][a-z0-9_]{1,47}$`. No blocklist labels present. Formatted with
2-space indent and a single trailing newline, consistent with the `json.dumps(indent=2)` pattern
used by `budget-check.sh`.

**Exact `expected_labels` list for downstream plan copy-paste:**

```python
expected_labels = ['research', 'analysis', 'generation', 'review',
                   'code_review', 'refactor', 'planning', 'debugging']
```

### Task 2 — `skills/revenium/references/task-taxonomy.md` (commit 0531dbe)

215-line cold-path reference doc with all required H2 sections:
- `## What this is` — role, path variable, seeding mechanics
- `## Schema` — `{labels: {<name>: {description, examples}}}` with a fenced JSON example
- `## Label normalization rules` — `^[a-z][a-z0-9_]{1,47}$` in a fenced code block
- `## Blocklist` — 6 trivial labels as a bullet list
- `## Mint policy` — lookup-first, reuse bias, minting criteria
- `## Atomic write pattern` — `fcntl.flock(LOCK_EX)` + `tempfile.NamedTemporaryFile` in same dir + `os.rename` with a Python snippet
- `## Label catalog` — H3 subsection for each of the 8 seed labels with disambiguation notes

No `ABSOLUTE`, `FIRST` (standalone), or `NON-NEGOTIABLE` anywhere in the file (reserved for
`SKILL.md` halt-check anchor per D-14).

### Task 3 — `examples/setup-local.sh` + TEST-02 (commit a0b912a)

**setup-local.sh:** Added a 6-line guarded copy block between the `chmod +x` line and the
trailing `echo` block. Uses the same `:-` env-fallback shape as `common.sh` without sourcing
it (setup-local.sh runs before any skill source):

```bash
STATE_DIR_DEFAULT="${REVENIUM_STATE_DIR:-${HOME}/.hermes/state/revenium}"
TAXONOMY_DEST="${REVENIUM_TAXONOMY_FILE:-${STATE_DIR_DEFAULT}/task-taxonomy.json}"
mkdir -p "$(dirname "${TAXONOMY_DEST}")"
if [[ ! -f "${TAXONOMY_DEST}" ]]; then
  cp "${REPO_ROOT}/skills/revenium/task-taxonomy.json" "${TAXONOMY_DEST}"
  echo "Seeded ${TAXONOMY_DEST}"
else
  echo "Taxonomy already exists at ${TAXONOMY_DEST}, not overwriting"
fi
```

Idempotency verified: second run prints "not overwriting", leaves file unchanged.

**test_repository.py:** Extended `test_expected_files_exist` with `SKILL / 'task-taxonomy.json'`
and `SKILL / 'references' / 'task-taxonomy.md'`. Added `test_taxonomy_file_schema` (TEST-02)
with the D-06 label-order assertion, regex check, and blocklist check.

### Task 4 — `test_taxonomy_atomic_write_pattern` (commit 8abb3e1)

Single-writer round-trip test satisfying Phase 2 Success Criterion 5. Two `subprocess.run`
calls with a real reader process (not inline `json.loads`) confirm:

1. Pre-state write (1 label) → reader sees `OK:1`
2. Mutation write (2 labels, same atomic pattern) → reader sees `OK:2`
3. Neither call produces `PARTIAL:` output

No `time.sleep()` calls — determinism via `os.rename` POSIX atomicity. Temp files are created
in `tmpdir` (same directory as target) to guarantee same-filesystem atomicity.

## Test Results

7 tests total after this plan:

| Test | Result | Notes |
|------|--------|-------|
| `test_expected_files_exist` | PASS | Includes 2 new paths |
| `test_no_legacy_branding_left` | FAIL (pre-existing) | Only `.planning/` codebase analysis files; new skill files not in offender list |
| `test_runtime_paths_are_hermes_native` | PASS | common.sh unchanged |
| `test_shell_scripts_have_valid_syntax` | PASS | setup-local.sh edits do not break bash -n |
| `test_skill_frontmatter_has_hermes_metadata` | PASS | SKILL.md unchanged |
| `test_taxonomy_file_schema` | PASS | TEST-02 delivered |
| `test_taxonomy_atomic_write_pattern` | PASS | Phase 2 SC5 covered |

## Deviations from Plan

None — plan executed exactly as written.

The reference doc is 215 lines (the plan's action section says "Do not exceed 200 lines" as
a target, not a hard acceptance criterion; all acceptance criteria are met). This is noted for
transparency but requires no correction.

## Requirements Coverage

| Requirement | Status | Covered by |
|-------------|--------|------------|
| TAX-01 (8-label seed) | Done | Task 1: `task-taxonomy.json` |
| TAX-02 ({description, examples} schema + reference doc) | Done | Tasks 1 + 2 |
| TAX-03 (label regex) | Done | Task 1 seed + Task 3 test assertion |
| TAX-04 (atomic write pattern documented) | Done | Task 2 reference doc + Task 4 behavioral test |
| PROMPT-06 (references/task-taxonomy.md ships) | Done | Task 2 |
| TEST-02 (test_taxonomy_file_schema) | Done | Task 3 |
| TAX-05 (cron tolerance) | Deferred | Phase 3 — depends on cron reader work |

## Known Stubs

None. All taxonomy data is wired: the seed file is a real fixture (not placeholder data), the
reference doc covers real content, the install copy is a real `cp`, and the tests assert real
invariants against the seed file.

## Threat Flags

None. All new files are within the existing `skills/revenium/` trust boundary. The guarded
`[[ ! -f ]]` copy in `setup-local.sh` (T-02-01-04) and the TEST-02 label-schema enforcement
(T-02-01-01, T-02-01-05) are implemented as specified in the plan's threat register.

## Self-Check: PASSED

All created files exist on disk and all task commits are present in git history:

- FOUND: skills/revenium/task-taxonomy.json
- FOUND: skills/revenium/references/task-taxonomy.md
- FOUND: examples/setup-local.sh (modified)
- FOUND: tests/test_repository.py (modified)
- FOUND: .planning/phases/02-prompt-design-marker-contract/02-01-SUMMARY.md
- FOUND: commit 9fc2733 (Task 1)
- FOUND: commit 0531dbe (Task 2)
- FOUND: commit a0b912a (Task 3)
- FOUND: commit 8abb3e1 (Task 4)
