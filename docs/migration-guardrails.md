# Migrating to Guardrails-Native Budget Enforcement

This guide documents the v1.3 upgrade from polling-style `revenium alerts budget`
enforcement to first-class `revenium guardrails` budget rules. It covers the
`config.json` schema change, the auto-migration path that runs invisibly on the
next cron tick after upgrade, what gets preserved and what gets orphaned, and the
manual-recovery paths for edge cases. For the majority of operators the only
required action is upgrading the skill — everything else happens automatically.

## What changed

The `config.json` schema has one change: the `ruleIds` array (active, v1.3+) replaces
the `alertId` string (deprecated, v1.2) as the active enforcement handle. Both fields
use camelCase consistent with the rest of the file.

| Field | Type | Status |
|-------|------|--------|
| `ruleIds` | array of strings | Active (v1.3) — IDs of Revenium guardrail rules |
| `alertId` | string | Deprecated (v1.2) — orphaned after auto-migration; preserved for reference |

The remaining fields — `autonomousMode`, `notifyChannel`, `notifyTarget`, and
`organizationName` — survive unchanged through the migration. For the complete
field-by-field schema including types and constraints, see
`skills/revenium/references/config-schema.md`.

The corresponding Revenium-side budget alert that `alertId` referenced is never
auto-deleted. It remains on the Revenium server after the migration; operators who
want to clean up can remove it in the Revenium UI at their convenience.

## What happens automatically

On the next per-minute cron tick after upgrading to v1.3, `cron.sh` invokes
`setup-guardrails.sh --from-alert <id> --auto` as a new first stage of the cron
pipeline. If your `config.json` carries a legacy `alertId` and no `ruleIds`, the
migration script does the following:

1. Looks up the legacy alert via `revenium alerts budget list --output json`,
   filtering on the stored `alertId`.
2. Derives `--hard-limit` from the alert's threshold and `--warn-threshold` as
   80% of that limit (matching the default convention for new setups).
3. Creates an equivalent team-wide `TOTAL_COST` budget rule via
   `revenium guardrails budget-rules create`.
4. Writes `ruleIds: [<new-rule-id>]` into `config.json` atomically (write-temp-
   then-rename), preserving every other field — including the legacy `alertId`
   orphan.
5. Emits a single `deprecation:` info line in
   `~/.hermes/state/revenium/revenium-metering.log`:

   ```
   deprecation: legacy alertId <id> orphaned, migrated to ruleId <new-id>
   ```

**No operator action is required for the common case.** The script is idempotent:
every cron tick after the first successful migration is a fast no-op — the
`ruleIds`-presence check in `config.json` exits early before any API call is made.

The legacy `alertId` is left in `config.json` as an orphan. The corresponding
Revenium-side budget alert is preserved server-side and continues to accumulate
budget data independently. If you want to remove the orphan `alertId` key from
`config.json`, edit the file manually after verifying the `ruleIds` path is working.

## We preserve your enforcement posture

Migrated rules enforce **immediately by default** — they are NOT created in shadow
mode. If the legacy alert was halting your agent under autonomous mode in v1.2, the
same hard-limit number will halt the agent under v1.3. Auto-shadowing on migration
would silently lift enforcement without your awareness — that is an unacceptable
surprise when a real budget breach is active.

In practice: if your agent was being halted Monday under v1.2, it will continue to
be halted Tuesday after the v1.3 upgrade.

**If you want to validate the v1.3 enforcement path against real traffic before
turning enforcement on**, you can run the upgrade in shadow-on-migration mode. Before
the first cron tick after upgrading, add this line to
`~/.hermes/state/revenium/env`:

```bash
REVENIUM_MIGRATE_SHADOW_MODE=true
```

Cron sources that env file before invoking the migration stage, so `setup-guardrails.sh`
sees the override and creates the new rule in shadow mode (observe-only — no blocking).

Once you have validated the v1.3 path against your real traffic, clear the
`REVENIUM_MIGRATE_SHADOW_MODE` line from `~/.hermes/state/revenium/env`, then
re-run setup in interactive mode to recreate the rule with enforcement enabled:

```bash
bash ~/.hermes/skills/revenium/scripts/setup-guardrails.sh --interactive
```

Note: `revenium guardrails budget-rules update` does not support changing the
hard-limit of an existing rule. Changing a rule's threshold always requires a
delete-and-recreate, which `--interactive` handles for you via the
`[r]ecreate / [c]ancel` prompt.

## Rules are scoped to `AGENT:IS:Hermes` by default

Starting with the v1.3 hotfix on top of the guardrails migration, every rule
created by `setup-guardrails.sh` is automatically scoped with
`--group-by AGENT --filter AGENT:IS:Hermes`. This makes the rule evaluate
against the meter completions this skill ships (every
`revenium meter completion` call carries `--agent "Hermes"`), with all
matching spend rolled into a single self-contained bucket — no dependency on
org/subscription resolution.

**Why this matters:** the original v1.3 default was `--group-by ORGANIZATION`
with no filter, which made the Revenium engine group spend by organization but
see nothing in the team's child-org buckets because metered events fall
through to the auto-discovery `UNCLASSIFIED` subscription. With
`--group-by AGENT --filter AGENT:IS:Hermes`, the rule matches incoming traffic
by agent name and accumulates into a stable per-agent bucket that evaluates
correctly out of the box.

**The agent name is `Hermes` by default and centralized in
`scripts/common.sh::REVENIUM_AGENT_NAME`.** Override it via environment when
running multiple distinct Hermes installs against one Revenium tenant:

```bash
echo 'REVENIUM_AGENT_NAME=HermesProd' >> ~/.hermes/state/revenium/env
```

The same variable is read by `hermes-report.sh` when shipping `--agent`, so
the rule filter and the per-call agent argv always agree.

**To override the default filter scope** (e.g. scope a rule to a specific
model instead of agent), pass `--filter` or `--filters-json` to
`setup-guardrails.sh`:

```bash
# Per-model scope (overrides the AGENT default):
bash ~/.hermes/skills/revenium/scripts/setup-guardrails.sh \
  --hard-limit 50 --period MONTHLY \
  --filter MODEL:IS:claude-3-opus

# Multiple --filter values are ANDed:
bash ~/.hermes/skills/revenium/scripts/setup-guardrails.sh \
  --hard-limit 50 --period MONTHLY \
  --filter AGENT:IS:Hermes --filter PROVIDER:IS:anthropic

# Or pass a full JSON expression (advanced):
bash ~/.hermes/skills/revenium/scripts/setup-guardrails.sh \
  --hard-limit 50 --period MONTHLY \
  --filters-json '{"...": "..."}'
```

`--filter` and `--filters-json` are mutually exclusive. Supported dimensions
are AGENT, MODEL, PROVIDER, ORGANIZATION, CREDENTIAL, PRODUCT, SUBSCRIBER,
TASK_TYPE; supported operators are IS and IS_NOT (per the upstream Revenium
CLI contract).

If you upgraded from an earlier v1.3 install whose rule was created without
the AGENT filter (so the dashboard shows `$0.00 / Total evaluations 0`
despite a successful cron-ship history), delete the existing rule and
re-run `setup-guardrails.sh` to regenerate it with the new default scope.
See `references/troubleshooting.md` for the recipe.

## Orphan Cleanup (Optional)

After migration completes, the legacy `alertId` line remains in `config.json` — it is inert (no code path reads it) but cosmetically orphaned. To clean up:

1. **Verify the new ruleId is enforcing.** Tail the log and inspect the status file:
   ```bash
   tail -n 5 ~/.hermes/state/revenium/revenium-metering.log
   cat ~/.hermes/state/revenium/guardrail-status.json
   ```
   The status file's `rules[]` array should be non-empty and the newest cron-log line should show `HALT_TRANSITION=false` (or `=true` if a budget is already over).

2. **Confirm enforcement is live.** Either trigger a known warn or block scenario, or wait until the next real budget event. This step is optional but recommended before deleting the legacy alert.

3. **Delete the legacy alert in the Revenium UI.** Alerts → Budget → find the alert whose id matches `config.json::alertId` → delete.

