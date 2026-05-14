# Phase 5: Housekeeping & Compat Hardening — Pattern Map

**Mapped:** 2026-05-14
**Files analyzed:** 12 (1 new script, 4 modified scripts/Python, 1 modified JSON, 4 modified docs/planning, 2 modified test)
**Analogs found:** 12 / 12

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `skills/revenium/scripts/prune-markers.sh` | operator-script (new) | batch, file-I/O | `skills/revenium/scripts/clear-halt.sh` (shape) + `skills/revenium/scripts/cron.sh` (flock) | role-match |
| `skills/revenium/scripts/common.sh` | config / path registry | — | self (add one variable adjacent to `MARKERS_DIR`) | exact |
| `skills/revenium/scripts/hermes-report.sh` | service / cron-script | batch | self (two targeted edits: WR-01 sanitize, WR-02 dead var) | exact |
| `skills/revenium/plugins/revenium-classifier/classifier.py` | plugin / service | event-driven | self (two targeted edits: D-32 mint-back, D-33 recency sort) | exact |
| `skills/revenium/task-taxonomy.json` | config / data | — | self (schema extension: `last_seen_at` per label) | exact |
| `tests/test_repository.py` | test | subprocess, unit | self (WR-03 base_env isolation; new prune, mint-back, recency tests) | exact |
| `skills/revenium/references/setup.md` | doc | — | self (prune runbook + classifier truth refresh) | exact |
| `skills/revenium/references/task-taxonomy.md` | doc | — | self (mint-first framing refresh) | exact |
| `README.md` | doc | — | self (pruning note + TAX-* framing update) | exact |
| `.planning/PROJECT.md` | planning doc | — | self (D-3/D-8 rewrite + Evolution Notes) | exact |
| `.planning/REQUIREMENTS.md` | planning doc | — | self (flip COMPAT-04, TEST-05 to Verified) | exact |
| `.planning/ROADMAP.md` | planning doc | — | self (Phase 5 row update) | exact |

---

## Pattern Assignments

### `skills/revenium/scripts/prune-markers.sh` (operator-script, file-I/O)

**Analogs:** `skills/revenium/scripts/clear-halt.sh` (script skeleton), `skills/revenium/scripts/cron.sh` (flock gate)

---

#### Script skeleton pattern
**Source:** `skills/revenium/scripts/clear-halt.sh` lines 1-11

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path
```

Notes:
- `set -euo pipefail` (hard-fail) — prune-markers.sh is a one-shot operator script, same as `clear-halt.sh`. It aborts loudly rather than partially completing.
- `SCRIPT_DIR` resolved via `BASH_SOURCE[0]`, not `$0`.
- `# shellcheck source=/dev/null` on the line immediately above every `source`.
- `ensure_path` called immediately after sourcing so `python3` resolves in cron/operator invocation.

---

#### Flock gate pattern
**Source:** `skills/revenium/scripts/cron.sh` lines 10-30

```bash
# Acquire cron.lock non-blocking. Held for the rest of this script's lifetime via fd 9,
# so the lock spans BOTH hermes-report.sh and budget-check.sh invocations below (CRON-08, D-12).
# `exec 9>"${LOCK_FILE}"` opens fd 9 in this bash process; the python3 subprocess inherits
# fd 9 automatically and calls fcntl.flock(9, ...) on it. No stdin redirection is used so
# the heredoc script body remains the Python program (NOT the empty lock file).
# The `if ! python3 ... ; then ... fi` form neutralizes `-e` for the contention branch so
# `warn + exit 0` is reached on EAGAIN (do NOT add `|| true`; do NOT change cron.sh's flag mode).
# flock(2) works on the underlying open file description regardless of access mode, so a
# write-opened fd 9 is fine for exclusive locking.
exec 9>"${LOCK_FILE}"
if ! python3 - <<'PY'
import fcntl, sys
try:
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
except (OSError, BlockingIOError):
    sys.exit(11)
PY
then
  warn "prior tick still active, skipping this minute"
  exit 0
fi
```

