---
phase: 05-housekeeping-compat-hardening
plan: 04
type: execute
executed: 2026-05-14
requirements_completed:
  - COMPAT-04
  - TEST-05
files_modified:
  - .planning/PROJECT.md
  - .planning/REQUIREMENTS.md
  - .planning/ROADMAP.md
  - README.md
  - docs/installation.md
  - skills/revenium/references/setup.md
  - skills/revenium/references/task-taxonomy.md
files_created:
  - .planning/phases/05-housekeeping-compat-hardening/05-04-SUMMARY.md
tests_added: 0
tests_modified: 0
tests_total_after: 45
commits:
  - T01: 490ef24
  - T02: 89506a2
  - T03: eb20b85
  - T04: 3e10488
  - T05: 97a4c9a
  - T06: (this commit)
tags:
  - documentation
  - truth-refresh
  - requirements-flip
  - roadmap-finalize
dependency_graph:
  requires:
    - 05-01 (prune-markers.sh shipped)
    - 05-02 (classifier mint-back + recency sort shipped)
    - 05-03 (WR-01/WR-02/WR-03 shipped)
  provides:
    - PROJECT.md D-3/D-8 current with shipping code
    - Evolution Notes section (dated transition history)
    - setup.md Marker file pruning operator runbook
    - task-taxonomy.md mint-first framing
    - README.md prune-markers.sh entry
    - docs/installation.md Operational hygiene section
    - REQUIREMENTS.md COMPAT-04 + TEST-05 verified
    - ROADMAP.md Phase 5 finalized (4/4 Executed 2026-05-14)
  affects:
    - Future agents reading PROJECT.md (no longer see stale D-3/D-8 framing)
    - Operators reading setup.md (see prune runbook)
    - Operators reading docs/installation.md (see Operational hygiene section)
tech_stack:
  added: []
  patterns:
    - Evolution Notes dated-transition format for PROJECT.md decision history
    - Docs-only plan: 6 atomic commits, no code changes
key_files:
  created:
    - path: .planning/phases/05-housekeeping-compat-hardening/05-04-SUMMARY.md
      summary: Phase 5 Plan 04 summary and Phase 5 roll-up
  modified:
    - path: .planning/PROJECT.md
      summary: D-3 rewritten to mint-first framing (Shipped Phase 5); D-8 rewritten to D-07 dead-code removal (Shipped Phase 5); new ## Evolution Notes section appended; footer updated to 2026-05-14
    - path: README.md
      summary: prune-markers.sh entry added to ## Manual commands between clear-halt.sh and install-cron.sh
    - path: docs/installation.md
      summary: New ## Operational hygiene section appended covering prune-markers.sh invocation, --dry-run, REVENIUM_MARKER_RETENTION_DAYS, marker location, and setup.md cross-reference
    - path: skills/revenium/references/setup.md
      summary: New ## Marker file pruning section appended after ## Mechanical classification hook; documents D-26/D-27/D-28/D-29 operator runbook with manual UAT triple-case
    - path: skills/revenium/references/task-taxonomy.md
      summary: Opening paragraph rewritten from lookup-first to mint-first; Mint policy section body rewritten to mint-first framing citing 260514-nfb and D-32 classifier persistence
    - path: .planning/REQUIREMENTS.md
      summary: COMPAT-04 + TEST-05 checkboxes flipped to [x]; traceability rows updated to Verified (Phase 5); footer updated to Phase 5 reference
    - path: .planning/ROADMAP.md
      summary: Phase 5 checkbox flipped to [x]; Plans list 4 entries all [x]; Progress Table 4/4 Executed 2026-05-14
metrics:
  duration_minutes: ~25
  tasks_completed: 6
  files_changed: 7
decisions:
  - D-30 PROJECT.md D-3/D-8 rewrites in place; Evolution Notes section captures dated transition history with quick task citations
  - D-31 doc audit across README.md, setup.md, task-taxonomy.md, docs/installation.md — all stale lookup-first/trivial-skip references rewritten or removed
