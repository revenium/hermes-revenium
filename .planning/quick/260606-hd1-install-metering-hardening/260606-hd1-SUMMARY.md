---
quick_id: 260606-hd1
title: Install & metering hardening
status: complete
date: 2026-06-06
one_liner: 14 merged PRs (#9–#22) — agentic-job reliability, one-command installer, and install/metering UX fixes, verified on live hosts.
prs: [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]
---

# Install & metering hardening — 2026-06-06

Retroactive record of a day of operational fixes shipped as direct PRs (not via a
planned GSD phase). All merged to `main` (final tip `3a553f0`) and verified
end-to-end on live Hermes sandbox hosts (`52.91.177.177`, `54.144.4.54`,
`3.81.151.214`). 135 repo tests passing throughout.

## Agentic-job metering reliability
- **#9** `--metadata` on `revenium jobs outcome` — ships `source` on every outcome
  and a `failure_reason` (classifier-inferred) on `FAILED` arcs.
- **#10** Root-cause fix for jobs not recording: `revenium jobs create` requires a
  `teamId`; a key-only config returned HTTP 400/exit 4, which the cron's 409-only
  success check treated as failure → `JOB:created` never ledgered → outcome
  deferred forever (`hasOutcome:false`). Added `resolve_team_id()` (env →
  `revenium config show`), explicit `--team-id` on job calls, a loud warn when
  unresolved, and fixed the SKILL.md setup gate to require all four creds.
- **#13** Stop the spurious `--from-alert requires an alertId` ERROR logged every
  cron tick on guardrails-native installs (looked like metering had stopped; it
  hadn't).
- **#14** Lower metering settle window 120s → 45s so in-progress sessions meter
  ~2.5× sooner (ended sessions already meter in ~12s via the sentinel).

## One-command install
- **#11** New `install.sh` orchestrator: preflight → verify+persist all four creds
  → plugin → hooks → guardrail rule → cron → gateway restart; idempotent.
- **#12** README rewritten around the one-command install.
- **#15** `setup-local.sh` footer pointed at the installer instead of stale manual
  steps.
- **#16** Dropped the interactive per-task-type budget-rule picker (base rule
  already enforces all task types).
- **#17** `setup-local.sh` now `exec`s `install.sh` — a single command does copy +
  full wiring.
- **#18** Unpinned the README clone from `v1.3.1` → default branch.
- **#19** Moved `examples/setup-local.sh` → repo-root `install.sh` (it had become
  the primary install entry point).
- **#21** `install.sh --reconfigure` to re-prompt for creds (fixes a wrong/
  truncated API key, which surfaces as HTTP 403 on rule creation).

## Cross-cutting fixes found via live testing
- **#20** `ensure_path` must `return 0` — its exit status was the last loop
  iteration's, which is non-zero when `~/.local/bin` is absent; under
  `set -euo pipefail` callers this aborted sub-scripts SILENTLY (symptom:
  "Plugin install failed" with zero output on a fresh host).
- **#22** Removed SKILL.md `required_environment_variables` — it made Hermes prompt
  "Skill Setup Required" for `REVENIUM_API_KEY` etc. on skill load, though the
  scripts read creds from the `revenium` CLI config, not env vars.

## Known follow-ups (not done)
- No new release tag cut; README install now tracks the default branch.
- `.planning/` lacks `STATE.md`/`ROADMAP.md`; `/gsd-progress` still reports
  "between milestones." Folding this work + the Task-Type Metering milestone into
  a proper roadmap is the natural next planning step.
- Live hosts run scripts deployed via `scp` during debugging; they match `main`.
