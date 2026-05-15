# Phase 7: Job Marker Schema & State Scaffolding - Research

**Researched:** 2026-05-15
**Domain:** Bash shell scripting, Python heredocs, JSONL schema extension, append-only ledger design, unittest
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01:** The `kind:"job"` marker is an additive JSONL line in the existing per-session `markers/<sid>.jsonl` file — never a per-turn field on a task marker, never a separate file. It is discriminated solely by the `kind` key.

**D-02:** Job marker keys are **snake_case**, consistent with the v1.0 task marker keys. `agenticJobId` becomes `agentic_job_id`. config.json / budget-status.json camelCase is a different contract.

**D-03:** Canonical job marker shape:
```json
{"kind":"job","ts":1747300000.12,"sid":"abc123",
 "agentic_job_id":"pr-review-fc7a","job_name":"Review PR #42",
 "job_type":"code_review","status":"SUCCESS"}
```

**D-04:** Reader-required keys for a `kind:"job"` line to be **accepted**: `kind`, `agentic_job_id`, `job_type`, `status`. Missing any → skip. `job_name`, `ts`, `sid` are optional.

**D-05:** "Reader-required" (D-04) is a separate, job-only validation gate — NOT the task-marker `REQUIRED_KEYS` tuple. `REQUIRED_KEYS` stays exactly `('muid', 'ts', 'sid', 'task_type', 'operation_type')`, unchanged.

**D-06:** The marker reader branches on `kind`:
- absent `kind` → v1.0 task marker path, byte-identical behavior.
- `kind:"job"` → collected as a job declaration.
- any other `kind` value → skipped.

**D-07:** An un-modified v1.0 cron naturally skips `kind:"job"` lines because they fail the task-marker `REQUIRED_KEYS` check — backward compat preserved without a separate guard.

**D-08:** Attribution is **positional (delimiter-based)**. A `kind:"job"` marker claims all task markers above it in file order, back to the previous `kind:"job"` or file start.

**D-09:** The job marker carries **no per-task linkage fields** (no muid list, no ranges). v1.0 task markers are written unchanged.

**D-10:** Explicit per-task back-references were rejected: jobs are declared retrospectively, so a task marker cannot carry a job id at write time.

**D-11:** Task markers after the last `kind:"job"` in a file belong to an undeclared arc and meter as v1.0 (no `--task-id`).

**D-12:** Reader collects all valid `kind:"job"` lines, then collapses to one declaration per `agentic_job_id`, **last line in file order winning**.

**D-13:** `scripts/common.sh` declares **both** new paths, and only there, using the existing `:-` env-override fallback shape:
- `JOBS_LEDGER_FILE="${REVENIUM_JOBS_LEDGER_FILE:-${STATE_DIR}/revenium-jobs.ledger}"`
- `JOB_TAXONOMY_FILE="${REVENIUM_JOB_TAXONOMY_FILE:-${STATE_DIR}/job-taxonomy.json}"`

**D-14:** `revenium-jobs.ledger` is a **separate file** from `revenium-hermes.ledger` — never reuse the metering ledger.

**D-15:** `revenium-jobs.ledger` is `touch`-created on cron run. `JOB_TAXONOMY_FILE` is declared for forward-compat only — unused in v1.1.

### Claude's Discretion
- Exact env-var names (`REVENIUM_JOBS_LEDGER_FILE` etc.) and the precise line of `common.sh` to insert declarations are planner/executor choices.
- The precise internal Python structure of the reader branch is a planner choice.
- Whether `revenium-jobs.ledger` line format is fully specified here or deferred to Phase 9.

