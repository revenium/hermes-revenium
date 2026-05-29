# Hermes Revenium Skill

Budget enforcement, semantic task-type metering, agentic job tracking, and tool-event metering for [Hermes Agent](https://hermes-agent.nousresearch.com) using the [Revenium](https://www.revenium.ai) platform. Every metered completion carries a meaningful `--task-type` drawn from a controlled vocabulary so Revenium analytics show *what the agent was doing* — not just an undifferentiated session total. Discrete task arcs are reported as Revenium agentic jobs with immutable once-only outcomes, and every Hermes tool call is metered via `revenium meter tool-event` — all while budget guardrails halt the agent structurally before it can overspend.

## Quick Start

Five steps to get up and running:

1. **Install the skill** — clone this repo at the v1.3.1 tag and run `examples/setup-local.sh` (see [Installation](#installation) below for why):

   ```bash
   git clone --branch v1.3.1 https://github.com/revenium/hermes-revenium /tmp/hermes-revenium
   bash /tmp/hermes-revenium/examples/setup-local.sh
   ```

   This copies the full skill bundle (SKILL.md + `scripts/` + `references/` + `plugins/`) into `~/.hermes/skills/revenium/` and restarts the Hermes gateway so the classifier plugin reloads.

2. **Set up guardrail budget rules:**

   ```bash
   bash ~/.hermes/skills/revenium/scripts/setup-guardrails.sh --interactive
   ```

   This creates a Revenium guardrail budget rule and writes `ruleIds` into `~/.hermes/state/revenium/config.json`. Legacy `alertId` installs auto-migrate on the first cron tick — see [`docs/migration-guardrails.md`](docs/migration-guardrails.md).

3. **Install the per-minute metering cron:**

   ```bash
   bash ~/.hermes/skills/revenium/scripts/install-cron.sh
   ```

4. **Install the Hermes shell hooks:**

   ```bash
   bash ~/.hermes/skills/revenium/scripts/install-hooks.sh
   ```

   The hooks register `pre_llm_call`, `pre_tool_call`, and `post_tool_call` in `~/.hermes/config.yaml`. They are inert until you approve them on first `hermes chat`.

5. **Install the on_session_end classifier plugin:**

   ```bash
   bash ~/.hermes/skills/revenium/scripts/install-plugin.sh
   ```

   This copies the `revenium-classifier` plugin into `~/.hermes/plugins/` and enables it in `~/.hermes/config.yaml`. Without this step, `on_session_end` never fires and no `kind:"job"` markers are written — so agentic-job usage never reaches Revenium even though completion metering still works.

6. **Approve hooks on first `hermes chat`** — Hermes shows an approval prompt the first time each hook fires.

Each step is detailed in full below.

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

### Option 1: `git clone` + `setup-local.sh` (recommended)

```bash
git clone --branch v1.3.1 https://github.com/revenium/hermes-revenium /tmp/hermes-revenium
bash /tmp/hermes-revenium/examples/setup-local.sh
```

`setup-local.sh` copies the full skill bundle (`SKILL.md` + `scripts/` + `references/` + `plugins/` + taxonomy JSONs) into `~/.hermes/skills/revenium/`, idempotently installs the `revenium-classifier` plugin into `~/.hermes/plugins/`, adds it to the Hermes plugin-enabled list, and restarts the Hermes gateway so the plugin loads. It runs with no network access to Hermes' Skills Hub — so no security-scanner verdict, no `--force`, no community-registry resolution. After it completes, proceed to [Required: set up guardrails, cron, and hooks](#required-set-up-guardrails-cron-and-hooks).

> **Why not `hermes skills install`?**
>
> Hermes' two `hermes skills install` modes both have problems for this skill, which is why `git clone + setup-local.sh` is the recommended path:
>
> - **`hermes skills install revenium/hermes-revenium/skills/revenium`** (the GitHub-tap form) routes through a fixed source-priority order in [`tools/skills_hub.py:create_source_router`](https://github.com/NousResearch/hermes-agent/blob/main/tools/skills_hub.py): `SkillsShSource` and `ClawHubSource` are checked before the configured GitHub taps. Both have a stale `revenium` snapshot indexed from a pre-v1.0 prototype that contains `AGENTS.md` injection logic and a `post-install.sh` neither of which exists in this repo. The scanner fires `CRITICAL persistence` findings on that stale content and refuses the install. Adding the `revenium/hermes-revenium` tap doesn't change the resolution; it's structurally shadowed.
> - **`hermes skills install https://raw.githubusercontent.com/.../SKILL.md`** (the direct-URL form) only fetches a single file — Hermes' `UrlSource` is documented as claiming "bare HTTP(S) URLs that end in `.md`." The other 30+ files in the skill (`scripts/`, `references/`, `plugins/`, taxonomy JSONs) are not pulled, so the installed skill is non-functional even though it passes the scanner.
>
> If you want `hermes skills check` and `hermes skills update` to notice when this repo ships a new version, add the tap anyway:
>
> ```bash
> hermes skills tap add revenium/hermes-revenium
> ```
>
> The tap entry doesn't change how this skill installs; it's purely a discovery hook surfaced by `hermes skills check`.
>
> **About the security scan.** `setup-local.sh` doesn't go through Hermes' Skills Hub install path so there's no scan. If you later run `hermes skills install` (against any source), expect two informational `MEDIUM persistence` findings — `crontab` references in `install-cron.sh` / `cron.sh` / `uninstall-cron.sh`. That's the scanner correctly detecting a real behavior: the skill installs a per-minute crontab entry to meter the Hermes session DB into Revenium. The cron is required for the skill to function — there is no version of this without it. Review the scripts in [`skills/revenium/scripts/`](skills/revenium/scripts/) before installing if you want to confirm them yourself.

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

## Required: set up guardrails, cron, and hooks

After installing the skill (any of the options above), run these commands once in order.

**Set up guardrail budget rules:**

```bash
bash ~/.hermes/skills/revenium/scripts/setup-guardrails.sh --interactive
```

The script prompts for budget hard-limit, period, organization name, autonomous mode and notification channel/target, and optionally per-task-type rules. On success it creates Revenium guardrail budget rules and writes `ruleIds` into `~/.hermes/state/revenium/config.json`. Legacy `alertId` installs auto-migrate on the first cron tick — see [`docs/migration-guardrails.md`](docs/migration-guardrails.md).

**Install the per-minute metering cron:**

```bash
bash ~/.hermes/skills/revenium/scripts/install-cron.sh
```

The cron meters `~/.hermes/state.db` into Revenium and refreshes `~/.hermes/state/revenium/guardrail-status.json`. Hermes can't add crontab entries itself, so this step is manual. **Without it, the agent will tell you "Guardrail status not yet available" before every operation** — that's the skill correctly detecting the missing cron.

For demos or dashboards where the default 60-second cadence is too slow, install with a sub-minute interval. The cron still fires once per minute, but the pipeline loops inside each tick:

```bash
bash ~/.hermes/skills/revenium/scripts/install-cron.sh --interval-seconds 15
# 4× per minute (every 15s). Trade-off: 4× more revenium-CLI calls.

bash ~/.hermes/skills/revenium/scripts/install-cron.sh --interval-seconds 15 --force
# Replace an existing entry to change interval on a host that already has the cron.
```

Valid values: `1..60`. Use `--dry-run` to print the crontab line without installing.

**Install the Hermes shell hooks:**

```bash
bash ~/.hermes/skills/revenium/scripts/install-hooks.sh
```

The shell hooks register `pre_llm_call`, `pre_tool_call`, and `post_tool_call` handlers in `~/.hermes/config.yaml`. They are inert until you approve them on first `hermes chat`. Without the hooks, structural budget enforcement and tool-event capture are inactive.

**Install the on_session_end classifier plugin:**

```bash
bash ~/.hermes/skills/revenium/scripts/install-plugin.sh
```

The script copies `revenium-classifier` into `~/.hermes/plugins/` and adds it to `plugins.enabled` in `~/.hermes/config.yaml`, then restarts the Hermes gateway so the change takes effect. Idempotent — re-run it safely after upgrading the skill. `hermes skills install` and `external_dirs` don't relocate the bundled `plugins/` subdirectory, so this step is what wires the classifier into Hermes' plugin discovery path. Without it, no `kind:"job"` markers are written — agentic-job usage never reaches Revenium even though completion metering still works. Pass `--dry-run` to preview, or `--no-restart` to skip the gateway restart.

To confirm the cron is running:

```bash
crontab -l | grep hermes-revenium-metering   # one entry
tail -f ~/.hermes/state/revenium/revenium-metering.log
```

## First-time setup

The guided Setup Flow is driven by `setup-guardrails.sh --interactive` (step 2 above, or invokable at any time via `/revenium` inside a Hermes session). The skill detects that no `config.json` or `ruleIds` exists and automatically begins setup. Once configured, invoking `/revenium` instead offers status and reconfigure options. The script will:

1. Verify the `revenium` CLI is configured (asks for API key, Team ID, Tenant ID, User ID if not — run `revenium config show` to check, then `revenium login` if unconfigured).
2. Optionally ask for an organization name (for Revenium reporting attribution).
3. Ask for a budget hard-limit, warn threshold, and period (`DAILY`, `WEEKLY`, `MONTHLY`, `QUARTERLY`).
4. Ask whether the agent runs autonomously and, if so, which Hermes messaging channel should receive halt notifications.
5. Create a Revenium guardrail budget rule via `revenium guardrails budget-rules create` and write `ruleIds` into `~/.hermes/state/revenium/config.json`.

Setup is atomic — if any step fails, no partial config is written. The full step-by-step flow lives in [`skills/revenium/references/setup.md`](skills/revenium/references/setup.md).

## How it works

### Token metering with task-type classification

A background cron runs every minute and reports token usage (`hermes-report.sh`): it reads token deltas from `~/.hermes/state.db`, then ships one `revenium meter completion` per marker. Each completion carries `--task-type` and `--operation-type` drawn from the task taxonomy, and job-owning markers also receive `--agentic-job-id`. The idempotency ledger key is `HERMES:<session_id>:<total_tokens>` so re-running the cron never double-reports.

Task-type and agentic-job inference is performed by the deterministic `revenium-classifier` plugin (`skills/revenium/plugins/revenium-classifier/`) at `on_session_end`. It reads session data directly — it does not rely on the agent voluntarily classifying its own turns. Sessions with no markers fall back to `--task-type unclassified`.

### Agentic job tracking

Discrete task arcs are reported as Revenium agentic jobs (`revenium jobs create` / `revenium jobs outcome`). Each arc's business outcome is recorded exactly once — outcomes are immutable and never re-sent. Idempotency is maintained in `~/.hermes/state/revenium/revenium-jobs.ledger`. AI transactions belonging to a job are linked in Revenium via `--agentic-job-id`.

### Tool-event metering

The `post_tool_call` hook captures each Hermes tool call (tool name, duration in milliseconds, success/failure, `tool_call_id`, session ID, error message) to a per-session file at `~/.hermes/state/revenium/tool-events/<sid>.jsonl`. The hook makes no network call — it is a pure local observer that exits 0 on any internal failure so it never blocks the agent. The cron's `tool-event-report.sh` stage then reads these files and ships each unledgered record via `revenium meter tool-event`, keyed on `<sid>:<tool_call_id>` in `revenium-tool-events.ledger`.

### Guardrail enforcement

Guardrail enforcement is **structural**: the `pre_llm_call` and `pre_tool_call` Hermes shell hooks check `guardrail-status.json` on every turn and act per the warn/block band, blocking the agent deterministically regardless of session length. The `SKILL.md` halt block is a procedural backstop — the hooks are the load-bearing enforcement path.

Before every operation the agent's state resolves to one of:

- **All rules ok** → proceed silently.
- **Warn-band rule active** → `pre_llm_call` emits one stderr line per (session, ruleId) and the agent continues.
- **Block-band rule active, autonomous mode** → `pre_tool_call` blocks all tool calls and emits an `action: block` response; `pre_llm_call` injects the verbatim halt directive into the turn. A notification (including the most recent enforcement-events list entry) is sent through the configured Hermes messaging channel.
- **Status file missing** → proceed with caution (fail-open).

The three shell hooks are registered by `install-hooks.sh` and removed by `uninstall-hooks.sh`. They are inert until the user approves them on first `hermes chat`. `guardrail-check.sh` (the second cron stage) refreshes `guardrail-status.json` and detects new halt transitions; on transition into halt, it embeds the latest enforcement-event into the halt notification.

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

> Legacy `alertId` field is preserved on upgraded hosts but no longer used — see [`docs/migration-guardrails.md`](docs/migration-guardrails.md).

Your Revenium credentials (API key, Team ID, Tenant ID, Owner ID) live separately at `~/.config/revenium/config.yaml`, written by `revenium config set`. The skill never reads or writes that file directly.

## Manual commands

```bash
# Run metering + guardrail check + tool-event reporting once
bash ~/.hermes/skills/revenium/scripts/cron.sh

# Run only the SQLite reporter (completion metering with task-type)
bash ~/.hermes/skills/revenium/scripts/hermes-report.sh

# Run only the guardrail check
bash ~/.hermes/skills/revenium/scripts/guardrail-check.sh

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

# Install the revenium-classifier on_session_end plugin into ~/.hermes/plugins/
bash ~/.hermes/skills/revenium/scripts/install-plugin.sh

# Diagnose whether the hooks are registered AND firing
bash ~/.hermes/skills/revenium/scripts/hooks-status.sh
```

## Status & diagnostics

```bash
# Tail the metering log
tail -f ~/.hermes/state/revenium/revenium-metering.log

# Inspect the live guardrail snapshot
cat ~/.hermes/state/revenium/guardrail-status.json

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

# Run the end-to-end hooks diagnostic — registration + approval mode + recent
# capture activity + state.db cross-check. Stable exit codes for scripting:
# 0 = hooks firing, 1 = not registered, 2 = registered but inert.
bash ~/.hermes/skills/revenium/scripts/hooks-status.sh
```

If `guardrail-status.json` does not exist, the cron has not run yet — run `cron.sh` once manually to seed it. If `tool-events/` stays empty even though Hermes is running tools, run `hooks-status.sh` first — the most common cause is the hooks being registered but not yet approved on `hermes chat`. More failure modes are documented in [`skills/revenium/references/troubleshooting.md`](skills/revenium/references/troubleshooting.md).

## Verification

Run these in order to confirm a successful install:

```bash
crontab -l | grep hermes-revenium-metering         # one entry
grep hermes-revenium-hooks ~/.hermes/config.yaml   # 3 hook commands registered
grep post_tool_call ~/.hermes/config.yaml          # post_tool_call hook present
jq '.ruleIds' ~/.hermes/state/revenium/config.json # non-empty array
```

Wait one cron tick (≤60s), then:

```bash
cat ~/.hermes/state/revenium/guardrail-status.json  # expect rules[] populated
```

When a guardrail block-band rule fires under autonomous mode, the agent emits the verbatim halt directive:

```
Guardrail halt active — rule '[name]' ([metricType], [windowType]) at [currentValue] of [hardLimit] hard-limit. To resume: `bash ~/.hermes/skills/revenium/scripts/clear-halt.sh`
```

(D-01 verbatim halt string — values substituted from `guardrail-status.json::haltedRule`.)

## Uninstalling

```bash
bash ~/.hermes/skills/revenium/scripts/uninstall-cron.sh
bash ~/.hermes/skills/revenium/scripts/uninstall-hooks.sh
rm -rf ~/.hermes/skills/revenium ~/.hermes/state/revenium
```

Optionally clean up the Revenium-side guardrail rules:

```bash
revenium guardrails budget-rules list
revenium guardrails budget-rules delete <rule-id> --yes
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
