# Multi-profile / fleet installs

[← Documentation index](README.md)

A Hermes profile is a separate Hermes home under `~/.hermes/profiles/<name>/`; the default
profile uses `~/.hermes/` directly. Every command in these docs is scoped to one home, and
the default home is not a superset of the others. A profile you never name gets no plugin,
no hooks, and no cron, and meters nothing — while the default profile keeps working, so
the host looks healthy.

To wire a fleet, name the profiles:

```bash
bash ~/.hermes/skills/revenium/scripts/install.sh --all-profiles
# or specific profiles:
bash ~/.hermes/skills/revenium/scripts/install.sh --profile gtm --profile qa
```

That installs plugin, hooks, and cron once per profile home, and gives each one:

**A distinct AGENT.** `REVENIUM_AGENT_NAME` defaults to `Hermes-<profile>`; the default
profile stays `Hermes`. Revenium then separates spend per agent.

This is the AGENT dimension, not the ORGANIZATION dimension. `organizationName` names a
company or product (`tableforone`, say) and is threaded through completions, tool-events,
and `jobs create` alike, so a job and its transactions share one org. Never set it to an
agent name. Set it non-interactively with `--organization-name <name>` on `install.sh` or
`setup-guardrails.sh`; it persists to each profile's `config.json` even under
`--skip-guardrails`.

**A unique crontab marker,** `# hermes-revenium-metering-<profile>`, so a second profile
install never clobbers the first. `uninstall-cron.sh` removes every profile's line, and
lines orphaned by a `~/.hermes` reset are reconciled automatically.

**`hooks_auto_accept: true`.** A headless profile gateway never shows the hook-approval
prompt, so without this the hooks stay inert forever. Fleet installs set it automatically
via `install-hooks.sh --auto-accept`. For a shadow or metering-only profile, register just
the observer with `install-hooks.sh --metering-only`.

**Optionally, one shared SQUAD identity.** Set `REVENIUM_SQUAD_NAME` to group every
profile's completions under a single squad name, distinct from the per-profile AGENT. See
[`references/setup.md`](../skills/revenium/references/setup.md) → *Squad grouping across
the fleet* for the resolution order and the recipe.

## Per-profile facts that bite

Each of these caused a real outage where the symptom pointed nowhere near the cause.

### The process serving the profile must restart before its plugin loads — and it is often not the gateway

Plugin discovery is per-profile, and the classifier is *copied* into
`~/.hermes/profiles/<name>/plugins/`. Whatever process serves that profile keeps running
the code it started with. Until it restarts, the profile meters normally and classifies
nothing: no markers, no jobs, `traceType: uncategorized`, no tool-events, and no error
anywhere.

Find the real owner before restarting anything:

```bash
ps -axo pid,lstart,command | grep -E 'hermes.*(serve|gateway run)' | grep -v grep
```

- `gateway run` → `hermes gateway restart` (or `hermes-gateways restart`). Check its
  `HERMES_HOME` first: on a desktop host it commonly serves only the default home and
  touches no profile at all.
- `--profile <name> serve` → spawned by the Hermes desktop app. Quit and reopen the app;
  restarting the gateway does nothing for these. Seen live: a nine-day-old `serve` process
  still answering requests while a freshly restarted gateway sat beside it classifying
  nothing.

`install.sh` restarts the gateway for you, which covers the gateway case and only that
case.

### "Registered" is not "loaded"

`plugin-status.sh` reports registration as recorded in `config.yaml`. That a plugin is
listed says nothing about whether the live gateway loaded it. Confirm with markers.

### Upgrades must name the profiles again

The skill tree is shared, but the classifier is copied per profile, so an upgrade that
omits the flag leaves every profile on the old plugin. See [Upgrading](upgrading.md).

### Fleet mode never prompts, so it skips guardrail creation

Unless you pass both `--hard-limit` and `--period`, each profile is wired for metering
with no budget rule. The installer says so at the end.

### Dashboards must filter on the per-profile agent

Spend for profile `ent` arrives as agent `Hermes-ent`. A view scoped to `Hermes` will not
show it, and a budget rule filtered `AGENT:IS:Hermes` will never match it.

### State is per-profile too

Ledgers, markers, `config.json`, and `guardrail-status.json` all live under
`~/.hermes/profiles/<name>/state/revenium/`. Point diagnostics at the profile you mean:

```bash
bash ~/.hermes/skills/revenium/scripts/diagnose.sh --profile ent
```

With no flag, `diagnose.sh` reads the default profile. Reading the wrong home is the
easiest way to conclude that nothing is being metered. Its last section lists every
profile's ledger size and last cron run, which is the fastest way to spot one profile that
has gone quiet.

## Deployment modes

Both work. One process per profile is the straightforward case. The multiplexed single
gateway (`gateway.multiplex_profiles: true`) also works: the classifier resolves the
owning profile's home, `state.db`, and markers per session from the `agent:<profile>:…`
namespace.

Either way, size `REVENIUM_CRON_SETTLE_SECONDS` (default 600s) above worst-case
job-inference latency. Metering a session before its marker lands orphans that completion
from its job permanently.

The full operational guide is
[`references/setup.md`](../skills/revenium/references/setup.md) → *Multi-profile / fleet
installs*.