### Deferred Ideas (OUT OF SCOPE)
- Host-grown job taxonomy — `JOB_TAXONOMY_FILE` declared but no reader/writer until v2 `JOBTAX-01`.
- `revenium-jobs.ledger` line grammar pinning — may be deferred to Phase 9/10 planning.
- Outcome enrichment (`outcome_type` / `outcome_value`) — v2 `ENRICH-01/02`.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SCHEMA-01 | New state paths (`JOBS_LEDGER_FILE` for `revenium-jobs.ledger`, and `JOB_TAXONOMY_FILE`) declared in `scripts/common.sh` only, with `:-` env-override fallback shape. | Path declaration pattern is fully verified in current `common.sh`. Exact env-var names per D-13 are confirmed planner discretion. |
| SCHEMA-02 | A `kind:"job"` JSONL line schema is defined and documented as an additive extension to `markers/<sid>.jsonl` — never a per-turn field, never a separate file. | Schema D-03/D-04 fully locked. Existing marker file format (compact JSONL, snake_case) is the template. |
| SCHEMA-03 | Cron marker reader branches on `kind`: absent→`"task"` (v1.0 byte-identical), `kind:"job"`→job declaration, unknown→skip. | Exact insertion point verified: Python heredoc at `hermes-report.sh:376–424`, just after REQUIRED_KEYS check. |
| SCHEMA-04 | Job-less / marker-less session produces byte-identical `revenium meter completion` argv to v1.0 — backward compat verified not assumed. | The zero-marker fallthrough at `hermes-report.sh:611–675` is unchanged. TEST-02 regression test structure is modeled on existing `test_cron_marker_split_end_to_end` sub-case 2. |
| SCHEMA-05 | New job-marker fields are `.get()`-optional; `REQUIRED_KEYS` for task markers is unchanged so an un-modified v1.0 cron skips job lines. | `REQUIRED_KEYS = ('muid', 'ts', 'sid', 'task_type', 'operation_type')` at line 377. Job lines missing `muid` fail this check naturally and are skipped in v1.0 readers. |
| TEST-01 | A test pins the `kind:"job"` marker schema shape. | New unittest method in `test_repository.py`. Pattern is identical to existing `test_marker_file_schema` at line 231. |
| TEST-02 | A regression test asserts a job-less marker produces byte-identical `meter completion` argv to v1.0. | Uses same shim+tempdir pattern as `test_cron_marker_split_end_to_end`. Reference argv can be captured from the existing zero-marker sub-case. |
</phase_requirements>

---

## Summary

Phase 7 is pure additive scaffolding — zero behavior change. It has three distinct sub-problems that each have a clear, low-risk implementation path grounded in the existing codebase.

**Sub-problem 1: `common.sh` path declarations.** The existing path declaration block (`lines 11–22`) follows a uniform `VAR="${ENV_OVERRIDE:-${STATE_DIR}/filename}"` pattern. Two new declarations follow this pattern: `JOBS_LEDGER_FILE` and `JOB_TAXONOMY_FILE`. The `mkdir -p` block at line 24 does not need to change for these files; `JOBS_LEDGER_FILE` is `touch`-created inside `hermes-report.sh` (mirroring the existing `touch "${LEDGER_FILE}"` at line 34). The `test_runtime_paths_are_hermes_native` test currently asserts specific regex patterns for existing paths; Phase 7 must add parallel assertions for the two new variables.

**Sub-problem 2: `hermes-report.sh` reader `kind` branch.** The marker reader is a Python heredoc (`lines 334–446`). The per-line parse loop collects task markers into a `markers: list` by applying `REQUIRED_KEYS` membership check and muid dedup. The `kind` branch is inserted immediately after the `json.loads(line)` parse, before the `REQUIRED_KEYS` check — this preserves the v1.0 path byte-identically (a line with absent `kind` falls through to the existing `REQUIRED_KEYS` check). The job collector is a separate local dict; the heredoc emits a new `JOBS_JSON=` output line alongside the existing `MARKERS_JSON=` and `N_MARKERS=` outputs. At Phase 7 the bash side of the reader does nothing with `JOBS_JSON` — it captures it with `sed` but ignores it. The key discipline is that the branch must not alter `markers` list population or `N_MARKERS` for the unchanged task-marker path.

**Sub-problem 3: Tests.** Two new test methods added to the existing `RepositoryTests` class in `tests/test_repository.py`. TEST-01 (`test_job_marker_schema`) pins the D-03 canonical shape and the D-04 reader-required keys using the same fixture pattern as `test_marker_file_schema`. TEST-02 (`test_job_marker_does_not_alter_task_completion_argv`) uses the same shim+tempdir plumbing as `test_cron_marker_split_end_to_end`; it writes a marker file containing one `kind:"job"` line alongside task markers for a session, runs `hermes-report.sh`, and asserts the resulting argv is byte-identical to what v1.0 emits for those same task markers. A separate zero-marker sub-case in TEST-02 can also verify the no-marker session is unaffected.

