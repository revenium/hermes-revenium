# Upgrading on a remote host

[← Documentation index](README.md)

Re-running `install.sh` **is** the upgrade — it is idempotent (already-configured steps are skipped, no duplicate rules or cron lines). Two things matter on every upgrade: get the new bytes onto the host, and re-sync the **plugin** (updating only `~/.hermes/skills/` leaves the active plugin at `~/.hermes/plugins/` stale). `install.sh` handles the plugin for you.

> **On a multi-profile host, repeat `--profile` / `--all-profiles` on every upgrade.**
> The skill tree at `~/.hermes/skills/revenium/` is shared, so refreshing it updates
> the *scripts* for every profile at once — but the classifier is `cp -R`'d into each
> profile's own `plugins/` dir, and nothing copies over it unless that profile is named
> again. An upgrade that omits the flag leaves every profile running the old classifier
> while the shared scripts move on, with no error and no warning. Restart the gateway
> afterwards or the refreshed plugin still will not load.

## Option A — host has the repo (or internet access)

```bash
ssh <host>
cd /path/to/hermes-revenium && git pull   # or: git clone https://github.com/revenium/hermes-revenium
bash install.sh                           # re-copies skill+plugin, re-runs hooks/cron/guardrails, restarts gateway
```

## Option B — push from your machine via rsync

```bash
# from the repo root locally — NOTE: no --delete, see the warning below
rsync -av -e ssh skills/revenium/ <user>@<host>:~/.hermes/skills/revenium/

# then on the host, re-run the installer (skips creds already in 'revenium config show')
# add --profile <name> / --all-profiles on a multi-profile host
ssh <user>@<host> 'bash ~/.hermes/skills/revenium/scripts/install.sh'
```

> **Do not add `--delete`.** Operators keep host-only scripts beside the shipped ones —
> a fleet cron wrapper, for instance — that exist in no clone. `--delete` removes them,
> and if the crontab invokes one, metering across every profile stops silently. Sync
> without it, or use Option D, which overlays by design.

> On hosts where `revenium`/`hermes` aren't on the bare login `PATH` (e.g. Linuxbrew installs), prefix the remote command: `PATH="/home/linuxbrew/.linuxbrew/bin:$HOME/.local/bin:$PATH" bash ~/.hermes/skills/revenium/scripts/install.sh`.

## Option C — native install path

```bash
ssh <host>
hermes skills install revenium/hermes-revenium/skills/revenium   # re-fetch the skill
bash ~/.hermes/skills/revenium/scripts/install.sh                        # complete setup
```

## Option D — `bootstrap.sh --update` (no repo, no rsync)

The native path refreshes `SKILL.md` and `references/` but never `scripts/` or
`plugins/`, and the bootstrap **skips the fetch** whenever `scripts/` already exists —
so on a host that installed once, re-running it silently hands off to the *old*
installer. `--update` forces the re-fetch:

```bash
bash ~/.hermes/skills/revenium/references/bootstrap.sh --update                  # default profile
bash ~/.hermes/skills/revenium/references/bootstrap.sh --update --profile ent    # one profile
bash ~/.hermes/skills/revenium/references/bootstrap.sh --update --all-profiles   # whole fleet
```

`--update` is consumed by the bootstrap; every other flag passes straight through to
`install.sh`. The refresh **overlays** rather than replacing, so host-only scripts
survive — which is why this is safer than `git clone && bash install.sh`, whose root
installer does `rm -rf` on the skill directory first.

If the host's own `bootstrap.sh` predates `--update` it will reject the flag; refresh
that one file first:

```bash
curl -fsSL https://raw.githubusercontent.com/revenium/hermes-revenium/main/skills/revenium/references/bootstrap.sh \
  -o ~/.hermes/skills/revenium/references/bootstrap.sh
```

## After any upgrade

- If you copied only the skill (not via `install.sh`), run `bash ~/.hermes/skills/revenium/scripts/install-plugin.sh` so `~/.hermes/plugins/revenium-classifier/` gets the new version and the gateway restarts.
- **Don't leave `.bak` copies** of the skill under `~/.hermes/skills/` — plugin discovery scans their bundled `plugins/` dirs and a stale duplicate can shadow the real one.
- **Restart the gateway.** A refreshed plugin on disk is not a loaded plugin — the
  running gateway keeps serving what it started with. `install.sh` does this unless
  you passed `--no-restart`.
- Verify: `bash ~/.hermes/skills/revenium/scripts/diagnose.sh` — one read-only report
  covering credentials, cron, ledgers, the settle gate, plugin/hook state and a
  per-profile summary. Add `--profile <name>` for a fleet member; without it you are
  reading the default home. `hooks-status.sh` and
  `crontab -l | grep hermes-revenium-metering` remain available for a narrower check.
- On a fleet, confirm one crontab line **per profile** (`# hermes-revenium-metering-<profile>`),
  not just the bare `# hermes-revenium-metering` of the default home.

For non-interactive/CI upgrades, `install.sh --non-interactive` takes credentials from the `REVENIUM_API_KEY` / `REVENIUM_TEAM_ID` / `REVENIUM_TENANT_ID` / `REVENIUM_OWNER_ID` env vars.

