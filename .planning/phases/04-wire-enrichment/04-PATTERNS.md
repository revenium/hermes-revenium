# Phase 4: Wire Enrichment - Pattern Map

**Mapped:** 2026-05-14
**Files analyzed:** 3 (1 production modified, 1 test modified, 1 doc modified)
**Analogs found:** 3 / 3

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `skills/revenium/scripts/hermes-report.sh` | service / cron-script | batch, event-driven | self (existing file; Phase 4 modifies two blocks within it) | exact |
| `tests/test_repository.py` | test | request-response (subprocess) | `tests/test_repository.py::test_cron_marker_split_end_to_end` (lines 355-636) | exact |
| `skills/revenium/references/setup.md` | doc | — | existing `setup.md` prose sections | exact |

---

## Pattern Assignments

### `skills/revenium/scripts/hermes-report.sh` (service, batch)

Two blocks require modification. No new file is created.

---

#### Block A: Marker-driven split path — WIRE-02 / WIRE-03

**Analog:** Same file, same block. Phase 4 extends what is already there.

**Current split_rows Python print (lines 528-530):**
```python
print(f"{marker['muid']}|{marker['task_type']}|{marker['operation_type']}|"
      f"{split['input']}|{split['output']}|{split['cache_read']}|"
      f"{split['cache_write']}|{split['total']}|{split['cost']}")
```

**Phase 4 target — add fields 10-11 (`m_agent`, `m_trace`) to the print:**
```python
m_agent = marker.get('agent', '')      # empty string → bash fallback
m_trace = marker.get('trace_id', '')   # empty string → bash fallback
# NOTE: agent and trace_id values must not contain '|' (pipe-safety constraint).
print(f"{marker['muid']}|{marker['task_type']}|{marker['operation_type']}|"
      f"{split['input']}|{split['output']}|{split['cache_read']}|"
      f"{split['cache_write']}|{split['total']}|{split['cost']}|"
      f"{m_agent}|{m_trace}")
```

**Current while-read variable list (line 546-547):**
```bash
local row muid t_type op_type d_in d_out d_cr d_cw d_tot d_cost
while IFS='|' read -r muid t_type op_type d_in d_out d_cr d_cw d_tot d_cost; do
```

**Phase 4 target — add two variables to consume fields 10-11:**
```bash
local row muid t_type op_type d_in d_out d_cr d_cw d_tot d_cost m_agent m_trace
while IFS='|' read -r muid t_type op_type d_in d_out d_cr d_cw d_tot d_cost m_agent m_trace; do
```

**Current hardcoded --agent / --trace-id in cmd array (lines 564-566):**
```bash
  --agent "Hermes"
  --transaction-id "${sid}-${total_tokens}-${muid}"
  --trace-id "${sid}"
```

**Phase 4 target — replace with `:-` fallback expansion (D-25: per-marker, no session-level collapse):**
```bash
  --agent "${m_agent:-Hermes}"
  --transaction-id "${sid}-${total_tokens}-${muid}"
  --trace-id "${m_trace:-${sid}}"
```

**CRITICAL: Both edits (Python print AND while-read variable list) must land in the same commit.** If only one is updated, `d_cost` silently absorbs `|m_agent|m_trace` as a string, breaking the `--total-cost` conditional. See RESEARCH.md Pitfall 1.

---

#### Block B: Zero-marker fallthrough — WIRE-01 (D-22, gate PASSED)

**Analog:** Same file, lines 616-636. Phase 4 adds exactly one line to the cmd array.

**Current fallthrough cmd array tail (lines 630-636):**
```bash
    --agent "Hermes"
    --transaction-id "${sid}-${total_tokens}"
    --trace-id "${sid}"
    --is-streamed
    --quiet
    --task-type "unclassified"
  )
```

**Phase 4 target — append `--operation-type "CHAT"` after `--task-type "unclassified"`:**
```bash
    --agent "Hermes"
    --transaction-id "${sid}-${total_tokens}"
    --trace-id "${sid}"
    --is-streamed
    --quiet
    --task-type "unclassified"
    --operation-type "CHAT"
  )
```

