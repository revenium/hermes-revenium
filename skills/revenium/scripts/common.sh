#!/usr/bin/env bash
# Common helpers for the Hermes Revenium skill.

set -uo pipefail

HERMES_HOME="${HERMES_HOME:-${HOME}/.hermes}"
REVENIUM_STATE_DIR="${REVENIUM_STATE_DIR:-${HERMES_HOME}/state/revenium}"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

STATE_DIR="${REVENIUM_STATE_DIR}"
CONFIG_FILE="${STATE_DIR}/config.json"
LEDGER_FILE="${STATE_DIR}/revenium-hermes.ledger"
LOG_FILE="${STATE_DIR}/revenium-metering.log"
ENV_FILE="${STATE_DIR}/env"
STATE_DB="${HERMES_HOME}/state.db"
TAXONOMY_FILE="${REVENIUM_TAXONOMY_FILE:-${STATE_DIR}/task-taxonomy.json}"
MARKERS_DIR="${REVENIUM_MARKERS_DIR:-${STATE_DIR}/markers}"
MARKERS_READY_DIR="${REVENIUM_MARKERS_READY_DIR:-${STATE_DIR}/markers/.ready}"
# Phase 19 (D-06): warn-band rate-limit sentinel directory (markers/.warn); zero-byte flag files per (session, ruleId).
WARN_FLAGS_DIR="${REVENIUM_WARN_FLAGS_DIR:-${MARKERS_DIR}/.warn}"
LOCK_FILE="${STATE_DIR}/cron.lock"
MARKER_RETENTION_DAYS="${REVENIUM_MARKER_RETENTION_DAYS:-30}"
PRUNE_LOCK_FILE="${STATE_DIR}/prune.lock"
# v1.3 hotfix (quick-task 260524-lpu): single source of truth for the agent name
# that ships on every meter completion (--agent argv) AND scopes default
# guardrails rule filters (--filter AGENT:IS:${REVENIUM_AGENT_NAME}). Override
# via env when running multiple distinct Hermes installs against one Revenium
# tenant that share an API key but need separate rule scoping.
REVENIUM_AGENT_NAME="${REVENIUM_AGENT_NAME:-Hermes}"
# v1.1 job-tracking scaffolding (D-13): separate ledger for agentic jobs and forward-compat taxonomy path.
JOBS_LEDGER_FILE="${REVENIUM_JOBS_LEDGER_FILE:-${STATE_DIR}/revenium-jobs.ledger}"
JOB_TAXONOMY_FILE="${REVENIUM_JOB_TAXONOMY_FILE:-${STATE_DIR}/job-taxonomy.json}"
# Phase 10 (D-07): staleness threshold for wedged-job warn. Env-overridable.
REVENIUM_JOBS_STALE_SECONDS="${REVENIUM_JOBS_STALE_SECONDS:-600}"
# Phase 12: target file for install-hooks.sh (registers pre_llm_call/pre_tool_call hooks).
HOOKS_CONFIG_FILE="${REVENIUM_HOOKS_CONFIG_FILE:-${HERMES_HOME}/config.yaml}"
# Phase 14: tool-event capture state paths.
TOOL_EVENTS_DIR="${REVENIUM_TOOL_EVENTS_DIR:-${STATE_DIR}/tool-events}"
TOOL_EVENTS_LEDGER_FILE="${REVENIUM_TOOL_EVENTS_LEDGER_FILE:-${STATE_DIR}/revenium-tool-events.ledger}"
# Phase 17: v1.3 guardrails-native paths.
GUARDRAIL_STATUS_FILE="${REVENIUM_GUARDRAIL_STATUS_FILE:-${STATE_DIR}/guardrail-status.json}"
RULES_LOCK_FILE="${REVENIUM_RULES_LOCK_FILE:-${STATE_DIR}/rules.lock}"
# Phase 18: notify-once gate for setup-guardrails.sh migration failures (D-10).
MIGRATION_NOTIFY_FILE="${REVENIUM_MIGRATION_NOTIFY_FILE:-${STATE_DIR}/migration-notify-state}"

mkdir -p "${STATE_DIR}" "${MARKERS_DIR}" "${MARKERS_READY_DIR}" "${TOOL_EVENTS_DIR}"

