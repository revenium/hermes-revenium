---
phase: 06-mechanical-classification-agent-end-hook
reviewed: 2026-05-13T00:00:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - skills/revenium/plugins/revenium-classifier/plugin.yaml
  - skills/revenium/plugins/revenium-classifier/__init__.py
  - skills/revenium/plugins/revenium-classifier/classifier.py
  - skills/revenium/plugins/revenium-classifier/test-payloads/trivial-turn.json
  - skills/revenium/plugins/revenium-classifier/test-payloads/substantive-turn.json
  - skills/revenium/plugins/revenium-classifier/test-payloads/subagent-turn.json
  - examples/setup-local.sh
  - skills/revenium/references/setup.md
  - tests/test_repository.py
findings:
  critical: 3
  warning: 8
  info: 3
  total: 14
status: issues_found
---

# Phase 6 (06-02): Code Review Report

**Reviewed:** 2026-05-13T00:00:00Z
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

The Phase 6 gap-closure (`06-02`) replaces the gateway `agent:end` shell hook tree with a hermes_cli plugin under `skills/revenium/plugins/revenium-classifier/`. The plugin entrypoint (`__init__.py::register/_on_session_end`) is structurally correct: synchronous callback signature matches the documented Hermes contract (`session_id`, `completed`, `interrupted`, `model`, `platform`, plus `**kwargs` for forward compatibility), D-04 belt is enforced at both the sync and async boundaries, and the registered callback is exercised end-to-end by `test_revenium_classifier_plugin_entrypoint`. Marker writes preserve `fcntl.LOCK_EX` + `O_APPEND` semantics, SQL is parameterized + `mode=ro`, and the budget-halt fail-open is preserved. `examples/setup-local.sh` correctly copies the plugin into `~/.hermes/plugins/revenium-classifier/` and prunes the stale `hooks/` tree from the skill copy. All 27 unit tests pass under `python3 -m unittest discover`.

However, the refactor regressed both of the critical findings from the 06-01 review, introduced two new BLOCKER issues in `setup-local.sh::plugins.enabled` patching (flow-style YAML list and empty-list shapes produce malformed YAML), and left several warning-tier robustness gaps: incomplete migration cleanup, `asyncio.run` reentry footgun on a running loop, idempotency holes for quoted/commented `enabled` list entries, and a depth-cap bug that returns a mid-chain sid (potentially causing cross-lineage task_type inheritance).

## Critical Issues

### CR-01: Subagent inheritance path skips D-13 dedup — same regression as 06-01 CR-01

**File:** `skills/revenium/plugins/revenium-classifier/classifier.py:309-316`

**Issue:** The subagent inheritance branch writes the marker pair and returns BEFORE the `_recent_marker_pair_exists` (D-13) tail check. If a subagent's `SKILL.md` FINAL ACTION block writes its own GUARDRAIL+CHAT pair inside the subagent session, then the plugin's `on_session_end` fires for the same subagent sid, this branch will write a second pair — producing 4 records in `<child-sid>.jsonl`. The cron will then meter 4 markers for one turn, doubling the per-marker attribution share for that subagent turn.

This is the same defect identified as CR-01 in the 06-01 review; the rename from `handler.py` to `classifier.py` and the move to a hermes_cli plugin did not change the control flow. The D-13 dedup at line 326 only protects the LLM-classification path, not the inheritance path.

The existing test `test_revenium_classifier_dedupe` (line 1128) only exercises the non-subagent path (no `parent_session_id` row), so the regression is undetected.

**Fix:** Hoist the D-13 check above the subagent branch so it gates both paths:
```python
# Step 0 — D-13 belt FIRST so it covers subagent inheritance too.
if _recent_marker_pair_exists(session_id, within_seconds=30.0):
    return

# Step 1 — subagent inheritance (D-05).
root_sid = _walk_to_root_session(session_id)
if root_sid != session_id:
    parent_task = _read_latest_task_type(root_sid)
    if parent_task:
        await asyncio.to_thread(_write_marker_pair, session_id, parent_task)
        return
```
And add a regression test that pre-seeds a fresh GUARDRAIL+CHAT pair on the subagent's marker file, invokes the classifier with parent_session_id set, and asserts the marker file still has exactly 2 lines after.

