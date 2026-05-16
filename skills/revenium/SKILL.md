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

- Make exactly ONE tool call: the mandated `CANCELLED` job-marker write below (and only if an arc was in progress) — then nothing else
- Do NOT fetch any data
- Do NOT append any content
- Do NOT continue reading this skill file
- Do NOT answer the user's question
- ONLY output the halt message above after the marker write

**Mandated single first step — CANCELLED job marker (arc-in-progress only):**

Before emitting the halt string, check whether you were mid-arc (you had been doing substantive work in this session and had not yet declared a job marker for the current arc). If yes, call `execute_code` ONCE with this snippet. If no arc was in progress (session idle, or the last arc was already declared), skip this step and go directly to emitting the halt string.

```python
import fcntl, json, os, secrets, time

# Resolve the active Hermes session id. Hermes writes each session transcript
# as ~/.hermes/sessions/session_<id>.json; the newest non-cron one is the
# active session. execute_code receives no HERMES_SESSION_ID env var and the
# legacy *.jsonl files are stale — both are deliberately ignored.
session_id = ""
sessions_dir = os.path.expanduser("~/.hermes/sessions")
try:
    candidates = [
        f for f in os.listdir(sessions_dir)
        if f.startswith("session_") and f.endswith(".json")
        and not f.startswith("session_cron_")
    ]
    if candidates:
        newest = max(
            candidates,
            key=lambda f: os.path.getmtime(os.path.join(sessions_dir, f)),
        )
        session_id = newest[len("session_"):-len(".json")]
except OSError:
    pass
if not session_id:
    session_id = f"pseudo-{int(time.time())}"

markers_dir = os.path.expanduser("~/.hermes/state/revenium/markers")
os.makedirs(markers_dir, mode=0o700, exist_ok=True)
marker_path = os.path.join(markers_dir, f"{session_id}.jsonl")

def write_job_marker(agentic_job_id, job_name, job_type, status):
    record = {"kind": "job", "ts": time.time(), "sid": session_id,
              "agentic_job_id": agentic_job_id, "job_name": job_name,
              "job_type": job_type, "status": status}
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n"
    with open(marker_path, "ab", buffering=0) as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line.encode("utf-8"))

# Degraded-deterministic halt marker (D-15): fixed shape, no taxonomy read.
# job_type "interrupted" is seeded in job-taxonomy.json — no mint needed.
write_job_marker(
    agentic_job_id="budget-halt-" + secrets.token_hex(2),
    job_name="Arc interrupted by budget halt",
    job_type="interrupted",
    status="CANCELLED",
)
print(f"halt job marker written: {marker_path}")
```

**If `halted` is `false`, proceed to the Budget Check Procedure below.**

This is not optional. If you output ANYTHING other than the halt message when `halted: true`, you are violating this skill's requirements.

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

**MANDATORY — NON-NEGOTIABLE. Execute before EVERY yield back to the user on a substantive turn.** Skipping leaves the cron pipeline blind and pollutes attribution with `unclassified` rows.

Classify the turn if you called any non-read-only tool, produced > 200 words, or answered a multi-step reasoning question. Skip only when your entire response is ≤ 2 sentences AND you called zero tools.

See `references/task-classification.md` for the trigger rules, the `write_marker` snippet, the blocklist, and worked examples.

## FINAL ACTION — JOB DECLARATION

**MANDATORY — NON-NEGOTIABLE. Execute once, retrospectively, at the end of every completed task arc.** Skipping leaves spend data with no business context — those markers will have no `--task-id`.

Declare a job marker when you complete, fail, or abandon the goal the arc was working toward. Skip only on a trivial turn (≤ 2 sentences, zero tools) with no arc in progress.

Step 1 — mint a specific `agentic_job_id` (business label + `secrets.token_hex(2)` suffix). Step 2 — select or mint a `job_type` from `~/.hermes/state/revenium/job-taxonomy.json`. Step 3 — determine `status`: `SUCCESS` (self-verified), `FAILED` (definitively unachievable), or `CANCELLED` (catch-all — when in doubt, use `CANCELLED`). Step 4 — call `execute_code` with the snippet below.

See `references/job-declaration.md` for arc-boundary rules, the SUCCESS/FAILED/CANCELLED criteria, the anti-collapse label examples, and worked examples.

