# Revenium Skill Setup

## Initial setup

### 1. Verify prerequisites

```bash
revenium config show
sqlite3 --version
python3 --version
```

### 2. Create the budget alert

Ask the user for:

- budget threshold
- budget period (`DAILY`, `WEEKLY`, `MONTHLY`, `QUARTERLY`)
- optional organization name
- optional autonomous notification channel + target

Before creating a new alert, remove any prior Revenium/Hermes budget alerts you own that would cause duplicates.

Create the alert:

```bash
revenium alerts budget create --name "Hermes Monthly Budget" --threshold 50 --period MONTHLY --json
```

Extract the `id` field from the JSON response.

### 3. Write state config

Write:

```json
{
  "alertId": "<alert-id>",
  "organizationName": "<optional>",
  "autonomousMode": true,
  "notifyChannel": "telegram",
  "notifyTarget": "123456789"
}
```

into:

```text
~/.hermes/state/revenium/config.json
```

### 4. Install cron

```bash
bash ~/.hermes/skills/revenium/scripts/install-cron.sh
```

## Reset flow

1. Read the current config.
2. Fetch the existing alert settings.
3. Delete the old alert.
4. Create a new alert with the same settings.
5. Replace `alertId` in `config.json`.
6. Reset `budget-status.json` to a non-halted zeroed state.

## Reconfigure flow

1. Read and remove the existing config.
2. Delete the old alert.
3. Run the initial setup flow again.

## How attribution works

GUARDRAIL share is overstated when work turns are much larger than classification turns. Read GUARDRAIL share as an upper bound, not an estimate. The S2 equal-split is intentionally simple and biases attribution toward classification overhead in mixed windows. Later strategies (S3 weighted, S4 guardrail-estimator) are deferred to v2.

The cron emits two S2 telemetry log lines per session per tick to make this visible to operators. They are written through the standard log helpers in `~/.hermes/state/revenium/revenium-metering.log`:

- `INFO: S2: window=<n>, mean_per_marker=<delta_total // n>` — every tick a session has at least one marker. Reports how many markers shared the session-delta this minute and the floor-divided per-marker share of the total token delta.
- `WARN: S2: classification-dominated window, attribution may be lossy` — fires when `n == 2` AND at least one marker has `operation_type == GUARDRAIL`. This is the canonical mixed-window signature where the equal-split overstates GUARDRAIL share the most.

Attribution is driven entirely by the `task_type` and `operation_type` fields the agent writes into each marker line (per the Phase 2 marker schema; see `references/task-taxonomy.md`). The cron does not infer task types from prompts or model output — every marker the agent emits maps to exactly one `revenium meter completion` call with those fields passed through verbatim. When a session window has zero markers (legacy install, missing marker file, all lines unparseable), the cron falls through to a single call with `--task-type unclassified` and `--operation-type CHAT` (Phase 4 / WIRE-01 — Revenium server-side default for absent `operationType` is `CHAT`, verified by the D-22 research gate, so emitting it explicitly is idempotent for existing dashboards and budgets).

This framing supersedes any earlier "self-cancels over many windows" mention in older planning notes — the bias is one-directional (GUARDRAIL is overstated, never understated) and does NOT average out across ticks.

When markers carry different `agent` or `trace_id` values across a session, each Revenium meter call records the per-turn attribution; per-session aggregation happens dashboard-side.

## Mechanical classification hook

Phase 6 ships an in-process Hermes lifecycle plugin at `~/.hermes/plugins/revenium-classifier/` that classifies every `run_conversation()` session end and writes the GUARDRAIL + CHAT marker pair the cron consumes. The plugin registers itself for the `on_session_end` event from the `hermes_cli` plugin bus, which fires for **every** session source — gateway-served (Telegram/Discord/Slack/WhatsApp/Webhook), CLI one-shot (`hermes chat -q`), interactive `hermes chat`, ACP integrations, and gateway-internal cron-ticker sessions. This is the mechanical floor — it fires regardless of whether the agent self-classifies via the FINAL ACTION block in `SKILL.md`. Both pathways write to the same `~/.hermes/state/revenium/markers/<sid>.jsonl`; the plugin tail-checks for a recent agent-written pair (within 30 seconds) before writing to avoid duplicates.

Subagent sessions (where `state.db.sessions.parent_session_id` is non-null) inherit the root user-facing session's `task_type` — one classification per user-request lineage, no per-subagent LLM call. The plugin also gates its LLM call on `budget-status.json::halted`; if the budget is halted, the plugin writes `task_type: unclassified` and emits a `WARN` log line instead of spending against the halted budget.

The plugin is installed by `examples/setup-local.sh` into `~/.hermes/plugins/revenium-classifier/`, and the same script idempotently adds `revenium-classifier` to `plugins.enabled` in `~/.hermes/config.yaml`. **`hermes skills install` does NOT relocate the `plugins/` subdirectory** — operators installing via that path must additionally copy `~/.hermes/skills/revenium/plugins/revenium-classifier/` to `~/.hermes/plugins/revenium-classifier/` themselves AND add `revenium-classifier` to `plugins.enabled` in `~/.hermes/config.yaml`.

