"""Trace naming, classification-pair collapse and the dependency graph.

Three defects shared one trace in the Revenium UI (evidence: ent profile,
session 20261012_203603_5008d5, 49,796 tokens):

  1. every trace read "Unnamed trace" -- hermes-report.sh never sent
     --trace-name;
  2. one classification shipped as TWO completions -- the classifier writes a
     GUARDRAIL marker and a CHAT marker back to back, the reporter equal-split
     the delta across both, and each half carried the SAME request-duration, so
     the timeline showed two near-identical $0.070 / 1.11 min rows;
  3. the dependency graph drew three unlinked nodes -- nothing ever sent
     --parent-transaction-id.

Everything here drives the REAL hermes-report.sh (same PATH-shim + state.db
idiom as tests/test_compat_meter_completion.py) or the real
split_strategies.py helpers it calls; nothing asserts against a literal the
test itself authored when the script's own output can be read instead.

The default build_shim() advertises neither --trace-name nor
--parent-transaction-id, so every other golden in the suite keeps pinning the
"older CLI" argv. That is the standing proof both flags fail open; the arms
below that need the flags opt in with trace_name_capable / parent_txn_capable.
"""
import json
import os
import shlex
import shutil
import sys
import tempfile
import unittest
from decimal import Decimal

from tests._compat_helpers import (
    argv_to_flags,
    assert_argv_is_golden_argv_order,
    assert_argv_matches_golden,
    build_session_model_usage,
    build_shim,
    build_state_db,
    load_golden,
    run_script,
    SCRIPTS_DIR,
    seed_parent_session_ids,
)

sys.path.insert(0, str(SCRIPTS_DIR))
import split_strategies  # noqa: E402  (path inserted just above)


# The ent trace that motivated this work.
ENT_SID = '20261012_203603_5008d5'
ENT_G_MUID = '001a132b0631cc94b8a1f5d2e3c40aa1'
ENT_C_MUID = '001a132b0631cde2b8a1f5d2e3c40aa2'
ENT_JOB_NAME = "Draft Claude Code notification guidance in John's voice"

# Both ends of the fixture's session are far in the past so the settle filter
# passes without a .ready sentinel.
OLD_START = 1715514000.0
OLD_END = 1715514066.0   # 66s: the "1.11 min" the UI showed on each duplicate row


def _session(sid, input_tokens, output_tokens, cost='0', **overrides):
    base = {
        'id': sid,
        'model': 'claude-sonnet-4-6',
        'source': 'test',
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'cache_read': 0,
        'cache_write': 0,
        'reasoning': 0,
        'estimated_cost': cost,
        'api_calls': 1,
        'started_at': OLD_START,
        'ended_at': OLD_END,
        'billing_provider': 'anthropic',
    }
    base.update(overrides)
    return base


def _child(sid, input_tokens, output_tokens, cost='0', **overrides):
    """A subagent session: it starts AFTER its root, so the reporter's
    ORDER BY started_at DESC visits it BEFORE the root -- the ordering the
    parent-link and the RC-2 hold both have to cope with."""
    overrides.setdefault('started_at', OLD_START + 10)
    overrides.setdefault('ended_at', OLD_END + 10)
    return _session(sid, input_tokens, output_tokens, cost, **overrides)


def _task(sid, muid, op, task_type, ts, **extra):
    rec = {'muid': muid, 'ts': ts, 'sid': sid, 'task_type': task_type,
           'operation_type': op, 'trace_id': extra.pop('trace_id', sid)}
    rec.update(extra)
    return rec


def _pair(sid, g_muid, c_muid, task_type, ts):
    """A classification exactly as classifier._write_marker_pair writes it."""
    return [
        _task(sid, g_muid, 'GUARDRAIL', task_type, ts),
        _task(sid, c_muid, 'CHAT', task_type, ts + 0.000027),
    ]


def _job(sid, job_id, name, job_type='drafting', status='SUCCESS', ts=1715515100.0):
    return {'kind': 'job', 'ts': ts, 'sid': sid, 'agentic_job_id': job_id,
            'job_name': name, 'job_type': job_type, 'status': status}


