# Configuration

[← Documentation index](README.md)

The skill stores its config at `~/.hermes/state/revenium/config.json`:

```json
{
  "ruleIds": ["d5jng5"],
  "organizationName": "my-org",
  "autonomousMode": false,
  "notifyChannel": "slack",
  "notifyTarget": "channel:C0123456789"
}
```

| Field               | Required | Purpose                                                                          |
| ------------------- | -------- | -------------------------------------------------------------------------------- |
| `ruleIds`           | yes      | Array of `revenium guardrails budget-rules` ruleIds owned by this install. Populated by `setup-guardrails.sh` and on first cron tick for legacy-upgrade installs. |
| `organizationName`  | no       | Used as `--organization-name` on metered transactions for Revenium attribution.  |
| `autonomousMode`    | no       | When `true`, a blocked guardrail rule halts the agent and sends a notification.  |
| `notifyChannel`     | autonomous only | Hermes messaging channel for halt notifications (e.g. `slack`, `discord`). |
| `notifyTarget`      | autonomous only | Channel-specific target (e.g. `channel:<id>`, `user:<id>`, `@username`).   |

> Legacy `alertId` field is preserved on upgraded hosts but no longer used — see [`docs/migration-guardrails.md`](migration-guardrails.md).

Your Revenium credentials (API key, Team ID, Tenant ID, Owner ID) live separately at `~/.config/revenium/config.yaml`, written by `revenium config set`. The skill never reads or writes that file directly.

