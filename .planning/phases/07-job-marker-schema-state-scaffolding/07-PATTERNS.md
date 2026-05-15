# Phase 7: Job Marker Schema & State Scaffolding - Pattern Map

**Mapped:** 2026-05-15
**Files analyzed:** 3 modified files (common.sh, hermes-report.sh, tests/test_repository.py)
**Analogs found:** 3 / 3

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `skills/revenium/scripts/common.sh` | config/utility | file-I/O (state path declaration) | `common.sh` lines 17-22 (`TAXONOMY_FILE`, `MARKERS_DIR`, `MARKERS_READY_DIR`, `LOCK_FILE`, `PRUNE_LOCK_FILE`) | exact — same `:-` env-override fallback, same placement before `mkdir -p` |
| `skills/revenium/scripts/hermes-report.sh` | service | file-I/O + transform (JSONL reader, heredoc output emitter) | `hermes-report.sh` lines 377-445 (REQUIRED_KEYS block, per-line parse loop, `print(f"MARKERS_JSON=...")`) | exact — the `kind` branch is inserted into the existing parse loop; bash capture follows the existing `sed -n 's/^KEY=//p'` pattern |
| `tests/test_repository.py` | test | batch (unittest assertions) | `test_runtime_paths_are_hermes_native` (lines 118-132), `test_marker_file_schema` (lines 231-270), `test_cron_marker_split_end_to_end` (lines 356-747) | exact — same `assertIn`/`assertRegex` assertion style; same shim+tempdir harness |

---

## Pattern Assignments

### `skills/revenium/scripts/common.sh` — 2 new path declarations (SCHEMA-01)

**Analog:** `skills/revenium/scripts/common.sh` lines 17-22 (existing path declaration block)

**Core declaration pattern** (lines 17-22, the immediate template):
```bash
TAXONOMY_FILE="${REVENIUM_TAXONOMY_FILE:-${STATE_DIR}/task-taxonomy.json}"
MARKERS_DIR="${REVENIUM_MARKERS_DIR:-${STATE_DIR}/markers}"
MARKERS_READY_DIR="${REVENIUM_MARKERS_READY_DIR:-${STATE_DIR}/markers/.ready}"
LOCK_FILE="${STATE_DIR}/cron.lock"
MARKER_RETENTION_DAYS="${REVENIUM_MARKER_RETENTION_DAYS:-30}"
PRUNE_LOCK_FILE="${STATE_DIR}/prune.lock"

mkdir -p "${STATE_DIR}" "${MARKERS_DIR}" "${MARKERS_READY_DIR}"
```

**Phase 7 additions — copy after `PRUNE_LOCK_FILE` line, before `mkdir -p`:**
- `JOBS_LEDGER_FILE` mirrors `LEDGER_FILE` (line 13) — same filename pattern `revenium-*.ledger`, same `:-` shape with env-override
- `JOB_TAXONOMY_FILE` mirrors `TAXONOMY_FILE` (line 17) — same `:-` shape, declared for forward-compat, no file created on disk

**Insertion point:** After line 22 (`PRUNE_LOCK_FILE="${STATE_DIR}/prune.lock"`), before line 24 (`mkdir -p ...`).

**Naming discipline from CLAUDE.md:**
- Env-override var: `REVENIUM_JOBS_LEDGER_FILE`, `REVENIUM_JOB_TAXONOMY_FILE` — `SCREAMING_SNAKE_CASE`
- Bash variable: `JOBS_LEDGER_FILE`, `JOB_TAXONOMY_FILE` — same
- File names: `revenium-jobs.ledger`, `job-taxonomy.json` — `kebab-case`

**Critical constraint:** The string literals `revenium-jobs.ledger` and `job-taxonomy.json` must appear in `common.sh` — `test_runtime_paths_are_hermes_native` will be extended to assert `assertIn('revenium-jobs.ledger', text)` etc.

---

### `skills/revenium/scripts/hermes-report.sh` — `touch` + `kind` branch + `JOBS_JSON` output (SCHEMA-03)

**Analog A — `touch` pattern** (line 34):
```bash
touch "${LEDGER_FILE}"
```
Phase 7 adds `touch "${JOBS_LEDGER_FILE}"` on the immediately following line. Same script, same startup block, before preflight tool checks. This is the only correct location (mirrors how `LEDGER_FILE` is initialized).

**Analog B — per-line parse loop** (lines 377-445 in Python heredoc):

Existing code structure to be modified (lines 377-424):
```python
FORBIDDEN = {'ack', 'acknowledgment', 'greeting', 'confirmation', 'hello', 'thanks'}
REQUIRED_KEYS = ('muid', 'ts', 'sid', 'task_type', 'operation_type')

marker_path = Path(markers_dir) / f"{sid}.jsonl"
markers = []
read_ok = True
read_err = ""
if marker_path.is_file():
    try:
        with marker_path.open() as f:
            for line in f:
                line = line.rstrip('\n')
                if not line:
                    continue
                if len(line) > 4096:
                    continue
                try:
                    m = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not all(k in m for k in REQUIRED_KEYS):   # <-- kind branch goes BEFORE this
                    continue
                if m['muid'] in prior_muids:
                    continue
                ...
                markers.append(m)
```

