---
phase: 19-guardrail-check-hook-repointing-enforcement-event-surfacing
plan: "05"
subsystem: cron-pipeline
tags: [guardrails, enforcement, cron-stage, halt-detection, audit]
dependency_graph:
  requires: [19-01, 19-02, 19-03]
  provides: [guardrail-status.json writer, HALT_TRANSITION machine, AUDIT-01/02 event embedding]
  affects: [cron.sh (invokes guardrail-check.sh), pre_llm_call.sh, pre_tool_call.sh, SKILL.md]
tech_stack:
  added: [os.replace atomic write pattern, name-to-string-id join via budget-rules list]
  patterns: [fail-open preflight, KEY=value stdout contract, HALT_TRANSITION carry-forward]
key_files:
  created:
    - skills/revenium/scripts/guardrail-check.sh
  modified:
    - tests/test_repository.py
decisions:
  - "PATH head saved before ensure_path and re-prepended after to preserve test stub precedence"
  - "EVENT_JSON sentinel __FAIL__ distinguishes API failure from empty result for AUDIT-02"
  - "_make_revenium_stub config-show case fixed to handle 2-arg trailing-space via alternation"
metrics:
  duration: ~40min
  completed: "2026-05-21"
  tasks_completed: 1
  files_created: 1
  files_modified: 1
---

# Phase 19 Plan 05: Author guardrail-check.sh Summary

guardrail-check.sh created as the v1.3 cron-stage replacement: polls enforcement-rules API, writes atomic guardrail-status.json with per-rule state machine (block/warn/ok), detects HALT_TRANSITION, and embeds enforcement-events (AUDIT-01/02) with graceful degradation.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Author guardrail-check.sh with preflight, per-rule status writer, HALT_TRANSITION machine | 839e3b9 | skills/revenium/scripts/guardrail-check.sh, tests/test_repository.py |

## Implementation Details

### guardrail-check.sh structure

The script follows the plan's exact structure:

**A. Shebang + strict-mode + SCRIPT_DIR + source + ensure_path** — `set -euo pipefail`, sources `common.sh`.

**PATH preservation**: Before `ensure_path`, the head of PATH is saved and re-prepended after, ensuring test-injected stub directories survive Homebrew path insertion. This is required because `ensure_path` prepends `/opt/homebrew/bin` which would otherwise displace stubs placed first in PATH by the test harness.

**B. Preflight checks** (fail-open, `warn` + `exit 0`):
1. `command -v revenium`
2. `command -v python3`
3. `[[ -f "${CONFIG_FILE}" ]]`
4. `has_guardrails_cli` (Phase 17 D-13 gate)
5. `revenium config show >/dev/null 2>&1`

**C. read_config_field** — Python heredoc helper for scalar config fields.

**D/E. Config extraction** — `RULE_IDS_JSON` (JSON array), `AUTONOMOUS`, `NOTIFY_CHANNEL`, `NOTIFY_TARGET`.

**F. teamId resolution** — `revenium config show 2>&1 | sed -n 's/.*Team ID:[ \t]*//p' | tr -d ' '`; empty → warn + exit 0.

**G. Enforcement rules fetch** — `enforcement-rules get "${TEAM_ID}" --output json 2>&1 || true`; EOF error response treated as empty rules.

**Pre-step: budget-rules list** — Called once per tick to build `name → string-id` map resolving the ruleId ID space mismatch (enforcement-rules API returns integer IDs; enforcement-events list requires string-hash IDs matching config.json::ruleIds).

**H. Python heredoc status writer** — Passes all data via env vars (bash 3.2 compat):
- Joins enforcement-rules response to budget-rules list via `name → string_id` map
- Derives per-rule `state`: `breached → 'block'`, `warnBreached → 'warn'`, else `'ok'`
- Loads prev state from existing `guardrail-status.json` (fail-open)
- Derives `new_halted = autonomous and any_blocked`
- HALT_TRANSITION: `new_halted and not prev_halted` → new halt; `new_halted and prev_halted` → carry forward `haltedAt`
- haltedRule (D-02 tiebreaker): first blocked rule in ruleIds[] declaration order
- Builds ENF-04 document; atomic write via `os.replace()` + `tempfile.mkstemp(dir=parent)`
- Emits `HALT_TRANSITION`, `HALTED_RULE_*` as KEY=value on stdout

**I. HALT_OUTPUT echo to stdout** — All KEY=value lines from Python heredoc are echoed to the script's stdout for observability.

**J. AUDIT-01/02** — On `HALT_TRANSITION=true`, fetches `enforcement-events list --rule-id HALTED_RULE_ID`. Failure sentinel `__FAIL__` distinguishes API failure from empty result:
- API failure → `EVENT_TS='(unavailable)'`, `EVENT_SUMMARY='(unavailable)'`, logs warn (AUDIT-02)
- Empty result → `(no events)` fallback
- Both paths emit `EVENT_TS=` and `EVENT_SUMMARY=` to stdout

