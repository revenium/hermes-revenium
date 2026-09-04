# Documentation

[← Back to the project README](../README.md)

This Hermes skill bundle uses a plugin, three shell hooks, and a cron for runtime work.
`SKILL.md` provides a halt-check backstop. See
[What's actually installed](../README.md#whats-actually-installed) for the components and
[How it works](how-it-works.md) for their behavior.

## Getting started

- [Installation](installation.md): the four install paths, four credentials,
  guardrail rules, cron, hooks, the classifier plugin, and how to verify the result.
- [Configuration](configuration.md): `config.json` fields, credential storage, and
  the two switches that control event-driven metering.

## Running it

- [How it works](how-it-works.md): the classification pipeline, all three metering
  paths, agentic jobs, tool events, and guardrail enforcement.
- [Multi-profile / fleet installs](fleet.md): per-profile wiring and failure modes
  that look like nothing is wrong.
- [Upgrading](upgrading.md): four upgrade paths and required follow-up steps.
- [Operations](operations.md): manual commands, diagnostics, uninstall, and tests.

## Job value and ROI

- [Job value: a practical overview](value-overview.md): how the mechanism
  works, what the number means, and a fully annotated configuration for a software
  engineering team, with the reasoning behind every figure. Short.
- [Job value and ROI](value-and-roi.md): the complete reference for the experimental
  value path: turning it on, the evaluator and its bounds, the abstention vocabulary, how a
  value is derived and bounded, costs and `net_value`, the six mechanisms, the nine evidence
  classes, reportability, the sidecar record, the wire shape and its byte ceiling,
  corrections, operations, and troubleshooting. Read the claim-discipline page below first.

## Claim discipline

- [Claim distinctions and evidence boundaries](claim-distinctions-and-evidence-boundaries.md):
  output vs. outcome vs. valuation vs. impact vs. ROI, the results chain, the product-truth
  boundary, and what the experimental value path deliberately does not ship. Start here
  before enabling it, then read [Job value and ROI](value-and-roi.md) for the mechanism;
  [`references/job-declaration.md`](../skills/revenium/references/job-declaration.md)
  has the label and mechanism reference both point to.

## Going deeper

- [Event metering](event-metering.md): the v1.5 event path, drain gate,
  cutover, and known differences from the delta reporter.
- [Guardrails migration](migration-guardrails.md): moving a legacy `alertId` install to
  `ruleIds`.
- [AGENT dimension migration](migration-agent-dimension.md): the per-profile agent name
  and its no-observable-change guarantee.
- [Auxiliary usage migration](migration-auxiliary-usage.md): metering Hermes' own
  compression, title-generation, approval, vision, web-extract, and session-search calls;
  the reported-spend step-up and its off switch.

## For contributors

- [Hermes plugin interface](plugin-interface.md): what the plugin surface
  actually does, measured against a live v0.20.1 install. Shipped code depends on
  it; [CONTRIBUTING.md](../CONTRIBUTING.md) has the rest of the workflow.
- [Evidence-class precedence and declaration authority](evidence-class-precedence.md):
  the Phase 48 reconciliation verdict and cross-boundary `evidence_class`
  precedence rule that Phase 50 and Phase 51 both plan against.
- [Live envelope verification](live-envelope-verification.md): whether a real
  Revenium API accepts the bounded `--metadata` envelope, measured against a live
  tenant rather than fixtures, with the limits of that result stated.
- [Live-tenant proof](live-tenant-proof.md): the declaration-authority and
  operator-mechanism work, and the sidecar carrier under both, measured against
  a live tenant: LIVE-02 through LIVE-06 plus two arms added in the open, with
  one criterion recorded NOT CONFIRMED live and its finding stated with its
  limit.
- [ROI read-surface ask](roi-read-surface-ask.md): the tracked, standing
  ask to the Revenium API team for `evidence_class`/`evaluator`/`confidence`
  on `jobs roi`, and the Phase 53 gate this skill shipped instead of waiting
  on it.
- [CLI-verb ask](cli-verb-ask.md): the tracked, dated ask to the same team
  for the five verbs and flags `1.5.0` doesn't expose yet — `jobs types
  economics`/`baselines`/`facts`, an outcome-update version flag, and a
  job-outcome metrics surface — why the CLI-only boundary makes each
  blocking, and what this project does the day each ships. Implements
  nothing.
- [Local evidence classes and server provenance](provenance-mapping.md): the
  decided mapping from each of the nine local `evidence_class` labels onto
  the two server `provenance` vocabularies, the resolution of the one label
  that maps to neither, and the fields Phase 59's valuation seam will still
  have to decide. Implements nothing.

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
