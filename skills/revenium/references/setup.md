# Revenium Skill Setup

Fresh-install and reconfigure flows are driven by `setup-guardrails.sh --interactive`. The script collects all operator input, calls `revenium guardrails budget-rules create`, and writes `ruleIds` into `~/.hermes/state/revenium/config.json`. Pass `--shadow-mode` to create rules in shadow mode (evaluate without blocking real traffic); the default is enforcing.

## Initial setup

1. **Verify prerequisites:**
   ```bash
   revenium config show
   sqlite3 --version
   python3 --version
   ```

2. **Configure CLI credentials** if `revenium config show` reports an empty API Key. See the SKILL.md Setup Flow step 2 for the four `revenium config set` calls.

3. **Run the setup script:**
   ```bash
   bash ~/.hermes/skills/revenium/scripts/setup-guardrails.sh --interactive
   ```
   The script prompts for budget hard-limit, period, organization name, autonomous mode and notification channel/target, and optionally per-task-type rules from the live `task-taxonomy.json`. On success it writes `ruleIds` into `~/.hermes/state/revenium/config.json`.

4. **Install the metering cron AND budget-halt hooks:**
   ```bash
   bash ~/.hermes/skills/revenium/scripts/install-cron.sh
   bash ~/.hermes/skills/revenium/scripts/install-hooks.sh
   ```

## Default rule filter scope

