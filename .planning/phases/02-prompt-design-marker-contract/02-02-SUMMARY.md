---
phase: 02-prompt-design-marker-contract
plan: "02"
subsystem: marker-schema-runbook
tags: [marker-schema, jsonl, halt-survivability, e2e-runbook, test-invariant]
dependency_graph:
  requires:
    - 02-01: skills/revenium/references/task-taxonomy.md and test_taxonomy_file_schema shipped
  provides:
    - halt-survivability-runbook: skills/revenium/references/halt-survivability.md
    - test-invariant: tests/test_repository.py::test_marker_file_schema (TEST-01)
    - file-existence-check: test_expected_files_exist extended with halt-survivability.md
    - d04-closure: README.md references the runbook with operator-runbook framing
  affects:
    - plan 02-03: SKILL.md canonical marker-write snippet must produce records satisfying TEST-01 shape
    - phase 3: cron reader inherits the allow-list and < 1024-byte contract established here
tech_stack:
  added: []
  patterns:
    - method-local imports in stdlib unittest (consistent with existing test style)
    - fixture-in-method pattern for marker schema assertions
    - operator runbook in references/ alongside troubleshooting.md and task-taxonomy.md
key_files:
  created:
    - skills/revenium/references/halt-survivability.md
    - .planning/phases/02-prompt-design-marker-contract/02-02-SUMMARY.md
  modified:
    - README.md
    - tests/test_repository.py
decisions:
  - "Fixture muids corrected to exactly 33 chars (13-char ms timestamp + 20-char random hex); the plan interface block showed 34-char muids by mistake"
  - "CLAUDE.md is git-ignored and untracked; edit applied directly to the working-tree file; only README.md carries a tracked git commit for D-04"
  - "halt-survivability.md avoids the reserved words ABSOLUTE and NON-NEGOTIABLE per D-14 — references the halt-check section by description not by its heading literal"
metrics:
  duration: "~20 minutes"
  completed: "2026-05-12"
  tasks_completed: 3
  files_changed: 4
  lines_added: 222
---

# Phase 2 Plan 2: Halt-Survivability Runbook, D-04 Surfacing, and TEST-01 Marker Schema Summary

Shipped the halt-survivability E2E operator runbook (Phase 2 research flag closure),
surfaced the runbook reference in README.md and CLAUDE.md (D-04 closure), and added
the TEST-01 marker-schema invariant test plus a file-existence check for the new
runbook to `tests/test_repository.py`.

## What Was Built

### Task 1 — `skills/revenium/references/halt-survivability.md` (commit 4b07144)

A 178-line manual E2E test plan covering:

- **When to run** — before every release that modifies `SKILL.md`
- **Pass criterion** — verbatim halt-string, no tools, any deviation = FAIL (D-03)
- **Test matrix** — 2×2 Markdown table (Short ~2K / Long ~20K) × (Claude Sonnet 4.6 / GPT-4o-class) producing 4 runs per release
- **Scenario 1** — short session baseline: 5 turns, flip `budget-status.json`, observe
- **Scenario 2** — long session context-dilution: inflate to ~20K tokens via blob or turn-count, flip, observe; cost estimate $0.05–$0.15 per run on Claude Sonnet 4.6
- **Recording results** — per-run template table with Date, Model, Scenario, Result, Notes
- **Why this test exists** — links to PITFALLS.md Pitfall 7 and Phase 2 ROADMAP success criteria

The exact halt-string template embedded in the runbook:

```
Budget enforcement halt is active. $[currentValue] of $[threshold] used ([percentUsed]%). To resume: `bash ~/.hermes/skills/revenium/scripts/clear-halt.sh`
```

Both `ABSOLUTE` and `NON-NEGOTIABLE` are absent from the doc body per D-14.

### Task 2 — README.md + CLAUDE.md references (commit 230e2f5)

**README.md:** Added two sentences in the `## Testing` section noting that beyond
the stdlib smoke checks, a manual halt-check survivability test plan — operator
runbook is documented at `skills/revenium/references/halt-survivability.md` and
should be run before releases that modify the halt block.

**CLAUDE.md (git-ignored, untracked):** Added one sentence in the `### Halt
transitions` subsection (outside all GSD-managed blocks) pointing to the runbook
with the same operator-runbook framing language. The edit is in the working-tree
copy only; CLAUDE.md is in `.gitignore` by design and carries no commit.

Both files contain the literal `halt-survivability.md` and the phrase `manual
halt-check survivability test plan — operator runbook` as required by D-04.

### Task 3 — `tests/test_repository.py` TEST-01 + file check (commit b1110af)

**`test_expected_files_exist` extended:** Added `SKILL / 'references' / 'halt-survivability.md'`
after the `task-taxonomy.md` entry, before `scripts/common.sh`.

**`test_marker_file_schema` added (TEST-01):** A new test method with:

- `allow_listed_required = {'muid', 'ts', 'sid', 'task_type', 'operation_type'}` (MARK-02, MARK-05)
- `allow_listed_optional = {'turn_seq', 'agent', 'trace_id', 'model'}`
- Two fixture records: one `GUARDRAIL` + one `CHAT` per substantive turn (Pitfall 4)
- Allow-list enforcement: `extra_keys == set()` check
- Required-key presence check via `issubset`
- Compact JSONL serialization: `json.dumps(record, separators=(',', ':')) + '\n'`
- Line budget: `len(line.encode('utf-8')) < 1024` (MARK-02)
- `task_type` regex: `^[a-z][a-z0-9_]{1,47}$`
- `operation_type` vocabulary: OpenInference span_kind set (CHAT, GUARDRAIL, TOOL, AGENT, LLM, CHAIN, RETRIEVER, EMBEDDING, RERANKER, EVALUATOR, UNKNOWN)
- MARK-03 muid assertion: `re.match(r'^[0-9a-f]{33}$', muid)` — pins the 13-char ms-timestamp + 20-char random hex shape
- Pitfall-4 invariant: `{r['operation_type'] for r in fixture_records} == {'GUARDRAIL', 'CHAT'}`