The comment block above (lines 610-612) that reads `"Do NOT emit --operation-type: Phase 4 owns the WIRE-01 default decision"` must be replaced with a note that D-22 shipped and the gate passed.

**`--agent` and `--trace-id` in the fallthrough are NOT changed** — they remain hardcoded `"Hermes"` and `"${sid}"`. Only the marker-driven split path gets the `:-` variable fallback.

---

### `tests/test_repository.py` (test, subprocess-driven e2e)

Two new methods added to `RepositoryTests`; one existing assertion updated.

---

#### Analog: `test_cron_marker_split_end_to_end` (lines 355-636)

The entire scaffold for both new test methods — `test_wire_agent_trace_passthrough` (WIRE-02/03) and `test_wire_no_provider_regression_per_class` (WIRE-04) — is a direct copy of this method's infrastructure.

**Reusable helpers already in the file (extract and reuse):**

`build_state_db` pattern (lines 373-395):
```python
def build_state_db(path, sessions):
    conn = sqlite3.connect(str(path))
    conn.execute(
        'CREATE TABLE sessions ('
        'id TEXT, model TEXT, source TEXT, '
        'input_tokens INTEGER, output_tokens INTEGER, '
        'cache_read_tokens INTEGER, cache_write_tokens INTEGER, '
        'reasoning_tokens INTEGER, estimated_cost_usd TEXT, '
        'api_call_count INTEGER, started_at REAL, ended_at REAL, '
        'billing_provider TEXT)'
    )
    for s in sessions:
        conn.execute(
            'INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (s['id'], s['model'], s['source'],
             s['input_tokens'], s['output_tokens'],
             s['cache_read'], s['cache_write'],
             s['reasoning'], s['estimated_cost'],
             s['api_calls'], s['started_at'], s['ended_at'],
             s['billing_provider']),
        )
    conn.commit()
    conn.close()
```

`run_cron` pattern (lines 409-428):
```python
def run_cron(env, invocations_log):
    if os.path.exists(invocations_log):
        os.unlink(invocations_log)
    open(invocations_log, 'w').close()
    result = subprocess.run(
        ['bash', str(HERMES_REPORT)],
        env=env, capture_output=True, text=True, timeout=60,
    )
    invocations = []
    with open(invocations_log) as f:
        for line in f:
            line = line.rstrip('\n')
            if not line:
                continue
            import shlex
            invocations.append(shlex.split(line))
    return result.returncode, invocations, result.stdout + result.stderr
```

`argv_to_flags` helper (lines 430-445):
```python
def argv_to_flags(argv):
    """Convert flat argv to {flag: value} dict for assertions."""
    d = {}
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok.startswith('--'):
            if i + 1 < len(argv) and not argv[i + 1].startswith('--'):
                d[tok] = argv[i + 1]
                i += 2
            else:
                d[tok] = True
                i += 1
        else:
            i += 1
    return d
```

`revenium` shim pattern (lines 461-481):
```python
shim_home = os.path.join(tmpdir, 'home')
bin_dir = os.path.join(shim_home, '.local', 'bin')
os.makedirs(bin_dir)
invocations_log = os.path.join(tmpdir, 'invocations.log')
shim = os.path.join(bin_dir, 'revenium')
with open(shim, 'w') as f:
    f.write(
        '#!/usr/bin/env bash\n'
        'case "$1" in\n'
        '  config) exit 0 ;;\n'
        '  meter)\n'
        '    shift; shift\n'
        '    printf "%q " "$@" >> "$INVOCATIONS_LOG"\n'
        '    printf "\\n" >> "$INVOCATIONS_LOG"\n'
        '    exit 0\n'
        '    ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n'
    )
os.chmod(shim, 0o755)
```

`base_env` pattern (lines 483-491):
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

