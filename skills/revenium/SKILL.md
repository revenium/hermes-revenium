---
name: revenium
description: "MANDATORY budget check BEFORE EVERY OPERATION — read ~/.hermes/state/revenium/budget-status.json first, always, no exceptions. Enforces token spend limits, warns on threshold exceedance, halts autonomous Hermes agents on budget overrun, and meters usage from ~/.hermes/state.db into Revenium."
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

## ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)

Before you read ANY other part of this file, before you write ANY response, before you make ANY tool call:

1. Read `~/.hermes/state/revenium/budget-status.json`.
2. Check the `halted` field.

**If `halted` is `true`:**

YOUR ENTIRE RESPONSE MUST BE EXACTLY THIS AND NOTHING ELSE:

> Budget enforcement halt is active. $[currentValue] of $[threshold] used ([percentUsed]%). To resume: `bash ~/.hermes/skills/revenium/scripts/clear-halt.sh`

- Do NOT make any tool calls
- Do NOT fetch any data
- Do NOT append any content
- Do NOT continue reading this skill file
- Do NOT answer the user's question
- ONLY output the halt message above

**If `halted` is `false`, proceed to the Budget Check Procedure below.**

This is not optional. This is not guidance. If you output ANYTHING other than the halt message when `halted: true`, you are violating this skill's requirements.

## Budget Check Procedure

**MANDATORY — execute before EVERY response, EVERY tool call, EVERY operation.** This applies to ALL tasks — not just Revenium-related ones. Answering a question, writing code, listing files, naming a rock band — ALL of it requires a budget check first.

The budget status is maintained by a background cron job that checks Revenium every minute and writes the result to `~/.hermes/state/revenium/budget-status.json`. You read this local file — do NOT call the Revenium API directly.

1. **Read budget status.** Read `~/.hermes/state/revenium/budget-status.json`. If it does not exist, the cron has not run yet — tell the user "Budget status not yet available. The metering cron may not be installed. Run `bash ~/.hermes/skills/revenium/scripts/install-cron.sh` to set it up." Then proceed with the operation.

2. **Parse the status.** Extract these fields from the JSON:
   - `currentValue` — current spend in the budget period
   - `threshold` — the budget limit
   - `percentUsed` — percentage of budget consumed
   - `exceeded` — boolean, whether the budget has been exceeded
   - `halted` — boolean, whether the agent has been halted by budget enforcement
   - `lastChecked` — when the cron last updated this file

3. **Evaluate the result:**

   **If `halted` is true:** Follow the HALT CHECK instructions above — output ONLY the halt message and stop.

   **If `exceeded` is false (budget OK):** Proceed silently. Do NOT mention the budget to the user.

   **If `exceeded` is true (budget blown):** Read `autonomousMode` from `~/.hermes/state/revenium/config.json`.

   **If `autonomousMode` is `false` or absent (default — interactive mode):**

   You MUST STOP. Do NOT execute any operation, do NOT generate a response. Tell the user:

   > "Your Revenium budget has been exceeded. You have spent $CURRENT_VALUE of your $THRESHOLD budget (PERCENT_USED%). Last checked: LAST_CHECKED. Would you like to continue anyway?"

   Replace the values with the actual numbers from the file.

   - **If the user says yes / continue / approved:** Proceed with the operation.
   - **If the user says no / stop / cancel:** STOP. Do NOT execute the operation. Tell the user: "Operation cancelled. Run `/revenium` to adjust your budget."

   **If `autonomousMode` is `true` and `halted` is `false` but `exceeded` is `true`:** The user has explicitly cleared the halt — this is an approval to proceed. Continue with the operation.

### If budget-status.json is missing or unreadable

- Tell the user: "Budget status unavailable. Proceeding with caution."
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
- `~/.hermes/state/revenium/budget-status.json` — last cron snapshot of Revenium budget state
- `~/.hermes/state/revenium/revenium-hermes.ledger` — idempotency ledger for metered transactions
- `~/.hermes/state/revenium/revenium-metering.log` — cron log

Skill content (scripts, references) lives at `~/.hermes/skills/revenium/`. Bundled scripts are addressable via `${HERMES_SKILL_DIR}/scripts/`.

