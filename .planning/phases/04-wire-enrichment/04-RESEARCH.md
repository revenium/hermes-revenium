# Phase 4: Wire Enrichment - Research

**Researched:** 2026-05-14
**Domain:** Bash/Python argv enrichment in `hermes-report.sh` — operation_type, agent, trace_id
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-22: WIRE-01 — Zero-marker fallthrough emits `--operation-type CHAT`, after research gate**
The cron's zero-marker fallthrough path will emit `--operation-type CHAT` alongside `--task-type unclassified`. Gated by mandatory research confirming Revenium treats `operation_type=null/absent` and `operation_type="CHAT"` identically. (See `## D-22 Research Gate Verdict` — gate has been discharged.)

**D-23: WIRE-02 + WIRE-03 — Cron pass-through ONLY; no upstream writer changes**
The cron reads optional `agent` and `trace_id` fields from each marker if present and emits them as `--agent <value>` / `--trace-id <value>`. When absent (universal case today), falls back to `--agent "Hermes"` and `--trace-id "${sid}"`. Extending `classifier.py` or `SKILL.md` FINAL ACTION snippet to populate these fields is explicitly out of scope.

**D-24: WIRE-04 — New argv-comparison regression test per provider class**
A new test method in `tests/test_repository.py` (suggested name: `test_wire_no_provider_regression_per_class`) stubs the `revenium` binary to capture argv, seeds synthetic state.db rows + markers per provider class, runs `hermes-report.sh`, and asserts the per-marker `revenium meter completion` argv carries the SAME `--provider`, `--model`, `--model-source` flags as the pre-Phase-3 single-call legacy path would have for that provider.

**D-25: Per-marker as-is for inconsistent agent/trace_id within a session**
When a session's markers have different `agent` or `trace_id` values across multiple markers, each per-marker `revenium meter completion` call carries THAT marker's values. No normalization / first-marker-wins / collapse to a single per-session value.

### Claude's Discretion

None declared (all implementation areas locked by D-22 through D-25).

### Deferred Ideas (OUT OF SCOPE)

- Extending `skills/revenium/plugins/revenium-classifier/classifier.py` to populate `agent` from session context (skill name, slash-command, model name).
- Extending the `SKILL.md` FINAL ACTION snippet to populate `agent` / `trace_id`.
- Sourcing `trace_id` from Hermes' internal trace propagation.
- Per-session dashboard aggregation guidance docs.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| WIRE-01 | `--operation-type` defaults to `CHAT` on zero-marker fallthrough — only after verifying the Revenium `manage_metering` tool confirms no cost-calculation shift | D-22 gate PASSES: API defaults absent operationType to CHAT server-side; cost calculation is identical regardless of operationType value |
| WIRE-02 | `--agent` populated from marker's `agent` field if present; falls back to `"Hermes"` | Marker MARKERS_JSON dict exposes `agent` key; split_rows pipe must be extended to carry it |
| WIRE-03 | `--trace-id` populated from marker's `trace_id` field if present; falls back to `${sid}` | Same as WIRE-02; `trace_id` is in MARKERS_JSON dict |
| WIRE-04 | Each split call carries same provider/model/source values as legacy single-call path | 8-class provider table in `## Provider Class Enumeration`; no change to provider inference code needed |
| COMPAT-01 | Existing installs without markers meter exactly as before, differing only by `--task-type unclassified` | The existing test assertion (`assertNotIn('--operation-type', flags)`) must be flipped to `assertEqual(flags['--operation-type'], 'CHAT')` after D-22 ships |
</phase_requirements>

---

## Summary

Phase 4 is a contained argv-enrichment of `skills/revenium/scripts/hermes-report.sh`. Two code paths require changes: the marker-driven per-marker emission block (lines 546-604) and the zero-marker fallthrough block (lines 606-669). No new state files, no new scripts, no upstream writer changes.

The D-22 research gate — the load-bearing blocker for WIRE-01 — has been discharged. Evidence from the Revenium API confirms that when `--operation-type` is absent from the wire, the API stores `operationType: "CHAT"` in the response record. Switching the zero-marker fallthrough from absent to explicit `--operation-type CHAT` causes NO change in cost aggregation, NO dashboard re-bucketing, and NO behavior difference for historical data. The gate PASSES.