---

# Phase 5 Plan 04: Docs Sweep + Requirements/Roadmap Finalize Summary

**One-liner:** Docs sweep closes Phase 5 — D-3/D-8 rewritten in PROJECT.md with dated Evolution Notes; task-taxonomy.md and setup.md updated to mint-first and prune-operator framing; REQUIREMENTS.md COMPAT-04/TEST-05 verified; ROADMAP.md Phase 5 finalized 4/4 Executed.

## Outcome

Six atomic commits bring all project documentation into sync with the shipping code and close Phase 5's two open requirements (COMPAT-04, TEST-05):

- **T01 (PROJECT.md):** D-3 row rewritten from "Controlled-vocabulary taxonomy with strict lookup-first reuse" to "LLM mints specific labels; reuses only on exact match (Shipped Phase 5)"; D-8 row rewritten from "Classify substantive turns only" to "D-07 heuristic skip removed (was dead code) (Shipped Phase 5)". Seven other Key Decisions rows unchanged. New `## Evolution Notes` section at EOF records the dated transitions (2026-05-14 / D-3 / 260514-nfb; 2026-05-14 / D-8 / 260514-n8e). Footer updated to Phase 5 reference.

- **T02 (README.md):** Single localized edit — two-line prune-markers.sh block inserted into `## Manual commands` between `clear-halt.sh` and `install-cron.sh`. No structural changes.

- **T03 (docs/installation.md):** New `## Operational hygiene` section appended documenting `prune-markers.sh` invocation with `--dry-run`, default 30-day retention, `REVENIUM_MARKER_RETENTION_DAYS` env override, marker file location, and cross-reference to `references/setup.md` for the full runbook. Closes Phase 5 SC3 (docs/installation.md half of the contract).

- **T04 (setup.md):** New `## Marker file pruning` section appended after `## Mechanical classification hook` (heading line 88 byte-unchanged). Documents D-26 ledger-based stale check, D-27 env override, D-28 operator-only invocation, D-29 dry-run + LOG_FILE audit logging. Manual UAT triple-case (old/fresh/orphan fixture) embedded from CONTEXT.md specifics.

- **T05 (task-taxonomy.md):** Opening paragraph rewritten to mint-first framing with citation to quick task 260514-nfb and D-32 classifier-side persistence. `## Mint policy` section body rewritten — minting is the default, reuse is the narrow exception; cites classifier plugin auto-persistence via atomic write pattern. No stale D-07/trivial-skip/lookup-first references remain.

- **T06 (REQUIREMENTS.md + ROADMAP.md + SUMMARY):** COMPAT-04 and TEST-05 checkboxes flipped to `[x]`; traceability rows updated to "Verified (Phase 5)"; REQUIREMENTS.md footer updated. ROADMAP.md Phase 5 checkbox `[x]`; Plans list all `[x]`; Progress Table `4/4 / Executed / 2026-05-14`.

All 45 tests pass at every commit boundary.

## Decisions Honored

### D-30 — PROJECT.md truth refresh

D-3 and D-8 rewrites are applied in-place with "Shipped (Phase 5)" outcome marker. The exact text follows the plan's must-have specification: D-3 → "LLM mints specific labels; reuses only on exact match"; D-8 → "D-07 heuristic skip removed (was dead code)". Seven other Key Decisions rows (D-1, D-2, D-4, D-5, D-6, D-7, D-9) remain byte-unchanged. The new `## Evolution Notes` section preserves transition history so future readers can trace why decisions changed (format: Date / Decision / Quick Task / Change Summary), making the PROJECT.md self-consistent across time without erasing the earlier rationale.

### D-31 — Doc audit across README.md, setup.md, task-taxonomy.md, docs/installation.md

