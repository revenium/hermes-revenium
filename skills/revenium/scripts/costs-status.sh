#!/usr/bin/env bash
# costs-status.sh — report which classified job types have no configured
# cost figures, so an operator can see the gap instead of discovering it as
# a silently un-netted value.
#
# The problem this exists for: `costs` is keyed by job type with NO
# fleet-wide default, so a job type the classifier has discovered but the
# operator has never priced nets nothing at all. Nothing surfaces that
# today. The classifier grows job-taxonomy.json continuously, so config
# drifts behind reality on its own, quietly.
#
# READ-ONLY BY DESIGN, and this is the load-bearing property, not an
# implementation detail. This script never writes config.json and never
# emits a cost NUMBER for a job type -- not even a zero. Per
# _resolve_supplied_costs (classifier.py), a supplied `0` is knowledge
# ("we reviewed this and it cost nothing") that participates in the
# subtraction, while an absent category is unknown and never participates.
# Scaffolding a `0` here would manufacture operator knowledge nobody
# supplied and silently corrupt every net_value for that job type -- the
# exact substitution EGV-15 exists to prevent. Names only. The operator
# supplies figures by hand, or they stay unknown.
#
# Writing config.json from a hot path is also deliberately out of scope:
# setup-guardrails.sh is the only writer today, and the classifier runs
# in-process per session across every profile, so a per-session writer
# would race on the operator's own file.
#
# set -uo pipefail (not -e): this is a reporting surface. A malformed
# taxonomy or config should degrade to a legible message and a non-zero
# exit, never a half-printed report.
#
# Exit codes (stable for scripting):
#   0   every classified job type has at least one configured cost category
#   10  at least one classified job type has no configured costs
#   1   could not determine — a required file is missing or unreadable

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

QUIET=false
for arg in "$@"; do
  case "${arg}" in
    --quiet) QUIET=true ;;
    -h|--help)
      cat <<'USAGE'
Usage: costs-status.sh [--quiet]

Reports job types the classifier has discovered that have no configured
cost categories in config.json. Read-only: never writes config.json and
never emits a cost figure.

  --quiet   print only the unpriced job type names, one per line

Exit: 0 all priced · 10 some unpriced · 1 could not determine
USAGE
      exit 0
      ;;
  esac
done

if [[ ! -f "${JOB_TAXONOMY_FILE}" ]]; then
  echo "costs-status: no job taxonomy at ${JOB_TAXONOMY_FILE}" >&2
  echo "costs-status: nothing has been classified yet, so there is nothing to price." >&2
  exit 1
fi

