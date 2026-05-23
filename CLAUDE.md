# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A distribution package for a single Hermes Agent skill (`revenium`) that adds Revenium guardrails-based budget enforcement and usage metering to Hermes. There is no build step, no compiled artifact, and no application runtime here — the repo is consumed by Hermes either as a GitHub tap, an `external_dirs` entry, or a copy into `~/.hermes/skills/`.

The skill itself lives at `skills/revenium/` and is the only thing end users install. Everything else (`docs/`, `examples/`, `tests/`, `README.md`) is packaging metadata.

## Common commands

```bash
# Run the smoke tests (stdlib unittest only)
python3 -m unittest discover -s tests -p 'test_*.py' -v

# Single test class / method
python3 -m unittest tests.test_repository.RepositoryTests
python3 -m unittest tests.test_repository.RepositoryTests.test_runtime_paths_are_hermes_native

# Install the skill into a local Hermes for end-to-end testing
bash examples/setup-local.sh

# Drive the runtime scripts manually after install (paths assume the skill is installed)
bash ~/.hermes/skills/revenium/scripts/install-cron.sh   # adds the per-minute cron
bash ~/.hermes/skills/revenium/scripts/cron.sh           # one-shot: report + budget check
bash ~/.hermes/skills/revenium/scripts/hermes-report.sh  # metering only
bash ~/.hermes/skills/revenium/scripts/guardrail-check.sh   # guardrail check only
bash ~/.hermes/skills/revenium/scripts/clear-halt.sh     # clear an active halt
bash ~/.hermes/skills/revenium/scripts/uninstall-cron.sh
```

There is no linter or formatter wired up. Bash scripts use `set -uo pipefail` (or `-euo pipefail` for the simpler ones); preserve that when editing.

## Architecture

The skill has two halves that communicate through files in `~/.hermes/state/revenium/`:

1. **The cron pipeline** (`scripts/cron.sh` → `hermes-report.sh` + `guardrail-check.sh`) runs every minute outside of Hermes. It reads `~/.hermes/state.db` (Hermes' session DB), ships token deltas to Revenium via `revenium meter completion`, refreshes `guardrail-status.json` with per-rule warn/block/ok state, and on transition into halt embeds the latest enforcement-event payload into the Hermes notification.

2. **The skill prompt** (`SKILL.md`) and the **`pre_llm_call` / `pre_tool_call` shell hooks** run inside a Hermes session. Before any costly operation, they read `guardrail-status.json`: warn-band rules emit a single stderr line per (session, ruleId); block-band rules emit a verbatim halt directive (the D-01 string referencing the offending rule). The SKILL.md halt block is a procedural backstop — the hooks are the load-bearing enforcement path.

The two halves never call each other directly. The only coupling is the shape of `config.json` and `guardrail-status.json`. Treat both files as the public interface between the cron and the skill prompt.

### State separation

Mutable state lives under `~/.hermes/state/revenium/` (config, status, ledger, log). Skill content lives under `~/.hermes/skills/revenium/`. Do not write runtime state into the skill directory — `tests/test_repository.py::test_runtime_paths_are_hermes_native` enforces that `common.sh` continues to use `.hermes` and `state/revenium`.

`scripts/common.sh` is the single source of truth for state paths (`STATE_DIR`, `CONFIG_FILE`, `GUARDRAIL_STATUS_FILE`, `LEDGER_FILE`, `LOG_FILE`, `STATE_DB`, `ENV_FILE`). All other scripts source it. Add new paths there, not inline.

### Metering ledger semantics

`hermes-report.sh` reports **deltas**, not totals. The ledger file (`revenium-hermes.ledger`) records `HERMES:<session_id>:<total_tokens>:<unix_ts>` lines. On each run the script:

- queries `state.db` sessions with non-zero tokens
- finds the previous ledger entry for that session, computes the delta, and scales `input/output/cache_read/cache_write/cost` by `(curr - prev) / curr`
- skips sessions whose totals haven't grown
- only writes a new ledger line on a successful `revenium meter completion` call

If you change how sessions are identified, scaled, or written to the ledger, preserve idempotency: re-running the cron must never double-report. The `transaction-id` is `${session_id}-${total_tokens}` for the same reason.

Provider inference (`anthropic` / `openai` / `google` / `xai` / `deepseek` / `meta`) is done from the `model` and `billing_provider` columns in Python heredocs inside `hermes-report.sh`. OpenRouter and Bedrock get special-cased to map to the underlying model provider.

### Halt transitions

`guardrail-check.sh` distinguishes a *new* halt (this run flipped a rule from ok→block under autonomous mode) from an existing halt (carries forward `haltedAt` + `haltedRule`). Only new transitions trigger a Hermes notification, which embeds the latest enforcement-event payload from `revenium guardrails enforcement-events list`. Clearing a halt is exclusively the job of `clear-halt.sh` — bare clears all blocked rules; `--rule-id <id>` clears one rule and recomputes `haltedRule`. `guardrail-check.sh` will not auto-clear.

Before every release that modifies `SKILL.md`, run the manual halt-check survivability test plan — operator runbook at `skills/revenium/references/halt-survivability.md` to confirm the halt-check anchor still fires under context dilution in long sessions.

### Frontmatter and tap discoverability

`skills/revenium/SKILL.md` requires `name: revenium`, a `metadata.hermes` block, and `category: devops` — `tests/test_repository.py::test_skill_frontmatter_has_hermes_metadata` enforces this. The skill is placed at `skills/revenium/` (not the repo root) so that `hermes skills tap add owner/repo` discovers it under the default `skills/` path; do not relocate it.

### Legacy branding guard

`tests/test_repository.py::test_no_legacy_branding_left` greps every text file for the legacy product names this skill was forked from and fails the build if any match. The disallowed strings are listed in the test's regex (`tests/test_repository.py:46`); read it directly rather than reproducing them here. This repo is a clean Hermes-only fork; if you're porting content from a previous tool, scrub those names before committing.

<!-- GSD:project-start source:PROJECT.md -->
## Project

**Hermes-Revenium Task-Type Metering**

An extension to the existing `revenium` Hermes skill that attaches a meaningful
`--task-type` (and `--operation-type`) to every metered completion shipped to
Revenium. Today the skill reports raw token deltas with no semantic label;
after this work, every Revenium-side row carries *what the agent was doing*
when those tokens were spent, drawn from an agent-maintained controlled
vocabulary of task labels.

The audience is anyone running Hermes with the Revenium budget skill installed
who wants their AI spend analytics broken down by activity (code review,
research, refactor, planning, etc.) instead of an undifferentiated session
total.

**Core Value:** **Every metered completion that leaves this skill carries an accurate,
consistently-spelled `--task-type` so Revenium analytics group spend by what
the agent actually did, not just by session.**

If the taxonomy fragments (`code_review` vs `code-review` vs `review_code`) or
attribution leaks across tasks, the feature has failed even if the wire
protocol works.

### Constraints

- **Tech stack**: Bash + Python heredocs + sqlite3 + the `revenium` CLI, with
  `set -uo pipefail` (or `-euo pipefail` for simpler scripts). No new runtime
  dependencies — anything new must be expressible in stdlib Python or POSIX
  sh.
- **State path discipline**: All new files live under
  `~/.hermes/state/revenium/`. Paths are declared in `scripts/common.sh` and
  nowhere else; `test_runtime_paths_are_hermes_native` will fail the build if
  this is violated.
- **No writes to `state.db`**: The skill is a pure consumer of Hermes'
  session DB. This is enforced socially today and must remain true.
- **Tap discoverability**: The skill must stay at `skills/revenium/`. Frontmatter
  in `skills/revenium/SKILL.md` requires `name: revenium`, the `metadata.hermes`
  block, and `category: devops` — enforced by
  `test_skill_frontmatter_has_hermes_metadata`.
- **Legacy branding guard**: `test_no_legacy_branding_left` greps every text
  file against a regex of forked-from product names; new docs and code must
  not reintroduce them.
- **Idempotency**: Re-running the cron must never double-report. This is the
  load-bearing invariant of the existing ledger and must extend to the new
  marker-split flow.
- **Backward compatibility**: Existing installs with no markers must continue
  to meter exactly as they do today, just with `--task-type unclassified`.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- Bash 4+ - All runtime/cron scripts under `skills/revenium/scripts/` (`common.sh`, `cron.sh`, `hermes-report.sh`, `budget-check.sh`, `install-cron.sh`, `uninstall-cron.sh`, `clear-halt.sh`)
- Python 3 - Embedded heredocs inside bash scripts for JSON manipulation, datetime formatting, and delta arithmetic (e.g., `skills/revenium/scripts/hermes-report.sh:90-97`, `skills/revenium/scripts/budget-check.sh:47-93`). Also used standalone for tests.
- SQL (SQLite dialect) - Inline query against the Hermes session DB in `skills/revenium/scripts/hermes-report.sh:45-53`
- YAML - Frontmatter at the top of `skills/revenium/SKILL.md` defining skill metadata
- Markdown - Documentation in `README.md`, `CLAUDE.md`, `docs/installation.md`, `skills/revenium/SKILL.md`, `skills/revenium/references/*.md`
## Runtime
- macOS (Darwin) and Linux — declared in `skills/revenium/SKILL.md:8` (`platforms: [macos, linux]`)
- POSIX shell with bash via `#!/usr/bin/env bash`
- Python 3 — invoked as `python3` (no minimum version pinned); required at runtime per `skills/revenium/scripts/hermes-report.sh:21-24`
- SQLite 3 CLI (`sqlite3`) — required at runtime per `skills/revenium/scripts/hermes-report.sh:17-20`
- cron — Unix per-minute scheduler installed by `skills/revenium/scripts/install-cron.sh`
- None for this repo itself (no `package.json`, `requirements.txt`, `pyproject.toml`, or lockfile)
- Homebrew is referenced as the recommended installer for the `revenium` CLI (`brew install revenium/tap/revenium`, see `README.md:9` and `skills/revenium/SKILL.md:130`)
- Homebrew prefixes are auto-prepended to `PATH` in `skills/revenium/scripts/common.sh:20-28` and `skills/revenium/scripts/install-cron.sh:17-24`
## Frameworks
- None — no application framework. The skill is a packaging artifact, not an executable.
- Python `unittest` (stdlib) — see `tests/test_repository.py:1-3`. Run via `python3 -m unittest discover -s tests -p 'test_*.py' -v`.
- `bash -n` syntax check is invoked from inside Python tests (`tests/test_repository.py:60-65`)
- No build system. No compiler, transpiler, bundler, or task runner.
- No linter, formatter, or pre-commit config is wired up (per `CLAUDE.md` "Common commands" section)
## Key Dependencies
- `revenium` CLI — primary external dependency. Used by `skills/revenium/scripts/hermes-report.sh:217` (`revenium meter completion`), `skills/revenium/scripts/budget-check.sh:32` (`revenium alerts budget get`), and during skill setup (`revenium config show/set`, `revenium alerts budget create/list/delete`).
- `sqlite3` CLI — reads `~/.hermes/state.db` in `skills/revenium/scripts/hermes-report.sh:45-53`
- `python3` — used inline for JSON parsing, ratio math, and datetime formatting throughout the bash scripts
- `bash` — declared shebang on every script; `set -euo pipefail` or `set -uo pipefail` is required by `tests/test_repository.py::test_shell_scripts_have_valid_syntax`
- `hermes` CLI — used by `skills/revenium/scripts/budget-check.sh:105-110` to dispatch halt notifications via Hermes' messaging toolset
- `cron`/`crontab` — required for the metering loop; managed by `install-cron.sh` and `uninstall-cron.sh`
- None vendored. The repo is intentionally zero-dependency at the file level.
## Configuration
- `HERMES_HOME` — defaults to `${HOME}/.hermes`, overridable. Set by `skills/revenium/scripts/common.sh:6`.
- `REVENIUM_STATE_DIR` — defaults to `${HERMES_HOME}/state/revenium`, overridable. Set by `skills/revenium/scripts/common.sh:7`.
- `REVENIUM_API_KEY`, `REVENIUM_API_URL`, `REVENIUM_TEAM_ID` — declared as `required_environment_variables` in `skills/revenium/SKILL.md:9-12`. In practice consumed by the `revenium` CLI, not this repo.
- Optional per-state env file at `${STATE_DIR}/env` (`ENV_FILE` in `skills/revenium/scripts/common.sh:15`), sourced by `skills/revenium/scripts/cron.sh:10-15` when present.
- `.env` files are git-ignored (`.gitignore:4`). No `.env` is shipped or read by the repo itself.
- None.
- `~/.hermes/state/revenium/config.json` — alert ID, organization name, autonomous flag, notification channel/target. Schema documented in `README.md:131-148` and `skills/revenium/SKILL.md:204-231`.
- `~/.hermes/state/revenium/budget-status.json` — last cron snapshot (`currentValue`, `threshold`, `percentUsed`, `exceeded`, `halted`, `haltedAt`, `lastChecked`). Produced by `skills/revenium/scripts/budget-check.sh:43-93`.
- `~/.hermes/state/revenium/revenium-hermes.ledger` — append-only idempotency ledger; lines are `HERMES:<session_id>:<total_tokens>:<unix_ts>` (`skills/revenium/scripts/hermes-report.sh:70-71, 256`).
- `~/.hermes/state/revenium/revenium-metering.log` — cron log (`skills/revenium/scripts/common.sh:14`).
- `~/.config/revenium/config.yaml` — Revenium CLI credentials. Declared in `skills/revenium/SKILL.md:13-15`. The skill never reads or writes this file directly (per `README.md:149`).
- Skill is placed at `skills/revenium/` so Hermes' default tap path resolves it (`README.md:29`, `docs/installation.md:12-18`). Do not relocate.
- `skills/revenium/SKILL.md` frontmatter must contain `name: revenium`, a `metadata.hermes` block, and `category: devops` — enforced by `tests/test_repository.py::test_skill_frontmatter_has_hermes_metadata`.
## Platform Requirements
- macOS or Linux with bash, python3, sqlite3, and the `revenium` CLI installed
- No Node, no JVM, no Docker, no compiled toolchain
- Same as development. The skill runs in the user's home directory under `~/.hermes/`. There is no server, container, or deployed artifact — distribution is by `git clone` / GitHub tap / `cp -R`.
- Crontab access on the host machine is required; `install-cron.sh` writes via `crontab -` (see `skills/revenium/scripts/install-cron.sh:34`).
- Hermes Agent must be installed locally for the skill to be useful, but Hermes itself is not a build/test dependency of this repo.
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Naming Patterns
- Bash scripts: `kebab-case.sh` — e.g., `skills/revenium/scripts/hermes-report.sh`, `skills/revenium/scripts/budget-check.sh`, `skills/revenium/scripts/clear-halt.sh`, `skills/revenium/scripts/install-cron.sh`, `skills/revenium/scripts/uninstall-cron.sh`, `skills/revenium/scripts/cron.sh`
- Library/sourced bash: lowercase single-word — `skills/revenium/scripts/common.sh`
- Python tests: `test_*.py` — required by the discovery pattern (`tests/test_repository.py`)
- Docs: `lower_or_kebab.md` — e.g., `docs/installation.md`, `skills/revenium/references/setup.md`, `skills/revenium/references/troubleshooting.md`
- Top-level docs: `UPPERCASE.md` — `README.md`, `CLAUDE.md`
- Exported / config-like globals: `SCREAMING_SNAKE_CASE` — `STATE_DIR`, `CONFIG_FILE`, `BUDGET_STATUS_FILE`, `LEDGER_FILE`, `LOG_FILE`, `STATE_DB`, `ENV_FILE`, `HERMES_HOME`, `REVENIUM_STATE_DIR`, `SKILL_DIR`, `SCRIPT_DIR`
- Loop / local / transient variables: `lower_snake_case` declared with `local` — see `hermes-report.sh` (`local total_tokens`, `local ledger_key`, `local prev_reported_tokens`, etc.)
- Cron-side env passed in: `SCREAMING_SNAKE_CASE` — `HERMES_HOME=…`, `REVENIUM_STATE_DIR=…`, `PATH=…` in `install-cron.sh:26`
- `lower_snake_case` — `ensure_path`, `log`, `info`, `warn`, `error`, `read_config_field`, `main`
- `camelCase` — `currentValue`, `threshold`, `percentUsed`, `exceeded`, `halted`, `haltedAt`, `lastChecked`, `alertId`, `autonomousMode`, `notifyChannel`, `notifyTarget`, `organizationName`. Preserve this casing when reading/writing `config.json` and `budget-status.json`.
## Code Style
- No linter or formatter is wired up (per `CLAUDE.md`). Match the style of neighboring files by example.
- 2-space indentation in Bash (see `hermes-report.sh`, `budget-check.sh`).
- 4-space indentation in Python (both standalone tests and embedded heredocs).
- LF line endings; trailing newline on every file.
- Use `set -euo pipefail` for simple top-level scripts that fail fast: `clear-halt.sh:2`, `cron.sh:2`, `budget-check.sh:2`, `install-cron.sh:2`, `uninstall-cron.sh:2`, `examples/setup-local.sh:2`.
- Use `set -uo pipefail` (without `-e`) for the two scripts that intentionally tolerate per-step failures and want to log/continue:
- Do not switch a script's flags without understanding which mode it needs. `CLAUDE.md:33` calls this out as a preserve-when-editing rule.
#!/usr/bin/env bash
- Always resolve `SCRIPT_DIR` via `BASH_SOURCE[0]` (not `$0`), so the script works when invoked via cron, symlink, or `bash <path>`.
- Always include the `# shellcheck source=/dev/null` directive on the line above `source`.
- Always call `ensure_path` immediately after sourcing — cron runs with a minimal `PATH` and needs `/opt/homebrew/bin`, `~/.local/bin`, etc., prepended before `revenium`, `sqlite3`, or `python3` will resolve.
- Always quote expansions: `"${STATE_DIR}"`, `"${cmd[@]}"`, `"${BASH_SOURCE[0]}"`.
- Always use `${var}` braces, never bare `$var`.
- Default-with-fallback for envs: `HERMES_HOME="${HERMES_HOME:-${HOME}/.hermes}"`, `REVENIUM_STATE_DIR="${REVENIUM_STATE_DIR:-${HERMES_HOME}/state/revenium}"` (`common.sh:6-7`). New env-driven paths must follow this `:-` fallback shape.
- Conditionals use `[[ ... ]]` exclusively, not `[ ... ]` or `test`.
- Array commands are built up and invoked with `"${cmd[@]}"` — see `hermes-report.sh:216-251` for the canonical pattern (conditionally appending flags via `cmd+=(--flag "${value}")`).
## Single Source of Truth: `common.sh`
| Variable | Path |
|----------|------|
| `HERMES_HOME` | `${HOME}/.hermes` (overridable) |
| `STATE_DIR` / `REVENIUM_STATE_DIR` | `${HERMES_HOME}/state/revenium` |
| `SKILL_DIR` | resolved from `BASH_SOURCE[0]/..` |
| `CONFIG_FILE` | `${STATE_DIR}/config.json` |
| `BUDGET_STATUS_FILE` | `${STATE_DIR}/budget-status.json` |
| `LEDGER_FILE` | `${STATE_DIR}/revenium-hermes.ledger` |
| `LOG_FILE` | `${STATE_DIR}/revenium-metering.log` |
| `ENV_FILE` | `${STATE_DIR}/env` |
| `STATE_DB` | `${HERMES_HOME}/state.db` |
- Never hardcode `~/.hermes/...` paths in any other script — always reference the variable from `common.sh`.
- Add new state paths to `common.sh` (between `STATE_DIR` and `mkdir -p`), not inline in the calling script.
- The string literals `.hermes` and `state/revenium` must remain in `common.sh` — `tests/test_repository.py::test_runtime_paths_are_hermes_native` (`tests/test_repository.py:51-55`) asserts both are present.
- `common.sh` also exposes the `ensure_path`, `log`, `info`, `warn`, `error` helpers. New logging should go through `info` / `warn` / `error`, which timestamp and tee to `${LOG_FILE}` and stderr.
## Python Heredocs Inside Bash
- Stdlib only (`json`, `os`, `re`, `time`, `datetime`, `pathlib`). No `pip install`-able imports.
- Inline `import` at top of each heredoc — these are throwaway interpreters, not modules.
- Use `print(...)` for the single piece of data the caller will capture with `$( ... )`. For multi-value output, emit `KEY=value` lines and parse with `sed -n 's/^KEY=//p'` (see `budget-check.sh:88-102`).
- Tolerate failure with `|| true` or `|| echo "fallback"` when the value is non-critical (provider inference, timestamp formatting in `hermes-report.sh:124,165,179`).
## Import Organization (Python)
- Stdlib imports only, alphabetized: `re`, `subprocess`, `unittest`, then `from pathlib import Path`.
- Module-level constants in `SCREAMING_SNAKE_CASE` immediately below imports: `ROOT = Path(__file__).resolve().parents[1]`, `SKILL = ROOT / 'skills' / 'revenium'`.
## Error Handling
- Hard-fail mode (`set -e`) is the default for orchestration scripts. They should fail loudly rather than partially complete.
- Soft-fail mode (`set -uo pipefail` without `-e`) is reserved for `common.sh` and `hermes-report.sh`. In soft-fail scripts:
- The orchestrator `cron.sh:17-18` deliberately appends `|| true` after each child invocation so a metering failure doesn't block the budget check (or vice versa).
- Preflight required tooling before doing work and exit `0` with a `warn` if missing (so cron doesn't email errors on a fresh machine):
- Wrap optional file reads in `try/except Exception: pass` and fall back to defaults — see `budget-check.sh:64-70` where a missing/corrupt `budget-status.json` becomes an empty `prev = {}` rather than a hard crash.
## Logging
- `info`: lifecycle events ("=== Hermes Metering Reporter starting ===", "Reported: session=…"), normal flow.
- `warn`: recoverable conditions, missing optional tooling, per-session failures. The script should keep going.
- `error`: fatal conditions before exiting (rare in this codebase — most fatal paths use a bare `echo` + `exit 1` because they're user-facing one-shot CLIs like `clear-halt.sh` and `budget-check.sh`).
- Bare `echo` (no log helper): user-facing CLI output from `install-cron.sh`, `uninstall-cron.sh`, `clear-halt.sh`, `setup-local.sh`. These talk to a human at a terminal, not to the cron logfile.
## Comments
- File-level comment after the shebang and `set` line, explaining the script's role — e.g., `hermes-report.sh:2-3` ("Hermes-native Revenium reporter. Reads token usage…"), `common.sh:2` ("Common helpers for the Hermes Revenium skill.").
- ShellCheck directives where required: `# shellcheck source=/dev/null` immediately above every dynamic `source`.
- Inline comments are sparse — prefer self-documenting variable names. When present, they explain *why*, not *what* (see `budget-check.sh:42` "Update budget-status.json and decide if we just transitioned into halt.").
## Function Design
- Tiny utility wrappers in `common.sh` (`info`, `warn`, `error`) one-line through to `log`. Don't inline `echo "[$(date ...)]"` constructions in callers.
- Larger scripts wrap their core flow in a `main()` function and invoke it with `main "$@"` at EOF (see `hermes-report.sh:41,268`). One-shot scripts that are linear (`install-cron.sh`, `clear-halt.sh`, `cron.sh`) skip this and run top-to-bottom.
- Declare all loop-scoped variables with `local`. The reporter's inner loop declares ~10 `local` vars per iteration (`hermes-report.sh:64-65`, `:87`, `:115`, `:167`, etc.) — preserve this when adding fields.
- Build long CLI invocations as arrays, then invoke `"${cmd[@]}"`. Append optional flags conditionally with `cmd+=(--flag "${value}")`. Canonical example: `hermes-report.sh:216-249`.
## File-Format Contracts (the public interface)
- Required: `alertId` (string).
- Optional: `autonomousMode` (bool), `notifyChannel` (string), `notifyTarget` (string), `organizationName` (string).
- Read via `read_config_field` in `budget-check.sh:15-24`.
- Fields (camelCase): `currentValue`, `threshold`, `percentUsed`, `exceeded`, `halted`, `haltedAt`, `lastChecked`.
- `halted` transitions: only `budget-check.sh:72-82` sets `halted: true` (on a *new* breach when `autonomousMode` is on) or carries forward an existing halt. Clearing is exclusively `clear-halt.sh`'s job. Do not add code paths that clear `halted` elsewhere.
- Format: `HERMES:<session_id>:<total_tokens>:<unix_ts>`
- Read with `grep "^HERMES:${sid}:"` + `cut -d: -fN`. The colon-delimited shape and the `HERMES:` prefix are part of the idempotency contract — see "Metering ledger semantics" in `CLAUDE.md`.
## SKILL.md Frontmatter Contract
## Legacy Branding Guard
## Module Design
- One concern per script. `cron.sh` orchestrates; `hermes-report.sh` meters; `budget-check.sh` evaluates budget; `clear-halt.sh` resets halt; `install-cron.sh` / `uninstall-cron.sh` manage the cron entry. Don't merge concerns.
- Sharing happens through `common.sh` (sourced) or through state files on disk. No script invokes another by relative path except through `${SKILL_DIR}/scripts/` (`cron.sh:17-18`).
- Every new script in `skills/revenium/scripts/` must (a) source `common.sh`, (b) be added to the `expected` list in `tests/test_repository.py:11-26`, (c) ship with `chmod +x` (preserved by `examples/setup-local.sh:10` and `install-cron.sh:10`), and (d) parse without errors under `bash -n` (covered by `test_shell_scripts_have_valid_syntax`).
- One `TestCase` subclass (`RepositoryTests`) per concern area; methods are independent and rely only on filesystem state, not on each other.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## System Overview
```text
```
## Component Responsibilities
| Component | Responsibility | File |
|-----------|----------------|------|
| Skill prompt | Mandatory budget check on every Hermes turn; emit verbatim halt string when `halted: true` | `skills/revenium/SKILL.md` |
| Path resolver / shared helpers | Single source of truth for all `~/.hermes` paths; `ensure_path`, logging | `skills/revenium/scripts/common.sh` |
| Cron orchestrator | Source `common.sh` + optional `env`, invoke reporter then checker (errors swallowed with `|| true`) | `skills/revenium/scripts/cron.sh` |
| Metering reporter | Read `state.db`, compute per-session token deltas vs ledger, scale costs, ship to Revenium, append ledger | `skills/revenium/scripts/hermes-report.sh` |
| Budget checker | Fetch alert from Revenium, write `budget-status.json`, detect new halt transitions, send notification | `skills/revenium/scripts/budget-check.sh` |
| Halt clearer | Manually clear `halted` flag and remove `haltedAt` from `budget-status.json` | `skills/revenium/scripts/clear-halt.sh` |
| Cron installer | Write `* * * * *` crontab line with explicit `PATH`, `HERMES_HOME`, `REVENIUM_STATE_DIR` env | `skills/revenium/scripts/install-cron.sh` |
| Cron uninstaller | Remove the tagged crontab line | `skills/revenium/scripts/uninstall-cron.sh` |
| Local install helper | Copy `skills/revenium/` into `~/.hermes/skills/revenium/` for end-to-end testing | `examples/setup-local.sh` |
| Repo invariant tests | Enforce file layout, frontmatter shape, runtime-path discipline, shell syntax, no legacy branding | `tests/test_repository.py` |
## Pattern Overview
- No runtime, no daemon, no IPC — coupling is filesystem-only (`config.json`, `budget-status.json`, `revenium-hermes.ledger`).
- The skill never calls the Revenium API directly; it only reads the local cron-maintained snapshot for low-latency budget checks.
- All Bash scripts source `common.sh` for path resolution — paths are never inlined.
- Idempotent metering via an append-only ledger keyed on `HERMES:<session_id>:<total_tokens>`.
## Layers
- Purpose: Static skill assets shipped to `~/.hermes/skills/revenium/`.
- Location: `skills/revenium/`
- Contains: `SKILL.md`, `scripts/*.sh`, `references/*.md`
- Depends on: nothing in this repo at runtime (it is the runtime).
- Used by: the Hermes agent (reads `SKILL.md`) and `cron` (executes `scripts/*.sh`).
- Purpose: The only communication channel between the two halves.
- Location: `~/.hermes/state/revenium/` (resolved by `common.sh`, not present in repo)
- Contains: `config.json`, `budget-status.json`, `revenium-hermes.ledger`, `revenium-metering.log`, optional `env`
- Depends on: written by `budget-check.sh`, `hermes-report.sh`, `clear-halt.sh`, and the Hermes setup flow.
- Used by: read by `SKILL.md` (via Hermes file tools) and by every script in the cron pipeline.
- Purpose: Reads from Hermes' session DB; writes to Revenium platform via the `revenium` CLI.
- Hermes session DB: `~/.hermes/state.db` (the `sessions` table — read-only from this skill's perspective)
- Revenium CLI: `revenium meter completion`, `revenium alerts budget get`, `revenium config show`
- Hermes messaging: `hermes chat --toolsets messaging -q "Use the send_message tool ..."` for halt notifications.
- Purpose: Distribution metadata and developer ergonomics.
- Location: repo root — `README.md`, `docs/`, `examples/`, `tests/`, `CLAUDE.md`
- Contains: install docs, local-setup helper, invariant tests, contributor guide.
- Used by: humans and the `hermes skills tap add` discovery mechanism (which scans `skills/`).
## Data Flow
### Primary metering path (every minute, out of process)
### Budget-status / halt path
### Skill-prompt read path (every Hermes turn, in process)
### Halt-clear path (manual operator action)
- All mutable state is plain JSON / line-oriented text files under `~/.hermes/state/revenium/`.
- No in-memory shared state between scripts — every script re-reads the files it cares about.
- The ledger is append-only; idempotency is enforced by `grep -q "^HERMES:${sid}:${total_tokens}:"` before the API call (`skills/revenium/scripts/hermes-report.sh:71`).
## Key Abstractions
- Purpose: One file owns every state path. All other scripts `source` it before doing anything.
- Variables exported: `HERMES_HOME`, `REVENIUM_STATE_DIR`, `SKILL_DIR`, `STATE_DIR`, `CONFIG_FILE`, `BUDGET_STATUS_FILE`, `LEDGER_FILE`, `LOG_FILE`, `ENV_FILE`, `STATE_DB`.
- File: `skills/revenium/scripts/common.sh`
- Pattern: Environment-variable-overridable defaults (`${HERMES_HOME:-${HOME}/.hermes}`) so cron and tests can redirect to alternate roots.
- Also provides: `ensure_path` (prepends brew / linuxbrew / `~/.local/bin` etc. so cron can find `revenium`, `sqlite3`, `python3`), and `log`/`info`/`warn`/`error` (timestamped writes to `LOG_FILE`).
- Purpose: Idempotent reporting of token usage that grows over time.
- File: `~/.hermes/state/revenium/revenium-hermes.ledger`
- Pattern: Each successful report appends `HERMES:<session_id>:<total_tokens>:<unix_ts>`. Re-running the cron skips any line whose `(session_id, total_tokens)` already exists. Token totals are diffed against the most recent prior line for the same session and per-field counts/costs are scaled by `(curr - prev) / curr`.
- Code: `skills/revenium/scripts/hermes-report.sh:70`–`107`
- Purpose: Distinguish a *new* halt (this run flipped exceeded under autonomous mode) from carrying an *existing* halt forward.
- File: `skills/revenium/scripts/budget-check.sh:64`–`82`
- Pattern: Read prior `halted` from existing `budget-status.json`. If `autonomous && exceeded && !prev_halted` → new halt, record `haltedAt = now`, emit `HALT_TRANSITION=true`. If `prev_halted` → carry forward `haltedAt`. Otherwise → `halted = false`. Clearing is never automatic.
- Purpose: Map Hermes' `model` + `billing_provider` columns to a Revenium provider string.
- File: `skills/revenium/scripts/hermes-report.sh:115`–`165`
- Pattern: Python heredoc with substring matching. OpenRouter and Bedrock are special-cased — they decode the *underlying* model provider rather than passing through the proxy name.
- Purpose: `hermes skills tap add owner/repo` looks for skills under `skills/<name>/SKILL.md` with `name:`, `metadata.hermes`, and `category: devops`.
- File: `skills/revenium/SKILL.md:1`–`20`
- Enforcement: `tests/test_repository.py::test_skill_frontmatter_has_hermes_metadata`.
## Entry Points
- Location: `skills/revenium/scripts/cron.sh`
- Triggers: per-minute crontab entry installed by `install-cron.sh`.
- Responsibilities: source `common.sh` + optional `env` file, run reporter, run checker.
- Location: `skills/revenium/scripts/hermes-report.sh`
- Triggers: `cron.sh` or direct invocation.
- Responsibilities: read `state.db`, compute deltas, call `revenium meter completion`, append ledger.
- Location: `skills/revenium/scripts/budget-check.sh`
- Triggers: `cron.sh` or direct invocation.
- Responsibilities: fetch alert, write `budget-status.json`, fire halt notification on transition.
- Location: `skills/revenium/scripts/clear-halt.sh`
- Triggers: human-invoked (or shown in the halt string of `SKILL.md`).
- Responsibilities: mutate `budget-status.json` only — does not touch Revenium.
- Location: `skills/revenium/scripts/install-cron.sh`, `skills/revenium/scripts/uninstall-cron.sh`
- Triggers: human-invoked, also called as the final step of the setup flow in `SKILL.md`.
- Responsibilities: idempotently add/remove a single crontab line tagged `# hermes-revenium-metering`.
- Location: `skills/revenium/SKILL.md`
- Triggers: Hermes loads on every relevant invocation.
- Responsibilities: enforce the mandatory pre-operation budget check.
- Location: `examples/setup-local.sh`
- Triggers: human-invoked from repo root.
- Responsibilities: copy `skills/revenium/` into `~/.hermes/skills/revenium/` and `chmod +x` the scripts.
## Architectural Constraints
- **No runtime / no build step:** This repo ships static text. The "application" is a skill plus a set of shell scripts; there is nothing to compile or package.
- **State paths must live in `common.sh`:** `tests/test_repository.py::test_runtime_paths_are_hermes_native` greps `common.sh` for `.hermes` and `state/revenium` and forbids the forked-tool runtime-path literal (see `tests/test_repository.py:55`). Adding a new state file means adding its variable to `common.sh`, not hard-coding it elsewhere.
- **Skill location is contractual:** The skill must live at `skills/revenium/` (not the repo root) for `hermes skills tap add owner/repo` to discover it.
- **Frontmatter is contractual:** `name: revenium`, `metadata.hermes:` block, and `category: devops` are all enforced by `tests/test_repository.py::test_skill_frontmatter_has_hermes_metadata`.
- **No legacy branding:** `tests/test_repository.py::test_no_legacy_branding_left` greps every `.md`/`.sh`/`.py`/`.txt`/`.json`/`.yml`/`.yaml` file in the repo for forbidden product names. The forbidden regex lives in `tests/test_repository.py:47`; consult the test, do not reproduce the strings.
- **Shell strictness:** Scripts use `set -euo pipefail` (simple ones) or `set -uo pipefail` (`common.sh`, `hermes-report.sh` — which need to continue past individual failures). Preserve these when editing. `tests/test_repository.py::test_shell_scripts_have_valid_syntax` runs `bash -n` on every script.
- **Two halves never call each other:** The skill prompt MUST NOT execute the cron scripts to refresh state on demand; conversely the cron scripts MUST NOT invoke Hermes for anything except the one notification call in `budget-check.sh`. All other coupling is filesystem state.
- **Cron environment is restricted:** `install-cron.sh:26` embeds an explicit `PATH=` and `HERMES_HOME=`, `REVENIUM_STATE_DIR=` because cron starts with an almost-empty environment. `ensure_path` in `common.sh` is a defense in depth.
- **Idempotency:** Re-running `cron.sh` must never double-report. The ledger + `transaction-id = ${sid}-${total_tokens}` design is what guarantees this — preserve both invariants together.
## Anti-Patterns
### Inlining state paths
### Auto-clearing a halt from `budget-check.sh`
### Reporting totals instead of deltas
### Calling the Revenium API from `SKILL.md`
### Modifying the halt response string
## Error Handling
- Reporter pre-flight checks (`hermes-report.sh:13`–`32`) `exit 0` on missing tools (`revenium`, `sqlite3`, `python3`, `state.db`, unconfigured CLI). Never aborts the cron pipeline.
- `cron.sh` calls each child with `|| true` so reporter failure does not block the budget check, and vice versa (`cron.sh:17`–`18`).
- Per-session loop in `hermes-report.sh` swallows individual failures with `((counter++)) || true` and `continue` rather than aborting the run.
- `budget-check.sh` uses `set -euo pipefail` — it aborts on any failure, which is appropriate because writing a stale or inconsistent `budget-status.json` is worse than not writing one.
- `SKILL.md` fails open if `budget-status.json` is missing or unreadable (`SKILL.md:85`–`88`) so a never-installed-cron does not prevent any work.
- All logs go through `info`/`warn`/`error` in `common.sh:30`–`38`, timestamped UTC, ISO-8601, to `LOG_FILE`.
## Cross-Cutting Concerns
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
