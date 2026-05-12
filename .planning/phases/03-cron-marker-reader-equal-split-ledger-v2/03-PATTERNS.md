# Phase 3: Cron Marker Reader + Equal-Split + Ledger v2 - Pattern Map

**Mapped:** 2026-05-12
**Files analyzed:** 6 (5 modified + 2 new; tests/test_repository.py counted once)
**Analogs found:** 6 / 6 (one as self-extension)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `skills/revenium/scripts/split_strategies.py` (NEW) | utility module (pure function) | transform (in-memory) | `tests/test_repository.py` (only Python file in repo; stdlib-only style) | role-partial (no existing pure-Python module in `scripts/`) |
| `skills/revenium/scripts/common.sh` (MOD) | config / path source-of-truth | request-response (env) | itself, lines 10-18 (existing `LEDGER_FILE`/`MARKERS_DIR` declarations) | exact (self-extension) |
| `skills/revenium/scripts/cron.sh` (MOD) | orchestrator | event-driven (per-minute) | itself, lines 1-19 (existing orchestrator shape) | exact (self-extension) |
| `skills/revenium/scripts/hermes-report.sh` (MOD) | metering reporter | batch / request-response | itself, lines 41-268 (the per-session loop being extended) | exact (self-extension) |
| `skills/revenium/references/setup.md` (MOD) | reference doc | doc | itself, lines 1-72 (existing section structure) | exact (self-extension) |
| `tests/test_repository.py` (MOD) | test | request-response (stdlib unittest) | itself, lines 64-200 (`test_taxonomy_*`, `test_marker_file_schema`) | exact (self-extension) |

**Rationale for "self-extension":** Per RESEARCH.md "State of the Art" section, Phase 3 explicitly *extends* the existing per-session loop in `hermes-report.sh:41-268`; it does NOT replace it. All four modified bash files have their own conventions as the closest analog. The only file with no in-repo analog is `split_strategies.py` (no Python module in `scripts/`); its conventions are dictated by `RESEARCH.md` Pattern 5 and the project's stdlib-only Python heredoc style.

---

## Pattern Assignments

### `skills/revenium/scripts/split_strategies.py` (NEW — utility, transform)

**Analog:** `tests/test_repository.py` (only Python file; nearest stdlib style guide) + RESEARCH.md `## Code Examples` section
**Note:** No existing standalone Python module in `scripts/`. This file establishes a new pattern for the codebase. Treat the RESEARCH.md Pattern 5 excerpt (lines 524-583) as the prototype; honor the project's stdlib-only constraint.

**Imports pattern** (from `tests/test_repository.py:1-7`):
```python
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
```
Alphabetized stdlib imports; module constants in `SCREAMING_SNAKE_CASE` immediately below. For `split_strategies.py`, the only required import is `from decimal import Decimal` per RESEARCH.md.

**Module docstring + public API pattern** (locked by D-06 — record S3/S4 plug-in shape):
```python
"""Pluggable split strategies for Hermes-Revenium marker-aware metering.

Each strategy takes a delta dict {input, output, cache_read, cache_write, total, cost}
and an N (number of markers), and returns a list of N dicts whose per-field
values sum exactly to the input.

Future strategies (deferred to v2 per PROJECT.md decision 5):
    def weighted_split(delta_fields, markers_with_length_hints) -> list[dict]
    def guardrail_estimator_split(delta_fields, markers, guardrail_share_estimator) -> list[dict]
"""
from decimal import Decimal

INT_FIELDS = ("input", "output", "cache_read", "cache_write", "total")
COST_FIELD = "cost"
```

