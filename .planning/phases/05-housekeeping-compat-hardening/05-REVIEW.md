---
phase: 05-housekeeping-compat-hardening
reviewed: 2026-05-14T00:00:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - skills/revenium/scripts/common.sh
  - skills/revenium/scripts/prune-markers.sh
  - skills/revenium/scripts/hermes-report.sh
  - skills/revenium/plugins/revenium-classifier/classifier.py
  - tests/test_repository.py
  - README.md
  - docs/installation.md
  - skills/revenium/references/setup.md
  - skills/revenium/references/task-taxonomy.md
findings:
  critical: 0
  blocker: 0
  warning: 4
  info: 4
  total: 8
status: issues_found
---

# Phase 5: Code Review Report

**Reviewed:** 2026-05-14
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

Phase 5 (Housekeeping & Compat Hardening) lands four plans across 16 atomic commits: marker pruning script (05-01), classifier mint-back + recency ordering (05-02), pipe-safety sanitization + dead-var cleanup (05-03), and documentation refresh (05-04).

The changes are technically sound and well-tested for the canonical paths. Test isolation in the new tests is correct (`tempfile.TemporaryDirectory` context manager, `try/finally` env restoration, `_setup_plugin_env`/`_restore_plugin_env` symmetry). No legacy branding regressions. Doc consistency across `README.md`, `docs/installation.md`, `references/setup.md`, and `references/task-taxonomy.md` is good — the env var name (`REVENIUM_MARKER_RETENTION_DAYS`), default (30 days), flag surface (`--dry-run`), and ledger-vs-mtime contract are described consistently and match the code in `prune-markers.sh`.

The findings below cluster in two areas:
1. **`_persist_label_to_taxonomy` deviates from the documented atomic-write pattern.** The classifier uses a fixed `<name>.tmp` filename without `fcntl.flock`, where `references/task-taxonomy.md` mandates `tempfile.NamedTemporaryFile` + `flock(LOCK_EX)` + `os.fsync`. Practical impact is low (single-writer on `on_session_end`), but it's a latent regression vs. the contract documented in the same phase.
2. **`prune-markers.sh` uses `${VAR@Q}` to interpolate paths into a Python heredoc.** `@Q` produces bash-style single-quoted strings (`'foo'\''bar'`) that are NOT valid Python string literals when the path contains a single quote. Triggers SyntaxError, not RCE — the script crashes cleanly under `set -e`. Low practical risk (operator-controlled paths) but defensive coding would round-trip via env vars like the existing pattern in `hermes-report.sh`.

No critical/blocker findings. The WR-01 pipe-safety fix in `hermes-report.sh` is correct and covered by a regression test that exercises the exact desync condition the fix prevents.

## Warnings

### WR-01: `_persist_label_to_taxonomy` does not use `fcntl.flock` and uses a fixed `.tmp` filename

**File:** `skills/revenium/plugins/revenium-classifier/classifier.py:370-407`
**Issue:** The mint-back helper writes via:
```python
tmp = TAXONOMY_FILE.parent / (TAXONOMY_FILE.name + ".tmp")
tmp.write_text(...)
tmp.replace(TAXONOMY_FILE)
```

This deviates from the atomic-write pattern documented in `skills/revenium/references/task-taxonomy.md:90-126`, which mandates:
- `fcntl.flock(LOCK_EX)` on the source file to serialize concurrent minters
- `tempfile.NamedTemporaryFile` with a unique random suffix (NOT a fixed `.tmp` name)
- `tmp.flush()` + `os.fsync(tmp.fileno())` before `os.rename`

With a fixed `.tmp` filename, two concurrent `_persist_label_to_taxonomy` calls (e.g., two near-simultaneous `on_session_end` events) race on the same path. Process A's `write_text` can be clobbered by process B's `write_text` before either calls `replace`, producing an incoherent final state. The current `test_persist_label_to_taxonomy_mint_and_update` only exercises serial calls, so the regression is not detected.

Practical impact today is low (the plugin fires on session end, which is rarely concurrent), but the same module imports `fcntl` at line 18 and already uses it correctly in `_write_marker_pair` (line 436) — using it here too would close the gap with zero additional dependency.

**Fix:**
```python
import tempfile
def _persist_label_to_taxonomy(label: str) -> None:
    if label == "unclassified":
        return
    import datetime
    try:
        TAXONOMY_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Acquire exclusive lock on the target (create if missing) before RMW
        with open(TAXONOMY_FILE if TAXONOMY_FILE.exists() else
                 TAXONOMY_FILE.parent / ".taxonomy.lock", "a+") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                data = json.loads(TAXONOMY_FILE.read_text(encoding="utf-8"))
            except Exception:
                data = {"labels": {}}
            labels = data.get("labels", {})
            if not isinstance(labels, dict):
                labels = {}
            now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if label not in labels:
                labels[label] = {"description": None, "examples": [], "last_seen_at": now_iso}
            else:
                if not isinstance(labels[label], dict):
                    labels[label] = {}
                labels[label]["last_seen_at"] = now_iso
            data["labels"] = labels
            with tempfile.NamedTemporaryFile(
                "w", dir=str(TAXONOMY_FILE.parent),
                delete=False, suffix=".tmp", encoding="utf-8",
            ) as tmp:
                json.dump(data, tmp, indent=2, ensure_ascii=False)
                tmp.write("\n")
                tmp.flush()
                os.fsync(tmp.fileno())
                tmpname = tmp.name
            os.replace(tmpname, TAXONOMY_FILE)
    except Exception as exc:
        logger.warning("revenium-classifier: mint-back failed for label=%s: %s", label, exc)
```

