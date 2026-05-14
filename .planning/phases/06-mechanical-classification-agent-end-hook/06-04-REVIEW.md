---
phase: 06-04-mechanical-classification-agent-end-hook
reviewed: 2026-05-14T00:00:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - skills/revenium/scripts/common.sh
  - skills/revenium/scripts/hermes-report.sh
  - skills/revenium/plugins/revenium-classifier/__init__.py
  - skills/revenium/plugins/revenium-classifier/classifier.py
  - tests/test_repository.py
findings:
  critical: 0
  warning: 3
  info: 4
  total: 7
status: issues_found
---

# Phase 6.04: Code Review Report

**Reviewed:** 2026-05-14T00:00:00Z
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found

## Summary

Reviewed the 06-04 G-03 gap closure: sentinel-or-aged session filter in the
cron pipeline + plugin-side sentinel write. The diff is narrowly scoped and
adheres to the plan's constraints (path discipline preserved, stdlib-only
Python heredoc, soft-fail discipline, D-04 invariant extended end-to-end,
existing 16 HOOK-* tests untouched).

The 6 new HOOK-13 tests (2 sentinel-write + 3 cron-filter + 1 end-to-end) are
well-isolated (tempdir + env-var redirection), use specific assertions, and
the end-to-end test at line 2178 is the regression guard for the 2026-05-14
G-03 race that UAT-3 surfaced — it would have caught the bug before operator
UAT had it not been present.

No BLOCKERs found. Three WARNINGs concern a defensive-coding gap in the
cron filter heredoc (empty-env-var defense is broken), an inconsistent mode
bit on the sentinel directory (security-doc mismatch with implementation),
and an unused `Path` import in the plugin entrypoint.

## Warnings

### WR-01: Filter heredoc misreads empty `MARKERS_READY_DIR` env as CWD

**File:** `skills/revenium/scripts/hermes-report.sh:84-85,117`
**Issue:** The defensive guard
```python
markers_ready_dir = Path(os.environ.get('MARKERS_READY_DIR', ''))
...
has_sentinel = (markers_ready_dir / sid).exists() if str(markers_ready_dir) else False
```
intends to skip the sentinel check when `MARKERS_READY_DIR` is unset/empty,
but `Path('')` resolves to `PosixPath('.')` and `str(Path('.'))` is `'.'`
(truthy). The guard therefore always runs the check, and on an
unset/empty env var the code evaluates `(Path('.') / sid).exists()` —
checking whether a file named `<session_id>` exists in the cron's CWD.
A stray file in `/`, `/tmp`, or wherever cron runs (matching a session id)
would erroneously be treated as a sentinel and skip the settle window.

In normal operation `common.sh` always sets `MARKERS_READY_DIR` to a
non-empty value, so this is defense-in-depth rather than a live bug. Still,
the dead branch should either work or be removed — leaving wrong-but-unused
code is a footgun for future edits.

**Fix:**
```python
markers_ready_dir_str = os.environ.get('MARKERS_READY_DIR', '')
markers_ready_dir = Path(markers_ready_dir_str) if markers_ready_dir_str else None
...
try:
    has_sentinel = markers_ready_dir is not None and (markers_ready_dir / sid).exists()
except OSError:
    has_sentinel = False
```

### WR-02: Sentinel directory mode-bit mismatch with security-threat-model

**File:** `skills/revenium/scripts/common.sh:22` and
`skills/revenium/plugins/revenium-classifier/__init__.py:37`
**Issue:** The 06-04 plan's threat-model section asserts the sentinel
directory inherits a `0o700` (owner-only) mode "inherited from STATE_DIR's
0o700 mode" (06-04-PLAN.md mitigation for threat #1). The actual code:

- `common.sh:22` — `mkdir -p "${STATE_DIR}" "${MARKERS_DIR}" "${MARKERS_READY_DIR}"`
  with NO mode argument. Default mode is `0o777 & ~umask`; on a typical
  Linux umask 022 that's `0o755`, world-readable.
- `__init__.py:37` — `MARKERS_READY_DIR.mkdir(parents=True, exist_ok=True)`
  with NO `mode=` kwarg. Same default.

Compare to `classifier.py::_write_marker_pair` (line 302) which DOES use
`mode=0o700`. The new sentinel directory is inconsistent with that
precedent, and the threat-model writeup overstates the actual protection.

The local-attacker risk surface is narrow (any local user with write access
to MARKERS_READY_DIR can also write to MARKERS_DIR alongside it, so this
does not open a new vector), but the implementation should match the
documented invariant or the documentation should be corrected.