The marker-driven path (per-marker emission) already emits `--operation-type ${op_type}` from the marker. Phase 4 extends this block to also emit `--agent` and `--trace-id` from the marker's optional fields, with fallback to today's hardcoded values. The extension happens by adding two fields (`agent` and `trace_id`) to the pipe-delimited split row that `split_strategies.py`'s second heredoc emits, then consuming them in the `while IFS='|' read` loop.

**Primary recommendation:** Extend the split_rows pipe format to carry `agent|trace_id` as fields 10-11, read them with default fallbacks in the while-read loop, and conditionally append `--agent` and `--trace-id` flags (or emit them unconditionally since both always have values — either from marker or from fallback).

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| `--operation-type` enrichment (zero-marker fallthrough) | Cron script (`hermes-report.sh`) | — | Pure argv addition; no agent or state changes |
| `--agent` / `--trace-id` enrichment (marker-driven path) | Cron script (`hermes-report.sh`) | Python heredoc (split_rows emitter) | Values sourced from marker JSON dict; passed through pipe |
| Provider inference preservation (WIRE-04) | Cron script (`hermes-report.sh`) existing code | — | No changes needed to inference; only to what surrounds it |
| New regression test (D-24) | `tests/test_repository.py` | Stubbed `revenium` binary shim | Follows existing `test_cron_marker_split_end_to_end` pattern exactly |
| COMPAT-01 test update | `tests/test_repository.py` | — | Flip one assertion line; the carve-out comment already anticipates this |
| `setup.md` D-25 attribution doc | `skills/revenium/references/setup.md` | — | One paragraph in existing "How attribution works" section |

---

## D-22 Research Gate Verdict

**GATE STATUS: PASSES**

### Query Executed

Three investigative paths were used:

**Path 1 — CLI dry-run comparison:**
```bash
# Absent operationType:
revenium meter completion --model claude-sonnet-4-6 --provider anthropic \
  --input-tokens 100 --output-tokens 50 --total-tokens 150 \
  --stop-reason END --request-time 2026-05-14T00:00:00Z \
  --completion-start-time 2026-05-14T00:00:01Z \
  --response-time 2026-05-14T00:00:05Z --request-duration 4000 \
  --is-streamed --task-type unclassified \
  --transaction-id d22-gate-test-absent-001 --dry-run --json
```
Body emitted to API: `{"operationType": ABSENT}` — the key is not included in the JSON body.

```bash
# Explicit CHAT:
--operation-type CHAT --transaction-id d22-gate-test-chat-001 --dry-run --json
```
Body emitted to API: `{"operationType": "CHAT"}`.

[VERIFIED: revenium CLI dry-run, 2026-05-14]

**Path 2 — Historical API record inspection:**
```bash
revenium metrics completions --from 2026-04-01T00:00:00Z --to 2026-05-12T23:59:59Z --json
```
All 50 records returned show `operationType: "CHAT"` in the API response — including records that predate Phase 3 (i.e., sent without any `--operation-type` flag from the pre-Phase-3 cron). This confirms the API server-side default for an absent `operationType` is `CHAT`.

[VERIFIED: Revenium API via revenium CLI, 2026-05-14]

**Path 3 — Cost calculation parity between GUARDRAIL and CHAT:**
```
GUARDRAIL: id=v94Kq7 inputTokens=28733 totalCost=0.009916
CHAT:      id=5jGkJK inputTokens=28733 totalCost=0.009915

GUARDRAIL: id=lmJAL1 inputTokens=17686 totalCost=0.005954
CHAT:      id=D84aJL inputTokens=17686 totalCost=0.005955
```
These are GUARDRAIL+CHAT pairs from the same session (same token count, equal-split). The difference ($0.000001) is floating-point rounding only. `operationType` is an analytics dimension, not a cost multiplier.

[VERIFIED: Revenium API via revenium CLI, 2026-05-14]

### Interpretation

The Revenium API treats `operationType` as a segmentation/analytics dimension only. It does not modify the cost calculation formula. The server-side default when absent is `CHAT`. Switching the zero-marker fallthrough from absent to explicit `--operation-type CHAT` is therefore:
- Idempotent from a cost perspective (no budget impact for existing customers)
- Idempotent from an analytics perspective (existing records already show `CHAT` in dashboards)
- Safe to ship without a migration period or feature flag

### Additional Finding: GUARDRAIL Not in CLI Help Enum

