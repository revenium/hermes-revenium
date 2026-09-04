"""Phase 59 Plan 03 (D-17) -- proves the fix for the folded todo
`aux-pass-silently-drops-zero-token-sessions` (filed 2026-09-03, severity
medium, source: Phase 57 plan 05's first successful live auxiliary tick).

Measured scale on that live host: the first tick predicted 142
`session_model_usage` identities with a non-empty `task`, shipped 130 -- a
silent 12-identity (~8%) gap with no warn, no ledger line, and nothing in
the metering log. The mechanism: the main session loop's own
`WHERE (input_tokens > 0 OR output_tokens > 0)` filter is the only place
`aux_session_ctx` was populated, so a session whose sole LLM activity was an
auxiliary call was never iterated, never cached, and fell through
`report_auxiliary_usage`'s own `if sid not in ctx: continue` backstop
without a trace.

D-20's scoping (ROADMAP Phase 59, `59-03-PLAN.md`'s own
`<requirements_scoping>` block): this plan advances neither SSE-04 nor
SSE-05. It deliberately changes what the auxiliary pass ships -- roughly 8%
more identities on the one measured host -- which is the point of the fix,
not a criterion-5 ("feature-off metering is byte-identical") violation,
because the auxiliary pass is not the feature criterion 5 governs. A
reader of this module alone should come away understanding that a
deliberate behaviour change on this path is correct, not a regression.

Every arm below drives the REAL `hermes-report.sh` against a synthetic
`state.db`, reusing the `_AuxMeteringTestCase` harness from
tests/test_phase55_auxiliary_metering.py (PATH-shim + state.db + shlex
round-trip idiom) rather than re-implementing it, per the fixture-fidelity
discipline `tests/test_phase54_revenue_valuation_boundary.py`'s
`GrossLeakFixtureTests` established and `tests/test_phase55_aux_proofs.py`
already copies.
"""
import os
import sqlite3
import unittest

from tests._compat_helpers import (
    build_session_model_usage,
    build_shim,
    build_state_db,
    SCRIPTS_DIR,
)
from tests.test_phase55_aux_edges import _AuxWarnGateTestCase, _bump_aux_row
from tests.test_phase55_auxiliary_metering import _AuxMeteringTestCase

HERMES_REPORT_SH = SCRIPTS_DIR / 'hermes-report.sh'


