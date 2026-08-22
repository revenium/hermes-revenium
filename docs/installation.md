# Installation

[← Documentation index](README.md)

Installing has two halves: get the skill onto the host, then wire it into Hermes.
Option 1 does both. The other three do only the first, and you finish with
[Set up guardrails, cron, and hooks](#set-up-guardrails-cron-and-hooks).

## Install paths

### Option 1: `hermes skills install` (recommended)

```bash
hermes skills install revenium/hermes-revenium/skills/revenium
bash ~/.hermes/skills/revenium/references/bootstrap.sh
```

The first command uses Hermes' native install path, which ships `SKILL.md` plus only the
support files `SKILL.md` names as bundle-relative paths. `references/bootstrap.sh` is one
of them. `plugins/` is not, and cannot be: Hermes disallows a `plugins/` directory in a
skill bundle outright, so the classifier can never arrive this way.

That is what the second command is for. It fetches the missing `scripts/` and `plugins/`
into `~/.hermes/skills/revenium/`, then completes setup — credentials, plugin, hooks,
guardrail rule, cron, gateway restart. Flags pass straight through to `install.sh`; see
[Set up guardrails, cron, and hooks](#set-up-guardrails-cron-and-hooks) for the list.

If `references/bootstrap.sh` did not come down either, clone and install directly:

```bash
git clone --depth 1 https://github.com/revenium/hermes-revenium.git /tmp/hermes-revenium
bash /tmp/hermes-revenium/install.sh
```

To refresh an existing install, use `bootstrap.sh --update`. Without that flag the
bootstrap sees a populated `scripts/` and skips the fetch, so the host keeps running
whatever it downloaded the first time. See [Upgrading](upgrading.md).

#### What the security scanner reports

The skill scans **`SAFE`** and installs without `--force`. Hermes still shows its standard
third-party disclaimer and asks you to confirm; that prompt applies to every external
skill, not to this one.

The scan does report two `MEDIUM` findings. Both describe behaviour the skill genuinely
has:

- **`persistence`** — the `crontab` calls in the cron scripts and setup docs. This is the
  per-minute metering loop. It is intentional, fully disclosed, and removing it would
  break the skill's core function.
- **`supply_chain`** — the `git clone` line in the documented install path above.

An earlier `HIGH exfiltration` finding was cleared in v1.1 and no longer appears. The
scanner had read `os.environ` in the Python heredocs as a credential dump; those heredocs
pass file paths and computed deltas.

> Observed 2026-08-21 against scanner `skills-guard-v1` (rules `git_clone`,
> `persistence_cron`). Hermes' scanner produces this verdict, not this repo, so it can
> change independently of anything here. If you get `CAUTION` or `DANGEROUS`, please
> [open an issue](https://github.com/revenium/hermes-revenium/issues) — that difference is
> worth knowing about.

To verify the behaviour yourself, read
[`skills/revenium/scripts/`](../skills/revenium/scripts/) before installing.

### Option 2: External directory (for contributors)

Point Hermes at this repo's `skills/` directory:

```yaml
# ~/.hermes/config.yaml
skills:
  external_dirs:
    - /absolute/path/to/hermes-revenium/skills
```

Restart Hermes or start a new session. External skill directories are read-only discovery
sources, and a local `~/.hermes/skills/` install wins on a name collision.

### Option 3: Local copy

```bash
mkdir -p ~/.hermes/skills
cp -R skills/revenium ~/.hermes/skills/
```

Or run the bundled helper, which copies the skill and the plugin together:

```bash
bash install.sh
```

### Option 4: Publish

To make the skill discoverable through Hermes' skill index:

```bash
hermes skills publish skills/revenium --to github --repo revenium/hermes-revenium
```

## Set up guardrails, cron, and hooks

**Option 1 already did this.** Read on if you installed another way, or want to re-run a
single step.

```bash
bash ~/.hermes/skills/revenium/scripts/install.sh
```

That one command runs every step in this section in order: credentials, plugin, hooks,
guardrail rule, cron, gateway restart. It is idempotent — already-configured steps are
skipped, so re-running it is how you upgrade.

| Flag | Effect |
|---|---|
| `--hard-limit N --period P` | Set the budget without prompting |
| `--organization-name <name>` | Set the ORGANIZATION dimension |
| `--non-interactive` | Take credentials from the `REVENIUM_*` environment variables |
| `--profile <name>`, `--all-profiles` | Wire a fleet — see [Multi-profile installs](fleet.md) |
| `--shadow-mode` | Compute without shipping |
| `--skip-guardrails`, `--skip-cron`, `--no-restart` | Omit a step |

`install.sh` only orchestrates the scripts below. Run them yourself if you need to
customize one.

### Credentials (all four required)

An API key alone is not enough. It meters completions fine, then fails every `guardrails`
and `jobs create` call with `HTTP 400: teamId is required`. You need four:

```bash
revenium config show                         # check what's configured
revenium config set key       <API_KEY>
revenium config set team-id   <TEAM_ID>
revenium config set tenant-id <TENANT_ID>
revenium config set owner-id  <OWNER_ID>
```

On every interactive run, `install.sh` walks the whole `revenium` CLI config — API URL,
API key, Team ID, Tenant ID, Owner ID — showing each current value in brackets as the
default. Enter keeps it; typing replaces it. It confirms rather than silently skipping
because an API URL pointing at the wrong environment is otherwise invisible until it
surfaces as an opaque `HTTP 403` on guardrail-rule creation.

### Guardrail budget rules

```bash
bash ~/.hermes/skills/revenium/scripts/setup-guardrails.sh --interactive
```

The script asks for a hard limit, period, organization name, autonomous mode, and
notification channel, and optionally for per-task-type rules. It then creates the Revenium
budget rules and writes `ruleIds` into `~/.hermes/state/revenium/config.json`. It needs
the four credentials above.

Installs still carrying a legacy `alertId` migrate on the first cron tick — see
[Guardrails migration](migration-guardrails.md).

### The per-minute metering cron

```bash
bash ~/.hermes/skills/revenium/scripts/install-cron.sh
```

The cron meters `~/.hermes/state.db` into Revenium and refreshes
`~/.hermes/state/revenium/guardrail-status.json`. Hermes cannot add crontab entries
itself, so this step stays manual. Skip it and the agent reports "Guardrail status not yet
available" before every operation, which is the skill correctly detecting that the cron
never ran.

Where 60 seconds is too slow — a demo, a live dashboard — install a sub-minute interval.
The cron still fires once a minute; the pipeline loops inside each tick.

```bash
bash ~/.hermes/skills/revenium/scripts/install-cron.sh --interval-seconds 15
# 4× per minute, and 4× the revenium-CLI calls.

bash ~/.hermes/skills/revenium/scripts/install-cron.sh --interval-seconds 15 --force
# --force replaces an existing entry, which is how you change the interval.
```

Valid intervals are `1..60`. `--dry-run` prints the crontab line without installing it.

### The Hermes shell hooks

```bash
bash ~/.hermes/skills/revenium/scripts/install-hooks.sh
```

This registers the `pre_llm_call`, `pre_tool_call`, and `post_tool_call` handlers in
`~/.hermes/config.yaml`. They stay inert until you approve them at the prompt Hermes shows
the first time each one fires. Without them, budget enforcement and tool-event capture do
nothing.

### The classifier plugin

```bash
bash ~/.hermes/skills/revenium/scripts/install-plugin.sh
```

Hermes loads plugins from `~/.hermes/plugins/`, a different root from the
`~/.hermes/skills/` tree the skill installs into, and neither `hermes skills install` nor
`external_dirs` relocates a bundled `plugins/` directory. This script bridges that gap: it
copies `revenium-classifier` into `~/.hermes/plugins/`, adds it to `plugins.enabled` in
`~/.hermes/config.yaml`, and restarts the gateway.

Skip it and completion metering still works, but nothing writes `kind:"job"` markers, so
agentic-job usage never reaches Revenium. Re-run it after every skill upgrade; it is
idempotent. `--dry-run` previews, `--no-restart` leaves the gateway alone.

## First-time setup

`setup-guardrails.sh --interactive` drives the guided flow. You can reach it three ways:
`install.sh` runs it, you can invoke it directly, or you can type `/revenium` inside a
Hermes session. When no `config.json` or `ruleIds` exists, the skill starts setup on its
own; once configured, `/revenium` offers status and reconfigure instead.

The flow:

1. **Check credentials.** `setup-guardrails.sh` does not prompt for them — it only checks
   that a Team ID resolves, and exits if not, because budget-rule creation fails without
   one. Set them with `install.sh` or `revenium config set`.
2. **Ask for an organization name**, optionally, for Revenium reporting attribution.
3. **Ask for a hard limit, warn threshold, and period** (`DAILY`, `WEEKLY`, `MONTHLY`,
   `QUARTERLY`).
4. **Ask whether the agent runs autonomously**, and if so which Hermes messaging channel
   should receive halt notifications.
5. **Create the budget rule** via `revenium guardrails budget-rules create` and write
   `ruleIds` into `~/.hermes/state/revenium/config.json`.

Setup is atomic: if a step fails, no partial config is written. The step-by-step flow
lives in [`references/setup.md`](../skills/revenium/references/setup.md).

## Verify the install

```bash
crontab -l | grep hermes-revenium-metering         # one entry
grep hermes-revenium-hooks ~/.hermes/config.yaml   # 3 hook commands registered
grep post_tool_call ~/.hermes/config.yaml          # post_tool_call hook present
jq '.ruleIds' ~/.hermes/state/revenium/config.json # non-empty array
```

Wait one cron tick, then confirm the guardrail snapshot exists and carries rules:

```bash
cat ~/.hermes/state/revenium/guardrail-status.json  # expect rules[] populated
tail -f ~/.hermes/state/revenium/revenium-metering.log
```

For a single read-only report covering all of the above plus ledgers, the settle gate, and
plugin state, run `diagnose.sh`:

```bash
bash ~/.hermes/skills/revenium/scripts/diagnose.sh
```

When a block-band rule fires under autonomous mode, the agent emits this directive
verbatim, with values substituted from `guardrail-status.json::haltedRule`:

```
Guardrail halt active — rule '[name]' ([metricType], [windowType]) at [currentValue] of [hardLimit] hard-limit. To resume: `bash ~/.hermes/skills/revenium/scripts/clear-halt.sh`
```
