---
name: revenium
description: "MANDATORY guardrail check BEFORE EVERY OPERATION — read ~/.hermes/state/revenium/guardrail-status.json first, always, no exceptions. Enforces Revenium guardrails-native budget rules, warns on threshold exceedance, halts autonomous Hermes agents on guardrail block, and meters usage from ~/.hermes/state.db into Revenium."
version: 1.0.0
author: Revenium
license: MIT
category: DevOps
platforms: [macos, linux]
required_environment_variables:
  - REVENIUM_API_KEY
  - REVENIUM_API_URL
  - REVENIUM_TEAM_ID
required_credential_files:
  - path: ~/.config/revenium/config.yaml
    description: Revenium CLI credentials (API key, team-id, tenant-id, owner-id)
metadata:
  hermes:
    tags: [DevOps, FinOps, revenium, budgets, metering, observability]
    category: devops
---

# Revenium

## HALT CHECK — DEFENSE-IN-DEPTH BACKSTOP

Guardrail enforcement is handled structurally by Hermes shell hooks: `pre_llm_call`
injects the halt directive into every turn before the LLM generates a response, and
`pre_tool_call` blocks all tool calls when a halt is active. This section is a
defense-in-depth fallback only — it applies if the hooks have not yet been consented
or are temporarily unavailable.

**If you read `guardrail-status.json` and `halted` is `true`:** read the `haltedRule`
block for the offending rule's details. Your entire response must be exactly the
following and nothing else:

> Guardrail halt active — rule '[haltedRule.name]' ([haltedRule.metricType],
> [haltedRule.windowType]) at [haltedRule.currentValue] of [haltedRule.hardLimit]
> hard-limit. To resume: `bash ~/.hermes/skills/revenium/scripts/clear-halt.sh`

Substitute the actual values from `guardrail-status.json::haltedRule`. Do not add
any other content.

**If `halted` is `false`, proceed to the Guardrail Check Procedure below.**

## Guardrail Check Procedure

**MANDATORY — execute before EVERY response, EVERY tool call, EVERY operation.**

The guardrail status is maintained by a background cron job that checks Revenium
every minute and writes the result to `~/.hermes/state/revenium/guardrail-status.json`.
You read this local file — do NOT call the Revenium API directly.

1. **Read guardrail status.** Read `~/.hermes/state/revenium/guardrail-status.json`.
   If it does not exist, tell the user "Guardrail status not yet available. The metering
   cron may not be installed. Run `bash ~/.hermes/skills/revenium/scripts/install-cron.sh`
   to set it up." Then proceed with the operation.

2. **Parse the status.** Extract `halted` from the JSON.

3. **Evaluate:**

   **If `halted` is `true`:** Follow the HALT CHECK backstop above — output ONLY the
   halt message using `haltedRule` fields, and stop.

   **If `halted` is `false`:** Proceed. Do NOT mention the guardrail status to the user.

### If guardrail-status.json is missing or unreadable

- Tell the user: "Guardrail status unavailable. Proceeding with caution."
- Proceed with the operation — fail open, do not block the user.

## Path Resolution

This skill stores its content under `~/.hermes/skills/revenium/` and its mutable runtime state under `~/.hermes/state/revenium/`. When using file tools (read, write, edit), pass paths with `~/` — the tool resolves `~` to `$HOME` automatically. When running shell commands via Hermes' terminal/execute_code toolsets, use the explicit `$HOME/.hermes/...` form so the shell expands `$HOME` correctly. In sandboxed Hermes execution environments, `~` may not resolve the same way `$HOME` does.

## When to Use

Use this skill when you want Hermes to:

- enforce a spending budget before costly operations
- meter usage from `~/.hermes/state.db` into Revenium
- maintain a local budget status file for low-latency checks
- halt autonomous execution when spend exceeds a threshold
- deliver budget halt notifications through Hermes messaging

## Runtime State

This skill stores mutable runtime state in:

- `~/.hermes/state/revenium/config.json` — alert ID, organization, autonomous flag, notification target
- `~/.hermes/state/revenium/guardrail-status.json` — last cron snapshot of Revenium guardrail rule state
- `~/.hermes/state/revenium/revenium-hermes.ledger` — idempotency ledger for metered transactions
- `~/.hermes/state/revenium/revenium-metering.log` — cron log

Skill content (scripts, references) lives at `~/.hermes/skills/revenium/`. Bundled scripts are addressable via `${HERMES_SKILL_DIR}/scripts/`.

## Setup

At the start of any operation, check: does `~/.hermes/state/revenium/config.json` exist AND contain a non-empty `ruleIds` array?

- **If YES** and the user has NOT requested reconfiguration: setup is complete. Proceed to the budget check. Do NOT re-run setup.
- **If NO** (file missing, or file exists but `ruleIds` is absent or an empty array): you MUST run the Setup Flow below before proceeding. Do NOT execute any operations until setup is complete.

