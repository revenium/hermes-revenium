#!/usr/bin/env bash
# Prune stale marker JSONL files from MARKERS_DIR.
# Staleness is determined by the latest ledger row timestamp for the session
# (field 4 of HERMES:<sid>:<total_tokens>:<unix_ts>:<muid> lines). If no
# ledger entry exists for a sid (orphan marker), file mtime is used instead.
# Safe to run manually at any time; NOT wired into cron (D-28).
#
# Phase 32 (D-15): also prunes the two per-session JSONL spool directories —
# the new event spool (EVENT_SPOOL_DIR) and the pre-existing tool-event spool
# (TOOL_EVENTS_DIR, which this script had NEVER referenced before this
# change) — and the new api_request_id-keyed ledger (EVENT_LEDGER_FILE). All
# four passes share the same lock, the same MARKER_RETENTION_DAYS preflight,
# and the same --dry-run semantics. The frozen legacy HERMES: ledger
# (LEDGER_FILE) is never touched by any of the new passes.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

ensure_path

# ---------------------------------------------------------------------------
# Flag parsing
# ---------------------------------------------------------------------------
DRY_RUN=false
for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=true ;;
    *) echo "Unknown flag: ${arg}" >&2; echo "Usage: $(basename "${BASH_SOURCE[0]}") [--dry-run]" >&2; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Preflight: validate MARKER_RETENTION_DAYS and, independently,
# REVENIUM_ASSESSMENT_RETENTION_DAYS (Phase 42 D-13/T-42-07-02) are each an
# integer >= 1 (HARDEN-03). A value of 0 (or non-integer) would make every
# record stale and trigger a mass-delete. Warn loudly and refuse to prune
# rather than deleting anything -- but a bad value in ONE tunable must gate
# only ITS OWN passes: the marker/flag/spool/ledger/owner passes below all
# key on MARKER_RETENTION_DAYS and are gated by MARKER_RETENTION_OK; the
# job-assessments sidecar pass keys on its own
# REVENIUM_ASSESSMENT_RETENTION_DAYS and is gated independently by
# ASSESSMENT_RETENTION_OK. The previous shape here was a single `exit 0` for
# the whole script on an invalid MARKER_RETENTION_DAYS -- that would also
# silently skip the unrelated sidecar pass, which is exactly the
# cross-tunable coupling this phase forbids. Only when BOTH tunables are
# invalid is there nothing left to prune, so only that case exits early.
# ---------------------------------------------------------------------------
MARKER_RETENTION_OK=true
if ! [[ "${MARKER_RETENTION_DAYS}" =~ ^[0-9]+$ ]] || [[ "${MARKER_RETENTION_DAYS}" -lt 1 ]]; then
  warn "prune-markers: REVENIUM_MARKER_RETENTION_DAYS=${MARKER_RETENTION_DAYS} is invalid (must be an integer >= 1); refusing to prune the marker/flag/spool/ledger/owner passes"
  MARKER_RETENTION_OK=false
fi

ASSESSMENT_RETENTION_OK=true
if ! [[ "${REVENIUM_ASSESSMENT_RETENTION_DAYS}" =~ ^[0-9]+$ ]] || [[ "${REVENIUM_ASSESSMENT_RETENTION_DAYS}" -lt 1 ]]; then
  warn "prune-markers: REVENIUM_ASSESSMENT_RETENTION_DAYS=${REVENIUM_ASSESSMENT_RETENTION_DAYS} is invalid (must be an integer >= 1); refusing to prune the job-assessments sidecar"
  ASSESSMENT_RETENTION_OK=false
fi

if [[ "${MARKER_RETENTION_OK}" == "false" && "${ASSESSMENT_RETENTION_OK}" == "false" ]]; then
  exit 0
fi

# ---------------------------------------------------------------------------
# Acquire prune.lock (non-blocking) so two concurrent operator invocations
# cannot race on the same file set (D-29 / T-05-01).  Uses the same
# exec-fd + Python fcntl pattern as cron.sh (CRON-08 / D-12).
# ---------------------------------------------------------------------------
exec 9>"${PRUNE_LOCK_FILE}"
if ! python3 - <<'PY'
import fcntl, sys
try:
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
except (OSError, BlockingIOError):
    sys.exit(11)
PY
then
  warn "prior prune still active, skipping"
  exit 0
fi

# ---------------------------------------------------------------------------
# Main pruning logic: run Python, capture its stdout to a temp file so the
# child's exit code is observable, then feed each output line through info()
# so every log event lands in ${LOG_FILE} with the standard timestamp format.
# Never use bare echo for logged events.
#
# Previously used a process-substitution form which discards the child's exit
# code (pipefail does not apply to that form); a temp-file + prune_rc=$?
# pattern is used instead so a failed os.unlink propagates as a non-zero exit.
# ---------------------------------------------------------------------------
prune_out="$(mktemp)"
# Pass paths via env (bash 3.2 compatible — `${VAR@Q}` requires bash 4.4+;
# per project bash 3.2 convention for macOS stock /bin/bash). Single-
# quoted heredoc keeps the Python source verbatim.
# set +e so set -euo pipefail does not abort before prune_rc=$? is captured.
set +e
MARKERS_DIR_PY="${MARKERS_DIR}" \
MARKERS_READY_DIR_PY="${MARKERS_READY_DIR}" \
LEDGER_FILE_PY="${LEDGER_FILE}" \
MARKER_RETENTION_DAYS_PY="${MARKER_RETENTION_DAYS}" \
MARKER_RETENTION_OK_PY="${MARKER_RETENTION_OK}" \
SETTLE_SECONDS_PY="${REVENIUM_CRON_SETTLE_SECONDS}" \
DRY_RUN_PY="${DRY_RUN}" \
FLAG_DIRS_PY="${WARN_FLAGS_DIR}
${FALLBACK_WARN_FLAGS_DIR}
${OUTCOME_WARN_FLAGS_DIR}
${PROBE_WARN_FLAGS_DIR}
${AUX_WARN_FLAGS_DIR}" \
SESSION_KEYED_FLAG_DIRS_PY="${WARN_FLAGS_DIR}
${FALLBACK_WARN_FLAGS_DIR}" \
EVENT_SPOOL_DIR_PY="${EVENT_SPOOL_DIR}" \
TOOL_EVENTS_DIR_PY="${TOOL_EVENTS_DIR}" \
EVENT_LEDGER_FILE_PY="${EVENT_LEDGER_FILE}" \
TOOL_EVENTS_LEDGER_FILE_PY="${TOOL_EVENTS_LEDGER_FILE}" \
OWNERS_DIR_PY="${OWNERS_DIR}" \
STATE_DB_PY="${STATE_DB}" \
JOB_ASSESSMENTS_DIR_PY="${JOB_ASSESSMENTS_DIR}" \
ASSESSMENT_RETENTION_DAYS_PY="${REVENIUM_ASSESSMENT_RETENTION_DAYS}" \
ASSESSMENT_RETENTION_OK_PY="${ASSESSMENT_RETENTION_OK}" \
python3 - <<'PY' >"${prune_out}"
import fcntl
import os
import re
import sqlite3
import sys
import time