For `prune-markers.sh`: use a prune-specific lock file (e.g., `${STATE_DIR}/prune.lock`) rather than sharing `LOCK_FILE` (`cron.lock`) — this prevents the prune script from blocking a cron tick when an operator runs it manually.  Declare `PRUNE_LOCK_FILE` in `common.sh` adjacent to `LOCK_FILE`.

---

#### Dry-run flag parsing pattern
**Source:** `skills/revenium/scripts/install-cron.sh` (flag-check convention) — adapted for prune:

```bash
DRY_RUN=false
for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=true ;;
    *) echo "Unknown flag: ${arg}" >&2; exit 1 ;;
  esac
done
```

---

#### Ledger-timestamp read pattern (D-26)
**Source:** `skills/revenium/scripts/hermes-report.sh` ledger grep convention (conceptual analog):

```bash
# Read the most recent ledger entry for a given sid.
# Ledger format: HERMES:<sid>:<total_tokens>:<unix_ts>:<muid>
# Cut field 4 (unix_ts) from the last matching line.
last_ts=$(grep "^HERMES:${sid}:" "${LEDGER_FILE}" 2>/dev/null | tail -1 | cut -d: -f4 || true)
```

Per D-26: if `last_ts` is empty (orphan marker with no ledger entry), fall back to file mtime for age comparison.

---

#### Logging-per-deletion pattern (D-29)
**Source:** `skills/revenium/scripts/common.sh` `info`/`warn`/`error` helpers (lines 40-42):

```bash
info()  { log "INFO " "$@"; }
warn()  { log "WARN " "$@"; }
error() { log "ERROR" "$@"; }
```

Apply in prune script exactly as:

```bash
# Per-deletion log line:
info "prune: removed sid=${sid} marker=${basename} last_ledger_ts=${iso_ts} age_days=${age_days}"
# Dry-run log line:
info "prune: dry-run, would remove sid=${sid} marker=${basename} last_ledger_ts=${iso_ts} age_days=${age_days}"
# Summary at end of run:
info "prune: summary, scanned=${scanned} kept=${kept} removed=${removed}"
```

Never use bare `echo` for logged events — `info` is the correct helper per CLAUDE.md conventions.

---

### `skills/revenium/scripts/common.sh` (config, path registry)

**Analog:** Self — add one line adjacent to `MARKERS_READY_DIR` (line 19 area).

**Current block (lines 17-20):**
```bash
TAXONOMY_FILE="${REVENIUM_TAXONOMY_FILE:-${STATE_DIR}/task-taxonomy.json}"
MARKERS_DIR="${REVENIUM_MARKERS_DIR:-${STATE_DIR}/markers}"
MARKERS_READY_DIR="${REVENIUM_MARKERS_READY_DIR:-${STATE_DIR}/markers/.ready}"
LOCK_FILE="${STATE_DIR}/cron.lock"
```

**Phase 5 additions (insert after `LOCK_FILE`):**
```bash
MARKER_RETENTION_DAYS="${REVENIUM_MARKER_RETENTION_DAYS:-30}"
PRUNE_LOCK_FILE="${STATE_DIR}/prune.lock"
```

Pattern rules to follow:
- `:-` fallback syntax (not bare `-`) — colon-dash handles both unset and empty-string.
- New env var name: `REVENIUM_MARKER_RETENTION_DAYS` (screaming snake, `REVENIUM_` prefix matches all other overridable vars).
- New path var: `PRUNE_LOCK_FILE` declared here; prune script sources `common.sh` and references `${PRUNE_LOCK_FILE}` — never hardcoded elsewhere.
- `test_runtime_paths_are_hermes_native` will pass as long as `MARKERS_DIR` and `MARKERS_READY_DIR` lines remain unchanged.

---

### `skills/revenium/scripts/hermes-report.sh` (service, batch — two targeted edits)

**Analog:** Self (existing file).

---

#### WR-01: Pipe-safety sanitization in split_rows heredoc (lines ~527-533)

