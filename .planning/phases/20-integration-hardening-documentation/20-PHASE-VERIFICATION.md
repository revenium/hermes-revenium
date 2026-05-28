---
phase: 20-integration-hardening-documentation
verified: 2026-05-23T20:00:00Z
status: PASS_WITH_DEVIATIONS
score: 6/6 success criteria verified (SC-6 carries one documented known limitation)
known_limitations:
  - id: D-20-04-01
    sc: SC-6 Scenario 5 (AUDIT-01)
    description: >
      Live enforcement-event embedding with a real breach cannot be verified on the
      OpenClaw Demo tenant (shadowMode: true at tenant level; enforcement engine shows
      currentValue: 0 regardless of CLI metering calls). The (no events) fallback in
      guardrail-check.sh:280 is confirmed correct for empty-array API response. Field
      names timestamp and summary remain LOW-confidence (unit-tested with mocked data only).
    disposition: Carried to v1.4. Re-test on a production account with real subscriber spend.
    operator_accepted: true
---

# Phase 20: Integration Hardening & Documentation — Goal-Backward Verification Report

**Phase Goal (ROADMAP.md):** With the swap done, prove byte-identical backward compatibility
for the v1.0/v1.1/v1.2 metering surface (markers, agentic jobs, tool-events), grow the
behavioral test suite from 89 to at least 100 tests covering setup, migration, enforcement,
hook integration, and audit surfacing, and rewrite all user-facing prose so README, SKILL.md,
the migration guide, the halt-survivability runbook, and CLAUDE.md reflect the shipped
guardrails-native flow rather than the v1.2 alerts-budget flow.

**Verified:** 2026-05-23  
**Status:** PASS_WITH_DEVIATIONS  
**Re-verification:** No — initial goal-backward report (separate from 20-VERIFICATION.md which
is the live-host scenario transcript).

---

## Methodology

Goal-backward, not task-forward. Each success criterion was traced from the ROADMAP contract
backward to observable codebase evidence, then run as a live check on the dev checkout.
SUMMARY.md claims were treated as hypotheses, not evidence.

---

## Success Criteria Verdicts

### SC-1: Byte-identical wire contract for meter completion, jobs create, jobs outcome, meter tool-event

**Verdict: VERIFIED**

**Codebase evidence:**

Four golden JSON fixtures under `tests/fixtures/compat/`:

| Fixture | Verb | exact_match_fields | forbidden_fields |
|---------|------|--------------------|-----------------|
| meter-completion.golden.json | ["meter","completion"] | 21 fields | --budget-id, --alert-id |
| jobs-create.golden.json | ["jobs","create"] | 7 fields | --budget-id, --alert-id |
| jobs-outcome.golden.json | ["jobs","outcome"] | 6 fields | --budget-id, --alert-id |
| meter-tool-event.golden.json | ["meter","tool-event"] | 7 fields | --error-message, --budget-id, --alert-id |

All four parse as valid JSON and contain all required keys (`verb`, `exact_match_fields`,
`pattern_fields`, `forbidden_fields`).

Four compat test files exercise real `subprocess.run(['bash', ...])` invocations against
synthetic state.db + marker fixtures. All four pass:

```
python3 -m unittest tests.test_compat_meter_completion tests.test_compat_jobs_create \
    tests.test_compat_jobs_outcome tests.test_compat_meter_tool_event
Ran 4 tests in 2.357s — OK
```

The no-shift shim design (PATTERNS lines 202-226) is verified: `build_shim` writes a shim
body containing `guardrails) exit 0 ;;` and zero occurrences of `shift`. This means every
captured argv starts with the verb token (`meter`, `jobs`), and the `__verb`/`__subcommand`
slots in `argv_to_flags` are always populated — making verb-identity assertions in
`exact_match_fields` meaningful.

**Wiring:** `tests/test_repository.py::test_expected_files_exist` was extended at lines 101-104
to assert all four golden fixtures exist. The test passes.

---

### SC-2: Test suite >= 100 passing tests; new coverage includes compat + enforcement; legacy tests removed

**Verdict: VERIFIED**

```
python3 -m unittest discover -s tests -p 'test_*.py'
Ran 118 tests in 38.727s — OK
```

118 tests exceeds the SC-2 bar of 100 by 18. The four new COMPAT-01 tests account for the
jump from 114 to 118. `test_no_legacy_budget_status_references` (SC-7 test) passes, confirming
no surviving budget-check/budget-status test surface in the guarded file types.

`test_no_legacy_branding_left` (COMPAT-04) passes — rewritten prose introduced no forbidden
product names.

---

### SC-3: README.md references only guardrails-native flow; clean walkthrough succeeds on Mac Studio

**Verdict: VERIFIED**