**Core split function pattern** (conservation invariant byte-exact; from RESEARCH.md Pattern 5):
```python
def equal_split(delta: dict, n: int) -> list[dict]:
    if n < 1:
        raise ValueError(f"n must be >= 1; got {n}")
    splits = [{} for _ in range(n)]
    for k in INT_FIELDS:
        v = int(delta.get(k, 0))
        per = v // n
        for i in range(n):
            splits[i][k] = per
        splits[-1][k] += v - per * n  # remainder absorbed by last marker
        assert sum(s[k] for s in splits) == v, f"conservation violated for {k}"
    cost = Decimal(str(delta.get(COST_FIELD, "0")))
    quant = Decimal("0.000001")
    per_cost = (cost / Decimal(n)).quantize(quant)
    for i in range(n):
        splits[i][COST_FIELD] = format(per_cost, "f")
    remainder_cost = cost - per_cost * n
    last_cost = (Decimal(splits[-1][COST_FIELD]) + remainder_cost).quantize(quant)
    splits[-1][COST_FIELD] = format(last_cost, "f")
    assert sum(Decimal(s[COST_FIELD]) for s in splits) == cost
    return splits
```

**Style conventions** (from CLAUDE.md + `tests/test_repository.py`):
- 4-space indentation
- stdlib-only (`decimal`, no `pip install` deps)
- `snake_case` function names
- `SCREAMING_SNAKE_CASE` module constants
- LF line endings; trailing newline

---

### `skills/revenium/scripts/common.sh` (MOD — config, request-response)

**Analog:** itself, lines 10-18 (existing path declarations)

**Path declaration pattern** (`common.sh:10-18`):
```bash
STATE_DIR="${REVENIUM_STATE_DIR}"
CONFIG_FILE="${STATE_DIR}/config.json"
BUDGET_STATUS_FILE="${STATE_DIR}/budget-status.json"
LEDGER_FILE="${STATE_DIR}/revenium-hermes.ledger"
LOG_FILE="${STATE_DIR}/revenium-metering.log"
ENV_FILE="${STATE_DIR}/env"
STATE_DB="${HERMES_HOME}/state.db"
TAXONOMY_FILE="${REVENIUM_TAXONOMY_FILE:-${STATE_DIR}/task-taxonomy.json}"
MARKERS_DIR="${REVENIUM_MARKERS_DIR:-${STATE_DIR}/markers}"
```

**New line to add (D-13):**
```bash
LOCK_FILE="${STATE_DIR}/cron.lock"
```
Follow the no-override form (no `REVENIUM_LOCK_FILE` env shadow — this is internal-only, not user-tunable). Insert between `STATE_DB` and `TAXONOMY_FILE` or after `MARKERS_DIR` — planner discretion.

**Path-discipline guardrail** (test that enforces this):
`tests/test_repository.py:54-62` greps `common.sh` for `.hermes` and `state/revenium` literals AND for specific variable name presence (`TAXONOMY_FILE=`, `MARKERS_DIR=...` regex). Phase 3 MUST extend this test with an assertion like `self.assertIn('LOCK_FILE=', text)` (D-13).

---

### `skills/revenium/scripts/cron.sh` (MOD — orchestrator, event-driven)

**Analog:** itself, lines 1-19 (entire existing file)

**Orchestrator shape to extend** (`cron.sh:1-19`):
```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

if [[ -f "${ENV_FILE}" ]]; then
  set -o allexport
  # shellcheck source=/dev/null
  source "${ENV_FILE}"
  set +o allexport
fi

bash "${SKILL_DIR}/scripts/hermes-report.sh" "$@" || true
bash "${SKILL_DIR}/scripts/budget-check.sh" "$@" || true
```

**Flock acquisition pattern to insert** (from RESEARCH.md Pattern 2b, lines 352-388; D-12 phrase locked):
```bash
# Acquire cron.lock non-blocking. Held for the rest of this script's lifetime.
exec 9>"${LOCK_FILE}"
if ! python3 - <<'PY' 9<&0
import fcntl, os, sys
try:
    fcntl.flock(0, fcntl.LOCK_EX | fcntl.LOCK_NB)
except (OSError, BlockingIOError):
    sys.exit(11)
PY
then
  warn "prior tick still active, skipping this minute"
  exit 0
fi
```
**Insert location (per open-question 1 in RESEARCH.md):** AFTER `ensure_path`, BEFORE the optional `ENV_FILE` source — so the lock-warn path can find `python3` on PATH, but a malformed env file is locked-serialized.