**Primary recommendation:** Implement in three sequential tasks: (1) `common.sh` + `test_runtime_paths_are_hermes_native` extension, (2) reader branch in `hermes-report.sh`, (3) TEST-01 + TEST-02. Each task is independently verifiable: task 1 is unit-testable with the existing test method, task 2 is verifiable with `bash -n` and a smoke run, task 3 completes the phase gate.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| State path declaration | `common.sh` (single source of truth) | — | Enforced by `test_runtime_paths_are_hermes_native` + CLAUDE.md architecture constraint |
| `revenium-jobs.ledger` file creation | `hermes-report.sh` (startup `touch`) | — | Mirrors existing `LEDGER_FILE` touch at line 34; cron.sh invokes hermes-report.sh first |
| `kind` branching in marker reader | `hermes-report.sh` Python heredoc | — | Reader already lives here; branch is a local modification of the per-line parse loop |
| Job collector output | `hermes-report.sh` Python heredoc | bash var capture | Emitted as `JOBS_JSON=` line; bash captures with `sed`, ignores in Phase 7 |
| TEST-01 schema pin | `tests/test_repository.py` | — | All invariant tests live in this single test class |
| TEST-02 regression | `tests/test_repository.py` | — | Uses same shim machinery as the existing end-to-end test |

## Standard Stack

### Core

| Component | Version/Form | Purpose | Why Standard |
|-----------|-------------|---------|--------------|
| Bash | 3.2+ (macOS minimum per v1.0 lesson) | Script logic, variable declarations | Existing runtime requirement |
| Python 3 (stdlib only) | `python3` invocation | JSON parsing in heredoc, test logic | Existing pattern throughout |
| Python `unittest` (stdlib) | `class RepositoryTests(unittest.TestCase)` | Test enforcement | Existing test infrastructure |
| `json` module | stdlib | JSONL parsing/serialization | Used throughout heredocs |

**No new runtime dependencies.** [VERIFIED: CLAUDE.md constraint, codebase grep]

### Supporting Patterns (existing, reused)

| Pattern | Location | Reused In Phase 7 |
|---------|----------|-------------------|
| `VAR="${ENV_OVERRIDE:-${STATE_DIR}/file}"` | `common.sh:17–19` | `JOBS_LEDGER_FILE` and `JOB_TAXONOMY_FILE` declarations |
| `touch "${LEDGER_FILE}"` | `hermes-report.sh:34` | `touch "${JOBS_LEDGER_FILE}"` immediately after |
| Per-line `try/except json.JSONDecodeError: continue` | `hermes-report.sh:396–398` | `kind` branch inherits same resiliency |
| `KEY=value\nNEXT=value` heredoc output parsed by `sed -n 's/^KEY=//p'` | `hermes-report.sh:450–466` | `JOBS_JSON=` output line + bash capture |
| `shim + tmpdir + subprocess.run` test harness | `test_repository.py:410–429` | TEST-02 reuses identical shim and `argv_to_flags` helper |
| `json.dumps(record, separators=(",",":")` compact JSONL | `SKILL.md:356` | D-03 job marker serialization format |

## Architecture Patterns

### System Architecture Diagram

```
markers/<sid>.jsonl (append-only, one line per event)
  ├── {"muid":"...","ts":...,"sid":"...","task_type":"...","operation_type":"..."}  ← v1.0 task line
  ├── {"muid":"...","ts":...,"sid":"...","task_type":"...","operation_type":"..."}  ← v1.0 task line
  └── {"kind":"job","ts":...,"sid":"...","agentic_job_id":"...","job_type":"...","status":"..."} ← new v1.1 job line

hermes-report.sh marker reader (per-session Python heredoc)
  ├── json.loads(line)
  ├── kind = m.get("kind")  [NEW BRANCH POINT]
  │   ├── kind absent → task_path (REQUIRED_KEYS check → markers.append(m))   ← unchanged
  │   ├── kind == "job" → job_path (D-04 check → jobs_by_id[agentic_job_id] = m)  ← NEW
  │   └── kind == other → skip                                                 ← NEW
  ├── N_MARKERS=<n>          (unchanged output)
  ├── MARKERS_JSON=<json>    (unchanged output)
  └── JOBS_JSON=<json>       (NEW output — ignored by bash in Phase 7)

~/.hermes/state/revenium/
  ├── revenium-hermes.ledger   (existing — unchanged)
  ├── revenium-jobs.ledger     (NEW — touch-created on cron run, empty in Phase 7)
  └── job-taxonomy.json        (NEW path declared only — no file created in Phase 7)
```