4. **Optionally remove the orphan `alertId` key from `config.json`.** No shipping script exists for this — run the one-liner manually:
   ```bash
   python3 -c "import json, pathlib; p = pathlib.Path('~/.hermes/state/revenium/config.json').expanduser(); d = json.loads(p.read_text()); d.pop('alertId', None); p.write_text(json.dumps(d, indent=2) + '\n')"
   ```
   The `setup-guardrails.sh` script intentionally does not auto-remove `alertId` — orphan keys are an operator-driven cleanup (Phase 18 D-09: "alertId is orphaned, never auto-deleted").

## What you'll see after a successful migration

On the first cron tick after upgrading, the metering log records the migration:

```
[2026-05-22T14:00:01Z] [INFO ] [revenium] === Hermes Metering Reporter starting ===
[2026-05-22T14:00:03Z] [INFO ] [revenium] Reported: session=20260522_140000_abc muid=01893b8a3... task_type=research op_type=CHAT in=120 out=80
[2026-05-22T14:00:03Z] [INFO ] [revenium] === Done. Reported 1, skipped 0. ===
HALT_TRANSITION=false
[2026-05-22T14:00:04Z] [INFO ] [revenium] Cleaned up legacy status file (Phase 19 clean break)
deprecation: legacy alertId 5jpaPv orphaned, migrated to ruleId d5jng5
```

The new `~/.hermes/state/revenium/guardrail-status.json` looks like this:

```json
{
  "halted": false,
  "autonomousMode": true,
  "lastChecked": "2026-05-22T14:00:03.512847+00:00",
  "rules": [
    {
      "ruleId": "d5jng5",
      "name": "Engineering Budget",
      "metricType": "TOTAL_COST",
      "windowType": "MONTHLY",
      "groupBy": "ORGANIZATION",
      "currentValue": 47.32,
      "warnThreshold": 80.0,
      "hardLimit": 100.0,
      "state": "ok",
      "lastChecked": "2026-05-22T14:00:03.512847+00:00"
    }
  ]
}
```

(`haltedRule` and `haltedAt` are absent when `halted: false`.)

When a rule actually breaches its hard-limit under autonomous mode, the Hermes notification contains the embedded enforcement event:

```
Guardrail halt active — rule 'Engineering Budget' (TOTAL_COST, MONTHLY) at 102.5 of 100.0 hard-limit. To resume: bash ~/.hermes/skills/revenium/scripts/clear-halt.sh | Event: [2026-05-22T14:03:38.478Z] Rule 'Engineering Budget' blocked 1 request: TOTAL_COST $102.50 exceeded hard limit $100.00
```

The text after the `|` separator is the most recent `revenium guardrails enforcement-events list` entry. If the events list API is unavailable or returns empty, the suffix degrades to `Event: [(unavailable)] (unavailable)` — the halt still fires; only the audit detail is missing.

## Loud-on-failure behavior

Migration failures are loud, not silent. The cron pipeline continues metering
and checking budgets regardless of migration outcome — a migration failure does
not block the other pipeline stages.

Failure classes and their behavior:

- **CLI too old** (`revenium guardrails` subcommands unavailable): cron logs a
  `warn` line and skips the migration stage for this tick. Metering continues
  unaffected. Upgrade with `brew upgrade revenium/tap/revenium` and the migration
  will succeed on the next tick.

- **`revenium alerts budget list` failed** (network error, auth error): an `error`
  line is written to `revenium-metering.log`. One Hermes notification is sent to
  your configured `notifyChannel`/`notifyTarget`. Cron retries on the next tick;
  repeat notifications are suppressed unless the failure class changes (see
  notify-once gate below). `config.json` is not touched.

- **`revenium guardrails budget-rules create` failed**: same loud path as above.
  The legacy alert on Revenium is preserved; no half-state is written.

- **Legacy `alertId` references an alert that was deleted upstream**: special-cased
  — see section 5 (Manual recovery) below.

**Where to look:**