## Setup

At the start of any operation, check: does `~/.hermes/state/revenium/config.json` exist AND contain a non-empty `alertId` field?

- **If YES** and the user has NOT requested reconfiguration: setup is complete. Proceed to the budget check. Do NOT re-run setup.
- **If NO** (file missing, or file exists but `alertId` is absent/empty): you MUST run the Setup Flow below before proceeding. Do NOT execute any operations until setup is complete.

### Setup Flow

Follow these steps in order. If any step fails, STOP. Do NOT write an `alertId` into `config.json`. Do NOT proceed with operations.

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
   Then re-run `revenium config show` and confirm the API Key is non-empty. If it is still empty, STOP and tell the user to run `/revenium` when ready. Do NOT write an `alertId` into `config.json`.

3. **Prompt for organization name (optional).** Ask: "What is your organization name for Revenium reporting? (optional — press Enter to skip)" If the user provides a value, call it `ORG_NAME`. If they skip, leave it empty.

4. **Prompt for budget amount.** Ask: "What budget threshold would you like to set? (numeric amount, e.g., 50.00)" Call this value `AMOUNT`.

5. **Prompt for budget period.** Ask: "Which budget period would you like?" and present these four options:
   - DAILY
   - WEEKLY
   - MONTHLY
   - QUARTERLY

   Call the user's selection `PERIOD`.

6. **Prompt for autonomous mode.** Ask: "Will this agent run autonomously (without a user present)? If yes, budget exceedance will halt all operations and notify you. (yes/no, default: no)"

   - **If yes:** Set `AUTONOMOUS_MODE` to `true`. Then:
     - Ask: "Which Hermes messaging channel should receive budget alerts?" — Hermes' messaging toolset supports channels such as Slack, Discord, Telegram, and others depending on what the user has configured.
     - Call this value `NOTIFY_CHANNEL`.
     - Ask: "What is the notification target on that channel?" The format varies by channel — typical examples:
       - Slack: `user:<id>` or `channel:<id>`
       - Discord: `user:<id>` or `channel:<id>`
       - Telegram: chat id or `@username`
     - Call this value `NOTIFY_TARGET`.
   - **If no (default):** Set `AUTONOMOUS_MODE` to `false`. Skip notification prompts.

7. **Generate the alert name.** Set `ALERT_NAME` to `"Hermes {Period} Budget"` where `{Period}` is the title-cased period:
   - DAILY → "Hermes Daily Budget"
   - WEEKLY → "Hermes Weekly Budget"
   - MONTHLY → "Hermes Monthly Budget"
   - QUARTERLY → "Hermes Quarterly Budget"

   Do NOT ask the user for a name. This is automatic.

8. **Delete any existing Hermes budget alerts.** Before creating a new alert, you MUST check for and remove pre-existing Hermes budget alerts to prevent duplicates. Run:
   ```
   revenium alerts budget list --json
   ```
   Parse the JSON output and look for any alerts whose name starts with `"Hermes "`. For EACH matching alert, delete it:
   ```
   revenium alerts budget delete EXISTING_ALERT_ID --yes
   ```
   If the list command fails or returns no results, proceed. If a delete fails, log a warning but continue.

9. **Create the budget alert.** Run:
   ```
   revenium alerts budget create --name "ALERT_NAME" --threshold AMOUNT --period PERIOD --json
   ```
   If the exit code is non-zero: tell the user what went wrong, tell them to run `/revenium` when ready, and STOP. Do NOT write `config.json`.

10. **Extract the alert ID.** From the JSON response, extract the `"id"` field. This is a short alphanumeric string (e.g., `"75BjG5"`). Call this value `ALERT_ID`.

    **CRITICAL:** Do NOT use `anomalyId` from `budget get` responses — that is an integer and will cause HTTP 400 errors when passed to `budget get`. The correct value is the string `"id"` from the `budget create` response.

    To extract reliably:
    ```
    python3 -c "import json,sys; d=json.load(sys.stdin); print(d['id'])"
    ```

