#!/usr/bin/env bash
set -euo pipefail
# pre_llm_call.sh — inject guardrail halt directive into every Hermes turn.
# Reads stdin (JSON payload from Hermes hook dispatcher), checks guardrail-status.json,
# emits {"context":"..."} when halted:true (HOOK-01, D-01), emits one rate-limited
# stderr warn line per (session, ruleId) when any rule is in warn state (HOOK-02, D-05..D-07),
# emits {} otherwise. Fail-open on missing or corrupt status file (HOOK-04).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

# MUST be the first executable statement after ensure_path — Hermes pipes the JSON
# payload and waits for stdin to be consumed before reading stdout. An early exit
# without reading stdin hangs the hook (RESEARCH.md Pitfall 1).
# Captured rather than discarded since 2026-08-19: the warn-band sentinel is keyed
# on (session, rule), and the payload is the only authoritative source of
# session_id. pre_tool_call.sh:17 has always done this; this hook scanned the
# sessions dir instead and silently degraded whenever that scan came up empty.
# `payload="$(cat -)"` drains stdin exactly as fully as `cat - >/dev/null` did.
# WARNING: Do NOT move this line. Moving it will cause the hook to hang in production
# because Hermes blocks on stdin before reading stdout (Pitfall 1 mitigation).
payload="$(cat -)"

# Read guardrail status — multi-value extraction (halted + haltedRule in one call).
# Fail-open: any exception prints HALTED=false (HOOK-04).
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

