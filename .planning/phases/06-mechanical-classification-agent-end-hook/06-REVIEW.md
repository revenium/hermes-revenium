---
phase: 06-mechanical-classification-agent-end-hook
reviewed: 2026-05-13T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - skills/revenium/hooks/revenium-classifier/HOOK.yaml
  - skills/revenium/hooks/revenium-classifier/handler.py
  - skills/revenium/hooks/revenium-classifier/test-payloads/trivial-turn.json
  - skills/revenium/hooks/revenium-classifier/test-payloads/substantive-turn.json
  - skills/revenium/hooks/revenium-classifier/test-payloads/subagent-turn.json
  - examples/setup-local.sh
  - skills/revenium/references/setup.md
  - tests/test_repository.py
findings:
  critical: 2
  warning: 9
  info: 7
  total: 18
status: issues_found
---

# Phase 6: Code Review Report

**Reviewed:** 2026-05-13T00:00:00Z
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Phase 6 introduces an in-process Hermes `agent:end` lifecycle hook
(`skills/revenium/hooks/revenium-classifier/`) that classifies turns via the
user's main LLM and writes a GUARDRAIL+CHAT marker pair under
`fcntl.LOCK_EX`. The implementation hits its declared invariants on the
happy path and the D-04 "never raise" contract is well-defended by an outer
`except Exception` plus the lazy `call_llm` import and tolerant SDK-shape
unpacking.

That said, two correctness bugs hide in the subagent-inheritance branch
that bypass guards the rest of the handler relies on, and the cycle-handling
behavior of `_walk_to_root_session` quietly produces wrong "root" sids
without test coverage of correctness. Several quality issues around
duplicate path constants (handler.py duplicates `common.sh` rather than
sourcing it), narrow `OSError`-only catches in helpers, and weak
dedup-race coverage round out the warnings.

## Critical Issues

### CR-01: Subagent inheritance branch bypasses the D-13 dedup check, enabling double-writes

**File:** `skills/revenium/hooks/revenium-classifier/handler.py:301-310`
**Issue:**
The `handle()` flow runs subagent inheritance (Step 1) BEFORE the D-13
dedup tail-check (Step 3). When `root_sid != sid` and the parent has a
valid `task_type`, the handler calls `_write_marker_pair` and returns
immediately at line 308-309, with no check for whether a recent
GUARDRAIL+CHAT pair already exists in the child's marker file.

If the agent's SKILL.md `FINAL ACTION` block runs inside a subagent
context (Hermes does load `SKILL.md` for subagent skills), the agent
self-writes a pair, then the `agent:end` hook fires immediately after,
walks to root, finds inherited `task_type`, and writes ANOTHER pair
without consulting `_recent_marker_pair_exists`. Net result: 4 marker
records per subagent turn, double-charged in Phase 3 attribution.

D-13 (Pitfall 6) is explicitly the dedup mechanism for the
agent/hook race, and the plan's D-05 description does not exempt
subagents from it.

**Fix:**
```python
# Step 1 — subagent inheritance (D-05).
root_sid = _walk_to_root_session(sid)
if root_sid != sid:
    parent_task = _read_latest_task_type(root_sid)
    if parent_task:
        # D-13 still applies — agent may have self-classified the subagent turn.
        if _recent_marker_pair_exists(sid, within_seconds=30.0):
            return
        await asyncio.to_thread(_write_marker_pair, sid, parent_task)
        return
    # Parent has no marker yet — fall through to classify as if root.
```

---

### CR-02: `_walk_to_root_session` returns mid-cycle sid when the depth cap trips, then writes wrong-parent task_type to subagent

**File:** `skills/revenium/hooks/revenium-classifier/handler.py:65-72`
**Issue:**
When the `parent_session_id` chain forms a cycle or exceeds `max_depth=10`,
the function returns `current` — which is a session somewhere in the cycle,
NOT a true root. The caller (`handle()` line 304-307) then reads that
arbitrary sid's marker file and inherits its `task_type`. This is a
silent correctness violation: the subagent gets attributed to the wrong
lineage's task_type with no error log.

The test `test_revenium_classifier_walk_to_root` Case D (line 1425-1434)
only asserts `isinstance(result, str)` — it does NOT verify the function
detected the cycle. A `parent_session_id` cycle (which can occur from
test data, manual db edits, or a future Hermes bug) silently mis-attributes
every subagent turn under that lineage.

The function should distinguish "hit depth cap (anomalous)" from "reached
root (normal)" and return `sid` (the input) on anomaly so the caller
falls through to classify-as-root, not inherit-from-arbitrary-mid-chain.