class _Harness(unittest.TestCase):
    """One scratch HERMES_HOME, many ticks."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='gsd-trace-dedup-')
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.hermes_home = os.path.join(self.tmpdir, 'hh')
        self.state_dir = os.path.join(self.hermes_home, 'state', 'revenium')
        self.markers_dir = os.path.join(self.state_dir, 'markers')
        os.makedirs(self.markers_dir, mode=0o700)
        self.state_db = os.path.join(self.hermes_home, 'state.db')
        self.shim_home = os.path.join(self.tmpdir, 'home')
        self.bin_dir = os.path.join(self.shim_home, '.local', 'bin')
        os.makedirs(self.bin_dir)
        self.tick_index = 0

    # ------------------------------------------------------------------ setup
    def make_db(self, sessions, aux_rows=None, parents=None):
        build_state_db(self.state_db, sessions)
        # Every production host carries parent_session_id (Phase 68 research
        # F4); a root's job attribution needs positive root evidence.
        mapping = {s['id']: None for s in sessions}
        mapping.update(parents or {})
        seed_parent_session_ids(self.state_db, mapping)
        if aux_rows is not None:
            build_session_model_usage(self.state_db, aux_rows)

    def make_shim(self, **kwargs):
        build_shim(os.path.join(self.bin_dir, 'revenium'), **kwargs)

    def write_markers(self, sid, records):
        with open(os.path.join(self.markers_dir, f'{sid}.jsonl'), 'w') as f:
            for rec in records:
                f.write(json.dumps(rec, separators=(',', ':')) + '\n')

    def seed_ledger(self, *lines):
        with open(self.ledger_path, 'a') as f:
            for line in lines:
                f.write(line + '\n')

    @property
    def ledger_path(self):
        return os.path.join(self.state_dir, 'revenium-hermes.ledger')

    def ledger_lines(self, sid=None):
        if not os.path.exists(self.ledger_path):
            return []
        with open(self.ledger_path) as f:
            lines = [ln.rstrip('\n') for ln in f if ln.strip()]
        if sid is None:
            return lines
        return [ln for ln in lines if ln.startswith(f'HERMES:{sid}:')]

    # ------------------------------------------------------------------- tick
    def tick(self, extra_env=None):
        self.tick_index += 1
        meter_log = os.path.join(self.tmpdir, f'meter-{self.tick_index}.log')
        jobs_log = os.path.join(self.tmpdir, f'jobs-{self.tick_index}.log')
        inv_log = os.path.join(self.tmpdir, f'inv-{self.tick_index}.log')
        env = {
            **os.environ,
            'HOME': self.shim_home,
            'HERMES_HOME': self.hermes_home,
            'REVENIUM_STATE_DIR': self.state_dir,
            'PATH': self.bin_dir + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': inv_log,
            'METER_LOG': meter_log,
            'JOBS_LOG': jobs_log,
            'TZ': 'UTC',
            'REVENIUM_ORGANIZATION_NAME': '',
        }
        if extra_env:
            env.update(extra_env)
        rc, _inv, output = run_script(SCRIPTS_DIR / 'hermes-report.sh', env, inv_log)
        meter = []
        if os.path.exists(meter_log):
            with open(meter_log) as f:
                meter = [shlex.split(ln) for ln in f.read().splitlines() if ln.strip()]
        self.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {output}')
        return {'argv': meter, 'flags': [argv_to_flags(a) for a in meter], 'output': output}

    @staticmethod
    def main_rows(flags_list):
        return [f for f in flags_list if not f.get('--transaction-id', '').startswith('aux-')]

    @staticmethod
    def aux_rows(flags_list):
        return [f for f in flags_list if f.get('--transaction-id', '').startswith('aux-')]


# =============================================================================
# FIX 2 -- one completion per classification
# =============================================================================
class PairCollapseEndToEndTests(_Harness):

    def _ent_fixture(self, **shim):
        self.make_db([_session(ENT_SID, 49000, 796, cost='0.140000')])
        self.write_markers(ENT_SID, _pair(ENT_SID, ENT_G_MUID, ENT_C_MUID,
                                          'draft_notification_guidance', 1715515000.0))
        self.make_shim(**shim)

    def test_one_classification_ships_one_completion_with_the_whole_delta(self):
        self._ent_fixture()
        run = self.tick()
        self.assertEqual(
            len(run['flags']), 1,
            f'a GUARDRAIL+CHAT pair is ONE classification and must ship ONE '
            f'completion, got {len(run["flags"])}: {run["argv"]}',
        )
        row = run['flags'][0]
        # The row carries the WHOLE session delta, not half of it.
        self.assertEqual(row['--input-tokens'], '49000')
        self.assertEqual(row['--output-tokens'], '796')
        self.assertEqual(row['--total-tokens'], '49796')
        self.assertEqual(Decimal(row['--total-cost']), Decimal('0.140000'))
        # CHAT, and the transaction id is the CHAT marker's, as it always was.
        self.assertEqual(row['--operation-type'], 'CHAT')
        self.assertEqual(row['--transaction-id'], f'{ENT_SID}-49796-{ENT_C_MUID}')
        self.assertEqual(row['--task-type'], 'draft_notification_guidance')

    def test_both_muids_are_ledgered_absorbed_first_and_shipped_last(self):
        self._ent_fixture()
        self.tick()
        lines = self.ledger_lines(ENT_SID)
        muids = [ln.split(':')[-1] for ln in lines]
        self.assertEqual(
            muids, [ENT_G_MUID, ENT_C_MUID],
            'the absorbed GUARDRAIL muid must be ledgered with the call that '
            'consumed it, BEFORE the shipped muid, so the newest line for a '
            f'session names a transaction that really went out. Got: {lines}',
        )

    def test_second_tick_ships_nothing_and_never_reships_the_absorbed_muid(self):
        self._ent_fixture()
        self.tick()
        before = self.ledger_lines()
        again = self.tick()
        self.assertEqual(again['argv'], [], f'a re-run must not re-report: {again["argv"]}')
        self.assertEqual(self.ledger_lines(), before, 'ledger must not grow')

    def test_growth_after_collapse_never_resurrects_a_guardrail_row(self):
        """The absorbed GUARDRAIL muid is consumed. When the session later
        grows with no new markers, the delta ships on the markerless path --
        not as a lone GUARDRAIL row (which is what an un-ledgered absorbed muid
        would produce)."""
        self._ent_fixture()
        self.tick()
        conn_sql = ("UPDATE sessions SET input_tokens = 61000, output_tokens = 1000 "
                    "WHERE id = ?")
        import sqlite3
        conn = sqlite3.connect(self.state_db)
        conn.execute(conn_sql, (ENT_SID,))
        conn.commit()
        conn.close()
        grown = self.tick()
        self.assertEqual(len(grown['flags']), 1, grown['argv'])
        self.assertEqual(grown['flags'][0]['--task-type'], 'unclassified')
        self.assertEqual(grown['flags'][0]['--operation-type'], 'CHAT')
        self.assertNotIn('GUARDRAIL', ' '.join(grown['argv'][0]))

    def test_delta_is_conserved_across_several_classifications(self):
        """Two classifications = two completions (each pair collapsed). Per-field
        sums equal the session delta exactly -- integers byte-exact, cost
        Decimal-exact -- including the odd remainder the last row absorbs."""
        self.make_db([_session('multi-sid', 40001, 6001, cost='0.100001')])
        self.write_markers('multi-sid',
                           _pair('multi-sid', 'g1', 'c1', 'planning', 1715515000.0)
                           + _pair('multi-sid', 'g2', 'c2', 'code_review', 1715515010.0))
        self.make_shim()
        run = self.tick()
        self.assertEqual(len(run['flags']), 2, run['argv'])
        self.assertEqual(sum(int(f['--input-tokens']) for f in run['flags']), 40001)
        self.assertEqual(sum(int(f['--output-tokens']) for f in run['flags']), 6001)
        self.assertEqual(sum(int(f['--total-tokens']) for f in run['flags']), 46002)
        self.assertEqual(sum(Decimal(f['--total-cost']) for f in run['flags']),
                         Decimal('0.100001'))
        self.assertEqual({f['--operation-type'] for f in run['flags']}, {'CHAT'})
        self.assertEqual([f['--task-type'] for f in run['flags']], ['planning', 'code_review'])
        # All four muids consumed.
        self.assertEqual(len(self.ledger_lines('multi-sid')), 4)

    def test_pair_failure_ledgers_nothing_and_retries_with_the_same_transaction_id(self):
        """The CLI call comes BEFORE any ledger line. A failed call must leave
        both markers unreported; the retry ships the same deterministic id."""
        self._ent_fixture()
        shim = os.path.join(self.bin_dir, 'revenium')
        failing = os.path.join(self.tmpdir, 'failing-shim')
        build_shim(failing)
        with open(failing) as f:
            body = f.read()
        # Fail only the completion call itself; --help probes keep answering.
        body = body.replace(
            '      completion)\n',
            '      completion)\n        [[ -n "${REVENIUM_FAIL:-}" ]] && exit 7\n', 1)
        with open(shim, 'w') as f:
            f.write(body)
        os.chmod(shim, 0o755)

        first = self.tick({'REVENIUM_FAIL': '1'})
        self.assertEqual(self.ledger_lines(ENT_SID), [], 'a failed call must ledger nothing')
        retry = self.tick()
        self.assertEqual(len(retry['flags']), 1, retry['argv'])
        self.assertEqual(retry['flags'][0]['--transaction-id'],
                         f'{ENT_SID}-49796-{ENT_C_MUID}')
        self.assertEqual(len(self.ledger_lines(ENT_SID)), 2)
        self.assertIsNotNone(first)


class PairCollapseMigrationTests(_Harness):
    """Sessions already partially reported under the old pair scheme: both
    halves used to ship as separate rows, each ledgered on its own success.
    Whatever half is left must ship exactly once and nothing may re-ship."""

    SID = 'migrating-sid'

    def _setup(self):
        # Session total is 150 now; an earlier tick reported up to 100.
        self.make_db([_session(self.SID, 100, 50, cost='0.030000')])
        self.write_markers(self.SID, _pair(self.SID, 'g-old', 'c-old', 'research', 1715515000.0))
        self.make_shim()

    def test_guardrail_already_ledgered_chat_ships_alone(self):
        """Old tick: the GUARDRAIL call succeeded, the CHAT call failed."""
        self._setup()
        self.seed_ledger(f'HERMES:{self.SID}:100:1715514500.000:g-old')
        run = self.tick()
        self.assertEqual(len(run['flags']), 1, run['argv'])
        self.assertEqual(run['flags'][0]['--operation-type'], 'CHAT')
        self.assertEqual(run['flags'][0]['--transaction-id'], f'{self.SID}-150-c-old')
        muids = [ln.split(':')[-1] for ln in self.ledger_lines(self.SID)]
        self.assertEqual(muids, ['g-old', 'c-old'], 'g-old must not be re-ledgered')

    def test_chat_already_ledgered_guardrail_ships_alone_as_chat(self):
        """Old tick: the CHAT call succeeded, the GUARDRAIL call failed. The
        orphan's twin went out as CHAT, so the orphan must not be the one
        GUARDRAIL row of its classification."""
        self._setup()
        self.seed_ledger(f'HERMES:{self.SID}:100:1715514500.000:c-old')
        run = self.tick()
        self.assertEqual(len(run['flags']), 1, run['argv'])
        self.assertEqual(run['flags'][0]['--operation-type'], 'CHAT')
        self.assertEqual(run['flags'][0]['--transaction-id'], f'{self.SID}-150-g-old')
        muids = [ln.split(':')[-1] for ln in self.ledger_lines(self.SID)]
        self.assertEqual(muids, ['c-old', 'g-old'])

    def test_both_halves_already_ledgered_ships_nothing_for_them(self):
        self._setup()
        self.seed_ledger(f'HERMES:{self.SID}:150:1715514500.000:g-old',
                         f'HERMES:{self.SID}:150:1715514500.001:c-old')
        run = self.tick()
        self.assertEqual(run['argv'], [])

    def test_delta_already_reported_under_the_old_scheme_is_not_double_counted(self):
        """100 of 150 tokens were reported (both halves) before the upgrade;
        the new classification's pair ships only the 50-token remainder."""
        self._setup()
        self.seed_ledger(f'HERMES:{self.SID}:100:1715514500.000:g-old',
                         f'HERMES:{self.SID}:100:1715514500.001:c-old')
        self.write_markers(self.SID,
                           _pair(self.SID, 'g-old', 'c-old', 'research', 1715515000.0)
                           + _pair(self.SID, 'g-new', 'c-new', 'research', 1715515500.0))
        run = self.tick()
        self.assertEqual(len(run['flags']), 1, run['argv'])
        row = run['flags'][0]
        self.assertEqual(row['--transaction-id'], f'{self.SID}-150-c-new')
        # 100 of 150 already shipped: the delta is the remaining third.
        self.assertEqual(int(row['--input-tokens']) + int(row['--output-tokens']),
                         int(row['--total-tokens']))
        self.assertLess(int(row['--total-tokens']), 150)


