#!/usr/bin/env bash
# Hermes-native Revenium reporter. Reads token usage from ~/.hermes/state.db
# and ships deltas to Revenium via `revenium meter completion`.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Phase 32 Plan 03 (C-9): captured BEFORE common.sh's own
# "${REVENIUM_LEGACY_COMPLETIONS:-enabled}" declaration overwrites the
# variable — see resolve_switch_setting's own comment in common.sh for why
# this precedes `source common.sh`.
_LEGACY_COMPLETIONS_ENV_RAW="${REVENIUM_LEGACY_COMPLETIONS:-}"
# quick-260818-0in (MODE-04): captured BEFORE `source common.sh` for the
# identical reason as _LEGACY_COMPLETIONS_ENV_RAW above — common.sh's own
# "${REVENIUM_EVENT_METERING_MODE:-shadow}" declaration would destroy the
# unset-versus-explicit distinction resolve_switch_setting needs to reach
# config.json. This mirrors api-event-report.sh's own capture of the same
# variable, byte-for-byte, so the two scripts' resolutions can only ever
# diverge on the DATA each process's own startup sees (env/config.json at
# two different instants), never on the CODE that resolves it.
_EVENT_METERING_MODE_ENV_RAW="${REVENIUM_EVENT_METERING_MODE:-}"
# Phase 55 (D-01): captured BEFORE `source common.sh` for the identical
# reason as _EVENT_METERING_MODE_ENV_RAW above — common.sh's own
# "${REVENIUM_AUX_METERING:-enabled}" declaration would destroy the
# unset-versus-explicit distinction resolve_switch_setting needs to reach
# config.json's "auxMetering" key.
_AUX_METERING_ENV_RAW="${REVENIUM_AUX_METERING:-}"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

if ! command -v revenium >/dev/null 2>&1; then
  warn "revenium CLI not found on PATH — skipping metering."
  exit 0
fi
if ! command -v sqlite3 >/dev/null 2>&1; then
  warn "sqlite3 not found — skipping metering."
  exit 0
fi
if ! command -v python3 >/dev/null 2>&1; then
  warn "python3 not found — skipping metering."
  exit 0
fi
if [[ ! -f "${STATE_DB}" ]]; then
  warn "Hermes state.db not found at ${STATE_DB} — skipping."
  exit 0
fi
if ! revenium config show >/dev/null 2>&1; then
  warn "revenium not configured — run /revenium to set up."
  exit 0
fi

# Phase 9 (D-05): probe both CLI capabilities once at startup; cache result for
# the whole cron tick. Both probes must pass for job work to proceed (D-06).
# A negative probe fails open — metering continues byte-identical to v1.0 (D-07).
# The flag half goes through supports_flag (common.sh) rather than the raw
# `--help | grep -q` idiom this probe used through Phase 31: grep -q's early
# exit can SIGPIPE the upstream revenium process, surfacing as exit 141 under
# pipefail so the probe reports "unsupported" NONDETERMINISTICALLY, and the
# unanchored match let a short flag match a longer sibling. Both faults fail
# open and therefore silently — the row just loses its job attribution. The
# `revenium jobs --help` half stays a raw check on purpose: it asks whether the
# SUBCOMMAND exists, which is a different question from flag support.
JOBS_CLI_CAPABLE=false
if revenium jobs --help >/dev/null 2>&1 && \
   supports_flag "meter completion" "--agentic-job-id"; then
  JOBS_CLI_CAPABLE=true
else
  warn "revenium jobs/--agentic-job-id not available — job work skipped; metering continues as v1.0."
fi

# quick-260625-mlc (TRACE-TYPE-01): independent probe for the --trace-type flag
# (revenium CLI 1.2.1+). Separate capability from jobs/--agentic-job-id — probe it
# on its own and cache for the whole tick. A negative probe fails open SILENTLY:
# older installs simply omit --trace-type and meter byte-identically to today
# (backward-compat constraint). No warn — flag absence is not an error.
# supports_flag for the same two reasons as the jobs probe above. No warn here
# is deliberate and unchanged: flag absence on an older CLI is the supported
# configuration, and a per-minute cron must not warn every tick for it.
TRACE_TYPE_CLI_CAPABLE=false
if supports_flag "meter completion" "--trace-type"; then
  TRACE_TYPE_CLI_CAPABLE=true
fi

# Phase 29 (SQUAD-04): capability gate for the v1.3.0 squad flags
# (--squad-id/--squad-name/--squad-role). Uses supports_flag (Phase 26,
# common.sh) rather than the raw `grep -q` idiom the two probes above still
# use — supports_flag closes two defects those older probes carry: `grep -q`'s
# early exit can SIGPIPE the upstream revenium process (surfacing as exit
# 141 under pipefail), and an unanchored match lets a shorter flag match a
# longer sibling (e.g. a probe for --squad-id false-positiving against a
# hypothetical --squad-identifier). Fails silently on a negative probe —
# flag absence on an older CLI is the supported configuration (SQUAD-04's
# byte-identical-argv contract), not an error, and a per-minute cron must
# not emit a per-tick warning for it.
SQUAD_CLI_CAPABLE=false
if supports_flag "meter completion" "--squad-id"; then
  SQUAD_CLI_CAPABLE=true
fi

# Skill attribution (revenium CLI 1.4.0). Same supports_flag posture as the
# squad probe above and for the same reason: a negative probe is a LIVE
# configuration, not an error — the fleet host still runs a CLI without these
# flags, and a session metered there must produce argv byte-identical to what
# the golden fixtures pin. Probed on --skill-name because it is the flag the
# feature is worthless without; the others ship or omit with it as one family.
SKILL_CLI_CAPABLE=false
if supports_flag "meter completion" "--skill-name"; then
  SKILL_CLI_CAPABLE=true
fi

# Phase 38 (CR-01): capability gate for the v1.5 `jobs outcome` value flags
# (--outcome-value/--outcome-currency). Same supports_flag posture as the
# squad/skill probes above, and for the same reason: a negative probe is a
# LIVE configuration (an older revenium CLI predating these two flags), not
# an error. Unlike the meter-completion probes, an ungated pair of unknown
# flags here does not just cost one dimension -- it fails the ENTIRE `jobs
# outcome` call (unrecognized-flag exit), wedging the job in OUTCOME-04's
# retry loop indefinitely. Probed once at startup and cached for the whole
# tick; both flags are gated on this single probe and are added together or
# not at all, mirroring the emission site's own "both or neither" comment.
#
# BOTH halves of the pair are probed, not just --outcome-value. The emission
# site sends the two together, so a CLI advertising one without the other
# would take the enabled branch and then reject the whole call -- the exact
# wedge this gate exists to prevent, reintroduced through the half of the pair
# nobody checked. `&&` short-circuits, so the common older-CLI case (neither
# flag present) still costs a single --help.
OUTCOME_VALUE_CLI_CAPABLE=false
if supports_flag "jobs outcome" "--outcome-value" \
   && supports_flag "jobs outcome" "--outcome-currency"; then
  OUTCOME_VALUE_CLI_CAPABLE=true
fi

# Resolve the skill a session was working with, if any.
#
# Signal: Hermes records skill tool calls as ordinary `messages` rows —
# tool_name in (skill_view, skill_manage, skills_list) — whose payload is JSON
# carrying {"name": "<skill>"}. `.usage.json` was rejected as a source: it is
# per-skill aggregate with no session linkage, so it cannot attribute a skill
# to a completion.
#
# Policy: MOST RECENT at-or-before the window end. --skill-name is singular on
# the wire while sessions routinely open several skills (19 of 30 skill-bearing
# sessions on one sampled profile), so a choice is unavoidable; the most recent
# one is what the session was working with while these tokens burned.
#
# Emits "name|trigger" on stdout, or nothing at all. Every failure — no rows, a
# payload that will not parse, no `name` key, sqlite3 itself failing — resolves
# to silence, which callers treat as "no skill" and omit the flags. Skill
# attribution is enrichment; it must never cost a completion its metering.
resolve_session_skill() {
  local sid="$1" window_end="$2"
  SID="${sid}" WINDOW_END="${window_end}" STATE_DB="${STATE_DB}" python3 - <<'SKILLPY' 2>/dev/null || true
import json
import os
import sqlite3

db = os.environ.get('STATE_DB', '')
sid = os.environ.get('SID', '')
try:
    window_end = float(os.environ.get('WINDOW_END') or 0) or None
except (TypeError, ValueError):
    window_end = None
if not (db and sid and os.path.isfile(db)):
    raise SystemExit(0)

sql = ("SELECT tool_name, COALESCE(content, tool_calls) FROM messages "
       "WHERE session_id = ? AND tool_name IN "
       "('skill_view','skill_manage','skills_list') ")
args = [sid]
if window_end:
    sql += "AND timestamp <= ? "
    args.append(window_end)
sql += "ORDER BY timestamp DESC LIMIT 25"

try:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(sql, args).fetchall()
    finally:
        conn.close()
except Exception:
    raise SystemExit(0)

for tool_name, payload in rows:
    if not payload:
        continue
    try:
        name = json.loads(payload).get('name')
    except Exception:
        continue          # unparseable payload: fall through to the next-most-recent
    if isinstance(name, str) and name.strip():
        # Pipe and newline are the field/record separators the caller reads
        # with; a skill name carrying either would desync that read.
        clean = name.strip().replace('|', '_').replace('\n', ' ')[:128]
        trigger = (tool_name or '').replace('|', '_')[:64]
        print(clean + "|" + trigger)
        break
SKILLPY
}

# Look up a skill's provenance in the hub lockfile. Emits "source|marketplace",
# or nothing when the skill is not recorded there (locally authored, or
# installed before the hub tracked it). Omitting is deliberate: an invented
# provenance is worse than an absent one.
resolve_skill_provenance() {
  local skill_name="$1"
  SKILL_NAME="${skill_name}" LOCK_FILE="${HERMES_HOME}/skills/.hub/lock.json" python3 - <<'PROVPY' 2>/dev/null || true
import json
import os

lock = os.environ.get('LOCK_FILE', '')
name = os.environ.get('SKILL_NAME', '')
if not (lock and name and os.path.isfile(lock)):
    raise SystemExit(0)
try:
    entry = (json.load(open(lock)).get('installed') or {}).get(name) or {}
except Exception:
    raise SystemExit(0)

source = str(entry.get('source') or '').replace('|', '_')[:64]
# The marketplace is the source when the source IS one. "official" means it
# shipped with Hermes — a source, but not a marketplace.
marketplace = source if source and source not in ('official', 'builtin', 'local') else ''
if source:
    print(source + "|" + marketplace)
PROVPY
}

# quick-260605: resolve teamId once for the whole tick. jobs create/outcome require
# it; absent, the CLI returns HTTP 400 / exit 4 which the cron's 409-only success
# check treats as a generic failure — stranding every outcome in permanent
# OUTCOME-04 deferral. We pass it explicitly on the job calls (robust to an
# incomplete `revenium config`, leveraging the CLI's --team-id override) and warn
# loudly when it cannot be resolved, so the failure is diagnosable instead of
# silent. Empty in the test harness (the shim's `config show` is a no-op) → the
# --team-id flag is simply omitted, preserving the v1.4 wire shape and argv goldens.
REVENIUM_TEAM_ID_RESOLVED="$(resolve_team_id)"
if [[ "${JOBS_CLI_CAPABLE}" == "true" && -z "${REVENIUM_TEAM_ID_RESOLVED}" ]]; then
  warn "teamId not configured — jobs create/outcome will fail (HTTP 400). Run 'revenium config set team-id <id>' or set REVENIUM_TEAM_ID; metering continues."
fi

# Phase 10: script-level accumulator for terminated job arcs needing outcome reporting.
# Must be script-global (not local inside main) so it survives from the session loop
# into the post-loop outcome stage within one main() invocation (CR-01 lesson, D-06).
# Plain indexed array — bash 3.2 portability (Mac Studio host, no associative arrays).
job_outcome_queue=()

touch "${LEDGER_FILE}"
touch "${JOBS_LEDGER_FILE}"

ORG_NAME=""
if [[ -f "${CONFIG_FILE}" ]]; then
  ORG_NAME=$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}')).get('organizationName', ''))" 2>/dev/null || true)
fi
# BUG-2: organizationName is the ORGANIZATION dimension (company/product), NOT the
# agent. Warn if it looks like an agent/profile name so a misconfigured install
# does not pollute the ORGANIZATION dimension.
warn_if_org_looks_like_agent "${ORG_NAME}"

# Phase 32 Plan 03 (C-11/D-13): resolve REVENIUM_LEGACY_COMPLETIONS once at
# startup (env > config.json's legacyCompletions > the "enabled" default),
# and re-read drain-status.json's own `drained` field once at startup with a
# FAIL-SAFE read — a missing file, invalid JSON, or an absent field ALL
# resolve to not-drained. This is the whole of contract C-11's enforcement:
# the legacy completions path is skipped for a session ONLY when the
# operator's setting is "disabled" AND the gate independently confirms
# drained. A disable request made while the gate says not-drained is
# refused — completions keep metering — because D-09 and D-11 compose into a
# silent, permanent under-bill otherwise (32-CONTEXT.md D-13).
_legacy_completions_resolution=$(resolve_switch_setting "${_LEGACY_COMPLETIONS_ENV_RAW}" "legacyCompletions" "enabled" "enabled" "disabled")
REVENIUM_LEGACY_COMPLETIONS_RESOLVED=$(printf '%s' "${_legacy_completions_resolution}" | sed -n '1p')
_legacy_completions_invalid=$(printf '%s' "${_legacy_completions_resolution}" | sed -n '2p')
if [[ "${_legacy_completions_invalid}" == "true" ]]; then
  warn "REVENIUM_LEGACY_COMPLETIONS/legacyCompletions had an unrecognised value — falling back to 'enabled' (completions keep metering)."
fi

# Phase 55 (D-01): resolve the auxiliary-metering activation tunable, same
# env > config.json ("auxMetering") > "enabled" default precedence as every
# other closed-two-literal switch in this file. A typo must never silently
# change billing behaviour, so an unrecognised value warns and falls back to
# the default rather than failing closed or open silently.
_aux_metering_resolution=$(resolve_switch_setting "${_AUX_METERING_ENV_RAW}" "auxMetering" "enabled" "enabled" "disabled")
REVENIUM_AUX_METERING_RESOLVED=$(printf '%s' "${_aux_metering_resolution}" | sed -n '1p')
_aux_metering_invalid=$(printf '%s' "${_aux_metering_resolution}" | sed -n '2p')
if [[ "${_aux_metering_invalid}" == "true" ]]; then
  warn "REVENIUM_AUX_METERING/auxMetering had an unrecognised value — falling back to 'enabled' (auxiliary usage keeps metering)."
fi
AUX_METERING_ENABLED="false"
if [[ "${REVENIUM_AUX_METERING_RESOLVED}" == "enabled" ]]; then
  AUX_METERING_ENABLED="true"
fi

DRAIN_GATE_DRAINED="false"
DRAIN_GATE_PENDING_COUNT=""
# quick-260818-f1g (STALE-07): the per-session carve-out. A missing key, a
# non-list value, or any parse failure below all resolve to the EMPTY set —
# reproducing today's global suppression exactly (AX-S28). Newline-delimited
# string with a leading AND trailing newline, membership tested via the
# `case ... *$'\n'"${sid}"$'\n'*)` glob idiom this repo already runs on
# api-event-report.sh's per-record hot path (:553,:1252) — bash 3.2 has no
# associative arrays.
LEGACY_RETAINED_SIDS=$'\n'
if [[ -f "${DRAIN_STATUS_FILE}" ]]; then
  _drain_gate_output=$(DRAIN_STATUS_FILE="${DRAIN_STATUS_FILE}" python3 - <<'PY' 2>/dev/null
import json, os
try:
    doc = json.load(open(os.environ['DRAIN_STATUS_FILE']))
except Exception:
    print('DRAINED=false')
    print('PENDING=')
else:
    drained = doc.get('drained')
    pending = doc.get('pendingCount')
    print(f"DRAINED={'true' if drained is True else 'false'}")
    print(f"PENDING={pending if isinstance(pending, int) else ''}")
    retained = doc.get('legacyRetainedSids')
    if isinstance(retained, list):
        for _sid in retained:
            if isinstance(_sid, str) and _sid:
                print(f"RETAINED_SID={_sid}")
PY
)
  DRAIN_GATE_DRAINED=$(printf '%s' "${_drain_gate_output}" | sed -n 's/^DRAINED=//p' | head -1)
  DRAIN_GATE_PENDING_COUNT=$(printf '%s' "${_drain_gate_output}" | sed -n 's/^PENDING=//p' | head -1)
  [[ "${DRAIN_GATE_DRAINED}" == "true" ]] || DRAIN_GATE_DRAINED="false"
  while IFS= read -r _retained_sid; do
    [[ -z "${_retained_sid}" ]] && continue
    LEGACY_RETAINED_SIDS="${LEGACY_RETAINED_SIDS}${_retained_sid}"$'\n'
  done < <(printf '%s\n' "${_drain_gate_output}" | sed -n 's/^RETAINED_SID=//p')
fi

LEGACY_COMPLETIONS_SKIP="false"
if [[ "${REVENIUM_LEGACY_COMPLETIONS_RESOLVED}" == "disabled" ]]; then
  if [[ "${DRAIN_GATE_DRAINED}" == "true" ]]; then
    LEGACY_COMPLETIONS_SKIP="true"
    info "legacy completions path disabled — drain gate reports drained; skipping legacy completion emission this run."
  else
    warn "REVENIUM_LEGACY_COMPLETIONS=disabled but the drain gate reports NOT drained (pending=${DRAIN_GATE_PENDING_COUNT:-unknown}) — refusing to disable; completions keep metering. Run drain-status.sh for details."
  fi
fi

