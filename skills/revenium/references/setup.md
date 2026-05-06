# Revenium Skill Setup

## Initial setup

### 1. Verify prerequisites

```bash
revenium config show
sqlite3 --version
python3 --version
```

### 2. Create the budget alert

Ask the user for:

- budget threshold
- budget period (`DAILY`, `WEEKLY`, `MONTHLY`, `QUARTERLY`)
- optional organization name
- optional autonomous notification channel + target

Before creating a new alert, remove any prior Revenium/Hermes budget alerts you own that would cause duplicates.

Create the alert:

```bash
revenium alerts budget create --name "Hermes Monthly Budget" --threshold 50 --period MONTHLY --json
```

Extract the `id` field from the JSON response.

### 3. Write state config

Write:

```json
{
  "alertId": "<alert-id>",
  "organizationName": "<optional>",
  "autonomousMode": true,
  "notifyChannel": "telegram",
  "notifyTarget": "123456789"
}
```

into:

```text
~/.hermes/state/revenium/config.json
```

### 4. Install cron

```bash
bash ~/.hermes/skills/revenium/scripts/install-cron.sh
```

## Reset flow

1. Read the current config.
2. Fetch the existing alert settings.
3. Delete the old alert.
4. Create a new alert with the same settings.
5. Replace `alertId` in `config.json`.
6. Reset `budget-status.json` to a non-halted zeroed state.

## Reconfigure flow

1. Read and remove the existing config.
2. Delete the old alert.
3. Run the initial setup flow again.
