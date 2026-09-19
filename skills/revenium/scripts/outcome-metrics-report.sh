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
    # Issue 4: reading unitMetricKey alone is not enough. A valid,
    # operator-managed contract may omit or rename any of the three metrics we
    # send, in which case EVERY append for that type is rejected with "key
    # 'x' is not declared for the job type" -- forever, once per job, with the
    # failure reading like a server problem rather than a contract mismatch.
    # Verify the whole set up front and skip the type with a diagnostic
    # naming what is missing, which is actionable; a per-job 400 is not.
    local verdict
    verdict="$(JSON_BLOB="${out}" DEFAULT_UNIT="${OM_UNIT_METRIC_KEY}" python3 -c '
import json, os, sys
try:
    d = json.loads(os.environ["JSON_BLOB"])
except Exception:
    print("SKIP	unreadable economics document"); sys.exit(0)
metrics = {m.get("key"): m for m in (d.get("metrics") or []) if isinstance(m, dict)}
required = ["estimated_value", "hours_saved", "assessment_confidence"]
missing = [k for k in required if k not in metrics]
if missing:
    print("SKIP	contract does not declare: " + ", ".join(missing)); sys.exit(0)
unit = d.get("unitMetricKey") or os.environ["DEFAULT_UNIT"]
if unit not in metrics:
    print("SKIP	unitMetricKey %r is not among the declared metrics" % unit); sys.exit(0)
if (metrics[unit].get("type") or "") != "COUNT":
    print("SKIP	unitMetricKey %r is declared %s, not COUNT" % (unit, metrics[unit].get("type"))); sys.exit(0)
print("OK	" + unit)
' 2>/dev/null)"
    if [[ "${verdict}" == SKIP* ]]; then
      warn "outcome-metrics: skipping job_type=${job_type} -- $(printf '%s' "${verdict}" | cut -f2-)"
      return 3
    fi
    if [[ -z "${verdict}" ]]; then
      warn "outcome-metrics: skipping job_type=${job_type} -- could not validate its economics contract"
      return 3
    fi
    printf '%s\n' "$(printf '%s' "${verdict}" | cut -f2-)"
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

  # Serialise the whole read-ledger / append / write-ledger sequence. cron.lock
  # only covers runs made THROUGH cron.sh, so an operator invoking this script
  # directly can overlap a tick: both processes read the same absent keys and
  # issue the same permanent append before either records it. Non-blocking --
  # a second run simply defers to the next tick rather than queueing behind a
  # long one. Same exec-fd + fcntl pattern as cron.sh and prune-markers.sh.
  exec 9>"${OUTCOME_METRICS_LOCK_FILE}"
  if ! python3 - <<'LOCKPY'
import fcntl, sys
try:
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
except (OSError, BlockingIOError):
    sys.exit(11)
LOCKPY
  then
    info "outcome-metrics: another run holds the lock, skipping this tick"
    exit 0
  fi

  mkdir -p "$(dirname "${OUTCOME_METRICS_LEDGER_FILE}")" 2>/dev/null
  touch "${OUTCOME_METRICS_LEDGER_FILE}" 2>/dev/null

  # Deliberately NOT `local`: the EXIT trap below fires after main() returns,
  # so a function-scoped variable is already out of scope and the trap's
  # `${econ_cache_dir:-}` expands to empty -- `rm -rf ""` is a silent no-op
  # and every run leaks a directory. Measured: three runs on the Linux host
  # left three dirs behind, while the identical script cleaned up correctly
  # on macOS bash 3.2, so a developer machine will not show this. The `:-` in
  # the trap stays as a guard for the window before this assignment, not as
  # the scoping fix -- it is what made the leak silent rather than loud.
  econ_cache_dir="$(mktemp -d 2>/dev/null || echo "/tmp/revenium-econ-cache.$$")"
  mkdir -p "${econ_cache_dir}" 2>/dev/null
  trap 'rm -rf "${econ_cache_dir:-}" 2>/dev/null' EXIT INT TERM

  # Resolve each TYPE's unit metric key BEFORE the work list is built. This
  # ordering is load-bearing: the ledger check keys on the metric NAME, so
  # deciding the name after the dedup check means checking one key and
  # appending another. On this host that shipped a duplicate
  # `signal_events_processed` for every job a previous backfill had already
  # covered -- permanent, undeletable, and invisible until the dry run showed
  # "1 entries" for a job whose four metrics were all supposedly ledgered.
  local econ_types
  econ_types="$(
    ASSESS_DIR="${JOB_ASSESSMENTS_DIR}" python3 -c '
