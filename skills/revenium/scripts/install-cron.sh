#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

# Argument parsing.
# --interval-seconds N : run the metering pipeline every N seconds within
#                        each cron tick (1..60). N=60 (or omitted) preserves
#                        once-per-minute behavior. Smaller N shortens demo
#                        feedback at the cost of more revenium-CLI calls.
# --dry-run            : print the crontab line(s) that would be installed and
#                        exit 0 without touching crontab.
# --force              : replace any existing per-target metering line instead
#                        of leaving it untouched (single-home mode only; the
#                        multi-profile modes always refresh each profile's line).
# --all-profiles       : BUG-3 fleet install — wire the metering cron for the
#                        default home AND every ~/.hermes/profiles/<name>/ home,
#                        each keyed on a UNIQUE crontab marker so per-profile
#                        installs never overwrite one another. Bakes per-profile
#                        HERMES_HOME, REVENIUM_STATE_DIR, REVENIUM_AGENT_NAME and
#                        REVENIUM_CRON_SETTLE_SECONDS into each line. Works in
#                        both deployment modes (one-process-per-profile and the
#                        multiplexed single gateway — see
#                        user-guide/multi-profile-gateways.md).
# --profile <name>     : (repeatable) wire only the named profile(s). Same
#                        per-profile marker/env baking as --all-profiles.
INTERVAL_SECONDS=""
DRY_RUN=false
FORCE=false
ALL_PROFILES=false
SELECTED_PROFILES=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --interval-seconds)
      INTERVAL_SECONDS="${2:-}"; shift 2 ;;
    --interval-seconds=*)
      INTERVAL_SECONDS="${1#--interval-seconds=}"; shift ;;
    --dry-run)
      DRY_RUN=true; shift ;;
    --force)
      FORCE=true; shift ;;
    --all-profiles)
      ALL_PROFILES=true; shift ;;
    --profile)
      SELECTED_PROFILES+=("${2:?--profile requires a name}"); shift 2 ;;
    --profile=*)
      SELECTED_PROFILES+=("${1#--profile=}"); shift ;;
    -h|--help)
      cat <<USAGE
Usage: install-cron.sh [--interval-seconds N] [--force] [--dry-run]
                       [--all-profiles | --profile <name> ...]

