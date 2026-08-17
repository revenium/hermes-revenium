#!/usr/bin/env bash
# api-event-report.sh — reads per-session api-event JSONL spool files (written
# by the revenium-classifier plugin's post_api_request hook), enriches each
# event with the task type that was actually in force when the call happened,
# and ships each unledgered record to Revenium via `revenium meter completion`.
#
# Phase 32 Plan 01 (D-01/D-03) proved the pipe end to end with a hardcoded
# "unclassified" task-type and no attribution. Plan 02 (this revision) makes
# what flows through it correct:
#
#   - D-09 partition (checked BEFORE the settle gate, session-level, not
#     per-record): a session already present in the frozen legacy HERMES:
#     ledger is skipped ENTIRELY by this path, so the two paths can never
#     double-report the same session.
#   - C-6 settle gate: a session's events are held until markers/.ready/<sid>
#     lands (resolved through the OWNING profile's directory — the same
#     per-session resolution hermes-report.sh already uses), or shipped as
#     unclassified once the session ages past REVENIUM_CRON_SETTLE_SECONDS
#     with no sentinel ever arriving (C-5b — preserves the standing
#     backward-compatibility guarantee for installs with no classifier).
#   - C-5/C-5a/D-14 temporal join: each event is attributed to the marker
#     whose window [marker_i.ts, marker_{i+1}.ts) contains the event's own
#     timestamp; events before the first window-owning marker extend that
#     marker's window backward — the deterministic shape of every session's
#     opening turn (classification fires strictly after turn 1's API calls
#     have already spooled), not a rare edge case. GUARDRAIL records are
#     excluded from the window-boundary list (they are classification
#     bookkeeping, always paired with a CHAT record carrying the identical
#     task_type, written microseconds apart) so a real API call — which is
#     always chat completion work on this event path — lands on the CHAT
#     window, matching contract C-5a's stated outcome: one row per API call,
#     `--operation-type CHAT`. No split_strategies import anywhere on this
#     path (D-05 retires the split here only — the legacy path is untouched).
#   - C-7 provider resolution: the event's native `provider` field, UNLESS it
#     names a routing layer (openrouter/litellm-substring/bedrock/custom/
#     empty/none/unknown), in which case derive the model provider from
#     response_model via the same mapping hermes-report.sh's retired heredoc
#     used — a strictly better input, since response_model is the model that
#     actually served rather than one column per session.
#   - C-8: no --total-cost. The event carries no cost field; Revenium prices
#     the row server-side from model/provider/tokens.
#   - Task 3: the new api_request_id ledger is a real idempotency domain —
#     presence-checked in memory (rebuilt from disk once per run, no grep
#     spawn per record), appended only after a successful call.
#
# Soft-fail: individual event/session failures are warned and skipped; the
# script never aborts (matches tool-event-report.sh's posture).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Phase 32 Plan 03 (C-9): captured BEFORE common.sh's own
# "${REVENIUM_EVENT_METERING_MODE:-shadow}" declaration overwrites the
# variable, so resolve_switch_setting (below) can tell "operator left this
# unset" (empty) from "operator explicitly set it" — the distinction that
# makes config.json's eventMeteringMode actually reachable when the env var
# is absent.
_EVENT_METERING_MODE_ENV_RAW="${REVENIUM_EVENT_METERING_MODE:-}"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

if ! command -v revenium >/dev/null 2>&1; then
  warn "revenium CLI not found on PATH — skipping api-event metering."
  exit 0
fi
if ! command -v python3 >/dev/null 2>&1; then
  warn "python3 not found — skipping api-event metering."
  exit 0
fi
if ! revenium config show >/dev/null 2>&1; then
  warn "revenium not configured — run /revenium to set up."
  exit 0
fi
if [[ ! -d "${EVENT_SPOOL_DIR}" ]]; then
  warn "api-events spool directory does not exist — skipping api-event metering."
  exit 0
fi

touch "${EVENT_LEDGER_FILE}"

# Phase 32 Plan 03 (C-9): resolve REVENIUM_EVENT_METERING_MODE once per run —
# env (the raw pre-source value captured above) over config.json's
# eventMeteringMode over the hard "shadow" default. Any value other than the
# two literals falls back to "shadow" (the safe, ships-nothing default) and
# warns exactly once (T-32-15) — a typo must never silently start (or stop)
# billing.
_event_metering_mode_resolution=$(resolve_switch_setting "${_EVENT_METERING_MODE_ENV_RAW}" "eventMeteringMode" "shadow" "shadow" "live")
EVENT_METERING_MODE=$(printf '%s' "${_event_metering_mode_resolution}" | sed -n '1p')
_event_metering_mode_invalid=$(printf '%s' "${_event_metering_mode_resolution}" | sed -n '2p')
if [[ "${_event_metering_mode_invalid}" == "true" ]]; then
  warn "REVENIUM_EVENT_METERING_MODE/eventMeteringMode had an unrecognised value — falling back to 'shadow' (ships nothing)."
fi
info "api-event-report.sh running in EVENT_METERING_MODE=${EVENT_METERING_MODE}"

if [[ "${EVENT_METERING_MODE}" == "shadow" ]]; then
  # T-32-18: bound the shadow report the same way the metering log is
  # bounded, at the same thresholds — a fleet-wide shadow window must not
  # become a second unbounded-growth incident.
  rotate_log_if_needed "${EVENT_SHADOW_REPORT_FILE}"
  touch "${EVENT_SHADOW_REPORT_FILE}"
fi

# --- Capability probes (once per run; fail open — a negative probe simply
# omits the flag, metering exactly as an older CLI always has). ---

JOBS_CLI_CAPABLE=false
if revenium jobs --help >/dev/null 2>&1 && \
   revenium meter completion --help 2>&1 | grep -q -- '--agentic-job-id'; then
  JOBS_CLI_CAPABLE=true
fi

TRACE_TYPE_CLI_CAPABLE=false
if revenium meter completion --help 2>&1 | grep -q -- '--trace-type'; then
  TRACE_TYPE_CLI_CAPABLE=true
fi