**Old `started_at` value required to bypass G-03 sentinel filter (from line 522):**
```python
'started_at': 1715514000.0,   # fixed 2024 timestamp — age ~63M s, bypasses G-03
```

---

#### New method: `test_wire_agent_trace_passthrough` (WIRE-02 / WIRE-03)

Seeds a single session with a marker pair that includes `agent` and `trace_id` optional fields. Asserts that `--agent` and `--trace-id` in the captured argv carry the marker values (not the hardcoded fallbacks). A second run with a marker that omits both fields asserts the fallbacks `"Hermes"` and `${sid}` appear.

Marker fixture with optional fields:
```python
markers = [
    {'muid': '01893b8a300abcdef0123456789abc01',
     'ts': 1715515001.0, 'sid': sid,
     'task_type': 'code_review', 'operation_type': 'GUARDRAIL',
     'agent': 'revenium-skill', 'trace_id': 'trace-abc-001'},
    {'muid': '01893b8a300abcdef0123456789abc02',
     'ts': 1715515002.0, 'sid': sid,
     'task_type': 'code_review', 'operation_type': 'CHAT',
     'agent': 'revenium-skill', 'trace_id': 'trace-abc-001'},
]
```

Assertions:
```python
for argv in invocations:
    flags = argv_to_flags(argv)
    self.assertEqual(flags.get('--agent'), 'revenium-skill',
                     'WIRE-02: --agent must carry marker agent field when present')
    self.assertEqual(flags.get('--trace-id'), 'trace-abc-001',
                     'WIRE-03: --trace-id must carry marker trace_id field when present')
```

Fallback sub-case (markers without optional fields):
```python
self.assertEqual(flags.get('--agent'), 'Hermes',
                 'WIRE-02 fallback: --agent must be Hermes when marker omits agent')
self.assertEqual(flags.get('--trace-id'), sid,
                 'WIRE-03 fallback: --trace-id must be sid when marker omits trace_id')
```

---

#### New method: `test_wire_no_provider_regression_per_class` (WIRE-04 / D-24)

Loops over an 8-tuple fixture table (one entry per provider class). Each iteration: fresh `tmpdir`, seeds state.db row + GUARDRAIL+CHAT marker pair, runs cron, asserts every invocation carries the expected `--provider`, `--model`, and `--model-source` values.

8-case fixture table (from RESEARCH.md provider enumeration, lines 157-166):
```python
PROVIDER_CASES = [
    # (label, billing_provider, model, expected_provider, expected_clean_model, expected_model_source)
    ('anthropic',        'anthropic', 'claude-sonnet-4-6',
     'anthropic', 'claude-sonnet-4-6', 'anthropic'),
    ('openai',           'openai',    'gpt-4o',
     'openai',    'gpt-4o',           'openai'),
    ('google',           'google',    'gemini-1.5-pro',
     'google',    'gemini-1.5-pro',   'google'),
    ('xai',              'xai',       'grok-2',
     'xai',       'grok-2',           'xai'),
    ('deepseek',         'deepseek',  'deepseek-chat',
     'deepseek',  'deepseek-chat',    'deepseek'),
    ('meta',             '',          'llama-3.1-70b',
     'meta',      'llama-3.1-70b',    None),  # no --model-source when billing_provider is empty
    ('openrouter-special','openrouter','anthropic/claude-sonnet-4-5',
     'anthropic', 'claude-sonnet-4-5','openrouter'),
    ('bedrock-special',  'bedrock',   'anthropic.claude-3-5-sonnet-20241022-v2:0',
     'anthropic', 'claude-3-5-sonnet-20241022-v2:0', 'bedrock'),
]
```

Per-case assertion pattern:
```python
for argv in invocations:
    flags = argv_to_flags(argv)
    self.assertEqual(flags.get('--provider'), expected_provider,
                     f'{label}: --provider mismatch')
    self.assertEqual(flags.get('--model'), expected_clean_model,
                     f'{label}: --model mismatch')
    if expected_model_source:
        self.assertEqual(flags.get('--model-source'), expected_model_source,
                         f'{label}: --model-source mismatch')
    else:
        self.assertNotIn('--model-source', flags,
                         f'{label}: --model-source must be absent (no billing_provider)')
```

