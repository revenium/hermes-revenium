"""Phase 55 Plan 03 (ROI-09/ROI-10/ROI-11) -- the three things this phase
cannot claim by construction: that the auxiliary pass never touches the
main-loop mirror bucket, that a re-run -- across ticks and across profile
homes -- never double-reports, and that an auxiliary row lands in the same
rule scope as its own session's primary row.

Every arm in this module drives the REAL `hermes-report.sh` against a
synthetic `state.db` via the `_AuxMeteringTestCase` harness (Plan 01,
tests/test_phase55_auxiliary_metering.py) and asserts on REAL captured argv
or REAL ledger-file bytes -- never on the text of the SQL query or the
script source. This is the fixture-fidelity discipline
`GrossLeakFixtureTests` (tests/test_phase54_revenue_valuation_boundary.py)
established and this module copies, per D-15.

FIX LANDED BY THIS PLAN (T-55-06): while authoring the cross-profile arm
below, driving the REAL `report_auxiliary_usage` against two profile homes
sharing one `state.db` showed it double-shipped a namespaced session's
auxiliary row once per profile process that happened to see it -- the
`sessions` / `session_model_usage` queries carry no profile-scoping WHERE
clause, and nothing gated which sessions a given process's auxiliary pass
was allowed to cache. `skills/revenium/scripts/hermes-report.sh` now gates
the `aux_session_ctx` cache append on `session_markers_dir == MARKERS_DIR`
(both already resolved earlier in the same loop iteration) -- a session
that resolves to a DIFFERENT, existing profile's markers directory belongs
to (and will be correctly reported by) THAT profile's own tick, not this
one. A session with no `agent:<profile>:` namespace prefix (every existing
install today) always resolves to this process's own `MARKERS_DIR`, so the
guard is a no-op everywhere except a genuinely namespaced multiplex
deployment -- confirmed by the full existing suite staying green. This is a
Rule 2 deviation (auto-added missing critical functionality against a
threat-register HIGH severity item, T-55-06) documented in the plan's own
SUMMARY.md, not a pre-planned artifact.
"""
import os
import shutil
import tempfile
import unittest

from tests._compat_helpers import (
    argv_to_flags,
    build_session_model_usage,
    build_shim,
    build_state_db,
    run_script,
    SCRIPTS_DIR,
)
from tests.test_phase55_auxiliary_metering import _AuxMeteringTestCase


