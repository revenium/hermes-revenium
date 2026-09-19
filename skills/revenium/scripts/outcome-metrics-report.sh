#!/usr/bin/env bash
# Append per-job outcome metrics from the ROI assessment sidecars, so the
# platform's Outcome timeline reflects what the classifier already computed
# locally. Until this existed the timeline could only be populated by hand:
# no deployed CLI carried `jobs outcome-metrics` and nothing in this skill
# called it, so a one-off operator backfill was the only source and every job
# created afterwards showed an empty panel.
#
# `set -uo pipefail` WITHOUT `-e`, matching hermes-report.sh: this loop must
# survive a per-job failure and keep going. One job whose economics contract
# is missing, or whose append is throttled, must not abandon the rest.
#
# THE STAKES, because they shape every decision below: an append is
# PERMANENT. The API never deduplicates (its own help says "two identical
# measurements are two measurements"), offers no amendment, no deletion, and
# no read-back -- the spec declares an OutcomeMetricEntry_Read shape and no
# endpoint among its 302 operations produces it. So a double-append cannot be
# detected afterwards, let alone undone, and OUTCOME_METRICS_LEDGER_FILE is
# the only thing standing between a retry and permanently doubled customer
# ROI data.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

# The COUNT metric that satisfies unitMetricKey. One job is one unit, so its
# value is always 1 -- it exists to satisfy the contract's cross-field rule
# ("unitMetricKey must name a COUNT metric"), not because anything varies.
OM_UNIT_METRIC_KEY="jobs_completed"

DRY_RUN=false
for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=true ;;
    *) echo "Unknown flag: ${arg}" >&2; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Capability probe -- MUST read the help TEXT, never an exit status.
#
# 44 of the CLI's 49 parent commands exit 0 on an unknown subcommand and print
# the PARENT's help, because cobra returns flag.ErrHelp at its `!c.Runnable()`
# check before ever validating args. So on a CLI without this verb:
#
#   revenium jobs outcome-metrics --help   -> prints `jobs` help, exit 0
#
# An exit-status probe therefore reports "supported", we invoke a verb that
# does not exist, the help text lands on stdout, the exit code is 0, and we
# write ledger lines for an append that never happened -- silent data loss
# that looks exactly like success, and self-concealing, because the ledger
# then suppresses every retry. Grepping the verb list is the only probe that
# distinguishes the two.
# ---------------------------------------------------------------------------
has_outcome_metrics_verb() {
  local help_text
  help_text="$(revenium jobs --help 2>/dev/null)" || return 1
  [[ "${help_text}" == *"outcome-metrics"* ]]
}

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
# 429 is detected from the JSON body's `status`, NEVER from the exit code.
# The CLI has no 429 arm in internal/errors/exitcodes.go, so a throttled
# request falls through to ExitGeneral and exits 1 -- indistinguishable from
# any unknown failure, with no reason text because the server sends no body.
# A caller branching on exit status cannot tell "slow down, retry next tick"
# from "this failed permanently", and the difference decides whether we
# defer or give up.
# ---------------------------------------------------------------------------
is_throttled() {
  [[ "$(json_field "${1}" status)" == "429" ]]
}

