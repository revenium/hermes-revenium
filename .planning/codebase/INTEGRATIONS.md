# External Integrations

**Analysis Date:** 2026-05-12

## APIs & External Services

**Revenium (primary integration):**
- Revenium platform — usage metering and budget alerting service
  - SDK/Client: `revenium` CLI (installed separately via `brew install revenium/tap/revenium`, see `README.md:9`)
  - Auth: managed by the CLI, not this repo. Stored at `~/.config/revenium/config.yaml` and written by `revenium config set` (per `README.md:149` and `skills/revenium/SKILL.md:140-145`).
  - Required env vars (declared in `skills/revenium/SKILL.md:9-12`): `REVENIUM_API_KEY`, `REVENIUM_API_URL`, `REVENIUM_TEAM_ID`
  - CLI subcommands used by this repo:
    - `revenium meter completion ...` — ships per-session token deltas. Invoked from `skills/revenium/scripts/hermes-report.sh:217-235`. Flags include `--model`, `--provider`, `--input-tokens`, `--output-tokens`, `--cache-read-tokens`, `--cache-creation-tokens`, `--total-tokens`, `--stop-reason`, `--request-time`, `--completion-start-time`, `--response-time`, `--request-duration`, `--agent Hermes`, `--transaction-id <session>-<total>`, `--trace-id <session>`, `--is-streamed`, `--quiet`, optionally `--model-source`, `--total-cost`, `--organization-name`, `--environment`.
    - `revenium alerts budget get <id> --json` — fetches the current budget snapshot. Invoked from `skills/revenium/scripts/budget-check.sh:32`.
    - `revenium alerts budget create --name --threshold --period --json` — creates the budget alert during setup. Documented in `skills/revenium/SKILL.md:189-192` and `skills/revenium/references/setup.md:24-30`.
    - `revenium alerts budget list --json` and `revenium alerts budget delete <id> --yes` — used during setup to remove pre-existing `Hermes *` budget alerts before creating a new one (`skills/revenium/SKILL.md:179-187`).
    - `revenium config show` / `revenium config set key|team-id|tenant-id|owner-id` — verify and seed CLI credentials during setup (`skills/revenium/SKILL.md:126-145`, `docs/installation.md:42-51`).

**Hermes Agent (peer integration):**
- Hermes Agent — the host runtime that loads and executes this skill
  - Hermes is not called as an external API; the skill participates in a Hermes session by providing `skills/revenium/SKILL.md` as a system-prompt fragment.
  - One outbound `hermes` CLI call: `skills/revenium/scripts/budget-check.sh:106` runs `hermes chat --toolsets messaging -q "..."` to dispatch a halt notification through Hermes' messaging toolset. Falls back to a log line if the `hermes` CLI is not on `PATH` (`skills/revenium/scripts/budget-check.sh:111-113`).

**Inferred AI provider mapping (no direct API calls — provider inference only):**
- `skills/revenium/scripts/hermes-report.sh:126-165` maps the `model` and `billing_provider` columns from Hermes' session DB to one of `anthropic`, `openai`, `google`, `xai`, `deepseek`, `meta`, `aws`, or `unknown`. Special cases: `openrouter` is decomposed into the underlying provider by model substring; `bedrock` maps to `anthropic` when the model contains `claude`, otherwise `aws`.
- These names are passed as `--provider` to `revenium meter completion`. The skill itself does not call any LLM provider API directly.

## Data Storage

**Databases:**
- SQLite (read-only consumer) — `~/.hermes/state.db`, owned by Hermes
  - Path: `STATE_DB="${HERMES_HOME}/state.db"` (`skills/revenium/scripts/common.sh:16`)
  - Client: `sqlite3` CLI invoked from `skills/revenium/scripts/hermes-report.sh:45-53`
  - Query: `SELECT id, model, source, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens, estimated_cost_usd, api_call_count, started_at, ended_at, billing_provider FROM sessions WHERE (input_tokens > 0 OR output_tokens > 0) ORDER BY started_at DESC`
  - The skill never writes to `state.db`. It is purely a consumer.

**File Storage:**
- Local filesystem only, under `~/.hermes/state/revenium/`:
  - `config.json` — skill configuration (`CONFIG_FILE` in `skills/revenium/scripts/common.sh:11`)
  - `budget-status.json` — last cron snapshot (`BUDGET_STATUS_FILE` in `skills/revenium/scripts/common.sh:12`)
  - `revenium-hermes.ledger` — append-only idempotency ledger (`LEDGER_FILE` in `skills/revenium/scripts/common.sh:13`)
  - `revenium-metering.log` — cron log (`LOG_FILE` in `skills/revenium/scripts/common.sh:14`)
  - `env` — optional per-state env file sourced by `cron.sh` (`ENV_FILE` in `skills/revenium/scripts/common.sh:15`)

**Caching:**
- None. The ledger functions as an idempotency record, not a cache. `budget-status.json` is a snapshot, not a cache layer.

## Authentication & Identity