**Critical flag discipline (CLAUDE.md):** `cron.sh` uses `set -euo pipefail` (with `-e`). The flock block above intentionally uses `if ! ...` to NEUTRALIZE `-e` for the contention case so that `exit 0` is reached. Do NOT add `|| true` after the python3 invocation — the `if !` form is already correct.

---

### `skills/revenium/scripts/hermes-report.sh` (MOD — reporter, batch/request-response)

**Analog:** itself, lines 41-268 (the per-session loop being extended)

**Imports / preflight pattern** (`hermes-report.sh:1-39`):
```bash
#!/usr/bin/env bash
# Hermes-native Revenium reporter. Reads token usage from ~/.hermes/state.db
# and ships deltas to Revenium via `revenium meter completion`.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

if ! command -v revenium >/dev/null 2>&1; then
  warn "revenium CLI not found on PATH — skipping metering."
  exit 0
fi
```
Preserve `set -uo pipefail` (NOT `-euo`) — soft-fail discipline for the per-session loop.

**Existing single-call argv pattern** (`hermes-report.sh:216-249` — canonical extend point):
```bash
local cmd=(
  revenium meter completion
  --model "${clean_model}"
  --provider "${provider}"
  --input-tokens "${delta_input}"
  --output-tokens "${delta_output}"
  --cache-read-tokens "${delta_cache_read}"
  --cache-creation-tokens "${delta_cache_write}"
  --total-tokens "${delta_total}"
  --stop-reason "END"
  --request-time "${request_time}"
  --completion-start-time "${request_time}"
  --response-time "${response_time}"
  --request-duration "${duration_ms}"
  --agent "Hermes"
  --transaction-id "${sid}-${total_tokens}"
  --trace-id "${sid}"
  --is-streamed
  --quiet
)
if [[ -n "${billing_provider}" ]]; then
  cmd+=(--model-source "${billing_provider}")
fi
if [[ "${delta_cost}" != "0" && "${delta_cost}" != "0.0" ]]; then
  cmd+=(--total-cost "${delta_cost}")
fi
```

**Extension for per-marker emission** (CRON-03, CRON-04 — wraps existing argv in a loop):
```bash
for row in "${marker_rows[@]}"; do
  IFS='|' read -r muid t_type op_type d_in d_out d_cr d_cw d_tot d_cost <<< "${row}"
  cmd=(
    revenium meter completion
    # ... all existing flags (copy from lines 216-249) ...
    --transaction-id "${sid}-${total_tokens}-${muid}"  # CRON-04: extended id
    --task-type "${t_type}"                            # CRON-03: per-marker
    --operation-type "${op_type}"                      # CRON-03: per-marker
    --is-streamed --quiet
  )
  # conditional flags unchanged from lines 237-248
  ...
done
```
Note: do NOT emit `--operation-type CHAT` as a default for the zero-marker fallthrough (Phase 4 owns that decision per CONTEXT.md research_gates). Zero-marker emits ONLY `--task-type unclassified`.

**Existing ledger idempotency pattern** (`hermes-report.sh:70-71`):
```bash
local ledger_key="HERMES:${sid}:${total_tokens}"
if grep -q "^HERMES:${sid}:${total_tokens}:" "${LEDGER_FILE}" 2>/dev/null; then
  ((skipped_count++)) || true
  continue
fi
```

**Existing v1 ledger write** (`hermes-report.sh:253-257`):
```bash
if [[ "${cmd_exit}" -eq 0 ]]; then
  local now_ts
  now_ts=$(python3 -c "import time; print(f'{time.time():.3f}')" 2>/dev/null || date +%s)
  echo "${ledger_key}:${now_ts}" >> "${LEDGER_FILE}"
  ((reported_count++)) || true
  info "Reported: session=${sid} model=${clean_model} provider=${provider} in=${delta_input} out=${delta_output} cost=${delta_cost}"
```