class PairIsOnlyCollapsedWhenProvablyOneClassificationTests(_Harness):
    SID = 'edge-sid'

    def setUp(self):
        super().setUp()
        self.make_db([_session(self.SID, 100, 50, cost='0.030000')])
        self.make_shim()

    def test_a_lone_guardrail_marker_still_ships_as_guardrail(self):
        """No CHAT twin: nothing proves it is bookkeeping for a CHAT row, so it
        passes through verbatim (the S2 documented bias case)."""
        self.write_markers(self.SID, [
            _task(self.SID, 'm-chat', 'CHAT', 'code_review', 1715515001.0),
            _task(self.SID, 'm-guard', 'GUARDRAIL', 'planning', 1715515002.0),
        ])
        run = self.tick()
        self.assertEqual(sorted(f['--operation-type'] for f in run['flags']),
                         ['CHAT', 'GUARDRAIL'])

    def test_adjacent_halves_of_different_classifications_are_not_collapsed(self):
        self.write_markers(self.SID, [
            _task(self.SID, 'm-g', 'GUARDRAIL', 'planning', 1715515001.0),
            _task(self.SID, 'm-c', 'CHAT', 'code_review', 1715515002.0),
        ])
        run = self.tick()
        self.assertEqual(len(run['flags']), 2, run['argv'])

    def test_a_chat_marker_before_a_guardrail_marker_is_not_a_pair(self):
        self.write_markers(self.SID, [
            _task(self.SID, 'm-c', 'CHAT', 'planning', 1715515001.0),
            _task(self.SID, 'm-g', 'GUARDRAIL', 'planning', 1715515002.0),
        ])
        run = self.tick()
        self.assertEqual(len(run['flags']), 2, run['argv'])

    def test_a_guardrail_muid_that_is_not_ledger_safe_is_never_absorbed(self):
        """An absorbed muid is written to the ledger on the survivor's behalf,
        so it must be provably free of ':' and whitespace first."""
        self.write_markers(self.SID, [
            _task(self.SID, 'bad muid', 'GUARDRAIL', 'planning', 1715515001.0),
            _task(self.SID, 'm-c', 'CHAT', 'planning', 1715515002.0),
        ])
        run = self.tick()
        self.assertEqual(len(run['flags']), 2, run['argv'])

    def test_markerless_session_is_unchanged(self):
        run = self.tick()
        self.assertEqual(len(run['flags']), 1)
        self.assertEqual(run['flags'][0]['--task-type'], 'unclassified')
        self.assertEqual(run['flags'][0]['--transaction-id'], f'{self.SID}-150')
        self.assertEqual(run['flags'][0]['--operation-type'], 'CHAT')


