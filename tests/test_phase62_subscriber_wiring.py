"""Phase 62 Plan 01 (SUB-05/07/08): the wiring proof for `--subscriber-id`
at hermes-report.sh's two `meter completion` emission sites (marker-split
and markerless).

This module's job is the four-run proof `62-01-PLAN.md`'s <the_central_property>
demands at every site it touches:

    - Run A -- CLI capable, no `user_id` column at all: captured argv equals
      the site's golden `argv_order` exactly.
    - Run B -- CLI capable, column present but NULL for this session:
      captured argv equals `argv_order` exactly.
    - Run C -- CLI capable, column present and populated: captured argv
      equals `argv_order` PLUS exactly the two trailing tokens
      (`--subscriber-id`, the resolved key), and nothing else differs.
    - Run D -- CLI NOT capable, column present and populated (SUB-07):
      captured argv equals `argv_order` exactly.

Runs B and C are each other's proof (D-05): they share the identical
fixture except for the identity VALUE, so a flag that appears
unconditionally fails Run B, and a flag that never appears fails Run C --
independently. Run A is the untouched-install arm. Run D is SUB-07.

`assert_argv_is_golden_argv_order` (tests/_compat_helpers.py) is the load-
bearing assertion throughout: `assert_argv_matches_golden` iterates only a
golden's own named fields and cannot see an ADDED flag, so it alone could
never prove Run B/D stayed byte-identical or that Run C added exactly two
tokens in exactly the right place.

Every actor id in this module is synthetic and `p62-`-prefixed; no value is
copied from any reference host.

Task 1 covers the markerless site only (`MarkerlessSubscriberWiringTests`),
reusing tests.test_phase29_agent_inheritance's exact fixture so the
deterministic values baked into meter-completion-markerless.golden.json's
argv_order still hold -- this phase adds NO new golden for the markerless
site (D-04: the existing golden IS the absent-case proof, unedited).

Task 2 extends this module with the marker-split site
(`MarkerSplitSubscriberWiringTests`, against the new argv_order this plan
adds to meter-completion.golden.json) and the multi-marker sameness proof
(`MultiMarkerSubscriberSamenessTests`).

Plan 62-02 Task 1 extends this module further with the FOURTH emission
site -- `api-event-report.sh`'s event path (`EventSubscriberWiringTests`),
against the new argv_order Plan 62-02 adds to
meter-completion-event.golden.json -- plus the pipe-in-user_id and
column-absent-environment-survives arms that site's `<behavior>` calls out
by name. `SubscriberWiringStructuralTests` below is updated in lockstep:
`EVENT_REPORT_SH` joins `SCRIPTS_WITH_SUBSCRIBER_PROBE` and
`EXPECTED_SUBSCRIBER_EMISSION_SITE_COUNT` moves from 2 to 3.

Plan 62-03 Task 1 extends this module with the FOURTH and last site --
hermes-report.sh's own auxiliary-usage pass (`AuxSubscriberWiringTests`,
`_AuxHarness`), against the SAME argv_order this plan adds to
meter-completion-aux.golden.json (captured pre-edit, before any of Plan
62-03's edits, matching tests.test_phase55_auxiliary_metering's
_AuxMeteringTestCase default fixture exactly: sid='aux-sid-001',
source='test'). No new script joins SCRIPTS_WITH_SUBSCRIBER_PROBE -- the aux
path lives inside hermes-report.sh, which already declares the probe.
`EXPECTED_SUBSCRIBER_EMISSION_SITE_COUNT` moves from 3 to 4. The
aux-specific behaviour this site's own `<behavior>` calls out (three-row
sameness, idempotency, the width-mismatch-line-absent case, and the D-09
producer/parser width proof) lives in the sibling module
tests/test_phase62_aux_backfill.py, not here -- this module stays scoped to
the four-run wiring proof shared by every site.

`SubscriberWiringStructuralTests` mirrors test_ticket_attribution.TicketWiringTests,
scoped to what has been wired as of THIS commit -- as of Plan 62-03 Task 1,
all four sites.
"""
import json
import os
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path

from tests._compat_helpers import (
    assert_argv_is_golden_argv_order,
    build_session_model_usage,
    build_shim,
    build_state_db,
    load_golden,
    run_script,
    seed_parent_session_ids,
    seed_user_ids,
    SCRIPTS_DIR,
)
from tests.test_phase61_identity_resolution import (
    _OLD_TS,
    _own_meter_invocations,
    _task_marker,
    _write_marker_lines,
)
# Imported as a MODULE reference (not `from ... import TicketWiringTests`)
# deliberately: importing the TestCase class by name would bind it into this
# module's globals, and unittest's discovery/loadTestsFromModule would then
# re-collect and re-run it a second time under this module -- a module
# reference does not get picked up as a TestCase subclass.
import tests.test_ticket_attribution as _test_ticket_attribution

HERMES_REPORT_SH = SCRIPTS_DIR / 'hermes-report.sh'
EVENT_REPORT_SH = SCRIPTS_DIR / 'api-event-report.sh'


def _write_jsonl(path, records):
    with open(path, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, separators=(',', ':')) + '\n')

# How far back an emission may sit from its guard. Set EQUAL to
# TicketWiringTests.GUARD_LOOKBACK (rather than a second literal 12) so the
# two lookback bounds cannot drift independently of each other.
GUARD_LOOKBACK = _test_ticket_attribution.TicketWiringTests.GUARD_LOOKBACK

