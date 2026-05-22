---
phase: 19-guardrail-check-hook-repointing-enforcement-event-surfacing
verified: 2026-05-22T14:00:00Z
status: human_needed
score: 12/12 must-haves verified
overrides_applied: 0
human_verification:
  - test: "SC-8 live-host warn-to-block guardrail transition with real Revenium API"
    expected: "Driving a real rule above its hardLimit triggers HALT_TRANSITION=true in guardrail-check.sh, guardrail-status.json flips halted:true with haltedRule populated, and the Hermes messaging-toolset notification arrives with enforcement-event timestamp+summary embedded"
    why_human: "The live-host verification (19-12-SUMMARY.md) was conducted using synthetic fixture files rather than a real breached Revenium rule — the enforcement-events list embedding (AUDIT-01) was not exercised against a real API enforcement event because HALT_TRANSITION=false on every live cron tick (live ruleIds array is empty after the legacy alertId was deleted upstream). The unit tests mock the enforcement-events API."
---

# Phase 19: Guardrail Check, Hook Repointing & Enforcement-Event Surfacing Verification Report

**Phase Goal:** `guardrail-check.sh` replaces `budget-check.sh`; `pre_llm_call`/`pre_tool_call` hooks read `guardrail-status.json` (warn vs. block); halt notifications embed `enforcement-events list` output.

**Verified:** 2026-05-22T14:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `guardrail-check.sh` is the cron second stage; `budget-check.sh` is deleted | VERIFIED | `cron.sh:76` invokes `guardrail-check.sh || true`; `skills/revenium/scripts/budget-check.sh` does not exist (confirmed `test ! -f` passes) |
| 2 | `guardrail-status.json` written per ENF-04 schema (rules[] + haltedRule on halt) | VERIFIED | `guardrail-check.sh:107-224` Python heredoc builds full 10-field per-rule entries + top-level fields; `test_guardrail_check_writes_status_file` passes |
| 3 | `budget-status.json` is absent from the skill tree (code + scripts) | VERIFIED | SC-7 grep returns zero matches in `.sh/.py/.yml/.yaml/.json` excluding the intentional `rm -f` cleanup carrier in `guardrail-check.sh`; `test_no_legacy_budget_status_references` passes |
| 4 | HALT_TRANSITION state machine distinguishes new vs. carry-forward halt | VERIFIED | `guardrail-check.sh:178-228` prev_halted detection; `test_guardrail_check_halt_transition` + `test_guardrail_check_halt_carry_forward` both pass |
| 5 | `clear-halt.sh` accepts `--rule-id <id>` (per-rule clear) and bare form (clear all) | VERIFIED | `clear-halt.sh:15-95` arg parsing + Python per-rule state recompute; `test_clear_halt_bare`, `test_clear_halt_rule_id`, `test_clear_halt_rule_id_not_blocked` all pass |
| 6 | Hooks read `guardrail-status.json`; emit D-01 halt string on `halted:true` | VERIFIED | `pre_llm_call.sh:23-145` and `pre_tool_call.sh:20-206` read `GUARDRAIL_STATUS_FILE`; D-01 template `"Guardrail halt active — rule '[name]' ([metricType], [windowType]) at [currentValue] of [hardLimit] hard-limit. To resume: bash ~/.hermes/skills/revenium/scripts/clear-halt.sh"` confirmed at `pre_llm_call.sh:137` and `pre_tool_call.sh:202` |
| 7 | Warn band: rate-limited stderr per (session, ruleId), sentinel under WARN_FLAGS_DIR | VERIFIED | `pre_llm_call.sh:46-115` and `pre_tool_call.sh:43-165`; sentinel files at `WARN_FLAGS_DIR/<sid>__<ruleId>.flag`; `test_pre_llm_call_warn_band_emits_stderr` + `test_pre_llm_call_warn_rate_limit` pass |
| 8 | Hooks fail open on missing/corrupt `guardrail-status.json` | VERIFIED | Both hooks have `except Exception: print('HALTED=false')` (HOOK-04); `test_pre_llm_call_fail_open` passes |
| 9 | SKILL.md HALT CHECK block reads `guardrail-status.json` with D-01 halt string | VERIFIED | `SKILL.md:24-67` rewritten; `grep -c "budget-status.json" SKILL.md` returns 0; `test_prompt_ordering_invariant` passes |
| 10 | `AUDIT-01`: enforcement-events list embedded in halt notification | VERIFIED (unit) / UNCERTAIN (live) | `guardrail-check.sh:265-297` calls `enforcement-events list --rule-id ... --page-size 1`; `test_guardrail_check_halt_transition` passes with mock. Live test not fired (no real block transition during Mac Studio verification — see human verification note) |
| 11 | `AUDIT-02`: graceful degradation when events API fails | VERIFIED | `guardrail-check.sh:271-274` uses `__FAIL__` sentinel; `test_guardrail_check_audit_api_fallback` passes |
| 12 | All 12 Phase 19 requirements pass full automated test suite (114 tests) | VERIFIED | `python3 -m unittest discover -s tests -p 'test_*.py'` → `Ran 114 tests in 39.4s OK` (confirmed locally; confirmed on Mac Studio per 19-12-SUMMARY.md Step 2) |