markers_dir    = os.environ['MARKERS_DIR_PY']
markers_ready_dir = os.environ['MARKERS_READY_DIR_PY']
ledger_file    = os.environ['LEDGER_FILE_PY']
marker_retention_ok = os.environ.get('MARKER_RETENTION_OK_PY') == 'true'
dry_run        = os.environ['DRY_RUN_PY'] == "true"

# REVENIUM_CRON_SETTLE_SECONDS always carries a default ("600") from
# common.sh, but it is not validated by the MARKER_RETENTION_DAYS preflight
# above, so a garbage override must still fail open to that default rather
# than crash the whole prune run over an unrelated tunable.
try:
    settle_seconds = int(float(os.environ.get('SETTLE_SECONDS_PY', '600')))
except (TypeError, ValueError, OverflowError):
    # OverflowError is NOT redundant and NOT covered by ValueError:
    # int(float('inf')) and int(float('1e400')) both raise OverflowError,
    # while float('nan') raises ValueError. Without it,
    # REVENIUM_CRON_SETTLE_SECONDS=inf kills this whole interpreter -- every
    # later pass included -- which is exactly what the comment above says must
    # not happen. Found in review on PR #139.
    settle_seconds = 600

# Only parsed when the bash-side preflight found MARKER_RETENTION_DAYS valid
# (Phase 42 D-13/T-42-07-02) -- an invalid value's raw string (e.g.
# "not-a-number") must never reach int() here, since marker_retention_ok
# already gates every consumer of cutoff_secs below to a no-op.
if marker_retention_ok:
    retention_days = int(os.environ['MARKER_RETENTION_DAYS_PY'])
    cutoff_secs = retention_days * 86400
else:
    retention_days = None
    cutoff_secs = None


def ledger_last_ts(sid, ledger_path):
    """Return the unix timestamp (float) from the latest matching ledger row,
    or None if no row exists for this sid. Reads field 4 (0-indexed) from
    lines matching HERMES:<sid>: (D-26 primary path)."""
    try:
        with open(ledger_path, 'r', encoding='utf-8') as f:
            prefix = 'HERMES:' + sid + ':'
            last_ts = None
            for line in f:
                line = line.rstrip('\n')
                if not line.startswith(prefix):
                    continue
                parts = line.split(':')
                # v2: HERMES:<sid>:<total_tokens>:<unix_ts>:<muid>  (5 fields)
                # v1: HERMES:<sid>:<total_tokens>:<unix_ts>          (4 fields)
                if len(parts) >= 4:
                    try:
                        ts = float(parts[3])
                        if last_ts is None or ts > last_ts:
                            last_ts = ts
                    except ValueError:
                        pass
            return last_ts
    except FileNotFoundError:
        return None


def iso(ts):
    """Format a unix timestamp as ISO-8601 UTC for log lines."""
    import datetime
    return datetime.datetime.utcfromtimestamp(ts).strftime('%Y-%m-%dT%H:%M:%SZ')


def live_session_ids(state_db):
    """Return the set of session ids in state.db, or None when it cannot be read.

    None is the "cannot tell" signal, and is deliberately NOT the same as an
    empty set: an empty set means the DB was read and holds no sessions (prune
    freely), while None means we have no basis for a judgement and the caller
    must fall back to the age-only rule. Collapsing the two would make an
    unreadable state.db look like "every session is gone" and mass-prune every
    sentinel -- the exact re-warn storm this gate exists to prevent.

    Mirrors prune_owners' read-only URI connection rather than sharing code
    with it: that pass returns early and removes NOTHING on an unreadable DB,
    because an ownership record deleted on doubt is a double-bill. Here the
    stake is only log noise, so doubt degrades to today's behaviour instead.
    """
    if not state_db or not os.path.isfile(state_db):
        return None
    try:
        uri = 'file:' + state_db + '?mode=ro'
        out = set()
        with sqlite3.connect(uri, uri=True) as conn:
            for (sid,) in conn.execute('SELECT id FROM sessions'):
                if sid is not None:
                    out.add(str(sid))
        return out
    except Exception:
        return None


def session_started_ats(state_db):
    """Return {sid: started_at_or_None} read from state.db's sessions table,
    or None (top-level) when the DB/table/column cannot be read at all.

    This is the belt for prune_ready_sentinels' clause (c) -- see that
    function's docstring for the full predicate and why clause (a) alone is
    already the proof. None mirrors live_session_ids' None-means-doubt
    contract verbatim: a caller that gets None has no basis for a liveness
    judgement and must degrade, never assume "every session is gone".

    Deliberately a SEPARATE helper, not a widening of live_session_ids
    above. The flags pass depends on live_session_ids' set-shaped return,
    and changing a flow's entry while missing one of its exits is this
    repo's own recurring defect -- see CLAUDE.md's "Shared-checkout
    concurrency" / "narrowing a race window" lessons for the general shape
    of that mistake. The one extra read of state.db this costs per run is
    acceptable because prune-markers.sh is operator-invoked (D-28), not
    run every minute the way hermes-report.sh is.

    A per-sid value of None (sid present, started_at column NULL) is
    distinct from the sid being absent from the dict entirely (no row) --
    prune_ready_sentinels treats both the same way (not pending), but the
    distinction is preserved here so a future caller with a different need
    does not have to re-derive it.
    """
    if not state_db or not os.path.isfile(state_db):
        return None
    try:
        uri = 'file:' + state_db + '?mode=ro'
        out = {}
        with sqlite3.connect(uri, uri=True) as conn:
            for sid, started_at in conn.execute('SELECT id, started_at FROM sessions'):
                if sid is None:
                    continue
                try:
                    out[str(sid)] = float(started_at) if started_at is not None else None
                except (TypeError, ValueError):
                    out[str(sid)] = None
        return out
    except Exception:
        return None


