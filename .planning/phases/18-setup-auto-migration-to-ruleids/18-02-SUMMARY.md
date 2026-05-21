---
phase: 18-setup-auto-migration-to-ruleids
plan: "02"
subsystem: setup-guardrails
tags: [setup-guardrails.sh, rule-creation, migration, interactive, flock, idempotency, bash-3.2]
dependency_graph:
  requires:
    - 18-01 (MIGRATION_NOTIFY_FILE declaration in common.sh; behavioral test stubs)
  provides:
    - skills/revenium/scripts/setup-guardrails.sh: single rule-creation entry point (D-01)
    - run_default(): create rule from CLI args
    - run_interactive(): operator-driven setup with TAXONOMY_FILE picker and re-run gate
    - run_migration(): cron auto-migration from legacy alertId preserving enforcement posture
  affects:
    - skills/revenium/scripts/setup-guardrails.sh
tech_stack:
  added: []
  patterns:
    - env-passing Python heredoc (bash 3.2 compat, no ${var@Q})
    - RULES_LOCK_FILE flock on fd 9 (mirrors cron.sh:19-29)
    - atomic temp-then-rename config.json write (tempfile.NamedTemporaryFile + os.rename)
    - notify-once gate via hashlib.sha256 hash in MIGRATION_NOTIFY_FILE (D-10)
    - array-built CLI argv with conditional --shadow-mode append (D-04)
key_files:
  created:
    - skills/revenium/scripts/setup-guardrails.sh
  modified: []
decisions:
  - "single create_rule() call site for revenium guardrails budget-rules create (D-01)"
  - "Interactive re-run UX is [r]ecreate / [c]ancel only — no [u]pdate (D-15 amended, Pitfall 4: update only accepts --name)"
  - "Migration uses alerts budget list --output json filtered by alertId — never alerts budget get (Pitfall 1: get missing cumulativePeriod)"
  - "alertId is never written or deleted by this script (SETUP-03 + D-09)"
  - "REVENIUM_MIGRATE_SHADOW_MODE env var forces shadow-mode in migration without requiring --shadow-mode CLI flag (D-11)"
  - "All Python heredocs use single-quoted <<'PY' and env-passing for all inbound values (T-18-INJECTION mitigation)"
  - "Alert name from alerts budget list truncated to 64 chars before logging (T-18-LOG-INJECT)"
  - "create_rule stderr truncated to 200 chars before logging via error() (T-18-LOG-INJECT)"
  - "Script is 863 lines; exceeds 600-line suggestion but is kept inline per planner's discretion note in plan (install-hooks.sh analog)"
metrics:
  duration: "~10 minutes"
  completed: "2026-05-21"
  tasks: 3
  files: 1
requirements: [SETUP-01, SETUP-02, SETUP-03, SETUP-04, SETUP-05, MIGR-01, MIGR-02, MIGR-03, MIGR-04, MIGR-05]
---

# Phase 18 Plan 02: setup-guardrails.sh — Single Rule-Creation Entry Point

Created `skills/revenium/scripts/setup-guardrails.sh` — the single `revenium guardrails budget-rules create` entry point (D-01) for the v1.3 guardrails-native budget enforcement path. Three modes: default (CLI args), --interactive (SKILL.md Setup Flow), --from-alert --auto (cron migration).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Scaffold setup-guardrails.sh with bootstrap, arg parsing, and has_guardrails_cli precheck | ae54349 | skills/revenium/scripts/setup-guardrails.sh |
| 2 | Implement flock + ruleIds pre-check + base rule creation + atomic config.json write-back | a8618af | skills/revenium/scripts/setup-guardrails.sh |
| 3 | Wire the three mode entry points (default / --interactive / --from-alert --auto) | bf45318 | skills/revenium/scripts/setup-guardrails.sh |

## Script Architecture

**Final line count:** 863 lines

