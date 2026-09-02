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
import json
import os
import shutil
import sqlite3
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
from tests.test_phase55_aux_edges import _bump_aux_row
from tests.test_phase55_auxiliary_metering import _AuxMeteringTestCase


def _bump_aux_row_with_cost(state_db, session_id, model, billing_provider='', billing_base_url='',
                             billing_mode='', task='', delta_input=0, delta_output=0,
                             delta_calls=0, delta_cost=0.0):
    """Sibling to tests/test_phase55_aux_edges.py::_bump_aux_row, extended
    with a cost delta -- that helper only advances token/call counters, and
    the cross-tick idempotency proof below needs the `--total-cost` flag's
    own increment-not-cumulative behaviour asserted too (plan Task 2)."""
    conn = sqlite3.connect(state_db)
    conn.execute(
        'UPDATE session_model_usage SET '
        'input_tokens = input_tokens + ?, output_tokens = output_tokens + ?, '
        'api_call_count = api_call_count + ?, estimated_cost_usd = estimated_cost_usd + ? '
        'WHERE session_id=? AND model=? AND billing_provider=? AND billing_base_url=? '
        'AND billing_mode=? AND task=?',
        (delta_input, delta_output, delta_calls, delta_cost,
         session_id, model, billing_provider, billing_base_url, billing_mode, task),
    )
    conn.commit()
    conn.close()


def _make_trace_type_capable(shim_path):
    """Patch a build_shim-produced shim to additionally advertise
    --trace-type in its `meter completion --help` probe response, so
    TRACE_TYPE_CLI_CAPABLE resolves true and the scope-parity assertions on
    --trace-type below are not vacuously true-by-absence (every existing
    driven test in this repo uses the default shim, which never advertises
    --trace-type, matching the four immutable goldens' own omission of it).
    Inserted BEFORE the --agentic-job-id line, which build_shim's own
    comment requires stay last (a live `grep -q` probe elsewhere depends on
    it) -- supports_flag's two-step full-text capture for --trace-type has
    no such ordering requirement, so this insertion is safe."""
    with open(shim_path) as f:
        body = f.read()
    marker = '      echo "--agentic-job-id  Agentic job instance identifier"\n'
    assert marker in body, 'build_shim shape changed -- update this patch'
    body = body.replace(
        marker,
        '      echo "--trace-type string        Trace type"\n' + marker,
    )
    with open(shim_path, 'w') as f:
        f.write(body)


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


