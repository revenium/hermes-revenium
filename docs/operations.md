# Operations

[← Documentation index](README.md)

Everything here lives under `~/.hermes/skills/revenium/scripts/`. On a multi-profile host,
add `--profile <name>` where the script accepts it; without it you are acting on the
default home. See [the fleet guide](fleet.md).

## Start here

`diagnose.sh` is the read-only triage report — credentials, cron, ledgers, the settle gate,
plugin and hook state, and a per-profile summary in one pass. Run it before reading
anything else:

```bash
bash ~/.hermes/skills/revenium/scripts/diagnose.sh
bash ~/.hermes/skills/revenium/scripts/diagnose.sh --profile ent
```

## Running a stage by hand

`cron.sh` runs the whole pipeline once under the same lock the crontab uses. The individual
stages are each safe to run alone.

| Command | What it does |
|---|---|
| `cron.sh` | One full tick: plugin health, completion metering, guardrails, tool events, API events, drain status |
| `hermes-report.sh` | Completion metering only — reads `state.db`, splits deltas across markers |
| `guardrail-check.sh` | Guardrail evaluation only — refreshes `guardrail-status.json` |
| `tool-event-report.sh` | Ship unledgered tool events |
| `api-event-report.sh` | Ship unledgered API events (the event-metering path) |
| `drain-status.sh` | Maintain the cutover drain gate |
| `plugin-status.sh` | Report classifier registration health; alert-only, never repairs |
| `hooks-status.sh` | Report whether the hooks are registered *and* firing |

`hooks-status.sh` returns stable exit codes for scripting: `0` hooks firing, `1` not
registered, `2` registered but inert.

## Changing state

| Command | What it does |
|---|---|
| `clear-halt.sh` | Clear an active halt. `--rule-id <id>` clears one rule. This is the only thing that clears a halt — nothing auto-clears. |
| `prune-markers.sh` | Remove marker files older than 30 days — and job-assessment sidecars on their own, longer clock (`REVENIUM_ASSESSMENT_RETENTION_DAYS`, 90 days by default), skipping any sidecar a correction currently holds locked — plus the warn-flag sentinel directories (`.warn`, `.fallback-warn`, `.outcome-warn`, `.probe-warn`) — these accumulate one zero-byte file per suppressed condition and are never pruned automatically. `--dry-run` previews. Deliberately not wired into cron; run it periodically by hand. |
| `install-cron.sh` / `uninstall-cron.sh` | Manage the per-minute crontab entry |
| `install-hooks.sh` / `uninstall-hooks.sh` | Manage the three shell hooks in `config.yaml` |
| `install-plugin.sh` | Copy the classifier into `~/.hermes/plugins/` and restart the gateway |
| `setup-guardrails.sh` | Create the budget rules |
| `correct-assessment.sh` | Append a correction to a job's value assessment. Requires `--job-id`, `--value`, `--currency` and `--reason`; `--value-low` / `--value-high` are optional and default to equal bounds. The correction **appends** — locally as a new line in the job's sidecar, remotely as a new revision via `revenium jobs outcome-update` — and the original stays byte-identical and readable. `--dry-run` previews without writing anything, locally or remotely. Operator-only and deliberately not wired into cron. Exits non-zero, loudly, on a `revenium` CLI that lacks `jobs outcome-update`. |

A halt clear buys one tick. If the rule is still breached, the next tick re-halts.

## Reading the state

```bash
tail -f ~/.hermes/state/revenium/revenium-metering.log      # the cron log
cat    ~/.hermes/state/revenium/guardrail-status.json       # live guardrail snapshot
crontab -l | grep hermes-revenium-metering                  # is the cron installed
```

Three append-only ledgers hold the idempotency record. A record present in one has already
shipped:

```bash
tail -n 20 ~/.hermes/state/revenium/revenium-hermes.ledger       # completions
tail -n 20 ~/.hermes/state/revenium/revenium-jobs.ledger         # agentic jobs
tail -n 20 ~/.hermes/state/revenium/revenium-tool-events.ledger  # tool events
cat        ~/.hermes/state/revenium/tool-events/<sid>.jsonl      # captured tool calls
```

## Two failure modes worth knowing first

**`guardrail-status.json` does not exist.** The cron has never run. Run `cron.sh` once by
hand to seed it.

**`tool-events/` stays empty while Hermes is clearly running tools.** Run `hooks-status.sh`.
The usual cause is hooks that are registered but not yet approved on `hermes chat`.

More failure modes are in
[`references/troubleshooting.md`](../skills/revenium/references/troubleshooting.md).

## Testing

The repo ships stdlib `unittest` checks covering the expected file inventory, frontmatter
shape, runtime path conventions, shell syntax, marker and taxonomy schemas, split
conservation, and the golden argv fixtures:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

One test plan is manual and not in the suite: the halt-check survivability runbook at
[`references/halt-survivability.md`](../skills/revenium/references/halt-survivability.md).
Run it before any release that modifies the halt block in `SKILL.md`, to confirm the
halt-check anchor still fires under context dilution in a long session.

## Uninstalling

```bash
bash ~/.hermes/skills/revenium/scripts/uninstall-cron.sh
bash ~/.hermes/skills/revenium/scripts/uninstall-hooks.sh
rm -rf ~/.hermes/skills/revenium ~/.hermes/state/revenium
```

That leaves the Revenium-side rules in place. To remove those too:

```bash
revenium guardrails budget-rules list
revenium guardrails budget-rules delete <rule-id> --yes
```