Grep checks:
- `grep -c 'alerts budget' README.md` = 0 (no legacy alert-budget instructions)
- `grep -c 'budget-check' README.md` = 0
- `grep -c 'budget-status' README.md` = 0
- `grep -c 'setup-guardrails' README.md` = 4 (correct references to new script)
- `grep -c 'guardrail-status' README.md` > 0 (correct state file referenced)

README Quick Start references `setup-guardrails.sh --interactive`, `install-cron.sh`,
`install-hooks.sh`, and `guardrail-status.json` throughout. The Verification section
describes `crontab -l | grep hermes-revenium-metering` and `jq .ruleIds` checks.

Mac Studio walkthrough (Step 3 of 20-VERIFICATION.md): setup-guardrails.sh, install-cron.sh,
and install-hooks.sh all executed end-to-end in a sandboxed `HERMES_HOME` with exit 0.

Note: git clone was substituted with `cp -R` (no GitHub SSH key on Mac Studio) per the
documented plan fallback. Script execution steps are byte-identical to README instructions.

---

### SC-4: SKILL.md Setup Flow and Verification blocks describe guardrails commands; halt string preserved verbatim

**Verdict: VERIFIED**

Phase 19 D-12 HALT CHECK block (SKILL.md lines 24-95) preserved completely:
```
grep -c 'Guardrail halt active' skills/revenium/SKILL.md = 1
```

Halt string in SKILL.md:
```
Guardrail halt active — rule '[haltedRule.name]' ([haltedRule.metricType],
[haltedRule.windowType]) at [haltedRule.currentValue] of [haltedRule.hardLimit]
hard-limit. To resume: `bash ~/.hermes/skills/revenium/scripts/clear-halt.sh`
```

Setup Flow is a 5-step numbered list ending with hook approval step (step 5: "Approve hooks
on first `hermes chat`"), per D-08. Verification block leads with grep commands (`crontab -l`,
`grep hermes-revenium-hooks`, `grep post_tool_call`, `jq .ruleIds`) followed by wait-and-cat.

SKILL.md frontmatter invariant: `test_skill_frontmatter_has_hermes_metadata` passes — `name:
revenium`, `metadata.hermes` block, `category: devops` all present.

halt-survivability.md refreshed: uses `guardrail-status.json` throughout, contains no-re-run
note citing Phase 19 D-16, and shows v1.3 fixture schema with `haltedRule` block.

---

### SC-5: migration-guardrails.md and CLAUDE.md Architecture describe the shipped two-half guardrails-native model; orphan-cleanup documented

**Verdict: VERIFIED**

`docs/migration-guardrails.md` H2 ordering confirmed:
```
## Orphan Cleanup (Optional)        (line 98)
## What you'll see after a successful migration  (line 119)
## Loud-on-failure behavior         (line 166)
```

Orphan cleanup section: 4-step procedure + python3 one-liner to remove `alertId` key from
config.json. `grep -c "d.pop('alertId'" docs/migration-guardrails.md` = 1.

Post-migration walkthrough section: cron-log lines, `guardrail-status.json` sample with
`halted: false` and `rules: [{state: ok}]`, and embedded enforcement-event halt notification
example. `grep -c '"halted": false' docs/migration-guardrails.md` = 1.

Pitfall 4 SC-7 gate: `grep -c 'budget-status' docs/migration-guardrails.md` = 0.

CLAUDE.md Architecture block (lines 35-76, un-managed region):
- Line 39: "guardrail-check.sh" (not budget-check.sh)
- Line 39: "guardrail-status.json" (not budget-status.json)
- Line 43: "config.json and guardrail-status.json" named as the public interface
- Line 49: `GUARDRAIL_STATUS_FILE` in state separation table
- Lines 64-66: halt transitions describe guardrail-check.sh, `haltedRule`, enforcement-event embedding

CLAUDE.md lines 1-128 (un-managed region): `grep budget-check/budget-status` = 0 matches.