**Current (lines 527-533):**
```python
m_agent = marker.get('agent', '')   # optional Phase 2 field; empty string triggers bash :- fallback
m_trace = marker.get('trace_id', '')   # optional Phase 2 field; empty string triggers bash :- fallback
# NOTE: m_agent / m_trace values MUST NOT contain '|' (pipe-safety; today's only values are pipe-safe fallbacks per D-23).
# Pipe-delimited; cost is a string for byte-exact round-trip.
print(f"{marker['muid']}|{marker['task_type']}|{marker['operation_type']}|"
      f"{split['input']}|{split['output']}|{split['cache_read']}|"
      f"{split['cache_write']}|{split['total']}|{split['cost']}|{m_agent}|{m_trace}")
```

**Phase 5 target — add sanitization before print (D-34):**
```python
m_agent = marker.get('agent', '')
m_trace = marker.get('trace_id', '')
# WR-01: sanitize pipe-delimiters and control chars so future upstream writers
# cannot corrupt the bash while-read IFS='|' parsing (D-34).
for _bad in ('|', '\n', '\r'):
    m_agent = m_agent.replace(_bad, '_')
    m_trace = m_trace.replace(_bad, '_')
print(f"{marker['muid']}|{marker['task_type']}|{marker['operation_type']}|"
      f"{split['input']}|{split['output']}|{split['cache_read']}|"
      f"{split['cache_write']}|{split['total']}|{split['cost']}|{m_agent}|{m_trace}")
```

---

#### WR-02: Remove dead `local row` variable (line ~549)

**Current (line 549):**
```bash
local row muid t_type op_type d_in d_out d_cr d_cw d_tot d_cost m_agent m_trace
```

**Phase 5 target — drop `row` (D-35):**
```bash
local muid t_type op_type d_in d_out d_cr d_cw d_tot d_cost m_agent m_trace
```

`row` is declared but never referenced; it is a relic from a pre-11-pipe iteration. No other change on this line.

---

### `skills/revenium/plugins/revenium-classifier/classifier.py` (plugin, event-driven — two targeted edits)

**Analog:** Self (existing file).

---

#### D-33: Recency-order sort in `_read_taxonomy_labels` (line ~254)

**Current `_read_taxonomy_labels` (lines 254-265):**
```python
def _read_taxonomy_labels() -> list:
    """Read TAXONOMY_FILE and return the sorted list of existing label keys. The
    live taxonomy is at ~/.hermes/state/revenium/task-taxonomy.json (managed by
    Phase 2). Returns [] on any failure — the LLM will mint a new label."""
    try:
        data = json.loads(TAXONOMY_FILE.read_text(encoding="utf-8"))
        labels = data.get("labels", {})
        if isinstance(labels, dict):
            return sorted(labels.keys())
    except Exception:
        pass
    return []
```

**Phase 5 target — sort by `last_seen_at` descending, then alphabetical (D-33):**
```python
def _read_taxonomy_labels() -> list:
    """Read TAXONOMY_FILE and return labels sorted recent-first, alpha within ties.

    Labels with a `last_seen_at` ISO timestamp within the last 7 days appear
    first (recent bucket); older labels and labels without `last_seen_at` (seed
    entries) follow alphabetically. Returns [] on any failure."""
    try:
        data = json.loads(TAXONOMY_FILE.read_text(encoding="utf-8"))
        labels = data.get("labels", {})
        if not isinstance(labels, dict):
            return []
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        recent_cutoff = now - datetime.timedelta(days=7)
        recent, older = [], []
        for key, meta in sorted(labels.items()):  # alpha pre-sort for stable tie-break
            raw_ts = meta.get("last_seen_at") if isinstance(meta, dict) else None
            if raw_ts:
                try:
                    ts = datetime.datetime.fromisoformat(raw_ts.rstrip("Z")).replace(
                        tzinfo=datetime.timezone.utc
                    )
                    if ts >= recent_cutoff:
                        recent.append((ts, key))
                        continue
                except Exception:
                    pass
            older.append(key)
        recent.sort(key=lambda x: x[0], reverse=True)
        return [k for _, k in recent] + older
    except Exception:
        pass
    return []
```

The 1024-byte cap on `labels_block` in `_build_classification_prompt` (lines 276-278) is unchanged.

