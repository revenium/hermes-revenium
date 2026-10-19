"""Carry a classified session's latest classification and job onto its later deltas.

The leak (measured on ent, session 20261018_134109_5d0360): the classifier
latches after a session's first marker pair, so once those muids are ledgered
every later delta takes hermes-report.sh's zero-marker branch and shipped
`--task-type unclassified` with no `--agentic-job-id`. Job cost was understated,
ROI inflated and task analytics lost the label. One marked row at 480,675
tokens, then five unclassified rows to 515,535.

Locked decision LD-1: a delta of a session that HAS classification markers
ships with that session's latest classification (task type, CHAT, trace) and the
job link the reporter resolves for it (a root: its own latest non-halt job; a
subagent: its root's). Reporter only. Accepted bias: an unrelated later turn is
charged to the earlier job, which understates that job's ROI.

Locked decision LD-2: a carried row links to a job whose outcome is already
ledgered only within REVENIUM_JOBS_STALE_SECONDS (600s) of that outcome, and
widening that bound after a live-tenant probe must change exactly one function,
`_carry_link_window` (C-15). Two classes here pin that seam from both sides.

Everything drives the REAL hermes-report.sh (the PATH-shim + state.db idiom of
tests/test_subagent_job_link_hold.py) or the real shell functions extracted from
it and run under /bin/bash (3.2 on macOS) as well as the bash on PATH.
"""
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests._compat_helpers import (
    SCRIPTS_DIR,
    argv_to_flags,
    assert_argv_is_golden_argv_order,
    assert_argv_matches_golden,
    build_shim,
    build_state_db,
    load_golden,
    run_script,
    seed_parent_session_ids,
)

sys.path.insert(0, str(SCRIPTS_DIR))
import split_strategies  # noqa: E402  (path inserted just above)

REPORTER = SCRIPTS_DIR / 'hermes-report.sh'

# Both ends of every fixture session are far in the past, so the settle filter
# passes with no .ready sentinel and no G-03 hold applies.
OLD_START = 1715514000.0
OLD_END = 1715514066.0
MARKER_TS = 1715515000.0

ROOT_SID = 'carry-root-0001'
KID_SID = 'carry-kid-0001'
KID2_SID = 'carry-kid-0002'
G_MUID = 'carry-g-0001'
C_MUID = 'carry-c-0001'
G2_MUID = 'carry-g-0002'
C2_MUID = 'carry-c-0002'
KG_MUID = 'carry-kg-0001'
KC_MUID = 'carry-kc-0001'
TRACE = 'carry-trace-0001'
KID_TRACE = 'carry-kid-trace-0001'
JOB = 'carry_job_ab12'
JOB_NAME = 'Carry the label forward'
JOB_TYPE = 'code_review'
LABEL = 'code_review'
HALT_JOB = 'guardrail-halt-ab12'

CARRY_UNLINKED = 'Carried completion shipping WITHOUT --agentic-job-id'

# The golden's session (tests/fixtures/compat/meter-completion-carried.golden.json).
GOLDEN_SID = 'compat-sid-carried-001'
GOLDEN_TRACE = 'compat-trace-carried-001'
GOLDEN_JOB = 'compat-job-carried-001'
GOLDEN_JOB_NAME = 'Carried Test Job'


def _session(sid, input_tokens, output_tokens, cost='0', **overrides):
    base = {
        'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
        'input_tokens': input_tokens, 'output_tokens': output_tokens,
        'cache_read': 0, 'cache_write': 0, 'reasoning': 0,
        'estimated_cost': cost, 'api_calls': 1,
        'started_at': OLD_START, 'ended_at': OLD_END,
        'billing_provider': 'anthropic',
    }
    base.update(overrides)
    return base


def _child(sid, input_tokens, output_tokens, cost='0', **overrides):
    """A subagent: it starts after its root, so the reporter's ORDER BY
    started_at DESC visits it BEFORE the root that performs the job create."""
    overrides.setdefault('started_at', OLD_START + 10)
    overrides.setdefault('ended_at', OLD_END + 10)
    return _session(sid, input_tokens, output_tokens, cost, **overrides)


_UNSET = object()


def _task(sid, muid, op, task_type, ts, trace_id=_UNSET):
    rec = {'muid': muid, 'ts': ts, 'sid': sid, 'task_type': task_type,
           'operation_type': op}
    if trace_id is _UNSET:
        rec['trace_id'] = sid
    elif trace_id is not None:
        rec['trace_id'] = trace_id
    return rec


def _pair(sid, g_muid, c_muid, task_type, ts=MARKER_TS, trace_id=_UNSET):
    """A classification exactly as the classifier writes it."""
    return [
        _task(sid, g_muid, 'GUARDRAIL', task_type, ts, trace_id),
        _task(sid, c_muid, 'CHAT', task_type, ts + 0.000027, trace_id),
    ]


def _job(sid, job_id=JOB, name=JOB_NAME, job_type=JOB_TYPE, status='SUCCESS', ts=1715515100.0):
    return {'kind': 'job', 'ts': ts, 'sid': sid, 'agentic_job_id': job_id,
            'job_name': name, 'job_type': job_type, 'status': status}


def _halt(sid, ts=1715515300.0):
    return _job(sid, HALT_JOB, 'Arc interrupted by guardrail halt',
                'interrupted', 'CANCELLED', ts)


