---
phase: 260514-nz8-add-state-db-message-lookup-to-classifie
plan: 01
status: complete
requirements:
  - STATE-DB-MSG-LOOKUP
files_modified:
  - skills/revenium/plugins/revenium-classifier/classifier.py
  - tests/test_repository.py
completed_date: 2026-05-14
commits:
  - "T01: 83bcac6 — feat(classifier): read last user+assistant messages from state.db when entrypoint passes None"
---

# Phase 260514-nz8 Plan 01: State.db Message Lookup Summary

**One-liner:** Added `_read_session_messages(sid)` to the classifier and wired it into `run_classification_async` Step 5 so the LLM receives the actual last user and assistant messages from `state.db.messages` instead of empty strings when the plugin entrypoint passes `message=None, response=None`.

## What Shipped

### `skills/revenium/plugins/revenium-classifier/classifier.py`

**New helper `_read_session_messages(sid)`** (inserted between `_count_tools_in_current_turn` and `_read_latest_task_type`):

- Opens `state.db` in read-only URI mode (`file:...?mode=ro`, matching the pattern used by `_walk_to_root_session` and `_count_tools_in_current_turn`) with a 2-second timeout.
- Queries `SELECT role, content FROM messages WHERE session_id = ? AND content IS NOT NULL AND content != '' ORDER BY timestamp DESC` and captures the first `user` and first `assistant` rows by walking the descending-timestamp cursor.
- Returns `(last_user_content, last_assistant_content)` as a `tuple[str, str]`.
- Returns `("", "")` if `sid` is falsy, if `STATE_DB.exists()` is `False`, or on any exception (D-04 invariant — the helper never raises).
- Uses the module-level `STATE_DB` constant rather than recomputing `HERMES_HOME / "state.db"` inline, matching the existing conventions in `_walk_to_root_session` and `_count_tools_in_current_turn`.

**Modified Step 5 in `run_classification_async`** (replaced the old 5-line block):

- When `not message or not response`, calls `_read_session_messages(session_id)` and resolves `user_msg` / `asst_resp` by preferring the caller's explicit content over the state.db values.
- When both `message` and `response` are provided (the existing test path), takes the `else` branch and passes them straight through — no state.db lookup occurs.
- Removed the old `response_preview = response or ""` single-liner; `asst_resp or ""` in the `_classify_via_llm` call replaces it.

Preserved unchanged: `_walk_to_root_session`, `_count_tools_in_current_turn`, `_read_latest_task_type`, `_recent_marker_pair_exists`, `_budget_halted`, `_read_taxonomy_labels`, `_build_classification_prompt`, `_classify_via_llm`, `_validate_label`, `_muid`, `_write_marker_pair`, `run_classification`, all module-level constants, and the lazy `try: from agent.auxiliary_client import call_llm` block.

### `tests/test_repository.py`

Added `test_revenium_classifier_reads_state_db_content` (test 41 of 41) — inserted after `test_revenium_classifier_plugin_entrypoint`. The test:

- Uses `_setup_plugin_env` / `_restore_plugin_env` and a `tempfile.mkdtemp(prefix='gsd-hook-statedb-msg-')` tmp directory.
- Builds a `state.db` with `sessions` and `messages` tables. Inserts session row `(sid, None, 1)` and two messages: `(sid, 'user', 'Summarize today news headlines', None, 1000)` and `(sid, 'assistant', 'Top stories: ...', None, 1001)`.
- After reloading `classifier` so `STATE_DB` resolves to the tmp path, directly asserts `_read_session_messages(sid) == ("Summarize today news headlines", "Top stories: ...")`.
- Asserts `_read_session_messages("nonexistent-sid") == ("", "")` (negative case).
- Asserts `_read_session_messages("") == ("", "")` (falsy guard).
- Mocks `call_llm` to return `"news_summary"`, calls `asyncio.run(handler.run_classification_async(session_id=sid, message=None, response=None))`, asserts `call_llm` was called exactly once, and asserts the full LLM call prompt contains both `"Summarize today news headlines"` and `"Top stories"`.

## Why This Change Was Needed

The root cause of bland classifier outputs (`generation`, `unknown_task`) was identified by Mac Studio diagnostics: the plugin entrypoint (`__init__.py:_on_session_end`) always passes `message=None, response=None` to `run_classification`. Even after the 260514-nfb mint-first prompt rewrite, the LLM still had nothing to work with — `user_preview` and `asst_preview` were always empty strings. The Hermes session DB (`state.db`) already stores full conversation content in the `messages` table; this task closes the gap by querying it when the entrypoint passes None. After this change, the LLM receives the actual last user message and last assistant message and can mint specific labels like `news_summary`, `email_triage`, or `pr_review` based on real session content.

## Files Touched

| File | Change |
|------|--------|
| `skills/revenium/plugins/revenium-classifier/classifier.py` | Added `_read_session_messages` helper (47 lines); replaced Step 5 6-line block with 11-line conditional; all other code byte-unchanged |
| `tests/test_repository.py` | Added `test_revenium_classifier_reads_state_db_content` after `test_revenium_classifier_plugin_entrypoint` |

## Verification

All four checks pass:

- `python3 -m py_compile skills/revenium/plugins/revenium-classifier/classifier.py` — exits 0
- `python3 -m unittest discover -s tests -p 'test_*.py' -v` — 41 tests, OK
- `grep -c 'def _read_session_messages' skills/revenium/plugins/revenium-classifier/classifier.py` — returns 1
- `grep -c 'response_preview = response or' skills/revenium/plugins/revenium-classifier/classifier.py` — returns 0

## Decisions Made

**Atomic T01 (code + integration + test in one commit):** The new helper, the Step 5 wiring, and the regression test were committed together so the test suite is green at every commit boundary. There is no intermediate state where the new code exists without its test, or the test exists without the implementation.

**Use module constant `STATE_DB` rather than recomputing inline:** `_read_session_messages` uses `STATE_DB` (defined at module scope as `HERMES_HOME / "state.db"`) rather than constructing `HERMES_HOME / "state.db"` inline. This is consistent with `_walk_to_root_session` and `_count_tools_in_current_turn`, which both reference the same constant. Tests redirect `HERMES_HOME` via env vars and `importlib.reload` — using the constant ensures redirects work correctly.

**`try/finally` + `conn.close()` rather than a `with` block for the sqlite handle:** The helper's outer `try/except Exception: return ("", "")` is the D-04 fail-open wrapper. If the sqlite `with` block raised during `__exit__`, the outer except would catch it — but using an explicit `try/finally` + `conn.close()` inside the body makes the resource lifecycle unambiguous: the connection is always closed before the outer except either catches or re-raises. This matches the plan's stated preference for the D-04 contract and avoids masking errors in the `with`-block `__exit__` path.

## Follow-ups / Out of Scope

**Real-world label quality verification:** Whether the LLM now mints specific labels (vs. falling back to bland outputs) can only be confirmed from the next 24-48 hours of cron markers on Mac Studio. That observation is not part of this commit.

**Tool-call signals from `messages.tool_calls`:** The `messages` table carries a `tool_calls` column. Injecting a summary of tool names (e.g., "read_file, terminal, grep") into the prompt could further enrich the classifier's signal. Out of scope here — the immediate priority was getting any content into the prompt at all.
