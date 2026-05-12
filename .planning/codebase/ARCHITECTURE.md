<!-- refreshed: 2026-05-12 -->
# Architecture

**Analysis Date:** 2026-05-12

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────┐
│                  Hermes Agent Session (in-process)                   │
│                                                                      │
│   SKILL.md prompt — read on every operation                          │
│   `skills/revenium/SKILL.md`                                         │
│      │                                                               │
│      │ reads (file I/O only)                                         │
│      ▼                                                               │
└──────┼───────────────────────────────────────────────────────────────┘
       │
       │           (the two halves NEVER call each other directly —
       │            they communicate exclusively via these JSON files)
       │
┌──────┼───────────────────────────────────────────────────────────────┐
│      ▼                                                               │
│  ~/.hermes/state/revenium/         (state contract surface)          │
│  ├── config.json                   alertId, autonomousMode, notify   │
│  ├── budget-status.json            currentValue/threshold/halted     │
│  ├── revenium-hermes.ledger        HERMES:<sid>:<tokens>:<ts> lines  │
│  ├── revenium-metering.log         cron log                          │
│  └── env                           optional env overrides            │
│      ▲              ▲                                                │
│      │ writes       │ writes                                         │
└──────┼──────────────┼────────────────────────────────────────────────┘
       │              │
┌──────┼──────────────┼────────────────────────────────────────────────┐
│      │              │       Cron Pipeline (out-of-process, * * * * *)│
│      │              │                                                │
│  ┌───┴──────────┐   │      `skills/revenium/scripts/cron.sh`         │
│  │ hermes-      │   │      (orchestrator: sources common.sh, env,    │
│  │ report.sh    │   │       then calls report + check sequentially)  │
│  └──────┬───────┘   │                                                │
│         │           │                                                │
│         │           └──── `skills/revenium/scripts/budget-check.sh`  │
│         │                 (reads alertId, GETs revenium alerts, writes│
│         │                  budget-status.json, detects halt transition,│
│         │                  fires Hermes messaging notification)       │
│         ▼                                                            │
│  reads ~/.hermes/state.db                                            │
│  → diffs against ledger                                              │
│  → POSTs deltas via `revenium meter completion`                      │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
                       Revenium platform API
                       (metering + alerts)
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

**Overall:** Two-half asynchronous design — an in-process Hermes skill prompt and an out-of-process cron pipeline communicating exclusively through a flat-file state contract under `~/.hermes/state/revenium/`.

**Key Characteristics:**
- No runtime, no daemon, no IPC — coupling is filesystem-only (`config.json`, `budget-status.json`, `revenium-hermes.ledger`).
- The skill never calls the Revenium API directly; it only reads the local cron-maintained snapshot for low-latency budget checks.
- All Bash scripts source `common.sh` for path resolution — paths are never inlined.
- Idempotent metering via an append-only ledger keyed on `HERMES:<session_id>:<total_tokens>`.

## Layers

**Skill content layer (immutable on a given install):**
- Purpose: Static skill assets shipped to `~/.hermes/skills/revenium/`.
- Location: `skills/revenium/`
- Contains: `SKILL.md`, `scripts/*.sh`, `references/*.md`
- Depends on: nothing in this repo at runtime (it is the runtime).
- Used by: the Hermes agent (reads `SKILL.md`) and `cron` (executes `scripts/*.sh`).

**State / contract layer (mutable per host):**
- Purpose: The only communication channel between the two halves.
- Location: `~/.hermes/state/revenium/` (resolved by `common.sh`, not present in repo)
- Contains: `config.json`, `budget-status.json`, `revenium-hermes.ledger`, `revenium-metering.log`, optional `env`
- Depends on: written by `budget-check.sh`, `hermes-report.sh`, `clear-halt.sh`, and the Hermes setup flow.
- Used by: read by `SKILL.md` (via Hermes file tools) and by every script in the cron pipeline.