### WR-02: `prune-markers.sh` interpolates paths via `${VAR@Q}` into a Python heredoc

**File:** `skills/revenium/scripts/prune-markers.sh:57-60`
**Issue:** The bash parameter expansion `${VAR@Q}` produces a **shell-quoted** string (e.g., `'foo'\''bar'` for a path containing a single quote). Shell-quoted strings are syntactically distinct from Python string literals; a path containing a single quote produces a Python `SyntaxError`. Reproducible locally:

```bash
$ MARKERS_DIR="weird'path" bash -c 'python3 - <<PY
x = ${MARKERS_DIR@Q}
PY'
  File "<stdin>", line 2
    x = 'weird'\''path'
                  ^
SyntaxError: unexpected character after line continuation character
```

The other Python heredocs in the same repo (`hermes-report.sh:73`, `hermes-report.sh:334`) avoid this by passing paths through environment variables (`MARKERS_DIR="${MARKERS_DIR}" python3 - <<'PY' ... os.environ['MARKERS_DIR']`), which side-steps the quoting question entirely. The `prune-markers.sh` heredoc is unquoted (`<<PY` not `<<'PY'`) precisely to allow the `@Q` substitution — switching to the env-var pattern would also let the heredoc be `<<'PY'` (matching house style).

Practical risk: operator-controlled paths rarely contain single quotes. But the script crashes under `set -euo pipefail` rather than degrading gracefully, and the failure mode is a confusing Python parse error rather than a clean `error "invalid marker directory path"`.

Secondary issue: `int(${MARKER_RETENTION_DAYS@Q})` silently accepts negative values and zero. `REVENIUM_MARKER_RETENTION_DAYS=0` makes every marker stale (cutoff_secs=0, every age > 0); a typo wipes the entire marker corpus. Validate.

**Fix:**
```bash
# Pass via env (matches hermes-report.sh pattern), quote the heredoc terminator,
# and validate retention_days inside Python with a clear error.
MARKERS_DIR="${MARKERS_DIR}" \
LEDGER_FILE="${LEDGER_FILE}" \
MARKER_RETENTION_DAYS="${MARKER_RETENTION_DAYS}" \
DRY_RUN="${DRY_RUN}" \
python3 - <<'PY'
import os, sys, time
markers_dir = os.environ['MARKERS_DIR']
ledger_file = os.environ['LEDGER_FILE']
try:
    retention_days = int(os.environ['MARKER_RETENTION_DAYS'])
except (KeyError, ValueError):
    print('prune: ERROR invalid REVENIUM_MARKER_RETENTION_DAYS, expected integer', file=sys.stderr)
    sys.exit(2)
if retention_days < 1:
    print('prune: ERROR REVENIUM_MARKER_RETENTION_DAYS must be >= 1', file=sys.stderr)
    sys.exit(2)
dry_run = os.environ['DRY_RUN'] == 'true'
# ... rest unchanged
PY
```

### WR-03: `prune-markers.sh` does not acquire `LOCK_FILE` (cron.lock) — concurrent prune+cron can race on marker writes

**File:** `skills/revenium/scripts/prune-markers.sh:32-43`
**Issue:** The prune script acquires `PRUNE_LOCK_FILE` to serialize concurrent prune invocations, but does NOT acquire `LOCK_FILE` (cron.lock). If an operator runs `prune-markers.sh` while the per-minute cron is mid-execution, the cron's `hermes-report.sh` may be reading a marker file via `with marker_path.open()` (line 385 of hermes-report.sh) at the same moment prune calls `os.unlink(fpath)` on it.

On POSIX `unlink` during an open read is safe (the file remains readable through the existing fd until close), so this is not data corruption. But the classifier plugin (`_write_marker_pair`, classifier.py:435-438) appends with `fcntl.LOCK_EX` to the same marker path the prune script may delete — a race where prune unlinks immediately before the plugin opens-for-append leaves the plugin writing to a stale inode, which is then orphaned. Next cron tick the plugin's write is "lost" (no marker file with that sid exists for the cron to read).

Practical risk is low — the prune script is operator-invoked, infrequent. But the symmetric defense is cheap: the script already has the `exec 9>` pattern; one more `exec 8>"${LOCK_FILE}"` plus `flock -n` would close the race.