def prune_ready_sentinels(ready_dir, markers_dir, pruned_sids, started_ats, settle_seconds):
    """Sixth pass: remove spent markers/.ready/<sid> sentinels.

    MOTIVATION (measured, reference host Jupi, 2026-10-01): 2843 sentinels
    against 1112 marker files -- 1733 orphans, every one of them past the
    30-day retention window. The marker pass earlier in this file has pruned
    markers for years; nothing has ever pruned .ready. Reading that imbalance
    cold produced a confident, wrong report of a systemic 70%
    classification-failure in one session. Zero sessions on the same host
    show .ready-without-markers INSIDE the window -- that absence is what the
    honest signal looks like, and it is the shape this pass restores.

    THE PREDICATE -- remove MARKERS_READY_DIR/<sid> when ALL THREE hold:

      (a) AGE -- now - mtime(sentinel) >= cutoff_secs, the SAME
          MARKER_RETENTION_DAYS cutoff every other pass in this file uses.
      (b) LIFETIME COUPLING -- the marker half is gone: markers_dir/<sid>.jsonl
          does not exist on disk, OR sid is in pruned_sids (the set the
          marker pass above removed, or WOULD remove under --dry-run).
      (c) BELT -- only evaluated when started_ats is not None: sid has no
          row in state.db at all (the reporter only ever walks state.db
          rows, so a row-less session can never be metered again), or
          now - started_at >= settle_seconds. When started_ats IS None
          (state.db missing, unreadable, or schema-older), clause (c) is
          skipped entirely and one line says so -- this pass degrades to
          (a)+(b), never to "prune freely".

    (a) IS THE PROOF, and it is airtight without the DB. The sentinel's only
    writer (the classifier plugin) touches it during the session it names,
    so mtime(sentinel) >= started_at(session) ALWAYS holds in production.
    Clause (a) therefore implies the session's own age also clears
    REVENIUM_CRON_SETTLE_SECONDS -- hermes-report.sh's
    `has_sentinel or age >= settle_seconds` gate -- by a 4,320x margin (30
    days against the 600-second default). A sentinel past (a) cannot change
    any metering decision, because the reporter's gate no longer consults it
    either way.

    (c) is a belt, not the proof, and is honestly labelled as one: state.db
    may be missing or unreadable, and on a multiplexed host the state.db at
    this HERMES_HOME is not necessarily the one that owns a sentinel sitting
    in this home's .ready. (a) does not depend on any of that.

    REJECTED: prune_owners' posture of removing NOTHING on doubt about
    state.db. Correct there -- an ownership record deleted on doubt is a
    double-bill. Wrong here -- doubt about state.db only risks leaving
    today's (broken) behaviour in place, while (a)'s proof stands without
    the DB at all, so a no-op here would forfeit the fix on exactly the
    measured host for no safety gain.

    THE ASYMMETRY WITH THE WARN FLAGS -- do not copy that rule here. Pruning
    a WARN sentinel RE-ARMS a warn that is still reachable (measured
    2026-09-18: one prune removed 1031 flags and drove trace-type fallback
    warns from ~1/hour to 1666 in that hour), which is why the flags pass
    above keeps a flag alive for as long as its session is live. A .ready
    sentinel is NOT re-armable -- nothing ever re-touches it once written --
    and its hazard runs the OTHER way: deleting one EARLY pushes a
    still-young session onto the settle-window fallback, which is how a
    completion gets metered before its job marker lands and orphans from its
    job permanently (BUG-1). Same family of hazard, opposite mechanism: this
    pass therefore gates on the sentinel being PROVABLY PAST the window in
    which the reporter's gate can even consult it (age), never on session
    liveness. Clause (c)'s liveness-shaped check is only the belt. A future
    reader "restoring consistency" by keying this pass on liveness instead
    of age would reintroduce exactly the early-delete hazard this paragraph
    exists to prevent.

    No suffix filter is available here -- unlike every sibling pass, a
    sentinel's whole filename IS the raw session id, with no .jsonl/.flag
    marker to distinguish a real entry from noise. The three-clause
    predicate above therefore carries the ENTIRE safety burden alone.
    """
    r_scanned = 0
    r_kept = 0
    r_removed = 0
    r_kept_marker_present = 0
    r_kept_session_pending = 0

    # A never-classified install has no .ready dir, which is not an error.
    # Catch OSError, not just FileNotFoundError: an existing-but-unreadable dir
    # (PermissionError, ENOTDIR) raises a sibling this pass must not die on,
    # because prune_spool_dir, prune_event_ledger and the owners pass all run
    # LATER in this same interpreter -- one unreadable directory must not
    # cancel every remaining pass. Mirrors the owners pass's own
    # 'owners pass skipped -- owners dir unreadable' precedent below.
    try:
        entries = sorted(os.listdir(ready_dir))
    except FileNotFoundError:
        entries = []
    except OSError as exc:
        print(
            'prune: ready pass skipped -- .ready dir unreadable: ' + str(exc),
            flush=True,
        )
        return

    # Clause (a) is only a proof while the retention cutoff actually clears the
    # reporter's settle window. Both are INDEPENDENT operator tunables
    # (REVENIUM_MARKER_RETENTION_DAYS, REVENIUM_CRON_SETTLE_SECONDS), so the
    # comfortable 30-days-against-600-seconds default margin is a DEFAULT, not
    # an invariant: retention=1d with settle=2d inverts it, and a sentinel past
    # the cutoff would then still belong to a session the reporter considers
    # young -- deleting it DEFERS a session the sentinel would have released,
    # the exact BUG-1 job-orphaning hazard this pass exists not to cause.
    # Taking the max restores the implication by construction for every
    # configuration, and is a no-op on a default install. Found in review on
    # PR #139; the original docstring argued from the defaults alone.
    effective_cutoff = cutoff_secs
    if settle_seconds is not None and settle_seconds > effective_cutoff:
        effective_cutoff = settle_seconds
        print(
            'prune: ready pass -- settle window (' + str(settle_seconds) +
            's) exceeds marker retention (' + str(int(cutoff_secs)) +
            's); using the settle window as the .ready cutoff',
            flush=True,
        )

    if started_ats is None:
        print(
            'prune: ready pass -- state.db unavailable, falling back to '
            'age+marker-coupling only for .ready sentinels (clause (c) skipped)',
            flush=True,
        )

    for sid in entries:
        fpath = os.path.join(ready_dir, sid)
        if not os.path.isfile(fpath):
            continue

        r_scanned += 1
        mtime = os.path.getmtime(fpath)
        age_secs = time.time() - mtime
        age_days = age_secs / 86400

        # Clause (a) -- AGE. effective_cutoff, not cutoff_secs: see the
        # settle-window note above.
        if age_secs < effective_cutoff:
            r_kept += 1
            continue

        # Clause (b) -- LIFETIME COUPLING. pruned_sids (not a bare
        # os.path.exists) is what makes --dry-run predict a live run: a dry
        # run leaves the marker file in place, so an existence test alone
        # would preview "kept" for a sentinel a live run actually removes.
        marker_path = os.path.join(markers_dir, sid + '.jsonl')
        marker_gone = (sid in pruned_sids) or not os.path.isfile(marker_path)
        if not marker_gone:
            r_kept += 1
            r_kept_marker_present += 1
            continue

        # Clause (c) -- BELT, only when state.db was readable. A sid with no
        # row at all, or a row whose started_at could not be parsed, is
        # treated as not-pending (nothing here blocks removal on doubt) --
        # the row-less case is the documented "can never be metered again"
        # shape, and an unparseable started_at carries no information (a).
        if started_ats is not None:
            started_at = started_ats.get(sid, None)
            if sid in started_ats and started_at is not None:
                pending_age = time.time() - started_at
                if pending_age < settle_seconds:
                    r_kept += 1
                    r_kept_session_pending += 1
                    continue

        action = 'dry-run, would remove' if dry_run else 'removed'
        print(
            'prune: ' + action +
            ' dir=ready' +
            ' sid=' + sid +
            ' mtime=' + iso(mtime) +
            ' age_days=' + str(round(age_days, 1)),
            flush=True,
        )

        if not dry_run:
            try:
                os.unlink(fpath)
                r_removed += 1
            except OSError as exc:
                print('prune: ERROR removing ' + sid + ': ' + str(exc), flush=True)
                sys.exit(1)
        else:
            r_removed += 1  # count for dry-run summary

    print(
        'prune: ready summary, scanned=' + str(r_scanned) +
        ' kept=' + str(r_kept) +
        ' removed=' + str(r_removed) +
        ' kept_marker_present=' + str(r_kept_marker_present) +
        ' kept_session_pending=' + str(r_kept_session_pending),
        flush=True,
    )
    return r_scanned, r_kept, r_removed


