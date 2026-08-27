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
import json
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
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

from tests._compat_helpers import build_shim, build_state_db  # noqa: E402

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


class ReporterReconciliationTests(unittest.TestCase):
    """Drives the real hermes-report.sh over a synthetic state.db containing
    one marker-split (classified) session and one markerless (unclassified)
    session, and proves the per-tick reconciliation line: (1) present
    exactly once when rows were observed, and absent for a quiet tick, (2)
    its three bucket cost totals sum to the tick's total metered cost
    (Decimal, assertEqual, never assertAlmostEqual), and (3) the classified
    and unclassified totals individually match the same run's own
    `Reported:` lines, proving the accumulator reads the numbers the
    metering path used rather than a parallel derivation. A fourth,
    negative case proves PA-10's accumulate-only rule at the wire: the argv
    for a session shared across two runs -- one where it is the only
    session, one where a second session also populates the accumulator --
    is byte-identical.

    PA-09 (recorded here in substance, per the plan's Task 3 instruction):
    this partition is new design work for Phase 44, not a reuse of an
    existing implementation. test_split_strategies_conservation supplied
    only the assertion STYLE (byte-exact ints, Decimal-exact cost,
    sum-equals-input) -- the classified/unclassified/unallocated grouping
    itself did not exist anywhere in this repo before this plan.
    """

    def _run_tick(self, sessions, write_marker_for=None):
        """Runs hermes-report.sh over `sessions` (list of state.db session
        dicts). write_marker_for: set of session ids that get a task marker
        (classified path); sessions not in that set take the markerless
        path. Returns (returncode, meter_invocations, combined_output)."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase44-cost-partition-')
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)

        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        markers_dir = os.path.join(state_dir, 'markers')
        os.makedirs(markers_dir, mode=0o700)
        state_db = os.path.join(hermes_home, 'state.db')

        shim_home = os.path.join(tmpdir, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)
        meter_log = os.path.join(tmpdir, 'meter.log')
        jobs_log = os.path.join(tmpdir, 'jobs.log')
        inv_log = os.path.join(tmpdir, 'inv.log')
        shim = os.path.join(bin_dir, 'revenium')

        build_state_db(state_db, sessions)

        write_marker_for = write_marker_for or set()
        for sess in sessions:
            if sess['id'] in write_marker_for:
                task_marker = {
                    'muid': f"muid-{sess['id']}",
                    'ts': sess['started_at'] + 500,
                    'sid': sess['id'],
                    'task_type': 'code_review',
                    'operation_type': 'CHAT',
                }
                with open(os.path.join(markers_dir, f"{sess['id']}.jsonl"), 'w') as f:
                    f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')

        build_shim(shim)

        env = {
            **os.environ,
            'HOME': shim_home,
            'HERMES_HOME': hermes_home,
            'REVENIUM_STATE_DIR': state_dir,
            'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': inv_log,
            'METER_LOG': meter_log,
            'JOBS_LOG': jobs_log,
            'TZ': 'UTC',
            'REVENIUM_ORGANIZATION_NAME': '',
        }

        result = subprocess.run(
            ['bash', str(SCRIPTS_DIR / 'hermes-report.sh')],
            env=env, capture_output=True, text=True, timeout=60,
        )

        meter_invocations = []
        if os.path.exists(meter_log):
            with open(meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        meter_invocations.append(shlex.split(line))

        # common.sh's log()/info() append to LOG_FILE unconditionally and
        # mirror to stderr ONLY when stderr is a TTY -- a non-interactive
        # subprocess run never sees `info` lines on stdout/stderr, so the
        # reconciliation line must be read from the metering log itself.
        metering_log = os.path.join(state_dir, 'revenium-metering.log')
        log_content = ''
        if os.path.exists(metering_log):
            with open(metering_log) as f:
                log_content = f.read()

        return (
            result.returncode,
            meter_invocations,
            result.stdout + result.stderr + log_content,
        )

    def _base_session(self, sid, cost, tokens_in=100, tokens_out=50):
        return {
            'id': sid,
            'model': 'claude-sonnet-4-6',
            'source': 'test',
            'input_tokens': tokens_in,
            'output_tokens': tokens_out,
            'cache_read': 0,
            'cache_write': 0,
            'reasoning': 0,
            'estimated_cost': cost,
            'api_calls': 1,
            'started_at': 1715514000.0,
            'ended_at': 1715514000.0,
            'billing_provider': 'anthropic',
        }

    def test_reconciliation_line_present_once_and_sums_match(self):
        classified_sid = 'phase44-cp-classified-001'
        unclassified_sid = 'phase44-cp-unclassified-001'
        sessions = [
            self._base_session(classified_sid, '0.100000'),
            self._base_session(unclassified_sid, '0.050000'),
        ]
        rc, invocations, output = self._run_tick(
            sessions, write_marker_for={classified_sid}
        )
        self.assertEqual(rc, 0, f"hermes-report.sh failed: {output}")
        self.assertEqual(len(invocations), 2, f"expected 2 meter completions: {output}")

        recon_lines = [
            line for line in output.splitlines() if 'cost reconciliation' in line
        ]
        self.assertEqual(
            len(recon_lines), 1,
            f"expected exactly one reconciliation line for a tick with observed "
            f"rows, got {len(recon_lines)}: {output}",
        )
        recon_line = recon_lines[0]

        def _extract(bucket):
            # \b guards against "classified" matching inside "unclassified"
            # since the latter contains the former as a literal substring.
            m = re.search(r'\b' + bucket + r'=([0-9.]+)', recon_line)
            self.assertIsNotNone(
                m, f"{bucket} total missing from reconciliation line: {recon_line}"
            )
            return Decimal(m.group(1))

        classified_total = _extract('classified')
        unclassified_total = _extract('unclassified')
        unallocated_total = _extract('unallocated')

        reported_costs = []
        for inv in invocations:
            if '--total-cost' in inv:
                reported_costs.append(Decimal(inv[inv.index('--total-cost') + 1]))
        tick_total_cost = sum(reported_costs, Decimal('0'))

        self.assertEqual(
            classified_total + unclassified_total + unallocated_total,
            tick_total_cost.quantize(QUANT),
            "reconciliation bucket totals do not sum to the tick's metered cost",
        )

        # classified/unclassified totals individually match the per-session
        # Reported: lines the same run emitted -- proves the accumulator is
        # reading the SAME numbers the metering path used, not a parallel
        # derivation.
        self.assertIn(
            f"session={classified_sid} muid=", output,
            f"no per-marker Reported: line found for {classified_sid}: {output}",
        )
        self.assertIn(
            f"session={unclassified_sid} task_type=unclassified", output,
            f"no markerless Reported: line found for {unclassified_sid}: {output}",
        )
        self.assertEqual(classified_total, Decimal('0.100000'))
        self.assertEqual(unclassified_total, Decimal('0.050000'))

    def test_reconciliation_line_absent_for_a_quiet_tick(self):
        rc, invocations, output = self._run_tick([])
        self.assertEqual(len(invocations), 0)
        recon_lines = [
            line for line in output.splitlines() if 'cost reconciliation' in line
        ]
        self.assertEqual(
            recon_lines, [],
            f"a tick observing no rows must stay quiet: {output}",
        )

    def test_reconciliation_presence_does_not_change_shared_argv(self):
        """PA-10's accumulate-only rule, executable form: the argv for a
        session shared across two runs (one with only that session, one with
        an additional session that also populates the accumulator) is
        byte-identical."""
        shared_sid = 'phase44-cp-shared-001'
        other_sid = 'phase44-cp-other-001'

        rc1, inv1, out1 = self._run_tick(
            [self._base_session(shared_sid, '0.200000')],
            write_marker_for={shared_sid},
        )
        self.assertEqual(rc1, 0, out1)
        self.assertEqual(len(inv1), 1)

        rc2, inv2, out2 = self._run_tick(
            [
                self._base_session(shared_sid, '0.200000'),
                self._base_session(other_sid, '0.075000'),
            ],
            write_marker_for={shared_sid},
        )
        self.assertEqual(rc2, 0, out2)
        self.assertEqual(len(inv2), 2)

        shared_argv_1 = inv1[0]
        shared_argv_2 = next(
            inv for inv in inv2
            if '--transaction-id' in inv
            and shared_sid in inv[inv.index('--transaction-id') + 1]
        )
        self.assertEqual(
            shared_argv_1, shared_argv_2,
            "the shared session's argv must be byte-identical whether or not "
            "the accumulator was also populated by another session this tick",
        )


if __name__ == '__main__':
    unittest.main()