The `revenium meter completion --help` output lists: `Operation type (CHAT, GENERATE, EMBED, CLASSIFY, SUMMARIZE, TRANSLATE, OTHER)`. `GUARDRAIL` is NOT listed. However, dry-run testing confirms the CLI accepts and passes through `GUARDRAIL` to the API body, and the API stores it correctly (confirmed by Phase 6 records showing `operationType: "GUARDRAIL"`). The CLI help enum is not exhaustive — the API accepts additional values including `GUARDRAIL`, `LLM`, and `TOOL_CALL`. No action needed for Phase 4.

### Gate Decision

D-22 **ships as stated**: add `--operation-type CHAT` to the zero-marker fallthrough cmd array in `hermes-report.sh`. The D-22 fallback (permanently omit, update setup.md) is NOT needed.

---

## Provider Class Enumeration (for D-24)

All 8 provider classes enumerated from `hermes-report.sh` lines 214-263. These are the test cases D-24's regression test must cover.

[VERIFIED: direct code reading of hermes-report.sh, 2026-05-14]

### Provider inference code structure

`clean_model` (lines 214-222): strips `owner/` prefix (OpenRouter), then strips any of `global.`, `anthropic.`, `openai.`, `google.`, `x-ai.` prefixes (Bedrock-style).

`provider` (lines 224-263): branch on `billing_provider` first; if present and not `openrouter`/`bedrock`, emit it verbatim. Special-case `openrouter` and `bedrock` to decode the underlying model provider from the model string. Fall through to model-string inference when `billing_provider` is absent/empty/`none`/`unknown`.

### The 8 Cases

| Class | `billing_provider` | `model` shape | `--provider` result | `--model` (clean) | `--model-source` | `--total-cost` |
|-------|--------------------|---------------|---------------------|-------------------|------------------|----------------|
| **anthropic** | `"anthropic"` | `"claude-sonnet-4-6"` | `anthropic` | `claude-sonnet-4-6` | `--model-source anthropic` | emitted if non-zero |
| **openai** | `"openai"` | `"gpt-4o"` | `openai` | `gpt-4o` | `--model-source openai` | emitted if non-zero |
| **google** | `"google"` | `"gemini-1.5-pro"` | `google` | `gemini-1.5-pro` | `--model-source google` | emitted if non-zero |
| **xai** | `"xai"` | `"grok-2"` | `xai` | `grok-2` | `--model-source xai` | emitted if non-zero |
| **deepseek** | `"deepseek"` | `"deepseek-chat"` | `deepseek` | `deepseek-chat` | `--model-source deepseek` | emitted if non-zero |
| **meta** | `""` (empty) | `"llama-3.1-70b"` | `meta` | `llama-3.1-70b` | **ABSENT** (no billing_provider) | emitted if non-zero |
| **openrouter-special** | `"openrouter"` | `"anthropic/claude-sonnet-4-5"` | `anthropic` | `claude-sonnet-4-5` | `--model-source openrouter` | emitted if non-zero |
| **bedrock-special** | `"bedrock"` | `"anthropic.claude-3-5-sonnet-20241022-v2:0"` | `anthropic` | `claude-3-5-sonnet-20241022-v2:0` | `--model-source bedrock` | emitted if non-zero |

### Key Observations for D-24 Test Design

1. **meta case is the only one with no `--model-source` flag** — the test must assert the flag is absent, not just that it has a specific value.

2. **openrouter-special**: `provider` becomes `anthropic` (not `openrouter`); `--model-source openrouter` is retained. The `clean_model` strips the `anthropic/` prefix leaving just `claude-sonnet-4-5`.

3. **bedrock-special**: `provider` becomes `anthropic` (not `bedrock`); `--model-source bedrock` is retained. The `clean_model` strips the `anthropic.` prefix leaving `claude-3-5-sonnet-20241022-v2:0` (note the `:0` version suffix is preserved — do not strip it).

4. **`--total-cost` omission condition**: the existing code checks `d_cost != "0"` and `!= "0.000000"` and `!= "0.0"` (slightly different between the two paths). Test fixtures should include non-zero `estimated_cost_usd` to exercise the cost-emitting branch.

5. **`--model-source` omission condition**: the `billing_provider` column is the direct gating condition (`if [[ -n "${billing_provider}" ]]`). The meta test case must seed `billing_provider` as empty string `""`.

