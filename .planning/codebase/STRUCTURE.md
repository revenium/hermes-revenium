# Codebase Structure

**Analysis Date:** 2026-05-12

## Directory Layout

```
hermes-revenium/
├── CLAUDE.md                       # Contributor guide for Claude Code — read first
├── README.md                       # End-user install / overview
├── .gitignore
├── docs/
│   └── installation.md             # Tap / external_dirs / manual install paths
├── examples/
│   └── setup-local.sh              # Copy skills/revenium/ to ~/.hermes/skills/revenium/
├── skills/
│   └── revenium/                   # THE shipped skill — only thing end users install
│       ├── SKILL.md                # Hermes-loaded prompt + frontmatter
│       ├── references/
│       │   ├── setup.md            # Setup / reset / reconfigure flows
│       │   └── troubleshooting.md  # Failure modes and operator fixes
│       └── scripts/
│           ├── common.sh           # Path resolver — sole source of truth
│           ├── cron.sh             # Orchestrator: report + check
│           ├── hermes-report.sh    # Reads state.db, ships token deltas
│           ├── budget-check.sh     # Writes budget-status.json, fires notification
│           ├── clear-halt.sh       # Manual halt clear
│           ├── install-cron.sh     # Adds per-minute crontab line
│           └── uninstall-cron.sh   # Removes the crontab line
├── tests/
│   └── test_repository.py          # stdlib unittest — file layout & invariant checks
└── .planning/
    └── codebase/                   # Generated mapping documents (this directory)
```

The repo has no build directory, no `dist/`, no compiled artifacts, no `node_modules`, no `venv`. There is also no `Makefile`, `package.json`, `pyproject.toml`, or `requirements.txt` — `tests/test_repository.py` is pure stdlib.

## Directory Purposes

**`skills/revenium/`:**
- Purpose: The only thing that gets installed. Everything under this directory is copied verbatim to `~/.hermes/skills/revenium/`.
- Contains: skill prompt, references, runtime scripts.
- Key files: `SKILL.md`, `scripts/common.sh`, `scripts/cron.sh`.
- Constraint: This directory must stay at `skills/revenium/` for `hermes skills tap add owner/repo` discovery. Do not relocate (`CLAUDE.md` "Frontmatter and tap discoverability").

**`skills/revenium/scripts/`:**
- Purpose: All runtime bash scripts the cron and the operator invoke.
- Contains: shell scripts only; no Python files (Python is used via heredocs inside the scripts).
- Key files: `common.sh` (sourced by every other script), `cron.sh` (cron entry point).
- Convention: all scripts begin with `#!/usr/bin/env bash`, `set -euo pipefail` (or `set -uo pipefail` for `common.sh` and `hermes-report.sh`), then `source "${SCRIPT_DIR}/common.sh"`.

**`skills/revenium/references/`:**
- Purpose: Supplementary docs the skill itself points to from `SKILL.md`.
- Contains: markdown notes for the operating agent.
- Key files: `setup.md`, `troubleshooting.md`.
- Convention: Referenced from `SKILL.md` "References" section — keep filenames stable.

**`docs/`:**
- Purpose: End-user install documentation, not part of the shipped skill.
- Contains: markdown only.
- Key files: `installation.md`.

**`examples/`:**
- Purpose: Developer ergonomics — scripts that help with local installation for testing.
- Contains: shell scripts.
- Key files: `setup-local.sh`.

**`tests/`:**
- Purpose: Repository-level invariant checks. Runs via `python3 -m unittest discover -s tests -p 'test_*.py' -v`.
- Contains: Python test files using only stdlib `unittest`.
- Key files: `test_repository.py`.
- Constraint: must remain stdlib-only — no `pip install` step in CI.

**`.planning/codebase/`:**
- Purpose: Generated codebase mapping documents consumed by GSD planning/execution commands.
- Contains: `ARCHITECTURE.md`, `STRUCTURE.md` (this file), and other focus-area docs.
- Constraint: regenerate by re-running the mapper; do not hand-edit unless touching only specific sections.