```python
import fcntl, json, os, re, secrets, tempfile, time

# Resolve the active Hermes session id. Hermes writes each session transcript
# as ~/.hermes/sessions/session_<id>.json; the newest non-cron one is the
# active session. execute_code receives no HERMES_SESSION_ID env var and the
# legacy *.jsonl files are stale — both are deliberately ignored.
session_id = ""
sessions_dir = os.path.expanduser("~/.hermes/sessions")
try:
    candidates = [
        f for f in os.listdir(sessions_dir)
        if f.startswith("session_") and f.endswith(".json")
        and not f.startswith("session_cron_")
    ]
    if candidates:
        newest = max(
            candidates,
            key=lambda f: os.path.getmtime(os.path.join(sessions_dir, f)),
        )
        session_id = newest[len("session_"):-len(".json")]
except OSError:
    pass
if not session_id:
    session_id = f"pseudo-{int(time.time())}"

markers_dir = os.path.expanduser("~/.hermes/state/revenium/markers")
os.makedirs(markers_dir, mode=0o700, exist_ok=True)
marker_path = os.path.join(markers_dir, f"{session_id}.jsonl")

def write_job_marker(agentic_job_id, job_name, job_type, status):
    # Phase 7 D-03 frozen shape — reader-required: kind, agentic_job_id, job_type, status
    record = {"kind": "job", "ts": time.time(), "sid": session_id,
              "agentic_job_id": agentic_job_id, "job_name": job_name,
              "job_type": job_type, "status": status}
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n"
    with open(marker_path, "ab", buffering=0) as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line.encode("utf-8"))

# --- Taxonomy: reuse or mint job_type ---
taxonomy_path = os.path.expanduser("~/.hermes/state/revenium/job-taxonomy.json")

# REPLACE these three values with your Step 1-3 decisions.
agentic_job_id = "replace-with-step1-label-" + secrets.token_hex(2)
job_name = "Replace with a short human-readable description of the arc"
job_type = "research"                  # REPLACE with your Step 2 job_type (reuse a taxonomy label, or mint snake_case)
status = "CANCELLED"                    # SUCCESS | FAILED | CANCELLED

# Fail-open: if the taxonomy file is missing or unreadable, treat as empty taxonomy and mint freely.
existing_types = {}
if os.path.exists(taxonomy_path):
    try:
        with open(taxonomy_path) as f:
            existing_types = json.load(f).get("labels", {})
    except Exception:
        existing_types = {}

# Normalize FIRST (hyphens/spaces -> underscore, lowercase, strip non-[a-z0-9_])
# so a casing/spelling variant of an already-seeded label ("Bug Fix" -> "bug_fix")
# is recognized as a reuse — not a fresh mint that would clobber the curated seed.
normalized = re.sub(r'[^a-z0-9_]', '', re.sub(r'[-\s]+', '_', job_type.lower()))
if re.match(r'^[a-z][a-z0-9_]{1,47}$', normalized):
    job_type = normalized

# Persist only a genuinely new, well-formed job_type. setdefault on the inner
# write guarantees a curated seed entry is never overwritten — even under a
# normalization collision the membership check above did not catch.
if job_type not in existing_types and re.match(r'^[a-z][a-z0-9_]{1,47}$', job_type):
    try:
        if os.path.exists(taxonomy_path):
            with open(taxonomy_path, "r+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                data = json.load(f)
                data.setdefault("labels", {}).setdefault(job_type, {
                    "description": job_name,
                    "examples": [],
                })
                d = os.path.dirname(taxonomy_path)
                with tempfile.NamedTemporaryFile("w", dir=d, delete=False, suffix=".tmp") as tmp:
                    json.dump(data, tmp, indent=2, ensure_ascii=True)
                    tmp.flush()
                    os.fsync(tmp.fileno())
                    tmpname = tmp.name
                os.rename(tmpname, taxonomy_path)
    except Exception:
        pass  # fail-open: taxonomy write failure must not abort job declaration

write_job_marker(agentic_job_id, job_name, job_type, status)
print(f"job marker written: {marker_path}")
```

## LAST WORD — IF HALTED, STOP

**If `~/.hermes/state/revenium/budget-status.json` has `halted: true`, re-read that file NOW before responding.** Do not trust a compressed or summarized earlier read — re-read it fresh on every turn.

When `halted: true`, the HALT CHECK section at the top of this file (the "ABSOLUTE FIRST" block) overrides EVERYTHING below it — including both FINAL ACTION sections (TASK CLASSIFICATION and JOB DECLARATION). Their "MANDATORY" imperatives do NOT apply while halted: do not classify the task, do not declare a job, do not write a SUCCESS/FAILED job marker. The only permitted action is the mandated CANCELLED marker write (if an arc was in progress) followed by the verbatim halt string from the HALT CHECK block. Nothing else.
