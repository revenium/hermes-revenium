"""Phase 44 Plan 04 (EGV-17) — the classified/unclassified/unallocated cost
partition and the reporter's per-tick reconciliation line.

Requirements covered:
  EGV-17 — "Existing job cost totals continue to reconcile across classified,
  unclassified, and unallocated cost."

Decisions this module exercises (44-CONTEXT.md):
  D-15 — the reconciliation is proven by a conservation test in the shape of
  test_split_strategies_conservation: per-field sums equal the input exactly,
  integers byte-exact and cost Decimal-exact, over the classified /
  unclassified / unallocated partition.

Planner assumptions this module is written against (44-04-PLAN.md):
  PA-09 — the partition DOES NOT EXIST as a coded concept anywhere in this
  repo prior to this plan (grep-confirmed absence of "unallocated" in
  hermes-report.sh). This is genuine new design work following the
  equal_split / test_split_strategies_conservation SHAPE, not a reuse of an
  existing implementation — test_split_strategies_conservation supplied only
  the assertion style.
  PA-10 — the partition is a pure function in split_strategies.py and the
  reporter's role is ACCUMULATE-ONLY: nothing in the metering decision path
  consults the accumulator; it feeds one `info` line in the existing
  end-of-run summary. ReporterReconciliationTests (added by Task 3) proves
  this at the wire.
"""
import random
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
SCRIPTS_DIR = SKILL / 'scripts'

sys.path.insert(0, str(SCRIPTS_DIR))
from split_strategies import (  # noqa: E402
    ATTRIBUTION_BUCKETS,
    COST_FIELD,
    INT_FIELDS,
    partition_by_attribution,
)

QUANT = Decimal("0.000001")
ZERO_COST_STR = format(Decimal("0").quantize(QUANT), "f")


def _row(bucket, **fields):
    delta = {
        "input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
        "total": 0, "cost": "0",
    }
    delta.update(fields)
    return (bucket, delta)


