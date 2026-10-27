"""quick-261027-fib: tool events carry `--workflow-id <owning job id>`.

Job `revenium_x_intelligence_scan_8e88` received 153 tool events with no job
association because tool-event-report.sh never sent `--workflow-id`, the field
Isotope's get-job-tool-costs.ts joins on. These tests pin the exporter side:

  * the pure selectors in split_strategies.py (arcs + first-after ownership);
  * the end-to-end argv, with the unchanged meter-tool-event.golden.json as the
    unattributed baseline and meter-tool-event-workflow.golden.json as the
    attributed shape;
  * the late-marker policy (bounded, once-logged holds) and the safety cases.

OWNERSHIP RULE (operator decision, 2026-10-27): FIRST RECORD ONLY. A job owns
the tool events captured at or before its FIRST job record; a later re-judge
record for the same id never extends ownership. On the reproduction root that
attributes 51 root + 73 subagent = 124 events, and leaves the 29 continuation
events and the 82 debugging events unattributed (basis after-job).

Every attributed fixture record carries "sid_source": "payload", the
provenance the post_tool_call.sh hook stamps on a session id Hermes supplied.
"""
import fcntl
import json
import math
import os
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
    assert_argv_matches_golden,
    build_shim,
    load_golden,
)

sys.path.insert(0, str(SCRIPTS_DIR))
import split_strategies as ss  # noqa: E402

REPORTER = SCRIPTS_DIR / 'tool-event-report.sh'
ROOT_SID = 'local-3786993359facf46d4d88db7ba4719163006f2b84c32c309d3515bf7bceb496f'
JOB = 'revenium_x_intelligence_scan_8e88'


# --------------------------------------------------------------------------
# Pure selectors
# --------------------------------------------------------------------------

def _job(job_id, ts, status='SUCCESS', **extra):
    rec = {'kind': 'job', 'ts': ts, 'sid': 'r', 'agentic_job_id': job_id,
           'job_name': 'n', 'job_type': 't', 'status': status}
    rec.update(extra)
    return rec