**Fix:**
```python
def _walk_to_root_session(sid: str, max_depth: int = 10) -> str:
    try:
        uri = f"file:{STATE_DB}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            visited = {sid}
            current = sid
            for _ in range(max_depth):
                row = conn.execute(
                    "SELECT parent_session_id FROM sessions WHERE id = ?", (current,)
                ).fetchone()
                if row is None or row[0] is None or row[0] == "":
                    return current
                parent = row[0]
                if parent in visited:
                    logger.warning(
                        "revenium-classifier: cycle detected in parent chain from sid=%s", sid
                    )
                    return sid  # fall back to "treat as root"
                visited.add(parent)
                current = parent
            logger.warning(
                "revenium-classifier: parent chain exceeded max_depth=%d from sid=%s",
                max_depth, sid,
            )
            return sid  # belt: don't inherit from an arbitrary mid-chain sid
    except sqlite3.OperationalError:
        return sid
    except Exception:
        return sid
```

And tighten the test:
```python
# Case D — cycle: must return input sid, not arbitrary mid-chain sid
result = handler._walk_to_root_session('loop0', max_depth=10)
self.assertEqual(result, 'loop0', 'cycle/cap must fall back to input sid')
```

## Warnings

### WR-01: `_read_latest_task_type` does not enforce the trivial-label blocklist when inheriting

**File:** `skills/revenium/hooks/revenium-classifier/handler.py:122-130`
**Issue:**
`_read_latest_task_type` returns any marker `task_type` that matches
`LABEL_RE`, but does NOT check `TRIVIAL_BLOCKLIST`. If a parent's
marker file ever carries a blocklist token (e.g., from a hand-edited
file, a future LLM-classifier bug that bypasses `_validate_label`, or a
pre-Phase-9 manual write), a subagent silently inherits the forbidden
label, breaking D-09 attribution downstream. Defense-in-depth is cheap
here.

**Fix:**
```python
for line in reversed(lines):
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        continue
    tt = rec.get("task_type")
    if isinstance(tt, str) and LABEL_RE.match(tt) and tt not in TRIVIAL_BLOCKLIST:
        return tt
return None
```

---

### WR-02: `_count_tools_in_current_turn` only catches `OSError`, will propagate `UnicodeDecodeError`

**File:** `skills/revenium/hooks/revenium-classifier/handler.py:86-89`
**Issue:**
`path.read_text(encoding="utf-8")` raises `UnicodeDecodeError` on
non-UTF-8 bytes (which is `ValueError`, not `OSError`). The function's
docstring promises a return of 0 on "unreadable" files, but the
inner-helper contract is silently broken: it raises out. The outer
`handle()` try/except catches it via D-04 belt, so the handler doesn't
crash, but the heuristic-skip path returns "unclassified" via
fall-through instead of "trivial-skip", and an unrelated WARN is
logged. Same issue in `_read_latest_task_type` (line 119-121) and
`_recent_marker_pair_exists` (line 141-144).

**Fix:** widen the exception class to `(OSError, UnicodeDecodeError)`
or just `Exception` for these helpers since they're already
fail-safe-and-default-zero:
```python
try:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
except OSError:
    return 0
```

---

### WR-03: Subagent inheritance branch bypasses the budget-halt gate

**File:** `skills/revenium/hooks/revenium-classifier/handler.py:301-310`
**Issue:**
Step 1 (subagent inheritance) returns BEFORE the Step 4 budget-halt
check. This is *probably* fine — inheritance does not call the LLM,
so there is no spend to gate — but it produces an inconsistency with
D-08, which states "halted → `task_type: unclassified` and WARN log".
Under halt, the subagent inherits the parent's real label (e.g.
`code_review`) rather than `unclassified`. Operators reading marker
files during a halt period will see real labels for subagents and
unclassified for root sessions, which complicates reasoning about
attribution during the halt.

If the design intent is "subagent inheritance is allowed under halt
because it's free", that should be documented in the docstring at the
top of the file. If the intent is "uniform unclassified during halt",
move the budget-halt check above the subagent path.

**Fix (preferred — document the intent):**
```python
# Step 1 — subagent inheritance (D-05). Cheap (no LLM call), so we run
# this BEFORE the budget gate; a halted budget does not forbid
# inheriting a parent's already-paid-for task_type.
```

---

### WR-04: `_recent_marker_pair_exists` performs lock-free read against an `fcntl.LOCK_EX` writer