Each case needs exactly 2 invocations (GUARDRAIL + CHAT marker pair).

---

#### COMPAT-01 assertion update (existing test; not a new method)

**File:** `tests/test_repository.py` lines 614-616

**Current (must be replaced in the same commit as the fallthrough code change):**
```python
self.assertNotIn('--operation-type', flags,
                 'zero-marker fallthrough must NOT emit --operation-type '
                 '(Phase 4 WIRE-01 owns that decision)')
```

**Phase 4 target:**
```python
self.assertEqual(flags.get('--operation-type'), 'CHAT',
                 'zero-marker fallthrough must emit --operation-type CHAT (WIRE-01 / D-22)')
```

---

### `skills/revenium/references/setup.md` (doc, D-25)

One paragraph appended to an existing section (or a new "Attribution semantics" section if absent). No pattern extraction needed — follow the plain-prose style of neighboring paragraphs in that file.

**Content (verbatim per D-25):**
> When markers carry different `agent` or `trace_id` values across a session, each Revenium meter call records the per-turn attribution; per-session aggregation happens dashboard-side.

---

## Shared Patterns

### `set -uo pipefail` discipline
**Source:** `skills/revenium/scripts/hermes-report.sh` line 5
**Apply to:** All edits within `hermes-report.sh`

`hermes-report.sh` uses soft-fail mode (`set -uo pipefail`, without `-e`). Do NOT change this flag. All new bash expressions in this file must be safe under soft-fail (failures do not propagate via `-e`; the per-session `continue` and `|| true` guards are already in place).

### Array-based CLI invocation
**Source:** `skills/revenium/scripts/hermes-report.sh` lines 550-576 (marker path) and 616-649 (fallthrough path)
**Apply to:** Both Block A and Block B edits

New flags are appended to the `cmd` array using the `cmd+=(--flag "${value}")` pattern, or declared inline in the array literal. Values are always quoted with `"${var}"`. Never use string concatenation or unquoted expansion for CLI arguments.

### `:-` default syntax for optional bash variables
**Source:** Established project convention (CLAUDE.md): `HERMES_HOME="${HERMES_HOME:-${HOME}/.hermes}"`
**Apply to:** Block A — `${m_agent:-Hermes}` and `${m_trace:-${sid}}`

Use colon-dash (`:-`) not bare dash (`-`). The colon-dash form substitutes the default for both *unset* and *empty-string* cases. Empty string from the pipe (`IFS='|' read`) leaves the variable set-but-empty; colon-dash is required for the fallback to fire.

### Python heredoc conventions
**Source:** `skills/revenium/scripts/hermes-report.sh` lines 517-534
**Apply to:** Block A — extending the split_rows heredoc

- Stdlib only (`json`, `os`, `sys`).
- `try/except Exception as exc` wraps the entire body; errors go to stderr (`file=sys.stderr`) and `sys.exit(3)`.
- `marker.get('key', '')` for optional fields — no `KeyError` risk.
- One `print(...)` per row; pipe-delimited; no trailing pipe.

### Test imports pattern
**Source:** `tests/test_repository.py` lines 361-368

All test methods import locally (not at module level), consistent with existing `RepositoryTests` methods:
```python
import json, os, shutil, sqlite3, subprocess, sys, tempfile
from decimal import Decimal
```

---

## No Analog Found

None. All three files have exact analogs in the codebase.

---

## Metadata

**Analog search scope:** `skills/revenium/scripts/`, `tests/`, `skills/revenium/references/`
**Files read:** `hermes-report.sh` (lines 1-60, 210-263, 505-674), `tests/test_repository.py` (lines 355-636)
**Pattern extraction date:** 2026-05-14