### Fixture shape per case

Each case needs one state.db row:
```python
{
    'id': sid,
    'model': <model from table above>,
    'source': 'test',
    'input_tokens': 10000,
    'output_tokens': 4000,
    'cache_read': 200,
    'cache_write': 100,
    'reasoning': 0,
    'estimated_cost': '0.123456',
    'api_calls': 2,
    'started_at': 1715514000.0,   # old timestamp — bypasses G-03 sentinel filter
    'ended_at': 1715515100.0,
    'billing_provider': <billing_provider from table above>,
}
```

Each case needs a marker pair (GUARDRAIL + CHAT) with the same `sid` so the split path runs (N=2). The test asserts `--provider`, `--model`, `--model-source` match expectations. Provider regression is per-call, so assert on every invocation.

---

## Wire Extension Points

### Marker-Driven Path (WIRE-02 / WIRE-03)

**File:** `skills/revenium/scripts/hermes-report.sh`
**Lines:** 517-534 (split_rows Python heredoc that emits pipe-delimited rows)

**Current format (line 528-529):**
```python
print(f"{marker['muid']}|{marker['task_type']}|{marker['operation_type']}|"
      f"{split['input']}|{split['output']}|{split['cache_read']}|"
      f"{split['cache_write']}|{split['total']}|{split['cost']}")
```

**Phase 4 extension:** Add two more fields (`agent` and `trace_id`) as fields 10-11:
```python
m_agent = marker.get('agent', '')      # empty string = use fallback
m_trace = marker.get('trace_id', '')   # empty string = use fallback
print(f"{marker['muid']}|{marker['task_type']}|{marker['operation_type']}|"
      f"{split['input']}|{split['output']}|{split['cache_read']}|"
      f"{split['cache_write']}|{split['total']}|{split['cost']}|"
      f"{m_agent}|{m_trace}")
```

**Lines:** 546-547 (bash while-read loop declaration)

**Current:**
```bash
while IFS='|' read -r muid t_type op_type d_in d_out d_cr d_cw d_tot d_cost; do
```

**Phase 4 extension:**
```bash
while IFS='|' read -r muid t_type op_type d_in d_out d_cr d_cw d_tot d_cost m_agent m_trace; do
```

**Lines:** 550-571 (cmd array construction)

**Current `--agent` and `--trace-id` lines (lines 564-566):**
```bash
--agent "Hermes"
...
--trace-id "${sid}"
```

**Phase 4 extension:** Replace with conditional fallback:
```bash
--agent "${m_agent:-Hermes}"
...
--trace-id "${m_trace:-${sid}}"
```

Since both always have a value (either from the pipe or the default), these can be unconditional flags. The `:-` default syntax handles the empty-string-from-pipe case cleanly.

### Zero-Marker Fallthrough (WIRE-01)

**File:** `skills/revenium/scripts/hermes-report.sh`
**Lines:** 606-669

**Insertion point:** After the `--task-type "unclassified"` line (line 635), before the first conditional append block (`if [[ -n "${billing_provider}" ]]`).

**Current (line 635):**
```bash
--task-type "unclassified"
)
```

**Phase 4 extension:**
```bash
--task-type "unclassified"
--operation-type "CHAT"
)
```

This is the ONLY change to the fallthrough cmd array. `--agent` and `--trace-id` are already present with their hardcoded values (`"Hermes"` and `"${sid}"`) — no change needed here.

### `set -uo pipefail` Discipline

`hermes-report.sh` uses `set -uo pipefail` (soft-fail mode). The two insertion points are:
- Inside a Python heredoc (uses `|| echo ''` fallback pattern) — safe
- In the bash cmd array construction — safe (no new process substitutions needed)

No change to the script's `set` flags is required or permitted.

---

## Marker Field Semantics

[VERIFIED: Phase 2 CONTEXT.md, tests/test_repository.py, 2026-05-14]

### Required Keys (all 5 must be present for a marker to be processed)

| Key | Type | Validation (cron-side) |
|-----|------|------------------------|
| `muid` | string | 33-char lowercase hex regex checked in test schema |
| `ts` | float | `float(m['ts'])` — fails → skip marker |
| `sid` | string | Must match the session id being processed |
| `task_type` | string | Not in FORBIDDEN set; cron enforces the blocklist |
| `operation_type` | string | Pass-through verbatim (no cron-side enum validation) |