# ---------------------------------------------------------------------------
# Recovery: an auxiliary-only session's spend reaches the wire, resolved
# from its own `sessions` row rather than from whether the main loop
# happened to iterate it.
# ---------------------------------------------------------------------------
class AuxOnlySessionRecoveryTests(_AuxMeteringTestCase):
    """A session with zero main-loop tokens but a session_model_usage row
    ships its auxiliary spend -- the exact shape the folded todo names."""

    def test_zero_token_session_ships_exactly_one_aux_invocation(self):
        fixture = self._setup_fixture(
            [self._one_session(input_tokens=0, output_tokens=0)],
            aux_rows=[self._one_aux_row()],
        )
        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])

        invocations = result['meter_invocations']
        self.assertEqual(
            len(invocations), 1,
            f'expected exactly 1 meter completion invocation (the aux row; '
            f'no main-loop row for a zero-token session), got '
            f'{len(invocations)}: {invocations!r}',
        )
        aux_flags_list = self._find_aux_invocation(invocations)
        self.assertEqual(len(aux_flags_list), 1, invocations)
        self.assertEqual(aux_flags_list[0].get('--task-type'), 'aux_approval')

        ledger_path = self._aux_ledger_path(fixture)
        self.assertTrue(os.path.exists(ledger_path))
        with open(ledger_path) as f:
            lines = [ln for ln in f if ln.strip()]
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith('AUX:'))

    def test_recovered_invocation_trace_id_and_environment(self):
        """--trace-id is the resolved root session id (== the sid itself,
        since the test schema carries no parent_session_id column and
        get_root_session_id / get-root-session-id.py fail open to the
        input sid on that OperationalError); --environment is the
        sessions row's own `source` column."""
        fixture = self._setup_fixture(
            [self._one_session(
                input_tokens=0, output_tokens=0, source='recovered-env',
            )],
            aux_rows=[self._one_aux_row()],
        )
        result = self._tick(fixture, 0)
        aux_flags = self._find_aux_invocation(result['meter_invocations'])[0]

        self.assertEqual(aux_flags.get('--trace-id'), 'aux-sid-001')
        self.assertEqual(aux_flags.get('--environment'), 'recovered-env')

    def test_session_id_with_sql_metacharacters_round_trips(self):
        """T-59-14: the supplementary lookup binds every sid as a `?`
        parameter, never interpolates it into statement text. A sid
        carrying a quote and a semicolon proves this by round-tripping
        rather than corrupting the query or being silently dropped."""
        hostile_sid = "sid-o'brien;drop--001"
        fixture = self._setup_fixture(
            [self._one_session(id=hostile_sid, input_tokens=0, output_tokens=0)],
            aux_rows=[self._one_aux_row(session_id=hostile_sid)],
        )
        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])

        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(
            len(aux_flags_list), 1,
            f'a session id containing SQL metacharacters must still be '
            f'recovered and emitted: {result["meter_invocations"]!r}',
        )
        self.assertTrue(
            aux_flags_list[0].get('--transaction-id', '').startswith('aux-'),
        )

    def test_state_db_byte_identical_before_and_after_tick(self):
        """T-59-21: the supplementary queries open state.db through a
        file:...?mode=ro URI and write nothing to it -- a project
        constraint ('the skill is a pure consumer'), not a preference."""
        fixture = self._setup_fixture(
            [self._one_session(input_tokens=0, output_tokens=0)],
            aux_rows=[self._one_aux_row()],
        )
        with open(fixture['state_db'], 'rb') as f:
            before = f.read()

        self._tick(fixture, 0)

        with open(fixture['state_db'], 'rb') as f:
            after = f.read()
        self.assertEqual(before, after, 'state.db must never be written to')


# ---------------------------------------------------------------------------
# The main loop is untouched, in source and in behaviour, and the empty-
# task mirror bucket never enters this recovery path either.
# ---------------------------------------------------------------------------
class MainLoopFilterUnchangedTests(_AuxMeteringTestCase):
    """What-NOT-to-do, verified: the todo is explicit that widening the
    main loop's token pre-filter to fix the auxiliary pass would change
    what the main loop meters -- it is load-bearing for the delta
    arithmetic and the ledger's idempotency contract."""

    def test_source_assertion_main_loop_filter_present_and_unwidened(self):
        text = HERMES_REPORT_SH.read_text()
        uncommented = '\n'.join(
            line for line in text.splitlines()
            if not line.strip().startswith('#')
        )
        self.assertEqual(
            uncommented.count('WHERE (input_tokens > 0 OR output_tokens > 0)'),
            1,
            'the main loop token filter must appear exactly once, unwidened',
        )

    def test_zero_token_session_produces_no_main_loop_invocation(self):
        fixture = self._setup_fixture(
            [self._one_session(input_tokens=0, output_tokens=0)],
            aux_rows=[self._one_aux_row()],
        )
        result = self._tick(fixture, 0)
        non_aux = self._find_non_aux_invocation(result['meter_invocations'])
        self.assertEqual(
            len(non_aux), 0,
            f'a zero-token session must never produce a main-loop row: {non_aux!r}',
        )

    def test_empty_task_row_alone_ships_nothing(self):
        """The mirror bucket (COALESCE(task, '') == '') must never enter
        the supplementary recovery path either -- its summed tokens/cost
        equal the sessions table's own totals to the cent (Phase 31), and
        shipping it here would double-meter exactly what the empty-task
        exclusion in the emit query already guards against."""
        fixture = self._setup_fixture(
            [self._one_session(input_tokens=0, output_tokens=0)],
            aux_rows=[self._one_aux_row(task='')],
        )
        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])
        self.assertEqual(
            len(result['meter_invocations']), 0,
            f'an empty-task-only fixture must ship nothing: '
            f'{result["meter_invocations"]!r}',
        )