class CostPartitionConservationTests(unittest.TestCase):
    """Pure-function proof of partition_by_attribution's inverse conservation
    invariant. Mirrors test_split_strategies_conservation's shape (44-PATTERNS.md
    Pattern 8) applied to a genuinely new grouping — see PA-09 above."""

    def test_empty_row_set_yields_all_three_buckets_zeroed(self):
        result = partition_by_attribution([])
        self.assertEqual(list(result), list(ATTRIBUTION_BUCKETS))
        for bucket in ATTRIBUTION_BUCKETS:
            for k in INT_FIELDS:
                self.assertEqual(result[bucket][k], 0)
            self.assertEqual(result[bucket][COST_FIELD], ZERO_COST_STR)

    def test_single_row_lands_entirely_in_its_bucket(self):
        rows = [_row("classified", input=100, output=50, cache_read=10,
                      cache_write=5, total=150, cost="0.123456")]
        result = partition_by_attribution(rows)
        self.assertEqual(result["classified"]["input"], 100)
        self.assertEqual(result["classified"]["output"], 50)
        self.assertEqual(result["classified"]["cache_read"], 10)
        self.assertEqual(result["classified"]["cache_write"], 5)
        self.assertEqual(result["classified"]["total"], 150)
        self.assertEqual(result["classified"][COST_FIELD], "0.123456")
        for bucket in ("unclassified", "unallocated"):
            for k in INT_FIELDS:
                self.assertEqual(result[bucket][k], 0)
            self.assertEqual(result[bucket][COST_FIELD], ZERO_COST_STR)

    def test_two_rows_same_bucket_merge_by_summation(self):
        rows = [
            _row("unclassified", input=100, output=50, cache_read=0,
                 cache_write=0, total=150, cost="0.100000"),
            _row("unclassified", input=25, output=25, cache_read=1,
                 cache_write=1, total=50, cost="0.050000"),
        ]
        result = partition_by_attribution(rows)
        self.assertEqual(result["unclassified"]["input"], 125)
        self.assertEqual(result["unclassified"]["output"], 75)
        self.assertEqual(result["unclassified"]["cache_read"], 1)
        self.assertEqual(result["unclassified"]["cache_write"], 1)
        self.assertEqual(result["unclassified"]["total"], 200)
        self.assertEqual(
            Decimal(result["unclassified"][COST_FIELD]), Decimal("0.150000")
        )

    def test_order_independence_shuffled_rows_produce_identical_totals(self):
        rows = [
            _row("classified", input=8000, output=3000, cache_read=100,
                 cache_write=50, total=11000, cost="0.123456"),
            _row("unclassified", input=8001, output=3001, cache_read=101,
                 cache_write=51, total=11003, cost="0.987654"),
            _row("unallocated", input=35372, output=212, cache_read=0,
                 cache_write=0, total=35584, cost="0.0119093"),
            _row("classified", input=1, output=1, cache_read=1, cache_write=1,
                 total=2, cost="0.000001"),
            _row("unallocated", input=99, output=1, cache_read=0, cache_write=0,
                 total=100, cost="0.5"),
        ]
        baseline = partition_by_attribution(rows)

        shuffled = list(rows)
        random.Random(44).shuffle(shuffled)
        self.assertNotEqual(
            [r[0] for r in shuffled], [r[0] for r in rows],
            "fixture is not actually testing order-independence — shuffle produced "
            "the original order",
        )
        shuffled_result = partition_by_attribution(shuffled)

        self.assertEqual(baseline, shuffled_result)

    def test_conservation_holds_more_rows_than_buckets_and_an_empty_bucket(self):
        """N > 3 rows, and one bucket (unallocated) receives no rows at all."""
        cases_seed = [
            {"input": 8000, "output": 3000, "cache_read": 100, "cache_write": 50,
             "total": 11000, "cost": "0.123456"},
            {"input": 8001, "output": 3001, "cache_read": 101, "cache_write": 51,
             "total": 11003, "cost": "0.987654"},
            {"input": 35372, "output": 212, "cache_read": 0, "cache_write": 0,
             "total": 35584, "cost": "0.0119093"},
            {"input": 1, "output": 2, "cache_read": 3, "cache_write": 4,
             "total": 5, "cost": "0.000001"},
        ]
        buckets_cycle = ["classified", "classified", "unclassified", "classified"]
        rows = [
            (buckets_cycle[i], cases_seed[i]) for i in range(len(cases_seed))
        ]
        result = partition_by_attribution(rows)

        # unallocated received no rows -- present, all zero.
        for k in INT_FIELDS:
            self.assertEqual(result["unallocated"][k], 0)
        self.assertEqual(result["unallocated"][COST_FIELD], ZERO_COST_STR)

        for k in INT_FIELDS:
            grand_total = sum(delta[k] for _, delta in rows)
            bucket_sum = sum(result[b][k] for b in ATTRIBUTION_BUCKETS)
            self.assertEqual(
                bucket_sum, grand_total,
                f"conservation violated for {k}",
            )
        grand_cost = sum(
            Decimal(str(delta[COST_FIELD])).quantize(QUANT) for _, delta in rows
        )
        bucket_cost_sum = sum(
            Decimal(result[b][COST_FIELD]) for b in ATTRIBUTION_BUCKETS
        )
        self.assertEqual(bucket_cost_sum, grand_cost, "cost conservation violated")

    def test_unknown_bucket_raises_value_error_naming_the_bucket(self):
        with self.assertRaises(ValueError) as ctx:
            partition_by_attribution([_row("bogus", total=1, cost="1")])
        self.assertIn("bogus", str(ctx.exception))

    def test_missing_delta_field_defaults_like_equal_split(self):
        result = partition_by_attribution([("classified", {})])
        for k in INT_FIELDS:
            self.assertEqual(result["classified"][k], 0)
        self.assertEqual(result["classified"][COST_FIELD], ZERO_COST_STR)

    def test_bucket_keys_iterate_in_declaration_order(self):
        result = partition_by_attribution([])
        self.assertEqual(list(result.keys()), list(ATTRIBUTION_BUCKETS))

    def test_non_divisible_six_decimal_cost_round_trips_without_drift(self):
        """Same cost shapes test_split_strategies_conservation uses, including
        the G-04 regression case (> 6 decimal places, e.g. qwen3.6-plus's
        0.0119093) and a non-divisible-by-N case."""
        rows = [
            _row("classified", cost="0.123456"),
            _row("classified", cost="0.987654"),
            _row("unclassified", cost="0.0119093"),
        ]
        result = partition_by_attribution(rows)
        grand_cost = sum(
            Decimal(str(delta[COST_FIELD])).quantize(QUANT) for _, delta in rows
        )
        bucket_cost_sum = sum(
            Decimal(result[b][COST_FIELD]) for b in ATTRIBUTION_BUCKETS
        )
        self.assertEqual(bucket_cost_sum, grand_cost)
        # 0.0119093 quantized to 6dp is 0.011909 -- confirm no silent truncation
        # produced a value that merely "rounds to the same cents".
        self.assertEqual(
            Decimal(result["unclassified"][COST_FIELD]),
            Decimal("0.0119093").quantize(QUANT),
        )


if __name__ == '__main__':
    unittest.main()