def _arcs_of(records, raw_lines=()):
    tmp = tempfile.mkdtemp(prefix='fib-arcs-')
    path = os.path.join(tmp, 'r.jsonl')
    with open(path, 'w') as fh:
        for rec in records:
            fh.write(json.dumps(rec) + '\n')
        for raw in raw_lines:
            fh.write(raw + '\n')
    try:
        return ss.tool_event_job_arcs(path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class SelectorTests(unittest.TestCase):

    def test_arcs_group_by_id_with_first_and_last(self):
        info = _arcs_of([
            {'kind': 'task', 'ts': 5, 'task_type': 'x'},
            _job('A', 100, 'CANCELLED'),
            _job('B', 300, 'SUCCESS'),
            _job('A', 400, 'SUCCESS'),
        ])
        self.assertTrue(info['ok'])
        self.assertFalse(info['unplaceable'])
        a, b = info['arcs']
        self.assertEqual((a['id'], a['first_ts'], a['last_ts'], a['status']), ('A', 100, 400, 'SUCCESS'))
        self.assertEqual((b['id'], b['first_ts'], b['last_ts'], b['status']), ('B', 300, 300, 'SUCCESS'))
        self.assertTrue(a['id_valid'] and b['id_valid'])

    def test_first_after_owns_events_up_to_the_first_record(self):
        info = _arcs_of([_job('A', 100)])
        self.assertEqual(ss.assign_tool_event_job(info, 40.0)[:2], ('A', 'first-after'))
        self.assertEqual(ss.assign_tool_event_job(info, 100.0)[:2], ('A', 'first-after'))

    def test_event_after_first_record_is_after_job_never_owned(self):
        # First record only: an event between a job's first record (100) and
        # its later re-judge record (400) is NOT owned by it.
        info = _arcs_of([_job('A', 100, 'CANCELLED'), _job('A', 400, 'SUCCESS')])
        job_id, basis, arc = ss.assign_tool_event_job(info, 250.0)
        self.assertIsNone(job_id)
        self.assertEqual(basis, 'after-job')
        self.assertEqual(arc['id'], 'A')
        self.assertEqual(ss.assign_tool_event_job(info, 900.0)[:2], (None, 'after-job'))

    def test_second_arc_owns_only_events_before_its_own_first_record(self):
        info = _arcs_of([_job('A', 100), _job('B', 300)])
        self.assertEqual(ss.assign_tool_event_job(info, 50.0)[:2], ('A', 'first-after'))
        # Between A's record and B's: B owns it (first-after), A's re-judge
        # window does not exist because A has a single record.
        self.assertEqual(ss.assign_tool_event_job(info, 200.0)[:2], ('B', 'first-after'))
        self.assertEqual(ss.assign_tool_event_job(info, 301.0)[:2], (None, 'after-job'))

    def test_aba_rejudge_never_reclaims_and_overlap_is_ambiguous(self):
        # A (100, re-judged at 400), B opened at 300. An event at 250 falls
        # inside A's own later record span AND before B's first record.
        info = _arcs_of([_job('A', 100, 'CANCELLED'), _job('B', 300), _job('A', 400, 'SUCCESS')])
        self.assertEqual(ss.assign_tool_event_job(info, 250.0)[:2], (None, 'ambiguous-arcs'))
        # After B opened, A's re-judge (400) never reclaims: after-job.
        self.assertEqual(ss.assign_tool_event_job(info, 350.0)[:2], (None, 'after-job'))
        self.assertEqual(ss.assign_tool_event_job(info, 450.0)[:2], (None, 'after-job'))

    def test_halt_job_is_never_an_owner_or_a_boundary(self):
        info = _arcs_of([_job('guardrail-halt-rule1', 50, 'CANCELLED'), _job('A', 100)])
        self.assertEqual([a['id'] for a in info['arcs']], ['A'])
        self.assertEqual(ss.assign_tool_event_job(info, 60.0)[:2], ('A', 'first-after'))
        only_halt = _arcs_of([_job('guardrail-halt-rule1', 50, 'CANCELLED')])
        self.assertEqual(ss.assign_tool_event_job(only_halt, 10.0)[:2], (None, 'no-job'))

    def test_invalid_job_id_is_refused_not_rewritten(self):
        for bad in ('has space', 'has:colon', '../etc', '-leading', 'a' * 129, 'pipe|id'):
            info = _arcs_of([_job(bad, 100)])
            arc = info['arcs'][0]
            self.assertEqual(arc['id'], bad, 'the id is never rewritten')
            self.assertFalse(arc['id_valid'], bad)
            job_id, basis, owner = ss.assign_tool_event_job(info, 50.0)
            self.assertEqual((job_id, basis), (None, 'invalid-job-id'), bad)
            self.assertEqual(owner['id'], bad)

    def test_invalid_owner_never_shifts_to_a_neighbour(self):
        info = _arcs_of([_job('bad id', 100), _job('GOOD', 300)])
        self.assertEqual(ss.assign_tool_event_job(info, 50.0)[:2], (None, 'invalid-job-id'))
        self.assertEqual(ss.assign_tool_event_job(info, 200.0)[:2], ('GOOD', 'first-after'))

    def test_bad_event_ts(self):
        info = _arcs_of([_job('A', 100)])
        for bad in (0, -5, 0.0, float('nan'), float('inf'), True, 'x', None):
            self.assertEqual(ss.assign_tool_event_job(info, bad)[:2], (None, 'bad-ts'), repr(bad))

    def test_unplaceable_record(self):
        for bad_ts in (0, -1, 'soon', None, True):
            info = _arcs_of([_job('A', bad_ts)])
            self.assertTrue(info['ok'])
            self.assertTrue(info['unplaceable'], repr(bad_ts))
            self.assertEqual(ss.assign_tool_event_job(info, 50.0)[:2], (None, 'unplaceable-job'))
        nan_info = _arcs_of([], raw_lines=[
            '{"kind":"job","ts":NaN,"agentic_job_id":"A","job_type":"t","status":"SUCCESS"}'])
        self.assertTrue(nan_info['unplaceable'])

    def test_missing_file_means_no_job(self):
        info = ss.tool_event_job_arcs('/nonexistent/dir/r.jsonl')
        self.assertEqual(info, {'ok': True, 'unplaceable': False, 'arcs': []})
        self.assertEqual(ss.assign_tool_event_job(info, 50.0)[:2], (None, 'no-job'))

    def test_directory_at_path_means_markers_unreadable(self):
        tmp = tempfile.mkdtemp(prefix='fib-dir-')
        try:
            info = ss.tool_event_job_arcs(tmp)
            self.assertFalse(info['ok'])
            self.assertEqual(ss.assign_tool_event_job(info, 50.0)[:2], (None, 'markers-unreadable'))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_malformed_and_unqualified_lines_are_skipped(self):
        info = _arcs_of(
            [
                {'kind': 'job', 'ts': 90, 'agentic_job_id': 'NOSTATUS', 'job_type': 't'},
                {'kind': 'job', 'ts': 91, 'agentic_job_id': '', 'job_type': 't', 'status': 'SUCCESS'},
                {'kind': 'job', 'ts': 92, 'agentic_job_id': 7, 'job_type': 't', 'status': 'SUCCESS'},
                {'kind': 'chat', 'ts': 93, 'agentic_job_id': 'X', 'job_type': 't', 'status': 'SUCCESS'},
                _job('A', 100),
            ],
            raw_lines=['{not json', '[1,2]', '', '{"kind":"job","ts":1,"agentic_job_id":"L","job_type":"t",'
                       '"status":"S","pad":"' + 'x' * 5000 + '"}'],
        )
        self.assertEqual([a['id'] for a in info['arcs']], ['A'])
        self.assertFalse(info['unplaceable'])

    def test_selectors_never_raise_on_garbage(self):
        for junk in (None, 5, 'x', [], {'ok': True, 'arcs': 'nope'}):
            result = ss.assign_tool_event_job(junk, 50.0)
            self.assertIsNone(result[0])


# --------------------------------------------------------------------------
# End-to-end harness
# --------------------------------------------------------------------------

class Harness:
    """An isolated HERMES_HOME with its own state.db, markers, spool, jobs
    ledger and a `revenium` PATH shim that records every tool-event argv."""

    def __init__(self, test, workflow_capable=True):
        self.test = test
        self.tmp = tempfile.mkdtemp(prefix='fib-e2e-')
        test.addCleanup(shutil.rmtree, self.tmp, True)
        self.hh = os.path.join(self.tmp, 'hh')
        self.state = os.path.join(self.hh, 'state', 'revenium')
        self.markers = os.path.join(self.state, 'markers')
        self.spool = os.path.join(self.state, 'tool-events')
        self.db = os.path.join(self.hh, 'state.db')
        self.home = os.path.join(self.tmp, 'home')
        self.bin = os.path.join(self.home, '.local', 'bin')
        self.tool_log = os.path.join(self.tmp, 'tool.log')
        self.probe_log = os.path.join(self.tmp, 'probe.log')
        self.fail_flag = os.path.join(self.tmp, 'fail.flag')
        for d in (self.hh, self.markers, self.spool, self.bin):
            os.makedirs(d, exist_ok=True)
        self.jobs_ledger = os.path.join(self.state, 'revenium-jobs.ledger')
        self.tool_ledger = os.path.join(self.state, 'revenium-tool-events.ledger')
        self.log_path = os.path.join(self.state, 'revenium-metering.log')
        self.now = time.time()
        conn = sqlite3.connect(self.db)
        conn.execute('CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT, '
                     'profile_name TEXT, started_at REAL, ended_at REAL, last_activity_at REAL)')
        conn.commit()
        conn.close()
        build_shim(os.path.join(self.bin, 'revenium'), workflow_capable=workflow_capable)
        os.rename(os.path.join(self.bin, 'revenium'), os.path.join(self.bin, 'revenium-real'))
        wrapper = (
            '#!/usr/bin/env bash\n'
            'if [[ "$1" == meter && "$2" == tool-event && "$3" == --help ]]; then\n'
            '  echo probe >> "$PROBE_LOG"\n'
            'fi\n'
            'if [[ "$1" == meter && "$2" == tool-event && "$3" != --help && -e "$FAIL_FLAG" ]]; then\n'
            '  exit 1\n'
            'fi\n'
            'exec "$(dirname "$0")/revenium-real" "$@"\n'
        )
        with open(os.path.join(self.bin, 'revenium'), 'w') as fh:
            fh.write(wrapper)
        os.chmod(os.path.join(self.bin, 'revenium'), 0o755)

    # -- fixtures ----------------------------------------------------------
    def session(self, sid, parent=None, profile=None, started=None, ended=None, activity=None):
        conn = sqlite3.connect(self.db)
        conn.execute('INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?)',
                     (sid, parent, profile, started if started is not None else self.now - 4000,
                      ended, activity))
        conn.commit()
        conn.close()

    def write_markers(self, sid, records, markers_dir=None):
        d = markers_dir or self.markers
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, sid + '.jsonl'), 'a') as fh:
            for rec in records:
                fh.write(json.dumps(rec) + '\n')

    @staticmethod
    def pair(sid, ts, task='x_task'):
        base = {'sid': sid, 'ts': ts, 'task_type': task, 'trace_id': sid}
        return [dict(base, muid='g%s' % ts, operation_type='GUARDRAIL'),
                dict(base, muid='c%s' % ts, operation_type='CHAT')]

    @staticmethod
    def job(sid, job_id, ts, status='SUCCESS'):
        return {'kind': 'job', 'ts': ts, 'sid': sid, 'agentic_job_id': job_id,
                'job_name': 'Scan', 'job_type': 'research', 'status': status}

    @staticmethod
    def event(sid, tcid, ts, tool='terminal', source='payload', **extra):
        rec = {'sid': sid, 'ts': ts, 'tool': tool, 'tool_call_id': tcid,
               'duration_ms': 10, 'success': True, 'error': None}
        if source is not None:
            rec['sid_source'] = source
        rec.update(extra)
        return rec

    def write_spool(self, sid, events):
        with open(os.path.join(self.spool, sid + '.jsonl'), 'a') as fh:
            for ev in events:
                fh.write(json.dumps(ev) + '\n')

    def created(self, *job_ids):
        with open(self.jobs_ledger, 'a') as fh:
            for job_id in job_ids:
                fh.write('JOB:%s:created:%.3f\n' % (job_id, self.now - 100))

    def plugin_status(self, healthy=True, registered=True):
        with open(os.path.join(self.state, 'plugin-status.json'), 'w') as fh:
            json.dump({'healthy': healthy, 'registered': registered}, fh)

    def ready(self, sid):
        d = os.path.join(self.markers, '.ready')
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, sid), 'w').close()

    # -- run ---------------------------------------------------------------
    def run(self, shell='bash', **env_extra):
        env = {
            **os.environ,
            'HOME': self.home,
            'HERMES_HOME': self.hh,
            'REVENIUM_STATE_DIR': self.state,
            'PATH': self.bin + os.pathsep + os.environ.get('PATH', ''),
            'TOOL_LOG': self.tool_log,
            'PROBE_LOG': self.probe_log,
            'FAIL_FLAG': self.fail_flag,
            'TZ': 'UTC',
        }
        for key in ('REVENIUM_CRON_SETTLE_SECONDS', 'REVENIUM_UNCLASSIFIED_MAX_HOLD_SECONDS',
                    'REVENIUM_JOBS_STALE_SECONDS', 'REVENIUM_ORGANIZATION_NAME'):
            env.pop(key, None)
        env.update({k: str(v) for k, v in env_extra.items()})
        result = subprocess.run([shell, str(REPORTER)], env=env, capture_output=True,
                                text=True, timeout=240)
        self.test.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def argvs(self):
        if not os.path.exists(self.tool_log):
            return []
        with open(self.tool_log) as fh:
            return [shlex.split(l) for l in fh.read().splitlines() if l.strip()]

    def flags(self):
        return [argv_to_flags(a) for a in self.argvs()]

    def log(self):
        if not os.path.exists(self.log_path):
            return ''
        with open(self.log_path) as fh:
            return fh.read()

    def ledger(self):
        if not os.path.exists(self.tool_ledger):
            return []
        with open(self.tool_ledger) as fh:
            return [l.strip() for l in fh if l.strip()]

    def probes(self):
        if not os.path.exists(self.probe_log):
            return 0
        with open(self.probe_log) as fh:
            return len([l for l in fh if l.strip()])