### CR-02: `_walk_to_root_session` returns a mid-chain sid on depth-cap — same regression as 06-01 CR-02

**File:** `skills/revenium/plugins/revenium-classifier/classifier.py:64-71`

**Issue:**
```python
current = sid
for _ in range(max_depth):
    row = conn.execute(...).fetchone()
    if row is None or row[0] is None:
        return current
    current = row[0]
return current   # depth-cap hit: returns the LAST sid visited, not the input sid
```

When the loop body iterates `max_depth` times without finding a null parent (pathological corrupt chain, real cycle, or a chain genuinely deeper than 10), the function returns whatever sid the loop last advanced to. That sid is NOT the root and may belong to an entirely unrelated lineage. The downstream subagent-inheritance branch (`classifier.py:312-316`) will then call `_read_latest_task_type(<wrong-sid>)`, and if that sid happens to have its own marker file from a different user request, the subagent will inherit the WRONG task_type. Cross-lineage attribution leak.

The existing test (`test_revenium_classifier_walk_to_root` Case D, line 1499-1508) only asserts `isinstance(result, str)` — it deliberately does not assert correctness on the depth-cap path, so the regression slips through.

Same defect identified as CR-02 in the 06-01 review.

**Fix:** Treat depth-cap as "give up — treat as root" — fall back to the input sid like the `OperationalError` handler at line 73 does:
```python
for _ in range(max_depth):
    row = conn.execute(...).fetchone()
    if row is None or row[0] is None:
        return current
    current = row[0]
return sid  # depth-cap → treat as root (do NOT inherit from a mid-chain sid)
```
Then strengthen the test: assert `handler._walk_to_root_session('loop0', max_depth=10) == 'loop0'` for the self-loop case so the regression cannot reappear silently.

### CR-03: `setup-local.sh` produces malformed YAML when `plugins.enabled` is a flow-style list or `[]`

**File:** `examples/setup-local.sh:88-109`

**Issue:** The script handles the `enabled:` key by appending a new block-style list item after the `enabled:` line:
```python
enabled_line_end_abs = plugins_match.end() + enabled_line_end_in_block
new_content = (
    content[:enabled_line_end_abs]
    + f"\n{list_item_indent}- {plugin_name}"
    + content[enabled_line_end_abs:]
)
```

This is incorrect for two real config.yaml shapes:

1. **Flow-style list (very common):** `enabled: [foo, bar]` → script appends `\n    - revenium-classifier`, producing:
   ```yaml
   plugins:
     enabled: [foo, bar]
       - revenium-classifier
   ```
   This is invalid YAML — you cannot mix flow-style `[...]` with block-style `-` items under the same key. The Hermes plugin loader will fail to parse `config.yaml` on next start, taking down ALL plugins, not just this one.

2. **Empty inline list:** `enabled: []` → same path, same malformed output. Operators commonly initialise `enabled: []` as a placeholder.

The regex at line 88 (`r"^(\s+)enabled:(.*)$"`) captures the trailing text into group(2) but never inspects it to detect flow style.

**Fix:** Inspect `enabled_match.group(2)` for flow-style markers before choosing the insertion strategy:
```python
trailer = enabled_match.group(2).strip()
if trailer.startswith('['):
    # Flow-style list — rewrite the whole line as block-style and append.
    # Parse the existing flow list, append plugin_name, emit block-style.
    items = [s.strip() for s in trailer.strip('[]').split(',') if s.strip()]
    if plugin_name not in items:
        items.append(plugin_name)
    indent = enabled_match.group(1)
    list_item_indent = indent + '  '
    new_block = f"{indent}enabled:\n" + "\n".join(
        f"{list_item_indent}- {item}" for item in items
    ) + "\n"
    # Replace the enabled: line + trailer with new_block.
    ...
elif trailer == '' or trailer.startswith('#'):
    # Block-style; safe to append a list item below.
    ...
```
Add tests that round-trip both flow-style and empty-list config.yaml shapes through the patch logic and assert the result is valid YAML (parseable by `yaml.safe_load` — used in test scope only, NOT runtime).

## Warnings

### WR-01: `setup-local.sh` does not remove the stale `~/.hermes/hooks/revenium-classifier/` from 06-01 installs