Note: `config.json` may carry a legacy `alertId` field from a v1.2 install — that field is deprecated and orphaned by auto-migration; ignore it for the setup-detection gate. The cron pipeline auto-migrates legacy installs on the next tick. See `docs/migration-guardrails.md` for the migration contract.

### Setup Flow

Follow these steps in order. If any step fails, STOP and explain the failure. Do NOT prompt the user for budget details yourself, and do NOT write any IDs into `config.json` yourself.

1. **Verify the Revenium CLI is configured.** Run:
   ```
   revenium config show
   ```
   If it reports a non-empty API Key, skip to step 3. If the CLI is not on PATH, tell the user to install it (`brew install revenium/tap/revenium` on macOS) and STOP.

2. **If no API key is configured:** collect the following from the user:
   - **API Key**: "Please provide your Revenium API key."
   - **Team ID**: "Please provide your Revenium Team ID."
   - **Tenant ID**: "Please provide your Revenium Tenant ID."
   - **User ID** (owner id): "Please provide your Revenium User ID."

   Then run, in order:
   ```
   revenium config set key API_KEY
   revenium config set team-id TEAM_ID
   revenium config set tenant-id TENANT_ID
   revenium config set owner-id USER_ID
   ```
   Then re-run `revenium config show` and confirm the API Key is non-empty. If it is still empty, STOP and tell the user to run `/revenium` when ready.

3. **Run the setup script:**
   ```
   bash ~/.hermes/skills/revenium/scripts/setup-guardrails.sh --interactive
   ```
   The script prompts the operator for budget hard-limit, period, organization name, autonomous mode + notification channel/target, and (optionally) per-task-type rules drawn from the live `task-taxonomy.json`. On success, it creates the Revenium guardrails budget rules via `revenium guardrails budget-rules create` and writes the resulting `ruleIds` array into `~/.hermes/state/revenium/config.json`. You do NOT prompt the user for budget details yourself, and you do NOT write any IDs into `config.json` yourself — the script owns the entire interaction and the entire write.

   Capture the exit code and act on it:
   - **Exit 0, final output line `Created N rule(s). config.json updated. ruleIds=[...]`**: succeeded. Proceed to step 4.
   - **Exit 0, final output line `Cancelled.`**: operator cancelled. STOP without proceeding to step 4.
   - **Non-zero exit**: failure. Tell the user the failure message verbatim, instruct them to address it and re-run `/revenium`. STOP. Do NOT proceed to step 4.

   If the user asks to set up in shadow mode, run `setup-guardrails.sh --interactive --shadow-mode` instead. By default, rules created via `--interactive` are enforcing.

4. **Install the metering cron AND guardrail-halt hooks** (in order):
   ```
   bash ~/.hermes/skills/revenium/scripts/install-cron.sh
   ```
   This adds a per-minute cron entry that ships token deltas from `~/.hermes/state.db` to Revenium and refreshes `guardrail-status.json`.
   ```
   bash ~/.hermes/skills/revenium/scripts/install-hooks.sh
   ```
   This registers the `pre_llm_call`, `pre_tool_call`, and `post_tool_call` revenium shell hooks in the Hermes hook configuration. The hooks are registered but inert until the user approves them on the next `hermes chat` invocation.

5. **Approve hooks on first `hermes chat`** — Hermes shows an approval prompt the first time each hook fires. The hooks are inert until approved.

Legacy `alertId` installs auto-migrate on the first cron tick — see `docs/migration-guardrails.md` for the schema-change and manual recovery procedure.

## `/revenium` Command Behavior

When the user invokes `/revenium`:

1. Show the configured `ruleIds` from `~/.hermes/state/revenium/config.json` and a one-line summary of each rule's current state (read from `guardrail-status.json`).
2. Show autonomous mode and current halt state from the available status file.
3. Offer:
   - `reconfigure` → run `bash ~/.hermes/skills/revenium/scripts/setup-guardrails.sh --interactive` (the script's re-run UX handles delete-and-recreate).
   - `done` → exit.

## Script Entry Points

- Set up guardrails budget rules (fresh install or reconfigure):
  ```
  bash ~/.hermes/skills/revenium/scripts/setup-guardrails.sh --interactive
  ```
- Install cron:
  ```
  bash ~/.hermes/skills/revenium/scripts/install-cron.sh
  ```
- Install hooks:
  ```
  bash ~/.hermes/skills/revenium/scripts/install-hooks.sh
  ```
- Run metering once:
  ```
  bash ~/.hermes/skills/revenium/scripts/cron.sh
  ```
- Clear halt:
  ```
  bash ~/.hermes/skills/revenium/scripts/clear-halt.sh
  ```

## References

- `references/setup.md` — setup, reset, and reconfigure flows
- `references/troubleshooting.md` — failure modes and operator fixes

## Verification

Run these in order:

```bash
crontab -l | grep hermes-revenium-metering         # one entry
bash ~/.hermes/skills/revenium/scripts/hooks-status.sh   # exit 0 = registered + firing
jq '.ruleIds' ~/.hermes/state/revenium/config.json # non-empty array
```

Wait one cron tick (≤60s), then:

```bash
cat ~/.hermes/state/revenium/guardrail-status.json  # expect rules[] populated
```

- `bash ~/.hermes/skills/revenium/scripts/install-cron.sh` succeeds and `crontab -l | grep hermes-revenium-metering` returns one entry.
- `bash ~/.hermes/skills/revenium/scripts/install-hooks.sh` succeeds; then `bash ~/.hermes/skills/revenium/scripts/hooks-status.sh` confirms all three hook commands (`pre_llm_call`, `pre_tool_call`, `post_tool_call`) are registered and firing.
- `bash ~/.hermes/skills/revenium/scripts/cron.sh` updates `~/.hermes/state/revenium/guardrail-status.json`.
- Revenium receives transactions from `~/.hermes/state.db` (visible in the Revenium UI under metering).
- When a guardrail rule is blocked with autonomous mode on, `guardrail-status.json` flips to `halted: true` and Hermes sends the halt notification (including the most recent enforcement-events list entry) through the configured messaging channel.

## FINAL ACTION — TASK CLASSIFICATION

**MANDATORY — NON-NEGOTIABLE. Execute before EVERY yield back to the user on a substantive turn.** Skipping leaves the cron pipeline blind and pollutes attribution with `unclassified` rows.

Classify the turn if you called any non-read-only tool, produced > 200 words, or answered a multi-step reasoning question. Skip only when your entire response is ≤ 2 sentences AND you called zero tools.

When the current session is a subagent (delegated via `delegate_task` from a root session), markers MUST carry the root delegator's `trace_id` and `agentic_job_id` so analytics roll subagent spend up under the root's arc. The code-side classifier plugin handles this automatically by walking `state.db.sessions.parent_session_id` at marker-write time; if you write a backstop marker yourself, use the root session's id, not the current subagent's id.

See `references/task-classification.md` for the trigger rules, the `write_marker` snippet, the blocklist, and worked examples.

## FINAL ACTION — JOB DECLARATION

Job markers are now written automatically by the `revenium-classifier` plugin at
session end — it infers the job arc(s) from session data and writes the
`kind:"job"` marker to `markers/<sid>.jsonl` without agent involvement. This
section is a defense-in-depth backstop only.

**Write a job marker yourself only if you have explicit, specific reason to
believe the automatic path failed** (e.g., you can see that `markers/<sid>.jsonl`
exists and contains task markers but no `kind:"job"` line for an arc you know
completed). Do not write a job marker as a routine end-of-turn action.

The frozen Phase 7 D-03 marker shape (for reference if you need the backstop):
`{"kind":"job","ts":<unix_float>,"sid":<session_id>,"agentic_job_id":<str>,`
`"job_name":<str>,"job_type":<str>,"status":"SUCCESS"|"FAILED"|"CANCELLED"}`

For a FAILED arc, add an optional `"failure_reason":<str>` (brief plain-text cause).
The cron ships it to Revenium as `--metadata` on `jobs outcome`; omit it for
SUCCESS/CANCELLED. Absent key = no-op (readers default to empty).

See `references/job-declaration.md` for the arc-boundary and SUCCESS/FAILED/CANCELLED
criteria the classifier uses (and the rare backstop case).

## LAST WORD — PRE-RESPONSE CHECKLIST (EVERY TURN)

Before you yield any response, answer these three questions. If any answer is NO, take the corrective action before sending.

1. **Have I read `~/.hermes/state/revenium/guardrail-status.json` during THIS turn?** If NO — read it now, before responding. Every turn requires a fresh read; a prior turn's read does not count. Do not trust memory, context, or a summarized earlier result.

2. **Is `halted` true in the file I just read?** If YES — the HALT CHECK section at the top of this file overrides EVERYTHING below it including both FINAL ACTION sections (TASK CLASSIFICATION and JOB DECLARATION). Their "MANDATORY" imperatives do NOT apply while halted. The only permitted action is the mandated CANCELLED marker write (if an arc was in progress) followed by the verbatim halt string from the HALT CHECK block. Nothing else.

3. **Did I complete the TASK CLASSIFICATION FINAL ACTION (and a job marker backstop if I had explicit reason to believe the automatic classifier path failed)? If NO — write the missing task marker first before sending the response.**
