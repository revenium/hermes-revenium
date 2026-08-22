# Documentation

[← Back to the project README](../README.md)

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

## Going deeper

- **[Event metering](event-metering.md)** — the v1.5 event path: mechanism, the drain gate,
  cutover, and known differences from the delta reporter.
- **[Guardrails migration](migration-guardrails.md)** — moving a legacy `alertId` install to
  `ruleIds`.
- **[AGENT dimension migration](migration-agent-dimension.md)** — the per-profile agent name
  and its no-observable-change guarantee.

## Inside the skill bundle

These ship to `~/.hermes/skills/revenium/` and are read at runtime, so they live with the
skill rather than here:

- [`references/setup.md`](../skills/revenium/references/setup.md) — the guided setup flow
- [`references/troubleshooting.md`](../skills/revenium/references/troubleshooting.md) — failure modes
- [`references/task-taxonomy.md`](../skills/revenium/references/task-taxonomy.md) — the controlled vocabulary
- [`references/config-schema.md`](../skills/revenium/references/config-schema.md) — `config.json` schema
- [`references/halt-survivability.md`](../skills/revenium/references/halt-survivability.md) — the manual halt-check runbook

## Release history

[CHANGELOG.md](../CHANGELOG.md) — product releases, drawn from the annotated git tags.

## Engineering evidence

[`internal/`](internal/) holds rehearsals, reconciliations, live-host verifications, and
milestone closeouts. They are committed because the planning tree they came from is
gitignored, and they record why the system has the shape it does. They are not operator
documentation — nothing here requires reading them.