if marker_retention_ok:
    scanned = 0
    kept = 0
    removed = 0
    # Records which sids THIS run decided to remove from markers_dir, in
    # BOTH the live and the dry-run branches below. prune_ready_sentinels'
    # clause (b) reads this set rather than re-checking os.path.exists, so
    # that --dry-run predicts a live run exactly (a dry run leaves the
    # marker file on disk, so an existence check alone would diverge).
    marker_pruned_sids = set()

    try:
        entries = sorted(os.listdir(markers_dir))
    except FileNotFoundError:
        entries = []

    for fname in entries:
        if not fname.endswith('.jsonl'):
            continue
        fpath = os.path.join(markers_dir, fname)
        if not os.path.isfile(fpath):
            continue

        scanned += 1
        sid = fname[:-len('.jsonl')]  # strip .jsonl suffix

        last_ts = ledger_last_ts(sid, ledger_file)
        if last_ts is not None:
            # Ledger-based stale check (D-26 primary path)
            age_secs  = time.time() - last_ts
            age_days  = age_secs / 86400
            ts_label  = iso(last_ts)
            ts_source = 'last_ledger_ts'
        else:
            # Orphan fallback: no ledger row — use file mtime (D-26 fallback)
            mtime     = os.path.getmtime(fpath)
            age_secs  = time.time() - mtime
            age_days  = age_secs / 86400
            ts_label  = iso(mtime)
            ts_source = 'mtime'

        if age_secs < cutoff_secs:
            kept += 1
            continue

        # File is stale — remove or report
        action = 'dry-run, would remove' if dry_run else 'removed'
        print(
            'prune: ' + action +
            ' sid=' + sid +
            ' marker=' + fname +
            ' ' + ts_source + '=' + ts_label +
            ' age_days=' + str(round(age_days, 1)),
            flush=True,
        )

        if not dry_run:
            try:
                os.unlink(fpath)
                removed += 1
                marker_pruned_sids.add(sid)
            except OSError as exc:
                print('prune: ERROR removing ' + fname + ': ' + str(exc), flush=True)
                sys.exit(1)
        else:
            removed += 1  # count for dry-run summary
            # Deliberately recorded even though nothing is deleted on this
            # branch: marker_pruned_sids is what lets prune_ready_sentinels
            # (and --dry-run's own preview) predict what a live run would do
            # to a sentinel whose marker a dry run leaves on disk. An
            # os.path.exists check alone would say "kept" here and diverge
            # from the live run's actual removal.
            marker_pruned_sids.add(sid)

    # ---------------------------------------------------------------------------
    # quick-260813-wnz (LOG-01/D-05): second pass -- bound the once-per-
    # (key, reason) flag directories (WARN_FLAGS_DIR, FALLBACK_WARN_FLAGS_DIR,
    # OUTCOME_WARN_FLAGS_DIR, PROBE_WARN_FLAGS_DIR, and AUX_WARN_FLAGS_DIR,
    # passed in newline-separated via FLAG_DIRS_PY) so the fix for each
    # re-warn spam cannot itself become a new unbounded-growth path. Filtered
    # to files ending in '.flag'; staleness is the flag's own mtime (a
    # flag's mtime IS the moment we last warned, so it needs no ledger
    # correlation, unlike a marker's mtime). Gated by the SAME
    # MARKER_RETENTION_DAYS preflight and cutoff_secs the marker pass above
    # uses; --dry-run honored identically.
    #
    # OUTCOME_WARN_FLAGS_DIR is Phase 39 D-02 (the deferred/wedged job-outcome
    # gate).
    #
    # PROBE_WARN_FLAGS_DIR is listed but this pass prunes NOTHING from it, and
    # that is correct rather than an oversight. Two independent reasons, both
    # load-bearing:
    #
    #   1. Its entries carry no '.flag' suffix -- common.sh writes
    #      "${flag_dir}/${probe_key}" with probe_key built straight from
    #      `printf '%s %s' <subcommand> <flag> | tr -c 'A-Za-z0-9._-' '_'` --
    #      so the endswith('.flag') filter below skips every one of them.
    #   2. It cannot grow without a code change. probe_key is derived from the
    #      two LITERAL arguments at each supports_flag call site, so the key
    #      space is closed at the number of those call sites (~16 across
    #      hermes-report.sh, api-event-report.sh, correct-assessment.sh,
    #      guardrail-check.sh and setup-guardrails.sh). A directory bounded by
    #      the source text is not the unbounded-growth hazard the other four
    #      dirs are.
    #
    # An earlier revision of this comment claimed the opposite -- that
    # PROBE_WARN_FLAGS_DIR was "the identical leak, closed alongside here".
    # It is neither identical nor closed, and the claim is corrected here
    # rather than made true, because making it true would be a REGRESSION:
    # pruning a probe sentinel re-arms its warn, so a probe that is still
    # indeterminate would re-warn once every retention period forever, for a
    # condition that has not changed. That is the same re-arm defect the
    # session-keyed gate below exists to prevent, and it is pinned by
    # PruneProbeWarnFlagsTests. Do not "fix" the suffix mismatch.
    #
    # AUX_WARN_FLAGS_DIR is Phase 59 Plan 03
    # (D-17, folded todo aux-pass-silently-drops-zero-token-sessions): the
    # new ctx-unresolvable-<sid> per-session key introduced there makes this
    # directory grow one file per unresolvable session, and this pass is
    # what stops that growth from becoming a new leak the way the
    # PROBE_WARN_FLAGS_DIR omission above already did.
    # ---------------------------------------------------------------------------
    flag_dirs = [d for d in os.environ.get('FLAG_DIRS_PY', '').split('\n') if d]

    # A warn sentinel is a LIFETIME rate-limiter, not a cache: hermes-report.sh
    # states the invariant as "a session can produce at most 3 lines for its
    # entire life instead of one per minute forever". Its mtime is the moment
    # we last warned and never refreshes, but the session it silences stays in
    # state.db and is re-walked every tick -- so ageing the flag out re-ARMS a
    # warn that is still reachable, it fires again, mtime resets, and the cycle
    # repeats every retention period forever. Measured on a live host
    # 2026-09-18: a prune removed 1031 flags and trace-type fallback warns went
    # from ~1/hour to 1666 in that hour, then back to 0.
    #
    # The gate is restricted to the directories whose key provably BEGINS with
    # a session id, because the five key shapes are not uniform and a blanket
    # session lookup would be wrong for three of them:
    #
    #   WARN_FLAGS_DIR      <session>__<ruleId>.flag      session-keyed
    #   FALLBACK_WARN       <session>__<reason>.flag      session-keyed
    #   OUTCOME_WARN        <outcomeId>__<reason>.flag    keyed by JOB id
    #   AUX_WARN            <sanitizedKey>.flag           mixed: ctx-unresolvable-<sid> OR a constant
    #   PROBE_WARN          <subcommand>_<flag>           not session-keyed at all
    #
    # The two session-keyed dirs are passed in explicitly via
    # SESSION_KEYED_FLAG_DIRS_PY rather than inferred from position in
    # FLAG_DIRS_PY -- a positional contract between two env vars is one
    # reordering away from silently gating the wrong directory.
    session_keyed_dirs = set(
        d for d in os.environ.get('SESSION_KEYED_FLAG_DIRS_PY', '').split('\n') if d
    )
    live_sids = live_session_ids(os.environ.get('STATE_DB_PY', ''))
    if session_keyed_dirs and live_sids is None:
        print(
            'prune: flags pass -- state.db unavailable, falling back to age-only '
            'for session-keyed flag dirs (a stale sentinel may re-warn once)',
            flush=True,
        )

    flags_scanned = 0
    flags_kept = 0
    flags_removed = 0
    flags_kept_live = 0
    flags_kept_unparseable = 0

    for flag_dir in flag_dirs:
        try:
            flag_entries = sorted(os.listdir(flag_dir))
        except FileNotFoundError:
            continue

        for fname in flag_entries:
            if not fname.endswith('.flag'):
                continue
            fpath = os.path.join(flag_dir, fname)
            if not os.path.isfile(fpath):
                continue

            flags_scanned += 1
            mtime = os.path.getmtime(fpath)
            age_secs = time.time() - mtime
            age_days = age_secs / 86400

            if age_secs < cutoff_secs:
                flags_kept += 1
                continue

            # Past the age cutoff, but a session-keyed sentinel whose session
            # is still live must survive anyway -- see the lifetime note above.
            # Counted rather than logged per file: a host with thousands of
            # live sessions would otherwise trade a warn storm for a prune-log
            # storm, which is the same unbounded-growth defect wearing a
            # different hat.
            if flag_dir in session_keyed_dirs and live_sids is not None:
                stem = fname[:-len('.flag')]
                if '__' not in stem:
                    # Both session-keyed dirs always emit a '__' separator, so
                    # a name without one is not a key this gate understands.
                    # Keeping it cannot threaten the growth bound (such names
                    # should not exist) and pruning it would re-warn.
                    flags_kept += 1
                    flags_kept_unparseable += 1
                    continue
                # EVERY '__' boundary is tried, not just the first: a session
                # id can itself contain '__', so the first separator is not
                # necessarily the session/reason boundary. FALLBACK_WARN keys
                # on safe_sid, which maps each character outside
                # [A-Za-z0-9_:.-] to '_' -- so two adjacent disallowed
                # characters in a raw id produce '__' inside the session
                # portion -- and WARN_FLAGS_DIR interpolates SESSION_ID with no
                # sanitisation at all. Splitting on the first separator would
                # test 'sess' for a live id of 'sess__live', miss the match,
                # prune the sentinel and re-warn: precisely the defect this
                # gate exists to close, still open for those ids. The loop is
                # bounded by the number of separators in the name (one, in
                # every key shape observed in practice).
                matched_live = False
                sep = stem.find('__')
                while sep != -1:
                    if stem[:sep] in live_sids:
                        matched_live = True
                        break
                    sep = stem.find('__', sep + 1)
                if matched_live:
                    flags_kept += 1
                    flags_kept_live += 1
                    continue

            action = 'dry-run, would remove' if dry_run else 'removed'
            print(
                'prune: ' + action +
                ' dir=' + flag_dir +
                ' flag=' + fname +
                ' mtime=' + iso(mtime) +
                ' age_days=' + str(round(age_days, 1)),
                flush=True,
            )

            if not dry_run:
                try:
                    os.unlink(fpath)
                    flags_removed += 1
                except OSError as exc:
                    print('prune: ERROR removing ' + fname + ': ' + str(exc), flush=True)
                    sys.exit(1)
            else:
                flags_removed += 1  # count for dry-run summary

    print(
        'prune: flags summary, scanned=' + str(flags_scanned) +
        ' kept=' + str(flags_kept) +
        ' removed=' + str(flags_removed) +
        ' kept_session_live=' + str(flags_kept_live) +
        ' kept_unparseable=' + str(flags_kept_unparseable),
        flush=True,
    )

    print(
        'prune: summary, scanned=' + str(scanned) +
        ' kept=' + str(kept) +
        ' removed=' + str(removed),
        flush=True,
    )

    # quick-261001-h5e: sixth pass -- the markers/.ready/<sid> sentinels.
    # Placed at the END of this block, AFTER the two summary prints above, so
    # the marker and flags passes' existing log order is unchanged (tests
    # assert on log text). See prune_ready_sentinels' docstring for the full
    # predicate.
    marker_started_ats = session_started_ats(os.environ.get('STATE_DB_PY', ''))
    prune_ready_sentinels(
        markers_ready_dir,
        markers_dir,
        marker_pruned_sids,
        marker_started_ats,
        settle_seconds,
    )