# ---------------------------------------------------------------------------
# Economics: GET first, SET only on 404.
#
# `economics set` is a WHOLE-DOCUMENT REPLACE. It fetches the current contract
# and demands --yes only when the replace would REMOVE something already
# declared, so create-if-absent runs unattended with no confirmation and no
# TTY. That asymmetry is what makes this safe to automate, and it is also why
# we must never pass --yes from cron: a --yes demand means a contract already
# exists and our document would destroy part of it, which is the tool telling
# us a human tuned that type. In that case we leave it alone and append
# against whatever they declared.
# ---------------------------------------------------------------------------
ensure_economics_contract() {
  local job_type="${1}"
  local out
  out="$(revenium jobs types economics get "${job_type}" --output json 2>&1)"
  if is_throttled "${out}"; then
    return 2
  fi
  if [[ "$(json_field "${out}" status)" != "404" ]]; then
    # A contract exists: adopt ITS unitMetricKey rather than assuming ours.
    # The per-job COUNT metric must be one the contract actually declares, and
    # an operator-tuned type may name it anything. Hardcoding our own would
    # append an undeclared key and take a 400 on every job of that type,
    # forever, with the failure reading like a server problem rather than our
    # assumption.
    local declared
    declared="$(json_field "${out}" unitMetricKey)"
    if [[ -n "${declared}" ]]; then
      printf '%s\n' "${declared}"
    else
      printf '%s\n' "${OM_UNIT_METRIC_KEY}"
    fi
    return 0
  fi

  if [[ "${DRY_RUN}" == "true" ]]; then
    info "outcome-metrics: dry-run, would declare economics for job_type=${job_type}"
    return 0
  fi

  local doc
  doc="$(mktemp 2>/dev/null || echo "/tmp/revenium-econ.$$")"
  UNIT_KEY="${OM_UNIT_METRIC_KEY}" python3 - >"${doc}" <<'PY'
import json, os
unit = os.environ['UNIT_KEY']
# No `dimensions` and no PERIOD metric: dimensions and period facts belong to
# the `types facts` path, which this script never calls. Declaring what we
# cannot satisfy would leave the contract permanently under-reported.
print(json.dumps({
    "metrics": [
        {"key": "estimated_value", "type": "MONEY", "direction": "HIGHER_IS_BETTER",
         "aggregation": "SUM", "resolution": "PER_JOB"},
        {"key": "hours_saved", "type": "DURATION", "direction": "HIGHER_IS_BETTER",
         "aggregation": "SUM", "resolution": "PER_JOB"},
        {"key": "assessment_confidence", "type": "SCORE", "direction": "HIGHER_IS_BETTER",
         "aggregation": "AVG", "resolution": "PER_JOB"},
        {"key": unit, "type": "COUNT", "direction": "HIGHER_IS_BETTER",
         "aggregation": "SUM", "resolution": "PER_JOB"},
    ],
    # unitMetricKey must name a COUNT metric -- a cross-field rule the CLI
    # does not pre-check, so pointing it at estimated_value costs a server
    # round-trip and a 400.
    "unitMetricKey": unit,
    "unitLabel": "Jobs completed",
    "monetization": {"category": "COST_AVOIDED", "basis": "EXPECTED",
                     "currency": "USD", "metricKey": "estimated_value",
                     "valuePerUnit": 1.0},
}, indent=2))
PY

  local set_out
  set_out="$(revenium jobs types economics set "${job_type}" --file "${doc}" 2>&1)"
  local rc=$?
  rm -f "${doc}" 2>/dev/null
  if is_throttled "${set_out}"; then
    return 2
  fi
  if [[ ${rc} -ne 0 ]]; then
    warn "outcome-metrics: could not declare economics for job_type=${job_type}: $(printf '%s' "${set_out}" | tr -d '\n' | cut -c1-160)"
    return 1
  fi
  info "outcome-metrics: declared economics contract for job_type=${job_type}"
  printf '%s\n' "${OM_UNIT_METRIC_KEY}"
  return 0
}

