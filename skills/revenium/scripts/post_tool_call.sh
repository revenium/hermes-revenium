#!/usr/bin/env bash
set -euo pipefail
# post_tool_call.sh — capture every tool call to a per-session JSONL file.
# Pure observer: writes to ~/.hermes/state/revenium/tool-events/<sid>.jsonl,
# makes no network call, and exits 0 on any internal failure (fail-open).
# Return value is ignored by Hermes for this event.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

# MUST be the first executable statement after ensure_path — Hermes pipes the JSON
# payload and waits for stdin to be consumed before reading stdout. An early exit
# without reading stdin hangs the hook (RESEARCH.md Pitfall 1).
payload="$(cat -)"

# Capture the tool call: parse payload, resolve session_id, apply success heuristic,
# append a compact 7-key JSONL record. Guarded with || true so any Python failure
# exits 0 and never blocks the agent (TOOLCAP-03, TOOLCAP-04).
TOOL_EVENTS_DIR="${TOOL_EVENTS_DIR}" HERMES_HOME="${HERMES_HOME}" \
  python3 - "${payload}" <<'PYEOF' || true
import fcntl, json, os, sys, time

payload_str = sys.argv[1] if len(sys.argv) > 1 else "{}"
try:
    payload = json.loads(payload_str)
except (json.JSONDecodeError, ValueError):
    payload = {}

tool_events_dir = os.environ.get("TOOL_EVENTS_DIR", "")
if not tool_events_dir:
    sys.exit(0)

tool_name = payload.get("tool_name") or "unknown"
extra = payload.get("extra") or {}

# Resolve session_id: three-tier fallback (mirror of pre_tool_call.sh lines 49-65).
# Tier 1: top-level payload field (may be empty string per Hermes source — Pitfall 2).
session_id = payload.get("session_id", "") or ""
if not session_id:
    # Tier 2: scan ~/.hermes/sessions/ for the newest non-cron session file.
    sessions_dir = os.path.join(
        os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")),
        "sessions"
    )
    try:
        candidates = [
            f for f in os.listdir(sessions_dir)
            if f.startswith("session_") and f.endswith(".json")
            and not f.startswith("session_cron_")
        ]
        if candidates:
            newest = max(candidates,
                key=lambda f: os.path.getmtime(os.path.join(sessions_dir, f)))
            session_id = newest[len("session_"):-len(".json")]
    except OSError:
        pass
if not session_id:
    # Tier 3: pseudo sentinel — always non-empty, event still captured.
    session_id = "pseudo-" + str(int(time.time()))

# Extract event-specific fields from extra.
# tool_call_id: fall back to ms-timestamp if absent (Pitfall 6 — may not be guaranteed).
tool_call_id = extra.get("tool_call_id") or ""
if not tool_call_id:
    tool_call_id = str(int(time.time() * 1000))

# duration_ms: cast to int — may be stringified by the Hermes serializer (Pitfall 4).
try:
    duration_ms = int(extra.get("duration_ms") or 0)
except (ValueError, TypeError):
    duration_ms = 0

# Success heuristic (D-03: default success; D-04: failure signals override).
# result is always a JSON string per the wire protocol.
success = True
error_msg = None
try:
    result_str = extra.get("result", "") or ""
    parsed = json.loads(result_str) if result_str else {}
    if isinstance(parsed, dict):
        # Failure signals — D-04: any signal overrides a positive flag.
        err = parsed.get("error")
        if err:
            success = False
            error_msg = str(err)[:500]  # D-05: cap at ~500 chars
        elif str(parsed.get("status", "")).lower() in ("error", "failed", "failure"):
            success = False
            error_msg = ("status=" + str(parsed.get("status")))[:500]
        elif parsed.get("exit_code") not in (None, 0):
            success = False
            error_msg = ("exit_code=" + str(parsed.get("exit_code")))[:500]
except (json.JSONDecodeError, TypeError, ValueError):
    # D-03: unparseable result treated as success; no error to extract.
    pass

# Build the JSONL record (D-02: compact key convention).
ts = time.time()  # D-01: hook capture time, not a payload field
record = {
    "sid": session_id,
    "ts": ts,
    "tool": tool_name,
    "tool_call_id": tool_call_id,
    "duration_ms": duration_ms,
    "success": success,
    "error": error_msg,
}
line = json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n"

# Append to per-session JSONL file with exclusive lock (mirrors pre_tool_call.sh pattern).
os.makedirs(tool_events_dir, mode=0o700, exist_ok=True)
# Ensure 0o700 even if common.sh mkdir -p created the dir first with umask-constrained mode.
try:
    os.chmod(tool_events_dir, 0o700)
except OSError:
    pass
event_file = os.path.join(tool_events_dir, session_id + ".jsonl")
with open(event_file, "ab", buffering=0) as fh:
    fcntl.flock(fh, fcntl.LOCK_EX)
    fh.write(line.encode("utf-8"))

print("tool-event captured: " + session_id + " " + tool_name, file=sys.stderr)
PYEOF