# How many `meter completion` emission SITES across skills/revenium/scripts/
# are expected to append --subscriber-id at the end of THIS commit. Counts
# sites, not scripts (both hermes-report.sh sites plus, as of Plan 62-02
# Task 1, api-event-report.sh's event-path site) -- confirmed by grep in
# each task, never by arithmetic on the prior value. Bumped deliberately by
# each task/plan in this phase (62-01: 1 then 2; 62-02 Task 1 here: 3, for
# the event path; 62-03 adds the aux path).
#
# Deliberate deviation from 62-01-PLAN.md's literal step-7 wording ("set to
# 2 in this plan"): that value was the correct FINAL state of THAT plan
# (both its tasks), but each test module commit must also pass on its own,
# so the constant tracks the ACTUAL state at each commit rather than a
# plan's final-state wording -- recorded as a deviation in 62-01-SUMMARY.md
# and continued here.
#
# Plan 62-03 Task 1: bumped 3 -> 4 for the auxiliary pass's own
# --subscriber-id append (hermes-report.sh, after the squad block) --
# confirmed by `grep -c -- '--subscriber-id "' skills/revenium/scripts/*.sh`
# = 3 (hermes-report.sh) + 1 (api-event-report.sh) = 4.
EXPECTED_SUBSCRIBER_EMISSION_SITE_COUNT = 4

# Scripts that declare the SUBSCRIBER_CLI_CAPABLE probe as of THIS commit.
# api-event-report.sh joins this tuple in Plan 62-02 Task 1 (the event
# path); 62-03 does not add a third script -- the aux path lives inside
# hermes-report.sh.
SCRIPTS_WITH_SUBSCRIBER_PROBE = (HERMES_REPORT_SH, EVENT_REPORT_SH)