### Optional Keys (Phase 4 reads these two)

| Key | Type | Semantics | Null-safe parse |
|-----|------|-----------|-----------------|
| `agent` | string | Free string — intended for skill name or slash-command. No regex validation defined. No `\|` restriction in schema (but fallback `"Hermes"` is pipe-safe). | `marker.get('agent', '')` → empty string triggers bash fallback |
| `trace_id` | string | Free string — intended for session-derived trace context (e.g., `"${sid}:17"`). No regex validation defined. | `marker.get('trace_id', '')` → empty string triggers bash fallback |

### Important: No Upstream Writer Populates These Today

Per D-23, `classifier.py` and `SKILL.md` write only the 5 required keys. In production, `m_agent` and `m_trace` will always be the empty string from the pipe, triggering the `"Hermes"` and `"${sid}"` fallbacks. Phase 4 ships the wire ready for the moment any upstream writer populates them.

### Pipe-Safety Note

The pipe-delimited split_rows format uses `|` as the field separator. The `agent` and `trace_id` values, when present, must not contain `|`. Today's only possible values are the fallback defaults (pipe-safe). When upstream writers do populate these fields, they should be documented as pipe-safe (e.g., skill names, session IDs, slash-command names). Add a comment at the extension point in `hermes-report.sh` noting this constraint.

### marker validation: optional fields do NOT break Phase 2 invariants

The cron's marker reader at line 399 only checks `REQUIRED_KEYS`:
```python
REQUIRED_KEYS = ('muid', 'ts', 'sid', 'task_type', 'operation_type')
if not all(k in m for k in REQUIRED_KEYS):
    continue
```
Reading `m.get('agent', '')` and `m.get('trace_id', '')` on the marker dict is safe whether or not the optional keys are present. No schema re-validation needed. Phase 2's invariants are preserved.

---

## OpenInference span_kind Verification

[CITED: .planning/research/STACK.md, Phase 2 implementation in classifier.py and SKILL.md]

### The CHAT Value

The Phase 2 implementation chose `CHAT` (not `LLM`) for work turn markers. This is the Revenium API's own primary enum value. The OpenInference spec defines `LLM` as the canonical value; Revenium's CLI enum defines `CHAT`. The production implementation already uses `CHAT` throughout:

- `classifier.py` line 315: `line_c = json.dumps(_record("CHAT"), ...)`
- `SKILL.md`: `write_marker("code_review", "CHAT")  # work span`
- All existing API records with a work span show `operationType: "CHAT"`

**Canonical casing for Phase 4: `"CHAT"` (all caps)**. This matches the Revenium CLI help, the existing production records, and the existing `classifier.py`/`SKILL.md` writes.

Do NOT use `"chat"`, `"Chat"`, or `"LLM"`. The string `"CHAT"` is what ships on the wire.

### The GUARDRAIL Value

`GUARDRAIL` is defined in the OpenInference spec as the span kind for "calls to a component to protect against jailbreak user input prompts." Phase 2/6 repurposed it for classification overhead — analytically appropriate ("this is overhead, not work"). The Revenium API accepts and stores it correctly despite it not appearing in the CLI help enum. No change needed for Phase 4 — the marker-driven path already emits `--operation-type "${op_type}"` verbatim, which passes `GUARDRAIL` through for classification markers.

---

## Pitfalls

### Pitfall 1: Pipe field count regression in split_rows heredoc

**What goes wrong:** Adding `agent|trace_id` as fields 10-11 of the pipe-delimited row means the `while IFS='|' read` loop must declare two additional variables. If the loop declaration is not updated to match, bash will assign the entire tail (fields 10+) to `d_cost`, causing `d_cost` to silently become `"0.123456|Hermes|session-id"` and break the `--total-cost` conditional check.

**How to avoid:** Update BOTH the Python print statement (in the split_rows heredoc) AND the bash while-read variable list atomically in the same edit. Test with a marker that has a non-zero `estimated_cost_usd` to confirm `--total-cost` still emits correctly.

**Warning signs:** The `assertNotIn('--total-cost', flags)` assertion passes when cost should be non-zero; or `--total-cost` carries a garbled value.

### Pitfall 2: COMPAT-01 test must be updated before the code change lands

