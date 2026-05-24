# Troubleshooting

## `revenium` CLI not found

Install it and ensure it is on PATH:

```bash
brew install revenium/tap/revenium
```

## `sqlite3` not found

Install SQLite or ensure it is on PATH.

## `guardrail-status.json` missing

Run the cron runner manually:

```bash
bash ~/.hermes/skills/revenium/scripts/cron.sh
```

## Halt will not clear

Inspect the state file:

```bash
cat ~/.hermes/state/revenium/guardrail-status.json
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

## Dashboard shows $0.00 / Total evaluations 0 even though cron is shipping meter completions

**Symptom.** The Revenium dashboard for your rule shows `currentValue: 0` and "Total evaluations 0," but `revenium-metering.log` is full of successful `Reported: session=...` lines and the ledger (`revenium-hermes.ledger`) is growing every minute. The cron is doing its job; the rule just is not seeing any of the events.

**Root cause.** The rule was created without an explicit `--filter`, so the Revenium engine groups spend by ORGANIZATION but sees nothing in your team's child-org buckets because metered events fall through to the auto-discovery `UNCLASSIFIED` subscription. This is the failure mode quick-task 260524-lpu fixed by defaulting freshly-created rules to `--filter AGENT:IS:Hermes`.

**Fix.** Delete the existing rule and re-run `setup-guardrails.sh` after upgrading to the hotfix; the new rule will be scoped to `AGENT:IS:Hermes` automatically and will start matching incoming traffic on the next cron tick.

```bash
# 1. List rules to find the id with currentValue: 0
revenium guardrails budget-rules list --output json | python3 -m json.tool

# 2. Delete the affected rule
revenium guardrails budget-rules delete <ruleId> --yes

# 3. Re-create with the hotfix defaults (uses --filter AGENT:IS:Hermes)
bash ~/.hermes/skills/revenium/scripts/setup-guardrails.sh \
  --hard-limit <N> --period MONTHLY

# 4. Wait one cron tick (~60s), then re-check currentValue
revenium guardrails budget-rules list --output json | python3 -m json.tool
```

If you want a non-default filter scope (per-model, per-provider, etc.), pass `--filter dim:op:val` or `--filters-json '<json>'` to `setup-guardrails.sh`. See `docs/migration-guardrails.md` for the full set of supported dimensions and operators.

## Notification did not send

The halt notifier uses Hermes itself to send a message through the configured channel. Verify:

- Hermes CLI is installed and on PATH
- the messaging target is valid
- the relevant messaging toolset is configured for Hermes