---

#### D-32: Mint-back call after `_write_marker_pair` succeeds

**Call sites in `run_classification_async` (lines 403, 413, 436):**
```python
await asyncio.to_thread(_write_marker_pair, session_id, parent_task)   # line 403
await asyncio.to_thread(_write_marker_pair, session_id, "unclassified") # line 413
await asyncio.to_thread(_write_marker_pair, session_id, task_type)     # line 436
```

**Atomic write pattern for mint-back (mirrors `clear-halt.sh` Python block):**
```python
def _persist_label_to_taxonomy(label: str) -> None:
    """Append label to task-taxonomy.json if not already present.

    Atomic via temp-file + os.replace. Fail-open: any I/O error logs a warning
    and returns without raising (D-32). Only called after _write_marker_pair succeeds."""
    import datetime, tempfile
    try:
        try:
            data = json.loads(TAXONOMY_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {"labels": {}}
        labels = data.get("labels", {})
        if not isinstance(labels, dict):
            labels = {}
        if label not in labels:
            labels[label] = {
                "description": None,
                "examples": [],
                "last_seen_at": datetime.datetime.now(datetime.timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
        else:
            # Update last_seen_at on every successful write (recency ordering D-33).
            if not isinstance(labels[label], dict):
                labels[label] = {}
            labels[label]["last_seen_at"] = datetime.datetime.now(
                datetime.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        data["labels"] = labels
        TAXONOMY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = TAXONOMY_FILE.parent / (TAXONOMY_FILE.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(TAXONOMY_FILE)
    except Exception as exc:
        logger.warning("revenium-classifier: mint-back failed for label=%s: %s", label, exc)
```

**Insert call at each `_write_marker_pair` site** (after the `await asyncio.to_thread(...)` line, inside the try-block at the same indentation). For the `"unclassified"` path (line 413), do NOT mint-back — `unclassified` is a sentinel, not a taxonomy entry. Only mint-back for `parent_task` and `task_type` paths.

---

### `skills/revenium/task-taxonomy.json` (config / data — schema extension)

**Analog:** Self (existing seed entries).

**Current seed entry shape:**
```json
"research": {
  "description": "Reading docs, exploring the codebase, or searching the web to learn before acting",
  "examples": ["find all usages of X", "what does this API return"]
}
```

**Phase 5 target — add `last_seen_at` to seed entries (lazy migration: existing installs get the field on first mint-back write):**
No change to the JSON file itself in Phase 5. Seed entries remain without `last_seen_at`. `_read_taxonomy_labels` treats absent `last_seen_at` as "older" bucket per D-33 — lazy migration is correct behavior and `dict.get("last_seen_at")` returns `None` for seed entries without the field.

The CONTEXT.md `<specifics>` section confirms: seed labels sort at the end alphabetically; only newly-minted labels get `last_seen_at`. No migration script needed.

---

### `tests/test_repository.py` (test — three concerns)

**Analog:** Self (existing `RepositoryTests` methods and test scaffolding).

---

#### WR-03: Extend `base_env` in Phase 4 tests for env isolation (D-36)

**Current `base_env` in `test_wire_agent_trace_passthrough` (lines 2827-2835) and `test_wire_no_provider_regression_per_class` (lines 2889-2897):**
```python
base_env = {
    **os.environ,
    'HOME': shim_home,
    'HERMES_HOME': hermes_home,
    'REVENIUM_STATE_DIR': state_dir,
    'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
    'INVOCATIONS_LOG': invocations_log,
    'TZ': 'UTC',
}
```

**Phase 5 target — add the three marker/taxonomy overrides so developer env vars cannot leak:**
```python
base_env = {
    **os.environ,
    'HOME': shim_home,
    'HERMES_HOME': hermes_home,
    'REVENIUM_STATE_DIR': state_dir,
    'REVENIUM_MARKERS_DIR': markers_dir,
    'REVENIUM_MARKERS_READY_DIR': os.path.join(markers_dir, '.ready'),
    'REVENIUM_TAXONOMY_FILE': os.path.join(state_dir, 'task-taxonomy.json'),
    'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
    'INVOCATIONS_LOG': invocations_log,
    'TZ': 'UTC',
}
```