import glob, json, os, sys
seen=set()
for path in sorted(glob.glob(os.path.join(os.environ["ASSESS_DIR"], "*.jsonl"))):
    try:
        for line in open(path, encoding="utf-8"):
            line=line.strip()
            if not line: continue
            try: r=json.loads(line)
            except ValueError: continue
            if r.get("kind")!="job_assessment": continue
            if r.get("reportability_status")!="reportable": continue
            t=r.get("job_type") or ""
            if t and t not in seen:
                seen.add(t); print(t)
    except OSError:
        continue' 2>/dev/null
  )"
  local t safe_t
  while IFS= read -r t; do
    [[ -z "${t}" ]] && continue
    safe_t="${t//[^A-Za-z0-9_.-]/_}"
    [[ -f "${econ_cache_dir}/${safe_t}" ]] && continue
    local resolved rc
    resolved="$(ensure_economics_contract "${t}")"
    rc=$?
    if [[ ${rc} -ne 0 ]]; then
      # Throttled or failed: leave this type unresolved so its jobs are
      # skipped this tick rather than appended under a guessed key.
      continue
    fi
    resolved="$(printf '%s' "${resolved}" | tail -1)"
    [[ -z "${resolved}" ]] && resolved="${OM_UNIT_METRIC_KEY}"
    printf '%s' "${resolved}" > "${econ_cache_dir}/${safe_t}" 2>/dev/null
  done <<< "${econ_types}"

  # Build the work list: one line per job, TAB-separated, already
  # range-validated. Validation happens HERE rather than at the append site so
  # a bad value can never reach a permanent, unreadable, undeletable write.
  local work
  work="$(
    ASSESS_DIR="${JOB_ASSESSMENTS_DIR}" \
    LEDGER="${OUTCOME_METRICS_LEDGER_FILE}" \
    MAX_JOBS="${REVENIUM_OUTCOME_METRICS_MAX_JOBS}" \
    UNIT_KEY="${OM_UNIT_METRIC_KEY}" \
    ECON_CACHE="${econ_cache_dir}" \
    python3 - <<'PY' 2>/dev/null
import datetime, glob, json, os, sys

assess_dir = os.environ['ASSESS_DIR']
ledger_path = os.environ['LEDGER']
default_unit_key = os.environ['UNIT_KEY']
econ_cache = os.environ.get('ECON_CACHE', '')


def unit_key_for(job_type):
    """The COUNT metric THIS type declares, resolved before we got here.

    Returns None when the type could not be resolved (throttled or failed),
    which skips its jobs this tick -- appending under a guessed key would be
    a permanent write of a metric the contract may not declare.
    """
    if not job_type:
        return default_unit_key
    safe = ''.join(c if (c.isalnum() or c in '_.-') else '_' for c in job_type)
    try:
        with open(os.path.join(econ_cache, safe), encoding='utf-8') as f:
            v = f.read().strip()
            return v or default_unit_key
    except OSError:
        return None
try:
    max_jobs = int(os.environ['MAX_JOBS'])
except ValueError:
    max_jobs = 25

# Declared type per metric key. This is the knowledge the CLI cannot have --
# it would need the contract, which means a network call in a path documented
# as request-free -- and it is why the range check lives here.
DECLARED_BASE = {
    'estimated_value': 'MONEY',
    'hours_saved': 'DURATION',
    'assessment_confidence': 'SCORE',
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

    job_type = r.get('job_type') or ''
    unit_key = unit_key_for(job_type)
    if unit_key is None:
        continue
    declared = dict(DECLARED_BASE)
    declared[unit_key] = 'COUNT'

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
        # Issue 3: a missing or non-numeric field rejects the WHOLE job, the
        # same as an out-of-range one. Silently dropping the field and
        # appending the rest writes a PARTIAL outcome -- permanently, and
        # looking populated -- which is the very result the range check
        # rejects whole jobs to avoid. A legacy, truncated or hand-edited
        # sidecar is exactly where this arises.
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            print('BADFIELD\t%s\t%s\t%r' % (jid, key, value), file=sys.stderr)
            rejected = True
            break
        if not in_range(declared[key], value):
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

    print('%s\t%s\t%s\t%s' % (jid, job_type, recorded_at, json.dumps(entries)))
    emitted += 1
PY
  )"

  if [[ -z "${work}" ]]; then
    info "outcome-metrics: nothing to append"
    exit 0
  fi

  local appended=0 deferred=0 failed=0
  local jid job_type recorded_at entries_json
  while IFS=$'\t' read -r jid job_type recorded_at entries_json; do
    [[ -z "${jid}" ]] && continue

    # Economics and the unit key were resolved per TYPE above, before the
    # work list was built, so nothing is decided here -- a type that failed to
    # resolve simply produced no work.

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
    # Issue 1: VERIFY the ledger write. The append has already happened and
    # cannot be undone, so if the key cannot be persisted -- full disk,
    # read-only state dir, anything -- the next tick will read an absent key
    # and append the same permanent metrics again. Counting this job as
    # appended and carrying on would turn one unwritable ledger into a
    # duplicate for every remaining job in the backlog, so this STOPS the run.
    local ledger_lines_after
    ledger_lines_after="$(grep -c "^OM:${jid}:" "${OUTCOME_METRICS_LEDGER_FILE}" 2>/dev/null || echo 0)"
    if [[ "${ledger_lines_after}" -eq 0 ]]; then
      error "outcome-metrics: APPENDED job=${jid} but could NOT persist its ledger keys to ${OUTCOME_METRICS_LEDGER_FILE}; stopping so the next tick cannot re-append. This job's metrics are already on the platform and must be added to the ledger by hand before this stage runs again."
      ((failed++)) || true
      break
    fi
    info "outcome-metrics: appended job=${jid} type=${job_type}"
    ((appended++)) || true
  done <<< "${work}"

  info "outcome-metrics: summary, appended=${appended} deferred=${deferred} failed=${failed}"
}

main "$@"