**v2 ledger write extension** (D-07, D-11 — append `:muids_csv`):
```bash
# After cmd success, per-call:
shipped_muids+=("${muid}")
local muids_csv
muids_csv=$(IFS=','; echo "${shipped_muids[*]}")
echo "HERMES:${sid}:${total_tokens}:${now_ts}:${muids_csv}" >> "${LEDGER_FILE}"
```
For zero-marker fallthrough (D-11), use a synthetic placeholder like `unclassified-${now_ts}` to keep `muids_csv` non-empty so `len(line.split(':'))` discrimination stays reliable.

**Python heredoc → caller pattern** (`hermes-report.sh:90-97` — single-value capture):
```bash
ratio=$(python3 -c "
prev = ${prev_reported_tokens}
curr = ${total_tokens}
if prev > 0 and curr > prev:
    print(f'{(curr - prev) / curr:.6f}')
else:
    print('1.0')
" 2>/dev/null || echo "1.0")
```
**Anti-pattern flagged in CONCERNS.md:** This style interpolates bash vars directly into Python source (shell-injection class). Phase 3's new heredocs MUST use `os.environ` instead:
```bash
DELTA_JSON="${delta_json}" N="${n_markers}" SCRIPT_DIR="${SCRIPT_DIR}" python3 - <<'PY'
import json, os, sys
sys.path.insert(0, os.environ['SCRIPT_DIR'])
from split_strategies import equal_split
delta = json.loads(os.environ['DELTA_JSON'])
splits = equal_split(delta, int(os.environ['N']))
print(json.dumps(splits))
PY
```

**Multi-value heredoc return pattern** (`budget-check.sh:88-102`, canonical):
```bash
HALT_OUTPUT=$(BUDGET_STATUS_FILE="${BUDGET_STATUS_FILE}" python3 - <<'PY'
...
print(f"HALT_TRANSITION={'true' if halt_transition else 'false'}")
print(f"CURRENT={current:.2f}")
print(f"SUMMARY=...")
PY
)
# Parse:
echo "${HALT_OUTPUT}" | sed -n 's/^SUMMARY=//p'
```
Use this for the marker-reader heredoc when it needs to emit S2_INFO + S2_WARN telemetry alongside the markers JSON.

**Per-session loop fail-open pattern** (`hermes-report.sh:60-68, 72, 82, 110-112`):
```bash
local total_tokens=$((input_tokens + output_tokens))
if [[ "${total_tokens}" -eq 0 ]]; then
  continue
fi
# ...
((skipped_count++)) || true
continue
```
Use `((counter++)) || true` so increments don't trip `-uo pipefail` when counters are 0. New marker-read and split blocks must wrap their core in try/except (Python side) + bash-level `continue` so one bad session doesn't abort.

**S2 bias telemetry routing pattern** (D-18 phrase locked):
```bash
# After heredoc returns S2_INFO=... and optional S2_WARN=... lines:
S2_INFO=$(echo "${HEREDOC_OUTPUT}" | sed -n 's/^S2_INFO=//p')
S2_WARN=$(echo "${HEREDOC_OUTPUT}" | sed -n 's/^S2_WARN=//p')
[[ -n "${S2_INFO:-}" ]] && info "S2: ${S2_INFO}"
[[ -n "${S2_WARN:-}" ]] && warn "S2: ${S2_WARN}"
```

---

### `skills/revenium/references/setup.md` (MOD — doc)

**Analog:** itself, lines 1-72 (existing section structure)

**Section heading pattern** (`setup.md:1-3, 56-72`):
```markdown
# Revenium Skill Setup

## Initial setup

### 1. Verify prerequisites
...

## Reset flow

1. Read the current config.
...

## Reconfigure flow

1. ...
```
Use ATX `#`/`##`/`###` headings, numbered steps where procedural, code fences for commands.

**New section to add (D-16 — phrase LOCKED, do not paraphrase):**
```markdown
## How attribution works

GUARDRAIL share is overstated when work turns are much larger than classification turns. Read GUARDRAIL share as an upper bound, not an estimate. The S2 equal-split is intentionally simple and biases attribution toward classification overhead in mixed windows. Later strategies (S3 weighted, S4 guardrail-estimator) are deferred to v2.
```
Section placement is at planner discretion (D-16: top, middle, end). The phrase ITSELF is locked verbatim.

