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
# quick-260813-wnz (LOG-01/D-01): once-per-(session, reason) sentinel directory
# for hermes-report.sh's trace-type fallback WARN (markers/.fallback-warn).
# Mirrors WARN_FLAGS_DIR above byte-for-byte: one zero-byte flag file per
# (session, reason), created lazily by its writer (deliberately absent from
# the eager `mkdir -p` below, same as WARN_FLAGS_DIR). Measured motivation:
# without this gate, an ended session that can never acquire a job
# classification re-warned once per minute forever -- 9,039,937 lines
# fleet-wide, 98.2% of one 646 MB log, in 27 days.
FALLBACK_WARN_FLAGS_DIR="${REVENIUM_FALLBACK_WARN_FLAGS_DIR:-${MARKERS_DIR}/.fallback-warn}"

# Third sentinel directory in the same family as WARN_FLAGS_DIR and
# FALLBACK_WARN_FLAGS_DIR: one zero-byte flag per (subcommand, flag) whose
# capability probe came back INDETERMINATE — the probe command failed, or
# succeeded while printing nothing. supports_flag still resolves those to
# "unsupported" (fail open), but warns once so the condition is visible
# instead of silently stripping a dimension off every row in the tick.
# Created lazily by its writer, deliberately absent from the eager mkdir -p.
PROBE_WARN_FLAGS_DIR="${REVENIUM_PROBE_WARN_FLAGS_DIR:-${MARKERS_DIR}/.probe-warn}"
LOCK_FILE="${STATE_DIR}/cron.lock"
MARKER_RETENTION_DAYS="${REVENIUM_MARKER_RETENTION_DAYS:-30}"
PRUNE_LOCK_FILE="${STATE_DIR}/prune.lock"
# v1.3 hotfix (quick-task 260524-lpu): single source of truth for the agent name
# that ships on every meter completion (--agent argv) AND scopes default
# guardrails rule filters (--filter AGENT:IS:${REVENIUM_AGENT_NAME}). Override
# via env when running multiple distinct Hermes installs against one Revenium
# tenant that share an API key but need separate rule scoping.
REVENIUM_AGENT_NAME="${REVENIUM_AGENT_NAME:-Hermes}"
# quick-260814-okp: the SQUAD dimension (--squad-name), deliberately distinct
# from the AGENT dimension above -- a squad is meant to SPAN agents, e.g. one
# fleet/team grouping many `Hermes-<profile>` agents. Measured motivation: the
# platform forms squad groups by NAME, and --squad-name resolved from the
# agent name (see hermes-report.sh's root_agent_name fallback), so every
# multi-profile fleet install collapsed one squad per agent -- observed
# 2026-08-14 on the dev tenant, `revenium squads list` returned four squads,
# three with agentCount: 1, each named after one agent. The empty default is
# LOAD-BEARING for backward compatibility: unset falls through to the
# pre-existing root_agent_name/REVENIUM_AGENT_NAME resolution unchanged. When
# set, this is the HIGHEST-precedence input to --squad-name -- it is an
# explicit operator declaration of squad identity and outranks any
# marker-derived value.
REVENIUM_SQUAD_NAME="${REVENIUM_SQUAD_NAME:-}"
# v1.1 job-tracking scaffolding (D-13): separate ledger for agentic jobs and forward-compat taxonomy path.
JOBS_LEDGER_FILE="${REVENIUM_JOBS_LEDGER_FILE:-${STATE_DIR}/revenium-jobs.ledger}"
JOB_TAXONOMY_FILE="${REVENIUM_JOB_TAXONOMY_FILE:-${STATE_DIR}/job-taxonomy.json}"
# Phase 10 (D-07): staleness threshold for wedged-job warn. Env-overridable.
REVENIUM_JOBS_STALE_SECONDS="${REVENIUM_JOBS_STALE_SECONDS:-600}"
# BUG-1 (agentic-job ↔ transaction association race): the reporter defers a
# session's completions until either the classifier plugin's .ready sentinel
# lands (authoritative gate) OR the session ages past this settle window
# (fallback for when NO plugin is installed and no sentinel ever arrives).
# The old 45s default was SHORTER than real job-inference latency (observed
# ~200s under concurrent multi-profile load), so the age-fallback routinely
# metered + ledgered completions BEFORE the job marker existed, permanently
# orphaning them from the job created a tick later. This MUST exceed worst-case
# job-inference time. Metering-only installs (no classifier plugin, no job
# markers) can safely lower it — there is nothing to wait for.
REVENIUM_CRON_SETTLE_SECONDS="${REVENIUM_CRON_SETTLE_SECONDS:-600}"
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
# Phase 26 (D-06): mktemp template for capturing CLI stderr on calls whose stdout is JSON-parsed.
CLI_STDERR_TMP_TEMPLATE="${REVENIUM_CLI_STDERR_TMP_TEMPLATE:-${STATE_DIR}/.cli-stderr.XXXXXX}"
# Phase 26 (D-09/D-11): per-request batch size for `--output json` list calls
# classified wants-all-pages. 500 is chosen so a realistic install resolves in
# a single request while remaining correct for larger ones (RESEARCH.md A3).
# Env-overridable for installs with unusually many rules. This is a policy
# tunable, not a state path — kept adjacent to the Phase 26 block for
# readability even though it belongs next to REVENIUM_CRON_SETTLE_SECONDS in kind.
REVENIUM_PAGE_BATCH_SIZE="${REVENIUM_PAGE_BATCH_SIZE:-500}"
# Phase 28 (D-06): writer=plugin-status.sh, reader=hermes-report.sh — the
# cross-process plugin-health contract that lets the reporter's trace-type
# fallback distinguish a registration outage from an unclassified session.
PLUGIN_STATUS_FILE="${REVENIUM_PLUGIN_STATUS_FILE:-${STATE_DIR}/plugin-status.json}"
# quick-260813-wnz (LOG-03/D-04): bound the per-profile metering log
# (LOG_FILE). There was no rotation anywhere and one profile's log reached
# 646 MB. 50 MiB (52428800 bytes) is the size at which rotate_log_if_needed
# (below) truncates IN PLACE, keeping the last 2 MiB (2097152 bytes) --
# never renaming or unlinking, since cron's `>> "${LOG_FILE}" 2>&1` append fd
# (install-cron.sh) is opened for the whole tick and would strand on a
# renamed/unlinked inode.
#
# KEEP_BYTES is 2 MiB rather than 10 MiB deliberately: it is the size of the
# in-place rewrite, and the rewrite's duration IS the window of the known
# race documented on rotate_log_if_needed below. Measured on a 59 MB log:
# 10 MiB keep => 68-223 ms rewrite; 2 MiB keep cuts that several-fold. 2 MiB
# still retains ~20k log lines, far more than any diagnostic needs.
REVENIUM_LOG_MAX_BYTES="${REVENIUM_LOG_MAX_BYTES:-52428800}"
REVENIUM_LOG_KEEP_BYTES="${REVENIUM_LOG_KEEP_BYTES:-2097152}"
# Phase 32 (D-01/D-03): per-API-call metering event spool + its idempotency
# ledger. The spool gets its OWN directory rather than sharing TOOL_EVENTS_DIR
# because the record shape (contract C-2) and downstream shipper
# (api-event-report.sh) are unrelated to tool-call capture; the ledger gets
# its OWN key domain rather than sharing LEDGER_FILE/HERMES: because
# api_request_id is a per-CALL identifier, not the per-SESSION-total key the
# old ledger indexes on (D-08) — the two idempotency domains must never
# collide.
EVENT_SPOOL_DIR="${REVENIUM_EVENT_SPOOL_DIR:-${STATE_DIR}/api-events}"
EVENT_LEDGER_FILE="${REVENIUM_EVENT_LEDGER_FILE:-${STATE_DIR}/revenium-api-events.ledger}"
# quick-260817-tfe (OWN-01/OWN-02): the durable session OWNERSHIP record —
# one small file per owned session, whose first line is the literal `legacy`
# or `event` and whose optional second line is the legacy delta path's
# catch-up baseline. Written by an O_EXCL create from hermes-report.sh and
# api-event-report.sh; read by both; pruned by prune-markers.sh.
#
# WHY A THIRD FILE, separate from both ledgers it partitions between. Before
# this, ownership was DERIVED — each shipper grepped the other's BILLING
# ledger at an arbitrary instant — which conflated two different facts and
# produced two P1 defects: the partition was order-dependent (a real
# production double-bill on 2026-08-17, see
# .planning/phases/32-event-driven-metering-on-post-api-request/32-CANARY-EVIDENCE.md),
# and it inherited the billing ledgers' RETENTION, so pruning an event-owned
# session's API: rows at MARKER_RETENTION_DAYS erased its only ownership
# record and let the legacy path re-bill the session's entire cumulative
# total from a zero baseline. Ownership is a fact established ONCE; a billing
# ledger is a mutable record of shipments. They need separate objects.
#
# WHY ITS LIFETIME IS state.db-KEYED, not retention-keyed. The record must
# outlive every billing row it partitions, for as long as the session it
# names can still accrue tokens — i.e. for as long as that session appears in
# state.db. prune-markers.sh's owners pass keys on exactly that and never on
# MARKER_RETENTION_DAYS; separating those two lifetimes is the whole point of
# this path existing.
#
# DELIBERATELY ABSENT from the eager `mkdir -p` below — created lazily by the
# claim primitive (mode 0700), exactly as WARN_FLAGS_DIR is created lazily by
# its writer. That laziness is load-bearing for OWN-03: an install with no
# event path in play never creates a single byte of ownership state.
OWNERS_DIR="${REVENIUM_OWNERS_DIR:-${STATE_DIR}/owners}"
# Phase 32 Plan 03 (C-9): the shadow-comparison readout, the drain-gate status
# document, and the rollout switches that separate the event path's DEPLOY
# (landing a hook + a shipper that are inert) from its BILLING FLIP (letting
# the new path ship for real, or letting the old path stop shipping).
# Defaults are the safe no-op for both switches: REVENIUM_EVENT_METERING_MODE
# defaults to "shadow" (ships nothing, writes no ledger line) and
# REVENIUM_LEGACY_COMPLETIONS defaults to "enabled" (the old path keeps
# billing). A fleet can therefore land this phase's code with zero observable
# change, then flip each switch independently and reversibly. Both switches
# are ALSO readable from config.json (eventMeteringMode / legacyCompletions)
# with the environment taking precedence over config — see
# resolve_switch_setting() below, and api-event-report.sh/hermes-report.sh's
# own pre-source capture of the raw environment value, which is what makes
# that precedence actually reachable.
EVENT_SHADOW_REPORT_FILE="${REVENIUM_EVENT_SHADOW_REPORT_FILE:-${STATE_DIR}/event-shadow-report.jsonl}"
DRAIN_STATUS_FILE="${REVENIUM_DRAIN_STATUS_FILE:-${STATE_DIR}/drain-status.json}"
REVENIUM_EVENT_METERING_MODE="${REVENIUM_EVENT_METERING_MODE:-shadow}"
REVENIUM_LEGACY_COMPLETIONS="${REVENIUM_LEGACY_COMPLETIONS:-enabled}"
# C-11: consecutive quiet drain-checks (no new HERMES: line for a tracked
# session) required before that session is considered drained. Env-overridable
# for an operator who wants a faster/slower cutover than the default.
REVENIUM_DRAIN_QUIET_TICKS="${REVENIUM_DRAIN_QUIET_TICKS:-15}"
# quick-260818-f1g (STALE-01..07): staleness threshold for drain-status.sh's
# ONLY new terminal route, applied ONLY on the `ended_at IS NULL` branch (an
# open session that legacy has stopped hearing from). Measured motivation:
# 216 open sessions fleet-wide, across all ten profiles, have `ended_at IS
# NULL` and will never close on their own -- the unconditionally-non-terminal
# open branch means the drain gate can never report drained, so legacy
# billing can never be disabled and the event path can never take over.
#
# The EFFECTIVE threshold is floored at REVENIUM_CRON_SETTLE_SECONDS + 86400
# (drain-status.sh resolves this, not this file) -- REVENIUM_CRON_SETTLE_SECONDS
# is the DELIBERATE metering-deferral term, so the floor keeps a session
# inside that window from ever being judged stale. That floor is NOT a
# general bound on ledger lag: a ledger line is appended only after a
# SUCCESSFUL `revenium` CLI call, so a persistently-failing per-session
# metering path withholds ledger progress indefinitely, with no upper bound
# at all. No threshold value makes that safe by itself -- safety rests on
# `legacyRetainedSids` (the per-session carve-out hermes-report.sh reads),
# never on this number being "big enough".
#
# A value <= 0 disables the staleness route entirely and restores pre-change
# behaviour exactly (the escape hatch is deliberately in the conservative
# direction; there is no matching "go faster than the floor" escape hatch).
#
# `started_at` was considered as a `COALESCE` fallback and rejected: it would
# judge a live, long-running session by when it BEGAN rather than by whether
# it is still spending, reproducing the exact silent permanent under-bill
# this tunable exists to avoid.
#
# This is a policy tunable, not a state path -- do not add it to the
# `mkdir -p` list below, and do not reference it from any script other than
# drain-status.sh.
REVENIUM_DRAIN_STALE_SECONDS="${REVENIUM_DRAIN_STALE_SECONDS:-604800}"

