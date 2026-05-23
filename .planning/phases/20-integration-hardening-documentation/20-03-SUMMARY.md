---
phase: 20-integration-hardening-documentation
plan: "03"
subsystem: docs/migration
tags: [docs, migration-guardrails, orphan-cleanup, walkthrough, DOCS-04]
dependency_graph:
  requires:
    - phase: 18-setup-auto-migration-to-ruleids
      provides: docs/migration-guardrails.md base file (MIGR-06)
    - phase: 19-guardrail-check-hook-repointing-enforcement-event-surfacing
      provides: enforcement-event-embedded halt notification + guardrail-status.json shape (referenced in examples)
  provides:
    - "## Orphan Cleanup (Optional) H2 documenting the 4-step manual cleanup of the legacy alertId"
    - "## What you'll see after a successful migration H2 with cron-log lines, guardrail-status.json sample, and embedded-event halt notification example"
    - DOCS-04 + roadmap SC #5 met (migration documented end-to-end including orphan-cleanup)
  affects: []
tech_stack:
  added: []
  patterns:
    - "Documentation-only H2 insertion between existing H2s — no new shipping artifact (D-11)"
    - "Pitfall 4 SC-7 grep gate: legacy `budget-status` literal kept at zero count via paraphrase"
key_files:
  created: []
  modified:
    - docs/migration-guardrails.md
decisions:
  - "D-09 4-step orphan cleanup procedure inserted verbatim from RESEARCH spec"
  - "D-10 walkthrough uses RESEARCH Examples 7/8/9 verbatim, except Example 8's cron-log line is PARAPHRASED ('Cleaned up legacy status file' instead of 'Cleaned up legacy budget-status.json') to honor Pitfall 4 SC-7 grep gate"
  - "D-11 honored: no new script, no new test surface; python3 one-liner documented inline only"
patterns_established:
  - "H2 insertion contract: line-anchored between two existing H2s; surrounding content unchanged"
metrics:
  duration: "~5 minutes"
  completed: "2026-05-23"
  tasks: 3
  files: 1
requirements: [DOCS-04]
---

# Phase 20 Plan 03: Migration Guide Finalization — Orphan Cleanup + Post-Migration Walkthrough

Inserted two new H2 sections into `docs/migration-guardrails.md` between the existing `## We preserve your enforcement posture` (line 62) and `## Loud-on-failure behavior` (now line 166): a 4-step `## Orphan Cleanup (Optional)` section that closes the D-09 gap, and a `## What you'll see after a successful migration` walkthrough with cron-log lines, `guardrail-status.json` shape, and an embedded-enforcement-event halt notification example that closes the D-10 gap.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Insert `## Orphan Cleanup (Optional)` H2 (D-09 4-step) | `edf910a` | docs/migration-guardrails.md |
| 2 | Insert `## What you'll see after a successful migration` H2 (D-10, with cron-log line paraphrased per Pitfall 4) | `80c3e07` | docs/migration-guardrails.md |
| 3 | Plan-wide acceptance — verifications only, no edits | (this commit) | — |

## Key Changes

### docs/migration-guardrails.md — Orphan Cleanup section (Task 1)

A 4-step numbered list documenting the *manual* cleanup of the legacy `alertId` after the cron auto-migration completes:

1. Verify the new ruleId is enforcing.
2. Confirm enforcement is live (the halt notification on a real breach).
3. Delete the legacy alert in the Revenium UI.
4. Optionally remove the `alertId` key from `config.json` via the D-11 python3 one-liner:

   ```bash
   python3 -c "import json, pathlib; p = pathlib.Path('~/.hermes/state/revenium/config.json').expanduser(); d = json.loads(p.read_text()); d.pop('alertId', None); p.write_text(json.dumps(d, indent=2) + '\n')"
   ```

Per D-11 this section is documentation only — no new shipping artifact, no new script, no new test surface.

### docs/migration-guardrails.md — Post-Migration Walkthrough section (Task 2)

A `## What you'll see after a successful migration` H2 showing:

- Example first-cron-tick log lines (Example 8, with the literal `budget-status.json` PARAPHRASED to "legacy status file" to honor the Pitfall 4 SC-7 grep gate).
- Example `guardrail-status.json` shape with one rule in `ok` state, `halted: false`, no `haltedRule` / `haltedAt` keys (Example 9).
- Example halt notification with embedded enforcement event (Example 7) — `"Guardrail halt active — rule 'Engineering Budget' (TOTAL_COST, MONTHLY) at 102.5 of 100.0 hard-limit. To resume: bash ~/.hermes/skills/revenium/scripts/clear-halt.sh | Event: [2026-05-22T14:03:38.478Z] Rule 'Engineering Budget' blocked 1 request: TOTAL_COST $102.50 exceeded hard limit $100.00"`

## Acceptance Gates (Task 3 verifications)

All four gates passed against the file as committed in `80c3e07`:

| Gate | Check | Result |
|------|-------|--------|
| H2 ordering | `grep -n '^## ' docs/migration-guardrails.md` returns `Orphan Cleanup` before `What you'll see` before `Loud-on-failure behavior` | ✓ lines 98 → 119 → 166 |
| Pitfall 4 SC-7 | `grep -c 'budget-status' docs/migration-guardrails.md` returns `0` | ✓ 0 |
| Halt-string presence | `grep -c "Guardrail halt active" docs/migration-guardrails.md` returns ≥1 | ✓ 1 |
| guardrail-status.json shape | `grep -c '"halted": false' docs/migration-guardrails.md` returns ≥1 | ✓ 1 |
| D-11 python3 one-liner | `grep -c "d.pop('alertId'" docs/migration-guardrails.md` returns ≥1 | ✓ 1 |
| Full test suite | `python3 -m unittest discover -s tests -p 'test_*.py'` | ✓ 114 tests OK |

## Deviations from Plan

None — plan executed exactly as written, including the deliberate Pitfall 4 paraphrase of Example 8.

## Threat Surface Scan

Doc-only edit. No new file paths, no new script entry points, no new network calls. T-20-C-04 (`budget-status` regression risk) is mitigated by the Pitfall 4 SC-7 grep gate documented in Task 3 — future edits that reintroduce the literal will fail this gate.

## Self-Check: PASSED

- FOUND: docs/migration-guardrails.md (+68 lines, two new H2 sections; original content unchanged)
- FOUND: commit `edf910a` (Task 1 — Orphan Cleanup H2)
- FOUND: commit `80c3e07` (Task 2 — What you'll see H2)
- VERIFIED: H2 order Orphan Cleanup (98) → What you'll see (119) → Loud-on-failure behavior (166)
- VERIFIED: `grep -c 'budget-status' docs/migration-guardrails.md` returns 0 (Pitfall 4 SC-7 gate)
- VERIFIED: full test suite 114/114 passing in worktree (no regressions; 20-01 adds the +4 to reach 118)
