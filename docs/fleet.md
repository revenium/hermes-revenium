# Multi-profile / fleet installs

[← Documentation index](README.md)

A Hermes [profile](https://github.com/revenium/hermes-revenium) is a separate Hermes home under `~/.hermes/profiles/<name>/` (the default profile uses `~/.hermes/` directly). To meter a fleet of profiles, add `--all-profiles` (or `--profile <name>`, repeatable) to the installer:

```bash
bash ~/.hermes/skills/revenium/scripts/install.sh --all-profiles
# or specific profiles:
bash ~/.hermes/skills/revenium/scripts/install.sh --profile gtm --profile qa
```

This wires plugin + hooks + cron once per profile home, each with:

- **A distinct AGENT** — `REVENIUM_AGENT_NAME` defaults to `Hermes-<profile>` (the default profile stays `Hermes`), so Revenium separates spend per agent. This is the **AGENT** dimension, *not* the ORGANIZATION dimension: `organizationName` is a company/product (e.g. `tableforone`) and is threaded through completions, tool-events, **and** `jobs create` so a job and its transactions share one org — never set it to an agent name. Set the org non-interactively with `--organization-name <name>` on `install.sh` (or `setup-guardrails.sh`); it's persisted to each profile's `config.json` even with `--skip-guardrails`.
- **A unique crontab marker** `# hermes-revenium-metering-<profile>` — a second profile install never clobbers the first. `uninstall-cron.sh` removes every profile's line; orphaned lines (after a `~/.hermes` reset) are reconciled automatically.
- **`hooks_auto_accept: true`** — headless profile gateways never show the hook-approval prompt, so hooks stay inert without this. Fleet installs set it automatically (`install-hooks.sh --auto-accept`). Use `install-hooks.sh --metering-only` to register only `post_tool_call` for shadow/metering-only profiles.
- **One shared SQUAD identity across the fleet (optional)** — set `REVENIUM_SQUAD_NAME` to group every profile's completions under one squad name, distinct from the per-profile AGENT. See [`references/setup.md`](../skills/revenium/references/setup.md) → **Squad grouping across the fleet** for the resolution order and the fleet recipe.

## Per-profile facts that bite

- **The process serving the profile must restart before its plugin loads —
  and that is often NOT the gateway.** Plugin discovery is per-profile and the
  classifier is *copied* into `~/.hermes/profiles/<name>/plugins/`, so whatever
  process serves the profile keeps running the code it started with. Until it
  restarts the profile meters normally but classifies nothing: no markers, no
  jobs, `traceType: uncategorized`, and no tool-events. Find the real owner
  before restarting anything:

  ```bash
  ps -axo pid,lstart,command | grep -E 'hermes.*(serve|gateway run)' | grep -v grep
  ```

  - `gateway run` → `hermes gateway restart` (or `hermes-gateways restart`).
    Check its `HERMES_HOME`: on a desktop host it commonly serves only the
    default home and touches no profile at all.
  - `--profile <name> serve` → spawned by the Hermes **desktop app**. Quit and
    reopen the app; restarting the gateway does nothing for these. Seen live
    with a `serve` process nine days old still answering while a freshly
    restarted gateway sat beside it classifying nothing.

  `install.sh` restarts the gateway for you, which covers the gateway case only.
- **"Registered" is not "loaded".** `plugin-status.sh` reports registration from
  `config.yaml`; that a plugin is listed says nothing about whether the live
  gateway has it. Confirm with markers, not with registration.
- **Upgrades must name the profiles again** — see
  [Upgrading on a remote host](#upgrading-on-a-remote-host).
- **Fleet mode never prompts, so it skips guardrail creation** unless you pass
  both `--hard-limit` and `--period`. Without them each profile is wired for
  metering with no budget rule, and the installer says so at the end.
- **Dashboards must filter on the per-profile agent.** Spend for profile `ent`
  arrives as agent `Hermes-ent`, so a rule or view scoped to `Hermes` will not
  show it and a budget rule filtered `AGENT:IS:Hermes` will never match it.
- **State is per-profile too.** Ledgers, markers, `config.json` and
  `guardrail-status.json` all live under
  `~/.hermes/profiles/<name>/state/revenium/`. Point diagnostics at the profile
  you mean:

  ```bash
  bash ~/.hermes/skills/revenium/scripts/diagnose.sh --profile ent
  ```

  `diagnose.sh` with no flag reads the **default** profile — the single easiest
  way to conclude "nothing is being metered" while looking at the wrong home.
  Its last section lists every profile's ledger size and last cron run, which is
  the fastest way to spot one profile that has gone quiet.

Both deployment modes work: one-process-per-profile and the multiplexed single gateway (`gateway.multiplex_profiles: true`, where the classifier resolves the owning profile's home/state.db/markers **per session** from the `agent:<profile>:…` namespace). Size `REVENIUM_CRON_SETTLE_SECONDS` (default **600s**) above worst-case job-inference latency. See [`references/setup.md`](../skills/revenium/references/setup.md) → **Multi-profile / fleet installs** for the full operational guide.