Installs the per-minute Revenium metering cron entry that drains markers,
ships token usage / tool-events to Revenium, and refreshes guardrail-status.json.

  --interval-seconds N   Run the metering pipeline every N seconds within
                         each cron tick (1..60). Defaults to 60. Set to 15
                         for a four-times-per-minute "demo" cadence so spend
                         appears in Revenium faster.
  --force                Replace an existing single-home metering line
                         (required to change --interval-seconds on a host
                         that already has the cron installed).
  --all-profiles         Fleet install: wire the default home AND every
                         ~/.hermes/profiles/<name>/ home, each on a unique
                         crontab marker (# hermes-revenium-metering-<profile>)
                         with per-profile env baked in. Idempotent per profile.
  --profile <name>       Wire only the named profile (repeatable).
  --dry-run              Print the crontab line(s) that would be installed and
                         exit without modifying crontab.

Uninstall (removes ALL per-profile lines + the legacy line):
  bash ${SCRIPT_DIR}/uninstall-cron.sh
USAGE
      exit 0 ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      echo "Run with --help for usage." >&2
      exit 1 ;;
  esac
done

ensure_path
mkdir -p "${STATE_DIR}"
chmod 700 "${MARKERS_DIR}" 2>/dev/null || true
chmod +x "${SKILL_DIR}/scripts/"*.sh

CRON_SCRIPT="${SKILL_DIR}/scripts/cron.sh"
CRON_SCHEDULE="* * * * *"
CRON_PATH="/usr/local/bin:/usr/bin:/bin"
NL=$'\n'

for p in \
  /home/linuxbrew/.linuxbrew/bin \
  /opt/homebrew/bin \
  "${HOME}/go/bin" \
  "${HOME}/.local/bin"; do
  [[ -d "${p}" ]] && CRON_PATH="${p}:${CRON_PATH}"
done

if command -v brew >/dev/null 2>&1; then
  BREW_BIN="$(brew --prefix 2>/dev/null)/bin"
  [[ -d "${BREW_BIN}" ]] && CRON_PATH="${BREW_BIN}:${CRON_PATH}"
fi

# Translate --interval-seconds N into the two loop knobs that cron.sh reads.
# Validation here is fail-loud (exit 1) because misconfigured cron lines are
# silent killers — cron just runs the bad line every minute until you notice.
LOOP_ENV=""
INTERVAL_DESCRIPTION="every minute"
if [[ -n "${INTERVAL_SECONDS}" ]]; then
  if ! [[ "${INTERVAL_SECONDS}" =~ ^[0-9]+$ ]] \
      || (( INTERVAL_SECONDS < 1 )) || (( INTERVAL_SECONDS > 60 )); then
    echo "ERROR: --interval-seconds must be an integer in 1..60 (got: ${INTERVAL_SECONDS})" >&2
    exit 1
  fi
  if (( INTERVAL_SECONDS < 60 )); then
    LOOP_COUNT=$(( 60 / INTERVAL_SECONDS ))
    LOOP_ENV="REVENIUM_CRON_LOOP_COUNT=${LOOP_COUNT} REVENIUM_CRON_LOOP_SLEEP_SECONDS=${INTERVAL_SECONDS} "
    INTERVAL_DESCRIPTION="${LOOP_COUNT}x per minute (every ${INTERVAL_SECONDS}s)"
  fi
fi

# ---------------------------------------------------------------------------
# Resolve the install targets: each is "name|home|state_dir|agent|marker".
# ---------------------------------------------------------------------------
MULTI_PROFILE=false
if ${ALL_PROFILES} || (( ${#SELECTED_PROFILES[@]} > 0 )); then
  MULTI_PROFILE=true
fi

# Build one crontab line for a target home.
build_cron_line() {
  local home="$1" state_dir="$2" agent="$3" marker="$4"
  local logfile="${state_dir}/revenium-metering.log"
  # Per-profile env baked into the line so cron (near-empty env) runs each
  # profile against its OWN home/state/agent. REVENIUM_CRON_SETTLE_SECONDS is
  # carried so per-profile tuning persists (BUG-1 sizing vs job-inference).
  printf '%s HERMES_HOME=%s REVENIUM_STATE_DIR=%s REVENIUM_AGENT_NAME=%s REVENIUM_CRON_SETTLE_SECONDS=%s %sPATH=%s bash %s >> %s 2>&1 %s' \
    "${CRON_SCHEDULE}" "${home}" "${state_dir}" "${agent}" \
    "${REVENIUM_CRON_SETTLE_SECONDS}" "${LOOP_ENV}" "${CRON_PATH}" \
    "${CRON_SCRIPT}" "${logfile}" "${marker}"
}

TARGETS=()
if ${MULTI_PROFILE}; then
  # Enumerate profile homes; filter to --profile names when given.
  while IFS=$'\t' read -r pname phome; do
    [[ -z "${pname}" ]] && continue
    if (( ${#SELECTED_PROFILES[@]} > 0 )); then
      local_match=false
      for want in "${SELECTED_PROFILES[@]}"; do
        [[ "${want}" == "${pname}" ]] && local_match=true
      done
      ${local_match} || continue
    fi
    pstate="${phome}/state/revenium"
    pagent="$(default_agent_name_for_profile "${pname}")"
    pmarker="# hermes-revenium-metering-${pname}"
    TARGETS+=("${pname}|${phome}|${pstate}|${pagent}|${pmarker}")
  done < <(hermes_profile_homes)

  # If explicit --profile names were requested but not found on disk, fail loud.
  if (( ${#SELECTED_PROFILES[@]} > 0 && ${#TARGETS[@]} == 0 )); then
    echo "ERROR: none of the requested profiles were found under ${HOME}/.hermes/profiles/" >&2
    exit 1
  fi
else
  # Legacy single-home target: the CURRENT common.sh-resolved home, bare marker
  # (backward compatible with pre-fleet installs).
  TARGETS+=("current|${HERMES_HOME}|${STATE_DIR}|${REVENIUM_AGENT_NAME}|# hermes-revenium-metering")
fi

# ---------------------------------------------------------------------------
# Dry-run: print each target's crontab line and exit.
# ---------------------------------------------------------------------------
if ${DRY_RUN}; then
  for t in "${TARGETS[@]}"; do
    IFS='|' read -r tname thome tstate tagent tmarker <<< "${t}"
    build_cron_line "${thome}" "${tstate}" "${tagent}" "${tmarker}"
    printf '\n'
  done
  exit 0
fi

# The crontab persistence below is intentional and fully disclosed:
# README.md §"How It Works", docs/installation.md, SKILL.md §"Setup"
# scanner finding: persistence_cron (MEDIUM) — expected behavior, not a threat.

# ---------------------------------------------------------------------------
# BUG-7: reconcile orphaned metering lines whose target cron.sh no longer exists
# (e.g. after a `~/.hermes` reset). Drop them so cron stops spamming
# "No such file" every minute. Runs in ALL modes.
# ---------------------------------------------------------------------------
CURRENT="$(crontab -l 2>/dev/null || true)"
RECONCILED=""
ORPHANS_REMOVED=0
if [[ -n "${CURRENT}" ]]; then
  while IFS= read -r line; do
    case "${line}" in
      *hermes-revenium-metering*)
        script_path="$(printf '%s' "${line}" | grep -oE '[^ ]*cron\.sh' | head -1 || true)"
        if [[ -n "${script_path}" && ! -f "${script_path}" ]]; then
          ORPHANS_REMOVED=$((ORPHANS_REMOVED + 1))
          echo "↻ Removing orphaned metering cron line (missing ${script_path})"
          continue
        fi
        ;;
    esac
    RECONCILED+="${line}${NL}"
  done <<< "${CURRENT}"
fi
# Strip the single trailing newline artifact for clean comparison.
RECONCILED="${RECONCILED%"${NL}"}"

# ---------------------------------------------------------------------------
# Install each target. Match a target's line by its EXACT marker at end-of-line
# (bash suffix glob) so profiles never clobber one another (# ...-metering-gtm
# vs # ...-metering-gtm2 vs bare # ...-metering are all distinct, and profile
# names containing regex metacharacters are matched literally).
# ---------------------------------------------------------------------------
NEW_CRONTAB="${RECONCILED}"
CHANGED=$(( ORPHANS_REMOVED > 0 ? 1 : 0 ))
ALREADY_MSGS=()

for t in "${TARGETS[@]}"; do
  IFS='|' read -r tname thome tstate tagent tmarker <<< "${t}"
  new_line="$(build_cron_line "${thome}" "${tstate}" "${tagent}" "${tmarker}")"

  # Find (and by default drop) any existing line ending in this EXACT marker.
  existing=""
  kept=""
  if [[ -n "${NEW_CRONTAB}" ]]; then
    while IFS= read -r line; do
      if [[ "${line}" == *"${tmarker}" ]]; then
        existing="${line}"
      else
        kept+="${line}${NL}"
      fi
    done <<< "${NEW_CRONTAB}"
    kept="${kept%"${NL}"}"
  fi

  if [[ -n "${existing}" && "${MULTI_PROFILE}" == "false" && "${FORCE}" == "false" ]]; then
    # Legacy single-home preserve-untouched-unless-force behavior.
    ALREADY_MSGS+=("✓ Revenium cron already installed (${tname}).")
    ALREADY_MSGS+=("${existing}")
    if [[ -n "${INTERVAL_SECONDS}" ]]; then
      ALREADY_MSGS+=("")
      ALREADY_MSGS+=("ℹ --interval-seconds was supplied but the existing entry was left in place.")
      ALREADY_MSGS+=("  Re-run with --force to replace it:")
      ALREADY_MSGS+=("    bash ${SKILL_DIR}/scripts/install-cron.sh --interval-seconds ${INTERVAL_SECONDS} --force")
    fi
    continue
  fi

  # Rebuild without the old target line, then append the fresh one.
  NEW_CRONTAB="${kept:+${kept}${NL}}${new_line}"
  CHANGED=1
  echo "✅ Revenium metering cron installed for '${tname}' (${INTERVAL_DESCRIPTION})"
  echo "   agent=${tagent}  home=${thome}"
done

if (( CHANGED == 1 )); then
  printf '%s\n' "${NEW_CRONTAB}" | crontab -
fi

# Print any "already installed" notices AFTER writing (legacy single-home path).
# Guard the expansion — bash 3.2 (macOS) errors on "${empty[@]}" under set -u.
if (( ${#ALREADY_MSGS[@]} > 0 )); then
  for m in "${ALREADY_MSGS[@]}"; do
    echo "${m}"
  done
fi

if (( CHANGED == 0 && ${#ALREADY_MSGS[@]} == 0 )); then
  echo "No metering cron changes."
fi

echo ""
echo "To view all metering lines:  crontab -l | grep hermes-revenium-metering"
echo "To run manually:             bash ${CRON_SCRIPT}"
echo "To uninstall (all profiles): bash ${SKILL_DIR}/scripts/uninstall-cron.sh"