**Fix:** Acquire both locks (prune lock first to serialize peer prune runs; cron lock to serialize against the per-minute cron):
```bash
exec 9>"${PRUNE_LOCK_FILE}"
exec 8>"${LOCK_FILE}"
if ! python3 - <<'PY'
import fcntl, sys
try:
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
    fcntl.flock(8, fcntl.LOCK_EX | fcntl.LOCK_NB)
except (OSError, BlockingIOError):
    sys.exit(11)
PY
then
  warn "prune skipped — cron.lock or prune.lock held"
  exit 0
fi
```

### WR-04: `test_persist_label_to_taxonomy_mint_and_update` captures `first_ts` but never asserts the update

**File:** `tests/test_repository.py:3275-3279`
**Issue:** The test stores `first_ts = entry['last_seen_at']` after the first call, then calls `_persist_label_to_taxonomy('sql_query_debug')` a second time and asserts only `len(data2['labels']) == 1`. It never asserts that `data2['labels']['sql_query_debug']['last_seen_at']` was updated. The "update last_seen_at on every successful write" behavior (classifier.py:397-400, comment "(recency ordering D-33)") is unverified by this test.

Also, even if an assertion were added, the timestamp format is second-resolution (`%Y-%m-%dT%H:%M:%SZ`) — two back-to-back calls in the same second would produce identical strings. A robust test needs `time.sleep(1)` between calls OR `freezegun`/monkeypatch on `datetime.datetime.now`.

**Fix:**
```python
# Sub-case 2: same label again — no duplicate, last_seen_at updated
first_ts = entry['last_seen_at']
import time
time.sleep(1.05)  # second-resolution timestamp; ensure tick increment
cls_module._persist_label_to_taxonomy('sql_query_debug')
data2 = json.loads(open(taxonomy_path).read())
self.assertEqual(len(data2['labels']), 1, 'no duplicate')
self.assertNotEqual(data2['labels']['sql_query_debug']['last_seen_at'], first_ts,
                    'last_seen_at must be refreshed on idempotent re-mint (D-33)')
self.assertGreater(data2['labels']['sql_query_debug']['last_seen_at'], first_ts)
```

## Info

### IN-01: `prune-markers.sh` lock file is never cleaned up

**File:** `skills/revenium/scripts/prune-markers.sh:32`
**Issue:** `exec 9>"${PRUNE_LOCK_FILE}"` creates `${STATE_DIR}/prune.lock` and never removes it. The file is empty and the lock is held via `flock` on the fd, so this is correct behavior — but the file accumulates as a permanent zero-byte artifact in `state/revenium/`. This matches the `cron.sh` pattern (which also never cleans up `cron.lock`), so it's consistent; flagging as INFO because new operators may wonder why two `*.lock` files sit alongside their config.

**Fix:** Optional `trap "rm -f \"${PRUNE_LOCK_FILE}\"" EXIT` after lock acquisition succeeds. Low priority — the cron.lock precedent argues for keeping current behavior.

### IN-02: `prune-markers.sh` test does not verify the `\r` sanitization branch

**File:** `tests/test_repository.py:3411-3430`
**Issue:** The pipe-safety test exercises `|` (in `agent`) and `\n` (in `trace_id`) but not `\r`. The Python loop (`for _bad in ('|', '\n', '\r')`) handles all three identically, so the missing case is unlikely to regress separately, but the test docstring mentions `\\r` (line 3291) so the intent is to cover all three.

**Fix:** Add a third marker variant or extend the existing fixture so `trace_id` contains all three: `'bad\r|value\nvalue'` → asserted `'bad__value_value'`.

### IN-03: `README.md` does not document `REVENIUM_MARKER_RETENTION_DAYS` env var

**File:** `README.md:166-167`
**Issue:** The README mentions the prune script (`# Prune stale marker files (30+ days old by default; --dry-run to preview)`) but does not document the `REVENIUM_MARKER_RETENTION_DAYS` env var that controls the default. `docs/installation.md:83` and `references/setup.md:128` both document it. The README is consistent with its general "summary, link to docs" stance, so this is a style note only — not a doc consistency bug.

**Fix:** Optional one-line addition to the prune entry: `# (Override default 30-day retention via REVENIUM_MARKER_RETENTION_DAYS=N)`.

### IN-04: `_read_taxonomy_labels` imports `datetime` inside the function body

**File:** `skills/revenium/plugins/revenium-classifier/classifier.py:265`
**Issue:** `import datetime` happens inside the function (line 265) rather than at the module-top alongside `import asyncio`, `import json`, etc. (lines 17-26). The same pattern repeats in `_persist_label_to_taxonomy` at line 380. Module-level imports are the house style throughout the codebase. The inline imports are functionally correct (`datetime` is stdlib, no startup cost concern), but they break the convention; a contributor scanning the imports won't see `datetime` is used.

**Fix:** Hoist `import datetime` to the top-level import block (line 22 or 26).

---

_Reviewed: 2026-05-14_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