# ---------------------------------------------------------------------------
# Idempotency: cross-tick, matching the ledger's existing per-column
# subtraction discipline exactly for a recovered identity.
# ---------------------------------------------------------------------------
class AuxRecoveryIdempotencyTests(_AuxMeteringTestCase):
    def test_two_ticks_over_unchanged_counters_ship_once_in_total(self):
        fixture = self._setup_fixture(
            [self._one_session(input_tokens=0, output_tokens=0)],
            aux_rows=[self._one_aux_row()],
        )
        result_0 = self._tick(fixture, 0)
        result_1 = self._tick(fixture, 1)

        self.assertEqual(len(self._find_aux_invocation(result_0['meter_invocations'])), 1)
        self.assertEqual(
            len(self._find_aux_invocation(result_1['meter_invocations'])), 0,
            f'unchanged counters must not re-ship: {result_1["meter_invocations"]!r}',
        )

        ledger_path = self._aux_ledger_path(fixture)
        with open(ledger_path) as f:
            lines = [ln for ln in f if ln.strip()]
        self.assertEqual(len(lines), 1, lines)

    def test_second_tick_after_counters_advance_ships_exact_delta(self):
        aux_row = self._one_aux_row()
        fixture = self._setup_fixture(
            [self._one_session(input_tokens=0, output_tokens=0)],
            aux_rows=[aux_row],
        )
        self._tick(fixture, 0)

        _bump_aux_row(
            fixture['state_db'], aux_row['session_id'], aux_row['model'],
            billing_provider=aux_row['billing_provider'],
            billing_base_url=aux_row['billing_base_url'],
            billing_mode=aux_row['billing_mode'],
            task=aux_row['task'],
            delta_input=15, delta_output=5, delta_calls=1,
        )
        result_1 = self._tick(fixture, 1)
        aux_flags_list = self._find_aux_invocation(result_1['meter_invocations'])
        self.assertEqual(len(aux_flags_list), 1, result_1['meter_invocations'])
        self.assertEqual(aux_flags_list[0].get('--input-tokens'), '15')
        self.assertEqual(aux_flags_list[0].get('--output-tokens'), '5')