**External integration layer:**
- Purpose: Reads from Hermes' session DB; writes to Revenium platform via the `revenium` CLI.
- Hermes session DB: `~/.hermes/state.db` (the `sessions` table — read-only from this skill's perspective)
- Revenium CLI: `revenium meter completion`, `revenium alerts budget get`, `revenium config show`
- Hermes messaging: `hermes chat --toolsets messaging -q "Use the send_message tool ..."` for halt notifications.

**Packaging / repo layer (build-time only, not shipped):**
- Purpose: Distribution metadata and developer ergonomics.
- Location: repo root — `README.md`, `docs/`, `examples/`, `tests/`, `CLAUDE.md`
- Contains: install docs, local-setup helper, invariant tests, contributor guide.
- Used by: humans and the `hermes skills tap add` discovery mechanism (which scans `skills/`).

## Data Flow

### Primary metering path (every minute, out of process)

1. `cron` triggers the line installed by `install-cron.sh` (`skills/revenium/scripts/install-cron.sh:26`), which sets `HERMES_HOME`, `REVENIUM_STATE_DIR`, `PATH`, and invokes `cron.sh`.
2. `cron.sh` sources `common.sh` and the optional `env` file (`skills/revenium/scripts/cron.sh:6`–`15`), then runs `hermes-report.sh` followed by `budget-check.sh`, each with `|| true` so a failure in one does not break the other.
3. `hermes-report.sh` queries the `sessions` table in `~/.hermes/state.db` for rows with non-zero `input_tokens` or `output_tokens` (`skills/revenium/scripts/hermes-report.sh:45`–`53`).
4. For each session, the reporter looks up the previous ledger line `HERMES:<sid>:` (`skills/revenium/scripts/hermes-report.sh:78`), computes `ratio = (curr - prev) / curr` and scales `input/output/cache_read/cache_write/cost` by that ratio (`skills/revenium/scripts/hermes-report.sh:88`–`107`, `199`–`214`).
5. Provider inference runs in Python heredocs against `model` + `billing_provider`, with OpenRouter and Bedrock special-cased (`skills/revenium/scripts/hermes-report.sh:115`–`165`).
6. `revenium meter completion` is invoked with `--transaction-id "${sid}-${total_tokens}"` (`skills/revenium/scripts/hermes-report.sh:216`–`235`). Only on exit code 0 is the ledger appended (`skills/revenium/scripts/hermes-report.sh:253`–`258`).

### Budget-status / halt path

1. `budget-check.sh` reads `alertId`, `autonomousMode`, `notifyChannel`, `notifyTarget` from `config.json` (`skills/revenium/scripts/budget-check.sh:26`–`40`).
2. It calls `revenium alerts budget get "${ALERT_ID}" --json` and feeds the JSON into a Python heredoc (`skills/revenium/scripts/budget-check.sh:32`, `43`–`94`).
3. The heredoc computes `exceeded = currentValue > threshold`, reads previous `halted`/`haltedAt` from the existing `budget-status.json` if any, and applies halt transition rules.
4. New `budget-status.json` is written atomically via `Path.write_text` (`skills/revenium/scripts/budget-check.sh:83`).
5. On a *new* halt transition only, the script invokes `hermes chat --toolsets messaging` to deliver the notification to the configured `notifyChannel:notifyTarget` (`skills/revenium/scripts/budget-check.sh:98`–`117`).

### Skill-prompt read path (every Hermes turn, in process)

1. Before any response or tool call, Hermes reads `~/.hermes/state/revenium/budget-status.json` (`skills/revenium/SKILL.md:28`, `52`).
2. If `halted: true`, the agent emits the contractual halt string verbatim and stops (`skills/revenium/SKILL.md:31`–`46`).
3. If `exceeded: true` and `halted: false`, the agent reads `autonomousMode` from `config.json` and either prompts the user (interactive) or proceeds (autonomous after clear-halt) (`skills/revenium/SKILL.md:70`–`83`).
4. If the file is missing, the skill fails open — proceed with caution but do not block (`skills/revenium/SKILL.md:85`–`88`).

### Halt-clear path (manual operator action)

1. Operator runs `bash ~/.hermes/skills/revenium/scripts/clear-halt.sh`.
2. Script reads `budget-status.json`, sets `halted = false`, pops `haltedAt`, writes back (`skills/revenium/scripts/clear-halt.sh:13`–`27`).
3. `budget-check.sh` will NOT auto-clear — clearing is exclusively this script's job (see CLAUDE.md "Halt transitions").

**State Management:**
- All mutable state is plain JSON / line-oriented text files under `~/.hermes/state/revenium/`.
- No in-memory shared state between scripts — every script re-reads the files it cares about.
- The ledger is append-only; idempotency is enforced by `grep -q "^HERMES:${sid}:${total_tokens}:"` before the API call (`skills/revenium/scripts/hermes-report.sh:71`).

## Key Abstractions

**Path resolver (`common.sh`):**
- Purpose: One file owns every state path. All other scripts `source` it before doing anything.
- Variables exported: `HERMES_HOME`, `REVENIUM_STATE_DIR`, `SKILL_DIR`, `STATE_DIR`, `CONFIG_FILE`, `BUDGET_STATUS_FILE`, `LEDGER_FILE`, `LOG_FILE`, `ENV_FILE`, `STATE_DB`.
- File: `skills/revenium/scripts/common.sh`
- Pattern: Environment-variable-overridable defaults (`${HERMES_HOME:-${HOME}/.hermes}`) so cron and tests can redirect to alternate roots.
- Also provides: `ensure_path` (prepends brew / linuxbrew / `~/.local/bin` etc. so cron can find `revenium`, `sqlite3`, `python3`), and `log`/`info`/`warn`/`error` (timestamped writes to `LOG_FILE`).

**Ledger delta semantics:**
- Purpose: Idempotent reporting of token usage that grows over time.
- File: `~/.hermes/state/revenium/revenium-hermes.ledger`
- Pattern: Each successful report appends `HERMES:<session_id>:<total_tokens>:<unix_ts>`. Re-running the cron skips any line whose `(session_id, total_tokens)` already exists. Token totals are diffed against the most recent prior line for the same session and per-field counts/costs are scaled by `(curr - prev) / curr`.
- Code: `skills/revenium/scripts/hermes-report.sh:70`–`107`

**Halt transition rules:**
- Purpose: Distinguish a *new* halt (this run flipped exceeded under autonomous mode) from carrying an *existing* halt forward.
- File: `skills/revenium/scripts/budget-check.sh:64`–`82`
- Pattern: Read prior `halted` from existing `budget-status.json`. If `autonomous && exceeded && !prev_halted` → new halt, record `haltedAt = now`, emit `HALT_TRANSITION=true`. If `prev_halted` → carry forward `haltedAt`. Otherwise → `halted = false`. Clearing is never automatic.

**Provider inference:**
- Purpose: Map Hermes' `model` + `billing_provider` columns to a Revenium provider string.
- File: `skills/revenium/scripts/hermes-report.sh:115`–`165`
- Pattern: Python heredoc with substring matching. OpenRouter and Bedrock are special-cased — they decode the *underlying* model provider rather than passing through the proxy name.

**Frontmatter contract for tap discovery:**
- Purpose: `hermes skills tap add owner/repo` looks for skills under `skills/<name>/SKILL.md` with `name:`, `metadata.hermes`, and `category: devops`.
- File: `skills/revenium/SKILL.md:1`–`20`
- Enforcement: `tests/test_repository.py::test_skill_frontmatter_has_hermes_metadata`.

## Entry Points

**Cron pipeline (out of process):**
- Location: `skills/revenium/scripts/cron.sh`
- Triggers: per-minute crontab entry installed by `install-cron.sh`.
- Responsibilities: source `common.sh` + optional `env` file, run reporter, run checker.

**Metering reporter (manual or via cron):**
- Location: `skills/revenium/scripts/hermes-report.sh`
- Triggers: `cron.sh` or direct invocation.
- Responsibilities: read `state.db`, compute deltas, call `revenium meter completion`, append ledger.

**Budget checker (manual or via cron):**
- Location: `skills/revenium/scripts/budget-check.sh`
- Triggers: `cron.sh` or direct invocation.
- Responsibilities: fetch alert, write `budget-status.json`, fire halt notification on transition.

**Halt clearer (manual operator action):**
- Location: `skills/revenium/scripts/clear-halt.sh`
- Triggers: human-invoked (or shown in the halt string of `SKILL.md`).
- Responsibilities: mutate `budget-status.json` only — does not touch Revenium.

**Cron installer / uninstaller:**
- Location: `skills/revenium/scripts/install-cron.sh`, `skills/revenium/scripts/uninstall-cron.sh`
- Triggers: human-invoked, also called as the final step of the setup flow in `SKILL.md`.
- Responsibilities: idempotently add/remove a single crontab line tagged `# hermes-revenium-metering`.

**Skill prompt (in process):**
- Location: `skills/revenium/SKILL.md`
- Triggers: Hermes loads on every relevant invocation.
- Responsibilities: enforce the mandatory pre-operation budget check.

**Local install helper (developer ergonomics):**
- Location: `examples/setup-local.sh`
- Triggers: human-invoked from repo root.
- Responsibilities: copy `skills/revenium/` into `~/.hermes/skills/revenium/` and `chmod +x` the scripts.

## Architectural Constraints

- **No runtime / no build step:** This repo ships static text. The "application" is a skill plus a set of shell scripts; there is nothing to compile or package.
- **State paths must live in `common.sh`:** `tests/test_repository.py::test_runtime_paths_are_hermes_native` greps `common.sh` for `.hermes` and `state/revenium` and forbids `.openclaw`. Adding a new state file means adding its variable to `common.sh`, not hard-coding it elsewhere.
- **Skill location is contractual:** The skill must live at `skills/revenium/` (not the repo root) for `hermes skills tap add owner/repo` to discover it.
- **Frontmatter is contractual:** `name: revenium`, `metadata.hermes:` block, and `category: devops` are all enforced by `tests/test_repository.py::test_skill_frontmatter_has_hermes_metadata`.
- **No legacy branding:** `tests/test_repository.py::test_no_legacy_branding_left` greps every `.md`/`.sh`/`.py`/`.txt`/`.json`/`.yml`/`.yaml` file in the repo for forbidden product names. The forbidden regex lives in `tests/test_repository.py:47`; consult the test, do not reproduce the strings.
- **Shell strictness:** Scripts use `set -euo pipefail` (simple ones) or `set -uo pipefail` (`common.sh`, `hermes-report.sh` — which need to continue past individual failures). Preserve these when editing. `tests/test_repository.py::test_shell_scripts_have_valid_syntax` runs `bash -n` on every script.
- **Two halves never call each other:** The skill prompt MUST NOT execute the cron scripts to refresh state on demand; conversely the cron scripts MUST NOT invoke Hermes for anything except the one notification call in `budget-check.sh`. All other coupling is filesystem state.
- **Cron environment is restricted:** `install-cron.sh:26` embeds an explicit `PATH=` and `HERMES_HOME=`, `REVENIUM_STATE_DIR=` because cron starts with an almost-empty environment. `ensure_path` in `common.sh` is a defense in depth.
- **Idempotency:** Re-running `cron.sh` must never double-report. The ledger + `transaction-id = ${sid}-${total_tokens}` design is what guarantees this — preserve both invariants together.

## Anti-Patterns

### Inlining state paths

**What happens:** A new script (or an edit to an existing one) hard-codes `~/.hermes/state/revenium/budget-status.json` directly instead of using `${BUDGET_STATUS_FILE}`.
**Why it's wrong:** Breaks the `HERMES_HOME` / `REVENIUM_STATE_DIR` override that cron, tests, and alternate installs rely on. Also makes `test_runtime_paths_are_hermes_native` brittle — it asserts the canonical strings appear in `common.sh`, not elsewhere.
**Do this instead:** Add the path to `skills/revenium/scripts/common.sh` and `source` it (`skills/revenium/scripts/budget-check.sh:5`–`6` is the pattern).

### Auto-clearing a halt from `budget-check.sh`

**What happens:** Logic is added to `budget-check.sh` that flips `halted: false` once `currentValue <= threshold`.
**Why it's wrong:** Halt clearing is an explicit operator action — the user has accepted the cost overrun and chosen to resume. Auto-clearing on budget reset would silently re-arm an autonomous agent.
**Do this instead:** Only `skills/revenium/scripts/clear-halt.sh` mutates `halted: true → false`. `budget-check.sh` carries `prev_halted` forward unconditionally (`skills/revenium/scripts/budget-check.sh:76`–`82`).

### Reporting totals instead of deltas

**What happens:** Refactoring `hermes-report.sh` to pass full session token totals to `revenium meter completion` on every run.
**Why it's wrong:** Sessions accumulate tokens over time in `state.db`; reporting totals would multiply spend by the number of cron runs the session is alive. The `transaction-id` would still de-dup the *first* duplicate but the scaling math would be wrong.
**Do this instead:** Compute deltas against the most recent ledger line for the same `session_id`, scale per-field counts by `(curr - prev) / curr`, and only append to the ledger after a successful API call (`skills/revenium/scripts/hermes-report.sh:78`–`107`, `253`–`258`).

### Calling the Revenium API from `SKILL.md`

**What happens:** Tweaking the skill prompt to call `revenium alerts budget get` directly so the budget check is "fresh."
**Why it's wrong:** It adds a synchronous, rate-limited, latency-sensitive network call to every Hermes turn — defeating the entire purpose of the local `budget-status.json` snapshot. It also bypasses the autonomous-mode and halt-transition rules in `budget-check.sh`.
**Do this instead:** Read `~/.hermes/state/revenium/budget-status.json` only (`skills/revenium/SKILL.md:52`). If the file is stale, that is the cron's problem, not the skill prompt's.

### Modifying the halt response string

**What happens:** Rewording or reformatting the verbatim halt message in `SKILL.md`.
**Why it's wrong:** The string is contractual — autonomous-mode integrators may grep for it to detect halts. It also includes the `clear-halt.sh` command the user needs to recover. Free-form rewrites lose both properties.
**Do this instead:** Treat `skills/revenium/SKILL.md:35` as a stable interface. Update it only with intent and update consumers in lock-step.

## Error Handling

**Strategy:** Fail open in the data plane; fail closed in the budget plane.

**Patterns:**
- Reporter pre-flight checks (`hermes-report.sh:13`–`32`) `exit 0` on missing tools (`revenium`, `sqlite3`, `python3`, `state.db`, unconfigured CLI). Never aborts the cron pipeline.
- `cron.sh` calls each child with `|| true` so reporter failure does not block the budget check, and vice versa (`cron.sh:17`–`18`).
- Per-session loop in `hermes-report.sh` swallows individual failures with `((counter++)) || true` and `continue` rather than aborting the run.
- `budget-check.sh` uses `set -euo pipefail` — it aborts on any failure, which is appropriate because writing a stale or inconsistent `budget-status.json` is worse than not writing one.
- `SKILL.md` fails open if `budget-status.json` is missing or unreadable (`SKILL.md:85`–`88`) so a never-installed-cron does not prevent any work.
- All logs go through `info`/`warn`/`error` in `common.sh:30`–`38`, timestamped UTC, ISO-8601, to `LOG_FILE`.

## Cross-Cutting Concerns

**Logging:** All scripts source `common.sh` and use `info`/`warn`/`error`. Output goes to `~/.hermes/state/revenium/revenium-metering.log`. Cron stdout/stderr is additionally redirected into the same file by the crontab line (`install-cron.sh:26`).

**Configuration:** Two-tier — `~/.hermes/state/revenium/config.json` for skill settings (alertId, autonomousMode, notifyChannel/Target, organizationName), and an optional `~/.hermes/state/revenium/env` file sourced by `cron.sh:10`–`15` for environment overrides (e.g., custom `PATH`).

**Authentication:** Delegated entirely to the `revenium` CLI (`~/.config/revenium/config.yaml` per `SKILL.md:13`–`15`). This skill never handles `REVENIUM_API_KEY` directly; it calls `revenium config show` to verify configuration and lets the CLI manage credentials.

**Validation:** `tests/test_repository.py` is the gate — file existence, frontmatter shape, runtime-path discipline, no legacy branding, and `bash -n` syntax validation on every shell script.

---

*Architecture analysis: 2026-05-12*