**What goes wrong:** The existing `test_cron_marker_split_end_to_end` sub-case 2 asserts `assertNotIn('--operation-type', flags)` with the comment `'(Phase 4 WIRE-01 owns that decision)'`. If the code change lands without updating this assertion, the test will FAIL.

**How to avoid:** Update the test assertion in the SAME commit that adds `--operation-type CHAT` to the fallthrough cmd array. The new assertion is:
```python
self.assertEqual(flags.get('--operation-type'), 'CHAT',
                 'zero-marker fallthrough must emit --operation-type CHAT (WIRE-01 / D-22)')
```

**Warning signs:** `test_cron_marker_split_end_to_end` fails immediately after the code edit.

### Pitfall 3: Agent/trace_id fallback using `:-` in bash with empty string from pipe

**What goes wrong:** When the Python heredoc emits `|` as the value for `m_agent` (empty string after split), the bash variable `m_agent` is set to the empty string. The `${m_agent:-Hermes}` expansion correctly expands to `"Hermes"` for the empty string case — this is the intended behavior. However, a developer might mistakenly write `${m_agent-Hermes}` (without `:`) which does NOT expand to the default for empty strings, only for unset variables.

**How to avoid:** Use `:-` (colon-dash) not `-` (dash) for the fallback expansion.

**Warning signs:** `--agent ""` appears in the argv (empty string value) instead of `--agent Hermes`.

### Pitfall 4: Provider inference regression from flag ordering

**What goes wrong:** The Phase 3 cmd array in the marker-driven path has a specific flag order. The `--agent` and `--trace-id` flags are at positions 15-17 in the array. Adding `--operation-type` to the fallthrough path and changing `--agent`/`--trace-id` to use variable expansion does NOT affect any flag ordering — Revenium CLI accepts flags in any order.

**How to avoid:** No special action needed. Revenium's `meter completion` is order-agnostic for flags. The `--quiet` and `--is-streamed` flags are boolean (no value argument); they will not interfere with the new flags.

**Warning signs:** None expected from flag ordering, but if CI fails with "unknown flag" errors, check that `${m_agent:-Hermes}` and `${m_trace:-${sid}}` are quoted correctly in the cmd array.

### Pitfall 5: Bedrock model string with colon not breaking pipe split

**What goes wrong:** The bedrock model `anthropic.claude-3-5-sonnet-20241022-v2:0` contains a colon (`:`) but NOT a pipe (`|`). The pipe-delimited split_rows format is safe. However, if a future model ID ever contains a pipe character, the split would silently corrupt. Note that the `billing_provider` value for bedrock (`"bedrock"`) is passed as `--model-source`, which is safe.

**How to avoid:** No action needed for Phase 4 — this is a pre-existing constraint of the pipe format that Phase 3 already accepted. Document the pipe-safety requirement in a comment at the extension point.

### Pitfall 6: D-24 test must use old `started_at` to bypass the G-03 sentinel filter

**What goes wrong:** Phase 6's G-03 filter skips sessions younger than `REVENIUM_CRON_SETTLE_SECONDS` (default 120s) that lack a sentinel file. If the D-24 test seeds sessions with `started_at = time.time()` (current time), the filter will skip them and the test gets 0 invocations.

**How to avoid:** Use `started_at = 1715514000.0` (a fixed timestamp in 2024, age ~63M seconds) as the existing `test_cron_marker_split_end_to_end` does. This automatically bypasses the sentinel filter without needing to create sentinel files.

**Warning signs:** D-24 test gets 0 invocations instead of the expected N.

---

## Test Scaffolding Reference

### Existing Pattern to Mirror (`test_cron_marker_split_end_to_end`)

The D-24 test mirrors the exact fixture pattern from the existing end-to-end test. Key elements:

**1. Temp directory layout:**
```python
tmpdir = tempfile.mkdtemp(prefix='gsd-wire-provider-e2e-')
hermes_home = os.path.join(tmpdir, 'hh')
state_dir = os.path.join(hermes_home, 'state', 'revenium')
markers_dir = os.path.join(state_dir, 'markers')
os.makedirs(markers_dir, mode=0o700)
state_db = os.path.join(hermes_home, 'state.db')
ledger = os.path.join(state_dir, 'revenium-hermes.ledger')
```