**K. Operator notification** — Hermes messaging toolset with D-01 halt string template embedding rule fields + event data.

### Test stub fix (Rule 1 - Bug)

`_make_revenium_stub` in `tests/test_repository.py` had two bugs:
1. `case "$1 $2 $3"` with pattern `'config show'` doesn't match when called with only 2 args — bash expands empty `$3` producing `"config show "` (trailing space). Fixed with `'config show'|'config show '` alternation.
2. `has_guardrails_cli` probe calls (`guardrails budget-rules --help`, `guardrails enforcement-events --help`) fell through to `*) exit 1` causing preflight to fail. Fixed with explicit exit-0 cases.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] PATH preservation around ensure_path**
- **Found during:** Task 1 implementation
- **Issue:** `ensure_path` prepends `/opt/homebrew/bin` to PATH, pushing test stub directories created by `_make_revenium_stub` behind the real `revenium` binary at `/opt/homebrew/bin/revenium`. All `revenium` calls went to the real CLI (returning EOF for enforcement-rules get), making enforcement rules appear empty.
- **Fix:** Save `_PATH_HEAD="${PATH%%:*}"` before `ensure_path`, re-prepend after: `export PATH="${_PATH_HEAD}:${PATH}"`. Preserves test PATH injection while still benefiting from Homebrew paths ensure_path adds.
- **Files modified:** `skills/revenium/scripts/guardrail-check.sh`
- **Commit:** 839e3b9

**2. [Rule 1 - Bug] _make_revenium_stub config show pattern mismatch**
- **Found during:** Task 1 test debugging
- **Issue:** `case "$1 $2 $3" in 'config show')` doesn't match when `revenium config show` is called with 2 args — bash expands unset `$3` to `""`, making the case value `"config show "` (trailing space) which doesn't match `'config show'` (no space).
- **Fix:** Changed pattern to `'config show'|'config show '` alternation.
- **Files modified:** `tests/test_repository.py`
- **Commit:** 839e3b9

**3. [Rule 1 - Bug] _make_revenium_stub missing --help cases for has_guardrails_cli**
- **Found during:** Task 1 test debugging
- **Issue:** `has_guardrails_cli` calls `revenium guardrails budget-rules --help` and `revenium guardrails enforcement-events --help` but the stub's `*) exit 1` catch-all caused both to fail, triggering the `has_guardrails_cli` preflight exit-0.
- **Fix:** Added `'guardrails budget-rules --help') exit 0 ;;` and `'guardrails enforcement-events --help') exit 0 ;;` cases to the stub.
- **Files modified:** `tests/test_repository.py`
- **Commit:** 839e3b9

**4. [Rule 1 - Bug] enforcement-events API failure vs empty result distinction**
- **Found during:** Task 1 test for test_guardrail_check_audit_api_fallback
- **Issue:** `|| echo '[]'` turned API failure (exit 1) into an empty array `[]`, which Python then reported as `(no events)` rather than `(unavailable)`. Test asserts `EVENT_TS=(unavailable)` on API failure.
- **Fix:** Use sentinel `__FAIL__` instead of `echo '[]'`. Shell checks for sentinel and sets EVENT_TS/EVENT_SUMMARY to `(unavailable)` directly. Clean result goes through Python parsing.
- **Files modified:** `skills/revenium/scripts/guardrail-check.sh`
- **Commit:** 839e3b9

## Test Results

All 5 required tests pass:
- `test_guardrail_check_writes_status_file` — ok
- `test_guardrail_check_halt_transition` — ok
- `test_guardrail_check_halt_carry_forward` — ok
- `test_guardrail_check_no_rules_empty` — ok
- `test_guardrail_check_audit_api_fallback` — ok

`test_no_legacy_branding_left` — ok (no legacy branding in new file)

12 pre-existing test failures remain from other plans (19-03, 19-04): `pre_llm_call.sh`, `pre_tool_call.sh`, `clear-halt.sh`, `cron.sh`, and `test_no_legacy_budget_status_references` (still referencing `budget-check.sh` which those plans delete). These are out of scope for plan 19-05.

## Known Stubs

None. `guardrail-check.sh` is a fully functional implementation — all data paths are wired.

## Self-Check

### Created files exist
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/.claude/worktrees/agent-ae364a976bb75f44d/skills/revenium/scripts/guardrail-check.sh` — FOUND
- `.planning/phases/19-guardrail-check-hook-repointing-enforcement-event-surfacing/19-05-SUMMARY.md` — this file

### Commits exist
- 839e3b9 — FOUND (feat(19-05): author guardrail-check.sh)

## Self-Check: PASSED