main() {
  if ! command -v revenium >/dev/null 2>&1; then
    warn "outcome-metrics: revenium CLI not found; skipping"
    exit 0
  fi
  if ! has_outcome_metrics_verb; then
    # Fail open and SILENT-ish: every install on a CLI without the verb would
    # otherwise warn every minute forever.
    info "outcome-metrics: this CLI has no 'jobs outcome-metrics' verb; stage is a no-op"
    exit 0
  fi
  if [[ "${REVENIUM_OUTCOME_METRICS_MAX_JOBS}" == "0" ]]; then
    info "outcome-metrics: disabled (REVENIUM_OUTCOME_METRICS_MAX_JOBS=0)"
    exit 0
  fi

  ensure_path
  mkdir -p "$(dirname "${OUTCOME_METRICS_LEDGER_FILE}")" 2>/dev/null
  touch "${OUTCOME_METRICS_LEDGER_FILE}" 2>/dev/null

  # Build the work list: one line per job, TAB-separated, already
  # range-validated. Validation happens HERE rather than at the append site so
  # a bad value can never reach a permanent, unreadable, undeletable write.
  local work
  work="$(
    ASSESS_DIR="${JOB_ASSESSMENTS_DIR}" \
    LEDGER="${OUTCOME_METRICS_LEDGER_FILE}" \
    MAX_JOBS="${REVENIUM_OUTCOME_METRICS_MAX_JOBS}" \
    UNIT_KEY="${OM_UNIT_METRIC_KEY}" \
    python3 - <<'PY' 2>/dev/null
import datetime, glob, json, os, sys

assess_dir = os.environ['ASSESS_DIR']
ledger_path = os.environ['LEDGER']
unit_key = os.environ['UNIT_KEY']
try:
    max_jobs = int(os.environ['MAX_JOBS'])
except ValueError:
    max_jobs = 25

# Declared type per metric key. This is the knowledge the CLI cannot have --
# it would need the contract, which means a network call in a path documented
# as request-free -- and it is why the range check lives here.
DECLARED = {
    'estimated_value': 'MONEY',
    'hours_saved': 'DURATION',
    'assessment_confidence': 'SCORE',
    unit_key: 'COUNT',
}

def in_range(metric_type, value):
    """SCORE and PERCENT are 0..1; the quantities are non-negative.

    The CLI bounds exactly ONE key, the literal `quality_rate`, because that
    is the only bound the spec states -- and it states it in free text on the
    value property, not as a schema constraint. Our SCORE metric is therefore
    completely unchecked downstream: a 0.7 -> 7.0 decimal slip is accepted
    client-side and lands permanently.
    """
    if metric_type in ('SCORE', 'PERCENT'):
        return 0 <= value <= 1
    return value >= 0

ledgered = set()
try:
    with open(ledger_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if line.startswith('OM:'):
                ledgered.add(line)
except OSError:
    pass

records = {}
for path in sorted(glob.glob(os.path.join(assess_dir, '*.jsonl'))):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get('kind') != 'job_assessment':
                    continue
                if r.get('reportability_status') != 'reportable':
                    continue
                jid = r.get('agentic_job_id')
                if not jid:
                    continue
                # Latest sequence wins for a job assessed more than once.
                prev = records.get(jid)
                if prev is None or (r.get('sequence') or 0) >= (prev.get('sequence') or 0):
                    records[jid] = r
    except OSError:
        continue

emitted = 0
for jid, r in sorted(records.items()):
    if emitted >= max_jobs:
        break
    ts = r.get('job_ended_at') or r.get('ts')
    if not ts:
        continue
    try:
        recorded_at = datetime.datetime.fromtimestamp(
            float(ts), datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except (TypeError, ValueError, OSError):
        continue

    a = r.get('assumptions') or {}
    candidates = [
        ('estimated_value', r.get('estimated_value')),
        ('hours_saved', a.get('estimated_hours_saved')),
        ('assessment_confidence', r.get('confidence')),
        (unit_key, 1),
    ]

    entries = []
    rejected = False
    for key, value in candidates:
        if value is None:
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if not in_range(DECLARED[key], value):
            # Refuse the WHOLE job, not just the offending metric: a partial
            # append is still permanent, and shipping three of four metrics
            # would leave the job looking populated while quietly missing one.
            print('BADRANGE\t%s\t%s\t%s' % (jid, key, value), file=sys.stderr)
            rejected = True
            break
        line_key = 'OM:%s:%s:%s' % (jid, key, recorded_at)
        if line_key in ledgered:
            continue
        entries.append({'key': key, 'value': value,
                        'recordedAt': recorded_at, 'provenance': 'DERIVED'})
    if rejected or not entries:
        continue

    job_type = r.get('job_type') or ''
    print('%s\t%s\t%s\t%s' % (jid, job_type, recorded_at, json.dumps(entries)))
    emitted += 1
PY
  )"

  if [[ -z "${work}" ]]; then
    info "outcome-metrics: nothing to append"
    exit 0
  fi

  local econ_cache_dir
  econ_cache_dir="$(mktemp -d 2>/dev/null || echo "/tmp/revenium-econ-cache.$$")"
  mkdir -p "${econ_cache_dir}" 2>/dev/null
  trap 'rm -rf "${econ_cache_dir:-}" 2>/dev/null' EXIT INT TERM

  local appended=0 deferred=0 failed=0
  local jid job_type recorded_at entries_json
  while IFS=$'\t' read -r jid job_type recorded_at entries_json; do
    [[ -z "${jid}" ]] && continue

    # Resolve the per-job COUNT metric for this TYPE once, not once per job:
    # resolution costs a GET, and a tick covering many jobs of one type would
    # otherwise spend its whole rate-limit budget re-asking the same question.
    # bash 3.2 has no associative arrays, so the cache is a file per type.
    local unit_key="${OM_UNIT_METRIC_KEY}"
    if [[ -n "${job_type}" ]]; then
      local safe_type cache_file
      safe_type="${job_type//[^A-Za-z0-9_.-]/_}"
      cache_file="${econ_cache_dir}/${safe_type}"
      if [[ -f "${cache_file}" ]]; then
        unit_key="$(cat "${cache_file}" 2>/dev/null)"
      else
        local econ_out econ_rc
        econ_out="$(ensure_economics_contract "${job_type}")"
        econ_rc=$?
        if [[ ${econ_rc} -eq 2 ]]; then
          ((deferred++)) || true
          continue
        fi
        if [[ ${econ_rc} -ne 0 ]]; then
          ((failed++)) || true
          continue
        fi
        econ_out="$(printf '%s' "${econ_out}" | tail -1)"
        [[ -n "${econ_out}" ]] && unit_key="${econ_out}"
        printf '%s' "${unit_key}" > "${cache_file}" 2>/dev/null
      fi
    fi

    # Re-key the unit metric to whatever this type declares. python3 -c, not a
    # heredoc: a heredoc here would occupy stdin inside a command
    # substitution, the same collision that silently broke the ledger write.
    if [[ -n "${unit_key}" && "${unit_key}" != "${OM_UNIT_METRIC_KEY}" ]]; then
      local rekeyed
      rekeyed="$(OM_ENTRIES="${entries_json}" FROM="${OM_UNIT_METRIC_KEY}" TO="${unit_key}" python3 -c 'import json,os;e=json.loads(os.environ["OM_ENTRIES"]);[x.__setitem__("key",os.environ["TO"]) for x in e if x.get("key")==os.environ["FROM"]];print(json.dumps(e))' 2>/dev/null)"
      [[ -n "${rekeyed}" ]] && entries_json="${rekeyed}"
    fi

    if [[ "${DRY_RUN}" == "true" ]]; then
      info "outcome-metrics: dry-run, would append $(OM_ENTRIES="${entries_json}" python3 -c 'import json,os;print(len(json.loads(os.environ["OM_ENTRIES"])))' 2>/dev/null || echo '?') entries to job=${jid}"
      ((appended++)) || true
      continue
    fi

    local out
    out="$(printf '%s' "${entries_json}" | revenium jobs outcome-metrics "${jid}" --file - 2>&1)"
    local rc=$?
    if is_throttled "${out}"; then
      # Throttled is NOT a failure: no ledger line, so the next tick retries.
      ((deferred++)) || true
      continue
    fi
    if [[ ${rc} -ne 0 ]]; then
      warn "outcome-metrics: append failed job=${jid}: $(printf '%s' "${out}" | tr -d '\n' | cut -c1-160)"
      ((failed++)) || true
      continue
    fi

    # Ledger ONLY after a confirmed success, one line per metric, matching the
    # (job id, metric key, recordedAt) key the work builder reads back.
    # Entries travel by ENV, not stdin: `python3 - <<'PY'` already consumes
    # stdin for the program itself, so piping the JSON in as well means
    # json.load(sys.stdin) reads an exhausted stream. That failure is silent
    # -- the append has already succeeded at this point, so the only symptom
    # is a missing ledger line, i.e. a permanent re-append every tick.
    OM_ENTRIES="${entries_json}" JID="${jid}" RECORDED="${recorded_at}" \
      python3 - >>"${OUTCOME_METRICS_LEDGER_FILE}" <<'PY' 2>/dev/null
import json, os
try:
    entries = json.loads(os.environ['OM_ENTRIES'])
except ValueError:
    raise SystemExit(1)
for e in entries:
    print('OM:%s:%s:%s' % (os.environ['JID'], e['key'], os.environ['RECORDED']))
PY
    info "outcome-metrics: appended job=${jid} type=${job_type}"
    ((appended++)) || true
  done <<< "${work}"

  info "outcome-metrics: summary, appended=${appended} deferred=${deferred} failed=${failed}"
}

main "$@"
