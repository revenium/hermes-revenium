#!/usr/bin/env bash
set -uo pipefail
# diagnose.sh — read-only triage for "the skill installed but no traffic reaches
# Revenium". Prints one report covering every stage of the pipeline, ordered by
# how often each stage is the actual cause.
#
# No -e: a broken stage must still print its own error and let the REST of the
# report run. A report that stops at section 2 is exactly the report nobody can
# act on.
#
# Read-only by default: it changes nothing and ships nothing unless --tick is
# passed. It never prints the API key — `revenium config show` masks it and the
# line is redacted again here, so the output is safe to paste into an issue.
#
# Usage:
#   bash diagnose.sh                # read-only report
#   bash diagnose.sh --tick         # ALSO run one real cron tick (SHIPS data)
#   bash diagnose.sh --profile qa   # inspect the 'qa' profile home instead
#
# Exit is always 0 — this is a report, not a gate. The findings are in the text.

TICK="false"
PROFILE=""
usage() { sed -n '3,21p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

# Args are parsed BEFORE common.sh is sourced: common.sh resolves every state
# path from HERMES_HOME at source time, so --profile has to redirect it first.
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tick) TICK="true"; shift ;;
    --profile) PROFILE="${2:?--profile requires a name}"; shift 2 ;;
    --profile=*) PROFILE="${1#--profile=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown flag: $1 (try --help)" >&2; exit 2 ;;
  esac
done

_BASE_HOME="${HERMES_DEFAULT_HOME:-${HOME}/.hermes}"
if [[ -n "${PROFILE}" ]]; then
  # "default" is the name section 8 prints for the base home, so an operator
  # copying a name out of that table will type it. The default profile does NOT
  # live at profiles/default — hermes_profile_homes emits the base home under
  # that label — so mapping it there would report an invented, all-absent tree
  # and read as a broken install.
  if [[ "${PROFILE}" == "default" ]]; then
    export HERMES_HOME="${_BASE_HOME}"
  else
    export HERMES_HOME="${_BASE_HOME}/profiles/${PROFILE}"
    if [[ ! -d "${HERMES_HOME}" ]]; then
      echo "ERROR: no profile '${PROFILE}' at ${HERMES_HOME}" >&2
      echo "Known profiles:" >&2
      echo "  default" >&2
      if [[ -d "${_BASE_HOME}/profiles" ]]; then
        for _d in "${_BASE_HOME}/profiles"/*/; do
          [[ -d "${_d}" ]] && echo "  $(basename "${_d}")" >&2
        done
      fi
      # Exiting non-zero here rather than reporting on a directory that does not
      # exist: an all-absent report for an invented tree is worse than no report.
      exit 2
    fi
  fi
  # Let common.sh re-derive STATE_DIR under the new home rather than inheriting
  # an ambient one that points at the default profile.
  unset REVENIUM_STATE_DIR
fi

hr()    { echo ""; echo "===== $* ====="; }
# "(absent)" rather than 0 — a missing file and an empty one mean different
# things here (never ran vs ran and found nothing).
count() { [[ -e "$1" ]] && { ls -1 "$1" 2>/dev/null | wc -l | tr -d ' '; } || echo "(absent)"; }
lines() { [[ -f "$1" ]] && { wc -l < "$1" | tr -d ' '; } || echo "(absent)"; }
mtime() { [[ -e "$1" ]] && { date -r "$1" 2>/dev/null || echo "(unknown)"; } || echo "(absent)"; }
# Same "(absent)" convention as lines() above, but counting occurrences of a
# literal (fixed-string) prefix rather than every line. Used by section 9 to
# count the two cron-side log-taxonomy outcomes without a second file-format.
grepcount() {
  local f="$1" pat="$2" n rc
  [[ -f "${f}" ]] || { echo "(absent)"; return; }
  # A present-but-unreadable file must not render as 0 -- that is
  # indistinguishable from a confirmed zero matches, same "(absent)" vs
  # "ran and found nothing" distinction lines()/count() already make above.
  # Check readability up front (covers the common permission-denied case
  # without ever invoking grep), and ALSO check grep's own exit code as
  # defense in depth for a file that fails to open despite passing -r (a
  # race, an I/O error). `grep -Fc` exits 1 on a legitimate zero-match --
  # that is NOT an error and must still print 0 -- so only an exit code
  # greater than 1 (2 = usage/read error) is treated as unreadable.
  [[ -r "${f}" ]] || { echo "(unreadable)"; return; }
  n="$(grep -Fc -- "${pat}" "${f}" 2>/dev/null)"
  rc=$?
  if [[ ${rc} -gt 1 ]]; then
    echo "(unreadable)"
    return
  fi
  echo "${n:-0}"
}

# Probe the state tree BEFORE sourcing common.sh, which eagerly `mkdir -p`s
# STATE_DIR, markers/, markers/.ready/ and tool-events/ at source time. After
# that runs, "this directory does not exist" is no longer observable — and it is
# a materially different diagnosis from "exists but empty" (never installed vs
# installed and idle). Sourcing would also CREATE the tree on a host that never
# had one, which is both a read-only violation and the destruction of the single
# clearest piece of evidence.
#
# This is the one place a state path is recomputed outside common.sh. The
# duplication is deliberate: observing the tree pre-source is impossible any
# other way. Keep the expression in sync with common.sh's STATE_DIR default.
_probe_state="${REVENIUM_STATE_DIR:-${HERMES_HOME:-${HOME}/.hermes}/state/revenium}"
PRE_STATE_EXISTED="true"; [[ -d "${_probe_state}" ]] || PRE_STATE_EXISTED="false"
PRE_MARKERS="$(count "${_probe_state}/markers")"
PRE_READY="$(count "${_probe_state}/markers/.ready")"
PRE_TOOL_EVENTS="$(count "${_probe_state}/tool-events")"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

echo "revenium diagnose  $(date -u +%Y-%m-%dT%H:%M:%SZ)  host=$(hostname -s 2>/dev/null)"
echo "HERMES_HOME = ${HERMES_HOME}"
echo "STATE_DIR   = ${STATE_DIR}"
[[ -n "${PROFILE}" ]] && echo "PROFILE     = ${PROFILE}"

# ---------------------------------------------------------------------------
hr "0. WHICH ENVIRONMENT IS THIS METERING INTO"
# The most common silent cause. An api-url on a dev host while the operator
# watches the prod dashboard makes every other section below look perfectly
# healthy while the data lands somewhere they are not looking.
if command -v revenium >/dev/null 2>&1; then
  revenium config show 2>&1 | sed -E 's/(Key:[[:space:]]*).*/\1<redacted>/'
  echo ""
  echo "NOTE: compare 'API URL' against the environment whose dashboard you are"
  echo "      watching. A dev api-url meters successfully into the wrong tenant."
