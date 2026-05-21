# config.json Schema

## Overview

`config.json` is the runtime configuration file for the Revenium skill. It is written
during setup and read by the cron pipeline on every tick. Location:
`~/.hermes/state/revenium/config.json` (declared as `CONFIG_FILE` in `common.sh`).
The file is the sole coupling point between the setup flow and the cron pipeline; its
schema is the public interface between those two halves.

## Fields

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `ruleIds` | array of strings | Active (v1.3) | IDs of Revenium guardrail rules to enforce. Written by `/revenium setup` (Phase 18); consumed by `guardrail-check.sh` (Phase 19). |
| `alertId` | string | Deprecated (v1.2) — orphaned by auto-migration; legacy alert preserved server-side; clean up manually in Revenium UI | Legacy budget-alert ID from v1.2 and earlier. No longer written or read by v1.3+ scripts; preserved in `config.json` after migration. |
| `autonomousMode` | boolean | Active | When `true`, a budget breach automatically halts the agent and triggers a notification. |
| `notifyChannel` | string | Active (required when `autonomousMode` is `true`) | Messaging channel for halt notifications (e.g., `slack`, `discord`). |
| `notifyTarget` | string | Active (required when `autonomousMode` is `true`) | Channel-specific target for halt notifications (e.g., `channel:<id>`, `user:<id>`, `@username`). |
| `organizationName` | string | Active (optional) | Used as `--organization-name` on metered transactions for Revenium attribution. |

## ruleIds

`ruleIds` is the active v1.3 replacement for the legacy `alertId` field. It holds an
array of Revenium guardrail rule IDs that the skill enforces on every cron tick. An
empty array or absent key means no guardrail rules are active; the cron pipeline
treats this as a no-op for enforcement and continues metering normally.

## alertId (Deprecated v1.2)

`alertId` was the budget-alert identifier used by v1.2 and earlier. It is orphaned by
the v1.3 auto-migration: the migration writes `ruleIds` and no longer touches `alertId`.
The corresponding budget alert is preserved server-side on Revenium and is never
auto-deleted; operators who no longer need it should clean it up manually in the
Revenium UI.

## autonomousMode

When `autonomousMode` is `true`, a budget breach detected by the cron pipeline
automatically sets `halted: true` in the guardrail status file and triggers a
notification via the configured channel and target. When absent or `false`, the cron
records the breach but does not halt the agent.

## notifyChannel and notifyTarget

These two fields work together and are only meaningful when `autonomousMode` is `true`.
`notifyChannel` identifies the messaging platform (e.g., `slack`, `discord`);
`notifyTarget` identifies the recipient within that platform using the channel-specific
format (e.g., `channel:C0123456789`, `user:<id>`, `@username`).

## organizationName

A human-readable label for the Revenium organization. When present, it is passed as
`--organization-name` on every metered transaction. It is optional; omitting it
skips the flag entirely on the `revenium meter completion` call.
