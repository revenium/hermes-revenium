"""Phase 55 Plan 03 (D-02): argv-shape golden for the auxiliary-usage
`revenium meter completion --operation-type OTHER` call shipped by
`report_auxiliary_usage` in skills/revenium/scripts/hermes-report.sh.

Sibling to tests/test_compat_meter_completion_event.py (COMPAT-02), in the
same additive-not-immutable standing: a NEW golden fixture and a NEW test
class, leaving the four v1.x fixtures and their runners byte-for-byte
untouched. This fixture pins the auxiliary path's own deliberate
differences from the legacy shape: `--operation-type OTHER` (Phase 57
D-01/D-02/D-07 -- was `AUX`, rejected server-side; see
tests/test_phase57_operationtype_spec_membership.py for the spec-sourced
proof), the `aux_` prefixed task type, the `aux-` transaction-id prefix,
and the required absence of `--reasoning-tokens`.

Source-of-truth for the argv shape: the `report_auxiliary_usage` function's
`cmd=(...)` array construction in
skills/revenium/scripts/hermes-report.sh (landed by Phase 55 Plan 01,
D-06/D-07/D-13).

Golden fixture: tests/fixtures/compat/meter-completion-aux.golden.json.
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


class TestCompatMeterCompletionAux(unittest.TestCase):
    def test_aux_meter_completion_argv_matches_golden(self):
        """One auxiliary invocation must byte-match the golden. Exercises
        hermes-report.sh's post-loop auxiliary pass against a synthetic
        state.db carrying one `sessions` row and one matching
        `session_model_usage` row (task='approval'), with no markers
        present -- the markerless main-loop path -- so the ONLY variable
        under test is the auxiliary emit's own argv shape."""
        sid = 'aux-golden-sid-001'
        session = {
            'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
            'input_tokens': 100, 'output_tokens': 50, 'cache_read': 0, 'cache_write': 0,
            'reasoning': 0, 'estimated_cost': '0', 'api_calls': 1,
            'started_at': 1715514000.0, 'ended_at': 1715514000.0, 'billing_provider': 'anthropic',
        }
        aux_row = {
            'session_id': sid, 'model': 'claude-3-5-haiku', 'billing_provider': 'anthropic',
            'billing_base_url': '', 'billing_mode': '', 'task': 'approval',
            'api_call_count': 3, 'input_tokens': 40, 'output_tokens': 10,
            'cache_read_tokens': 0, 'cache_write_tokens': 0, 'estimated_cost_usd': 0.002,
            'first_seen': 1715514500.0, 'last_seen': 1715514600.0,
        }

        tmpdir = tempfile.mkdtemp(prefix='gsd-compat-meter-completion-aux-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            shim = os.path.join(bin_dir, 'revenium')

            build_state_db(state_db, [session])
            build_session_model_usage(state_db, [aux_row])
            build_shim(shim)

            meter_log = os.path.join(tmpdir, 'meter.log')
            jobs_log = os.path.join(tmpdir, 'jobs.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
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
            }
            rc, _ignored_inv, output = run_script(
                SCRIPTS_DIR / 'hermes-report.sh', env, inv_log
            )
            self.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {output}')

            meter_invocations = []
            if os.path.exists(meter_log):
                with open(meter_log) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            meter_invocations.append(shlex.split(line))

            aux_invocations = [
                inv for inv in meter_invocations
                if argv_to_flags(inv).get('--operation-type') == 'OTHER'
            ]
            self.assertEqual(
                len(aux_invocations), 1,
                f'expected exactly 1 AUX invocation, got {len(aux_invocations)}: '
                f'{meter_invocations!r}\nOutput: {output}',
            )

            captured = aux_invocations[0]
            # No-shift contract: argv must begin with 'meter completion'.
            self.assertEqual(
                captured[0], 'meter',
                f'no-shift violation: expected argv[0]="meter" got {captured[0]!r}',
            )
            self.assertEqual(
                captured[1], 'completion',
                f'no-shift violation: expected argv[1]="completion" got {captured[1]!r}',
            )

            golden = load_golden('meter-completion-aux.golden.json')
            assert_argv_matches_golden(self, captured, golden)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