After installing or updating the plugin, **run `hermes gateway restart`**. The plugin manager loads plugins once at agent startup; there is no file-watch reload.

To verify the plugin loaded, inspect the Hermes plugin-manager startup log for the plugin-load line (reference shape — same form Hermes uses for bundled plugins such as `hermes-agent/plugins/disk-cleanup/`).

Or a direct filesystem check:

```
test -f ~/.hermes/plugins/revenium-classifier/plugin.yaml
test -f ~/.hermes/plugins/revenium-classifier/__init__.py
test -f ~/.hermes/plugins/revenium-classifier/classifier.py
```

**Do NOT** use `hermes hooks list` or `hermes hooks test` to verify — that CLI is for shell hooks declared in `~/.hermes/config.yaml::hooks` (a different subsystem). The `on_session_end` plugin and `hermes hooks` shell hooks share the word "hook" but are wired separately.

_Migration note (from earlier 06-01 implementation):_ if you previously installed the `agent:end` gateway hook into `~/.hermes/hooks/revenium-classifier/`, you may delete that directory manually after running the new setup. The gateway will load it but it produces no markers (the `on_session_end` plugin supersedes it); it is harmless but stale.

## Marker file pruning

The skill accumulates one JSONL marker file per Hermes session under `~/.hermes/state/revenium/markers/`. On long-running hosts these files grow without bound. `prune-markers.sh` removes stale marker files using the ledger as the authoritative staleness source (D-26): the script reads the latest `HERMES:<sid>:…:<unix_ts>:…` ledger row per session and removes the marker file if that timestamp is older than the retention threshold. For orphan markers with no ledger entry, file modification time is used instead.

Default retention is 30 days, configurable via `REVENIUM_MARKER_RETENTION_DAYS` (declared in `common.sh`, D-27). The script is **not** wired into the per-minute cron — it is an operator-invoked maintenance action (D-28). Every deletion (and dry-run candidate) is logged via `info` to `${LOG_FILE}` so the operator can audit (D-29).

### How to run

```bash
# Preview candidates without deleting (dry-run)
bash ~/.hermes/skills/revenium/scripts/prune-markers.sh --dry-run

# Delete stale marker files
bash ~/.hermes/skills/revenium/scripts/prune-markers.sh

# Override the retention window (e.g., 60 days)
REVENIUM_MARKER_RETENTION_DAYS=60 bash ~/.hermes/skills/revenium/scripts/prune-markers.sh
```

### Manual UAT triple-case

To verify the script against a seeded fixture:

```bash
STATE_DIR=~/.hermes/state/revenium
mkdir -p "${STATE_DIR}/markers"

# 1. Create a stale session marker (31 days old)
OLD_TS=$(python3 -c "import time; print(int(time.time()) - 31*86400)")
echo '{"muid":"aaa","ts":'"${OLD_TS}"',"sid":"old-test","task_type":"research","operation_type":"CHAT"}' \
  > "${STATE_DIR}/markers/old-test.jsonl"
echo "HERMES:old-test:1000:${OLD_TS}:aaa" >> "${STATE_DIR}/revenium-hermes.ledger"

# 2. Create a fresh session marker (today)
FRESH_TS=$(python3 -c "import time; print(int(time.time()))")
echo '{"muid":"bbb","ts":'"${FRESH_TS}"',"sid":"fresh-test","task_type":"generation","operation_type":"CHAT"}' \
  > "${STATE_DIR}/markers/fresh-test.jsonl"
echo "HERMES:fresh-test:500:${FRESH_TS}:bbb" >> "${STATE_DIR}/revenium-hermes.ledger"

# 3. Create an orphan marker (no ledger entry, mtime 31 days ago)
echo '{"muid":"ccc","ts":'"${OLD_TS}"',"sid":"orphan-test","task_type":"review","operation_type":"CHAT"}' \
  > "${STATE_DIR}/markers/orphan-test.jsonl"
touch -t "$(python3 -c "import datetime; dt=datetime.datetime.utcnow()-datetime.timedelta(days=31); print(dt.strftime('%Y%m%d%H%M.%S'))")" \
  "${STATE_DIR}/markers/orphan-test.jsonl"

# 4. Dry-run: expect old-test + orphan-test in output, fresh-test absent
bash ~/.hermes/skills/revenium/scripts/prune-markers.sh --dry-run

# 5. Live run: confirm old-test + orphan-test deleted, fresh-test kept
bash ~/.hermes/skills/revenium/scripts/prune-markers.sh
ls "${STATE_DIR}/markers/"

# 6. Idempotent re-run: expect "prune: summary, scanned=1 kept=1 removed=0"
bash ~/.hermes/skills/revenium/scripts/prune-markers.sh
```