class _Harness:
    """One temp HERMES_HOME + PATH-shim `revenium` + one meter log,
    parameterised on `subscriber_capable` so Run D (CLI incapable) is a
    real, separate shim process rather than a flag threaded through every
    call site. Mirrors tests.test_phase61_subscriber_boundary._Harness,
    itself mirroring tests.test_phase61_identity_resolution's harness.
    """

    def __init__(self, subscriber_capable=True, prefix='gsd-phase62-wiring-'):
        self.tmp = tempfile.mkdtemp(prefix=prefix)
        self.hermes_home = os.path.join(self.tmp, 'hh')
        self.state_dir = os.path.join(self.hermes_home, 'state', 'revenium')
        self.markers_dir = os.path.join(self.state_dir, 'markers')
        os.makedirs(self.markers_dir, mode=0o700)
        self.state_db = os.path.join(self.hermes_home, 'state.db')
        self.log_file = os.path.join(self.state_dir, 'revenium-metering.log')

        self.shim_home = os.path.join(self.tmp, 'home')
        self.bin_dir = os.path.join(self.shim_home, '.local', 'bin')
        os.makedirs(self.bin_dir)
        self.meter_log = os.path.join(self.tmp, 'meter.log')
        self.jobs_log = os.path.join(self.tmp, 'jobs.log')
        self.inv_log = os.path.join(self.tmp, 'inv.log')
        self.shim = os.path.join(self.bin_dir, 'revenium')
        build_shim(
            self.shim, squad_capable=True, subscriber_capable=subscriber_capable
        )

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def base_env(self):
        return {
            **os.environ,
            'HOME': self.shim_home,
            'HERMES_HOME': self.hermes_home,
            'REVENIUM_STATE_DIR': self.state_dir,
            'PATH': self.bin_dir + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': self.inv_log,
            'METER_LOG': self.meter_log,
            'JOBS_LOG': self.jobs_log,
            'TZ': 'UTC',
            'REVENIUM_ORGANIZATION_NAME': '',
            'REVENIUM_AGENT_NAME': 'Hermes',
            'REVENIUM_SQUAD_NAME': '',
        }

    def run(self):
        rc, _ignored_inv, output = run_script(
            HERMES_REPORT_SH, self.base_env(), self.inv_log
        )
        meter_invocations = []
        if os.path.exists(self.meter_log):
            with open(self.meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        meter_invocations.append(shlex.split(line))
        if rc != 0:
            raise AssertionError(f'hermes-report.sh failed (rc={rc}): {output}')
        return meter_invocations


class MarkerlessSubscriberWiringTests(unittest.TestCase):
    """Task 1: the four-run proof for the markerless emit path.

    Reuses tests.test_phase29_agent_inheritance's exact fixture (same sid,
    model, source='test', tokens, timestamps) so the deterministic values
    baked into meter-completion-markerless.golden.json's argv_order still
    hold. `source` stays 'test' (not a synthetic source) specifically
    because it must match the golden's own `--environment` field; only the
    ACTOR id is a synthetic p62- value.
    """

    SID = 'compat-sid-markerless-001'
    ACTOR = 'p62-markerless-actor'

    def _seed(self, subscriber_capable, user_id_mapping=None):
        tree = _Harness(subscriber_capable=subscriber_capable)
        build_state_db(tree.state_db, [{
            'id': self.SID,
            'model': 'claude-sonnet-4-6',
            'source': 'test',
            'input_tokens': 100,
            'output_tokens': 50,
            'cache_read': 0,
            'cache_write': 0,
            'reasoning': 0,
            'estimated_cost': '0',
            'api_calls': 1,
            'started_at': _OLD_TS,
            'ended_at': _OLD_TS,
            'billing_provider': 'anthropic',
        }])
        if user_id_mapping is not None:
            seed_user_ids(tree.state_db, user_id_mapping)
        return tree

    def test_run_a_capable_no_user_id_column_matches_golden_argv_order(self):
        """Run A: CLI advertises the flag, `sessions` has no `user_id`
        column at all (the pre-Phase-61 schema, `build_state_db`'s exact
        13-column shape used at 139 call sites). Captured argv equals the
        golden's argv_order exactly -- the untouched-install arm.

        MISSES: proves the argv this skill CONSTRUCTS, not that Revenium
        accepts the flag (Phase 64); pins ONE session shape (no marker, no
        ticket, no skill), so a session carrying several attribution flags
        at once has its interleaving untested here.
        """
        tree = self._seed(subscriber_capable=True)
        try:
            invocations = tree.run()
            own = _own_meter_invocations(invocations, self.SID)
            self.assertEqual(len(own), 1, own)
            golden = load_golden('meter-completion-markerless.golden.json')
            assert_argv_is_golden_argv_order(self, own[0], golden)
        finally:
            tree.cleanup()

    def test_run_b_capable_column_present_null_matches_golden_argv_order(self):
        """Run B: CLI advertises the flag, column present but NULL for this
        session. Captured argv equals argv_order exactly -- proves the
        capability probe's presence ALONE never appends the flag; only a
        RESOLVED key does. Run B and Run C (below) share this exact
        fixture, differing only in the identity VALUE (D-05): that is what
        makes an unconditionally-appearing flag fail THIS test
        independently of whether Run C's assertion also fails.

        MISSES: says nothing about the schema-absent case (Run A above).
        """
        tree = self._seed(
            subscriber_capable=True, user_id_mapping={self.SID: None}
        )
        try:
            invocations = tree.run()
            own = _own_meter_invocations(invocations, self.SID)
            self.assertEqual(len(own), 1, own)
            golden = load_golden('meter-completion-markerless.golden.json')
            assert_argv_is_golden_argv_order(self, own[0], golden)
        finally:
            tree.cleanup()

    def test_run_c_capable_column_populated_matches_golden_plus_two_tokens(self):
        """Run C: CLI advertises the flag, column present and populated.
        Captured argv equals argv_order plus exactly the two trailing
        tokens for the flag and the resolved key, in that order, and
        nothing else differs. Run B (above) and this run are each other's
        proof (D-05): sharing this fixture except for the identity value
        means a flag that appears unconditionally fails Run B, and a flag
        that never appears fails this one -- independently.

        MISSES: does not prove the resolved key names the right actor --
        that is Phase 61's contract, not this phase's.
        """
        tree = self._seed(
            subscriber_capable=True, user_id_mapping={self.SID: self.ACTOR}
        )
        try:
            invocations = tree.run()
            own = _own_meter_invocations(invocations, self.SID)
            self.assertEqual(len(own), 1, own)
            golden = load_golden('meter-completion-markerless.golden.json')
            expected_key = f'test:{self.ACTOR}'
            assert_argv_is_golden_argv_order(
                self, own[0], golden,
                extra_tail=('--subscriber-id', expected_key),
            )
        finally:
            tree.cleanup()

    def test_run_d_incapable_column_populated_matches_golden_argv_order(self):
        """Run D (SUB-07): CLI does NOT advertise the flag, column present
        and populated. Captured argv equals argv_order exactly -- an
        install running an older `revenium` CLI must meter byte-identically
        even when an actor DOES resolve; the probe, not the resolved value,
        gates emission.

        MISSES: this is a synthetic incapable shim, not a live older CLI;
        Phase 64's live-host proof is the corroborating evidence for a real
        install.
        """
        tree = self._seed(
            subscriber_capable=False, user_id_mapping={self.SID: self.ACTOR}
        )
        try:
            invocations = tree.run()
            own = _own_meter_invocations(invocations, self.SID)
            self.assertEqual(len(own), 1, own)
            golden = load_golden('meter-completion-markerless.golden.json')
            assert_argv_is_golden_argv_order(self, own[0], golden)
        finally:
            tree.cleanup()


class MarkerSplitSubscriberWiringTests(unittest.TestCase):
    """Task 2: the four-run proof for the marker-split emit path.

    Reuses tests.test_compat_meter_completion.py's exact fixture (sid,
    muid, job id, model, tokens, source='test') so the values baked into
    meter-completion.golden.json's new argv_order (this plan's own
    addition, D-05) still hold. `source` stays 'test' for the same reason
    as the markerless class above; only the ACTOR id is a synthetic p62-
    value.
    """

    SID = 'compat-sid-001'
    MUID = 'compat-muid-001'
    ACTOR = 'p62-marker-actor'

    def _seed(self, subscriber_capable, user_id_mapping=None):
        tree = _Harness(subscriber_capable=subscriber_capable)
        build_state_db(tree.state_db, [{
            'id': self.SID,
            'model': 'claude-sonnet-4-6',
            'source': 'test',
            'input_tokens': 100,
            'output_tokens': 50,
            'cache_read': 0,
            'cache_write': 0,
            'reasoning': 0,
            'estimated_cost': '0',
            'api_calls': 1,
            'started_at': _OLD_TS,
            'ended_at': _OLD_TS,
            'billing_provider': 'anthropic',
        }])
        if user_id_mapping is not None:
            seed_user_ids(tree.state_db, user_id_mapping)
        # Production hosts carry parent_session_id (research F4); D-17 attributes a
        # resolved owner only on positive root evidence.
        seed_parent_session_ids(tree.state_db, {self.SID: None})
        task_marker = {
            'muid': self.MUID,
            'ts': 1715515000.5,
            'sid': self.SID,
            'task_type': 'code_review',
            'operation_type': 'CHAT',
        }
        job_marker = {
            'kind': 'job',
            'ts': 1715515001.0,
            'sid': self.SID,
            'agentic_job_id': 'compat-job-001',
            'job_name': 'COMPAT Test Job',
            'job_type': 'code_review',
            'status': 'IN_PROGRESS',
        }
        _write_marker_lines(tree.markers_dir, self.SID, [task_marker, job_marker])
        return tree

    def test_run_a_capable_no_user_id_column_matches_golden_argv_order(self):
        """Run A: CLI advertises the flag, `sessions` has no `user_id`
        column at all. Captured argv equals the golden's argv_order exactly
        -- the untouched-install arm.

        MISSES: proves the argv this skill CONSTRUCTS, not that Revenium
        accepts the flag (Phase 64); pins ONE session shape (one marker,
        one job marker) -- the multi-marker sameness proof is a separate
        class below.
        """
        tree = self._seed(subscriber_capable=True)
        try:
            invocations = tree.run()
            own = _own_meter_invocations(invocations, self.SID)
            self.assertEqual(len(own), 1, own)
            golden = load_golden('meter-completion.golden.json')
            assert_argv_is_golden_argv_order(self, own[0], golden)
        finally:
            tree.cleanup()

    def test_run_b_capable_column_present_null_matches_golden_argv_order(self):
        """Run B: CLI advertises the flag, column present but NULL for this
        session. Captured argv equals argv_order exactly -- proves the
        capability probe's presence ALONE never appends the flag; only a
        RESOLVED key does. Run B and Run C (below) share this exact
        fixture, differing only in the identity VALUE (D-05).

        MISSES: says nothing about the schema-absent case (Run A above).
        """
        tree = self._seed(
            subscriber_capable=True, user_id_mapping={self.SID: None}
        )
        try:
            invocations = tree.run()
            own = _own_meter_invocations(invocations, self.SID)
            self.assertEqual(len(own), 1, own)
            golden = load_golden('meter-completion.golden.json')
            assert_argv_is_golden_argv_order(self, own[0], golden)
        finally:
            tree.cleanup()

    def test_run_c_capable_column_populated_matches_golden_plus_two_tokens(self):
        """Run C: CLI advertises the flag, column present and populated.
        Captured argv equals argv_order plus exactly the two trailing
        tokens for the flag and the resolved key, and nothing else differs.
        Run B (above) and this run are each other's proof (D-05).

        MISSES: does not prove the resolved key names the right actor --
        that is Phase 61's contract, not this phase's.
        """
        tree = self._seed(
            subscriber_capable=True, user_id_mapping={self.SID: self.ACTOR}
        )
        try:
            invocations = tree.run()
            own = _own_meter_invocations(invocations, self.SID)
            self.assertEqual(len(own), 1, own)
            golden = load_golden('meter-completion.golden.json')
            expected_key = f'test:{self.ACTOR}'
            assert_argv_is_golden_argv_order(
                self, own[0], golden,
                extra_tail=('--subscriber-id', expected_key),
            )
        finally:
            tree.cleanup()

    def test_run_d_incapable_column_populated_matches_golden_argv_order(self):
        """Run D (SUB-07): CLI does NOT advertise the flag, column present
        and populated. Captured argv equals argv_order exactly.

        MISSES: this is a synthetic incapable shim, not a live older CLI;
        Phase 64's live-host proof is the corroborating evidence for a real
        install.
        """
        tree = self._seed(
            subscriber_capable=False, user_id_mapping={self.SID: self.ACTOR}
        )
        try:
            invocations = tree.run()
            own = _own_meter_invocations(invocations, self.SID)
            self.assertEqual(len(own), 1, own)
            golden = load_golden('meter-completion.golden.json')
            assert_argv_is_golden_argv_order(self, own[0], golden)
        finally:
            tree.cleanup()


class MultiMarkerSubscriberSamenessTests(unittest.TestCase):
    """Task 2 <behavior>: a session with THREE task markers and ONE
    resolved actor ships three `meter completion` calls, and all three
    carry the SAME subscriber key -- the actor is a property of the
    SESSION, not of a marker. The negative arm (three markers, no resolved
    actor) ships three calls carrying no subscriber token at all.

    MISSES: proves the key is uniform across markers of ONE session; says
    nothing about two SESSIONS sharing a trace (a squad/subagent scenario)
    -- untested here.
    """

    SID = 'p62-multi-marker'
    ACTOR = 'p62-multi-actor'

    def _seed(self, with_actor):
        tree = _Harness(subscriber_capable=True)
        build_state_db(tree.state_db, [{
            'id': self.SID,
            'model': 'claude-sonnet-4-6',
            'source': 'slack',
            'input_tokens': 300,
            'output_tokens': 150,
            'cache_read': 0,
            'cache_write': 0,
            'reasoning': 0,
            'estimated_cost': '0',
            'api_calls': 1,
            'started_at': _OLD_TS,
            'ended_at': _OLD_TS,
            'billing_provider': 'anthropic',
        }])
        seed_user_ids(
            tree.state_db,
            {self.SID: self.ACTOR if with_actor else None},
        )
        _write_marker_lines(tree.markers_dir, self.SID, [
            _task_marker(self.SID, 'p62-muid-1'),
            _task_marker(self.SID, 'p62-muid-2'),
            _task_marker(self.SID, 'p62-muid-3'),
        ])
        return tree

    def test_three_markers_one_resolved_actor_all_calls_carry_same_key(self):
        tree = self._seed(with_actor=True)
        try:
            invocations = tree.run()
            own = _own_meter_invocations(invocations, self.SID)
            self.assertEqual(len(own), 3, own)
            expected_key = f'slack:{self.ACTOR}'
            for argv in own:
                self.assertIn('--subscriber-id', argv, argv)
                idx = argv.index('--subscriber-id')
                self.assertEqual(argv[idx + 1], expected_key, argv)
        finally:
            tree.cleanup()

    def test_three_markers_no_resolved_actor_no_calls_carry_subscriber_token(self):
        tree = self._seed(with_actor=False)
        try:
            invocations = tree.run()
            own = _own_meter_invocations(invocations, self.SID)
            self.assertEqual(len(own), 3, own)
            for argv in own:
                self.assertNotIn('--subscriber-id', argv, argv)
        finally:
            tree.cleanup()


class _EventHarness:
    """One temp HERMES_HOME + PATH-shim `revenium` + one meter log for
    api-event-report.sh, mirroring `_Harness` above but wired for the event
    path's spool/markers/.ready layout rather than hermes-report.sh's
    marker/state.db layout. The spool record and marker pair are FIXED --
    byte-identical to test_compat_meter_completion_event.py's own fixture --
    so this class's runs share meter-completion-event.golden.json's
    argv_order with that compat test, per that golden's own 'captured'
    provenance note (which records this exact richer-fixture shape: the
    compat test's OWN fixture seeds no `sessions` table at all).
    """

    SID = 'compat-event-sid-001'
    ARID = 'compat-event-arid-001'

    def __init__(self, subscriber_capable=True, subscriber_email_capable=False,
                 email_mode=None, event_metering_mode='live',
                 prefix='gsd-phase62-event-'):
        self.tmp = tempfile.mkdtemp(prefix=prefix)
        self.hermes_home = os.path.join(self.tmp, 'hh')
        self.state_dir = os.path.join(self.hermes_home, 'state', 'revenium')
        self.spool_dir = os.path.join(self.state_dir, 'api-events')
        self.markers_dir = os.path.join(self.state_dir, 'markers')
        self.ready_dir = os.path.join(self.markers_dir, '.ready')
        os.makedirs(self.spool_dir, mode=0o700)
        os.makedirs(self.markers_dir, mode=0o700)
        os.makedirs(self.ready_dir, mode=0o700)
        self.state_db = os.path.join(self.hermes_home, 'state.db')

        self.shim_home = os.path.join(self.tmp, 'home')
        self.bin_dir = os.path.join(self.shim_home, '.local', 'bin')
        os.makedirs(self.bin_dir)
        self.meter_log = os.path.join(self.tmp, 'meter.log')
        self.inv_log = os.path.join(self.tmp, 'inv.log')
        self.shim = os.path.join(self.bin_dir, 'revenium')
        # subscriber_email_capable/email_mode (Phase 63, SUB-06): default
        # False/None so every existing caller of this harness (Phase 62's
        # own EventSubscriberWiringTests) keeps exercising the pre-Phase-63
        # shim/env shape byte-for-byte -- only a Phase 63 caller opts in.
        build_shim(
            self.shim, subscriber_capable=subscriber_capable,
            subscriber_email_capable=subscriber_email_capable,
        )
        self.email_mode = email_mode
        self.event_metering_mode = event_metering_mode

        Path(self.ready_dir, self.SID).touch()
        _write_jsonl(os.path.join(self.spool_dir, f'{self.SID}.jsonl'), [{
            'v': 1, 'sid': self.SID, 'api_request_id': self.ARID,
            'ts': 1715514000.5, 'ended_at': 1715514001.0,
            'duration_ms': 500, 'platform': 'cli',
            'model': 'compat-session-model-should-not-ship',
            'response_model': 'claude-sonnet-4-6',
            'provider': 'anthropic',
            'base_url': 'https://api.anthropic.com',
            'api_mode': 'anthropic_messages',
            'finish_reason': 'stop',
            'input_tokens': 100, 'output_tokens': 50,
            'cache_read_tokens': 10, 'cache_write_tokens': 5,
            'reasoning_tokens': 0, 'total_tokens': 165,
        }])
        _write_jsonl(os.path.join(self.markers_dir, f'{self.SID}.jsonl'), [
            {'muid': 'compat-event-muid-001', 'ts': 1715513900.0,
             'sid': self.SID, 'task_type': 'code_review',
             'operation_type': 'GUARDRAIL'},
            {'muid': 'compat-event-muid-002', 'ts': 1715513900.5,
             'sid': self.SID, 'task_type': 'code_review',
             'operation_type': 'CHAT',
             'agentic_job_id': 'compat-event-job-001'},
        ])

    def seed_session(self, source='test', user_id_mapping=None):
        """Add a `sessions` row (the golden's own values, source='test') so
        the environment dimension is present, then optionally add/set
        `user_id` via seed_user_ids. Omitting `user_id_mapping` entirely
        (the default) is Run A -- no ALTER TABLE at all, the column-absent
        arm; passing `{SID: None}` is Run B; a real value is Run C/D.
        """
        build_state_db(self.state_db, [{
            'id': self.SID,
            'model': 'claude-sonnet-4-6',
            'source': source,
            'input_tokens': 100,
            'output_tokens': 50,
            'cache_read': 10,
            'cache_write': 5,
            'reasoning': 0,
            'estimated_cost': '0',
            'api_calls': 1,
            'started_at': 1715514000.5,
            'ended_at': 1715514001.0,
            'billing_provider': 'anthropic',
        }])
        if user_id_mapping is not None:
            seed_user_ids(self.state_db, user_id_mapping)

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def base_env(self):
        env = {
            **os.environ,
            'HOME': self.shim_home,
            'HERMES_HOME': self.hermes_home,
            'REVENIUM_STATE_DIR': self.state_dir,
            'PATH': self.bin_dir + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': self.inv_log,
            'METER_LOG': self.meter_log,
            'TZ': 'UTC',
            'REVENIUM_EVENT_METERING_MODE': self.event_metering_mode,
        }
        env.pop('REVENIUM_SUBSCRIBER_EMAIL_MODE', None)
        if self.email_mode is not None:
            env['REVENIUM_SUBSCRIBER_EMAIL_MODE'] = self.email_mode
        return env

    def run(self):
        rc, _ignored_inv, output = run_script(
            EVENT_REPORT_SH, self.base_env(), self.inv_log
        )
        meter_invocations = []
        if os.path.exists(self.meter_log):
            with open(self.meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        meter_invocations.append(shlex.split(line))
        if rc != 0:
            raise AssertionError(
                f'api-event-report.sh failed (rc={rc}): {output}'
            )
        return meter_invocations


class EventSubscriberWiringTests(unittest.TestCase):
    """Plan 62-02 Task 1: the four-run proof for the event-path emit site
    (api-event-report.sh), against meter-completion-event.golden.json's new
    argv_order -- captured from the pre-emission-edit tree, with a
    `sessions` row added so the environment dimension is a CONSTANT across
    all four runs (that golden's own 'captured' key records this).

    Plus the two additional arms this site's PLAN.md <behavior> calls out
    by name: an unsafe (pipe-bearing) actor id ships no subscriber token
    while leaving --environment and --total-tokens on the same row
    untouched, and the identity-column-absent arm still carries
    --environment -- proof the ten-column map did not come back empty
    (T-62-08).
    """

    ACTOR = 'p62-event-actor'

    def test_run_a_capable_no_user_id_column_matches_golden_argv_order(self):
        """Run A: CLI advertises the flag, `sessions` has no `user_id`
        column at all. Captured argv equals the golden's argv_order exactly
        -- the untouched-install arm, and (T-62-08) --environment is still
        present, proving the ten-column map did not come back empty.
        """
        tree = _EventHarness(subscriber_capable=True)
        try:
            tree.seed_session()
            invocations = tree.run()
            self.assertEqual(len(invocations), 1, invocations)
            golden = load_golden('meter-completion-event.golden.json')
            assert_argv_is_golden_argv_order(self, invocations[0], golden)
            self.assertIn('--environment', invocations[0], invocations[0])
        finally:
            tree.cleanup()

    def test_run_b_capable_column_present_null_matches_golden_argv_order(self):
        """Run B: CLI advertises the flag, column present but NULL for this
        session. Captured argv equals argv_order exactly -- proves the
        capability probe's presence ALONE never appends the flag; only a
        RESOLVED key does. Run B and Run C (below) share this exact
        fixture, differing only in the identity VALUE.
        """
        tree = _EventHarness(subscriber_capable=True)
        try:
            tree.seed_session(user_id_mapping={_EventHarness.SID: None})
            invocations = tree.run()
            self.assertEqual(len(invocations), 1, invocations)
            golden = load_golden('meter-completion-event.golden.json')
            assert_argv_is_golden_argv_order(self, invocations[0], golden)
        finally:
            tree.cleanup()

    def test_run_c_capable_column_populated_matches_golden_plus_two_tokens(self):
        """Run C: CLI advertises the flag, column present and populated.
        Captured argv equals argv_order plus exactly the two trailing
        tokens for the flag and the resolved key, and nothing else differs.
        """
        tree = _EventHarness(subscriber_capable=True)
        try:
            tree.seed_session(
                user_id_mapping={_EventHarness.SID: self.ACTOR}
            )
            invocations = tree.run()
            self.assertEqual(len(invocations), 1, invocations)
            golden = load_golden('meter-completion-event.golden.json')
            expected_key = f'test:{self.ACTOR}'
            assert_argv_is_golden_argv_order(
                self, invocations[0], golden,
                extra_tail=('--subscriber-id', expected_key),
            )
        finally:
            tree.cleanup()

    def test_run_d_incapable_column_populated_matches_golden_argv_order(self):
        """Run D (SUB-07): CLI does NOT advertise the flag, column present
        and populated. Captured argv equals argv_order exactly -- the
        probe, not the resolved value, gates emission.
        """
        tree = _EventHarness(subscriber_capable=False)
        try:
            tree.seed_session(
                user_id_mapping={_EventHarness.SID: self.ACTOR}
            )
            invocations = tree.run()
            self.assertEqual(len(invocations), 1, invocations)
            golden = load_golden('meter-completion-event.golden.json')
            assert_argv_is_golden_argv_order(self, invocations[0], golden)
        finally:
            tree.cleanup()

    def test_pipe_in_user_id_ships_no_token_environment_and_tokens_intact(self):
        """A session whose stored actor id contains a pipe ships NO
        subscriber token, and the environment dimension and total-tokens
        value on that same row are unaffected -- the unsafe value is
        REJECTED, not sanitised into a plausible different key.
        """
        tree = _EventHarness(subscriber_capable=True)
        try:
            tree.seed_session(user_id_mapping={_EventHarness.SID: 'U|600'})
            invocations = tree.run()
            self.assertEqual(len(invocations), 1, invocations)
            argv = invocations[0]
            self.assertNotIn('--subscriber-id', argv, argv)
            golden = load_golden('meter-completion-event.golden.json')
            assert_argv_is_golden_argv_order(self, argv, golden)
            idx = argv.index('--total-tokens')
            self.assertEqual(argv[idx + 1], '165', argv)
        finally:
            tree.cleanup()


class _AuxHarness:
    """One temp HERMES_HOME + PATH-shim `revenium` + one meter log for
    hermes-report.sh's auxiliary-usage pass, mirroring `_Harness` above but
    additionally seeding `session_model_usage` (Phase 55) so a real
    auxiliary row exists to emit.

    The seeded `sessions` and `session_model_usage` rows are deliberately
    byte-identical to tests.test_phase55_auxiliary_metering
    ._AuxMeteringTestCase's own defaults (_one_session()/_one_aux_row(),
    sid='aux-sid-001') -- NOT imported from that module (this plan's
    files_modified list does not touch it), but reproduced here because
    meter-completion-aux.golden.json's argv_order was captured against that
    exact fixture shape (see the golden's own 'captured' provenance note);
    a different sid/model/token shape would not compare byte-identically.
    """

    SID = 'aux-sid-001'

    def __init__(self, subscriber_capable=True, prefix='gsd-phase62-aux-'):
        self.tmp = tempfile.mkdtemp(prefix=prefix)
        self.hermes_home = os.path.join(self.tmp, 'hh')
        self.state_dir = os.path.join(self.hermes_home, 'state', 'revenium')
        self.markers_dir = os.path.join(self.state_dir, 'markers')
        os.makedirs(self.markers_dir, mode=0o700)
        self.state_db = os.path.join(self.hermes_home, 'state.db')
        self.log_file = os.path.join(self.state_dir, 'revenium-metering.log')

        self.shim_home = os.path.join(self.tmp, 'home')
        self.bin_dir = os.path.join(self.shim_home, '.local', 'bin')
        os.makedirs(self.bin_dir)
        self.meter_log = os.path.join(self.tmp, 'meter.log')
        self.jobs_log = os.path.join(self.tmp, 'jobs.log')
        self.inv_log = os.path.join(self.tmp, 'inv.log')
        self.shim = os.path.join(self.bin_dir, 'revenium')
        build_shim(
            self.shim, squad_capable=True, subscriber_capable=subscriber_capable
        )

        build_state_db(self.state_db, [{
            'id': self.SID,
            'model': 'claude-sonnet-4-6',
            'source': 'test',
            'input_tokens': 100,
            'output_tokens': 50,
            'cache_read': 0,
            'cache_write': 0,
            'reasoning': 0,
            'estimated_cost': '0',
            'api_calls': 1,
            'started_at': _OLD_TS,
            'ended_at': _OLD_TS,
            'billing_provider': 'anthropic',
        }])
        build_session_model_usage(self.state_db, [{
            'session_id': self.SID,
            'model': 'claude-3-5-haiku',
            'billing_provider': 'anthropic',
            'task': 'approval',
            'api_call_count': 3,
            'input_tokens': 40,
            'output_tokens': 10,
            'estimated_cost_usd': 0.002,
            'first_seen': _OLD_TS + 500.0,
            'last_seen': _OLD_TS + 600.0,
        }])

    def seed_user_id(self, mapping):
        seed_user_ids(self.state_db, mapping)

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def base_env(self):
        return {
            **os.environ,
            'HOME': self.shim_home,
            'HERMES_HOME': self.hermes_home,
            'REVENIUM_STATE_DIR': self.state_dir,
            'PATH': self.bin_dir + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': self.inv_log,
            'METER_LOG': self.meter_log,
            'JOBS_LOG': self.jobs_log,
            'TZ': 'UTC',
            'REVENIUM_ORGANIZATION_NAME': '',
            'REVENIUM_AGENT_NAME': 'Hermes',
            'REVENIUM_SQUAD_NAME': '',
        }

    def run(self):
        rc, _ignored_inv, output = run_script(
            HERMES_REPORT_SH, self.base_env(), self.inv_log
        )
        meter_invocations = []
        if os.path.exists(self.meter_log):
            with open(self.meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        meter_invocations.append(shlex.split(line))
        if rc != 0:
            raise AssertionError(f'hermes-report.sh failed (rc={rc}): {output}')
        return meter_invocations

    @staticmethod
    def aux_invocation(invocations):
        """Return the single invocation carrying --operation-type OTHER, or
        raise if there isn't exactly one -- the aux row, distinguished from
        the main-loop CHAT invocation the same tick also ships."""
        aux = [
            inv for inv in invocations
            if '--operation-type' in inv
            and inv[inv.index('--operation-type') + 1] == 'OTHER'
        ]
        if len(aux) != 1:
            raise AssertionError(
                f'expected exactly 1 aux (--operation-type OTHER) invocation, '
                f'got {len(aux)}: {invocations!r}'
            )
        return aux[0]


class AuxSubscriberWiringTests(unittest.TestCase):
    """Plan 62-03 Task 1: the four-run proof for the FOURTH and last emission
    site -- hermes-report.sh's auxiliary-usage pass -- against
    meter-completion-aux.golden.json's new argv_order (captured pre-edit,
    before any of this plan's changes existed on this site)."""

    ACTOR = 'p62-aux-actor'

    def test_run_a_capable_no_user_id_column_matches_golden_argv_order(self):
        """Run A: CLI advertises the flag, `sessions` has no `user_id`
        column at all. Captured argv equals the golden's argv_order exactly
        -- the untouched-install arm."""
        tree = _AuxHarness(subscriber_capable=True)
        try:
            invocations = tree.run()
            aux = tree.aux_invocation(invocations)
            golden = load_golden('meter-completion-aux.golden.json')
            assert_argv_is_golden_argv_order(self, aux, golden)
        finally:
            tree.cleanup()

    def test_run_b_capable_column_present_null_matches_golden_argv_order(self):
        """Run B: CLI advertises the flag, column present but NULL for this
        session. Captured argv equals argv_order exactly -- proves the
        capability probe's presence ALONE never appends the flag; only a
        RESOLVED key does."""
        tree = _AuxHarness(subscriber_capable=True)
        try:
            tree.seed_user_id({_AuxHarness.SID: None})
            invocations = tree.run()
            aux = tree.aux_invocation(invocations)
            golden = load_golden('meter-completion-aux.golden.json')
            assert_argv_is_golden_argv_order(self, aux, golden)
        finally:
            tree.cleanup()

    def test_run_c_capable_column_populated_matches_golden_plus_two_tokens(self):
        """Run C: CLI advertises the flag, column present and populated.
        Captured argv equals argv_order plus exactly the two trailing
        tokens for the flag and the resolved key, and nothing else
        differs."""
        tree = _AuxHarness(subscriber_capable=True)
        try:
            tree.seed_user_id({_AuxHarness.SID: self.ACTOR})
            invocations = tree.run()
            aux = tree.aux_invocation(invocations)
            golden = load_golden('meter-completion-aux.golden.json')
            expected_key = f'test:{self.ACTOR}'
            assert_argv_is_golden_argv_order(
                self, aux, golden,
                extra_tail=('--subscriber-id', expected_key),
            )
        finally:
            tree.cleanup()

    def test_run_d_incapable_column_populated_matches_golden_argv_order(self):
        """Run D (SUB-07): CLI does NOT advertise the flag, column present
        and populated. Captured argv equals argv_order exactly -- the
        probe, not the resolved value, gates emission."""
        tree = _AuxHarness(subscriber_capable=False)
        try:
            tree.seed_user_id({_AuxHarness.SID: self.ACTOR})
            invocations = tree.run()
            aux = tree.aux_invocation(invocations)
            golden = load_golden('meter-completion-aux.golden.json')
            assert_argv_is_golden_argv_order(self, aux, golden)
        finally:
            tree.cleanup()


class SubscriberWiringStructuralTests(unittest.TestCase):
    """Structural guards mirroring test_ticket_attribution.TicketWiringTests,
    scoped to what has been wired as of THIS commit (see module docstring):
    all four emission sites, as of Plan 62-03 Task 1."""

    def test_probe_declared_with_subcommand_scoped_supports_flag(self):
        for script in SCRIPTS_WITH_SUBSCRIBER_PROBE:
            with self.subTest(script=script.name):
                text = script.read_text()
                self.assertIn('SUBSCRIBER_CLI_CAPABLE=false', text)
                self.assertIn(
                    'supports_flag "meter completion" "--subscriber-id"',
                    text,
                )

    def test_each_emission_guarded_within_lookback_and_count_matches_constant(self):
        """A CLI without the flag must meter byte-identically to before, so
        every real `--subscriber-id "` emission line must sit within
        GUARD_LOOKBACK lines of a `SUBSCRIBER_CLI_CAPABLE` guard -- the
        guard is never on the emitting line itself (it opens a block a few
        lines above), so this walks backwards from each emission rather
        than matching within the line. The total emission count across the
        in-scope scripts is also asserted against the module constant,
        confirmed here by grep, never by arithmetic on a prior value: if
        this fails, the CONSTANT is wrong and the grep is right.
        """
        total = 0
        for script in SCRIPTS_WITH_SUBSCRIBER_PROBE:
            lines = script.read_text().splitlines()
            emissions = [
                i for i, l in enumerate(lines) if '--subscriber-id "' in l
            ]
            with self.subTest(script=script.name):
                self.assertTrue(
                    emissions,
                    f'{script.name} emits --subscriber-id nowhere',
                )
                for i in emissions:
                    window = lines[max(0, i - GUARD_LOOKBACK):i]
                    self.assertTrue(
                        any('SUBSCRIBER_CLI_CAPABLE' in w for w in window),
                        f'{script.name}:{i + 1} emits --subscriber-id with '
                        f'no SUBSCRIBER_CLI_CAPABLE guard within '
                        f'{GUARD_LOOKBACK} lines above it',
                    )
            total += len(emissions)
        self.assertEqual(total, EXPECTED_SUBSCRIBER_EMISSION_SITE_COUNT)


if __name__ == '__main__':
    unittest.main()