class _CarryHarness(unittest.TestCase):
    """One scratch HERMES_HOME, many ticks."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='gsd-carry-forward-')
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
        self.now = time.time()

    # ------------------------------------------------------------------ setup
    def make_db(self, sessions, parents=None, parent_column=True):
        build_state_db(self.state_db, sessions)
        if parent_column:
            mapping = {s['id']: None for s in sessions}
            mapping.update(parents or {})
            seed_parent_session_ids(self.state_db, mapping)

    def make_shim(self, fail_jobs_create=False, **kwargs):
        shim = os.path.join(self.bin_dir, 'revenium')
        build_shim(shim, **kwargs)
        if fail_jobs_create:
            with open(shim) as f:
                body = f.read()
            # `jobs create --help` is the capability probe and must keep
            # answering; only a real create fails.
            body = body.replace(
                '  jobs)\n',
                '  jobs)\n    if [[ "$2" == "create" && "$3" != "--help" ]]; then exit 9; fi\n', 1)
            with open(shim, 'w') as f:
                f.write(body)
            os.chmod(shim, 0o755)

    def write_markers(self, sid, records):
        with open(os.path.join(self.markers_dir, f'{sid}.jsonl'), 'w') as f:
            for rec in records:
                f.write(json.dumps(rec, separators=(',', ':')) + '\n')

    def append_markers(self, sid, records):
        with open(os.path.join(self.markers_dir, f'{sid}.jsonl'), 'a') as f:
            for rec in records:
                f.write(json.dumps(rec, separators=(',', ':')) + '\n')

    @property
    def ledger_path(self):
        return os.path.join(self.state_dir, 'revenium-hermes.ledger')

    @property
    def jobs_ledger_path(self):
        return os.path.join(self.state_dir, 'revenium-jobs.ledger')

    def seed_hermes(self, sid, total, muids, ts=1715515200.0):
        """Ledger `muids` as consumed at `total` tokens (v2 lines)."""
        with open(self.ledger_path, 'a') as f:
            for muid in muids:
                f.write(f'HERMES:{sid}:{total}:{ts:.3f}:{muid}\n')

    def seed_job(self, job_id=JOB, *, created_ago=4000, outcome_ago=None, status='SUCCESS'):
        with open(self.jobs_ledger_path, 'a') as f:
            if created_ago is not None:
                f.write(f'JOB:{job_id}:created:{self.now - created_ago:.3f}\n')
            if outcome_ago is not None:
                f.write(f'JOB:{job_id}:outcome:{self.now - outcome_ago:.3f}:{status}\n')

    def grow(self, sid, input_tokens, output_tokens):
        conn = sqlite3.connect(self.state_db)
        try:
            conn.execute('UPDATE sessions SET input_tokens = ?, output_tokens = ? WHERE id = ?',
                         (input_tokens, output_tokens, sid))
            conn.commit()
        finally:
            conn.close()

    def ledger_lines(self, sid=None):
        if not os.path.exists(self.ledger_path):
            return []
        with open(self.ledger_path) as f:
            lines = [ln.rstrip('\n') for ln in f if ln.strip()]
        if sid is None:
            return lines
        return [ln for ln in lines if ln.startswith(f'HERMES:{sid}:')]

    def log_text(self):
        path = os.path.join(self.state_dir, 'revenium-metering.log')
        if not os.path.exists(path):
            return ''
        with open(path) as f:
            return f.read()

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
            'REVENIUM_JOBS_STALE_SECONDS': '600',
            'REVENIUM_CRON_SETTLE_SECONDS': '600',
        }
        for key in ('REVENIUM_AGENT_NAME', 'REVENIUM_SQUAD_NAME', 'REVENIUM_AUX_METERING'):
            env.pop(key, None)
        if extra_env:
            env.update(extra_env)
        rc, _inv, output = run_script(REPORTER, env, inv_log)
        meter, jobs = [], []
        if os.path.exists(meter_log):
            with open(meter_log) as f:
                meter = [shlex.split(ln) for ln in f.read().splitlines() if ln.strip()]
        if os.path.exists(jobs_log):
            with open(jobs_log) as f:
                jobs = [shlex.split(ln) for ln in f.read().splitlines() if ln.strip()]
        self.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {output}')
        return {'argv': meter, 'flags': [argv_to_flags(a) for a in meter],
                'jobs': jobs, 'output': output}

    @staticmethod
    def rows_for(run, sid):
        return [f for f in run['flags'] if f.get('--transaction-id', '').startswith(f'{sid}-')]

    # --------------------------------------------------------------- fixtures
    def carried_root(self, records, *, sid=ROOT_SID, grown=(200, 100), seed_total=150,
                     seeded=(G_MUID, C_MUID), parent_column=True, **session_overrides):
        """A root whose markers are all ledgered at `seed_total`, then grown, so
        the FIRST tick is the carry tick."""
        session_overrides.setdefault('ended_at', OLD_START)
        self.make_db([_session(sid, *grown, **session_overrides)], parent_column=parent_column)
        self.write_markers(sid, records)
        self.seed_hermes(sid, seed_total, seeded)

    def assert_no_job_flags(self, flags, why=''):
        for flag in ('--agentic-job-id', '--agentic-job-name', '--agentic-job-type'):
            self.assertNotIn(flag, flags, f'{why}: {flag} present in {flags}')


# =============================================================================
# The selectors (split_strategies.py), pure
# =============================================================================
class CarrySelectorUnitTests(unittest.TestCase):

    def _select_class(self):
        fn = getattr(split_strategies, 'select_carry_classification', None)
        if fn is None:
            self.fail('split_strategies.select_carry_classification is not defined')
        return fn

    def _select_job(self):
        fn = getattr(split_strategies, 'select_carry_job', None)
        if fn is None:
            self.fail('split_strategies.select_carry_job is not defined')
        return fn

    @staticmethod
    def _m(muid, task_type, ts, **extra):
        rec = {'muid': muid, 'ts': ts, 'sid': 's', 'task_type': task_type,
               'operation_type': 'CHAT'}
        rec.update(extra)
        return rec

    # -- select_carry_classification ------------------------------------------

    def test_the_greatest_ts_wins_even_when_it_is_not_last_in_the_file(self):
        select = self._select_class()
        got = select([self._m('a', 'planning', 20.0), self._m('b', 'research', 10.0)])
        self.assertEqual(got['muid'], 'a')

    def test_a_tie_goes_to_the_later_line(self):
        select = self._select_class()
        got = select([self._m('a', 'planning', 10.0), self._m('b', 'research', 10.0)])
        self.assertEqual(got['muid'], 'b')

    def test_a_missing_boolean_or_non_finite_ts_ranks_zero(self):
        select = self._select_class()
        for bad in (None, True, False, float('nan'), float('inf'), float('-inf'), 'x', [1]):
            with self.subTest(bad=bad):
                good = self._m('good', 'planning', 5.0)
                broken = self._m('broken', 'research', bad)
                # Ranks 0, so the finite ts beats it wherever it sits in the file.
                self.assertEqual(select([good, broken])['muid'], 'good')
                self.assertEqual(select([broken, good])['muid'], 'good')
        missing = {k: v for k, v in self._m('m', 'research', 1.0).items() if k != 'ts'}
        self.assertEqual(select([self._m('good', 'planning', 5.0), missing])['muid'], 'good')
        # Two rank-0 candidates tie, and the later line wins.
        a, b = self._m('a', 'planning', None), self._m('b', 'research', float('nan'))
        self.assertEqual(select([a, b])['muid'], 'b')

    def test_trivial_labels_are_skipped(self):
        select = self._select_class()
        got = select([self._m('a', 'planning', 1.0), self._m('b', 'thanks', 9.0),
                      self._m('c', 'greeting', 8.0)])
        self.assertEqual(got['muid'], 'a')

    def test_an_all_trivial_or_empty_list_is_none(self):
        select = self._select_class()
        self.assertIsNone(select([self._m('a', 'ack', 1.0), self._m('b', 'hello', 2.0)]))
        self.assertIsNone(select([]))
        self.assertIsNone(select(None))

    def test_non_string_and_empty_labels_never_qualify_and_nothing_raises(self):
        select = self._select_class()
        junk = ['nope', 7, None, {}, self._m('e', '', 9.0), self._m('n', None, 9.0),
                self._m('l', ['x'], 9.0), self._m('ok', 'planning', 1.0)]
        self.assertEqual(select(junk)['muid'], 'ok')

    # -- select_carry_job -------------------------------------------------------

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gsd-carry-selector-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _file(self, records, raw_lines=()):
        path = os.path.join(self.tmp, 'markers.jsonl')
        with open(path, 'w') as f:
            for rec in records:
                f.write(json.dumps(rec, separators=(',', ':')) + '\n')
            for line in raw_lines:
                f.write(line + '\n')
        return path

    @staticmethod
    def _j(job_id, name='N', job_type='t', status='SUCCESS', ts=1.0, **extra):
        rec = {'kind': 'job', 'ts': ts, 'sid': 's', 'agentic_job_id': job_id,
               'job_name': name, 'job_type': job_type, 'status': status}
        rec.update(extra)
        return rec

    def test_job_selection_skips_guardrail_halt_jobs_even_when_last(self):
        select = self._select_job()
        path = self._file([self._j('real', 'Real', ts=10.0), self._j('guardrail-halt-1', 'Halt', ts=20.0)])
        self.assertEqual(select(path), ('real', 'Real', 't', 10))

    def test_a_halt_only_file_selects_nothing(self):
        select = self._select_job()
        self.assertIsNone(select(self._file([self._j('guardrail-halt-1')])))

    def test_a_rejudged_id_is_one_job_with_its_latest_record(self):
        select = self._select_job()
        path = self._file([self._j('j1', 'Goal', status='CANCELLED', ts=10.0),
                           self._j('j1', 'Goal', status='SUCCESS', ts=30.0)])
        self.assertEqual(select(path), ('j1', 'Goal', 't', 30))

    def test_the_latest_ts_wins_not_the_last_line_and_a_tie_goes_to_the_later_line(self):
        select = self._select_job()
        path = self._file([self._j('later_ts', ts=200.0), self._j('earlier_ts', ts=100.0)])
        self.assertEqual(select(path)[0], 'later_ts')
        path = self._file([self._j('first', ts=100.0), self._j('second', ts=100.0)])
        self.assertEqual(select(path)[0], 'second')

    def test_a_folded_jobs_name_passes_through_verbatim(self):
        select = self._select_job()
        name = 'Main goal (also: second goal) (+2 more)'
        self.assertEqual(select(self._file([self._j('j', name)]))[1], name)

    def test_ids_are_sanitised_and_pipe_ids_are_dropped(self):
        select = self._select_job()
        path = self._file([self._j('a:b c\td', ts=1.0)])
        self.assertEqual(select(path)[0], 'a_b_c_d')
        path = self._file([self._j('pipe|id', ts=5.0), self._j('fine', ts=1.0)])
        self.assertEqual(select(path)[0], 'fine')

    def test_name_and_type_are_stripped_of_pipe_and_newlines(self):
        select = self._select_job()
        path = self._file([self._j('j', 'a|b\nc\rd', 'x|y')])
        got = select(path)
        self.assertEqual((got[1], got[2]), ('a_b_c_d', 'x_y'))

    def test_a_record_missing_a_required_key_or_an_id_is_not_a_job(self):
        select = self._select_job()
        no_status = self._j('a')
        del no_status['status']
        no_type = self._j('b')
        del no_type['job_type']
        path = self._file([no_status, no_type, self._j('', ts=1.0), self._j(None, ts=1.0),
                           self._j(['x'], ts=1.0)])
        self.assertIsNone(select(path))

    def test_ts_is_none_when_unusable_but_the_job_still_selects(self):
        select = self._select_job()
        for bad in (None, True, 'x', float('nan'), -5):
            with self.subTest(bad=bad):
                got = select(self._file([self._j('j', ts=bad)]))
                self.assertEqual(got[0], 'j')
                self.assertIsNone(got[3])

    def test_unreadable_inputs_select_nothing_and_never_raise(self):
        select = self._select_job()
        self.assertIsNone(select(os.path.join(self.tmp, 'absent.jsonl')))
        self.assertIsNone(select(self.tmp))  # a directory
        self.assertIsNone(select(''))
        self.assertIsNone(select(None))
        # Only task records, and only malformed lines.
        self.assertIsNone(select(self._file([_task('s', 'm', 'CHAT', 'planning', 1.0)])))
        self.assertIsNone(select(self._file([], raw_lines=['{not json', '[1,2]', '"str"'])))
        # A malformed line does not abort the lines around it.
        path = self._file([self._j('before', ts=1.0)], raw_lines=['{torn'])
        self.assertEqual(select(path)[0], 'before')
        # Not valid UTF-8.
        bad = os.path.join(self.tmp, 'bad.jsonl')
        with open(bad, 'wb') as f:
            f.write(b'\xff\xfe\x00bad\n')
        self.assertIsNone(select(bad))


# =============================================================================
# Shell functions, extracted from hermes-report.sh and run directly
# =============================================================================
FAKE_NOW = 1_900_000_000

_PRELUDE = '''
info() { echo "INFO: $*"; }
warn() { echo "WARN: $*"; }
date() { if [[ "$1" == "+%s" ]]; then printf '%s\\n' "${FAKE_NOW}"; else command date "$@"; fi; }
'''


def _function_source(name):
    text = REPORTER.read_text()
    m = re.search(rf'^{name}\(\) \{{\n.*?^\}}\n', text, re.S | re.M)
    return m.group(0) if m else None


class _ShellHarness(unittest.TestCase):
    BASHES = ('/bin/bash', 'bash')
    FUNCS = ()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gsd-carry-shell-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ledger = os.path.join(self.tmp, 'jobs.ledger')
        self.flags = os.path.join(self.tmp, 'outcome-warn')
        os.makedirs(self.flags)

    def _ledger(self, *lines):
        with open(self.ledger, 'w') as f:
            f.write(''.join(line + '\n' for line in lines))

    def _run(self, bash, call, env=None, redefine=''):
        bodies = []
        for name in self.FUNCS:
            src = _function_source(name)
            if src is None:
                self.fail(f'{name} is not defined in hermes-report.sh')
            bodies.append(src)
        script = _PRELUDE + '\n'.join(bodies) + f'\n{redefine}\n{call}\necho "rc=$?"\n'
        full_env = {
            **os.environ, 'JOBS_LEDGER_FILE': self.ledger,
            'OUTCOME_WARN_FLAGS_DIR': self.flags, 'FAKE_NOW': str(FAKE_NOW),
            'REVENIUM_JOBS_STALE_SECONDS': '600', 'REVENIUM_CRON_SETTLE_SECONDS': '600',
        }
        for key, value in (env or {}).items():
            if value is None:
                full_env.pop(key, None)
            else:
                full_env[key] = value
        out = subprocess.run([bash, '-c', script], env=full_env,
                             capture_output=True, text=True, timeout=30)
        m = re.search(r'rc=(\d+)\s*$', out.stdout)
        self.assertIsNotNone(m, out.stdout + out.stderr)
        return int(m.group(1)), out

    def _each(self, call, expected_rc, **kw):
        for bash in self.BASHES:
            rc, out = self._run(bash, call, **kw)
            self.assertEqual(rc, expected_rc, f'{bash}: {call}\n{out.stdout}{out.stderr}')


class CarryLinkWindowTests(_ShellHarness):
    """C-15: every carry link decision is `_carry_job_linkable`, and its
    outcome-age bound is `_carry_link_window` and nothing else."""

    FUNCS = ('_job_ledger_id', '_job_create_ledgered', '_job_linkable_for_aux',
             '_carry_link_window', '_carry_job_linkable')

    def _outcome_line(self, age):
        return f'JOB:j:outcome:{FAKE_NOW - age}.000:SUCCESS'

    def test_boundary_at_the_default_window(self):
        created = 'JOB:j:created:1.000'
        self._ledger(created)
        self._each('_carry_job_linkable j', 0)  # no outcome line: the job is open
        self._ledger(created, self._outcome_line(600))
        self._each('_carry_job_linkable j', 0)  # exactly one window old links
        self._ledger(created, self._outcome_line(601))
        self._each('_carry_job_linkable j', 1)  # a second older does not
        self._ledger(self._outcome_line(5))
        self._each('_carry_job_linkable j', 1)  # no created line
        self._ledger(created, 'JOB:j:outcome:garbage:SUCCESS')
        self._each('_carry_job_linkable j', 1)  # a malformed ts withholds
        self._ledger(created, f'JOB:j:outcome:{FAKE_NOW - 30}.9:SUCCESS')
        self._each('_carry_job_linkable j', 0)  # the fraction is dropped
        self._ledger(created)
        self._each('_carry_job_linkable ""', 1)
        self._each('_carry_job_linkable j', 1, env={'JOBS_LEDGER_FILE': os.path.join(self.tmp, 'absent')})

    def test_the_latest_outcome_line_decides(self):
        self._ledger('JOB:j:created:1.000', self._outcome_line(5000), self._outcome_line(10))
        self._each('_carry_job_linkable j', 0)
        self._ledger('JOB:j:created:1.000', self._outcome_line(10), self._outcome_line(5000))
        self._each('_carry_job_linkable j', 1)

    def test_an_id_that_is_a_prefix_of_another_does_not_borrow_its_lines(self):
        self._ledger('JOB:job_abc:created:1.000')
        self._each('_carry_job_linkable job_ab', 1)

    def test_window_prints_600_for_unset_or_garbage_and_the_value_when_valid(self):
        for bash in self.BASHES:
            for value, expected in ((None, '600'), ('', '600'), ('banana', '600'),
                                    ('12345678901', '600'), ('-5', '600'), ('90', '90'),
                                    ('86400', '86400')):
                with self.subTest(bash=bash, value=value):
                    rc, out = self._run(bash, 'printf "w=%s\\n" "$(_carry_link_window)"',
                                        env={'REVENIUM_JOBS_STALE_SECONDS': value})
                    self.assertIn(f'w={expected}\n', out.stdout)

    def test_the_window_follows_the_stale_setting(self):
        self._ledger('JOB:j:created:1.000', self._outcome_line(90))
        self._each('_carry_job_linkable j', 1, env={'REVENIUM_JOBS_STALE_SECONDS': '30'})
        self._each('_carry_job_linkable j', 0, env={'REVENIUM_JOBS_STALE_SECONDS': '300'})

    def test_aux_isolation_a_narrower_carry_window_moves_only_the_carry_decision(self):
        self._ledger('JOB:j:created:1.000', self._outcome_line(300))
        redefine = '_carry_link_window() { printf "%s" 60; }'
        self._each('_carry_job_linkable j', 1, redefine=redefine)
        self._each('_job_linkable_for_aux j', 0, redefine=redefine)

    def test_aux_isolation_a_wider_carry_window_moves_only_the_carry_decision(self):
        self._ledger('JOB:j:created:1.000', self._outcome_line(700))
        redefine = '_carry_link_window() { printf "%s" 86400; }'
        self._each('_carry_job_linkable j', 0, redefine=redefine)
        self._each('_job_linkable_for_aux j', 1, redefine=redefine)


class CarryWindowRc2IsolationTests(_ShellHarness):
    """C-15: the RC-2 hold bound is REVENIUM_JOBS_STALE_SECONDS read directly,
    so widening the carry window moves neither it nor the aux bound."""

    FUNCS = ('_job_ledger_id', '_job_create_ledgered', '_job_outcome_log_once',
             '_job_child_hold_age', '_child_job_link_hold', '_carry_link_window')

    def _hold(self, bash, age, redefine=''):
        call = (f'sessions=$\'other-session|x\\n\'\n'
                f'_child_job_link_hold carry_job_x {FAKE_NOW - age} root-sid kid-sid')
        return self._run(bash, call, redefine=redefine)

    def test_rc2_holds_and_releases_identically_for_any_carry_window(self):
        for redefine in ('', '_carry_link_window() { printf "%s" 60; }',
                         '_carry_link_window() { printf "%s" 86400; }'):
            for bash in self.BASHES:
                with self.subTest(bash=bash, redefine=redefine):
                    rc, out = self._hold(bash, 300, redefine)
                    self.assertEqual(rc, 0, f'300s old must HOLD\n{out.stdout}{out.stderr}')
                    self.assertIn('Subagent completions held', out.stdout)
                    rc, out = self._hold(bash, 700, redefine)
                    self.assertEqual(rc, 1, f'700s old must release\n{out.stdout}{out.stderr}')
                    self.assertIn('Subagent completions shipping WITHOUT --agentic-job-id', out.stdout)
                    for name in os.listdir(self.flags):
                        os.remove(os.path.join(self.flags, name))

    def test_rc2_log_lines_and_flag_keys_are_the_per_marker_gates_own(self):
        rc, out = self._hold('bash', 300)
        self.assertEqual(rc, 0)
        self.assertIn('INFO: Subagent completions held: root job carry_job_x has no confirmed '
                      'create yet (session=kid-sid); retried next tick, nothing ledgered', out.stdout)
        self.assertTrue(os.path.exists(os.path.join(self.flags, 'carry_job_x__child-hold.flag')))
        rc, out = self._hold('bash', 700)
        self.assertEqual(rc, 1)
        self.assertIn('WARN: Subagent completions shipping WITHOUT --agentic-job-id: root job '
                      'carry_job_x still has no confirmed create after 700s (session=kid-sid); '
                      'linking now would make Revenium create it nameless', out.stdout)
        self.assertTrue(os.path.exists(os.path.join(self.flags, 'carry_job_x__child-unlinked.flag')))

    def test_a_job_ts_that_proves_nothing_ships_unlinked(self):
        for ts in ('', 'garbage'):
            call = (f'sessions=$\'other-session|x\\n\'\n'
                    f'_child_job_link_hold carry_job_x "{ts}" root-sid kid-sid')
            self._each(call, 1)
        # A marker ts from the future is not "very recent" either.
        call = (f'sessions=$\'other-session|x\\n\'\n'
                f'_child_job_link_hold carry_job_x {FAKE_NOW + 9999} root-sid kid-sid')
        self._each(call, 1)

    def test_a_root_in_this_ticks_set_counts_continuously_renewed_holds(self):
        call = (f'sessions=$\'root-sid|x\\n\'\n'
                f'_child_job_link_hold carry_job_x {FAKE_NOW - 5000} root-sid kid-sid')
        # First hold of the job: the persisted clock starts at 0, so it holds
        # however old the marker is.
        self._each(call, 0)

    def test_source_scan_the_carry_window_is_read_in_one_place_only(self):
        text = REPORTER.read_text()
        code = '\n'.join(ln for ln in text.splitlines() if not ln.lstrip().startswith('#'))
        for name in ('_carry_link_window', '_carry_job_linkable'):
            self.assertIsNotNone(re.search(rf'^{name}\(\) \{{', code, re.M),
                                 f'{name} is not defined in hermes-report.sh')
        # Drop the two defining bodies; nothing else may mention the window.
        rest = code
        for name in ('_carry_link_window', '_carry_job_linkable'):
            rest = re.sub(rf'^{name}\(\) \{{\n.*?^\}}\n', '', rest, flags=re.S | re.M)
        self.assertNotIn('_carry_link_window', rest,
                         '_carry_link_window must be called only inside _carry_job_linkable')
        body = re.search(r'^_carry_job_linkable\(\) \{\n.*?^\}\n', code, re.S | re.M).group(0)
        self.assertIn('_carry_link_window', body)
        for name in ('_job_linkable_for_aux', '_job_child_hold_age', '_child_job_link_hold'):
            src = re.search(rf'^{name}\(\) \{{\n.*?^\}}\n', code, re.S | re.M)
            self.assertIsNotNone(src, f'{name} is not defined in hermes-report.sh')
            self.assertNotIn('_carry_link_window', src.group(0), name)

    def test_source_scan_the_zero_marker_branch_decides_through_the_carry_predicate(self):
        text = REPORTER.read_text()
        start = text.index('=== Zero-marker fallthrough')
        end = text.index('fi # LEGACY_COMPLETIONS_SKIP')
        region = '\n'.join(ln for ln in text[start:end].splitlines()
                           if not ln.lstrip().startswith('#'))
        self.assertIn('_carry_job_linkable', region)
        self.assertNotIn('_job_linkable_for_aux', region)
        self.assertNotIn('_carry_link_window', region)


# =============================================================================
# A root session's carried row (CF-1, CF-3)
# =============================================================================
class RootCarryTests(_CarryHarness):

    def test_pair_and_success_job_ship_per_marker_then_the_follow_up_carries_both(self):
        """The reported defect, end to end: tick 1 ships the pair per-marker
        and ledgers the outcome; the session grows; tick 2 ships ONE completion
        carrying the label, CHAT, the marker's trace and the job."""
        sid = GOLDEN_SID
        self.make_db([_session(sid, 100, 50, ended_at=OLD_START)])
        self.write_markers(sid, _pair(sid, G_MUID, C_MUID, LABEL, trace_id=GOLDEN_TRACE)
                           + [_job(sid, GOLDEN_JOB, GOLDEN_JOB_NAME)])
        self.make_shim()

        first = self.tick()
        self.assertEqual(len(first['flags']), 1, first['argv'])
        self.assertEqual(first['flags'][0]['--transaction-id'], f'{sid}-150-{C_MUID}')

        self.grow(sid, 200, 100)
        second = self.tick()
        self.assertEqual(len(second['flags']), 1, second['argv'])
        row = second['flags'][0]
        self.assertEqual(row['--task-type'], LABEL)
        self.assertEqual(row['--operation-type'], 'CHAT')
        self.assertEqual(row['--trace-id'], GOLDEN_TRACE)
        self.assertEqual(row['--transaction-id'], f'{sid}-300')
        self.assertEqual(row['--agentic-job-id'], GOLDEN_JOB)
        self.assertEqual(row['--agentic-job-name'], GOLDEN_JOB_NAME)
        self.assertEqual(row['--agentic-job-type'], LABEL)
        golden = load_golden('meter-completion-carried.golden.json')
        assert_argv_matches_golden(self, second['argv'][0], golden)
        assert_argv_is_golden_argv_order(self, second['argv'][0], golden)

        reported = [ln for ln in self.log_text().splitlines()
                    if f'Reported: session={sid} task_type={LABEL} ' in ln and 'carried_from=' in ln]
        self.assertEqual(len(reported), 1, self.log_text())
        self.assertIn(f' carried_from={C_MUID} job={GOLDEN_JOB}', reported[0])

    def test_no_job_record_carries_the_label_with_no_job_flags(self):
        self.carried_root(_pair(ROOT_SID, G_MUID, C_MUID, LABEL, trace_id=TRACE))
        self.make_shim()
        run = self.tick()
        self.assertEqual(len(run['flags']), 1, run['argv'])
        row = run['flags'][0]
        self.assertEqual(row['--task-type'], LABEL)
        self.assertEqual(row['--operation-type'], 'CHAT')
        self.assertEqual(row['--trace-id'], TRACE)
        self.assertEqual(row['--transaction-id'], f'{ROOT_SID}-300')
        self.assert_no_job_flags(row, 'no job record')
        self.assertIn(f' carried_from={C_MUID} job=none', self.log_text())

    def test_a_marker_without_a_trace_id_falls_back_to_the_root_session(self):
        self.carried_root(_pair(ROOT_SID, G_MUID, C_MUID, LABEL, trace_id=None))
        self.make_shim()
        row = self.tick()['flags'][0]
        self.assertEqual(row['--task-type'], LABEL)
        self.assertEqual(row['--trace-id'], ROOT_SID)

    def test_a_job_closed_beyond_the_window_carries_the_label_unlinked_and_logs_once(self):
        self.carried_root(_pair(ROOT_SID, G_MUID, C_MUID, LABEL, trace_id=TRACE) + [_job(ROOT_SID)])
        self.seed_job(created_ago=4200, outcome_ago=3600)
        self.make_shim()
        first = self.tick()
        self.assertEqual(first['flags'][0]['--task-type'], LABEL)
        self.assert_no_job_flags(first['flags'][0], 'closed 3600s ago, window 600s')
        self.grow(ROOT_SID, 300, 150)
        second = self.tick()
        self.assertEqual(second['flags'][0]['--transaction-id'], f'{ROOT_SID}-450')
        self.assert_no_job_flags(second['flags'][0], 'second growth')
        line = f'{CARRY_UNLINKED}: job {JOB} closed more than 600s ago (session={ROOT_SID})'
        self.assertEqual(self.log_text().count(line), 1, self.log_text())

    def test_a_job_closed_inside_the_window_links(self):
        self.carried_root(_pair(ROOT_SID, G_MUID, C_MUID, LABEL, trace_id=TRACE) + [_job(ROOT_SID)])
        self.seed_job(created_ago=200, outcome_ago=60)
        self.make_shim()
        row = self.tick()['flags'][0]
        self.assertEqual((row['--agentic-job-id'], row['--agentic-job-name'],
                          row['--agentic-job-type']), (JOB, JOB_NAME, JOB_TYPE))
        self.assertNotIn(CARRY_UNLINKED, self.log_text())

    def test_an_open_job_links(self):
        self.carried_root(_pair(ROOT_SID, G_MUID, C_MUID, LABEL, trace_id=TRACE)
                          + [_job(ROOT_SID, status='IN_PROGRESS')])
        self.seed_job(created_ago=200)
        self.make_shim()
        self.assertEqual(self.tick()['flags'][0]['--agentic-job-id'], JOB)

    def test_a_halt_job_appended_after_the_real_job_leaves_the_link_on_the_real_job(self):
        self.carried_root(_pair(ROOT_SID, G_MUID, C_MUID, LABEL, trace_id=TRACE)
                          + [_job(ROOT_SID), _halt(ROOT_SID)])
        self.seed_job(created_ago=200, outcome_ago=60)
        self.make_shim()
        row = self.tick()['flags'][0]
        self.assertEqual(row['--agentic-job-id'], JOB)
        self.assertEqual(row['--agentic-job-name'], JOB_NAME)

    def test_a_halt_only_job_set_gives_no_link(self):
        self.carried_root(_pair(ROOT_SID, G_MUID, C_MUID, LABEL, trace_id=TRACE) + [_halt(ROOT_SID)])
        self.make_shim()
        row = self.tick()['flags'][0]
        self.assertEqual(row['--task-type'], LABEL)
        self.assert_no_job_flags(row, 'halt-only')

    def test_cancelled_then_success_for_one_id_links_that_id(self):
        self.carried_root(_pair(ROOT_SID, G_MUID, C_MUID, LABEL, trace_id=TRACE) + [
            _job(ROOT_SID, status='CANCELLED', ts=1715515100.0),
            _job(ROOT_SID, status='SUCCESS', ts=1715515200.0)])
        self.seed_job(created_ago=200, outcome_ago=60)
        self.make_shim()
        run = self.tick()
        self.assertEqual(run['flags'][0]['--agentic-job-id'], JOB)

    def test_a_folded_jobs_name_passes_through(self):
        name = 'Main goal (also: second goal) (+1 more)'
        self.carried_root(_pair(ROOT_SID, G_MUID, C_MUID, LABEL, trace_id=TRACE)
                          + [_job(ROOT_SID, name=name)])
        self.seed_job(created_ago=200, outcome_ago=60)
        self.make_shim()
        self.assertEqual(self.tick()['flags'][0]['--agentic-job-name'], name)

    def test_a_job_that_was_never_created_gives_no_link(self):
        self.carried_root(_pair(ROOT_SID, G_MUID, C_MUID, LABEL, trace_id=TRACE) + [_job(ROOT_SID)])
        self.make_shim(fail_jobs_create=True)
        run = self.tick()
        row = run['flags'][0]
        self.assertEqual(row['--task-type'], LABEL)
        self.assert_no_job_flags(row, 'create failed')
        self.assertIn(f'{CARRY_UNLINKED}: job {JOB} was never created (session={ROOT_SID})',
                      self.log_text())

    def test_a_root_that_cannot_be_confirmed_gives_no_link(self):
        self.carried_root(_pair(ROOT_SID, G_MUID, C_MUID, LABEL, trace_id=TRACE) + [_job(ROOT_SID)],
                          parent_column=False)
        self.seed_job(created_ago=200, outcome_ago=60)
        self.make_shim()
        row = self.tick()['flags'][0]
        self.assertEqual(row['--task-type'], LABEL)
        self.assert_no_job_flags(row, 'parent_session_id column absent')
        self.assertIn(f'{CARRY_UNLINKED}: job {JOB} has an unconfirmed root (session={ROOT_SID})',
                      self.log_text())

    def test_a_trivial_label_never_carries(self):
        """The latest marker is a greeting; the session's latest REAL
        classification is what carries."""
        self.carried_root(_pair(ROOT_SID, G_MUID, C_MUID, LABEL, trace_id=TRACE)
                          + [_task(ROOT_SID, 'carry-t-0001', 'CHAT', 'thanks', MARKER_TS + 50)])
        self.make_shim()
        row = self.tick()['flags'][0]
        self.assertEqual(row['--task-type'], LABEL)

    def test_the_latest_classification_wins_over_an_earlier_one(self):
        self.carried_root(
            _pair(ROOT_SID, G_MUID, C_MUID, 'planning', MARKER_TS, TRACE)
            + _pair(ROOT_SID, G2_MUID, C2_MUID, 'research', MARKER_TS + 100, TRACE),
            seeded=(G_MUID, C_MUID, G2_MUID, C2_MUID))
        self.make_shim()
        run = self.tick()
        self.assertEqual(len(run['flags']), 1, run['argv'])
        self.assertEqual(run['flags'][0]['--task-type'], 'research')

    def test_an_unclassified_pair_is_still_a_classification_and_carries_the_job(self):
        self.carried_root(_pair(ROOT_SID, G_MUID, C_MUID, 'unclassified', trace_id=TRACE)
                          + [_job(ROOT_SID)])
        self.seed_job(created_ago=200, outcome_ago=60)
        self.make_shim()
        row = self.tick()['flags'][0]
        self.assertEqual(row['--task-type'], 'unclassified')
        self.assertEqual(row['--agentic-job-id'], JOB)
        self.assertIn(f' carried_from={C_MUID} job={JOB}', self.log_text())