**File:** `skills/revenium/hooks/revenium-classifier/handler.py:133-163`
**Issue:**
The dedup tail-check reads the marker file without acquiring a shared
lock (`fcntl.LOCK_SH`). Under concurrent writers (the hook itself
serializes via `LOCK_EX` in `_write_marker_pair`, but the cron
pipeline reads markers too, and a hypothetical Phase 3 partial line
appearing during read is possible since marker writes are 2 `f.write`
calls inside the same lock — atomic per process, but the page-cache
flush is not atomic).

In practice `splitlines()` tolerates a truncated final line and
`json.loads` returns JSONDecodeError on a partial line (handled), so
the worst-case outcome is "miss a fresh pair and write a duplicate" —
the cron's per-muid global dedup is the wire-level safety net. Worth
documenting in the function docstring so a future maintainer doesn't
introduce a strict invariant that requires a shared lock.

**Fix:** add a comment, or actually take `LOCK_SH`:
```python
# NOTE: read is lock-free. The write path uses LOCK_EX, so we may read
# a partially-flushed pair. splitlines + json.loads tolerate truncated
# final lines; the failure mode is "miss a fresh pair → write
# duplicate", caught by the cron's per-muid dedup. Do not strengthen
# the dedup contract without taking LOCK_SH here.
```

---

### WR-05: `handler.py` duplicates path constants from `common.sh` with no enforcement of parity

**File:** `skills/revenium/hooks/revenium-classifier/handler.py:38-44`
**Issue:**
Per `CLAUDE.md` "Single Source of Truth: `common.sh`", all state paths
live in `common.sh` and "all other scripts source it." `handler.py` is
Python and cannot source bash, so it re-derives the paths from the same
env vars. This duplication is necessary, but there is NO test that
asserts handler.py's paths match common.sh's. If a future change
adds `BACKUP_MARKERS_DIR` to common.sh or changes the `markers`
subdir name, handler.py silently diverges.

`test_runtime_paths_are_hermes_native` (test_repository.py:116-128)
only inspects common.sh. Extend it to load handler.py and assert the
same path shape.

**Fix:** add a parity test:
```python
def test_handler_paths_mirror_common_sh(self):
    """handler.py module-level constants must match common.sh shape."""
    import importlib, os, sys, tempfile
    # ... (use _setup_hook_env)
    if 'handler' in sys.modules:
        importlib.reload(sys.modules['handler'])
    import handler
    # The same env vars common.sh respects must produce the same paths.
    common_text = (SKILL / 'scripts' / 'common.sh').read_text()
    self.assertIn('REVENIUM_MARKERS_DIR', common_text)
    self.assertEqual(handler.MARKERS_DIR.name, 'markers')
    self.assertTrue(str(handler.MARKERS_DIR).endswith('state/revenium/markers'))
    # ... etc.
```

---

### WR-06: `_recent_marker_pair_exists` partial-pair race not covered by tests

**File:** `skills/revenium/hooks/revenium-classifier/handler.py:147-163`
**Issue:**
The dedup logic requires BOTH `GUARDRAIL` and `CHAT` ops in the window
to skip the write. If the agent's `FINAL ACTION` snippet wrote only
the first marker (GUARDRAIL) at the moment the `agent:end` hook fires,
the hook sees `seen_ops = {GUARDRAIL}`, does not return True, and
writes its own GUARDRAIL+CHAT pair. The agent then writes the CHAT
moments later. Net result: 1 agent-GUARDRAIL + 1 hook-GUARDRAIL +
1 hook-CHAT + 1 agent-CHAT = 4 records, double-attribution.

This race window is small (the agent's two markers are written under
the same flock acquire-release in the SKILL.md snippet — assuming Phase 2
shipped that pattern), but it exists if the agent snippet has even
one operation between the two writes. `test_revenium_classifier_dedupe`
does NOT cover the partial-pair scenario.

**Fix:** add a test where the marker file contains ONLY a fresh
GUARDRAIL (no CHAT), confirm whether the hook writes or skips, then
either:
- accept the spec ("partial pair = not deduped, hook writes" — current
  behavior), OR
- tighten the rule ("any fresh GUARDRAIL or CHAT in window → skip") to
  close the race.

---

### WR-07: `setup-local.sh` destroys `${HOME}/.hermes/hooks/revenium-classifier/` without checking gateway-is-stopped

**File:** `examples/setup-local.sh:31-32`
**Issue:**
`rm -rf "${HOOK_TARGET}"` followed by `cp -R ...` runs unconditionally,
even if the Hermes gateway is currently running with the old
handler.py loaded. On Linux this is benign (gateway holds the open
file descriptor through unlink), but a subsequent reload or
config-rescan could try to read the now-deleted file. The "Next
steps" echo at line 40 instructs `hermes gateway restart` AFTER the
destructive operation, when the safer order is "stop → rm/cp →
start".