class RootEventTests(unittest.TestCase):

    def _root_with_job(self, h, ts_job=None):
        ts_job = ts_job or h.now - 500
        h.session(ROOT_SID, started=h.now - 2000, ended=h.now - 100)
        h.write_markers(ROOT_SID, h.pair(ROOT_SID, ts_job - 3) + [h.job(ROOT_SID, JOB, ts_job)])
        h.created(JOB)
        return ts_job

    def test_root_event_ships_workflow_id_and_root_trace(self):
        h = Harness(self)
        ts_job = self._root_with_job(h)
        h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc1', ts_job - 20, tool='compat-tool', duration_ms=42)])
        result = h.run()
        flags = h.flags()
        self.assertEqual(len(flags), 1, result.stdout + result.stderr + h.log())
        golden = load_golden('meter-tool-event-workflow.golden.json')
        golden = json.loads(json.dumps(golden))
        golden['exact_match_fields']['--trace-id'] = ROOT_SID
        golden['exact_match_fields']['--workflow-id'] = JOB
        assert_argv_matches_golden(self, h.argvs()[0], golden)
        self.assertEqual(
            sorted(k for k in flags[0] if k.startswith('--')),
            sorted(['--tool-id', '--duration-ms', '--timestamp', '--trace-id',
                    '--workflow-id', '--success', '--quiet']))
        self.assertIn('job=%s basis=first-after' % JOB, h.log())
        self.assertEqual(h.ledger()[0].split(':')[:3], ['TOOL', ROOT_SID, 'tc1'])

    def test_golden_file_matches_its_declared_shape(self):
        golden = load_golden('meter-tool-event-workflow.golden.json')
        self.assertEqual(golden['exact_match_fields']['--workflow-id'], 'compat_job_001')
        self.assertIn('--transaction-id', golden['forbidden_fields'])
        self.assertIn('--timestamp', golden['pattern_fields'])

    def test_subagent_event_inherits_root_job_and_trace(self):
        h = Harness(self)
        ts_job = self._root_with_job(h)
        child = '20261027_102629_864844'
        h.session(child, parent=ROOT_SID, started=h.now - 1900, ended=h.now - 120)
        # The subagent's own marker file holds a DECOY job: it must never be read.
        h.write_markers(child, [h.job(child, 'DECOY_JOB', ts_job - 1)])
        h.created('DECOY_JOB')
        h.write_spool(child, [h.event(child, 'tcc1', ts_job - 30)])
        h.run()
        flags = h.flags()
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]['--trace-id'], ROOT_SID)
        self.assertEqual(flags[0]['--workflow-id'], JOB)
        self.assertEqual(h.ledger()[0].split(':')[:3], ['TOOL', child, 'tcc1'])

    def test_reproduction_shaped_root_attributes_scan_not_debugging(self):
        h = Harness(self)
        t_job = h.now - 3000
        t_rejudge = t_job + 400
        h.session(ROOT_SID, started=t_job - 300, ended=h.now - 600)
        children = ['20261027_102629_864844', '20261027_102629_ab680d', '20261027_102629_ff3710']
        for c in children:
            h.session(c, parent=ROOT_SID, started=t_job - 250, ended=t_job - 5)
        h.write_markers(ROOT_SID,
                        h.pair(ROOT_SID, t_job - 3, 'x_radar_reply_discovery')
                        + [h.job(ROOT_SID, JOB, t_job, 'CANCELLED'),
                           h.job(ROOT_SID, JOB, t_rejudge, 'SUCCESS')]
                        + h.pair(ROOT_SID, t_rejudge + 600, 'debugging')
                        + h.pair(ROOT_SID, t_rejudge + 1300, 'debugging'))
        h.created(JOB)
        root_events = [h.event(ROOT_SID, 'r%03d' % i, t_job - 2 * i, tool='scan_root') for i in range(51)]
        root_events[0]['ts'] = t_job  # exactly at the first record: still owned
        root_events += [h.event(ROOT_SID, 'k%03d' % i, t_job + 5 + i * 10, tool='continuation')
                        for i in range(29)]
        root_events += [h.event(ROOT_SID, 'd%03d' % i, t_rejudge + 500 + i * 10, tool='debugging')
                        for i in range(82)]
        h.write_spool(ROOT_SID, root_events)
        sizes = [25, 24, 24]
        for c, n in zip(children, sizes):
            h.write_spool(c, [h.event(c, 'c%03d' % i, t_job - 10 - i, tool='scan_child') for i in range(n)])
        h.run()
        flags = h.flags()
        self.assertEqual(len(flags), 235)  # 153 scan events + 82 debugging
        by_tool = {}
        for f in flags:
            self.assertEqual(f['--trace-id'], ROOT_SID)
            by_tool.setdefault(f['--tool-id'], []).append(f.get('--workflow-id'))
        self.assertEqual(by_tool['scan_root'], [JOB] * 51)
        self.assertEqual(by_tool['scan_child'], [JOB] * 73)
        self.assertEqual(by_tool['continuation'], [None] * 29)
        self.assertEqual(by_tool['debugging'], [None] * 82)
        log = h.log()
        self.assertIn('attributed 124, unassigned 111', log)
        self.assertEqual(log.count('basis=after-job'), 111)
        self.assertIn('roots resolved 1', log)