The `kind` branch must be inserted **after** `json.loads(line)` and **before** the `REQUIRED_KEYS` check. Also `jobs_by_id = {}` must be initialized **before** `if marker_path.is_file():` (so it is in scope when `JOBS_JSON` is printed even if the file is absent).

**Analog C — heredoc output pattern** (lines 440-445):
```python
print(f"READ_OK={'true' if read_ok else 'false'}")
if read_err:
    print(f"READ_ERR={read_err}")
print(f"N_MARKERS={n}")
print(f"PRIOR_MUIDS_COUNT={len(prior_muids)}")
print(f"MARKERS_JSON={json.dumps(markers, separators=(',', ':'))}")
```
The new `JOBS_JSON=` line follows this same `print(f"KEY={value}")` form, appended after the existing output lines.

**Analog D — bash `sed` capture** (lines 449-486):
```bash
if [[ -n "${marker_output}" ]]; then
  read_ok=$(echo "${marker_output}" | sed -n 's/^READ_OK=//p' | head -1)
  n_markers=$(echo "${marker_output}" | sed -n 's/^N_MARKERS=//p' | head -1)
  ...
  markers_json=$(echo "${marker_output}" | sed -n 's/^MARKERS_JSON=//p' | head -1)
```
The new bash variable `jobs_json` is captured with the identical `sed -n 's/^JOBS_JSON=//p' | head -1` pattern. In Phase 7 the variable is declared `local` and assigned, but not consumed further.

---

### `tests/test_repository.py` — 2 new test methods + 2 new assertions in existing method (TEST-01, TEST-02)

**Analog A — path assertion method** (`test_runtime_paths_are_hermes_native`, lines 118-132):
```python
def test_runtime_paths_are_hermes_native(self):
    text = (SKILL / 'scripts' / 'common.sh').read_text()
    self.assertIn('.hermes', text)
    self.assertIn('state/revenium', text)
    self.assertNotIn('.openclaw', text)
    self.assertIn('task-taxonomy.json', text)
    self.assertIn('TAXONOMY_FILE=', text)
    self.assertRegex(text, r'MARKERS_DIR="\$\{REVENIUM_MARKERS_DIR:-\$\{STATE_DIR\}/markers\}"')
    ...
    self.assertIn('LOCK_FILE=', text)
    self.assertIn('cron.lock', text)
```
Phase 7 extends this method by appending 4 new assertions (after line 132):
```python
self.assertIn('JOBS_LEDGER_FILE=', text)
self.assertIn('revenium-jobs.ledger', text)
self.assertIn('JOB_TAXONOMY_FILE=', text)
self.assertIn('job-taxonomy.json', text)
```

**Analog B — schema pin test** (`test_marker_file_schema`, lines 231-270):
```python
def test_marker_file_schema(self):
    """Marker fixture records contain only allow-listed keys and are < 1024 bytes."""
    import json, re
    allow_listed_required = {'muid', 'ts', 'sid', 'task_type', 'operation_type'}
    fixture_records = [
        {"muid": "01893b8a300abcdef0123456789abcdef", "ts": 1715515200.0,
         "sid": "test-session", "task_type": "code_review",
         "operation_type": "GUARDRAIL"},
        ...
    ]
    for record in fixture_records:
        ...
        line = json.dumps(record, separators=(',', ':')) + '\n'
        self.assertLess(len(line.encode('utf-8')), 1024, ...)
        self.assertRegex(record['task_type'], r'^[a-z][a-z0-9_]{1,47}$', ...)
```
`test_job_marker_schema` (TEST-01) copies this structure: instantiate canonical D-03 fixture, assert D-04 reader-required keys present, assert all keys are snake_case (no uppercase), assert `kind == "job"`, assert compact JSONL serialization fits within 1024 bytes, assert a minimal valid job line (no optional fields) is also valid.

**Analog C — end-to-end regression test** (`test_cron_marker_split_end_to_end`, lines 356-747):
Key helpers to copy for TEST-02:
```python
def build_state_db(path, sessions):
    conn = sqlite3.connect(str(path))
    conn.execute('CREATE TABLE sessions (...)')
    for s in sessions:
        conn.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', ...)
    conn.commit(); conn.close()

def run_cron(env, invocations_log):
    result = subprocess.run(['bash', str(HERMES_REPORT)], env=env, ...)
    invocations = []
    with open(invocations_log) as f:
        for line in f:
            import shlex; invocations.append(shlex.split(line.rstrip('\n')))
    return result.returncode, invocations, result.stdout + result.stderr

def argv_to_flags(argv):
    d = {}
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok.startswith('--'):
            if i + 1 < len(argv) and not argv[i + 1].startswith('--'):
                d[tok] = argv[i + 1]; i += 2
            else:
                d[tok] = True; i += 1
        else:
            i += 1
    return d
```

