#!/usr/bin/env bash
# quick-261029-tyq: operator-declared job-type economics that the "Edit Job
# Type" dialog exposes and nothing else in this skill writes:
#
#   * a pre-AI baseline version (`revenium jobs types baselines append`):
#     cost per unit, human minutes per unit, quality rate, hourly rate,
#     effective from, provenance, evidence URL;
#   * the declared overhead per unit on the type's economics contract
#     (`overheadPerUnit` / `overheadCurrency`, via `economics get` + `set`).
#
# This file is deliberately NOT named anywhere in cron.sh or install-cron.sh.
# A baseline version is PERMANENT -- the API appends, never amends or deletes
# -- and its provenance (CUSTOMER_DECLARED, MEASURED, SIGNED_OFF) is a claim
# about who stands behind the numbers. None of the three describes a model
# estimate, so the classifier's learned figures are shown as SUGGESTIONS only
# and a human must type every value that is declared.
#
# Value per unit (the contract's `monetization` rule) is deliberately not
# offered: a per-unit rate makes Revenium compute a job's Value as rate x
# units and ignore the reported outcomeValue (the $1-per-job bug, #156). An
# existing rule is preserved verbatim; this script never adds one.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

usage() {
  cat <<'USAGE'
Usage: declare-baseline.sh <job_type> [baseline flags] [overhead flags] [--dry-run] [--force]

With no baseline or overhead flags, prints the job type's declared overhead,
the baseline version in force and suggestions learned from this host's job
assessments. Nothing is written.

Baseline version (permanent; appended with `revenium jobs types baselines append`):
  --cost-per-unit <n>      Pre-AI cost to produce one unit.
  --minutes-per-unit <n>   Pre-AI minutes of human effort per unit.
  --quality-rate <0..1>    Pre-AI quality rate.
  --hourly-rate <n>        Fully loaded hourly rate of the human doing the work.
  --currency <CUR>         USD, EUR, GBP, CAD, AUD, JPY or CHF.
  --provenance <P>         Required. CUSTOMER_DECLARED, MEASURED or SIGNED_OFF.
  --declared-by <text>     Who declared it (server defaults to the API key's principal).
  --evidence-url <url>     http(s) link to the supporting evidence, at most 2048 characters.
  --effective-from <ts>    RFC 3339 timestamp with a zone. Defaults to now (UTC).
  At least one of the four numeric fields is required.

Declared overhead (rewrites the economics contract, every other field kept):
  --overhead-per-unit <n>  Declared non-AI overhead per unit.
  --overhead-currency <C>  Defaults to --currency when given, else USD.
  The type must already have an economics contract; the cron outcome-metrics
  stage declares one the first time a reportable job of that type is appended.

  --dry-run   Show the requests the CLI would send; write nothing anywhere.
  --force     Append a baseline even when it repeats one already declared.
  --help, -h  Show this message.

Value per unit is not offered: a per-unit rate replaces each job's reported
value with rate x units. See docs/value-overview.md.
USAGE
}

JOB_TYPE=""
COST_PER_UNIT=""
MINUTES_PER_UNIT=""
QUALITY_RATE=""
HOURLY_RATE=""
CURRENCY=""
PROVENANCE=""
DECLARED_BY=""
EVIDENCE_URL=""
EFFECTIVE_FROM=""
OVERHEAD_PER_UNIT=""
OVERHEAD_CURRENCY=""
DRY_RUN=false
FORCE=false
BASELINE_REQUESTED=false
OVERHEAD_REQUESTED=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cost-per-unit) COST_PER_UNIT="${2:-}"; BASELINE_REQUESTED=true; shift 2 ;;
    --minutes-per-unit) MINUTES_PER_UNIT="${2:-}"; BASELINE_REQUESTED=true; shift 2 ;;
    --quality-rate) QUALITY_RATE="${2:-}"; BASELINE_REQUESTED=true; shift 2 ;;
    --hourly-rate) HOURLY_RATE="${2:-}"; BASELINE_REQUESTED=true; shift 2 ;;
    --currency) CURRENCY="${2:-}"; shift 2 ;;
    --provenance) PROVENANCE="${2:-}"; BASELINE_REQUESTED=true; shift 2 ;;
    --declared-by) DECLARED_BY="${2:-}"; BASELINE_REQUESTED=true; shift 2 ;;
    --evidence-url) EVIDENCE_URL="${2:-}"; BASELINE_REQUESTED=true; shift 2 ;;
    --effective-from) EFFECTIVE_FROM="${2:-}"; BASELINE_REQUESTED=true; shift 2 ;;
    --overhead-per-unit) OVERHEAD_PER_UNIT="${2:-}"; OVERHEAD_REQUESTED=true; shift 2 ;;
    --overhead-currency) OVERHEAD_CURRENCY="${2:-}"; OVERHEAD_REQUESTED=true; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --force) FORCE=true; shift ;;
    --help|-h) usage; exit 0 ;;
    -*) echo "Unknown flag: $1" >&2; usage >&2; exit 2 ;;
    *)
      if [[ -n "${JOB_TYPE}" ]]; then
        echo "Unexpected argument: $1 (job type already given as ${JOB_TYPE})" >&2
        exit 2
      fi
      JOB_TYPE="$1"; shift ;;
  esac