# ---------------------------------------------------------------------------
# Ownership: a multiplexed host's OTHER profile ticks must never double-
# ship a session this process does not own. This repo has already paid
# for the union-of-N-profiles regression once (T-55-06); the arm here is
# the identical shape, applied to the NEW recovery path.
# ---------------------------------------------------------------------------
class AuxRecoveryOwnershipTests(_AuxMeteringTestCase):
    def test_two_profile_ticks_ship_exactly_once_across_both(self):
        import shutil
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix='gsd-phase59-aux-ownership-')
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)

        hermes_home = os.path.join(tmpdir, 'hh')
        os.makedirs(hermes_home)
        state_db = os.path.join(hermes_home, 'state.db')

        sid = 'agent:alpha:aux59-crossprofile-001'
        build_state_db(state_db, [self._one_session(
            id=sid, input_tokens=0, output_tokens=0,
        )])
        build_session_model_usage(state_db, [self._one_aux_row(session_id=sid)])

        shim_home = os.path.join(tmpdir, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)
        shim = os.path.join(bin_dir, 'revenium')
        build_shim(shim)

        for profile in ('alpha', 'beta'):
            os.makedirs(
                os.path.join(hermes_home, 'profiles', profile, 'state', 'revenium', 'markers'),
                exist_ok=True,
            )

        def _run_profile(profile_name):
            import shlex

            from tests._compat_helpers import run_script

            state_dir = os.path.join(hermes_home, 'profiles', profile_name, 'state', 'revenium')
            meter_log = os.path.join(tmpdir, f'meter-{profile_name}.log')
            inv_log = os.path.join(tmpdir, f'inv-{profile_name}.log')
            env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'INVOCATIONS_LOG': inv_log,
                'METER_LOG': meter_log,
                'TZ': 'UTC',
            }
            rc, _ignored, output = run_script(HERMES_REPORT_SH, env, inv_log)
            invocations = []
            if os.path.exists(meter_log):
                with open(meter_log) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            invocations.append(shlex.split(line))
            return rc, invocations, output

        rc_alpha, invs_alpha, out_alpha = _run_profile('alpha')
        rc_beta, invs_beta, out_beta = _run_profile('beta')
        self.assertEqual(rc_alpha, 0, out_alpha)
        self.assertEqual(rc_beta, 0, out_beta)

        aux_alpha = self._find_aux_invocation(invs_alpha)
        aux_beta = self._find_aux_invocation(invs_beta)

        self.assertEqual(
            len(aux_alpha), 1,
            f'alpha owns this session (agent:alpha:...) and must ship it: {invs_alpha!r}',
        )
        self.assertEqual(
            len(aux_beta), 0,
            f'beta does not own this session and must ship nothing for it -- '
            f'a non-zero count here is the T-55-06 shape recurring on the '
            f'NEW recovery path: {invs_beta!r}',
        )
        self.assertEqual(len(aux_alpha) + len(aux_beta), 1)


# ---------------------------------------------------------------------------
# Visibility: the defect being fixed was invisible, not merely wrong. It
# produced no warn, no ledger line, nothing in the metering log. Assert on
# the log contents and the sentinel flag file, not only the absence of an
# invocation.
# ---------------------------------------------------------------------------
class ResidualDropVisibilityTests(_AuxWarnGateTestCase):
    def test_unresolvable_session_warns_once_and_flags_once(self):
        """An owned sid with session_model_usage rows and NO sessions row
        at all: the tick completes, ships nothing for it, but says so --
        one warn line and one sentinel flag, not repeated on a second
        tick over the unchanged fixture."""
        orphan_sid = 'orphan-aux59-sid-001'
        fixture = self._setup_fixture([], aux_rows=[self._one_aux_row(session_id=orphan_sid)])

        result_0 = self._tick(fixture, 0)
        self.assertEqual(result_0['rc'], 0, result_0['output'])
        self.assertEqual(len(result_0['meter_invocations']), 0)

        log_text = self._log_text(fixture)
        self.assertIn(orphan_sid, log_text)
        self.assertIn('no sessions row could be found to attribute', log_text)

        sentinel_names = self._sentinel_names(fixture)
        matching = [n for n in sentinel_names if orphan_sid in n]
        self.assertEqual(len(matching), 1, sentinel_names)

        result_1 = self._tick(fixture, 1)
        self.assertEqual(result_1['rc'], 0, result_1['output'])

        log_text_after = self._log_text(fixture)
        self.assertEqual(
            log_text_after.count('no sessions row could be found to attribute'), 1,
            'a second tick over the unchanged fixture must not repeat the warn',
        )
        sentinel_names_after = self._sentinel_names(fixture)
        matching_after = [n for n in sentinel_names_after if orphan_sid in n]
        self.assertEqual(len(matching_after), 1, sentinel_names_after)

    def test_nothing_to_recover_produces_no_aggregate_line(self):
        """A normal main-loop session with no session_model_usage rows to
        recover: the per-tick aggregate info line must not appear at all,
        so an ordinary install's log stays byte-unchanged."""
        fixture = self._setup_fixture([self._one_session()], aux_rows=[])
        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])

        log_text = self._log_text(fixture)
        self.assertNotIn('Aux session context supplement', log_text)


if __name__ == '__main__':
    unittest.main()