# ---------------------------------------------------------------------------
# Task 2 -- cross-tick idempotency plus the six local edge predicates.
# ---------------------------------------------------------------------------
class AuxIdempotencyTests(_AuxMeteringTestCase):
    """ROI-11's idempotency proof, in the shape of the ledger idempotency
    tests already in this repo (tests/test_phase32_event_ledger_idempotency.py),
    plus the six edge predicates the plan's probe surfaced. Every arm drives
    the real script; none asserts on script text."""

    def test_cross_tick_idempotency_ships_increment_not_cumulative_total(self):
        aux_row = self._one_aux_row()  # api_call_count=3, input=40, output=10, cost=0.002
        fixture = self._setup_fixture([self._one_session()], aux_rows=[aux_row])
        result_1 = self._tick(fixture, 0)
        self.assertEqual(len(self._find_aux_invocation(result_1['meter_invocations'])), 1)

        ledger_path = self._aux_ledger_path(fixture)
        with open(ledger_path, 'rb') as f:
            ledger_after_tick_1 = f.read()

        result_2 = self._tick(fixture, 1)
        self.assertEqual(
            len(self._find_aux_invocation(result_2['meter_invocations'])), 0,
            'a second tick over unchanged counters must ship zero auxiliary invocations',
        )
        with open(ledger_path, 'rb') as f:
            ledger_after_tick_2 = f.read()
        self.assertEqual(
            ledger_after_tick_1, ledger_after_tick_2,
            'revenium-aux.ledger must be byte-identical across the no-op tick',
        )

        # Grow the row's cumulative counters -- what the confirmed UPSERT does.
        _bump_aux_row_with_cost(
            fixture['state_db'], session_id=aux_row['session_id'], model=aux_row['model'],
            billing_provider=aux_row['billing_provider'],
            billing_base_url=aux_row['billing_base_url'], billing_mode=aux_row['billing_mode'],
            task=aux_row['task'], delta_input=30, delta_output=8, delta_calls=2,
            delta_cost=0.0015,
        )
        result_3 = self._tick(fixture, 2)
        aux_flags_list = self._find_aux_invocation(result_3['meter_invocations'])
        self.assertEqual(len(aux_flags_list), 1, result_3['meter_invocations'])
        aux_flags = aux_flags_list[0]
        self.assertEqual(
            aux_flags.get('--input-tokens'), '30',
            'must ship the INCREMENT (30), never the cumulative total (70) again',
        )
        self.assertEqual(aux_flags.get('--output-tokens'), '8')
        self.assertEqual(
            aux_flags.get('--total-cost'), '0.001500',
            'the cost flag must carry the cost INCREMENT, not the cumulative total',
        )

        with open(ledger_path) as f:
            lines = [ln.rstrip('\n') for ln in f if ln.strip()]
        self.assertEqual(
            len(lines), 2,
            f'the ledger must now hold two lines for this identity (two cumulative '
            f'snapshots, in order), got {lines!r}',
        )

    def test_edge_roi11_adjacency_a_tied_counter_ships_nothing_a_grown_sibling_still_ships(self):
        row_tied = self._one_aux_row(task='approval')
        row_grows = self._one_aux_row(task='title_generation', model='claude-3-5-haiku')
        fixture = self._setup_fixture([self._one_session()], aux_rows=[row_tied, row_grows])
        result_1 = self._tick(fixture, 0)
        self.assertEqual(len(self._find_aux_invocation(result_1['meter_invocations'])), 2)

        # Only row_grows advances; row_tied's counters stay exactly equal.
        _bump_aux_row(
            fixture['state_db'], session_id=row_grows['session_id'], model=row_grows['model'],
            billing_provider=row_grows['billing_provider'],
            billing_base_url=row_grows['billing_base_url'], billing_mode=row_grows['billing_mode'],
            task=row_grows['task'],
        )
        result_2 = self._tick(fixture, 1)
        aux_flags_list = self._find_aux_invocation(result_2['meter_invocations'])
        self.assertEqual(
            len(aux_flags_list), 1,
            'exactly one identity (the grown sibling) must ship this tick',
        )
        self.assertEqual(
            aux_flags_list[0].get('--task-type'), 'aux_title_generation',
            'the SHIPPED identity must be the grown sibling, not the tied one -- '
            'proving the tied identity\'s absence is a real skip, not "nothing ran"',
        )

    def test_edge_roi11_empty_absent_and_zero_byte_ledger_both_ship_full_cumulative_once(self):
        aux_row = self._one_aux_row()

        # Pass 1: ledger genuinely absent (the ordinary first-ever-tick case).
        fixture_a = self._setup_fixture([self._one_session()], aux_rows=[aux_row])
        result_a = self._tick(fixture_a, 0)
        aux_a = self._find_aux_invocation(result_a['meter_invocations'])
        self.assertEqual(len(aux_a), 1)
        self.assertEqual(aux_a[0].get('--input-tokens'), str(aux_row['input_tokens']))
        with open(self._aux_ledger_path(fixture_a)) as f:
            lines_a = [ln for ln in f if ln.strip()]
        self.assertEqual(len(lines_a), 1)

        # Pass 2: ledger present but zero bytes -- same outcome.
        fixture_b = self._setup_fixture([self._one_session()], aux_rows=[aux_row])
        ledger_b = self._aux_ledger_path(fixture_b)
        open(ledger_b, 'w').close()
        result_b = self._tick(fixture_b, 0)
        aux_b = self._find_aux_invocation(result_b['meter_invocations'])
        self.assertEqual(len(aux_b), 1)
        self.assertEqual(aux_b[0].get('--input-tokens'), str(aux_row['input_tokens']))
        with open(ledger_b) as f:
            lines_b = [ln for ln in f if ln.strip()]
        self.assertEqual(len(lines_b), 1)

    def test_edge_roi11_ordering_a_counter_tie_between_distinct_identities_never_merges(self):
        row_a = self._one_aux_row(task='approval')
        row_b = self._one_aux_row(task='title_generation', model='claude-3-5-haiku')
        fixture = self._setup_fixture([self._one_session()], aux_rows=[row_a, row_b])
        result = self._tick(fixture, 0)
        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(len(aux_flags_list), 2)
        task_types = sorted(f.get('--task-type') for f in aux_flags_list)
        self.assertEqual(task_types, ['aux_approval', 'aux_title_generation'])

        ledger_path = self._aux_ledger_path(fixture)
        with open(ledger_path) as f:
            lines = [ln.rstrip('\n') for ln in f if ln.strip()]
        self.assertEqual(len(lines), 2)
        tasks_in_ledger = set()
        for line in lines:
            parts = line.split('|')
            self.assertEqual(len(parts), 8, f'malformed ledger line: {line!r}')
            tasks_in_ledger.add(parts[5])
        self.assertEqual(
            tasks_in_ledger, {'approval', 'title_generation'},
            'a tie on the counter value must not merge, mask, or reorder the two '
            'distinct identities\' ledger lines',
        )

        # Re-run: both are now no-ops -- the tie did not leave one unrecorded.
        result_2 = self._tick(fixture, 1)
        self.assertEqual(len(self._find_aux_invocation(result_2['meter_invocations'])), 0)

    def test_edge_roi09_adjacency_the_two_ledgers_never_cross_contaminate(self):
        # Deliberately NOT the harness default 'aux-sid-001' -- that session
        # id itself begins with "aux-", which would make the transaction-id
        # prefix assertion below vacuously true regardless of which emit
        # path produced it.
        sid = 'roi09-adjacency-sid-001'
        fixture = self._setup_fixture(
            [self._one_session(id=sid)], aux_rows=[self._one_aux_row(session_id=sid)],
        )
        result = self._tick(fixture, 0)
        aux_flags = self._find_aux_invocation(result['meter_invocations'])[0]
        main_flags = self._find_non_aux_invocation(result['meter_invocations'])[0]

        self.assertNotEqual(aux_flags.get('--transaction-id'), main_flags.get('--transaction-id'))
        self.assertTrue(str(aux_flags.get('--transaction-id', '')).startswith('aux-'))
        self.assertFalse(str(main_flags.get('--transaction-id', '')).startswith('aux-'))
        self.assertNotEqual(aux_flags.get('--operation-type'), main_flags.get('--operation-type'))

        main_ledger_path = os.path.join(fixture['state_dir'], 'revenium-hermes.ledger')
        aux_ledger_path = self._aux_ledger_path(fixture)
        with open(main_ledger_path) as f:
            main_lines = [ln for ln in f if ln.strip()]
        with open(aux_ledger_path) as f:
            aux_lines = [ln for ln in f if ln.strip()]
        self.assertTrue(
            all(not ln.startswith('AUX:') for ln in main_lines),
            f'revenium-hermes.ledger must contain no AUX: line: {main_lines!r}',
        )
        self.assertTrue(
            all(not ln.startswith('HERMES:') for ln in aux_lines),
            f'revenium-aux.ledger must contain no HERMES: line: {aux_lines!r}',
        )

    def test_edge_roi09_empty_zero_one_and_empty_task_row_counts(self):
        # Zero session_model_usage rows (table present, no rows).
        fixture_1 = self._setup_fixture([self._one_session()], aux_rows=[])
        result_1 = self._tick(fixture_1, 0)
        self.assertEqual(len(self._find_aux_invocation(result_1['meter_invocations'])), 0)

        # Exactly one row.
        fixture_2 = self._setup_fixture([self._one_session()], aux_rows=[self._one_aux_row()])
        result_2 = self._tick(fixture_2, 0)
        self.assertEqual(len(self._find_aux_invocation(result_2['meter_invocations'])), 1)

        # One row, empty task.
        fixture_3 = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row(task='')],
        )
        result_3 = self._tick(fixture_3, 0)
        self.assertEqual(len(self._find_aux_invocation(result_3['meter_invocations'])), 0)

    def test_edge_roi09_ordering_stable_across_independent_runs_and_matches_sort_order(self):
        session = self._one_session()
        insertion_order = ['web_extract', 'approval', 'compression', 'title_generation']
        rows = [self._one_aux_row(task=t) for t in insertion_order]
        expected_order = ['aux_approval', 'aux_compression', 'aux_title_generation', 'aux_web_extract']

        fixture_1 = self._setup_fixture([session], aux_rows=rows)
        result_1 = self._tick(fixture_1, 0)
        seq_1 = [
            f.get('--task-type') for f in self._find_aux_invocation(result_1['meter_invocations'])
        ]

        fixture_2 = self._setup_fixture([session], aux_rows=rows)
        result_2 = self._tick(fixture_2, 0)
        seq_2 = [
            f.get('--task-type') for f in self._find_aux_invocation(result_2['meter_invocations'])
        ]

        self.assertEqual(seq_1, expected_order, seq_1)
        self.assertEqual(seq_2, expected_order, seq_2)
        self.assertEqual(
            seq_1, seq_2,
            'emission order must be identical across two independent runs of the '
            'same insertion-scrambled input -- total and stable, not insertion-dependent',
        )


