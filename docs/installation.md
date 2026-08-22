# Installation

[← Documentation index](README.md)

## Install paths

### Option 1: `hermes skills install` (recommended)

```bash
hermes skills install revenium/hermes-revenium/skills/revenium
bash ~/.hermes/skills/revenium/references/bootstrap.sh
```

The first command installs the skill via Hermes' native install path. That path ships `SKILL.md` plus only the support files `SKILL.md` names as bundle-relative paths — `references/bootstrap.sh` among them — and never `plugins/`, which Hermes disallows in a skill bundle outright. So the bootstrap fetches the missing `scripts/` + `plugins/` into `~/.hermes/skills/revenium/` and then completes setup — credentials, plugin, hooks, guardrail rule, cron, and gateway restart. See [Required: set up guardrails, cron, and hooks](#required-set-up-guardrails-cron-and-hooks) for what `install.sh` covers and the flags it accepts.

#### What the security scanner reports

The skill scans **`SAFE`** and installs without `--force`. Hermes still shows its
standard third-party disclaimer and asks you to confirm — that prompt applies to every
external skill, not to this one specifically.

The scan does surface `MEDIUM` findings. They are expected, and both categories describe
behaviour the skill genuinely has:

- **`persistence`** — `crontab` references in the cron scripts and setup docs. This is the
  load-bearing per-minute metering loop; it is intentional, fully disclosed, and cannot be
  removed without breaking the skill's core function.
- **`supply_chain`** — a `git clone` line in the documented install path.

An earlier `HIGH exfiltration` finding — the scanner reading `os.environ` in Python
heredocs as a potential credential dump — was cleared in v1.1 and no longer appears. Those
heredocs pass file paths and computed deltas, never credentials.

> Observed 2026-08-21 against scanner `skills-guard-v1` (rules `git_clone`,
> `persistence_cron`). The verdict is produced by Hermes' scanner, not by this repo, so it
> can change independently of anything here. If you get a `CAUTION` or `DANGEROUS` verdict,
> please [open an issue](https://github.com/revenium/hermes-revenium/issues) — that is a
> difference worth knowing about.

Review [`skills/revenium/scripts/`](../skills/revenium/scripts/) before installing if you want
to verify the behaviour yourself.

### Option 2: Local development (for contributors)

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
bash install.sh
```

### Option 4: Publish

To make this skill discoverable through Hermes' skill index:

```bash
hermes skills publish skills/revenium --to github --repo revenium/hermes-revenium
```


## Set up guardrails, cron, and hooks

**Option 1 (`hermes skills install` + `install.sh`) already ran this for you.** This section applies if you installed the skill another way (external_dirs, manual copy), or want to re-run/customize a step. Run the one-command installer:

```bash
bash ~/.hermes/skills/revenium/scripts/install.sh
```

It performs every step in this section in order — credentials, plugin, hooks, guardrail rule, cron, gateway restart — and is **idempotent** (already-configured steps are skipped on re-run). Flags: `--hard-limit N --period P` (non-interactive budget), `--non-interactive` (creds from `REVENIUM_*` env vars), `--shadow-mode`, `--skip-guardrails`, `--skip-cron`, `--no-restart`, `--help`.

If you'd rather run the steps yourself (or need to customize one), the individual scripts are documented below — `install.sh` is just an orchestrator over them.

### Credentials (all four required)

`install.sh` walks the whole `revenium` CLI config — **API URL, API key, Team ID, Tenant ID, and Owner ID** — on every interactive run, showing each current value in brackets as the default. Enter keeps it; typing replaces it; the result is persisted with `revenium config set`. Confirming rather than silently skipping is deliberate: an API URL left pointing at the wrong environment is invisible otherwise, and only shows up later as an opaque `HTTP 403` on guardrail-rule creation. All four ids matter: a config with only an API key meters completions fine but fails every `guardrails`/`jobs create` with `HTTP 400: teamId is required` — the API key alone is not enough. To set them manually:

```bash
revenium config show                         # check what's configured
revenium config set key       <API_KEY>
revenium config set team-id   <TEAM_ID>
revenium config set tenant-id <TENANT_ID>
revenium config set owner-id  <OWNER_ID>
```

### Set up guardrail budget rules

```bash
bash ~/.hermes/skills/revenium/scripts/setup-guardrails.sh --interactive
```

The script prompts for budget hard-limit, period, organization name, autonomous mode and notification channel/target, and optionally per-task-type rules. On success it creates Revenium guardrail budget rules and writes `ruleIds` into `~/.hermes/state/revenium/config.json`. Requires the four credentials above. Legacy `alertId` installs auto-migrate on the first cron tick — see [`docs/migration-guardrails.md`](migration-guardrails.md).

### Install the per-minute metering cron

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

### Install the Hermes shell hooks

```bash
bash ~/.hermes/skills/revenium/scripts/install-hooks.sh
```

The shell hooks register `pre_llm_call`, `pre_tool_call`, and `post_tool_call` handlers in `~/.hermes/config.yaml`. They are inert until you approve them on first `hermes chat`. Without the hooks, structural budget enforcement and tool-event capture are inactive.

### Install the classifier plugin

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

The guided Setup Flow is driven by `setup-guardrails.sh --interactive` (run for you by `install.sh`, invokable directly, or available at any time via `/revenium` inside a Hermes session). The skill detects that no `config.json` or `ruleIds` exists and automatically begins setup. Once configured, invoking `/revenium` instead offers status and reconfigure options. The script will:

1. Verify the `revenium` CLI already has all four credentials configured (API key, Team ID, Tenant ID, Owner ID). **`setup-guardrails.sh` does not prompt for credentials** — it only checks that a Team ID resolves, and exits with an error if not, since budget-rule creation fails without one. Credentials are set up by `install.sh` (which prompts for any that are missing) or manually with `revenium config set` (see [Credentials (all four required)](#credentials-all-four-required)). Run `revenium config show` to check what's configured.
2. Optionally ask for an organization name (for Revenium reporting attribution).
3. Ask for a budget hard-limit, warn threshold, and period (`DAILY`, `WEEKLY`, `MONTHLY`, `QUARTERLY`).
4. Ask whether the agent runs autonomously and, if so, which Hermes messaging channel should receive halt notifications.
5. Create a Revenium guardrail budget rule via `revenium guardrails budget-rules create` and write `ruleIds` into `~/.hermes/state/revenium/config.json`.

Setup is atomic — if any step fails, no partial config is written. The full step-by-step flow lives in [`skills/revenium/references/setup.md`](../skills/revenium/references/setup.md).


## Verify the install

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