mkdir -p "${STATE_DIR}" "${MARKERS_DIR}" "${MARKERS_READY_DIR}" "${TOOL_EVENTS_DIR}" "${EVENT_SPOOL_DIR}"

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

# quick-260813-wnz (LOG-03/D-04): bound a metering log file to
# REVENIUM_LOG_MAX_BYTES, truncating IN PLACE (never renaming, never
# unlinking, never creating a `.1` sibling) so cron's `>> "${LOG_FILE}" 2>&1`
# append fd -- opened for the whole tick (install-cron.sh) -- keeps writing
# to the LIVE file rather than an unlinked inode. Takes one optional
# argument, the target path, defaulting to ${LOG_FILE}; the argument exists
# so the out-of-tree fleet wrapper can point it at its own log without a
# second implementation. Never fatal: every failure path (missing target,
# malformed override, a keep size not strictly less than the max, an
# unwritable target) degrades to a silent no-op returning 0 -- matching
# ensure_path's never-fatal contract.
#
# KNOWN RACE, accepted deliberately -- read this before "fixing" it.
# The rewrite below reads the retained tail, writes it at offset 0, then
# truncates. A process appending in that window writes at the OLD end of file
# (O_APPEND targets current EOF), and the truncate then discards those bytes.
# Such an append is silently lost.
#
# Measured exposure at these defaults on a 59 MB log: a 68-223 ms window with
# 10 MiB keep (hence the 2 MiB keep above, which cuts it several-fold), during
# which ~0.4-1.8% of a concurrent append storm was dropped. Bounded further by:
#   * it only fires when the log crosses REVENIUM_LOG_MAX_BYTES -- roughly once
#     every two months per profile at the post-quick-260813-wnz growth rate;
#   * cron.sh calls this while holding LOCK_FILE, and the reporter/guardrail/
#     tool-event children of that same tick log AFTER it returns, so they are
#     never exposed. Only a SEPARATELY invoked script (a human running
#     `bash hermes-report.sh` by hand) can hit it;
#   * only log lines are at risk. The ledger, the metering argv, and
#     idempotency are all untouched by rotation.
#
# Two fixes were evaluated and rejected:
#   1. Absorb the race by re-reading anything appended past original_size until
#      the file stops growing. IMPLEMENTED AND MEASURED: no effect (old 2686/
#      2655/2367 vs new 2640/2764/2542 lines surviving -- indistinguishable).
#      The dominant window is the WRITE, which happens after any such settle
#      check, so the loop covers the wrong phase. Do not re-attempt this.
#   2. Exclude appenders with a lock. `log()` appends with a bare `>>` from
#      every script, so this needs flock(1) per log line -- a subprocess per
#      line, which directly undoes quick-260814-e7c's spawn reduction.
# A real fix means making the standalone entry points take LOCK_FILE, which
# changes their semantics (a manual run would skip/block during a live tick).
# That is a deliberate design change, not a patch to this function.
rotate_log_if_needed() {
  local target="${1:-${LOG_FILE}}"
  local rotate_output
  rotate_output=$(
    ROTATE_TARGET="${target}" \
    ROTATE_MAX_BYTES="${REVENIUM_LOG_MAX_BYTES}" \
    ROTATE_KEEP_BYTES="${REVENIUM_LOG_KEEP_BYTES}" \
    python3 - <<'PY' 2>/dev/null
import os

target = os.environ.get('ROTATE_TARGET', '')

try:
    max_bytes = int(os.environ.get('ROTATE_MAX_BYTES', ''))
    keep_bytes = int(os.environ.get('ROTATE_KEEP_BYTES', ''))
except (TypeError, ValueError):
    raise SystemExit(0)

if keep_bytes >= max_bytes:
    raise SystemExit(0)

if not target:
    raise SystemExit(0)

try:
    original_size = os.path.getsize(target)
except OSError:
    raise SystemExit(0)

if original_size <= max_bytes:
    raise SystemExit(0)

try:
    with open(target, 'r+b') as f:
        f.seek(original_size - keep_bytes)
        # Discard one partial line so the retained content starts on a
        # whole line -- never mid-line.
        f.readline()
        remainder = f.read()
        f.seek(0)
        f.write(remainder)
        f.truncate()
    print(f"ROTATED_FROM={original_size}")
    print(f"ROTATED_RETAINED={len(remainder)}")
except OSError:
    raise SystemExit(0)
PY
  ) || true

  if [[ -n "${rotate_output}" ]]; then
    local rotated_from rotated_retained
    rotated_from=$(echo "${rotate_output}" | sed -n 's/^ROTATED_FROM=//p' | head -1)
    rotated_retained=$(echo "${rotate_output}" | sed -n 's/^ROTATED_RETAINED=//p' | head -1)
    if [[ "${rotated_from}" =~ ^[0-9]+$ ]]; then
      # Lands as the first entry appended AFTER truncation -- ahead of
      # whatever else this tick's scripts log next -- making the
      # truncation self-documenting.
      info "rotate_log_if_needed: ${target} exceeded ${REVENIUM_LOG_MAX_BYTES} bytes (was ${rotated_from}) — truncated in place, retained last ${rotated_retained} bytes"
    fi
  fi
  return 0
}