ensure_path() {
  local brew_prefix=""
  if command -v brew >/dev/null 2>&1; then
    brew_prefix="$(brew --prefix 2>/dev/null || true)"
  fi
  for p in     "${brew_prefix:+${brew_prefix}/bin}"     "${brew_prefix:+${brew_prefix}/sbin}"     /home/linuxbrew/.linuxbrew/bin     /home/linuxbrew/.linuxbrew/sbin     /opt/homebrew/bin     /opt/homebrew/sbin     /usr/local/bin     /usr/bin     "${HOME}/go/bin"     "${HOME}/.local/bin"; do
    [[ -n "${p}" && -d "${p}" ]] && export PATH="${p}:${PATH}"
  done
  # quick-260606: always succeed. The loop's exit status is that of the LAST
  # `[[ -d ... ]] && export` — which is 1 when the final candidate (~/.local/bin)
  # doesn't exist on a host. Callers run `set -euo pipefail` and call ensure_path
  # right after sourcing, so a non-zero return aborted them silently before any
  # output (observed: install-plugin.sh dying with no message on a host lacking
  # ~/.local/bin). ensure_path is best-effort PATH augmentation — never fatal.
  return 0
}

log() {
  # Single-source log writer. Always appends ONE line to LOG_FILE; mirrors to
  # stderr only when the caller is interactive (TTY).
  #
  # Why not `tee -a "${LOG_FILE}" >&2`? Cron invokes the pipeline with
  # `>> ${LOG_FILE} 2>&1`, which captures stderr back into LOG_FILE. The prior
  # tee+stderr combo therefore wrote every line to LOG_FILE *twice* under cron
  # (once via tee's append, once via the cron redirect catching tee's stdout
  # that we'd routed to stderr). The TTY guard preserves the interactive UX —
  # an operator running `bash hermes-report.sh` still sees log lines on stderr —
  # while keeping cron's log clean.
  local level="$1"; shift
  local line="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [${level}] [revenium] $*"
  mkdir -p "${STATE_DIR}"
  printf '%s\n' "${line}" >> "${LOG_FILE}"
  if [[ -t 2 ]]; then
    printf '%s\n' "${line}" >&2
  fi
}

info()  { log "INFO " "$@"; }
warn()  { log "WARN " "$@"; }
error() { log "ERROR" "$@"; }

# Phase 17 (D-10..D-13): two-subcommand probe for v1.3 guardrails CLI capability.
# Returns 0 if both subcommand families exist, non-zero otherwise (fail-open).
# Callers must warn + exit 0 on failure; this helper never logs or exits itself.
has_guardrails_cli() {
  revenium guardrails budget-rules --help >/dev/null 2>&1 && \
  revenium guardrails enforcement-events --help >/dev/null 2>&1
}

# Phase 21 (TRACE-01, v1.4 path foundation): walk state.db.sessions.parent_session_id
# to the root delegator and print it on stdout. Shells into the Python sidecar at
# scripts/get-root-session-id.py (canonical implementation per D-01).
# Production usage: root_sid="$(get_root_session_id "${sid}")"
# Fail-open per D-05: empty sid → empty stdout; missing python3 or sidecar failure
# → echoes the input sid unchanged (matches classifier.py fail-open semantics).
get_root_session_id() {
  local sid="${1:-}"
  if [[ -z "${sid}" ]]; then
    return 0
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "${sid}"
    return 0
  fi
  python3 "${SKILL_DIR}/scripts/get-root-session-id.py" "${sid}" 2>/dev/null || printf '%s\n' "${sid}"
}

# quick-260605: resolve the Revenium teamId for CLI calls that require it
# (jobs create/outcome). Prefers the REVENIUM_TEAM_ID env override, then falls
# back to parsing `revenium config show`. Prints the team-id on stdout, or an
# empty string when unresolved. Mirrors guardrail-check.sh's resolution so every
# caller agrees on one source of truth.
#
# Why this exists: `revenium jobs create` requires teamId. When it is absent the
# CLI returns HTTP 400 / exit 4 ("Missing request parameter: teamId"), which the
# cron's 409-only success detection treats as a generic failure — so the
# JOB:created ledger line is never written and the outcome stays deferred forever
# (OUTCOME-04). Resolving + passing teamId explicitly, plus a loud warn when it is
# missing, turns that silent permanent failure into a diagnosable one.
#
# ANSI-safe via a literal ESC byte (portable across BSD/GNU sed); whitespace
# stripped. Empty output is the contract for "unresolved" — callers must guard.
resolve_team_id() {
  if [[ -n "${REVENIUM_TEAM_ID:-}" ]]; then
    printf '%s\n' "${REVENIUM_TEAM_ID}"
    return 0
  fi
  local esc
  esc=$(printf '\033')
  revenium config show 2>/dev/null \
    | sed "s/${esc}\[[0-9;]*m//g" \
    | sed -n 's/.*Team ID:[[:space:]]*//p' \
    | head -1 \
    | tr -d '[:space:]'
}