**File:** `examples/setup-local.sh:7-12`, `skills/revenium/references/setup.md:108`

**Issue:** Operators who installed the 06-01 implementation got `~/.hermes/hooks/revenium-classifier/` (a SIBLING of `~/.hermes/skills/`, not a child). The setup script removes `${TARGET_DIR}/hooks` (i.e., `~/.hermes/skills/revenium/hooks/`) but does NOT touch `~/.hermes/hooks/revenium-classifier/`. The setup.md note (line 108) acknowledges this and asks the operator to delete the directory manually — but with a re-run of `setup-local.sh` advertised as the migration path, this stale tree silently lingers and Hermes may still load it as a gateway hook. Per the setup.md note, it produces no markers, but it is dead code that confuses debugging and increases the surface for the no-op hook to misbehave.

**Fix:** Add an explicit removal step in `setup-local.sh` near the plugin install (line 30):
```bash
# 06-02 migration: clear the deprecated agent:end gateway hook tree from 06-01.
rm -rf "${HOME}/.hermes/hooks/revenium-classifier"
```
The `rm -rf` is safe — if the path does not exist, it's a no-op. Add a one-line `echo` if the directory was removed so operators see the migration happened.

### WR-02: `asyncio.run` inside `_on_session_end` will raise `RuntimeError` if Hermes invokes the callback from a running event loop

**File:** `skills/revenium/plugins/revenium-classifier/classifier.py:369-378`

**Issue:** `run_classification` wraps the async pipeline in `asyncio.run(...)`. `asyncio.run` raises `RuntimeError: asyncio.run() cannot be called from a running event loop` if the calling thread already has a running loop. The outer `try/except Exception` swallows the error and logs a `logger.warning`, but the entire classification pipeline silently never executes for THAT session and every subsequent session — defeating the universal-coverage invariant the plugin exists to enforce.

Whether this triggers depends on Hermes' actual dispatch: if `on_session_end` callbacks run synchronously inside the gateway's asyncio loop, every invocation will hit this path. The plan asserts the contract is synchronous, but the existing test (`test_revenium_classifier_plugin_entrypoint`) calls the registered callback from a fresh thread with no running loop, so the test would not catch this.

**Fix:** Detect a running loop and dispatch onto a worker thread, falling back to `asyncio.run` only if no loop is active:
```python
def run_classification(session_id, model=None, platform=None, message=None, response=None):
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        coro = run_classification_async(
            session_id=session_id, model=model, platform=platform,
            message=message, response=response,
        )
        if loop is None:
            asyncio.run(coro)
        else:
            # Already in a loop — schedule and let it run; do not block the loop thread.
            loop.create_task(coro)
    except Exception as exc:
        logger.warning("revenium-classifier run_classification failed for sid=%s: %s", session_id, exc)
```
If creating-and-forgetting a task is unsafe (no place to gather the result), an explicit `threading.Thread(target=lambda: asyncio.run(coro), daemon=True).start()` is the simpler, race-free choice. Add a regression test that calls `_on_session_end` from inside `asyncio.run(...)` and asserts a marker pair lands on disk anyway.

### WR-03: `plugins.enabled` regex misses quoted, commented, and indented duplicate detection

**File:** `examples/setup-local.sh:62-66`

**Issue:** The duplicate-detection regex (`r"^\s*-\s*" + re.escape(plugin_name) + r"\s*$"`) requires the plugin name to appear as a bare token alone on the line. It does NOT match any of the following legitimate YAML representations of "revenium-classifier already enabled":
- `- "revenium-classifier"` (quoted)
- `- 'revenium-classifier'` (single-quoted)
- `- revenium-classifier  # added 2025-12-01` (trailing comment)
- `-     revenium-classifier` (extra inner whitespace handled by `\s*` — OK)

Re-running `setup-local.sh` against a config that uses any of the quoted/commented forms will fall through to the insertion path and append a SECOND `- revenium-classifier` entry. Hermes may then attempt to load the plugin twice — best case a harmless dedup, worst case `register(ctx)` is called twice and the callback fires twice per session (double-write of markers).

