#!/usr/bin/env bash
set -euo pipefail
# pre_tool_call.sh — block all tool calls when the budget is halted.
# Also writes a CANCELLED job marker if an arc was in progress (D-05, D-06).
# Reads stdin (JSON payload from Hermes hook dispatcher), checks budget-status.json,
# emits {"action":"block",...} when halted:true, {} otherwise (fail-open).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

# MUST be the first executable statement after ensure_path — Hermes pipes the JSON
# payload and waits for stdin to be consumed before reading stdout. An early exit
# without reading stdin hangs the hook (RESEARCH.md Pitfall 1).
payload="$(cat -)"

# Read budget status — fail open to false if missing or corrupt (V5 Input Validation).
halted="$(BUDGET_STATUS_FILE="${BUDGET_STATUS_FILE}" python3 -c "
import json, os
try:
    d = json.load(open(os.environ['BUDGET_STATUS_FILE']))
    print('true' if d.get('halted') else 'false')
except Exception:
    print('false')
" 2>/dev/null || echo 'false')"

# Fast path: not halted — emit no-op and exit cleanly.
if [[ "${halted}" != "true" ]]; then
  printf '{}\n'
  exit 0
fi

# Arc-in-progress gate (D-06): write the CANCELLED marker only if an arc was in
# progress. Guard with || true so a failure here never prevents the block directive.
MARKERS_DIR="${MARKERS_DIR}" python3 - "${MARKERS_DIR}" "${payload}" <<'PYEOF' || true
import fcntl, json, os, secrets, sys, time

markers_dir = sys.argv[1]
try:
    payload = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
except (json.JSONDecodeError, IndexError):
    payload = {}

# Resolve session_id: try payload first (may be empty string per Hermes source),
# then scan ~/.hermes/sessions/ for the newest non-cron session file (RESEARCH.md
# Pitfall 2 — session_id is kwargs.get("session_id") or "" in _serialize_payload).
session_id = payload.get("session_id", "") or ""
if not session_id:
    sessions_dir = os.path.join(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")), "sessions")
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
    session_id = "pseudo-" + str(int(time.time()))

marker_path = os.path.join(markers_dir, session_id + ".jsonl")

# Arc-in-progress check: does the marker file contain any task/job line?
# kind absent = v1.0 task marker; kind 'task'/'job' = arc marker.
# A corrupt JSONL line is skipped, not fatal (T-12-06).
arc_in_progress = False
if os.path.exists(marker_path):
    try:
        with open(marker_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("kind") in ("task", "job", None):
                        arc_in_progress = True
                        break
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass

if not arc_in_progress:
    sys.exit(0)

# Write CANCELLED job marker (degraded-deterministic shape, Phase 8 D-15).
os.makedirs(markers_dir, mode=0o700, exist_ok=True)
record = {
    "kind": "job",
    "ts": time.time(),
    "sid": session_id,
    "agentic_job_id": "budget-halt-" + secrets.token_hex(2),
    "job_name": "Arc interrupted by budget halt",
    "job_type": "interrupted",
    "status": "CANCELLED",
}
line = json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n"
with open(marker_path, "ab", buffering=0) as fh:
    fcntl.flock(fh, fcntl.LOCK_EX)
    fh.write(line.encode("utf-8"))
print("halt job marker written: " + marker_path, file=sys.stderr)
PYEOF

# Emit block directive — stdout carries ONLY this JSON object; diagnostics go to stderr.
SKILL_DIR="${SKILL_DIR}" python3 -c "
import json, os
skill_dir = os.environ['SKILL_DIR']
msg = (
    'Budget halt active — all tool calls are blocked. '
    'To resume: bash ' + skill_dir + '/scripts/clear-halt.sh'
)
print(json.dumps({'action': 'block', 'message': msg}))
"