# =============================================================================
# A subagent's carried row (CF-2)
# =============================================================================
class SubagentCarryTests(_CarryHarness):

    def _family(self, *, root_tokens=(100, 50), root_records=None, kid_grown=(120, 60),
                root_in_set=True, root_markers_ts=None):
        """A root with a job and a finished child whose own markers are ledgered
        at total 90 and which has since grown."""
        root_records = root_records if root_records is not None else (
            _pair(ROOT_SID, G_MUID, C_MUID, 'planning', MARKER_TS, TRACE) + [_job(ROOT_SID)])
        root = _session(ROOT_SID, *(root_tokens if root_in_set else (0, 0)),
                        ended_at=OLD_START)
        kid = _child(KID_SID, *kid_grown, ended_at=OLD_START + 10)
        self.make_db([root, kid], parents={KID_SID: ROOT_SID})
        self.write_markers(ROOT_SID, root_records)
        self.write_markers(KID_SID, _pair(KID_SID, KG_MUID, KC_MUID, 'research',
                                          MARKER_TS + 10, KID_TRACE))
        if root_in_set:
            self.seed_hermes(ROOT_SID, sum(root_tokens), (G_MUID, C_MUID))
        self.seed_hermes(KID_SID, 90, (KG_MUID, KC_MUID))

    def test_a_child_carries_its_own_label_and_trace_plus_its_roots_job_id_only(self):
        self._family()
        self.seed_job(created_ago=200, outcome_ago=60)
        self.make_shim()
        run = self.tick()
        rows = self.rows_for(run, KID_SID)
        self.assertEqual(len(rows), 1, run['argv'])
        row = rows[0]
        self.assertEqual(row['--task-type'], 'research')
        self.assertEqual(row['--operation-type'], 'CHAT')
        self.assertEqual(row['--trace-id'], KID_TRACE)
        self.assertEqual(row['--transaction-id'], f'{KID_SID}-180')
        self.assertEqual(row['--agentic-job-id'], JOB)
        self.assertNotIn('--agentic-job-name', row)
        self.assertNotIn('--agentic-job-type', row)
        self.assertEqual(row['--squad-id'], ROOT_SID)
        self.assertEqual(row['--squad-role'], 'subagent')
        self.assertIn(f' carried_from={KC_MUID} job={JOB}', self.log_text())

    def test_a_missing_root_create_holds_the_child_then_links_after_the_create(self):
        self._family()
        self.make_shim()
        first = self.tick()
        self.assertEqual(self.rows_for(first, KID_SID), [], first['argv'])
        self.assertEqual(len(self.ledger_lines(KID_SID)), 2, 'a held child must ledger nothing')
        self.assertIn(f'Subagent completions held: root job {JOB} has no confirmed create yet '
                      f'(session={KID_SID}); retried next tick, nothing ledgered', self.log_text())
        # The root's own iteration performed the create.
        self.assertIn(f'JOB:{JOB}:created:', open(self.jobs_ledger_path).read())

        second = self.tick()
        rows = self.rows_for(second, KID_SID)
        self.assertEqual(len(rows), 1, second['argv'])
        self.assertEqual(rows[0]['--agentic-job-id'], JOB)
        self.assertEqual(rows[0]['--task-type'], 'research')
        self.assertEqual(self.log_text().count(f'Subagent completions held: root job {JOB}'), 1)

    def test_past_the_bound_the_child_ships_its_label_unlinked_and_logs_once(self):
        """The root is not in this tick's set (no tokens) and its job marker is
        older than the bound, so nothing will create the job: ship unlinked."""
        self._family(root_in_set=False,
                     root_records=_pair(ROOT_SID, G_MUID, C_MUID, 'planning', MARKER_TS, TRACE)
                     + [_job(ROOT_SID, ts=self.now - 5000)])
        self.make_shim()
        run = self.tick()
        rows = self.rows_for(run, KID_SID)
        self.assertEqual(len(rows), 1, run['argv'])
        self.assertEqual(rows[0]['--task-type'], 'research')
        self.assertNotIn('--agentic-job-id', rows[0])
        self.grow(KID_SID, 150, 70)
        self.tick()
        marker = f'Subagent completions shipping WITHOUT --agentic-job-id: root job {JOB}'
        self.assertEqual(self.log_text().count(marker), 1, self.log_text())

    def test_the_roots_last_job_record_being_a_halt_marker_still_links_the_real_job(self):
        self._family(root_records=_pair(ROOT_SID, G_MUID, C_MUID, 'planning', MARKER_TS, TRACE)
                     + [_job(ROOT_SID), _halt(ROOT_SID)])
        self.seed_job(created_ago=200, outcome_ago=60)
        self.make_shim()
        rows = self.rows_for(self.tick(), KID_SID)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['--agentic-job-id'], JOB)

    def test_a_root_job_closed_beyond_the_window_ships_the_child_unlinked(self):
        self._family()
        self.seed_job(created_ago=4200, outcome_ago=3600)
        self.make_shim()
        rows = self.rows_for(self.tick(), KID_SID)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['--task-type'], 'research')
        self.assertNotIn('--agentic-job-id', rows[0])
        self.assertIn(f'{CARRY_UNLINKED}: job {JOB} closed more than 600s ago (session={KID_SID})',
                      self.log_text())

    def test_a_child_never_links_the_job_in_its_own_marker_file(self):
        """The id comes from the ROOT's file; a job record in the child's own
        file would be an orphan reference."""
        self._family()
        self.append_markers(KID_SID, [_job(KID_SID, 'kid_own_job', 'Kid job')])
        self.seed_job(created_ago=200, outcome_ago=60)
        self.seed_job('kid_own_job', created_ago=200, outcome_ago=60)
        self.make_shim()
        rows = self.rows_for(self.tick(), KID_SID)
        self.assertEqual(rows[0]['--agentic-job-id'], JOB)