# ---------------------------------------------------------------------------
# Task 1 -- the mirror-bucket adversarial proof, with a positive control, a
# two-identity arm, and the cross-profile arm (T-55-06).
# ---------------------------------------------------------------------------
class AuxMirrorLeakFixtureTests(_AuxMeteringTestCase):
    """D-15's adversarial fixture, in `GrossLeakFixtureTests`' shape
    (tests/test_phase54_revenue_valuation_boundary.py:2387).

    WHAT THIS FIXTURE PROVES, AND WHAT WOULD MAKE IT A LIE: it proves, by
    driving the REAL `report_auxiliary_usage` query and emit chain against a
    synthetic `state.db` whose empty-`task` `session_model_usage` row is
    byte-equal to the `sessions` row's own totals (reproducing the mirror
    relationship `docs/internal/auxiliary-usage-sizing.md` measured to the
    cent fleet-wide), that the mirror row contributes NOTHING to any emitted
    auxiliary row -- across four arms: the hazard alone, a positive control
    proving the harness would have caught a leak, a two-identity arm proving
    a four-column identity assumption would not silently collapse two real
    rows into one, and a cross-profile arm proving a multiplexed host cannot
    double-ship a namespaced session's row once per profile process that
    sees it. It does NOT prove no other query anywhere could omit the
    `WHERE COALESCE(task, '') != ''` filter -- it proves THIS ONE, the only
    query `report_auxiliary_usage` runs, does not.
    """

    def test_hazard_arm_mirror_row_alone_ships_no_aux_invocation(self):
        session = self._one_session()
        mirror_row = self._one_aux_row(
            task='', model=session['model'], billing_provider=session['billing_provider'],
            input_tokens=session['input_tokens'], output_tokens=session['output_tokens'],
            api_call_count=session['api_calls'], estimated_cost_usd=0.0,
        )
        fixture = self._setup_fixture([session], aux_rows=[mirror_row])
        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])

        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(
            len(aux_flags_list), 0,
            f'the empty-task mirror row must ship NO auxiliary invocation at all, '
            f'got {len(aux_flags_list)}: {result["meter_invocations"]!r}',
        )

        ledger_path = self._aux_ledger_path(fixture)
        if os.path.exists(ledger_path):
            with open(ledger_path) as f:
                lines = [ln for ln in f if ln.strip()]
            self.assertEqual(lines, [], 'revenium-aux.ledger must be absent or empty')

        # The doubling tell, stated in the sizing document's own terms: the
        # total tokens across EVERY captured invocation must equal the
        # session's own totals exactly -- the run reported the session once,
        # not twice.
        total_tokens = sum(
            int(argv_to_flags(inv).get('--total-tokens', '0'))
            for inv in result['meter_invocations']
        )
        self.assertEqual(
            total_tokens, session['input_tokens'] + session['output_tokens'],
            'total tokens across all invocations must equal the session total exactly '
            '-- a higher figure means the mirror bucket doubled reported spend',
        )

    def test_positive_control_a_real_row_alongside_the_mirror_ships_exactly_one(self):
        session = self._one_session()
        mirror_row = self._one_aux_row(
            task='', model=session['model'], billing_provider=session['billing_provider'],
            input_tokens=session['input_tokens'], output_tokens=session['output_tokens'],
            api_call_count=session['api_calls'], estimated_cost_usd=0.0,
        )
        real_row = self._one_aux_row()
        fixture = self._setup_fixture([session], aux_rows=[mirror_row, real_row])
        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])

        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(
            len(aux_flags_list), 1,
            'the positive control must ship EXACTLY one auxiliary invocation -- if '
            'this is zero, the hazard arm above proves nothing (the pass never ran)',
        )
        aux_flags = aux_flags_list[0]
        self.assertEqual(aux_flags.get('--input-tokens'), str(real_row['input_tokens']))
        self.assertEqual(aux_flags.get('--output-tokens'), str(real_row['output_tokens']))

        total_tokens = sum(
            int(argv_to_flags(inv).get('--total-tokens', '0'))
            for inv in result['meter_invocations']
        )
        expected = (
            session['input_tokens'] + session['output_tokens']
            + real_row['input_tokens'] + real_row['output_tokens']
        )
        self.assertEqual(
            total_tokens, expected,
            'total tokens must equal the session total PLUS the real row -- proving '
            'the harness arithmetic would have caught a mirror leak rather than '
            'being blind to it',
        )

    def test_multi_row_arm_two_identities_differing_only_by_billing_still_both_ship(self):
        session = self._one_session()
        mirror_row = self._one_aux_row(
            task='', model=session['model'], billing_provider=session['billing_provider'],
            input_tokens=session['input_tokens'], output_tokens=session['output_tokens'],
            api_call_count=session['api_calls'], estimated_cost_usd=0.0,
        )
        row_a = self._one_aux_row(billing_provider='anthropic', billing_base_url='')
        row_b = self._one_aux_row(
            billing_provider='openrouter', billing_base_url='https://openrouter.ai/api/v1',
        )
        fixture = self._setup_fixture([session], aux_rows=[mirror_row, row_a, row_b])
        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])

        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(
            len(aux_flags_list), 2,
            f'two identities differing only by billing_provider/billing_base_url must '
            f'both ship as distinct rows -- the sizing document\'s own worked example '
            f'(a four-column identity would collapse these into one), got '
            f'{len(aux_flags_list)}',
        )

        ledger_path = self._aux_ledger_path(fixture)
        with open(ledger_path) as f:
            lines = [ln.rstrip('\n') for ln in f if ln.strip()]
        self.assertEqual(len(lines), 2, f'expected exactly 2 ledger lines, got {lines!r}')
        model_sources = sorted(f.get('--model-source') for f in aux_flags_list)
        self.assertEqual(model_sources, ['anthropic', 'openrouter'])

    def test_cross_profile_arm_a_namespaced_session_ships_from_only_its_owning_profile(self):
        """T-55-06 mitigation (this plan's own fix, see module docstring).

        Two profile homes (`${HERMES_HOME}/profiles/alpha`,
        `${HERMES_HOME}/profiles/beta`), each with its own REVENIUM_STATE_DIR
        (hence its own markers dir and its own AUX_LEDGER_FILE), run the
        reporter once each against the SAME shared `state.db`
        (`${HERMES_HOME}/state.db` -- one file, one path, read by both
        ticks) -- the literal T-55-06 shape: "multiplexed host, N profile
        homes, one state.db". The session is namespaced `agent:alpha:...`,
        so `resolve_markers_dir` routes it to alpha's OWN markers directory
        regardless of which process asks.

        Mechanism relied on: `report_auxiliary_usage` only reaches sids
        `aux_session_ctx` cached during THIS process's own session-loop
        iteration (as before this plan), and that cache is now ADDITIONALLY
        gated on `session_markers_dir == MARKERS_DIR` -- alpha's tick
        resolves the session's markers dir to ITS OWN MARKERS_DIR (match,
        cached, shipped); beta's tick resolves the SAME session to alpha's
        markers dir, which is NOT beta's own MARKERS_DIR (no match, never
        cached, never shipped). Each profile also keeps its own
        AUX_LEDGER_FILE (T-55-04's pre-existing accepted-risk framing), so
        this is not relying on any shared ledger coordination -- ownership
        is decided before the ledger is ever consulted.

        A FAILURE here means: alpha's tick shipped the row (expected) AND
        beta's tick ALSO shipped it (the T-55-06 regression this arm exists
        to catch) -- i.e. the union would contain two invocations for one
        auxiliary identity instead of one.
        """
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase55-aux-crossprofile-')
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)

        hermes_home = os.path.join(tmpdir, 'hh')
        os.makedirs(hermes_home)
        state_db = os.path.join(hermes_home, 'state.db')

        sid = 'agent:alpha:aux-crossprofile-sid-001'
        build_state_db(state_db, [self._one_session(id=sid)])
        build_session_model_usage(state_db, [self._one_aux_row(session_id=sid)])

        shim_home = os.path.join(tmpdir, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)
        shim = os.path.join(bin_dir, 'revenium')
        build_shim(shim)

        # Both profile homes must exist on disk -- resolve_markers_dir's
        # profile_home.is_dir() check is load-bearing security (a crafted
        # namespace segment is harmless without a matching directory).
        for profile in ('alpha', 'beta'):
            os.makedirs(
                os.path.join(hermes_home, 'profiles', profile, 'state', 'revenium', 'markers'),
                exist_ok=True,
            )

        def _run_profile(profile_name):
            state_dir = os.path.join(hermes_home, 'profiles', profile_name, 'state', 'revenium')
            meter_log = os.path.join(tmpdir, f'meter-{profile_name}.log')
            jobs_log = os.path.join(tmpdir, f'jobs-{profile_name}.log')
            inv_log = os.path.join(tmpdir, f'inv-{profile_name}.log')
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
            rc, _ignored, output = run_script(SCRIPTS_DIR / 'hermes-report.sh', env, inv_log)
            invocations = []
            if os.path.exists(meter_log):
                import shlex
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
            f'alpha OWNS this session (agent:alpha:...) and must ship it: {invs_alpha!r}',
        )
        self.assertEqual(
            len(aux_beta), 0,
            f'beta does NOT own this session and must ship nothing for it -- a '
            f'non-zero count here is the T-55-06 double-ship regression: {invs_beta!r}',
        )

        union = aux_alpha + aux_beta
        self.assertEqual(
            len(union), 1,
            'the union of captured auxiliary invocations across both profile ticks '
            'must contain exactly one row for this identity, not two',
        )


if __name__ == '__main__':
    unittest.main()