class CollapseClassificationPairsUnitTests(unittest.TestCase):
    """The pure function, so the rule is pinned independent of bash."""

    @staticmethod
    def _m(muid, op, task='t', **extra):
        rec = {'muid': muid, 'ts': 1.0, 'sid': 's', 'task_type': task,
               'operation_type': op, 'trace_id': 's'}
        rec.update(extra)
        return rec

    def test_pair_collapses_to_the_chat_marker_carrying_the_guardrail_muid(self):
        g, c = self._m('g', 'GUARDRAIL'), self._m('c', 'CHAT')
        out = split_strategies.collapse_classification_pairs([(g, True), (c, True)])
        self.assertEqual(out, [c])
        self.assertEqual(c['absorbed_muids'], ['g'])
        self.assertEqual(c['operation_type'], 'CHAT')

    def test_markers_around_a_pair_keep_their_order(self):
        a = self._m('a', 'CHAT', 'x')
        g, c = self._m('g', 'GUARDRAIL'), self._m('c', 'CHAT')
        z = self._m('z', 'CHAT', 'y')
        out = split_strategies.collapse_classification_pairs(
            [(a, True), (g, True), (c, True), (z, True)])
        self.assertEqual([m['muid'] for m in out], ['a', 'c', 'z'])

    def test_ineligible_twin_relabels_the_orphan_chat(self):
        g, c = self._m('g', 'GUARDRAIL'), self._m('c', 'CHAT')
        out = split_strategies.collapse_classification_pairs([(g, True), (c, False)])
        self.assertEqual([m['muid'] for m in out], ['g'])
        self.assertEqual(out[0]['operation_type'], 'CHAT')
        self.assertNotIn('absorbed_muids', out[0])

    def test_ineligible_guardrail_leaves_the_chat_alone(self):
        g, c = self._m('g', 'GUARDRAIL'), self._m('c', 'CHAT')
        out = split_strategies.collapse_classification_pairs([(g, False), (c, True)])
        self.assertEqual([m['muid'] for m in out], ['c'])
        self.assertNotIn('absorbed_muids', out[0])

    def test_a_guardrail_with_no_twin_is_untouched(self):
        g = self._m('g', 'GUARDRAIL')
        out = split_strategies.collapse_classification_pairs([(g, True)])
        self.assertEqual(out[0]['operation_type'], 'GUARDRAIL')

    def test_every_pair_field_must_agree(self):
        for field, other in (('task_type', 'zzz'), ('trace_id', 'other'),
                             ('agentic_job_id', 'job-x'), ('agent', 'Other'),
                             ('sid', 'other-sid')):
            g = self._m('g', 'GUARDRAIL')
            c = self._m('c', 'CHAT')
            c[field] = other
            out = split_strategies.collapse_classification_pairs([(g, True), (c, True)])
            self.assertEqual(len(out), 2, f'{field} differs: must not collapse')

    def test_a_forged_absorbed_muids_key_from_a_marker_file_is_discarded(self):
        c = self._m('c', 'CHAT', absorbed_muids=['evil'])
        out = split_strategies.collapse_classification_pairs([(c, True)])
        self.assertNotIn('absorbed_muids', out[0])

    def test_run_of_guardrails_pairs_only_the_last_with_its_chat(self):
        g1, g2, c = self._m('g1', 'GUARDRAIL'), self._m('g2', 'GUARDRAIL'), self._m('c', 'CHAT')
        out = split_strategies.collapse_classification_pairs([(g1, True), (g2, True), (c, True)])
        self.assertEqual([m['muid'] for m in out], ['g1', 'c'])
        self.assertEqual(out[1]['absorbed_muids'], ['g2'])