### Recommended Project Structure

No new directories. All changes are:
- `skills/revenium/scripts/common.sh` — 2 new variable declarations
- `skills/revenium/scripts/hermes-report.sh` — kind branch in existing Python heredoc, second `touch`
- `tests/test_repository.py` — 2 new test methods, 2 new assertions in existing test method

### Pattern 1: common.sh Path Declaration Template

**What:** All state paths are declared once in `common.sh` using the `:-` env-override fallback shape, immediately after existing path declarations.

**When to use:** Any new state file, every time, without exception.

**Example:**
```bash
# Source: skills/revenium/scripts/common.sh:17–19 (existing patterns)
TAXONOMY_FILE="${REVENIUM_TAXONOMY_FILE:-${STATE_DIR}/task-taxonomy.json}"
MARKERS_DIR="${REVENIUM_MARKERS_DIR:-${STATE_DIR}/markers}"
LOCK_FILE="${STATE_DIR}/cron.lock"

# Phase 7 additions (immediately after PRUNE_LOCK_FILE, before mkdir -p):
JOBS_LEDGER_FILE="${REVENIUM_JOBS_LEDGER_FILE:-${STATE_DIR}/revenium-jobs.ledger}"
JOB_TAXONOMY_FILE="${REVENIUM_JOB_TAXONOMY_FILE:-${STATE_DIR}/job-taxonomy.json}"
```

### Pattern 2: `kind` Branch in Per-Line Parse Loop

**What:** Insert a `kind` discriminator immediately after `json.loads(line)`, before the `REQUIRED_KEYS` check. This preserves backward compat: a line with absent `kind` falls through the existing `REQUIRED_KEYS` gate unchanged. A line with `kind:"job"` is diverted to a separate collector and never reaches `markers.append(m)`.

**When to use:** This is the sole location of the branch — do not add branching elsewhere.

**Example:**
```python
# Source: skills/revenium/scripts/hermes-report.sh (adapted for Phase 7)
# After: try: m = json.loads(line)
# Before: if not all(k in m for k in REQUIRED_KEYS):

kind = m.get("kind")
if kind == "job":
    # D-04: validate reader-required keys; skip if any missing
    if all(k in m for k in ("agentic_job_id", "job_type", "status")):
        # D-12: last line wins per agentic_job_id
        jobs_by_id[m["agentic_job_id"]] = m
    continue  # never reaches task-marker collector
elif kind is not None:
    # unknown kind — skip for forward compat (D-06)
    continue
# kind is None (absent) → fall through to existing REQUIRED_KEYS check
```

Note: `jobs_by_id: dict` is initialized at the top of the marker-reading block, before the file-open loop.

### Pattern 3: Heredoc Output Emission + Bash Capture

**What:** The Python heredoc emits one additional `KEY=value` line at the end. The bash side captures it with `sed`. In Phase 7, the bash side captures but does not act on `JOBS_JSON`.

**Example:**
```python
# At the end of the heredoc, after existing print() calls:
print(f"JOBS_JSON={json.dumps(list(jobs_by_id.values()), separators=(',', ':'))}")
```

```bash
# In bash, after existing sed captures:
local jobs_json
jobs_json=$(echo "${marker_output}" | sed -n 's/^JOBS_JSON=//p' | head -1)
# Phase 7: jobs_json captured but not used — Phase 9 will consume it.
```

### Pattern 4: Test Structure for Schema Pin (TEST-01)

**What:** A pure-Python unit test that instantiates the canonical D-03 fixture, asserts all required keys are present, asserts optional keys can be absent, and asserts the line serializes compactly. Mirrors `test_marker_file_schema`.

