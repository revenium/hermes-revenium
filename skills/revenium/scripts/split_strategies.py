"""Pluggable split strategies for Hermes-Revenium marker-aware metering.

Each strategy takes a delta dict {input, output, cache_read, cache_write, total, cost}
and an N (number of markers), and returns a list of N dicts whose per-field
values sum exactly to the input.

Conservation invariant: for every field key K,
    sum(s[K] for s in result) == delta[K]
This is asserted byte-exact for integer fields (tokens) and Decimal-exact for cost.

Future strategies (deferred to v2 per PROJECT.md decision 5):
    def weighted_split(delta_fields, markers_with_length_hints) -> list[dict]
    def guardrail_estimator_split(delta_fields, markers, guardrail_share_estimator) -> list[dict]

This module also exposes parse_prior_state, a shared reader helper for the
revenium-hermes.ledger file. Both hermes-report.sh (via Python heredoc) and
tests/test_repository.py invoke it directly so production logic and tests are
load-bearing on the same code path.

Three more helpers live here for the same reason (one implementation, called
from the bash heredocs and from the tests):

    collapse_classification_pairs -- folds each GUARDRAIL+CHAT marker pair the
        classifier writes into the single completion it represents.
    resolve_trace_name            -- the --trace-name for a root session's marker
        file (job name, else first task type).
    latest_transaction_id         -- rebuilds the wire transaction id of a
        session's most recent main-loop completion from the ledger, for
        --parent-transaction-id.

Phase 44 Plan 04 (EGV-17/D-15) adds a second, INVERSE conservation invariant
owned by this file: equal_split() conserves DOWNWARD — one observed delta is
split across N markers, and the N parts sum back to the whole. partition_by_
attribution() conserves UPWARD — N observed rows are merged into exactly
three attribution buckets, and the three buckets sum back to the row-set
total. Both are asserted byte-exact for integer fields and Decimal-exact for
cost, at the same Decimal("0.000001") quantum.

The three buckets, in ATTRIBUTION_BUCKETS declaration order:
    classified   -- metered cost the reporter split across real markers
                    carrying an attribution.
    unclassified -- metered cost on a session with no marker at all -- the
                    existing synthetic unclassified-<epoch> markerless path.
    unallocated  -- metered cost the reporter observed but did not attribute
                    this tick -- a row whose report attempt did not result in
                    a ledger line.
"""
import json
import re
from decimal import Decimal


INT_FIELDS = ("input", "output", "cache_read", "cache_write", "total")
COST_FIELD = "cost"  # Decimal string in input; Decimal string in output

ATTRIBUTION_BUCKETS = ("classified", "unclassified", "unallocated")

# A muid is written into a colon-delimited ledger line, so an absorbed muid
# (one that is never shipped itself and is therefore never read back from the
# survivor's own pipe row) must be provably free of ':' and whitespace before
# it is allowed anywhere near the ledger. The classifier's muids are hex.
_SAFE_MUID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

# The markerless emit path ledgers a synthetic muid with this prefix. Its wire
# transaction id has no muid segment (see latest_transaction_id).
SYNTHETIC_MUID_PREFIX = "unclassified-"

# Marker fields that must agree for a GUARDRAIL marker and a CHAT marker to be
# the two halves of ONE classification. The classifier writes them back to
# back under one lock from a single call, so they share all of these; anything
# that differs is two separate classifications that merely sit side by side.
PAIR_FIELDS = ("sid", "task_type", "trace_id", "agentic_job_id", "agent")

TRACE_NAME_MAX_CHARS = 128

# Mirrors the reader heredoc's FORBIDDEN set in hermes-report.sh: a marker with
# one of these task types is never shipped, so it must never name a trace.
_TRIVIAL_TASK_TYPES = frozenset(
    ("ack", "acknowledgment", "greeting", "confirmation", "hello", "thanks")
)
_TASK_MARKER_KEYS = ("muid", "ts", "sid", "task_type", "operation_type")
# pre_tool_call.sh writes a synthetic CANCELLED job marker with this id prefix
# when a guardrail halts an arc. It describes the halt, not the work, so it must
# not rename a trace that already has a real job name.
_HALT_JOB_ID_PREFIX = "guardrail-halt-"