Each file committed independently (small, isolated, low cross-coupling). Audit confirmed:
- `README.md`: no "lookup-first" phrase existed; only edit is the new prune-markers.sh entry.
- `setup.md`: existing `## How attribution works` and `## Mechanical classification hook` sections correctly describe shipping behavior; only edit is appending the new `## Marker file pruning` section.
- `task-taxonomy.md`: two localized rewrites (opening paragraph + Mint policy body); no stale references remain.
- `docs/installation.md`: pre-existing sections byte-unchanged; only edit is appending `## Operational hygiene`.

## Key Files

| File | Change | Commit |
|------|--------|--------|
| `.planning/PROJECT.md` | D-3/D-8 rows rewritten; ## Evolution Notes section appended; footer updated | 490ef24 |
| `README.md` | prune-markers.sh entry in ## Manual commands | 89506a2 |
| `docs/installation.md` | ## Operational hygiene section appended | eb20b85 |
| `skills/revenium/references/setup.md` | ## Marker file pruning section appended | 3e10488 |
| `skills/revenium/references/task-taxonomy.md` | Opening paragraph + ## Mint policy body rewritten to mint-first | 97a4c9a |
| `.planning/REQUIREMENTS.md` | COMPAT-04 + TEST-05 [x]; traceability Verified (Phase 5); footer updated | T06 |
| `.planning/ROADMAP.md` | Phase 5 [x]; 4-entry Plans list all [x]; Progress Table 4/4 Executed 2026-05-14 | T06 |

## Verification

```
python3 -m unittest discover -s tests -p 'test_*.py' -v
Ran 45 tests in ~13s
OK
```

Confirmed at every commit boundary (T01 through T06).

- `test_no_legacy_branding_left` — passes against all modified files (no forbidden product names introduced)
- `test_setup_md_has_mechanical_classification_hook_section` — passes; heading at line 88 byte-unchanged after T04
- `test_skill_frontmatter_has_hermes_metadata` — unaffected (no SKILL.md touch)
- `test_runtime_paths_are_hermes_native` — unaffected (no common.sh touch)

## Phase 5 Roll-up

Phase 5: Housekeeping & Compat Hardening shipped as 4 plans across 2 waves. All Phase 5 success criteria (SC1, SC2, SC3) are now verified.

### Plan 05-01 (Wave 1) — prune-markers.sh + common.sh retention knob
**SUMMARY:** `.planning/phases/05-housekeeping-compat-hardening/05-01-SUMMARY.md`

Shipped `prune-markers.sh` — an operator-invoked script that removes stale marker JSONL files using ledger-based stale check (D-26), mtime fallback for orphans, flock gate (D-29), and `--dry-run` flag. Two new declarations added to `common.sh` (`MARKER_RETENTION_DAYS`, `PRUNE_LOCK_FILE`). One new E2E test (`test_prune_markers_dry_run_and_live`) verifying all three D-29 sub-cases. Test suite: 42 tests at completion.

Key commits: `5ed83a7` (feat: common.sh + prune-markers.sh scaffold), `93221c7` (test: E2E prune test).

### Plan 05-02 (Wave 1) — classifier mint-back (D-32) + recency-order sort (D-33)
**SUMMARY:** `.planning/phases/05-housekeeping-compat-hardening/05-02-SUMMARY.md`

Closed the mint-feedback loop: `_persist_label_to_taxonomy` helper persists newly-minted labels back to `task-taxonomy.json` with ISO `last_seen_at` timestamps (D-32). `_read_taxonomy_labels` rewritten to sort recent-first within a 7-day bucket (D-33). Two new tests (`test_persist_label_to_taxonomy_mint_and_update`, `test_read_taxonomy_labels_recency_order`). Test suite: 44 tests at completion.

Key commits: `d9ddb85` (feat: D-32 mint-back), `b9237ec` (feat: D-33 recency sort).

### Plan 05-03 (Wave 1) — Phase 4 review WRs cleanup
**SUMMARY:** `.planning/phases/05-housekeeping-compat-hardening/05-03-SUMMARY.md`

