# Documentation

[← Back to the project README](../README.md)

Packaged as a Hermes skill bundle, but the working parts are a plugin, three shell hooks,
and a cron; `SKILL.md` is only a halt-check backstop. The README's
[What's actually installed](../README.md#whats-actually-installed) has the breakdown, and
[How it works](how-it-works.md) has the mechanism.

## Getting started

- **[Installation](installation.md)** — the four install paths, the four credentials,
  guardrail rules, cron, hooks, the classifier plugin, and how to verify the result.
- **[Configuration](configuration.md)** — `config.json` fields, where credentials live, and
  the two switches that control event-driven metering.

## Running it

- **[How it works](how-it-works.md)** — the classification pipeline, both metering paths,
  agentic jobs, tool events, and guardrail enforcement.
- **[Multi-profile / fleet installs](fleet.md)** — per-profile wiring and the failure modes
  that look like nothing is wrong.
- **[Upgrading](upgrading.md)** — four upgrade paths and what has to be re-run after each.
- **[Operations](operations.md)** — manual commands, diagnostics, uninstall, and the tests.

## Claim discipline

- **[Claim distinctions and evidence boundaries](claim-distinctions-and-evidence-boundaries.md)**
  — output vs. outcome vs. valuation vs. impact vs. ROI, the results chain, the product-truth
  boundary, and what the experimental value path deliberately does not ship. Start here
  before enabling it; [`references/job-declaration.md`](../skills/revenium/references/job-declaration.md)
  has the label and mechanism reference it points to.

## Going deeper

- **[Event metering](event-metering.md)** — the v1.5 event path: mechanism, the drain gate,
  cutover, and known differences from the delta reporter.
- **[Guardrails migration](migration-guardrails.md)** — moving a legacy `alertId` install to
  `ruleIds`.
- **[AGENT dimension migration](migration-agent-dimension.md)** — the per-profile agent name
  and its no-observable-change guarantee.

## For contributors

- **[Hermes plugin interface](plugin-interface.md)** — what the plugin surface
  actually does, measured against a live v0.20.1 install. Shipped code depends on
  it; [CONTRIBUTING.md](../CONTRIBUTING.md) has the rest of the workflow.

## Inside the skill bundle

These ship to `~/.hermes/skills/revenium/` and are read at runtime, so they live with the
skill rather than here:

- [`references/setup.md`](../skills/revenium/references/setup.md) — the guided setup flow
- [`references/troubleshooting.md`](../skills/revenium/references/troubleshooting.md) — failure modes
- [`references/task-taxonomy.md`](../skills/revenium/references/task-taxonomy.md) — the controlled vocabulary
- [`references/config-schema.md`](../skills/revenium/references/config-schema.md) — `config.json` schema
- [`references/job-declaration.md`](../skills/revenium/references/job-declaration.md) — what makes a
  job arc, and the reference for the experimental value path: the nine evidence-class
  labels with their exact spellings, the six economic mechanisms, `double_counting_group`,
  and the sidecar assessment record
- [`references/halt-survivability.md`](../skills/revenium/references/halt-survivability.md) — the manual halt-check runbook

## Release history

[CHANGELOG.md](../CHANGELOG.md) — new functionality and fixes, release by release.