# ---------------------------------------------------------------------------
# Task 3 -- scope parity (ROI-10, D-09/D-11).
# ---------------------------------------------------------------------------
class AuxScopeParityTests(_AuxMeteringTestCase):
    """An auxiliary row's session-resolved scope dimensions must equal the
    same session's primary completion argv's, so a rule scoped on any of
    them counts the session's overhead WITH the session (ROI-10). Two
    per-row divergences are deliberate and asserted directly: MODEL/PROVIDER
    are the auxiliary row's own facts (a small model serving an approval
    call reports THAT model, corroborated by --model-source), and
    TASK_TYPE/OPERATION_TYPE differ by design (the whole point of the
    aux_ prefix).

    WRITTEN LIMIT (D-11): server-side *counting* is Revenium's own effect on
    what it ingested, scoped by the rule's filter -- no local test can
    observe it. This class proves only the local, falsifiable half: the row
    is emitted inside the SAME rule scope as its session's primary row. The
    counting half is confirmed live in Phase 56.
    """

    def test_agent_organization_and_attribution_parity_with_a_job_marker(self):
        sid = 'aux-parity-withjob-sid-001'
        job_id = 'aux-parity-withjob-job-001'

        fixture = self._setup_fixture(
            [self._one_session(id=sid)],
            aux_rows=[self._one_aux_row(
                session_id=sid, model='gpt-4o-mini', billing_provider='openai',
            )],
        )
        _make_trace_type_capable(os.path.join(fixture['bin_dir'], 'revenium'))

        markers_path = os.path.join(fixture['state_dir'], 'markers', f'{sid}.jsonl')
        with open(markers_path, 'w') as f:
            f.write(json.dumps({
                'muid': 'aux-parity-muid-001', 'ts': 1715515000.5, 'sid': sid,
                'task_type': 'code_review', 'operation_type': 'CHAT',
            }, separators=(',', ':')) + '\n')
            f.write(json.dumps({
                'kind': 'job', 'ts': 1715515001.0, 'sid': sid,
                'agentic_job_id': job_id, 'job_name': 'Scope Parity Job',
                'job_type': 'code_review', 'status': 'IN_PROGRESS',
            }, separators=(',', ':')) + '\n')

        config_path = os.path.join(fixture['state_dir'], 'config.json')
        with open(config_path, 'w') as f:
            json.dump({'organizationName': 'acme-corp'}, f)

        result = self._tick(fixture, 0, extra_env={'REVENIUM_AGENT_NAME': 'Hermes-scopeparity'})
        self.assertEqual(result['rc'], 0, result['output'])

        aux_list = self._find_aux_invocation(result['meter_invocations'])
        main_list = self._find_non_aux_invocation(result['meter_invocations'])
        self.assertEqual(len(aux_list), 1, result['meter_invocations'])
        self.assertEqual(len(main_list), 1, result['meter_invocations'])
        aux_flags, main_flags = aux_list[0], main_list[0]

        # Session-resolved dimensions: equal across both, and NOT a
        # hardcoded literal (proven by the non-default REVENIUM_AGENT_NAME).
        self.assertEqual(aux_flags.get('--agent'), main_flags.get('--agent'))
        self.assertEqual(aux_flags.get('--agent'), 'Hermes-scopeparity')

        self.assertEqual(aux_flags.get('--organization-name'), main_flags.get('--organization-name'))
        self.assertEqual(aux_flags.get('--organization-name'), 'acme-corp')

        self.assertEqual(aux_flags.get('--environment'), main_flags.get('--environment'))
        self.assertEqual(aux_flags.get('--trace-id'), main_flags.get('--trace-id'))
        self.assertEqual(aux_flags.get('--trace-type'), main_flags.get('--trace-type'))
        self.assertIsNotNone(aux_flags.get('--trace-type'))

        self.assertEqual(aux_flags.get('--squad-id'), main_flags.get('--squad-id'))
        self.assertEqual(aux_flags.get('--squad-name'), main_flags.get('--squad-name'))
        self.assertEqual(aux_flags.get('--squad-role'), main_flags.get('--squad-role'))

        # --agentic-job-id: present and equal on both, given the job marker.
        self.assertEqual(aux_flags.get('--agentic-job-id'), job_id)
        self.assertEqual(main_flags.get('--agentic-job-id'), job_id)

        # Deliberate row-own divergences.
        self.assertNotEqual(aux_flags.get('--operation-type'), main_flags.get('--operation-type'))
        self.assertNotEqual(aux_flags.get('--task-type'), main_flags.get('--task-type'))
        self.assertEqual(aux_flags.get('--model'), 'gpt-4o-mini')
        self.assertEqual(aux_flags.get('--provider'), 'openai')
        self.assertNotEqual(aux_flags.get('--model'), main_flags.get('--model'))
        self.assertNotEqual(aux_flags.get('--provider'), main_flags.get('--provider'))

    def test_agentic_job_id_absent_from_both_without_a_job_marker(self):
        sid = 'aux-parity-nojob-sid-001'
        fixture = self._setup_fixture(
            [self._one_session(id=sid)],
            aux_rows=[self._one_aux_row(session_id=sid)],
        )
        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])

        aux_list = self._find_aux_invocation(result['meter_invocations'])
        main_list = self._find_non_aux_invocation(result['meter_invocations'])
        self.assertEqual(len(aux_list), 1, result['meter_invocations'])
        self.assertEqual(len(main_list), 1, result['meter_invocations'])

        self.assertNotIn('--agentic-job-id', aux_list[0])
        self.assertNotIn('--agentic-job-id', main_list[0])


if __name__ == '__main__':
    unittest.main()