# =============================================================================
# CF-4: a session with no classification ships exactly what it shipped before
# =============================================================================
class UnchangedMarkerlessTests(_CarryHarness):

    SID = 'carry-plain-0001'

    def _assert_markerless_row(self, run, why):
        self.assertEqual(len(run['flags']), 1, f'{why}: {run["argv"]}')
        row = run['flags'][0]
        self.assertEqual(row['--task-type'], 'unclassified', why)
        self.assertEqual(row['--operation-type'], 'CHAT', why)
        self.assertEqual(row['--trace-id'], self.SID, why)
        self.assertEqual(row['--transaction-id'], f'{self.SID}-150', why)
        self.assert_no_job_flags(row, why)
        lines = self.ledger_lines(self.SID)
        self.assertEqual(len(lines), 1, f'{why}: {lines}')
        self.assertRegex(lines[0], rf'^HERMES:{re.escape(self.SID)}:150:\d+\.\d+:unclassified-\d+$', why)
        self.assertIn(f'Reported: session={self.SID} task_type=unclassified model=', self.log_text(), why)
        self.assertNotIn('carried_from=', self.log_text(), why)

    def _fresh(self):
        self.make_db([_session(self.SID, 100, 50, ended_at=OLD_START)])
        self.make_shim()

    def test_no_marker_file(self):
        self._fresh()
        self._assert_markerless_row(self.tick(), 'no marker file')

    def test_a_job_records_only_file(self):
        self._fresh()
        self.write_markers(self.SID, [_job(self.SID)])
        self._assert_markerless_row(self.tick(), 'job records only')

    def test_a_trivial_labels_only_file(self):
        self._fresh()
        self.write_markers(self.SID, [_task(self.SID, 'carry-t-1', 'CHAT', 'thanks', MARKER_TS),
                                      _task(self.SID, 'carry-t-2', 'GUARDRAIL', 'hello', MARKER_TS + 1),
                                      _job(self.SID)])
        self._assert_markerless_row(self.tick(), 'trivial labels only')

    def test_a_directory_at_the_marker_path(self):
        self._fresh()
        os.makedirs(os.path.join(self.markers_dir, f'{self.SID}.jsonl'))
        self._assert_markerless_row(self.tick(), 'directory at the marker path')

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root ignores file modes')
    def test_an_unreadable_marker_file(self):
        self._fresh()
        path = os.path.join(self.markers_dir, f'{self.SID}.jsonl')
        self.write_markers(self.SID, _pair(self.SID, G_MUID, C_MUID, LABEL))
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o600)
        self._assert_markerless_row(self.tick(), 'unreadable marker file')

    def test_a_session_whose_markers_are_unconsumed_still_ships_per_marker(self):
        """No carry: the pair has not shipped yet, so it ships per-marker."""
        self._fresh()
        self.write_markers(self.SID, _pair(self.SID, G_MUID, C_MUID, LABEL))
        run = self.tick()
        self.assertEqual(len(run['flags']), 1, run['argv'])
        self.assertEqual(run['flags'][0]['--transaction-id'], f'{self.SID}-150-{C_MUID}')
        self.assertNotIn('carried_from=', self.log_text())