**Example:**
```python
def test_job_marker_schema(self):
    """TEST-01: pins the kind:"job" marker schema shape per D-03/D-04."""
    import json
    job_marker = {
        "kind": "job",
        "ts": 1747300000.12,
        "sid": "abc123",
        "agentic_job_id": "pr-review-fc7a",
        "job_name": "Review PR #42",   # optional
        "job_type": "code_review",
        "status": "SUCCESS",
    }
    reader_required = ("agentic_job_id", "job_type", "status")
    # D-04: all reader-required keys present
    for k in reader_required:
        self.assertIn(k, job_marker, f'reader-required key "{k}" missing')
    # D-02: all keys are snake_case (no camelCase)
    for k in job_marker:
        self.assertNotRegex(k, r'[A-Z]', f'key "{k}" must be snake_case')
    # D-01: kind discriminator present and correct
    self.assertEqual(job_marker["kind"], "job")
    # Serialization: compact JSONL
    line = json.dumps(job_marker, separators=(",", ":")) + "\n"
    self.assertLess(len(line.encode("utf-8")), 1024, "job marker line must be < 1024 bytes")
    # Optional fields: a minimal valid job line (no job_name, no ts, no sid)
    minimal = {
        "kind": "job",
        "agentic_job_id": "pr-review-fc7a",
        "job_type": "code_review",
        "status": "SUCCESS",
    }
    for k in reader_required:
        self.assertIn(k, minimal)
    self.assertNotIn("job_name", minimal)  # optional — absence is valid
```

### Pattern 5: Regression Test Structure (TEST-02)

**What:** An end-to-end test that uses the existing shim harness, writes a JSONL marker file containing both task markers AND a `kind:"job"` line, runs `hermes-report.sh`, and asserts the resulting argv list is byte-identical to the v1.0 reference argv (produced by running the same task markers without the job line). The key assertion is that adding a job line to the marker file does not change the `revenium meter completion` call for the task tokens.

**Critical detail:** The shim captures `meter completion` args. `jobs create` calls are not yet issued in Phase 7, so the shim only sees `meter` calls. The regression is: same task markers + job line in the file → same meter argv as task markers alone.

### Anti-Patterns to Avoid

- **Modifying `REQUIRED_KEYS`:** This tuple is the v1.0 backward-compat contract. It must not change in Phase 7. [VERIFIED: CLAUDE.md]
- **Adding `kind` check before `json.loads`:** The `kind` check can only happen after successful JSON parse. Lines that fail `json.loads` are already skipped by the existing `except json.JSONDecodeError: continue`.
- **Appending to `markers` for job lines:** A `kind:"job"` line that reaches `markers.append(m)` would be passed to `equal_split` and generate spurious `revenium meter completion` calls.
- **Creating `job-taxonomy.json` on disk:** The file path is declared in `common.sh` for forward-compat only. Phase 7 must not write or `touch` this file — only declare the variable. [VERIFIED: D-15]
- **Writing job ledger lines in Phase 7:** `revenium-jobs.ledger` is `touch`-created (empty) in Phase 7. No content is written until Phase 9.
- **Hardcoding env var names outside `common.sh`:** The `REVENIUM_JOBS_LEDGER_FILE` env-var name must appear only in `common.sh`. [VERIFIED: CLAUDE.md constraint]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON parse resiliency | Custom line parser | Existing `try/except json.JSONDecodeError: continue` in the heredoc | Already handles torn lines, oversized lines, malformed content |
| Backward-compat for unknown `kind` values | Version-number gating | Forward-compat `elif kind is not None: continue` branch | Simpler, zero maintenance, is the established JSONL extension pattern |
| Deduplication of repeated job lines | Hash set across cron ticks | `last-wins` per `agentic_job_id` in memory within a single cron tick | The file is re-read every cron tick; in-tick dedup is sufficient for Phase 7 |
| Custom test harness for TEST-02 | New subprocess fixtures | Existing `build_state_db`, `run_cron`, `argv_to_flags` helpers in `test_cron_marker_split_end_to_end` | Copy these as local helpers in the new test method, or extract to module-level |

## Common Pitfalls

### Pitfall 1: `kind` Check AFTER `REQUIRED_KEYS` Check Breaks SCHEMA-05

**What goes wrong:** If the `kind` branch is placed after `if not all(k in m for k in REQUIRED_KEYS)`, then `kind:"job"` lines (which lack `muid`) are dropped before reaching the branch.

**Why it happens:** Natural instinct to add the new branch "at the end" of the existing filter chain.

**How to avoid:** Insert the `kind` check as the FIRST conditional after `json.loads(line)`. The `REQUIRED_KEYS` check only runs when `kind` is absent (task marker path). The test for this: a marker file with a valid `kind:"job"` line produces `N_JOBS=1` in reader output.