def equal_split(delta: dict, n: int) -> list:
    """Split delta equally across n markers; last marker absorbs remainder.

    delta: {"input": int, "output": int, "cache_read": int, "cache_write": int,
            "total": int, "cost": str (Decimal-parseable)}
    n: positive int

    Returns: list of n dicts with the same keys; integer fields use //
    division with remainder on the last marker; cost is Decimal-quantized
    to 6 decimal places with remainder on the last marker.

    Conservation invariant (asserted byte-exact for ints, Decimal-exact for cost):
        for every key K, sum(s[K] for s in result) == delta[K]
    """
    if n < 1:
        raise ValueError("n must be >= 1; got {0}".format(n))
    splits = [{} for _ in range(n)]
    # Integer fields
    for k in INT_FIELDS:
        v = int(delta.get(k, 0))
        per = v // n
        for i in range(n):
            splits[i][k] = per
        splits[-1][k] += v - per * n  # remainder absorbed by last marker
        assert sum(s[k] for s in splits) == v, "conservation violated for {0}".format(k)
    # Cost field — Decimal arithmetic to 6 decimal places.
    # Quantize the input cost up-front so per_cost, remainder, and last_cost
    # all share the same 6-decimal grid. Without this, an input cost with > 6
    # decimal places (e.g. "0.0119093" from qwen3.6-plus) loses its 7th digit
    # in the last_cost quantize step and the conservation invariant fails.
    cost_raw = delta.get(COST_FIELD, "0")
    quant = Decimal("0.000001")
    cost = Decimal(str(cost_raw)).quantize(quant)
    per_cost = (cost / Decimal(n)).quantize(quant)
    for i in range(n):
        splits[i][COST_FIELD] = format(per_cost, "f")
    remainder_cost = cost - per_cost * n
    last_cost = Decimal(splits[-1][COST_FIELD]) + remainder_cost
    splits[-1][COST_FIELD] = format(last_cost, "f")
    # Conservation check (Decimal-exact against the quantized input)
    assert sum(Decimal(s[COST_FIELD]) for s in splits) == cost, "conservation violated for cost"
    return splits


def partition_by_attribution(rows) -> dict:
    """Partition observed metered-cost rows into three attribution buckets.

    rows: an iterable of (bucket, delta) pairs. bucket MUST be a member of
    ATTRIBUTION_BUCKETS ("classified", "unclassified", "unallocated"); delta
    is a dict shaped like equal_split's own input ({"input": int, "output":
    int, "cache_read": int, "cache_write": int, "total": int, "cost": str
    (Decimal-parseable)}).

    Returns a dict keyed by every member of ATTRIBUTION_BUCKETS, always all
    three, always in ATTRIBUTION_BUCKETS declaration order, even when a
    bucket received no rows (its totals are all-zero, not absent). A missing
    field in a delta defaults to 0 for an integer field and "0" for cost,
    matching equal_split's own delta.get(k, 0) tolerance.

    Conservation invariant (the inverse of equal_split's, asserted
    byte-exact for INT_FIELDS and Decimal-exact for COST_FIELD, both
    internally before returning and by the external conservation test):
        for every key K,
            sum(result[b][K] for b in ATTRIBUTION_BUCKETS) == sum(delta[K] for _, delta in rows)

    A row naming a bucket outside ATTRIBUTION_BUCKETS raises ValueError
    naming the offending value -- never a silent drop and never a fallback
    bucket, because a dropped row is exactly what would make totals
    reconcile falsely, which is the failure EGV-17's reconciliation clause
    exists to prevent.
    """
    quant = Decimal("0.000001")
    zero_cost = Decimal("0").quantize(quant)

    int_totals = {bucket: {k: 0 for k in INT_FIELDS} for bucket in ATTRIBUTION_BUCKETS}
    cost_totals = {bucket: zero_cost for bucket in ATTRIBUTION_BUCKETS}

    grand_int_totals = {k: 0 for k in INT_FIELDS}
    grand_cost_total = zero_cost

    for bucket, delta in rows:
        if bucket not in ATTRIBUTION_BUCKETS:
            raise ValueError(
                "unknown attribution bucket: {0!r} (must be one of {1})".format(
                    bucket, ATTRIBUTION_BUCKETS
                )
            )
        for k in INT_FIELDS:
            v = int(delta.get(k, 0))
            int_totals[bucket][k] += v
            grand_int_totals[k] += v
        cost = Decimal(str(delta.get(COST_FIELD, "0"))).quantize(quant)
        cost_totals[bucket] += cost
        grand_cost_total += cost

    result = {}
    for bucket in ATTRIBUTION_BUCKETS:
        result[bucket] = {k: int_totals[bucket][k] for k in INT_FIELDS}
        result[bucket][COST_FIELD] = format(cost_totals[bucket], "f")

    for k in INT_FIELDS:
        assert (
            sum(int_totals[b][k] for b in ATTRIBUTION_BUCKETS) == grand_int_totals[k]
        ), "conservation violated for {0}".format(k)
    assert (
        sum(cost_totals[b] for b in ATTRIBUTION_BUCKETS) == grand_cost_total
    ), "conservation violated for cost"

    return result


