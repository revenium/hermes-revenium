---
phase: 260514-nfb-rewrite-classifier-prompt-to-mint-first-
plan: 01
status: complete
requirements:
  - PROMPT-MINT-FIRST
files_modified:
  - skills/revenium/plugins/revenium-classifier/classifier.py
  - tests/test_repository.py
completed_date: 2026-05-14
commits:
  - T01: e079144 — feat(classifier): rewrite _build_classification_prompt to mint-first bias
---

# Phase 260514-nfb Plan 01: Mint-First Prompt Rewrite Summary

**One-liner:** Rewrote `_build_classification_prompt` from lookup-first to mint-first framing so the LLM mints specific descriptive labels (e.g., `weekly_pr_review`, `prod_log_triage`) instead of collapsing every output-producing turn to `generation`.

## What Shipped

### `skills/revenium/plugins/revenium-classifier/classifier.py`

Replaced the body of `_build_classification_prompt` with a four-part mint-first prompt:

1. **Anchor phrase:** "Mint a SPECIFIC, DESCRIPTIVE label" as the primary instruction (replaces the old "Pick the single best-fitting existing label" lookup-first framing).
2. **Concrete examples:** `weekly_pr_review`, `prod_log_triage`, `news_summary`, `sql_query_debug`, `release_notes_draft` — anchors the LLM to 2-4 word granularity.
3. **AVOID line:** Explicitly names `generation`, `analysis`, `review`, `task` as bland catch-alls to avoid when a more specific label fits.
4. **Narrow reuse exception:** Existing labels are framed as "you MAY reuse, but only if they describe the SAME specific work" — reuse is the exception, not the default.

Preserved unchanged: function signature `(user_msg, assistant_resp, labels) -> str`, regex contract `^[a-z][a-z0-9_]{1,47}$`, TRIVIAL_BLOCKLIST forbidden-labels line, labels_block cap (≤1024 chars), user/assistant preview caps (≤800 chars each), all surrounding helpers and globals.

### `tests/test_repository.py`

Added `test_revenium_classifier_prompt_mint_first_bias` (test 40 of 40) — a regression guard that:

- Calls `_build_classification_prompt("user message text", "assistant response text", ["generation", "code_review", "research"])`.
- Asserts the mint-first anchor phrase is present.
- Asserts all five concrete example labels are present.
- Asserts the AVOID line naming `generation` is present.
- Asserts the regex contract `^[a-z][a-z0-9_]{1,47}$` is present.
- Asserts the forbidden-labels line containing `ack` is present.
- Asserts the old "Pick the single best-fitting existing label" framing is absent.
- Asserts `len(result) <= 4096` (prompt-size invariant).

The two pre-existing classifier tests (`test_revenium_classifier_llm_label`, `test_revenium_classifier_llm_blocklist_fallthrough`) pass unchanged — they mock `call_llm`'s return value and do not inspect the prompt text.

## Why This Change Was Needed

Live evidence from Mac Studio showed 12 of the last 16 markers in 24 hours landed on `task_type=generation`. The seed taxonomy had not grown in days. Root cause: the old "Pick the single best-fitting existing label; if NONE fit, mint" framing caused the LLM to treat the eight seed labels as a near-exhaustive lookup table — it almost never minted. After the D-07 fix landed in commit `a9f9411` (quick task 260514-n8e), the classifier fires on every session, fully exposing the prompt bias as the only remaining barrier to useful per-task-type spend attribution.

## Files Touched

| File | Change |
|------|--------|
| `skills/revenium/plugins/revenium-classifier/classifier.py` | Rewrote `_build_classification_prompt` body (lines 219-249); all other code byte-unchanged |
| `tests/test_repository.py` | Added `test_revenium_classifier_prompt_mint_first_bias` after line 1339 |

## Verification

All four checks pass:

- `python3 -m py_compile skills/revenium/plugins/revenium-classifier/classifier.py` — exits 0
- `python3 -m unittest discover -s tests -p 'test_*.py' -v` — 40 tests, OK
- `grep -c 'Mint a SPECIFIC, DESCRIPTIVE label' skills/revenium/plugins/revenium-classifier/classifier.py` — returns 1
- `grep -c 'weekly_pr_review' skills/revenium/plugins/revenium-classifier/classifier.py` — returns 1
- `grep -c 'Pick the single best-fitting existing label' skills/revenium/plugins/revenium-classifier/classifier.py` — returns 0

## Decisions Made

**Atomic T01 (code + test in one commit):** The regression guard and the prompt rewrite were committed together so the test suite is always green at every commit boundary — there is no intermediate state where the new assertions exist but the implementation does not yet satisfy them. This matches the plan's must-have that "full test suite stays green at the single commit boundary."

**Minimal import approach for the new test:** `_build_classification_prompt` reads no state (no env vars, no files), so the new test uses the same `_setup_plugin_env` / `_restore_plugin_env` scaffolding as neighboring tests for consistency, even though only the sys.path setup and module reload are strictly needed. This keeps the test pattern uniform with the rest of the classifier test suite.

## Follow-ups / Out of Scope

**Real-world bias-shift verification:** Whether the LLM now mints specific labels (vs. collapsing to `generation`) can only be confirmed from the next 24-48 hours of cron markers on Mac Studio. That observation is not part of this commit — it is an operational follow-up. If the distribution still shows heavy `generation` bias after this change, the next step is to inspect the LLM's actual prompt via logging or to increase the temperature slightly from 0.0.

**Taxonomy growth strategy:** This commit only changes what the LLM is instructed to do. A follow-up task could add a periodic review step that consolidates near-duplicate minted labels (e.g., `pr_review` and `code_review` and `weekly_pr_review` all describing the same work). That is out of scope here.