# =============================================================================
# FIX 1 -- --trace-name
# =============================================================================
class TraceNameTests(_Harness):

    def _ent(self, markers, trace_type_capable, **shim):
        self.make_db([_session(ENT_SID, 49000, 796, cost='0.140000')])
        self.write_markers(ENT_SID, markers)
        self.make_shim(trace_name_capable=True, trace_type_capable=trace_type_capable, **shim)

    def _both_resolutions(self):
        """The name is resolved inside the --trace-type heredoc when the CLI has
        both flags, and by a standalone call when it has only --trace-name. The
        two must agree on every shape below."""
        return (True, False)

    def test_a_job_name_names_the_trace(self):
        for trace_type_capable in self._both_resolutions():
            with self.subTest(trace_type_capable=trace_type_capable):
                self.setUp()
                self._ent(_pair(ENT_SID, ENT_G_MUID, ENT_C_MUID, 'draft_notification_guidance',
                                1715515000.0) + [_job(ENT_SID, 'job-ent-1', ENT_JOB_NAME)],
                          trace_type_capable)
                run = self.tick()
                self.assertEqual(len(run['flags']), 1, run['argv'])
                self.assertEqual(run['flags'][0].get('--trace-name'), ENT_JOB_NAME)

    def test_without_a_job_the_first_task_type_names_the_trace(self):
        for trace_type_capable in self._both_resolutions():
            with self.subTest(trace_type_capable=trace_type_capable):
                self.setUp()
                self._ent(_pair(ENT_SID, 'g1', 'c1', 'planning', 1715515000.0)
                          + _pair(ENT_SID, 'g2', 'c2', 'code_review', 1715515100.0),
                          trace_type_capable)
                run = self.tick()
                self.assertEqual(len(run['flags']), 2, run['argv'])
                # BOTH rows carry the SAME name: a trace has one.
                self.assertEqual([f.get('--trace-name') for f in run['flags']],
                                 ['planning', 'planning'])

    def test_the_latest_job_name_wins_like_the_trace_type_does(self):
        for trace_type_capable in self._both_resolutions():
            with self.subTest(trace_type_capable=trace_type_capable):
                self.setUp()
                self._ent(_pair(ENT_SID, 'g1', 'c1', 'planning', 1715515000.0) + [
                    _job(ENT_SID, 'job-a', 'First job', ts=1715515100.0),
                    _job(ENT_SID, 'job-b', 'Second job', ts=1715515200.0)],
                    trace_type_capable)
                run = self.tick()
                self.assertEqual(run['flags'][0].get('--trace-name'), 'Second job')

    def test_a_guardrail_halt_job_never_renames_a_trace(self):
        halt = _job(ENT_SID, 'guardrail-halt-ab12', 'Arc interrupted by guardrail halt',
                    job_type='interrupted', status='CANCELLED', ts=1715515300.0)
        for trace_type_capable in self._both_resolutions():
            with self.subTest(trace_type_capable=trace_type_capable):
                self.setUp()
                self._ent(_pair(ENT_SID, 'g1', 'c1', 'planning', 1715515000.0) + [
                    _job(ENT_SID, 'job-a', 'Real work', ts=1715515100.0), halt],
                    trace_type_capable)
                self.assertEqual(self.tick()['flags'][0].get('--trace-name'), 'Real work')

    def test_a_halt_job_alone_falls_back_to_the_task_type(self):
        halt = _job(ENT_SID, 'guardrail-halt-ab12', 'Arc interrupted by guardrail halt',
                    job_type='interrupted', status='CANCELLED')
        self._ent(_pair(ENT_SID, 'g1', 'c1', 'planning', 1715515000.0) + [halt], True)
        self.assertEqual(self.tick()['flags'][0].get('--trace-name'), 'planning')

    def test_flag_sits_right_after_trace_type(self):
        self._ent(_pair(ENT_SID, ENT_G_MUID, ENT_C_MUID, 'planning', 1715515000.0)
                  + [_job(ENT_SID, 'job-a', 'Named job')], True)
        argv = self.tick()['argv'][0]
        i = argv.index('--trace-type')
        self.assertEqual(argv[i + 2], '--trace-name', argv)
        self.assertEqual(argv[i + 3], 'Named job', argv)

    def test_markerless_row_of_a_named_trace_carries_the_name(self):
        """Once a session's markers are all consumed, later growth ships on the
        markerless path (task type `unclassified`). It is still a row of a trace
        the root's marker file names, so it must carry that name -- or one trace
        would show the name on some rows and "Unnamed trace" on others."""
        import sqlite3
        self._ent(_pair(ENT_SID, ENT_G_MUID, ENT_C_MUID, 'planning', 1715515000.0)
                  + [_job(ENT_SID, 'job-ent-1', ENT_JOB_NAME)], True)
        first = self.tick()
        self.assertEqual(first['flags'][0].get('--trace-name'), ENT_JOB_NAME)
        conn = sqlite3.connect(self.state_db)
        conn.execute("UPDATE sessions SET input_tokens = 61000, output_tokens = 1000 WHERE id = ?",
                     (ENT_SID,))
        conn.commit()
        conn.close()
        grown = self.tick()
        self.assertEqual(len(grown['flags']), 1, grown['argv'])
        self.assertEqual(grown['flags'][0]['--task-type'], 'unclassified')
        self.assertEqual(grown['flags'][0].get('--trace-name'), ENT_JOB_NAME)

    def test_markerless_install_sends_no_trace_name(self):
        """No marker file anywhere in the trace: nothing to name it by, so the
        argv is byte-identical to a CLI without the flag."""
        self.make_db([_session('plain-sid', 100, 50)])
        self.make_shim(trace_name_capable=True, trace_type_capable=True)
        run = self.tick()
        self.assertEqual(len(run['flags']), 1)
        self.assertNotIn('--trace-name', run['flags'][0])

    def test_older_cli_sends_no_trace_name_and_keeps_the_golden_argv(self):
        """The default shim does not advertise --trace-name: the probe is a
        determinate negative, the flag is never sent and the argv is exactly
        what the v1.x golden pins (the fail-open proof)."""
        self.make_db([_session('compat-sid-001', 100, 50, ended_at=OLD_START)])
        self.write_markers('compat-sid-001', [
            {'muid': 'compat-muid-001', 'ts': 1715515000.5, 'sid': 'compat-sid-001',
             'task_type': 'code_review', 'operation_type': 'CHAT'},
            {'kind': 'job', 'ts': 1715515001.0, 'sid': 'compat-sid-001',
             'agentic_job_id': 'compat-job-001', 'job_name': 'COMPAT Test Job',
             'job_type': 'code_review', 'status': 'IN_PROGRESS'},
        ])
        self.make_shim()
        argv = self.tick()['argv'][0]
        self.assertNotIn('--trace-name', argv)
        golden = load_golden('meter-completion.golden.json')
        assert_argv_matches_golden(self, argv, golden)
        assert_argv_is_golden_argv_order(self, argv, golden)

    def test_a_pure_nameless_trace_with_only_an_unusable_label_sends_nothing(self):
        self.make_db([_session('triv-sid', 100, 50)])
        self.write_markers('triv-sid', [_task('triv-sid', 'm1', 'CHAT', 'thanks', 1715515000.0)])
        self.make_shim(trace_name_capable=True, trace_type_capable=True)
        run = self.tick()
        # 'thanks' is on the cron-side forbidden list: no marker ships, and it
        # must not name the trace either.
        for f in run['flags']:
            self.assertNotIn('--trace-name', f)

    def test_subagent_completion_carries_the_roots_trace_name(self):
        root, child = 'root-sid', 'child-sid'
        self.make_db([_session(root, 100, 50), _child(child, 60, 40)],
                     parents={child: root})
        self.write_markers(root, _pair(root, 'rg', 'rc', 'planning', 1715515000.0)
                           + [_job(root, 'job-root', 'Root job name')])
        self.write_markers(child, [
            _task(child, 'cc', 'CHAT', 'research', 1715515010.0, trace_id=root)])
        self.make_shim(trace_name_capable=True, trace_type_capable=True)
        # The root carries a job, so the existing RC-2 gate holds the child until
        # the root's `jobs create` is ledgered: the child ships on the next tick.
        first = self.tick()
        second = self.tick()
        by_task = {f['--task-type']: f for f in first['flags'] + second['flags']}
        self.assertEqual(by_task['research'].get('--trace-name'), 'Root job name')
        self.assertEqual(by_task['planning'].get('--trace-name'), 'Root job name')
        self.assertEqual(by_task['research']['--trace-id'], root)