def parse_prior_state(ledger_path, sid, total_tokens):
    """Read ledger and return (prior_ts, prior_muids) for sid.

    ledger_path: str path to revenium-hermes.ledger
    sid: str Hermes session id (MUST NOT contain ':' — A2 mitigation)
    total_tokens: int cumulative total_tokens for the current delta window
                  (kept in the signature for forward compatibility but no
                  longer narrows prior_muids — see below).

    Returns (prior_ts, prior_muids):
      - prior_ts: float, the latest ledger timestamp seen for this sid.
        v2-takes-precedence per Pitfall D: when any v2 row exists for this sid,
        prior_ts is the MAX ts across all v2 rows for this sid; otherwise fall
        back to MAX ts across v1 rows for this sid. Returns 0.0 if no rows
        match this sid at all. Used for v1-fallback marker filtering only.
      - prior_muids: set[str], the GLOBAL set of all field-5 muids across all
        v2 rows for this sid — across every total_tokens window, not just the
        current one. This makes partial-failure recovery (COMPAT-03 / SC2)
        correct: muids 1-3 of a 5-marker batch that crashed between calls 3
        and 5 stay in this set forever, and muids 4-5 (never written to the
        ledger) stay OUT of this set, so the cron emits them on the next tick
        regardless of the new total_tokens.

    Field-count discrimination (D-07/D-08/D-10):
      - 4 fields ("HERMES:<sid>:<total_tokens>:<ts>") = v1 row
      - 5 fields ("HERMES:<sid>:<total_tokens>:<ts>:<muid>") = v2 row, ONE muid

    Defense in depth (A2 mitigation): asserts `':' not in sid` so a future sid
    format change can't silently corrupt field-count discrimination.

    History note: an earlier draft narrowed prior_muids to the exact
    (sid, total_tokens) window. Testing T08's partial-failure recovery
    showed that combined with the cron's ts-based marker filter, that
    narrower scope made SC2 unachievable — markers 4-5 of a partial-failure
    batch have ts < the successful ledger rows' ts and were wrongly skipped.
    Global muid dedup is sufficient (any muid that ever made it to the
    ledger never repeats) and lets the cron drop the ts filter for v2
    sessions, which is the simpler invariant.
    """
    assert ':' not in sid, "sid must not contain ':' (would corrupt field-count discrimination)"

    v1_ts_max = 0.0
    v2_ts_max = 0.0
    has_v2 = False
    prior_muids = set()

    try:
        with open(ledger_path) as f:
            for line in f:
                line = line.rstrip('\n')
                if not line:
                    continue
                if not line.startswith("HERMES:"):
                    continue
                parts = line.split(':')
                # Field shape: ["HERMES", sid, total_tokens, ts] (v1) or
                #              ["HERMES", sid, total_tokens, ts, muid] (v2)
                if len(parts) < 4:
                    continue
                row_sid = parts[1]
                if row_sid != sid:
                    continue
                try:
                    int(parts[2])
                except (TypeError, ValueError):
                    continue
                try:
                    row_ts = float(parts[3])
                except (TypeError, ValueError):
                    continue
                if len(parts) == 4:
                    # v1 row
                    if row_ts > v1_ts_max:
                        v1_ts_max = row_ts
                elif len(parts) == 5:
                    # v2 row — one muid in field 5; collect across ALL total_tokens
                    has_v2 = True
                    if row_ts > v2_ts_max:
                        v2_ts_max = row_ts
                    muid = parts[4]
                    if muid:
                        prior_muids.add(muid)
                # parts > 5 = malformed; ignore defensively (no production writer produces this)
    except FileNotFoundError:
        return (0.0, set())
    except OSError:
        return (0.0, set())

    if has_v2:
        prior_ts = v2_ts_max
    else:
        prior_ts = v1_ts_max
    return (prior_ts, prior_muids)


