---
phase: 260514-n8e-remove-d-07-trivial-skip-from-classifier
plan: 01
status: complete
requirements:
  - HOTFIX-D07-MIRROR
files_modified:
  - skills/revenium/plugins/revenium-classifier/classifier.py
  - tests/test_repository.py
completed_date: "2026-05-14"
commits:
  - hash: a9f9411
    message: "fix(classifier): mirror Mac Studio hotfix — remove D-07 trivial-skip"
---

# Phase 260514-n8e Plan 01: Remove D-07 Trivial-Skip from Classifier Summary

**One-liner:** Removed D-07 heuristic skip predicate from `run_classification_async` that silently dropped ~94% of cron-fired no-tools sessions due to `response=None` always being passed from the plugin entrypoint.

## What Shipped

- **`skills/revenium/plugins/revenium-classifier/classifier.py`**: Deleted the 5-line D-07/HOOK-02 skip block (`# Step 2 — heuristic skip-fast-path`) from `run_classification_async`. The block contained `response_preview = response or ""`, `tool_count = _count_tools_in_current_turn(session_id)`, and the conditional `if tool_count == 0 and len(response_preview) < 200: return`. Relocated `response_preview = response or ""` to just before Step 5 (LLM classification call) where the variable is still needed. `_count_tools_in_current_turn` helper definition preserved — 19 downstream tests reference it and continue to pass.

- **`tests/test_repository.py`**: Renamed `test_revenium_classifier_trivial_skip` to `test_revenium_classifier_no_tools_classified_not_skipped`. Updated docstring to reflect the HOTFIX D-07 mirror contract. Inverted the final assertion from `assertFalse(marker exists)` to `assertTrue(marker exists)` — with `call_llm is None` in the test environment, the classifier now falls through to `_classify_via_llm` → `unclassified` → `_write_marker_pair` → marker file present.

## Why This Change Was Needed

**Root cause:** `skills/revenium/plugins/revenium-classifier/__init__.py` line 84 always passes `response=None` to `run_classification()`. With `response=None`, `response_preview = response or ""` always produces an empty string, making `len(response_preview) < 200` permanently `True`. This collapsed the D-07 predicate to just `tool_count == 0`, which is true for the majority of cron-fired sessions — those that answer from internal knowledge without invoking tools. Result: ~94% of legitimate classification candidates were silently dropped before reaching the LLM classifier.

**Live diagnosis on Mac Studio:** The bug was identified when cron sessions with `tool_call_count=0` produced no markers. The D-07 skip block was removed from the live install at `~/.hermes/plugins/revenium-classifier/classifier.py`. A backup was retained at `~/.hermes/plugins/revenium-classifier/classifier.py.bak.1778789306`. The gateway was restarted at 20:14 UTC 2026-05-14. A post-restart cron session with `tool_call_count=0` (`cron_1e6c1d2a1cd0_20260514_162536`) successfully produced a marker with `task_type=generation`, confirming the fix is effective. This repo commit mirrors that live patch so the source of truth and the deployment are byte-identical.

## Files Touched

| File | Change |
|------|--------|
| `skills/revenium/plugins/revenium-classifier/classifier.py` | D-07 skip block deleted (lines 349-354 in prior version); `response_preview = response or ""` relocated to just before Step 5 LLM call; docstring updated to remove "heuristic skip" reference |
| `tests/test_repository.py` | `test_revenium_classifier_trivial_skip` renamed to `test_revenium_classifier_no_tools_classified_not_skipped`; assertion inverted from `assertFalse` to `assertTrue`; docstring updated |

## Verification

- `python3 -m unittest discover -s tests -p 'test_*.py' -v` passes green at both commit boundaries (T01 code+test, T02 summary). All 39 tests OK.
- `grep -c '^def _count_tools_in_current_turn' skills/revenium/plugins/revenium-classifier/classifier.py` returns `1` — helper preserved.
- No `D-07 / HOOK-02` step header or `len(response_preview) < 200` predicate remains in `classifier.py`.
- `test_revenium_classifier_no_tools_classified_not_skipped` exists; `test_revenium_classifier_trivial_skip` does not.
- `python3 -m py_compile` exits 0 for both modified files.
- The 19 downstream tests referencing `_count_tools_in_current_turn` (test lines 1054, 1151, 1234, 1286, 1340, 1394, 1416, 1486, 1536, 1567, 1605, 1651, 1677, 1761, 1821, 1881, 1985, 2085, 2187) continue to pass unchanged.

## Live-Environment Evidence

- **Backup path:** `~/.hermes/plugins/revenium-classifier/classifier.py.bak.1778789306` (Mac Studio)
- **Gateway restart:** 20:14 UTC 2026-05-14
- **Post-restart confirmation:** cron session `cron_1e6c1d2a1cd0_20260514_162536` with `tool_call_count=0` produced a marker with `task_type=generation`
- **Repo now matches live install:** byte-identical `classifier.py`

## Decisions Made

- `_count_tools_in_current_turn` kept intact — it remains relevant for logging/future use and its 19 test references provide a regression safety net.
- Step numbers in the remaining `run_classification_async` comments (Step 3, 4, 5, 6) left as-is — renumbering would widen the diff with no benefit.
- `response_preview` placement: moved to immediately before Step 5 LLM call (closest first-use) to keep the diff minimal and readable.

## Follow-ups / Out of Scope

None for this quick task. If a future change rewires `__init__.py` to pass an actual response string, a separate evaluation of whether to reintroduce a length-based skip (with a different degeneration guard) can be done at that point — not here.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- `skills/revenium/plugins/revenium-classifier/classifier.py` modified: FOUND
- `tests/test_repository.py` modified: FOUND
- Commit `a9f9411` exists: FOUND
- Full test suite: 39 tests, OK
