---
phase: 02-prompt-design-marker-contract
plan: "03"
subsystem: skill-prompt
tags: [skill-md, prompt-design, end-loaded, marker-write, hermes-session-id, prompt-invariant-test]
dependency_graph:
  requires: [02-01, 02-02]
  provides: [SKILL.md-classification-section, test_prompt_ordering_invariant]
  affects: [skills/revenium/SKILL.md, tests/test_repository.py]
tech_stack:
  added: []
  patterns: [Python-heredoc-stdlib, O_APPEND-atomic-write, fcntl-advisory-lock, ULID-style-muid]
key_files:
  modified:
    - skills/revenium/SKILL.md
    - tests/test_repository.py
decisions:
  - "HERMES_SESSION_ID resolution: option (b) — primary os.environ.get with timestamp fallback (no empirical verification possible from executor context)"
  - "Section heading uses U+2014 em dash to match halt anchor convention"
  - "Two write_marker calls per substantive turn per Pitfall 4 invariant"
metrics:
  duration: "~20 minutes"
  completed: "2026-05-12"
  tasks_completed: 3
  files_changed: 2
---

# Phase 2 Plan 3: SKILL.md Classification Section and PROMPT-07 Test Summary

End-loaded `## FINAL ACTION — TASK CLASSIFICATION` section appended to SKILL.md with D-09 hard rule verbatim, 4 canonical examples, D-12 trivial-label blocklist, canonical Python marker-write heredoc snippet (two write_marker calls per turn — GUARDRAIL + CHAT per Pitfall 4), and `test_prompt_ordering_invariant` test pinning structural ordering invariant with U+2014 em-dash literals.

## What Was Built

### Task 1: HERMES_SESSION_ID Resolution Decision

**Decision record:** Option (b) chosen — timestamp-based fallback with primary env var check.

- **Mechanism:** `session_id = os.environ.get("HERMES_SESSION_ID") or f"pseudo-{int(time.time())}"`
- **Evidence:** Empirical verification not possible from within this executor environment (no Hermes session available to inspect). Research document (02-RESEARCH.md) marks the env var as `[ASSUMED]` without confirmation, and the open questions section recommends defaulting to option (b) if verification cannot be completed.
- **Fallback semantics:** The `pseudo-{timestamp}` fallback produces a new pseudo-session-id on every Python invocation. Markers written from the same Hermes session via separate Python invocations may land in different `.jsonl` files. This is a documented limitation — the cron's Phase 3 session reconciliation against `state.db` is the authoritative cross-check.
- **Frontmatter:** Unchanged. `HERMES_SESSION_ID` NOT added to `required_environment_variables` (option b chosen, not option a).
- **`[ASSUMED]` tag:** Removed. The mechanism is pinned with documented rationale in the snippet comment block.

### Task 2: SKILL.md `## FINAL ACTION — TASK CLASSIFICATION` Section

Appended to `skills/revenium/SKILL.md` after the existing `## Verification` section (line 278), becoming the new file terminus per D-13. Total new content: 140 lines (lines 279–418).

**Section structure (in order):**
1. Heading: `## FINAL ACTION — TASK CLASSIFICATION` (U+2014 em dash per D-14)
2. Framing paragraph — completion-voice register (no prohibition language)
3. D-09 hard rule verbatim in a blockquote
4. `### Examples` — 4 canonical examples per D-10:
   - Example 1: Clear substantive (CLASSIFY) — code review, 2 tool calls, `task_type = code_review`
   - Example 2: Clear trivial (SKIP) — "what is 2+2?", one sentence, no tools
   - Example 3: Borderline classify (CLASSIFY) — 5-paragraph explanation, no tools, rule (b) fires, `task_type = analysis`
   - Example 4: Borderline skip (SKIP) — greeting/confirmation, ≤ 2 sentences, no tools