Apply the same change to both `test_wire_agent_trace_passthrough` sub-cases and `test_wire_no_provider_regression_per_class` (every place `base_env` is constructed in those two methods).

---

#### New test: prune script (subprocess-driven)

**Scaffold pattern** — reuse `build_state_db`, `run_cron` shape from `test_cron_marker_split_end_to_end` (lines 373-491), but invoke `prune-markers.sh` not `hermes-report.sh`.

```python
def test_prune_markers_dry_run_and_live(self):
    import json, os, shutil, subprocess, tempfile, time
    PRUNE_SCRIPT = SKILL / 'scripts' / 'prune-markers.sh'

    with tempfile.TemporaryDirectory() as tmpdir:
        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        markers_dir = os.path.join(state_dir, 'markers')
        os.makedirs(markers_dir, mode=0o700)
        ledger_file = os.path.join(state_dir, 'revenium-hermes.ledger')

        # --- Fixture: three marker files ---
        # 1. "old" sid — ledger entry 31 days ago → should be pruned
        old_sid = 'old-session-31d'
        old_ts = int(time.time()) - 31 * 86400
        with open(os.path.join(markers_dir, f'{old_sid}.jsonl'), 'w') as f:
            f.write(json.dumps({'muid': 'aaa', 'ts': float(old_ts),
                                'sid': old_sid, 'task_type': 'research',
                                'operation_type': 'CHAT'}) + '\n')
        with open(ledger_file, 'a') as f:
            f.write(f'HERMES:{old_sid}:1000:{old_ts}:aaa\n')

        # 2. "fresh" sid — ledger entry today → should be kept
        fresh_sid = 'fresh-session-today'
        fresh_ts = int(time.time())
        with open(os.path.join(markers_dir, f'{fresh_sid}.jsonl'), 'w') as f:
            f.write(json.dumps({'muid': 'bbb', 'ts': float(fresh_ts),
                                'sid': fresh_sid, 'task_type': 'generation',
                                'operation_type': 'CHAT'}) + '\n')
        with open(ledger_file, 'a') as f:
            f.write(f'HERMES:{fresh_sid}:500:{fresh_ts}:bbb\n')

        # 3. "orphan" sid — no ledger entry, mtime 31 days old → should be pruned
        orphan_sid = 'orphan-no-ledger'
        orphan_path = os.path.join(markers_dir, f'{orphan_sid}.jsonl')
        with open(orphan_path, 'w') as f:
            f.write(json.dumps({'muid': 'ccc', 'ts': float(old_ts),
                                'sid': orphan_sid, 'task_type': 'review',
                                'operation_type': 'CHAT'}) + '\n')
        old_atime = old_ts
        os.utime(orphan_path, (old_atime, old_atime))

        env = {
            **os.environ,
            'HERMES_HOME': hermes_home,
            'REVENIUM_STATE_DIR': state_dir,
            'REVENIUM_MARKERS_DIR': markers_dir,
            'REVENIUM_MARKER_RETENTION_DAYS': '30',
            'TZ': 'UTC',
        }

        # --- Sub-case 1: dry-run — nothing deleted ---
        r = subprocess.run(['bash', str(PRUNE_SCRIPT), '--dry-run'],
                           env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, f'dry-run exit {r.returncode}: {r.stderr}')
        self.assertTrue(os.path.exists(os.path.join(markers_dir, f'{old_sid}.jsonl')),
                        'dry-run must not delete old marker')
        self.assertTrue(os.path.exists(orphan_path),
                        'dry-run must not delete orphan marker')

        # --- Sub-case 2: live run — old + orphan deleted, fresh kept ---
        r = subprocess.run(['bash', str(PRUNE_SCRIPT)],
                           env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, f'live run exit {r.returncode}: {r.stderr}')
        self.assertFalse(os.path.exists(os.path.join(markers_dir, f'{old_sid}.jsonl')),
                         'old marker must be deleted')
        self.assertFalse(os.path.exists(orphan_path),
                         'orphan marker must be deleted')
        self.assertTrue(os.path.exists(os.path.join(markers_dir, f'{fresh_sid}.jsonl')),
                        'fresh marker must be kept')

        # --- Sub-case 3: idempotent re-run — exit 0, removed=0 ---
        r = subprocess.run(['bash', str(PRUNE_SCRIPT)],
                           env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, f'idempotent run exit {r.returncode}: {r.stderr}')
```