**`.cache/`:**
- Purpose: Local working scratch space (gitignored).
- Contains: nothing tracked.

**`.git/`:**
- Standard git metadata.

## Key File Locations

**Entry Points:**
- `skills/revenium/scripts/cron.sh`: per-minute cron entry; orchestrates reporter + checker.
- `skills/revenium/scripts/hermes-report.sh`: metering reporter (manual or via cron).
- `skills/revenium/scripts/budget-check.sh`: budget snapshot writer (manual or via cron).
- `skills/revenium/scripts/clear-halt.sh`: manual operator halt clear.
- `skills/revenium/scripts/install-cron.sh`: per-minute cron installer.
- `skills/revenium/scripts/uninstall-cron.sh`: cron remover.
- `skills/revenium/SKILL.md`: the in-process skill prompt loaded by Hermes.

**Configuration:**
- `skills/revenium/scripts/common.sh`: every state path lives here (`STATE_DIR`, `CONFIG_FILE`, `BUDGET_STATUS_FILE`, `LEDGER_FILE`, `LOG_FILE`, `STATE_DB`, `ENV_FILE`).
- `skills/revenium/SKILL.md` (frontmatter): declares `name`, `category`, required env vars, required credential files, and `metadata.hermes`.
- `~/.hermes/state/revenium/config.json` (runtime, not in repo): `alertId`, `autonomousMode`, `notifyChannel`, `notifyTarget`, `organizationName`.
- `~/.hermes/state/revenium/env` (runtime, optional, not in repo): sourced by `cron.sh` for environment overrides.

**Core Logic:**
- `skills/revenium/scripts/hermes-report.sh`: ledger delta logic, provider inference, `revenium meter completion` invocation.
- `skills/revenium/scripts/budget-check.sh`: halt-transition rules, `budget-status.json` writer, notification dispatch.
- `skills/revenium/SKILL.md`: budget-check decision tree, halt response contract, setup flow.

**Testing:**
- `tests/test_repository.py`: file-existence, frontmatter, runtime-path, legacy-branding, and shell-syntax checks.

**Documentation:**
- `CLAUDE.md`: contributor-facing architecture notes — the source of truth for "why".
- `README.md`: end-user install + overview.
- `docs/installation.md`: install paths (tap, external_dirs, manual copy).
- `skills/revenium/references/setup.md`: setup / reset / reconfigure flows.
- `skills/revenium/references/troubleshooting.md`: operator fixes.

## Naming Conventions

**Files:**
- Shell scripts: `kebab-case.sh` (`hermes-report.sh`, `budget-check.sh`, `clear-halt.sh`, `install-cron.sh`, `uninstall-cron.sh`). The single exception is `common.sh` (shared helper, sourced not executed).
- Markdown docs: `lowercase.md` for references and docs (`installation.md`, `setup.md`, `troubleshooting.md`). The single exception is `SKILL.md` (uppercase per Hermes skill convention) and the planning docs (`ARCHITECTURE.md`, `STRUCTURE.md`).
- Python tests: `test_*.py` (matches the unittest discover glob).

**Directories:**
- All lowercase: `skills/`, `scripts/`, `references/`, `docs/`, `examples/`, `tests/`.
- The skill directory is the canonical slug `revenium` (lowercased name from `SKILL.md` frontmatter).

**State files (runtime, under `~/.hermes/state/revenium/`):**
- JSON: `config.json`, `budget-status.json` (kebab-case).
- Ledger: `revenium-hermes.ledger` (kebab-case, custom extension).
- Log: `revenium-metering.log`.
- Env: `env` (no extension — sourced as bash).

**Shell variables (in `common.sh`):**
- UPPER_SNAKE_CASE for exported paths: `STATE_DIR`, `CONFIG_FILE`, `BUDGET_STATUS_FILE`, `LEDGER_FILE`, `LOG_FILE`, `STATE_DB`, `ENV_FILE`, `SKILL_DIR`, `HERMES_HOME`, `REVENIUM_STATE_DIR`.
- snake_case for local variables inside functions and loops.