# Phase 17 (D-10..D-13): two-subcommand probe for v1.3 guardrails CLI capability.
# Returns 0 if both subcommand families exist, non-zero otherwise (fail-open).
# Callers must warn + exit 0 on failure; this helper never logs or exits itself.
has_guardrails_cli() {
  revenium guardrails budget-rules --help >/dev/null 2>&1 && \
  revenium guardrails enforcement-events --help >/dev/null 2>&1
}

# Phase 26 (D-01/D-02): generic capability probe for a single CLI flag on a given
# `revenium` subcommand. Fail-open — returns non-zero (unsupported) on any error,
# including a missing CLI, a subcommand that rejects --help, or no match. Never
# logs, never exits itself; callers resolve the result into a shell variable via
# `if supports_flag ...; then VAR=true; fi` (never `VAR=$(supports_flag ...)` —
# `local x=$(...)` swallows the command substitution's exit status, see
# RESEARCH.md Pitfall 2).
#
# Usage: supports_flag "<subcommand words>" "<--flag>"
#   arg1 is deliberately word-split (unquoted) so multi-word subcommands like
#   "guardrails enforcement-events list" expand into separate positional args.
#   shellcheck disable=SC2086
supports_flag() {
  local help_text
  # Two-step capture instead of `revenium ... --help 2>&1 | grep -q` — `grep -q`
  # exits on its first match and can SIGPIPE the upstream `revenium` process;
  # under `pipefail` that surfaces as exit 141 and the probe would report
  # "unsupported" nondeterministically. The trailing `|| true` makes explicit
  # that this assignment's own exit status is deliberately not consulted.
  local probe_rc=0
  # shellcheck disable=SC2086
  help_text="$(revenium ${1} --help 2>&1)" || probe_rc=$?

  # INDETERMINATE vs NEGATIVE. A probe has three possible outcomes, and this
  # function used to collapse them into two:
  #
  #   non-empty help, flag not present  -> the flag is genuinely absent
  #   non-empty help, flag present      -> supported
  #   command failed, or said nothing   -> WE DO NOT KNOW
  #
  # The third was silently reported as "absent". Because every caller fails
  # open, that costs the metered row its optional dimensions
  # (--agentic-job-id / --trace-type / --squad-*) with no signal at all: the
  # output is byte-indistinguishable from a legitimate older-CLI install.
  # Measured 2026-08-19 across 8 instrumented full-suite runs: of 513 negative
  # probes per run, 123 returned rc=0 with ZERO bytes and 9 returned a
  # non-zero rc. Those 132 were not answers.
  #
  # The RESOLUTION stays fail-open on purpose — assuming "supported" here
  # would hand an old CLI a flag it rejects, which fails the whole meter call
  # rather than one dimension. What changes is that an indeterminate probe is
  # no longer SILENT. Rate-limited per (subcommand, flag) through the same
  # sentinel-directory pattern the warn band uses, because this runs in a
  # per-minute cron and an ungated warn here is how the log grew to millions
  # of lines before.
  if [[ ${probe_rc} -ne 0 || -z "${help_text}" ]]; then
    local probe_key flag_dir
    probe_key="$(printf '%s %s' "${1}" "${2}" | tr -c 'A-Za-z0-9._-' '_')"
    flag_dir="${PROBE_WARN_FLAGS_DIR}"
    if mkdir -p "${flag_dir}" 2>/dev/null \
       && [[ ! -e "${flag_dir}/${probe_key}" ]]; then
      : > "${flag_dir}/${probe_key}" 2>/dev/null || true
      warn "capability probe for '${2}' on 'revenium ${1}' was INDETERMINATE (exit ${probe_rc}, ${#help_text} bytes of help) — treating the flag as unsupported, so rows from this run omit it. This is not a confirmed absence."
    fi
    return 1
  fi
  # The capture above only moved the SIGPIPE off `revenium`; it did NOT remove
  # it. `printf ... | grep -q` reproduced the identical defect one level down —
  # grep exits on the first match and SIGPIPEs `printf`, and under `pipefail`
  # this function then returned 141 and reported a supported flag as absent.
  # Measured 2026-08-19: with help text past the pipe buffer and a match on
  # line 1, the pipeline form failed 200/200; the here-string form 0/200.
  #
  # This defect was LATENT, not active: a real `--help` fits the 64KB pipe
  # buffer today, so the writer finishes before grep exits. It becomes reachable
  # as the CLI's help grows. It therefore does NOT explain the ~1-in-4
  # full-suite flake in the page-size probe tests — that shim emits ~150 bytes,
  # far below the buffer — and PATH leakage to the real CLI is ruled out too
  # (v1.3.0 advertises --page on both probed subcommands). THAT FLAKE IS STILL
  # OPEN AND UNDIAGNOSED; do not read this fix as having closed it.
  #
  # A here-string is a temp FILE, not a pipe, so there is no reader to
  # disappear and no SIGPIPE to race. This CLOSES the window rather than
  # narrowing it; do not "simplify" it back into a pipeline.
  # The `([^A-Za-z0-9-]|$)` trailing boundary stops a probe for "--page" from
  # matching "--page-size". Without it, any CLI that advertises --page-size
  # (which includes every pre-v1.3.0 CLI this skill already calls today) would
  # false-positive as supporting --page.
  grep -qE -- "${2}([^A-Za-z0-9-]|\$)" <<< "${help_text}"
}