**Legacy-branding test** (`tests/test_repository.py:40-52`): runs over `.md` files. The locked D-16 phrase contains no forbidden regex (`OpenClaw|openclaw|ClawHub|clawhub`) per RESEARCH.md open-question 4. Safe to add.

---

### `tests/test_repository.py` (MOD — test, request-response)

**Analog:** itself, lines 64-200 (existing rich tests: `test_taxonomy_file_schema`, `test_taxonomy_atomic_write_pattern`, `test_marker_file_schema`)

**Existing test method naming pattern** (`tests/test_repository.py:11, 33, 40, 54, 64, 88, 161, 202, 217`):
```python
def test_expected_files_exist(self): ...
def test_skill_frontmatter_has_hermes_metadata(self): ...
def test_no_legacy_branding_left(self): ...
def test_runtime_paths_are_hermes_native(self): ...
def test_taxonomy_file_schema(self): ...
def test_taxonomy_atomic_write_pattern(self): ...
def test_marker_file_schema(self): ...
def test_prompt_ordering_invariant(self): ...
def test_shell_scripts_have_valid_syntax(self): ...
```
Pattern: `test_<area>_<behavior>` snake_case. For Phase 3:
- `test_split_strategies_conservation` (TEST-03, COMPAT-02)
- `test_s2_bias_50_50_attribution` (TEST-04 — D-17 says name SHOULD include "bias")
- `test_ledger_v1_v2_discrimination` (D-10)
- `test_expected_files_exist` extended to include `split_strategies.py` (D-05)
- `test_runtime_paths_are_hermes_native` extended to assert `LOCK_FILE=` (D-13)
- `test_shell_scripts_have_valid_syntax` skip-list extension for `.py` files (already only globs `*.sh` — D-05 satisfied incidentally; verify)

**Inline-fixture pattern** (`tests/test_repository.py:88-159` — atomic write test):
```python
import json, os, shutil, subprocess, sys, tempfile
tmpdir = tempfile.mkdtemp(prefix="gsd-atomic-")
try:
    target = os.path.join(tmpdir, "task-taxonomy.json")
    pre_state = {"labels": {"seed": {"description": "seed", "examples": ["a", "b"]}}}
    with tempfile.NamedTemporaryFile("w", dir=tmpdir, delete=False, suffix=".tmp") as tmp:
        json.dump(pre_state, tmp, indent=2, ensure_ascii=True)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmpname = tmp.name
    os.rename(tmpname, target)
    # ... assertions ...
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)
```
Build fixtures inline using `tempfile.TemporaryDirectory()` or `tempfile.mkdtemp() + try/finally shutil.rmtree`. Stdlib-only.

**Conservation test fixture pattern** (RESEARCH.md Example 3, lines 781-810 — already in research):
```python
def test_split_strategies_conservation(self):
    """COMPAT-02: sum of split numeric fields equals input delta byte-exact."""
    from decimal import Decimal
    import sys
    sys.path.insert(0, str(SKILL / 'scripts'))
    from split_strategies import equal_split

    cases = [
        ({"input": 8000, "output": 3000, "cache_read": 100, "cache_write": 50,
          "total": 11000, "cost": "0.123456"}, 1),
        ({"input": 8001, "output": 3001, "cache_read": 101, "cache_write": 51,
          "total": 11003, "cost": "0.987654"}, 10),  # non-divisible by N
    ]
    for delta, n in cases:
        splits = equal_split(delta, n)
        self.assertEqual(len(splits), n, f"expected {n} splits for n={n}")
        for k in ("input", "output", "cache_read", "cache_write", "total"):
            self.assertEqual(sum(s[k] for s in splits), delta[k])
        self.assertEqual(
            sum(Decimal(s["cost"]) for s in splits),
            Decimal(delta["cost"]),
        )
```