Rules created by `setup-guardrails.sh` are automatically scoped with `--group-by AGENT --filter AGENT:IS:Hermes` so they evaluate against the meter completions this skill ships (every call carries `--agent "Hermes"`). Grouping by AGENT puts all matching spend in one self-contained bucket keyed on the agent name — no dependency on org/subscription resolution. Without this default, an `ORGANIZATION`-grouped rule on a team whose orgs have no subscriptions would see `currentValue: 0` forever (events fall through to Revenium's auto-discovery `UNCLASSIFIED` subscription). The agent name is centralized in `scripts/common.sh::REVENIUM_AGENT_NAME` (default `Hermes`, env-overridable) so the rule filter and the per-call `--agent` argv stay in sync.

To override the default filter — for example, scoping a rule to a specific model or provider — pass `--filter dim:op:val` (repeatable) or `--filters-json '<json>'` (single expression, mutually exclusive with `--filter`):

```bash
bash ~/.hermes/skills/revenium/scripts/setup-guardrails.sh \
  --hard-limit 50 --period MONTHLY \
  --filter MODEL:IS:claude-3-opus
```

Supported dimensions: AGENT, MODEL, PROVIDER, ORGANIZATION, CREDENTIAL, PRODUCT, SUBSCRIBER, TASK_TYPE. Operators: IS, IS_NOT. See `docs/migration-guardrails.md` for the full discussion and the upgrade-time recovery path for installs whose existing rule was created without the filter.

## Reconfigure flow

Re-run `setup-guardrails.sh --interactive`. The script detects existing `ruleIds`, prints the current rules via `revenium guardrails budget-rules list`, and prompts `[r]ecreate / [c]ancel`. The recreate path deletes every listed rule via `revenium guardrails budget-rules delete <id> --yes` and runs the fresh-install prompts. The cancel path exits 0 without changes. Note that hard-limit and period cannot be updated in place (the Revenium CLI's `budget-rules update` only supports `--name`); the recreate flow is the supported path for changing limits or periods.

## Auto-migration (legacy alertId installs)

Hosts upgrading from a v1.2 install that has only `alertId` in `config.json` and no `ruleIds` are auto-migrated on the next cron tick — no operator action required for the common case. Full contract in `docs/migration-guardrails.md` (what changes, what happens automatically, enforcement-posture preservation, loud-on-failure behavior, manual recovery, contributor appendix).

## Multi-profile / fleet installs

A Hermes **profile** is a separate Hermes home directory — its own `config.yaml`,
`.env`, `SOUL.md`, sessions, skills, cron jobs, and `state.db` under
`~/.hermes/profiles/<name>/`. The default profile uses `~/.hermes/` directly
(see the Hermes user guide `user-guide/profiles.md`; enumerate with
`hermes profile list` or by scanning `~/.hermes/profiles/*/`).

Install the metering skill across a whole fleet in one command:

```bash
# Wire the default home AND every ~/.hermes/profiles/<name>/ home:
bash ~/.hermes/skills/revenium/scripts/install.sh --all-profiles

# Or wire specific profiles (repeatable):
bash ~/.hermes/skills/revenium/scripts/install.sh --profile gtm --profile qa
```

`--all-profiles` runs the full wiring (plugin, hooks, cron) once per profile with
`HERMES_HOME` / `REVENIUM_STATE_DIR` / `REVENIUM_AGENT_NAME` set to that profile.
The individual leaf scripts also accept the same flags:

```bash
bash ~/.hermes/skills/revenium/scripts/install-cron.sh  --all-profiles
bash ~/.hermes/skills/revenium/scripts/install-hooks.sh --all-profiles --auto-accept
```

### Per-agent attribution (AGENT vs ORGANIZATION dimension)

Each profile's completions attribute to a **distinct AGENT** so Revenium
analytics separate spend per agent. `--all-profiles` defaults
`REVENIUM_AGENT_NAME` to **`Hermes-<profile>`** for named profiles (and `Hermes`
for the default profile). Override per profile by baking `REVENIUM_AGENT_NAME`
into that profile's crontab env or the per-state `env` file.

This is the **AGENT** dimension (`--agent` argv). It is **not** the same as the
**ORGANIZATION** dimension. `organizationName` in `config.json` is the
ORGANIZATION — a company/product like `tableforone` — and it is threaded through
completions, tool-events, **and** `revenium jobs create` so a job and its
transactions never land in different orgs. **Do not** set `organizationName` to
an agent or profile name; that pollutes the ORGANIZATION dimension. The cron logs
a `WARN` if `organizationName` looks like an agent name (`Hermes`, `Hermes-<x>`,
or the configured agent).

### Cron fan-out (no clobbering)

Each profile gets a **unique** crontab marker
`# hermes-revenium-metering-<profile>` that bakes that profile's `HERMES_HOME`,
`REVENIUM_STATE_DIR`, `REVENIUM_AGENT_NAME`, and `REVENIUM_CRON_SETTLE_SECONDS`.
Installing a second profile never overwrites the first. `uninstall-cron.sh`
removes **all** metering lines (every profile) and leaves foreign crontab lines
untouched. Orphaned metering lines (whose `cron.sh` target no longer exists after
a `~/.hermes` reset) are reconciled automatically on the next `install-cron.sh`.

### `REVENIUM_CRON_SETTLE_SECONDS` sizing vs job-inference latency

The reporter defers a session's completions until the classifier plugin's
`.ready` sentinel lands (the **authoritative** gate — the plugin writes it only
*after* it has written the `kind:"job"` marker), or until the session ages past
`REVENIUM_CRON_SETTLE_SECONDS`. This age-fallback exists only for installs with
**no** classifier plugin (no sentinel ever arrives).

The default is **600 seconds**. It **must exceed worst-case job-inference
latency** — the classifier's job-inference LLM call can take ~200s under
concurrent multi-profile load. If the window is shorter than that latency, the
age-fallback meters and ledgers a session's completions *before* the job marker
exists, and per-muid dedup then permanently **orphans** them from the job created
a tick later (`revenium jobs transactions <id>` shows "No transactions found").
Metering-only installs (no classifier plugin, no job markers) can safely lower it
— there is nothing to wait for.

### Headless gateways: `hooks_auto_accept`

Profile gateways are **headless** and never show Hermes' interactive hook-approval
prompt, so registered hooks stay **inert** — tool-event capture silently never
happens. For gateway-served profiles you MUST set `hooks_auto_accept: true` in
that profile's `config.yaml`. `install-hooks.sh --auto-accept` does this;
`install.sh --all-profiles` passes `--auto-accept` for every fleet child
automatically. In shadow/metering-only mode the two `pre_*` enforcement hooks are
inert overhead that still fire on every LLM/tool call — use
`install-hooks.sh --metering-only` to register only `post_tool_call`
(tool-event capture).

### Multiplex mode (one gateway serves all profiles)

Both deployment modes from `user-guide/multi-profile-gateways.md` are supported:

- **One process per profile** (default): each profile's gateway runs with
  `HERMES_HOME` set to that profile's home. The classifier and cron resolve paths
  from `HERMES_HOME` directly.
- **Multiplexed single gateway** (`gateway.multiplex_profiles: true`): ONE default
  gateway serves every profile; sessions are namespaced `agent:<profile>:…` and
  each profile keeps its own home/`state.db`/markers. The classifier resolves the
  **owning profile's** home/state.db/markers/`config.json` **per session** from
  the `agent:<profile>:…` namespace, so a namespaced session's markers and
  `.ready` sentinel land under that profile's `state/revenium/` where its
  per-profile cron picks them up — not in the default home. Non-namespaced
  sessions and the default profile resolve to the process home unchanged.

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

Subagent sessions (where `state.db.sessions.parent_session_id` is non-null) inherit the root user-facing session's `task_type` — one classification per user-request lineage, no per-subagent LLM call. The plugin also gates its LLM call on `guardrail-status.json::halted`; if the budget is halted, the plugin writes `task_type: unclassified` and emits a `WARN` log line instead of spending against the halted budget.

The plugin is installed by `install.sh` into `~/.hermes/plugins/revenium-classifier/`, and the same script idempotently adds `revenium-classifier` to the `plugins.enabled` list in the Hermes configuration. **`hermes skills install` does NOT relocate the `plugins/` subdirectory** — operators installing via that path must additionally copy `~/.hermes/skills/revenium/plugins/revenium-classifier/` to `~/.hermes/plugins/revenium-classifier/` themselves AND add `revenium-classifier` to the `plugins.enabled` list in the Hermes configuration.

After installing or updating the plugin, **run `hermes gateway restart`**. The plugin manager loads plugins once at agent startup; there is no file-watch reload.

To verify the plugin loaded, inspect the Hermes plugin-manager startup log for the plugin-load line (reference shape — same form Hermes uses for bundled plugins such as `hermes-agent/plugins/disk-cleanup/`).

Or a direct filesystem check:

```
test -f ~/.hermes/plugins/revenium-classifier/plugin.yaml
test -f ~/.hermes/plugins/revenium-classifier/__init__.py
test -f ~/.hermes/plugins/revenium-classifier/classifier.py
```

**Do NOT** use `hermes hooks list` or `hermes hooks test` to verify — that CLI is for shell hooks declared under the `hooks:` block of the Hermes configuration (a different subsystem). The `on_session_end` plugin and `hermes hooks` shell hooks share the word "hook" but are wired separately.

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