# ---------------------------------------------------------------------------
# Phase 32 (D-15): third pass -- the two per-session JSONL spool directories,
# the new event spool (EVENT_SPOOL_DIR) and the pre-existing tool-event spool
# (TOOL_EVENTS_DIR). TOOL_EVENTS_DIR is in scope DELIBERATELY: this script has
# never referenced it before, so the spool-then-ship pattern D-01/D-03 copy
# has had NO retention at all until now -- the new event spool would have
# silently inherited that same unbounded-growth gap. Structure mirrors the
# marker pass above (ledger-timestamp staleness, mtime fallback for an
# orphan, the same cutoff_secs, the same --dry-run semantics) so the file
# reads as one idea repeated rather than three separate designs.
# ---------------------------------------------------------------------------

_NS_PREFIX_RE = re.compile(r'^agent:([^:]+):')


def _strip_ns_prefix(sid):
    """Strip a leading `agent:<profile>:` namespace prefix, if present.
    Mirrors api_event_spool.py's _NS_RE -- deliberately not shared code (see
    that module's own docstring on why the duplication is intentional)."""
    m = _NS_PREFIX_RE.match(sid)
    if m:
        return sid[m.end():]
    return sid


def tool_ledger_last_ts(sid, ledger_path):
    """Newest timestamp for sid in the TOOL: ledger. Colon-delimited
    (TOOL:<sid>:<tool_call_id>:<ts>) and safe to fixed-position-split on ':'
    because post_tool_call.sh strips structural colons from sid before ever
    ledgering it -- unlike the marker pass's HERMES: ledger, whose sid can be
    a colon-bearing agent:<profile>:... identifier."""
    try:
        with open(ledger_path, 'r', encoding='utf-8') as f:
            prefix = 'TOOL:' + sid + ':'
            last_ts = None
            for line in f:
                line = line.rstrip('\n')
                if not line.startswith(prefix):
                    continue
                parts = line.split(':')
                if len(parts) >= 4:
                    try:
                        ts = float(parts[3])
                        if last_ts is None or ts > last_ts:
                            last_ts = ts
                    except ValueError:
                        pass
            return last_ts
    except FileNotFoundError:
        return None