done

if [[ -z "${JOB_TYPE}" ]]; then
  echo "Missing job type." >&2
  usage >&2
  exit 2
fi

# The same id shape tool-event attribution accepts. The type is a path segment
# on the wire (/jobs/types/<type>/baselines), so anything else is refused
# rather than rewritten.
if [[ ! "${JOB_TYPE}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]]; then
  echo "Invalid job type: ${JOB_TYPE}" >&2
  exit 2
fi

# --currency alone (no other baseline flag) only denominates overhead.
if [[ -n "${CURRENCY}" && "${BASELINE_REQUESTED}" != true && "${OVERHEAD_REQUESTED}" != true ]]; then
  echo "--currency needs a baseline or overhead value to denominate." >&2
  exit 2
fi
if [[ "${OVERHEAD_REQUESTED}" == true && -z "${OVERHEAD_PER_UNIT}" ]]; then
  echo "--overhead-currency requires --overhead-per-unit." >&2
  exit 2
fi
if [[ "${OVERHEAD_REQUESTED}" == true && -z "${OVERHEAD_CURRENCY}" ]]; then
  OVERHEAD_CURRENCY="${CURRENCY:-USD}"
fi

if ! command -v revenium >/dev/null 2>&1; then
  echo "revenium CLI not found on PATH." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Local validation of every value BEFORE any request. A baseline cannot be
# taken back, so a decimal slip (quality 9.5 for 0.95) must die here. Emits
# KEY=value lines; any ERR= line aborts.
# ---------------------------------------------------------------------------
VALIDATED="$(
  BASELINE_REQUESTED="${BASELINE_REQUESTED}" OVERHEAD_REQUESTED="${OVERHEAD_REQUESTED}" \
  COST_PER_UNIT="${COST_PER_UNIT}" MINUTES_PER_UNIT="${MINUTES_PER_UNIT}" \
  QUALITY_RATE="${QUALITY_RATE}" HOURLY_RATE="${HOURLY_RATE}" \
  CURRENCY="${CURRENCY}" PROVENANCE="${PROVENANCE}" DECLARED_BY="${DECLARED_BY}" \
  EVIDENCE_URL="${EVIDENCE_URL}" EFFECTIVE_FROM="${EFFECTIVE_FROM}" \
  OVERHEAD_PER_UNIT="${OVERHEAD_PER_UNIT}" OVERHEAD_CURRENCY="${OVERHEAD_CURRENCY}" \
  python3 - <<'PY'
import datetime, math, os

E = os.environ
errs = []
CURRENCIES = ('USD', 'EUR', 'GBP', 'CAD', 'AUD', 'JPY', 'CHF')
PROVENANCES = ('CUSTOMER_DECLARED', 'MEASURED', 'SIGNED_OFF')


def number(flag, raw, hi=None):
    try:
        v = float(raw)
    except ValueError:
        errs.append('%s must be a number, got %r' % (flag, raw))
        return None
    if not math.isfinite(v) or v < 0:
        errs.append('%s must be a finite number >= 0, got %r' % (flag, raw))
        return None
    if hi is not None and v > hi:
        errs.append('%s must be at most %s, got %r' % (flag, hi, raw))
        return None
    return v


if E['BASELINE_REQUESTED'] == 'true':
    nums = [('--cost-per-unit', 'COST_PER_UNIT', None),
            ('--minutes-per-unit', 'MINUTES_PER_UNIT', None),
            ('--quality-rate', 'QUALITY_RATE', 1.0),
            ('--hourly-rate', 'HOURLY_RATE', None)]
    given = [(f, k, hi) for f, k, hi in nums if E[k] != '']
    if not given:
        errs.append('a baseline needs at least one of --cost-per-unit, '
                    '--minutes-per-unit, --quality-rate, --hourly-rate')
    for f, k, hi in given:
        number(f, E[k], hi)
    if E['PROVENANCE'] == '':
        errs.append('--provenance is required: say who stands behind these numbers '
                    '(%s)' % ', '.join(PROVENANCES))
    elif E['PROVENANCE'] not in PROVENANCES:
        errs.append('--provenance must be one of %s, got %r'
                    % (', '.join(PROVENANCES), E['PROVENANCE']))
    money = E['COST_PER_UNIT'] != '' or E['HOURLY_RATE'] != ''
    if money and E['CURRENCY'] == '':
        errs.append('--currency is required with --cost-per-unit or --hourly-rate')
    url = E['EVIDENCE_URL']
    if url and (len(url) > 2048 or not url.startswith(('https://', 'http://'))):
        errs.append('--evidence-url must be an http(s) URL of at most 2048 characters')
    if len(E['DECLARED_BY']) > 256:
        errs.append('--declared-by must be at most 256 characters')
    eff = E['EFFECTIVE_FROM']
    if eff == '':
        eff = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    else:
        try:
            parsed = datetime.datetime.fromisoformat(eff.replace('Z', '+00:00'))
        except ValueError:
            parsed = None
        if parsed is None or parsed.tzinfo is None or 'T' not in eff:
            errs.append('--effective-from must be an RFC 3339 timestamp with a zone, '
                        'e.g. 2026-01-07T00:00:00Z; got %r' % eff)
    print('EFFECTIVE_FROM=' + eff)

if E['CURRENCY'] and E['CURRENCY'] not in CURRENCIES:
    errs.append('--currency must be one of %s, got %r' % (', '.join(CURRENCIES), E['CURRENCY']))

if E['OVERHEAD_REQUESTED'] == 'true':
    number('--overhead-per-unit', E['OVERHEAD_PER_UNIT'])
    if E['OVERHEAD_CURRENCY'] not in CURRENCIES:
        errs.append('--overhead-currency must be one of %s, got %r'
                    % (', '.join(CURRENCIES), E['OVERHEAD_CURRENCY']))

for e in errs:
    print('ERR=' + e)
PY
)"

if grep -q '^ERR=' <<<"${VALIDATED}"; then
  sed -n 's/^ERR=/error: /p' <<<"${VALIDATED}" >&2
  exit 2
fi
EFFECTIVE_FROM="$(sed -n 's/^EFFECTIVE_FROM=//p' <<<"${VALIDATED}")"

# Extract a field from a `revenium ... --output json` blob without jq.
json_field() {
  JSON_BLOB="${1}" FIELD="${2}" python3 - <<'PY' 2>/dev/null || true
import json, os
try:
    d = json.loads(os.environ['JSON_BLOB'])
except Exception:
    raise SystemExit(0)
if isinstance(d, dict):
    v = d.get(os.environ['FIELD'])
    if v is not None:
        print(v)
PY
}

# ---------------------------------------------------------------------------
# Capability probes read help TEXT, never an exit status: cobra prints the
# PARENT's help and exits 0 for an unknown subcommand, so on a CLI without
# `baselines` the `baselines append --help` probe prints `jobs types` help.
# A flag only `append` declares tells the two apart. For economics the
# subcommand's own description is the marker, because `jobs types` help
# quotes `economics get` in its examples.
# ---------------------------------------------------------------------------
has_baselines_verb() {
  supports_flag "jobs types baselines append" "--minutes-per-unit"
}

has_economics_set_verb() {
  local help_text
  help_text="$(revenium jobs types economics --help 2>&1)" || return 1
  [[ "${help_text}" == *"Create or replace"* ]]
}

# ---------------------------------------------------------------------------
# Suggestions: medians over this host's latest assessment per job of the type.
# A model estimate, labelled as one; never applied. One job is one unit in the
# contract the cron declares (`jobs_completed`); an operator-tuned contract
# may count something else, and the report says so.
# ---------------------------------------------------------------------------
print_suggestions() {
  local unit_key="${1:-}"
  ASSESS_DIR="${JOB_ASSESSMENTS_DIR}" JOB_TYPE="${JOB_TYPE}" UNIT_KEY="${unit_key}" python3 - <<'PY' || true
import glob, json, math, os, statistics

job_type = os.environ['JOB_TYPE']
latest = {}
for path in glob.glob(os.path.join(os.environ['ASSESS_DIR'], '*.jsonl')):
    try:
        lines = open(path, encoding='utf-8').read().splitlines()
    except OSError:
        continue
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not isinstance(r, dict) or r.get('kind') != 'job_assessment':
            continue
        if r.get('job_type') != job_type:
            continue
        key = r.get('agentic_job_id') or path
        rank = (r.get('sequence') or 0, r.get('ts') or 0)
        if key not in latest or rank >= latest[key][0]:
            latest[key] = (rank, r)


def finite_pos(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


rows = []
for _, r in latest.values():
    a = r.get('assumptions') if isinstance(r.get('assumptions'), dict) else {}
    hours = finite_pos(a.get('estimated_hours_saved'))
    rate = finite_pos(a.get('assumed_loaded_rate'))
    if hours is not None:
        rows.append((hours, rate, r.get('currency') or ''))

print('Suggestions from this host\'s assessments (MODEL ESTIMATES, never applied):')
if not rows:
    print('  none: no assessment of %s carries an estimated_hours_saved' % job_type)
    raise SystemExit(0)
minutes = statistics.median(h for h, _, _ in rows) * 60
print('  --minutes-per-unit %.1f   (median of %d job(s))' % (minutes, len(rows)))
currencies = [c for _, rate, c in rows if rate is not None and c]
if currencies:
    cur = max(set(currencies), key=currencies.count)
    priced = [(h, rate) for h, rate, c in rows if rate is not None and c == cur]
    print('  --hourly-rate %.2f --currency %s   (median of %d job(s))'
          % (statistics.median(rate for _, rate in priced), cur, len(priced)))
    print('  --cost-per-unit %.2f   (median of hours x rate)'
          % statistics.median(h * rate for h, rate in priced))
unit_key = os.environ.get('UNIT_KEY') or ''
if unit_key and unit_key != 'jobs_completed':
    print('  note: this contract counts units as %r, not one per job; the figures '
          'above are per JOB' % unit_key)
print('  These come from the evaluator, not from a person. None of the three provenance')
print('  values describes a model estimate: declare them only if you stand behind them.')
PY
}

# ---------------------------------------------------------------------------
# Read-only report (no write flags).
# ---------------------------------------------------------------------------
report() {
  local econ unit_key=""
  echo "Job type: ${JOB_TYPE}"
  econ="$(revenium jobs types economics get "${JOB_TYPE}" --output json 2>&1 || true)"
  if [[ "$(json_field "${econ}" status)" == "404" ]]; then
    echo "  economics contract: none declared"
  elif [[ -n "$(json_field "${econ}" status)" ]]; then
    echo "  economics contract: could not read ($(printf '%s' "${econ}" | tr -d '\n' | cut -c1-160))"
  else
    unit_key="$(json_field "${econ}" unitMetricKey)"
    local overhead overhead_cur
    overhead="$(json_field "${econ}" overheadPerUnit)"
    overhead_cur="$(json_field "${econ}" overheadCurrency)"
    echo "  unit: ${unit_key:-?} ($(json_field "${econ}" unitLabel))"
    echo "  declared overhead per unit: ${overhead:-none}${overhead:+ ${overhead_cur}}"
    if [[ -n "$(json_field "${econ}" monetization)" ]]; then
      echo "  WARNING: a value-per-unit (monetization) rule is declared; Revenium computes"
      echo "           each job's Value from it and ignores the reported outcome value."
    fi
  fi
  if has_baselines_verb; then
    local list
    list="$(revenium jobs types baselines list "${JOB_TYPE}" --output json 2>&1 || true)"
    LIST_BLOB="${list}" python3 - <<'PY' || true
import json, os
try:
    d = json.loads(os.environ['LIST_BLOB'])
except ValueError:
    print('  baseline in force: could not read')
    raise SystemExit(0)
if isinstance(d, dict) and d.get('status') == 404:
    d = []
if not isinstance(d, list):
    print('  baseline in force: could not read')
elif not d:
    print('  baseline in force: none declared')
else:
    keys = ('costPerUnit', 'minutesPerUnit', 'qualityRate', 'hourlyRate', 'currency',
            'provenance', 'effectiveFrom')
    print('  baseline in force (%d version(s)): %s' % (len(d), ', '.join(
        '%s=%s' % (k, d[0].get(k)) for k in keys if d[0].get(k) is not None)))
PY
  else
    echo "  baselines: this CLI has no 'jobs types baselines' verbs"
  fi
  echo
  print_suggestions "${unit_key}"
}

# ---------------------------------------------------------------------------
# Declared overhead: read-modify-write of the WHOLE contract. `economics set`
# replaces the document, so everything we read is sent back verbatim and only
# the two overhead keys change. stdin is /dev/null so the CLI's "this replace
# would remove something, confirm" prompt can never be answered: if our round
# trip ever loses a field, the set fails instead of deleting it.
# ---------------------------------------------------------------------------
set_overhead() {
  if ! has_economics_set_verb; then
    echo "error: this CLI has no 'jobs types economics set'; upgrade the revenium CLI." >&2
    return 1
  fi
  local econ status
  econ="$(revenium jobs types economics get "${JOB_TYPE}" --output json 2>&1 || true)"
  status="$(json_field "${econ}" status)"
  if [[ "${status}" == "404" ]]; then
    echo "error: ${JOB_TYPE} has no economics contract to add overhead to." >&2
    echo "       The cron outcome-metrics stage declares one the first time a reportable" >&2
    echo "       job of this type is appended; or declare one with" >&2
    echo "       'revenium jobs types economics set ${JOB_TYPE} --file <doc>'." >&2
    return 1
  fi
  if [[ -n "${status}" ]]; then
    echo "error: could not read the economics contract for ${JOB_TYPE}: $(printf '%s' "${econ}" | tr -d '\n' | cut -c1-200)" >&2
    return 1
  fi

  local doc
  doc="$(mktemp 2>/dev/null || echo "/tmp/revenium-overhead.$$")"
  if ! JSON_BLOB="${econ}" OVERHEAD="${OVERHEAD_PER_UNIT}" OVERHEAD_CUR="${OVERHEAD_CURRENCY}" \
      python3 - >"${doc}" <<'PY'
import json, os, sys
try:
    d = json.loads(os.environ['JSON_BLOB'])
except ValueError:
    sys.exit(1)
if not isinstance(d, dict) or not isinstance(d.get('metrics'), list):
    sys.exit(1)
# Read-only keys: the CLI strips them anyway, and says so on stderr.
d.pop('jobType', None)
d.pop('currentBaseline', None)
d['overheadPerUnit'] = float(os.environ['OVERHEAD'])
d['overheadCurrency'] = os.environ['OVERHEAD_CUR']
# `monetization` is sent back exactly as read: omitting it would DELETE an
# operator's rule, and this script never creates one.
d.setdefault('monetization', None)
print(json.dumps(d, indent=2))
PY
  then
    rm -f "${doc}" 2>/dev/null
    echo "error: the economics contract for ${JOB_TYPE} is not a document this script understands; nothing written." >&2
    return 1
  fi

  local cmd=(revenium jobs types economics set "${JOB_TYPE}" --file "${doc}" --output json)
  [[ "${DRY_RUN}" == true ]] && cmd+=(--dry-run)
  local out rc=0
  out="$("${cmd[@]}" </dev/null 2>&1)" || rc=$?
  rm -f "${doc}" 2>/dev/null
  if [[ ${rc} -ne 0 ]]; then
    if [[ "$(json_field "${out}" status)" == "429" ]]; then
      echo "error: throttled (429); the contract was not changed. Retry shortly." >&2
    else
      echo "error: could not set overhead for ${JOB_TYPE}; the contract was not changed:" >&2
      printf '%s\n' "${out}" >&2
    fi
    return 1
  fi
  if [[ "${DRY_RUN}" == true ]]; then
    echo "Dry run: would set overhead per unit ${OVERHEAD_PER_UNIT} ${OVERHEAD_CURRENCY} on ${JOB_TYPE}:"
    printf '%s\n' "${out}"
  else
    echo "Set declared overhead per unit on ${JOB_TYPE}: ${OVERHEAD_PER_UNIT} ${OVERHEAD_CURRENCY}"
  fi
}

# ---------------------------------------------------------------------------
# Baseline append. Two duplicate guards, either one refusing unless --force:
#   1. the local ledger: the same declared values were appended before (any
#      effective date -- a re-run computes a new "now");
#   2. the server: the version in force already carries these exact values.
# The ledger line is written only after a successful append. If the CLI fails
# after the server accepted (a timeout), guard 2 catches the re-run.
# ---------------------------------------------------------------------------
append_baseline() {
  if ! has_baselines_verb; then
    echo "error: this CLI has no 'jobs types baselines append'; upgrade the revenium CLI." >&2
    return 1
  fi

  local digest
  digest="$(
    COST_PER_UNIT="${COST_PER_UNIT}" MINUTES_PER_UNIT="${MINUTES_PER_UNIT}" \
    QUALITY_RATE="${QUALITY_RATE}" HOURLY_RATE="${HOURLY_RATE}" CURRENCY="${CURRENCY}" \
    PROVENANCE="${PROVENANCE}" DECLARED_BY="${DECLARED_BY}" EVIDENCE_URL="${EVIDENCE_URL}" \
    python3 - <<'PY'
import hashlib, json, os
E = os.environ
doc = {k: (float(E[k]) if k in ('COST_PER_UNIT', 'MINUTES_PER_UNIT', 'QUALITY_RATE',
                                'HOURLY_RATE') else E[k])
       for k in ('COST_PER_UNIT', 'MINUTES_PER_UNIT', 'QUALITY_RATE', 'HOURLY_RATE',
                 'CURRENCY', 'PROVENANCE', 'DECLARED_BY', 'EVIDENCE_URL') if E[k] != ''}
print(hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()[:12])
PY
  )"

  if [[ "${FORCE}" != true ]]; then
    local prior
    prior="$(grep -F "BASELINE:${JOB_TYPE}:${digest}:" "${BASELINES_LEDGER_FILE}" 2>/dev/null | tail -1 || true)"
    if [[ -n "${prior}" ]]; then
      echo "error: these baseline values were already appended for ${JOB_TYPE} (${prior})." >&2
      echo "       Baselines are permanent; pass --force to append them again anyway." >&2
      return 1
    fi

    local list verdict
    list="$(revenium jobs types baselines list "${JOB_TYPE}" --output json 2>&1 || true)"
    verdict="$(
      LIST_BLOB="${list}" COST_PER_UNIT="${COST_PER_UNIT}" MINUTES_PER_UNIT="${MINUTES_PER_UNIT}" \
      QUALITY_RATE="${QUALITY_RATE}" HOURLY_RATE="${HOURLY_RATE}" CURRENCY="${CURRENCY}" \
      PROVENANCE="${PROVENANCE}" python3 - <<'PY'
import json, os
E = os.environ
try:
    d = json.loads(E['LIST_BLOB'])
except ValueError:
    print('UNKNOWN'); raise SystemExit(0)
if isinstance(d, dict) and d.get('status') == 404:
    d = []
if not isinstance(d, list):
    print('UNKNOWN'); raise SystemExit(0)
if not d or not isinstance(d[0], dict):
    print('NEW'); raise SystemExit(0)
cur = d[0]
pairs = [('costPerUnit', 'COST_PER_UNIT'), ('minutesPerUnit', 'MINUTES_PER_UNIT'),
         ('qualityRate', 'QUALITY_RATE'), ('hourlyRate', 'HOURLY_RATE')]
same = True
for wire, env in pairs:
    if E[env] == '':
        continue
    try:
        same = same and abs(float(cur.get(wire)) - float(E[env])) < 1e-9
    except (TypeError, ValueError):
        same = False
for wire, env in (('currency', 'CURRENCY'), ('provenance', 'PROVENANCE')):
    if E[env] != '':
        same = same and cur.get(wire) == E[env]
print('SAME' if same else 'NEW')
PY
    )"
    case "${verdict}" in
      SAME)
        echo "error: the baseline in force for ${JOB_TYPE} already declares these values." >&2
        echo "       Pass --force to append an identical version anyway." >&2
        return 1 ;;
      NEW) ;;
      *)
        echo "error: could not read the baselines of ${JOB_TYPE} to check for a duplicate: $(printf '%s' "${list}" | tr -d '\n' | cut -c1-200)" >&2
        echo "       Nothing appended; pass --force to append without the check." >&2
        return 1 ;;
    esac
  fi

  local cmd=(revenium jobs types baselines append "${JOB_TYPE}" --provenance "${PROVENANCE}"
             --effective-from "${EFFECTIVE_FROM}" --output json)
  [[ -n "${COST_PER_UNIT}" ]] && cmd+=(--cost-per-unit "${COST_PER_UNIT}")
  [[ -n "${MINUTES_PER_UNIT}" ]] && cmd+=(--minutes-per-unit "${MINUTES_PER_UNIT}")
  [[ -n "${QUALITY_RATE}" ]] && cmd+=(--quality-rate "${QUALITY_RATE}")
  [[ -n "${HOURLY_RATE}" ]] && cmd+=(--hourly-rate "${HOURLY_RATE}")
  [[ -n "${CURRENCY}" ]] && cmd+=(--currency "${CURRENCY}")
  [[ -n "${DECLARED_BY}" ]] && cmd+=(--declared-by "${DECLARED_BY}")
  [[ -n "${EVIDENCE_URL}" ]] && cmd+=(--evidence-url "${EVIDENCE_URL}")
  [[ "${DRY_RUN}" == true ]] && cmd+=(--dry-run)

  local out rc=0
  out="$("${cmd[@]}" </dev/null 2>&1)" || rc=$?
  if [[ ${rc} -ne 0 ]]; then
    if [[ "$(json_field "${out}" status)" == "429" ]]; then
      echo "error: throttled (429); nothing appended. Retry shortly." >&2
    else
      echo "error: baseline append for ${JOB_TYPE} failed:" >&2
      printf '%s\n' "${out}" >&2
    fi
    return 1
  fi
  if [[ "${DRY_RUN}" == true ]]; then
    echo "Dry run: would append this PERMANENT baseline version to ${JOB_TYPE}:"
    printf '%s\n' "${out}"
    return 0
  fi
  mkdir -p "$(dirname "${BASELINES_LEDGER_FILE}")" 2>/dev/null || true
  printf 'BASELINE:%s:%s:%s\n' "${JOB_TYPE}" "${digest}" "$(date +%s)" >> "${BASELINES_LEDGER_FILE}"
  info "declare-baseline: appended baseline for job_type=${JOB_TYPE} digest=${digest} provenance=${PROVENANCE} effective_from=${EFFECTIVE_FROM}"
  echo "Appended baseline version to ${JOB_TYPE} (effective ${EFFECTIVE_FROM}, ${PROVENANCE})."
}

main() {
  if [[ "${BASELINE_REQUESTED}" != true && "${OVERHEAD_REQUESTED}" != true ]]; then
    report
    return 0
  fi
  local rc=0
  # Overhead first: it is a replaceable setting, the baseline is permanent. A
  # failed overhead write stops before anything permanent happens.
  if [[ "${OVERHEAD_REQUESTED}" == true ]]; then
    set_overhead || return 1
  fi
  if [[ "${BASELINE_REQUESTED}" == true ]]; then
    append_baseline || rc=1
  fi
  return "${rc}"
}

main "$@"