11. **Write `config.json`.** This MUST be the FINAL step — only write after ALL previous steps have succeeded. Load any existing config first so unknown keys are preserved, then merge in the values collected above:
    ```
    python3 -c "
    import json, os
    path = os.path.expanduser('~/.hermes/state/revenium/config.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path) as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        config = {}
    config['alertId'] = 'ALERT_ID'
    org = 'ORG_NAME'
    if org:
        config['organizationName'] = org
    autonomous = AUTONOMOUS_MODE  # True or False
    config['autonomousMode'] = autonomous
    if autonomous:
        config['notifyChannel'] = 'NOTIFY_CHANNEL'
        config['notifyTarget'] = 'NOTIFY_TARGET'
    else:
        config.pop('notifyChannel', None)
        config.pop('notifyTarget', None)
    with open(path, 'w') as f:
        json.dump(config, f, indent=2)
        f.write('\n')
    "
    ```

12. **Install the metering cron.** Run:
    ```
    bash ~/.hermes/skills/revenium/scripts/install-cron.sh
    ```
    This adds a per-minute cron entry that ships token deltas from `~/.hermes/state.db` to Revenium and refreshes `budget-status.json`.

If any step from 1–12 fails, stop and explain the failure. Do NOT leave a partial `config.json` with an `alertId` for an alert that does not exist.

## `/revenium` Command Behavior

When the user invokes `/revenium`:

1. Show the current budget status from Revenium using the configured `alertId`.
2. Show autonomous mode and current halt state.
3. Offer:
   - `reset` → recreate the alert with the same settings (zeroes current spend)
   - `reconfigure` → delete and recreate with new settings
   - `done` → exit

## Script Entry Points

- Install cron:
  ```
  bash ~/.hermes/skills/revenium/scripts/install-cron.sh
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

- `bash ~/.hermes/skills/revenium/scripts/install-cron.sh` succeeds and `crontab -l | grep hermes-revenium-metering` returns one entry.
- `bash ~/.hermes/skills/revenium/scripts/cron.sh` updates `~/.hermes/state/revenium/budget-status.json`.
- Revenium receives transactions from `~/.hermes/state.db` (visible in the Revenium UI under metering).
- When over budget with autonomous mode on, `budget-status.json` flips to `halted: true` and Hermes sends the halt notification through the configured messaging channel.

## FINAL ACTION — TASK CLASSIFICATION

After you have responded to the user, your last action before yielding back is to classify the
just-completed turn and write one or two marker records so the cron pipeline can attribute token
spend to a meaningful activity label. This is closing discipline — it mirrors the halt check at
the top of this file, which is opening discipline. Neither replaces the other.

> **Hard rule (D-09):** Classify the turn if ANY of: (a) you called a tool other than read-only file inspection; (b) you produced > 200 words of new content; (c) the user asked a question requiring multi-step reasoning. Skip the turn if your entire output is ≤ 2 sentences and called no tools.

When uncertain whether a turn crosses the threshold, skip — do not write a marker. The cron
falls back to `--task-type unclassified` for un-marked deltas. Under-classification is
recoverable; over-classification permanently pollutes the taxonomy.

### Examples

**Example 1 — Clear substantive (CLASSIFY):**
The user asked for a code review. You read two files with `read_file` and ran `grep` to find
usages. You wrote a 12-sentence review with suggested changes.
- Trigger: rule (a) — called tools (read_file, grep).
- Decision: **classify** with `task_type = code_review`.

**Example 2 — Clear trivial (SKIP):**
The user typed "what is 2+2?" You replied "4." in one sentence. No tools called.
- Trigger: none — ≤ 2 sentences, no tools.
- Decision: **skip** — no marker written.

**Example 3 — Borderline classify (CLASSIFY):**
The user asked you to explain how POSIX O_APPEND atomicity works. You wrote a five-paragraph
explanation covering the kernel guarantee, practical limits on macOS vs Linux, and the
belt-and-suspenders flock recommendation. No tools were called.
- Trigger: rule (b) — > 200 words of new content.
- Decision: **classify** with `task_type = analysis`.

**Example 4 — Borderline skip (SKIP):**
The user said "good morning, can you confirm you're ready?" You replied:
"Good morning — ready when you are." over two lines. No tools called.
- Trigger: none — despite being multi-line, the response is ≤ 2 sentences and called no tools.
- Decision: **skip** — no marker written.

### Lookup-first reuse

Before minting a new label, read the live taxonomy and reuse any existing label that fits the
turn's semantics. New labels are minted ONLY when no existing label clearly fits. Reuse is
aggressive — fragmentation (`code_review` vs `code-review`) is permanent harm; minting a
slightly-too-broad label is recoverable.

```python
import json, os

