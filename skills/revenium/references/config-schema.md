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

---

# guardrail-status.json Schema

## Overview

`guardrail-status.json` is the runtime enforcement-status file written by `guardrail-check.sh`
on every cron tick. Location: `~/.hermes/state/revenium/guardrail-status.json` (declared as
`GUARDRAIL_STATUS_FILE` in `common.sh`). It is the coupling point between the cron pipeline
(writer) and the shell hooks (`pre_llm_call.sh`, `pre_tool_call.sh`) and the SKILL.md backstop
(readers). The cron pipeline writes this file; the hooks and the SKILL.md procedural block read
it on every Hermes turn.

## Top-Level Fields

| Field | Type | Present when | Description |
|-------|------|--------------|-------------|
| `halted` | boolean | Always | `true` when `autonomousMode` is on and at least one rule is in `block` state. |
| `haltedAt` | string (ISO-8601) | `halted: true` only | Timestamp of the first halt transition for the current halt epoch. Carried forward on subsequent cron ticks while halt persists; removed on clear. |
| `haltedRule` | object | `halted: true` only | Pre-computed tiebreaker rule (first blocked rule in `ruleIds[]` declaration order, D-04). See haltedRule Extension below. |
| `autonomousMode` | boolean | Always | Mirrors `config.json::autonomousMode` at time of last cron tick. |
| `lastChecked` | string (ISO-8601) | Always | Timestamp of the most recent `guardrail-check.sh` run. |
| `rules` | array | Always | Per-rule state array; see `rules[]` Fields below. |

## `rules[]` Fields

| Field | Type | Description |
|-------|------|-------------|
| `ruleId` | string | Revenium-hashed rule ID; same format as `config.json::ruleIds`. |
| `name` | string | Rule name as declared in Revenium. |
| `metricType` | string | Metric being enforced (e.g., `TOTAL_COST`). |
| `windowType` | string | Billing window (e.g., `MONTHLY`). Mapped from API `periodType`. |
| `groupBy` | string | Grouping dimension (e.g., `ORGANIZATION`). |
| `currentValue` | number | Current value of the metric. |
| `warnThreshold` | number | Warn-band threshold. |
| `hardLimit` | number | Hard-limit threshold. Mapped from API `threshold`. |
| `state` | string | Derived state: `ok`, `warn`, or `block`. `block`: metric has breached the hard limit. `warn`: metric has breached the warn threshold but not the hard limit. `ok`: neither threshold breached. |
| `lastChecked` | string (ISO-8601) | Timestamp of this rule's last update. |

## `haltedRule` Extension (D-04)

When `halted` is `true`, the top-level `haltedRule` block is pre-computed by
`guardrail-check.sh` from the first blocked rule in `config.json::ruleIds` declaration
order. This eliminates tiebreaker logic from hook scripts and the SKILL.md backstop —
all three become trivial readers of one pre-resolved block. When `halted` is `false`,
`haltedRule` is absent entirely.

The `haltedRule` block contains a subset of `rules[]` fields: `ruleId`, `name`,
`metricType`, `windowType`, `currentValue`, and `hardLimit`. The fields `groupBy`,
`warnThreshold`, `state`, and `lastChecked` are intentionally omitted — hooks only
need the static rule identity and current breach values to render the halt message.