---

#### New test: mint-back (unit, plugin env)

**Scaffold pattern** — reuse `_setup_plugin_env` / `_restore_plugin_env` helpers already in the file (lines 21-55):

```python
def test_persist_label_to_taxonomy_mint_and_update(self):
    import json, os, importlib, tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot, sys_path_added, hermes_home, state_dir, markers_dir = \
            _setup_plugin_env(tmpdir)
        try:
            taxonomy_path = os.path.join(state_dir, 'task-taxonomy.json')
            import classifier as cls_module
            importlib.reload(cls_module)

            # First call — label is not in taxonomy yet
            cls_module._persist_label_to_taxonomy('sql_query_debug')
            data = json.loads(open(taxonomy_path).read())
            self.assertIn('sql_query_debug', data['labels'])
            entry = data['labels']['sql_query_debug']
            self.assertIsNone(entry['description'])
            self.assertEqual(entry['examples'], [])
            self.assertIn('last_seen_at', entry)

            # Second call — last_seen_at updated, no duplicate
            cls_module._persist_label_to_taxonomy('sql_query_debug')
            data2 = json.loads(open(taxonomy_path).read())
            self.assertEqual(len(data2['labels']), 1)  # no duplicate

            # 'unclassified' must NOT be minted (sentinel)
            cls_module._persist_label_to_taxonomy('unclassified')
            data3 = json.loads(open(taxonomy_path).read())
            self.assertNotIn('unclassified', data3['labels'])
        finally:
            _restore_plugin_env(snapshot, sys_path_added)
```

---

#### New test: recency ordering in `_read_taxonomy_labels`

```python
def test_read_taxonomy_labels_recency_order(self):
    import datetime, json, os, importlib, tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot, sys_path_added, hermes_home, state_dir, markers_dir = \
            _setup_plugin_env(tmpdir)
        try:
            taxonomy_path = os.path.join(state_dir, 'task-taxonomy.json')
            now = datetime.datetime.now(datetime.timezone.utc)
            ts_recent = (now - datetime.timedelta(days=2)).strftime('%Y-%m-%dT%H:%M:%SZ')
            ts_old = (now - datetime.timedelta(days=10)).strftime('%Y-%m-%dT%H:%M:%SZ')
            data = {
                'labels': {
                    'alpha_old': {'description': None, 'examples': [], 'last_seen_at': ts_old},
                    'beta_recent': {'description': None, 'examples': [], 'last_seen_at': ts_recent},
                    'gamma_seed': {'description': 'seed label', 'examples': []},  # no last_seen_at
                }
            }
            with open(taxonomy_path, 'w') as f:
                json.dump(data, f)
            os.environ['REVENIUM_TAXONOMY_FILE'] = taxonomy_path
            import classifier as cls_module
            importlib.reload(cls_module)

            result = cls_module._read_taxonomy_labels()
            # 'beta_recent' (2 days) before 'alpha_old' (10 days) before 'gamma_seed' (no ts)
            self.assertEqual(result[0], 'beta_recent', 'most recent label must be first')
            self.assertIn('alpha_old', result[1:], 'older dated label after recent')
            self.assertEqual(result[-1], 'gamma_seed', 'seed label (no last_seen_at) must be last')
        finally:
            _restore_plugin_env(snapshot, sys_path_added)
```

---

### `skills/revenium/references/setup.md` (doc — two additions)

**Analog:** Self — prose paragraphs, plain Markdown. Follow the existing paragraph + bash-block style.

**Addition 1: Prune operator runbook (new section after "Mechanical classification hook")**

