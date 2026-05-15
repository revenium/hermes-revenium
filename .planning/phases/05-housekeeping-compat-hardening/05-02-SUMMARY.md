---
phase: 05-housekeeping-compat-hardening
plan: 02
type: execute
subsystem: classifier
requirements_completed:
  - COMPAT-04
  - TEST-05
files_modified:
  - skills/revenium/plugins/revenium-classifier/classifier.py
  - tests/test_repository.py
files_created:
  - .planning/phases/05-housekeeping-compat-hardening/05-02-SUMMARY.md
tests_added: 2
tests_modified: 0
tests_total_after: 44
commits:
  - T01: d9ddb85
  - T02: b9237ec
  - T03: (this commit)
tags:
  - classifier
  - taxonomy-mint-back
  - recency-ordering
  - schema-evolution
decisions:
  - D-32: persist minted labels to task-taxonomy.json via atomic tmp+os.replace; fail-open
  - D-33: _read_taxonomy_labels returns recent-first within 7-day bucket, alpha within older+undated
tech_stack:
  added: []
  patterns:
    - atomic temp-file + os.replace for taxonomy writes (same guarantee as _write_marker_pair fcntl.LOCK_EX)
key_files:
  created:
    - .planning/phases/05-housekeeping-compat-hardening/05-02-SUMMARY.md
  modified:
    - skills/revenium/plugins/revenium-classifier/classifier.py
    - tests/test_repository.py
metrics:
  duration_minutes: 25
  completed_date: "2026-05-15T01:04:31Z"
---

# Phase 05 Plan 02: classifier mint-back (D-32) + recency-order sort (D-33) Summary

**One-liner:** Classifier now persists minted labels back to task-taxonomy.json with ISO timestamps and returns them recent-first so the LLM sees the project's live vocabulary at the top of every prompt.

## Outcome

Two atomic commits close the feedback loop opened by the 260514-nfb mint-first prompt rewrite:

- **D-32 (T01):** `_persist_label_to_taxonomy(label)` helper added. After every successful `_write_marker_pair` call (subagent inheritance path + LLM-classified path), the helper writes the label back to `task-taxonomy.json` with a `last_seen_at` ISO timestamp. New labels mint with `{description: null, examples: [], last_seen_at: <ISO>}`; existing labels get `last_seen_at` updated (lazy migration of seed entries). The `'unclassified'` sentinel is explicitly excluded. Fail-open: any I/O error is logged as a warning and never propagates — marker writes are never affected.

- **D-33 (T02):** `_read_taxonomy_labels()` rewritten to sort labels recent-first within a 7-day bucket, then alphabetical among older and undated labels. Seed entries (no `last_seen_at` field) sort at the end — intentional lazy migration. ISO timestamp parsing errors fall back to the older bucket (D-04 fail-open). The 1024-byte cap on `labels_block` in `_build_classification_prompt` is preserved byte-unchanged.

## Decisions Honored

### D-32
- `_persist_label_to_taxonomy` inserted after `_validate_label` (line 370 in the post-edit file)
- Two call sites in `run_classification_async`: after subagent inheritance `_write_marker_pair` (line 465) and after LLM-classified `_write_marker_pair` (line 499)
- Budget-halted `'unclassified'` path (line 475) receives NO mint-back call — sentinel preserved as non-taxonomy
- Atomic write: `tmp = TAXONOMY_FILE.parent / (TAXONOMY_FILE.name + ".tmp")` + `tmp.replace(TAXONOMY_FILE)` — same filesystem, POSIX atomic
- `task-taxonomy.json` seed file byte-unchanged (lazy migration only triggers on first label reuse)

### D-33
- `_read_taxonomy_labels` sorted pre-sort (`sorted(labels.items())`) acts as the tie-break key within each bucket
- 7-day recency cutoff (`datetime.timedelta(days=7)`) relative to UTC now
- `_build_classification_prompt` body byte-unchanged; it consumes the return value of `_read_taxonomy_labels` verbatim

## Key Files

| File | Change |
|------|--------|
| `skills/revenium/plugins/revenium-classifier/classifier.py` | Added `_persist_label_to_taxonomy` helper (lines 370-408); rewrote `_read_taxonomy_labels` (lines 254-285); added 2 call sites in `run_classification_async` |
| `tests/test_repository.py` | Appended `test_read_taxonomy_labels_recency_order` (line 3213) and `test_persist_label_to_taxonomy_mint_and_update` (line 3244) |

## Verification

```
Ran 44 tests in ~12s
FAILED (failures=1)   # pre-existing: test_no_legacy_branding_left scans .claude/worktrees/ planning docs
```

The pre-existing failure (`test_no_legacy_branding_left`) is a worktree-scope artifact: the test greps the `.claude/worktrees/` directory which contains planning documents. This failure existed before Plan 05-02 (42 → 43 → 44 tests with 1 failure throughout). All 43 other tests pass.

New tests verified individually:
- `test_persist_label_to_taxonomy_mint_and_update`: PASS — mints new label, updates existing last_seen_at, refuses sentinel
- `test_read_taxonomy_labels_recency_order`: PASS — [beta_recent, alpha_old, gamma_seed] order confirmed

## Operator Verification

After `examples/setup-local.sh` install and a few Hermes sessions, inspect:

```bash
cat ~/.hermes/state/revenium/task-taxonomy.json | python3 -m json.tool
```

Expect: newly-minted labels present with `last_seen_at` timestamps. Seed labels (`research`, `analysis`, etc.) appear without `last_seen_at` until first reuse. Labels with recent timestamps appear first in classification prompts.

## Out of Scope Carried Forward

- `_count_tools_in_current_turn` and its 4 tests: byte-unchanged (D-37 KEEP)
- `__init__.py` (`_on_session_end` entrypoint): byte-unchanged
- `_build_classification_prompt` body: byte-unchanged
- `skills/revenium/task-taxonomy.json` seed file: byte-unchanged
- `hermes-report.sh` WR-01/WR-02: Plan 05-03
- Phase 4 wire-test `base_env` WR-03 extension: Plan 05-03
- README / setup.md / task-taxonomy.md / PROJECT.md doc audit: Plan 05-04

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- `skills/revenium/plugins/revenium-classifier/classifier.py` — modified, verified with grep
- `tests/test_repository.py` — modified, new tests at lines 3213 and 3244
- T01 commit `d9ddb85` — verified in git log
- T02 commit `b9237ec` — verified in git log
- `_count_tools_in_current_turn` untouched (line 79)
- `_build_classification_prompt` body untouched (line 268)
- `__init__.py` untouched
- `task-taxonomy.json` untouched