**Ledger keys:**
- `HERMES:<session_id>:<total_tokens>:<unix_ts>` — colon-separated, fixed five-field layout. The `HERMES:` prefix is contractual; do not change it.

**Crontab tag:**
- `# hermes-revenium-metering` — used as the grep key by both `install-cron.sh` and `uninstall-cron.sh`. Do not rename.

## Where to Add New Code

**A new runtime script (e.g., a diagnostic dumper):**
- File: `skills/revenium/scripts/<verb-noun>.sh` (e.g., `dump-ledger.sh`).
- Start with `#!/usr/bin/env bash`, `set -euo pipefail`, `SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"`, `source "${SCRIPT_DIR}/common.sh"`, `ensure_path`.
- Add an entry to `tests/test_repository.py::test_expected_files_exist`.
- Update `CLAUDE.md` "Common commands" if the script is user-facing.

**A new state path:**
- Add the variable to `skills/revenium/scripts/common.sh` next to the existing ones (lines 10–16). Never inline a path elsewhere.
- Use `${STATE_DIR}/<name>` so the override in `REVENIUM_STATE_DIR` continues to work.

**A new field in `config.json`:**
- Update the writer in `SKILL.md` setup flow (`skills/revenium/SKILL.md:204`–`231`) to preserve unknown keys (it already does this via `json.load → merge → json.dump`).
- Update `budget-check.sh` to read the field via the `read_config_field` helper if the cron pipeline needs it (`skills/revenium/scripts/budget-check.sh:15`–`24`).
- Document the field in `references/setup.md`.

**A new field in `budget-status.json`:**
- Update the heredoc in `skills/revenium/scripts/budget-check.sh:47`–`93` that writes the file.
- Update `SKILL.md` "Parse the status" list (`skills/revenium/SKILL.md:57`–`62`) so the prompt knows about it.

**A new reference doc:**
- File: `skills/revenium/references/<topic>.md`.
- Link it from the "References" section of `SKILL.md`.

**A new repository-level doc:**
- File: `docs/<topic>.md`.
- Do NOT add to `skills/revenium/` — that directory is the shipped skill, not project docs.

**A new test:**
- File: `tests/test_<area>.py`.
- Use only Python stdlib (no `pip install` available in CI).
- Run with `python3 -m unittest discover -s tests -p 'test_*.py' -v`.

**A new install path (e.g., a different runtime):**
- Update `docs/installation.md` first.
- If it requires a setup script, add it to `examples/`.

## Special Directories

**`skills/revenium/`:**
- Purpose: The shipped skill. Copied verbatim to `~/.hermes/skills/revenium/`.
- Generated: No.
- Committed: Yes.
- Constraint: location and frontmatter are enforced by `tests/test_repository.py`.

**`~/.hermes/state/revenium/` (runtime — not in repo):**
- Purpose: Mutable state contract between the cron pipeline and the skill prompt.
- Generated: Yes — created by `mkdir -p "${STATE_DIR}"` in `common.sh:18` and populated by `budget-check.sh`, `hermes-report.sh`, and the setup flow.
- Committed: N/A — never in the repo.
- Constraint: Do not write runtime state into `skills/revenium/`. Test `test_runtime_paths_are_hermes_native` enforces this.

**`.cache/`:**
- Purpose: Local scratch.
- Generated: Yes.
- Committed: No (gitignored).

**`.planning/`:**
- Purpose: GSD planning / codebase-mapping output.
- Generated: Yes (by mapping commands).
- Committed: depends on team policy — typically yes for `codebase/` snapshots.

**`tests/__pycache__/`:**
- Purpose: Python bytecode cache from running unittest.
- Generated: Yes.
- Committed: No (gitignored).

---

*Structure analysis: 2026-05-12*