# =============================================================================
# CF-5: a carried row is idempotent and keeps the markerless ledger shape
# =============================================================================
class CarryIdempotencyTests(_CarryHarness):

    def _carry_fixture(self):
        self.carried_root(_pair(ROOT_SID, G_MUID, C_MUID, LABEL, trace_id=TRACE))
        self.make_shim()

    def test_a_rerun_with_no_growth_ships_nothing_and_grows_no_ledger(self):
        self._carry_fixture()
        first = self.tick()
        self.assertEqual(len(first['flags']), 1, first['argv'])
        lines = self.ledger_lines(ROOT_SID)
        self.assertRegex(lines[-1], rf'^HERMES:{ROOT_SID}:300:\d+\.\d+:unclassified-\d+$')
        with open(self.ledger_path, 'rb') as f:
            before = f.read()
        again = self.tick()
        self.assertEqual(again['argv'], [], 'a re-run must not re-report')
        with open(self.ledger_path, 'rb') as f:
            self.assertEqual(f.read(), before)

    def test_the_parent_link_resolves_to_exactly_the_carried_wire_id(self):
        self._carry_fixture()
        row = self.tick()['flags'][0]
        self.assertEqual(split_strategies.latest_transaction_id(self.ledger_path, ROOT_SID),
                         row['--transaction-id'])
        self.assertEqual(row['--transaction-id'], f'{ROOT_SID}-300')

    def test_a_third_growth_carries_again_at_the_new_total(self):
        self._carry_fixture()
        self.tick()
        self.grow(ROOT_SID, 300, 150)
        run = self.tick()
        self.assertEqual(len(run['flags']), 1, run['argv'])
        self.assertEqual(run['flags'][0]['--transaction-id'], f'{ROOT_SID}-450')
        self.assertEqual(run['flags'][0]['--task-type'], LABEL)

    def test_a_marker_that_lands_after_a_carry_ships_per_marker_without_collision(self):
        self._carry_fixture()
        carried = self.tick()['flags'][0]
        self.append_markers(ROOT_SID, _pair(ROOT_SID, G2_MUID, C2_MUID, 'research',
                                            MARKER_TS + 500, TRACE))
        self.grow(ROOT_SID, 300, 150)
        run = self.tick()
        self.assertEqual(len(run['flags']), 1, run['argv'])
        row = run['flags'][0]
        self.assertEqual(row['--task-type'], 'research')
        self.assertEqual(row['--transaction-id'], f'{ROOT_SID}-450-{C2_MUID}')
        self.assertNotEqual(row['--transaction-id'], carried['--transaction-id'])
        # The carried line is not a marker muid and did not make the pair ineligible.
        self.assertEqual(self.tick()['argv'], [])

    def test_a_failed_call_ledgers_nothing_and_retries_with_the_same_transaction_id(self):
        self._carry_fixture()
        shim = os.path.join(self.bin_dir, 'revenium')
        with open(shim) as f:
            body = f.read()
        body = body.replace('      completion)\n',
                            '      completion)\n        [[ -n "${REVENIUM_FAIL:-}" ]] && exit 7\n', 1)
        with open(shim, 'w') as f:
            f.write(body)
        os.chmod(shim, 0o755)
        before = self.ledger_lines()
        self.tick({'REVENIUM_FAIL': '1'})
        self.assertEqual(self.ledger_lines(), before, 'a failed call must ledger nothing')
        retry = self.tick()
        self.assertEqual(len(retry['flags']), 1, retry['argv'])
        self.assertEqual(retry['flags'][0]['--transaction-id'], f'{ROOT_SID}-300')

    def test_a_v1_only_ledger_carries_its_latest_old_label_then_ships_the_old_markers(self):
        """C-16. A session whose ledger holds only a 4-field v1 line: the
        `ts <= prior_ts` cutoff filters its old markers out, so n == 0 and HEAD
        shipped `unclassified`; it now carries the label that describes the
        session. That row's v2 `unclassified-` line makes prior_muids non-empty,
        so on the NEXT growth the cutoff no longer applies and the old markers
        ship per-marker -- exactly what HEAD does after its markerless row."""
        sid = ROOT_SID
        self.make_db([_session(sid, 200, 100, ended_at=OLD_START)])
        self.write_markers(sid, _pair(sid, G_MUID, C_MUID, LABEL, trace_id=TRACE))
        with open(self.ledger_path, 'a') as f:
            f.write(f'HERMES:{sid}:150:1715515500.000\n')
        self.make_shim()

        first = self.tick()
        self.assertEqual(len(first['flags']), 1, first['argv'])
        self.assertEqual(first['flags'][0]['--task-type'], LABEL)
        self.assertEqual(first['flags'][0]['--transaction-id'], f'{sid}-300')
        self.assertRegex(self.ledger_lines(sid)[-1], rf'^HERMES:{sid}:300:\d+\.\d+:unclassified-\d+$')

        self.grow(sid, 300, 150)
        second = self.tick()
        self.assertEqual(len(second['flags']), 1, second['argv'])
        self.assertEqual(second['flags'][0]['--transaction-id'], f'{sid}-450-{C_MUID}',
                         'the old markers ship per-marker on the next growth, as they do at HEAD')
        self.assertEqual(second['flags'][0]['--task-type'], LABEL)


if __name__ == '__main__':
    unittest.main()