# quick-260817-tfe (OWN-03): the ENGAGEMENT GATE. The ownership protocol is
# active only when SOME event-path artifact exists on this install — a
# non-empty event ledger, any entry under OWNERS_DIR, or any spool file. When
# it is false nothing below claims, nothing creates OWNERS_DIR, and the wire
# output is byte-identical to an install that never heard of this change,
# which is the overwhelming majority of them.
#
# Pure bash, no subprocess: an UNMATCHED glob stays literal (nullglob is off),
# so the array always has exactly one element and `-e` on it is a safe
# emptiness probe. `${arr[0]}` is therefore always defined under `set -u`.
#
# WHY THE SPOOL DISJUNCT IS SAFE. A spool file must already exist for the
# event path to ever reach a session, and the composed 600-second settle
# windows on BOTH sides defer any session whose spool file appeared after
# this tick's startup — so a session cannot slip past this gate and be
# claimed by the event path in the same tick.
_owners_probe_glob=("${OWNERS_DIR}"/*)
_spool_probe_glob=("${EVENT_SPOOL_DIR}"/*.jsonl)
OWNERSHIP_PROTOCOL_ACTIVE="false"
if [[ -s "${EVENT_LEDGER_FILE}" ]] \
   || [[ -e "${_owners_probe_glob[0]}" ]] \
   || [[ -e "${_spool_probe_glob[0]}" ]]; then
  OWNERSHIP_PROTOCOL_ACTIVE="true"
fi

# quick-260818-0in (MODE-04): THE LIVENESS PREDICATE. Resolved ONCE per run,
# through the IDENTICAL resolve_switch_setting call api-event-report.sh
# makes at its own startup — same config key ("eventMeteringMode"), same
# default ("shadow"), same two allowed literals ("shadow"/"live"). "Identical"
# means identical CODE, not a shared read: each script calls
# resolve_switch_setting at its OWN process startup, two sequential reads by
# two processes. Under cron they can never race — cron.sh runs this script's
# stage before api-event-report.sh's, both inside one cron.lock — so no
# same-tick divergence is constructible for a cron-only deployment. A
# config.json edit landing between two out-of-band invocations, or a
# per-process environment override, remains a residual (AX-21), closed
# separately by the takeover primitive's publish-instant re-read below.
#
# Gated on OWNERSHIP_PROTOCOL_ACTIVE (F-7): resolving this switch costs one
# python3 spawn when the environment variable is unset and a config file
# exists, and the reporter's measured no-marker spawn ceiling
# (NO_MARKER_SPAWN_CEILING=13, tests/test_reporter_spawn_guards.py) is a
# locked test constant a disengaged install must not move. A disengaged
# install has no owners record, so no takeover branch below is reachable
# regardless of this value — EVENT_PATH_LIVE simply stays false and unread.
EVENT_PATH_LIVE="false"
_event_metering_mode_resolved="shadow"
if [[ "${OWNERSHIP_PROTOCOL_ACTIVE}" == "true" ]]; then
  _event_metering_mode_resolution=$(resolve_switch_setting "${_EVENT_METERING_MODE_ENV_RAW}" "eventMeteringMode" "shadow" "shadow" "live")
  _event_metering_mode_resolved=$(printf '%s' "${_event_metering_mode_resolution}" | sed -n '1p')
  _event_metering_mode_invalid=$(printf '%s' "${_event_metering_mode_resolution}" | sed -n '2p')
  if [[ "${_event_metering_mode_invalid}" == "true" ]]; then
    warn "REVENIUM_EVENT_METERING_MODE/eventMeteringMode had an unrecognised value — falling back to 'shadow' (ships nothing)."
  fi
  if [[ "${_event_metering_mode_resolved}" == "live" ]]; then
    EVENT_PATH_LIVE="true"
  fi
fi

# quick-260817-tfe (OWN-01/OWN-04): the CLAIM PRIMITIVE. Establishes session
# ownership with a create-and-exclusive open — atomic across processes, with
# no lock held and none needed. That matters here specifically: flock is taken
# only by cron.sh (this script takes none, api-event-report.sh takes none), so
# an out-of-band shipper invocation — the exact pattern behind the 2026-08-17
# double-bill — runs unlocked and can interleave with a cron tick. O_EXCL
# holds regardless, and holds for any future caller that forgets to lock.
#
# Usage: _claim_session_owner <sid> <legacy|event> <baseline-tokens>
# Prints, on stdout, three KEY=value lines:
#   OWNER=    the side that owns the session (this call's side on a fresh
#             create; the EXISTING record's first line when the file was
#             already there — the file always wins, that is the arbiter)
#   CLAIMED=  true only when THIS call created the record. The
#             once-per-record gate the dual-ledger warn hangs on.
#   BASELINE= the record's catch-up baseline, or empty when it has none.
# Prints NOTHING on any I/O failure — empty output is the contract for
# "sentinel unavailable", and each caller resolves that its own way
# (OWN-04: legacy fails OPEN and bills, the event path fails CLOSED and
# defers). The EXISTS branch has its OWN handler because a record whose bytes
# are not valid UTF-8 raises there, not in the create — relying on the
# create's handler would let a decode failure crash the heredoc.
_claim_session_owner() {
  OWNERS_DIR="${OWNERS_DIR}" \
  CLAIM_SID="${1:-}" \
  CLAIM_SIDE="${2:-}" \
  CLAIM_BASELINE="${3:-0}" \
  python3 - <<'PY' 2>/dev/null
import os
import tempfile

owners_dir = os.environ.get('OWNERS_DIR', '')
sid = os.environ.get('CLAIM_SID', '')
side = os.environ.get('CLAIM_SIDE', '')

# Closed two-literal vocabulary; anything else is a caller bug, not a record
# state, and must not create a file that the total ownership predicate would
# then have to interpret.
if not owners_dir or not sid or side not in ('legacy', 'event'):
    raise SystemExit(0)

# T-OWN-01: the ONLY filename derivation, mirrored byte-for-byte by
# prune-markers.sh's owners pass. Replacing the separator and NUL means no
# traversal-shaped segment can escape OWNERS_DIR; the 200-character cap keeps
# the name inside every filesystem's per-component limit.
name = sid.replace('/', '_').replace('\x00', '_')[:200]
if not name:
    raise SystemExit(0)
path = os.path.join(owners_dir, name)

try:
    baseline = int(os.environ.get('CLAIM_BASELINE', '0') or '0')
except (TypeError, ValueError):
    baseline = 0
if baseline < 0:
    baseline = 0

try:
    os.makedirs(owners_dir, mode=0o700, exist_ok=True)
    # quick-260817-tfe / PR #54 review (P1): publish the record ATOMICALLY.
    # O_EXCL makes CREATION exclusive but leaves the file empty until the
    # write lands. A concurrent reader inside that window reads an empty
    # owner, resolves "not owned" (the total predicate's safe direction for a
    # CORRUPT record, but wrong for a half-published one), and bills — while
    # the creator finishes writing and bills too. That is the very double-bill
    # this record exists to prevent, reintroduced in the gap between create
    # and write.
    #
    # Build the record in a temp file and os.link() it into place instead:
    # link() is atomic AND raises FileExistsError if the target exists, so it
    # supplies exclusivity and content-at-publication in one step. The record
    # is therefore never observable without its content. The FileExistsError
    # propagates to the same handler the O_EXCL create used, so the reader
    # half below is unchanged.
    _payload = side + "\n"
    # A second line is written ONLY for a real catch-up baseline. A record
    # with no second line is "no floor" — which is what every non-dual-ledger
    # claim wants, and what a record written by an older build degrades to.
    if baseline > 0:
        _payload += str(baseline) + "\n"
    _tfd, _tmp = tempfile.mkstemp(dir=owners_dir, prefix='.claim.')
    try:
        with os.fdopen(_tfd, 'w') as _tfh:
            _tfh.write(_payload)
        os.chmod(_tmp, 0o600)
        # A filesystem without hardlink support raises OSError (not
        # FileExistsError); that falls to the outer `except Exception`, which
        # prints nothing — the documented fail-open direction (legacy bills,
        # event defers), never a crash.
        os.link(_tmp, path)
    finally:
        try:
            os.unlink(_tmp)
        except Exception:
            pass
except FileExistsError:
    # The record already exists — it wins, always. Read only its FIRST line
    # (the owner) and SECOND line (the baseline); a multi-line file can
    # therefore never forge a second decision. Its own handler: a non-UTF-8
    # or otherwise unreadable record degrades to empty output here rather
    # than raising out of the heredoc. Never repaired, never overwritten.
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            existing_owner = fh.readline().strip()
            existing_baseline_raw = fh.readline().strip()
    except Exception:
        raise SystemExit(0)
    try:
        existing_baseline = int(existing_baseline_raw)
    except (TypeError, ValueError):
        existing_baseline = None
    if existing_baseline is not None and existing_baseline < 0:
        existing_baseline = None
    print(f"OWNER={existing_owner}")
    print("CLAIMED=false")
    print(f"BASELINE={existing_baseline if existing_baseline is not None else ''}")
    raise SystemExit(0)
except Exception:
    raise SystemExit(0)

# The record was written and published atomically above; nothing to do here.

print(f"OWNER={side}")
print("CLAIMED=true")
print(f"BASELINE={baseline if baseline > 0 else ''}")
PY
}

# quick-260818-0in (MODE-02/MODE-03/AX-21): the TAKEOVER PRIMITIVE. Flips an
# event-owned record to `legacy`, ONE-WAY, recording a catch-up floor so the
# legacy path bills forward without re-billing what the event path already
# shipped. Mirrors _claim_session_owner's shape and output contract.
#
# Usage: _takeover_session_owner <sid> <requested-baseline> <known-baseline>
#
# (a) WHY REPLACE, NOT LINK. _claim_session_owner's os.link() publishes a NEW
#     file and requires the target be ABSENT — exactly the create-exclusivity
#     arbiter PR #54 needs. The takeover's target always EXISTS (an
#     event-owned record). os.replace() is the one call that is atomic on
#     POSIX and, like link, only ever makes the record observable WITH its
#     final content (built off-path in a temp file, then swapped in). Confine
#     os.replace to here; os.link remains the claim's sole publication
#     primitive — #54's create-exclusivity arbiter is untouched.
# (b) WHY IT NEVER RE-READS THE OWNERS RECORD. The claim that ran
#     microseconds earlier in the same loop iteration already returned both
#     the owner and the record's own baseline; those reach this primitive as
#     positional arguments. One reader of those bytes, one decision point,
#     no drift between two readers of the same file. This invariant is about
#     owners/<sid> specifically — it says nothing about state.db, which (d)
#     below reads for an entirely different reason.
# (c) IT CAN ONLY EVER WRITE THE LITERAL "legacy" — there is no argument, no
#     branch and no environment variable that reaches the other literal. A
#     later shadow->live mode flip therefore cannot resurrect a second
#     biller for this session (MODE-03): the event path's own total
#     predicate (api-event-report.sh) defers forever once the record's first
#     line is anything but the exact literal "event".
# (d) WHY IT NEVERTHELESS DOES READ state.db (AX-21). owners/<sid> and
#     state.db are two DIFFERENT files answering two DIFFERENT questions:
#     the owners record says who owns the session; state.db says how many
#     tokens it had at the publish instant. Reading (d) is not a
#     contradiction of (b) — a reader who conflates the two files and
#     "simplifies" this away reopens AX-21. The reporter's session snapshot
#     is taken by ONE sqlite3 query at process start (main()'s `sessions=`
#     assignment) and carried down the whole loop, so by the time a given
#     session's takeover runs, that snapshot can be the entire run stale. An
#     out-of-band `live` api-event-report.sh invocation can ship tokens into
#     `sessions` during exactly that window. Re-reading immediately before
#     the replace and folding the result into the floor's max() collapses
#     that window down to the microseconds between this query and the
#     replace (F-8 fact 4). ANY failure of this re-read — missing database,
#     missing row, locked database, any exception — drops the term silently
#     and proceeds: it can only ever RAISE the floor, so its failure
#     degrades to the pre-AX-21 exposure and never to a worse one. It must
#     never abort the takeover.
_takeover_session_owner() {
  OWNERS_DIR="${OWNERS_DIR}" \
  STATE_DB="${STATE_DB}" \
  TAKEOVER_SID="${1:-}" \
  TAKEOVER_REQUESTED_BASELINE="${2:-0}" \
  TAKEOVER_KNOWN_BASELINE="${3:-0}" \
  python3 - <<'PY' 2>/dev/null
import fcntl
import os
import tempfile

owners_dir = os.environ.get('OWNERS_DIR', '')
state_db = os.environ.get('STATE_DB', '')
sid = os.environ.get('TAKEOVER_SID', '')

if not owners_dir or not sid:
    raise SystemExit(0)

# T-OWN-01's derivation, mirrored byte-for-byte — no second rule anywhere.
name = sid.replace('/', '_').replace('\x00', '_')[:200]
if not name:
    raise SystemExit(0)
path = os.path.join(owners_dir, name)


# MUTUAL EXCLUSION, not a narrower window.
#
# os.replace is atomic with respect to READERS, but the read-modify-write
# around it is not atomic with respect to another WRITER. Two unlocked
# reporters both reach here: A reads floor 150, B publishes 300, A replaces
# with a max() computed from its stale 150 — and the floor goes BACKWARDS,
# re-billing what the event path already shipped.
#
# This was fixed twice by narrowing the window (re-read state.db at publish
# instant; then re-read the record itself "immediately before" the replace)
# and review correctly rejected both: narrowing a TOCTOU window is not
# closing it. Only exclusion closes it. Do not replace this lock with a
# smaller gap.
#
# The lock is taken on the owners DIRECTORY fd, deliberately:
#   - no new state path, so nothing to declare in common.sh and nothing new
#     for prune-markers.sh to reason about;
#   - the record FILE is the wrong target: os.replace swaps the inode, so two
#     racers would each hold a lock on a different inode and both proceed.
# Contention is a non-issue: takeovers are rare and the critical section is
# two file operations.
_lock_fd = None
try:
    _lock_fd = os.open(owners_dir, os.O_RDONLY)
    fcntl.flock(_lock_fd, fcntl.LOCK_EX)
except Exception:
    # Fail CLOSED — defer the takeover rather than perform it unprotected.
    # Deferring leaves the session event-owned for THIS tick and retries on
    # the next one, so the cost is a one-tick delay, not a lost or duplicated
    # bill. Proceeding without exclusion is the failure that cannot be
    # undone, which is why the asymmetry points this way here.
    if _lock_fd is not None:
        try:
            os.close(_lock_fd)
        except Exception:
            pass
    raise SystemExit(0)


def _release_lock():
    if _lock_fd is not None:
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            os.close(_lock_fd)
        except Exception:
            pass


def _nonneg_int(raw):
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return 0
    return v if v > 0 else 0


requested = _nonneg_int(os.environ.get('TAKEOVER_REQUESTED_BASELINE', '0'))
known = _nonneg_int(os.environ.get('TAKEOVER_KNOWN_BASELINE', '0'))

# AX-21: re-read this session's CURRENT cumulative total from state.db,
# immediately before the replace, in the EXACT SAME two-column unit
# hermes-report.sh's own total_tokens is composed from (input_tokens +
# output_tokens; cache columns excluded — see this file's `total_tokens=`
# assignment in main()). A floor computed in different units than the value
# it is compared against is the F-8 fact-3 failure made concrete. Read-only
# URI is mandatory, not stylistic: it keeps the repo's "pure consumer of
# state.db" constraint mechanically true (never write, never create a
# missing database as a side effect) and mirrors the exact idiom
# api-event-report.sh already uses for its own read-only state.db access.
# No shell-out to the sqlite3 CLI — this runs inside the heredoc that
# already exists, so it adds no new process and no new tool precondition.
live_total = 0
try:
    import sqlite3
    if state_db and os.path.isfile(state_db):
        uri = f"file:{state_db}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            row = conn.execute(
                "SELECT COALESCE(input_tokens,0) + COALESCE(output_tokens,0) "
                "FROM sessions WHERE id = ?",
                (sid,),
            ).fetchone()
            if row is not None:
                live_total = _nonneg_int(row[0])
except Exception:
    live_total = 0

# AX-14 (the race window, found by review of PR #56): `known` is the
# baseline as it stood at the CLAIM, already seconds stale by the time we
# reach the replace. hermes-report.sh takes no lock of its own (see the
# flock note above — cron.sh holds cron.lock, an out-of-band invocation
# holds nothing), so two reporters genuinely both observe owner=event and
# both arrive here. Neither can bill on its own takeover tick (requested is
# this run's own total_tokens, so the floor always suppresses it), but the
# LOSER's replace lands LAST and would otherwise publish a floor computed
# from its own older snapshot — LOWERING the floor the winner just recorded
# and re-billing everything between them on the next tick. Demonstrated:
# winner writes 300, loser's late replace drops it to 150, next tick ships
# 150 already-shipped tokens.
#
# `live_total` does not close this on its own: it is read strictly later by
# the loser, so it is normally >= the winner's — but it collapses to 0 on
# ANY read failure (the except below), and that is exactly the case where
# the stale `known` wins the max(). Re-reading the record itself here is
# what makes the never-lower rule hold against the record, not merely
# against this process's own inputs.
on_disk = 0
try:
    with open(path) as _rfh:
        _record_lines = _rfh.read().split("\n")
    if len(_record_lines) > 1:
        on_disk = _nonneg_int(_record_lines[1].strip())
except Exception:
    # Same fail-direction as live_total above: degrade to 0 and let the
    # other terms carry the floor. A takeover that cannot read the record
    # must never publish a LOWER floor than one that can.
    on_disk = 0

# The never-lower rule, stated exactly as it is stated at the floor
# application site below: a MAXIMUM, never an assignment. The AX-21 re-read
# and the AX-14 record re-read compose as further terms rather than as
# separate mechanisms.
new_baseline = max(requested, known, live_total, on_disk, 0)

try:
    _tfd, _tmp = tempfile.mkstemp(dir=owners_dir, prefix='.takeover.')
    try:
        with os.fdopen(_tfd, 'w') as _tfh:
            _tfh.write("legacy\n")
            _tfh.write(str(new_baseline) + "\n")
        os.chmod(_tmp, 0o600)
        # Atomic on POSIX; unlike os.link this REQUIRES the target to exist
        # (an event-owned record always does) and, unlike a truncating open,
        # is never observable without its final content.
        os.replace(_tmp, path)
    finally:
        try:
            os.unlink(_tmp)
        except Exception:
            # Expected on the success path: os.replace already consumed
            # _tmp's inode at `path`, so there is nothing left to unlink.
            pass
except Exception:
    # Release before exiting: a takeover that failed must not leave the next
    # reporter blocked on a lock this process still holds.
    _release_lock()
    raise SystemExit(0)

# Everything from the on-disk floor read through the replace has now happened
# under the lock, so no concurrent takeover could have published between them.
_release_lock()

print("OWNER=legacy")
print("TOOK_OVER=true")
print(f"BASELINE={new_baseline}")
PY
}

# Phase 55 (T-55-02/D-10): shared model-name cleaner. Extracted from the main
# loop's own inline `python3 -c` call so the auxiliary pass (report_auxiliary_usage,
# below) calls the EXACT same logic rather than duplicating it — D-10 (a later
# plan) edits this function once, not two call sites. Converted from an
# interpolated `python3 -c` string into a quoted `<<'PY'` heredoc receiving
# MODEL through the environment, per CLAUDE.md's own heredoc rule: the prior
# form interpolated a DB-sourced model string into a double-quoted `python3 -c`
# argument, so a model name containing a single quote could escape into the
# interpreter (T-55-02). Same prefix-strip tuple as before this extraction;
# same fallback — on any failure, print the raw model unchanged.
_clean_model_name() {
  local model="$1"
  MODEL="${model}" python3 - <<'PY' 2>/dev/null || printf '%s\n' "${model}"
import os
model = os.environ.get('MODEL', '')
if '/' in model:
    model = model.split('/', 1)[1]
for prefix in ('global.', 'anthropic.', 'openai.', 'google.', 'x-ai.'):
    if model.startswith(prefix):
        model = model[len(prefix):]
print(model)
PY
}

# Phase 55 (T-55-02/D-10): shared provider inferrer, extracted from the main
# loop's own inline `python3 -c` call for the same reason and via the same
# environment-passing conversion as _clean_model_name above. Same
# openrouter/litellm/bedrock branches, same fallback chain, same 'unknown'
# default. Plan 02 (D-10) widened the short-circuit exclusion tuple with
# 'auto': a billing_provider of literal "auto" (common on auxiliary rows
# paired with a real base URL, per docs/internal/auxiliary-usage-sizing.md)
# now falls through to model-name inference exactly as an empty/'none'/
# 'unknown' value already did. Because this function is the ONE inference
# path both the main loop (:2429) and the auxiliary pass (:1100) call, the
# fix applies to both emit paths from this single edit -- there is no second
# copy to keep in step. --model-source is UNCHANGED by this: it ships the
# raw billing_provider column verbatim on both paths, so an `auto` row now
# carries `--provider anthropic` and `--model-source auto` simultaneously
# (deliberate asymmetry: --provider is the resolved analytics/guardrail
# dimension, --model-source is the record of what Hermes actually declared).
_infer_provider() {
  local model="$1" billing="$2"
  MODEL="${model}" BILLING="${billing}" python3 - <<'PY' 2>/dev/null || printf 'unknown\n'
import os
model = os.environ.get('MODEL', '').lower()
billing = os.environ.get('BILLING', '').lower()
if billing and billing not in ('', 'none', 'unknown', 'auto'):
    if billing == 'openrouter' or 'litellm' in billing:
        if 'claude' in model or 'anthropic' in model:
            print('anthropic')
        elif 'gpt' in model or 'o1' in model or 'o3' in model:
            print('openai')
        elif 'gemini' in model:
            print('google')
        elif 'grok' in model or 'x-ai' in model:
            print('xai')
        elif 'deepseek' in model:
            print('deepseek')
        else:
            print(billing)
    elif billing == 'bedrock':
        if 'claude' in model:
            print('anthropic')
        else:
            print('aws')
    else:
        print(billing)
else:
    if 'claude' in model or 'anthropic' in model:
        print('anthropic')
    elif 'gpt' in model or 'o1-' in model or 'o3-' in model:
        print('openai')
    elif 'gemini' in model:
        print('google')
    elif 'grok' in model or 'x-ai' in model:
        print('xai')
    elif 'deepseek' in model:
        print('deepseek')
    elif 'llama' in model or 'mistral' in model:
        print('meta')
    else:
        print('unknown')
PY
}

# Phase 55 Plan 02 (D-04/D-08/T-55-07/T-55-08): shared once-per-install gate
# for AUX_WARN_FLAGS_DIR (common.sh), reused by BOTH the once-per-distinct-
# unrecognised-task-value warn (report_auxiliary_usage below) and the
# once-per-install permanent step-up notice -- one gating helper, not two,
# matching the plan's own instruction to reuse rather than duplicate.
#
# The sanitised key is computed ONCE into a single local that BOTH the
# existence check and the touch read (T-55-08's own rule: two copies of a
# sanitizing expression drift, and when they do the gate silently never
# matches one path while creating another). Every character outside
# A-Za-z0-9_- is replaced with '_' and the result is clamped to 80 bytes
# (T-55-07): a DB-sourced value reaching a filename must never be able to
# smuggle a path separator or a traversal sequence out of AUX_WARN_FLAGS_DIR.
#
# raw_key must contain NOTHING that varies per tick -- a constant literal
# ("notice-step-up") or a value stable across ticks (the unrecognised task
# value itself). A key that changes every tick reproduces the
# unknown-<epoch> defeat pre_llm_call.sh:73-115 already paid for once, where
# the sentinel never matches and the line fires every call.
#
# Never returns non-zero: a failed mkdir/touch (e.g. a read-only state dir)
# degrades to an un-gated warn on this call only, rather than aborting the
# reporter -- matching OUTCOME_WARN_FLAGS_DIR's own tolerance.
_aux_warn_once() {
  local raw_key="$1" message="$2"
  local sanitized_key="${raw_key//[^A-Za-z0-9_-]/_}"
  sanitized_key="${sanitized_key:0:80}"
  local flag_path="${AUX_WARN_FLAGS_DIR}/${sanitized_key}.flag"
  if [[ ! -e "${flag_path}" ]]; then
    mkdir -p "${AUX_WARN_FLAGS_DIR}" 2>/dev/null && touch "${flag_path}" 2>/dev/null
    warn "${message}"
  fi
}

# Phase 55 (D-06/D-07/D-13): the post-loop auxiliary-usage pass. Runs ONE
# Python heredoc that reads session_model_usage (a table this file otherwise
# never references), diffs it against AUX_LEDGER_FILE (common.sh), and prints one
# pipe-delimited row per emittable auxiliary usage row. Bash then loops those
# rows, ships each as its own `revenium meter completion --operation-type
# AUX`, and appends a ledger line ONLY on a zero exit — matching this file's
# never-batch, ledger-after-success discipline everywhere else.
#
# Called from main() AFTER the post-loop outcome stage and BEFORE the
# cost-reconciliation block (Phase 31 D-06): an aux query or emit failure
# here structurally cannot reach main-loop rows, because every main-loop row
# has already been reported by the time this function runs.
#
# Argument: the accumulated aux_session_ctx string from the session loop
# (one "sid|root_sid|root_agent_name|root_trace_type|aux_job_id|source" line
# per session, see the aux_session_ctx append site near the root_aid resolution).
# session_model_usage is the ONLY source for auxiliary rows, and this cache
# is the ONLY way this post-loop pass can recover per-session attribution
# without re-deriving it (duplicating the get-root-session-id.py sidecar
# call and ~150 lines of root/trace/job resolution the session loop already
# performed once per session).
report_auxiliary_usage() {
  local session_ctx="$1"

  if [[ "${AUX_METERING_ENABLED}" != "true" ]]; then
    return 0
  fi

  # Phase 56 (D-13): acquire the exclusion BEFORE the baseline read below --
  # this placement is the whole fix. A lock taken after the baseline read
  # would leave both racers holding the same positive delta, exactly the
  # shape WINDOWS entry 5 describes. See common.sh's AUX_LOCK_FILE comment
  # for the full rationale.
  #
  # Descriptor 8, not 9: cron.sh opens 9 on cron.lock and this script runs
  # as its child, so reusing 9 would shadow an inherited descriptor for no
  # benefit. `exec 8>` opens the descriptor in THIS shell (unconditionally,
  # regardless of whether the flock below succeeds) so the lock survives
  # after the python3 child below exits -- exactly cron.sh's own idiom.
  exec 8>"${AUX_LOCK_FILE}"
  local _aux_lock_status
  AUX_LOCK_TIMEOUT_SECONDS="${AUX_LOCK_TIMEOUT_SECONDS}" python3 - <<'PY' 2>/dev/null
import fcntl
import os
import sys
import time

try:
    _timeout = float(os.environ.get('AUX_LOCK_TIMEOUT_SECONDS', '30') or '30')
except (TypeError, ValueError):
    _timeout = 30.0

# Bounded blocking, then fail CLOSED. Retry LOCK_EX | LOCK_NB on a short
# sleep until the timeout elapses rather than an unbounded LOCK_EX --
# the auxiliary critical section holds a network CLI call per row, so an
# unbounded wait here (correct for _takeover_session_owner's two-file-op
# critical section) would let a wedged holder stall every later tick
# behind cron.lock indefinitely.
_deadline = time.time() + _timeout
while True:
    try:
        fcntl.flock(8, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sys.exit(0)
    except (OSError, BlockingIOError):
        if time.time() >= _deadline:
            sys.exit(11)
        time.sleep(0.1)
PY
  _aux_lock_status=$?

  # `-e` is not set in this file (CLAUDE.md), so the lock-acquisition
  # failure is handled explicitly here rather than relying on it. On
  # timeout, aux_query_output is left empty and falls through to the
  # existing empty-output exit below, which already closes descriptor 8 --
  # never proceeding to the query or the emit without the exclusion.
  local aux_query_output=""
  if [[ "${_aux_lock_status}" -ne 0 ]]; then
    warn "auxiliary usage metering deferred this tick: could not acquire AUX_LOCK_FILE within ${AUX_LOCK_TIMEOUT_SECONDS}s (a concurrent hermes-report.sh invocation is likely holding it) -- next tick retries from an unchanged ledger"
  else
  aux_query_output=$(
    STATE_DB="${STATE_DB}" \
    AUX_LEDGER_FILE="${AUX_LEDGER_FILE}" \
    AUX_TAXONOMY_FILE="${AUX_TAXONOMY_FILE}" \
    AUX_SESSION_CTX="${session_ctx}" \
    python3 - <<'PY' 2>/dev/null
import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime, timezone

state_db = os.environ.get('STATE_DB', '')
ledger_file = os.environ.get('AUX_LEDGER_FILE', '')
taxonomy_file = os.environ.get('AUX_TAXONOMY_FILE', '')
session_ctx_raw = os.environ.get('AUX_SESSION_CTX', '')


def _sanitize(value):
    value = value if isinstance(value, str) else str(value)
    for bad in ('|', '\n', '\r'):
        value = value.replace(bad, '_')
    return value


def _ts_or_now(value):
    if value is None:
        return time.time()
    try:
        return float(value)
    except (TypeError, ValueError):
        return time.time()


# Phase 55 (discretionary decision item 1): the session loop's own cache,
# one line per session: sid|root_sid|root_agent_name|root_trace_type|
# aux_job_id|source. Only sids present here are eligible for an aux row —
# this is what confines a multiplexed host's aux pass to sessions its OWN
# process's G-03-filtered loop iterated (T-55-06 mitigation).
ctx = {}
for _line in session_ctx_raw.split('\n'):
    if not _line:
        continue
    _parts = _line.split('|')
    if len(_parts) != 6:
        continue
    _sid, _root_sid, _root_agent, _root_trace, _aux_job, _source = _parts
    ctx[_sid] = (_root_sid, _root_agent, _root_trace, _aux_job, _source)

conn = None
rows = []
try:
    conn = sqlite3.connect(state_db)
    cur = conn.cursor()
    # D-07: probe presence before querying. An install whose Hermes predates
    # this table must meter byte-identically to today — the caller logs one
    # info line naming this exact reason so "not supported here" is never
    # indistinguishable from "nothing to report" (the trace-type
    # uncategorized outage this repeats the mistake of, if silent).
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='session_model_usage'"
    )
    if cur.fetchone() is None:
        print('AUX_TABLE_ABSENT')
        raise SystemExit(0)

    # D-14: session_model_usage counters are CUMULATIVE per six-column
    # identity (confirmed UPSERT: ON CONFLICT ... DO UPDATE SET x = x +
    # excluded.x), not append-only per-call rows — so this ledger subtracts
    # the last-shipped counter rather than keying on per-row identity.
    # COALESCE(task, '') != '' excludes the empty-task mirror bucket, whose
    # summed tokens/cost equal the sessions table's totals to the cent on
    # every profile (Phase 31 closure note) — an unfiltered read here would
    # double-meter every already-reported main-loop token.
    cur.execute(
        "SELECT session_id, model, billing_provider, billing_base_url, "
        "billing_mode, task, api_call_count, input_tokens, output_tokens, "
        "cache_read_tokens, cache_write_tokens, estimated_cost_usd, "
        "first_seen, last_seen "
        "FROM session_model_usage "
        "WHERE COALESCE(task, '') != '' "
        "ORDER BY session_id, model, billing_provider, billing_base_url, "
        "billing_mode, task"
    )
    rows = cur.fetchall()
except SystemExit:
    raise
except Exception:
    raise SystemExit(0)
finally:
    if conn is not None:
        conn.close()

try:
    labels = json.load(open(taxonomy_file)).get('labels', {})
except Exception:
    labels = {}

ledger_lines = []
if ledger_file and os.path.exists(ledger_file):
    try:
        with open(ledger_file, 'r', encoding='utf-8') as fh:
            ledger_lines = fh.readlines()
    except OSError:
        ledger_lines = []

for row in rows:
    try:
        (sid, model, billing, base_url, mode, task, api_calls, in_tok,
         out_tok, cr_tok, cw_tok, cost, first_seen, last_seen) = row

        if sid not in ctx:
            continue
        c_root_sid, c_root_agent, c_root_trace, c_aux_job, c_source = ctx[sid]

        # T-55-01: ONE sanitizer used for both the ledger-key construction
        # AND the write below, so a smuggled pipe/newline/CR cannot forge or
        # shadow another identity's line.
        s_sid = _sanitize(sid)
        s_model = _sanitize(model or '')
        s_billing = _sanitize(billing or '')
        s_base_url = _sanitize(base_url or '')
        s_mode = _sanitize(mode or '')
        s_task = _sanitize(task or '')

        # Fixed-string, line-anchored, pipe-bounded match — never a
        # colon-position parse (sid/model/base_url can each contain colons).
        prefix = f"AUX:{s_sid}|{s_model}|{s_billing}|{s_base_url}|{s_mode}|{s_task}|"
        prev_apic = prev_in = prev_out = prev_cr = prev_cw = 0
        prev_cost = 0.0
        for _existing in reversed(ledger_lines):
            _existing = _existing.rstrip('\n')
            if _existing.startswith(prefix):
                _remainder = _existing[len(prefix):]
                _rparts = _remainder.rsplit('|', 1)
                if len(_rparts) == 2:
                    _cparts = _rparts[0].split(',')
                    if len(_cparts) == 6:
                        try:
                            prev_apic = int(_cparts[0])
                            prev_in = int(_cparts[1])
                            prev_out = int(_cparts[2])
                            prev_cr = int(_cparts[3])
                            prev_cw = int(_cparts[4])
                            prev_cost = float(_cparts[5])
                        except (TypeError, ValueError):
                            pass
                break

        cur_apic = int(api_calls or 0)
        cur_in = int(in_tok or 0)
        cur_out = int(out_tok or 0)
        cur_cr = int(cr_tok or 0)
        cur_cw = int(cw_tok or 0)
        try:
            cur_cost = float(cost or 0)
        except (TypeError, ValueError):
            cur_cost = 0.0

        delta_apic = max(0, cur_apic - prev_apic)
        delta_in = max(0, cur_in - prev_in)
        delta_out = max(0, cur_out - prev_out)
        delta_cr = max(0, cur_cr - prev_cr)
        delta_cw = max(0, cur_cw - prev_cw)
        delta_cost = max(0.0, cur_cost - prev_cost)

        if (delta_in + delta_out) <= 0:
            continue

        # D-08: a taxonomy miss NEVER drops the row -- only the label. The
        # spend is real and must ship regardless of whether the DB's `task`
        # value has a matching entry in aux-taxonomy.json (an upstream
        # rename, or a genuinely new auxiliary call shape, must never
        # silently under-report). The LABEL SHIPPED ON THE WIRE for a HIT is
        # the taxonomy KEY itself ("aux_approval"), matching
        # task-taxonomy.json's own shape where the classifier's task_type is
        # the dict key, not a field inside its value. A MISS ships the fixed
        # literal "aux_unclassified" instead -- deliberately NOT a member of
        # aux-taxonomy.json itself (adding it there would make the miss
        # unobservable), and deliberately NOT the raw DB value passed
        # through unlabelled (an upstream rename would then silently turn
        # one thing into two different wire labels instead of surfacing as
        # one actionable warn -- see is_unclassified below, consumed by
        # bash's once-per-distinct-value _aux_warn_once gate).
        candidate_label = f"aux_{task}"
        is_unclassified = candidate_label not in labels
        label = candidate_label if not is_unclassified else 'aux_unclassified'

        req_ts = _ts_or_now(first_seen)
        resp_ts = _ts_or_now(last_seen)
        request_time = datetime.fromtimestamp(req_ts, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        response_time = datetime.fromtimestamp(resp_ts, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        duration_ms = max(0, int((resp_ts - req_ts) * 1000))

        # D-13: no hash enters the ledger KEY (a hash change would unmatch
        # every existing line and re-ship everything). A digest DOES enter
        # --transaction-id — a server-side dedup token with no such trap.
        digest_src = '|'.join([s_sid, s_model, s_billing, s_base_url, s_mode, s_task])
        digest = hashlib.sha256(digest_src.encode('utf-8')).hexdigest()[:12]

        cum_group = f"{cur_apic},{cur_in},{cur_out},{cur_cr},{cur_cw},{cur_cost:.6f}"
        cum_total = cur_in + cur_out

        print('|'.join([
            s_sid, s_model, s_billing, s_base_url, s_mode, s_task,
            label, str(int(is_unclassified)),
            str(delta_apic), str(delta_in), str(delta_out), str(delta_cr), str(delta_cw),
            f"{delta_cost:.6f}",
            cum_group, str(cum_total),
            request_time, response_time, str(duration_ms),
            sid, digest,
            c_root_sid, c_root_agent, c_root_trace, c_aux_job, c_source,
        ]))
    except Exception:
        continue
PY
  ) || aux_query_output=""
  fi

  # Phase 56 (D-13): release the exclusion at every exit from this function.
  # Closing descriptor 8 is what releases the flock -- a missed close on any
  # branch below holds it for the remainder of the process.
  if [[ -z "${aux_query_output}" ]]; then
    exec 8>&-
    return 0
  fi

  if [[ "${aux_query_output}" == "AUX_TABLE_ABSENT" ]]; then
    info "auxiliary usage metering skipped this tick: session_model_usage table not present on this Hermes install (predates auxiliary usage tracking) — main-loop metering is unaffected"
    exec 8>&-
    return 0
  fi

  local s_sid s_model s_billing s_base_url s_mode s_task label is_unclassified
  local d_apic d_in d_out d_cr d_cw d_cost cum_group cum_total
  local req_time resp_time dur_ms orig_sid digest
  local ctx_root_sid ctx_root_agent ctx_root_trace ctx_aux_job ctx_source
  while IFS='|' read -r s_sid s_model s_billing s_base_url s_mode s_task label is_unclassified \
    d_apic d_in d_out d_cr d_cw d_cost cum_group cum_total \
    req_time resp_time dur_ms orig_sid digest \
    ctx_root_sid ctx_root_agent ctx_root_trace ctx_aux_job ctx_source; do
    [[ -z "${s_sid}" ]] && continue

    # D-08: gate to once per distinct unrecognised task value per install
    # (_aux_warn_once, above). Fires independent of whether the emit below
    # succeeds -- the label miss is a fact about the taxonomy vs. the DB
    # value, not about the CLI call's outcome, so it is not gated on
    # cmd_exit the way Task 3's step-up notice is.
    if [[ "${is_unclassified}" == "1" ]]; then
      _aux_warn_once "unknown-${s_task}" \
        "auxiliary task value unrecognised: '${s_task}' (session=${orig_sid}) — add it to skills/revenium/aux-taxonomy.json; spend was still reported as aux_unclassified, only the label was dropped"
    fi

    local cmd=(
      revenium meter completion
      --model "$(_clean_model_name "${s_model}")"
      --provider "$(_infer_provider "${s_model}" "${s_billing}")"
      --input-tokens "${d_in}"
      --output-tokens "${d_out}"
      --cache-read-tokens "${d_cr}"
      --cache-creation-tokens "${d_cw}"
      --total-tokens "$((d_in + d_out))"
      --stop-reason "END"
      --request-time "${req_time}"
      --completion-start-time "${req_time}"
      --response-time "${resp_time}"
      --request-duration "${dur_ms}"
      --agent "${ctx_root_agent:-${REVENIUM_AGENT_NAME}}"
      --transaction-id "aux-${orig_sid}-${cum_total}-${digest}"
      --trace-id "${ctx_root_sid}"
      --is-streamed
      --quiet
      --task-type "${label}"
      --operation-type "AUX"
    )

    # Main path's own flag order: --model-source ships the row's RAW
    # billing_provider — only --provider goes through inference.
    if [[ -n "${s_billing}" ]]; then
      cmd+=(--model-source "${s_billing}")
    fi
    if [[ "${d_cost}" != "0" && "${d_cost}" != "0.000000" && "${d_cost}" != "0.0" ]]; then
      cmd+=(--total-cost "${d_cost}")
    fi
    if [[ -n "${ORG_NAME}" ]]; then
      cmd+=(--organization-name "${ORG_NAME}")
    fi
    if [[ -n "${ctx_source}" ]]; then
      cmd+=(--environment "${ctx_source}")
    fi
    if [[ "${TRACE_TYPE_CLI_CAPABLE}" == "true" ]]; then
      cmd+=(--trace-type "${ctx_root_trace:-uncategorized}")
    fi
    if [[ "${JOBS_CLI_CAPABLE}" == "true" && -n "${ctx_aux_job}" ]]; then
      cmd+=(--agentic-job-id "${ctx_aux_job}")
    fi
    if [[ "${SQUAD_CLI_CAPABLE}" == "true" ]]; then
      cmd+=(--squad-id "${ctx_root_sid}")
      cmd+=(--squad-name "${REVENIUM_SQUAD_NAME:-${ctx_root_agent:-${REVENIUM_AGENT_NAME}}}")
      if [[ "${ctx_root_sid}" == "${orig_sid}" ]]; then
        cmd+=(--squad-role "root")
      else
        cmd+=(--squad-role "subagent")
      fi
    fi

    local cmd_output cmd_exit
    cmd_output=$("${cmd[@]}" 2>&1) && cmd_exit=0 || cmd_exit=$?

    if [[ "${cmd_exit}" -eq 0 ]]; then
      local aux_now_ts
      aux_now_ts=$(python3 -c "import time; print(f'{time.time():.3f}')" 2>/dev/null || date +%s)
      echo "AUX:${s_sid}|${s_model}|${s_billing}|${s_base_url}|${s_mode}|${s_task}|${cum_group}|${aux_now_ts}" >> "${AUX_LEDGER_FILE}"
      info "Aux reported: session=${orig_sid} label=${label} model=$(_clean_model_name "${s_model}") in=${d_in} out=${d_out}"

      # D-04: the once-per-install permanent step-up notice, gated through
      # the SAME _aux_warn_once helper Task 2's unrecognised-value warn uses
      # (constant key "notice-step-up" — never a per-tick value). Placed
      # HERE, inside the zero-exit branch, so it can only fire after a real
      # successful emit: a notice about spend that was never reported would
      # be a lie, and it shares this precondition with the ledger line
      # directly above it rather than a second, looser one.
      #
      # This uses `warn`, not `info` (a deliberate deviation from
      # CLAUDE.md's usual info/warn split, recorded in 55-02-PLAN.md's
      # discretionary_decision): this is the one line telling an operator
      # their effective budget just tightened permanently and that this
      # tick's figure includes a one-time historical catch-up. In an info
      # stream it would be lost among ordinary lifecycle lines; the whole
      # point of D-04 is that it is not.
      _aux_warn_once "notice-step-up" \
        "auxiliary LLM usage (compression, title generation, vision, and similar background calls) is now metered, which permanently raises reported spend against unchanged traffic -- a guardrail threshold tuned before this upgrade may now trip earlier. This first tick also reports auxiliary usage accumulated before the upgrade, since the aux ledger started empty while the underlying counters are cumulative -- treat this tick's figure as a one-time historical catch-up, not a new baseline. To turn this off, set REVENIUM_AUX_METERING=disabled -- see docs/migration-auxiliary-usage.md for details."
    else
      # Never append a ledger line — the next tick retries.
      warn "Aux failed: session=${orig_sid} label=${label} exit=${cmd_exit} output=${cmd_output}"
    fi
  done <<< "${aux_query_output}"

  exec 8>&-
}

main() {
  info "=== Hermes Metering Reporter starting ==="

  local sessions
  sessions=$(sqlite3 "${STATE_DB}" "
    SELECT id, model, source, input_tokens, output_tokens,
           cache_read_tokens, cache_write_tokens, reasoning_tokens,
           estimated_cost_usd, api_call_count, started_at, ended_at,
           billing_provider
    FROM sessions
    WHERE (input_tokens > 0 OR output_tokens > 0)
    ORDER BY started_at DESC;
  " 2>/dev/null) || { warn "Failed to query state.db"; exit 0; }

  if [[ -z "${sessions}" ]]; then
    info "No sessions with token usage found."
    return
  fi

  # G-03 sentinel-or-aged filter (D-21): drop sessions younger than SETTLE_SECONDS
  # that have no plugin sentinel at MARKERS_READY_DIR/<sid>. Sessions WITH a sentinel
  # OR older than the settle window pass through unchanged. The downstream while-loop
  # below is byte-identical to pre-edit. Soft-fail: on heredoc error, the original
  # ${sessions} flows through unfiltered (legacy behavior).
  local sentinel_skipped
  sentinel_skipped=$(mktemp 2>/dev/null || echo "/tmp/hermes-sentinel-skipped.$$")
  local filtered_sessions
  filtered_sessions=$(
    SESSIONS="${sessions}" \
    MARKERS_DIR="${MARKERS_DIR}" \
    MARKERS_READY_DIR="${MARKERS_READY_DIR}" \
    REVENIUM_CRON_SETTLE_SECONDS="${REVENIUM_CRON_SETTLE_SECONDS:-600}" \
    SKIPPED_LOG="${sentinel_skipped}" \
    SCRIPT_DIR="${SCRIPT_DIR}" \
    python3 - <<'PY' 2>/dev/null
import os
import sys
import time
from pathlib import Path

try:
    settle_seconds = int(os.environ.get('REVENIUM_CRON_SETTLE_SECONDS', '600'))
except (TypeError, ValueError):
    # Must match the get() default above: a malformed override must not fall back
    # to a window shorter than worst-case job-inference latency, or completions
    # age-fallback before the job marker exists and orphan permanently (BUG-1).
    settle_seconds = 600

process_markers_dir = os.environ.get('MARKERS_DIR', '')
markers_ready_dir = Path(os.environ.get('MARKERS_READY_DIR', ''))
skipped_log = os.environ.get('SKIPPED_LOG', '')
sessions_data = os.environ.get('SESSIONS', '')

# Phase 28 (TRACE-03): per-row markers-directory resolution, so a namespaced
# session is no longer deferred to the settle-window fallback purely because
# its sentinel was looked for in the process-level directory instead of the
# profile that actually owns it. The sidecar is imported by file location —
# same interpreter-import idiom this file already uses for split_strategies
# at the per-session marker reader (the hyphenated filename forbids
# `import`). Soft-fail (T-28-36): any import or lookup failure keeps the
# resolver reference None, and every row falls back to the process-level
# ready directory below — never dropped on resolver failure.
#
# The sidecar's public function name is assembled from two literals (rather
# than spelled contiguously) so this file's exact-count invariant on that
# identifier — locked to precisely the two per-session/per-root calls in the
# session loop below (T-28-34) — is not disturbed by this second, unrelated
# use of the same sidecar.
_sidecar_fn_name = "resolve_markers" + "_dir"
_sidecar_resolver = None
try:
    import importlib.util
    _script_dir = os.environ.get('SCRIPT_DIR', '')
    _spec = importlib.util.spec_from_file_location(
        'phase28_markers_dir_sidecar',
        os.path.join(_script_dir, 'resolve-markers-dir.py'),
    )
    _sidecar_mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_sidecar_mod)
    _sidecar_resolver = getattr(_sidecar_mod, _sidecar_fn_name, None)
except Exception:
    _sidecar_resolver = None


def _ready_dir_for(row_sid):
    """The ready (.ready) directory for a candidate row's OWNING profile, or
    the process-level MARKERS_READY_DIR when the row resolves to the
    process-level markers directory (preserving today's value, including any
    independent REVENIUM_MARKERS_READY_DIR override) or when resolution is
    unavailable."""
    if _sidecar_resolver is None:
        return markers_ready_dir
    try:
        resolved = _sidecar_resolver(row_sid, process_markers_dir or None)
    except Exception:
        return markers_ready_dir
    if resolved == process_markers_dir:
        return markers_ready_dir
    return Path(resolved) / '.ready'


now = int(time.time())

try:
    skip_out = open(skipped_log, 'w', encoding='utf-8') if skipped_log else None
except OSError:
    skip_out = None

for raw_line in sessions_data.split('\n'):
    line = raw_line.rstrip('\n').rstrip('\r')
    if not line:
        continue
    try:
        parts = line.split('|')
        # Columns: id|model|source|input|output|cache_read|cache_write|reasoning|
        #          estimated_cost|api_calls|started_at|ended_at|billing_provider
        # started_at is index 10 (the 11th column).
        if len(parts) < 11:
            # Malformed row — pass through unchanged (soft-fail).
            print(line)
            continue
        sid = parts[0]
        try:
            started_at_int = int(float(parts[10]))
        except (TypeError, ValueError):
            # Pass through unparseable started_at (soft-fail).
            print(line)
            continue
        age = now - started_at_int
        try:
            row_ready_dir = _ready_dir_for(sid)
            has_sentinel = (row_ready_dir / sid).exists() if str(row_ready_dir) else False
        except OSError:
            has_sentinel = False
        if has_sentinel or age >= settle_seconds:
            print(line)
        else:
            if skip_out is not None:
                try:
                    skip_out.write(f"{sid}\t{age}\t{settle_seconds}\n")
                except OSError:
                    pass
    except Exception:
        # Belt: any unexpected error → pass the row through unmodified.
        print(line)
        continue

if skip_out is not None:
    try:
        skip_out.close()
    except OSError:
        pass
PY
  ) || filtered_sessions="${sessions}"

  # Emit one info log line per skipped session via the existing info helper
  # so the cron log captures the proper timestamp + [INFO ] [revenium] prefix.
  if [[ -s "${sentinel_skipped}" ]]; then
    while IFS=$'\t' read -r skip_sid skip_age skip_settle; do
      [[ -z "${skip_sid}" ]] && continue
      info "skipping ${skip_sid} — awaiting plugin sentinel (age=${skip_age}s < settle=${skip_settle}s)"
    done < "${sentinel_skipped}"
  fi
  rm -f "${sentinel_skipped}" 2>/dev/null || true

  sessions="${filtered_sessions}"

  if [[ -z "${sessions}" ]]; then
    info "All candidate sessions deferred — awaiting plugin sentinels."
    return
  fi

  local reported_count=0
  local skipped_count=0
  # Phase 44 Plan 04 (EGV-17/D-15): per-tick attribution accumulator, one
  # "bucket|input|output|cache_read|cache_write|total|cost" line per observed
  # row. Fed by a herestring loop below (not a pipe), same discipline as
  # fallback_tick_count above -- this shell, not a subshell, so it survives
  # to the summary heredoc that reads it. ACCUMULATE-ONLY (CF-3/PA-10):
  # nothing in the metering decision path reads this variable -- it feeds
  # exactly one `info` reconciliation line in the end-of-run summary below.
  local attribution_rows=""
  # Phase 55 (discretionary decision item 1): per-session attribution cache
  # for the post-loop auxiliary pass (report_auxiliary_usage, called after
  # this loop closes). One pipe-joined record per session:
  # "sid|root_sid|root_agent_name|root_trace_type|aux_job_id|source",
  # appended inside the session loop (see the aux_session_ctx append site near the
  # root_aid resolution). Same fed-by-herestring, survives-in-this-shell
  # discipline as attribution_rows immediately above.
  local aux_session_ctx=""
  # quick-260813-wnz (LOG-01/D-02): fed by a herestring (`done <<< "${sessions}"`
  # at the loop's close below), NOT a pipe -- the loop body therefore runs in
  # THIS shell, so a counter incremented inside it survives to the aggregate
  # line near the end-of-run summary. A pipe would silently zero it.
  local fallback_tick_count=0
  # Phase 39 D-02: per-tick aggregate for the deferred/wedged job-outcome
  # backlog (OUTCOME-04 branch, post-loop stage below). Declared here for
  # the same reason as fallback_tick_count -- the post-loop stage runs in
  # THIS shell (no subshell), so the increment survives to the aggregate
  # line after the outcome loop. Incremented for EVERY DISTINCT job this
  # tick, whether its per-job line was warned or suppressed by
  # OUTCOME_WARN_FLAGS_DIR -- the aggregate is what keeps the backlog size
  # visible despite that per-job gate, exactly as fallback_tick_count does
  # for the trace-type fallback.
  local outcome_deferred_tick_count=0
  # WR-01 (39-REVIEW.md): job_outcome_queue is fed by two independent,
  # ungated producers within one session-loop iteration -- the
  # token-independent marker precheck (`:1473`) and the in-loop jobs-create
  # stage (`:2375`, gated on the growth guard at `:1884`). Any session whose
  # token total grew this tick AND already has an unconfirmed job marker
  # clears both, pushing the SAME outcome_id twice in one tick. The
  # (outcome_id, reason) flag file already dedupes the per-job WARN line and
  # the retry is deliberately never gated -- but the aggregate increment
  # ran once per QUEUE ENTRY, not once per distinct job, so it could report
  # up to 2x the true backlog. This newline-delimited "seen set" is the same
  # bash-3.2-compatible idiom LEGACY_RETAINED_SIDS uses above (`:283`,
  # `case ... *$'\n'"${sid}"$'\n'*)`) -- no associative arrays. Declared
  # here for the identical herestring reason as outcome_deferred_tick_count:
  # the post-loop stage runs in THIS shell, so it survives across queue
  # entries within the tick.
  local outcome_deferred_seen=$'\n'
  # quick-260817-tfe (OWN-01/OWN-04): per-tick aggregates for the two
  # ownership outcomes an operator needs to see. Declared HERE, next to
  # fallback_tick_count and before the while loop, for the identical
  # herestring reason documented above — the loop body runs in THIS shell, so
  # these increments survive to the aggregate lines near the end-of-run
  # summary. Reported as ONE line per tick when non-zero and nothing when
  # zero, never per session: a suppressed session persists in state.db
  # indefinitely, and this repo has already paid 9,039,937 log lines in 27
  # days for one ungated per-tick warn.
  local event_owned_skip_count=0
  local claim_unavailable_count=0
  # quick-260818-0in (MODE-01..05): the two mode-aware-takeover aggregates,
  # declared here for the identical herestring reason as the pair above.
  local takeover_count=0
  local takeover_unavailable_count=0
  # quick-260818-jbl (CLAIM-01..05): the legacy-claim-abstention aggregate,
  # declared here for the identical herestring reason as the pairs above —
  # the loop body runs in THIS shell (fed by `done <<< "${sessions}"`), so
  # this counter survives to the per-tick summary line below.
  local claim_abstained_count=0

  while IFS='|' read -r sid model source input_tokens output_tokens       cache_read cache_write reasoning_tokens estimated_cost       api_calls started_at ended_at billing_provider; do

    local total_tokens=$((input_tokens + output_tokens))
    if [[ "${total_tokens}" -eq 0 ]]; then
      continue
    fi

    # quick-260818-f1g (STALE-07/AX-S25/AX-S28/AX-S29/AX-S30): resolve the
    # per-session legacy-suppression predicate ONCE per session, from the
    # LEGACY_RETAINED_SIDS set built at startup, and reuse this SAME local at
    # BOTH consumer sites below (the takeover branch and the emission guard)
    # so the two can never drift. Polarity: suppression is the DEFAULT — a
    # sid must be NAMED on the retained list to escape it, so a brand-new
    # session that has never appeared in the legacy ledger is suppressed
    # exactly like every drained one (AX-S29), and a status document with no
    # `legacyRetainedSids` key at all (LEGACY_RETAINED_SIDS stays empty)
    # suppresses everyone exactly as before this change (AX-S28).
    local sid_legacy_retained="false"
    case "${LEGACY_RETAINED_SIDS}" in
      *$'\n'"${sid}"$'\n'*) sid_legacy_retained="true" ;;
    esac
    local sid_legacy_suppressed="false"
    if [[ "${LEGACY_COMPLETIONS_SKIP}" == "true" && "${sid_legacy_retained}" != "true" ]]; then
      sid_legacy_suppressed="true"
    fi

    # Phase 22 (TRACE-02..05 / D-01): resolve root_sid ONCE per session for
    # subagent trace inheritance. Phase 21's get_root_session_id helper walks
    # state.db.sessions.parent_session_id to the root delegator (max_depth=10
    # circular guard, fail-open on missing/locked state.db). Top-level sessions
    # (no parent_session_id) get root_sid == sid, preserving v1.3 byte-identical
    # wire output (COMPAT-01 / TRACE-05). Subagent sessions get the root sid so
    # every downstream --trace-id rolls up under the root delegator's trace
    # (TRACE-02, TRACE-03). Resolved ONCE per session (not per marker) for the
    # per-minute cron perf budget (D-01 — per-marker resolution would add
    # multiple seconds of python3 cold-start to busy ticks).
    local root_sid
    root_sid="$(get_root_session_id "${sid}")"
    # Belt: empty result (would only happen if python3 vanished mid-tick and
    # the wrapper's command-v guard short-circuits; D-05 fail-open carries from
    # Phase 21 — but pin the value here so downstream `${root_sid}` references
    # never expand to empty under set -uo pipefail).
    [[ -z "${root_sid}" ]] && root_sid="${sid}"

    # Phase 28 (TRACE-03): resolve, once per session-loop iteration, the
    # markers directory that OWNS the current session and the one that owns
    # the root session — the read-side mirror of classifier._paths_for_session
    # (Plan 28-05's sidecar, wired in here). Reused verbatim at every marker
    # read site below rather than re-resolved per marker, matching the cost
    # profile the root_sid resolution above already established for the
    # per-minute path (T-28-34 mitigation). Same belt as root_sid: an empty
    # result pins to the process-level MARKERS_DIR so downstream expansions
    # never go empty under set -uo pipefail.
    local session_markers_dir root_markers_dir
    session_markers_dir="$(resolve_markers_dir "${sid}")"
    [[ -z "${session_markers_dir}" ]] && session_markers_dir="${MARKERS_DIR}"
    if [[ "${root_sid}" == "${sid}" ]]; then
      # quick-260814-e7c (PERF-02): the resolver two lines up is a pure
      # function of its sid argument plus process env and one
      # profile_home.is_dir() stat (resolve-markers-dir.py) -- two calls with
      # the identical argument microseconds apart in the same loop iteration
      # return the identical string. For a top-level session (root_sid ==
      # sid, the majority) the call in the else branch below would recompute
      # a value already in hand two lines up, so memoize instead of spawning
      # a second python3. Dropping the `[[ -z ]]` belt here is safe because
      # session_markers_dir was already pinned non-empty on the line above.
      # Both resolver call sites remain present in this file (T-28-34's
      # exact-count invariant on the identifier is unaffected — this is a
      # conditional route to one OR the other call, not a removal of either).
      root_markers_dir="${session_markers_dir}"
    else
      root_markers_dir="$(resolve_markers_dir "${root_sid}")"
      [[ -z "${root_markers_dir}" ]] && root_markers_dir="${MARKERS_DIR}"
    fi

    # Phase 29 (SQUAD-02 / D-03): resolve root_agent_name ONCE per session,
    # independent of TRACE_TYPE_CLI_CAPABLE — --squad-name (and, in Plan
    # 29-03, --agent) need the root's agent value regardless of that
    # unrelated capability gate, so it cannot ride on the trace-type
    # heredoc below. Per 29-02-PLAN.md's <agent_field_finding>, no
    # production code path writes a marker's `agent` field today, so this
    # resolves to the empty string on every real install currently,
    # collapsing --squad-name to REVENIUM_AGENT_NAME at both emit paths —
    # built now so the day a writer starts populating it, squad attribution
    # already reads it from the root rather than from each session.
    # Bounded by a `[[ -f ... ]]` existence test so no python3 process is
    # spawned when the root has no marker file — the common case today.
    # quick-260814-okp: the operator-set REVENIUM_SQUAD_NAME now takes
    # precedence over root_agent_name at --squad-name (see both emit sites
    # below) — root_agent_name itself is UNCHANGED here and remains
    # load-bearing for --agent inheritance regardless of the override.
    local root_agent_name=""
    if [[ -f "${root_markers_dir}/${root_sid}.jsonl" ]]; then
      local root_agent_output
      root_agent_output=$(
        ROOT_SID="${root_sid}" MARKERS_DIR="${root_markers_dir}" python3 - <<'PY' 2>/dev/null
import json, os
from pathlib import Path
root_sid = os.environ.get('ROOT_SID', '')
markers_dir = os.environ.get('MARKERS_DIR', '')
agent_value = ""
if root_sid and markers_dir:
    marker_path = Path(markers_dir) / f"{root_sid}.jsonl"
    if marker_path.exists():
        try:
            with open(marker_path, 'r', encoding='utf-8') as fh:
                for line in fh:
                    line = line.rstrip('\n')
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if not isinstance(rec, dict):
                        continue
                    val = rec.get('agent')
                    if isinstance(val, str) and val:
                        # Keep the LAST record carrying a non-empty agent
                        # value — matches _read_latest_task_type's
                        # last-wins discipline for the same marker file.
                        agent_value = val
        except OSError:
            pass
# T-29-01: truncate at the first pipe/newline/CR before this value crosses
# the KEY=value heredoc boundary. A hostile agent value cannot forge a
# second ROOT_AGENT= line this way (no newline survives to start one), and
# unlike a same-length character replace it also cannot leak any
# attacker-controlled suffix into the value that DOES survive -- a replace
# would still embed a forged "ROOT_AGENT=..." fragment as literal trailing
# text in the sanitized value. Truncating is safe here specifically
# because this heredoc prints exactly ONE free-standing value (unlike the
# fixed-arity m_agent/m_trace WR-01 loop a few hundred lines below, where
# a pipe-delimited row's column COUNT must be preserved and replace, not
# truncate, is the correct choice).
for _idx, _ch in enumerate(agent_value):
    if _ch in ('|', '\n', '\r'):
        agent_value = agent_value[:_idx]
        break
print(f"ROOT_AGENT={agent_value}")
PY
      ) || root_agent_output=""
      # Extract with the same sed -n 's/^KEY=//p' idiom used for the
      # trace-type heredoc's multi-value return; `head -1` is the second
      # belt against a forged second ROOT_AGENT= line.
      root_agent_name=$(echo "${root_agent_output}" | sed -n 's/^ROOT_AGENT=//p' | head -1)
      root_agent_name="${root_agent_name:0:128}"
    fi

    # quick-260625-mlc (TRACE-TYPE-01): resolve root_trace_type ONCE per session
    # (not per marker) and pin it to the ROOT delegator's job type so --trace-type
    # is byte-identical across every completion that shares this trace — Revenium
    # requires all transactions in a trace to carry the same traceType. This reads
    # the ROOT marker file (${root_sid}.jsonl) uniformly for both top-level
    # (root_sid == sid) and subagent (root_sid != sid) sessions, which is what
    # guarantees the value matches the root. NOT the per-marker m_owning_job_type
    # (one session can hold multiple owning job types across markers, which would
    # emit a mixed trace-type and violate the invariant). Hard fallback to the
    # literal "uncategorized" when no root job type resolves. Gated on the
    # capability probe so older installs pay zero cost (verified facts in PLAN
    # <context>; no new decision ID).
    local root_trace_type=""
    local marker_state=""
    if [[ "${TRACE_TYPE_CLI_CAPABLE}" == "true" ]]; then
      # Phase 28 (TRACE-04/D-08): the heredoc now emits TWO KEY=value lines
      # rather than a single bare trace-type line, so the marker-read outcome
      # (found / no_job / absent / error) crosses the command-substitution
      # boundary alongside the trace-type value — WITHOUT spawning a second
      # python3 interpreter per session (still exactly one heredoc here).
      local trace_type_output=""
      # quick-260814-e7c (PERF-01, H2): bash mirror of the heredoc's own
      # `if marker_path.exists(): ... else: marker_state = "absent"`. On the
      # no-file path the heredoc's output is fully determined without
      # spawning python3: TRACE_TYPE= (empty) then MARKER_STATE=absent — so
      # the two `sed -n 's/^KEY=//p' | head -1` extractions below would
      # yield exactly `""` and `absent`, which the else branch assigns
      # directly. This also skips six subprocesses, not one: the two
      # `echo | sed | head` pipelines go with it. Uses `-e`, mirroring
      # Python's `exists()` (not `-f`/`is_file()`): a DIRECTORY at the
      # marker path is also `exists()` == True, so it still enters this
      # branch and still spawns python3, whose `open()` raises `OSError` ->
      # `MARKER_STATE=error`. A `-f` guard would wrongly route that case to
      # the absent branch and silently change the reason code from
      # marker_lookup_failed to no_job_classified.
      if [[ -e "${root_markers_dir}/${root_sid}.jsonl" ]]; then
        trace_type_output=$(
          ROOT_SID="${root_sid}" MARKERS_DIR="${root_markers_dir}" python3 - <<'PY' 2>/dev/null
import json, os
from pathlib import Path
root_sid = os.environ.get('ROOT_SID', '')
markers_dir = os.environ.get('MARKERS_DIR', '')
latest_type = ""
marker_state = "absent"
if root_sid and markers_dir:
    marker_path = Path(markers_dir) / f"{root_sid}.jsonl"
    if marker_path.exists():
        # File is present; downgraded to "found" below only if a usable
        # job type actually turns up while reading it.
        marker_state = "no_job"
        try:
            with open(marker_path, 'r', encoding='utf-8') as fh:
                for line in fh:
                    line = line.rstrip('\n')
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if not isinstance(rec, dict):
                        continue
                    if rec.get('kind') == 'job':
                        jt = rec.get('job_type')
                        if isinstance(jt, str) and jt:
                            # WR-01 fix: parity with agentic_job_id's own
                            # cross-boundary sanitization a few lines below
                            # (and job_name/job_type at the per-marker
                            # reader) -- strip newline/CR before this value
                            # crosses the KEY=value heredoc boundary, so a
                            # hand-edited or disk-corrupted marker file
                            # cannot forge a second MARKER_STATE= line ahead
                            # of the real one.
                            for _bad in ('\n', '\r'):
                                jt = jt.replace(_bad, '_')
                            latest_type = jt
        except OSError:
            # Fail-open for the trace-type VALUE (unchanged): latest_type
            # stays empty. The signal below is what makes this visible.
            marker_state = "error"
    else:
        marker_state = "absent"
if latest_type:
    marker_state = "found"
print(f"TRACE_TYPE={latest_type}")
print(f"MARKER_STATE={marker_state}")
PY
        ) || trace_type_output=""

        # Extract both values with the same sed -n 's/^KEY=//p' idiom
        # guardrail-check.sh uses for multi-value heredoc returns.
        root_trace_type=$(echo "${trace_type_output}" | sed -n 's/^TRACE_TYPE=//p' | head -1)
        marker_state=$(echo "${trace_type_output}" | sed -n 's/^MARKER_STATE=//p' | head -1)
      else
        root_trace_type=""
        marker_state="absent"
      fi

      # Sanitize to the allowed charset [A-Za-z0-9_-] (bash bracket class — value
      # is sanitized here in bash, not python; parity with the m_trace style),
      # cap at 128 chars, then hard fallback to the literal "uncategorized".
      # This sequence is unchanged from before Task 1 — it operates on exactly
      # the extracted trace-type value, same as when it was the sole heredoc line.
      root_trace_type="${root_trace_type//[^A-Za-z0-9_-]/_}"
      root_trace_type="${root_trace_type:0:128}"
      [[ -z "${root_trace_type}" ]] && root_trace_type="uncategorized"

      # Phase 28 (D-07/D-08, assumption-delta: promote): reason-coded
      # diagnostic for the wire fallback. Fires ONLY when root_trace_type
      # just resolved to the fallback literal above — this is a diagnostic
      # side-channel into revenium-metering.log and never touches
      # --trace-type, the transaction id, or any ledger line. The resolver
      # reads PLUGIN_STATUS_FILE FIRST (before any marker-state reasoning),
      # so a registration outage is never misdiagnosed as "no job
      # classified" — that ordering IS the fix TRACE-04 exists to land.
      if [[ "${root_trace_type}" == "uncategorized" ]]; then
        local plugin_healthy_check="true"
        # quick-260814-e7c (PERF-01, H3): the heredoc's body is a single
        # `try: open(path); json.load(...) except Exception: print('true')`.
        # A missing path, an empty string path, and a zero-byte file all
        # raise and print `true` — exactly the value this guard already
        # defaults to, so skipping the spawn entirely reproduces every one
        # of those cases. Uses `-s` (not `-f`) because it also covers the
        # zero-byte case; a directory has nonzero size, so `-s` is true
        # there too and the interpreter still runs and still prints `true`
        # (its `open()` raises, caught by the same `except Exception`) — no
        # behavioral difference for that shape either.
        if [[ -s "${PLUGIN_STATUS_FILE}" ]]; then
          plugin_healthy_check=$(
            PLUGIN_STATUS_FILE="${PLUGIN_STATUS_FILE}" python3 - <<'PY' 2>/dev/null || true
import json, os
path = os.environ.get('PLUGIN_STATUS_FILE', '')
try:
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    healthy = data.get('healthy', True)
    print('true' if healthy else 'false')
except Exception:
    # Fail-open (D-06 reader rule): missing/empty/unparseable status file
    # is treated as healthy, matching every other status read in this repo.
    print('true')
PY
          )
          # Strip any trailing newline the heredoc emitted; fail-open default.
          plugin_healthy_check="${plugin_healthy_check%%$'\n'*}"
          [[ -z "${plugin_healthy_check}" ]] && plugin_healthy_check="true"
        fi

        # Phase 28 (TRACE-04/D-08): three-branch closed vocabulary. Health is
        # consulted FIRST — an unhealthy read always wins, regardless of
        # marker_state, so a registration outage is never misdiagnosed as
        # "no job classified" (the ordering this whole plan exists to lock).
        # Only when healthy does marker_state get a say: a read error names
        # itself distinctly; every other signal (no_job / absent / any
        # unrecognised value) resolves to the same not-classified literal —
        # the vocabulary is closed at exactly three literals, never a fourth.
        local fallback_reason="no_job_classified"
        if [[ "${plugin_healthy_check}" != "true" ]]; then
          fallback_reason="plugin_unregistered"
        elif [[ "${marker_state}" == "error" ]]; then
          fallback_reason="marker_lookup_failed"
        fi

        # T-28-02 mitigation: restrict ids to a safe charset BEFORE
        # interpolation so a control character in a session id can never
        # forge a second log line.
        local safe_sid safe_root_sid
        safe_sid="${sid//[^A-Za-z0-9_:.-]/_}"
        safe_root_sid="${root_sid//[^A-Za-z0-9_:.-]/_}"

        # quick-260813-wnz (LOG-01/D-01/D-02): count every fallback (warned
        # or suppressed) for the per-tick aggregate below, then gate the
        # per-session WARN to once per (session, reason) via a zero-byte
        # flag file under FALLBACK_WARN_FLAGS_DIR -- mirrors
        # pre_llm_call.sh's warn-band rate-limit idiom (WARN_FLAGS_DIR)
        # byte-for-byte. Keying on (session, reason) means a reason
        # TRANSITION creates a NEW flag filename and therefore warns once
        # more -- that transition is the informative event and must not be
        # swallowed. The vocabulary is closed at three literals, so a
        # session can produce at most 3 lines for its entire life instead of
        # one per minute forever.
        ((fallback_tick_count++)) || true
        local fallback_flag="${FALLBACK_WARN_FLAGS_DIR}/${safe_sid}__${fallback_reason}.flag"
        if [[ ! -e "${fallback_flag}" ]]; then
          # Tolerate a failed flag creation (e.g. a read-only state dir)
          # without aborting: this script runs `set -uo pipefail` without
          # `-e`, and a read-only state directory must degrade to today's
          # every-tick warn rather than crash the reporter.
          mkdir -p "${FALLBACK_WARN_FLAGS_DIR}" 2>/dev/null && touch "${fallback_flag}" 2>/dev/null
          warn "trace-type fallback: reason=${fallback_reason} session=${safe_sid} root=${safe_root_sid}"
        fi
      fi
    fi

    # Phase 22 (JOB-01 / D-02): resolve root_aid ONCE per session for subagent
    # agentic-job inheritance. Only meaningful when root_sid != sid (subagent);
    # top-level sessions take the v1.3 path (the existing --agentic-job-id
    # conditional continues to ship m_owning_job_id). On missing root marker
    # file or no kind:"job" line yet (race window per D-05), root_aid stays
    # empty and the per-marker cmd array OMITS --agentic-job-id entirely
    # for this subagent meter call rather than stubbing or shipping the
    # subagent's own (orphan) m_owning_job_id. The next cron tick retries
    # idempotently once the root's job marker exists.
    local root_aid=""
    # Phase 55 (D-13, discretionary decision item 3): resolved unconditionally
    # (guard is now presence-only — see below) so the auxiliary pass can reach
    # the session's own latest agentic_job_id without a second primitive.
    # `aux_job_id` is set unconditionally from this resolution; `root_aid`
    # keeps its EXACT pre-existing v1.3/Phase 22 value by re-gating the
    # assignment on `root_sid != sid` immediately below, so every existing
    # --agentic-job-id decision on the per-marker and markerless paths is
    # byte-identical to before this change.
    local aux_job_id=""
    # quick-260814-e7c (PERF-01, H4): bash mirror of the heredoc's own
    # `if marker_path.exists():` guard. The heredoc prints only inside
    # `if marker_path.exists():` -> `try:` -> `if latest_aid:`; with no file
    # it prints nothing, resolved_aid stays "" (already its `local` default),
    # and the trailing strip of "" is "". Uses `-e` for predicate fidelity
    # with `exists()`, though here the directory case converges either way —
    # `open()` on a directory raises `OSError`, caught, nothing printed — so
    # `-e` is chosen for consistency with H2, not necessity.
    #
    # Phase 55 (D-13): the guard's original `root_sid != sid` clause is
    # DROPPED — presence-only now — so a top-level session (root_sid == sid)
    # also resolves resolved_aid from its own marker file (the same file
    # session_markers_dir/root_markers_dir already point at when they are
    # equal). This gives the aux row the session's own latest kind:"job"
    # agentic_job_id for a root session, and the root's for a subagent — the
    # Phase 22/29 rule honoured, not re-invented.
    local resolved_aid=""
    if [[ -e "${root_markers_dir}/${root_sid}.jsonl" ]]; then
      resolved_aid=$(
        ROOT_SID="${root_sid}" MARKERS_DIR="${root_markers_dir}" python3 - <<'PY' 2>/dev/null || true
import json, os
from pathlib import Path
root_sid = os.environ.get('ROOT_SID', '')
markers_dir = os.environ.get('MARKERS_DIR', '')
if not root_sid or not markers_dir:
    pass
else:
    marker_path = Path(markers_dir) / f"{root_sid}.jsonl"
    if marker_path.exists():
        latest_aid = ""
        try:
            with open(marker_path, 'r', encoding='utf-8') as fh:
                for line in fh:
                    line = line.rstrip('\n')
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if not isinstance(rec, dict):
                        continue
                    if rec.get('kind') == 'job':
                        aid = rec.get('agentic_job_id') or ''
                        if isinstance(aid, str) and aid:
                            # Sanitize pipe / newline / colon (parity with WR-01)
                            for _bad in ('|', '\n', '\r', ':'):
                                aid = aid.replace(_bad, '_')
                            latest_aid = aid
            if latest_aid:
                print(latest_aid)
        except OSError:
            pass
PY
      )
      # Strip any trailing newline/whitespace the heredoc emitted.
      resolved_aid="${resolved_aid%%$'\n'*}"
    fi
    if [[ "${root_sid}" != "${sid}" ]]; then
      root_aid="${resolved_aid}"
    fi
    aux_job_id="${resolved_aid}"

    # Phase 55 (discretionary decision item 1): cache this session's
    # per-session attribution context for the auxiliary pass, which runs
    # AFTER this whole session loop closes and therefore cannot re-derive
    # these values without duplicating the get-root-session-id.py sidecar
    # call and ~150 lines of root/trace/job resolution this loop already
    # performs once per session. Newline-accumulated-string idiom (the same
    # one attribution_rows/LEGACY_RETAINED_SIDS/outcome_deferred_seen already
    # use in this file) rather than a bash-4 associative array — this repo is
    # bash-3.2-constrained (setup-guardrails.sh states it explicitly) and
    # contains no bash-4-only associative arrays anywhere.
    #
    # Placement is load-bearing: this append sits ABOVE both the zero-delta
    # `continue` and the legacy/ownership emit guard further down this same
    # loop iteration, so a session that would be skipped or suppressed by
    # either of those STILL gets cached here — session_model_usage is the
    # ONLY source for its auxiliary rows, so skipping the cache would lose
    # that spend permanently, not just defer it. `source` is populated
    # earlier in this same iteration (the sessions query column), consumed
    # here as ctx_source by report_auxiliary_usage as the --environment value.
    #
    # Phase 55 Plan 03 (T-55-06): gated on session_markers_dir (already
    # resolved above, no re-derivation) matching THIS process's own
    # MARKERS_DIR. A multiplexed host can run one cron tick per profile, each
    # with its own REVENIUM_STATE_DIR, against sessions/session_model_usage
    # tables that carry namespaced `agent:<profile>:...` ids with no
    # profile-scoping WHERE clause -- every tick sees every profile's rows.
    # resolve_markers_dir routes a namespaced sid to the markers directory
    # its OWN profile owns, independent of which process is asking; when that
    # owning directory is NOT this process's own MARKERS_DIR, the session
    # belongs to (and will be correctly reported by) a DIFFERENT profile's own
    # tick, so this process must not cache it for its auxiliary pass --
    # AUX_LEDGER_FILE has no cross-profile coordination of its own (each
    # profile keeps its own ledger), so caching here would double-ship. A
    # session with no `agent:<profile>:` prefix (every existing install
    # today) always resolves session_markers_dir to MARKERS_DIR, so this
    # guard is a no-op everywhere except a genuinely namespaced multiplex
    # deployment.
    if [[ "${session_markers_dir}" == "${MARKERS_DIR}" ]]; then
      local _aux_ctx_sid="${sid//[|$'\n'$'\r']/_}"
      local _aux_ctx_root_sid="${root_sid//[|$'\n'$'\r']/_}"
      local _aux_ctx_root_agent_name="${root_agent_name//[|$'\n'$'\r']/_}"
      local _aux_ctx_aux_job_id="${aux_job_id//[|$'\n'$'\r']/_}"
      local _aux_ctx_source="${source//[|$'\n'$'\r']/_}"
      aux_session_ctx+="${_aux_ctx_sid}|${_aux_ctx_root_sid}|${_aux_ctx_root_agent_name}|${root_trace_type:-}|${_aux_ctx_aux_job_id}|${_aux_ctx_source}"$'\n'
    fi

    # Phase 9 (WR-02 fix): standalone job-only marker scan — token-independent.
    # Runs BEFORE the token pre-filter guards so that token-stable sessions
    # (D-08 arc-close: job marker appended after the last LLM call) still reach
    # the jobs-create stage even though their token total has not grown since
    # the prior HERMES ledger row. The in-loop jobs-create stage below is NOT
    # moved — this scan is additive only. Both share the single
    # JOB:<id>:created gate; the synchronous-on-success ledger write prevents
    # a double-create within one tick (D-09).
    #
    # quick-260814-e7c (PERF-01, H5): the heredoc's own first two statements
    # (after reading its env) are `if not markers_dir or not sid: raise
    # SystemExit(0)` and `if not marker_path.is_file(): raise SystemExit(0)`
    # — mirrored here as a bash `-f` pre-test on the session marker file, the
    # same predicate the heredoc evaluates itself (is_file() -> -f). Measured
    # on the live fleet host: 1,663 of 1,977 `devops` sessions (84%) have NO
    # marker file at all, so for those sessions this heredoc's ENTIRE body
    # already reduces to "exit 0, print nothing" — both exit paths leave
    # `precheck_job_rows` empty, which makes the `if [[ -n
    # "${precheck_job_rows}" ]]` body below (the ONLY other content in this
    # block) a no-op. Hoisting `-f` into the outer condition therefore skips
    # a block that was already a no-op; it is NOT a skip predicated on token
    # totals, ledger rows, or `ended_at` (the forbidden approach this plan
    # explicitly rules out — see PLAN.md's <forbidden_approach>), so a
    # token-stable session WITH a job marker still reaches this block and
    # still reaches the jobs-create call below (WR-02, proven by
    # tests/test_reporter_spawn_guards.py's WR-02 regression test).
    if [[ "${JOBS_CLI_CAPABLE}" == "true" && -f "${session_markers_dir}/${sid}.jsonl" ]]; then
      local precheck_job_rows
      precheck_job_rows=$(
        MARKERS_DIR="${session_markers_dir}" \
        SID="${sid}" SOURCE="${source}" \
        python3 - <<'PY' 2>/dev/null || true
import json
import os
from pathlib import Path

def _clamp_bytes(value, limit):
    # D-10 byte-safe clamp; mirrors classifier.py::_clamp_assessment_text (duplicated -- this heredoc cannot import it).
    def _slen(s): return len(json.dumps(s, ensure_ascii=True).encode('utf-8')) - 2
    if _slen(value) <= limit: return value
    lo, hi = 0, len(value)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _slen(value[:mid]) <= limit: lo = mid
        else: hi = mid - 1
    return value[:lo]

markers_dir = os.environ.get('MARKERS_DIR', '')
sid = os.environ.get('SID', '')
if not markers_dir or not sid: raise SystemExit(0)
# CR-01: this precheck stage's own job_outcome_queue push bypasses the job-row heredoc's SOURCE clamp entirely -- same 64-byte budget here, computed once (source is session-level, not per-job-marker-line).
source_clean = _clamp_bytes(os.environ.get('SOURCE', '').replace('|', '_').replace('\n', '_').replace('\r', '_'), 64)

marker_path = Path(markers_dir) / f"{sid}.jsonl"
if not marker_path.is_file(): raise SystemExit(0)

JOB_REQUIRED = ("agentic_job_id", "job_type", "status")
_bad_chars = (':', ' ', '\t', '\n', '\r')

try:
    with marker_path.open() as f:
        for line in f:
            line = line.rstrip('\n')
            if not line:
                continue
            # 4 KB cap (T-03-04 defense, same as marker reader).
            if len(line) > 4096:
                continue
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(m, dict):
                continue
            if m.get("kind") != "job":
                continue
            # D-04: validate reader-required keys; skip if any missing.
            job_id = m.get("agentic_job_id")
            if not isinstance(job_id, str) or not job_id:
                continue
            if not all(k in m for k in JOB_REQUIRED):
                continue
            # D-16: colon-safe sanitization (same replace(bad,'_') as marker reader).
            clean_id = job_id
            for _bad in _bad_chars:
                clean_id = clean_id.replace(_bad, '_')
            job_name = m.get('job_name', '') or ''
            job_type = m.get('job_type', '') or ''
            # Pipe-sanitize optional string fields for bash IFS='|' read.
            for _bad in ('|', '\n', '\r'):
                job_name = job_name.replace(_bad, '_')
                job_type = job_type.replace(_bad, '_')
            # Phase 10: emit status and marker ts as 4th/5th pipe fields for the outcome-queue accumulator (OUTCOME-05, D-07).
            status = m.get('status', '') or ''
            for _bad in ('|', '\n', '\r'):
                status = status.replace(_bad, '_')
            marker_ts = m.get('ts', 0) or 0
            # Phase 24 (quick-260531-n4i): carry failure_reason (FAILED arcs only) for --metadata; strip IFS chars, cap length.
            failure_reason = m.get('failure_reason', '') or ''
            if not isinstance(failure_reason, str):
                failure_reason = ''
            for _bad in ('|', '\n', '\r'):
                failure_reason = failure_reason.replace(_bad, ' ')
            failure_reason = _clamp_bytes(failure_reason, 500)
            print(f"{clean_id}|{job_name}|{job_type}|{source_clean}|{status}|{marker_ts}|{failure_reason}")
except OSError:
    pass
PY
      )

      if [[ -n "${precheck_job_rows}" ]]; then
        # Phase 22 (JOB-02 + JOB-03 / D-06): subagent sessions (root_sid != sid) skip BOTH the outcome queue push and the jobs create call -- the root's ledger entry is the single create per arc; outcome ships once; top-level takes the v1.3 path.
        if [[ "${root_sid}" == "${sid}" ]]; then
          local precheck_clean_job_id precheck_job_name precheck_job_type precheck_source precheck_status_raw precheck_marker_ts precheck_failure_reason
          while IFS='|' read -r precheck_clean_job_id precheck_job_name precheck_job_type precheck_source precheck_status_raw precheck_marker_ts precheck_failure_reason; do
            [[ -z "${precheck_clean_job_id}" ]] && continue

            # Phase 10: push every row to the outcome queue regardless of create outcome (JOB:<id>:outcome: gate dedupes; field 6 = sid, Phase 38 ROI-10). CR-01: precheck_source is the clamped field printed above, not the raw ${source}.
            job_outcome_queue+=("${precheck_clean_job_id}|${precheck_status_raw}|${precheck_source}|${precheck_marker_ts}|${precheck_failure_reason}|${sid}")

            # D-09: single shared idempotency gate — same grep pattern as in-loop stage.
            if grep -q "^JOB:${precheck_clean_job_id}:created:" "${JOBS_LEDGER_FILE}" 2>/dev/null; then
              continue
            fi

            local precheck_jobs_cmd=(
              revenium jobs create
              --agentic-job-id "${precheck_clean_job_id}"
              --quiet
            )
            if [[ -n "${precheck_job_name}" ]]; then
              precheck_jobs_cmd+=(--name "${precheck_job_name}")
            fi
            if [[ -n "${precheck_job_type}" ]]; then
              precheck_jobs_cmd+=(--type "${precheck_job_type}")
            fi
            # PR #101 / Greptile: this path was already correct — kept for contrast
            # with the sibling in-loop stage (~line 2459), which regressed to the
            # CLAMPED field until this fix. --environment must stay the raw ${source}
            # on BOTH paths; only --metadata's source key has a byte ceiling.
            if [[ -n "${source}" ]]; then
              precheck_jobs_cmd+=(--environment "${source}")
            fi
            # quick-260605: pass teamId explicitly when resolved (omitted in tests).
            if [[ -n "${REVENIUM_TEAM_ID_RESOLVED}" ]]; then
              precheck_jobs_cmd+=(--team-id "${REVENIUM_TEAM_ID_RESOLVED}")
            fi
            # BUG-2: thread the SAME organization dimension through jobs create as
            # completions/tool-events carry, so a job and its transactions never
            # land in different orgs. Omitted when unset (preserves v1.4 wire shape).
            if [[ -n "${ORG_NAME}" ]]; then
              precheck_jobs_cmd+=(--organization-name "${ORG_NAME}")
            fi

            # D-10: best-effort — never abort or continue the session loop.
            local precheck_cmd_output precheck_cmd_exit
            precheck_cmd_output=$("${precheck_jobs_cmd[@]}" 2>&1) && precheck_cmd_exit=0 || precheck_cmd_exit=$?

            # D-09: treat exit 0 AND HTTP-409/already-exists as success-equivalent.
            local precheck_success=false
            if [[ "${precheck_cmd_exit}" -eq 0 ]]; then
              precheck_success=true
            elif echo "${precheck_cmd_output}" | grep -qi "409\|already.exist\|conflict"; then
              precheck_success=true
            fi

            if [[ "${precheck_success}" == "true" ]]; then
              # D-15: synchronous-on-success ledger write — same JOB:<id>:created:<ts> pattern.
              local precheck_now_ts
              precheck_now_ts=$(python3 -c "import time; print(f'{time.time():.3f}')" 2>/dev/null || date +%s)
              echo "JOB:${precheck_clean_job_id}:created:${precheck_now_ts}" >> "${JOBS_LEDGER_FILE}"
              info "Job created (pre-guard scan): agentic_job_id=${precheck_clean_job_id}"
            else
              warn "jobs create failed (pre-guard): id=${precheck_clean_job_id} exit=${precheck_cmd_exit} — metering continues"
            fi
          done <<< "${precheck_job_rows}"
        fi
      fi
    fi

    # quick-260817-tfe: HOISTED legacy-ledger lookup. This is the SAME grep the
    # prior-line read below has always done — moved up so the ownership
    # resolution can reuse its result rather than adding a third grep of the
    # same file for the same sid. It answers both questions at once: "does the
    # legacy path already hold rows for this session?" (the resolution table's
    # own-ledger predicate) and "what is its last reported total?" (the delta
    # baseline).
    local prev_line
    prev_line=$(grep "^HERMES:${sid}:" "${LEDGER_FILE}" 2>/dev/null | tail -1 || true)
    local legacy_rows_present="false"
    [[ -n "${prev_line}" ]] && legacy_rows_present="true"

    # quick-260818-jbl (CLAIM-01..05): HOISTED above the OWNERSHIP_PROTOCOL_ACTIVE
    # guard below (it used to live inside it, recomputed on every claim). Hoisting
    # instead of nesting a new `if` around the existing claim block is deliberate:
    # nesting would re-indent ~45 lines and silently invalidate the exact-substring
    # anchors tests/mutation_verify_takeover.py mutates (AX-09's two-line search,
    # AX-16's dual_ledger/claim_side pair, _TAKEOVER_PATH_BLOCK) — an unapplied
    # mutation row reports as a hard error, not as coverage, and this phase has
    # already produced five instrumentation bugs that looked like results. The
    # cost is one `[[ -s ]]` test on a disengaged install; the `-s` short-circuits
    # before the grep and spawns no python3, so NO_MARKER_SPAWN_CEILING is
    # untouched.
    local event_rows_present="false"
    if [[ -s "${EVENT_LEDGER_FILE}" ]] && grep -qF "|${sid}|" "${EVENT_LEDGER_FILE}" 2>/dev/null; then
      event_rows_present="true"
    fi

    # THE ABSTENTION PREDICATE (CLAIM-01/CLAIM-02). Why this exists: the claim
    # block's default (`claim_side="legacy"` below) was written when legacy
    # always billed. Since quick-260818-f1g (#57), legacy emission can be
    # SUPPRESSED per session while this claim still runs — so on a brand-new
    # session (neither ledger has rows yet) legacy claimed `legacy`, wrote a
    # durable record, and then never emitted a completion for it; the event
    # path's own ship predicate (api-event-report.sh:1232) then deferred to
    # that durable `legacy` record forever, and the session was billed by
    # NEITHER path. Measured live: session 20260818_171928_2ba368 — owner
    # `legacy`, 0 HERMES: rows, 0 API: rows.
    #
    # Why abstaining beats claiming `event` on the event path's own behalf
    # (rejected alternative (ii)): that path only claims `event` in `live`
    # mode (api-event-report.sh:1174 — "a shadow-mode claim would starve the
    # legacy path of a session this path will never bill"), so a legacy-side
    # `event` claim is false whenever the event path is shadow, off, or
    # uninstalled, AND it is self-locking — the next tick's takeover branch
    # (:1537, below) sees `sid_legacy_suppressed == "true"` and defers with NO
    # takeover (MODE-05), so legacy can never undo its own false assertion
    # while suppression holds. (ii) trades a durable wrong `legacy` for a
    # durable wrong `event`; abstention writes nothing, so nothing wrong is
    # durable.
    #
    # Why this restores no inference (rejected alternative (iii), teaching the
    # event path that a zero-row `legacy` record is claimable): the record is
    # still created atomically by the biller through the IDENTICAL
    # _claim_session_owner primitive PR #54 introduced. "No record yet" is not
    # a new state — it is the initial state of every session on every install,
    # and the state OWNERSHIP_PROTOCOL_ACTIVE already describes for the
    # overwhelming majority of them. This branch adds no read of any billing
    # ledger to any decision and takes no lock, because it decides nothing
    # beyond "do not write".
    #
    # Why this cannot leak a bill (checkable as a source property, AX-Q14):
    # the predicate's first conjunct, sid_legacy_suppressed, is the SAME local
    # (declared once at :817-819, one iteration of the loop opened at :796 and
    # closed at :2519) the emission guard at :2219 reads
    # (`[[ "${sid_legacy_suppressed}" != "true" && ... ]]`). On the abstain
    # path that guard is false unconditionally — session_event_owned staying
    # "false" and owner_baseline staying unread are unreachable consequences
    # of that shared local, not latent hazards.
    # FOURTH CONJUNCT, found by this task's own mutation verifier
    # (tests/mutation_verify_takeover.py's AX-08 row): abstention must only
    # apply when NO owner record exists yet for this sid. Without this
    # check, a session that already HAS a record (of any owner) but happens
    # to have zero rows in EITHER billing ledger — e.g. the event path
    # claimed it and then every one of its ship attempts failed, or a test
    # fixture seeds a record directly — would skip the ENTIRE claim block,
    # including the mode-aware takeover's own defensive guard (:1537,
    # MODE-05), even though there is nothing left to CREATE and therefore
    # nothing for abstention to prevent. That skip does not double-bill
    # (sid_legacy_suppressed alone still blocks the emission guard at
    # :2219), but it silently defeats reconciliation of an EXISTING record
    # and undercounts the event_owned_skip_count/takeover aggregates — a
    # regression this task's own AX-08 mutation row caught by observing the
    # mutated inner guard become unreachable. The filename derivation below
    # mirrors the claim primitive's own Python-side derivation
    # (sid.replace('/', '_').replace('\x00', '_')[:200]) byte-for-byte; bash
    # cannot hold a NUL byte in a variable so that half is a structural
    # no-op, kept only for parity with the primitive it mirrors.
    local claim_abstain_probe_name="${sid//\//_}"
    claim_abstain_probe_name="${claim_abstain_probe_name:0:200}"
    local owner_record_absent="true"
    [[ -e "${OWNERS_DIR}/${claim_abstain_probe_name}" ]] && owner_record_absent="false"

    local claim_abstain="false"
    if [[ "${sid_legacy_suppressed}" == "true" && "${legacy_rows_present}" == "false" && "${event_rows_present}" == "false" && "${owner_record_absent}" == "true" ]]; then
      claim_abstain="true"
      ((claim_abstained_count++)) || true
    fi

    # =====================================================================
    # quick-260817-tfe (OWN-01/OWN-02/OWN-04): SESSION OWNERSHIP RESOLUTION.
    #
    # WHY THIS EXISTS. Before this, the two metering paths partitioned by
    # DERIVING ownership — each grepped the other's BILLING ledger at an
    # arbitrary instant. That is order-dependent (it double-billed a real
    # production session on 2026-08-17) and retention-coupled (pruning an
    # event-owned session's API: rows erased its only ownership record and let
    # this path re-bill its whole cumulative total from a zero baseline).
    # Ownership is now a fact established ONCE, by an O_EXCL create.
    #
    # WHY HERE, and not at the emission guard. Only the SUPPRESSION composes
    # into the D-13 guard below; the RESOLUTION has to run before the delta
    # block, because the catch-up baseline must be in hand before any delta is
    # computed. Resolving early also tightens the partition: this path now
    # claims a session on the first tick it sees it, even when that tick's
    # delta is zero.
    #
    # WHY THE PIPE-DELIMITED FIXED-STRING MATCH, and not the `^HERMES:` colon
    # idiom used a few lines up. An event ledger line is
    # `API:<api_request_id>|<sid>|<ts>` — pipe-delimited ON PURPOSE, because a
    # real api_request_id embeds colons (`sess:t1:api:1`); the shipper's own
    # reader agrees (strip the `API:` prefix, then find the first pipe). A
    # colon-position parse here would be a silent ALWAYS-FALSE no-op that
    # looks correct in review and never once fires. Both surrounding pipes are
    # required so another session's api_request_id cannot false-positive, and
    # the identifier is pipe-sanitised on write, so a smuggled pipe cannot
    # forge a match. The `-s` pre-test is both the fail-open mechanism and the
    # perf guard.
    #
    # OPERATOR REVIEW — SURFACED, DELIBERATELY NOT FIXED HERE.
    # drain-status.sh reasons over the HERMES: ledger to answer what is really
    # an ownership question (which legacy-owned sessions are still open, and
    # therefore whether this path may be disabled). An EVENT-owned session
    # never appears in that ledger, so it is invisible to that gate. Two
    # consequences: (1) the gate can report `drained` while event-owned
    # sessions are still spending — correct for what it measures, easy to
    # misread as "all sessions are accounted for"; (2) if the event path owns
    # a session and is later returned to `shadow` or uninstalled while this
    # path stays enabled, the DURABLE record keeps this path off that session
    # FOREVER and its later growth is billed by neither. That hole existed
    # before too, but transiently — it healed when the API: rows aged out, by
    # way of the zero-baseline re-bill that is P1-2. This design makes the
    # hole permanent and the re-bill impossible. That is the intended trade
    # (over-billing is the failure this repo treats as load-bearing) and it is
    # a CHANGE in behaviour, not a preservation of it. Candidate follow-ups,
    # none implemented here: teach drain-status.sh to read OWNERS_DIR; add an
    # event-side drain gate; or document a "clear the owners records and the
    # event ledger before rolling the event path back" runbook step.
    # =====================================================================
    local session_event_owned="false"
    local owner_baseline=""
    # quick-260818-jbl: `claim_abstain` composes HERE as a second conjunct on
    # the existing OWNERSHIP_PROTOCOL_ACTIVE guard — event_rows_present is no
    # longer (re)computed inside this block; it is hoisted above, alongside
    # the abstention predicate, so there is exactly one computation to drift.
    if [[ "${OWNERSHIP_PROTOCOL_ACTIVE}" == "true" && "${claim_abstain}" != "true" ]]; then

      # The resolution table, implemented identically in api-event-report.sh:
      #   neither ledger  -> the claiming side (here: legacy)
      #   legacy only     -> legacy       (backfill)
      #   event only      -> event        (backfill)
      #   BOTH            -> legacy, plus a warn, plus a catch-up baseline
      #
      # The dual row resolves to LEGACY, and consulting THIS script's own
      # ledger is what makes that possible. A one-directional backfill would
      # see a non-empty event ledger, cede the session as `event`, and lock
      # this path out of a session it has an active, still-growing billing
      # history for — while the event path may be on `shadow` and shipping
      # nothing. That session's future growth would be billed by NEITHER path,
      # permanently. Legacy wins because it holds a working delta baseline,
      # because the event path may not even be enabled, and because it
      # composes with OWN-04's fail direction rather than fighting it.
      local claim_side="legacy"
      local claim_baseline_in=0
      local dual_ledger="false"
      if [[ "${legacy_rows_present}" == "true" && "${event_rows_present}" == "true" ]]; then
        dual_ledger="true"
        claim_side="legacy"
        # BASELINE CATCH-UP: legacy-wins is UNSAFE without this. This path's
        # delta baseline comes SOLELY from LEDGER_FILE and is blind to the
        # event ledger, so on a dual claim whose last HERMES: line PREDATES
        # the event rows, the first post-claim delta would span tokens the
        # event path already metered and bill them twice — the original
        # defect's own class, reintroduced by the rule meant to close it.
        # Recording the session's CURRENT total at the claim instant makes the
        # claim honest instead of assuming it: the first post-claim delta is
        # genuinely zero, and only real future growth bills. The cost is a
        # bounded, one-time, quantifiable UNDER-bill — the direction OWN-04
        # already commits to.
        claim_baseline_in="${total_tokens}"
      elif [[ "${event_rows_present}" == "true" ]]; then
        claim_side="event"
      fi

      local claim_output=""
      claim_output=$(_claim_session_owner "${sid}" "${claim_side}" "${claim_baseline_in}") || claim_output=""

      if [[ -z "${claim_output}" ]]; then
        # OWN-04, fail OPEN: an unreadable/uncreatable sentinel must leave
        # exactly ONE biller, and this is the incumbent path every install
        # depends on and the goldens pin. The event path fails CLOSED under
        # the same condition; symmetric fail-open would double-bill under a
        # shared directory failure.
        ((claim_unavailable_count++)) || true
      else
        local claim_owner claim_created claim_baseline_out
        claim_owner=$(printf '%s\n' "${claim_output}" | sed -n 's/^OWNER=//p' | head -1)
        claim_created=$(printf '%s\n' "${claim_output}" | sed -n 's/^CLAIMED=//p' | head -1)
        claim_baseline_out=$(printf '%s\n' "${claim_output}" | sed -n 's/^BASELINE=//p' | head -1)

        # THE SINGLE OWNERSHIP PREDICATE, total over every possible string:
        # the record blocks this path if and only if its first line is exactly
        # the literal `event`. A corrupt, truncated or hostile record resolves
        # to "legacy bills, event defers" — today's behaviour, exactly one
        # biller. There is no third branch.
        if [[ "${claim_baseline_out}" =~ ^[0-9]+$ ]]; then
          owner_baseline="${claim_baseline_out}"
        fi
        if [[ "${claim_owner}" == "event" ]]; then
          # quick-260818-0in (MODE-01): the guard composes HERE, inside the
          # existing owner-is-the-event-path branch, and nowhere else. The
          # emission-side suppression below and the floor application just
          # after it are reused UNCHANGED (D-10) — this only decides which
          # literal `session_event_owned` ends up as.
          #
          #   EVENT_PATH_LIVE=true              -> defer, unchanged from #54.
          #   EVENT_PATH_LIVE=false,
          #     sid_legacy_suppressed=true        -> defer, no takeover (MODE-05).
          #   EVENT_PATH_LIVE=false,
          #     sid_legacy_suppressed=false        -> take over.
          #
          # WHY NO TAKEOVER WHILE LEGACY EMISSION IS SUPPRESSED FOR THIS SID.
          # If legacy is not emitting for this session, flipping ownership
          # bills nobody either way — but it converts a state that HEALS when
          # the operator returns the mode to `live` (the event path resumes
          # and bills the session) into one that cannot: the record would say
          # `legacy`, the event path would defer forever, and legacy would be
          # suppressed. Preferring the reversible state is the same reasoning
          # that makes clear-halt.sh the sole clearer of `halted`. A guard
          # written only against the mode axis gets this wrong, which is why
          # it has its own branch and its own axis (AX-08) rather than being
          # folded into the mode check.
          #
          # quick-260818-f1g (STALE-07/AX-S30): `sid_legacy_suppressed` is
          # the SAME per-session local the emission guard below reads —
          # resolved once, used at both sites, so a sid on
          # `legacyRetainedSids` (legacy IS still emitting for it) is
          # correctly allowed to take over even while the fleet-global
          # `LEGACY_COMPLETIONS_SKIP` boolean is true.
          if [[ "${EVENT_PATH_LIVE}" == "true" || "${sid_legacy_suppressed}" == "true" ]]; then
            session_event_owned="true"
            ((event_owned_skip_count++)) || true
          else
            local takeover_output=""
            takeover_output=$(_takeover_session_owner "${sid}" "${total_tokens}" "${owner_baseline:-0}") || takeover_output=""
            if [[ -z "${takeover_output}" ]]; then
              # MODE-02, AX-09: empty output -> defer, NOT bill. This is NOT
              # a violation of OWN-04's fail-open: OWN-04 covers a claim that
              # could not establish whether a record exists, where legacy
              # billing from its own ledger baseline is today's correct
              # behaviour. Here the record demonstrably names the event path
              # and the floor was never written (F-2) — billing would start
              # from a zero baseline and re-bill the session's entire
              # cumulative history, a double-bill, which this repo treats as
              # the load-bearing failure. Under-bill on doubt.
              session_event_owned="true"
              ((takeover_unavailable_count++)) || true
            else
              local takeover_owner takeover_took_over takeover_baseline_out
              takeover_owner=$(printf '%s\n' "${takeover_output}" | sed -n 's/^OWNER=//p' | head -1)
              takeover_took_over=$(printf '%s\n' "${takeover_output}" | sed -n 's/^TOOK_OVER=//p' | head -1)
              takeover_baseline_out=$(printf '%s\n' "${takeover_output}" | sed -n 's/^BASELINE=//p' | head -1)
              if [[ "${takeover_owner}" == "legacy" ]]; then
                session_event_owned="false"
                if [[ "${takeover_baseline_out}" =~ ^[0-9]+$ ]]; then
                  owner_baseline="${takeover_baseline_out}"
                fi
                ((takeover_count++)) || true
                # Gated on the primitive's OWN flag, exactly as the
                # dual-ledger warn just below is gated on `claim_created` —
                # a takeover is a permanent, operator-visible change of who
                # bills a session and must stay findable, without becoming a
                # per-tick warn (steady state never re-enters this branch:
                # the record now says `legacy`, so claim_owner is never
                # `event` again for this session).
                if [[ "${takeover_took_over}" == "true" ]]; then
                  local safe_takeover_sid="${sid//[^A-Za-z0-9_:.-]/_}"
                  warn "session ownership taken over from the event path: session=${safe_takeover_sid} floor=${owner_baseline} mode=${_event_metering_mode_resolved} — legacy now bills this session forward from the recorded floor, never re-billing what the event path already shipped"
                fi
              else
                session_event_owned="true"
                ((event_owned_skip_count++)) || true
              fi
            fi
          fi
        fi

        # Gated on the primitive's OWN created flag so it fires exactly ONCE
        # per record — on the tick the record is actually created, by whichever
        # process creates it. A dual-ledger session is a PERMANENT on-disk
        # state that matches every tick forever; an ungated warn here would be
        # the same unbounded per-tick warn this repo has already paid
        # 9,039,937 lines for. It must stay findable (it is evidence of a past
        # double-bill) and it must not be per-tick.
        if [[ "${dual_ledger}" == "true" && "${claim_created}" == "true" ]]; then
          local safe_claim_sid="${sid//[^A-Za-z0-9_:.-]/_}"
          warn "dual-ledger session claimed for the legacy path: session=${safe_claim_sid} baseline=${claim_baseline_in} — rows exist in BOTH the HERMES: and API: ledgers (evidence of a past double-bill); legacy retains ownership and its delta baseline is reset to the session's current total, so the overlap is never re-billed"
        fi
      fi
    fi

    local ledger_key="HERMES:${sid}:${total_tokens}"
    if grep -q "^HERMES:${sid}:${total_tokens}:" "${LEDGER_FILE}" 2>/dev/null; then
      ((skipped_count++)) || true
      continue
    fi

    local prev_reported_tokens=0
    if [[ -n "${prev_line}" ]]; then
      # CR-01 fix: sid may itself embed ':' (multiplex-namespaced sessions,
      # e.g. "agent:<profile>:<rest>"), which shifts every fixed-position
      # `cut -d: -fN` read of the ledger line by however many colons sid
      # contains. Compute the tokens field position FROM sid's own known
      # colon count (pure bash, no subprocess) rather than assuming a fixed
      # position 3 — this is exact, not a guess at ledger-row shape, and
      # reduces byte-for-byte to the prior `-f3` behavior when sid has no
      # colon, so existing non-namespaced ledger lines parse identically.
      local sid_no_colons sid_colon_count tokens_field
      sid_no_colons="${sid//:/}"
      sid_colon_count=$(( ${#sid} - ${#sid_no_colons} ))
      tokens_field=$((3 + sid_colon_count))
      prev_reported_tokens=$(echo "${prev_line}" | cut -d: -f"${tokens_field}")
    fi

    # quick-260817-tfe (OWN-02): FLOOR the ledger-derived baseline at the
    # catch-up value carried on the owners record's second line. Read from the
    # DURABLE record on EVERY tick — not special-cased to the claim tick —
    # which is what makes it survive a restart, a prune of the event ledger,
    # and an operator's manual run. Take the MAXIMUM, never an assignment: a
    # stale record must never LOWER a baseline the ledger has already moved
    # past, or it would re-open the very re-bill it exists to close.
    # Everything downstream is unchanged — the growth guard below
    # short-circuits the claim tick on its own, and the ratio math measures
    # from the floored value on every later tick.
    if [[ "${owner_baseline}" =~ ^[0-9]+$ && "${owner_baseline}" -gt 0 ]]; then
      local _floor_prev="${prev_reported_tokens}"
      [[ "${_floor_prev}" =~ ^[0-9]+$ ]] || _floor_prev=0
      if [[ "${owner_baseline}" -gt "${_floor_prev}" ]]; then
        prev_reported_tokens="${owner_baseline}"
      fi
    fi

    # The growth guard, unchanged in effect: it previously lived inside the
    # `[[ -n "${prev_line}" ]]` block above and is hoisted out only so the
    # floor can be applied before it runs. With no prior line and no floor,
    # prev_reported_tokens is 0 and this is false — byte-identical to before.
    if [[ "${prev_reported_tokens}" -gt 0 && "${total_tokens}" -le "${prev_reported_tokens}" ]]; then
      ((skipped_count++)) || true
      continue
    fi

    local delta_input delta_output delta_cache_read delta_cache_write delta_total
    if [[ "${prev_reported_tokens}" -gt 0 ]]; then
      local ratio
      ratio=$(python3 -c "
prev = ${prev_reported_tokens}
curr = ${total_tokens}
if prev > 0 and curr > prev:
    print(f'{(curr - prev) / curr:.6f}')
else:
    print('1.0')
" 2>/dev/null || echo "1.0")
      delta_input=$(python3 -c "print(max(0, int(${input_tokens} * ${ratio})))" 2>/dev/null)
      delta_output=$(python3 -c "print(max(0, int(${output_tokens} * ${ratio})))" 2>/dev/null)
      delta_cache_read=$(python3 -c "print(max(0, int(${cache_read} * ${ratio})))" 2>/dev/null)
      delta_cache_write=$(python3 -c "print(max(0, int(${cache_write} * ${ratio})))" 2>/dev/null)
    else
      delta_input="${input_tokens}"
      delta_output="${output_tokens}"
      delta_cache_read="${cache_read}"
      delta_cache_write="${cache_write}"
    fi
    delta_total=$((delta_input + delta_output))

    if [[ "${delta_total}" -eq 0 ]]; then
      ((skipped_count++)) || true
      continue
    fi

    local clean_model provider
    clean_model="$(_clean_model_name "${model}")"
    provider="$(_infer_provider "${model}" "${billing_provider}")"

    local request_time response_time duration_ms
    local last_report_ts=""
    if [[ "${prev_reported_tokens}" -gt 0 ]]; then
      # CR-01 fix: same colon-safe field computation as the tokens read
      # above — sid may embed ':' and shift the ts field position, so
      # derive it from sid's own colon count instead of a fixed `-f4`.
      local sid_no_colons_ts sid_colon_count_ts ts_field
      sid_no_colons_ts="${sid//:/}"
      sid_colon_count_ts=$(( ${#sid} - ${#sid_no_colons_ts} ))
      ts_field=$((4 + sid_colon_count_ts))
      last_report_ts=$(grep "^HERMES:${sid}:" "${LEDGER_FILE}" 2>/dev/null | tail -1 | cut -d: -f"${ts_field}" || true)
    fi

    request_time=$(python3 -c "
from datetime import datetime, timezone
last_ts = '${last_report_ts}'
started = float('${started_at}')
ts = float(last_ts) if last_ts else started
print(datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
" 2>/dev/null || date -u +%Y-%m-%dT%H:%M:%SZ)

    response_time=$(python3 -c "
from datetime import datetime, timezone
import time
ended = '${ended_at}'
ts = float(ended) if ended else time.time()
print(datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
" 2>/dev/null || date -u +%Y-%m-%dT%H:%M:%SZ)

    duration_ms=$(python3 -c "
import time
last_ts = '${last_report_ts}'
started = float('${started_at}')
ended = '${ended_at}'
start = float(last_ts) if last_ts else started
end = float(ended) if ended else time.time()
print(max(0, int((end - start) * 1000)))
" 2>/dev/null || echo "0")

    local delta_cost="0"
    if [[ -n "${estimated_cost}" && "${estimated_cost}" != "0" && "${estimated_cost}" != "0.0" ]]; then
      if [[ "${prev_reported_tokens}" -gt 0 ]]; then
        delta_cost=$(python3 -c "
prev = ${prev_reported_tokens}
curr = ${total_tokens}
cost = float('${estimated_cost}')
if prev > 0 and curr > prev:
    print(f'{cost * (curr - prev) / curr:.6f}')
else:
    print(f'{cost:.6f}')
" 2>/dev/null || echo "0")
      else
        delta_cost="${estimated_cost}"
      fi
    fi

    # Phase 3 (CRON-01 / MARK-04 / TAX-05 / D-14 / D-15 / D-18): per-session marker reader.
    # Reads ${MARKERS_DIR}/${sid}.jsonl filtered by the prior ledger row's cutoff (ts,
    # muids) via the shared parse_prior_state helper (B6). Emits the S2 telemetry log
    # lines locked by D-18. This commit (T04) does NOT yet change wire behavior — the
    # legacy single-call cmd array below is still emitted unchanged. T05 introduces the
    # per-marker cutover wrapped in 'if n_markers > 0' / else.
    local marker_rows=()
    local n_markers=0
    local prior_muids_count=0
    local s2_info_line=""
    local s2_warn_line=""
    local read_ok="true"
    local marker_output=""
    local jobs_json=""
    local read_err=""
    marker_output=$(
      MARKERS_DIR="${session_markers_dir}" \
      SID="${sid}" \
      TOTAL_TOKENS="${total_tokens}" \
      DELTA_TOTAL="${delta_total}" \
      SCRIPT_DIR="${SCRIPT_DIR}" \
      LEDGER_PATH="${LEDGER_FILE}" \
      python3 - <<'PY' 2>&1
import json
import os
import sys
from pathlib import Path

try:
    sys.path.insert(0, os.environ['SCRIPT_DIR'])
    from split_strategies import parse_prior_state
except Exception as exc:
    # B6 / Pitfall A defense: if the helper can't be imported, fall through to
    # the legacy single-call path. The bash side sees READ_OK=false.
    print(f"READ_OK=false")
    print(f"READ_ERR=import: {exc}")
    sys.exit(0)

markers_dir = os.environ['MARKERS_DIR']
sid = os.environ['SID']
try:
    total_tokens = int(os.environ['TOTAL_TOKENS'])
except (TypeError, ValueError):
    total_tokens = 0
try:
    delta_total = int(os.environ['DELTA_TOTAL'])
except (TypeError, ValueError):
    delta_total = 0
ledger_path = os.environ['LEDGER_PATH']

# A2 defense lives inside parse_prior_state (asserts ':' not in sid). Catch the
# AssertionError here and fall through to the legacy path with a warn log.
try:
    prior_ts, prior_muids = parse_prior_state(ledger_path, sid, total_tokens)
except AssertionError as exc:
    print("READ_OK=false")
    print(f"READ_ERR=sid-format: {exc}")
    sys.exit(0)
except Exception as exc:
    print("READ_OK=false")
    print(f"READ_ERR=parse: {exc}")
    sys.exit(0)

# TAX-05 (D-14) trivial-label blocklist enforced cron-side as defense-in-depth.
FORBIDDEN = {'ack', 'acknowledgment', 'greeting', 'confirmation', 'hello', 'thanks'}
REQUIRED_KEYS = ('muid', 'ts', 'sid', 'task_type', 'operation_type')
# Phase 7 (D-04): reader-required keys for a kind:"job" line to be accepted.
JOB_REQUIRED = ("agentic_job_id", "job_type", "status")
# Phase 7 (D-12): job collector — keyed by agentic_job_id, last line in file order wins.
# Initialized before the is_file() check so JOBS_JSON= print is always safe (Pitfall 2).
jobs_by_id = {}
# Phase 9 (D-11, D-12): list of (file_position, sanitized_agentic_job_id) for ALL
# valid job markers seen in the file, used for deferred owning_job_id resolution.
# Resolved over the full file regardless of the prior-ledger emission cutoff (D-12).
job_positions = []

marker_path = Path(markers_dir) / f"{sid}.jsonl"
markers = []
read_ok = True
read_err = ""
# Phase 9 (D-11): file-order position counter — incremented for every valid parsed
# dict line (both job and task markers) so positions reflect true file order.
_file_pos = 0
if marker_path.is_file():
    try:
        with marker_path.open() as f:
            for line in f:
                line = line.rstrip('\n')
                if not line:
                    continue
                # T-03-04 defense: cap per-line memory at 4 KB.
                if len(line) > 4096:
                    continue
                # MARK-04 / D-15: per-line try/except. A torn last line or any
                # malformed line is skipped; loop continues.
                try:
                    m = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # A valid-JSON line that is not an object (list/scalar) has no .get;
                # skip it before any attribute access so one bad line never aborts
                # the whole session's attribution (v1.0 'k in m' tolerated this).
                if not isinstance(m, dict):
                    continue
                _file_pos += 1
                # Phase 7 (SCHEMA-03 / D-06): branch on kind BEFORE REQUIRED_KEYS check.
                # This preserves v1.0 byte-identity: absent kind falls through to the
                # existing REQUIRED_KEYS gate unchanged. A kind:"job" line must never
                # reach markers.append() — that would generate spurious meter calls.
                kind = m.get("kind")
                if kind == "job":
                    # D-04: validate reader-required keys; skip if any missing.
                    # agentic_job_id must be a non-empty string — a list/dict value
                    # would raise unhashable TypeError when used as a dict key.
                    job_id = m.get("agentic_job_id")
                    if isinstance(job_id, str) and job_id and all(k in m for k in JOB_REQUIRED):
                        # Phase 9 (D-16): sanitize agentic_job_id colon-safe before
                        # any ledger write or CLI argument — replace bad chars with '_'.
                        # Same replace(bad,'_') approach as WR-01 pipe sanitization.
                        _bad_chars = (':', ' ', '\t', '\n', '\r')
                        clean_id = job_id
                        for _bad in _bad_chars:
                            clean_id = clean_id.replace(_bad, '_')
                        # Phase 9 (D-11/D-12): track (file_position, sanitized_id,
                        # job_name, job_type) for ALL valid job markers — full file
                        # order (D-12). job_name/job_type ride along so the deferred
                        # resolution pass can stamp --agentic-job-name / --agentic-job-type
                        # onto each owned task marker's meter completion call.
                        job_positions.append((
                            _file_pos,
                            clean_id,
                            m.get('job_name', '') or '',
                            m.get('job_type', '') or '',
                        ))
                        jobs_by_id[job_id] = m  # D-12: last line wins
                    continue  # never reaches task-marker collector
                elif kind is not None:
                    continue  # unknown kind — skip for forward compat (D-06)
                # kind is None (absent) → v1.0 task marker path (byte-identical)
                if not all(k in m for k in REQUIRED_KEYS):
                    continue
                # Primary dedup: global muid set. parse_prior_state returns
                # every muid ever ledger'd for this sid across all total_tokens
                # windows, so a muid that already shipped will be in this set
                # regardless of which tick reported it. Partial-failure recovery
                # (COMPAT-03 / SC2) relies on this: muids 4-5 of a 5-marker batch
                # whose tick crashed between calls 3 and 5 stay OUT of the set
                # and are correctly re-emitted on the next tick.
                if m['muid'] in prior_muids:
                    continue
                # Secondary (v1-only) fallback: when no v2 muids exist yet for
                # this sid (fresh upgrade, ledger has only v1 rows), use the
                # ts cutoff to avoid mass-emitting any marker history that
                # predates the upgrade. Once any v2 row exists, prior_muids is
                # the complete record and the ts filter is harmful (it would
                # skip un-emitted markers whose ts predates the latest v2 row).
                if not prior_muids:
                    try:
                        if float(m['ts']) <= prior_ts:
                            continue
                    except (TypeError, ValueError):
                        continue
                if m.get('task_type') in FORBIDDEN:
                    continue
                # Phase 9 (D-11): store file position in the marker dict for the
                # deferred owning_job_id resolution pass below.
                m['_file_pos'] = _file_pos
                markers.append(m)
    except OSError as exc:
        # D-14 / D-15: any other file-read OSError falls through.
        read_ok = False
        read_err = f"oserror: {exc}"

# Phase 9 (D-11, D-12): deferred owning_job_id resolution pass.
# Primary rule (D-08): a task marker is owned by the FIRST job marker whose file
# position is GREATER than the task marker's position (job markers appear at arc
# end, claiming all task markers above them in file order).
#
# Fallback (TRACE-FIX 2026-06-25): a task marker with NO later job marker is NOT
# orphaned — it is attributed to the NEAREST PRECEDING job marker instead. The
# pure "first job after" rule assumed every arc closes with its own job marker
# below it, but the classifier's _job_marker_exists gate writes at most ONE job
# marker per session, written EARLY (after the first arc). In long-lived
# multi-turn sessions (daily pipeline, Slack gateway) the remaining task markers
# accumulate BELOW that single early job marker and were silently dropped to
# owning_job_id = None — shipping ~95% of completions with no --agentic-job-id,
# which in turn left Revenium's server-derived traceType/agenticJobId null.
# Falling back to the nearest preceding job marker keeps existing arc-end
# semantics byte-identical (any task WITH a later job still binds to it) while
# rescuing the trailing tasks. Resolution uses ALL job markers in file order
# regardless of emission cutoff (D-12).
for marker in markers:
    task_pos = marker.pop('_file_pos', 0)
    owner = None
    owner_name = ''
    owner_type = ''
    for job_pos, clean_job_id, job_name, job_type in job_positions:
        if job_pos > task_pos:
            owner = clean_job_id
            owner_name = job_name
            owner_type = job_type
            break
    if owner is None:
        # No job marker after this task: bind to the nearest preceding job marker
        # (largest job_pos still below task_pos). job_positions is in ascending
        # file order, so iterate in reverse to find the closest one first.
        for job_pos, clean_job_id, job_name, job_type in reversed(job_positions):
            if job_pos < task_pos:
                owner = clean_job_id
                owner_name = job_name
                owner_type = job_type
                break
    marker['owning_job_id'] = owner
    marker['owning_job_name'] = owner_name
    marker['owning_job_type'] = owner_type

n = len(markers)
# D-18 telemetry log lines — locked text, do NOT paraphrase. mean_per_marker
# uses floor-division of the CURRENT-TICK delta (W2). Only emitted when n>0;
# the zero-marker fallthrough has no S2 telemetry per D-18.
if read_ok and n > 0:
    mean_per_marker = delta_total // n if n > 0 else 0
    print(f"S2_INFO=window={n}, mean_per_marker={mean_per_marker}")
    if n == 2 and any(m.get('operation_type') == 'GUARDRAIL' for m in markers):
        print("S2_WARN=classification-dominated window, attribution may be lossy")

print(f"READ_OK={'true' if read_ok else 'false'}")
if read_err:
    print(f"READ_ERR={read_err}")
print(f"N_MARKERS={n}")
print(f"PRIOR_MUIDS_COUNT={len(prior_muids)}")
print(f"MARKERS_JSON={json.dumps(markers, separators=(',', ':'))}")
# Phase 7 (SCHEMA-03): emit collected job declarations for Phase 9 consumption.
# jobs_by_id is always defined (initialized before is_file() check — Pitfall 2).
print(f"JOBS_JSON={json.dumps(list(jobs_by_id.values()), separators=(',', ':'))}")
PY
    ) || marker_output=""

    if [[ -n "${marker_output}" ]]; then
      read_ok=$(echo "${marker_output}" | sed -n 's/^READ_OK=//p' | head -1)
      read_ok="${read_ok:-false}"
      n_markers=$(echo "${marker_output}" | sed -n 's/^N_MARKERS=//p' | head -1)
      n_markers="${n_markers:-0}"
      prior_muids_count=$(echo "${marker_output}" | sed -n 's/^PRIOR_MUIDS_COUNT=//p' | head -1)
      prior_muids_count="${prior_muids_count:-0}"
      s2_info_line=$(echo "${marker_output}" | sed -n 's/^S2_INFO=//p' | head -1)
      s2_warn_line=$(echo "${marker_output}" | sed -n 's/^S2_WARN=//p' | head -1)
      read_err=$(echo "${marker_output}" | sed -n 's/^READ_ERR=//p' | head -1)
      # Phase 9 (D-08): capture jobs_json — used by the jobs create stage below.
      jobs_json=$(echo "${marker_output}" | sed -n 's/^JOBS_JSON=//p' | head -1)
      if [[ "${read_ok}" != "true" ]]; then
        warn "marker-read fall-through: session=${sid} reason=${read_err:-unknown}"
        n_markers=0
      fi
    else
      warn "marker-read fall-through: session=${sid} reason=empty-output"
      n_markers=0
    fi

    if [[ -n "${s2_info_line}" ]]; then
      info "S2: ${s2_info_line}"
    fi
    if [[ -n "${s2_warn_line}" ]]; then
      warn "S2: ${s2_warn_line}"
    fi

    # Phase 9 (D-08, D-09, D-10, CREATE-02, CREATE-04): idempotent best-effort jobs create.
    # Runs in-loop, per-session, before the per-marker --agentic-job-id stamping so the
    # Revenium job record exists before any completion is linked to it (D-08 spirit).
    # Gated on JOBS_CLI_CAPABLE — skip entirely when CLI lacks jobs/--agentic-job-id.
    if [[ "${JOBS_CLI_CAPABLE}" == "true" && -n "${jobs_json}" && "${jobs_json}" != "[]" ]]; then
      local job_rows
      job_rows=$(
        JOBS_JSON="${jobs_json}" \
        SOURCE="${source}" \
        python3 - <<'PY' 2>/dev/null || true
import json, os, sys

# Phase 46 (D-10): byte-safe clamp, duplicated from
# classifier.py::_clamp_assessment_text -- this is a standalone python3
# subprocess body inside a bash heredoc and cannot import that module, and
# this repo's convention is deliberate duplication for isolation between
# the fail-open in-session code and the out-of-process reporter. Measures
# SERIALIZED BYTES (json.dumps ensure_ascii=True), not characters, since a
# character clamp under-counts by up to 12x for non-ASCII text. Binary
# search over code-point slices so a surrogate pair is never split.
def _clamp_bytes(value, limit):
    if not isinstance(value, str):
        value = '' if value is None else str(value)

    def _serialized_len(s):
        return len(json.dumps(s, ensure_ascii=True).encode('utf-8')) - 2

    if _serialized_len(value) <= limit:
        return value
    lo, hi = 0, len(value)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _serialized_len(value[:mid]) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return value[:lo]

jobs = []
try:
    jobs = json.loads(os.environ.get('JOBS_JSON', '[]'))
    if not isinstance(jobs, list):
        jobs = []
except Exception:
    jobs = []

source = os.environ.get('SOURCE', '')

_bad_chars = (':', ' ', '\t', '\n', '\r')
for job in jobs:
    if not isinstance(job, dict):
        continue
    raw_id = job.get('agentic_job_id', '')
    if not isinstance(raw_id, str) or not raw_id:
        continue
    # D-16: sanitize agentic_job_id colon-safe (same replace(bad,'_') as reader D-16).
    clean_id = raw_id
    for _bad in _bad_chars:
        clean_id = clean_id.replace(_bad, '_')
    job_name = job.get('job_name', '') or ''
    job_type = job.get('job_type', '') or ''
    # Sanitize optional string fields so they are pipe-delimiter safe.
    for _bad in ('|', '\n', '\r'):
        job_name = job_name.replace(_bad, '_')
        job_type = job_type.replace(_bad, '_')
        source_clean = source.replace(_bad, '_') if source else ''
    source_clean = source
    for _bad in ('|', '\n', '\r'):
        source_clean = source_clean.replace(_bad, '_')
    # CR-01 (46-REVIEW.md): source is the one base-metering key the
    # --metadata ceiling's two-tier drop (D-02, ~line 3900) NEVER pops --
    # 'base metering never yields' is unconditional, so an unclamped source
    # is the one path that can still put an over-ceiling blob on the wire
    # after failure_reason's own byte clamp closed that field's version of
    # this gap. Clamp here, at the producer, exactly like failure_reason two
    # lines below -- same _clamp_bytes helper, same heredoc. 64 bytes
    # matches the other short caller-supplied identifiers this file already
    # clamps to 64 (evaluator, model, double_counting_group below) -- long
    # enough that a realistic Hermes deployment-source label (also forwarded
    # unclamped as --environment elsewhere in this file; that flag has no
    # ceiling of its own and is out of scope here) survives untouched, short
    # enough that source alone can never again single-handedly exceed
    # _METADATA_CEILING_BYTES.
    source_clean = _clamp_bytes(source_clean, 64)
    # Phase 10: emit status and marker ts as 5th and 6th pipe fields
    # for the outcome-queue accumulator (OUTCOME-05, D-07).
    status = job.get('status', '') or ''
    for _bad in ('|', '\n', '\r'):
        status = status.replace(_bad, '_')
    marker_ts = job.get('ts', 0) or 0
    # Phase 24 (quick-260531-n4i): carry failure_reason (FAILED arcs only) for
    # the outcome stage's --metadata. Prose — strip IFS chars, cap length.
    failure_reason = job.get('failure_reason', '') or ''
    if not isinstance(failure_reason, str):
        failure_reason = ''
    for _bad in ('|', '\n', '\r'):
        failure_reason = failure_reason.replace(_bad, ' ')
    failure_reason = _clamp_bytes(failure_reason, 500)
    print(f"{clean_id}|{job_name}|{job_type}|{source_clean}|{status}|{marker_ts}|{failure_reason}")
PY
      )

      if [[ -n "${job_rows}" ]]; then
        # Phase 22 (JOB-02 + JOB-03 / D-06): subagent sessions skip the in-loop jobs
        # stage for the same reason the pre-guard stage skips it — see plan 22-03
        # Task 2 comment. The two stages must be gated symmetrically; the
        # pre-guard scan is token-independent (job-only marker arc-close path), the
        # in-loop stage runs alongside token-positive emission. Both feed the same
        # job_outcome_queue and both invoke revenium jobs create; both are root-only.
        if [[ "${root_sid}" == "${sid}" ]]; then
          local clean_job_id job_name job_type job_env_source job_status_raw job_marker_ts job_failure_reason
          while IFS='|' read -r clean_job_id job_name job_type job_env_source job_status_raw job_marker_ts job_failure_reason; do
            [[ -z "${clean_job_id}" ]] && continue

            # Phase 10: push to outcome queue for every job row — regardless of create outcome.
            # The JOB:<id>:outcome: gate in the post-loop stage prevents double-reporting.
            # Push before the create-gated continue so already-created jobs are also queued.
            # Field 5 (failure_reason) is empty for SUCCESS/CANCELLED arcs.
            # Phase 38 (ROI-10): field 6 is sid, NOT the assessment itself — a nested
            # object cannot be a pipe field. The outcome stage re-reads this session's
            # marker for the assessment (38-RESEARCH.md: the marker is the carrier).
            job_outcome_queue+=("${clean_job_id}|${job_status_raw}|${job_env_source}|${job_marker_ts}|${job_failure_reason}|${sid}")

            # D-09: ledger-gated idempotency — skip if this job was already created.
            if grep -q "^JOB:${clean_job_id}:created:" "${JOBS_LEDGER_FILE}" 2>/dev/null; then
              continue
            fi

            # Build the jobs create cmd array (D-03, D-04, Pattern 8).
            local jobs_cmd=(
              revenium jobs create
              --agentic-job-id "${clean_job_id}"
              --quiet
            )
            if [[ -n "${job_name}" ]]; then
              jobs_cmd+=(--name "${job_name}")
            fi
            if [[ -n "${job_type}" ]]; then
              jobs_cmd+=(--type "${job_type}")
            fi
            # Planner discretion (D-03): pass --environment from session source column.
            # PR #101 / Greptile: --environment is a separate Revenium dimension from
            # the --metadata transport that CR-01 (d2606f0) clamped. job_env_source is
            # the CLAMPED pipe field (4th column of job_rows, shared with --metadata's
            # source key) — using it here regressed --environment to a 64-byte-truncated
            # value on this path while the precheck path (~line 1516) kept shipping the
            # raw ${source}. Use the raw, in-scope ${source} bash variable directly (the
            # same one lines 2653/2819/1516 already pass to --environment) so both
            # jobs-create paths agree byte-for-byte, matching pre-d2606f0 behavior.
            # Only --metadata has a byte ceiling; --environment has none.
            if [[ -n "${source}" ]]; then
              jobs_cmd+=(--environment "${source}")
            fi
            # quick-260605: pass teamId explicitly when resolved (omitted in tests).
            if [[ -n "${REVENIUM_TEAM_ID_RESOLVED}" ]]; then
              jobs_cmd+=(--team-id "${REVENIUM_TEAM_ID_RESOLVED}")
            fi
            # BUG-2: thread the SAME organization dimension through jobs create as
            # completions/tool-events carry, so a job and its transactions never
            # land in different orgs. Omitted when unset (preserves v1.4 wire shape).
            if [[ -n "${ORG_NAME}" ]]; then
              jobs_cmd+=(--organization-name "${ORG_NAME}")
            fi

            # D-10: best-effort invocation — capture output and exit code; never abort.
            local jobs_cmd_output jobs_cmd_exit
            jobs_cmd_output=$("${jobs_cmd[@]}" 2>&1) && jobs_cmd_exit=0 || jobs_cmd_exit=$?

            # D-04 / D-09: treat exit 0 AND HTTP-409/already-exists as success-equivalent.
            # The CLI exits non-zero for a 409, so check stdout/stderr for 409 indicators too.
            local jobs_success=false
            if [[ "${jobs_cmd_exit}" -eq 0 ]]; then
              jobs_success=true
            elif echo "${jobs_cmd_output}" | grep -qi "409\|already.exist\|conflict"; then
              jobs_success=true
            fi

            if [[ "${jobs_success}" == "true" ]]; then
              # D-15: write JOB:<id>:created:<unix_ts> to jobs ledger on success-or-409.
              local now_ts
              now_ts=$(python3 -c "import time; print(f'{time.time():.3f}')" 2>/dev/null || date +%s)
              echo "JOB:${clean_job_id}:created:${now_ts}" >> "${JOBS_LEDGER_FILE}"
              info "Job created: agentic_job_id=${clean_job_id}"
            else
              # D-10: best-effort — warn once, never abort or continue the session loop.
              warn "jobs create failed: id=${clean_job_id} exit=${jobs_cmd_exit} — metering continues"
            fi
          done <<< "${job_rows}"
        fi
      fi
    fi

    # Phase 32 Plan 03 (C-11/D-13): the ENTIRE legacy completion-emission
    # block below (both the per-marker and zero-marker paths) is skipped for
    # this session only when this session's own suppression predicate
    # resolved true at loop-entry (REVENIUM_LEGACY_COMPLETIONS=disabled AND
    # the drain gate reports drained AND — quick-260818-f1g STALE-07 — this
    # sid is not on `legacyRetainedSids`). This is the ONLY change this plan
    # makes to the session loop — the jobs-create stage above (and the
    # post-loop jobs outcome stage below) are OUTSIDE this guard and keep
    # running in every configuration, because post_api_request carries no job
    # lifecycle signal (D-10). The superseded code inside this guard is
    # retained, not deleted — disabling it is a setting flip, not a revert
    # (D-11).
    #
    # quick-260817-tfe (OWN-01): the condition now requires BOTH gates clear.
    # The ownership SUPPRESSION composes HERE, and nowhere earlier, for a
    # measured reason: api-event-report.sh SHIPS --agentic-job-id but contains
    # zero `jobs create` calls — job creation is legacy-only (D-10) — so an
    # early `continue` at the top of the session loop would orphan every event
    # row's job reference. This guard wraps only the completion-emission block
    # and deliberately leaves the pre-guard jobs scan, the in-loop jobs-create
    # stage and the post-loop outcome stage OUTSIDE it. reported_count and
    # skipped_count are left untouched by the ownership suppression so the
    # existing summary keeps its meaning.
    #
    # quick-260818-f1g (STALE-07/AX-S25): `sid_legacy_suppressed` is resolved
    # ONCE per session at loop-entry (above, near `total_tokens`) and reused
    # here verbatim — the SAME local the takeover branch reads — so the two
    # consumer sites of the carve-out cannot drift.
    if [[ "${sid_legacy_suppressed}" != "true" && "${session_event_owned}" != "true" ]]; then
    # Phase 3 cutover (T05 / B3 / B4): if markers exist for this window, emit
    # per-marker Revenium calls with extended transaction-id and per-call v2
    # ledger writes. Else fall through to the legacy single-call path (T06
    # finalizes that branch with --task-type unclassified + synthetic muid).
    # The per-session idempotency pre-filter on line 71 already short-circuits
    # sessions whose (sid, total_tokens) already has any v2 row — the precise
    # per-muid dedupe happens INSIDE the T04 marker reader via parse_prior_state.
    if [[ "${n_markers}" -gt 0 ]]; then
      # === Per-marker emission (CRON-01..06) ===
      local markers_json
      markers_json=$(echo "${marker_output}" | sed -n 's/^MARKERS_JSON=//p' | head -1)
      local delta_fields_json
      delta_fields_json=$(
        DELTA_INPUT="${delta_input}" \
        DELTA_OUTPUT="${delta_output}" \
        DELTA_CACHE_READ="${delta_cache_read}" \
        DELTA_CACHE_WRITE="${delta_cache_write}" \
        DELTA_TOTAL="${delta_total}" \
        DELTA_COST="${delta_cost}" \
        python3 - <<'PY' 2>/dev/null || echo '{}'
import json, os
print(json.dumps({
    "input": int(os.environ.get('DELTA_INPUT', '0') or '0'),
    "output": int(os.environ.get('DELTA_OUTPUT', '0') or '0'),
    "cache_read": int(os.environ.get('DELTA_CACHE_READ', '0') or '0'),
    "cache_write": int(os.environ.get('DELTA_CACHE_WRITE', '0') or '0'),
    "total": int(os.environ.get('DELTA_TOTAL', '0') or '0'),
    "cost": os.environ.get('DELTA_COST', '0') or '0',
}, separators=(',', ':')))
PY
      )

      # B5: second heredoc — merge markers with equal_split outputs into one
      # pipe-delimited row per marker for bash consumption. Cost is serialized
      # as a STRING so Decimal precision round-trips across the bash boundary.
      local split_rows
      split_rows=$(
        MARKERS_JSON="${markers_json}" \
        DELTA_FIELDS_JSON="${delta_fields_json}" \
        N_MARKERS="${n_markers}" \
        SCRIPT_DIR="${SCRIPT_DIR}" \
        python3 - <<'PY' 2>&1
import json, os, sys
try:
    sys.path.insert(0, os.environ['SCRIPT_DIR'])
    from split_strategies import equal_split
    markers = json.loads(os.environ['MARKERS_JSON'])
    delta = json.loads(os.environ['DELTA_FIELDS_JSON'])
    n = int(os.environ['N_MARKERS'])
    splits = equal_split(delta, n)
    for marker, split in zip(markers, splits):
        m_agent = marker.get('agent', '')
        m_trace = marker.get('trace_id', '')
        # Phase 9 (D-13): pass owning_job_id (+ name/type) through the pipe row so the
        # bash per-marker loop can append --agentic-job-id / --agentic-job-name /
        # --agentic-job-type when non-empty.
        m_owning_job_id = marker.get('owning_job_id') or ''
        m_owning_job_name = marker.get('owning_job_name') or ''
        m_owning_job_type = marker.get('owning_job_type') or ''
        # WR-01: sanitize pipe-delimiters and control chars so future upstream writers
        # cannot corrupt the bash while-read IFS='|' parsing (D-34).
        for _bad in ('|', '\n', '\r'):
            m_agent = m_agent.replace(_bad, '_')
            m_trace = m_trace.replace(_bad, '_')
            m_owning_job_id = m_owning_job_id.replace(_bad, '_')
            m_owning_job_name = m_owning_job_name.replace(_bad, '_')
            m_owning_job_type = m_owning_job_type.replace(_bad, '_')
        print(f"{marker['muid']}|{marker['task_type']}|{marker['operation_type']}|"
              f"{split['input']}|{split['output']}|{split['cache_read']}|"
              f"{split['cache_write']}|{split['total']}|{split['cost']}|{m_agent}|{m_trace}|"
              f"{m_owning_job_id}|{m_owning_job_name}|{m_owning_job_type}")
except Exception as exc:
    print(f"SPLIT_ERROR={exc}", file=sys.stderr)
    sys.exit(3)
PY
      ) || split_rows=""

      if [[ -z "${split_rows}" ]]; then
        warn "split-emit fall-through: session=${sid} reason=empty-split-rows"
        # If the split fails, do NOT silently re-emit as legacy — the markers
        # were valid (n_markers > 0) but the splitter or json round-trip
        # broke. Skip this session entirely; the next tick retries.
        ((skipped_count++)) || true
        continue
      fi

      local muid t_type op_type d_in d_out d_cr d_cw d_tot d_cost m_agent m_trace
      local m_owning_job_id m_owning_job_name m_owning_job_type
      while IFS='|' read -r muid t_type op_type d_in d_out d_cr d_cw d_tot d_cost m_agent m_trace m_owning_job_id m_owning_job_name m_owning_job_type; do
        [[ -z "${muid}" ]] && continue

        local cmd=(
          revenium meter completion
          --model "${clean_model}"
          --provider "${provider}"
          --input-tokens "${d_in}"
          --output-tokens "${d_out}"
          --cache-read-tokens "${d_cr}"
          --cache-creation-tokens "${d_cw}"
          --total-tokens "${d_tot}"
          --stop-reason "END"
          --request-time "${request_time}"
          --completion-start-time "${request_time}"
          --response-time "${response_time}"
          --request-duration "${duration_ms}"
          --agent "${m_agent:-${REVENIUM_AGENT_NAME}}"
          --transaction-id "${sid}-${total_tokens}-${muid}"
          --trace-id "${m_trace:-${root_sid}}"
          --is-streamed
          --quiet
          --task-type "${t_type}"
          --operation-type "${op_type}"
        )

        if [[ -n "${billing_provider}" ]]; then
          cmd+=(--model-source "${billing_provider}")
        fi
        if [[ "${d_cost}" != "0" && "${d_cost}" != "0.000000" && "${d_cost}" != "0.0" ]]; then
          cmd+=(--total-cost "${d_cost}")
        fi
        if [[ -n "${ORG_NAME}" ]]; then
          cmd+=(--organization-name "${ORG_NAME}")
        fi
        if [[ -n "${source}" ]]; then
          cmd+=(--environment "${source}")
        fi
        # quick-260625-mlc (TRACE-TYPE-01): ship the once-per-session root
        # trace-type (identical for every completion in this session/trace).
        # Value is always non-empty (falls back to "uncategorized"), so the wire
        # value is explicit rather than relying on the server default. Never
        # enters --transaction-id or the ledger line — idempotency is preserved.
        if [[ "${TRACE_TYPE_CLI_CAPABLE}" == "true" ]]; then
          cmd+=(--trace-type "${root_trace_type:-uncategorized}")
        fi
        # Phase 22 (JOB-01 / D-02 / D-05): per-marker --agentic-job-id slot.
        # The CLI has exactly one --agentic-job-id field (verified via
        # `revenium meter completion --help` 2026-05-29); this is REPLACE, not ADD.
        # Top-level (root_sid == sid): v1.3 path, ships m_owning_job_id +
        #   optional --agentic-job-name / --agentic-job-type siblings.
        # Subagent (root_sid != sid) with resolved root_aid: OVERRIDE with
        #   root's agentic_job_id. Sibling name/type flags are dropped in
        #   this plan; analytics rollup is keyed on --agentic-job-id alone
        #   (sufficient per D-02 design; future quick-task can plumb siblings).
        # Subagent with no root_aid (D-05 race): NO --agentic-job-id append.
        #   The subagent's own m_owning_job_id is NEVER shipped (would
        #   orphan-reference a non-existent Revenium job row since JOB-02
        #   suppresses the create). Next cron tick retries idempotently.
        if [[ "${JOBS_CLI_CAPABLE}" == "true" ]]; then
          if [[ "${root_sid}" == "${sid}" && -n "${m_owning_job_id}" ]]; then
            cmd+=(--agentic-job-id "${m_owning_job_id}")
            if [[ -n "${m_owning_job_name}" ]]; then
              cmd+=(--agentic-job-name "${m_owning_job_name}")
            fi
            if [[ -n "${m_owning_job_type}" ]]; then
              cmd+=(--agentic-job-type "${m_owning_job_type}")
            fi
          elif [[ "${root_sid}" != "${sid}" && -n "${root_aid}" ]]; then
            cmd+=(--agentic-job-id "${root_aid}")
          fi
        fi

        # Phase 29 (SQUAD-01/02/03 / D-03/D-04): squad attribution, gated on
        # a single CLI capability probe and appended identically at both
        # emit paths (29-02-PLAN.md <shared_root_resolution_decision>).
        # --squad-id is the root session id — the same per-session root
        # walk already feeding --trace-id above; --squad-name resolves
        # three levels deep (quick-260814-okp): the operator-set
        # REVENIUM_SQUAD_NAME first (an explicit squad-identity
        # declaration), then the root's marker-derived agent name, then
        # REVENIUM_AGENT_NAME — never emitted empty (D-03); --squad-role is
        # the literal "root" for the root session itself and "subagent" for
        # every session hanging off it. Flag order (--squad-id,
        # --squad-name, --squad-role) is part of the argv contract the
        # tests assert — keep it identical at both sites.
        if [[ "${SQUAD_CLI_CAPABLE}" == "true" ]]; then
          cmd+=(--squad-id "${root_sid}")
          cmd+=(--squad-name "${REVENIUM_SQUAD_NAME:-${root_agent_name:-${REVENIUM_AGENT_NAME}}}")
          if [[ "${root_sid}" == "${sid}" ]]; then
            cmd+=(--squad-role "root")
          else
            cmd+=(--squad-role "subagent")
          fi
        fi

        # Skill attribution (CLI 1.4.0), gated on one capability probe and
        # appended identically at both emit paths, exactly as the squad flags
        # above. Flag order (--skill-name, --skill-invocation-trigger,
        # --skill-source, --skill-marketplace-name) is part of the argv
        # contract the tests assert — keep it identical at both sites.
        #
        # --skill-kind and --skill-plugin-name are deliberately NEVER emitted:
        # we do not know what Revenium expects in them, and a guessed value
        # poisons a dimension worse than an absent one leaves it.
        #
        # A session with no skill signal appends NOTHING — that is the common
        # case (3-36% of token-bearing sessions carry a skill), and its argv
        # must stay byte-identical to the golden fixtures.
        if [[ "${SKILL_CLI_CAPABLE}" == "true" ]]; then
          local skill_pair skill_name skill_trigger prov_pair skill_source skill_marketplace
          skill_pair="$(resolve_session_skill "${sid}" "${ended_at:-}")"
          if [[ -n "${skill_pair}" ]]; then
            skill_name="${skill_pair%%|*}"
            skill_trigger="${skill_pair#*|}"
            cmd+=(--skill-name "${skill_name}")
            [[ -n "${skill_trigger}" ]] && cmd+=(--skill-invocation-trigger "${skill_trigger}")
            prov_pair="$(resolve_skill_provenance "${skill_name}")"
            if [[ -n "${prov_pair}" ]]; then
              skill_source="${prov_pair%%|*}"
              skill_marketplace="${prov_pair#*|}"
              [[ -n "${skill_source}" ]] && cmd+=(--skill-source "${skill_source}")
              [[ -n "${skill_marketplace}" ]] && cmd+=(--skill-marketplace-name "${skill_marketplace}")
            fi
          fi
        fi

        local cmd_output cmd_exit
        cmd_output=$("${cmd[@]}" 2>&1) && cmd_exit=0 || cmd_exit=$?

        if [[ "${cmd_exit}" -eq 0 ]]; then
          # CRON-06 / D-07 / B1 / Pitfall 8: write the v2 ledger row IMMEDIATELY
          # after each successful call (ONE row per muid; NEVER batched). Field
          # 5 carries EXACTLY ONE muid — never a CSV.
          local now_ts
          now_ts=$(python3 -c "import time; print(f'{time.time():.3f}')" 2>/dev/null || date +%s)
          echo "HERMES:${sid}:${total_tokens}:${now_ts}:${muid}" >> "${LEDGER_FILE}"
          ((reported_count++)) || true
          info "Reported: session=${sid} muid=${muid} task_type=${t_type} op_type=${op_type} in=${d_in} out=${d_out}"
          # Phase 44 Plan 04 (EGV-17): classified bucket -- attributed to a
          # real marker.
          attribution_rows+="classified|${d_in}|${d_out}|${d_cr}|${d_cw}|${d_tot}|${d_cost}"$'\n'
        else
          # Pitfall 8: on failure, do NOT append a ledger row. The next tick
          # re-reads the marker (still absent from prior_muids) and retries.
          warn "Failed: session=${sid} muid=${muid} exit=${cmd_exit} output=${cmd_output}"
          warn "Command: ${cmd[*]}"
          # Phase 44 Plan 04 (EGV-17): unallocated bucket -- this report
          # attempt did not result in a ledger line.
          attribution_rows+="unallocated|${d_in}|${d_out}|${d_cr}|${d_cw}|${d_tot}|${d_cost}"$'\n'
        fi
      done <<< "${split_rows}"
    else
      # === Zero-marker fallthrough (CRON-07 / D-11 / D-14 / D-15 / B4) ===
      # No markers in this window. Reasons: older install with no agent classification,
      # missing/empty marker file, all marker lines unparseable, or this session's
      # marker file was unreadable (TAX-05 / MARK-04 tolerance — see T04 reader heredoc).
      # WIRE-01 / D-22: emit --operation-type CHAT — gate discharged in 04-RESEARCH.md (Revenium server-side default; cost parity verified across 50+ historical records).
      # B4: --transaction-id stays as ${sid}-${total_tokens} — the synthetic muid that
      # appears in the v2 ledger row's field 5 is a LEDGER-SIDE identifier only, NEVER
      # in the wire transaction-id. Extending --transaction-id here would break SC3.
      local cmd=(
        revenium meter completion
        --model "${clean_model}"
        --provider "${provider}"
        --input-tokens "${delta_input}"
        --output-tokens "${delta_output}"
        --cache-read-tokens "${delta_cache_read}"
        --cache-creation-tokens "${delta_cache_write}"
        --total-tokens "${delta_total}"
        --stop-reason "END"
        --request-time "${request_time}"
        --completion-start-time "${request_time}"
        --response-time "${response_time}"
        --request-duration "${duration_ms}"
        # Phase 29 (AGENT-01 / D-01): inherit the root session's agent name
        # instead of reading REVENIUM_AGENT_NAME directly — same expression
        # and same once-per-session root_agent_name plan 29-02 resolves for
        # --squad-name, so both consumers share one resolution. Byte-
        # identical to today per the measured finding in
        # docs/migration-agent-dimension.md: no marker writer has ever
        # populated the `agent` field, so this falls back to
        # REVENIUM_AGENT_NAME on every current install.
        --agent "${root_agent_name:-${REVENIUM_AGENT_NAME}}"
        --transaction-id "${sid}-${total_tokens}"
        --trace-id "${root_sid}"
        --is-streamed
        --quiet
        --task-type "unclassified"
        --operation-type "CHAT"
      )

      if [[ -n "${billing_provider}" ]]; then
        cmd+=(--model-source "${billing_provider}")
      fi
      if [[ "${delta_cost}" != "0" && "${delta_cost}" != "0.0" ]]; then
        cmd+=(--total-cost "${delta_cost}")
      fi
      if [[ -n "${ORG_NAME}" ]]; then
        cmd+=(--organization-name "${ORG_NAME}")
      fi
      if [[ -n "${source}" ]]; then
        cmd+=(--environment "${source}")
      fi
      # quick-260625-mlc (TRACE-TYPE-01): identical gated --trace-type append as
      # the per-marker path — root_trace_type is in scope and already resolved for
      # this session-loop iteration. Never enters --transaction-id or the ledger.
      if [[ "${TRACE_TYPE_CLI_CAPABLE}" == "true" ]]; then
        cmd+=(--trace-type "${root_trace_type:-uncategorized}")
      fi

      # Phase 29 (SQUAD-01/02/03 / D-03/D-04): identical gated squad append
      # as the per-marker path above — root_sid and root_agent_name are
      # already resolved for this session-loop iteration. See that site's
      # comment for the full rationale (including the quick-260814-okp
      # REVENIUM_SQUAD_NAME override) — kept byte-identical here so the
      # argv contract holds at both emit paths.
      if [[ "${SQUAD_CLI_CAPABLE}" == "true" ]]; then
        cmd+=(--squad-id "${root_sid}")
        cmd+=(--squad-name "${REVENIUM_SQUAD_NAME:-${root_agent_name:-${REVENIUM_AGENT_NAME}}}")
        if [[ "${root_sid}" == "${sid}" ]]; then
          cmd+=(--squad-role "root")
        else
          cmd+=(--squad-role "subagent")
        fi
      fi

      # Skill attribution (CLI 1.4.0), gated on one capability probe and
      # appended identically at both emit paths, exactly as the squad flags
      # above. Flag order (--skill-name, --skill-invocation-trigger,
      # --skill-source, --skill-marketplace-name) is part of the argv
      # contract the tests assert — keep it identical at both sites.
      #
      # --skill-kind and --skill-plugin-name are deliberately NEVER emitted:
      # we do not know what Revenium expects in them, and a guessed value
      # poisons a dimension worse than an absent one leaves it.
      #
      # A session with no skill signal appends NOTHING — that is the common
      # case (3-36% of token-bearing sessions carry a skill), and its argv
      # must stay byte-identical to the golden fixtures.
      if [[ "${SKILL_CLI_CAPABLE}" == "true" ]]; then
        local skill_pair skill_name skill_trigger prov_pair skill_source skill_marketplace
        skill_pair="$(resolve_session_skill "${sid}" "${ended_at:-}")"
        if [[ -n "${skill_pair}" ]]; then
          skill_name="${skill_pair%%|*}"
          skill_trigger="${skill_pair#*|}"
          cmd+=(--skill-name "${skill_name}")
          [[ -n "${skill_trigger}" ]] && cmd+=(--skill-invocation-trigger "${skill_trigger}")
          prov_pair="$(resolve_skill_provenance "${skill_name}")"
          if [[ -n "${prov_pair}" ]]; then
            skill_source="${prov_pair%%|*}"
            skill_marketplace="${prov_pair#*|}"
            [[ -n "${skill_source}" ]] && cmd+=(--skill-source "${skill_source}")
            [[ -n "${skill_marketplace}" ]] && cmd+=(--skill-marketplace-name "${skill_marketplace}")
          fi
        fi
      fi

      local cmd_output cmd_exit
      cmd_output=$("${cmd[@]}" 2>&1) && cmd_exit=0 || cmd_exit=$?

      if [[ "${cmd_exit}" -eq 0 ]]; then
        # CRON-06 / D-07 / D-09 / D-11 / B1: write v2 ledger row with synthetic
        # placeholder muid. Field 5 holds EXACTLY one value (not a CSV) per B1
        # one-row-per-muid lock. The `unclassified-` prefix marks this row as
        # the zero-marker path so the field-count discrimination remains reliable
        # (v2 = 5 fields, never empty tail).
        local now_ts synthetic_muid
        now_ts=$(python3 -c "import time; print(f'{time.time():.3f}')" 2>/dev/null || date +%s)
        synthetic_muid="unclassified-${now_ts//./}"
        echo "HERMES:${sid}:${total_tokens}:${now_ts}:${synthetic_muid}" >> "${LEDGER_FILE}"
        ((reported_count++)) || true
        info "Reported: session=${sid} task_type=unclassified model=${clean_model} provider=${provider} in=${delta_input} out=${delta_output} cost=${delta_cost}"
        # Phase 44 Plan 04 (EGV-17): unclassified bucket -- the markerless path.
        attribution_rows+="unclassified|${delta_input}|${delta_output}|${delta_cache_read}|${delta_cache_write}|${delta_total}|${delta_cost}"$'\n'
      else
        warn "Failed: session=${sid} exit=${cmd_exit} output=${cmd_output}"
        warn "Command: ${cmd[*]}"
        # Phase 44 Plan 04 (EGV-17): unallocated bucket -- this report
        # attempt did not result in a ledger line.
        attribution_rows+="unallocated|${delta_input}|${delta_output}|${delta_cache_read}|${delta_cache_write}|${delta_total}|${delta_cost}"$'\n'
      fi
    fi
    fi # LEGACY_COMPLETIONS_SKIP + session_event_owned guard (Phase 32 Plan 03 C-11/D-13; quick-260817-tfe OWN-01)
  done <<< "${sessions}"

  # Phase 10: post-loop outcome stage — report each terminated arc exactly once.
  # Placement is load-bearing: every JOB:<id>:created: line that any session could
  # write this tick has already been written by the time this stage runs (D-01).
  # Mirrors the in-loop jobs create stage (D-06: API-first, ledger-on-exit-0).
  if [[ "${JOBS_CLI_CAPABLE}" == "true" && "${#job_outcome_queue[@]}" -gt 0 ]]; then
    local outcome_id outcome_status_raw outcome_source outcome_marker_ts outcome_failure_reason outcome_sid
    local outcome_status outcome_cmd_output outcome_cmd_exit outcome_success
    local outcome_now_ts _age_s _stale_threshold outcome_metadata
    local outcome_warn_reason outcome_warn_key outcome_warn_flag
    # Phase 42 (C-04): the marker-sourced outcome_evidence_class/
    # outcome_evaluator/outcome_evaluator_version/outcome_confidence/
    # outcome_hours_saved/outcome_loaded_rate locals are gone -- the outcome
    # stage now resolves an accepted assessment from the sidecar, never the
    # marker (D-10). outcome_value/outcome_currency remain scalars because
    # the outcome_cmd+=(--outcome-value ...) construction below runs BEFORE
    # the metadata heredoc; outcome_assessment_json carries the rest as one
    # JSON blob. outcome_markers_dir returns (Phase 42 Plan 04, D-10): a
    # narrow read-only presence PROBE on the job marker's own `assessment`
    # key, used only to tell "never evaluated" apart from "evaluated by an
    # older classifier, sidecar since pruned or never written" for the
    # rolling-upgrade diagnostic reason word -- never a value source.
    local outcome_assessment_dir outcome_value outcome_currency outcome_markers_dir
    local outcome_assessment_json outcome_reason
    for _entry in "${job_outcome_queue[@]}"; do
      IFS='|' read -r outcome_id outcome_status_raw outcome_source outcome_marker_ts outcome_failure_reason outcome_sid <<< "${_entry}"
      [[ -z "${outcome_id}" ]] && continue

      # OUTCOME-01 gate: skip if already reported (ledger-gated idempotency).
      if grep -q "^JOB:${outcome_id}:outcome:" "${JOBS_LEDGER_FILE}" 2>/dev/null; then
        continue
      fi

      # OUTCOME-04 gate: skip if create not yet confirmed; re-attempt next tick.
      if ! grep -q "^JOB:${outcome_id}:created:" "${JOBS_LEDGER_FILE}" 2>/dev/null; then
        # D-07: stale warn if marker ts is older than threshold.
        _stale_threshold="${REVENIUM_JOBS_STALE_SECONDS:-600}"
        _age_s=$(python3 -c "
import time
try:
    ts = float('${outcome_marker_ts}')
    print(int(time.time() - ts))
except Exception:
    print(0)
" 2>/dev/null || echo "0")

        # WR-01: count DISTINCT jobs, not raw queue entries -- the two
        # producers above (`:1473`, `:2375`) can both push this same
        # outcome_id in one tick (see outcome_deferred_seen's declaration
        # comment). Increment only the first time this outcome_id is seen
        # this tick; a later entry for the same job (deferred or wedged,
        # doesn't matter) is already the same backlog item.
        case "${outcome_deferred_seen}" in
          *$'\n'"${outcome_id}"$'\n'*) ;;  # already counted this tick
          *)
            ((outcome_deferred_tick_count++)) || true
            outcome_deferred_seen="${outcome_deferred_seen}${outcome_id}"$'\n'
            ;;
        esac

        # Phase 39 D-02: bound this per-job line to once per (outcome_id,
        # reason) via a zero-byte flag file under OUTCOME_WARN_FLAGS_DIR --
        # mirrors FALLBACK_WARN_FLAGS_DIR byte-for-byte. The key is computed
        # ONCE into a local shared by both the existence check and the
        # touch (sanitize-before-compare, T-38-08 one level down) -- two
        # copies of the sanitizing expression drift, and when they do the
        # check tests one path while the touch creates another, so the gate
        # silently never matches. Nothing per-tick (_age_s, a timestamp, a
        # tick counter) may enter this key: outcome_id is stable per job
        # across ticks (the whole reason it is the key), and a key that
        # changes every tick reproduces the unknown-<epoch> defeat
        # pre_llm_call.sh:73-115 already paid for once -- a gate that never
        # matches, warns every time, and leaks one file per event. A reason
        # TRANSITION (deferred -> wedged) deliberately changes the key and
        # therefore warns once more -- that transition is the informative
        # event and must not be swallowed.
        if [[ "${_age_s}" -ge "${_stale_threshold}" ]]; then
          outcome_warn_reason="wedged"
        else
          outcome_warn_reason="deferred"
        fi
        outcome_warn_key="${outcome_id//[^A-Za-z0-9_:.-]/_}__${outcome_warn_reason}.flag"
        outcome_warn_flag="${OUTCOME_WARN_FLAGS_DIR}/${outcome_warn_key}"
        if [[ ! -e "${outcome_warn_flag}" ]]; then
          # Tolerate a failed flag creation (e.g. a read-only state dir)
          # without aborting: this script runs `set -uo pipefail` without
          # `-e`, and a read-only state directory must degrade to today's
          # every-tick warn rather than crash the reporter.
          mkdir -p "${OUTCOME_WARN_FLAGS_DIR}" 2>/dev/null && touch "${outcome_warn_flag}" 2>/dev/null
          if [[ "${outcome_warn_reason}" == "wedged" ]]; then
            warn "wedged job (no create confirmed after ${_age_s}s): id=${outcome_id}"
          else
            warn "outcome deferred: id=${outcome_id} — JOB:...:created not yet confirmed"
          fi
        fi
        # The retry is NEVER gated -- only the LINE above is. A job that
        # stops being retried is a job that never reports, which is a
        # strictly worse failure than a noisy log.
        continue
      fi

      # OUTCOME-05: uppercase and validate enum; invalid -> skip + warn, no ledger write.
      outcome_status=$(python3 -c "print('${outcome_status_raw}'.upper())" 2>/dev/null \
        || echo "${outcome_status_raw}")
      case "${outcome_status}" in
        SUCCESS|FAILED|CANCELLED) ;;
        *)
          warn "outcome skipped: id=${outcome_id} invalid status=${outcome_status}"
          continue
          ;;
      esac

      # Phase 42 (C-01/C-04/D-10): resolve an accepted assessment. The
      # assessment is re-read from the job-assessments SIDECAR, never from
      # the job marker's own 9-key `assessment` summary (D-10) — C-01
      # demoted that object to pointer-and-summary, not the record of
      # record. An absent, unreadable, over-SIDECAR_LINE_MAX_BYTES, or
      # pruned sidecar record reports the outcome status-only, with no
      # --outcome-value, and never falls back to the marker. The sidecar
      # directory is resolved per-session below (not read off
      # JOB_ASSESSMENTS_DIR) because a multiplexed gateway owns each
      # session's state under its own profile home — the same per-session
      # resolution pattern resolve_markers_dir already provides for the
      # marker directory.
      #
      # Phase 44 (EGV-17, D-14): this gate USED to be
      # `outcome_status == "SUCCESS"` on the premise that FAILED/CANCELLED
      # are never evaluated, so no sidecar could exist for them. That
      # premise is now FALSE — classifier.py's run_classification_async
      # Step 7 gained a non-SUCCESS abstention branch (44-03-PLAN.md Task
      # 2) that writes a sidecar record for a FAILED or CANCELLED job too
      # (never through _attach_assessment, so the evaluator is still never
      # reached; only the RECORD side changed). Gating this read on
      # outcome_status would silently orphan every non-SUCCESS record's
      # supplied_costs/cost_coverage/double_counting_group from ever
      # reaching --metadata, defeating EGV-17's whole point (cost stays
      # visible even when there is no value). The read below is otherwise
      # unchanged and remains status-agnostic past this point: a
      # non-SUCCESS abstention record carries no value_low/currency, so
      # _value_ok resolves false and no --outcome-value flag is ever built
      # for it, exactly as an unvalued SUCCESS record already behaves.
      outcome_value=""
      outcome_currency=""
      outcome_assessment_json=""
      outcome_reason=""
      if [[ -n "${outcome_sid}" ]]; then
        outcome_assessment_dir="$(resolve_assessments_dir "${outcome_sid}")"
        [[ -z "${outcome_assessment_dir}" ]] && outcome_assessment_dir="${JOB_ASSESSMENTS_DIR}"
        # D-10 diagnostic reason word: resolve the SAME per-session markers
        # dir the marker reader uses, so the presence probe below reads the
        # profile that actually owns this session, not the process-level
        # default (the same reasoning resolve_assessments_dir already
        # documents for the sidecar directory itself).
        outcome_markers_dir="$(resolve_markers_dir "${outcome_sid}")"
        [[ -z "${outcome_markers_dir}" ]] && outcome_markers_dir="${MARKERS_DIR}"
        local _assessment_kv
        _assessment_kv=$(
          ASSESSMENTS_DIR="${outcome_assessment_dir}" \
          OUTCOME_JOB_ID="${outcome_id}" \
          OUTCOME_MARKERS_DIR="${outcome_markers_dir}" \
          OUTCOME_SID="${outcome_sid}" \
          python3 - <<'PY' 2>/dev/null || true
import json
import os
import re
from pathlib import Path

assessments_dir = os.environ.get('ASSESSMENTS_DIR', '')
job_id = os.environ.get('OUTCOME_JOB_ID', '')

if not assessments_dir or not job_id:
    raise SystemExit(0)

# Phase 42: a fourth independent copy of the writer-side sanitize transform
# (hermes-report.sh:1418/:2332/:2996; classifier.py's
# _sidecar_filename_component's first step) plus its filename-safety pass
# (that function's second step) -- kept in sync by hand, matching this
# file's existing deliberate-duplication posture (CLAUDE.md). A
# one-character disagreement between the writer and this reader orphans
# every record for that job (the CR-02 bug class this repo already paid
# for once, at a different join site).
_bad_chars = (':', ' ', '\t', '\n', '\r')


def _clean(v):
    for bad in _bad_chars:
        v = v.replace(bad, '_')
    return v


def _sidecar_component(raw):
    if not isinstance(raw, str):
        return '_'
    value = _clean(raw)
    value = re.sub(r'[^A-Za-z0-9._-]', '_', value)
    if value in ('', '.', '..'):
        return '_'
    return value


component = _sidecar_component(job_id)
sidecar_path = Path(assessments_dir) / f"{component}.jsonl"

# Phase 42's own guard, sized to the sidecar's SIDECAR_LINE_MAX_BYTES
# per-record ceiling -- deliberately NOT the marker reader's 4096 (that
# guard governs a different re-read and a different budget). Skip an
# over-length line, never crash.
SIDECAR_LINE_MAX_BYTES = 8192

found = None
try:
    with sidecar_path.open() as f:
        for line in f:
            raw_line = line.rstrip('\n')
            if not raw_line or len(raw_line.encode('utf-8')) > SIDECAR_LINE_MAX_BYTES:
                continue
            try:
                rec = json.loads(raw_line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(rec, dict):
                continue
            if rec.get('kind') not in ('job_assessment', 'correction'):
                continue
            raw_id = rec.get('agentic_job_id')
            if not isinstance(raw_id, str) or _clean(raw_id) != job_id:
                continue
            # Deliberate: no break. A later kind:"correction" line for the
            # same job id must naturally supersede the original on a
            # scan-to-end -- unlike the marker reader's identical-looking
            # loop (accidental), this one is deliberate, per
            # 41-CARRIER-DECISION.md Part 2.
            found = rec
except OSError:
    pass

# Greptile (PR #110), Phase 51 D-08: a mechanism-only correction carries NO
# value family -- absent by decision, so a correction never restates a
# valuation the operator did not supply. But the reader above replaces the
# effective record WHOLESALE (`found = rec`, last-match-wins, deliberate per
# 41-CARRIER-DECISION.md), so such a correction would otherwise make every
# downstream consumer see a record with no value at all: --outcome-value
# would go empty, the bound forwarders would emit nothing, and a perfectly
# good standing valuation would be silently dropped from the wire.
#
# Normalised HERE, once, rather than at each of the three consumer sites --
# the value flag, the bound-triple validity check, and the --metadata bound
# forwarder -- because patching consumers is how one of them gets missed.
#
# On a correction, `prior_value_*` IS the standing value; recording it is
# that field's entire purpose. It is promoted only into a gap: a correction
# that carries its own value keeps it untouched, and a job_assessment is
# never touched at all.
if isinstance(found, dict) and found.get('kind') == 'correction':
    for _cur, _prior in (
        ('value_low', 'prior_value_low'),
        ('value_base', 'prior_value_base'),
        ('value_high', 'prior_value_high'),
        ('currency', 'prior_currency'),
    ):
        if found.get(_cur) is None and found.get(_prior) is not None:
            found[_cur] = found[_prior]

if found is None:
    # D-10 diagnostic reason word (Phase 42 Plan 04): tell "never
    # evaluated" apart from "evaluated by an older classifier, sidecar
    # since pruned or never written" -- a PRESENCE probe only, on the job
    # marker's own frozen 9-key `assessment` summary (C-01's demoted
    # pointer-and-summary object). No field is extracted and no value is
    # taken from it here; D-10 still forbids using the marker as a value
    # source -- this only tells the operator which unvalued case they are
    # looking at.
    _reason = 'sidecar_unavailable'
    _markers_dir = os.environ.get('OUTCOME_MARKERS_DIR', '')
    _sid = os.environ.get('OUTCOME_SID', '')
    if _markers_dir and _sid:
        _marker_path = Path(_markers_dir) / f"{_sid}.jsonl"
        try:
            with _marker_path.open() as _mf:
                for _mline in _mf:
                    _mraw = _mline.rstrip('\n')
                    if not _mraw or len(_mraw.encode('utf-8')) > 4096:
                        continue
                    try:
                        _mrec = json.loads(_mraw)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if not isinstance(_mrec, dict) or _mrec.get('kind') != 'job':
                        continue
                    _mid = _mrec.get('agentic_job_id')
                    if not isinstance(_mid, str) or _clean(_mid) != job_id:
                        continue
                    # Deliberate: no break -- mirrors this file's own
                    # scan-to-end convention; a later job-status line for
                    # the same id supersedes an earlier one.
                    _reason = (
                        'sidecar_missing_for_valued_marker'
                        if 'assessment' in _mrec
                        else 'sidecar_unavailable'
                    )
        except OSError:
            pass
    print(f"REASON={_reason}")
    raise SystemExit(0)

# D-07 (Phase 42 Plan 04): fail closed on an unrecognized (newer)
# assessment_schema_version -- a newer version may redefine what the value
# field means (gross vs net lands in Phase 44), and billing on a guess is
# the failure mode worth avoiding. A recognized OLDER version is still
# valued normally -- do not strand every pre-upgrade record on the fleet at
# a version bump. Exactly one version is recognized today, so that branch
# is inert; it stays explicit because the first bump is when a missing
# branch becomes a silent outage.
RECOGNIZED_ASSESSMENT_SCHEMA_VERSIONS = frozenset({1})
_schema_version = found.get('assessment_schema_version')
if _schema_version not in RECOGNIZED_ASSESSMENT_SCHEMA_VERSIONS:
    # Emit NOTHING for the value scalars and NOTHING for the assessment
    # portion of --metadata -- an unrecognized version is not valued on a
    # guess, and its shape is not trusted enough to even echo back.
    print("REASON=schema_unrecognized")
    raise SystemExit(0)


def _s(v, maxlen=None):
    # Pipe/newline/CR-safe (IFS='|' transport, same rule as every other
    # sidecar/marker-derived field in this file). Also length-capped on
    # read, matching this file's existing convention.
    v = '' if v is None else str(v)
    for bad in ('|', '\n', '\r'):
        v = v.replace(bad, ' ')
    if maxlen is not None:
        v = v[:maxlen]
    return v


# Phase 43 (EGV-18, D-05/D-06/CF-1/CF-3): resolve reportability BEFORE the
# value scalars below are computed. hermes-report.sh holds NO independent
# reportability policy (CF-3) -- it reads and obeys reportability_status,
# with exactly one carve-out: a correction (kind == "correction") is
# reportable by construction. D-06: a correction is filed by an operator
# under explicit human authorisation, so EGV-18's gate over naked-LLM
# estimates does not apply to it -- this is the reasoning that keeps
# test_last_match_wins_ships_newest_correction_low_bound green, untouched
# by this change. Otherwise the record's own reportability_status must
# equal the reportable literal exactly; anything else (absent, "candidate",
# or a malformed value) is NOT reportable.
_REPORTABILITY_REPORTABLE = 'reportable'
_REPORTABILITY_STATUSES = frozenset({'reportable', 'candidate'})
_is_correction = found.get('kind') == 'correction'
_reportable = _is_correction or found.get('reportability_status') == _REPORTABILITY_REPORTABLE

# CR-01 (43-REVIEW.md): the value family and the function that removes it are
# declared ONCE, and every refusal branch calls it. Two independent gates
# refuse a value here -- the reportability gate below and the CF-2
# evidence_class allow-list further down -- and the allow-list branch
# originally cleared only the two CLI scalars, leaving value_low/base/high,
# bounds_source and assumptions in the transported record. A record that was
# reportable but carried an out-of-set evidence_class (a hand-edited sidecar:
# precisely the threat CF-2 exists to catch) therefore had its flags refused
# while the estimate still rode out in --metadata. Fixing it as one shared
# stripper rather than a second copy of the tuple is deliberate: a third
# refusal branch added later cannot forget the family, because there is
# nothing to forget -- it calls the same function.
#
# Phase 44 (EGV-14/EGV-15, D-07): 'net_value' joins this tuple because it is
# MODEL-DERIVED MONEY -- the same reason estimated_value is already in the
# family. supplied_costs and cost_coverage deliberately do NOT join it: they
# are OPERATOR input, not model output, and withholding them is what would
# make a null ROI unreadable (D-07's second sentence) -- they ship
# unconditionally via their own --metadata forwarders further below,
# regardless of reportability_status.
#
# Phase 54 (D-10/T-54-05, ROI-08): 'attribution_fraction' and
# 'attribution_basis' join this tuple because, as of this phase, a
# job_assessment record (not only a kind:"correction" record) can carry the
# pair -- _build_job_assessment's success-path record.update() emits both
# when a configured revenue registrant's attribution was accepted. They join
# for the same reason net_value did above and the same reason the pair
# already sits in _VALUE_FAMILY_META_KEYS' tier-1 shed further below in this
# file: a surviving value whose attribution has vanished is the failure
# worth preventing, and a surviving ATTRIBUTION whose value has vanished is
# that same failure inverted -- a fraction and a basis attributing a number
# that never reached the wire is exactly as misleading as a number with no
# caveat. A kind:"correction" record is unaffected: `_reportable` is true by
# construction for it (see `_is_correction` above), so this branch -- and
# `_strip_value_family` -- is never reached on that path, and both keys
# still ride to --metadata via the unconditional forwarder further below.
_VALUE_OMIT_FAMILY = ('value_low', 'value_base', 'value_high', 'bounds_source',
                      'currency', 'estimated_value', 'assumptions', 'net_value',
                      'attribution_fraction', 'attribution_basis')


def _strip_value_family(rec):
    """Remove every value-bearing key from the transported record.

    Withholding --outcome-value/--outcome-currency alone does NOT withhold
    the value: the bounds and the assumptions object (whose
    estimated_hours_saved * assumed_loaded_rate product IS the estimate)
    ride into --metadata via their own forwarders. Deleting them from the
    blob means no current or future forwarder can reintroduce the leak.
    Provenance (evidence_class, evaluator, evaluator_version, model, the
    version family) and confidence are deliberately KEPT -- D-05 withholds
    the VALUE, not the fact that an estimate happened.
    """
    for _k in _VALUE_OMIT_FAMILY:
        rec.pop(_k, None)


_not_reportable_reason = ''
if not _reportable:
    # T-43-01: sanitize the TRANSPORTED RECORD, not the forwarder list.
    # Withholding --outcome-value/--outcome-currency alone does NOT
    # withhold the value: value_low/value_base/value_high/bounds_source and
    # assumptions (whose estimated_hours_saved * assumed_loaded_rate
    # product IS the estimate) already ride into --metadata via the
    # forwarders further below in the metadata heredoc. Deleting them here,
    # from the blob itself, means no current or future forwarder can
    # reintroduce the leak -- exactly the same omit family D-11 already
    # established on the classifier's abstention path (value_low,
    # value_base, value_high, bounds_source, currency, estimated_value,
    # assumptions), applied here by the other half of the pipeline.
    # confidence and every provenance field (evidence_class, evaluator,
    # evaluator_version, model, the four version fields) are deliberately
    # KEPT: D-05 withholds the VALUE, not the fact that an estimate
    # happened.
    _strip_value_family(found)
    _not_reportable_reason = 'not_reportable'

# An unrecognized reportability_status must never cross the wire -- only
# the two locked D-05 values are meaningful downstream, so a future or
# hand-edited status word is dropped rather than forwarded unexamined.
if found.get('reportability_status') not in _REPORTABILITY_STATUSES:
    found.pop('reportability_status', None)

# D-08: --outcome-value carries the LOW bound, not base -- understates
# rather than overstates. All three bounds still ride in --metadata via
# ASSESSMENT_JSON below, so the range stays recoverable. Read-side defense
# against a hand-edited or corrupt sidecar record, carried over intact from
# the marker reader (WR-02): a non-numeric value or an unsupported/
# malformed currency drops BOTH flags together, never one alone. Phase 43:
# ANDed with _reportable, stated explicitly rather than relying only on the
# sanitizer above having already emptied value_low -- the D-09 second-site
# comment elsewhere in this file names exactly this trap (a partial clear
# that relies on downstream/incidental behavior instead of stating intent
# locally).
_SUPPORTED_CURRENCIES = frozenset({'USD', 'EUR', 'GBP', 'CAD', 'AUD', 'JPY', 'CHF'})
_raw_value = found.get('value_low', '')
_raw_currency = found.get('currency', '')
_value_ok = False
try:
    float(_raw_value)
    _value_ok = True
except (TypeError, ValueError):
    _value_ok = False
_currency_ok = (
    isinstance(_raw_currency, str)
    and _raw_currency.strip().upper() in _SUPPORTED_CURRENCIES
)
if _reportable and _value_ok and _currency_ok:
    value_out = _s(_raw_value)
    currency_out = _s(_raw_currency, maxlen=32)
else:
    value_out = ''
    currency_out = ''

# Phase 43 (C-02, CF-2): the reporter's OWN independent evidence_class
# allow-list -- defense in depth immediately before the value is emitted,
# NOT a duplicate resolver (CF-3: hermes-report.sh holds no reportability
# policy of its own). This is the gate a hand-edited sidecar or a future
# rogue evaluator would otherwise reach the wire through entirely; C-02
# accepts the one duplication with classifier.py's own EVIDENCE_CLASSES for
# that reason. Declared and checked exactly ONCE in this file.
#
# NOT case-folded, unlike the currency allow-list just above: these are
# upper-snake constants compared for identity, not user-typed currency
# codes. A .strip().upper() here would quietly accept a lowercase spelling
# classifier.py would never produce -- exactly the drift this allow-list
# exists to catch, so this check deliberately diverges from the currency
# precedent rather than copying it blind.
#
# ABSENT vs INVALID: a kind:"correction" record carries no evidence_class
# key at all -- correct-assessment.sh has never written one (see its
# record literal). An absent field is NOT a rejection: there is nothing to
# forward, so there is nothing to refuse, and the record's value is
# governed by the reportability gate above, not this check. Only a field
# that IS PRESENT and outside the nine is a rejection. Getting this
# backwards would clear the value on every operator-filed correction and
# turn test_last_match_wins_ships_newest_correction_low_bound
# (tests/test_phase42_assessment_contract.py) red -- treat that as the
# signal this branch is inverted, never as a test to adjust.
_EVIDENCE_CLASSES = frozenset({
    'ACTIVITY_MEASURED', 'OUTPUT_OBSERVED', 'OUTCOME_OBSERVED',
    'MODEL_ESTIMATED_DEMO', 'CUSTOMER_CONFIGURED', 'CUSTOMER_CONFIRMED',
    'ASSOCIATIONAL', 'QUASI_EXPERIMENTAL_IMPACT', 'EXPERIMENTAL_IMPACT',
})

# Phase 53 (ROI-01, D-01): the reporter's own copy of the class gate --
# the SECOND enforcement point, deliberately independent of the classifier's.
# This is the gate a sidecar written by a pre-Phase-53 classifier, or a
# hand-edited one, would otherwise reach the wire through: the classifier
# refuses to WRITE reportable for these classes, and this refuses to SHIP a
# value for them regardless of what the record claims.
#
# ONE RULE, TWO ENFORCEMENT POINTS -- not two rules. Read that precisely:
# this set is a hand-written LITERAL, not a mechanical derivation. It cannot
# import classifier.py's _REPORTABLE_EVIDENCE_CLASSES -- that lives in the
# in-process plugin, on the far side of a language and process boundary this
# file can never cross. What makes the pair one rule is that both are written
# to the same definition (the declarable six minus the forced constant) and
# that a test fails the moment they disagree -- NOT that either is computed
# from the other. The guard is therefore STATIC-class: it catches drift that
# exists, it does not prevent drift by construction. The divergence guard in
# tests/test_phase53_reportable_class_gate.py fails if the two ever disagree,
# because a hand-synced pair that can drift silently is exactly the failure
# this file's own C-02 comment accepts a duplication in order to catch.
#
# The three causal-impact labels are absent here as well as from the
# classifier's set: they are already undeclarable
# (classifier._DECLARABLE_EVIDENCE_CLASSES refuses them even from a trusted
# registrant), so a record carrying one is malformed, and a malformed record
# must not ship a value either.
_REPORTABLE_EVIDENCE_CLASSES = frozenset({
    'ACTIVITY_MEASURED', 'OUTPUT_OBSERVED', 'OUTCOME_OBSERVED',
    'CUSTOMER_CONFIGURED', 'CUSTOMER_CONFIRMED',
})
# WR-02 (43-REVIEW.md): scope the absent-is-permissible exception to the
# record kind that actually earns it. Only a kind:"correction" record
# legitimately carries no evidence_class -- correct-assessment.sh has never
# written one. classifier.py populates it unconditionally on every
# job_assessment via _forced_evidence_class(), so an ABSENT field on a
# job_assessment is not a normal state: it is a hand-edited or truncated
# line, the same bypass CR-01 came in through. Treating absence as
# permissible for every kind let exactly that record sail through with no
# rejection at all.
_raw_evidence_class = found.get('evidence_class', None)
_evidence_class_missing = _raw_evidence_class is None
if _evidence_class_missing and not _is_correction:
    # A job_assessment with no evidence_class is refused like an invalid
    # one: there is no provenance to forward and no basis to ship a value.
    _reject_evidence_class = True
elif _evidence_class_missing:
    _reject_evidence_class = False
else:
    _reject_evidence_class = (
        not isinstance(_raw_evidence_class, str)
        or _raw_evidence_class not in _EVIDENCE_CLASSES
    )
if _reject_evidence_class:
    # Reject: remove the key from the resolved record before ASSESSMENT_JSON
    # is dumped below -- the --metadata heredoc's existing conditional-emit
    # rule already adds no key for a field absent from the record, so one
    # declaration and one check here is sufficient; no second copy of the
    # nine labels lives in the metadata heredoc. Clear both value scalars
    # together, never one alone -- the same trap this file's own D-09
    # second-site comment (further below) already documents.
    found.pop('evidence_class', None)
    value_out = ''
    currency_out = ''
    # CR-01: strip the value family here too. Clearing the two CLI scalars
    # is not enough -- the bounds and assumptions have their own --metadata
    # forwarders, so a rejected record would otherwise ship the estimate it
    # was just refused.
    _strip_value_family(found)
    if not _not_reportable_reason:
        _not_reportable_reason = 'evidence_class_unrecognized'
elif not _evidence_class_missing and (
        _raw_evidence_class not in _REPORTABLE_EVIDENCE_CLASSES):
    # Phase 53 (ROI-01, D-01): a RECOGNIZED class that may not carry a value
    # onto the wire -- MODEL_ESTIMATED_DEMO in practice. Distinct from the
    # rejection branch above in one load-bearing way: `evidence_class` is
    # KEPT on the record, not popped.
    #
    # `not _evidence_class_missing` is LOAD-BEARING and was missing from this
    # branch's first draft, which broke corrections. A kind:"correction"
    # record legitimately carries NO evidence_class -- correct-assessment.sh
    # has never written one -- and is reportable BY CONSTRUCTION under D-06.
    # Without this guard, `None not in _REPORTABLE_EVIDENCE_CLASSES` is True,
    # so every correction had its value stripped. Caught by
    # test_correction_ships_even_when_the_reportability_gate_is_closed and
    # test_absent_evidence_class_is_not_a_rejection, which exist for exactly
    # this trap. Absence is handled by the WR-02 branch above, not here.
    #
    # That asymmetry is Phase 43's rule, not an inconsistency. An
    # unrecognized class is evidence of a malformed or tampered record, so
    # the claim itself is removed. A model-estimated class is a perfectly
    # honest claim that simply may not carry a value to a read surface that
    # cannot display its provenance -- and withholding the VALUE must not
    # withhold the FACT that an estimate happened. The record still ships
    # evidence_class, evaluator, confidence and the whole provenance family;
    # only the value is withheld.
    value_out = ''
    currency_out = ''
    _strip_value_family(found)
    if not _not_reportable_reason:
        _not_reportable_reason = 'evidence_class_not_reportable'

# Phase 42 (C-04): the whole resolved sidecar record rides as ONE JSON
# blob -- replacing the eight separate KEY=value prints the marker reader
# used. Fields holding lists/dicts (evidence_references, correction_history,
# added by later plans) cannot be represented as scalar env lines at all
# under the old transport; a single JSON variable removes that ceiling.
# VALUE/CURRENCY still ride as their own scalar lines because
# outcome_cmd+=(--outcome-value ...) below runs BEFORE the metadata heredoc
# that parses ASSESSMENT_JSON.
# Phase 43: print the not_reportable REASON exactly once, only when it
# exists -- the shell captures REASON with a `sed` filter (see
# outcome_reason= below) that would concatenate two matching lines. The
# earlier REASON prints in this same heredoc (sidecar_unavailable,
# schema_unrecognized, ...) all `raise SystemExit(0)` before reaching here,
# so at most one REASON line is ever emitted per run.
if _not_reportable_reason:
    print(f"REASON={_not_reportable_reason}")
print(f"VALUE={value_out}")
print(f"CURRENCY={currency_out}")
print(f"ASSESSMENT_JSON={json.dumps(found, separators=(',', ':'))}")
PY
        )
        outcome_value=$(printf '%s\n' "${_assessment_kv}" | sed -n 's/^VALUE=//p')
        outcome_currency=$(printf '%s\n' "${_assessment_kv}" | sed -n 's/^CURRENCY=//p')
        outcome_assessment_json=$(printf '%s\n' "${_assessment_kv}" | sed -n 's/^ASSESSMENT_JSON=//p')
        outcome_reason=$(printf '%s\n' "${_assessment_kv}" | sed -n 's/^REASON=//p')

        # D-09 second site (Phase 42 Plan 04): re-validate the three bounds
        # INDEPENDENTLY of anything the classifier did, immediately before
        # the value flags are constructed below -- the check standing
        # between a hand-edited or corrupt sidecar line and a dollar figure
        # on a customer's bill (same shape and reasoning as C-02's
        # evidence_class allow-list, and the currency allow-list already
        # above in this same reader). On failure, clear BOTH value scalars
        # together, never one -- the emission gate below already refuses to
        # send one flag without the other, and a partial clear would rely
        # on that downstream rule instead of stating the intent here. The
        # outcome arc itself is still reported; only the value is withheld.
        if [[ -n "${outcome_value}" && -n "${outcome_currency}" ]]; then
          local _bounds_ok
          _bounds_ok=$(
            ASSESSMENT_JSON="${outcome_assessment_json}" \
            python3 -c "
import json, math, os
raw = os.environ.get('ASSESSMENT_JSON', '').strip()
try:
    rec = json.loads(raw) if raw else {}
except (ValueError, TypeError):
    rec = {}
if not isinstance(rec, dict):
    rec = {}


def _finite(v):
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


low = _finite(rec.get('value_low'))
base = _finite(rec.get('value_base'))
high = _finite(rec.get('value_high'))
ok = (
    low is not None and base is not None and high is not None
    and low >= 0 and base >= 0 and high >= 0
    and low <= base <= high
)
print('true' if ok else 'false')
" 2>/dev/null || echo "false"
          )
          if [[ "${_bounds_ok}" != "true" ]]; then
            outcome_value=""
            outcome_currency=""
            outcome_reason="bounds_invalid"
          fi
        fi

        # Phase 39 D-02 pattern, reused (Plan 42-04): one warn per
        # (outcome_id, reason), gated through the SAME OUTCOME_WARN_FLAGS_DIR
        # sentinel the deferred/wedged block above uses -- not a fifth
        # sentinel directory. The key is computed ONCE into a single local
        # shared by both the existence test and the touch, for the identical
        # reason the deferred/wedged block's own comment gives: two copies of
        # the sanitizing expression drift, and when they do the check tests
        # one path while the touch creates another and the gate never
        # matches. Nothing per-tick (age, timestamp, counter) may enter the
        # key -- outcome_id is stable per job across ticks, and a per-tick
        # key reproduces the unknown-<epoch> defeat this repo already paid
        # for once. Tolerate a failed flag creation without aborting: this
        # script runs without -e and a read-only state directory must
        # degrade to a noisier log, never crash the reporter.
        if [[ -n "${outcome_reason}" ]]; then
          outcome_warn_key="${outcome_id//[^A-Za-z0-9_:.-]/_}__${outcome_reason}.flag"
          outcome_warn_flag="${OUTCOME_WARN_FLAGS_DIR}/${outcome_warn_key}"
          if [[ ! -e "${outcome_warn_flag}" ]]; then
            mkdir -p "${OUTCOME_WARN_FLAGS_DIR}" 2>/dev/null && touch "${outcome_warn_flag}" 2>/dev/null
            case "${outcome_reason}" in
              schema_unrecognized)
                warn "assessment schema unrecognized, reporting status-only: id=${outcome_id}"
                ;;
              sidecar_unavailable)
                warn "assessment sidecar unavailable, reporting status-only: id=${outcome_id}"
                ;;
              sidecar_missing_for_valued_marker)
                warn "assessment sidecar missing for a marker carrying assessment (rolling-upgrade window), reporting status-only: id=${outcome_id}"
                ;;
              bounds_invalid)
                warn "assessment bounds reversed, negative, or non-finite at the second site, reporting status-only: id=${outcome_id}"
                ;;
              not_reportable)
                warn "assessment not reportable per EGV-18 gate, reporting status-only: id=${outcome_id}"
                ;;
              evidence_class_unrecognized)
                warn "assessment evidence_class unrecognized, reporting status-only: id=${outcome_id}"
                ;;
              *)
                warn "assessment unvalued (${outcome_reason}), reporting status-only: id=${outcome_id}"
                ;;
            esac
          fi
        fi
      fi

      # D-06: API first — build command as array (bash 3.2 portability).
      local outcome_cmd=(
        revenium jobs outcome "${outcome_id}"
        --result "${outcome_status}"
        --quiet
      )
      # quick-260605: pass teamId explicitly when resolved (omitted in tests).
      if [[ -n "${REVENIUM_TEAM_ID_RESOLVED}" ]]; then
        outcome_cmd+=(--team-id "${REVENIUM_TEAM_ID_RESOLVED}")
      fi
      # --result is the execution result; --outcome-type is the separate business
      # outcome. A SUCCESS arc maps to a CONVERTED business outcome so Revenium does
      # not leave the job's Outcome Type at its PENDING default. FAILED / CANCELLED
      # carry no --outcome-type (Revenium default applies).
      if [[ "${outcome_status}" == "SUCCESS" ]]; then
        outcome_cmd+=(--outcome-type CONVERTED)
      fi
      # Phase 38 (ROI-10): a resolved assessment ships as the two value flags,
      # never as --outcome-type — a SUCCESS arc already sends CONVERTED above,
      # and changing that mapping is out of scope for this plan (would move a
      # golden). Both flags are added together or not at all (outcome_value is
      # only ever set alongside outcome_currency by the resolver above).
      # CR-01: gated on OUTCOME_VALUE_CLI_CAPABLE -- an older CLI predating
      # these two flags must still receive the rest of the `jobs outcome`
      # call (fail OPEN), not have the whole call rejected.
      if [[ "${OUTCOME_VALUE_CLI_CAPABLE}" == "true" \
            && -n "${outcome_value}" && -n "${outcome_currency}" ]]; then
        outcome_cmd+=(--outcome-value "${outcome_value}")
        outcome_cmd+=(--outcome-currency "${outcome_currency}")
      fi
      # Phase 24 (quick-260531-n4i): attach --metadata JSON. source (deployment
      # environment from the session source column) rides on every outcome when
      # present; failure_reason is added only for FAILED arcs. json.dumps handles
      # quoting/escaping so prose reasons cannot break the JSON arg. Omit the flag
      # entirely when there is nothing to send (preserves v1.4 wire shape for
      # source-less sessions).
      # Phase 42 (C-04): provenance for a resolved assessment rides beside
      # source/failure_reason in this SAME metadata object, so the estimate's
      # nature is unmistakable next to its value flags. Parsed ONCE from the
      # single ASSESSMENT_JSON blob printed by the sidecar re-read above,
      # replacing the eight separate OUTCOME_* env vars the marker-sourced
      # transport used — a field holding a list/dict (evidence_references,
      # correction_history, added by later plans) could never ride the old
      # scalar-per-field transport at all.
      outcome_metadata=$(
        OUTCOME_SOURCE="${outcome_source}" \
        OUTCOME_STATUS="${outcome_status}" \
        OUTCOME_FAILURE_REASON="${outcome_failure_reason}" \
        ASSESSMENT_JSON="${outcome_assessment_json}" \
        python3 - <<'PY' 2>/dev/null || true
import json, os

# Phase 46 (EGV-19, D-01/D-03/D-11): the --metadata envelope's own byte
# ceiling, enforced HERE and only here -- this is the single emit site
# where the actual wire bytes exist before they leave the machine (D-03).
# The classifier must never predict this number; grep -c on that file for
# this name is a phase-46 acceptance criterion. Derivation, not a guess:
#   - pre-fix measured worst case (before this same plan's classifier.py
#     failure_reason byte-clamp fix) was 6,976 bytes for a 500-EMOJI
#     failure_reason alone, 7,734 bytes with a 64-emoji `source` on top --
#     both driven by a character-count clamp under-counting by up to 12x
#     under ensure_ascii=True, not by anything Phases 42-45 added.
#   - the ASCII baseline for the WHOLE Phase 42-45 field set (every
#     provenance + value + cost key this heredoc can emit) measured 956
#     bytes -- comfortably under any reasonable ceiling once the clamp
#     driving the worst case is fixed.
#   - there is NO observed Revenium server-side --metadata limit to derive
#     a ceiling from, so 4096 is chosen defensively, not measured against a
#     documented server bound.
# Two alternatives considered and rejected:
#   - 8192: collides numerically with SIDECAR_LINE_MAX_BYTES
#     (classifier.py) and would invite exactly the sidecar-vs-envelope
#     conflation this phase must not make -- these are two different
#     ceilings for two different transports.
#   - a config-tunable value: rejected per D-11 -- D-09 deliberately froze
#     the llmOutcomeEvaluation opt-in surface at five knobs, and a sixth
#     would widen that surface for a transport bound, not a policy choice.
#
# CF-3 restated (D-03): this is a TRANSPORT bound, not a value or
# reportability judgment. The reporter still only READS reportability_status
# upstream (see the reader stage above) -- this decides only what physically
# fits on the wire, and it must live here because nowhere else in the
# pipeline has the serialized bytes to measure.
_METADATA_CEILING_BYTES = 4096

# The two ordered drop tiers, in the order they are popped below: the
# enrichment yields before base metering ever does (D-02). `source` and
# `failure_reason` are the base metering keys and are never in either tuple.
_VALUE_FAMILY_META_KEYS = (
    'value_low', 'value_base', 'value_high', 'bounds_source',
    'net_value', 'assumptions', 'supplied_costs', 'cost_coverage',
    # Phase 51 (D-07): the attribution pair joins the VALUE tier, not the
    # provenance tier, and the tier ordering is the whole reason. Tier 1
    # sheds value and tier 2 sheds provenance, so provenance OUTLIVES value.
    # In provenance these would survive the value they document, leaving a
    # fraction attributing nothing. In the value family they shed TOGETHER,
    # which is what D-07 actually requires: the failure to prevent is a
    # surviving value whose attribution has vanished.
    'attribution_fraction', 'attribution_basis',
)
_PROVENANCE_FAMILY_META_KEYS = (
    'evaluator', 'evaluator_version', 'model', 'evidence_class',
    'reportability_status', 'study_id', 'study_version', 'confidence',
    'economic_mechanism', 'double_counting_group', 'correction_sequence',
    # Phase 46 (EGV-21, D-06/D-07, plan 46-02 Task 4, checkpoint decision
    # ship-both): the two locality facts join the provenance tier, not the
    # value tier and not the always-kept set -- they describe WHERE the
    # evaluation was configured to run, the same footing as evaluator/model
    # above, so a truncated record still says where inference was
    # configured to go for as long as any provenance survives, and only
    # yields alongside the rest of provenance at tier 2.
    'inference_provider', 'inference_address_class',
    # Phase 50 (DECL-05, D-04): names WHICH boundary's declaration decided
    # evidence_class above -- provenance tier, not the value tier, per D-04:
    # it describes WHO decided, the same footing as evaluator/model, not a
    # monetary value.
    'evidence_class_authority',
)

meta = {}
source = os.environ.get('OUTCOME_SOURCE', '').strip()
if source:
    meta['source'] = source
status = os.environ.get('OUTCOME_STATUS', '').strip().upper()
reason = os.environ.get('OUTCOME_FAILURE_REASON', '').strip()
if status == 'FAILED' and reason:
    meta['failure_reason'] = reason

# Phase 42 (C-04): the sidecar's resolved assessment record, parsed once
# from ASSESSMENT_JSON. Present whenever the sidecar re-read above found
# one. NOT SUCCESS-only since Phase 44 Plan 03: that gate was widened from
# `outcome_status == "SUCCESS"` to `-n "${outcome_sid}"` precisely so a
# FAILED/CANCELLED job's non-evaluated abstention record (which carries
# costs and coverage and omits the whole value family) reaches this block
# too. Every consumer below is status-agnostic by construction, so no
# status test belongs here — an empty/malformed blob degrades to an empty
# contribution here, never crashes the heredoc (2>/dev/null || true above
# is the outer belt; the try/except is the inner suspenders). Conditional-
# emit rule preserved: a field absent from the record adds no key to meta.
assessment_raw = os.environ.get('ASSESSMENT_JSON', '').strip()
if assessment_raw:
    try:
        record = json.loads(assessment_raw)
    except (json.JSONDecodeError, ValueError):
        record = None
    if isinstance(record, dict):
        # Phase 42 (D-08/D-09/EGV-07, Plan 04): the full bound family plus
        # its source and the schema version that produced it -- so the
        # range is recoverable from what was actually reported, whether or
        # not the D-09 second site accepted it for --outcome-value above.
        # Same conditional-emit rule as every other field here: a field
        # absent from the record adds no key to meta.
        for _bound_key in ('value_low', 'value_base', 'value_high'):
            _bound_raw = record.get(_bound_key)
            if _bound_raw is not None:
                try:
                    meta[_bound_key] = float(_bound_raw)
                except (TypeError, ValueError):
                    pass
        bounds_source = record.get('bounds_source')
        if isinstance(bounds_source, str) and bounds_source:
            meta['bounds_source'] = bounds_source[:16]
        schema_version = record.get('assessment_schema_version')
        if isinstance(schema_version, (int, float)) and not isinstance(schema_version, bool):
            meta['assessment_schema_version'] = schema_version
        # EGV-07 (Phase 42 Plan 05): the sibling provenance-version fields
        # the requirement names alongside the schema version -- taxonomy,
        # prompt, and policy versions must survive a deferred create and a
        # retry exactly like assessment_schema_version already does. Same
        # conditional-emit rule: absent from the record, absent from meta.
        taxonomy_version = record.get('taxonomy_version')
        if isinstance(taxonomy_version, (int, float)) and not isinstance(taxonomy_version, bool):
            meta['taxonomy_version'] = taxonomy_version
        prompt_version = record.get('prompt_version')
        if isinstance(prompt_version, (int, float)) and not isinstance(prompt_version, bool):
            meta['prompt_version'] = prompt_version
        policy_version = record.get('policy_version')
        if isinstance(policy_version, (int, float)) and not isinstance(policy_version, bool):
            meta['policy_version'] = policy_version
        evidence_class = record.get('evidence_class')
        if isinstance(evidence_class, str) and evidence_class:
            meta['evidence_class'] = evidence_class[:32]
        # Phase 50 (DECL-05, D-04): forwards WHICH boundary's declaration
        # decided evidence_class immediately above -- an auditor otherwise
        # cannot tell "a declaration won" from "which one." Unlike
        # evidence_class's own forwarder (whose single allow-list check
        # already ran upstream in classifier.py's precedence walk, so this
        # forwarder simply trusts the already-sanitized record), an
        # out-of-set evidence_class_authority here would be a CORRECTNESS
        # bug, not a cosmetic one -- it would misname the authority that
        # decided a billing-adjacent record -- so this allow-list check
        # lives AT THE FORWARDER, mirroring economic_mechanism's own
        # allow-list-then-drop shape below rather than evidence_class's
        # trust-the-record shape. Hand-synced against classifier.py's
        # _EVIDENCE_CLASS_AUTHORITIES; this heredoc is its own independent
        # python3 process (a separate subshell, never a shared Python
        # namespace), so the vocabulary is declared fresh here, the same
        # reasoning _ECONOMIC_MECHANISMS below already documents for
        # itself. FOUR words, not three: the Task 1 checkpoint decision
        # (50-01-SUMMARY.md, "option-b") widened the classifier's walk to
        # include the classification boundary, and this set must name every
        # authority the walk can return. Clamped to 16 bytes -- the longest
        # member, 'classification', is 14 bytes, comfortably under the
        # clamp but close enough that a fifth authority word must re-check
        # it, not assume headroom.
        _EVIDENCE_CLASS_AUTHORITIES = frozenset({
            'evidence', 'valuation', 'classification', 'evaluator',
        })
        evidence_class_authority = record.get('evidence_class_authority')
        if (
            isinstance(evidence_class_authority, str)
            and evidence_class_authority in _EVIDENCE_CLASS_AUTHORITIES
        ):
            meta['evidence_class_authority'] = evidence_class_authority[:16]
        # Phase 43 (EGV-18, T-43-04): forwards the reportability decision
        # itself, not just its effect -- without this, a row withheld by
        # the gate above is indistinguishable on the tenant from a row
        # dropped for bounds or schema reasons. Same conditional-emit rule:
        # absent from the record (or already stripped/dropped by the gate
        # above for an unrecognized value) adds no key to meta. 16 bytes is
        # ample for both locked D-05 words ("reportable"/"candidate").
        reportability_status = record.get('reportability_status')
        if isinstance(reportability_status, str) and reportability_status:
            meta['reportability_status'] = reportability_status[:16]
        # Phase 44 (EGV-05, D-01/D-03, T-44-02): the economic-mechanism
        # forwarder block this plan opens. Plans 44-02 (net_value,
        # supplied_costs, cost_coverage) and 44-03 (double_counting_group)
        # append to this SAME contiguous block, in that order, immediately
        # below -- meter-completion-assessment.golden.json pins --metadata's
        # key order with an anchored pattern, so appending here keeps every
        # plan's re-pin a pure insertion instead of three competing
        # reorderings.
        #
        # Unlike evidence_class above (whose single allow-list check lives
        # upstream in the sidecar re-read stage, and whose forwarder simply
        # trusts the already-sanitized record), T-44-02's mitigation puts
        # this allow-list AT THE FORWARDER: an out-of-set economic_mechanism
        # drops silently from --metadata (no key added at all), while the
        # rest of the record -- value, currency, every other provenance
        # field -- still ships normally. That is a deliberately different
        # shape from evidence_class's whole-record rejection, so it cannot
        # reuse that stage's check. This heredoc is its own independent
        # python3 process (a separate subshell from the sidecar re-read
        # heredoc above, connected only through shell variables, never
        # through a shared Python namespace), so the six-string vocabulary
        # is declared fresh here rather than "shared" from that heredoc --
        # there is no runtime mechanism by which it could be. Hand-synced
        # against classifier.py's ECONOMIC_MECHANISMS; the drift test in
        # tests/test_phase44_economic_mechanisms.py::MechanismDriftTests is
        # what holds the two declarations equal, and its own extractor
        # requires this exact anchor to appear exactly once in this file --
        # so this is the ONLY declaration of _ECONOMIC_MECHANISMS in
        # hermes-report.sh.
        _ECONOMIC_MECHANISMS = frozenset({
            'labor_substitution', 'augmentation_capacity_expansion',
            'newly_enabled_work', 'quality_decision_improvement',
            'risk_avoidance', 'incremental_revenue',
        })

        # Phase 44 (EGV-14/EGV-15, D-05/D-06, T-44-09): the same four cost
        # categories classifier.py declares as COST_CATEGORIES, hand-synced
        # exactly like _ECONOMIC_MECHANISMS immediately above -- a TUPLE,
        # not a frozenset, because emission order is part of the contract
        # (EGV-14's ordering probe edge) and
        # tests/test_phase44_economic_mechanisms.py::CostCategoryDriftTests
        # compares the two as an ORDERED sequence, not a set (unlike
        # MechanismDriftTests' set comparison). This is the ONLY
        # declaration of _COST_CATEGORIES in hermes-report.sh.
        _COST_CATEGORIES = (
            'human_review', 'rework_or_error', 'handoff', 'training_or_change',
        )
        economic_mechanism = record.get('economic_mechanism')
        if (
            isinstance(economic_mechanism, str)
            and economic_mechanism in _ECONOMIC_MECHANISMS
        ):
            meta['economic_mechanism'] = economic_mechanism[:64]

        # Phase 44 (EGV-14/EGV-15, D-06/D-07/D-08): APPENDED to the same
        # contiguous Phase 44 forwarder block plan 44-01 opened above, in
        # the fixed order net_value / supplied_costs / cost_coverage --
        # order and placement are contract, not style:
        # meter-completion-assessment.golden.json's anchored pattern pins
        # --metadata's key order, so appending here keeps this plan's
        # re-pin a pure insertion.
        #
        # net_value survives to this point ONLY when the record was
        # reportable -- D-07 strips it from `record` through the single
        # shared _strip_value_family(), never a second per-forwarder gate.
        net_value_raw = record.get('net_value')
        if net_value_raw is not None:
            try:
                meta['net_value'] = float(net_value_raw)
            except (TypeError, ValueError):
                pass

        # supplied_costs and cost_coverage are OPERATOR input, not model
        # output, and are deliberately NEVER in _VALUE_OMIT_FAMILY (D-07's
        # second half) -- they ship regardless of reportability, because
        # withholding them is what would make a null ROI unreadable.
        # T-44-09: an allow-list rebuild against _COST_CATEGORIES, key by
        # key, so a hand-edited sidecar cannot smuggle an unknown key or a
        # non-numeric value onto the wire; a value that fails float() is
        # dropped rather than crashing this heredoc.
        supplied_costs_raw = record.get('supplied_costs')
        if isinstance(supplied_costs_raw, dict):
            _rebuilt_costs = {}
            for _category in _COST_CATEGORIES:
                if _category not in supplied_costs_raw:
                    continue
                try:
                    _rebuilt_costs[_category] = float(supplied_costs_raw[_category])
                except (TypeError, ValueError):
                    continue
            if _rebuilt_costs:
                meta['supplied_costs'] = _rebuilt_costs

        cost_coverage_raw = record.get('cost_coverage')
        if isinstance(cost_coverage_raw, dict):
            _COST_COVERAGE_EXCLUDED_AI = 'metered_ai_cost'
            _rebuilt_coverage = {}
            for _list_key in ('included', 'known_zero', 'unknown'):
                _raw_list = cost_coverage_raw.get(_list_key)
                if isinstance(_raw_list, list):
                    _filtered = [v for v in _raw_list if v in _COST_CATEGORIES]
                    if _filtered:
                        _rebuilt_coverage[_list_key] = _filtered
            _raw_excluded = cost_coverage_raw.get('excluded')
            if isinstance(_raw_excluded, list):
                _filtered_excluded = [
                    v for v in _raw_excluded if v == _COST_COVERAGE_EXCLUDED_AI
                ]
                if _filtered_excluded:
                    _rebuilt_coverage['excluded'] = _filtered_excluded
            if _rebuilt_coverage:
                meta['cost_coverage'] = _rebuilt_coverage

        # Phase 44 (EGV-16, D-12/D-13, T-44-12): APPENDED to the END of the
        # contiguous Phase 44 forwarder block plans 44-01/44-02 built above
        # -- this closes the block; no later field in this phase follows
        # it. double_counting_group is caller-supplied structural identity
        # (a Hermes session id), never a monetary claim, so it is not in
        # _VALUE_OMIT_FAMILY and ships regardless of reportability_status,
        # exactly like supplied_costs/cost_coverage above. No allow-list
        # applies here -- unlike economic_mechanism's fixed six-value set,
        # this is a free-form identifier -- so this forwarder relies on the
        # isinstance/non-empty check plus the 64-byte slice, plus the
        # existing _s() transport sanitiser downstream.
        double_counting_group = record.get('double_counting_group')
        if isinstance(double_counting_group, str) and double_counting_group:
            meta['double_counting_group'] = double_counting_group[:64]
        # Phase 43 (D-06, T-43-17): a correction stays reportable by
        # construction -- the reader's carve-out above never consults the
        # reportability gate for it -- but Finding 4 / C-06 established that
        # `jobs roi` surfaces the corrected value indistinguishably from an
        # original. `jobs roi` will not surface this marker either, but with
        # it the distinguishing signal exists in data Revenium HOLDS rather
        # than only in the local sidecar, which is the compensating control
        # C-06 asked this phase for. Emitted ONLY when the resolved record's
        # kind is a correction -- same conditional-emit rule as every other
        # field here: a key absent from the record adds no key to meta, and
        # an ORIGINAL assessment must never carry a marker saying it is not
        # one. `sequence` guarded by the same non-bool numeric check the
        # version fields above already use.
        if record.get('kind') == 'correction':
            meta['corrected'] = True
            sequence_raw = record.get('sequence')
            if isinstance(sequence_raw, (int, float)) and not isinstance(sequence_raw, bool):
                meta['correction_sequence'] = int(sequence_raw)
        evaluator = record.get('evaluator')
        if isinstance(evaluator, str) and evaluator:
            meta['evaluator'] = evaluator[:64]
        evaluator_version = record.get('evaluator_version')
        if isinstance(evaluator_version, str) and evaluator_version:
            meta['evaluator_version'] = evaluator_version[:16]
        # EGV-07: the fifth named provenance field -- which MODEL produced
        # the assessment (Phase 45/EGV-08 owns real semantics; today's
        # value is PROVENANCE_MODEL_UNKNOWN, but the field still crosses
        # the wire so a later phase's real value survives the same path
        # without another edit here).
        model_field = record.get('model')
        if isinstance(model_field, str) and model_field:
            meta['model'] = model_field[:64]
        # Phase 46 (EGV-21, D-06/D-07, plan 46-02 Task 4, checkpoint
        # decision ship-both): the two locality facts, immediately after
        # model above -- same caller-supplied-provenance footing, forwarded
        # under two different disciplines. inference_provider mirrors
        # evaluator's isinstance + non-empty + slice shape (32 bytes,
        # matching classifier.py's INFERENCE_PROVIDER_MAX_BYTES). A hand-
        # edited or corrupt sidecar value that is a non-empty non-string
        # (or simply absent) adds no key -- same conditional-emit rule as
        # every other field here.
        inference_provider = record.get('inference_provider')
        if isinstance(inference_provider, str) and inference_provider:
            meta['inference_provider'] = inference_provider[:32]
        # inference_address_class uses an allow-list-then-drop discipline,
        # exactly like _ECONOMIC_MECHANISMS above (T-46-02): an out-of-set
        # string, an empty string, a non-string, or a hand-edited/corrupt
        # sidecar value is DROPPED SILENTLY -- never passed through. Unlike
        # _ECONOMIC_MECHANISMS' six-string vocabulary, this frozenset is not
        # hand-synced against classifier.py by a drift test -- it mirrors
        # classifier.py's own _ADDRESS_CLASSES literally (D-12: exactly
        # four values, no fifth "unknown" bucket).
        _INFERENCE_ADDRESS_CLASSES = frozenset({'loopback', 'private', 'public', 'unset'})
        inference_address_class = record.get('inference_address_class')
        if (
            isinstance(inference_address_class, str)
            and inference_address_class in _INFERENCE_ADDRESS_CLASSES
        ):
            meta['inference_address_class'] = inference_address_class
        confidence_raw = record.get('confidence')
        if confidence_raw is not None:
            try:
                meta['confidence'] = float(confidence_raw)
            except (TypeError, ValueError):
                pass
        assumptions_raw = record.get('assumptions')
        assumptions = {}
        if isinstance(assumptions_raw, dict):
            hours_raw = assumptions_raw.get('estimated_hours_saved')
            if hours_raw is not None:
                try:
                    assumptions['estimated_hours_saved'] = float(hours_raw)
                except (TypeError, ValueError):
                    pass
            rate_raw = assumptions_raw.get('assumed_loaded_rate')
            if rate_raw is not None:
                try:
                    assumptions['assumed_loaded_rate'] = float(rate_raw)
                except (TypeError, ValueError):
                    pass
        if assumptions:
            meta['assumptions'] = assumptions

        # Phase 51 (D-05/D-07): the attribution pair, forwarded from a
        # correction record. APPENDED last --
        # meter-completion-assessment.golden.json's anchored pattern pins
        # --metadata's key order, so a new key goes at the end or every
        # existing golden shifts.
        #
        # Forwarded, never derived. The operator supplied an already
        # attributed value; nothing here multiplies, and no gross figure
        # exists in this record to multiply. The fraction is an operator
        # ASSERTION validated only for shape -- a real, finite number in
        # [0, 1] -- because there is nothing here to check it against.
        # attribution_basis is what makes it auditable, which is why
        # correct-assessment.sh refuses a fraction without one; the basis is
        # therefore only forwarded alongside a valid fraction, never alone.
        attribution_fraction = record.get('attribution_fraction')
        if (
            isinstance(attribution_fraction, (int, float))
            and not isinstance(attribution_fraction, bool)
        ):
            try:
                _af = float(attribution_fraction)
            except OverflowError:
                _af = None
            if (
                _af is not None
                and _af == _af
                and _af not in (float('inf'), float('-inf'))
                and 0.0 <= _af <= 1.0
            ):
                # Greptile (PR #110): the PAIR is validated together, never
                # the fraction alone. correct-assessment.sh refuses a
                # fraction without a basis, but the reporter reads whatever
                # is on disk -- a legacy, hand-edited, or partially-written
                # sidecar can carry a valid fraction with no basis, and
                # shipping it would put a naked number on the wire, defeating
                # the one constraint the whole design rests on. A fraction
                # whose basis is missing is not forwarded at all: an absent
                # attribution is honest, a naked one is not.
                attribution_basis = record.get('attribution_basis')
                if isinstance(attribution_basis, str) and attribution_basis.strip():
                    meta['attribution_fraction'] = _af
                    meta['attribution_basis'] = attribution_basis[:500]

# Phase 46 (EGV-19, D-01/D-02/D-03): bounded emit -- the single place the
# actual wire bytes are measured before the payload leaves the machine.
# Base metering (source, failure_reason) is NEVER popped; only the Phase
# 42-45 enrichment yields, value family first, then provenance, in that
# order (D-02: metering never breaks, the enrichment is what gives way).
# metadata_truncated marks a partial payload so a consumer can distinguish
# "this job had no net_value" (both keys absent) from "net_value did not
# fit" (net_value absent, metadata_truncated present) -- an unmarked
# partial record is the silent substitution this milestone exists to
# prevent. AMEND-D-02: this key lives ONLY in this transport dict -- never
# in the sidecar record and never in _VALUE_OMIT_FAMILY, which governs an
# earlier pipeline stage that can never see it.
#
# CR-01 (46-REVIEW.md): the marker must be set ONLY when a tier actually
# removed a key. Before source (above) was clamped, an over-ceiling blob
# with no value-family/provenance-family keys present (e.g. driven entirely
# by an outsized source) still walked into this branch, popped nothing from
# either tier, and got `metadata_truncated: True` unconditionally -- a false
# "value did not fit" signal on a record that dropped nothing. Compare
# `meta`'s key set before/after each pop loop and only flip the marker when
# it actually shrank; a `set(meta)` snapshot is cheap here (single digits of
# keys) and reads as the intent directly, unlike diffing pop() return values.
if meta:
    blob = json.dumps(meta, separators=(',', ':')).encode('utf-8')
    if len(blob) > _METADATA_CEILING_BYTES:
        _before_tier1 = set(meta)
        for _k in _VALUE_FAMILY_META_KEYS:
            meta.pop(_k, None)
        if set(meta) != _before_tier1:
            meta['metadata_truncated'] = True
        blob = json.dumps(meta, separators=(',', ':')).encode('utf-8')
        if len(blob) > _METADATA_CEILING_BYTES:
            _before_tier2 = set(meta)
            for _k in _PROVENANCE_FAMILY_META_KEYS:
                meta.pop(_k, None)
            if set(meta) != _before_tier2:
                meta['metadata_truncated'] = True
            blob = json.dumps(meta, separators=(',', ':')).encode('utf-8')
    print(blob.decode('utf-8'))
PY
      )
      outcome_metadata="${outcome_metadata%%$'\n'*}"
      if [[ -n "${outcome_metadata}" ]]; then
        outcome_cmd+=(--metadata "${outcome_metadata}")
      fi
      outcome_cmd_output=$("${outcome_cmd[@]}" 2>&1) && outcome_cmd_exit=0 || outcome_cmd_exit=$?

      # OUTCOME-03: 409 is success-equivalent (mirrors jobs create pattern).
      outcome_success=false
      if [[ "${outcome_cmd_exit}" -eq 0 ]]; then
        outcome_success=true
      elif echo "${outcome_cmd_output}" | grep -qi "409\|already.exist\|conflict"; then
        outcome_success=true
      fi

      if [[ "${outcome_success}" == "true" ]]; then
        # D-06: ledger write is the last statement of the success branch (OUTCOME-02).
        # A crash between API call and ledger write re-attempts on next tick; the API
        # absorbs the repeat as a 409 which OUTCOME-03 treats as success-equivalent.
        outcome_now_ts=$(python3 -c "import time; print(f'{time.time():.3f}')" \
          2>/dev/null || date +%s)
        echo "JOB:${outcome_id}:outcome:${outcome_now_ts}:${outcome_status}" \
          >> "${JOBS_LEDGER_FILE}"
        info "Outcome reported: agentic_job_id=${outcome_id} result=${outcome_status}"
      else
        warn "outcome failed: id=${outcome_id} exit=${outcome_cmd_exit} — retries next tick"
      fi
    done
  fi

  # Phase 39 D-02: one aggregate line per tick when the deferred/wedged
  # job-outcome backlog is non-zero; silent when zero. Per-job detail is
  # gated to once-per-(outcome_id, reason) above (OUTCOME_WARN_FLAGS_DIR) --
  # this line is what keeps the backlog-size signal alive despite that
  # gate, rather than trading the per-tick spam for total silence: without
  # it a growing wedged backlog becomes invisible, the same reason
  # fallback_tick_count exists for the trace-type fallback below.
  if [[ "${outcome_deferred_tick_count}" -gt 0 ]]; then
    info "outcome backlog: ${outcome_deferred_tick_count} job(s) awaiting a confirmed create this tick (per-job detail logged once per job+reason, not every tick)"
  fi

  # quick-260813-wnz (LOG-01/D-02): one aggregate line per tick when the
  # fallback count is non-zero; silent when zero. Per-session detail is
  # gated to once-per-(session, reason) above (FALLBACK_WARN_FLAGS_DIR) --
  # this line is what keeps the backlog-size signal alive despite that gate,
  # rather than trading the per-tick spam for total silence.
  if [[ "${fallback_tick_count}" -gt 0 ]]; then
    info "trace-type fallback: ${fallback_tick_count} session(s) resolved to the fallback this tick (per-session detail logged once per session+reason, not every tick)"
  fi

  # quick-260817-tfe (T-OWN-04): the same per-tick-aggregate discipline for
  # the two ownership outcomes — one line when non-zero, silent when zero, and
  # never a per-session line (an event-owned session stays in state.db
  # forever, so a per-session line would grow without bound).
  if [[ "${event_owned_skip_count}" -gt 0 ]]; then
    info "legacy completions suppressed for ${event_owned_skip_count} session(s) this tick — the session ownership record names the event path"
  fi
  if [[ "${claim_unavailable_count}" -gt 0 ]]; then
    warn "session ownership record unavailable for ${claim_unavailable_count} session(s) this tick — failing OPEN (legacy billed them, as it does today); check permissions on ${OWNERS_DIR}"
  fi

  # quick-260818-0in (MODE-01..05): the same per-tick-aggregate discipline
  # for the two mode-aware-takeover outcomes — one line when non-zero,
  # silent when zero, never a per-session line.
  if [[ "${takeover_count}" -gt 0 ]]; then
    info "legacy took over ${takeover_count} session(s) this tick from the event path (event mode reverted; catch-up floor recorded, billing forward only)"
  fi
  if [[ "${takeover_unavailable_count}" -gt 0 ]]; then
    warn "session ownership takeover unavailable for ${takeover_unavailable_count} session(s) this tick — deferring (fail-closed; an event-owned record with no floor must never be re-billed from a zero baseline); check permissions on ${OWNERS_DIR}"
  fi

  # quick-260818-jbl (CLAIM-01..05/AX-Q16/T-jbl-03/T-jbl-04/T-jbl-07): the
  # same per-tick-aggregate discipline as the pairs above — one line when
  # non-zero, silent when zero, never a per-session line (names counts only,
  # never a sid, per T-jbl-05). This is the audit record for an abstention:
  # without it, "abstained then claimed by the event path this same tick" and
  # "abstained then nobody will ever claim it" are indistinguishable on disk.
  #
  # SEVERITY IS CONDITIONAL ON EVENT_PATH_LIVE (AX-Q16), read here and
  # nowhere else in this branch — this branch must not add a fourth read of
  # sid_legacy_suppressed, which would make AX-Q14's three-site-coupling
  # extraction ambiguous for no benefit.
  #   EVENT_PATH_LIVE=true  -> info. cron.sh runs the legacy stage before the
  #     event stage, so the event path claims and bills these sessions in
  #     THIS SAME TICK. Normal cutover flow.
  #   EVENT_PATH_LIVE=false -> warn. Nobody will claim these sessions this
  #     tick. Recovery is bounded, not silent, and has two independent
  #     routes with two different bounds: (1) flip REVENIUM_EVENT_METERING_MODE
  #     to "live" — recovers from the session's event spool file, which
  #     prune-markers.sh removes REVENIUM_MARKER_RETENTION_DAYS (default 30)
  #     after the session's last event, and only when an operator actually
  #     runs that manual pruner; (2) set REVENIUM_LEGACY_COMPLETIONS=enabled —
  #     recovers from the session's row in state.db, which this skill never
  #     prunes, for as long as Hermes retains that row. Permanent loss needs
  #     BOTH closed.
  if [[ "${claim_abstained_count}" -gt 0 ]]; then
    if [[ "${EVENT_PATH_LIVE}" == "true" ]]; then
      info "legacy declined to claim ${claim_abstained_count} session(s) this tick — emission is suppressed for them and neither ledger holds rows; the event path is live and claims them this same tick"
    else
      warn "legacy declined to claim ${claim_abstained_count} session(s) this tick — emission is suppressed for them and neither ledger holds rows, and the event path is NOT live, so nobody will claim or bill them this tick. Recovery is bounded, not permanent: flip REVENIUM_EVENT_METERING_MODE=live (recovers from the event spool, bounded by REVENIUM_MARKER_RETENTION_DAYS from each session's last event, only when the manual pruner has been run) or set REVENIUM_LEGACY_COMPLETIONS=enabled (recovers from state.db, which this skill never prunes). Do not wait on this — act on one of the two remedies."
    fi
  fi

  # Phase 55 (D-06): the post-loop auxiliary-usage pass. Placement is
  # load-bearing: after the outcome stage (every JOB:<id>:created: line this
  # tick could write already exists, so aux rows can reach --agentic-job-id)
  # and before the cost-reconciliation block below, so an aux query or emit
  # failure structurally cannot reach main-loop rows.
  report_auxiliary_usage "${aux_session_ctx}"

  # Phase 44 Plan 04 (EGV-17/D-15): one per-tick reconciliation line naming
  # the classified/unclassified/unallocated cost totals, built by
  # partition_by_attribution over the rows accumulated above. ACCUMULATE-ONLY
  # (CF-3/PA-10): this heredoc reads attribution_rows and prints a summary --
  # it makes no ledger write, no CLI call and influences no metering
  # decision. Wrapped so a failure degrades to "no reconciliation line"
  # rather than aborting the tick, matching this file's existing discipline
  # for non-critical heredocs -- this file runs `set -uo pipefail`,
  # deliberately without `-e`, precisely so a per-item failure never aborts
  # the run. Skipped entirely when the accumulator is empty, so a quiet tick
  # stays quiet.
  if [[ -n "${attribution_rows}" ]]; then
    local recon_output
    recon_output=$(
      ATTRIBUTION_ROWS="${attribution_rows}" \
      SCRIPT_DIR="${SCRIPT_DIR}" \
      python3 - <<'PY' 2>/dev/null
import os, sys
try:
    sys.path.insert(0, os.environ['SCRIPT_DIR'])
    from split_strategies import partition_by_attribution
    rows = []
    for line in os.environ.get('ATTRIBUTION_ROWS', '').splitlines():
        if not line:
            continue
        parts = line.split('|')
        if len(parts) != 7:
            continue
        bucket, i, o, cr, cw, tot, cost = parts
        rows.append((bucket, {
            "input": int(i), "output": int(o), "cache_read": int(cr),
            "cache_write": int(cw), "total": int(tot), "cost": cost,
        }))
    result = partition_by_attribution(rows)
    for bucket in ("classified", "unclassified", "unallocated"):
        b = result[bucket]
        print(f"{bucket.upper()}_COST={b['cost']}")
        print(f"{bucket.upper()}_TOTAL={b['total']}")
except Exception as exc:
    print(f"RECON_ERROR={exc}", file=sys.stderr)
    sys.exit(1)
PY
    ) || recon_output=""
    if [[ -n "${recon_output}" ]]; then
      local recon_classified_cost recon_unclassified_cost recon_unallocated_cost
      local recon_classified_total recon_unclassified_total recon_unallocated_total
      recon_classified_cost=$(echo "${recon_output}" | sed -n 's/^CLASSIFIED_COST=//p')
      recon_classified_total=$(echo "${recon_output}" | sed -n 's/^CLASSIFIED_TOTAL=//p')
      recon_unclassified_cost=$(echo "${recon_output}" | sed -n 's/^UNCLASSIFIED_COST=//p')
      recon_unclassified_total=$(echo "${recon_output}" | sed -n 's/^UNCLASSIFIED_TOTAL=//p')
      recon_unallocated_cost=$(echo "${recon_output}" | sed -n 's/^UNALLOCATED_COST=//p')
      recon_unallocated_total=$(echo "${recon_output}" | sed -n 's/^UNALLOCATED_TOTAL=//p')
      if [[ -n "${recon_classified_cost}" && -n "${recon_unclassified_cost}" && -n "${recon_unallocated_cost}" ]]; then
        info "cost reconciliation this tick: classified=${recon_classified_cost} (tokens=${recon_classified_total}) unclassified=${recon_unclassified_cost} (tokens=${recon_unclassified_total}) unallocated=${recon_unallocated_cost} (tokens=${recon_unallocated_total})"
      fi
    fi
  fi

  info "=== Done. Reported ${reported_count}, skipped ${skipped_count}. ==="
}

main "$@"