**Fix:** Broaden the regex to tolerate quoted and trailing-comment forms:
```python
re.search(
    r"^\s*-\s*['\"]?" + re.escape(plugin_name) + r"['\"]?\s*(#.*)?$",
    content,
    re.MULTILINE,
)
```
Add a unit-style test fixture that exercises each shape (quoted, commented, mixed) and asserts second-run idempotency.

### WR-04: `_read_latest_task_type` will return `unclassified` and propagate it to all subagents

**File:** `skills/revenium/plugins/revenium-classifier/classifier.py:111-129`

**Issue:** If the root session was budget-halted (line 330-335 writes `task_type: unclassified` markers) or fell back to LLM-failure unclassified, `_read_latest_task_type` returns `"unclassified"` (it matches `LABEL_RE` and is not in `TRIVIAL_BLOCKLIST`). Every subagent of that root will then inherit `"unclassified"` — even if the budget halt has since cleared. The subagent never gets re-classified.

This is the same failure mode as the cron's zero-marker fallthrough, but here it propagates ACROSS the entire subagent lineage of one user-facing request rather than just one session. For long-running parent sessions with many subagents, the entire spend window is permanently `unclassified` in Revenium.

**Fix:** When `_read_latest_task_type` would return `"unclassified"`, fall through to LLM classification instead of inheriting. Quickest patch:
```python
def _read_latest_task_type(sid: str) -> "str | None":
    ...
    for line in reversed(lines):
        ...
        tt = rec.get("task_type")
        if isinstance(tt, str) and LABEL_RE.match(tt) and tt != "unclassified":
            return tt
    return None
```
Document the rationale in a comment — "unclassified is the cron's zero-marker fallback sentinel, not a real label; do not inherit it across the lineage."

### WR-05: `_walk_to_root_session` leaks sqlite3 Connection objects

**File:** `skills/revenium/plugins/revenium-classifier/classifier.py:60-71`

**Issue:** `with sqlite3.connect(...) as conn:` is a stdlib quirk — the context manager handles commit/rollback but does NOT close the connection on exit. Each session end leaks one Connection object until GC. The leak is bounded by GC pressure, so it does not blow up in tests, but it accumulates in long-running Hermes gateway processes and can exhaust file descriptors on hosts with many sessions/hour.

**Fix:** Use an explicit `try/finally` or `contextlib.closing`:
```python
conn = sqlite3.connect(uri, uri=True)
try:
    current = sid
    for _ in range(max_depth):
        row = conn.execute(
            "SELECT parent_session_id FROM sessions WHERE id = ?", (current,)
        ).fetchone()
        if row is None or row[0] is None:
            return current
        current = row[0]
    return sid  # depth-cap → see CR-02
finally:
    conn.close()
```

### WR-06: Plugin relative import will fail if Hermes loads `__init__.py` as a top-level module

**File:** `skills/revenium/plugins/revenium-classifier/__init__.py:16`

**Issue:** `from .classifier import run_classification` requires `__init__.py` to be loaded as part of a package (i.e., with `submodule_search_locations` set, or via `importlib.import_module("revenium_classifier")` after the directory is on `sys.path`). If Hermes' plugin loader instead uses `runpy.run_path(...)` or `importlib.util.spec_from_file_location(name, path)` WITHOUT `submodule_search_locations`, the relative import raises `ImportError: attempted relative import with no known parent package`, and the plugin silently fails to register.

The unit test at `tests/test_repository.py:1637-1644` works around this by explicitly setting `submodule_search_locations=[str(PLUGIN_DIR)]`, but the production loader's behavior is undocumented in this review's source set.

**Fix (defensive):** Either guard the relative import with a fallback:
```python
try:
    from .classifier import run_classification
except ImportError:
    # Fallback for loaders that do not set __package__ correctly.
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from classifier import run_classification  # type: ignore
```
Or switch to an absolute-by-path import. Document the import-loader contract in `setup.md`. Verify against the actual Hermes plugin manager invocation before considering this resolved.

### WR-07: `_recent_marker_pair_exists` assumes monotonic ts ordering — break-early can miss valid pairs

**File:** `skills/revenium/plugins/revenium-classifier/classifier.py:147-162`