**2. Revenium shim placement:**
```python
shim_home = os.path.join(tmpdir, 'home')
bin_dir = os.path.join(shim_home, '.local', 'bin')
os.makedirs(bin_dir)
```
Place the stub at `${shim_home}/.local/bin/revenium`. The `common.sh::ensure_path` prepends `/opt/homebrew/bin` (where the real revenium lives) AFTER the loop, so `${HOME}/.local/bin` ends up FIRST in PATH and the shim wins.

**3. Shim script (captures argv):**
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
The shim shifts past `meter completion` and captures the remaining argv shell-escaped on one line per invocation.

**4. Base env:**
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

**5. state.db schema (must match exactly):**
```python
conn.execute(
    'CREATE TABLE sessions ('
    'id TEXT, model TEXT, source TEXT, '
    'input_tokens INTEGER, output_tokens INTEGER, '
    'cache_read_tokens INTEGER, cache_write_tokens INTEGER, '
    'reasoning_tokens INTEGER, estimated_cost_usd TEXT, '
    'api_call_count INTEGER, started_at REAL, ended_at REAL, '
    'billing_provider TEXT)'
)
```

**6. Marker fixture per case (GUARDRAIL + CHAT pair for N=2):**
```python
markers = [
    {'muid': '01893b8a300abcdef0123456789abc01',
     'ts': 1715515001.0, 'sid': sid,
     'task_type': 'code_review', 'operation_type': 'GUARDRAIL'},
    {'muid': '01893b8a300abcdef0123456789abc02',
     'ts': 1715515002.0, 'sid': sid,
     'task_type': 'code_review', 'operation_type': 'CHAT'},
]
```
Write as JSONL to `markers_dir/{sid}.jsonl`.

**7. argv_to_flags helper** (already in the file — reuse it):
```python
def argv_to_flags(argv):
    """Convert flat argv to {flag: value} dict for assertions."""
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

**8. Per-case assertion pattern for D-24:**
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

**9. Test structure choice:** DRY loop over the 8-case tuple list is preferred over 8 separate methods. Use descriptive `label` strings in assertion messages so CI output identifies the failing case.

### COMPAT-01 Test Update Required

The existing assertion at `test_cron_marker_split_end_to_end` sub-case 2 (line 614):
```python
self.assertNotIn('--operation-type', flags,
                 'zero-marker fallthrough must NOT emit --operation-type '
                 '(Phase 4 WIRE-01 owns that decision)')
```
Must be replaced with:
```python
self.assertEqual(flags.get('--operation-type'), 'CHAT',
                 'zero-marker fallthrough must emit --operation-type CHAT (WIRE-01 / D-22)')
```
This is a single-line change in an existing sub-case. The surrounding test structure does not change.

---

## Assumptions Log

No `[ASSUMED]` claims in this research. All findings were verified via tool calls (revenium CLI dry-run, Revenium API metrics query, direct code reading).

If this table is empty: All claims in this research were verified or cited — no user confirmation needed.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `revenium` CLI | D-22 gate query, tests | Yes | Homebrew installed at `/opt/homebrew/bin/revenium` | — |
| `python3` | hermes-report.sh heredocs | Yes | System python3 | — |
| `sqlite3` CLI | hermes-report.sh state.db read | Yes | System sqlite3 | — |
| `bash` | script execution | Yes | macOS bash | — |

No missing dependencies. Phase 4 is purely a code-and-test modification with no new external dependencies.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Python unittest (stdlib) |
| Config file | None — discovery via `python3 -m unittest discover -s tests -p 'test_*.py' -v` |
| Quick run command | `python3 -m unittest tests.test_repository.RepositoryTests.test_cron_marker_split_end_to_end -v` |
| Full suite command | `python3 -m unittest discover -s tests -p 'test_*.py' -v` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| WIRE-01 | Zero-marker fallthrough emits `--operation-type CHAT` | end-to-end (existing test updated) | `python3 -m unittest tests.test_repository.RepositoryTests.test_cron_marker_split_end_to_end -v` | Yes (assertion update) |
| WIRE-02 | `--agent` carries marker value when present | unit + e2e (new test method, WIRE-02 sub-case) | `python3 -m unittest tests.test_repository.RepositoryTests.test_wire_agent_trace_passthrough -v` | No — Wave 0 |
| WIRE-03 | `--trace-id` carries marker value when present | unit + e2e (same new test method) | Same as WIRE-02 | No — Wave 0 |
| WIRE-04 | Provider/model/source preserved across all 8 provider classes | end-to-end (new test method `test_wire_no_provider_regression_per_class`) | `python3 -m unittest tests.test_repository.RepositoryTests.test_wire_no_provider_regression_per_class -v` | No — Wave 0 |
| COMPAT-01 | Zero-marker argv diff: only addition is `--task-type unclassified` + `--operation-type CHAT` | assertion update in existing test | `python3 -m unittest tests.test_repository.RepositoryTests.test_cron_marker_split_end_to_end -v` | Yes (assertion update) |

### Sampling Rate

- **Per task commit:** `python3 -m unittest discover -s tests -p 'test_*.py' -v`
- **Per wave merge:** `python3 -m unittest discover -s tests -p 'test_*.py' -v`
- **Phase gate:** Full suite green (currently 37 tests; Phase 4 adds 2 new methods) before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/test_repository.py::test_wire_agent_trace_passthrough` — covers WIRE-02 + WIRE-03 (new method; seeds marker with explicit `agent`/`trace_id` fields and asserts the argv carries them)
- [ ] `tests/test_repository.py::test_wire_no_provider_regression_per_class` — covers WIRE-04 (new method; 8-case loop per provider class table above)

