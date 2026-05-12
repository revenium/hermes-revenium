# Coding Conventions

**Analysis Date:** 2026-05-12

This is a Hermes Agent skill distribution package. The vast majority of executable code is Bash (under `skills/revenium/scripts/`), with Python embedded inline as heredocs for any JSON/datetime/math logic. The only standalone Python lives under `tests/` and uses the standard-library `unittest` framework. There is no build step, no compiled artifact, no application runtime, and no linter/formatter wired up — preserve existing style by example.

## Naming Patterns

**Files:**
- Bash scripts: `kebab-case.sh` — e.g., `skills/revenium/scripts/hermes-report.sh`, `skills/revenium/scripts/budget-check.sh`, `skills/revenium/scripts/clear-halt.sh`, `skills/revenium/scripts/install-cron.sh`, `skills/revenium/scripts/uninstall-cron.sh`, `skills/revenium/scripts/cron.sh`
- Library/sourced bash: lowercase single-word — `skills/revenium/scripts/common.sh`
- Python tests: `test_*.py` — required by the discovery pattern (`tests/test_repository.py`)
- Docs: `lower_or_kebab.md` — e.g., `docs/installation.md`, `skills/revenium/references/setup.md`, `skills/revenium/references/troubleshooting.md`
- Top-level docs: `UPPERCASE.md` — `README.md`, `CLAUDE.md`

**Bash variables:**
- Exported / config-like globals: `SCREAMING_SNAKE_CASE` — `STATE_DIR`, `CONFIG_FILE`, `BUDGET_STATUS_FILE`, `LEDGER_FILE`, `LOG_FILE`, `STATE_DB`, `ENV_FILE`, `HERMES_HOME`, `REVENIUM_STATE_DIR`, `SKILL_DIR`, `SCRIPT_DIR`
- Loop / local / transient variables: `lower_snake_case` declared with `local` — see `hermes-report.sh` (`local total_tokens`, `local ledger_key`, `local prev_reported_tokens`, etc.)
- Cron-side env passed in: `SCREAMING_SNAKE_CASE` — `HERMES_HOME=…`, `REVENIUM_STATE_DIR=…`, `PATH=…` in `install-cron.sh:26`

**Bash functions:**
- `lower_snake_case` — `ensure_path`, `log`, `info`, `warn`, `error`, `read_config_field`, `main`

**JSON keys (the cron / skill contract):**
- `camelCase` — `currentValue`, `threshold`, `percentUsed`, `exceeded`, `halted`, `haltedAt`, `lastChecked`, `alertId`, `autonomousMode`, `notifyChannel`, `notifyTarget`, `organizationName`. Preserve this casing when reading/writing `config.json` and `budget-status.json`.

## Code Style

**Formatting:**
- No linter or formatter is wired up (per `CLAUDE.md`). Match the style of neighboring files by example.
- 2-space indentation in Bash (see `hermes-report.sh`, `budget-check.sh`).
- 4-space indentation in Python (both standalone tests and embedded heredocs).
- LF line endings; trailing newline on every file.

**Bash `set` flags (mandatory):**
- Use `set -euo pipefail` for simple top-level scripts that fail fast: `clear-halt.sh:2`, `cron.sh:2`, `budget-check.sh:2`, `install-cron.sh:2`, `uninstall-cron.sh:2`, `examples/setup-local.sh:2`.
- Use `set -uo pipefail` (without `-e`) for the two scripts that intentionally tolerate per-step failures and want to log/continue:
  - `skills/revenium/scripts/common.sh:4` — sourced by every script; `-e` would propagate aggressively into every caller.
  - `skills/revenium/scripts/hermes-report.sh:6` — a single failed `revenium meter completion` call must not abort the rest of the session loop. Errors are explicitly captured with `cmd_exit=$?` and logged via `warn`.
- Do not switch a script's flags without understanding which mode it needs. `CLAUDE.md:33` calls this out as a preserve-when-editing rule.

**Bootstrap pattern (every script that does work):**
```bash
#!/usr/bin/env bash
set -euo pipefail   # or -uo pipefail for common.sh / hermes-report.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path
```
- Always resolve `SCRIPT_DIR` via `BASH_SOURCE[0]` (not `$0`), so the script works when invoked via cron, symlink, or `bash <path>`.
- Always include the `# shellcheck source=/dev/null` directive on the line above `source`.
- Always call `ensure_path` immediately after sourcing — cron runs with a minimal `PATH` and needs `/opt/homebrew/bin`, `~/.local/bin`, etc., prepended before `revenium`, `sqlite3`, or `python3` will resolve.

