"""Phase 55 Plan 01 (ROI-09/ROI-11) -- the auxiliary-usage metering tracer.

Drives the REAL hermes-report.sh against a synthetic state.db carrying both
a `sessions` row (the existing main-loop source) and a `session_model_usage`
row (the new auxiliary-usage source this plan wires up for the first time).
Proves the full slice end to end: one auxiliary row ships as its own
`revenium meter completion --operation-type AUX`, records itself in
`revenium-aux.ledger`, and a second tick over the unchanged fixture is a
no-op.

Harness shape copied from tests/test_compat_meter_completion.py (the
PATH-shim + state.db + shlex round-trip idiom); extended with
build_session_model_usage (tests/_compat_helpers.py) to seed the new table.

Task 3 (this same module) adds the two byte-identical arms required by
ROADMAP criterion 4: the operator off switch (D-01) and an install whose
Hermes predates session_model_usage entirely (D-07).
"""
import os
import shlex
import shutil
import tempfile
import unittest

from tests._compat_helpers import (
    argv_to_flags,
    assert_argv_matches_golden,
    build_session_model_usage,
    build_shim,
    build_state_db,
    load_golden,
    run_script,
    SCRIPTS_DIR,
)


class _AuxMeteringTestCase(unittest.TestCase):
    """Shared fixture-DB + PATH-shim harness.

    _setup_fixture() creates the state.db + shim ONCE; _tick() re-invokes
    hermes-report.sh against that SAME state_dir/state_db as many times as a
    test needs (idempotency / multi-tick tests), with a fresh meter/jobs/
    invocations log per tick so each tick's OWN invocation count is
    countable independent of prior ticks.
    """

    def _setup_fixture(self, sessions, aux_rows=None):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase55-aux-')
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)

        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        markers_dir = os.path.join(state_dir, 'markers')
        os.makedirs(markers_dir, mode=0o700)
        state_db = os.path.join(hermes_home, 'state.db')

        shim_home = os.path.join(tmpdir, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)
        shim = os.path.join(bin_dir, 'revenium')

        build_state_db(state_db, sessions)
        if aux_rows is not None:
            build_session_model_usage(state_db, aux_rows)
        build_shim(shim)

        return {
            'tmpdir': tmpdir,
            'hermes_home': hermes_home,
            'state_dir': state_dir,
            'state_db': state_db,
            'shim_home': shim_home,
            'bin_dir': bin_dir,
        }

    def _tick(self, fixture, tick_index=0, extra_env=None):
        meter_log = os.path.join(fixture['tmpdir'], f'meter-{tick_index}.log')
        jobs_log = os.path.join(fixture['tmpdir'], f'jobs-{tick_index}.log')
        inv_log = os.path.join(fixture['tmpdir'], f'inv-{tick_index}.log')

        base_env = {
            **os.environ,
            'HOME': fixture['shim_home'],
            'HERMES_HOME': fixture['hermes_home'],
            'REVENIUM_STATE_DIR': fixture['state_dir'],
            'PATH': fixture['bin_dir'] + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': inv_log,
            'METER_LOG': meter_log,
            'JOBS_LOG': jobs_log,
            'TZ': 'UTC',
        }
        if extra_env:
            base_env.update(extra_env)

        rc, _ignored, output = run_script(
            SCRIPTS_DIR / 'hermes-report.sh', base_env, inv_log
        )

        meter_invocations = []
        if os.path.exists(meter_log):
            with open(meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        meter_invocations.append(shlex.split(line))

        return {'rc': rc, 'output': output, 'meter_invocations': meter_invocations}

    @staticmethod
    def _aux_ledger_path(fixture):
        return os.path.join(fixture['state_dir'], 'revenium-aux.ledger')

    @staticmethod
    def _one_session(**overrides):
        base = {
            'id': 'aux-sid-001',
            'model': 'claude-sonnet-4-6',
            'source': 'test',
            'input_tokens': 100,
            'output_tokens': 50,
            'cache_read': 0,
            'cache_write': 0,
            'reasoning': 0,
            'estimated_cost': '0',
            'api_calls': 1,
            # Far in the past so the G-03 sentinel-or-aged filter passes
            # without a markers-ready sentinel (matches the compat harness).
            'started_at': 1715514000.0,
            'ended_at': 1715514000.0,
            'billing_provider': 'anthropic',
        }
        base.update(overrides)
        return base

    @staticmethod
    def _one_aux_row(**overrides):
        base = {
            'session_id': 'aux-sid-001',
            'model': 'claude-3-5-haiku',
            'billing_provider': 'anthropic',
            'billing_base_url': '',
            'billing_mode': '',
            'task': 'approval',
            'api_call_count': 3,
            'input_tokens': 40,
            'output_tokens': 10,
            'cache_read_tokens': 0,
            'cache_write_tokens': 0,
            'estimated_cost_usd': 0.002,
            'first_seen': 1715514500.0,
            'last_seen': 1715514600.0,
        }
        base.update(overrides)
        return base

    def _find_aux_invocation(self, meter_invocations):
        aux = [
            argv_to_flags(inv) for inv in meter_invocations
            if argv_to_flags(inv).get('--operation-type') == 'AUX'
        ]
        return aux

    def _find_non_aux_invocation(self, meter_invocations):
        non_aux = [
            argv_to_flags(inv) for inv in meter_invocations
            if argv_to_flags(inv).get('--operation-type') != 'AUX'
        ]
        return non_aux


class TracerEndToEndTests(_AuxMeteringTestCase):
    """Task 1 behaviour tests 1-5: one aux row, end to end."""

    def test_1_one_aux_row_ships_its_own_meter_completion(self):
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, f"hermes-report.sh failed: {result['output']}")

        invocations = result['meter_invocations']
        self.assertEqual(
            len(invocations), 2,
            f'expected exactly 2 meter completion invocations, got '
            f'{len(invocations)}: {invocations!r}\nOutput: {result["output"]}',
        )

        aux_flags_list = self._find_aux_invocation(invocations)
        self.assertEqual(
            len(aux_flags_list), 1,
            f'expected exactly 1 invocation carrying --operation-type AUX, '
            f'got {len(aux_flags_list)}: {invocations!r}',
        )
        aux_flags = aux_flags_list[0]

        self.assertEqual(aux_flags.get('--task-type'), 'aux_approval')
        self.assertEqual(aux_flags.get('--input-tokens'), '40')
        self.assertEqual(aux_flags.get('--output-tokens'), '10')
        self.assertEqual(aux_flags.get('--total-tokens'), '50')
        self.assertTrue(
            str(aux_flags.get('--transaction-id', '')).startswith('aux-'),
            f'--transaction-id must start with "aux-", got {aux_flags.get("--transaction-id")!r}',
        )

    def test_2_transaction_ids_differ_agent_and_trace_id_match(self):
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        result = self._tick(fixture, 0)
        invocations = result['meter_invocations']

        aux_flags = self._find_aux_invocation(invocations)[0]
        main_flags = self._find_non_aux_invocation(invocations)[0]

        self.assertNotEqual(
            aux_flags.get('--transaction-id'), main_flags.get('--transaction-id'),
            'the aux and main-loop transaction-ids must never collide',
        )
        self.assertEqual(aux_flags.get('--agent'), main_flags.get('--agent'))
        self.assertEqual(aux_flags.get('--trace-id'), main_flags.get('--trace-id'))

    def test_3_ledger_line_shape(self):
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        self._tick(fixture, 0)

        ledger_path = self._aux_ledger_path(fixture)
        self.assertTrue(os.path.exists(ledger_path), 'revenium-aux.ledger must exist after a successful aux emit')
        with open(ledger_path) as f:
            lines = [ln.rstrip('\n') for ln in f if ln.strip()]
        self.assertEqual(len(lines), 1, f'expected exactly 1 ledger line, got {lines!r}')

        line = lines[0]
        self.assertTrue(
            line.startswith('AUX:aux-sid-001'),
            f'ledger line must start with "AUX:" glued to the sid, got {line!r}',
        )

        parts = line.split('|')
        # Six identity fields (session_id, model, billing_provider,
        # billing_base_url, billing_mode, task) + the cumulative counter
        # group + a numeric timestamp = 8 parts.
        self.assertEqual(
            len(parts), 8,
            f'ledger line must split into 8 pipe-delimited parts, got {len(parts)}: {parts!r}',
        )
        ts = parts[-1]
        self.assertRegex(ts, r'^\d+(\.\d+)?$', f'trailing field must be a numeric timestamp, got {ts!r}')

    def test_4_second_tick_over_unchanged_fixture_is_a_no_op(self):
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        self._tick(fixture, 0)

        ledger_path = self._aux_ledger_path(fixture)
        with open(ledger_path) as f:
            ledger_after_tick_1 = f.read()

        result_2 = self._tick(fixture, 1)
        aux_flags_list = self._find_aux_invocation(result_2['meter_invocations'])
        self.assertEqual(
            len(aux_flags_list), 0,
            f'second tick over an unchanged fixture must ship zero AUX '
            f'invocations, got {len(aux_flags_list)}',
        )

        with open(ledger_path) as f:
            ledger_after_tick_2 = f.read()
        self.assertEqual(
            ledger_after_tick_1, ledger_after_tick_2,
            'revenium-aux.ledger must be byte-identical across the no-op tick',
        )

    def test_5_empty_task_mirror_row_contributes_nothing(self):
        mirror_row = self._one_aux_row(task='', model='claude-sonnet-4-6',
                                        input_tokens=100, output_tokens=50,
                                        api_call_count=1, estimated_cost_usd=0.0)
        fixture = self._setup_fixture(
            [self._one_session()],
            aux_rows=[self._one_aux_row(), mirror_row],
        )
        result = self._tick(fixture, 0)

        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(
            len(aux_flags_list), 1,
            f'the empty-task mirror row must contribute NO additional aux '
            f'invocation -- expected exactly 1 (from the real approval row), '
            f'got {len(aux_flags_list)}',
        )


if __name__ == '__main__':
    unittest.main()