This is acceptable for v1 (the script is an example, operators read
the docs), but document the requirement.

**Fix:** add a pre-flight check or warning:
```bash
if pgrep -f 'hermes.*gateway' >/dev/null 2>&1; then
  echo "WARNING: Hermes gateway appears to be running."
  echo "Stop it (hermes gateway stop) before re-installing, or the"
  echo "running gateway will keep the old handler.py loaded until restart."
fi
```

---

### WR-08: `_classify_via_llm` `timeout=10.0` is a kwarg, not enforced if `call_llm` ignores it

**File:** `skills/revenium/hooks/revenium-classifier/handler.py:226-236`
**Issue:**
The handler passes `timeout=10.0` to `call_llm`, but there is no
`asyncio.wait_for` or `signal.alarm` around the `to_thread`
invocation. If the upstream `agent.auxiliary_client.call_llm` does
not honor its own `timeout` parameter (e.g., the underlying SDK
returns a streaming response that ignores per-request timeout), the
hook stalls indefinitely. Because `handle()` is fired inside the
gateway event loop and there is no outer timeout, this blocks the
event loop's hook-emit slot and degrades agent latency.

The plan (line 235) makes the `timeout=10.0` kwarg a load-bearing
guarantee, but the implementation trusts `call_llm` to honor it.

**Fix:** wrap with `asyncio.wait_for`:
```python
try:
    response = await asyncio.wait_for(
        asyncio.to_thread(
            call_llm,
            messages=[...],
            temperature=0.0,
            max_tokens=64,
            timeout=10.0,  # kept for upstream contract; wait_for is belt
        ),
        timeout=15.0,
    )
except asyncio.TimeoutError:
    logger.warning("revenium-classifier LLM call timed out")
    return "unclassified"
```

---

### WR-09: `_count_tools_in_current_turn` assumes Hermes' session jsonl uses `role: user` / `role: tool`

**File:** `skills/revenium/hooks/revenium-classifier/handler.py:96, 107`
**Issue:**
The heuristic-skip path hinges on parsing
`~/.hermes/sessions/<sid>.jsonl` and counting lines where
`obj.get("role") == "tool"` after the last `obj.get("role") == "user"`.
If Hermes' session writer ever uses different role tokens (e.g.,
`role: user_message`, `role: tool_call`, or nested under
`message.role`), this function returns 0 for every turn, causing the
heuristic-skip to fire on every short-response turn even though tools
ran. Net effect: substantial under-attribution and missing markers
across substantive turns.

This is a Hermes-coupling risk that no test catches — every test
seeds its own jsonl with the assumed shape. A schema-drift assertion
against a real Hermes-installed session jsonl is out of v1 scope, but
the assumption should be called out in the docstring AND a comment
should reference the Hermes session-writer code that defines the
shape.

**Fix:** document the dependency and add a tolerant fallback:
```python
def _count_tools_in_current_turn(sid: str) -> int:
    """...
    DEPENDS ON: Hermes session writer emitting {"role": "user"} and
    {"role": "tool"} at the top level. See hermes-agent/agent/session.py
    (Hermes ref); if Hermes ever nests the role under "message" or
    renames it, this returns 0 silently and the heuristic-skip
    over-fires.
    """
```

## Info

### IN-01: `_read_latest_task_type` and `_recent_marker_pair_exists` re-read whole file on every turn

**File:** `skills/revenium/hooks/revenium-classifier/handler.py:118-130, 141-163`
**Issue:**
Both helpers do `marker_path.read_text().splitlines()` and walk the
file in reverse. For a long-lived session (hundreds of turns), each
hook invocation re-reads N KB. v1 marker files won't exceed ~50 KB
realistically (2 records per turn, < 1 KB each, ~25 turns per session),
so this is fine for v1. Document the scale assumption.

**Fix:** add a comment in both helpers acknowledging the O(n) tail
read and noting the v1 turn-count assumption.

---

### IN-02: `_walk_to_root_session` does not handle empty-string `parent_session_id`

**File:** `skills/revenium/hooks/revenium-classifier/handler.py:69-71`
**Issue:**
The condition `if row is None or row[0] is None` does not treat
`parent_session_id == ""` (empty string) as "no parent". If Hermes
ever writes empty strings instead of NULL for top-level sessions, the
loop continues with `current = ""`, queries `WHERE id = ""` next
iteration, finds no row, returns `""`. Then `_read_latest_task_type("")`
reads `markers/.jsonl` (a hidden file in the markers dir) — almost
certainly missing → returns None → falls through to classify. No
crash, but the "wrong root" is technically returned.