taxonomy_path = os.path.expanduser("~/.hermes/state/revenium/task-taxonomy.json")
try:
    with open(taxonomy_path) as f:
        taxonomy = json.load(f)
    candidate = next(
        (label for label in taxonomy.get("labels", {}) if label in <turn_description_keywords>),
        None
    )
except (FileNotFoundError, json.JSONDecodeError):
    candidate = None
# If candidate is None, mint a new snake_case label matching ^[a-z][a-z0-9_]{1,47}$
```

For the full schema, normalization rules, and the atomic mint pattern, see
`references/task-taxonomy.md`. The seed file ships at `skills/revenium/task-taxonomy.json`; the
live mutable copy is at `~/.hermes/state/revenium/task-taxonomy.json`.

### Trivial-label blocklist

The cron rejects markers carrying any of these `task_type` values — they indicate the hard rule
was not applied and a trivial acknowledgment was mis-classified as substantive work:

- `ack`
- `acknowledgment`
- `greeting`
- `confirmation`
- `hello`
- `thanks`

This list is closed-set for v1. New entries require a release.

### Marker write

The marker write is your last action before yielding back to the user. It is intentionally
placed here — physically last — so recency bias works in its favor. It is the step most likely
to be skipped under context pressure; placing it last makes it hardest to overlook.

Write two marker records for every substantive turn: one with `operation_type = "GUARDRAIL"`
(the classification decision itself, metered as a guardrail span per PROMPT-04) and one with
`operation_type = "CHAT"` (the task work). Two records per turn is the correct invariant.

```python
import fcntl
import json
import os
import secrets
import time

# Session ID resolution: primary mechanism is the HERMES_SESSION_ID environment variable,
# which Hermes is expected to set for every agent invocation. If the env var is absent
# (e.g., older Hermes versions or non-Hermes environments), fall back to a timestamp-based
# pseudo-session-id. The fallback produces a new ID on every Python invocation, so markers
# written across separate invocations within the same Hermes session may land in different
# files. This is a documented limitation — the cron's Phase 3 session reconciliation against
# state.db is the authoritative cross-check; the marker filename only needs to be groupable
# per logical conversation.
session_id = os.environ.get("HERMES_SESSION_ID") or f"pseudo-{int(time.time())}"

markers_dir = os.path.expanduser("~/.hermes/state/revenium/markers")
os.makedirs(markers_dir, exist_ok=True)
marker_path = os.path.join(markers_dir, f"{session_id}.jsonl")

def muid():
    # 13-char millisecond hex timestamp prefix (sortable) + 20-char random hex suffix
    # Total: 33 chars, collision-safe on a single machine, no pip dependency (MARK-03)
    return f"{int(time.time_ns() // 1_000_000):013x}" + secrets.token_hex(10)

def write_marker(task_type, operation_type):
    record = {
        "muid": muid(),
        "ts": time.time(),
        "sid": session_id,
        "task_type": task_type,       # replace with the looked-up or minted label
        "operation_type": operation_type,
    }
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n"
    encoded = line.encode("utf-8")
    # Single O_APPEND write; atomic on local POSIX fs for records < 1024 bytes
    with open(marker_path, "ab", buffering=0) as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(encoded)

# Replace "code_review" below with the label from your taxonomy lookup or mint.
# Call write_marker twice: once for the classification turn (GUARDRAIL), once for the work (CHAT).
write_marker("code_review", "GUARDRAIL")
write_marker("code_review", "CHAT")
```

If the turn was a skip (≤ 2 sentences, no tools), no marker is written; the cron will fall back
to `--task-type unclassified` for that session delta.