**Warning signs:** TEST-01 passes (pure schema test) but TEST-02 reports `N_JOBS=0` when a job line is present.

### Pitfall 2: `jobs_by_id` Variable Not Initialized Before Loop

**What goes wrong:** `NameError: name 'jobs_by_id' is not defined` at runtime if `jobs_by_id = {}` is placed inside the `if marker_path.is_file():` block but the file is absent.

**Why it happens:** Python heredoc — the `jobs_by_id` collector must be in scope at the `print(f"JOBS_JSON=...")` line even when the marker file does not exist.

**How to avoid:** Initialize `jobs_by_id = {}` immediately after the `REQUIRED_KEYS = (...)` line, before the `if marker_path.is_file():` block.

### Pitfall 3: `JOBS_JSON` Contains Pipe Characters That Corrupt Bash IFS Parsing

**What goes wrong:** A `job_name` or `agentic_job_id` containing `|` would corrupt the bash `while IFS='|' read -r` parser if `JOBS_JSON` were ever consumed by a pipe-delimited bash loop.

**Why it happens:** `json.dumps` does not escape pipe characters. Phase 7 does not consume JOBS_JSON in bash (it is ignored), so this is not a current bug — but it must be noted for Phase 9 planning.

**How to avoid (Phase 7):** The `JOBS_JSON=` line is parsed with `sed` and stored in a bash variable, never IFS-split. Phase 9 must apply the same WR-01 sanitization (`replace('|', '_')`) if it ever pipe-splits job fields.

**Warning signs:** Not observable in Phase 7. Documented here for the Phase 9 planner.

### Pitfall 4: `test_runtime_paths_are_hermes_native` Not Extended

**What goes wrong:** The test passes (it checks only existing variables) but the planner/verifier is misled into thinking the new paths are asserted. The success criterion requires `test_runtime_paths_are_hermes_native` to still pass — which it will even WITHOUT the new assertions. The test needs new `assertIn` / `assertRegex` calls for `JOBS_LEDGER_FILE` and `JOB_TAXONOMY_FILE`.

**How to avoid:** Explicitly extend the test method with assertions for:
- `self.assertIn('JOBS_LEDGER_FILE=', text)` 
- `self.assertIn('revenium-jobs.ledger', text)`
- `self.assertIn('JOB_TAXONOMY_FILE=', text)`
- `self.assertIn('job-taxonomy.json', text)`

### Pitfall 5: `touch "${JOBS_LEDGER_FILE}"` Placed in Wrong Script

**What goes wrong:** Placing the `touch` in `cron.sh` (the orchestrator) rather than `hermes-report.sh` means the file is created by a different script than the one that will eventually write to it (Phase 9). This creates a subtle ordering dependency.

**How to avoid:** Follow the existing `touch "${LEDGER_FILE}"` at `hermes-report.sh:34` — the jobs ledger `touch` goes in the same script, immediately after, before the preflight `if !` checks for tools.

### Pitfall 6: Mac Studio bash 3.2 Compatibility

**What goes wrong:** New bash code uses bash 4+ features (e.g., `declare -A` associative arrays, `${VAR@Q}` quoting) that fail silently or with cryptic errors on macOS bash 3.2.57.

**Why it happens:** Dev machine uses a Homebrew bash 5.x; the live host (Mac Studio, `ssh 172.16.1.175`) runs Apple's bash 3.2.57.

**How to avoid:** The `kind` branch is entirely in Python (a heredoc). No new bash associative arrays are needed. Bash only captures `JOBS_JSON` with `sed` into a scalar string variable — valid in bash 3.2. Verify any bash-side changes by running `bash --version` awareness. The existing `test_shell_scripts_have_valid_syntax` catches syntax errors but does not catch semantic bash-4-only constructs.

## Code Examples

### common.sh additions (exact location)

```bash
# Source: skills/revenium/scripts/common.sh (after PRUNE_LOCK_FILE, before mkdir -p)
PRUNE_LOCK_FILE="${STATE_DIR}/prune.lock"
JOBS_LEDGER_FILE="${REVENIUM_JOBS_LEDGER_FILE:-${STATE_DIR}/revenium-jobs.ledger}"
JOB_TAXONOMY_FILE="${REVENIUM_JOB_TAXONOMY_FILE:-${STATE_DIR}/job-taxonomy.json}"

mkdir -p "${STATE_DIR}" "${MARKERS_DIR}" "${MARKERS_READY_DIR}"
```