# Phase 32 Plan 03 (C-9/T-32-15): resolve a closed two-literal switch with
# env > config.json > hard-default precedence. Shared by api-event-report.sh
# (REVENIUM_EVENT_METERING_MODE / config key eventMeteringMode) and
# hermes-report.sh (REVENIUM_LEGACY_COMPLETIONS / config key
# legacyCompletions) so the two scripts can never disagree on how this
# resolution works.
#
# Callers MUST pass the RAW environment value captured BEFORE this file's own
# "${VAR:-default}" declarations above overwrote it (each caller captures its
# own raw value into a differently-named variable immediately after computing
# SCRIPT_DIR and before `source common.sh`) — passing the already-defaulted
# variable would make config.json unreachable whenever the operator simply
# left the env var unset, since it would never appear empty by the time this
# function saw it.
#
# Prints two lines on stdout: the resolved value, then "true"/"false" for
# whether the input was present but neither empty nor one of the two allowed
# literals (a typo). Callers warn on "true" using their own warn() — never
# silently, per T-32-15: a typo must never silently change billing behavior.
#
# Usage: resolve_switch_setting "${_RAW_ENV_VALUE}" configKeyName default_val allowed1 allowed2
resolve_switch_setting() {
  local raw_env="$1" config_key="$2" default_val="$3" allowed1="$4" allowed2="$5"
  local raw="${raw_env}"
  if [[ -z "${raw}" && -f "${CONFIG_FILE}" ]]; then
    raw=$(CONFIG_FILE="${CONFIG_FILE}" KEY="${config_key}" python3 - <<'PY' 2>/dev/null
import json, os
try:
    v = json.load(open(os.environ['CONFIG_FILE'])).get(os.environ['KEY'], '')
    print(v if isinstance(v, str) else '')
except Exception:
    print('')
PY
)
  fi
  case "${raw}" in
    "${allowed1}"|"${allowed2}")
      printf '%s\nfalse\n' "${raw}"
      ;;
    "")
      printf '%s\nfalse\n' "${default_val}"
      ;;
    *)
      printf '%s\ntrue\n' "${default_val}"
      ;;
  esac
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