**Bias-pinning test pattern** (RESEARCH.md Example 4, lines 815-833):
```python
def test_s2_bias_50_50_attribution(self):
    """D-17: pin the documented S2 50/50 bias for small-GUARDRAIL + large-work windows."""
    import sys
    sys.path.insert(0, str(SKILL / 'scripts'))
    from split_strategies import equal_split
    delta = {"input": 8000, "output": 0, "cache_read": 0, "cache_write": 0,
             "total": 8000, "cost": "0.080000"}
    splits = equal_split(delta, 2)
    self.assertEqual(splits[0]["input"], 4000)
    self.assertEqual(splits[1]["input"], 4000)
```

**Path-test extension pattern** (`tests/test_repository.py:54-62` to extend per D-13):
```python
def test_runtime_paths_are_hermes_native(self):
    text = (SKILL / 'scripts' / 'common.sh').read_text()
    self.assertIn('.hermes', text)
    self.assertIn('state/revenium', text)
    # ... existing assertions ...
    self.assertIn('LOCK_FILE=', text)  # D-13 new assertion
    self.assertIn('cron.lock', text)   # D-13 path literal
```

**Expected-files extension pattern** (`tests/test_repository.py:11-31` to extend per D-05):
```python
expected = [
    # ... existing entries ...
    SKILL / 'scripts' / 'split_strategies.py',  # D-05
]
```

**Shell syntax skip-list** (`tests/test_repository.py:217-230`): already globs `*.sh` only (line 218: `(SKILL / 'scripts').glob('*.sh')`), so `.py` files are naturally excluded. No skip-list edit needed — D-05's `bash -n` exclusion is satisfied incidentally. Document this in the planner's task note.

---

## Shared Patterns

### Shell strictness flags
**Source:** CLAUDE.md "Code Style" section + each script's line 2-5
**Apply to:** All bash files (new + modified)

| Script | Flags | Why |
|--------|-------|-----|
| `common.sh` | `set -uo pipefail` | Sourced; soft-fail tolerated |
| `hermes-report.sh` | `set -uo pipefail` | Per-session continue-on-failure |
| `cron.sh` | `set -euo pipefail` | Orchestrator; fail-fast on setup errors |
| `budget-check.sh` | `set -euo pipefail` | Atomic state writes; fail rather than corrupt |
| `clear-halt.sh` | `set -euo pipefail` | One-shot user CLI |
| `install/uninstall-cron.sh` | `set -euo pipefail` | One-shot user CLI |

Do NOT switch a script's flag mode. `cron.sh` flock block must use `if ! python3 -...; then warn + exit 0; fi` to escape `-e` for the contention path.

### Script preamble
**Source:** every script's first ~10 lines (`hermes-report.sh:1-11`, `cron.sh:1-8`, etc.)
**Apply to:** All bash files in `scripts/`

```bash
#!/usr/bin/env bash
# <one-line description of the script's role>

set -euo pipefail    # or -uo per role table

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path
```

### Path-discipline rule
**Source:** `common.sh:6-18` + `tests/test_repository.py::test_runtime_paths_are_hermes_native`
**Apply to:** Any new state path or file location

Every `~/.hermes/...` or `state/revenium/...` path must be a variable declared in `common.sh`. Phase 3 example: `LOCK_FILE="${STATE_DIR}/cron.lock"`. Never inline. The test will fail if you do.

### Python heredoc → bash communication
**Source:** `budget-check.sh:43-93` (multi-value via `KEY=value` lines) and `hermes-report.sh:90-97` (single-value via `print(...)`)
**Apply to:** All new heredocs

```bash
# Single value:
RESULT=$(VAR1="${var1}" VAR2="${var2}" python3 - <<'PY'
import os
print(os.environ['VAR1'] + os.environ['VAR2'])
PY
)

# Multi-value (parse with sed):
OUTPUT=$(VAR1="${var1}" python3 - <<'PY'
print(f"KEY_A={value_a}")
print(f"KEY_B={value_b}")
PY
)
KEY_A=$(echo "${OUTPUT}" | sed -n 's/^KEY_A=//p')
```