else
  echo "!! revenium CLI not on PATH — nothing can ship."
  echo "   Fix: brew install revenium/tap/revenium"
fi

# ---------------------------------------------------------------------------
hr "1. CRON REGISTERED"
if crontab -l 2>/dev/null | grep hermes-revenium-metering; then
  :
else
  echo "!! NO metering cron line — nothing ever ships on its own."
  echo "   Fix: bash ${SKILL_DIR}/scripts/install-cron.sh"
fi

# ---------------------------------------------------------------------------
hr "2. CRON LOG"
if [[ -f "${LOG_FILE}" ]]; then
  echo "(last modified: $(mtime "${LOG_FILE}"))"
  echo "--- last 40 lines ---"
  tail -40 "${LOG_FILE}"
else
  echo "!! no log at ${LOG_FILE} — the cron has never run."
fi

# ---------------------------------------------------------------------------
hr "3. LEDGERS (what has already shipped)"
printf '%-30s %s lines\n' "revenium-hermes.ledger"      "$(lines "${LEDGER_FILE}")"
printf '%-30s %s lines\n' "revenium-jobs.ledger"        "$(lines "${JOBS_LEDGER_FILE}")"
printf '%-30s %s lines\n' "revenium-tool-events.ledger" "$(lines "${TOOL_EVENTS_LEDGER_FILE}")"
echo "--- last 3 completion ledger lines ---"
tail -3 "${LEDGER_FILE}" 2>/dev/null || echo "(none)"

# ---------------------------------------------------------------------------
hr "4. IS THERE ANYTHING TO METER"
# Mirrors hermes-report.sh's own predicate. There is no total_tokens column;
# the reporter selects on input_tokens/output_tokens and ships DELTAS, so a
# session already at its last-reported total is skipped by design, not by fault.
if [[ -f "${STATE_DB}" ]]; then
  printf 'sessions with tokens: '
  sqlite3 "${STATE_DB}" \
    "SELECT COUNT(*) FROM sessions WHERE input_tokens > 0 OR output_tokens > 0;" 2>&1
  echo "--- 8 most recent ---"
  sqlite3 -header -column "${STATE_DB}" \
    "SELECT substr(id,1,26) AS sid, input_tokens AS in_tok, output_tokens AS out_tok,
            datetime(started_at,'unixepoch') AS started
     FROM sessions
     WHERE input_tokens > 0 OR output_tokens > 0
     ORDER BY started_at DESC LIMIT 8;" 2>&1