Three Phase 4 review WRs closed: WR-01 pipe-safety sanitization of `|`/`\n`/`\r` in split_rows heredoc (D-34); WR-02 dead `local row` variable removed from while-read declaration (D-35); WR-03 `base_env` extended with three `REVENIUM_*` env overrides in two Phase 4 wire test methods (D-36). One new test (`test_hermes_report_pipe_safety_marker_sanitization`); two tests modified (WR-03 base_env extensions). Test suite: 45 tests at completion.

Key commits: `eb23d8d` (feat: WR-01/D-34 + regression test), `ed87520` (refactor: WR-02/D-35 dead-var removal), `c3be715` (test: WR-03/D-36 env isolation).

### Plan 05-04 (Wave 2) — Docs sweep + Requirements/Roadmap finalize
**SUMMARY:** this file

Docs sweep brings all project documentation into sync with shipping code. D-3/D-8 rewritten in PROJECT.md with Evolution Notes. task-taxonomy.md and setup.md updated to mint-first and prune-operator framing. README.md and docs/installation.md gain prune-markers.sh entries. REQUIREMENTS.md COMPAT-04/TEST-05 verified. ROADMAP.md Phase 5 finalized 4/4. Test suite: 45 tests (unchanged — no test changes in this plan).

### Phase 5 Success Criteria Status

| Criterion | Status | Closed By |
|-----------|--------|-----------|
| SC1: prune-markers.sh operator UAT runbook documented | Verified | 05-01 (shipped), 05-04/T04 (runbook in setup.md) |
| SC2: Full suite green (45 tests, OK) at every commit | Verified | All 4 plans maintained green at every commit boundary |
| SC3: docs/installation.md + setup.md describe marker/taxonomy contract + prune invocation | Verified | 05-04/T03 (docs/installation.md) + 05-04/T04 (setup.md) |

## Out of Scope Carried Forward

Per the plan scope locks (D-37, D-38):

- `_count_tools_in_current_turn` helper and its tests: byte-unchanged (D-37 explicit KEEP). Will be revisited in v1.1 if zero callers remain.
- No changes to any code file (classifier.py, hermes-report.sh, common.sh, prune-markers.sh, tests/test_repository.py, SKILL.md, scripts/*.sh, plugins/) — all code landed in Plans 05-01/05-02/05-03.
- No new test methods or test modifications.
- halt-survivability.md / troubleshooting.md: not touched (confirmed not actively contradicting shipping behavior).

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| `.planning/PROJECT.md` D-3 row rewritten to mint-first | FOUND |
| `.planning/PROJECT.md` D-8 row rewritten to D-07 dead-code | FOUND |
| `.planning/PROJECT.md` ## Evolution Notes section appended | FOUND |
| `README.md` prune-markers.sh entry in ## Manual commands | FOUND |
| `docs/installation.md` ## Operational hygiene section | FOUND |
| `skills/revenium/references/setup.md` ## Marker file pruning section | FOUND |
| `skills/revenium/references/task-taxonomy.md` mint-first framing | FOUND |
| `.planning/REQUIREMENTS.md` COMPAT-04 [x] | FOUND |
| `.planning/REQUIREMENTS.md` TEST-05 [x] | FOUND |
| `.planning/REQUIREMENTS.md` traceability Verified (Phase 5) | FOUND |
| `.planning/ROADMAP.md` Phase 5 [x] | FOUND |
| `.planning/ROADMAP.md` Progress Table 4/4 Executed 2026-05-14 | FOUND |
| T01 commit 490ef24 | FOUND |
| T02 commit 89506a2 | FOUND |
| T03 commit eb20b85 | FOUND |
| T04 commit 3e10488 | FOUND |
| T05 commit 97a4c9a | FOUND |
| Test suite: 45 tests, OK | PASSED |
| test_no_legacy_branding_left | PASSED |
| test_setup_md_has_mechanical_classification_hook_section | PASSED |
