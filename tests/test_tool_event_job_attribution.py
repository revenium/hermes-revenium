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



# --------------------------------------------------------------------------
# Task 2: bounded late-marker holds
# --------------------------------------------------------------------------

class LateMarkerPolicyTests(unittest.TestCase):
    """A job record is written at the END of the turn whose tools it owns, so an
    event usually ships (3-122s after capture, measured) before its job exists.
    The policy: hold, bounded and logged once; never ledger a held row; always
    end with a basis that separates intentionally-unassigned work from a marker
    that never arrived."""

    def _live_root(self, h, started=None, activity=None):
        h.plugin_status()
        h.session(ROOT_SID, started=started if started is not None else h.now - 300,
                  ended=None, activity=activity if activity is not None else h.now - 10)

    def test_job_pending_holds_then_attributes_exactly_once(self):
        h = Harness(self)
        self._live_root(h)
        h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc1', h.now - 30)])
        for _ in range(2):
            h.run()
        self.assertEqual(h.argvs(), [])
        self.assertEqual(h.ledger(), [])
        log = h.log()
        self.assertEqual(log.count('Tool events held (job-pending)'), 1, log)
        self.assertIn('Held 1;', log)
        # The marker and the create land.
        h.write_markers(ROOT_SID, h.pair(ROOT_SID, h.now - 8) + [h.job(ROOT_SID, JOB, h.now - 5)])
        h.created(JOB)
        h.run()
        self.assertEqual([f.get('--workflow-id') for f in h.flags()], [JOB])
        h.run()
        self.assertEqual(len(h.argvs()), 1, 'run 4 ships nothing')
        self.assertEqual(len(h.ledger()), 1)

    def test_cancelled_latest_record_ships_after_job_without_a_hold(self):
        h = Harness(self)
        self._live_root(h)
        h.write_markers(ROOT_SID, [h.job(ROOT_SID, JOB, h.now - 100, 'CANCELLED')])
        h.created(JOB)
        h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc1', h.now - 50)])
        h.run()
        self.assertEqual([f.get('--workflow-id') for f in h.flags()], [None])
        self.assertIn('basis=after-job', h.log())
        self.assertIn('Held 0;', h.log())
        # A later re-judge for the same id does not reach back or extend ownership.
        h.write_markers(ROOT_SID, [h.job(ROOT_SID, JOB, h.now - 10, 'SUCCESS')])
        h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc2', h.now - 40)])
        h.run()
        self.assertEqual([f.get('--workflow-id') for f in h.flags()], [None, None])
        self.assertEqual(len(h.ledger()), 2)

    def test_success_latest_record_event_after_ships_at_once_unattributed(self):
        h = Harness(self)
        self._live_root(h)
        h.write_markers(ROOT_SID, [h.job(ROOT_SID, JOB, h.now - 100, 'SUCCESS')])
        h.created(JOB)
        h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc1', h.now - 20)])
        h.run()
        self.assertEqual([f.get('--workflow-id') for f in h.flags()], [None])
        self.assertIn('basis=after-job', h.log())

    def test_root_older_than_the_cap_ships_hold_expired_and_warns_once(self):
        h = Harness(self)
        self._live_root(h, started=h.now - 120, activity=h.now - 5)
        h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc1', h.now - 10)])
        h.run(REVENIUM_UNCLASSIFIED_MAX_HOLD_SECONDS=60)
        self.assertEqual([f.get('--workflow-id') for f in h.flags()], [None])
        self.assertIn('basis=hold-expired', h.log())
        h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc2', h.now - 9)])
        h.run(REVENIUM_UNCLASSIFIED_MAX_HOLD_SECONDS=60)
        self.assertEqual(h.log().count('WITHOUT --workflow-id (hold-expired)'), 1, h.log())

    def test_no_job_releases_at_once(self):
        scenarios = {
            'sentinel': lambda h: (h.plugin_status(), h.session(ROOT_SID, started=h.now - 300, activity=h.now - 5),
                                   h.ready(ROOT_SID)),
            'idle root': lambda h: (h.plugin_status(),
                                    h.session(ROOT_SID, started=h.now - 4000, activity=h.now - 3000)),
            'no plugin status': lambda h: h.session(ROOT_SID, started=h.now - 300, activity=h.now - 5),
            'unhealthy plugin': lambda h: (h.plugin_status(healthy=False),
                                           h.session(ROOT_SID, started=h.now - 300, activity=h.now - 5)),
        }
        for name, setup in scenarios.items():
            with self.subTest(name):
                h = Harness(self)
                setup(h)
                h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc1', h.now - 30)])
                h.run()
                self.assertEqual([f.get('--workflow-id') for f in h.flags()], [None])
                self.assertIn('basis=no-job', h.log())
                self.assertNotIn('Tool events held', h.log())

    def test_cap_zero_switches_every_hold_off(self):
        h = Harness(self)
        self._live_root(h)
        h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc1', h.now - 30)])
        h.run(REVENIUM_UNCLASSIFIED_MAX_HOLD_SECONDS=0)
        self.assertEqual(len(h.argvs()), 1)
        h2 = Harness(self)
        self._live_root(h2)
        h2.write_markers(ROOT_SID, [h2.job(ROOT_SID, JOB, h2.now - 5)])       # no create
        h2.write_spool(ROOT_SID, [h2.event(ROOT_SID, 'tc1', h2.now - 30)])
        h2.run(REVENIUM_UNCLASSIFIED_MAX_HOLD_SECONDS=0)
        self.assertEqual([f.get('--workflow-id') for f in h2.flags()], [None])
        self.assertNotIn('Tool events held', h2.log())

    def test_create_pending_holds_then_ships_once_created(self):
        h = Harness(self)
        self._live_root(h)
        h.write_markers(ROOT_SID, [h.job(ROOT_SID, JOB, h.now - 20)])
        h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc1', h.now - 30)])
        h.run()
        h.run()
        self.assertEqual(h.argvs(), [])
        self.assertEqual(h.log().count('Tool events held (create-pending)'), 1, h.log())
        h.created(JOB)
        h.run()
        self.assertEqual([f.get('--workflow-id') for f in h.flags()], [JOB])

    def test_create_missing_after_the_bound_ships_unattributed_and_warns_once(self):
        h = Harness(self)
        self._live_root(h)
        ts_job = h.now - 3000
        h.write_markers(ROOT_SID, [h.job(ROOT_SID, JOB, ts_job)])
        h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc1', ts_job - 5)])
        h.run()
        self.assertEqual([f.get('--workflow-id') for f in h.flags()], [None])
        self.assertIn('basis=create-missing', h.log())
        h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc2', ts_job - 4)])
        h.run()
        self.assertEqual(h.log().count('WITHOUT --workflow-id (create-missing)'), 1, h.log())
        self.assertEqual(len(h.argvs()), 2)

    def test_older_cli_ships_held_rows_unattributed_with_no_notice(self):
        h = Harness(self, workflow_capable=False)
        self._live_root(h)
        h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc1', h.now - 30)])
        h.run()
        self.assertEqual([f.get('--workflow-id') for f in h.flags()], [None])
        log = h.log()
        self.assertIn('basis=cli-unsupported', log)
        self.assertNotIn('Tool events held', log)
        self.assertNotIn('WITHOUT --workflow-id', log)

    def test_cli_failure_leaves_no_ledger_line_and_the_rerun_keeps_the_attribution(self):
        h = Harness(self)
        ts_job = h.now - 500
        h.session(ROOT_SID, started=h.now - 2000, ended=h.now - 100)
        h.write_markers(ROOT_SID, [h.job(ROOT_SID, JOB, ts_job)])
        h.created(JOB)
        h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc1', ts_job - 5)])
        open(h.fail_flag, 'w').close()
        h.run()
        self.assertEqual(h.ledger(), [], 'a failed call must never ledger')
        self.assertIn('Failed: sid=', h.log())
        os.remove(h.fail_flag)
        h.run()
        h.run()
        self.assertEqual([f.get('--workflow-id') for f in h.flags()], [JOB])
        self.assertEqual(len(h.ledger()), 1)


