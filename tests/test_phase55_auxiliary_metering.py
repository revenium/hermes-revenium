"""Phase 55 Plan 01 (ROI-09/ROI-11) -- the auxiliary-usage metering tracer.

Drives the REAL hermes-report.sh against a synthetic state.db carrying both
a `sessions` row (the existing main-loop source) and a `session_model_usage`
row (the new auxiliary-usage source this plan wires up for the first time).
Proves the full slice end to end: one auxiliary row ships as its own
`revenium meter completion --operation-type OTHER` (Phase 57 D-01/D-02;
`AUX` was rejected server-side and is no longer sent), records itself in
`revenium-aux.ledger`, and a second tick over the unchanged fixture is a
no-op.

Harness shape copied from tests/test_compat_meter_completion.py (the
PATH-shim + state.db + shlex round-trip idiom); extended with
build_session_model_usage (tests/_compat_helpers.py) to seed the new table.

Task 3 (this same module) adds the two byte-identical arms required by
ROADMAP criterion 4: the operator off switch (D-01) and an install whose
Hermes predates session_model_usage entirely (D-07).
"""
import json
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
            if argv_to_flags(inv).get('--operation-type') == 'OTHER'
        ]
        return aux

    def _find_non_aux_invocation(self, meter_invocations):
        non_aux = [
            argv_to_flags(inv) for inv in meter_invocations
            if argv_to_flags(inv).get('--operation-type') != 'OTHER'
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
            f'expected exactly 1 invocation carrying --operation-type OTHER, '
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


class OffSwitchArmTests(_AuxMeteringTestCase):
    """Task 3 Arm A -- the operator off switch (D-01, ROADMAP criterion 4).

    An opt-out install must ship zero AUX invocations, write no aux ledger,
    and meter the main loop byte-identically to an install whose Hermes has
    no session_model_usage table at all.
    """

    @staticmethod
    def _log_text(fixture):
        log_path = os.path.join(fixture['state_dir'], 'revenium-metering.log')
        if not os.path.exists(log_path):
            return ''
        with open(log_path) as f:
            return f.read()

    def test_env_disabled_ships_zero_aux_and_matches_absent_table_control(self):
        # Control: session_model_usage never created at all.
        control_fixture = self._setup_fixture([self._one_session()])
        control_result = self._tick(control_fixture, 0)
        self.assertEqual(control_result['rc'], 0, control_result['output'])
        self.assertEqual(len(control_result['meter_invocations']), 1)
        control_argv = control_result['meter_invocations'][0]

        # Arm: table present and carrying a real emittable row, but the
        # operator has explicitly opted out via the environment.
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        result = self._tick(fixture, 0, extra_env={'REVENIUM_AUX_METERING': 'disabled'})
        self.assertEqual(result['rc'], 0, result['output'])

        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(len(aux_flags_list), 0, 'the off switch must ship zero AUX invocations')
        self.assertEqual(len(result['meter_invocations']), 1)

        ledger_path = self._aux_ledger_path(fixture)
        self.assertFalse(os.path.exists(ledger_path), 'the off switch must write no aux ledger at all')

        self.assertEqual(
            result['meter_invocations'][0], control_argv,
            'the main-loop argv must be the SAME ordered token list as a '
            'control run whose Hermes has no session_model_usage table',
        )

    def test_config_json_disabled_with_env_unset_exercises_the_precedence_path(self):
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        config_path = os.path.join(fixture['state_dir'], 'config.json')
        with open(config_path, 'w') as f:
            json.dump({'auxMetering': 'disabled'}, f)

        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])

        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(
            len(aux_flags_list), 0,
            'config.json auxMetering=disabled must be honoured when the env var is unset',
        )

        ledger_path = self._aux_ledger_path(fixture)
        self.assertFalse(os.path.exists(ledger_path))

    def test_typo_value_falls_back_to_enabled_and_warns(self):
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        result = self._tick(fixture, 0, extra_env={'REVENIUM_AUX_METERING': 'disabeld'})
        self.assertEqual(result['rc'], 0, result['output'])

        # A typo must never silently change billing behaviour -- it falls
        # back to the enabled default, so the aux row still ships.
        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(len(aux_flags_list), 1)

        log_text = self._log_text(fixture)
        self.assertIn('unrecognised value', log_text)
        self.assertIn("falling back to 'enabled'", log_text)


class AbsentTableArmTests(_AuxMeteringTestCase):
    """Task 3 Arm B -- the absent table (D-07, ROADMAP criterion 4).

    An install whose Hermes predates session_model_usage must ship zero AUX
    invocations, write no aux ledger, log the reason exactly once, and meter
    the main loop byte-identically to the pinned v1.x golden.
    """

    def test_absent_table_meters_byte_identically_and_logs_reason_once(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase55-aux-absent-')
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

        # Byte-for-byte the same fixture as
        # TestCompatMeterCompletion.test_meter_completion_per_marker_argv_matches_v12_golden
        # -- build_state_db only, session_model_usage never created at all.
        build_state_db(state_db, [{
            'id': 'compat-sid-001',
            'model': 'claude-sonnet-4-6',
            'source': 'test',
            'input_tokens': 100,
            'output_tokens': 50,
            'cache_read': 0,
            'cache_write': 0,
            'reasoning': 0,
            'estimated_cost': '0',
            'api_calls': 1,
            'started_at': 1715514000.0,
            'ended_at': 1715514000.0,
            'billing_provider': 'anthropic',
        }])

        task_marker = {
            'muid': 'compat-muid-001',
            'ts': 1715515000.5,
            'sid': 'compat-sid-001',
            'task_type': 'code_review',
            'operation_type': 'CHAT',
        }
        job_marker = {
            'kind': 'job',
            'ts': 1715515001.0,
            'sid': 'compat-sid-001',
            'agentic_job_id': 'compat-job-001',
            'job_name': 'COMPAT Test Job',
            'job_type': 'code_review',
            'status': 'IN_PROGRESS',
        }
        with open(os.path.join(markers_dir, 'compat-sid-001.jsonl'), 'w') as f:
            f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
            f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

        build_shim(shim)

        base_env = {
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

        rc, _ignored_inv, output = run_script(
            SCRIPTS_DIR / 'hermes-report.sh', base_env, inv_log
        )
        self.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {output}')

        meter_invocations = []
        if os.path.exists(meter_log):
            with open(meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        meter_invocations.append(shlex.split(line))

        aux_flags_list = [
            argv_to_flags(inv) for inv in meter_invocations
            if argv_to_flags(inv).get('--operation-type') == 'OTHER'
        ]
        self.assertEqual(len(aux_flags_list), 0, 'an absent table must ship zero AUX invocations')

        ledger_path = os.path.join(state_dir, 'revenium-aux.ledger')
        self.assertFalse(os.path.exists(ledger_path), 'an absent table must write no aux ledger at all')

        log_path = os.path.join(state_dir, 'revenium-metering.log')
        log_text = open(log_path).read() if os.path.exists(log_path) else ''
        combined = output + '\n' + log_text
        occurrences = combined.count('session_model_usage table not present')
        self.assertEqual(
            occurrences, 1,
            f'the absent-table reason must be logged exactly once, found {occurrences}:\n{combined}',
        )

        self.assertEqual(
            len(meter_invocations), 1,
            f'expected exactly 1 meter completion invocation, got '
            f'{len(meter_invocations)}: {meter_invocations!r}\nOutput: {output}',
        )
        assert_argv_matches_golden(
            self, meter_invocations[0], load_golden('meter-completion.golden.json')
        )


if __name__ == '__main__':
    unittest.main()
