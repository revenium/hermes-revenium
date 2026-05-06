---
name: revenium
description: Hermes-native Revenium integration for budget enforcement and usage metering. Reads local budget state before costly work, ships Hermes session usage to Revenium, and can halt autonomous operation when spend exceeds a configured threshold.
version: 1.0.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [revenium, budgets, finops, metering, observability]
    category: devops
---

# Revenium

## When to Use

Use this skill when you want Hermes to:

- enforce a spending budget before costly operations
- meter usage from `~/.hermes/state.db` into Revenium
- maintain a local budget status file for low-latency checks
- halt autonomous execution when spend exceeds a threshold
- deliver budget halt notifications through Hermes messaging

## Runtime State

This skill stores mutable runtime state in:

- `~/.hermes/state/revenium/config.json`
- `~/.hermes/state/revenium/budget-status.json`
- `~/.hermes/state/revenium/revenium-hermes.ledger`
- `~/.hermes/state/revenium/revenium-metering.log`

Bundled scripts live at `${HERMES_SKILL_DIR}/scripts/`.

## Mandatory Budget Check

Before any expensive operation or unnecessary exploration:

1. Read `~/.hermes/state/revenium/budget-status.json`.
2. Inspect `halted`, `exceeded`, `currentValue`, `threshold`, and `lastChecked`.

### If `halted` is `true`

Your entire response must be exactly:

> Budget enforcement halt is active. $[currentValue] of $[threshold] used ([percentUsed]%). To resume: `bash ~/.hermes/skills/revenium/scripts/clear-halt.sh`

No extra text. No extra tool calls.

### If `exceeded` is `false`

Proceed silently.

### If `exceeded` is `true` and `halted` is `false`

Read `~/.hermes/state/revenium/config.json`:

- if `autonomousMode` is `false` or missing, stop and ask the user whether to continue anyway
- if `autonomousMode` is `true`, the halt was explicitly cleared and you may proceed

### If the budget file is missing

Say:

> Budget status unavailable. Proceeding with caution.

Then continue.

## Setup Procedure

If `~/.hermes/state/revenium/config.json` does not exist:

1. Verify the Revenium CLI is configured:
   ```bash
   revenium config show
   ```
2. Ask for:
   - optional organization name
   - budget threshold
   - budget period (`DAILY`, `WEEKLY`, `MONTHLY`, `QUARTERLY`)
   - whether autonomous mode should halt and notify
   - if autonomous: notification channel + target
3. Create the Revenium budget alert.
4. Write `~/.hermes/state/revenium/config.json`.
5. Install the cron job:
   ```bash
   bash ~/.hermes/skills/revenium/scripts/install-cron.sh
   ```

If setup fails, stop and explain the failure.

## `/revenium` Command Behavior

When the user invokes `/revenium`:

1. Show budget status from Revenium using the configured alert ID.
2. Show autonomous mode and current halt state.
3. Offer:
   - `reset` → recreate the alert with the same settings
   - `reconfigure` → delete and recreate with new settings
   - `done`

## Script Entry Points

- Install cron:
  ```bash
  bash ~/.hermes/skills/revenium/scripts/install-cron.sh
  ```
- Run metering once:
  ```bash
  bash ~/.hermes/skills/revenium/scripts/cron.sh
  ```
- Clear halt:
  ```bash
  bash ~/.hermes/skills/revenium/scripts/clear-halt.sh
  ```

## References

- `references/setup.md` — setup, reset, and reconfigure flows
- `references/troubleshooting.md` — failure modes and operator fixes

## Verification

- `bash ~/.hermes/skills/revenium/scripts/install-cron.sh` succeeds
- `bash ~/.hermes/skills/revenium/scripts/cron.sh` updates `~/.hermes/state/revenium/`
- Revenium receives transactions from `~/.hermes/state.db`
- when over budget, `budget-status.json` flips to `halted: true` and Hermes sends the alert