**Score:** 12/12 truths verified (truth #10 has a live-API uncertainty on the enforcement-event embedding path; automated tests cover it with mocks)

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `skills/revenium/scripts/guardrail-check.sh` | New cron stage writer | VERIFIED | 314 lines; bash -n passes; substantive implementation |
| `skills/revenium/scripts/budget-check.sh` | Deleted (clean break) | VERIFIED | File absent; `test_expected_files_exist` excludes it |
| `skills/revenium/scripts/cron.sh` | Line 76 swapped to guardrail-check.sh | VERIFIED | `grep -c "guardrail-check.sh" cron.sh` = 1 at line 76 |
| `skills/revenium/scripts/pre_llm_call.sh` | Repointed to guardrail-status.json with warn-band | VERIFIED | 146 lines; GUARDRAIL_STATUS_FILE refs x4, WARN_FLAGS_DIR x2, D-01 halt string x1 |
| `skills/revenium/scripts/pre_tool_call.sh` | Repointed; CANCELLED marker preserved | VERIFIED | 207 lines; block directive confirmed; CANCELLED marker block preserved verbatim |
| `skills/revenium/scripts/clear-halt.sh` | Rule-aware with --rule-id flag, atomic write | VERIFIED | 95 lines; arg parsing confirmed; os.replace atomic write at line 84 |
| `skills/revenium/scripts/common.sh` | WARN_FLAGS_DIR added; BUDGET_STATUS_FILE removed | VERIFIED | Line 20: WARN_FLAGS_DIR; no BUDGET_STATUS_FILE in file |
| `skills/revenium/SKILL.md` | HALT CHECK + Procedure rewritten; D-01 halt string | VERIFIED | grep budget-status.json = 0; Guardrail halt active x1; haltedRule x5 |
| `skills/revenium/references/config-schema.md` | guardrail-status.json schema section appended | VERIFIED | 107 lines; guardrail-status.json Schema H1 confirmed; haltedRule extension documented |
| `skills/revenium/plugins/revenium-classifier/classifier.py` | GUARDRAIL_STATUS_FILE + _guardrail_halted | VERIFIED | GUARDRAIL_STATUS_FILE at line 43; _guardrail_halted def + 2 call sites confirmed |
| `tests/test_repository.py` | 12 new behavioral stubs + 9 repoints; SC-7 gate | VERIFIED | 114 total tests; SC-7 gate (test_no_legacy_budget_status_references) passes |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `cron.sh:76` | `guardrail-check.sh` | `bash "${SKILL_DIR}/scripts/guardrail-check.sh" "$@" \|\| true` | WIRED | Confirmed by grep |
| `pre_llm_call.sh` | `GUARDRAIL_STATUS_FILE` | `GUARDRAIL_STATUS_FILE="${GUARDRAIL_STATUS_FILE}" python3 -c "..."` | WIRED | 4 refs |
| `pre_tool_call.sh` | `GUARDRAIL_STATUS_FILE` | Same pattern | WIRED | 4 refs |
| `clear-halt.sh` | `GUARDRAIL_STATUS_FILE` | `GUARDRAIL_STATUS_FILE_PY=... python3 - <<'PY'` | WIRED | Confirmed |
| `guardrail-check.sh` | `enforcement-rules get` | `revenium guardrails enforcement-rules get "${TEAM_ID}" --output json` | WIRED | Line 79 |
| `guardrail-check.sh` | `enforcement-events list` | `revenium guardrails enforcement-events list --rule-id ... --page-size 1` | WIRED | Line 269 (HALT_TRANSITION path) |
| `guardrail-check.sh` | `budget-status.json` cleanup | `rm -f "${STATE_DIR}/budget-status.json"` | WIRED | Lines 251-253 (idempotent) |
| `SKILL.md` HALT CHECK | `guardrail-status.json` | Agent reads file and reads `haltedRule` block | WIRED | Lines 32-40 |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `guardrail-check.sh` | `ENFORCEMENT_JSON` | `revenium guardrails enforcement-rules get` | Yes (real API in cron; mock in tests) | FLOWING |
| `guardrail-check.sh` | `guardrail-status.json` write | Python heredoc computes per-rule state from `ENFORCEMENT_JSON` + `RULE_IDS_JSON` | Yes | FLOWING |
| `pre_llm_call.sh` | `HALTED_AND_RULE` | `GUARDRAIL_STATUS_FILE` read via Python | Yes (reads file written by cron) | FLOWING |
| `pre_tool_call.sh` | `HALTED_AND_RULE` | Same | Yes | FLOWING |
| `clear-halt.sh` | JSON mutation | `GUARDRAIL_STATUS_FILE` read + per-rule state flip + `os.replace` write | Yes | FLOWING |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full test suite passes | `python3 -m unittest discover -s tests -p 'test_*.py'` | `Ran 114 tests in 39.4s OK` | PASS |
| budget-check.sh absent | `test ! -f skills/revenium/scripts/budget-check.sh` | exit 0 | PASS |
| SC-7 grep gate (code files, excl. cleanup carrier) | `grep -r 'budget-check\|budget-status' skills/ --include="*.sh" ... \| grep -v guardrail-check.sh` | 0 matches | PASS |
| cron.sh wired to guardrail-check.sh | `grep -c 'guardrail-check.sh' skills/revenium/scripts/cron.sh` | 1 | PASS |
| D-01 halt string present in pre_llm_call.sh | `grep -c 'Guardrail halt active' pre_llm_call.sh` | 1 | PASS |
| WARN_FLAGS_DIR in common.sh | `grep WARN_FLAGS_DIR skills/revenium/scripts/common.sh` | line 20 found | PASS |
| BUDGET_STATUS_FILE absent from common.sh | `grep BUDGET_STATUS_FILE skills/revenium/scripts/common.sh` | 0 matches | PASS |
| SKILL.md clean of budget-status.json | `grep -c budget-status.json skills/revenium/SKILL.md` | 0 | PASS |
| guardrail-check.sh bash syntax valid | `bash -n skills/revenium/scripts/guardrail-check.sh` | exit 0 | PASS |
| clear-halt.sh bash syntax valid | `bash -n skills/revenium/scripts/clear-halt.sh` | exit 0 | PASS |

---

## Requirements Coverage

| Requirement | Evidence | Status |
|-------------|----------|--------|
| **ENF-01**: `guardrail-check.sh` in cron, `budget-check.sh` deleted | `cron.sh:76`; `test_expected_files_exist` (guardrail-check.sh in expected list, budget-check.sh absent); `test_cron_sh_loops_per_REVENIUM_CRON_LOOP_COUNT` passes | SATISFIED |
| **ENF-02**: Walks `config.json::ruleIds` via `enforcement-rules get` | `guardrail-check.sh:60-79` Python reads `ruleIds` from `CONFIG_FILE`; calls `enforcement-rules get "${TEAM_ID}"` | SATISFIED |
| **ENF-03**: `guardrail-status.json` written; `budget-status.json` removed | `GUARDRAIL_STATUS_FILE` declared in `common.sh:35`; cleanup block at `guardrail-check.sh:251-253`; SC-7 gate passes | SATISFIED |
| **ENF-04**: Schema: 10-field `rules[]` + 6 top-level fields + optional `haltedRule` | `guardrail-check.sh:154-224`; `config-schema.md:59-107` documents schema; `test_guardrail_check_writes_status_file` asserts all fields | SATISFIED |
| **ENF-05**: New halt vs. carry-forward halt state machine | `guardrail-check.sh:178-228` prev_halted detection; `test_guardrail_check_halt_transition` + `test_guardrail_check_halt_carry_forward` | SATISFIED |
| **ENF-06**: `clear-halt.sh --rule-id <id>` + bare mode; no server mutation | `clear-halt.sh:15-95`; 3 ENF-06 tests pass; no `revenium` API calls in script | SATISFIED |
| **HOOK-01**: Hooks refuse on `halted:true`; halt UX preserved | `pre_llm_call.sh:118-145`; `pre_tool_call.sh:184-206`; D-01 string confirmed; both halt tests pass | SATISFIED |
| **HOOK-02**: Warn band: rate-limited stderr, sentinel marker, continue | `pre_llm_call.sh:46-115`; `pre_tool_call.sh:43-165`; sentinel at `WARN_FLAGS_DIR/<sid>__<ruleId>.flag`; 2 warn tests pass | SATISFIED |
| **HOOK-03**: `SKILL.md` updated to D-01 halt string; `guardrail-status.json` reads | `SKILL.md:24-67`; `test_prompt_ordering_invariant` passes; `Guardrail halt active` confirmed in SKILL.md | SATISFIED |
| **HOOK-04**: Hooks fail open on missing/corrupt status file | Both hooks: `except Exception: print('HALTED=false')`; `test_pre_llm_call_fail_open` passes | SATISFIED |
| **AUDIT-01**: `enforcement-events list` embedded in halt notification | `guardrail-check.sh:265-297`; `test_guardrail_check_halt_transition` passes with mock events; live path not exercised with real breach (see human verification) | SATISFIED (unit) / UNCERTAIN (live) |
| **AUDIT-02**: Graceful degradation on events API failure | `guardrail-check.sh:271-274` `__FAIL__` sentinel → `(unavailable)` literals; `test_guardrail_check_audit_api_fallback` passes | SATISFIED |

---

## Decision Verification (D-01, D-04, D-06, D-16)

| Decision | Status | Evidence |
|----------|--------|----------|
| **D-01**: Single-line halt string `"Guardrail halt active — rule '...' (..., ...) at ... of ... hard-limit. To resume: bash ~/.hermes/skills/revenium/scripts/clear-halt.sh"` | VERIFIED | `pre_llm_call.sh:137`; `pre_tool_call.sh:202`; `SKILL.md:36`; exact template matches D-01 spec |
| **D-04**: `haltedRule` pre-computed block in `guardrail-status.json` when `halted:true` | VERIFIED | `guardrail-check.sh:188-213` (first blocked rule in `ruleIds[]` order with 6 subfields); hooks read `haltedRule` without tiebreaker logic |
| **D-06**: `WARN_FLAGS_DIR` sentinel directory declared in `common.sh` as `${MARKERS_DIR}/.warn` | VERIFIED | `common.sh:20`: `WARN_FLAGS_DIR="${REVENIUM_WARN_FLAGS_DIR:-${MARKERS_DIR}/.warn}"`; comment includes literal `markers/.warn` for `assertIn` test |
| **D-16**: Halt-survivability runbook re-run deferred to Phase 20 DOCS-03 | VERIFIED as deferral | `halt-survivability.md` still contains v1.2 `budget-status.json` references (confirmed); `19-12-SUMMARY.md` explicitly defers to Phase 20 per D-16; the operative gate (`test_prompt_ordering_invariant` + live hook tests) is verified |

---

## SC-7 Gate

**SC-7 Claim**: `grep -r 'budget-check|budget-status' skills/` returns zero matches outside historical milestone docs.

**Actual result** (run locally 2026-05-22):
```
grep -r 'budget-check|budget-status' skills/ \
  --include="*.sh" --include="*.py" --include="*.yml" \
  --include="*.yaml" --include="*.json" \
  | grep -v guardrail-check.sh
=> 0 matches
```

`guardrail-check.sh` exclusion is correct: the 3 matching lines are `rm -f "${STATE_DIR}/budget-status.json"` (the intentional cleanup mechanism, not a legacy consumer). This exclusion is documented in `test_repository.py:138-141` with an explanatory comment.

**SC-7 status: MET** (with documented exclusion)

Note: `halt-survivability.md` contains 9+ legacy `budget-status.json` strings — these are excluded from the SC-7 grep scope (`.md` files excluded per the test design decision in 19-01-SUMMARY.md and ratified in 19-11-SUMMARY.md). This is the Phase 20 DOCS-03 backlog item.

---

## Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| `skills/revenium/references/halt-survivability.md` | 9+ `budget-status.json` / `Budget enforcement halt` references | INFO | Stale runbook; explicitly deferred per D-16 to Phase 20 DOCS-03. Not a Phase 19 defect. |
| `skills/revenium/references/troubleshooting.md:15,28` | `budget-status.json` references | INFO | Legacy troubleshooting doc; deferred to Phase 20 DOCS-02 cleanup. Not in SC-7 scope (.md excluded). |
| `skills/revenium/references/setup.md:55` | `budget-status.json::halted` reference | INFO | Legacy setup doc; deferred to Phase 20 DOCS-02. Not in SC-7 scope (.md excluded). |

No TBD/FIXME/XXX debt markers found in Phase 19 modified code files.

---

## Human Verification Required

### 1. Real Revenium guardrail breach — AUDIT-01 enforcement-event embedding

**Test:** On Mac Studio (`ssh 172.16.1.175`), set a test rule's `hardLimit` low enough that the next cron tick drives it into `block` state. Wait one cycle. Observe:
1. `guardrail-check.sh` emits `HALT_TRANSITION=true` in cron log
2. `guardrail-status.json` has `halted:true` + `haltedRule` populated
3. The Hermes messaging-toolset notification arrived with the enforcement-event `timestamp` and `summary` embedded (not `(unavailable)`)
4. After clearing (`bash clear-halt.sh`), the next hook call emits `{}` without waiting for cron

**Expected:** All four points confirmed. In particular AUDIT-01 requires `timestamp` and `summary` come from a real enforcement event (not the `(no events)` fallback). The field names `timestamp` and `summary` in the events API response must match what `guardrail-check.sh:276-292` parses.

**Why human:** The 19-12 live verification used synthetic `guardrail-status.json` fixtures (the real cron's `ruleIds` array was empty because the upstream `alertId` was deleted before Phase 18 migration — the server-side rule never existed on Mac Studio). `HALT_TRANSITION=false` on every live cron tick. The enforcement-events list API and its field-name contract (`timestamp`, `summary`) were NOT exercised against a real enforcement event.

---

## Gaps Summary

No gaps blocking goal achievement were found in the automated test suite or codebase. All 12 requirements have passing automated tests, all implementation artifacts are substantive and wired, and the SC-7 gate passes cleanly.

The `human_needed` status is solely because AUDIT-01's enforcement-event embedding path (the happy path where a real breach fires and the `enforcement-events list` API returns a real event) was not verified against the live Revenium API during Phase 19 close. The unit test covers this with a mock; the mock asserts on field names `timestamp` and `summary` that are LOW-confidence per the 19-VALIDATION.md (research could not observe a live enforcement event during development). If the API returns different field names in production, `guardrail-check.sh:276-292` would silently fall back to `(no events)` rather than `(unavailable)` — the notification would still fire but the embedded event body would be empty rather than the API-failure sentinel, making the degradation invisible.

---

_Verified: 2026-05-22T14:00:00Z_
_Verifier: Claude (gsd-verifier)_