Pattern: mimic the style of the existing "Reset flow" and "Reconfigure flow" numbered-step sections. New section title: `## Marker file pruning`. Include:
- What the script does (ledger-based stale check, 30-day default, orphan fallback).
- How to run: `bash ~/.hermes/skills/revenium/scripts/prune-markers.sh --dry-run` then without `--dry-run`.
- The manual UAT triple-case from CONTEXT.md `<specifics>`.
- How to change the retention window via `REVENIUM_MARKER_RETENTION_DAYS`.
- Note that this is NOT auto-run from cron (D-28 explicit).

**Addition 2: Classifier behavior truth refresh**

The existing "How attribution works" section and "Mechanical classification hook" section describe the system correctly for wire-level behavior; no structural rewrite needed. Identify and update any stale sentence that claims "lookup-first reuse pressure" or "trivial-skip heuristic" (D-30/D-31). Replace with: mint-first framing (LLM mints specific labels; reuse only when exact match) and note D-07 heuristic skip was removed as dead code.

---

### `skills/revenium/references/task-taxonomy.md` (doc — framing refresh)

**Analog:** Self — grep the file for any sentence using "lookup-first", "reuse an existing label before minting", or D-07/D-8 references, and update to reflect mint-first framing per 260514-nfb quick task.

No structural change needed; the file describes the taxonomy schema and label format. Only the behavioral description of how the classifier selects labels needs updating.

---

### `README.md` (doc — two targeted updates)

**Analog:** Self.

1. Add a brief mention of `prune-markers.sh` in the operational section — e.g., after the existing cron installation description, one sentence noting operators should run the prune script periodically and reference `references/setup.md#marker-file-pruning`.
2. Grep for any claim framed as "lookup-first taxonomy reuse" in TAX-* wording and update to mint-first per D-31.

---

### `.planning/PROJECT.md` (planning doc — D-3/D-8 rewrite + Evolution Notes)

**Analog:** Self — in-place rewrite of rows in the `## Key Decisions` table plus append a new section.

**Current D-3 row (Key Decisions table):**
```
| Controlled-vocabulary taxonomy with strict lookup-first reuse | Pure free-form labels fragment ... | — Pending |
```

**Phase 5 target — rewrite in place:**
```
| LLM mints specific labels; reuses only on exact match | Pure free-form labels fragment without a vocabulary; mint-first with a recency-ordered existing list gives the LLM its current vocabulary without forcing reuse ("close enough" reuse caused taxonomy fragmentation in practice — 260514-nfb) | Shipped (Phase 5) |
```

**Current D-8 row:**
```
| Classify substantive turns only — D-07 heuristic skip | ... | — Pending |
```

**Phase 5 target:**
```
| D-07 heuristic skip removed (was dead code) | _count_tools_in_current_turn never returned non-None at the plugin entrypoint; quick task 260514-n8e removed the dead code path. Substantive-turn filtering was already achieved by the LLM itself (trivial turns produce trivial labels blocked by TRIVIAL_BLOCKLIST). | Shipped (Phase 5) |
```

**New section to append at EOF:**

```markdown
## Evolution Notes

| Date | Decision Affected | Quick Task | Change |
|------|-------------------|------------|--------|
| 2026-05-14 | D-3 | 260514-nfb | Lookup-first reuse pressure removed; LLM now mints specific labels and reuses only on identical work. |
| 2026-05-14 | D-8 | 260514-n8e | D-07 heuristic skip was dead code (response always None at the entrypoint); removed. |
```

---

### `.planning/REQUIREMENTS.md` (planning doc — checkbox flip)

**Analog:** Self — locate COMPAT-04 and TEST-05 rows, flip `[ ]` to `[x]`, update traceability column to `Verified (Phase 5)`.

---

### `.planning/ROADMAP.md` (planning doc — Phase 5 row update)