**Critical safety rule (CONCERNS.md flagged for `hermes-report.sh:90`):** Always pass bash vars via `os.environ`, never via `'${var}'` interpolation into the Python source. New Phase 3 heredocs MUST use the `os.environ` form. Existing legacy interpolations stay (out of scope for Phase 3 to refactor).

### Stdlib-only Python
**Source:** CLAUDE.md "Python Heredocs Inside Bash" section
**Apply to:** All Python (heredoc + `split_strategies.py` + tests)

Allowed: `json`, `os`, `re`, `time`, `datetime`, `pathlib`, `fcntl`, `sqlite3`, `tempfile`, `secrets`, `decimal`, `unittest`, `subprocess`, `sys`. No `pip install`-able imports.

### Bash array CLI argv
**Source:** `hermes-report.sh:216-249`
**Apply to:** New per-marker `revenium meter completion` calls

```bash
local cmd=(
  revenium meter completion
  --flag-a "${value_a}"
  --flag-b "${value_b}"
)
[[ -n "${optional}" ]] && cmd+=(--opt "${optional}")
local cmd_output cmd_exit
cmd_output=$("${cmd[@]}" 2>&1) && cmd_exit=0 || cmd_exit=$?
```

NEVER use `eval`; NEVER build the command as a single string. Each value is a separate argv element via array semantics — prevents shell injection from marker fields.

### Logging
**Source:** `common.sh:32-40`
**Apply to:** All scripts

Use `info` / `warn` / `error` helpers (timestamped, tee to LOG_FILE and stderr). Never inline `echo "[$(date)] ..."`. User-facing one-shot scripts (`clear-halt.sh`, `install-cron.sh`) use bare `echo` for terminal output — distinct from the cron-logged scripts.

D-18 locked log phrases:
- `info "S2: window=<n>, mean_per_marker=<delta/n>"` (per session per tick)
- `warn "S2: classification-dominated window, attribution may be lossy"` (when n==2 + GUARDRAIL)
- `warn "prior tick still active, skipping this minute"` (D-12, flock contention)

### Idempotency invariant
**Source:** `hermes-report.sh:70-71, 256` + `CLAUDE.md "Metering ledger semantics"`
**Apply to:** Every code path that writes the ledger

The ledger is append-only, prefix-keyed (`HERMES:`), and re-running cron MUST NEVER double-report. Phase 3 preserves this via:
1. Per-call ledger writes (CRON-06) — write after each successful `revenium meter completion`, not at end-of-batch
2. `--transaction-id ${sid}-${total_tokens}-${muid}` (CRON-04) — server-side dedupe belt-and-suspenders
3. Reader-side muid filter against prior row's tail (CRON-01)

D-11 invariant: v2 row's `muids_csv` field is NEVER empty. Use a synthetic `unclassified-${ts_short}` placeholder in zero-marker fallthrough.

---

## No Analog Found

| File | Role | Data Flow | Reason | Mitigation |
|------|------|-----------|--------|------------|
| `skills/revenium/scripts/split_strategies.py` | utility module | transform | No standalone Python module exists in `scripts/`. All other Python lives in bash heredocs. | Use RESEARCH.md Pattern 5 (lines 524-583) as the prototype. Honor `tests/test_repository.py` stdlib-only conventions. |

Suggested helper `_flock.py` mentioned in RESEARCH.md is NOT in the Phase 3 file inventory — the inline heredoc form in `cron.sh` (Pattern 2b) is the preferred approach per the orchestrator brief's flock pattern. If the planner elects to extract it to `_flock.py`, add it to `tests/test_repository.py::test_expected_files_exist`.

---

## Metadata

**Analog search scope:**
- `skills/revenium/scripts/` (all 7 .sh files)
- `skills/revenium/references/` (4 .md files)
- `tests/` (1 .py file)
- RESEARCH.md as supplementary pattern source for `split_strategies.py` (no in-repo Python module analog)

**Files scanned:** 13
**Pattern extraction date:** 2026-05-12