**Not a new file gap:** `tests/test_repository.py` exists; both methods are added to the existing `RepositoryTests` class.

---

## Security Domain

`security_enforcement` is not explicitly configured in `.planning/config.json` (file does not exist). Treating as enabled.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | — |
| V3 Session Management | No | — |
| V4 Access Control | No | — |
| V5 Input Validation | Yes (partial) | Marker field reads use `.get()` with default; no injection risk since values become CLI flag values passed as array elements not shell-interpolated strings |
| V6 Cryptography | No | — |

### Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Marker `agent` field injection | Tampering | The cmd array pattern `cmd+=(--agent "${value}")` passes values as argv array elements — no shell word splitting, no injection risk. Already established pattern for all marker fields. |
| Marker `trace_id` field injection | Tampering | Same array-element pattern; no risk. |
| Pipe field count manipulation via crafted marker | Tampering | The 4096-byte per-line cap in the marker reader (line 392 of hermes-report.sh) limits blast radius. The split_rows heredoc reads from `MARKERS_JSON` env var (already parsed and sanitized by the first heredoc). No direct file-to-pipe path. |

No new security concerns introduced by Phase 4. The existing defense-in-depth (array-based argv, per-line size cap, try/except around marker parsing) covers the new fields.

---

## Open Questions

None. All research areas specified in the phase scope were resolved.

---

## Sources

### Primary (HIGH confidence)

- Direct code reading of `skills/revenium/scripts/hermes-report.sh` (lines 214-669) — provider inference, marker-driven path, zero-marker fallthrough
- Direct code reading of `skills/revenium/scripts/split_strategies.py` — pipe format and field ordering
- Direct code reading of `tests/test_repository.py` (lines 355-748) — `test_cron_marker_split_end_to_end` pattern
- `revenium meter completion --dry-run --json` CLI introspection — confirmed absent vs CHAT body difference
- `revenium metrics completions --json` API query (50+ records, 2026-04-01 to 2026-05-14) — confirmed server-side default of CHAT for absent operationType

### Secondary (MEDIUM confidence)

- `.planning/phases/04-wire-enrichment/04-CONTEXT.md` — locked decisions D-22 through D-25
- `.planning/research/STACK.md` — OpenInference span_kind vocabulary reference
- `.planning/phases/02-prompt-design-marker-contract/02-CONTEXT.md` — marker optional field semantics

### Tertiary (LOW confidence)

None. All findings in this research are verified at HIGH or MEDIUM confidence.

---

## Metadata

**Confidence breakdown:**
- D-22 gate verdict: HIGH — multiple independent evidence paths (CLI dry-run + API historical data + cost parity)
- Provider class enumeration: HIGH — direct code reading verified with Python simulation
- Wire extension points: HIGH — direct code reading with line-number citations
- Marker field semantics: HIGH — verified from Phase 2 CONTEXT.md + production test schema
- Test scaffolding: HIGH — mirrors existing passing test pattern exactly

**Research date:** 2026-05-14
**Valid until:** 2026-06-14 (stable; no external API dependency that would change)