def event_ledger_last_ts(sid, ledger_path):
    """Newest timestamp for sid in the API: ledger
    (API:<api_request_id>|<sid>|<unix_ts>). Deliberately NOT the marker
    pass's colon-splitting parser: api_request_id preserves structural
    colons (contract C-4), so a colon-based split would misparse it -- pipe
    is this ledger's real delimiter. The ledger's sid field is the RAW
    session id (Phase 32 Plan 01 decision); the spool FILENAME is already
    the namespace-stripped component, so both sides are normalized through
    _strip_ns_prefix before comparing."""
    target = _strip_ns_prefix(sid)
    try:
        with open(ledger_path, 'r', encoding='utf-8') as f:
            last_ts = None
            for line in f:
                line = line.rstrip('\n')
                if not line.startswith('API:'):
                    continue
                parts = line.split('|')
                if len(parts) != 3:
                    continue
                _arid_field, ledger_sid, ts_field = parts
                if _strip_ns_prefix(ledger_sid) != target:
                    continue
                try:
                    ts = float(ts_field)
                    if last_ts is None or ts > last_ts:
                        last_ts = ts
                except ValueError:
                    pass
            return last_ts
    except FileNotFoundError:
        return None


def prune_spool_dir(spool_dir, ledger_fn, ledger_path, label):
    s_scanned = s_kept = s_removed = 0
    try:
        entries = sorted(os.listdir(spool_dir))
    except FileNotFoundError:
        entries = []

    for fname in entries:
        if not fname.endswith('.jsonl'):
            continue
        fpath = os.path.join(spool_dir, fname)
        if not os.path.isfile(fpath):
            continue

        s_scanned += 1
        sid = fname[:-len('.jsonl')]

        # Age a spool from the NEWER of its last successful shipment and its
        # own mtime. The ledger timestamp alone is not safe here: every line
        # in a spool file is a billable record, and mtime advances whenever a
        # fresh event is appended. A session that shipped long ago and then
        # resumed carries an ancient ledger entry alongside brand-new
        # unshipped events in the same file -- ageing that file from the
        # ledger alone deletes revenue before it is ever reported.
        #
        # Markers can age from the ledger alone because a marker is a
        # classification record that has already served its purpose once its
        # session is reported. A spool line has not.
        last_ts = ledger_fn(sid, ledger_path)
        mtime = os.path.getmtime(fpath)
        if last_ts is not None and last_ts >= mtime:
            age_secs = time.time() - last_ts
            ts_label = iso(last_ts)
            ts_source = 'last_ledger_ts'
        else:
            age_secs = time.time() - mtime
            ts_label = iso(mtime)
            ts_source = 'mtime'
        age_days = age_secs / 86400

        if age_secs < cutoff_secs:
            s_kept += 1
            continue

        action = 'dry-run, would remove' if dry_run else 'removed'
        print(
            'prune: ' + action +
            ' dir=' + label +
            ' sid=' + sid +
            ' spool=' + fname +
            ' ' + ts_source + '=' + ts_label +
            ' age_days=' + str(round(age_days, 1)),
            flush=True,
        )

        if not dry_run:
            try:
                os.unlink(fpath)
                s_removed += 1
            except OSError as exc:
                print('prune: ERROR removing ' + fname + ': ' + str(exc), flush=True)
                sys.exit(1)
        else:
            s_removed += 1

    print(
        'prune: ' + label + ' summary, scanned=' + str(s_scanned) +
        ' kept=' + str(s_kept) +
        ' removed=' + str(s_removed),
        flush=True,
    )
    return s_scanned, s_kept, s_removed


event_spool_dir_py = os.environ.get('EVENT_SPOOL_DIR_PY', '')
tool_events_dir_py = os.environ.get('TOOL_EVENTS_DIR_PY', '')
event_ledger_file_py = os.environ.get('EVENT_LEDGER_FILE_PY', '')
tool_events_ledger_file_py = os.environ.get('TOOL_EVENTS_LEDGER_FILE_PY', '')

# Gated by marker_retention_ok (Phase 42 D-13/T-42-07-02): these two spool
# passes age from cutoff_secs, which is None when MARKER_RETENTION_DAYS was
# invalid -- see the preflight decoupling note above prune_owners below.
if marker_retention_ok and event_spool_dir_py:
    prune_spool_dir(event_spool_dir_py, event_ledger_last_ts, event_ledger_file_py, 'api-events')

if marker_retention_ok and tool_events_dir_py:
    prune_spool_dir(tool_events_dir_py, tool_ledger_last_ts, tool_events_ledger_file_py, 'tool-events')

# ---------------------------------------------------------------------------
# Phase 32 (D-15/D-08): fourth pass -- the new api_request_id-keyed ledger
# (EVENT_LEDGER_FILE, API: lines). An API: line is dropped only when it is
# BOTH past the cutoff AND its session's spool file no longer exists
# (T-32-20): removing an idempotency record ahead of the data it protects is
# how a pruning change turns into a double-report, so survival of the spool
# file always wins over age. The frozen legacy HERMES: ledger (LEDGER_FILE)
# is NEVER touched by this pass -- it is the rollback record (D-08) and the
# drain gate's own input (contract C-11); this function only ever opens
# EVENT_LEDGER_FILE, a wholly separate file.
# ---------------------------------------------------------------------------

