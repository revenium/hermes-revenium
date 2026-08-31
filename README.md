<div align="center">

<img src="assets/hermes-revenium-nous-research.png" alt="Hermes × Revenium — Revenium Labs" width="620">

# Hermes Revenium

**Budget enforcement, semantic task-type metering, agentic job tracking, and tool-event
metering for [Hermes Agent](https://hermes-agent.nousresearch.com), on the
[Revenium](https://www.revenium.ai) platform. Ships as a Hermes skill bundle; the work is
done by a plugin, three shell hooks, and a cron.**

![Revenium Labs](https://img.shields.io/badge/Revenium-Labs-6f42c1?style=for-the-badge)
![Status: Beta](https://img.shields.io/badge/status-beta%20(best--effort)-f0a020?style=for-the-badge)

[![Tests](https://github.com/revenium/hermes-revenium/actions/workflows/tests.yml/badge.svg)](https://github.com/revenium/hermes-revenium/actions/workflows/tests.yml)
[![Secret Scan](https://github.com/revenium/hermes-revenium/actions/workflows/secret-scan.yml/badge.svg)](https://github.com/revenium/hermes-revenium/actions/workflows/secret-scan.yml)

[Quick start](#quick-start) ·
[Install](docs/installation.md) ·
[How it works](docs/how-it-works.md) ·
[Fleet](docs/fleet.md) ·
[Operations](docs/operations.md) ·
[Docs](docs/README.md) ·
[Discord](https://discord.gg/J2DbmjZ2nA)

</div>

> ### 🧪 This is a Revenium Labs project
> **Revenium Labs** projects are field-developed, best-effort solutions. They are working,
> beta-quality software, built to solve real customer problems and shared in the open. They are
> **not** part of Revenium's officially supported products.
>
> - It works and solves a real problem, but may need adaptation to fit your exact environment.
> - It's provided as-is, without the versioned-release guarantees, SLAs, or formal support
>   that back our core products.
> - We welcome your issues, feedback, and PRs, and **we're happy to work with you** to make it
>   fit your use case. [Come talk to us on Discord](https://discord.gg/J2DbmjZ2nA).
>
> → **[What is Revenium Labs?](https://github.com/revenium/.github/blob/main/LABS.md)**

Hermes reports token totals per session. That tells you what you spent, but not what
you bought. Revenium adds that context: each metered completion is labelled with the
agent's task, each task arc is tracked as a billable job, every tool call is metered, and
a blocking budget rule halts the agent structurally. A successful job can also include an
estimated economic value, which Revenium combines with metered cost to display ROI.

## What you get

| | |
|---|---|
| **Semantic task types** | Every completion ships with `--task-type` and `--operation-type` from a controlled vocabulary, inferred by a plugin that reads the session transcript — not by asking the agent to label itself. |
| **Agentic job tracking** | Discrete task arcs become Revenium jobs with immutable, once-only outcomes, and their transactions are linked back via `--agentic-job-id`. |
| **Tool-event metering** | Every Hermes tool call is metered — name, duration, success, error — through `revenium meter tool-event`. |
| **Structural budget guardrails** | Hermes shell hooks read a local guardrail snapshot before every LLM call and every tool call, so enforcement does not depend on the agent choosing to comply. |
| **Job value estimation** *(experimental, opt-in, off by default)* | On a `SUCCESS` arc only, one bounded LLM call on your own provider estimates the job's economic value from two independently capped inputs. It is an **unverified model estimate**, not an observed outcome. Absent or malformed config fails closed, so an existing install meters byte-identically to before. Start with the **[practical overview](docs/value-overview.md)**; **[Job value and ROI](docs/value-and-roi.md)** is the full reference. |

> **Which number crosses the wire.** When value estimation is enabled, `--outcome-value`
> ships the **low** bound of the low/base/high band — the conservative figure, not the base.
> All three bounds and their provenance ride in `--metadata`, so the full range stays
> recoverable. The estimate understates by design rather than overstating, which means the
> value on a Revenium dashboard is deliberately the floor of the range.
> [Job value and ROI](docs/value-and-roi.md) documents the whole path.

## What's actually installed

"Skill" is how this is packaged and installed, not what does the work. Five pieces land on
the host, and only one of them is the skill:

| Piece | What Hermes calls it | Where it lives | What it does |
|---|---|---|---|
| `revenium-classifier` | **plugin** — Python, `register(ctx)`, four lifecycle hooks | `~/.hermes/plugins/` (per **profile** on a fleet) | All classification, and the per-API-call event spool |
| `pre_llm_call`, `pre_tool_call`, `post_tool_call` | **shell hooks** registered in `config.yaml` | `~/.hermes/skills/revenium/scripts/` | All budget enforcement, and tool-call capture |
| `cron.sh` and its six stages | **cron job**, out of process | `~/.hermes/skills/revenium/scripts/` | Everything that talks to the Revenium API |
| `SKILL.md` | **skill** — markdown loaded into the agent's context | `~/.hermes/skills/revenium/` | A halt-check backstop, by its own description defense-in-depth only |
| `job-assessments/` | **state** — one append-only JSONL file per job | `~/.hermes/state/revenium/` | The record of record for a job's assessment and its correction history. Kept 90 days (`REVENIUM_ASSESSMENT_RETENTION_DAYS`), against 30 for markers |

Hermes loads plugins from `~/.hermes/plugins/` and skills from
`~/.hermes/skills/`. They use different roots and loaders, and `hermes skills install`
carries only the skill. The bootstrap installs the other pieces. On a multi-profile host,
a stale plugin copy is the most common silent failure because the skill tree is shared but
the plugin is not.

An assessment is never rewritten. If a value turns out to be wrong,
`scripts/correct-assessment.sh` appends a correction — locally as a new line in the job's
sidecar, and remotely through `revenium jobs outcome-update`, which adds a revision rather
than replacing one. The original stays byte-identical and readable. It is operator-only and
deliberately unreachable from cron, and `--dry-run` shows what it would do without writing
anything, locally or remotely.

## Quick start

```bash
hermes skills install revenium/hermes-revenium/skills/revenium
bash ~/.hermes/skills/revenium/references/bootstrap.sh
```

The first command installs the skill through Hermes' native path; it scans `SAFE`, so no
`--force` is needed. The second one fetches the parts that path cannot carry — `scripts/`
and `plugins/` — and then completes setup: credentials, classifier plugin, shell hooks,
guardrail budget rule, per-minute cron, gateway restart. It is idempotent, so re-running it
is always safe.

Then start a Hermes session and **approve the hooks** at the prompt Hermes shows the first
time each one fires. Until you do, they are registered but inert.

> **Running more than one Hermes profile?** Add `--profile <name>` (repeatable) or
> `--all-profiles`. Every command here is scoped to **one** Hermes home, and the default
> home is not a superset of the others — a profile you never name gets no plugin, no hooks,
> no cron, and meters nothing. See [Multi-profile / fleet installs](docs/fleet.md).

Full instructions, the other three install paths, and what the security scanner reports:
**[docs/installation.md](docs/installation.md)**.

## Prerequisites

- [Hermes Agent](https://hermes-agent.nousresearch.com/docs/) installed and running
- [Revenium](https://app.revenium.ai/connections) API key, Team ID, Tenant ID, and User ID
- [`revenium` CLI](https://github.com/revenium/revenium-cli) — `brew install revenium/tap/revenium`
- `sqlite3` and `python3` on `PATH`

```bash
revenium config show
sqlite3 --version
python3 --version
```

## Documentation

| Guide | What it covers |
|---|---|
| [Installation](docs/installation.md) | Four install paths, credentials, guardrail rules, cron, hooks, plugin, and how to verify the result |
| [How it works](docs/how-it-works.md) | The classification pipeline, both metering paths, agentic jobs, tool events, and guardrail enforcement |
| [Configuration](docs/configuration.md) | `config.json` fields, credential storage, and the two event-metering switches |
| [Multi-profile / fleet](docs/fleet.md) | Per-profile installs and the footguns that cost real time on a live fleet |
| [Upgrading](docs/upgrading.md) | Four upgrade paths and what must be re-run after each |
| [Operations](docs/operations.md) | Manual commands, diagnostics, uninstall, and the test suite |
| [Event metering](docs/event-metering.md) | The v1.5 event path in depth: mechanism, cutover, and rollback |
| [Plugin interface](docs/plugin-interface.md) | The Hermes plugin surfaces the classifier registers against, and what each one can and cannot see |
| [Evidence classes](docs/evidence-class-precedence.md) | Which boundary decides a record's `evidence_class`, the fixed precedence order, and what a declaration may and may not claim · [Claim distinctions](docs/claim-distinctions-and-evidence-boundaries.md) |
| [Migrations](docs/migration-guardrails.md) | [Guardrails](docs/migration-guardrails.md) · [AGENT dimension](docs/migration-agent-dimension.md) |

Reference material that ships inside the skill bundle lives at
[`skills/revenium/references/`](skills/revenium/references/) —
[setup](skills/revenium/references/setup.md),
[troubleshooting](skills/revenium/references/troubleshooting.md),
[task taxonomy](skills/revenium/references/task-taxonomy.md), and the
[config schema](skills/revenium/references/config-schema.md).


## Notes

- The skill is packaged at `skills/revenium/` so the default `hermes skills tap add owner/repo`
  discovery path resolves it without extra configuration.
- Mutable runtime state lives under `~/.hermes/state/revenium/`; skill content lives under
  `~/.hermes/skills/revenium/`. Don't mix the two.
- This repo is Hermes-only by design — no legacy runtime assumptions carried over from the
  skill it was forked from.

## Contributing

Issues and PRs are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for how the repo is
laid out, the invariants the test suite enforces, and what to run before opening a PR.

## Changelog

Release history is in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE) — the same license as [Hermes Agent](https://github.com/NousResearch/hermes-agent)
itself, and the one `skills/revenium/SKILL.md` already declares in its frontmatter.

## Support

Questions, bugs, or feature requests? Join us on [Discord](http://discord.gg/J2DbmjZ2nA).