**Issue:** The loop walks the marker file backward and uses `break` when `(now - ts) > within_seconds` — assuming "records are timestamp-ordered". This holds if all writers use `time.time()` from the same host clock and `O_APPEND` is honored, but breaks under:
- NTP clock skew across a sleep/wake (laptop closing the lid mid-session)
- Two writers racing into the same file with separately-captured `ts` values (the lock orders the WRITES, not the captured timestamps)
- Out-of-order replays after an editor or `cp` rewrite

In these cases the loop sees an older record near the tail, breaks, and misses the genuinely-fresh GUARDRAIL+CHAT pair just above it — defeating the dedup and re-introducing a double-write.

**Fix:** Drop the `break` optimization and just walk the entire tail of the file (or a bounded tail, e.g., last 16 records — markers are < 1024 bytes so this is bounded):
```python
for line in reversed(lines[-32:]):  # bounded tail
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        continue
    ts = rec.get("ts")
    op = rec.get("operation_type")
    if not isinstance(ts, (int, float)) or not isinstance(op, str):
        continue
    if (now - ts) <= within_seconds and op in ("GUARDRAIL", "CHAT"):
        seen_ops.add(op)
        if seen_ops >= {"GUARDRAIL", "CHAT"}:
            return True
return False
```

### WR-08: `_classify_via_llm` may leak prompt content into WARN log on certain provider errors

**File:** `skills/revenium/plugins/revenium-classifier/classifier.py:225-245`

**Issue:** Line 244 logs `exc` directly. Some LLM SDK exceptions include the full prompt or response body in their `str(exc)` (e.g., OpenAI's `BadRequestError` echoes the request body for token-limit errors). If a user message happens to contain credentials, PII, or sensitive code paths, that content can land in `~/.hermes/state/revenium/revenium-metering.log` — which is plaintext and ungated.

**Fix:** Use a fixed-class log line that intentionally drops the exception message body:
```python
except Exception as exc:
    logger.warning(
        "revenium-classifier LLM call failed: %s",
        type(exc).__name__,
    )
```
Or whitelist a small set of safe exception types and log their message; for everything else, log only the class name.

## Info

### IN-01: `test-payloads/subagent-turn.json` is shipped and listed in `test_expected_files_exist` but never loaded by any test

**File:** `skills/revenium/plugins/revenium-classifier/test-payloads/subagent-turn.json`, `tests/test_repository.py:82`

**Issue:** `tests/test_repository.py:82` asserts `subagent-turn.json` exists, but no test in the file reads its contents (`grep "subagent-turn.json"` in `test_repository.py` only finds the file-existence assertion). The subagent test (`test_revenium_classifier_subagent_inherits`, line 1393) hand-builds its `context` dict instead of loading the fixture. The fixture is currently unused dead data.

**Fix:** Either drop the fixture and remove it from the expected-files list, or refactor `test_revenium_classifier_subagent_inherits` to load it (preferred — the fixture documents the expected payload shape).

### IN-02: `_write_marker_pair` ignores existing directory permissions

**File:** `skills/revenium/plugins/revenium-classifier/classifier.py:272`

**Issue:** `MARKERS_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)` — `mode` only applies when the directory is being CREATED, not when it already exists. If an earlier tool created `markers/` with `0o755` (the umask default), the dir keeps the looser perms forever. Not a security catastrophe (markers contain only the controlled vocabulary and a sid prefix), but inconsistent with the implied 0o700 invariant.

**Fix:** After `mkdir`, explicitly `os.chmod(MARKERS_DIR, 0o700)` if you mean it to be enforced — or drop the `mode=0o700` argument so the discrepancy is honest.

### IN-03: `plugin.yaml` lacks any version pin or compatibility metadata

**File:** `skills/revenium/plugins/revenium-classifier/plugin.yaml:1-5`

**Issue:** The plugin manifest declares `name`, `version`, `description`, `hooks` — no `requires` (minimum Hermes version), no `entrypoint` (in case the Hermes plugin spec eventually requires one). If the Hermes plugin contract for `on_session_end` evolves (different kwargs, async-vs-sync, etc.), there is no version gate to detect the mismatch — the plugin will load and silently misbehave.

**Fix:** Add a `requires:` field with the minimum Hermes version that introduced the `on_session_end` event, and document the dependency in `setup.md` so operators upgrading Hermes see when the plugin needs an update.

---

_Reviewed: 2026-05-13T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
