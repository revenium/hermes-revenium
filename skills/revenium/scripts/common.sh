#!/usr/bin/env bash
# Common helpers for the Hermes Revenium skill.

set -uo pipefail

HERMES_HOME="${HERMES_HOME:-${HOME}/.hermes}"
REVENIUM_STATE_DIR="${REVENIUM_STATE_DIR:-${HERMES_HOME}/state/revenium}"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

STATE_DIR="${REVENIUM_STATE_DIR}"
CONFIG_FILE="${STATE_DIR}/config.json"
BUDGET_STATUS_FILE="${STATE_DIR}/budget-status.json"
LEDGER_FILE="${STATE_DIR}/revenium-hermes.ledger"
LOG_FILE="${STATE_DIR}/revenium-metering.log"
ENV_FILE="${STATE_DIR}/env"
STATE_DB="${HERMES_HOME}/state.db"
TAXONOMY_FILE="${REVENIUM_TAXONOMY_FILE:-${STATE_DIR}/task-taxonomy.json}"
MARKERS_DIR="${REVENIUM_MARKERS_DIR:-${STATE_DIR}/markers}"
MARKERS_READY_DIR="${REVENIUM_MARKERS_READY_DIR:-${STATE_DIR}/markers/.ready}"
LOCK_FILE="${STATE_DIR}/cron.lock"
MARKER_RETENTION_DAYS="${REVENIUM_MARKER_RETENTION_DAYS:-30}"
PRUNE_LOCK_FILE="${STATE_DIR}/prune.lock"
# v1.1 job-tracking scaffolding (D-13): separate ledger for agentic jobs and forward-compat taxonomy path.
JOBS_LEDGER_FILE="${REVENIUM_JOBS_LEDGER_FILE:-${STATE_DIR}/revenium-jobs.ledger}"
JOB_TAXONOMY_FILE="${REVENIUM_JOB_TAXONOMY_FILE:-${STATE_DIR}/job-taxonomy.json}"
# Phase 10 (D-07): staleness threshold for wedged-job warn. Env-overridable.
REVENIUM_JOBS_STALE_SECONDS="${REVENIUM_JOBS_STALE_SECONDS:-600}"
# Phase 12: target file for install-hooks.sh (registers pre_llm_call/pre_tool_call hooks).
HOOKS_CONFIG_FILE="${REVENIUM_HOOKS_CONFIG_FILE:-${HERMES_HOME}/config.yaml}"

mkdir -p "${STATE_DIR}" "${MARKERS_DIR}" "${MARKERS_READY_DIR}"

ensure_path() {
  local brew_prefix=""
  if command -v brew >/dev/null 2>&1; then
    brew_prefix="$(brew --prefix 2>/dev/null || true)"
  fi
  for p in     "${brew_prefix:+${brew_prefix}/bin}"     "${brew_prefix:+${brew_prefix}/sbin}"     /home/linuxbrew/.linuxbrew/bin     /home/linuxbrew/.linuxbrew/sbin     /opt/homebrew/bin     /opt/homebrew/sbin     /usr/local/bin     /usr/bin     "${HOME}/go/bin"     "${HOME}/.local/bin"; do
    [[ -n "${p}" && -d "${p}" ]] && export PATH="${p}:${PATH}"
  done
}

log() {
  local level="$1"; shift
  mkdir -p "${STATE_DIR}"
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [${level}] [revenium] $*" | tee -a "${LOG_FILE}" >&2
}

info()  { log "INFO " "$@"; }
warn()  { log "WARN " "$@"; }
error() { log "ERROR" "$@"; }
