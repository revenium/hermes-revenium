# Hermes Revenium Skill

Budget enforcement, semantic task-type metering, agentic job tracking, and tool-event metering for [Hermes Agent](https://hermes-agent.nousresearch.com) using the [Revenium](https://www.revenium.ai) platform. Every metered completion carries a meaningful `--task-type` drawn from a controlled vocabulary so Revenium analytics show *what the agent was doing* — not just an undifferentiated session total. Discrete task arcs are reported as Revenium agentic jobs with immutable once-only outcomes, and every Hermes tool call is metered via `revenium meter tool-event` — all while budget guardrails halt the agent structurally before it can overspend.

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

## Required: install the cron and hooks

After installing the skill (any of the options above), run these two commands once.

**Install the per-minute metering cron:**

```bash
bash ~/.hermes/skills/revenium/scripts/install-cron.sh
```

The cron meters `~/.hermes/state.db` into Revenium and refreshes `~/.hermes/state/revenium/budget-status.json`. Hermes can't add crontab entries itself, so this step is manual. **Without it, the agent will tell you "Budget status not yet available" before every operation** — that's the skill correctly detecting the missing cron.

**Install the Hermes shell hooks:**

```bash
bash ~/.hermes/skills/revenium/scripts/install-hooks.sh
```

The shell hooks register `pre_llm_call`, `pre_tool_call`, and `post_tool_call` handlers in `~/.hermes/config.yaml`. They are inert until you approve them on first `hermes chat`. Without the hooks, structural budget enforcement and tool-event capture are inactive.

To confirm the cron is running:

```bash
crontab -l | grep hermes-revenium-metering   # one entry
tail -f ~/.hermes/state/revenium/revenium-metering.log
```

## First-time setup

Once the cron and hooks are in place, setup runs the first time you use the skill — Hermes walks you through it. The skill will:

1. Verify the `revenium` CLI is configured (asks for API key, Team ID, Tenant ID, User ID if not).
2. Optionally ask for an organization name (for Revenium reporting attribution).
3. Ask for a budget threshold and period (`DAILY`, `WEEKLY`, `MONTHLY`, `QUARTERLY`).
4. Ask whether the agent runs autonomously and, if so, which Hermes messaging channel should receive halt notifications.
5. Delete any pre-existing `Hermes …` budget alerts (to prevent duplicates) and create a fresh one.
6. Write `~/.hermes/state/revenium/config.json`.

Setup is atomic — if any step fails, no partial config is written. The full step-by-step flow lives in [`skills/revenium/references/setup.md`](skills/revenium/references/setup.md).

## How it works

### Token metering with task-type classification

A background cron runs every minute and reports token usage (`hermes-report.sh`): it reads token deltas from `~/.hermes/state.db`, then ships one `revenium meter completion` per marker. Each completion carries `--task-type` and `--operation-type` drawn from the task taxonomy, and job-owning markers also receive `--agentic-job-id`. The idempotency ledger key is `HERMES:<session_id>:<total_tokens>` so re-running the cron never double-reports.

Task-type and agentic-job inference is performed by the deterministic `revenium-classifier` plugin (`skills/revenium/plugins/revenium-classifier/`) at `on_session_end`. It reads session data directly — it does not rely on the agent voluntarily classifying its own turns. Sessions with no markers fall back to `--task-type unclassified`.

### Agentic job tracking

Discrete task arcs are reported as Revenium agentic jobs (`revenium jobs create` / `revenium jobs outcome`). Each arc's business outcome is recorded exactly once — outcomes are immutable and never re-sent. Idempotency is maintained in `~/.hermes/state/revenium/revenium-jobs.ledger`. AI transactions belonging to a job are linked in Revenium via `--agentic-job-id`.

### Tool-event metering

The `post_tool_call` hook captures each Hermes tool call (tool name, duration in milliseconds, success/failure, `tool_call_id`, session ID, error message) to a per-session file at `~/.hermes/state/revenium/tool-events/<sid>.jsonl`. The hook makes no network call — it is a pure local observer that exits 0 on any internal failure so it never blocks the agent. The cron's `tool-event-report.sh` stage then reads these files and ships each unledgered record via `revenium meter tool-event`, keyed on `<sid>:<tool_call_id>` in `revenium-tool-events.ledger`.

### Budget enforcement

Budget enforcement is now **structural**: the `pre_llm_call` and `pre_tool_call` Hermes shell hooks check `budget-status.json` on every turn and block the agent deterministically regardless of session length. The `SKILL.md` halt block is now a backstop rather than the primary mechanism.

Before every operation the agent's state resolves to one of:

- **Within budget** → proceed silently.
- **Exceeded, interactive mode** → warn the user with current spend vs. threshold and ask permission to continue.
- **Exceeded, autonomous mode** → the `pre_tool_call` hook blocks all tool calls and emits an `action: block` response; `pre_llm_call` injects a halt directive into the turn. A notification is sent through the configured Hermes messaging channel.
- **Status file missing** → proceed with caution (fail-open).

The three shell hooks are registered by `install-hooks.sh` and removed by `uninstall-hooks.sh`. They are inert until the user approves them on first `hermes chat`. `budget-check.sh` (the second cron stage) refreshes `budget-status.json` and detects new halt transitions.

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
# Run metering + budget check + tool-event reporting once
bash ~/.hermes/skills/revenium/scripts/cron.sh

# Run only the SQLite reporter (completion metering with task-type)
bash ~/.hermes/skills/revenium/scripts/hermes-report.sh

# Run only the budget check
bash ~/.hermes/skills/revenium/scripts/budget-check.sh

# Run only the tool-event reporter
bash ~/.hermes/skills/revenium/scripts/tool-event-report.sh

# Clear an active halt
bash ~/.hermes/skills/revenium/scripts/clear-halt.sh

# Prune stale marker files (30+ days old by default; --dry-run to preview)
bash ~/.hermes/skills/revenium/scripts/prune-markers.sh

# (Re)install the per-minute cron entry
bash ~/.hermes/skills/revenium/scripts/install-cron.sh

# Remove the cron entry
bash ~/.hermes/skills/revenium/scripts/uninstall-cron.sh

# Register the pre_llm_call / pre_tool_call / post_tool_call hooks
bash ~/.hermes/skills/revenium/scripts/install-hooks.sh

# Remove the shell hooks
bash ~/.hermes/skills/revenium/scripts/uninstall-hooks.sh
```

## Status & diagnostics

```bash
# Tail the metering log
tail -f ~/.hermes/state/revenium/revenium-metering.log

# Inspect the live budget snapshot
cat ~/.hermes/state/revenium/budget-status.json

# Confirm the cron is installed
crontab -l | grep hermes-revenium-metering

# Inspect the completion idempotency ledger
tail -n 20 ~/.hermes/state/revenium/revenium-hermes.ledger

# Inspect the agentic-job idempotency ledger
tail -n 20 ~/.hermes/state/revenium/revenium-jobs.ledger

# Inspect the tool-event idempotency ledger
tail -n 20 ~/.hermes/state/revenium/revenium-tool-events.ledger

# Inspect captured tool-event records for a session
cat ~/.hermes/state/revenium/tool-events/<sid>.jsonl
```

If `budget-status.json` does not exist, the cron has not run yet — run `cron.sh` once manually to seed it. More failure modes are documented in [`skills/revenium/references/troubleshooting.md`](skills/revenium/references/troubleshooting.md).

## Uninstalling

```bash
bash ~/.hermes/skills/revenium/scripts/uninstall-cron.sh
bash ~/.hermes/skills/revenium/scripts/uninstall-hooks.sh
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

Beyond the automated smoke checks, a manual halt-check survivability test plan — operator runbook is documented at `skills/revenium/references/halt-survivability.md`. Run it before any release that modifies the `SKILL.md` halt block to confirm the halt-check anchor still fires correctly under context dilution in long sessions.

## Notes

- This repo is Hermes-only and intentionally clean — no legacy runtime assumptions from the source skill it was forked from.
- The skill is packaged at `skills/revenium/` so the default `hermes skills tap add owner/repo` discovery path resolves it without extra configuration.
- Mutable runtime state lives under `~/.hermes/state/revenium/`. Skill content lives under `~/.hermes/skills/revenium/`. Don't mix the two.

## Support

Questions, bugs, or feature requests? Join us on [Discord](http://discord.gg/J2DbmjZ2nA).
