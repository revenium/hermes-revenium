#!/usr/bin/env bash
# Phase 42 Plan 06 (D-01/D-02/EGV-09): operator-triggered correction of a
# JobAssessment sidecar record. Appends a `kind:"correction"` line to the
# job's sidecar file (never rewrites the original), appends a distinct
# `JOB:<id>:correction:<seq>:<ts>` line to the jobs ledger (structurally
# unmatchable by the ordinary path's OUTCOME-01/OUTCOME-04 grep gates --
# proven against a real ledger in plan 42-01, before this script existed),
# and, when the installed revenium CLI supports it, ships the correction to
# Revenium via `revenium jobs outcome-update`.
#
# This file is deliberately NOT named anywhere in cron.sh or install-cron.sh
# -- correction code must never be reachable from the per-tick pipeline
# (D-02). It is invoked only by a human operator at a terminal.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

# No ensure_path — correct-assessment.sh is a human-facing operator CLI;
# cron PATH extension is not needed here (same posture as clear-halt.sh).

usage() {
  cat <<'USAGE'
Usage: correct-assessment.sh --job-id <id> --value <n> --currency <CUR> --reason <text>
                              [--value-low <n>] [--value-high <n>] [--dry-run]

Files a correction against a job's JobAssessment sidecar record (EGV-09).
The original record and every earlier correction are preserved -- this
appends a new correction line, it never rewrites what is already there.
When the installed revenium CLI supports 'jobs outcome-update', the
correction is also shipped to Revenium; an older CLI still saves the local
correction but exits non-zero (D-04 -- fail loudly, never silently skip).

  --job-id      Required. The agentic_job_id whose assessment is being corrected.
  --value       Required. The corrected value (the point/base estimate).
  --value-low   Optional. Corrected low bound. Defaults to --value (equal bounds).
  --value-high  Optional. Corrected high bound. Defaults to --value (equal bounds).
  --currency    Required. One of: USD, EUR, GBP, CAD, AUD, JPY, CHF.
  --reason      Required. Audit-trail text explaining the correction.
  --dry-run     Preview the correction; writes nothing, locally or remotely.
  --help, -h    Show this message.
USAGE
}

JOB_ID=""
VALUE=""
VALUE_LOW=""
VALUE_HIGH=""
CURRENCY=""
REASON=""
MECHANISM=""
MECHANISM_GIVEN=false
ATTRIBUTION_FRACTION=""
ATTRIBUTION_FRACTION_GIVEN=false
ATTRIBUTION_BASIS=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --job-id) JOB_ID="${2:-}"; shift 2 ;;
    --value) VALUE="${2:-}"; shift 2 ;;
    --value-low) VALUE_LOW="${2:-}"; shift 2 ;;
    --value-high) VALUE_HIGH="${2:-}"; shift 2 ;;
    --currency) CURRENCY="${2:-}"; shift 2 ;;
    --reason) REASON="${2:-}"; shift 2 ;;
    --mechanism) MECHANISM="${2:-}"; MECHANISM_GIVEN=true; shift 2 ;;
    --attribution-fraction) ATTRIBUTION_FRACTION="${2:-}"; ATTRIBUTION_FRACTION_GIVEN=true; shift 2 ;;
    --attribution-basis) ATTRIBUTION_BASIS="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
done

# D-08: --value (and the --currency that denominates it) are required
# UNLESS --mechanism is supplied. A mechanism-only correction is legal --
# EGV-10 holds mechanism and value apart, and economic_mechanism already
# travels without a value on the not-reportable path (it is absent from
# hermes-report.sh's _VALUE_OMIT_FAMILY, whose docstring records that
# withholding the VALUE does not withhold the fact that a record exists).
# --job-id and --reason stay unconditionally required: this script's whole
# purpose is an auditable trail, and neither is ever meaningless.
if [[ -z "${JOB_ID}" || -z "${REASON}" ]]; then
  echo "Missing required flag(s) -- --job-id and --reason are always required." >&2
  usage >&2
  exit 2
fi

if [[ "${MECHANISM_GIVEN}" != true && -z "${VALUE}" ]]; then
  echo "Missing required flag(s) -- --value is required unless --mechanism is supplied." >&2
  usage >&2
  exit 2
fi

# A currency with no amount denominates nothing.
if [[ -n "${VALUE}" && -z "${CURRENCY}" ]]; then
  echo "Missing required flag(s) -- --currency is required whenever --value is supplied." >&2
  usage >&2
  exit 2
fi

# Range flags without a base value have nothing to bound.
if [[ -z "${VALUE}" && ( -n "${VALUE_LOW}" || -n "${VALUE_HIGH}" ) ]]; then
  echo "--value-low/--value-high require --value." >&2
  exit 2
fi

# MECH-01: the six declared economic mechanisms, in classifier.py's
# ECONOMIC_MECHANISMS order. This is a THIRD declaration of that vocabulary
# (classifier.py and hermes-report.sh hold the other two), so a drift test
# pins it -- the repo already treats the first two as a hazard worth testing.
#
# Discipline mirrored from _resolve_economic_mechanism, with one deliberate
# divergence. Mirrored: `.strip()` is applied and `.lower()` is NOT, because
# per D-03 an out-of-set value must not be coerced, and case-folding is
# coercion. Diverged: that function ABSTAINS to unknown on a bad value
# because it runs on the per-tick path; this is an interactive operator CLI
# where D-04 already establishes the opposite posture -- fail loudly, since
# "a silently-skipped correction is worse than a refused one". So an
# unrecognised mechanism is a non-zero exit, never an abstention.
_MECHANISMS="labor_substitution augmentation_capacity_expansion newly_enabled_work quality_decision_improvement risk_avoidance incremental_revenue"