def prune_event_ledger(ledger_path, spool_dir):
    if not ledger_path:
        return 0, 0, 0
    try:
        with open(ledger_path, 'r', encoding='utf-8') as f:
            raw_lines = [ln.rstrip('\n') for ln in f if ln.strip()]
    except FileNotFoundError:
        return 0, 0, 0

    l_scanned = l_kept = l_removed = 0
    out_lines = []
    now_ts = time.time()

    for raw_line in raw_lines:
        if not raw_line.startswith('API:'):
            out_lines.append(raw_line)
            continue
        parts = raw_line.split('|')
        if len(parts) != 3:
            # Unrecognised shape -- keep. Never guess-delete an idempotency
            # record whose fields this pass cannot parse with confidence.
            out_lines.append(raw_line)
            continue

        l_scanned += 1
        _arid_field, ledger_sid, ts_field = parts
        try:
            ts = float(ts_field)
        except ValueError:
            out_lines.append(raw_line)
            l_kept += 1
            continue

        age_secs = now_ts - ts
        if age_secs < cutoff_secs:
            out_lines.append(raw_line)
            l_kept += 1
            continue

        component = _strip_ns_prefix(ledger_sid)
        spool_path = os.path.join(spool_dir, component + '.jsonl') if spool_dir else ''
        if spool_path and os.path.isfile(spool_path):
            # T-32-20: the record this line protects could still be re-read
            # and re-shipped -- keep it regardless of age.
            out_lines.append(raw_line)
            l_kept += 1
            continue

        action = 'dry-run, would remove' if dry_run else 'removed'
        print(
            'prune: ' + action +
            ' dir=api-events-ledger' +
            ' sid=' + ledger_sid +
            ' age_days=' + str(round(age_secs / 86400, 1)),
            flush=True,
        )
        l_removed += 1
        if dry_run:
            # --dry-run must remove nothing -- keep the line in the rewrite
            # buffer too (moot in practice since the write below is also
            # gated on `not dry_run`, but keeps this function's own
            # bookkeeping honest under either gate independently).
            out_lines.append(raw_line)

    if not dry_run and l_removed:
        with open(ledger_path, 'w', encoding='utf-8') as f:
            for ln in out_lines:
                f.write(ln + '\n')

    print(
        'prune: api-events-ledger summary, scanned=' + str(l_scanned) +
        ' kept=' + str(l_kept) +
        ' removed=' + str(l_removed),
        flush=True,
    )
    return l_scanned, l_kept, l_removed


# Gated by marker_retention_ok: this pass ages API: lines from cutoff_secs,
# which is None when MARKER_RETENTION_DAYS was invalid.
if marker_retention_ok and event_ledger_file_py:
    prune_event_ledger(event_ledger_file_py, event_spool_dir_py)

# ---------------------------------------------------------------------------
# quick-260817-tfe (OWN-02): fifth pass -- the session OWNERSHIP records
# (OWNERS_DIR). Same idea as the passes above, with ONE deliberate difference
# that is the entire point of this pass existing:
#
#   STALENESS IS PRESENCE IN state.db, AND NOTHING ELSE. cutoff_secs is NOT
#   used here, and the coupling to MARKER_RETENTION_DAYS is deliberately
#   ABSENT. An ownership record must outlive every billing row it partitions,
#   for as long as the session it names can still accrue tokens. That is
#   exactly P1-2: the ownership signal used to live in the API: ledger, which
#   this script prunes at MARKER_RETENTION_DAYS (default 30), so ~30 days on a
#   STILL-LIVE session erased its only ownership record and let the legacy
#   path re-bill the session's entire cumulative token count from a zero
#   baseline. A future reader "restoring consistency" by keying this pass on
#   age would reintroduce that defect exactly.
#
# FAIL-SAFE, HARD. A missing state.db, an unreadable one, or ANY sqlite error
# removes NOTHING and says why. Deleting an ownership record on doubt is how a
# pruning change becomes a double-bill -- the same reasoning the event-ledger
# pass above already carries for its own idempotency records.
#
# Note this script is MANUAL and deliberately not wired into cron (D-28), so
# owners records accumulate between operator runs exactly as markers do.
# ---------------------------------------------------------------------------

def _owner_record_name(sid):
    """The SAME filename derivation the claim primitive uses in both
    hermes-report.sh and api-event-report.sh (separator and NUL to underscore,
    200-character cap). Applied to every state.db id before comparing, so an
    exotic session id compares against the right key on both sides."""
    return sid.replace('/', '_').replace('\x00', '_')[:200]


def prune_owners(owners_dir, state_db):
    if not owners_dir:
        return 0, 0, 0
    try:
        entries = sorted(os.listdir(owners_dir))
    except FileNotFoundError:
        return 0, 0, 0
    except OSError as exc:
        print('prune: owners pass skipped -- owners dir unreadable: ' + str(exc), flush=True)
        return 0, 0, 0

    if not state_db or not os.path.isfile(state_db):
        print('prune: owners pass skipped -- state.db not found at ' + str(state_db) +
              '; removing NOTHING (an ownership record deleted on doubt is a double-bill)',
              flush=True)
        return 0, 0, 0

    live = set()
    try:
        # Read-only URI connection, the established stdlib-sqlite3 pattern
        # drain-status.sh already uses -- this pass adds no new external-tool
        # precondition, and a missing state.db is never created as a side effect.
        uri = 'file:' + state_db + '?mode=ro'
        with sqlite3.connect(uri, uri=True) as conn:
            for (sid,) in conn.execute('SELECT id FROM sessions'):
                if sid is None:
                    continue
                live.add(_owner_record_name(str(sid)))
    except Exception as exc:
        print('prune: owners pass skipped -- state.db unreadable (' + str(exc) +
              '); removing NOTHING', flush=True)
        return 0, 0, 0

    o_scanned = o_kept = o_removed = 0
    for fname in entries:
        fpath = os.path.join(owners_dir, fname)
        if not os.path.isfile(fpath):
            continue

        o_scanned += 1
        if fname in live:
            o_kept += 1
            continue

        action = 'dry-run, would remove' if dry_run else 'removed'
        print(
            'prune: ' + action +
            ' dir=owners' +
            ' sid=' + fname +
            ' reason=absent_from_state_db',
            flush=True,
        )

        if not dry_run:
            try:
                os.unlink(fpath)
                o_removed += 1
            except OSError as exc:
                print('prune: ERROR removing ' + fname + ': ' + str(exc), flush=True)
                sys.exit(1)
        else:
            o_removed += 1

    print(
        'prune: owners summary, scanned=' + str(o_scanned) +
        ' kept=' + str(o_kept) +
        ' removed=' + str(o_removed),
        flush=True,
    )
    return o_scanned, o_kept, o_removed


prune_owners(os.environ.get('OWNERS_DIR_PY', ''), os.environ.get('STATE_DB_PY', ''))