**Variable quoting and expansion:**
- Always quote expansions: `"${STATE_DIR}"`, `"${cmd[@]}"`, `"${BASH_SOURCE[0]}"`.
- Always use `${var}` braces, never bare `$var`.
- Default-with-fallback for envs: `HERMES_HOME="${HERMES_HOME:-${HOME}/.hermes}"`, `REVENIUM_STATE_DIR="${REVENIUM_STATE_DIR:-${HERMES_HOME}/state/revenium}"` (`common.sh:6-7`). New env-driven paths must follow this `:-` fallback shape.
- Conditionals use `[[ ... ]]` exclusively, not `[ ... ]` or `test`.
- Array commands are built up and invoked with `"${cmd[@]}"` — see `hermes-report.sh:216-251` for the canonical pattern (conditionally appending flags via `cmd+=(--flag "${value}")`).

## Single Source of Truth: `common.sh`

**`skills/revenium/scripts/common.sh` is the single source of truth for state paths.** All other scripts must source it and consume:

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

**Rules:**
- Never hardcode `~/.hermes/...` paths in any other script — always reference the variable from `common.sh`.
- Add new state paths to `common.sh` (between `STATE_DIR` and `mkdir -p`), not inline in the calling script.
- The string literals `.hermes` and `state/revenium` must remain in `common.sh` — `tests/test_repository.py::test_runtime_paths_are_hermes_native` (`tests/test_repository.py:51-55`) asserts both are present.
- `common.sh` also exposes the `ensure_path`, `log`, `info`, `warn`, `error` helpers. New logging should go through `info` / `warn` / `error`, which timestamp and tee to `${LOG_FILE}` and stderr.

## Python Heredocs Inside Bash

Bash is the orchestration layer; Python heredocs are used wherever JSON, datetimes, or floating-point math are needed. The pattern appears in `budget-check.sh`, `clear-halt.sh`, and heavily in `hermes-report.sh`.

**Two heredoc shapes are in use — pick deliberately:**

1. **Quoted delimiter (`<<'PY'`) — values passed via environment.** Use when the Python body must run verbatim and any expansion would be unsafe. Bash variables are exposed by exporting them on the same command line.

   ```bash
   read_config_field() {
     CONFIG_FILE="${CONFIG_FILE}" KEY="$1" python3 - <<'PY'
   import json, os
   val = json.load(open(os.environ['CONFIG_FILE'])).get(os.environ['KEY'], '')
   ...
   PY
   }
   ```
   See `budget-check.sh:15-24` and the larger block at `budget-check.sh:43-94`. This is the preferred shape for any Python doing real work — it's safer against quoting bugs.

2. **Unquoted delimiter (`<<PY`) — values interpolated by Bash.** Used in `clear-halt.sh:13-27` (`path = Path(${BUDGET_STATUS_FILE@Q})` — the `@Q` operator shell-quotes the value safely) and in the small `python3 -c "..."` one-liners scattered through `hermes-report.sh:90-214`. Acceptable for short scalar math/formatting, but never interpolate untrusted strings without `@Q`.

**Conventions for embedded Python:**
- Stdlib only (`json`, `os`, `re`, `time`, `datetime`, `pathlib`). No `pip install`-able imports.
- Inline `import` at top of each heredoc — these are throwaway interpreters, not modules.
- Use `print(...)` for the single piece of data the caller will capture with `$( ... )`. For multi-value output, emit `KEY=value` lines and parse with `sed -n 's/^KEY=//p'` (see `budget-check.sh:88-102`).
- Tolerate failure with `|| true` or `|| echo "fallback"` when the value is non-critical (provider inference, timestamp formatting in `hermes-report.sh:124,165,179`).

## Import Organization (Python)

**Test files (`tests/test_repository.py`):**
- Stdlib imports only, alphabetized: `re`, `subprocess`, `unittest`, then `from pathlib import Path`.
- Module-level constants in `SCREAMING_SNAKE_CASE` immediately below imports: `ROOT = Path(__file__).resolve().parents[1]`, `SKILL = ROOT / 'skills' / 'revenium'`.

No path aliases; no third-party imports anywhere in the repo.

## Error Handling

