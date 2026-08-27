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
from decimal import Decimal


INT_FIELDS = ("input", "output", "cache_read", "cache_write", "total")
COST_FIELD = "cost"  # Decimal string in input; Decimal string in output

ATTRIBUTION_BUCKETS = ("classified", "unclassified", "unallocated")


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