class SafetyTests(unittest.TestCase):

    def test_overlapping_run_defers_to_the_lock_holder(self):
        h = Harness(self)
        ts_job = h.now - 500
        h.session(ROOT_SID, started=h.now - 2000, ended=h.now - 100)
        h.write_markers(ROOT_SID, [h.job(ROOT_SID, JOB, ts_job)])
        h.created(JOB)
        h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc1', ts_job - 5)])
        with open(os.path.join(h.state, 'tool-events.lock'), 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            h.run()
            self.assertEqual(h.argvs(), [])
            self.assertIn('another run holds the lock', h.log())
        h.run()
        self.assertEqual(len(h.argvs()), 1, 'the next run, with the lock free, ships once')

    def test_locked_state_db_holds_db_busy_then_ships_with_the_root_trace(self):
        h = Harness(self)
        ts_job = h.now - 500
        child = '20261027_102629_864844'
        h.session(ROOT_SID, started=h.now - 2000, ended=h.now - 100)
        h.session(child, parent=ROOT_SID, started=h.now - 1900, ended=h.now - 120)
        h.write_markers(ROOT_SID, [h.job(ROOT_SID, JOB, ts_job)])
        h.created(JOB)
        h.write_spool(child, [h.event(child, 'tcc1', ts_job - 5)])
        blocker = sqlite3.connect(h.db, isolation_level=None)
        blocker.execute('BEGIN EXCLUSIVE')
        try:
            h.run()
            self.assertEqual(h.argvs(), [], 'a locked ancestry db must not ship under the wrong root')
            self.assertEqual(h.ledger(), [])
            self.assertEqual(h.log().count('Tool events held (db-busy)'), 1, h.log())
        finally:
            blocker.execute('ROLLBACK')
            blocker.close()
        h.run()
        flags = h.flags()
        self.assertEqual(len(flags), 1)
        self.assertEqual((flags[0]['--trace-id'], flags[0]['--workflow-id']), (ROOT_SID, JOB))

    def test_locked_state_db_past_the_cap_ships_with_the_sid_as_root(self):
        h = Harness(self)
        h.session('sess-old', started=h.now - 9000, ended=h.now - 8000)
        h.write_spool('sess-old', [h.event('sess-old', 'tc1', h.now - 8500)])
        blocker = sqlite3.connect(h.db, isolation_level=None)
        blocker.execute('BEGIN EXCLUSIVE')
        try:
            h.run()
        finally:
            blocker.execute('ROLLBACK')
            blocker.close()
        self.assertEqual([f['--trace-id'] for f in h.flags()], ['sess-old'])
        self.assertIn('basis=ancestry-unavailable', h.log())

    def test_missing_state_db_ships_with_the_sid_as_trace_and_no_hold(self):
        h = Harness(self)
        os.remove(h.db)
        h.write_spool('sess-a', [h.event('sess-a', 'tc1', h.now - 30)])
        h.run()
        self.assertEqual([f['--trace-id'] for f in h.flags()], ['sess-a'])
        self.assertNotIn('Tool events held', h.log())

    def test_unverified_sid_never_picks_a_job(self):
        for source in (None, 'recent-session', 'pseudo', 'bogus'):
            with self.subTest(source=source):
                h = Harness(self)
                ts_job = h.now - 500
                h.session(ROOT_SID, started=h.now - 2000, ended=h.now - 100)
                h.write_markers(ROOT_SID, [h.job(ROOT_SID, JOB, ts_job)])
                h.created(JOB)
                h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc1', ts_job - 5, source=source)])
                h.run()
                self.assertEqual([f.get('--workflow-id') for f in h.flags()], [None])
                self.assertIn('basis=sid-unverified', h.log())
                self.assertIn('Tool events unattributed (sid-unverified)', h.log())
                self.assertEqual(h.probes(), 0)

    def test_traversal_shaped_parent_is_never_used_as_a_path(self):
        h = Harness(self)
        ts_job = h.now - 500
        evil = '../x'
        h.session('child-sess', parent=evil, started=h.now - 1900, ended=h.now - 120)
        # A job file the traversal would reach: <markers>/../x.jsonl == <state>/x.jsonl
        with open(os.path.join(h.state, 'x.jsonl'), 'w') as fh:
            fh.write(json.dumps(h.job('x', JOB, ts_job)) + '\n')
        h.created(JOB)
        h.write_spool('child-sess', [h.event('child-sess', 'tc1', ts_job - 5)])
        h.run()
        self.assertEqual([f.get('--workflow-id') for f in h.flags()], [None])
        self.assertIn('basis=bad-sid', h.log())

    def test_events_ledgered_by_an_earlier_pass_are_never_reshipped(self):
        h = Harness(self)
        ts_job = h.now - 500
        h.session(ROOT_SID, started=h.now - 2000, ended=h.now - 100)
        h.write_markers(ROOT_SID, [h.job(ROOT_SID, JOB, ts_job)])
        h.created(JOB)
        h.write_spool(ROOT_SID, [h.event(ROOT_SID, 'tc1', ts_job - 5)])
        h.run()
        h.run()
        self.assertEqual(len(h.argvs()), 1)
        self.assertEqual(len(h.ledger()), 1)

    def test_common_sh_declares_the_lock_before_mkdir(self):
        text = (SCRIPTS_DIR / 'common.sh').read_text()
        decl = text.index('TOOL_EVENTS_LOCK_FILE=')
        self.assertLess(decl, text.index('mkdir -p "${STATE_DIR}"'))
        self.assertIn('tool-events.lock', text)


class HookProvenanceTests(unittest.TestCase):
    """post_tool_call.sh stamps where the session id came from: only a sid
    Hermes SUPPLIED (`payload`) may pick a job; a Tier-2/3 guess must not."""

    def _run_hook(self, payload, sessions=()):
        tmp = tempfile.mkdtemp(prefix='fib-hook-')
        self.addCleanup(shutil.rmtree, tmp, True)
        hh = os.path.join(tmp, 'hh')
        os.makedirs(os.path.join(hh, 'sessions'))
        for name in sessions:
            open(os.path.join(hh, 'sessions', name), 'w').close()
        env = {**os.environ, 'HOME': tmp, 'HERMES_HOME': hh,
               'REVENIUM_STATE_DIR': os.path.join(hh, 'state', 'revenium')}
        result = subprocess.run(['bash', str(SCRIPTS_DIR / 'post_tool_call.sh')], input=json.dumps(payload),
                                env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        spool = os.path.join(hh, 'state', 'revenium', 'tool-events')
        records = []
        for name in os.listdir(spool):
            with open(os.path.join(spool, name)) as fh:
                records += [json.loads(l) for l in fh if l.strip()]
        self.assertEqual(len(records), 1, records)
        return records[0]

    def test_payload_session_id_is_stamped_payload(self):
        rec = self._run_hook({'tool_name': 'terminal', 'session_id': 'abc-123', 'extra': {'tool_call_id': 'x'}})
        self.assertEqual((rec['sid'], rec['sid_source']), ('abc-123', 'payload'))

    def test_recent_session_guess_is_stamped_recent_session(self):
        rec = self._run_hook({'tool_name': 'terminal', 'session_id': '', 'extra': {'tool_call_id': 'x'}},
                             sessions=['session_20261027_000000_ab12cd.json'])
        self.assertEqual((rec['sid'], rec['sid_source']), ('20261027_000000_ab12cd', 'recent-session'))

    def test_pseudo_sid_is_stamped_pseudo(self):
        rec = self._run_hook({'tool_name': 'terminal', 'session_id': '', 'extra': {'tool_call_id': 'x'}})
        self.assertTrue(rec['sid'].startswith('pseudo-'))
        self.assertEqual(rec['sid_source'], 'pseudo')

    def test_traversal_session_id_falls_through_and_is_not_payload(self):
        rec = self._run_hook({'tool_name': 'terminal', 'session_id': '../../etc', 'extra': {'tool_call_id': 'x'}})
        self.assertNotEqual(rec['sid_source'], 'payload')


if __name__ == '__main__':
    unittest.main()