class AttributionGateTests(unittest.TestCase):

    def test_job_without_ledgered_create_never_appears_in_argv(self):
        h = Harness(self)
        ts_job = h.now - 3000          # old enough that no hold applies
        h.session(ROOT_SID, started=h.now - 4000, ended=h.now - 100)
        h.write_markers(ROOT_SID, [h.job(ROOT_SID, JOB, ts_job)])
        h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc1', ts_job - 5)])
        h.run()
        for argv in h.argvs():
            self.assertNotIn('--workflow-id', argv)
            self.assertNotIn(JOB, argv)

    def test_no_markers_capable_cli_matches_unattributed_golden_and_skips_the_probe(self):
        h = Harness(self, workflow_capable=True)
        h.session('compat-sid-001', started=h.now - 4000, ended=h.now - 100)
        h.write_spool('compat-sid-001', [h.event('compat-sid-001', 'compat-tool-001', 1715515000.0,
                                                 tool='compat-tool', duration_ms=42)])
        h.run()
        self.assertEqual(len(h.argvs()), 1)
        assert_argv_matches_golden(self, h.argvs()[0], load_golden('meter-tool-event.golden.json'))
        self.assertNotIn('--workflow-id', h.argvs()[0])
        self.assertEqual(h.probes(), 0, 'the --workflow-id probe is paid only when a row has an owner')

    def test_known_job_with_older_cli_ships_at_once_without_workflow_id(self):
        h = Harness(self, workflow_capable=False)
        ts_job = h.now - 500
        h.session(ROOT_SID, started=h.now - 2000, ended=h.now - 100)
        h.write_markers(ROOT_SID, [h.job(ROOT_SID, JOB, ts_job)])
        h.created(JOB)
        h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc1', ts_job - 5, tool='compat-tool', duration_ms=42)])
        h.run()
        self.assertEqual(len(h.argvs()), 1)
        golden = json.loads(json.dumps(load_golden('meter-tool-event.golden.json')))
        golden['exact_match_fields']['--trace-id'] = ROOT_SID
        assert_argv_matches_golden(self, h.argvs()[0], golden)
        self.assertNotIn('--workflow-id', h.argvs()[0])
        self.assertEqual(h.probes(), 1, 'probed once, lazily')
        self.assertIn('basis=cli-unsupported', h.log())

    def test_separate_profiles_use_the_owning_profiles_markers(self):
        h = Harness(self)
        ts_job = h.now - 500
        p2_markers = os.path.join(h.hh, 'profiles', 'p2', 'state', 'revenium', 'markers')
        os.makedirs(p2_markers)
        h.session(ROOT_SID, profile='p2', started=h.now - 2000, ended=h.now - 100)
        h.write_markers(ROOT_SID, [h.job(ROOT_SID, 'P2_JOB', ts_job)], markers_dir=p2_markers)
        h.write_markers(ROOT_SID, [h.job(ROOT_SID, 'DECOY_JOB', ts_job)])     # process-level decoy
        other = 'unrelated-root-001'
        h.session(other, started=h.now - 2000, ended=h.now - 100)
        h.write_markers(other, [h.job(other, 'OTHER_JOB', ts_job)])
        h.created('P2_JOB', 'DECOY_JOB', 'OTHER_JOB')
        h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc1', ts_job - 5)])
        h.write_spool(other, [h.event(other, 'tc2', ts_job - 5)])
        h.run()
        got = {f['--trace-id']: f.get('--workflow-id') for f in h.flags()}
        self.assertEqual(got, {ROOT_SID: 'P2_JOB', other: 'OTHER_JOB'})

    @unittest.skipUnless(os.path.exists('/bin/bash'), '/bin/bash not present')
    def test_root_known_job_under_system_bash(self):
        h = Harness(self)
        ts_job = h.now - 500
        h.session(ROOT_SID, started=h.now - 2000, ended=h.now - 100)
        h.write_markers(ROOT_SID, [h.job(ROOT_SID, JOB, ts_job)])
        h.created(JOB)
        h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc1', ts_job - 5)])
        h.run(shell='/bin/bash')
        self.assertEqual([f.get('--workflow-id') for f in h.flags()], [JOB])


if __name__ == '__main__':
    unittest.main()
