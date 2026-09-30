#!/usr/bin/env bash
# subscriber-names.sh — turn each subscriber id this skill actually SHIPS
# (via meter completion's --subscriber-id) back into the human name behind
# it, for every profile home on this host.
#
# `meter completion` has no --subscriber-name -- SUB-09's whole reason for
# existing: the wire carries a stable key and nothing more. This script is
# the documented mapping procedure D-08 settled on instead of provisioning
# Revenium subscriber entities. `subscribers create` requires `--email` and
# Slack actors have no email anywhere in state.db, so meeting SUB-09 that
# way would mean fabricating an address, which this repo refuses.
#
# READ-ONLY BY DESIGN, and this is the load-bearing property, not an
# implementation detail. It opens state.db mode=ro, writes nothing
# anywhere, and never calls the Revenium API.
#
# UNMASKED BY DESIGN (D-11). Resolution is this script's entire purpose, so
# masking its output would defeat it. Its output goes to stdout only and
# NEVER through log/info/warn -- revenium-metering.log is byte-identical
# before and after every run, whether the run succeeds, finds nothing, or
# fails. This is identity data about named individuals and is explicitly
# NOT the artifact to paste into a support ticket, unlike diagnose.sh's
# output, which is.
#
# Never omits an actor (D-12). An actor whose name cannot be resolved is
# listed with an explicit UNRESOLVED marker, counted, and signalled by exit
# code -- never dropped and never backfilled from display_name. 146 of 275
# Slack rows on the reference host hold the CHANNEL id in display_name, so
# a fallback there would label spend with channel names.
#
# Ordering is a promise, not an accident: homes in hermes_profile_homes
# order (default first), then (source, user_id) in UTF-8 byte order within
# each home. An operator diffing two runs to spot a new actor depends on
# it -- two consecutive runs over one fleet's state produce byte-identical
# stdout.
#
# set -uo pipefail (not -e): this is a reporting surface, the same mode as
# three of the four other read-only status scripts (costs-status.sh,
# plugin-status.sh, hooks-status.sh; drain-status.sh is the outlier at
# -euo). A malformed database or a missing column should degrade to a
# legible message and a non-zero exit, never a half-printed report.
#
# Exit codes (stable for scripting):
#   0   every resolved subscriber id (an actor whose id actually ships)
#       has at least one name
#   10  at least one resolved subscriber id has no name
#   1   could not determine -- no inspected home had a readable state.db
#       with a sessions table

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

QUIET=false
PROFILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --quiet) QUIET=true; shift ;;
    --profile) PROFILE="${2:?--profile requires a name}"; shift 2 ;;
    --profile=*) PROFILE="${1#--profile=}"; shift ;;
    -h|--help)
      cat <<'USAGE'
Usage: subscriber-names.sh [--quiet] [--profile PROFILE]

Maps each subscriber id this skill actually ships (meter completion's
--subscriber-id) back to the human name behind it, for every profile home
on this host, or one home with --profile.

Read-only: opens state.db mode=ro, writes nothing anywhere, never calls
the Revenium API. Output is unmasked identity data for an operator's own
terminal -- not the artifact to paste into a support ticket.

  --quiet             print only "<shipped-id><TAB><name>" lines, one per
                      actor with a shippable id -- no header, no summary,
                      and nothing at all for an actor with no id
  --profile PROFILE   inspect only this profile's home ("default" is the
                      base $HERMES_HOME, matching the label this script's
                      own report uses in the PROFILE column)

Exit: 0 every resolved id has a name · 10 some do not · 1 could not
determine (no inspected home had a readable state.db with a sessions
table)
USAGE
      exit 0
      ;;
    *)
      echo "subscriber-names: unknown argument: $1 (try --help)" >&2
      exit 2
      ;;
  esac
done

# Review WR-01: probe --subscriber-id capability, matching the reporters'
# own idiom (hermes-report.sh:131, api-event-report.sh:193) --
# `if supports_flag ...; then VAR=true; fi`, never a command substitution,
# which would swallow supports_flag's exit status. On an older CLI, ALL
# FOUR production emission sites ship NO subscriber attribution for ANY
# actor that tick (SUB-07's fail-open contract) -- this script's own ID
# column must not imply otherwise on a host in that state.
#
# SUPPORTS_FLAG_QUIET (common.sh) is what keeps this probe compatible with D-11.
# An INDETERMINATE probe -- which is every probe on a host with no `revenium` on
# PATH, CI included -- otherwise appends a WARN line to revenium-metering.log and
# drops a .probe-warn sentinel under MARKERS_DIR. Both are writes this script
# promises never to make, and the log line breaks the byte-identical guarantee
# outright. Nothing is suppressed but those two writes: the verdict below is
# identical either way, and the indeterminate result still reaches the operator
# through the NOTE on stderr immediately after -- which is the only reason
# silencing the log line here is honest rather than a swallowed finding.
SUBSCRIBER_CLI_CAPABLE=false
if SUPPORTS_FLAG_QUIET=true supports_flag "meter completion" "--subscriber-id"; then
  SUBSCRIBER_CLI_CAPABLE=true