**Auth Provider:**
- Delegated to the `revenium` CLI. The skill itself holds no credentials.
- `revenium config show` is the gate (`skills/revenium/scripts/hermes-report.sh:29-32`); if it fails, metering is skipped with a warning rather than erroring.
- Setup collects API Key, Team ID, Tenant ID, and User ID (owner) from the user and forwards them to `revenium config set` (`skills/revenium/SKILL.md:132-145`).

## Monitoring & Observability

**Error Tracking:**
- None. No Sentry, Datadog, Rollbar, or equivalent.

**Logs:**
- Single log file at `~/.hermes/state/revenium/revenium-metering.log`, written by the `log()`/`info()`/`warn()`/`error()` helpers in `skills/revenium/scripts/common.sh:30-38`.
- Log format: `[<iso-utc-ts>] [<LEVEL>] [revenium] <message>`. Levels are `INFO `, `WARN `, `ERROR` (padded to 5 chars).
- Cron stdout/stderr are appended to the same log via `>> ${LOG_FILE} 2>&1` in the crontab line (`skills/revenium/scripts/install-cron.sh:26`).
- `*.log` is git-ignored (`.gitignore:7`).

## CI/CD & Deployment

**Hosting:**
- Not applicable. The skill runs on the end user's machine. There is no server, container, or deployable artifact.

**CI Pipeline:**
- None detected in the repository (no `.github/`, no CircleCI/Travis config, no GitLab CI). Tests are run manually with `python3 -m unittest discover -s tests -p 'test_*.py' -v` per `CLAUDE.md`.

**Distribution channels:**
- GitHub tap: `hermes skills tap add revenium/hermes-revenium` (`README.md:25`). Discovery requires the skill to be at `skills/revenium/`.
- `external_dirs` in `~/.hermes/config.yaml` for local development (`README.md:39-44`).
- Direct copy via `bash examples/setup-local.sh` (`README.md:57-59`, `examples/setup-local.sh`).
- `hermes skills publish` to GitHub for indexed discovery (`README.md:66`).

## Environment Configuration

**Required env vars (declared by the skill, consumed by the `revenium` CLI):**
- `REVENIUM_API_KEY`
- `REVENIUM_API_URL`
- `REVENIUM_TEAM_ID`

**Runtime-configurable env vars (consumed by this repo's scripts):**
- `HERMES_HOME` — root for Hermes state. Defaults to `${HOME}/.hermes` (`skills/revenium/scripts/common.sh:6`).
- `REVENIUM_STATE_DIR` — root for skill state. Defaults to `${HERMES_HOME}/state/revenium` (`skills/revenium/scripts/common.sh:7`).

**Secrets location:**
- Revenium API credentials live in `~/.config/revenium/config.yaml`, managed exclusively by the `revenium` CLI (`README.md:149`, `skills/revenium/SKILL.md:14-15`).
- `.env`, `.venv/`, and `venv/` are git-ignored (`.gitignore:4-6`). No secrets are stored in the repo.

## Webhooks & Callbacks

**Incoming:**
- None. The skill exposes no HTTP endpoints.

**Outgoing:**
- No direct HTTPS calls from this repo. All outbound network traffic is mediated by the `revenium` CLI (token metering, budget alert lookup/create/delete) and by the `hermes` CLI (messaging notifications).
- Halt notifications are dispatched indirectly: `skills/revenium/scripts/budget-check.sh:106` shells out to `hermes chat --toolsets messaging -q "Use the send_message tool to send this exact message to <channel>:<target>: <msg>"`, which lets Hermes' configured messaging toolset (Slack/Discord/Telegram/etc.) deliver the message.

## Scheduled Jobs / Cron

**Per-minute crontab entry** (`hermes-revenium-metering`):
- Installed by `skills/revenium/scripts/install-cron.sh` and removed by `skills/revenium/scripts/uninstall-cron.sh`.
- Schedule: `* * * * *` (every minute) — `skills/revenium/scripts/install-cron.sh:14`.
- Command shape (`skills/revenium/scripts/install-cron.sh:26`): `* * * * * HERMES_HOME=<...> REVENIUM_STATE_DIR=<...> PATH=<...> bash <skill>/scripts/cron.sh >> <log> 2>&1 # hermes-revenium-metering`.
- The cron line is identified by the trailing comment `# hermes-revenium-metering`; both install and uninstall use this string as the idempotency marker.
- `PATH` is pre-populated at install time with Homebrew prefixes (`/opt/homebrew/bin`, `/home/linuxbrew/.linuxbrew/bin`), `~/go/bin`, and `~/.local/bin` so the cron environment can find `revenium`, `sqlite3`, and `python3` (`skills/revenium/scripts/install-cron.sh:15-24`).
- `cron.sh` runs `hermes-report.sh` then `budget-check.sh`, each guarded with `|| true` so a failure in one does not block the other (`skills/revenium/scripts/cron.sh:17-18`).

---

*Integration audit: 2026-05-12*