SQUAD_CLI_CAPABLE=false
if supports_flag "meter completion" "--squad-id"; then
  SQUAD_CLI_CAPABLE=true
fi

# Task 1c: native per-record reasoning-token breakout, gated behind its own
# probe (resolved once into a shell variable via `if supports_flag; then`,
# never `VAR=$(supports_flag ...)` — the latter swallows the exit status).
REASONING_TOKENS_CLI_CAPABLE=false
if supports_flag "meter completion" "--reasoning-tokens"; then
  REASONING_TOKENS_CLI_CAPABLE=true
fi

ORG_NAME=""
if [[ -f "${CONFIG_FILE}" ]]; then
  ORG_NAME=$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}')).get('organizationName', ''))" 2>/dev/null || true)
fi

# Phase 32 (EVT-03): sweep THIS profile's spool directory only.
#
# An earlier revision also swept every OTHER profile's api-events directory,
# intending to protect a multiplexed gateway from stranding records. Measured
# on the live fleet, that produced a cross-profile double-ship: every profile's
# run read every other profile's spool files, while each per-session lookup —
# the state.db env map, the legacy HERMES: ledger that D-09 partitions on, and
# the api_request_id event ledger that provides idempotency — resolved against
# the RUNNING profile rather than the OWNING one.
#
# Observed: one marketing-owned session appeared in all ten profiles' shadow
# reports. Its owner found 2 legacy ledger lines and correctly skipped it;
# every non-owner found 0, concluded the session was unowned, and in live mode
# would have shipped it — each appending to its OWN event ledger, so nothing
# deduplicated them. Up to 9x duplicate billing per session. The
# never-double-report invariant held across ticks and failed across profiles,
# an axis no test exercised.
#
# The sweep was also unnecessary. The plugin's own `_paths_for_session` already
# routes each spool WRITE into the owning profile's directory (confirmed live:
# the marketing session's spool file was in marketing's directory), and the
# fleet runner already invokes this script once per profile. So every spool
# file is read by exactly its owner, nothing is stranded, and D-09's ledger
# check is correct again because the ledger it consults always belongs to the
# session it is asked about.
_spool_dirs=("${EVENT_SPOOL_DIR}")

# C-6: the .ready directory that owns a resolved per-session markers
# directory — mirrors hermes-report.sh's own belt: when the resolved
# directory equals the process-level MARKERS_DIR, use the (possibly
# independently overridden) MARKERS_READY_DIR; otherwise the resolved
# directory's own .ready subdirectory. Pure string function — no python3
# spawn needed.
_ready_dir_for_markers_dir() {
  local mdir="$1"
  if [[ "${mdir}" == "${MARKERS_DIR}" ]]; then
    printf '%s\n' "${MARKERS_READY_DIR}"
  else
    printf '%s\n' "${mdir}/.ready"
  fi
}