**Fix:** Pass `mode=0o700` explicitly at both creation sites:
```python
# __init__.py:37
MARKERS_READY_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
```
And in `common.sh`, either `(umask 077; mkdir -p ...)` or post-chmod. If
correctness of the documented threat model is preferred to the
implementation cost, alternatively update the plan's mitigation language
to reflect the actual (umask-derived) mode.

### WR-03: Filter heredoc swallows ALL Python errors via `2>/dev/null`

**File:** `skills/revenium/scripts/hermes-report.sh:73`
**Issue:** The heredoc is invoked as `python3 - <<'PY' 2>/dev/null` so
ANY stderr output (syntax errors after a future edit, traceback from a
runtime exception that escapes the inner try, etc.) is silently dropped.
Combined with the outer `|| filtered_sessions="${sessions}"` fallback,
a broken filter degrades to "report everything immediately" — defeating
the entire G-03 race fix without any operator-visible signal.

The existing per-row `try/except Exception: print(line); continue` belt
already preserves rows through soft-fail. The outer `2>/dev/null` is
redundant defense that hides the diagnostic signal a future operator
would need to see when something has gone wrong.

**Fix:** Drop `2>/dev/null` so stderr surfaces in the cron log; keep the
`||` fallback to preserve the soft-fail semantic.
```bash
filtered_sessions=$(
  SESSIONS="${sessions}" \
  ...
  python3 - <<'PY'
  ...
PY
) || filtered_sessions="${sessions}"
```
A stderr line in the cron log is harmless when the filter is healthy
(quiet) and load-bearing the day a future edit breaks the filter.

## Info

### IN-01: Unused `Path` import in plugin entrypoint

**File:** `skills/revenium/plugins/revenium-classifier/__init__.py:15`
**Issue:** `from pathlib import Path` was added in 06-04 but is never
referenced in the module body. `MARKERS_READY_DIR` is already a `Path`
object (constructed in `classifier.py:40`), so the `/ session_id` operator
overload works without re-importing `Path` here.

**Fix:** Remove the import:
```python
import logging

from .classifier import run_classification, MARKERS_READY_DIR
```

### IN-02: Untyped `session_id` parameter in `_write_sentinel`

**File:** `skills/revenium/plugins/revenium-classifier/__init__.py:22`
**Issue:** `_write_sentinel(session_id) -> None` lacks an annotation on
`session_id`. Style is loose throughout this module (e.g.,
`_on_session_end` parameters are also untyped), so this is consistent
within the file but inconsistent with `classifier.py` which uses
`"str | None"` quoted annotations on similar parameters.

**Fix:**
```python
def _write_sentinel(session_id: "str | None") -> None:
```

### IN-03: `_write_sentinel(session_id)` not delegated to from inside `_write_sentinel`'s except

**File:** `skills/revenium/plugins/revenium-classifier/__init__.py:40-45`
**Issue:** `_write_sentinel` catches `Exception` — appropriate. But the
warning-log call itself (`logger.warning(...)`) is not wrapped in a belt;
if the logging subsystem is in a degenerate state (a broken handler, a
filesystem-full condition affecting a FileHandler), the `logger.warning`
call inside the except could itself raise and propagate out of
`_write_sentinel`. The probability is extraordinarily low — but D-04
"never raises" claims end-to-end immunity.

**Fix (optional, defense-in-depth):**
```python
except Exception as exc:
    try:
        logger.warning(
            "revenium-classifier sentinel write failed for sid=%s: %s",
            session_id,
            exc,
        )
    except Exception:
        pass
```
Equally acceptable: accept that a broken logger is a system-level failure
beyond this plugin's purview and leave the code as-is.

### IN-04: Unnecessary `if 'classifier' in sys.modules: importlib.reload(...)` in HOOK-13 sentinel tests

**File:** `tests/test_repository.py:1773-1774` and `tests/test_repository.py:1833-1834`
**Issue:** Both new sentinel tests do
```python
if 'classifier' in sys.modules:
    importlib.reload(sys.modules['classifier'])
```
before constructing the plugin package via `spec_from_file_location` with
`submodule_search_locations`. Because the plugin uses a relative import
(`from .classifier import ...`), Python resolves it as
`<mod_name>.classifier` — a DIFFERENT module object from the bare
`classifier` in `sys.modules`. The reload only refreshes the bare module,
which the plugin under test does not consume.

The pattern is copied from earlier HOOK-* tests where it WAS load-bearing,
but in these two new tests it is a no-op. Harmless, but a maintenance trap
for the next reader who assumes the reload is necessary.

**Fix:** Either delete the no-op reload or add a comment explaining why
it is kept (parity with the older tests that import `classifier` directly).
```python
# No-op for plugin-package tests; kept for parity with HOOK-* tests that
# import classifier directly.
if 'classifier' in sys.modules:
    importlib.reload(sys.modules['classifier'])
```

---

_Reviewed: 2026-05-14T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
