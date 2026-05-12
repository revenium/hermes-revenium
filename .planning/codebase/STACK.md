# Technology Stack

**Analysis Date:** 2026-05-12

## Languages

**Primary:**
- Bash 4+ - All runtime/cron scripts under `skills/revenium/scripts/` (`common.sh`, `cron.sh`, `hermes-report.sh`, `budget-check.sh`, `install-cron.sh`, `uninstall-cron.sh`, `clear-halt.sh`)
- Python 3 - Embedded heredocs inside bash scripts for JSON manipulation, datetime formatting, and delta arithmetic (e.g., `skills/revenium/scripts/hermes-report.sh:90-97`, `skills/revenium/scripts/budget-check.sh:47-93`). Also used standalone for tests.

**Secondary:**
- SQL (SQLite dialect) - Inline query against the Hermes session DB in `skills/revenium/scripts/hermes-report.sh:45-53`
- YAML - Frontmatter at the top of `skills/revenium/SKILL.md` defining skill metadata
- Markdown - Documentation in `README.md`, `CLAUDE.md`, `docs/installation.md`, `skills/revenium/SKILL.md`, `skills/revenium/references/*.md`

## Runtime

**Environment:**
- macOS (Darwin) and Linux — declared in `skills/revenium/SKILL.md:8` (`platforms: [macos, linux]`)
- POSIX shell with bash via `#!/usr/bin/env bash`
- Python 3 — invoked as `python3` (no minimum version pinned); required at runtime per `skills/revenium/scripts/hermes-report.sh:21-24`
- SQLite 3 CLI (`sqlite3`) — required at runtime per `skills/revenium/scripts/hermes-report.sh:17-20`
- cron — Unix per-minute scheduler installed by `skills/revenium/scripts/install-cron.sh`

**Package Manager:**
- None for this repo itself (no `package.json`, `requirements.txt`, `pyproject.toml`, or lockfile)
- Homebrew is referenced as the recommended installer for the `revenium` CLI (`brew install revenium/tap/revenium`, see `README.md:9` and `skills/revenium/SKILL.md:130`)
- Homebrew prefixes are auto-prepended to `PATH` in `skills/revenium/scripts/common.sh:20-28` and `skills/revenium/scripts/install-cron.sh:17-24`

## Frameworks

**Core:**
- None — no application framework. The skill is a packaging artifact, not an executable.

**Testing:**
- Python `unittest` (stdlib) — see `tests/test_repository.py:1-3`. Run via `python3 -m unittest discover -s tests -p 'test_*.py' -v`.
- `bash -n` syntax check is invoked from inside Python tests (`tests/test_repository.py:60-65`)

**Build/Dev:**
- No build system. No compiler, transpiler, bundler, or task runner.
- No linter, formatter, or pre-commit config is wired up (per `CLAUDE.md` "Common commands" section)

## Key Dependencies

**Critical (runtime, not vendored — must be present on the host):**
- `revenium` CLI — primary external dependency. Used by `skills/revenium/scripts/hermes-report.sh:217` (`revenium meter completion`), `skills/revenium/scripts/budget-check.sh:32` (`revenium alerts budget get`), and during skill setup (`revenium config show/set`, `revenium alerts budget create/list/delete`).
- `sqlite3` CLI — reads `~/.hermes/state.db` in `skills/revenium/scripts/hermes-report.sh:45-53`
- `python3` — used inline for JSON parsing, ratio math, and datetime formatting throughout the bash scripts
- `bash` — declared shebang on every script; `set -euo pipefail` or `set -uo pipefail` is required by `tests/test_repository.py::test_shell_scripts_have_valid_syntax`
- `hermes` CLI — used by `skills/revenium/scripts/budget-check.sh:105-110` to dispatch halt notifications via Hermes' messaging toolset
- `cron`/`crontab` — required for the metering loop; managed by `install-cron.sh` and `uninstall-cron.sh`

**Infrastructure:**
- None vendored. The repo is intentionally zero-dependency at the file level.

## Configuration

**Environment:**
- `HERMES_HOME` — defaults to `${HOME}/.hermes`, overridable. Set by `skills/revenium/scripts/common.sh:6`.
- `REVENIUM_STATE_DIR` — defaults to `${HERMES_HOME}/state/revenium`, overridable. Set by `skills/revenium/scripts/common.sh:7`.
- `REVENIUM_API_KEY`, `REVENIUM_API_URL`, `REVENIUM_TEAM_ID` — declared as `required_environment_variables` in `skills/revenium/SKILL.md:9-12`. In practice consumed by the `revenium` CLI, not this repo.
- Optional per-state env file at `${STATE_DIR}/env` (`ENV_FILE` in `skills/revenium/scripts/common.sh:15`), sourced by `skills/revenium/scripts/cron.sh:10-15` when present.
- `.env` files are git-ignored (`.gitignore:4`). No `.env` is shipped or read by the repo itself.

**Build:**
- None.

**Skill state files (the runtime "public interface" between cron and skill prompt):**
- `~/.hermes/state/revenium/config.json` — alert ID, organization name, autonomous flag, notification channel/target. Schema documented in `README.md:131-148` and `skills/revenium/SKILL.md:204-231`.
- `~/.hermes/state/revenium/budget-status.json` — last cron snapshot (`currentValue`, `threshold`, `percentUsed`, `exceeded`, `halted`, `haltedAt`, `lastChecked`). Produced by `skills/revenium/scripts/budget-check.sh:43-93`.
- `~/.hermes/state/revenium/revenium-hermes.ledger` — append-only idempotency ledger; lines are `HERMES:<session_id>:<total_tokens>:<unix_ts>` (`skills/revenium/scripts/hermes-report.sh:70-71, 256`).
- `~/.hermes/state/revenium/revenium-metering.log` — cron log (`skills/revenium/scripts/common.sh:14`).

**Credential files (read by the `revenium` CLI, not this repo):**
- `~/.config/revenium/config.yaml` — Revenium CLI credentials. Declared in `skills/revenium/SKILL.md:13-15`. The skill never reads or writes this file directly (per `README.md:149`).

**Tap/discovery metadata:**
- Skill is placed at `skills/revenium/` so Hermes' default tap path resolves it (`README.md:29`, `docs/installation.md:12-18`). Do not relocate.
- `skills/revenium/SKILL.md` frontmatter must contain `name: revenium`, a `metadata.hermes` block, and `category: devops` — enforced by `tests/test_repository.py::test_skill_frontmatter_has_hermes_metadata`.

## Platform Requirements

**Development:**
- macOS or Linux with bash, python3, sqlite3, and the `revenium` CLI installed
- No Node, no JVM, no Docker, no compiled toolchain

**Production:**
- Same as development. The skill runs in the user's home directory under `~/.hermes/`. There is no server, container, or deployed artifact — distribution is by `git clone` / GitHub tap / `cp -R`.
- Crontab access on the host machine is required; `install-cron.sh` writes via `crontab -` (see `skills/revenium/scripts/install-cron.sh:34`).
- Hermes Agent must be installed locally for the skill to be useful, but Hermes itself is not a build/test dependency of this repo.

---

*Stack analysis: 2026-05-12*