**Mode entry-point functions:**
- `run_default()` — lines 447-483
- `run_interactive()` — lines 484-747
- `run_migration()` — lines 748-857
- Mode dispatch `case "${MODE}"` — line 858

**Single create call site (D-01):** `revenium guardrails budget-rules create` — line 249 inside `create_rule()`

**D-01 verification:** `grep -r "guardrails budget-rules create" skills/revenium/ | wc -l` == 1 (confirmed)

## Decision Coverage

| Decision ID | Implementation | Location |
|-------------|---------------|----------|
| D-01 | `create_rule()` is the single call site for budget-rules create | Line 249 |
| D-02 | Three modes: default, --interactive, --from-alert --auto | Lines 447, 484, 748 |
| D-04 | `--shadow-mode` flag appended via `cmd+=(--shadow-mode)` | Line 268 |
| D-07 | RULES_LOCK_FILE flock on fd 9 (exec 9>); TOCTOU re-check after acquire | Lines 214-234 |
| D-08 | SHADOW_MODE defaults to "false"; migration enforces immediately unless overridden | Lines 46, 748-751 |
| D-09 | Deleted-alert: error+notify-once+exit 0; config.json untouched | Lines 798-804 |
| D-10 | `migration_notify_once()` with hashlib.sha256 hash in MIGRATION_NOTIFY_FILE | Lines 387-416 |
| D-11 | `REVENIUM_MIGRATE_SHADOW_MODE` env override for shadow-on-migration | Lines 749-751 |
| D-12 | Numbered task-type picker from TAXONOMY_FILE labels | Lines 574-618 |
| D-13 | Each task-type rule prompts for its own hard-limit; warn=80% | Lines 619-647 |
| D-14 | Empty/missing TAXONOMY_FILE → silent skip; base rule only | Lines 573-574 |
| D-15 | Re-run UX: [r]ecreate / [c]ancel only (no [u]pdate — Pitfall 4) | Lines 512-551 |

## Key Behaviors

### Default Mode
Validates `--hard-limit` (regex `^[0-9]+(\.[0-9]+)?$`) and `--period` (DAILY/WEEKLY/MONTHLY/QUARTERLY) before constructing create argv. Computes `warn = 0.8 × hard`. Creates one base rule named "Hermes {Period} Budget". Writes `ruleIds: [<id>]` atomically. Fails loudly (exit 1) on create failure.

### Interactive Mode
Prompts for all 6 fields with up to 3 re-tries on invalid input. Re-run gate shows existing rules and offers [r]ecreate (deletes via `budget-rules delete <id> --yes` then recreates) or [c]ancel. Optional numbered taxonomy picker creates per-task rules with independent limits. Writes all config fields via `write_rule_ids_and_config()`.

### Migration Mode (--from-alert --auto)
Reads legacy alert using `alerts budget list --output json` filtered by alertId (not `alerts budget get` — Pitfall 1: `get` lacks `cumulativePeriod`). D-09: if alertId not in list, logs error + notify-once + exits 0. Validates threshold (numeric) and period (enum). Creates equivalent TOTAL_COST BLOCK rule. Writes `ruleIds: [<new-id>]` preserving `alertId` orphan (SETUP-03 + D-09). Emits one-time `deprecation: legacy alertId <id> orphaned, migrated to ruleId <new>` info line (MIGR-03). Exits 0 on all failure paths so cron pipeline continues.

## Idempotency Design

1. Pre-check: `read_config_field ruleIds` → `nonempty` → exit 0 silently (auto) or enter re-run gate (interactive)
2. Flock: `exec 9>"${RULES_LOCK_FILE}"` + Python `fcntl.flock(9, LOCK_EX|LOCK_NB)` guards the window
3. TOCTOU re-check: after acquiring flock, re-reads ruleIds in case a concurrent process completed first

## Security Controls Applied