REPORT=$(
  JOB_TAXONOMY_FILE="${JOB_TAXONOMY_FILE}" \
  CONFIG_FILE="${CONFIG_FILE}" \
  QUIET="${QUIET}" \
  python3 - <<'PY'
import json, os, sys

tax_path = os.environ['JOB_TAXONOMY_FILE']
cfg_path = os.environ['CONFIG_FILE']
quiet = os.environ.get('QUIET') == 'true'

try:
    with open(tax_path, encoding='utf-8') as fh:
        tax = json.load(fh)
except Exception as exc:
    print(f'ERR|could not read job taxonomy: {exc}')
    sys.exit(0)

labels = tax.get('labels')
if not isinstance(labels, dict):
    print('ERR|job taxonomy has no "labels" object')
    sys.exit(0)
job_types = sorted(labels)

# An ABSENT config means nothing is priced -- a legitimate, common state
# worth reporting. A config that EXISTS but cannot be parsed is a different
# thing entirely: it may well contain prices this script cannot see, so
# reporting those job types as unpriced would be a false claim. That case
# is "could not determine" (exit 1), not "unpriced" (exit 10).
#
# Collapsing the two would repeat, one level up, the exact error this
# script exists to warn against: treating unknown as if it were zero.
costs = {}
if os.path.exists(cfg_path):
    try:
        with open(cfg_path, encoding='utf-8') as fh:
            cfg = json.load(fh)
    except Exception as exc:
        print(f'ERR|config exists but could not be read: {exc}')
        sys.exit(0)
    if not isinstance(cfg, dict):
        print('ERR|config exists but is not a JSON object')
        sys.exit(0)
    evaluation = cfg.get('llmOutcomeEvaluation')
    if isinstance(evaluation, dict):
        candidate = evaluation.get('costs')
        if isinstance(candidate, dict):
            costs = candidate

# The four names must stay identical to classifier.py's COST_CATEGORIES
# and hermes-report.sh's _COST_CATEGORIES. tests/test_costs_status.py's
# drift test fails if they diverge -- this is the third declaration, and
# the repo already treats the first two as a drift hazard worth a test.
COST_CATEGORIES = ('human_review', 'rework_or_error', 'handoff', 'training_or_change')


# "Priced" means at least one category carries a figure the RESOLVER would
# actually use. This predicate has to match _resolve_supplied_costs exactly,
# or the report claims pricing is complete while net_value stays empty:
#
#   - only the four COST_CATEGORIES count. An unrecognised key "is ignored
#     entirely -- absent from supplied_costs, from every coverage list, and
#     from the subtraction", so {"bogus": 50} is unpriced.
#   - a malformed value ("non-finite, boolean, negative, wrong type") fails
#     closed to unknown, so Infinity, NaN, True and -5 are all unpriced.
#   - a supplied 0 IS a price: measured knowledge that participates.
#
# An empty object is therefore unpriced, exactly as absence is.
def priced(entry):
    if not isinstance(entry, dict):
        return False
    for category in COST_CATEGORIES:
        value = entry.get(category)
        if isinstance(value, bool):
            continue
        if not isinstance(value, (int, float)):
            continue
        if value != value or value in (float('inf'), float('-inf')):
            continue
        if value >= 0:
            return True
    return False

unpriced = [j for j in job_types if not priced(costs.get(j))]
configured = [j for j in job_types if priced(costs.get(j))]

# Cost keys with no matching classified job type. Usually a typo or a
# renamed label, and worth surfacing because such an entry never applies
# to anything.
orphans = sorted(k for k in costs if k not in labels)

if quiet:
    for j in unpriced:
        print(f'NAME|{j}')
    sys.exit(0)

print(f'COUNT|{len(job_types)}|{len(configured)}|{len(unpriced)}')
for j in unpriced:
    print(f'UNPRICED|{j}')
for j in orphans:
    print(f'ORPHAN|{j}')
PY
)

if [[ -z "${REPORT}" ]]; then
  echo "costs-status: the report produced no output" >&2
  exit 1
fi

if [[ "${REPORT}" == ERR\|* ]]; then
  echo "costs-status: ${REPORT#ERR|}" >&2
  exit 1
fi

if [[ "${QUIET}" == true ]]; then
  echo "${REPORT}" | sed -n 's/^NAME|//p'
  if echo "${REPORT}" | grep -q '^NAME|'; then exit 10; fi
  exit 0
fi

total=$(echo "${REPORT}" | sed -n 's/^COUNT|\([0-9]*\)|.*/\1/p')
priced_count=$(echo "${REPORT}" | sed -n 's/^COUNT|[0-9]*|\([0-9]*\)|.*/\1/p')
unpriced_count=$(echo "${REPORT}" | sed -n 's/^COUNT|[0-9]*|[0-9]*|\([0-9]*\)/\1/p')

echo "Job types classified : ${total}"
echo "With configured costs: ${priced_count}"
echo "Without              : ${unpriced_count}"

if [[ "${unpriced_count}" != "0" ]]; then
  echo
  echo "These job types net nothing today — every cost category is unknown:"
  echo "${REPORT}" | sed -n 's/^UNPRICED|/  /p'
  echo
  echo "To price one, add it under llmOutcomeEvaluation.costs in:"
  echo "  ${CONFIG_FILE}"
  echo
  echo "Supply only figures you have actually measured. A category you omit"
  echo "stays unknown and is excluded from the subtraction; a 0 you supply"
  echo "means \"measured, and it cost nothing\" and IS subtracted. Those are"
  echo "different claims — do not write 0 to silence this report."
fi

if echo "${REPORT}" | grep -q '^ORPHAN|'; then
  echo
  echo "Configured cost keys matching no classified job type (typo or rename?):"
  echo "${REPORT}" | sed -n 's/^ORPHAN|/  /p'
fi

if [[ "${unpriced_count}" != "0" ]]; then
  exit 10
fi
exit 0
