# Hermes Revenium Skill

Budget enforcement and token metering for [Hermes Agent](https://hermes-agent.nousresearch.com) using the [Revenium](https://www.revenium.ai) platform. Tracks AI spend, enforces configurable budget guardrails, and reports usage automatically — so agents never silently blow through your token budget.

## Prerequisites

- [Hermes Agent](https://hermes-agent.nousresearch.com/docs/) installed and running
- [Revenium](https://app.revenium.ai/connections) API key, Team ID, Tenant ID, and User ID
- [`revenium` CLI](https://github.com/revenium/revenium-cli) — `brew install revenium/tap/revenium`
- `sqlite3` and `python3` on `PATH`

Verify:

```bash
revenium config show
sqlite3 --version
python3 --version
```

## Installation

### Option 1: GitHub tap (recommended)

```bash
hermes skills tap add revenium/hermes-revenium
hermes skills install revenium/hermes-revenium/skills/revenium --force
```

Hermes discovers tap repositories by scanning the repo's `skills/` directory, which is why the skill lives at `skills/revenium/`.

> **About the `--force` flag and the security scan.** Hermes' install-time scanner classifies this skill as `DANGEROUS` and lists ~6 `MEDIUM persistence` findings against `install-cron.sh`, `cron.sh`, and `uninstall-cron.sh`. That's the scanner correctly detecting a real behavior: the skill installs a per-minute crontab entry to meter `~/.hermes/state.db` into Revenium. The cron is required for the skill to function — there is no version of this without it. `--force` acknowledges that and proceeds. Review the findings yourself if you want to confirm they're all crontab-related; the scripts are also viewable in [`skills/revenium/scripts/`](skills/revenium/scripts/) before you install.
>
> If the scanner reports `CRITICAL persistence` findings referencing `AGENTS.md` or a `post-install.sh`, those are stale artifacts from a previous (non-Hermes) install in your `~/.hub/quarantine/revenium/` cache. Clean it with `rm -rf ~/.hub/quarantine/revenium` and re-run the install — the genuine Hermes skill has no such files.

### Option 2: Local development

Point Hermes at this repo's `skills/` directory:

```yaml
# ~/.hermes/config.yaml
skills:
  external_dirs:
    - /absolute/path/to/hermes-revenium/skills
```

Then restart Hermes or start a new session. External skill directories are read-only discovery sources; the local `~/.hermes/skills/` install wins on name collision.

### Option 3: Local copy

```bash
mkdir -p ~/.hermes/skills
cp -R skills/revenium ~/.hermes/skills/
```

Or use the bundled helper:

```bash
bash examples/setup-local.sh
```

### Option 4: Publish

To make this skill discoverable through Hermes' skill index:

```bash
hermes skills publish skills/revenium --to github --repo revenium/hermes-revenium
```

## First-time setup

Setup runs the first time you use the skill — Hermes walks you through it. The skill will:

1. Verify the `revenium` CLI is configured (asks for API key, Team ID, Tenant ID, User ID if not).
2. Optionally ask for an organization name (for Revenium reporting attribution).
3. Ask for a budget threshold and period (`DAILY`, `WEEKLY`, `MONTHLY`, `QUARTERLY`).
4. Ask whether the agent runs autonomously and, if so, which Hermes messaging channel should receive halt notifications.
5. Delete any pre-existing `Hermes …` budget alerts (to prevent duplicates) and create a fresh one.
6. Write `~/.hermes/state/revenium/config.json` and install the metering cron.

Setup is atomic — if any step fails, no partial config is written. The full step-by-step flow lives in [`skills/revenium/references/setup.md`](skills/revenium/references/setup.md).

To verify the cron is running after setup:

```bash
tail -f ~/.hermes/state/revenium/revenium-metering.log
```

## How it works

### Token metering

A background cron runs every minute and:

1. **Reports usage** (`hermes-report.sh`) — reads token usage from `~/.hermes/state.db`, computes deltas against an idempotency ledger, and ships each delta to Revenium via `revenium meter completion` with the model, provider, token counts, request/response timestamps, and an optional organization name. The ledger key is `HERMES:<session_id>:<total_tokens>` so re-running the cron never double-reports.
2. **Refreshes budget** (`budget-check.sh`) — fetches the configured budget alert from Revenium, computes whether spend exceeds the threshold, and writes the result to `~/.hermes/state/revenium/budget-status.json`. This is the local file the agent reads on every turn — no Revenium API round-trip needed in-session.

### Budget enforcement

Before every operation (response, tool call, exploration) the agent reads `~/.hermes/state/revenium/budget-status.json`:

- **Within budget** → proceed silently.
- **Exceeded, interactive mode** → warn the user with current spend vs. threshold and ask permission to continue.
- **Exceeded, autonomous mode** → halt all operations and send a notification through the configured Hermes messaging channel.
- **Status file missing** → proceed with caution (fail-open).

The full halt/exceed contract — including the exact halt response string the agent must emit verbatim — is specified in [`skills/revenium/SKILL.md`](skills/revenium/SKILL.md).

### `/revenium` command

Run `/revenium` at any time inside a Hermes session to:

- **View budget status** — current spend, threshold, percent used, halt state.
- **Reset** — recreate the alert with the same settings (zeroes current spend).
- **Reconfigure** — update API key, budget amount, or period (deletes the old alert and creates a new one).

## Configuration

The skill stores its config at `~/.hermes/state/revenium/config.json`:

```json
{
  "alertId": "75BjG5",
  "organizationName": "my-org",
  "autonomousMode": false,
  "notifyChannel": "slack",
  "notifyTarget": "channel:C0123456789"
}
```

| Field               | Required | Purpose                                                                          |
| ------------------- | -------- | -------------------------------------------------------------------------------- |
| `alertId`           | yes      | Revenium budget alert ID, written by setup. Do not edit by hand.                 |
| `organizationName`  | no       | Used as `--organization-name` on metered transactions for Revenium attribution.  |
| `autonomousMode`    | no       | When `true`, exceedance halts the agent and sends a notification.                |
| `notifyChannel`     | autonomous only | Hermes messaging channel for halt notifications (e.g. `slack`, `discord`). |
| `notifyTarget`      | autonomous only | Channel-specific target (e.g. `channel:<id>`, `user:<id>`, `@username`).   |

Your Revenium credentials (API key, Team ID, Tenant ID, Owner ID) live separately at `~/.config/revenium/config.yaml`, written by `revenium config set`. The skill never reads or writes that file directly.

## Manual commands

```bash
# Run metering + budget check once
bash ~/.hermes/skills/revenium/scripts/cron.sh

# Run only the SQLite reporter
bash ~/.hermes/skills/revenium/scripts/hermes-report.sh

# Run only the budget check
bash ~/.hermes/skills/revenium/scripts/budget-check.sh

# Clear an active halt
bash ~/.hermes/skills/revenium/scripts/clear-halt.sh

# (Re)install the per-minute cron entry
bash ~/.hermes/skills/revenium/scripts/install-cron.sh

# Remove the cron entry
bash ~/.hermes/skills/revenium/scripts/uninstall-cron.sh
```

## Status & diagnostics

```bash
# Tail the metering log
tail -f ~/.hermes/state/revenium/revenium-metering.log

# Inspect the live budget snapshot
cat ~/.hermes/state/revenium/budget-status.json

# Confirm the cron is installed
crontab -l | grep hermes-revenium-metering

# Inspect the idempotency ledger
tail -n 20 ~/.hermes/state/revenium/revenium-hermes.ledger
```

If `budget-status.json` does not exist, the cron has not run yet — run `cron.sh` once manually to seed it. More failure modes are documented in [`skills/revenium/references/troubleshooting.md`](skills/revenium/references/troubleshooting.md).

## Uninstalling

```bash
bash ~/.hermes/skills/revenium/scripts/uninstall-cron.sh
rm -rf ~/.hermes/skills/revenium ~/.hermes/state/revenium
```

Optionally clean up the Revenium-side budget alert:

```bash
revenium alerts budget list
revenium alerts budget delete <alert-id> --yes
```

## Testing

The repo ships stdlib `unittest` smoke checks covering expected files, frontmatter shape, runtime path conventions, and shell-script syntax:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Notes

- This repo is Hermes-only and intentionally clean — no legacy runtime assumptions from the source skill it was forked from.
- The skill is packaged at `skills/revenium/` so the default `hermes skills tap add owner/repo` discovery path resolves it without extra configuration.
- Mutable runtime state lives under `~/.hermes/state/revenium/`. Skill content lives under `~/.hermes/skills/revenium/`. Don't mix the two.

## Support

Questions, bugs, or feature requests? Join us on [Discord](http://discord.gg/J2DbmjZ2nA).