**Fix:** treat empty string as no-parent:
```python
if row is None or not row[0]:  # None or empty string
    return current
```

---

### IN-03: `_muid()` Y2106 overflow risk

**File:** `skills/revenium/hooks/revenium-classifier/handler.py:262-264`
**Issue:**
`int(time.time_ns() // 1_000_000):013x` formats ms-since-epoch as
13-char hex. 13 hex chars = 52 bits, max value
2^52 - 1 = 4,503,599,627,370,495 ms ≈ year 2112. After that, the format
widens to 14 chars, the muid becomes 34 chars, and the
`^[0-9a-f]{33}$` regex in tests + downstream rejects it. Cosmetic for
this century.

**Fix:** add a comment so a future maintainer doesn't accidentally
tighten the regex past Y2112:
```python
def _muid() -> str:
    """13-char ms-timestamp prefix + 20-char random hex = 33 char lowercase hex.
    NOTE: the 13-char hex prefix overflows at ~year 2112; the regex
    ^[0-9a-f]{33}$ will reject those muids. Acceptable for v1.
    """
```

---

### IN-04: `_build_classification_prompt` truncates `labels_block` mid-label

**File:** `skills/revenium/hooks/revenium-classifier/handler.py:195-196`
**Issue:**
The 1024-char truncation on the comma-joined labels list can chop a
label name in half (e.g., "code_revie ... [truncated]"). The LLM might
emit the truncated label verbatim, which `_validate_label` rejects (good,
falls through to "unclassified"), or it might emit a different valid
label (also fine). No correctness impact, but the prompt looks
malformed to the LLM. Truncate at the last full comma:

**Fix:**
```python
if len(labels_block) > 1024:
    truncated = labels_block[:1024]
    last_comma = truncated.rfind(", ")
    if last_comma > 0:
        truncated = truncated[:last_comma]
    labels_block = truncated + " ... [truncated]"
```

---

### IN-05: Exception messages from `call_llm` could leak partial PII / prompt content into logs

**File:** `skills/revenium/hooks/revenium-classifier/handler.py:244-246`
**Issue:**
`logger.warning("revenium-classifier LLM call failed: %s", exc)` logs
the raw exception message. Many LLM SDKs include the partial request
body or response snippet in error messages (e.g., openai's
`BadRequestError` may include token-overflow context). If the user's
prompt contains code/credentials/PII, those leak into
`~/.hermes/state/revenium/revenium-metering.log` (or wherever the
logger is configured to write).

Probably acceptable for a self-hosted developer tool, but worth a
docstring callout so operators know NOT to ship the log offsite
without sanitization.

**Fix:** add a comment, or truncate the exc message to e.g. 200 chars:
```python
exc_str = str(exc)[:200]
logger.warning("revenium-classifier LLM call failed (truncated): %s", exc_str)
```

---

### IN-06: `_recent_marker_pair_exists` "timestamp-ordered" assumption documented but not enforced

**File:** `skills/revenium/hooks/revenium-classifier/handler.py:157-158`
**Issue:**
The comment "records are timestamp-ordered (append-only); no point
continuing" justifies the `break` on the first stale record. Under
single-process append-with-flock writes, this holds. But if clock
skew or NTP jumps occur, a later write could carry an EARLIER ts than
an earlier write, breaking the assumption. The `break` then misses a
fresh record buried below a stale one.

Vanishingly rare in practice. Document the assumption, or remove the
break and walk the whole file (cheap for v1 file sizes per IN-01).

**Fix:** swap the break for `continue` to be robust:
```python
if (now - ts) > within_seconds:
    continue  # tolerant of out-of-order timestamps; file is small
```

---

### IN-07: Test `test_revenium_classifier_walk_to_root` Case D does not assert correctness, only non-crash

**File:** `tests/test_repository.py:1425-1434`
**Issue:**
After seeding a 15-link self-referencing chain, the test only
checks `self.assertIsInstance(result, str)`. It does NOT verify the
function detected the cycle and returned the input sid (the safe
fallback). This means CR-02's silent mis-attribution is undetectable
by the current test suite.

**Fix:** see CR-02 — strengthen the assertion to
`self.assertEqual(result, 'loop0')` once `_walk_to_root_session` is
hardened to return the input sid on cap/cycle.

---

_Reviewed: 2026-05-13T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