else
  echo "!! no state.db at ${STATE_DB} — Hermes has not run here."
fi

# ---------------------------------------------------------------------------
hr "5. CLASSIFIER SETTLE GATE"
# A session with no .ready sentinel is deferred for the whole settle window
# before it is metered at all. Sentinels never appearing at all means the
# plugin is not loaded — usually the gateway was never restarted after install.
# Counts are the PRE-SOURCE snapshot — see the probe above.
echo "marker files:   ${PRE_MARKERS}"
echo ".ready files:   ${PRE_READY}"
echo "tool-events:    ${PRE_TOOL_EVENTS}"
echo "settle seconds: ${REVENIUM_CRON_SETTLE_SECONDS}"
echo ""
if [[ "${PRE_STATE_EXISTED}" == "false" ]]; then
  echo "!! ${STATE_DIR} did not exist before this run."
  echo "   Nothing has ever written state here — the skill has not run on this host."
  echo "   (The directories exist now only because loading common.sh creates them.)"
  echo ""
fi
echo "NOTE: a session with no .ready sentinel waits out the full settle window."
echo "      Zero .ready files ever = the classifier plugin is not loaded."

# ---------------------------------------------------------------------------
hr "6. PLUGIN + HOOKS"
# REVENIUM_LOG_FILE=/dev/null on both children: they use the shared log
# helpers, and a diagnostic must not interleave its own lines into the metering
# log that section 2 above is displaying.
if [[ -f "${SKILL_DIR}/scripts/plugin-status.sh" ]]; then
  # plugin-status.sh REWRITES plugin-status.json (and takes a .lock beside it).
  # That file is itself evidence — the cron maintains it, and hermes-report.sh
  # reads it to tell a registration outage apart from a genuinely unclassified
  # session. Redirecting it to a scratch path keeps the live one intact while
  # still running the real check. Redirecting the file moves its lock too.
  _ps_tmp="$(mktemp -t revenium-plugin-status.XXXXXX 2>/dev/null || echo /dev/null)"
  REVENIUM_LOG_FILE=/dev/null REVENIUM_PLUGIN_STATUS_FILE="${_ps_tmp}" \
    bash "${SKILL_DIR}/scripts/plugin-status.sh" 2>&1 | head -25
  [[ "${_ps_tmp}" != "/dev/null" ]] && rm -f "${_ps_tmp}" "${_ps_tmp}.lock"
  echo "--- stored plugin-status.json (written by the cron, not by this run) ---"
  cat "${PLUGIN_STATUS_FILE}" 2>/dev/null || echo "(absent — the cron has not run a health check yet)"
else
  echo "(plugin-status.sh absent — stale skill tree; re-run references/bootstrap.sh)"
fi
echo ""
if [[ -f "${SKILL_DIR}/scripts/hooks-status.sh" ]]; then
  REVENIUM_LOG_FILE=/dev/null bash "${SKILL_DIR}/scripts/hooks-status.sh" 2>&1 | head -25
else
  echo "(hooks-status.sh absent — stale skill tree; re-run references/bootstrap.sh)"
fi
echo ""
echo "NOTE: unapproved hooks cost you tool-events only, never completions."

# ---------------------------------------------------------------------------
hr "7. CONFIG + GUARDRAIL STATUS"
echo "--- config.json ---"
cat "${CONFIG_FILE}" 2>/dev/null || echo "!! missing — setup-guardrails.sh has not run"
echo "--- guardrail-status.json ---"
cat "${GUARDRAIL_STATUS_FILE}" 2>/dev/null || echo "(absent — cron has not evaluated rules yet)"

# ---------------------------------------------------------------------------
hr "8. PROFILES ON THIS HOST"
# A single-profile view hides a fleet where only some profiles went stale.
while IFS=$'\t' read -r pname phome; do
  [[ -z "${pname}" ]] && continue
  pstate="${phome}/state/revenium"
  printf '%-16s ledger=%-10s log=%s\n' \
    "${pname}" \
    "$(lines "${pstate}/revenium-hermes.ledger")" \
    "$(mtime "${pstate}/revenium-metering.log")"
done < <(hermes_profile_homes)
echo ""
echo "(re-run with --profile <name> to inspect one of these in full)"