- `~/.hermes/state/revenium/revenium-metering.log` — every migration cron tick
  logs at least one line (`info` on success, `warn` if CLI is too old, `error` on
  a real failure). This is the first place to check.

- `~/.hermes/state/revenium/migration-notify-state` — the notify-once gate file.
  Its presence means "the operator has been notified about the most recent failure
  class." Its content is a 16-character SHA-256 hash that uniquely identifies the
  failure class. Delete the file to force a fresh notification on the next failure.

- Your configured Hermes messaging channel (`notifyChannel` + `notifyTarget` in
  `config.json`) — one notification per failure class is sent there. If those
  fields are not set, the notification falls back to a `warn` line in the log.

## Manual recovery: the deleted-upstream-alert case

**Symptom:** the cron migration stage logs this error:

```
error: Legacy alertId <id> not found in Revenium alerts budget list — it was deleted upstream.
```

Your configured notification channel also receives a one-time message with the same
text. `config.json` is NOT modified — the orphan `alertId` is left in place because
the script will not silently mutate operator-owned config when the upstream alert is
gone.

**Recovery steps:**

1. Verify the alert is indeed gone from Revenium:

   ```bash
   revenium alerts budget list --output json | python3 -m json.tool
   ```

   Grep for the orphaned `alertId` value — if it is absent from the output, the
   alert was deleted upstream as expected.

2. Re-run `/revenium setup` inside a Hermes session, or invoke the script directly:

   ```bash
   bash ~/.hermes/skills/revenium/scripts/setup-guardrails.sh --interactive
   ```

   The script collects fresh budget args (hard-limit, period, autonomous mode,
   notify channel and target), creates a new guardrails rule, and writes `ruleIds`
   into `config.json`. The orphan `alertId` line is still preserved — manually
   edit `config.json` to remove it once the new path is verified, or leave it
   (it is inert after migration).

3. Verify the new rule exists and has the expected limits:

   ```bash
   revenium guardrails budget-rules list --output json | python3 -m json.tool
   ```

   The new rule should appear with the expected `hardLimit`, `windowType`, and a
   status that is not shadow-mode (unless you chose shadow-mode during setup).
   Enforcement against the new rule begins on the next cron tick.

4. Optional cleanup: delete `~/.hermes/state/revenium/migration-notify-state`
   after recovery so the next failure (whatever class) gets a fresh notification
   rather than being silently suppressed by the old hash.

## Appendix: How it works internally

This section is contributor-facing. Operators who only need to understand the
migration outcome can stop reading after section 5.

**Single rule-creation entry point.** `skills/revenium/scripts/setup-guardrails.sh`
owns every `revenium guardrails budget-rules create` invocation in the codebase.
No other script issues a create. This keeps the rule-creation contract in one
place, regardless of whether the caller is an operator running `--interactive` or
the cron pipeline running `--from-alert <id> --auto`.

**Three modes, one code path.** The script supports three flag-driven modes: default
(all args from CLI flags), `--interactive` (operator prompts for missing args), and
`--from-alert <id> --auto` (cron migration). All three converge on the same
`create_rule` and `write_rule_ids_to_config` helpers — setup and migration share
a code path by design.

**Idempotency.** The `ruleIds`-presence check in `config.json` is the durable signal
that migration is complete. There is no separate sentinel file. After the first
successful migration, every subsequent cron tick exits 0 before any API call is made.

**Concurrency guard.** The script acquires an exclusive `flock` on
`~/.hermes/state/revenium/rules.lock` (declared as `RULES_LOCK_FILE` in `common.sh`)
before the pre-check-and-create window. Concurrent cron retries cannot race-create
duplicate rules.

**alertId preservation.** `setup-guardrails.sh` never writes or removes `alertId`.
Migration writes `ruleIds` alongside the existing `alertId` using an atomic
temp-then-rename write. Removal of the orphan `alertId` is always a manual operator
action.

**State paths.** Every path lives in `skills/revenium/scripts/common.sh` as the
single source of truth. The new v1.3 paths introduced for this feature are
`GUARDRAIL_STATUS_FILE`, `RULES_LOCK_FILE`, and `MIGRATION_NOTIFY_FILE`.