fi
if [[ "${SUBSCRIBER_CLI_CAPABLE}" != "true" ]]; then
  echo "NOTE: this host's revenium CLI does not advertise --subscriber-id --" \
       "no subscriber attribution actually ships from here; the table below" \
       "shows what WOULD ship on a CLI new enough to carry the flag." >&2
fi

# --- resolve which home(s) to walk ------------------------------------------
# Mirrors diagnose.sh's own --profile redirect: "default" is the label this
# script's own PROFILE column and hermes_profile_homes both use for the base
# home, and the default profile does NOT live at profiles/default.
_BASE_HOME="${HERMES_DEFAULT_HOME:-${HOME}/.hermes}"
HOMES_TSV=""
if [[ -n "${PROFILE}" ]]; then
  if [[ "${PROFILE}" == "default" ]]; then
    _resolved_home="${_BASE_HOME}"
  else
    _resolved_home="${_BASE_HOME}/profiles/${PROFILE}"
    if [[ ! -d "${_resolved_home}" ]]; then
      echo "subscriber-names: no profile '${PROFILE}' at ${_resolved_home}" >&2
      echo "Known profiles:" >&2
      echo "  default" >&2
      if [[ -d "${_BASE_HOME}/profiles" ]]; then
        for _d in "${_BASE_HOME}/profiles"/*/; do
          [[ -d "${_d}" ]] && echo "  $(basename "${_d}")" >&2
        done
      fi
      exit 1
    fi
  fi
  HOMES_TSV="$(printf '%s\t%s\n' "${PROFILE}" "${_resolved_home}")"
else
  HOMES_TSV="$(hermes_profile_homes)"
fi

# Review WR-02: the ID column must show what actually SHIPS from EACH
# profile's own reporter, so the mode is resolved PER HOME below (inside
# the loop, mirroring db_path's own per-home derivation two lines down),
# never once up front. A fleet host lets each profile set its own
# subscriberEmailMode independently -- resolving it once at process start
# from the default profile's config.json would show every OTHER profile's
# email-source actors in the wrong wire form (plaintext when that
# profile's own reporter ships obfuscated, or vice versa).

DATA_LINES=""
NOTE_LINES=""
READABLE_HOMES=0
NAMED_COUNT=0
UNRESOLVED_COUNT=0
NOID_COUNT=0

while IFS=$'\t' read -r profile home; do
  [[ -z "${profile}" ]] && continue
  db_path="${home}/state.db"
  if [[ ! -f "${db_path}" ]]; then
    NOTE_LINES+="${profile}: skipped -- no state.db at ${db_path}"$'\n'
    continue
  fi

  # One Python heredoc per home. The Python side owns ALL row formatting --
  # the bash side below never re-parses NAME content -- so a user_name
  # carrying the 0x1F transport delimiter, a tab, a CR or an LF cannot shift
  # a later column: it is replaced before it ever crosses the boundary.
  report=$(DB_PATH="${db_path}" python3 - <<'PY'
import os, re, sqlite3, sys
from urllib.parse import quote

db = os.environ['DB_PATH']

# mode=ro so a malformed path can never create a database, and so this
# script stays a pure reader of Hermes' own state -- never a writer.
try:
    conn = sqlite3.connect('file:' + quote(db) + '?mode=ro', uri=True)
except Exception as exc:
    print(f'ERR|could not open state.db: {exc}')
    sys.exit(0)

try:
    cols = [r[1] for r in conn.execute('PRAGMA table_info(sessions)').fetchall()]
except Exception as exc:
    print(f'ERR|could not read sessions table: {exc}')
    sys.exit(0)

if not cols:
    print('ERR|no sessions table')
    sys.exit(0)

if 'user_id' not in cols:
    print('NOUSERID|sessions has no user_id column -- no actor can be resolved from this database')
    sys.exit(0)

has_origin = 'origin_json' in cols

try:
    rows = conn.execute(
        "SELECT source, user_id FROM sessions "
        "WHERE user_id IS NOT NULL AND TRIM(user_id) != ''"
    ).fetchall()
except Exception as exc:
    print(f'ERR|could not query sessions: {exc}')
    sys.exit(0)

actors = {}
for source, user_id in rows:
    source = (source or '').strip()
    user_id = (user_id or '').strip()
    if not user_id:
        continue
    key = (source, user_id)
    actors[key] = actors.get(key, 0) + 1

names_by_actor = {}
if has_origin and actors:
    # json_valid() is load-bearing, not belt-and-braces: sqlite's
    # json_extract RAISES "malformed JSON" on the first unparseable row it
    # scans, aborting the WHOLE query. Guarding per row skips only the junk
    # -- one bad row must never cost every OTHER row its lookup.
    try:
        name_rows = conn.execute(
            "SELECT source, user_id, json_extract(origin_json, '$.user_name') "
            "FROM sessions "
            "WHERE user_id IS NOT NULL AND TRIM(user_id) != '' "
            "AND origin_json IS NOT NULL AND json_valid(origin_json)"
        ).fetchall()
    except Exception:
        name_rows = []
    for source, user_id, name in name_rows:
        source = (source or '').strip()
        user_id = (user_id or '').strip()
        if not user_id or not isinstance(name, str):
            continue
        n = name.strip()
        if not n:
            continue
        names_by_actor.setdefault((source, user_id), set()).add(n)

if not actors:
    print(f'ZERO|no identity-bearing sessions found in {db}')
    sys.exit(0)

# The delimiter set resolve_subscriber_id itself rejects: 0x1F, 0x1E, tab,
# CR, LF and the pipe. A source or user_id containing one ships no
# subscriber id at all (T-63-20) -- emitted as UNSAFE with only its count,
# never its raw bytes, because putting them on this stream would corrupt
# the report the same way an unguarded delimiter in a name would (T-63-19).
UNSAFE_CHARS = set('\x1f\x1e\t\r\n|')
CTRL_RE = re.compile(r'[\x1f\x1e\t\r\n|]')

def is_unsafe(s):
    return any(c in UNSAFE_CHARS for c in s)

# Deterministic order: UTF-8 byte order == Python code-point order for
# valid Unicode text, so sorting the tuple keys here is what makes two
# runs over the same database produce byte-identical stdout.
for source, user_id in sorted(actors.keys()):
    count = actors[(source, user_id)]
    if is_unsafe(source) or is_unsafe(user_id):
        print(f'UNSAFE\x1f{count}')
        continue
    if not has_origin:
        name_field = 'UNRESOLVED:no-origin_json-column'
    else:
        names = sorted(names_by_actor.get((source, user_id), set()))
        if not names:
            name_field = 'UNRESOLVED:no-name-recorded'
        else:
            altered = False
            cleaned = []
            for n in names:
                if CTRL_RE.search(n):
                    altered = True
                    n = CTRL_RE.sub('?', n)
                cleaned.append(n)
            name_field = ' / '.join(cleaned)
            if len(cleaned) > 1:
                name_field += ' [AMBIGUOUS]'
            if altered:
                name_field += ' [ALTERED]'
    print(f'ROW\x1f{source}\x1f{user_id}\x1f{name_field}\x1f{count}')
PY
)

  first_line="${report%%$'\n'*}"
  case "${first_line}" in
    ERR\|*)
      NOTE_LINES+="${profile}: skipped -- ${first_line#ERR|}"$'\n'
      continue
      ;;
    NOUSERID\|*)
      READABLE_HOMES=$((READABLE_HOMES + 1))
      NOTE_LINES+="${profile}: ${first_line#NOUSERID|}"$'\n'
      continue
      ;;
    ZERO\|*)
      READABLE_HOMES=$((READABLE_HOMES + 1))
      NOTE_LINES+="${profile}: ${first_line#ZERO|}"$'\n'
      continue
      ;;
  esac

  READABLE_HOMES=$((READABLE_HOMES + 1))

  # WR-02 fix: resolve THIS home's own subscriberEmailMode, not the
  # process-wide one. The "default" profile is the one entry whose config
  # path can legitimately diverge from the standard ${home}/state/revenium
  # layout -- an operator (or install-cron.sh's own single-home target,
  # install-cron.sh:170) may point REVENIUM_STATE_DIR somewhere else for
  # the process this script itself is running as, and CONFIG_FILE (set at
  # common.sh source time) already reflects that. Every OTHER profile home
  # is provisioned exclusively by install.sh/install-hooks.sh, always at
  # ${phome}/state/revenium -- there is no override mechanism for a named
  # profile's config path, so deriving it from `home` here mirrors db_path's
  # own per-home derivation exactly.
  #
  # REVENIUM_SUBSCRIBER_EMAIL_MODE keeps winning regardless of which path is
  # used below: resolve_subscriber_email_mode checks the env var FIRST and
  # only falls through to CONFIG_FILE when it is unset, so an operator who
  # exports the env var still overrides every home in one pass, exactly as
  # before this fix.
  if [[ "${profile}" == "default" ]]; then
    home_config_file="${CONFIG_FILE}"
  else
    home_config_file="${home}/state/revenium/config.json"
  fi
  _saved_config_file="${CONFIG_FILE}"
  CONFIG_FILE="${home_config_file}"
  _subscriber_email_mode_resolution=$(resolve_subscriber_email_mode)
  CONFIG_FILE="${_saved_config_file}"
  SUBSCRIBER_EMAIL_MODE=$(printf '%s' "${_subscriber_email_mode_resolution}" | sed -n '1p')
  # One NOTE per home (never per actor -- this is a one-shot script, not a
  # per-tick cron loop, but the sentinel-directory discipline the rest of
  # this repo uses for repeating warnings is the right instinct even here:
  # N homes with a typo produce N single lines, not N-times-the-actor-count).
  if [[ "$(printf '%s' "${_subscriber_email_mode_resolution}" | sed -n '2p')" == "true" ]]; then
    NOTE_LINES+="${profile}: subscriberEmailMode in ${home_config_file} is unrecognised -- treating as 'plaintext' for this home"$'\n'
  fi

  while IFS=$'\x1f' read -r kind a b c d; do
    [[ -z "${kind}" ]] && continue
    if [[ "${kind}" == "UNSAFE" ]]; then
      NOID_COUNT=$((NOID_COUNT + 1))
      DATA_LINES+="$(printf '%s\t%s\t%s\t%s' "${profile}" "NO-ID:unsafe" "(n/a)" "${a}")"$'\n'
      continue
    fi
    # kind == ROW; a=source b=user_id c=name_field d=count -- source and
    # user_id are guaranteed free of the delimiter set above, so they are
    # safe to pass straight to resolve_subscriber_id.
    resolved=$(resolve_subscriber_id "${a}" "${b}")
    status="${resolved%%|*}"
    key="${resolved#*|}"
    if [[ "${status}" != "ok" || -z "${key}" ]]; then
      NOID_COUNT=$((NOID_COUNT + 1))
      DATA_LINES+="$(printf '%s\t%s\t%s\t%s' "${profile}" "NO-ID:rejected" "(n/a)" "${d}")"$'\n'
      continue
    fi
    wire=$(resolve_subscriber_wire_pair "${key}" "${SUBSCRIBER_EMAIL_MODE}")
    wire_id="${wire%%|*}"
    case "${c}" in
      UNRESOLVED:*) UNRESOLVED_COUNT=$((UNRESOLVED_COUNT + 1)) ;;
      *) NAMED_COUNT=$((NAMED_COUNT + 1)) ;;
    esac
    DATA_LINES+="$(printf '%s\t%s\t%s\t%s' "${profile}" "${wire_id}" "${c}" "${d}")"$'\n'
  done <<< "${report}"

done <<< "${HOMES_TSV}"

TOTAL_LISTED=$((NAMED_COUNT + UNRESOLVED_COUNT + NOID_COUNT))

if [[ "${QUIET}" == true ]]; then
  if [[ -n "${DATA_LINES}" ]]; then
    while IFS=$'\t' read -r _profile _id _name _count; do
      [[ -z "${_profile}" ]] && continue
      case "${_id}" in
        NO-ID:*) continue ;;
      esac
      printf '%s\t%s\n' "${_id}" "${_name}"
    done <<< "${DATA_LINES}"
  fi
else
  if [[ -n "${DATA_LINES}" ]]; then
    printf 'PROFILE\tID\tNAME\tSESSIONS\n'
    printf '%s' "${DATA_LINES}"
  fi

  if [[ -n "${NOTE_LINES}" ]]; then
    [[ -n "${DATA_LINES}" ]] && echo
    printf '%s' "${NOTE_LINES}"
  fi

  if [[ -n "${DATA_LINES}" ]]; then
    echo
    echo "Actors listed         : ${TOTAL_LISTED}"
    echo "With a resolved name   : ${NAMED_COUNT}"
    echo "Without a name         : ${UNRESOLVED_COUNT}"
    echo "No shippable id        : ${NOID_COUNT}"
  fi
fi

if [[ "${READABLE_HOMES}" -eq 0 ]]; then
  exit 1
fi
if [[ "${UNRESOLVED_COUNT}" -gt 0 ]]; then
  exit 10
fi
exit 0
