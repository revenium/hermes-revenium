# Upgrading

[← Documentation index](README.md)

Re-run `install.sh` to upgrade. It is idempotent: configured steps are skipped,
and it creates no duplicate rules or cron lines.

Every upgrade must copy the new files to the host and re-sync the plugin. Refreshing
`~/.hermes/skills/` alone leaves the active copy at
`~/.hermes/plugins/` stale. `install.sh` handles the second for you.

> On a multi-profile host, repeat `--profile` / `--all-profiles` on every upgrade.
> The skill tree at `~/.hermes/skills/revenium/` is shared, so refreshing it updates the
> *scripts* for every profile at once. The classifier is not shared: it is copied into
> each profile's own `plugins/` directory, and nothing copies over it unless you name that
> profile again. An upgrade that omits the flag leaves every profile running the old
> classifier while the shared scripts are updated without an error or warning. Restart the gateway
> afterwards, or the refreshed plugin still will not load.

Pick the path that matches what the host can reach.

## Option A — the host has the repo, or internet access

```bash
ssh <host>
cd /path/to/hermes-revenium && git pull   # or clone it
bash install.sh
```

`install.sh` re-copies the skill and the plugin, re-runs hooks, cron, and guardrails, and
restarts the gateway.

## Option B — push from your machine with rsync

```bash
# from the repo root locally — note the absent --delete
rsync -av -e ssh skills/revenium/ <user>@<host>:~/.hermes/skills/revenium/

# then re-run the installer on the host; it skips credentials already in
# `revenium config show`. Add --profile <name> / --all-profiles on a fleet.
ssh <user>@<host> 'bash ~/.hermes/skills/revenium/scripts/install.sh'
```

> Do not add `--delete`. Operators may keep host-only scripts beside the shipped ones, such
> as a fleet cron wrapper. `--delete` removes them, and
> if the crontab invokes one, metering stops silently across every profile. Sync without
> it, or use Option D, which overlays by design.

Where `revenium` and `hermes` are not on the bare login `PATH` — Linuxbrew installs, most
often — prefix the remote command:

```bash
PATH="/home/linuxbrew/.linuxbrew/bin:$HOME/.local/bin:$PATH" \
  bash ~/.hermes/skills/revenium/scripts/install.sh
```

## Option C — the native install path

```bash
ssh <host>
hermes skills install revenium/hermes-revenium/skills/revenium   # re-fetch the skill
bash ~/.hermes/skills/revenium/scripts/install.sh                # complete setup
```

## Option D — `bootstrap.sh --update`, with no repo and no rsync

The native path refreshes `SKILL.md` and `references/`, never `scripts/` or `plugins/`.
The bootstrap skips its fetch whenever `scripts/` already exists, so on a host that
installed once, re-running it silently hands off to the *old* installer. `--update` forces
the re-fetch:

```bash
bash ~/.hermes/skills/revenium/references/bootstrap.sh --update                  # default profile
bash ~/.hermes/skills/revenium/references/bootstrap.sh --update --profile ent    # one profile
bash ~/.hermes/skills/revenium/references/bootstrap.sh --update --all-profiles   # whole fleet
```

The bootstrap consumes `--update` and passes every other flag through to `install.sh`.
This refresh overlays rather than replaces, so host-only scripts survive. Unlike this
path, `git clone && bash install.sh` removes the skill
directory first.

A `bootstrap.sh` predating `--update` rejects the flag. Refresh that one file first:

```bash
curl -fsSL https://raw.githubusercontent.com/revenium/hermes-revenium/main/skills/revenium/references/bootstrap.sh \
  -o ~/.hermes/skills/revenium/references/bootstrap.sh
```

## What this release changes on an install that adopts none of it

This section states the closing scope precisely, in the terms this skill's own
tests hold it to. This release ships new capabilities that are, deliberately,
almost entirely inert until turned on. What is asserted here is narrow: **the
argv crossing the wire — the metering requests this skill sends to
Revenium — is byte-identical to the previous release.** That is not a claim
that nothing resolves differently internally, only that nothing different
leaves the wire. Read the distinction carefully; a later reader stretching
this claim into a statement about internal resolution would be wrong to.

Four different shapes turn a capability off:

- **An explicit switch.** `REVENIUM_AUX_METERING`, readable from the
  environment or from the `auxMetering` key in `config.json` with the
  environment taking precedence, defaults to `enabled`. Set it to `disabled`
  to turn auxiliary-usage metering off. An unrecognised value falls back to
  the default *with a warning* rather than silently changing billing
  behaviour — see [Auxiliary usage migration](migration-auxiliary-usage.md)
  for the full shape of this switch.