## Test Results

8 tests total after this plan (7 from 02-01 + `test_marker_file_schema`):

| Test | Result | Notes |
|------|--------|-------|
| `test_expected_files_exist` | PASS | Includes halt-survivability.md path |
| `test_marker_file_schema` | PASS | TEST-01 delivered |
| `test_no_legacy_branding_left` | PASS | halt-survivability.md does not trigger regex |
| `test_runtime_paths_are_hermes_native` | PASS | common.sh unchanged |
| `test_shell_scripts_have_valid_syntax` | PASS | No script changes |
| `test_skill_frontmatter_has_hermes_metadata` | PASS | SKILL.md unchanged |
| `test_taxonomy_atomic_write_pattern` | PASS | From 02-01; no regression |
| `test_taxonomy_file_schema` | PASS | From 02-01; no regression |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected 34-char fixture muids to 33 chars (MARK-03)**
- **Found during:** Task 3 — `test_marker_file_schema` failed on first run with
  `AssertionError: Regex didn't match: '^[0-9a-f]{33}$' not found in '01893b8a300abcdef0123456789abcdef0'`
- **Issue:** The plan's `<interfaces>` block showed `01893b8a300abcdef0123456789abcdef0` (34 chars) and `01893b8a301abcdef0123456789abcdef1` (34 chars). Each was one character too long.
- **Fix:** Trimmed the trailing digit: `01893b8a300abcdef0123456789abcdef` (33 chars) and `01893b8a301abcdef0123456789abcde1` (33 chars).
- **Files modified:** `tests/test_repository.py`
- **Commit:** b1110af (same task commit)

**2. [Rule 1 - Bug] Removed reserved keyword from halt-survivability.md**
- **Found during:** Task 1 verification — the initial draft quoted the SKILL.md section heading
  literally (`ABSOLUTE FIRST — HALT CHECK`), which violated the D-14 acceptance criterion.
- **Fix:** Replaced the literal heading quote with a description (`the halt-check priority
  section in SKILL.md`) that conveys the same meaning without using the reserved word.
- **Files modified:** `skills/revenium/references/halt-survivability.md`
- **Commit:** 4b07144 (same task commit after inline fix)

### Structural Note

**CLAUDE.md is git-ignored.** The plan assumed CLAUDE.md would be tracked and committed.
It is in `.gitignore` by design. The edit was applied to the working-tree copy
(`/Users/johndemic/Development/projects/revenium/hermes-revenium/CLAUDE.md`), which
satisfies the D-04 grep gate (`grep -q "halt-survivability.md" CLAUDE.md` passes).
The commit for Task 2 records only the README.md change.

## Requirements Coverage

| Requirement | Status | Covered by |
|-------------|--------|------------|
| MARK-01 (single write line < 1024 bytes — JSONL format) | Done | TEST-01 compact serialization + size assertion |
| MARK-02 (allow-list + size budget) | Done | TEST-01 extra_keys check + < 1024-byte assertion |
| MARK-03 (muid is 33-char sortable hex string) | Done | TEST-01 `assertRegex(muid, r'^[0-9a-f]{33}$')` |
| MARK-04 (cron tolerates torn last line) | Partial | Contract documented via allow-list shape; cron reader is Phase 3 |
| MARK-05 (allow-list enforcement) | Done | TEST-01 no-extra-keys assertion |
| TEST-01 (test_marker_file_schema) | Done | Task 3 |

## Plan 02-03 Consumption Note

Plan 02-03 (Wave 3) adds the `## FINAL ACTION — TASK CLASSIFICATION` section to
`SKILL.md`, including a canonical Python heredoc snippet for writing marker records.
That snippet MUST produce records that satisfy TEST-01 exactly: allow-listed keys,
`muid` matching `^[0-9a-f]{33}$`, `operation_type` in the span_kind vocabulary, and
compact JSONL format under 1024 bytes. The fixture records in this plan's test are
the acceptance oracle.

## Known Stubs

None. All delivered artifacts are real content:
- The runbook documents real test procedures against the real `budget-status.json` interface.
- The TEST-01 fixture is real JSONL data that exercises the real schema contract.
- The README.md reference points to a real file on disk.

## Threat Flags

None. All new files are within the existing `skills/revenium/` trust boundary.
T-02-02-01 through T-02-02-07 are all mitigated as specified in the plan's threat
register.

## Self-Check: PASSED

- FOUND: skills/revenium/references/halt-survivability.md
- FOUND: tests/test_repository.py (modified)
- FOUND: README.md (modified)
- FOUND: CLAUDE.md (modified, git-ignored working-tree file)
- FOUND: commit 4b07144 (Task 1)
- FOUND: commit 230e2f5 (Task 2)
- FOUND: commit b1110af (Task 3)
- All 8 tests pass: `python3 -m unittest discover -s tests -p 'test_*.py' -v` → OK