def is_classification_pair(first, second):
    """True when `first` and `second` are the two halves of ONE classification.

    The classifier records every classification as a GUARDRAIL marker followed
    immediately by a CHAT marker (classifier.py::_write_marker_pair): same
    session, same task_type, same trace, same inherited job, written under one
    lock. They exist so a classification leaves two markers, but the tokens
    they sit over are one stretch of chat work, not two.
    """
    if first.get("operation_type") != "GUARDRAIL":
        return False
    if second.get("operation_type") != "CHAT":
        return False
    for key in PAIR_FIELDS:
        if first.get(key, "") != second.get(key, ""):
            return False
    return True


def collapse_classification_pairs(tasks):
    """Collapse each GUARDRAIL+CHAT classification pair into one shippable marker.

    tasks: list of (marker_dict, eligible) in FILE ORDER, one entry for every
    valid task marker in the file -- eligible (not yet ledgered, not filtered)
    or not. Adjacency is judged over ALL of them, because a pair whose one
    half was already ledgered under the old pair scheme is not a pair any more.

    Returns the eligible markers to ship, in file order:

      * An adjacent eligible GUARDRAIL+CHAT pair becomes ONE marker -- the CHAT
        one -- carrying `absorbed_muids`: [<the GUARDRAIL muid>]. The caller
        ships one completion for it and must ledger every absorbed muid with
        the same call (absorbed lines first, the survivor LAST), or the next
        tick sees the absorbed marker as unreported and ships it again.
      * An eligible GUARDRAIL marker whose CHAT twin is NOT eligible (already
        ledgered by a pre-collapse tick whose second call failed) is a
        remainder of the old scheme. It is shipped alone, relabelled CHAT: its
        twin went out as CHAT, so a lone GUARDRAIL row would be the only one
        of its classification.
      * Every other marker, including a GUARDRAIL marker with no CHAT twin at
        all (a hand-written or genuinely lone classification marker), passes
        through unchanged.

    The returned dicts are the input dicts, mutated: `absorbed_muids` is set on
    survivors only, and any `absorbed_muids` key that arrived inside a marker
    FILE is dropped first -- that key is this function's output, never input.

    Conservation: nothing here touches tokens or cost. The caller splits the
    session delta across the RETURNED markers, so the per-field sums still
    equal the delta exactly; fewer markers means a larger share each, never a
    smaller total.
    """
    for marker, _eligible in tasks:
        marker.pop("absorbed_muids", None)

    absorbed = set()      # id() of GUARDRAIL markers folded into their twin
    relabel = set()       # id() of GUARDRAIL markers shipped alone as CHAT
    for i in range(len(tasks) - 1):
        first, first_ok = tasks[i]
        second, second_ok = tasks[i + 1]
        if not first_ok or id(first) in absorbed:
            continue
        if not is_classification_pair(first, second):
            continue
        if second_ok:
            muid = first.get("muid")
            if isinstance(muid, str) and _SAFE_MUID_RE.match(muid):
                second["absorbed_muids"] = [muid]
                absorbed.add(id(first))
            # An unsafe muid cannot be ledgered by proxy, so the pair is left
            # alone and both halves ship exactly as they did before.
        else:
            relabel.add(id(first))

    shipped = []
    for marker, eligible in tasks:
        if not eligible or id(marker) in absorbed:
            continue
        if id(marker) in relabel:
            marker["operation_type"] = "CHAT"
        shipped.append(marker)
    return shipped