# Phase 28 (TRACE-03): resolve the markers directory that OWNS a given session
# identifier, mirroring classifier._paths_for_session's per-session resolution
# for the multiplexed-profile case. Shells into the Python sidecar at
# scripts/resolve-markers-dir.py (canonical implementation, deliberately not
# shared code with classifier.py — see that file's docstring).
# Production usage: markers_dir="$(resolve_markers_dir "${sid}")"
# Fail-open per the sidecar's own contract: empty sid → empty stdout; missing
# python3 or sidecar failure → prints the process-level MARKERS_DIR unchanged.
resolve_markers_dir() {
  local sid="${1:-}"
  if [[ -z "${sid}" ]]; then
    return 0
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "${MARKERS_DIR}"
    return 0
  fi
  python3 "${SKILL_DIR}/scripts/resolve-markers-dir.py" "${sid}" 2>/dev/null || printf '%s\n' "${MARKERS_DIR}"
}

# Phase 32 (EVT-03): resolve the api-events spool directory that OWNS a given
# session identifier — the same per-session, per-profile resolution as
# resolve_markers_dir above, generalized onto a second subdirectory (see
# scripts/resolve-markers-dir.py's resolve_state_subdir). Shells into the
# SAME sidecar with a second "api-events" argument rather than a new file.
# Production usage: spool_dir="$(resolve_spool_dir "${sid}")"
# Fail-open, identical contract to resolve_markers_dir: empty sid → empty
# stdout; missing python3 or sidecar failure → prints the process-level
# EVENT_SPOOL_DIR unchanged.
resolve_spool_dir() {
  local sid="${1:-}"
  if [[ -z "${sid}" ]]; then
    return 0
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "${EVENT_SPOOL_DIR}"
    return 0
  fi
  python3 "${SKILL_DIR}/scripts/resolve-markers-dir.py" "${sid}" "api-events" 2>/dev/null || printf '%s\n' "${EVENT_SPOOL_DIR}"
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

# BUG-3 (multi-profile fan-out): enumerate the Hermes profile homes on this host
# for fleet install/uninstall operations. Prints one TAB-separated
# "<name>\t<home>" line per profile: the default profile first ("default" →
# ${HERMES_DEFAULT_HOME:-${HOME}/.hermes}), then one line per
# ${HERMES_DEFAULT_HOME}/profiles/*/ directory (Hermes' per-profile home layout,
# see user-guide/profiles.md — "~/.hermes/profiles/<name>/"). The base is the
# real DEFAULT home, NOT the possibly-overridden HERMES_HOME, so a fleet install
# enumerates every profile regardless of which home this process was pointed at.
# `hermes profile list` is the canonical enumerator (reference/profile-commands.md)
# but scanning the profiles/ dir needs no CLI and works headless — both modes of
# multi-profile-gateways.md (one-process-per-profile and the multiplexed single
# gateway) keep each profile's home under this path.
hermes_profile_homes() {
  local base="${HERMES_DEFAULT_HOME:-${HOME}/.hermes}"
  printf 'default\t%s\n' "${base}"
  local d name
  if [[ -d "${base}/profiles" ]]; then
    for d in "${base}/profiles"/*/; do
      [[ -d "${d}" ]] || continue
      name="$(basename "${d}")"
      # Skip a literal "default" profile dir — the default home is already emitted.
      [[ "${name}" == "default" ]] && continue
      printf '%s\t%s\n' "${name}" "${d%/}"
    done
  fi
}

# BUG-3: derive the default per-profile AGENT dimension name. The default
# profile keeps the historical "Hermes"; named profiles attribute to
# "Hermes-<profile>" so each profile's completions land under a distinct AGENT
# (--agent argv). Operators override per profile via REVENIUM_AGENT_NAME.
default_agent_name_for_profile() {
  local profile="${1:-default}"
  if [[ -z "${profile}" || "${profile}" == "default" ]]; then
    printf 'Hermes\n'
  else
    printf 'Hermes-%s\n' "${profile}"
  fi
}

# BUG-2 (organization-vs-agent hygiene): warn when organizationName looks like it
# was mistakenly set to the agent/profile identity instead of the ORGANIZATION
# dimension (a company/product, e.g. "tableforone"). Per-agent attribution is the
# AGENT dimension (REVENIUM_AGENT_NAME / --agent), NOT organizationName. Best-effort
# heuristic — only warns, never mutates or fails.
warn_if_org_looks_like_agent() {
  local org="${1:-}"
  [[ -z "${org}" ]] && return 0
  local agent="${REVENIUM_AGENT_NAME:-Hermes}"
  # Case-insensitive exact match, or the "Hermes"/"Hermes-<profile>" family.
  local org_lc agent_lc
  org_lc="$(printf '%s' "${org}" | tr '[:upper:]' '[:lower:]')"
  agent_lc="$(printf '%s' "${agent}" | tr '[:upper:]' '[:lower:]')"
  if [[ "${org_lc}" == "${agent_lc}" || "${org_lc}" == hermes || "${org_lc}" == hermes-* ]]; then
    warn "organizationName='${org}' looks like an AGENT name, not an ORGANIZATION. The ORGANIZATION dimension should be a company/product (e.g. 'tableforone'); per-agent attribution is the AGENT dimension via REVENIUM_AGENT_NAME/--agent. See references/setup.md."
  fi
  return 0
}