### hermes-report.sh: second touch (exact location)

```bash
# Source: skills/revenium/scripts/hermes-report.sh (after existing touch on line 34)
touch "${LEDGER_FILE}"
touch "${JOBS_LEDGER_FILE}"
```

### hermes-report.sh: kind branch insertion point (Python heredoc)

The following shows the before/after state of the per-line loop inside the Python heredoc at `hermes-report.sh:383–424`:

```python
# BEFORE (existing code, lines ~395-424):
try:
    m = json.loads(line)
except json.JSONDecodeError:
    continue
if not all(k in m for k in REQUIRED_KEYS):
    continue
if m['muid'] in prior_muids:
    continue
# ... ts filter, FORBIDDEN check ...
markers.append(m)

# AFTER (Phase 7 addition):
try:
    m = json.loads(line)
except json.JSONDecodeError:
    continue
# Phase 7 (SCHEMA-03): branch on kind before REQUIRED_KEYS check.
kind = m.get("kind")
if kind == "job":
    JOB_REQUIRED = ("agentic_job_id", "job_type", "status")
    if all(k in m for k in JOB_REQUIRED):
        jobs_by_id[m["agentic_job_id"]] = m   # D-12: last wins
    continue  # never reaches task-marker path
elif kind is not None:
    continue  # unknown kind — skip (D-06 forward-compat)
# kind absent → v1.0 task marker path (byte-identical)
if not all(k in m for k in REQUIRED_KEYS):
    continue
# ... existing code unchanged below this line ...
```

Initialization (placed before the `if marker_path.is_file():` block):

```python
# After REQUIRED_KEYS = ('muid', ...) line:
jobs_by_id = {}  # Phase 7: keyed by agentic_job_id, last line wins (D-12)
```

Output emission (at end of heredoc, after existing `print(f"READ_OK=...")` lines):

```python
print(f"JOBS_JSON={json.dumps(list(jobs_by_id.values()), separators=(',', ':'))}")
```

Bash capture (after existing `sed` captures in the `if [[ -n "${marker_output}" ]]; then` block):

```bash
local jobs_json
jobs_json=$(echo "${marker_output}" | sed -n 's/^JOBS_JSON=//p' | head -1)
# Phase 7: jobs_json captured for Phase 9 consumption — not used here.
```

### test_runtime_paths_are_hermes_native extensions

```python
# Source: tests/test_repository.py — test_runtime_paths_are_hermes_native
# Append after existing assertions (last line currently at line 132):
self.assertIn('JOBS_LEDGER_FILE=', text)
self.assertIn('revenium-jobs.ledger', text)
self.assertIn('JOB_TAXONOMY_FILE=', text)
self.assertIn('job-taxonomy.json', text)
```

## State of the Art

| Old Approach | Current Approach | Phase 7 Change | Impact |
|--------------|------------------|----------------|--------|
| Single JSONL per session (task markers only) | Same file, same format | Add `kind:"job"` lines as discriminated records in same file | Zero schema migration; forward/backward compat by design |
| `REQUIRED_KEYS` gate as the sole line discriminator | Still the task-marker gate | `kind` check fires BEFORE `REQUIRED_KEYS` for job lines | v1.0 reader naturally drops job lines (no `muid`); v1.1 reader routes them |
| Single metering ledger (`revenium-hermes.ledger`) | Unchanged | Add `revenium-jobs.ledger` as separate file for Phase 9 idempotency | Different colon-field count avoids field-count discrimination confusion |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `JOBS_LEDGER_FILE` and `JOB_TAXONOMY_FILE` are the correct env-var names per D-13 (planner discretion) | common.sh additions | Low — any name following the pattern passes `test_runtime_paths_are_hermes_native` as long as the underlying file names (`revenium-jobs.ledger`, `job-taxonomy.json`) are used |
| A2 | The `JOBS_JSON=` line is safe to emit even when `jobs_by_id` is empty (`[]`) | Reader output | Low — `json.dumps([], ...)` is `"[]"`, bash captures it, `sed` output is `[]`, bash variable holds `[]` — no downstream effect in Phase 7 |
| A3 | The `continue` after job line processing correctly bypasses `markers.append(m)` | Kind branch | HIGH if wrong — a missed `continue` would pass the job line to `REQUIRED_KEYS` check (it would fail on missing `muid`) so it would not reach `markers.append`, but the intent should be explicit |

