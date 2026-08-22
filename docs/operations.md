# Operations

[← Documentation index](README.md)

## Manual commands

```bash
# Run metering + guardrail check + tool-event reporting once
bash ~/.hermes/skills/revenium/scripts/cron.sh

# Run only the SQLite reporter (completion metering with task-type)
bash ~/.hermes/skills/revenium/scripts/hermes-report.sh

# Run only the guardrail check
bash ~/.hermes/skills/revenium/scripts/guardrail-check.sh

# Run only the tool-event reporter
bash ~/.hermes/skills/revenium/scripts/tool-event-report.sh

# Clear an active halt
bash ~/.hermes/skills/revenium/scripts/clear-halt.sh

# Prune stale marker files (30+ days old by default; --dry-run to preview)
bash ~/.hermes/skills/revenium/scripts/prune-markers.sh

# (Re)install the per-minute cron entry
bash ~/.hermes/skills/revenium/scripts/install-cron.sh

# Remove the cron entry
bash ~/.hermes/skills/revenium/scripts/uninstall-cron.sh

# Register the pre_llm_call / pre_tool_call / post_tool_call hooks
bash ~/.hermes/skills/revenium/scripts/install-hooks.sh

# Remove the shell hooks
bash ~/.hermes/skills/revenium/scripts/uninstall-hooks.sh

# Install the revenium-classifier plugin into ~/.hermes/plugins/
bash ~/.hermes/skills/revenium/scripts/install-plugin.sh

# Diagnose whether the hooks are registered AND firing
bash ~/.hermes/skills/revenium/scripts/hooks-status.sh
```


## Status & diagnostics

```bash
# Tail the metering log
tail -f ~/.hermes/state/revenium/revenium-metering.log

# Inspect the live guardrail snapshot
cat ~/.hermes/state/revenium/guardrail-status.json

# Confirm the cron is installed
crontab -l | grep hermes-revenium-metering

# Inspect the completion idempotency ledger
tail -n 20 ~/.hermes/state/revenium/revenium-hermes.ledger

# Inspect the agentic-job idempotency ledger
tail -n 20 ~/.hermes/state/revenium/revenium-jobs.ledger

# Inspect the tool-event idempotency ledger
tail -n 20 ~/.hermes/state/revenium/revenium-tool-events.ledger

# Inspect captured tool-event records for a session
cat ~/.hermes/state/revenium/tool-events/<sid>.jsonl

# Run the end-to-end hooks diagnostic — registration + approval mode + recent
# capture activity + state.db cross-check. Stable exit codes for scripting:
# 0 = hooks firing, 1 = not registered, 2 = registered but inert.
bash ~/.hermes/skills/revenium/scripts/hooks-status.sh
```

If `guardrail-status.json` does not exist, the cron has not run yet — run `cron.sh` once manually to seed it. If `tool-events/` stays empty even though Hermes is running tools, run `hooks-status.sh` first — the most common cause is the hooks being registered but not yet approved on `hermes chat`. More failure modes are documented in [`skills/revenium/references/troubleshooting.md`](../skills/revenium/references/troubleshooting.md).


## Uninstalling

```bash
bash ~/.hermes/skills/revenium/scripts/uninstall-cron.sh
bash ~/.hermes/skills/revenium/scripts/uninstall-hooks.sh
rm -rf ~/.hermes/skills/revenium ~/.hermes/state/revenium
```

Optionally clean up the Revenium-side guardrail rules:

```bash
revenium guardrails budget-rules list
revenium guardrails budget-rules delete <rule-id> --yes
```


## Testing

The repo ships stdlib `unittest` smoke checks covering expected files, frontmatter shape, runtime path conventions, and shell-script syntax:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Beyond the automated smoke checks, a manual halt-check survivability test plan — operator runbook is documented at `skills/revenium/references/halt-survivability.md`. Run it before any release that modifies the `SKILL.md` halt block to confirm the halt-check anchor still fires correctly under context dilution in long sessions.