# ---------------------------------------------------------------------------
hr "9. LLM OUTCOME EVALUATION (opt-in, experimental)"
# Read-only, and stays that way: config.json and this profile's own LOG_FILE
# only. No `revenium` CLI call, no write, no --tick behaviour (T-39-12) --
# the existing functional test catches a stray ledger/log write but cannot
# catch a stray API call, so that guarantee lives here in the action, not in
# a test.
while IFS=$'\t' read -r pname phome; do
  [[ -z "${pname}" ]] && continue
  pstate="${phome}/state/revenium"
  pcfg="${pstate}/config.json"
  plog="${pstate}/revenium-metering.log"

  # Mirror classifier.py's _llm_evaluation_enabled / _llm_evaluation_config
  # EXACTLY (T-39-13): `enabled` must be a literal JSON boolean true. The
  # string "true", the integer 1, or any other truthy value reports disabled
  # here because it IS disabled in the runtime -- a truthiness test would be
  # the read-side twin of the sanitize-before-compare defect phase 38 found
  # on the write side. Fail CLOSED on any read error, same as the consumer:
  # a missing or malformed config.json means "off", never a traceback.
  _row="$(CFG="${pcfg}" python3 - <<'PY'
import json, os

try:
    with open(os.environ["CFG"]) as fh:
        data = json.load(fh)
    cfg = data.get("llmOutcomeEvaluation")
    cfg = cfg if isinstance(cfg, dict) else {}
    enabled = cfg.get("enabled") is True
    evaluator = cfg.get("evaluator") or "llm"
    # Mirror evaluators.resolve, not just the fallback: `or "llm"` only
    # catches FALSY values -- 0, "", None, an empty list, an empty dict.
    # A truthy non-string -- an int, a list, a dict, True -- sails
    # through unchanged and would print as though it were a working
    # evaluator name. At runtime resolve rejects it because
    # isinstance(name, str) is False, fn comes back None, and
    # classifier.py logs "unknown evaluator" and returns WITHOUT
    # evaluating -- the same "reports armed, nothing runs" shape
    # T-39-13 fixed for `enabled`. Render it unmistakably as invalid
    # rather than silently coercing to "llm", which would be a
    # different lie: the runtime does not fall back to "llm" here, it
    # skips.
    # NOTE: no apostrophes and no unbalanced parens across lines in this
    # comment block -- bash 3.2 mis-parses a heredoc nested inside
    # $(...) when either shows up, closing the substitution early.
    # Verified with bash -n while writing this fix; a balanced,
    # same-line paren such as isinstance(name, str) above is fine.
    if not isinstance(evaluator, str):
        evaluator = "INVALID(not-a-string)"
except Exception:
    enabled = False
    evaluator = "llm"
print("{}\t{}".format("true" if enabled else "false", evaluator))
PY
)"
  IFS=$'\t' read -r p_enabled p_evaluator <<<"${_row}"
  # IN-01 (39-REVIEW.md): if python3 is unavailable, the heredoc above never
  # runs, `_row` is empty, and this `read` from an empty here-string still
  # succeeds under `set -uo pipefail` -- silently leaving both fields blank
  # rather than erroring. Default explicitly so the row reads "unknown"
  # instead of a blank that looks like an unset/empty config value.
  p_enabled="${p_enabled:-unknown}"
  p_evaluator="${p_evaluator:-unknown}"

  # Two of the six taxonomy words are visible here: "deferred" (plus its aged
  # "wedged" restatement of the same outcome) and "reported". Literal prefixes
  # per 39-01-SUMMARY.md / 39-02-SUMMARY.md -- do not paraphrase a fourth
  # variant of text already fixed by those plans.
  deferred="$(grepcount "${plog}" "outcome deferred: id=")"
  wedged="$(grepcount "${plog}" "wedged job (no create confirmed after")"
  reported="$(grepcount "${plog}" "Outcome reported: agentic_job_id=")"

  printf '%-16s enabled=%-6s evaluator=%-6s deferred=%-8s wedged=%-8s reported=%-8s\n' \
    "${pname}" "${p_enabled}" "${p_evaluator}" "${deferred}" "${wedged}" "${reported}"
done < <(hermes_profile_homes)
echo ""
echo "NOTE: the other four outcomes -- evaluated, abstained, invalid, timed-out"
echo "      -- are written IN-PROCESS by the classifier plugin on the Python"
echo "      logger 'revenium_classifier', not into revenium-metering.log, so"
echo "      they land wherever Hermes' own logging is configured. This report"
echo "      cannot show them; it can only tell you where to look."

# ---------------------------------------------------------------------------
if [[ "${TICK}" == "true" ]]; then
  hr "10. ONE REAL CRON TICK — THIS SHIPS DATA"
  bash "${SKILL_DIR}/scripts/cron.sh" 2>&1 | tail -40
  echo "--- log after the tick ---"
  tail -25 "${LOG_FILE}" 2>/dev/null || echo "(no log)"
fi

echo ""
echo "===== done ====="
exit 0
