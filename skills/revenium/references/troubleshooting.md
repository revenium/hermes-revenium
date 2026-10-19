# Troubleshooting

## `revenium` CLI not found

Install it and ensure it is on PATH:

```bash
brew install revenium/tap/revenium
```

## `sqlite3` not found

Install SQLite or ensure it is on PATH.

## `guardrail-status.json` missing

Run the cron runner manually:

```bash
bash ~/.hermes/skills/revenium/scripts/cron.sh
```

## Halt will not clear

Inspect the state file:

```bash
cat ~/.hermes/state/revenium/guardrail-status.json
```

Then clear it:

```bash
bash ~/.hermes/skills/revenium/scripts/clear-halt.sh
```

## No data appearing in Revenium

Run the read-only diagnostic report. It checks each pipeline stage, starting with
the most common failures:

```bash
bash ~/.hermes/skills/revenium/scripts/diagnose.sh
```

It changes nothing and ships nothing unless you add `--tick` (which runs one
real cron tick). It never prints the API key, so the output is safe to paste
into an issue. Add `--profile <name>` to inspect one profile home of a fleet.

Read `0. WHICH ENVIRONMENT` first. If `api-url` points to a different environment
from the dashboard you are watching, the other stages can look healthy while
the data arrives elsewhere.

For the raw log on its own:

```bash
tail -f ~/.hermes/state/revenium/revenium-metering.log
```

A long-running session (a Hermes cron job, a long one-shot) can legitimately show nothing for a
while: its completions are held until its first turn ends and the classifier writes its markers, so
that all of its spend ships linked to its job. Look for `holding <sid> — live session awaiting its
first classification` in the log. The hold lasts at most `REVENIUM_UNCLASSIFIED_MAX_HOLD_SECONDS`
(default 7200) from the session start, and ends sooner when the session goes idle for
`REVENIUM_CRON_SETTLE_SECONDS`; set it to `0` to meter long turns as they run.

Subagent sessions show the same silence for a different reason: their spend waits for the
delegating session's job marker, so it ships linked to that job. Look for `holding <n> subagent
session(s) of <root>` in the log. The wait ends when the root's job record appears, when the root
reaches a session boundary or goes idle for `REVENIUM_CRON_SETTLE_SECONDS`, or when the root is
older than the same cap (counted from the root's start).

Then verify:

- `~/.hermes/state.db` exists
- `revenium config show` succeeds
- the session rows in `state.db` have non-zero token counts
- if the data is arriving but every completion's trace type reads `uncategorized`, see [trace-type-uncategorized.md](trace-type-uncategorized.md)

## Dashboard shows $0.00 / Total evaluations 0 even though cron is shipping meter completions

Symptom: The Revenium dashboard for your rule shows `currentValue: 0` and "Total evaluations 0," but `revenium-metering.log` contains successful `Reported: session=...` lines and the ledger (`revenium-hermes.ledger`) grows every minute. The cron runs, but the rule sees none of the events.

Root cause: The rule was created with `--group-by ORGANIZATION` and no explicit `--filter`. The Revenium engine groups spend by ORGANIZATION but sees nothing in your team's child-org buckets because metered events fall through to the auto-discovery `UNCLASSIFIED` subscription. Quick-task 260524-lpu changed new rules to default to `--group-by AGENT --filter AGENT:IS:Hermes`, which does not depend on org/subscription resolution.

Fix: Delete the existing rule and re-run `setup-guardrails.sh` after upgrading to the hotfix. The new rule uses `--group-by AGENT --filter AGENT:IS:Hermes` and starts matching incoming traffic on the next cron tick.

```bash
# 1. List rules to find the id with currentValue: 0
revenium guardrails budget-rules list --output json | python3 -m json.tool

# 2. Delete the affected rule
revenium guardrails budget-rules delete <ruleId> --yes

# 3. Re-create with the hotfix defaults (uses --filter AGENT:IS:Hermes)
bash ~/.hermes/skills/revenium/scripts/setup-guardrails.sh \
  --hard-limit <N> --period MONTHLY