- **A capability probe that is negative on every CLI in existence today.**
  `correct-assessment.sh` probes `jobs outcome-update --help` for
  `--expected-entity-version` before attaching it to a correction. The whole
  positive branch is written and tested and does not run, because no shipped
  `revenium` CLI advertises that flag. See [the CLI-verb ask](cli-verb-ask.md)
  for what would need to ship for that to change.
- **A config-absent default.** The valuation seam this milestone built
  resolves to this skill's own local (hours × rate) valuation whenever no
  `valuationSource` is configured. There is no switch to set here; the
  default *is* the absence of configuration.
- **No switch at all.** The fourth shape, and the one that needs the most
  care — see the next section.

### The one change with no switch

Per-session profile resolution — introduced to close a multiplexed-profile
metering gap — now reads the session row's `profile_name` column instead of
pattern-matching the session id. It has no off switch and engages
unconditionally wherever that column resolves to a usable value.

This is a **bug fix, not a feature**: the code it replaced applied a
session-key-shaped pattern (`agent:<profile>:...`) to a session id and
matched no real session id on any measured host, so it was inert rather than
correct. An install adopting none of this release still gets this change,
deliberately, the same way it would get any other bug fix.

Its boundary is proven, not assumed. On a single-profile install — no
`profiles/` directory on disk — resolution falls to the process-level paths
and the reporter's argv is unchanged, proven byte-for-byte against
`tests/fixtures/compat/meter-completion.golden.json` by
`tests/test_phase60_feature_off_closeout.py`. On a multiplexed install,
resolution is *deliberately different* — that difference is the defect being
fixed, not a regression against this claim. This document does not claim
anything about multiplexed-host behaviour beyond that it differs; the
proof above covers the single-profile install and the reporter's argv only.

### Why the golden fixtures are trustworthy evidence

`tests/fixtures/compat/jobs-outcome-update.golden.json` pins the feature-off
shape every `revenium` CLI in existence produces today; its sibling,
`jobs-outcome-update-versioned.golden.json`, pins the positive-probe arm and
is explicitly *not* part of this claim. Neither fixture pins what a test
produces instead of what production sends — that recurring failure mode in
this project's history is what `SidecarFixtureFidelityTests` in
`tests/test_phase38_reporter_path.py` exists to catch structurally, by
diffing the shipped script's own metadata keys against the fixture's, rather
than trusting that a fixture and its script still agree.

## After any upgrade

Restart the gateway. A refreshed plugin on disk is not a loaded plugin; the running
gateway keeps serving what it started with. `install.sh` restarts it unless you passed
`--no-restart`. On a multi-profile host, confirm which process actually serves each
profile — see [the fleet guide](fleet.md).

Sync the plugin if you copied only the skill. Anything short of `install.sh` leaves
`~/.hermes/plugins/revenium-classifier/` on the old version:

```bash
bash ~/.hermes/skills/revenium/scripts/install-plugin.sh
```

Delete any `.bak` copies of the skill under `~/.hermes/skills/`. Plugin discovery
scans their bundled `plugins/` directories, and a stale duplicate can shadow the real one.

Auxiliary usage metering turns on with this upgrade. Reported spend increases
permanently against unchanged traffic — nothing about your traffic changes, but a
category of spend that was never reported before now is. The first tick after upgrading
additionally reports each identity's whole accumulated pre-upgrade auxiliary usage,
because the counters are cumulative and the new ledger starts empty. If you run an
autonomous-mode guardrail close to its limit, read
[Auxiliary usage migration](migration-auxiliary-usage.md) before upgrading. The off
switch is `REVENIUM_AUX_METERING=disabled`.

Verify with `diagnose.sh`. It produces one read-only report covering credentials, cron,
ledgers, the settle gate, plugin and hook state, and a per-profile summary:

```bash
bash ~/.hermes/skills/revenium/scripts/diagnose.sh              # default home
bash ~/.hermes/skills/revenium/scripts/diagnose.sh --profile ent
```

For a narrower check, `hooks-status.sh` and
`crontab -l | grep hermes-revenium-metering` still work. On a fleet, expect one crontab
line per profile (`# hermes-revenium-metering-<profile>`), not just the bare
`# hermes-revenium-metering` of the default home.

For CI or other non-interactive upgrades, `install.sh --non-interactive` takes credentials
from `REVENIUM_API_KEY`, `REVENIUM_TEAM_ID`, `REVENIUM_TENANT_ID`, and
`REVENIUM_OWNER_ID`.