**All three are LOW risk and all are verified by the TEST-01/TEST-02 regression tests in Phase 7 itself.**

## Open Questions

1. **`revenium-jobs.ledger` line format pinned here or in Phase 9?**
   - What we know: D-15 defers grammar to Phase 9/10. Context.md marks this as planner discretion.
   - What's unclear: Whether documenting the planned grammar now (`JOB:<id>:created` / outcome line) in a reference doc is in scope for Phase 7.
   - Recommendation: Pin the grammar in a comment in `common.sh` next to `JOBS_LEDGER_FILE` declaration (one line). This costs nothing and prevents Phase 9 from re-researching it. Not a blocker for Phase 7 planning.

2. **Should `JOB_REQUIRED` be a module-level constant or inline in the loop?**
   - What we know: `REQUIRED_KEYS` is a module-level constant in the heredoc.
   - What's unclear: Whether `JOB_REQUIRED` should follow the same pattern.
   - Recommendation: Define `JOB_REQUIRED = ("agentic_job_id", "job_type", "status")` immediately after `REQUIRED_KEYS` (same pattern, same location). Keeps both visible side by side for Phase 9 readers.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `python3` | Heredoc execution, test runner | Verified (used throughout) | system | — |
| `bash` | Script execution | Verified (all scripts) | 3.2+ (macOS) | — |
| `bash -n` | `test_shell_scripts_have_valid_syntax` | Verified | — | — |

Step 2.6: No new external dependencies. This phase is purely code/config changes on files already in the repo.

## Validation Architecture

nyquist_validation is explicitly `false` in `.planning/config.json` — this section is skipped.

## Security Domain

Phase 7 introduces no new network calls, no new credentials, no new user-controlled input surfaces, and no new file permissions. The `JOBS_LEDGER_FILE` path follows the same local-only state pattern as all other files under `~/.hermes/state/revenium/`. No ASVS categories apply.

## Sources

### Primary (HIGH confidence)

- `skills/revenium/scripts/common.sh` — verified current state of all path declarations; exact template for new declarations [VERIFIED: file read]
- `skills/revenium/scripts/hermes-report.sh` — verified exact lines 34, 376–446 (REQUIRED_KEYS, per-line parse loop, heredoc output pattern, touch location) [VERIFIED: file read]
- `tests/test_repository.py` — verified existing test methods: `test_runtime_paths_are_hermes_native` (lines 118–132), `test_marker_file_schema` (lines 231–270), `test_cron_marker_split_end_to_end` (lines 356–747); shim/tempdir pattern confirmed [VERIFIED: file read]
- `skills/revenium/scripts/split_strategies.py` — verified `parse_prior_state` signature and field-count discrimination; `HERMES:` prefix + colon format confirmed [VERIFIED: file read]
- `.planning/phases/07-job-marker-schema-state-scaffolding/07-CONTEXT.md` — locked decisions D-01 through D-15 [VERIFIED: file read]
- `CLAUDE.md` — no new runtime dependencies, `common.sh` single-source-of-truth constraint, `set -uo pipefail` preservation, bash 3.2 compatibility requirement [VERIFIED: file read]

### Secondary (MEDIUM confidence)

- `.planning/STATE.md` — separate-ledger rationale, phase ordering context [VERIFIED: file read]
- `.planning/REQUIREMENTS.md` — SCHEMA-01..05, TEST-01..02 full text [VERIFIED: file read]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Bash/Python/unittest are the entire stack; no new libraries; verified in codebase
- Architecture: HIGH — All three sub-problems have exact verified insertion points; no ambiguity
- Pitfalls: HIGH — Pitfalls 1-4 are verifiable from the existing codebase structure; Pitfall 5 is a known lesson from v1.0 history (STATE.md)
- Test structure: HIGH — Exact shim/tempdir pattern is lifted from existing passing tests

**Research date:** 2026-05-15
**Valid until:** 2026-06-15 (stable codebase — only changes if Phases 8-10 land before Phase 7 is planned, which STATE.md says is blocked on Phase 7 completing first)