# ---------------------------------------------------------------------------
# Phase 42 (D-13/C-01): sixth pass -- the job-assessments sidecar
# (JOB_ASSESSMENTS_DIR). This is a BESPOKE, SIMPLER shape than
# prune_spool_dir above, and the simplification is deliberate
# (42-RESEARCH.md Assumption A3): prune_spool_dir ages a file from the
# NEWER of a ledger timestamp and the file's mtime because a spool file
# mixes shipped and unshipped billable lines, and ageing from the ledger
# alone would delete revenue. The sidecar has no shipped-versus-unshipped
# distinction -- it is a local audit record, never itself billed -- so
# D-13's rule is mtime-only, full stop: a correction append (which rewrites
# nothing but appends a new line to the SAME file) is itself what refreshes
# the file's mtime and therefore the record's retention window. A later
# reader "restoring" a ledger correlation here, the way prune_spool_dir has
# one, would reintroduce exactly the race C-01 identified: a correction
# filed against a session whose OWN ledger clock has long since expired
# would no longer protect the file it is appending to.
#
# This pass is gated by ASSESSMENT_RETENTION_OK (its OWN preflight, wholly
# independent of MARKER_RETENTION_OK above) and ages from its OWN cutoff --
# assessment_cutoff_secs, computed from REVENIUM_ASSESSMENT_RETENTION_DAYS,
# never from the shared cutoff_secs the marker/flag/spool/ledger passes use.
# Two retention rules, two numbers, two reasons.
#
# Race-closing lock coordination (Greptile P1, PR #94 follow-up), the other
# half of the fix in correct-assessment.sh: this pass used to unlink a
# stale record with NO coordination at all -- os.unlink() here has never
# taken any lock, per-file or otherwise (the prune.lock held by fd 9 in the
# surrounding shell is global to the whole prune run, not scoped to any one
# sidecar). correct-assessment.sh now holds a per-sidecar flock(LOCK_EX)
# continuously from its D-14 existence check through its remote ship; for
# that lock to mean anything, this pass must take the SAME lock before it
# may unlink, or the two scripts are still just racing on an inode neither
# of them is actually coordinating on.
#
#   * O_RDONLY, non-blocking (LOCK_EX | LOCK_NB). A manual, human-triggered
#     prune must NEVER block waiting on an in-flight correction -- unlike
#     correct-assessment.sh's blocking acquisition (an operator filing a
#     correction may reasonably wait a moment for a concurrent prune to
#     finish its own per-file check), a prune run is a maintenance sweep
#     over potentially thousands of files, and stalling the whole sweep on
#     one busy record defeats the point of it being non-interactive.
#   * Busy -> skip THIS FILE ONLY and log it, then move on to the next
#     entry. A locked sidecar is, by construction, either being actively
#     corrected (which just refreshed or is about to refresh its mtime) or
#     about to be D-14-refused (which touches nothing) -- neither case
#     benefits from waiting, and D-13's own rule already says a live
#     correction is not stale.
#   * Staleness is DECIDED under the lock, not before it. The mtime read
#     happens via os.fstat(fd) AFTER flock() succeeds -- never via
#     os.path.getmtime(fpath) taken earlier (e.g. during the os.listdir()
#     scan or in a cached value) -- so a correction that lands between
#     "this file's name turned up in the directory listing" and "this
#     process actually acquired the lock" is what the unlink decision
#     sees, not a stale snapshot from before the file was reachable. This
#     is the specific half a pre-lock decision gets wrong: narrowing the
#     window between an early stat and a later unlink is not the same as
#     making the stat happen only once the lock guarantees nothing else
#     can be writing.
# ---------------------------------------------------------------------------

def prune_assessments_dir(assessments_dir, retention_secs, dry_run):
    a_scanned = a_kept = a_removed = a_skipped_busy = 0
    try:
        entries = sorted(os.listdir(assessments_dir))
    except FileNotFoundError:
        entries = []

    for fname in entries:
        if not fname.endswith('.jsonl'):
            continue
        fpath = os.path.join(assessments_dir, fname)
        if not os.path.isfile(fpath):
            continue

        a_scanned += 1

        try:
            fd = os.open(fpath, os.O_RDONLY)
        except OSError as exc:
            print('prune: ERROR opening ' + fname + ' for lock: ' + str(exc), flush=True)
            continue

        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, BlockingIOError):
                # Busy -- a correction is being filed against this record
                # right now (or is about to be D-14-refused). Not stale by
                # definition (D-13); skip without waiting, per the block
                # comment above.
                a_skipped_busy += 1
                print(
                    'prune: skipped (locked, correction in progress)' +
                    ' dir=job-assessments' +
                    ' assessment=' + fname,
                    flush=True,
                )
                continue

            # Re-stat UNDER the lock -- the authoritative staleness read.
            # fstat(fd) rather than getmtime(fpath): the fd was opened
            # before the lock and stays valid even if the path is later
            # unlinked by something else, so this always reflects the
            # inode this process is actually holding the lock on.
            try:
                mtime = os.fstat(fd).st_mtime
            except OSError as exc:
                print('prune: ERROR stating ' + fname + ': ' + str(exc), flush=True)
                continue
            age_secs = time.time() - mtime
            age_days = age_secs / 86400

            if age_secs < retention_secs:
                a_kept += 1
                continue

            action = 'dry-run, would remove' if dry_run else 'removed'
            print(
                'prune: ' + action +
                ' dir=job-assessments' +
                ' assessment=' + fname +
                ' mtime=' + iso(mtime) +
                ' age_days=' + str(round(age_days, 1)),
                flush=True,
            )

            if not dry_run:
                try:
                    os.unlink(fpath)
                    a_removed += 1
                except OSError as exc:
                    print('prune: ERROR removing ' + fname + ': ' + str(exc), flush=True)
                    sys.exit(1)
            else:
                a_removed += 1  # count for dry-run summary
        finally:
            os.close(fd)

    print(
        'prune: job-assessments summary, scanned=' + str(a_scanned) +
        ' kept=' + str(a_kept) +
        ' removed=' + str(a_removed) +
        ' skipped_busy=' + str(a_skipped_busy),
        flush=True,
    )
    return a_scanned, a_kept, a_removed


assessment_retention_ok = os.environ.get('ASSESSMENT_RETENTION_OK_PY') == 'true'
job_assessments_dir_py = os.environ.get('JOB_ASSESSMENTS_DIR_PY', '')

if assessment_retention_ok and job_assessments_dir_py:
    assessment_retention_days = int(os.environ['ASSESSMENT_RETENTION_DAYS_PY'])
    assessment_cutoff_secs = assessment_retention_days * 86400
    prune_assessments_dir(job_assessments_dir_py, assessment_cutoff_secs, dry_run)
PY
prune_rc=$?
set -e
while IFS= read -r log_line; do
  info "${log_line}"
done < "${prune_out}"
rm -f "${prune_out}"
if [[ "${prune_rc}" -ne 0 ]]; then
  warn "prune-markers: pruning failed (python exit ${prune_rc}); some stale markers may remain"
  exit "${prune_rc}"
fi
