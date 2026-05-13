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
"""
from decimal import Decimal


INT_FIELDS = ("input", "output", "cache_read", "cache_write", "total")
COST_FIELD = "cost"  # Decimal string in input; Decimal string in output


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
    # Cost field — Decimal arithmetic to 6 decimal places
    cost_raw = delta.get(COST_FIELD, "0")
    cost = Decimal(str(cost_raw))
    quant = Decimal("0.000001")
    per_cost = (cost / Decimal(n)).quantize(quant)
    for i in range(n):
        splits[i][COST_FIELD] = format(per_cost, "f")
    remainder_cost = cost - per_cost * n
    last_cost = (Decimal(splits[-1][COST_FIELD]) + remainder_cost).quantize(quant)
    splits[-1][COST_FIELD] = format(last_cost, "f")
    # Conservation check (Decimal-exact)
    assert sum(Decimal(s[COST_FIELD]) for s in splits) == cost, "conservation violated for cost"
    return splits


def parse_prior_state(ledger_path, sid, total_tokens):
    """Read ledger and return (prior_ts, prior_muids) for the (sid, total_tokens) key.

    ledger_path: str path to revenium-hermes.ledger
    sid: str Hermes session id (MUST NOT contain ':' — A2 mitigation)
    total_tokens: int cumulative total_tokens for this delta window

    Returns (prior_ts, prior_muids):
      - prior_ts: float, the cutoff timestamp for marker filtering. v2-takes-precedence
        per Pitfall D: when any v2 row exists for this sid, prior_ts is the MAX ts
        across all matching v2 rows; otherwise fall back to MAX ts across v1 rows
        for this sid. Returns 0.0 if no rows match this sid at all.
      - prior_muids: set[str], the UNION of field-5 values across all v2 rows
        matching (sid, total_tokens). Muids belonging to a DIFFERENT total_tokens
        are NOT included — they belong to a different delta window. Returns set()
        if no v2 rows match this (sid, total_tokens).

    Field-count discrimination (D-07/D-08/D-10):
      - 4 fields ("HERMES:<sid>:<total_tokens>:<ts>") = v1 row
      - 5 fields ("HERMES:<sid>:<total_tokens>:<ts>:<muid>") = v2 row, ONE muid

    Defense in depth (A2 mitigation): asserts `':' not in sid` so a future sid
    format change can't silently corrupt field-count discrimination.
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
                    row_total = int(parts[2])
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
                    # v2 row — one muid in field 5
                    has_v2 = True
                    if row_ts > v2_ts_max:
                        v2_ts_max = row_ts
                    if row_total == total_tokens:
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
