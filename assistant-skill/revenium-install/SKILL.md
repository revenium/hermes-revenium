---
name: revenium-install
description: >-
  Install, verify, and troubleshoot the Revenium usage-metering + budget-guardrail
  skill for Hermes Agent on a single host or multi-profile fleet, including
  headless and multiplexed gateways. Use this when setting up Revenium metering on
  a machine, wiring a fleet of Hermes profiles, or diagnosing why metering / agentic
  jobs / tool-events / budget halts are not working. Symptoms include "jobs have no
  transactions", "teamId is required", hooks registered but inert (no tool-events),
  orphaned cron lines spamming errors, spend showing up as "unclassified", or one
  profile metering while others don't.
license: MIT
---

# revenium-install

This runbook installs and operates the `hermes-revenium` metering
skill. Every action is a POSIX shell command that runs the skill's own scripts
under `~/.hermes/skills/revenium/scripts/`. It contains no assistant-specific tool calls.

This skill selects the existing script to run and explains how to verify the
result. The shell scripts perform every mutation.

## When to use

- Installing Revenium metering on a host (single profile) or a fleet
  (`~/.hermes/profiles/*`).
- Verifying that an install meters completions, agentic jobs, tool-events, and
  budget guardrails.
- Diagnosing a broken or partial install. Route symptoms through
  [`references/decision-tree.md`](references/decision-tree.md).

## Prerequisites (check first, don't assume)

```sh
command -v revenium sqlite3 python3 >/dev/null 2>&1 && echo "tools OK" || echo "MISSING TOOLS"
revenium config show    # need API Key, Team ID, Tenant ID, Owner ID — all four
```

If the `revenium` CLI is missing: `brew install revenium/tap/revenium` (macOS) or
see the CLI releases. If any of the four credentials is missing, `install.sh`
will prompt for it (or take `REVENIUM_*` env vars with `--non-interactive`).

## Install

### 1. Bootstrap (only needed after `hermes skills install`)

`hermes skills install` ships `SKILL.md` plus only the support files `SKILL.md`
names as bundle-relative paths, not `scripts/` and never `plugins/`, which
Hermes disallows in a skill bundle. If `~/.hermes/skills/revenium/scripts/install.sh`
does not exist yet, fetch the missing pieces:

```sh
bash ~/.hermes/skills/revenium/references/bootstrap.sh          # single host
# add fleet/creds flags — they pass straight through to install.sh:
bash ~/.hermes/skills/revenium/references/bootstrap.sh --all-profiles
```

If `references/bootstrap.sh` didn't come down either, clone and install directly:

```sh
git clone --depth 1 https://github.com/revenium/hermes-revenium.git /tmp/hermes-revenium \
  && bash /tmp/hermes-revenium/install.sh
```

### 2. Run the installer

`install.sh` is idempotent. It configures credentials, the classifier plugin,
shell hooks, a guardrail rule, the per-minute cron, and the gateway restart.

```sh
# Single host, interactive budget prompt:
bash ~/.hermes/skills/revenium/scripts/install.sh

# Non-interactive budget + org (CI-friendly):
bash ~/.hermes/skills/revenium/scripts/install.sh \
  --hard-limit 50 --period MONTHLY --organization-name <company-or-product>

# Whole fleet — one command wires every ~/.hermes/profiles/<name>/ + the default
# home, each with a distinct AGENT (Hermes-<profile>) and its own cron marker:
bash ~/.hermes/skills/revenium/scripts/install.sh --all-profiles

# Specific profiles only (repeatable):
bash ~/.hermes/skills/revenium/scripts/install.sh --profile gtm --profile qa
```

Key flags (full list: `install.sh --help`):

- `--all-profiles` / `--profile <name>` — fleet install (per-profile plugin,
  hooks with `hooks_auto_accept`, and a unique cron marker).
- `--organization-name <name>` — the **ORGANIZATION** dimension (a company/
  product, e.g. `tableforone`). **Not** the agent. Persisted even with
  `--skip-guardrails`.
- `--hard-limit N --period P` — non-interactive budget rule.
- `--non-interactive`, `--shadow-mode`, `--skip-guardrails`, `--skip-cron`,
  `--no-restart`.

### 3. Deployment-mode note (fleets)

The same install supports both modes without extra flags:

- **One process per profile** (default): each gateway runs with its own
  `HERMES_HOME`.
- **Multiplexed single gateway** (`gateway.multiplex_profiles: true`): one
  gateway serves all profiles; the classifier resolves each profile's own
  home/state.db/markers per session from the `agent:<profile>:…` namespace.

## Verify (always do this — a silent install is the failure mode)

```sh
# 1. Cron installed (one line per metered profile):
crontab -l | grep hermes-revenium-metering

# 2. Hooks registered AND firing (exit 0 = firing; 1 = not registered; 2 = registered-but-idle):
bash ~/.hermes/skills/revenium/scripts/hooks-status.sh; echo "exit=$?"

# 3. Guardrail rules configured:
python3 -c "import json;print(json.load(open('$HOME/.hermes/state/revenium/config.json')).get('ruleIds'))"

# 4. Wait one cron tick (<=60s), then confirm the guardrail snapshot is fresh:
cat ~/.hermes/state/revenium/guardrail-status.json

# 5. Metering is happening (recent Reported lines, no repeated Failed):
tail -n 40 ~/.hermes/state/revenium/revenium-metering.log
```

For a fleet, run checks 1–5 per profile with the profile's home, e.g.:

```sh
HERMES_HOME=~/.hermes/profiles/gtm REVENIUM_STATE_DIR=~/.hermes/profiles/gtm/state/revenium \
  bash ~/.hermes/skills/revenium/scripts/hooks-status.sh
tail -n 20 ~/.hermes/profiles/gtm/state/revenium/revenium-metering.log
```

Confirm in the Revenium UI that completions carry a real `task-type` (not all
`unclassified`) and that `revenium jobs transactions <agenticJobId>` returns
transactions.

## Troubleshoot

Route the symptom through **[`references/decision-tree.md`](references/decision-tree.md)**.
It maps each known failure mode (no job transactions, `teamId is required`, inert
hooks, orphaned cron, `unclassified` spend, one-profile-only metering, multiplex
markers in the wrong home) to the exact remediation command.

## Uninstall

```sh
bash ~/.hermes/skills/revenium/scripts/uninstall-cron.sh   # removes ALL metering cron lines (every profile + fleet wrapper)
bash ~/.hermes/skills/revenium/scripts/uninstall-hooks.sh  # removes the shell hooks
```

## Reference

- Operational depth (per-agent attribution, org-vs-agent, settle sizing,
  `hooks_auto_accept`, multiplex): `~/.hermes/skills/revenium/references/setup.md`
  (repo: `skills/revenium/references/setup.md`).
- Failure-mode decision tree: [`references/decision-tree.md`](references/decision-tree.md).