# Fast path: not halted — run warn-band check then emit no-op.
if [[ "${halted}" != "true" ]]; then
  # Warn-band: emit one stderr line per (session, ruleId) for rules in 'warn' state.
  # D-05: stderr only — NOT routed through common.sh::warn (which writes to LOG_FILE).
  # Pitfall 3: do NOT call warn() here — that writes to the cron log.
  WARN_INFO=$(GUARDRAIL_STATUS_FILE="${GUARDRAIL_STATUS_FILE}" python3 -c "
import json, os
try:
    d = json.load(open(os.environ['GUARDRAIL_STATUS_FILE']))
    for r in d.get('rules', []):
        if r.get('state') == 'warn':
            print('WARN_RULE=' + str(r['ruleId']) + ':' + str(r.get('name', '?')) + ':' + str(r.get('metricType', '?')) + ':' + str(r.get('windowType', '?')) + ':' + str(r.get('currentValue', '?')) + ':' + str(r.get('hardLimit', '?')))
except Exception:
    pass
" 2>/dev/null || true)

  if [[ -n "${WARN_INFO}" ]]; then
    # Resolve session_id for rate-limit sentinel (mirrors pre_tool_call.sh:51-64 pattern).
    # Pitfall 4: session_id is often empty in the hook payload; scan newest non-cron session file.
    # REVENIUM_HOOK_PAYLOAD passes the payload through the ENVIRONMENT rather than
    # interpolating it into the quoted heredoc. pre_tool_call.sh interpolates
    # ('''${payload}'''), which a payload carrying a quote or a triple-quote can
    # break; the env route cannot be broken by payload content at all.
    SESSION_ID=$(HERMES_HOME="${HERMES_HOME}" REVENIUM_HOOK_PAYLOAD="${payload}" python3 -c "
import json, os
# The sentinel that rate-limits this warn is keyed on (session, rule), so an
# UNRESOLVABLE session must still yield a STABLE key. It used to return
# 'unknown-' + int(time.time()), which changes every second: the sentinel never
# matched, the warn fired on EVERY call, and one flag file leaked per call.
# Measured 2026-08-19 during the Phase 19 SC-8 real-breach run — 4 calls, 4 warn
# lines, 4 files. That is exactly the unbounded-warn failure WARN_FLAGS_DIR
# exists to prevent. A constant under-warns (one line per rule per install
# instead of per session) and that is the correct direction to err.
UNRESOLVED_SID = 'unresolved-session'

# Payload first — it is authoritative when present. Only fall back to scanning
# the sessions dir (which picks the newest file, not necessarily THIS session)
# when the payload carries no usable id.
try:
    _sid = (json.loads(os.environ.get('REVENIUM_HOOK_PAYLOAD') or '{}') or {}).get('session_id') or ''
    if _sid and '/' not in _sid and '..' not in _sid:
        print(_sid)
        raise SystemExit(0)
except SystemExit:
    raise
except Exception:
    pass

sessions_dir = os.path.join(os.environ.get('HERMES_HOME', os.path.expanduser('~/.hermes')), 'sessions')
try:
    candidates = [f for f in os.listdir(sessions_dir)
                  if f.startswith('session_') and f.endswith('.json')
                  and not f.startswith('session_cron_')]
    if candidates:
        newest = max(candidates, key=lambda f: os.path.getmtime(os.path.join(sessions_dir, f)))
        sid = newest[len('session_'):-len('.json')]
        # T-19-07-05: reject session_id with path separators
        if '/' not in sid and '..' not in sid:
            print(sid)
        else:
            print(UNRESOLVED_SID)
    else:
        print(UNRESOLVED_SID)
except Exception:
    print(UNRESOLVED_SID)
" 2>/dev/null || echo "unresolved-session")

    while IFS= read -r warn_line; do
      [[ -z "${warn_line}" ]] && continue
      # Extract ruleId from WARN_RULE=<ruleId>:<name>:... format.
      # f1 = WARN_RULE=<ruleId>, so strip the WARN_RULE= prefix for ruleId.
      rule_id="$(echo "${warn_line}" | cut -d: -f1 | sed 's/^WARN_RULE=//')"
      rule_name="$(echo "${warn_line}" | cut -d: -f2)"
      metric_type="$(echo "${warn_line}" | cut -d: -f3)"
      window_type="$(echo "${warn_line}" | cut -d: -f4)"
      current_value="$(echo "${warn_line}" | cut -d: -f5)"
      hard_limit="$(echo "${warn_line}" | cut -d: -f6)"

      # T-19-07-04: validate ruleId character set before constructing flag path.
      # Only allow [A-Za-z0-9_-]; skip and log a warn if malformed.
      if ! echo "${rule_id}" | grep -Eq '^[A-Za-z0-9_-]+$'; then
        warn "pre_llm_call: malformed ruleId '${rule_id}' — skipping warn emit (T-19-07-04)"
        continue
      fi

      warn_flag="${WARN_FLAGS_DIR}/${SESSION_ID}__${rule_id}.flag"
      if [[ ! -f "${warn_flag}" ]]; then
        mkdir -p "${WARN_FLAGS_DIR}"
        touch "${warn_flag}"
        # D-05: stderr ONLY — do NOT route through common.sh::warn (Pitfall 3)
        echo "Guardrail warn: rule '${rule_name}' (${metric_type}, ${window_type}): ${current_value} of ${hard_limit} hard-limit." >&2
      fi
    done < <(echo "${WARN_INFO}" | grep '^WARN_RULE=')
  fi

  printf '{}\n'
  exit 0
fi

# Halted: extract the 5 haltedRule fields from HALTED_AND_RULE.
RULE_NAME="$(echo "${HALTED_AND_RULE}" | sed -n 's/^RULE_NAME=//p')"
METRIC_TYPE="$(echo "${HALTED_AND_RULE}" | sed -n 's/^METRIC_TYPE=//p')"
WINDOW_TYPE="$(echo "${HALTED_AND_RULE}" | sed -n 's/^WINDOW_TYPE=//p')"
CURRENT_VALUE="$(echo "${HALTED_AND_RULE}" | sed -n 's/^CURRENT_VALUE=//p')"
HARD_LIMIT="$(echo "${HALTED_AND_RULE}" | sed -n 's/^HARD_LIMIT=//p')"

# Emit halt context injection via json.dumps (handles quoting/escaping safely).
# The context string instructs the agent to emit the D-01 verbatim halt string and nothing else.
# Pass field values via env vars for bash 3.2 compatibility (no ${VAR@Q}).
RULE_NAME="${RULE_NAME}" METRIC_TYPE="${METRIC_TYPE}" WINDOW_TYPE="${WINDOW_TYPE}" \
CURRENT_VALUE="${CURRENT_VALUE}" HARD_LIMIT="${HARD_LIMIT}" python3 -c "
import json, os
rule_name = os.environ['RULE_NAME']
metric_type = os.environ['METRIC_TYPE']
window_type = os.environ['WINDOW_TYPE']
current_value = os.environ['CURRENT_VALUE']
hard_limit = os.environ['HARD_LIMIT']
halt_str = (
    \"Guardrail halt active — rule '\" + rule_name + \"' (\" + metric_type + ', '
    + window_type + ') at ' + current_value + ' of ' + hard_limit
    + ' hard-limit. To resume: \`bash ~/.hermes/skills/revenium/scripts/clear-halt.sh\`'
)
directive = (
    'GUARDRAIL HALT ACTIVE. Your response for this turn MUST be EXACTLY the following '
    'message and nothing else:\n' + halt_str
)
print(json.dumps({'context': directive}))
"