class ResolveTraceNameUnitTests(unittest.TestCase):

    def _resolve(self, records_or_text):
        with tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False) as f:
            if isinstance(records_or_text, str):
                f.write(records_or_text)
            else:
                for rec in records_or_text:
                    f.write(json.dumps(rec) + '\n')
            path = f.name
        self.addCleanup(os.unlink, path)
        return split_strategies.resolve_trace_name(path)

    def test_missing_file_is_no_name(self):
        self.assertEqual(split_strategies.resolve_trace_name('/nonexistent/x.jsonl'), '')

    def test_corrupt_lines_are_skipped_not_fatal(self):
        text = 'not json\n[1,2]\n' + json.dumps(_job('s', 'j', 'Good name')) + '\n{"torn":'
        self.assertEqual(self._resolve(text), 'Good name')

    def test_newlines_tabs_and_runs_of_space_collapse_to_one_line(self):
        name = self._resolve([_job('s', 'j', '  Fix\nthe\tbuild   now\r\n ')])
        self.assertEqual(name, 'Fix the build now')

    def test_the_name_is_bounded(self):
        name = self._resolve([_job('s', 'j', 'x' * 500)])
        self.assertEqual(len(name), split_strategies.TRACE_NAME_MAX_CHARS)

    def test_clamp_counts_characters_not_bytes(self):
        name = self._resolve([_job('s', 'j', 'é' * 300)])
        self.assertEqual(name, 'é' * split_strategies.TRACE_NAME_MAX_CHARS)

    def test_a_job_without_a_name_does_not_erase_an_earlier_one(self):
        name = self._resolve([_job('s', 'a', 'Named'), _job('s', 'b', '')])
        self.assertEqual(name, 'Named')

    def test_non_string_job_name_is_ignored(self):
        rec = _job('s', 'j', 'x')
        rec['job_name'] = ['not', 'a', 'string']
        self.assertEqual(self._resolve([rec, _task('s', 'm', 'CHAT', 'planning', 1.0)]), 'planning')


# =============================================================================
# FIX 3 -- --parent-transaction-id
# =============================================================================
class LatestTransactionIdUnitTests(unittest.TestCase):

    def _ledger(self, *lines):
        f = tempfile.NamedTemporaryFile('w', suffix='.ledger', delete=False)
        f.write('\n'.join(lines) + '\n')
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_per_marker_line_names_sid_total_muid(self):
        p = self._ledger('HERMES:s1:150:1715514500.000:abc123')
        self.assertEqual(split_strategies.latest_transaction_id(p, 's1'), 's1-150-abc123')

    def test_markerless_synthetic_muid_names_sid_total_only(self):
        p = self._ledger('HERMES:s1:150:1715514500.000:unclassified-1715514500000')
        self.assertEqual(split_strategies.latest_transaction_id(p, 's1'), 's1-150')

    def test_v1_four_field_row_names_sid_total_only(self):
        p = self._ledger('HERMES:s1:150:1715514500.000')
        self.assertEqual(split_strategies.latest_transaction_id(p, 's1'), 's1-150')

    def test_the_last_line_wins(self):
        p = self._ledger('HERMES:s1:100:1.0:old', 'HERMES:s2:999:2.0:other',
                         'HERMES:s1:150:3.0:newer')
        self.assertEqual(split_strategies.latest_transaction_id(p, 's1'), 's1-150-newer')

    def test_a_collapsed_pair_names_the_shipped_muid_not_the_absorbed_one(self):
        p = self._ledger('HERMES:s1:150:1.0:absorbed-g', 'HERMES:s1:150:1.0:shipped-c')
        self.assertEqual(split_strategies.latest_transaction_id(p, 's1'), 's1-150-shipped-c')

    def test_a_sid_that_prefixes_another_cannot_borrow_its_lines(self):
        p = self._ledger('HERMES:agent:p:x:150:1.0:m1')
        self.assertEqual(split_strategies.latest_transaction_id(p, 'agent'), '')
        self.assertEqual(split_strategies.latest_transaction_id(p, 'agent:p'), '')
        self.assertEqual(split_strategies.latest_transaction_id(p, 'agent:p:x'),
                         'agent:p:x-150-m1')

    def test_unknown_session_missing_ledger_and_garbage_are_empty(self):
        p = self._ledger('HERMES:s1:notanumber:1.0:m', 'HERMES:s1:5:nope:m', 'junk')
        self.assertEqual(split_strategies.latest_transaction_id(p, 's1'), '')
        self.assertEqual(split_strategies.latest_transaction_id(p, 'zzz'), '')
        self.assertEqual(split_strategies.latest_transaction_id('/nonexistent', 's1'), '')