Shim pattern (lines 462-482) — the `revenium` shim that logs `meter completion` args:
```bash
#!/usr/bin/env bash
case "$1" in
  config) exit 0 ;;
  meter)
    shift; shift
    printf "%q " "$@" >> "$INVOCATIONS_LOG"
    printf "\n" >> "$INVOCATIONS_LOG"
    exit 0
    ;;
  *) exit 0 ;;
esac
```

The `tmpdir`, `shim_home`, `bin_dir` scaffolding at lines 448-492 is reused verbatim for TEST-02. The regression assertion is: run with task markers + a job line in the JSONL file → same `meter completion` argv as running with task markers alone.

---

## Shared Patterns

### Single-source state path declaration
**Source:** `skills/revenium/scripts/common.sh` lines 11-22
**Apply to:** `JOBS_LEDGER_FILE` and `JOB_TAXONOMY_FILE` in the same file
```bash
# Pattern: VAR="${ENV_OVERRIDE_VAR:-${STATE_DIR}/filename}"
LEDGER_FILE="${STATE_DIR}/revenium-hermes.ledger"         # no env-override (existing)
TAXONOMY_FILE="${REVENIUM_TAXONOMY_FILE:-${STATE_DIR}/task-taxonomy.json}"  # with env-override
MARKERS_DIR="${REVENIUM_MARKERS_DIR:-${STATE_DIR}/markers}"                 # with env-override
PRUNE_LOCK_FILE="${STATE_DIR}/prune.lock"                  # no env-override (existing)
```
`JOBS_LEDGER_FILE` and `JOB_TAXONOMY_FILE` use the env-override shape (with `REVENIUM_` prefix), identical to `TAXONOMY_FILE` and `MARKERS_DIR`.

### Startup `touch` for ledger files
**Source:** `skills/revenium/scripts/hermes-report.sh` line 34
**Apply to:** `touch "${JOBS_LEDGER_FILE}"` — immediately after the existing `touch "${LEDGER_FILE}"` line, in the same script, before preflight checks.
```bash
touch "${LEDGER_FILE}"
touch "${JOBS_LEDGER_FILE}"   # Phase 7 addition
```

### Heredoc per-line resiliency
**Source:** `hermes-report.sh` lines 390-398
**Apply to:** The `kind` branch in Phase 7. The existing pattern handles malformed lines with `try/except json.JSONDecodeError: continue` and a 4 KB line-length cap. The `kind` branch inherits this resiliency — it is placed after `json.loads(line)` succeeds and never raises.
```python
if len(line) > 4096:
    continue
try:
    m = json.loads(line)
except json.JSONDecodeError:
    continue
# kind branch goes here — BEFORE REQUIRED_KEYS check
```

### Heredoc `KEY=value` output + bash `sed` capture
**Source:** `hermes-report.sh` lines 440-445 (Python), lines 449-486 (bash)
**Apply to:** `JOBS_JSON=` output line + `jobs_json` bash variable capture. Same `print(f"KEY={json.dumps(...)}")` form in Python, same `sed -n 's/^KEY=//p' | head -1` form in bash.

### `assertIn` + `assertRegex` path test assertions
**Source:** `tests/test_repository.py` lines 118-132 (`test_runtime_paths_are_hermes_native`)
**Apply to:** 4 new assertions appended to the same method for `JOBS_LEDGER_FILE`, `revenium-jobs.ledger`, `JOB_TAXONOMY_FILE`, `job-taxonomy.json`. Same `self.assertIn(string, text)` form — no `assertRegex` needed unless the full variable declaration pattern is pinned (optional stricter form mirrors line 125-126).

### `RepositoryTests` class structure
**Source:** `tests/test_repository.py` lines 55-747
**Apply to:** Both new test methods (`test_job_marker_schema`, `test_job_marker_does_not_alter_task_completion_argv`) are added as methods of the existing `RepositoryTests(unittest.TestCase)` class. No new class or file needed.

---

## No Analog Found

None. All three modified files have exact analogs in the existing codebase. The patterns for all Phase 7 changes — path declarations, `touch` startup, heredoc branching, output emission, bash capture, test assertions, and the end-to-end shim harness — are present verbatim in the current codebase.

---

## Metadata

**Analog search scope:**
- `skills/revenium/scripts/common.sh` (full file, 45 lines)
- `skills/revenium/scripts/hermes-report.sh` lines 29-35 (touch/preflight), lines 320-510 (marker reader heredoc + bash capture)
- `tests/test_repository.py` lines 1-747 (full file)

**Files scanned:** 3 (all primary; no secondary scan needed — early stopping at 3 strong exact matches)
**Pattern extraction date:** 2026-05-15
