# Task Classification — Operational Detail

This file holds the full operational detail for the `## FINAL ACTION — TASK CLASSIFICATION` step in `SKILL.md`. Refer here for trigger rules, the `write_marker` snippet, the blocklist, and worked examples.

## Trigger (binary — no judgment calls)

You **MUST** classify the turn if ANY of these are true:
- You called any tool other than read-only file inspection. `read_file` alone does not count. `terminal`, `execute_code`, `write_file`, `patch`, `browser_*`, `memory`, `delegate_task`, `search_files`, `process`, `vision_analyze`, etc. ALL count.
- You produced > 200 words of new content in your response.
- The user asked a question that required multi-step reasoning to answer.

You **MUST** skip the marker write ONLY when ALL of these are true:
- Your entire response is ≤ 2 sentences.
- You called zero tools.

There is no "borderline / when in doubt skip" path. If you can argue either side, you have already triggered rule (a), (b), or (c) — classify.

## Required action sequence

Before your final response yields back to the user, you **MUST** call `execute_code` with the snippet below. **DO NOT skip it. DO NOT defer it to "next turn". DO NOT respond to the user without performing it.** The success print line (`markers written: <path>`) is your confirmation that the action completed.

**Step 1 — pick a `task_type` label.** Read the live taxonomy at `~/.hermes/state/revenium/task-taxonomy.json` and reuse the closest-fitting existing label. Mint a new `^[a-z][a-z0-9_]{1,47}$` snake_case label only if no existing label fits. Fragmentation (`code_review` vs `code-review`) is permanent harm; minting a slightly-too-broad label is recoverable.

The cron REJECTS markers carrying any of these `task_type` values — using them is a protocol violation:

- `ack`
- `acknowledgment`
- `greeting`
- `confirmation`
- `hello`
- `thanks`

For the full schema, normalization rules, and the atomic mint pattern, see `references/task-taxonomy.md`. The seed file ships at `skills/revenium/task-taxonomy.json`; the live mutable copy is at `~/.hermes/state/revenium/task-taxonomy.json`.

**Step 2 — call `execute_code` with this snippet.** Replace `"code_review"` with the label you picked in Step 1. Both calls happen in the same `execute_code` invocation — one with `operation_type="GUARDRAIL"` (the classification span), one with `operation_type="CHAT"` (the work span). Two records per substantive turn is the load-bearing invariant — exactly one is a protocol violation, zero on a substantive turn is a protocol violation.

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

def muid():
    # 13-char millisecond hex timestamp prefix (sortable) + 20-char random hex suffix
    # = 33 chars total, collision-safe on a single machine, no pip dependency (MARK-03)
    return f"{int(time.time_ns() // 1_000_000):013x}" + secrets.token_hex(10)

def write_marker(task_type, operation_type):
    record = {"muid": muid(), "ts": time.time(), "sid": session_id,
              "task_type": task_type, "operation_type": operation_type}
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n"
    with open(marker_path, "ab", buffering=0) as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line.encode("utf-8"))

# REPLACE "code_review" with your Step 1 label.
write_marker("code_review", "GUARDRAIL")  # classification span
write_marker("code_review", "CHAT")       # work span
print(f"markers written: {marker_path}")
```

## Self-check before yielding

Immediately before yielding your final response, answer these three questions to yourself. If markers were required and you have not written them, fix it NOW — call `execute_code` with the snippet above before sending your response. Do not promise to do it next turn. There is no next turn for this protocol.

1. Did I call any tool other than `read_file` in this turn? → if yes, markers REQUIRED.
2. Did I produce > 200 words of new content? → if yes, markers REQUIRED.
3. Did I just call `execute_code` with the `write_marker` snippet above? → if markers were REQUIRED, YES is the only acceptable answer.

## Examples

**Example 1 — Clear substantive (CLASSIFY):**
User asked for a code review. You called `read_file` twice and `terminal` once (for grep). You wrote 12 sentences with suggested changes.
- Rule (a) triggered: `terminal` is a non-read-only tool.
- Required action: `write_marker("code_review", "GUARDRAIL")` then `write_marker("code_review", "CHAT")`.

**Example 2 — Clear trivial (SKIP):**
User typed "what is 2+2?" You replied "4." in one sentence. No tools called.
- All skip conditions met: ≤ 2 sentences AND zero tools.
- Required action: NONE. No marker written.

**Example 3 — Borderline classify (CLASSIFY):**
User asked you to explain POSIX O_APPEND atomicity. You wrote a five-paragraph response covering the kernel guarantee, macOS vs Linux behavior, and the belt-and-suspenders flock recommendation. No tools were called.
- Rule (b) triggered: > 200 words of new content.
- Required action: `write_marker("analysis", "GUARDRAIL")` then `write_marker("analysis", "CHAT")`.

**Example 4 — Borderline skip (SKIP):**
User said "good morning, can you confirm you're ready?" You replied "Good morning — ready when you are." over two short lines. No tools called.
- All skip conditions met: ≤ 2 sentences AND zero tools.
- Required action: NONE.

Writing a marker on a clear-skip turn pollutes the taxonomy. Skipping a marker on a clear-classify turn breaks attribution. The rule is binary by design — there is no middle ground.