class ParentTransactionIdTests(_Harness):

    AUX = {
        'session_id': ENT_SID, 'model': 'claude-3-5-haiku', 'billing_provider': 'anthropic',
        'billing_base_url': '', 'billing_mode': '', 'task': 'title_generation',
        'api_call_count': 1, 'input_tokens': 40, 'output_tokens': 10,
        'cache_read_tokens': 0, 'cache_write_tokens': 0, 'estimated_cost_usd': 0.002,
        'first_seen': 1715514500.0, 'last_seen': 1715514600.0,
    }

    def _ent(self, markers=None, aux=True, **shim):
        self.make_db([_session(ENT_SID, 49000, 796, cost='0.140000')],
                     aux_rows=[dict(self.AUX)] if aux else None)
        self.write_markers(ENT_SID, markers if markers is not None else
                           _pair(ENT_SID, ENT_G_MUID, ENT_C_MUID, 'planning', 1715515000.0))
        self.make_shim(parent_txn_capable=True, **shim)

    def test_aux_row_links_to_the_main_row_it_belongs_to(self):
        """The ent trace: the title-generation AUX row must point at the one
        main completion of its session -- the id read off the REAL main row."""
        self._ent()
        run = self.tick()
        main, aux = self.main_rows(run['flags']), self.aux_rows(run['flags'])
        self.assertEqual((len(main), len(aux)), (1, 1), run['argv'])
        self.assertEqual(aux[0].get('--parent-transaction-id'), main[0]['--transaction-id'])
        # The main row itself has no parent: it is the root of its subtree.
        self.assertNotIn('--parent-transaction-id', main[0])

    def test_aux_row_links_to_the_newest_main_row_of_its_session(self):
        self._ent(markers=_pair(ENT_SID, 'g1', 'c1', 'planning', 1715515000.0)
                  + _pair(ENT_SID, 'g2', 'c2', 'code_review', 1715515100.0))
        run = self.tick()
        main, aux = self.main_rows(run['flags']), self.aux_rows(run['flags'])
        self.assertEqual(len(main), 2)
        self.assertEqual(aux[0].get('--parent-transaction-id'), main[-1]['--transaction-id'])

    def test_aux_row_links_to_a_markerless_main_row(self):
        self.make_db([_session(ENT_SID, 49000, 796)], aux_rows=[dict(self.AUX)])
        self.make_shim(parent_txn_capable=True)
        run = self.tick()
        main, aux = self.main_rows(run['flags']), self.aux_rows(run['flags'])
        self.assertEqual(main[0]['--transaction-id'], f'{ENT_SID}-49796')
        self.assertEqual(aux[0].get('--parent-transaction-id'), f'{ENT_SID}-49796')

    def test_aux_idempotency_key_and_transaction_id_are_unchanged_by_the_link(self):
        """The parent link must never enter --transaction-id or the aux ledger
        key, or a re-run (or an upgrade) would re-ship every aux row."""
        self._ent()
        linked = self.aux_rows(self.tick()['flags'])[0]
        self.setUp()
        self._ent(aux=True)
        self.make_shim()  # older CLI: no parent flag at all
        plain = self.aux_rows(self.tick()['flags'])[0]
        self.assertEqual(linked['--transaction-id'], plain['--transaction-id'])
        self.assertNotIn('--parent-transaction-id', plain)

    def test_second_tick_reships_nothing(self):
        self._ent()
        self.tick()
        self.assertEqual(self.tick()['argv'], [])

    def test_aux_only_session_falls_back_to_its_roots_latest_transaction(self):
        root, child = 'root-sid', 'auxonly-child'
        self.make_db([_session(root, 100, 50), _child(child, 0, 0)],
                     aux_rows=[dict(self.AUX, session_id=child)], parents={child: root})
        self.write_markers(root, _pair(root, 'rg', 'rc', 'planning', 1715515000.0))
        self.make_shim(parent_txn_capable=True)
        run = self.tick()
        aux = self.aux_rows(run['flags'])
        self.assertEqual(len(aux), 1, run['argv'])
        self.assertEqual(aux[0].get('--parent-transaction-id'), f'{root}-150-rc')

    def test_older_cli_sends_no_parent_flag(self):
        self.make_db([_session(ENT_SID, 49000, 796)], aux_rows=[dict(self.AUX)])
        self.write_markers(ENT_SID, _pair(ENT_SID, 'g', 'c', 'planning', 1715515000.0))
        self.make_shim()
        for f in self.tick()['flags']:
            self.assertNotIn('--parent-transaction-id', f)


class SubagentParentTests(_Harness):
    ROOT, CHILD = 'root-sid', 'child-sid'

    def _setup(self, root_total=(100, 50)):
        self.make_db([_session(self.ROOT, *root_total), _child(self.CHILD, 60, 40)],
                     parents={self.CHILD: self.ROOT})
        self.write_markers(self.CHILD, [
            _task(self.CHILD, 'cc', 'CHAT', 'research', 1715515010.0, trace_id=self.ROOT)])
        self.make_shim(parent_txn_capable=True)

    def test_child_links_to_the_roots_most_recent_shipped_transaction(self):
        self._setup()
        # The root shipped on an earlier tick.
        self.seed_ledger(f'HERMES:{self.ROOT}:150:1715514500.000:r-old')
        run = self.tick()
        child = [f for f in run['flags'] if f['--task-type'] == 'research']
        self.assertEqual(len(child), 1, run['argv'])
        self.assertEqual(child[0].get('--parent-transaction-id'), f'{self.ROOT}-150-r-old')
        self.assertEqual(child[0]['--squad-role'] if '--squad-role' in child[0] else 'subagent',
                         'subagent')

    def test_child_ships_unlinked_not_held_when_the_root_has_not_shipped(self):
        """The root is visited AFTER the child (ORDER BY started_at DESC), so on
        the first tick the root has nothing in the ledger yet. The child's spend
        must still go out THIS tick -- a hold would delay budget visibility for a
        cosmetic edge."""
        self._setup()
        run = self.tick()
        child = [f for f in run['flags'] if f['--task-type'] == 'research']
        self.assertEqual(len(child), 1, f'the child must not be held: {run["argv"]}')
        self.assertNotIn('--parent-transaction-id', child[0])
        self.assertEqual(len(self.ledger_lines(self.CHILD)), 1)

    def test_root_completions_have_no_parent(self):
        self._setup()
        self.write_markers(self.ROOT, _pair(self.ROOT, 'rg', 'rc', 'planning', 1715515000.0))
        self.seed_ledger(f'HERMES:{self.ROOT}:90:1715514400.000:r-prev')
        run = self.tick()
        root_rows = [f for f in run['flags'] if f['--task-type'] == 'planning']
        self.assertEqual(len(root_rows), 1, run['argv'])
        self.assertNotIn('--parent-transaction-id', root_rows[0])

    def test_markerless_child_links_too(self):
        self.make_db([_session(self.ROOT, 100, 50), _child(self.CHILD, 60, 40)],
                     parents={self.CHILD: self.ROOT})
        self.make_shim(parent_txn_capable=True)
        self.seed_ledger(f'HERMES:{self.ROOT}:150:1715514500.000:unclassified-17155145000')
        run = self.tick()
        child = [f for f in run['flags'] if f['--trace-id'] == self.ROOT
                 and f['--transaction-id'] == f'{self.CHILD}-100']
        self.assertEqual(len(child), 1, run['argv'])
        self.assertEqual(child[0].get('--parent-transaction-id'), f'{self.ROOT}-150')

    def test_older_cli_sends_no_parent_flag(self):
        self._setup()
        self.make_shim()
        self.seed_ledger(f'HERMES:{self.ROOT}:150:1715514500.000:r-old')
        for f in self.tick()['flags']:
            self.assertNotIn('--parent-transaction-id', f)


