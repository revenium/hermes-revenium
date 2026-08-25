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
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --job-id) JOB_ID="${2:-}"; shift 2 ;;
    --value) VALUE="${2:-}"; shift 2 ;;
    --value-low) VALUE_LOW="${2:-}"; shift 2 ;;
    --value-high) VALUE_HIGH="${2:-}"; shift 2 ;;
    --currency) CURRENCY="${2:-}"; shift 2 ;;
    --reason) REASON="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "${JOB_ID}" || -z "${VALUE}" || -z "${CURRENCY}" || -z "${REASON}" ]]; then
  echo "Missing required flag(s) -- --job-id, --value, --currency, and --reason are all required." >&2
  usage >&2
  exit 2
fi

# D-03: a bare --value with no range flags produces an equal-bounds record.
[[ -z "${VALUE_LOW}" ]] && VALUE_LOW="${VALUE}"
[[ -z "${VALUE_HIGH}" ]] && VALUE_HIGH="${VALUE}"

# --------------------------------------------------------------------------
# Step 1+2: resolve the sidecar path and perform the D-14 refusal check in
# ONE pass -- both need the same filename component and the same read of
# the file, so doing them together avoids a second independent read that
# could observe a different file state.
#
# The filename component is derived through the SAME three-step transform
# `_sidecar_filename_component` in classifier.py uses (a fifth independent
# copy, deliberate per CLAUDE.md's no-shared-code-across-the-two-halves
# rule): the five-character sanitize tuple, then the A-Za-z0-9._- filename-
# safety pass, then the empty/dot/dot-dot guard. This is also the value
# used below for `assessment_id` and the jobs-ledger correction line, so
# the whole script has one internally-consistent notion of "this job's
# identity on disk" rather than a second hand-maintained transform.
# --------------------------------------------------------------------------
RESOLVE_OUTPUT=$(JOB_ID_PY="${JOB_ID}" JOB_ASSESSMENTS_DIR_PY="${JOB_ASSESSMENTS_DIR}" python3 - <<'PY'
import json
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
sidecar_path = os.path.join(assessments_dir, f'{component}.jsonl')
target_clean = _clean(raw_job_id)

print(f'COMPONENT={component}')
print(f'SIDECAR_PATH={sidecar_path}')

found = None
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
    except OSError:
        pass

print(f'LINE_COUNT={line_count}')
print(f'CORRECTION_COUNT={correction_count}')
if found is None:
    print('FOUND=0')
else:
    print('FOUND=1')
    print(f"CURRENT_VALUE_LOW={found.get('value_low', '')}")
    print(f"CURRENT_VALUE_BASE={found.get('value_base', '')}")
    print(f"CURRENT_VALUE_HIGH={found.get('value_high', '')}")
    print(f"CURRENT_CURRENCY={found.get('currency', '')}")
PY
)

COMPONENT=$(printf '%s\n' "${RESOLVE_OUTPUT}" | sed -n 's/^COMPONENT=//p')
SIDECAR_PATH=$(printf '%s\n' "${RESOLVE_OUTPUT}" | sed -n 's/^SIDECAR_PATH=//p')
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
# of existing lines (to compute `sequence`) and the append happen under
# ONE lock acquisition (fcntl.LOCK_EX), so the sequence can never be
# computed against a stale count. O_APPEND + LOCK_EX mirrors
# _write_job_assessment's own append discipline exactly.
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
  python3 - <<'PY'
import fcntl
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

# 'a+b' opens with O_APPEND (writes always land at EOF regardless of the
# current seek position) while still allowing the read needed to compute
# `sequence` -- both happen under the SAME flock acquisition below.
with open(path, 'a+b', buffering=0) as f:
    fcntl.flock(f, fcntl.LOCK_EX)
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
        'value_low': _num(os.environ.get('VALUE_LOW_PY', '')),
        'value_base': _num(os.environ.get('VALUE_PY', '')),
        'value_high': _num(os.environ.get('VALUE_HIGH_PY', '')),
        'currency': os.environ.get('CURRENCY_PY', ''),
        'reason': reason,
    }
    line_bytes = (json.dumps(record, separators=(',', ':'), ensure_ascii=True) + '\n').encode('utf-8')
    f.write(line_bytes)

print(f'SEQUENCE={sequence}')
print(f'TS={now}')
PY
)

SEQUENCE=$(printf '%s\n' "${APPEND_OUTPUT}" | sed -n 's/^SEQUENCE=//p')
CORRECTION_TS=$(printf '%s\n' "${APPEND_OUTPUT}" | sed -n 's/^TS=//p')

echo "Local correction saved: job='${JOB_ID}' sequence=${SEQUENCE} sidecar=${SIDECAR_PATH}"

# --------------------------------------------------------------------------
# Step 6: append the ledger line. `correction` is neither `outcome` nor
# `created` -- OUTCOME-01 (`^JOB:<id>:outcome:`) and OUTCOME-04
# (`^JOB:<id>:created:`) fail to match this line at the very first
# character of the differing word, which is what keeps the ordinary
# per-tick path neither unblocked nor re-triggered by a correction. Plan
# 42-01 proved this disjointness against a real ledger before this script
# existed; this line is what plan 42-06 asserts it against.
# --------------------------------------------------------------------------
echo "JOB:${COMPONENT}:correction:${SEQUENCE}:${CORRECTION_TS}" >> "${JOBS_LEDGER_FILE}"

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
print(json.dumps(meta, separators=(',', ':')))
PY
)

outcome_update_cmd=(
  revenium jobs outcome-update "${JOB_ID}"
  --reason "${REASON}"
  --outcome-value "${VALUE}"
  --outcome-currency "${CURRENCY}"
  --metadata "${OUTCOME_UPDATE_METADATA}"
  --quiet
)
TEAM_ID_RESOLVED="$(resolve_team_id)"
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
