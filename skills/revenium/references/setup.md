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

Attribution is driven entirely by the `task_type` and `operation_type` fields the agent writes into each marker line (per the Phase 2 marker schema; see `references/task-taxonomy.md`). The cron does not infer task types from prompts or model output — every marker the agent emits maps to exactly one `revenium meter completion` call with those fields passed through verbatim. When a session window has zero markers (legacy install, missing marker file, all lines unparseable), the cron falls through to a single call with `--task-type unclassified` and no `--operation-type` — argv-compatible with the pre-Phase-3 single-call form so backward-compat installs keep metering unchanged.

This framing supersedes any earlier "self-cancels over many windows" mention in older planning notes — the bias is one-directional (GUARDRAIL is overstated, never understated) and does NOT average out across ticks.

## Mechanical classification hook

Phase 6 ships an in-process Hermes lifecycle hook at `~/.hermes/hooks/revenium-classifier/` that classifies every `agent:end` turn and writes the GUARDRAIL + CHAT marker pair the cron consumes. This hook is the mechanical floor — it fires regardless of whether the agent self-classifies via the FINAL ACTION block in `SKILL.md`. Both pathways write to the same `~/.hermes/state/revenium/markers/<sid>.jsonl`; the hook tail-checks for a recent agent-written pair (within 30 seconds) before writing to avoid duplicates.

Subagent sessions (where `state.db.sessions.parent_session_id` is non-null) inherit the root user-facing session's `task_type` — one classification per user-request lineage, no per-subagent LLM call. The hook also gates its LLM call on `budget-status.json::halted`; if the budget is halted, the hook writes `task_type: unclassified` and emits a `WARN` log line instead of spending against the halted budget.

The hook is installed by `examples/setup-local.sh` into `~/.hermes/hooks/revenium-classifier/`. **`hermes skills install` does NOT relocate the `hooks/` subdirectory** — operators installing via that path must additionally copy `~/.hermes/skills/revenium/hooks/revenium-classifier/` to `~/.hermes/hooks/revenium-classifier/` themselves.

After installing or updating the hook, **run `hermes gateway restart`**. Hermes loads hooks once at gateway startup; there is no file-watch reload.

To verify the hook loaded, inspect the gateway startup log for:

```
[hooks] Loaded hook 'revenium-classifier' for events: ['agent:end']
```

Or run a one-shot discovery check:

```
cd ~/.hermes/hermes-agent && ./venv/bin/python3 -c \
  "from gateway.hooks import HookRegistry; r=HookRegistry(); r.discover_and_load(); print(r.loaded_hooks)"
```

Or a direct filesystem check:

```
test -f ~/.hermes/hooks/revenium-classifier/HOOK.yaml
test -f ~/.hermes/hooks/revenium-classifier/handler.py
```

**Do NOT** use `hermes hooks list` or `hermes hooks test` to verify — that CLI is for shell hooks declared in `~/.hermes/config.yaml`, a different subsystem. The two hook systems share a name but are wired separately.