**Bash:**
- Hard-fail mode (`set -e`) is the default for orchestration scripts. They should fail loudly rather than partially complete.
- Soft-fail mode (`set -uo pipefail` without `-e`) is reserved for `common.sh` and `hermes-report.sh`. In soft-fail scripts:
  - Capture exit codes explicitly: `cmd_output=$("${cmd[@]}" 2>&1) && cmd_exit=0 || cmd_exit=$?` (`hermes-report.sh:251`).
  - Log via `warn` / `error` and continue the loop; never silently swallow.
  - Use `|| true` on counters and best-effort lookups (`((reported_count++)) || true`, `grep ... || true`).
- The orchestrator `cron.sh:17-18` deliberately appends `|| true` after each child invocation so a metering failure doesn't block the budget check (or vice versa).
- Preflight required tooling before doing work and exit `0` with a `warn` if missing (so cron doesn't email errors on a fresh machine):
  ```bash
  if ! command -v revenium >/dev/null 2>&1; then
    warn "revenium CLI not found on PATH — skipping metering."
    exit 0
  fi
  ```
  See `hermes-report.sh:13-32` for the full preflight stack (`revenium`, `sqlite3`, `python3`, `state.db`, `revenium config show`).

**Python heredocs:**
- Wrap optional file reads in `try/except Exception: pass` and fall back to defaults — see `budget-check.sh:64-70` where a missing/corrupt `budget-status.json` becomes an empty `prev = {}` rather than a hard crash.

## Logging

**Framework:** Custom `log` / `info` / `warn` / `error` helpers in `skills/revenium/scripts/common.sh:30-38`.

**Format:** `[<ISO8601 UTC>] [<LEVEL>] [revenium] <message>` — tee'd to `${LOG_FILE}` and stderr.

**When to use which:**
- `info`: lifecycle events ("=== Hermes Metering Reporter starting ===", "Reported: session=…"), normal flow.
- `warn`: recoverable conditions, missing optional tooling, per-session failures. The script should keep going.
- `error`: fatal conditions before exiting (rare in this codebase — most fatal paths use a bare `echo` + `exit 1` because they're user-facing one-shot CLIs like `clear-halt.sh` and `budget-check.sh`).
- Bare `echo` (no log helper): user-facing CLI output from `install-cron.sh`, `uninstall-cron.sh`, `clear-halt.sh`, `setup-local.sh`. These talk to a human at a terminal, not to the cron logfile.

**Never log secrets.** No script should `echo` or `info` the contents of `${ENV_FILE}`, `REVENIUM_API_KEY`, or anything from `~/.config/revenium/config.yaml`.

## Comments

**When to comment:**
- File-level comment after the shebang and `set` line, explaining the script's role — e.g., `hermes-report.sh:2-3` ("Hermes-native Revenium reporter. Reads token usage…"), `common.sh:2` ("Common helpers for the Hermes Revenium skill.").
- ShellCheck directives where required: `# shellcheck source=/dev/null` immediately above every dynamic `source`.
- Inline comments are sparse — prefer self-documenting variable names. When present, they explain *why*, not *what* (see `budget-check.sh:42` "Update budget-status.json and decide if we just transitioned into halt.").

**Avoid:** TODO/FIXME comments. None currently exist in `skills/revenium/scripts/`; keep it that way by filing issues instead.

## Function Design

**Bash:**
- Tiny utility wrappers in `common.sh` (`info`, `warn`, `error`) one-line through to `log`. Don't inline `echo "[$(date ...)]"` constructions in callers.
- Larger scripts wrap their core flow in a `main()` function and invoke it with `main "$@"` at EOF (see `hermes-report.sh:41,268`). One-shot scripts that are linear (`install-cron.sh`, `clear-halt.sh`, `cron.sh`) skip this and run top-to-bottom.
- Declare all loop-scoped variables with `local`. The reporter's inner loop declares ~10 `local` vars per iteration (`hermes-report.sh:64-65`, `:87`, `:115`, `:167`, etc.) — preserve this when adding fields.
- Build long CLI invocations as arrays, then invoke `"${cmd[@]}"`. Append optional flags conditionally with `cmd+=(--flag "${value}")`. Canonical example: `hermes-report.sh:216-249`.

## File-Format Contracts (the public interface)

The cron half and the skill-prompt half of this package **never call each other** — they communicate by file. Treat the shapes of these files as a stable interface; don't change keys without coordinating both sides.

**`${STATE_DIR}/config.json`** — written by the user / `/revenium` setup, read by cron.
- Required: `alertId` (string).
- Optional: `autonomousMode` (bool), `notifyChannel` (string), `notifyTarget` (string), `organizationName` (string).
- Read via `read_config_field` in `budget-check.sh:15-24`.

**`${STATE_DIR}/budget-status.json`** — written by `budget-check.sh`, read by Hermes and `clear-halt.sh`.
- Fields (camelCase): `currentValue`, `threshold`, `percentUsed`, `exceeded`, `halted`, `haltedAt`, `lastChecked`.
- `halted` transitions: only `budget-check.sh:72-82` sets `halted: true` (on a *new* breach when `autonomousMode` is on) or carries forward an existing halt. Clearing is exclusively `clear-halt.sh`'s job. Do not add code paths that clear `halted` elsewhere.

**`${STATE_DIR}/revenium-hermes.ledger`** — append-only, one line per successful Revenium report.
- Format: `HERMES:<session_id>:<total_tokens>:<unix_ts>`
- Read with `grep "^HERMES:${sid}:"` + `cut -d: -fN`. The colon-delimited shape and the `HERMES:` prefix are part of the idempotency contract — see "Metering ledger semantics" in `CLAUDE.md`.

**`${STATE_DIR}/env`** — optional shell file sourced by `cron.sh:10-15` under `allexport`. Plain `KEY=value` lines. Never read or echo its contents from logs.

## SKILL.md Frontmatter Contract

`skills/revenium/SKILL.md` must keep this exact frontmatter shape — enforced by `tests/test_repository.py::test_skill_frontmatter_has_hermes_metadata` (`tests/test_repository.py:30-35`):

```yaml
---
name: revenium
description: "..."
version: ...
author: Revenium
license: MIT
category: DevOps
platforms: [macos, linux]
required_environment_variables:
  - REVENIUM_API_KEY
  - REVENIUM_API_URL
  - REVENIUM_TEAM_ID
required_credential_files:
  - path: ~/.config/revenium/config.yaml
    description: ...
metadata:
  hermes:
    tags: [DevOps, FinOps, revenium, budgets, metering, observability]
    category: devops
---
```

**Test-enforced minimum:** the file must contain the literal substrings `name: revenium`, `metadata:`, `hermes:`, and `category: devops`. (The top-level `category: DevOps` and the nested `metadata.hermes.category: devops` are intentionally both present — the lowercase one drives Hermes tap discoverability and matches the test, the capitalized one is human-facing.)

**Halt response string:** the exact halt sentence in `SKILL.md:35` is contractual — Hermes is instructed to emit it verbatim when `halted: true`. Treat the string as part of the public interface; don't rewrite it casually.

**Location:** the skill must live at `skills/revenium/`, not the repo root — `hermes skills tap add owner/repo` discovers it via the default `skills/` prefix. Moving it breaks tap installation.

## Legacy Branding Guard

`tests/test_repository.py::test_no_legacy_branding_left` (`tests/test_repository.py:37-49`) greps every `.md`, `.sh`, `.py`, `.txt`, `.json`, `.yml`, and `.yaml` file in the repo for forbidden strings forked from a previous tool. Read the regex directly at `tests/test_repository.py:47` — do not reproduce the strings elsewhere. The test file itself is exempted by name (`tests/test_repository.py:44`).

**Rule for contributors:** when porting any content from upstream sources, scrub all matches before committing. The test fails the build on a single occurrence.

## Module Design

**Bash:**
- One concern per script. `cron.sh` orchestrates; `hermes-report.sh` meters; `budget-check.sh` evaluates budget; `clear-halt.sh` resets halt; `install-cron.sh` / `uninstall-cron.sh` manage the cron entry. Don't merge concerns.
- Sharing happens through `common.sh` (sourced) or through state files on disk. No script invokes another by relative path except through `${SKILL_DIR}/scripts/` (`cron.sh:17-18`).
- Every new script in `skills/revenium/scripts/` must (a) source `common.sh`, (b) be added to the `expected` list in `tests/test_repository.py:11-26`, (c) ship with `chmod +x` (preserved by `examples/setup-local.sh:10` and `install-cron.sh:10`), and (d) parse without errors under `bash -n` (covered by `test_shell_scripts_have_valid_syntax`).

**Python tests:**
- One `TestCase` subclass (`RepositoryTests`) per concern area; methods are independent and rely only on filesystem state, not on each other.

---

*Convention analysis: 2026-05-12*