# Gate on whether the FLAG was supplied, not on whether its value is
# non-empty: `--mechanism ""` is an explicit request carrying an
# out-of-set value, and silently treating it as "no mechanism" would be
# the coercion this allow-list exists to refuse.
if [[ "${MECHANISM_GIVEN}" == true ]]; then
  # shellcheck disable=SC2295
  MECHANISM="${MECHANISM#"${MECHANISM%%[![:space:]]*}"}"
  MECHANISM="${MECHANISM%"${MECHANISM##*[![:space:]]}"}"
  _found=false
  for _m in ${_MECHANISMS}; do
    [[ "${MECHANISM}" == "${_m}" ]] && { _found=true; break; }
  done
  if [[ "${_found}" != true ]]; then
    echo "Unsupported --mechanism '${MECHANISM}'." >&2
    echo "Must be exactly one of: ${_MECHANISMS// /, }" >&2
    echo "Matching is case-sensitive and exact -- an out-of-set value is refused, never coerced." >&2
    exit 2
  fi
fi

# D-01/D-05: the attribution pair. The operator supplies the ALREADY
# ATTRIBUTED value; this script multiplies nothing and never sees a gross
# figure. The fraction and basis document how the operator reached the
# value they passed.
#
# The fraction cannot be validated against anything -- there is no gross
# here to check it against, by design, because keeping a full business
# figure out of an agent-metering record is the only structural defence
# against cross-system double counting available at this layer. So the
# fraction is an ASSERTION, and the one constraint worth having is that it
# may never travel naked: --attribution-basis is REQUIRED whenever
# --attribution-fraction is supplied. A bare number has the authority of a
# measurement with none of the accountability; a cited one is auditable.
if [[ "${ATTRIBUTION_FRACTION_GIVEN}" == true ]]; then
  if [[ -z "${ATTRIBUTION_BASIS//[[:space:]]/}" ]]; then
    echo "--attribution-fraction requires --attribution-basis." >&2
    echo "A declared fraction is an operator assertion, not a measurement -- it must carry the stated basis it rests on." >&2
    exit 2
  fi
  ATTRIBUTION_ERROR=$(ATTRIBUTION_FRACTION_PY="${ATTRIBUTION_FRACTION}" python3 - <<'ATTRPY'
import math
import os

raw = os.environ.get('ATTRIBUTION_FRACTION_PY', '')
# Mirrors _finite_number's rejection set (classifier.py), including the
# OverflowError guard added under PR #109 -- float() raises on an
# arbitrary-precision int, and this flag takes operator input.
try:
    f = float(raw)
except OverflowError:
    print('--attribution-fraction is too large to represent')
    raise SystemExit(0)
except (TypeError, ValueError):
    print(f'--attribution-fraction {raw!r} is not a number')
    raise SystemExit(0)
if math.isnan(f) or math.isinf(f):
    print('--attribution-fraction must be finite')
    raise SystemExit(0)
if not (0.0 <= f <= 1.0):
    print(f'--attribution-fraction must be between 0 and 1 inclusive (got {f})')
    raise SystemExit(0)
ATTRPY
)
  if [[ -n "${ATTRIBUTION_ERROR}" ]]; then
    echo "Invalid input: ${ATTRIBUTION_ERROR}" >&2
    exit 2
  fi
fi

if [[ -n "${ATTRIBUTION_BASIS//[[:space:]]/}" && "${ATTRIBUTION_FRACTION_GIVEN}" != true ]]; then
  echo "--attribution-basis requires --attribution-fraction." >&2
  exit 2
fi

# D-03: a bare --value with no range flags produces an equal-bounds record.
# Guarded on VALUE (D-08): with no value there is nothing to equal, and
# defaulting the bounds to "" would write three empty value keys rather than
# omitting them.
if [[ -n "${VALUE}" ]]; then
  [[ -z "${VALUE_LOW}" ]] && VALUE_LOW="${VALUE}"
  [[ -z "${VALUE_HIGH}" ]] && VALUE_HIGH="${VALUE}"
fi

# --------------------------------------------------------------------------
# Step 1: resolve the sidecar path AND the ledger-line id -- a pure string
# transform over JOB_ID and JOB_ASSESSMENTS_DIR, no file I/O. Split out from
# the read that used to follow it in the same pass (see the lock block
# immediately below for why): the path must be known BEFORE anything can be
# locked, but resolving it needs no lock of its own.
#
# Two DELIBERATELY DIFFERENT transforms of the same raw job id, kept
# distinct on purpose (WR-01, 42-REVIEW.md):
#
#   COMPONENT -- the filename component, derived through the SAME
#   three-step transform `_sidecar_filename_component` in classifier.py uses
#   (a fifth independent copy, deliberate per CLAUDE.md's no-shared-code-
#   across-the-two-halves rule): the five-character sanitize tuple, then the
#   A-Za-z0-9._- filename-safety pass, then the empty/dot/dot-dot guard.
#   This is what protects against path traversal (a job id of `../../evil`
#   must never escape JOB_ASSESSMENTS_DIR) and is used for the sidecar path
#   and `assessment_id` below. It must stay the fuller transform -- do not
#   weaken it to fix WR-01.
#
#   LEDGER_ID -- for the `JOB:<id>:correction:...` ledger line ONLY, using
#   the SAME five-character-only transform hermes-report.sh's ordinary path
#   uses for `clean_id`/`outcome_id`/`precheck_clean_job_id` (see
#   hermes-report.sh's `_bad_chars = (':', ' ', '\t', '\n', '\r')`, applied
#   with no filename-safety pass on top). `agentic_job_id` is LLM-generated
#   free text -- `_validate_job` in classifier.py only requires a non-empty
#   string and, unlike `job_type`, never checks it against LABEL_RE -- so an
#   apostrophe, parenthesis, or comma can survive into it. Before this fix,
#   such a job id made the ordinary path's `created:`/`outcome:` lines keep
#   the punctuation verbatim while this script's `correction:` line replaced
#   it with `_`, so the two no longer shared the same `<id>` substring and an
#   operator's `^JOB:<id>:` grep for a job's full history came back
#   incomplete. Using the identical narrow transform here restores that
#   correlation, without touching the filename-safe COMPONENT the path
#   traversal protection depends on.
# --------------------------------------------------------------------------
PATH_OUTPUT=$(JOB_ID_PY="${JOB_ID}" JOB_ASSESSMENTS_DIR_PY="${JOB_ASSESSMENTS_DIR}" python3 - <<'PY'
import os
import re

raw_job_id = os.environ.get('JOB_ID_PY', '')
assessments_dir = os.environ.get('JOB_ASSESSMENTS_DIR_PY', '')


def _clean(v):
    for bad in (':', ' ', '\t', '\n', '\r'):
        v = v.replace(bad, '_')
    return v


def _sidecar_filename_component(raw):
    if not isinstance(raw, str):
        return '_'
    value = _clean(raw)
    value = re.sub(r'[^A-Za-z0-9._-]', '_', value)
    if value in ('', '.', '..'):
        return '_'
    return value


component = _sidecar_filename_component(raw_job_id)
# WR-01: the ledger-line id uses ONLY the narrow five-character transform --
# the same one hermes-report.sh's ordinary path applies via `_clean` above,
# deliberately WITHOUT the filename-safety pass `component` layers on top,
# so a `JOB:<id>:correction:...` line shares its `<id>` substring with that
# same job's `created:`/`outcome:` lines even when the raw id carries
# punctuation outside [A-Za-z0-9._-].
ledger_id = _clean(raw_job_id)
sidecar_path = os.path.join(assessments_dir, f'{component}.jsonl')

print(f'COMPONENT={component}')
print(f'LEDGER_ID={ledger_id}')
print(f'SIDECAR_PATH={sidecar_path}')
PY
)

COMPONENT=$(printf '%s\n' "${PATH_OUTPUT}" | sed -n 's/^COMPONENT=//p')
LEDGER_ID=$(printf '%s\n' "${PATH_OUTPUT}" | sed -n 's/^LEDGER_ID=//p')
SIDECAR_PATH=$(printf '%s\n' "${PATH_OUTPUT}" | sed -n 's/^SIDECAR_PATH=//p')

# --------------------------------------------------------------------------
# Race-closing lock (Greptile P1, PR #94 follow-up). Prior to this, the
# D-14 existence check (Step 2 below) ran UNLOCKED, and the append (old
# Step 5) released its own lock the instant its heredoc exited -- Step 6's
# ledger append and Step 8's remote ship ran AFTER that, with nothing held.
# prune-markers.sh's os.unlink took no per-sidecar lock either (only the
# global prune.lock), so it never blocked on the append's brief hold. Two
# st_nlink checks (still below, unchanged) narrowed the window an unlink
# could land in; narrowing is not closing it -- this project has now
# learned that lesson three times, twice already on this very PR. Only
# mutual exclusion closes it: acquire ONE lock here, covering the D-14
# check through the remote ship (Step 8), and release only at the very end.
#
# `exec 9<"${SIDECAR_PATH}"` -- `<`, deliberately NOT `<>`. Bash's `<>`
# opens for read/write and CREATES the file if it is missing, which would
# reintroduce exactly the O_CREAT vivification bug PR #94's Step 5 fix
# already closed once (a correction script must never be able to conjure a
# sidecar into existence). flock() locks the INODE, not a particular open
# mode, so a read-only fd serializes against any other cooperating locker
# (this script and prune-markers.sh's job-assessments pass) just as well as
# a read/write one would; Step 5 below still writes through its own
# O_RDWR|O_APPEND descriptor, opened separately.
#
# A missing sidecar must produce the ordinary D-14 refusal, never bash's
# raw "No such file or directory" redirection diagnostic. `exec` with only
# redirections (no command) is special-cased by bash to abort the whole
# (non-interactive) shell on a failed redirection, bypassing `set -e` and
# any surrounding `if`/`||` guard on the exec form itself -- confirmed
# against this repo's bash 3.2 -- so the existence is probed with `[[ -e ]]`
# FIRST (avoiding the attempt entirely in the common case), and the `exec`
# itself is wrapped in a `{ ...; }` group with its own `2>/dev/null` so even
# a probe-to-exec TOCTOU (the file vanishing in between) degrades to a
# catchable, silent failure rather than an uncatchable shell exit.
# --------------------------------------------------------------------------
if [[ ! -e "${SIDECAR_PATH}" ]]; then
  echo "No assessment record found for job '${JOB_ID}' (sidecar absent, unreadable, or pruned) -- cannot correct (D-14)." >&2
  echo "An operator willing to lose the audit trail can still correct the row with the revenium CLI directly." >&2
  exit 1
fi
if ! { exec 9<"${SIDECAR_PATH}"; } 2>/dev/null; then
  echo "No assessment record found for job '${JOB_ID}' (sidecar absent, unreadable, or pruned) -- cannot correct (D-14)." >&2
  echo "An operator willing to lose the audit trail can still correct the row with the revenium CLI directly." >&2
  exit 1
fi
if ! python3 - <<'PY'
import fcntl
import sys

try:
    # Blocking, deliberately: two operators correcting the same job, or an
    # operator correcting while a manual prune-markers.sh is mid-check on
    # this exact file, should serialize rather than one of them failing
    # outright. prune-markers.sh's own acquisition (job-assessments pass)
    # is non-blocking and skips instead -- a manual prune must never make an
    # operator's correction wait, but an operator's correction MAY make a
    # manual prune wait one tick's worth of skip-and-retry-later.
    fcntl.flock(9, fcntl.LOCK_EX)
except OSError as exc:
    print(f'flock(LOCK_EX) failed on the sidecar: {exc}', file=sys.stderr)
    sys.exit(1)
PY
then
  echo "Failed to acquire the assessment lock for job '${JOB_ID}' -- cannot correct." >&2
  exit 1
fi

# --------------------------------------------------------------------------
# Step 2: the D-14 existence / effective-assessment read, NOW performed
# under the lock acquired above -- this is the change that actually closes
# the race: nothing between here and Step 8's remote ship can be
# invalidated by a cooperating prune anymore, because a cooperating prune
# must take the same lock before it may unlink (see prune-markers.sh).
# --------------------------------------------------------------------------
RESOLVE_OUTPUT=$(JOB_ID_PY="${JOB_ID}" SIDECAR_PATH_PY="${SIDECAR_PATH}" python3 - <<'PY'
import json
import os

raw_job_id = os.environ.get('JOB_ID_PY', '')
sidecar_path = os.environ.get('SIDECAR_PATH_PY', '')


def _clean(v):
    for bad in (':', ' ', '\t', '\n', '\r'):
        v = v.replace(bad, '_')
    return v


target_clean = _clean(raw_job_id)

found = None
valued = None
line_count = 0
correction_count = 0
if os.path.exists(sidecar_path):
    try:
        with open(sidecar_path) as f:
            for line in f:
                raw_line = line.rstrip('\n')
                if not raw_line:
                    continue
                line_count += 1
                try:
                    rec = json.loads(raw_line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(rec, dict):
                    continue
                if rec.get('kind') not in ('job_assessment', 'correction'):
                    continue
                raw_id = rec.get('agentic_job_id')
                if not isinstance(raw_id, str) or _clean(raw_id) != target_clean:
                    continue
                if rec.get('kind') == 'correction':
                    correction_count += 1
                # Deliberate: no break -- scan-to-end, same convention the
                # reader in hermes-report.sh uses (41-CARRIER-DECISION.md
                # Part 2's last-match-wins property).
                found = rec
                # Greptile (PR #110), Phase 51 D-08: track the last record
                # that actually CARRIED a value, separately from the last
                # record overall.
                #
                # A mechanism-only correction has no value family, so on a
                # plain last-match-wins read the NEXT correction would
                # snapshot its absent values and write an empty
                # prior_value_*. Two chained mechanism-only corrections
                # would then leave nothing for the reporter to promote, and
                # the standing valuation would vanish from the wire --
                # exactly the defect the one-level promotion was meant to
                # close, one link further down the chain.
                #
                # Fixed at the WRITE side so prior_value_* always records
                # the true standing value, however many valueless
                # corrections precede it. That keeps every correction record
                # self-describing rather than requiring a reader to walk
                # backwards through history.
                if rec.get('value_base') is not None:
                    valued = rec
                elif rec.get('kind') == 'correction' and rec.get('prior_value_base') is not None:
                    # A valueless correction still carries the standing
                    # value it inherited; carry it forward unchanged.
                    valued = {
                        'value_low': rec.get('prior_value_low'),
                        'value_base': rec.get('prior_value_base'),
                        'value_high': rec.get('prior_value_high'),
                        'currency': rec.get('prior_currency'),
                    }
    except OSError:
        pass

print(f'LINE_COUNT={line_count}')
print(f'CORRECTION_COUNT={correction_count}')
if found is None:
    print('FOUND=0')
else:
    print('FOUND=1')
    # Emitted from `valued`, not `found`: the standing value survives any
    # number of valueless corrections in between.
    _v = valued if valued is not None else {}
    print(f"CURRENT_VALUE_LOW={_v.get('value_low') if _v.get('value_low') is not None else ''}")
    print(f"CURRENT_VALUE_BASE={_v.get('value_base') if _v.get('value_base') is not None else ''}")
    print(f"CURRENT_VALUE_HIGH={_v.get('value_high') if _v.get('value_high') is not None else ''}")
    print(f"CURRENT_CURRENCY={_v.get('currency') if _v.get('currency') is not None else ''}")
PY
)

FOUND=$(printf '%s\n' "${RESOLVE_OUTPUT}" | sed -n 's/^FOUND=//p')
LINE_COUNT=$(printf '%s\n' "${RESOLVE_OUTPUT}" | sed -n 's/^LINE_COUNT=//p')
CORRECTION_COUNT=$(printf '%s\n' "${RESOLVE_OUTPUT}" | sed -n 's/^CORRECTION_COUNT=//p')

# D-14: refuse a correction against an absent or pruned sidecar record.
# Nothing is written, locally or remotely, when this fires.
if [[ "${FOUND}" != "1" ]]; then
  echo "No assessment record found for job '${JOB_ID}' (sidecar absent, unreadable, or pruned) -- cannot correct (D-14)." >&2
  echo "An operator willing to lose the audit trail can still correct the row with the revenium CLI directly." >&2
  exit 1
fi

CURRENT_VALUE_LOW=$(printf '%s\n' "${RESOLVE_OUTPUT}" | sed -n 's/^CURRENT_VALUE_LOW=//p')
CURRENT_VALUE_BASE=$(printf '%s\n' "${RESOLVE_OUTPUT}" | sed -n 's/^CURRENT_VALUE_BASE=//p')
CURRENT_VALUE_HIGH=$(printf '%s\n' "${RESOLVE_OUTPUT}" | sed -n 's/^CURRENT_VALUE_HIGH=//p')
CURRENT_CURRENCY=$(printf '%s\n' "${RESOLVE_OUTPUT}" | sed -n 's/^CURRENT_CURRENCY=//p')

echo "Current effective assessment for job '${JOB_ID}': value_low=${CURRENT_VALUE_LOW} value_base=${CURRENT_VALUE_BASE} value_high=${CURRENT_VALUE_HIGH} currency=${CURRENT_CURRENCY} (${CORRECTION_COUNT} prior correction(s))"

# --------------------------------------------------------------------------
# Step 3: validate the operator's input BEFORE any write or CLI call. This
# is the security boundary of the whole script -- operator-supplied text
# reaching a billing verb. Finite, non-negative, non-strictly-ordered
# bounds and a supported currency, or refuse.
# --------------------------------------------------------------------------
# D-08: the value validators below have nothing to validate on a
# mechanism-only correction. Skipped rather than made lenient -- when a
# value IS supplied every original rule still applies unchanged.
VALIDATION_ERROR=""
if [[ -n "${VALUE}" ]]; then
VALIDATION_ERROR=$(VALUE_PY="${VALUE}" VALUE_LOW_PY="${VALUE_LOW}" VALUE_HIGH_PY="${VALUE_HIGH}" CURRENCY_PY="${CURRENCY}" python3 - <<'PY'
import math
import os

_SUPPORTED_CURRENCIES = frozenset({'USD', 'EUR', 'GBP', 'CAD', 'AUD', 'JPY', 'CHF'})


def _finite(raw):
    try:
        f = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


low = _finite(os.environ.get('VALUE_LOW_PY', ''))
base = _finite(os.environ.get('VALUE_PY', ''))
high = _finite(os.environ.get('VALUE_HIGH_PY', ''))

if low is None or base is None or high is None:
    print('--value, --value-low, and --value-high must all be finite numbers')
    raise SystemExit(0)
if low < 0 or base < 0 or high < 0:
    print('--value, --value-low, and --value-high must all be non-negative')
    raise SystemExit(0)
if not (low <= base <= high):
    print(f'bounds must satisfy --value-low <= --value <= --value-high (got {low} <= {base} <= {high})')
    raise SystemExit(0)

currency = os.environ.get('CURRENCY_PY', '').strip().upper()
if currency not in _SUPPORTED_CURRENCIES:
    print(f'--currency {currency!r} is not supported (must be one of {sorted(_SUPPORTED_CURRENCIES)})')
    raise SystemExit(0)
PY
)
fi

if [[ -n "${VALIDATION_ERROR}" ]]; then
  echo "Invalid input: ${VALIDATION_ERROR}" >&2
  exit 2
fi

CURRENCY="$(printf '%s' "${CURRENCY}" | tr '[:lower:]' '[:upper:]')"

# --------------------------------------------------------------------------
# Step 4: probe the CLI capability. Resolved in the guard form ONLY -- an
# `if supports_flag ...; then VAR=true; fi` whose body sets the capability
# variable -- never `VAR=$(supports_flag ...)`, which discards the exit
# status supports_flag's three-way outcome depends on (D-04).
# --------------------------------------------------------------------------
OUTCOME_UPDATE_CLI_CAPABLE=false
if supports_flag "jobs outcome-update" "--reason"; then
  OUTCOME_UPDATE_CLI_CAPABLE=true
fi

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "[dry-run] Would append correction sequence ${LINE_COUNT} for job '${JOB_ID}' (component=${COMPONENT}):"
  echo "[dry-run]   prior: value_low=${CURRENT_VALUE_LOW} value_base=${CURRENT_VALUE_BASE} value_high=${CURRENT_VALUE_HIGH} currency=${CURRENT_CURRENCY}"
  echo "[dry-run]   new:   value_low=${VALUE_LOW} value_base=${VALUE} value_high=${VALUE_HIGH} currency=${CURRENCY}"
  echo "[dry-run]   reason: ${REASON}"
  if [[ "${OUTCOME_UPDATE_CLI_CAPABLE}" == "true" ]]; then
    echo "[dry-run] revenium CLI supports 'jobs outcome-update' -- would ship this correction to Revenium."
  else
    echo "[dry-run] revenium CLI does NOT support 'jobs outcome-update' -- would save the local correction only and exit non-zero (D-04)."
  fi
  echo "[dry-run] No file, ledger, or CLI call was made -- --dry-run performs no writes, local or remote."
  exit 0
fi

# --------------------------------------------------------------------------
# Step 5: write the local correction line FIRST, before any network call,
# so nothing is lost when the remote leg fails or is unsupported. The read
# of existing lines (to compute `sequence`) and the append happen under the
# fd9 lock acquired above (held continuously since before Step 2), so the
# sequence can never be computed against a stale count and nothing else
# cooperating can be appending or unlinking underneath this. O_APPEND
# mirrors _write_job_assessment's own append discipline exactly.
#
# WR-02 (42-REVIEW.md): Step 1+2's original D-14 refusal check (now Step 2,
# above) used to read the sidecar with NO lock held, and this append's own
# internal flock() released the instant this heredoc exited -- both closed
# by the fd9 lock now held end-to-end (see the block above Step 2). This
# open is STILL opened WITHOUT O_CREAT and its existence is STILL
# re-verified via st_nlink, both retained deliberately (see the heredoc
# below) as defense in depth against a deleter that predates this change or
# does not honor the fd9 lock protocol -- flock is advisory, so a bare `rm`
# or an unpatched prune-markers.sh is not stopped by it.
# --------------------------------------------------------------------------
APPEND_OUTPUT=$(
  SIDECAR_PATH_PY="${SIDECAR_PATH}" \
  JOB_ID_PY="${JOB_ID}" \
  COMPONENT_PY="${COMPONENT}" \
  VALUE_PY="${VALUE}" \
  VALUE_LOW_PY="${VALUE_LOW}" \
  VALUE_HIGH_PY="${VALUE_HIGH}" \
  CURRENCY_PY="${CURRENCY}" \
  PRIOR_VALUE_LOW_PY="${CURRENT_VALUE_LOW}" \
  PRIOR_VALUE_BASE_PY="${CURRENT_VALUE_BASE}" \
  PRIOR_VALUE_HIGH_PY="${CURRENT_VALUE_HIGH}" \
  PRIOR_CURRENCY_PY="${CURRENT_CURRENCY}" \
  REASON_PY="${REASON}" \
  MECHANISM_PY="${MECHANISM}" \
  ATTRIBUTION_FRACTION_PY="${ATTRIBUTION_FRACTION}" \
  ATTRIBUTION_BASIS_PY="${ATTRIBUTION_BASIS}" \
  python3 - <<'PY'
import json
import os
import time


def _num(raw):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _clamp_reason(raw, limit=500):
    # Same rule as NARRATIVE_CLAMP_BYTES elsewhere in this schema family:
    # SERIALIZED bytes, not characters (ensure_ascii=True escapes every
    # non-ASCII code point up to 6x/12x its character count). Also strips
    # the IFS-unsafe characters this repo's pipe-delimited transports rely
    # on staying clean.
    v = raw.strip()
    for bad in ('|', '\n', '\r'):
        v = v.replace(bad, ' ')
    while len(json.dumps(v, ensure_ascii=True).encode('utf-8')) > limit and v:
        v = v[:-1]
    return v


path = os.environ.get('SIDECAR_PATH_PY', '')
job_id = os.environ.get('JOB_ID_PY', '')
component = os.environ.get('COMPONENT_PY', '')
reason = _clamp_reason(os.environ.get('REASON_PY', ''))

# WR-02 (42-REVIEW.md), CLOSED for good by the fd9 lock held since before
# Step 2: a cooperating deleter (this script's own earlier D-14 check, or
# prune-markers.sh's job-assessments pass, both updated to take the same
# per-sidecar lock) literally cannot unlink this file while we hold fd9.
# The two defenses below are retained anyway, as defense in depth against
# an UNCOOPERATING deleter -- a bare `rm`, a hand-rolled script, or a
# not-yet-upgraded prune-markers.sh that has never heard of this lock.
# flock() is advisory: it only serializes against other processes that
# also call flock() on the same file, never against unlink() itself.
#
#   1. Open WITHOUT O_CREAT (os.O_RDWR | os.O_APPEND, no os.O_CREAT). The
#      open() syscall itself becomes the atomic "does this path exist
#      right now" test -- there is no separate check-then-act step left to
#      race, and a missing file raises FileNotFoundError instead of being
#      silently vivified (the OLD code opened with 'a+b', which CREATES
#      the file if missing -- silently turning a should-be-refused
#      correction into a brand-new sidecar whose only line is the
#      correction, with no original `job_assessment` line ever having
#      existed; that is precisely the D-14 invariant this script exists to
#      enforce). O_APPEND is kept so writes still land at EOF regardless of
#      seek position, matching the original append discipline exactly.
#   2. Re-verify os.fstat(fd).st_nlink != 0 immediately after the open
#      above, and again after the write below. This is NOT re-acquiring a
#      lock -- a second flock() call on a second fd for the same file
#      would deadlock against the fd9 lock this process's own parent shell
#      already holds (flock locks are scoped to the open file description,
#      not the process; a same-process second open+flock on the same inode
#      blocks on the first, and here the "first" is held by an ancestor
#      that is waiting on THIS subprocess to exit -- proven with a two-fd
#      same-process reproduction before this fix was written). st_nlink
#      drops to 0 the instant no path points at the inode anymore --
#      fd-local and race-free, unlike os.path.exists(path), which asks
#      about the PATH rather than the specific inode this fd already holds
#      open, and would not detect an uncooperating unlink+recreate at all.
try:
    fd = os.open(path, os.O_RDWR | os.O_APPEND)
except FileNotFoundError:
    print('REFUSED_TOCTOU=1')
    raise SystemExit(0)

with os.fdopen(fd, 'r+b', buffering=0) as f:
    if os.fstat(f.fileno()).st_nlink == 0:
        print('REFUSED_TOCTOU=1')
        raise SystemExit(0)
    f.seek(0)
    sequence = 0
    for line in f:
        if line.rstrip(b'\n'):
            sequence += 1
    now = time.time()
    record = {
        'kind': 'correction',
        'ts': now,
        'agentic_job_id': job_id,
        'assessment_id': f'{component}:{sequence}',
        'sequence': sequence,
        'assessment_schema_version': 1,
        'prior_value_low': _num(os.environ.get('PRIOR_VALUE_LOW_PY', '')),
        'prior_value_base': _num(os.environ.get('PRIOR_VALUE_BASE_PY', '')),
        'prior_value_high': _num(os.environ.get('PRIOR_VALUE_HIGH_PY', '')),
        'prior_currency': os.environ.get('PRIOR_CURRENCY_PY', ''),
        'reason': reason,
    }
    # D-08: on a mechanism-only correction the value family is ABSENT, not
    # null and not zero -- the same distinction the value docs draw for an
    # abstained record. `prior_value_*` above still records what stood
    # before, so the history stays walkable; this line simply does not
    # restate a valuation the operator never supplied.
    _value_base = _num(os.environ.get('VALUE_PY', ''))
    if _value_base is not None:
        record['value_low'] = _num(os.environ.get('VALUE_LOW_PY', ''))
        record['value_base'] = _value_base
        record['value_high'] = _num(os.environ.get('VALUE_HIGH_PY', ''))
        record['currency'] = os.environ.get('CURRENCY_PY', '')
    # MECH-01/MECH-04: the operator-declared mechanism, already validated
    # against the six-member allow-list in the shell above.
    _mechanism = os.environ.get('MECHANISM_PY', '')
    if _mechanism:
        record['economic_mechanism'] = _mechanism
    # D-05: the attribution pair, recorded as documentation of how the
    # operator reached the value above. Nothing is multiplied here, and no
    # gross figure exists to multiply. The basis is clamped exactly as the
    # reason is -- this metadata path has no ceiling of its own, so an
    # unbounded operator string is the one way to blow the envelope from
    # this direction.
    _fraction = os.environ.get('ATTRIBUTION_FRACTION_PY', '')
    if _fraction:
        record['attribution_fraction'] = float(_fraction)
        record['attribution_basis'] = _clamp_reason(
            os.environ.get('ATTRIBUTION_BASIS_PY', ''))
    line_bytes = (json.dumps(record, separators=(',', ':'), ensure_ascii=True) + '\n').encode('utf-8')
    f.write(line_bytes)
    # Greptile P1 (PR #94), CLOSED for good by the fd9 lock: this check used
    # to be the ONLY thing standing between a concurrent, uncoordinated
    # prune-markers.sh unlink and a write succeeding against an orphaned
    # inode -- bytes that vanish when the last fd closes, while the shell
    # goes on to append the ledger line and ship the remote outcome-update,
    # telling the operator it worked. prune-markers.sh's job-assessments
    # pass now takes this SAME lock before it may unlink, so a cooperating
    # prune cannot land here at all. Retained as defense in depth against an
    # uncooperating deleter (see the block comment above the open() call):
    # once this check passes the record lives in a file that still has a
    # name, so any LATER unlink is ordinary pruning rather than a lost
    # write. Refusing here (before SEQUENCE is emitted) is what keeps the
    # shell from writing the ledger line or shipping -- leaving no local
    # record, no remote correction and no ledger line, which a re-run then
    # reports truthfully as D-14.
    os.fsync(f.fileno())
    if os.fstat(f.fileno()).st_nlink == 0:
        print('REFUSED_TOCTOU=1')
        raise SystemExit(0)

print(f'SEQUENCE={sequence}')
print(f'TS={now}')
# Greptile P1 (PR #93): the CLAMPED reason must go back to the shell so the
# remote `outcome-update --reason` ships byte-identically what the sidecar
# recorded. Sending the raw ${REASON} here let the local audit record and
# the correction filed at Revenium disagree whenever _clamp_reason stripped
# a character, trimmed whitespace, or truncated past 500 serialized bytes --
# on the one script whose whole purpose is an accurate audit trail.
# Safe as a single KEY=value line: _clamp_reason has already replaced every
# '\n'/'\r'/'|' with a space, so the value cannot span lines.
print(f'REASON_CLAMPED={reason}')
PY
)

# WR-02 (42-REVIEW.md): the heredoc above refuses (prints only this marker,
# writes nothing) when its st_nlink defense-in-depth finds the sidecar
# gone. Under the fd9 lock held since before Step 2, a cooperating deleter
# (prune-markers.sh's job-assessments pass) cannot have caused this; if it
# fires, the file was removed by something that never took the lock at all
# -- a bare `rm` or an un-upgraded prune-markers.sh. Checked BEFORE parsing
# SEQUENCE/TS below, which are meaningless (empty) on this path.
REFUSED_TOCTOU=$(printf '%s\n' "${APPEND_OUTPUT}" | sed -n 's/^REFUSED_TOCTOU=//p')
if [[ "${REFUSED_TOCTOU}" == "1" ]]; then
  echo "Sidecar record for job '${JOB_ID}' disappeared between the existence check and the correction append (likely a concurrent prune) -- refusing without writing (D-14)." >&2
  echo "Re-run this exact command; if the record was legitimately pruned, an operator willing to lose the audit trail can still correct the row with the revenium CLI directly." >&2
  exit 1
fi

SEQUENCE=$(printf '%s\n' "${APPEND_OUTPUT}" | sed -n 's/^SEQUENCE=//p')
CORRECTION_TS=$(printf '%s\n' "${APPEND_OUTPUT}" | sed -n 's/^TS=//p')
# Greptile P1 (PR #93): ship what was RECORDED, not what was typed. Fall back
# to the raw reason only if the emission is somehow absent, so a parsing
# failure degrades to today's behaviour rather than shipping an empty reason.
REASON_SHIPPED=$(printf '%s\n' "${APPEND_OUTPUT}" | sed -n 's/^REASON_CLAMPED=//p')
if [[ -z "${REASON_SHIPPED}" ]]; then
  REASON_SHIPPED="${REASON}"
fi

echo "Local correction saved: job='${JOB_ID}' sequence=${SEQUENCE} sidecar=${SIDECAR_PATH}"

# --------------------------------------------------------------------------
# Step 6: append the ledger line. `correction` is neither `outcome` nor
# `created` -- OUTCOME-01 (`^JOB:<id>:outcome:`) and OUTCOME-04
# (`^JOB:<id>:created:`) fail to match this line at the very first
# character of the differing word, which is what keeps the ordinary
# per-tick path neither unblocked nor re-triggered by a correction. Plan
# 42-01 proved this disjointness against a real ledger before this script
# existed; this line is what plan 42-06 asserts it against.
#
# WR-01 (42-REVIEW.md): uses LEDGER_ID, not COMPONENT -- the narrow
# five-character transform, matching hermes-report.sh's `created:`/
# `outcome:` lines for the SAME job id byte-for-byte, so a single
# `^JOB:<id>:` grep returns a job's complete history regardless of
# punctuation in the raw agentic_job_id. COMPONENT stays reserved for the
# sidecar filename, where the extra filename-safety pass is load-bearing
# for path-traversal protection.
# --------------------------------------------------------------------------
echo "JOB:${LEDGER_ID}:correction:${SEQUENCE}:${CORRECTION_TS}" >> "${JOBS_LEDGER_FILE}"

# --------------------------------------------------------------------------
# Step 7: fail loudly when the CLI cannot ship it. D-04's deliberate
# divergence from this repo's fail-open norm: fail-open is right for the
# per-tick path, but an operator running one command interactively can act
# on an error, and a silently-skipped correction is worse than a refused
# one. The local record and the ledger line above are already saved.
# --------------------------------------------------------------------------
if [[ "${OUTCOME_UPDATE_CLI_CAPABLE}" != "true" ]]; then
  echo "revenium CLI does not support 'jobs outcome-update --reason' -- the local correction was saved, but NOT shipped to Revenium." >&2
  echo "Upgrade to a revenium CLI release that supports 'jobs outcome-update' (run 'revenium jobs outcome-update --help' to check) and re-run this exact command." >&2
  exit 1
fi

# --------------------------------------------------------------------------
# Step 8: ship it. Built as an array per the project's long-invocation
# convention. On a non-zero exit, the local record is already intact and
# the command may be re-run -- no automatic retry.
#
# --metadata carries the same prior-value/sequence provenance the local
# correction line records, so the revision on Revenium's side is
# traceable back to what it superseded without a second round trip.
# --------------------------------------------------------------------------
OUTCOME_UPDATE_METADATA=$(
  SEQUENCE_PY="${SEQUENCE}" \
  PRIOR_VALUE_LOW_PY="${CURRENT_VALUE_LOW}" \
  PRIOR_VALUE_BASE_PY="${CURRENT_VALUE_BASE}" \
  PRIOR_VALUE_HIGH_PY="${CURRENT_VALUE_HIGH}" \
  PRIOR_CURRENCY_PY="${CURRENT_CURRENCY}" \
  MECHANISM_PY="${MECHANISM}" \
  ATTRIBUTION_FRACTION_PY="${ATTRIBUTION_FRACTION}" \
  ATTRIBUTION_BASIS_PY="${ATTRIBUTION_BASIS}" \
  python3 - <<'PY'
import json
import os


def _num(raw):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


meta = {
    'assessment_schema_version': 1,
    'sequence': int(os.environ.get('SEQUENCE_PY', '0') or '0'),
}
for key, env_key in (
    ('prior_value_low', 'PRIOR_VALUE_LOW_PY'),
    ('prior_value_base', 'PRIOR_VALUE_BASE_PY'),
    ('prior_value_high', 'PRIOR_VALUE_HIGH_PY'),
):
    v = _num(os.environ.get(env_key, ''))
    if v is not None:
        meta[key] = v
prior_currency = os.environ.get('PRIOR_CURRENCY_PY', '')
if prior_currency:
    meta['prior_currency'] = prior_currency
# MECH-04: the declared mechanism travels with the correction, so the
# revision filed at Revenium says WHY the value changed, not only that
# it did. Validated against the six-member allow-list in the shell.
mechanism = os.environ.get('MECHANISM_PY', '')
if mechanism:
    meta['economic_mechanism'] = mechanism
# D-07: the attribution assumption travels with the value it
# documents. A value whose attribution is invisible downstream is
# exactly the failure the claim-distinctions doc warns about --
# the number travels and the caveat does not.
fraction = os.environ.get('ATTRIBUTION_FRACTION_PY', '')
if fraction:
    meta['attribution_fraction'] = float(fraction)
    basis = os.environ.get('ATTRIBUTION_BASIS_PY', '').strip()
    for _bad in ('|', '\n', '\r'):
        basis = basis.replace(_bad, ' ')
    while len(json.dumps(basis, ensure_ascii=True).encode('utf-8')) > 500 and basis:
        basis = basis[:-1]
    meta['attribution_basis'] = basis
print(json.dumps(meta, separators=(',', ':')))
PY
)

outcome_update_cmd=(
  revenium jobs outcome-update "${JOB_ID}"
  --reason "${REASON_SHIPPED}"
)
# D-08: --outcome-value is a float64 flag; passing "" on a mechanism-only
# correction would be a malformed invocation, not an omission. Appended
# conditionally, the same way every other optional flag in this repo is.
if [[ -n "${VALUE}" ]]; then
  outcome_update_cmd+=(--outcome-value "${VALUE}" --outcome-currency "${CURRENCY}")
fi
outcome_update_cmd+=(
  --metadata "${OUTCOME_UPDATE_METADATA}"
  --quiet
)
# WR-03 (42-REVIEW.md): resolve_team_id (common.sh) is a PIPELINE
# (`revenium config show | sed | sed | head -1 | tr -d ...`) -- a
# DIFFERENT call from the `jobs outcome-update --help` capability probe
# above, so its success proves nothing about this one. Under this script's
# `set -euo pipefail`, an unguarded `TEAM_ID_RESOLVED="$(resolve_team_id)"`
# lets a transient `revenium config show` failure (auth, network) kill the
# script via `set -e` BEFORE any diagnostic reaches the operator --
# strictly AFTER Steps 5-6 already durably saved the local correction and
# the ledger line, so nothing is lost, but the operator gets no signal at
# all that the ship-to-Revenium leg never ran. That is the exact failure
# D-04's own rationale rules out ("a silently-skipped correction is worse
# than a refused one"). Guarded the same way every other fallible call in
# this file already is -- `... && x=0 || x=$?` -- so this one is fail-loud
# too, matching Step 7's message shape.
TEAM_ID_RESOLVED="$(resolve_team_id)" && team_id_exit=0 || team_id_exit=$?
if [[ "${team_id_exit}" -ne 0 ]]; then
  echo "revenium config show failed while resolving team id (exit ${team_id_exit}) -- the local correction was saved, but NOT shipped to Revenium." >&2
  echo "The local correction record is intact; this command may be re-run once the underlying issue is fixed." >&2
  exit 1
fi
if [[ -n "${TEAM_ID_RESOLVED}" ]]; then
  outcome_update_cmd+=(--team-id "${TEAM_ID_RESOLVED}")
fi

cmd_output=$("${outcome_update_cmd[@]}" 2>&1) && cmd_exit=0 || cmd_exit=$?

if [[ "${cmd_exit}" -ne 0 ]]; then
  echo "revenium jobs outcome-update failed (exit ${cmd_exit}): ${cmd_output}" >&2
  echo "The local correction record is intact; this command may be re-run once the underlying issue is fixed." >&2
  exit 1
fi

echo "Correction shipped to Revenium: job='${JOB_ID}' sequence=${SEQUENCE}"

# --------------------------------------------------------------------------
# Release the fd9 lock explicitly on the success path. Every refusal path
# above exits non-zero instead, which releases it just as well via process
# exit -- explicit release is only needed here, at the one place execution
# falls off the end of the script.
# --------------------------------------------------------------------------
exec 9<&-