5. `### Lookup-first reuse` — Python lookup expression, reference to task-taxonomy.md and task-taxonomy.json
6. `### Trivial-label blocklist` — all 6 D-12 tokens: `ack`, `acknowledgment`, `greeting`, `confirmation`, `hello`, `thanks`
7. `### Marker write` — canonical Python snippet (stdlib only: fcntl, json, os, secrets, time; `muid()` with `time.time_ns` + `secrets.token_hex(10)`; `write_marker()` with `open("ab", buffering=0)` + `fcntl.flock(LOCK_EX)`; two `write_marker(...)` calls — GUARDRAIL then CHAT)
8. Closing line — skip semantics and cron fallback to `unclassified`

**Halt-block byte equality:** Confirmed. Line 24 (`## ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)`) is byte-unchanged. The halt block (lines 24–46) was not touched.

**Reserved keywords in new section:** `ABSOLUTE` and `NON-NEGOTIABLE` are NOT present in the new section. Confirmed by `awk + grep` check.

**Commit:** `1625242`

### Task 3: `test_prompt_ordering_invariant` (PROMPT-07)

Added to `tests/test_repository.py` after `test_marker_file_schema` and before `test_shell_scripts_have_valid_syntax`.

```python
def test_prompt_ordering_invariant(self):
    """Halt-check anchor appears before the classification anchor in SKILL.md."""
    text = (SKILL / 'SKILL.md').read_text()
    halt_anchor = 'ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)'
    classify_anchor = 'FINAL ACTION — TASK CLASSIFICATION'
    self.assertIn(halt_anchor, text,
                  'halt-check anchor missing from SKILL.md — do not remove or rename it')
    self.assertIn(classify_anchor, text,
                  'classification anchor missing from SKILL.md — Phase 2 deliverable not present')
    self.assertLess(
        text.index(halt_anchor),
        text.index(classify_anchor),
        'halt-check anchor must appear before classification anchor in SKILL.md',
    )
```

**Em-dash verification:** Both `halt_anchor` and `classify_anchor` string literals contain U+2014 (0xE2 0x80 0x94), confirmed by hex inspection: `em_dash byte sequence e28094`.

**Commit:** `7ab6c51`

## Test Suite Results

All 9 tests pass:

```
test_expected_files_exist                    ok
test_marker_file_schema                      ok
test_no_legacy_branding_left                 ok
test_prompt_ordering_invariant               ok  (NEW)
test_runtime_paths_are_hermes_native         ok
test_shell_scripts_have_valid_syntax         ok
test_skill_frontmatter_has_hermes_metadata   ok
test_taxonomy_atomic_write_pattern           ok
test_taxonomy_file_schema                    ok
Ran 9 tests in 0.134s — OK
```

## Deviations from Plan

**1. [Rule 1 - Bug] Combined import line → separate import lines**
- **Found during:** Task 2 verification
- **Issue:** The initial snippet used `import fcntl, json, os, secrets, time` (one combined line). The Task 2 verify script checks for `import os` as a substring — which fails when os is not the first module in a combined import line.
- **Fix:** Expanded to separate `import fcntl`, `import json`, `import os`, `import secrets`, `import time` lines. This matches the "imports alphabetized" style guideline from PATTERNS.md and is cleaner for human readers.
- **Files modified:** `skills/revenium/SKILL.md`
- **Commit:** `1625242` (fixed before committing)

## Phase 2 Requirement Coverage

All 19 Phase 2 requirement IDs addressed across plans 02-01, 02-02, 02-03:

