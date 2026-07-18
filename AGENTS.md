# AGENTS.md

Cross-assistant guidance for this repository. Read by tools that honor the
`AGENTS.md` convention (Codex, Cursor, and others); Claude Code additionally
reads [`CLAUDE.md`](CLAUDE.md), which is the fuller reference.

## What this repo is

A distribution package for a single **Hermes Agent** skill (`revenium`) that adds
Revenium budget guardrails and usage metering to Hermes. There is no build step
and no application runtime — the product is `skills/revenium/` (a Hermes skill:
`SKILL.md`, `scripts/*.sh`, `plugins/`, `references/`). Everything else is
packaging, docs, and tests.

## Build / test

No build. Tests are stdlib `unittest`:

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Runtime scripts are Bash (`set -euo pipefail` or `-uo pipefail`) with embedded
Python 3 heredocs; `sqlite3` and the `revenium` CLI are runtime deps. See
[`CLAUDE.md`](CLAUDE.md) for architecture, conventions, and the invariants the
test suite enforces (state-path discipline, frontmatter, no legacy branding).

## Skills in this repo

- **`assistant-skill/revenium-install/`** — a portable, tool-agnostic
  coding-assistant skill (Anthropic Agent Skills `SKILL.md` format) that drives
  **install / verify / troubleshoot** for the metering skill on a host or fleet.
  It delegates all mutation to `skills/revenium/scripts/*.sh` and contains no
  assistant-specific tool calls, so any assistant that reads markdown and runs
  `bash` can use it. Start at
  [`assistant-skill/revenium-install/SKILL.md`](assistant-skill/revenium-install/SKILL.md);
  failure-mode routing lives in
  [`assistant-skill/revenium-install/references/decision-tree.md`](assistant-skill/revenium-install/references/decision-tree.md).

  Use it when setting up Revenium metering, wiring a multi-profile fleet, or
  diagnosing metering/jobs/tool-events/budget-halt problems.

> The Hermes skill at `skills/revenium/SKILL.md` is a *different* artifact — it is
> installed into Hermes, governed by the Hermes tap-discovery + frontmatter rules,
> and must stay under `skills/`. Do not confuse the two. The install skill above
> deliberately lives outside `skills/`.

## Conventions (summary — full detail in CLAUDE.md)

- Runtime state lives under `~/.hermes/state/revenium/`; all state paths are
  declared only in `skills/revenium/scripts/common.sh`.
- The skill is a pure consumer of Hermes' `~/.hermes/state.db` — never write it.
- Keep the metering idempotent (the append-only ledger); re-running the cron must
  never double-report.
- No legacy branding from the forked-from tool (the test suite fails the build on
  it).