# =============================================================================
# All three together: the capable-CLI wire shape, pinned as its own fixture
# =============================================================================
class CapableCliWireShapeTests(_Harness):

    def test_ent_trace_matches_the_capable_cli_golden(self):
        self.make_db([_session(ENT_SID, 49000, 796, cost='0.140000', ended_at=OLD_START)],
                     aux_rows=[dict(ParentTransactionIdTests.AUX)])
        self.write_markers(ENT_SID,
                           _pair(ENT_SID, ENT_G_MUID, ENT_C_MUID,
                                 'draft_notification_guidance', 1715515000.0)
                           + [_job(ENT_SID, 'job-ent-1', ENT_JOB_NAME)])
        self.make_shim(trace_name_capable=True, parent_txn_capable=True,
                       trace_type_capable=True)
        run = self.tick()
        main, aux = self.main_rows(run['flags']), self.aux_rows(run['flags'])
        self.assertEqual((len(main), len(aux)), (1, 1), run['argv'])

        main_argv = next(a for a in run['argv']
                         if not argv_to_flags(a)['--transaction-id'].startswith('aux-'))
        aux_argv = next(a for a in run['argv']
                        if argv_to_flags(a)['--transaction-id'].startswith('aux-'))
        main_golden = load_golden('meter-completion-trace.golden.json')
        aux_golden = load_golden('meter-completion-aux-trace.golden.json')
        assert_argv_matches_golden(self, main_argv, main_golden)
        assert_argv_is_golden_argv_order(self, main_argv, main_golden)
        assert_argv_matches_golden(self, aux_argv, aux_golden)
        assert_argv_is_golden_argv_order(self, aux_argv, aux_golden)
        # Both rows name the SAME trace, and the aux row hangs off the main one
        # -- checked against the LIVE main row, not the golden's literal.
        self.assertEqual(main[0]['--trace-name'], ENT_JOB_NAME)
        self.assertEqual(aux[0]['--trace-name'], ENT_JOB_NAME)
        self.assertEqual(aux[0]['--parent-transaction-id'], main[0]['--transaction-id'])


# =============================================================================
# The event path names its traces the same way (api-event-report.sh, live mode)
# =============================================================================
class EventPathTraceNameTests(_Harness):
    """The event path is the legacy reporter's eventual replacement, so a trace
    must not lose its name when an operator flips the mode to live. It shares
    resolve_trace_name_at (common.sh) with the legacy reporter, so the two
    cannot disagree about a session's name."""

    SID = 'event-name-sid'

    def _event_fixture(self, markers, **shim):
        spool = os.path.join(self.state_dir, 'api-events')
        ready = os.path.join(self.markers_dir, '.ready')
        os.makedirs(spool, mode=0o700)
        os.makedirs(ready, mode=0o700)
        open(os.path.join(ready, self.SID), 'w').close()
        with open(os.path.join(spool, f'{self.SID}.jsonl'), 'w') as f:
            f.write(json.dumps({
                'v': 1, 'sid': self.SID, 'api_request_id': 'arid-001',
                'ts': 1715514000.5, 'ended_at': 1715514001.0, 'duration_ms': 500,
                'platform': 'cli', 'model': 'm', 'response_model': 'claude-sonnet-4-6',
                'provider': 'anthropic', 'base_url': 'https://api.anthropic.com',
                'api_mode': 'anthropic_messages', 'finish_reason': 'stop',
                'input_tokens': 100, 'output_tokens': 50, 'cache_read_tokens': 0,
                'cache_write_tokens': 0, 'reasoning_tokens': 0, 'total_tokens': 150,
            }, separators=(',', ':')) + '\n')
        self.write_markers(self.SID, markers)
        self.make_shim(**shim)

    def _tick_event(self):
        meter_log = os.path.join(self.tmpdir, 'event-meter.log')
        inv_log = os.path.join(self.tmpdir, 'event-inv.log')
        env = {
            **os.environ, 'HOME': self.shim_home, 'HERMES_HOME': self.hermes_home,
            'REVENIUM_STATE_DIR': self.state_dir,
            'PATH': self.bin_dir + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': inv_log, 'METER_LOG': meter_log, 'TZ': 'UTC',
            'REVENIUM_EVENT_METERING_MODE': 'live',
        }
        rc, _inv, output = run_script(SCRIPTS_DIR / 'api-event-report.sh', env, inv_log)
        self.assertEqual(rc, 0, output)
        with open(meter_log) as f:
            return [shlex.split(ln) for ln in f.read().splitlines() if ln.strip()]

    def _markers(self):
        return _pair(self.SID, 'eg', 'ec', 'planning', 1715513900.0) + [
            _job(self.SID, 'job-ev', 'Event path job name', ts=1715513950.0)]

    def test_event_row_carries_the_trace_name_right_after_trace_type(self):
        self._event_fixture(self._markers(), trace_name_capable=True, trace_type_capable=True)
        rows = self._tick_event()
        self.assertEqual(len(rows), 1, rows)
        argv = rows[0]
        i = argv.index('--trace-type')
        self.assertEqual(argv[i + 2:i + 4], ['--trace-name', 'Event path job name'], argv)
        # No parent link on this path, by design.
        self.assertNotIn('--parent-transaction-id', argv)

    def test_event_row_falls_back_to_the_first_task_type(self):
        self._event_fixture(_pair(self.SID, 'eg', 'ec', 'planning', 1715513900.0),
                            trace_name_capable=True, trace_type_capable=True)
        flags = argv_to_flags(self._tick_event()[0])
        self.assertEqual(flags.get('--trace-name'), 'planning')

    def test_older_cli_event_row_has_no_trace_name(self):
        self._event_fixture(self._markers())
        self.assertNotIn('--trace-name', self._tick_event()[0])

    def test_event_and_legacy_paths_agree_on_the_name(self):
        """Same marker file, same helper, same name."""
        self._event_fixture(self._markers(), trace_name_capable=True, trace_type_capable=True)
        event_name = argv_to_flags(self._tick_event()[0]).get('--trace-name')
        path = os.path.join(self.markers_dir, f'{self.SID}.jsonl')
        self.assertEqual(event_name, split_strategies.resolve_trace_name(path))


if __name__ == '__main__':
    unittest.main()