# 4. Wait one cron tick (~60s), then re-check currentValue
revenium guardrails budget-rules list --output json | python3 -m json.tool
```

If you want a non-default filter scope (per-model, per-provider, etc.), pass `--filter dim:op:val` or `--filters-json '<json>'` to `setup-guardrails.sh`. See `docs/migration-guardrails.md` for the full set of supported dimensions and operators.

## Jobs on Revenium are nameless, stuck at PENDING or closed too early

Six log lines in `revenium-metering.log` explain what the reporter held back or sent unlinked, and why. The first three and the fifth are written once per job, not every tick; the fourth is written once per held root per tick, bounded by `REVENIUM_UNCLASSIFIED_MAX_HOLD_SECONDS`; the sixth appears only on a tick that actually withheld a link. A completion that carried its classification forward ends its `Reported:` line with ` carried_from=<muid> job=<id|none>`; `job=none` means the row shipped the task type without a job.

| Log line | Meaning | What to do |
|---|---|---|
| `Subagent completions held: root job <id> has no confirmed create yet` | A subagent's completion was held because it would have named a job Revenium has not been told about yet. Revenium creates such a job with no name or type. The completion goes out on the next tick, once the root's `jobs create` is in `revenium-jobs.ledger`. | Nothing. |
| `Subagent completions shipping WITHOUT --agentic-job-id: root job <id> still has no confirmed create after <n>s` | The create did not land within `REVENIUM_JOBS_STALE_SECONDS`, so the spend was shipped unlinked instead of waiting forever. | Find out why the create fails: `grep 'jobs create failed' revenium-metering.log` and `revenium config show` (team id, auth). |
| `outcome held while session open: id=<id>` | A `CANCELLED` verdict was not reported because the session has no `ended_at` yet and is not idle. `CANCELLED` is the classifier's "uncertain" verdict. | Nothing. While the session is open the classifier re-checks a `CANCELLED` job on every turn, and if the work turns out to be finished it appends a `SUCCESS` marker for the same job id, which is reported instead. Otherwise `CANCELLED` is reported when the session ends, or after `REVENIUM_OPEN_SESSION_MAX_IDLE_SECONDS` of inactivity (default one day; `0` turns the hold off). A session that stays active never goes idle, so its job stays pending until the session ends. |
| `holding <n> subagent session(s) of <root> — its job marker has not landed yet` | <n> subagent sessions have finished and are ready to meter, but the session that delegated to them is still running and has not written its job yet, so their spend is held to ship linked to that job (a completion that has shipped cannot be linked afterwards). It goes out within a tick or two of the root's job marker landing. The wait ends sooner if the root goes idle for `REVENIUM_CRON_SETTLE_SECONDS`, reaches a session boundary without a job, or is older than `REVENIUM_UNCLASSIFIED_MAX_HOLD_SECONDS`. | Nothing. Set `REVENIUM_UNCLASSIFIED_MAX_HOLD_SECONDS=0` to meter subagents as they finish, unlinked. |
| `Carried completion shipping WITHOUT --agentic-job-id: job <id> <reason> (session=<sid>); the task type still carries` | A later turn of a classified session shipped with its task type but no job link. `<reason>` is `was never created` (no `JOB:<id>:created:` line, so a link would make Revenium create the job nameless), `closed more than <n>s ago` (the job's outcome was reported longer ago than `REVENIUM_JOBS_STALE_SECONDS`, and linking to a long-closed job resurrected it as a nameless pending row before) or `has an unconfirmed root` (the session cannot be shown to be a root, see the `parent_session_id` warn). | Nothing for `closed more than`: the spend is counted and the label is right. For `was never created`: `grep 'jobs create failed' revenium-metering.log`. For `unconfirmed root`: check that `sessions.parent_session_id` exists in `state.db`. |
| `Aux job link withheld on <n> row(s)` | Auxiliary usage was reported without a job link because the job is closed or was never created. This is expected on the first tick after an upgrade. | Nothing. The spend is counted either way. |

A job that is already nameless on Revenium was created by an earlier version of the reporter. The local ledger records it as created, so the reporter will not create it again and the name and type are not backfilled. Correct it in Revenium.

## Notification did not send

The halt notifier uses Hermes itself to send a message through the configured channel. Verify:

- Hermes CLI is installed and on PATH
- the messaging target is valid
- the relevant messaging toolset is configured for Hermes
