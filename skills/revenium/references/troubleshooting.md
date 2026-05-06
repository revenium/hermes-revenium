# Troubleshooting

## `revenium` CLI not found

Install it and ensure it is on PATH:

```bash
brew install revenium/tap/revenium
```

## `sqlite3` not found

Install SQLite or ensure it is on PATH.

## `budget-status.json` missing

Run the cron runner manually:

```bash
bash ~/.hermes/skills/revenium/scripts/cron.sh
```

## Halt will not clear

Inspect the state file:

```bash
cat ~/.hermes/state/revenium/budget-status.json
```

Then clear it:

```bash
bash ~/.hermes/skills/revenium/scripts/clear-halt.sh
```

## No data appearing in Revenium

Check the Hermes reporter log:

```bash
tail -f ~/.hermes/state/revenium/revenium-metering.log
```

Then verify:

- `~/.hermes/state.db` exists
- `revenium config show` succeeds
- the session rows in `state.db` have non-zero token counts

## Notification did not send

The halt notifier uses Hermes itself to send a message through the configured channel. Verify:

- Hermes CLI is installed and on PATH
- the messaging target is valid
- the relevant messaging toolset is configured for Hermes