# Phase 32 Plan 03 (C-10): append ONE shadow-comparison row for one session
# to EVENT_SHADOW_REPORT_FILE (and to the run-scoped accumulator file used to
# build the end-of-run per-platform aggregate). Called once per session, at
# EVERY exit from the per-session flow — a session that reaches no exit at
# all is a session missing from the platform aggregate, which would read as
# "the hook never fired on that platform" and is the one failure mode this
# report cannot afford (constraint 5 is answered from those buckets).
#
# Two INDEPENDENT facts are recorded, deliberately in separate fields,
# because an earlier revision conflated them in `gate` and lost one:
#
#   gate          — what stopped this session on THIS tick, or "shipped".
#                   Transient: "held" resolves itself once the marker lands.
#                   One of: shipped | held | legacy_skip | no_valid_events.
#   legacy_owned  — whether the legacy HERMES: ledger owns this session.
#                   Permanent, and true regardless of which gate won, so
#                   ownership survives a tick where some other gate fired.
#
# Event-side fields are zeroed only where enrichment genuinely could not run
# (held: no marker yet; no_valid_events: nothing survived validation). A
# legacy-owned session in shadow mode DOES enrich — see the D-09 gate's own
# comment for why that is both necessary and safe.
#
# Relies on ${_env_map_file} (the once-per-run state.db map: sid, source,
# model, billing_provider, input/output/cache_read/cache_write tokens, cost —
# built once in main(), below) and ${_shadow_run_file} (this run's
# accumulator, also a main()-local) via bash's normal dynamic scoping — both
# are `local` to main() but visible here because this function is only ever
# CALLED from within main()'s own execution.
#
# Args: sid, gate ("shipped"|"held"|"legacy_skip"), platform, rows_text
# Args: sid, gate, platform, rows_text (pipe-delimited enriched event rows
# exactly as built for CLI argv construction — empty only where enrichment
# could not run), legacy_owned ("true"|"false", defaults false).
_emit_shadow_row() {
  local s_sid="$1" s_gate="$2" s_platform="$3" s_rows="$4"
  local s_legacy_owned="${5:-false}"

  local db_row model_legacy billing_provider_legacy
  local db_input db_output db_cache_read db_cache_write cost_legacy
  db_row=""
  if [[ -n "${_env_map_file:-}" && -f "${_env_map_file}" ]]; then
    db_row=$(awk -F"${_MAP_SEP:-$'\x1f'}" -v s="${s_sid}" '$1==s{print; exit}' "${_env_map_file}" 2>/dev/null)
  fi
  # 0x1F (not tab) is the field separator here — see _MAP_SEP's comment at
  # its declaration in main(): unlike a tab, it is not an IFS-whitespace
  # character, so bash's `read` does not collapse an empty billing_provider
  # field into the delimiter run and shift every field after it.
  IFS=$'\x1f' read -r _ _ model_legacy billing_provider_legacy \
    db_input db_output db_cache_read db_cache_write cost_legacy <<< "${db_row}"
  db_input="${db_input:-0}"
  db_output="${db_output:-0}"
  db_cache_read="${db_cache_read:-0}"
  db_cache_write="${db_cache_write:-0}"

  local legacy_ledger_lines legacy_last_total_tokens
  legacy_ledger_lines=$(grep -c "^HERMES:${s_sid}:" "${LEDGER_FILE}" 2>/dev/null || echo 0)
  legacy_last_total_tokens=$(grep "^HERMES:${s_sid}:" "${LEDGER_FILE}" 2>/dev/null | tail -1 | cut -d: -f3)

  SHADOW_SID="${s_sid}" SHADOW_GATE="${s_gate}" SHADOW_PLATFORM="${s_platform}" \
  SHADOW_LEGACY_OWNED="${s_legacy_owned}" \
  SHADOW_ROWS="${s_rows}" \
  SHADOW_DB_INPUT="${db_input}" SHADOW_DB_OUTPUT="${db_output}" \
  SHADOW_DB_CACHE_READ="${db_cache_read}" SHADOW_DB_CACHE_WRITE="${db_cache_write}" \
  SHADOW_MODEL_LEGACY="${model_legacy}" SHADOW_BILLING_PROVIDER_LEGACY="${billing_provider_legacy}" \
  SHADOW_COST_LEGACY="${cost_legacy}" \
  SHADOW_LEGACY_LEDGER_LINES="${legacy_ledger_lines}" \
  SHADOW_LEGACY_LAST_TOTAL="${legacy_last_total_tokens}" \
  SHADOW_REPORT_FILE="${EVENT_SHADOW_REPORT_FILE}" \
  SHADOW_RUN_FILE="${_shadow_run_file:-}" \
  python3 - <<'PY' 2>/dev/null || true
import json
import os
from datetime import datetime, timezone

sid = os.environ.get('SHADOW_SID', '')
gate = os.environ.get('SHADOW_GATE', 'held')
# Independent of `gate`: ownership is permanent, gate is per-tick.
legacy_owned = (os.environ.get('SHADOW_LEGACY_OWNED', 'false') == 'true')
platform = os.environ.get('SHADOW_PLATFORM', '') or ''
rows_text = os.environ.get('SHADOW_ROWS', '')
report_file = os.environ.get('SHADOW_REPORT_FILE', '')
run_file = os.environ.get('SHADOW_RUN_FILE', '')


def _int(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


db_input = _int(os.environ.get('SHADOW_DB_INPUT'))
db_output = _int(os.environ.get('SHADOW_DB_OUTPUT'))
db_cache_read = _int(os.environ.get('SHADOW_DB_CACHE_READ'))
db_cache_write = _int(os.environ.get('SHADOW_DB_CACHE_WRITE'))
db_total = db_input + db_output + db_cache_read + db_cache_write

model_legacy = os.environ.get('SHADOW_MODEL_LEGACY', '') or ''
billing_provider_legacy = os.environ.get('SHADOW_BILLING_PROVIDER_LEGACY', '') or ''
cost_legacy_raw = os.environ.get('SHADOW_COST_LEGACY', '') or ''

legacy_ledger_lines = _int(os.environ.get('SHADOW_LEGACY_LEDGER_LINES'))
legacy_last_total_raw = os.environ.get('SHADOW_LEGACY_LAST_TOTAL', '') or ''
try:
    legacy_last_total_tokens = int(float(legacy_last_total_raw)) if legacy_last_total_raw else None
except ValueError:
    legacy_last_total_tokens = None


def _infer_provider(model_lc):
    # Mirrors the enrichment heredoc's own _infer_provider (and the retired
    # hermes-report.sh heredoc it was ported from) verbatim — this IS the
    # comparison, so the two must use identical logic on the LEGACY side too.
    if 'claude' in model_lc or 'anthropic' in model_lc:
        return 'anthropic'
    if 'gpt' in model_lc or 'o1' in model_lc or 'o3' in model_lc:
        return 'openai'
    if 'gemini' in model_lc:
        return 'google'
    if 'grok' in model_lc or 'x-ai' in model_lc:
        return 'xai'
    if 'deepseek' in model_lc:
        return 'deepseek'
    if 'llama' in model_lc or 'mistral' in model_lc:
        return 'meta'
    return 'unknown'


def _legacy_provider(model, billing):
    # C-10: what the LEGACY path's provider heredoc would have resolved for
    # this session's own state.db model/billing_provider columns.
    model_lc = (model or '').lower()
    billing_lc = (billing or '').lower()
    if billing_lc and billing_lc not in ('', 'none', 'unknown'):
        if billing_lc == 'openrouter' or 'litellm' in billing_lc:
            inferred = _infer_provider(model_lc)
            return inferred if inferred != 'unknown' else billing_lc
        if billing_lc == 'bedrock':
            return 'anthropic' if 'claude' in model_lc else 'aws'
        return billing_lc
    return _infer_provider(model_lc)


provider_legacy_would_be = _legacy_provider(model_legacy, billing_provider_legacy)

cost_present_legacy = False
try:
    cost_present_legacy = float(cost_legacy_raw) != 0
except (TypeError, ValueError):
    cost_present_legacy = False

event_rows = 0
event_input = event_output = event_cache_read = event_cache_write = 0
event_reasoning = event_total = 0
task_types = {}
operation_types = {}
provider_event = ''
models_seen = set()
transaction_id_sample = ''

for line in rows_text.splitlines():
    line = line.rstrip('\n')
    if not line:
        continue
    fields = line.split('|')
    if len(fields) != 19:
        continue
    (_sid_f, arid_f, response_model_f, _provider_raw_f, provider_resolved_f,
     input_f, output_f, cache_read_f, cache_write_f, reasoning_f, total_f,
     _request_time_f, _response_time_f, _duration_f, _stop_reason_f,
     task_type_f, operation_type_f, _trace_id_f, _agentic_job_id_f) = fields
    event_rows += 1
    event_input += _int(input_f)
    event_output += _int(output_f)
    event_cache_read += _int(cache_read_f)
    event_cache_write += _int(cache_write_f)
    event_reasoning += _int(reasoning_f)
    event_total += _int(total_f)
    task_types[task_type_f] = task_types.get(task_type_f, 0) + 1
    operation_types[operation_type_f] = operation_types.get(operation_type_f, 0) + 1
    models_seen.add(response_model_f)
    if not provider_event:
        provider_event = provider_resolved_f
    if not transaction_id_sample:
        transaction_id_sample = f'event:{arid_f}'

event_usage_total = event_input + event_output + event_cache_read + event_cache_write
coverage_ratio = None
if db_total > 0:
    coverage_ratio = round(event_usage_total / db_total, 6)

row = {
    'sid': sid,
    'platform': platform,
    'gate': gate,
    'legacy_owned': legacy_owned,
    'event_rows': event_rows,
    'event_input': event_input,
    'event_output': event_output,
    'event_cache_read': event_cache_read,
    'event_cache_write': event_cache_write,
    'event_reasoning': event_reasoning,
    'event_total': event_total,
    'db_input': db_input,
    'db_output': db_output,
    'db_cache_read': db_cache_read,
    'db_cache_write': db_cache_write,
    'db_total': db_total,
    'coverage_ratio': coverage_ratio,
    'legacy_ledger_lines': legacy_ledger_lines,
    'legacy_last_total_tokens': legacy_last_total_tokens,
    'task_types': task_types,
    'operation_types': operation_types,
    'provider_event': provider_event,
    'provider_legacy_would_be': provider_legacy_would_be,
    'model_event_distinct': len(models_seen),
    'model_legacy': model_legacy,
    'cost_present_event': False,
    'cost_present_legacy': cost_present_legacy,
    'transaction_id_sample': transaction_id_sample,
    'ts': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
}

line_out = json.dumps(row, separators=(',', ':'), sort_keys=True) + '\n'
if report_file:
    try:
        with open(report_file, 'a', encoding='utf-8') as f:
            f.write(line_out)
    except OSError:
        pass
if run_file:
    try:
        with open(run_file, 'a', encoding='utf-8') as f:
            f.write(line_out)
    except OSError:
        pass
PY
}

main() {
  info "=== API Event Reporter starting ==="

  local reported_count=0
  local held_sessions=0
  local legacy_skipped_sessions=0
  local dup_skipped_events=0

  local now
  now=$(date +%s)

  # Task 3a: build the new ledger's api_request_id presence lookup ONCE, in
  # memory, rather than a grep spawn per record — this path sees strictly
  # more records than the reporter's per-session spawns, which were already
  # the measured dominant fleet cost (quick-task 260814-e7c). Rebuilt from
  # the file at the start of this run; appended to in memory as new lines
  # are written below, so two records with the same id inside one run also
  # deduplicate (not just across runs).
  local _seen_arids=$'\n'
  if [[ -s "${EVENT_LEDGER_FILE}" ]]; then
    while IFS= read -r _arid; do
      [[ -z "${_arid}" ]] && continue
      _seen_arids="${_seen_arids}${_arid}"$'\n'
    done < <(
      EVENT_LEDGER_FILE="${EVENT_LEDGER_FILE}" python3 - <<'PY' 2>/dev/null
import os
p = os.environ.get("EVENT_LEDGER_FILE", "")
try:
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.startswith("API:"):
                continue
            rest = line[4:]
            idx = rest.find("|")
            if idx == -1:
                continue
            print(rest[:idx])
except OSError:
    pass
PY
    )
  fi

  # Enumerate every candidate spool file across every swept directory.
  local -a event_files=()
  local spool_dir event_file
  for spool_dir in "${_spool_dirs[@]}"; do
    for event_file in "${spool_dir}"/*.jsonl; do
      [[ -f "${event_file}" ]] || continue
      event_files+=("${event_file}")
    done
  done

  if [[ "${#event_files[@]}" -eq 0 ]]; then
    info "=== Done. No spool files found. ==="
    return
  fi

  # C-6/attribution: read state.db's sessions columns ONCE for the whole run
  # (not per session, and not one extra query per shadow row — C-10's own
  # requirement) for the --environment flag AND (Plan 03) the shadow
  # readout's db_* fields and legacy-provider comparison. Uses Python's
  # stdlib sqlite3 module directly (no shelling to the sqlite3 CLI, so this
  # script gains no new external-tool precondition), opened read-only via a
  # URI so a missing state.db is never created as a side effect — this is
  # the cron-side shipper, not the in-session hook D-01 restricts.
  # Field separator for _env_map_file: 0x1F (unit separator), NOT a tab.
  # bash's `IFS=$'\t' read` collapses RUNS of IFS-whitespace characters
  # (tab included, regardless of what else is in IFS) into a single
  # delimiter, silently dropping empty fields (e.g. an empty
  # billing_provider between two tabs) and shifting every field after it —
  # measured directly while building the Task 1 shadow-row parser. 0x1F is
  # not a whitespace character, so bash treats every occurrence as a
  # distinct delimiter and empty fields round-trip correctly.
  local _MAP_SEP
  _MAP_SEP=$'\x1f'
  local _env_map_file
  _env_map_file=$(mktemp 2>/dev/null || echo "/tmp/revenium-api-event-env-map.$$")
  STATE_DB="${STATE_DB}" ENV_MAP_FILE="${_env_map_file}" python3 - <<'PY' 2>/dev/null || true
import os
import sqlite3

db = os.environ.get("STATE_DB", "")
out = os.environ.get("ENV_MAP_FILE", "")
SEP = "\x1f"
if db and out and os.path.isfile(db):
    try:
        uri = f"file:{db}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            cur = conn.execute(
                "SELECT id, COALESCE(source, ''), COALESCE(model, ''), "
                "COALESCE(billing_provider, ''), COALESCE(input_tokens, 0), "
                "COALESCE(output_tokens, 0), COALESCE(cache_read_tokens, 0), "
                "COALESCE(cache_write_tokens, 0), COALESCE(estimated_cost_usd, '') "
                "FROM sessions"
            )
            with open(out, "w", encoding="utf-8") as f:
                for sid, source, model, billing_provider, inp, outp, cread, cwrite, cost in cur:
                    sid = str(sid) if sid is not None else ""
                    source = str(source) if source is not None else ""
                    model = str(model) if model is not None else ""
                    billing_provider = str(billing_provider) if billing_provider is not None else ""
                    cost = str(cost) if cost is not None else ""
                    if not sid:
                        continue
                    for bad in ("\t", "\n", "\r", SEP):
                        sid = sid.replace(bad, "_")
                        source = source.replace(bad, "_")
                        model = model.replace(bad, "_")
                        billing_provider = billing_provider.replace(bad, "_")
                        cost = cost.replace(bad, "_")
                    f.write(
                        SEP.join([sid, source, model, billing_provider,
                                  str(inp), str(outp), str(cread), str(cwrite), cost])
                        + "\n"
                    )
    except Exception:
        pass
PY

  # Phase 32 Plan 03 (C-10): this run's shadow-row accumulator, read back
  # once at the end of the loop below to build the per-platform aggregate.
  # Only created (and only ever written to) in shadow mode.
  local _shadow_run_file=""
  if [[ "${EVENT_METERING_MODE}" == "shadow" ]]; then
    _shadow_run_file=$(mktemp 2>/dev/null || echo "/tmp/revenium-api-event-shadow-run.$$")
  fi

  for event_file in "${event_files[@]}"; do
    # --- Peek: one pass to learn this file's owning sid, event count, and
    # oldest event timestamp — cheap enough to do once per session file and
    # needed before any directory resolution below (which is keyed on sid).
    local peek
    peek=$(EVENT_FILE="${event_file}" python3 - <<'PY' 2>/dev/null
import json
import os

event_file = os.environ.get("EVENT_FILE", "")
sid = ""
count = 0
min_ts = None
platform = ""
try:
    with open(event_file, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or len(line) > 4096:
                continue
            try:
                r = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(r, dict):
                continue
            r_sid = r.get("sid") or ""
            arid = r.get("api_request_id") or ""
            if not r_sid or not arid:
                continue
            if not sid:
                sid = r_sid
            count += 1
            # Phase 32 Plan 03 (C-10): first record's platform value — needed
            # even for a session that turns out held/legacy-skipped, so the
            # shadow readout can still bucket it by platform.
            if not platform:
                p = r.get("platform") or ""
                for bad in ("\n", "\r"):
                    p = p.replace(bad, "_")
                platform = p
            try:
                ts = float(r.get("ts"))
            except (TypeError, ValueError):
                continue
            if min_ts is None or ts < min_ts:
                min_ts = ts
except OSError:
    pass
print(f"SID={sid}")
print(f"COUNT={count}")
print(f"MIN_TS={min_ts if min_ts is not None else ''}")
print(f"PLATFORM={platform}")
PY
    )

    local sid count min_ts platform
    sid=$(echo "${peek}" | sed -n 's/^SID=//p' | head -1)
    count=$(echo "${peek}" | sed -n 's/^COUNT=//p' | head -1)
    min_ts=$(echo "${peek}" | sed -n 's/^MIN_TS=//p' | head -1)
    platform=$(echo "${peek}" | sed -n 's/^PLATFORM=//p' | head -1)

    [[ -z "${sid}" ]] && continue
    [[ -z "${count}" || "${count}" == "0" ]] && continue

    # Per-session shadow-row state, reset every iteration. `session_gate`
    # is what stops this session on THIS tick; `session_legacy_owned` is a
    # permanent property recorded independently so it cannot be lost when a
    # later gate overwrites the gate label.
    local session_gate="shipped"
    local session_legacy_owned=false

    # D-09 partition: session-level skip, checked BEFORE the settle gate —
    # this is the whole of the no-overlap guarantee between the two paths.
    #
    # D-09 is a SHIPPING guard, and shadow mode does not ship. In live mode
    # the skip is absolute: the legacy path owns this session, so returning
    # here is what makes the two paths partition disjointly. In shadow mode
    # returning here would destroy the stage's entire purpose. Legacy is
    # still actively billing during shadow, so EVERY session lands in the
    # HERMES: ledger within a tick; skipping them all leaves every event-side
    # field zero and coverage_ratio pinned at 0.0000 forever, and no
    # per-field equivalence can ever be measured (C-10's own requirement,
    # and plan 32-05's stated deliverable).
    #
    # So in shadow we record the gate and fall THROUGH to enrichment. This is
    # safe by construction rather than by care: the mode check immediately
    # before the CLI invocation below already suppresses both the call and
    # the ledger append, so a fallen-through session cannot ship or be
    # recorded no matter what it computes. Its row is tagged "legacy_skip",
    # which still tells the operator it would not have shipped in live mode.
    if grep -q "^HERMES:${sid}:" "${LEDGER_FILE}" 2>/dev/null; then
      ((legacy_skipped_sessions++)) || true
      if [[ "${EVENT_METERING_MODE}" == "shadow" ]]; then
        # Ownership is permanent and is recorded in its own field, so it
        # survives a tick on which some other gate (held, no_valid_events)
        # is the thing that actually stopped this session.
        session_legacy_owned=true
        session_gate="legacy_skip"
        info "shadow: ${sid} is legacy-owned (D-09) — computing would-be rows for comparison, shipping nothing"
      else
        info "skipping ${sid} — already owned by the legacy HERMES: ledger (D-09 partition)"
        continue
      fi
    fi

    local session_markers_dir
    session_markers_dir="$(resolve_markers_dir "${sid}")"
    [[ -z "${session_markers_dir}" ]] && session_markers_dir="${MARKERS_DIR}"

    local ready_dir
    ready_dir="$(_ready_dir_for_markers_dir "${session_markers_dir}")"

    local has_sentinel=false
    [[ -e "${ready_dir}/${sid}" ]] && has_sentinel=true

    local join_mode
    if [[ "${has_sentinel}" == "true" ]]; then
      join_mode="join"
    else
      local age=0
      if [[ -n "${min_ts}" ]]; then
        age=$(NOW="${now}" MIN_TS="${min_ts}" python3 -c "
import os
try:
    now = float(os.environ.get('NOW', '0'))
    min_ts = float(os.environ.get('MIN_TS', '0'))
    print(max(0, int(now - min_ts)))
except Exception:
    print(0)
" 2>/dev/null || echo 0)
      fi
      if [[ "${age}" -lt "${REVENIUM_CRON_SETTLE_SECONDS}" ]]; then
        # T-32-10: logged ONCE per session per tick, never per record — the
        # measured precedent (9M lines/27 days from an ungated per-tick warn)
        # is exactly why this line lives here, outside any per-record loop.
        info "holding ${sid} — awaiting plugin sentinel (age=${age}s < settle=${REVENIUM_CRON_SETTLE_SECONDS}s, events=${count})"
        ((held_sessions++)) || true
        if [[ "${EVENT_METERING_MODE}" == "shadow" ]]; then
          # "held" is genuinely what stopped it this tick and enrichment
          # truly cannot run without a marker, so the event fields ARE
          # legitimately zero here — but ownership rides along separately.
          _emit_shadow_row "${sid}" "held" "${platform}" "" "${session_legacy_owned}"
        fi
        continue
      fi
      # C-5b / C-6 point 3: aged out with no sentinel — ship unclassified,
      # exactly the zero-marker fallback backward-compat guarantee. Do NOT
      # read the markers file in this mode even if one happens to exist.
      join_mode="unclassified"
    fi

    # Attribution flags resolved ONCE per session (not per event), mirroring
    # hermes-report.sh's own per-session-loop cost discipline.
    local root_sid
    root_sid="$(get_root_session_id "${sid}")"
    [[ -z "${root_sid}" ]] && root_sid="${sid}"

    local root_trace_type=""
    if [[ "${TRACE_TYPE_CLI_CAPABLE}" == "true" ]]; then
      local root_markers_dir
      if [[ "${root_sid}" == "${sid}" ]]; then
        root_markers_dir="${session_markers_dir}"
      else
        root_markers_dir="$(resolve_markers_dir "${root_sid}")"
        [[ -z "${root_markers_dir}" ]] && root_markers_dir="${MARKERS_DIR}"
      fi
      root_trace_type=$(
        ROOT_SID="${root_sid}" MARKERS_DIR="${root_markers_dir}" python3 - <<'PY' 2>/dev/null
import json, os
from pathlib import Path
root_sid = os.environ.get('ROOT_SID', '')
markers_dir = os.environ.get('MARKERS_DIR', '')
latest_type = ""
if root_sid and markers_dir:
    marker_path = Path(markers_dir) / f"{root_sid}.jsonl"
    if marker_path.exists():
        try:
            with open(marker_path, 'r', encoding='utf-8') as fh:
                for line in fh:
                    line = line.rstrip('\n')
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if not isinstance(rec, dict):
                        continue
                    if rec.get('kind') == 'job':
                        jt = rec.get('job_type')
                        if isinstance(jt, str) and jt:
                            for bad in ('\n', '\r'):
                                jt = jt.replace(bad, '_')
                            latest_type = jt
        except OSError:
            pass
print(latest_type)
PY
      )
      root_trace_type="${root_trace_type//[^A-Za-z0-9_-]/_}"
      root_trace_type="${root_trace_type:0:128}"
      [[ -z "${root_trace_type}" ]] && root_trace_type="uncategorized"
    fi

    local source_env=""
    if [[ -f "${_env_map_file}" ]]; then
      source_env=$(awk -F"${_MAP_SEP}" -v s="${sid}" '$1==s{print $2; exit}' "${_env_map_file}" 2>/dev/null)
    fi

    local markers_file="${session_markers_dir}/${sid}.jsonl"

    # --- Enrich: read the event file (and, in join mode, the markers file)
    # once each, join per event, and emit one pipe-delimited row per
    # shippable event. Contract C-4/T-32-08: pipe/newline/CR stripped and
    # length-capped on every field before it crosses the row boundary.
    local rows
    rows=$(
      EVENT_FILE="${event_file}" \
      MARKERS_FILE="${markers_file}" \
      JOIN_MODE="${join_mode}" \
      python3 - <<'PY' 2>/dev/null
import bisect
import json
import os
from datetime import datetime, timezone

event_file = os.environ.get("EVENT_FILE", "")
markers_file = os.environ.get("MARKERS_FILE", "")
join_mode = os.environ.get("JOIN_MODE", "unclassified")


def _iso(ts):
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def _clean(s, cap=128):
    s = s or ""
    for bad in ("|", "\n", "\r"):
        s = s.replace(bad, "_")
    return s[:cap]


def _infer_provider(model_lc):
    if "claude" in model_lc or "anthropic" in model_lc:
        return "anthropic"
    if "gpt" in model_lc or "o1" in model_lc or "o3" in model_lc:
        return "openai"
    if "gemini" in model_lc:
        return "google"
    if "grok" in model_lc or "x-ai" in model_lc:
        return "xai"
    if "deepseek" in model_lc:
        return "deepseek"
    if "llama" in model_lc or "mistral" in model_lc:
        return "meta"
    return "unknown"


_ROUTING_LAYER_NAMES = {"openrouter", "bedrock", "custom", "none", "unknown", ""}


def _resolve_provider(provider_raw, response_model):
    # Contract C-7: verbatim, unless the field names a ROUTING layer rather
    # than a model provider — in which case derive the model provider from
    # response_model, the same mapping the retired hermes-report.sh heredoc
    # used, with a strictly better input (the model that actually served).
    p_lc = (provider_raw or "").strip().lower()
    is_routing = p_lc in _ROUTING_LAYER_NAMES or "litellm" in p_lc
    if not is_routing:
        return provider_raw or ""
    return _infer_provider((response_model or "").lower())


_STOP_REASON_MAP = {
    "stop": "END", "end_turn": "END",
    "tool_calls": "TOOL_CALL", "tool_use": "TOOL_CALL",
    "length": "TOKEN_LIMIT", "max_tokens": "TOKEN_LIMIT",
    "content_filter": "CONTENT_FILTER",
}


def _stop_reason(finish_reason):
    # Closed allowlist; anything unrecognised/empty/absent maps to END (the
    # constant the legacy path always shipped) so an unexpected provider
    # value can never strand a record via CLI rejection.
    return _STOP_REASON_MAP.get((finish_reason or "").strip().lower(), "END")


# --- Load markers (task markers only) for the temporal join (C-5). ---
markers = []
if join_mode == "join" and markers_file and os.path.isfile(markers_file):
    REQUIRED = ("muid", "ts", "sid", "task_type", "operation_type")
    try:
        with open(markers_file, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line or len(line) > 4096:
                    continue
                try:
                    m = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(m, dict):
                    continue
                if m.get("kind") is not None:
                    continue
                if not all(k in m for k in REQUIRED):
                    continue
                try:
                    m["ts"] = float(m["ts"])
                except (TypeError, ValueError):
                    continue
                markers.append(m)
    except OSError:
        pass
markers.sort(key=lambda m: m["ts"])

# Contract C-5a: GUARDRAIL records are classification bookkeeping, always
# paired microseconds apart with a CHAT record carrying the IDENTICAL
# task_type. Excluding them from the window-BOUNDARY list (they are still
# read and validated above) means a real API call — which is always chat
# completion work on this event path — lands on the CHAT window, including
# events preceding the pair entirely (D-14's backward extension then reaches
# the CHAT window rather than GUARDRAIL's degenerate one). Falls back to the
# unfiltered list only if that would leave nothing to attribute to.
window_markers = [m for m in markers if m.get("operation_type") != "GUARDRAIL"]
if not window_markers:
    window_markers = markers
marker_ts = [m["ts"] for m in window_markers]


def _attribution_for(ts):
    if not window_markers:
        return "unclassified", "CHAT", "", ""
    idx = bisect.bisect_right(marker_ts, ts) - 1
    if idx < 0:
        idx = 0
    m = window_markers[idx]
    task_type = _clean(m.get("task_type") or "unclassified", 128)
    operation_type = _clean(m.get("operation_type") or "CHAT", 32)
    trace_id = _clean(m.get("trace_id") or "", 256)
    agentic_job_id = _clean(m.get("agentic_job_id") or "", 128)
    return task_type, operation_type, trace_id, agentic_job_id


try:
    with open(event_file, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or len(line) > 4096:
                continue
            try:
                r = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(r, dict):
                continue
            sid = r.get("sid") or ""
            arid = r.get("api_request_id") or ""
            if not sid or not arid:
                continue
            model = r.get("model") or ""
            response_model = r.get("response_model") or model
            provider_raw = r.get("provider") or ""
            ts = r.get("ts")
            ended_at = r.get("ended_at")
            try:
                duration_ms = int(r.get("duration_ms") or 0)
            except (TypeError, ValueError):
                duration_ms = 0
            try:
                input_tokens = int(r.get("input_tokens") or 0)
                output_tokens = int(r.get("output_tokens") or 0)
                cache_read_tokens = int(r.get("cache_read_tokens") or 0)
                cache_write_tokens = int(r.get("cache_write_tokens") or 0)
                reasoning_tokens = int(r.get("reasoning_tokens") or 0)
                total_tokens = int(r.get("total_tokens") or 0)
            except (TypeError, ValueError):
                continue

            try:
                event_ts = float(ts)
            except (TypeError, ValueError):
                continue

            request_time = _iso(ts)
            response_time = _iso(ended_at)
            if not request_time or not response_time:
                continue

            if join_mode == "join":
                task_type, operation_type, trace_id, agentic_job_id = _attribution_for(event_ts)
            else:
                task_type, operation_type, trace_id, agentic_job_id = "unclassified", "CHAT", "", ""

            provider_resolved = _resolve_provider(provider_raw, response_model)
            stop_reason = _stop_reason(r.get("finish_reason"))

            row = [
                _clean(sid, 256), _clean(arid, 256), _clean(response_model, 256),
                _clean(provider_raw, 128), _clean(provider_resolved, 128),
                str(input_tokens), str(output_tokens), str(cache_read_tokens),
                str(cache_write_tokens), str(reasoning_tokens), str(total_tokens),
                request_time, response_time, str(duration_ms), stop_reason,
                task_type, operation_type, trace_id, agentic_job_id,
            ]
            print("|".join(row))
except OSError:
    pass
PY
    )

    if [[ -z "${rows}" ]]; then
      # Every exit must emit. A session that vanishes here is missing from
      # the platform aggregate, and an empty gateway bucket would read as
      # "post_api_request never fires on gateway" — a false negative on the
      # exact question the shadow stage exists to answer (constraint 5).
      if [[ "${EVENT_METERING_MODE}" == "shadow" ]]; then
        _emit_shadow_row "${sid}" "no_valid_events" "${platform}" "" "${session_legacy_owned}"
      fi
      continue
    fi

    local sid_r arid_r model_r provider_raw_r provider_resolved_r
    local input_r output_r cache_read_r cache_write_r reasoning_r total_r
    local request_time_r response_time_r duration_r stop_reason_r
    local task_type_r operation_type_r trace_id_r agentic_job_id_r

    while IFS='|' read -r sid_r arid_r model_r provider_raw_r provider_resolved_r \
      input_r output_r cache_read_r cache_write_r reasoning_r total_r \
      request_time_r response_time_r duration_r stop_reason_r \
      task_type_r operation_type_r trace_id_r agentic_job_id_r; do
      [[ -z "${sid_r}" || -z "${arid_r}" ]] && continue

      # Task 3a: in-memory presence check — no subprocess per record.
      case "${_seen_arids}" in
        *$'\n'"${arid_r}"$'\n'*)
          ((dup_skipped_events++)) || true
          continue
          ;;
      esac

      local cmd=(
        revenium meter completion
        --model "${model_r}"
        --provider "${provider_resolved_r}"
        --input-tokens "${input_r}"
        --output-tokens "${output_r}"
        --cache-read-tokens "${cache_read_r}"
        --cache-creation-tokens "${cache_write_r}"
        --total-tokens "${total_r}"
        --stop-reason "${stop_reason_r}"
        --request-time "${request_time_r}"
        --completion-start-time "${request_time_r}"
        --response-time "${response_time_r}"
        --request-duration "${duration_r}"
        --agent "${REVENIUM_AGENT_NAME}"
        --transaction-id "event:${arid_r}"
        --trace-id "${trace_id_r:-${root_sid}}"
        --is-streamed
        --quiet
        --task-type "${task_type_r}"
        --operation-type "${operation_type_r}"
      )

      # Task 1c: native per-record reasoning breakout, capability-gated.
      if [[ "${REASONING_TOKENS_CLI_CAPABLE}" == "true" && "${reasoning_r}" -gt 0 ]]; then
        cmd+=(--reasoning-tokens "${reasoning_r}")
      fi
      # C-7: --model-source mirrors the legacy path's use of billing_provider
      # as the routing-info slot — the event's RAW (unresolved) provider.
      if [[ -n "${provider_raw_r}" ]]; then
        cmd+=(--model-source "${provider_raw_r}")
      fi
      # C-8: --total-cost is deliberately never appended on this path — the
      # event carries no cost field; Revenium prices the row server-side.
      if [[ -n "${ORG_NAME}" ]]; then
        cmd+=(--organization-name "${ORG_NAME}")
      fi
      if [[ -n "${source_env}" ]]; then
        cmd+=(--environment "${source_env}")
      fi
      if [[ "${TRACE_TYPE_CLI_CAPABLE}" == "true" ]]; then
        cmd+=(--trace-type "${root_trace_type:-uncategorized}")
      fi
      if [[ "${JOBS_CLI_CAPABLE}" == "true" && -n "${agentic_job_id_r}" ]]; then
        cmd+=(--agentic-job-id "${agentic_job_id_r}")
      fi
      if [[ "${SQUAD_CLI_CAPABLE}" == "true" ]]; then
        cmd+=(--squad-id "${root_sid}")
        cmd+=(--squad-name "${REVENIUM_SQUAD_NAME:-${REVENIUM_AGENT_NAME}}")
        if [[ "${root_sid}" == "${sid_r}" ]]; then
          cmd+=(--squad-role "root")
        else
          cmd+=(--squad-role "subagent")
        fi
      fi

      if [[ "${EVENT_METERING_MODE}" == "shadow" ]]; then
        # C-10: argv is fully constructed above (the `cmd` array), but shadow
        # mode never invokes it and never writes a ledger line — the
        # per-session aggregate row appended after this while loop (below)
        # is shadow mode's only output.
        continue
      fi

      local cmd_output cmd_exit
      cmd_output=$("${cmd[@]}" 2>&1) && cmd_exit=0 || cmd_exit=$?

      if [[ "${cmd_exit}" -eq 0 ]]; then
        # Task 3b: ledger line is the LAST statement of the success branch
        # only. A failed call must never produce a ledger entry — it would
        # permanently suppress retry.
        local now_ts
        now_ts=$(python3 -c "import time; print(f'{time.time():.3f}')" 2>/dev/null || date +%s)
        echo "API:${arid_r}|${sid_r}|${now_ts}" >> "${EVENT_LEDGER_FILE}"
        _seen_arids="${_seen_arids}${arid_r}"$'\n'
        ((reported_count++)) || true
        info "Reported: sid=${sid_r} api_request_id=${arid_r} model=${model_r} task_type=${task_type_r} operation_type=${operation_type_r}"
      else
        warn "Failed: sid=${sid_r} api_request_id=${arid_r} exit=${cmd_exit} output=${cmd_output}"
      fi
    done <<< "${rows}"

    if [[ "${EVENT_METERING_MODE}" == "shadow" ]]; then
      # ${session_gate} is "shipped" unless a gate above moved it. A
      # legacy-owned session reaches here in shadow mode carrying fully
      # enriched rows and the gate that would have stopped it live.
      _emit_shadow_row "${sid}" "${session_gate}" "${platform}" "${rows}" "${session_legacy_owned}"
    fi
  done

  if [[ "${EVENT_METERING_MODE}" == "shadow" && -n "${_shadow_run_file}" && -s "${_shadow_run_file}" ]]; then
    # C-10: one info line per distinct platform value (plus one for sessions
    # whose platform was empty) — the operator reads this BEFORE authorising
    # a canary, so it must be legible without post-processing the JSONL file.
    local _platform_agg_output
    _platform_agg_output=$(SHADOW_RUN_FILE="${_shadow_run_file}" python3 - <<'PY' 2>/dev/null
import json
import os
from collections import defaultdict

run_file = os.environ.get('SHADOW_RUN_FILE', '')
buckets = defaultdict(lambda: {'sessions': 0, 'event_rows': 0, 'db_total': 0, 'ratio_sum': 0.0, 'ratio_count': 0})

try:
    with open(run_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            platform = row.get('platform') or ''
            b = buckets[platform]
            b['sessions'] += 1
            b['event_rows'] += int(row.get('event_rows') or 0)
            b['db_total'] += int(row.get('db_total') or 0)
            ratio = row.get('coverage_ratio')
            if isinstance(ratio, (int, float)):
                b['ratio_sum'] += ratio
                b['ratio_count'] += 1
except OSError:
    pass

for platform in sorted(buckets.keys()):
    b = buckets[platform]
    mean_ratio = (b['ratio_sum'] / b['ratio_count']) if b['ratio_count'] else None
    label = platform if platform else '(empty)'
    ratio_str = f"{mean_ratio:.4f}" if mean_ratio is not None else 'n/a'
    print(f"platform={label} sessions={b['sessions']} event_rows={b['event_rows']} db_total_tokens={b['db_total']} mean_coverage_ratio={ratio_str}")
PY
    )
    if [[ -n "${_platform_agg_output}" ]]; then
      while IFS= read -r _agg_line; do
        [[ -z "${_agg_line}" ]] && continue
        info "shadow platform aggregate: ${_agg_line}"
      done <<< "${_platform_agg_output}"
    fi
  fi
  rm -f "${_shadow_run_file}" 2>/dev/null || true

  rm -f "${_env_map_file}" 2>/dev/null || true

  info "=== Done. Reported ${reported_count}, held-sessions=${held_sessions}, legacy-skipped-sessions=${legacy_skipped_sessions}, duplicate-skipped-events=${dup_skipped_events}. ==="
}

main "$@"