| Threat ID | Control |
|-----------|---------|
| T-18-INJECTION | All Python heredocs use `<<'PY'` (verbatim body); all inbound values pass via `KEY="${VAR}" python3 - <<'PY'` env-passing pattern |
| T-18-INPUT-VALID | `validate_hard_limit()` regex-checks before create argv; `validate_period()` enum-checks; interactive re-prompts up to 3 times |
| T-18-LOG-INJECT | Alert `name` truncated to 64 chars; create stderr truncated to 200 chars; log writes via `info`/`warn`/`error` helpers |

## Bash 3.2 Compatibility

- No `${var@Q}` operator (fails on bash 3.2; use env-passing heredoc instead)
- No `declare -A` associative arrays (fails on bash 3.2; use Python or indexed arrays)
- Verified: `grep -c "@Q" ... == 0`, `grep -c "declare -A" ... == 0`

## Test Gate Status After This Plan

| Test | Status |
|------|--------|
| `test_shell_scripts_have_valid_syntax` | PASS |
| `test_no_legacy_branding_left` | PASS |
| `test_expected_files_exist` | FAIL only on `docs/migration-guardrails.md` (plan 18-05) |
| `test_setup_guardrails_migration_happy_path` | PASS at stub level (script exists) |
| `test_setup_guardrails_idempotency` | PASS at stub level (script exists) |
| `test_setup_guardrails_missing_alert_edge_case` | PASS at stub level (script exists) |

Full behavioral test fixtures (tmpdir + fake-revenium) land in plan 18-06.

## Downstream Pointers

- **Plan 18-03:** Wires `cron.sh` to invoke `setup-guardrails.sh --from-alert ... --auto || true` as the first loop stage (D-06). Uses inline alertId read (Pitfall 5 mitigation).
- **Plan 18-04:** Rewrites SKILL.md Setup Flow to invoke `setup-guardrails.sh --interactive` (D-05). Agent never writes rule IDs.
- **Plan 18-05:** Creates `docs/migration-guardrails.md` operator doc (D-16) — turns the remaining `test_expected_files_exist` failure green.
- **Plan 18-06:** Replaces behavioral test stubs with full `tmpdir + fake-revenium` fixtures (MIGR-01..06 full coverage).

## Deviations from Plan

None — plan executed exactly as written, with one note:

**Script length:** 863 lines vs the 350-500 line target (600 line warning threshold). The interactive mode's taxonomy picker and re-run gate, combined with the complete migration mode, required the additional lines. Per the plan's own discretion note ("if it grows beyond 600, planner should re-evaluate — for THIS plan, keep inline"), the choice was made to keep all logic in one file matching the install-hooks.sh precedent.

## Known Stubs

None. All behavior is wired. The Wave 0 behavioral tests pass at the script-existence stub level; full behavioral verification (fake CLI + tmpdir) arrives in plan 18-06.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes introduced. `setup-guardrails.sh` reads `config.json` (pre-existing trust boundary) and calls the `revenium` CLI (pre-existing external dependency). All new surfaces match the threat model documented in the plan's `<threat_model>` section.

## Self-Check: PASSED

- FOUND: skills/revenium/scripts/setup-guardrails.sh (863 lines, executable)
- FOUND: commit ae54349 (Task 1 — scaffold)
- FOUND: commit a8618af (Task 2 — helpers)
- FOUND: commit bf45318 (Task 3 — mode entry points)
- CONFIRMED: `grep -r "guardrails budget-rules create" skills/revenium/ | wc -l` == 1 (D-01)
- CONFIRMED: `grep -c "@Q"` == 0 (bash 3.2 compat)
- CONFIRMED: `grep -c "declare -A"` == 0 (bash 3.2 compat)
- CONFIRMED: `grep -c "alerts budget get"` == 0 (Pitfall 1)
- CONFIRMED: `grep -c "budget-rules update"` == 0 (Pitfall 4)
- CONFIRMED: `grep -c "config\['alertId'\]"` == 0 (SETUP-03 + D-09)
- CONFIRMED: test suite reports 99 PASS / 1 FAIL (docs/migration-guardrails.md — plan 18-05)