CLAUDE.md lines 133+ (GSD-managed block): references to `budget-check.sh` and
`budget-status.json` remain because the GSD-managed Technology Stack, Conventions, and
Architecture sections were explicitly out of scope (per plan D-06 "un-managed regions lines
5-76 only"). This is a documented intentional exclusion, not a regression.

---

### SC-6: Whole milestone verified live on Mac Studio (7 scenarios)

**Verdict: VERIFIED WITH KNOWN LIMITATION (D-20-04-01)**

Evidence source: `.planning/phases/20-integration-hardening-documentation/20-VERIFICATION.md`
(SSH-driven verification transcript, not SUMMARY.md narrative).

| # | Scenario | Verdict |
|---|----------|---------|
| 1 | Fresh install README walkthrough | PASS |
| 2 | Legacy-alertId upgrade install | PASS |
| 3 | Warn band (HOOK-02, ENF-04) | PASS |
| 4 | Block band — verbatim D-01 halt string | PASS |
| 5 | Halt with embedded enforcement event (AUDIT-01) | PARTIAL — D-20-04-01 |
| 6 | Hook fail-open on missing/corrupt status file | PASS |
| 7 | clear-halt bare + --rule-id | PASS |

Mac Studio state post-verification: `halted: false`, rule `4vK3Zv` active, no synthetic
halt, sandbox rule Ol3xj5 deleted.

**Scenario #5 PARTIAL is NOT a hidden regression.** It is the same AUDIT-01 gate that was
deferred at Phase 19 close (see Phase 19 VERIFICATION.md: "human_needed — AUDIT-01"). The
technical root cause is a tenant-level shadowMode constraint on the OpenClaw Demo account,
not a code defect. The `(no events)` fallback at guardrail-check.sh:280 is correct behavior
for an empty-array API response. The enforcement-events code path (lines 269-288) is live
and reachable. Field names (`timestamp`, `summary`) are unit-tested with mock data.

118/118 tests pass on Mac Studio Python 3.13.2 + bash 3.2.57.

---

## Requirements Coverage

| Req | Description | SC | Verdict |
|-----|-------------|-----|---------|
| COMPAT-01 | Byte-identical argv shapes for 4 verbs | SC-1 | SATISFIED |
| COMPAT-02 | Test suite >= 100 tests | SC-2 | SATISFIED (118 tests) |
| COMPAT-04 | test_no_legacy_branding_left still passes | SC-2 | SATISFIED |
| DOCS-01 | README guardrails-native; walkthrough succeeds on Mac Studio | SC-3 | SATISFIED |
| DOCS-02 | SKILL.md Setup Flow + halt string preserved | SC-4 | SATISFIED |
| DOCS-03 | halt-survivability.md prose refreshed | SC-4 | SATISFIED |
| DOCS-04 | docs/migration-guardrails.md Orphan Cleanup section | SC-5 | SATISFIED |
| DOCS-05 | CLAUDE.md Architecture/two-halves rewritten | SC-5 | SATISFIED |

---

## Anti-Patterns Found

### guardrail-check.sh references budget-status.json (lines 251-253)

**Severity: INFO (not a blocker)**

```bash
if [[ -f "${STATE_DIR}/budget-status.json" ]]; then
  rm -f "${STATE_DIR}/budget-status.json"
  info "Cleaned up legacy budget-status.json (Phase 19 clean break)"
fi
```

This is a migration cleanup routine that removes the legacy file. It does NOT document
`budget-status.json` as an active feature — it removes it. This is Phase 19 intentional
design (clean break on first successful guardrail-check.sh write) and is correctly covered
by the test `test_no_legacy_budget_status_references` which excludes `guardrail-check.sh`
from its scope precisely because this cleanup code is expected.

### CLAUDE.md GSD-managed block (lines 133+) contains budget-check.sh / budget-status.json references

**Severity: WARNING (intentional exclusion, not a regression)**

The GSD-managed block (lines 78+) is auto-generated from PROJECT.md, Technology Stack, and
Architecture sections. Plan 20-02 explicitly scoped edits to lines 5-76 only (D-06: "CLAUDE.md
edits confined to lines 5-76 (un-managed regions)"). The references in lines 133+ describe
v1.2 history and are stale, but updating them was out of scope for this milestone. This
should be addressed in v1.4 when the GSD-managed block is regenerated.

---

## Known Limitations Ledger

| ID | Area | Severity | Description | Disposition |
|----|------|----------|-------------|-------------|
| D-20-04-01 | AUDIT-01 enforcement-event embedding | MEDIUM | Demo account shadowMode prevents real breach; (no events) fallback confirmed correct; field names (timestamp, summary) unit-tested only with mocked data | Carried to v1.4 — re-test on production account with real subscriber spend |

---

## Invariant Tests: All Pass

| Test | Result |
|------|--------|
| test_skill_frontmatter_has_hermes_metadata | OK |
| test_runtime_paths_are_hermes_native | OK |
| test_shell_scripts_have_valid_syntax | OK |
| test_expected_files_exist | OK |
| test_no_legacy_branding_left | OK |
| test_no_legacy_budget_status_references | OK |
| Full suite (118 tests) | OK |

---

## Recommendation

**CLOSE the phase and milestone v1.3.**

All six success criteria are verified against actual codebase artifacts and live test runs.
The one deviation (SC-6 Scenario #5 PARTIAL on AUDIT-01) is an operator-accepted infrastructure
constraint, identical in nature and scope to the Phase 19 AUDIT-01 deferral. It is documented,
traceable, and non-regressive. The `(no events)` fallback is correct behavior.

The GSD-managed CLAUDE.md block (lines 133+) carries stale v1.2 references — flag for v1.4
cleanup when the managed block is regenerated.

---

_Verified: 2026-05-23_
_Verifier: Claude (gsd-verifier) — goal-backward, codebase evidence only_