| ID | Status | Evidence |
|----|--------|----------|
| TAX-01 | DONE | `skills/revenium/task-taxonomy.json` — 8 seed labels (plan 02-01) |
| TAX-02 | DONE | `{description, examples}` schema in task-taxonomy.json and task-taxonomy.md (plan 02-01) |
| TAX-03 | DONE | `^[a-z][a-z0-9_]{1,47}$` enforced by `test_taxonomy_file_schema` (plan 02-01) |
| TAX-04 | DONE | Atomic write pattern documented in references/task-taxonomy.md (plan 02-01) |
| TAX-05 | DONE | Cron fallback to `unclassified` documented; graceful fallback in snippet (plan 02-01/02-03) |
| MARK-01 | DONE | Single O_APPEND write per marker, < 1024 bytes (plan 02-02 TEST-01, plan 02-03 snippet) |
| MARK-02 | DONE | Allow-list fields only: `muid, ts, sid, task_type, operation_type` + optional 4 (plan 02-02/02-03) |
| MARK-03 | DONE | `muid()` = 13-hex-ts + `secrets.token_hex(10)`, 33 chars sortable (plan 02-03 snippet) |
| MARK-04 | DONE | Torn-last-line tolerance documented; cron-side Phase 3 concern (plan 02-01/02-02) |
| MARK-05 | DONE | No free-form text in record dict; allow-list enforces privacy (plan 02-02 TEST-01, plan 02-03) |
| PROMPT-01 | DONE | New section end-loaded after `## Verification` (D-13, this plan) |
| PROMPT-02 | DONE | D-09 hard rule verbatim + 4 examples + D-12 blocklist in new section (this plan) |
| PROMPT-03 | DONE | Lookup-first subsection with taxonomy reference (this plan) |
| PROMPT-04 | DONE | GUARDRAIL write_marker call in canonical snippet (this plan) |
| PROMPT-05 | DONE | Marker write is `### Marker write` — the final subsection (this plan) |
| PROMPT-06 | DONE | `references/task-taxonomy.md` cold-path reference shipped (plan 02-01) |
| PROMPT-07 | DONE | `test_prompt_ordering_invariant` with U+2014 em-dash literals (this plan) |
| TEST-01 | DONE | `test_marker_file_schema` with inline fixture (plan 02-02) |
| TEST-02 | DONE | `test_taxonomy_file_schema` with D-06 label order (plan 02-01) |

## Pre-Merge Gate Reminder

**Operator action required before merging Phase 2:**

Run at least Scenario 1 (short session × Claude Sonnet 4.6) from
`skills/revenium/references/halt-survivability.md`. The automated test
`test_prompt_ordering_invariant` is a structural guard but NOT a behavioral
guard — it does not verify that the agent actually emits the halt string
verbatim when `halted: true`. The halt-survivability runbook is the empirical
regression check required by D-03.

## Hand-off Note for Phase 3

The marker record shape is pinned by two independent sources:

1. **SKILL.md canonical snippet** (this plan) — the agent's write-time contract:
   - Required fields: `muid, ts, sid, task_type, operation_type`
   - `muid`: 33-char lowercase hex (13-ts + 20-random)
   - `task_type`: matches `^[a-z][a-z0-9_]{1,47}$`
   - `operation_type`: from OpenInference span_kind vocabulary (`CHAT`, `GUARDRAIL`, etc.)
   - Line budget: < 1024 bytes UTF-8

2. **`test_marker_file_schema`** (plan 02-02 TEST-01) — the CI contract:
   - Validates fixture records against allow-list
   - Enforces `muid` regex `^[0-9a-f]{33}$`
   - Enforces operation_type span_kind set
   - Enforces < 1024 byte budget

Phase 3 cron-side marker reader can rely on this contract without re-deriving it. The
session-id in marker filenames may be a `pseudo-{timestamp}` for installs where
`HERMES_SESSION_ID` is not set by Hermes — Phase 3 reconciliation against `state.db` rows
should treat markers as "groupable-per-file" rather than requiring session-id equality
with `state.db` session rows.

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| `skills/revenium/SKILL.md` exists | FOUND |
| `tests/test_repository.py` exists | FOUND |
| `02-03-SUMMARY.md` exists | FOUND |
| Commit `1625242` (Task 2) exists | FOUND |
| Commit `7ab6c51` (Task 3) exists | FOUND |
| `FINAL ACTION — TASK CLASSIFICATION` in SKILL.md | OK |
| `[ASSUMED]` not in SKILL.md | OK |
| `ABSOLUTE FIRST — HALT CHECK` precedes `FINAL ACTION` | OK |
| em dash in test halt_anchor literal | OK |
| All 9 tests pass | OK (9 tests, 0 failures) |
