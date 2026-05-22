---
phase: 19-guardrail-check-hook-repointing-enforcement-event-surfacing
plan: "08"
subsystem: pre-tool-call-hook
tags: [guardrails, hook, enforcement, warn-band, block-directive]
dependency_graph:
  requires: [19-02, 19-05]
  provides: [pre_tool_call_guardrail_repoint]
  affects: [skills/revenium/scripts/pre_tool_call.sh]
tech_stack:
  added: []
  patterns: [multi-value-python-status-read, warn-band-rate-limit, block-directive-env-pass]
key_files:
  modified:
    - skills/revenium/scripts/pre_tool_call.sh
decisions:
  - "Preserved CANCELLED marker block (lines 35-109) byte-identical with only budget-halt- -> guardrail-halt- rename"
  - "Warn-band uses payload session_id first, then sessions-dir scan fallback (mirrors existing logic)"
  - "ruleId char-set validation [A-Za-z0-9_-]+ applied before constructing WARN_FLAGS_DIR flag path (T-19-08-04)"
  - "Block directive emits action:block (not context: like pre_llm_call) - different hook shapes"
metrics:
  duration: "~5 minutes"
  completed: "2026-05-21"
  tasks_completed: 1
  files_modified: 1
---

# Phase 19 Plan 08: pre_tool_call.sh Guardrail Repoint Summary

Rewrote pre_tool_call.sh to read guardrail-status.json (Phase 19 schema with haltedRule), emit the D-01 verbatim halt string in the block directive, emit one rate-limited stderr warn line per (session, ruleId) when in warn band, and fail open when the file is missing or corrupt.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Rewrite pre_tool_call.sh — repoint status file, add warn-band, swap block directive, preserve CANCELLED marker | dd65510 | skills/revenium/scripts/pre_tool_call.sh |

## What Was Built

**pre_tool_call.sh** now has three behavioral branches:

1. **Halt branch** (`halted: true`): Reads multi-value haltedRule fields (RULE_NAME, METRIC_TYPE, WINDOW_TYPE, CURRENT_VALUE, HARD_LIMIT) from guardrail-status.json, runs the CANCELLED job marker block (Phase 12 D-05/D-06 invariant, preserved verbatim), then emits `{"action": "block", "message": "Guardrail halt active — rule '...' (..., ...) at ... of ... hard-limit. To resume: bash .../clear-halt.sh"}`.

2. **Warn branch** (`halted: false`, rules in `warn` state): Resolves session_id from payload or sessions-dir scan, validates ruleId char-set, checks sentinel marker at `WARN_FLAGS_DIR/<sid>__<ruleId>.flag`, creates marker and emits one `Guardrail warn:` line per (session, ruleId) to stderr (D-05: stderr only, not LOG_FILE). Then emits `{}` and exits 0.

3. **OK branch** (`halted: false`, no warn rules): Emits `{}` and exits 0 immediately.

**Fail-open behavior**: Any exception reading guardrail-status.json results in `HALTED=false`, emitting `{}` (HOOK-04).

## Deviations from Plan

None - plan executed exactly as written.

The optional `budget-halt-` → `guardrail-halt-` string rename (planner discretion, step F) was applied as recommended for SC-7 grep cleanliness.

## Verification Results

All plan verification criteria satisfied:

- `bash -n skills/revenium/scripts/pre_tool_call.sh` → 0
- `head -18 ... | grep -c 'cat -'` → 1 (stdin capture preserved as first executable statement after ensure_path)
- `grep -c 'GUARDRAIL_STATUS_FILE'` → 4 (≥1 required)
- `grep -c 'WARN_FLAGS_DIR'` → 2 (≥2 required)
- `grep -c 'haltedRule|RULE_NAME|METRIC_TYPE'` → 9 (≥1 required)
- `grep -c 'Guardrail halt active'` → 1 (≥1 required, D-01 string anchor)
- `grep -c 'agentic_job_id.*halt'` → 1 (CANCELLED marker preserved)
- `grep -c '"action".*"block"'` → 1 (block directive shape)
- `grep -v '^#' ... | grep -c 'budget'` → 0 (clean break in non-comment lines)
- `test_pre_tool_call_halted_blocks` → PASS
- `test_pre_tool_call_halted_blocks_guardrail` → PASS

Total lines: 207 (≥120 required by must_haves.artifacts.min_lines)

## Known Stubs

None.

## Threat Flags

No new security surface introduced beyond the plan's threat_model. All STRIDE mitigations applied:
- T-19-08-01: fail-open on missing/corrupt guardrail-status.json
- T-19-08-02: CANCELLED marker block preserved byte-identical (with only string-literal rename)
- T-19-08-03: warn line uses plain `echo ... >&2` not common.sh::warn
- T-19-08-04: ruleId char-set validation `[A-Za-z0-9_-]+` applied
- T-19-08-05: session_id from payload or scan (no path traversal; pseudo- fallback on failure)
- T-19-08-06: existing `|| true` on line wrapping CANCELLED marker heredoc preserved

## Self-Check: PASSED

- [x] skills/revenium/scripts/pre_tool_call.sh exists and modified
- [x] Commit dd65510 exists
- [x] Both halt-blocks tests pass
