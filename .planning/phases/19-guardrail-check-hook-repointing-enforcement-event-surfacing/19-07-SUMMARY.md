---
phase: 19-guardrail-check-hook-repointing-enforcement-event-surfacing
plan: "07"
subsystem: hooks
tags: [bash, pre_llm_call, guardrails, halt-enforcement, warn-band, rate-limit, sentinel]

# Dependency graph
requires:
  - phase: 19-02
    provides: WARN_FLAGS_DIR path constant in common.sh
  - phase: 19-05
    provides: guardrail-status.json schema with haltedRule block (D-04)
provides:
  - pre_llm_call.sh with guardrail-native halt + warn-band enforcement
  - D-01 verbatim halt string injection via context key
  - Rate-limited warn stderr emit per (session, ruleId) sentinel scheme
  - Fail-open on missing/corrupt guardrail-status.json
affects:
  - 19-08 (pre_tool_call.sh analogous rewrite)
  - 19-09 (test wave validating both hooks)
  - Phase 20 (halt-survivability runbook re-run)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Multi-value KEY=value Python extraction for multi-field status reads (bash 3.2 compat)
    - Sentinel-file rate-limiting under WARN_FLAGS_DIR/.warn/<sid>__<ruleId>.flag
    - ruleId char-set validation ([A-Za-z0-9_-]) before flag path construction (T-19-07-04)
    - Path-traversal mitigation for session_id scan (T-19-07-05)

key-files:
  created: []
  modified:
    - skills/revenium/scripts/pre_llm_call.sh

key-decisions:
  - "Exemplar field-extraction bug: WARN_RULE=ruleId:name:... uses cut -d: -f1 | sed to extract ruleId, not cut -f2 as in the PATTERNS.md exemplar (f2 is name). Verified against test expectations."
  - "warn-band emit uses plain echo >&2 (D-05/Pitfall 3); malformed ruleId case uses common.sh::warn to LOG_FILE per design intent"
  - "cat - >/dev/null placed at line 21 (immediately after ensure_path + comment block) — first executable statement as required by Pitfall 1"

patterns-established:
  - "WARN_RULE line format: WARN_RULE=<ruleId>:<name>:<metricType>:<windowType>:<currentValue>:<hardLimit> — extract ruleId via cut -d: -f1 | sed 's/^WARN_RULE=//'"
  - "Multi-value Python extraction: one python3 invocation outputs KEY=value lines; bash side parses with sed -n 's/^KEY=//p'"

requirements-completed: [HOOK-01, HOOK-02, HOOK-03, HOOK-04]

# Metrics
duration: 17min
completed: 2026-05-21
---

# Phase 19 Plan 07: pre_llm_call.sh Guardrail Repoint Summary

**pre_llm_call.sh rewritten to enforce guardrail-status.json with D-01 verbatim halt string, per-(session,ruleId) rate-limited warn-band stderr, and fail-open on missing/corrupt status file**

## Performance

- **Duration:** ~17 min
- **Started:** 2026-05-21T19:00:00Z
- **Completed:** 2026-05-21T18:17:42Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Replaced BUDGET_STATUS_FILE reads with GUARDRAIL_STATUS_FILE + haltedRule block extraction in one Python call
- D-01 verbatim halt string emitted: `Guardrail halt active — rule 'X' (metricType, windowType) at N of M hard-limit. To resume: ...`
- Warn-band check iterates rules array for state='warn', emits one rate-limited stderr line per (session, ruleId)
- Sentinel files at WARN_FLAGS_DIR/<sid>__<ruleId>.flag with ruleId char-set validation (T-19-07-04) and session_id path-traversal mitigation (T-19-07-05)
- `cat - >/dev/null` preserved as first executable after ensure_path (Pitfall 1, T-19-07-02)
- All 5 required tests pass: fail_open, halted_emits_halt_string, halted_emits_guardrail_halt_string, warn_band_emits_stderr, warn_rate_limit

## Task Commits

1. **Task 1: Rewrite pre_llm_call.sh** - `85c2af7` (feat)

**Plan metadata:** (docs commit to follow from orchestrator)

## Files Created/Modified

- `skills/revenium/scripts/pre_llm_call.sh` — Rewritten with three behavioral branches: halt (inject D-01 directive), warn (stderr sentinel), ok (emit {})

## Decisions Made

- **PATTERNS.md exemplar field extraction bug corrected:** The exemplar at lines 587-592 uses `cut -d: -f2` for `rule_id` but the WARN_RULE format is `WARN_RULE=<ruleId>:<name>:...` so f2 is the name, not the ruleId. Corrected to `cut -d: -f1 | sed 's/^WARN_RULE=//'` to extract the actual ruleId. Verified against test assertions which check for `rule_id in flag_files`.
- **Malformed ruleId logging:** Uses `warn` helper (goes to LOG_FILE) deliberately for operator diagnostics; warn-band normal path uses plain `echo >&2` per D-05/Pitfall 3.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected WARN_RULE field extraction in warn-band loop**
- **Found during:** Task 1 (implementation review before writing)
- **Issue:** PATTERNS.md exemplar uses `cut -d: -f2` for `rule_id` but the WARN_RULE= prefix is on f1, making f2 the rule name. Test `test_pre_llm_call_warn_band_emits_stderr` checks `any(rule_id in f for f in flag_files)` which would fail with name in flag path.
- **Fix:** Extract ruleId via `cut -d: -f1 | sed 's/^WARN_RULE=//'` and shift remaining fields (name=f2, metricType=f3, windowType=f4, currentValue=f5, hardLimit=f6)
- **Files modified:** skills/revenium/scripts/pre_llm_call.sh
- **Verification:** test_pre_llm_call_warn_band_emits_stderr and test_pre_llm_call_warn_rate_limit both PASS
- **Committed in:** 85c2af7

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug in reference exemplar)
**Impact on plan:** Required correction for tests to pass. No scope creep.

## Issues Encountered

None — implementation proceeded cleanly once the exemplar field extraction issue was identified.

## Threat Flags

All T-19-07-01 through T-19-07-05 mitigations are implemented:
- T-19-07-01: try/except → HALTED=false fail-open (HOOK-04)
- T-19-07-02: cat - >/dev/null first after ensure_path (Pitfall 1)
- T-19-07-03: warn-band uses echo >&2, not common.sh::warn (D-05/Pitfall 3)
- T-19-07-04: ruleId validated against [A-Za-z0-9_-]+ before flag path
- T-19-07-05: session_id checked for '/' and '..' before use

T-19-07-06 (WARN_FLAGS_DIR disk fill) accepted per design.

## Next Phase Readiness

- pre_llm_call.sh is complete; pre_tool_call.sh analogous rewrite is 19-08
- 5/5 target tests green
- No budget-* references remain in pre_llm_call.sh

## Self-Check: PASSED

| Artifact | Status |
|----------|--------|
| skills/revenium/scripts/pre_llm_call.sh (146 lines, min 80) | FOUND |
| 19-07-SUMMARY.md | FOUND |
| Commit 85c2af7 | FOUND |
| GUARDRAIL_STATUS_FILE refs (≥1) | 4 |
| haltedRule refs (≥1) | 3 |
| WARN_FLAGS_DIR refs (≥2) | 2 |
| cat - >/dev/null (stdin drain) | 1 |
| budget-* references (must be 0) | 0 |
| All 5 hook tests | PASS |

---
*Phase: 19-guardrail-check-hook-repointing-enforcement-event-surfacing*
*Completed: 2026-05-21*
