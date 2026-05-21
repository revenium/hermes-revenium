#!/usr/bin/env bash
set -euo pipefail
# pre_tool_call.sh — block all tool calls when a guardrail halt is active.
# Also writes a CANCELLED job marker if an arc was in progress (D-05, D-06).
# Reads stdin (JSON payload from Hermes hook dispatcher), checks guardrail-status.json,
# emits {"action":"block",...} when halted:true, {} otherwise (fail-open).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

# MUST be the first executable statement after ensure_path — Hermes pipes the JSON
# payload and waits for stdin to be consumed before reading stdout. An early exit
# without reading stdin hangs the hook (RESEARCH.md Pitfall 1).
payload="$(cat -)"

# Read guardrail status — fail open to HALTED=false if missing or corrupt (HOOK-04).
HALTED_AND_RULE=$(GUARDRAIL_STATUS_FILE="${GUARDRAIL_STATUS_FILE}" python3 -c "
import json, os
try:
    d = json.load(open(os.environ['GUARDRAIL_STATUS_FILE']))
    halted = d.get('halted', False)
    if halted:
        hr = d.get('haltedRule', {})
        print('HALTED=true')
        print('RULE_NAME=' + str(hr.get('name', '?')))
        print('METRIC_TYPE=' + str(hr.get('metricType', '?')))
        print('WINDOW_TYPE=' + str(hr.get('windowType', '?')))
        print('CURRENT_VALUE=' + str(hr.get('currentValue', '?')))
        print('HARD_LIMIT=' + str(hr.get('hardLimit', '?')))
    else:
        print('HALTED=false')
except Exception:
    print('HALTED=false')
" 2>/dev/null || echo 'HALTED=false')

halted="$(echo "${HALTED_AND_RULE}" | sed -n 's/^HALTED=//p')"

# Not-halted path: check warn band, emit {}, exit.
if [[ "${halted}" != "true" ]]; then
  # Warn-band: emit one stderr line per (session, ruleId) for rules in 'warn' state.
  # D-05: stderr only — NOT routed through common.sh::warn (which writes to LOG_FILE).
  WARN_INFO=$(GUARDRAIL_STATUS_FILE="${GUARDRAIL_STATUS_FILE}" python3 -c "
import json, os
try:
    d = json.load(open(os.environ['GUARDRAIL_STATUS_FILE']))
    for r in d.get('rules', []):
        if r.get('state') == 'warn':
            print('WARN_RULE=' + r['ruleId'] + ':' + r['name'] + ':' + r['metricType'] + ':' + r['windowType'] + ':' + str(r['currentValue']) + ':' + str(r['hardLimit']))
except Exception:
    pass
" 2>/dev/null || true)

  if [[ -n "${WARN_INFO}" ]]; then
    # Resolve session_id: try payload first, then scan sessions dir (Pitfall 2).
    SESSION_ID=$(HERMES_HOME="${HERMES_HOME}" python3 -c "
import json, os, time
payload_str = '''${payload}'''
try:
    payload_obj = json.loads(payload_str)
    sid = payload_obj.get('session_id', '') or ''
    if sid:
        print(sid)
        raise SystemExit(0)
except Exception:
    pass
sessions_dir = os.path.join(os.environ.get('HERMES_HOME', os.path.expanduser('~/.hermes')), 'sessions')
try:
    candidates = [f for f in os.listdir(sessions_dir)
                  if f.startswith('session_') and f.endswith('.json')
                  and not f.startswith('session_cron_')]
    if candidates:
        newest = max(candidates, key=lambda f: os.path.getmtime(os.path.join(sessions_dir, f)))
        print(newest[len('session_'):-len('.json')])
    else:
        print('unknown-' + str(int(time.time())))
except Exception:
    print('unknown-' + str(int(time.time())))
" 2>/dev/null || echo "unknown-$$")

    while IFS= read -r warn_line; do
      [[ -z "${warn_line}" ]] && continue
      rule_id="$(echo "${warn_line}" | cut -d: -f2)"
      rule_name="$(echo "${warn_line}" | cut -d: -f3)"
      metric_type="$(echo "${warn_line}" | cut -d: -f4)"
      window_type="$(echo "${warn_line}" | cut -d: -f5)"
      current_value="$(echo "${warn_line}" | cut -d: -f6)"
      hard_limit="$(echo "${warn_line}" | cut -d: -f7)"
      # Security T-19-08-04: validate ruleId char-set before constructing flag path.
      if [[ ! "${rule_id}" =~ ^[A-Za-z0-9_-]+$ ]]; then
        continue
      fi
      warn_flag="${WARN_FLAGS_DIR}/${SESSION_ID}__${rule_id}.flag"
      if [[ ! -f "${warn_flag}" ]]; then
        mkdir -p "${WARN_FLAGS_DIR}"
        touch "${warn_flag}"
        echo "Guardrail warn: rule '${rule_name}' (${metric_type}, ${window_type}): ${current_value} of ${hard_limit} hard-limit." >&2
      fi
    done < <(echo "${WARN_INFO}" | grep '^WARN_RULE=')
  fi

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
    "agentic_job_id": "guardrail-halt-" + secrets.token_hex(2),
    "job_name": "Arc interrupted by guardrail halt",
    "job_type": "interrupted",
    "status": "CANCELLED",
}
line = json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n"
with open(marker_path, "ab", buffering=0) as fh:
    fcntl.flock(fh, fcntl.LOCK_EX)
    fh.write(line.encode("utf-8"))
print("halt job marker written: " + marker_path, file=sys.stderr)
PYEOF

# Extract haltedRule fields for the block directive.
RULE_NAME="$(echo "${HALTED_AND_RULE}" | sed -n 's/^RULE_NAME=//p')"
METRIC_TYPE="$(echo "${HALTED_AND_RULE}" | sed -n 's/^METRIC_TYPE=//p')"
WINDOW_TYPE="$(echo "${HALTED_AND_RULE}" | sed -n 's/^WINDOW_TYPE=//p')"
CURRENT_VALUE="$(echo "${HALTED_AND_RULE}" | sed -n 's/^CURRENT_VALUE=//p')"
HARD_LIMIT="$(echo "${HALTED_AND_RULE}" | sed -n 's/^HARD_LIMIT=//p')"

# Emit block directive — stdout carries ONLY this JSON object; diagnostics go to stderr.
SKILL_DIR="${SKILL_DIR}" RULE_NAME="${RULE_NAME}" METRIC_TYPE="${METRIC_TYPE}" \
WINDOW_TYPE="${WINDOW_TYPE}" CURRENT_VALUE="${CURRENT_VALUE}" HARD_LIMIT="${HARD_LIMIT}" \
python3 -c "
import json, os
rule_name = os.environ['RULE_NAME']
metric_type = os.environ['METRIC_TYPE']
window_type = os.environ['WINDOW_TYPE']
current_value = os.environ['CURRENT_VALUE']
hard_limit = os.environ['HARD_LIMIT']
msg = (
    \"Guardrail halt active — rule '\" + rule_name + \"' (\" + metric_type + ', '
    + window_type + ') at ' + current_value + ' of ' + hard_limit
    + ' hard-limit. To resume: bash ' + os.environ['SKILL_DIR'] + '/scripts/clear-halt.sh'
)
print(json.dumps({'action': 'block', 'message': msg}))
"