**Analog:** Self — add Plans list under the Phase 5 row (matching the format of Phase 4's row), update Progress Table status.

---

## Shared Patterns

### `set -euo pipefail` for new operator script
**Source:** `skills/revenium/scripts/clear-halt.sh` line 2, `skills/revenium/scripts/cron.sh` line 2
**Apply to:** `prune-markers.sh`

`prune-markers.sh` is a one-shot operator CLI (same category as `clear-halt.sh`): use `set -euo pipefail`, NOT `set -uo pipefail`. Hard-fail ensures partial runs don't go unnoticed. Do not change this to soft-fail.

### `set -uo pipefail` (soft-fail) preserved
**Source:** `skills/revenium/scripts/hermes-report.sh` line 5
**Apply to:** All edits within `hermes-report.sh` (WR-01, WR-02)

WR-01 and WR-02 are edits inside `hermes-report.sh` which uses soft-fail mode. Do NOT change the flag. The per-session `continue` and `|| true` guards that surround these code sites are already in place.

### `common.sh` single-source-of-truth discipline
**Source:** `skills/revenium/scripts/common.sh` + `tests/test_repository.py::test_runtime_paths_are_hermes_native`
**Apply to:** `prune-markers.sh`, `common.sh` additions

Every new state path (`PRUNE_LOCK_FILE`) and configurable default (`MARKER_RETENTION_DAYS`) must be declared in `common.sh` and nowhere else. `prune-markers.sh` references `${MARKER_RETENTION_DAYS}` and `${PRUNE_LOCK_FILE}` after sourcing `common.sh` — never hardcodes the values inline.

### Atomic write via temp + rename
**Source:** `skills/revenium/plugins/revenium-classifier/classifier.py::_write_marker_pair` (lines 374-378) + `skills/revenium/scripts/clear-halt.sh` Python block (lines 13-27)
**Apply to:** `_persist_label_to_taxonomy` in `classifier.py` (D-32)

```python
tmp = TAXONOMY_FILE.parent / (TAXONOMY_FILE.name + ".tmp")
tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
tmp.replace(TAXONOMY_FILE)
```

`os.replace` / `Path.replace` is atomic on POSIX — same guarantee as the marker write's `fcntl.LOCK_EX` append.

### Fail-open for non-critical I/O
**Source:** `skills/revenium/scripts/hermes-report.sh` per-session error handling; `skills/revenium/scripts/budget-check.sh` lines 64-70 (missing/corrupt JSON → empty dict)
**Apply to:** `_persist_label_to_taxonomy` (D-32), `_read_taxonomy_labels` D-33 extension

Any I/O exception in mint-back or taxonomy read wraps into `except Exception as exc: logger.warning(...)` and continues. Taxonomy failures must NEVER affect marker writes or the main classification pipeline.

### New test methods append to `RepositoryTests` — no new files
**Source:** `tests/test_repository.py` module structure + CLAUDE.md: "Tests live in `tests/test_repository.py`, no other files"
**Apply to:** All new tests (prune, mint-back, recency ordering)

Methods are independent and rely only on filesystem state. Import stdlib modules locally inside each method (matching the pattern of existing `RepositoryTests` methods). Use `with tempfile.TemporaryDirectory() as tmpdir:` for isolation.

### `test_required_files_exist` must include `prune-markers.sh`
**Source:** `tests/test_repository.py` lines 58-85 (the `expected` list)
**Apply to:** `prune-markers.sh` as a new expected file

Add `SKILL / 'scripts' / 'prune-markers.sh'` to the `expected` list. The test then covers existence + `bash -n` syntax validation automatically.

---

## No Analog Found

None. All files have a strong analog in the codebase (either self-modification or a role-match script).

---

## Metadata

**Analog search scope:** `skills/revenium/scripts/`, `skills/revenium/plugins/`, `tests/`, `skills/revenium/references/`, `.planning/`
**Files read:** `clear-halt.sh` (full), `common.sh` (full), `cron.sh` (full), `hermes-report.sh` (lines 1-60, 510-570), `classifier.py` (lines 1-50, 250-443), `task-taxonomy.json` (lines 1-30), `test_repository.py` (lines 1-130, 480-491, 2820-2898), `setup.md` (full), `04-PATTERNS.md` (full, for format reference)
**Pattern extraction date:** 2026-05-14