def _clean_trace_name(value):
    """One line, single-spaced, bounded -- safe as an argv value and as a
    KEY=value heredoc line (no newline survives to forge a second key)."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:TRACE_NAME_MAX_CHARS].strip()


def resolve_trace_name(markers_path):
    """The name a trace should carry, from its ROOT session's marker file.

    Returns "" when nothing usable exists, and the caller then omits the flag.
    Never raises: a missing, unreadable or corrupt file is "no name".

    Rule, chosen so every transaction in one trace carries the same name:
      1. the job_name of the LATEST kind:"job" marker that has one -- the same
         record the trace-type resolution reads its job_type from, so a trace's
         name and type describe the same job. A synthetic guardrail-halt job is
         skipped: it describes the halt, not the work.
      2. else the task_type of the FIRST valid task marker (append-only, so it
         cannot drift as the session grows).
    Both the main-loop and the auxiliary pass resolve through this function, so
    they cannot disagree about a session's name.
    """
    job_name = ""
    first_task = ""
    try:
        with open(markers_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict):
                    continue
                kind = rec.get("kind")
                if kind == "job":
                    job_id = rec.get("agentic_job_id")
                    if isinstance(job_id, str) and job_id.startswith(_HALT_JOB_ID_PREFIX):
                        continue
                    name = _clean_trace_name(rec.get("job_name"))
                    if name:
                        job_name = name
                elif kind is None and not first_task:
                    if not all(k in rec for k in _TASK_MARKER_KEYS):
                        continue
                    label = rec.get("task_type")
                    if isinstance(label, str) and label not in _TRIVIAL_TASK_TYPES:
                        first_task = _clean_trace_name(label)
    except (OSError, UnicodeDecodeError):
        return ""
    return job_name or first_task


def latest_transaction_id(ledger_path, sid):
    """The wire transaction id of the most recent main-loop completion shipped
    for `sid`, or "" when there is none this install can name.

    This is the id a child row (a subagent completion, an auxiliary row) sends
    as --parent-transaction-id. It is rebuilt from the ledger, never guessed:
    a ledger line is only written after its CLI call succeeded, so the id it
    names is one Revenium has accepted.

    Ledger line -> wire id (the two shapes hermes-report.sh ships; do not
    unify them, the golden fixtures pin both):
      HERMES:<sid>:<total>:<ts>:<muid>           -> <sid>-<total>-<muid>
      HERMES:<sid>:<total>:<ts>:unclassified-N   -> <sid>-<total>   (markerless)
      HERMES:<sid>:<total>:<ts>                  -> <sid>-<total>   (v1 row)

    The LAST matching line wins. A pair collapsed into one call ledgers the
    absorbed muid first and the shipped one last, so "last" is the real
    transaction. The prefix test is exact and the remainder is validated, so a
    session id that is a colon-prefix of another cannot borrow its lines.
    """
    prefix = "HERMES:" + sid + ":"
    latest = ""
    try:
        with open(ledger_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.startswith(prefix):
                    continue
                parts = line[len(prefix):].rstrip("\n").split(":")
                if len(parts) not in (2, 3):
                    continue
                try:
                    total = int(parts[0])
                    float(parts[1])
                except ValueError:
                    continue
                muid = parts[2] if len(parts) == 3 else ""
                if not muid or muid.startswith(SYNTHETIC_MUID_PREFIX):
                    latest = "{0}-{1}".format(sid, total)
                else:
                    latest = "{0}-{1}-{2}".format(sid, total, muid)
    except OSError:
        return ""
    return latest
