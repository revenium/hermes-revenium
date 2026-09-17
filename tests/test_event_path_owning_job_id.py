"""The event path resolves owning_job_id by FILE POSITION, like the legacy one.

Why this exists. `revenium jobs roi <id>` returned `transactionCount: 0,
totalCost: 0` for essentially every fleet job, while the rows themselves were
metered fine — they just carried no `--agentic-job-id`. Measured on the fleet
2026-09-16, two jobs, both ROOT cron sessions:

    patch_sentry_watch_..._ed4f  (legacy-shipped)     transactionCount 2, cost 0.063108
    tableforone_bsky_..._62c2    (event-path only)    transactionCount 0, cost 0

A root session's transactions DO link — when `hermes-report.sh` ships them. It
runs a deferred `owning_job_id` pass; `api-event-report.sh` never received one,
and additionally dropped job markers at the loader (`kind is not None`), so it
was structurally incapable of producing a job id for a root session. 27 of 28
recent job-bearing sessions were event-path-only, which is why this mattered.

The rule is FILE POSITION, not timestamp, and that is load-bearing: session
ownership can flip between the two paths mid-session, so a timestamp rule here
would disagree with the legacy pass on the same marker file and split one
session's transactions across job ids. These tests pin the agreement, not just
the presence of a flag.
"""
import json
import os
import shlex
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests._compat_helpers import argv_to_flags, build_shim, run_script

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / 'skills' / 'revenium' / 'scripts'

_OLD_TS = 1715514000.0


def _write_jsonl(path, records):
    with open(path, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, separators=(',', ':')) + '\n')


def _seed_sessions_db(db_path, rows):
    """sessions table WITH parent_session_id, so get_root_session_id can
    resolve a root distinct from the child. Same shape as
    tests/test_phase29_agent_inheritance.py::_seed_sessions_db."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, model TEXT, source TEXT,
                input_tokens INTEGER, output_tokens INTEGER,
                cache_read_tokens INTEGER, cache_write_tokens INTEGER,
                reasoning_tokens INTEGER, estimated_cost_usd REAL,
                api_call_count INTEGER, started_at REAL, ended_at REAL,
                billing_provider TEXT, parent_session_id TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (sid, "claude-sonnet-4-6", "test", 100, 50, 0, 0, 0,
                 0.0, 1, _OLD_TS, _OLD_TS, "anthropic", parent)
                for sid, parent in rows
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _event_record(sid, arid, ts, ended_at, **overrides):
    rec = {
        'v': 1, 'sid': sid, 'api_request_id': arid,
        'ts': ts, 'ended_at': ended_at, 'duration_ms': 500,
        'platform': 'cli', 'model': 'claude-sonnet-4-6',
        'response_model': 'claude-sonnet-4-6', 'provider': 'anthropic',
        'base_url': 'https://api.anthropic.com', 'api_mode': 'anthropic_messages',
        'finish_reason': 'stop',
        'input_tokens': 100, 'output_tokens': 50,
        'cache_read_tokens': 0, 'cache_write_tokens': 0,
        'reasoning_tokens': 0, 'total_tokens': 150,
    }
    rec.update(overrides)
    return rec


def _muid(tag):
    base = f'{abs(hash(tag)):x}'
    return (base + '0' * 33)[:33]


def _task_marker(sid, task_type, ts, **extra):
    m = {
        'muid': _muid(f'{sid}{task_type}{ts}'), 'ts': ts, 'sid': sid,
        'task_type': task_type, 'operation_type': 'CHAT', 'trace_id': sid,
    }
    m.update(extra)
    return m


def _job_marker(sid, job_id, ts, status='SUCCESS'):
    return {
        'kind': 'job', 'ts': ts, 'sid': sid, 'agentic_job_id': job_id,
        'job_name': 'Monitor something', 'job_type': 'social_media_monitoring',
        'status': status,
    }


class EventPathOwningJobIdBase(unittest.TestCase):
    def _setup_tree(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-event-owning-job-')
        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        spool_dir = os.path.join(state_dir, 'api-events')
        markers_dir = os.path.join(state_dir, 'markers')
        ready_dir = os.path.join(markers_dir, '.ready')
        os.makedirs(spool_dir, mode=0o700)
        os.makedirs(markers_dir, mode=0o700)
        os.makedirs(ready_dir, mode=0o700)

        shim_home = os.path.join(tmpdir, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)
        build_shim(os.path.join(bin_dir, 'revenium'))

        return tmpdir, hermes_home, state_dir, spool_dir, markers_dir, ready_dir, shim_home

    def _run(self, hermes_home, state_dir, shim_home, meter_log, inv_log):
        env = {
            **os.environ,
            'HOME': shim_home,
            'HERMES_HOME': hermes_home,
            'REVENIUM_STATE_DIR': state_dir,
            'PATH': os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': inv_log,
            'METER_LOG': meter_log,
            'TZ': 'UTC',
            'REVENIUM_EVENT_METERING_MODE': 'live',
        }
        return run_script(SCRIPTS_DIR / 'api-event-report.sh', env, inv_log)

    def _completions(self, meter_log):
        invs = []
        if os.path.exists(meter_log):
            with open(meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        invs.append(shlex.split(line))
        return [a for a in invs if len(a) >= 2 and a[0] == 'meter' and a[1] == 'completion']

    def _run_case(self, sid, marker_records, events, sessions=None):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home = self._setup_tree()
        try:
            Path(ready_dir, sid).touch()
            _write_jsonl(os.path.join(markers_dir, f'{sid}.jsonl'), marker_records)
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), events)
            if sessions:
                _seed_sessions_db(os.path.join(hh, 'state.db'), sessions)

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)
            return [argv_to_flags(a) for a in self._completions(meter_log)], out
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class ForwardRuleTests(EventPathOwningJobIdBase):
    """Primary rule (D-08): a task marker is owned by the FIRST job marker
    BELOW it in file order. This is the ordinary arc shape, and the one the
    fleet's cron sessions produce."""

    def test_root_task_marker_binds_to_the_job_marker_written_after_it(self):
        sid = 'evt-root-forward'
        flags, out = self._run_case(
            sid,
            [
                _task_marker(sid, 'social_mention_watch', 1000000.0),
                _job_marker(sid, 'tableforone_bsky_monitor_62c2', 1000014.0),
            ],
            [_event_record(sid, f'{sid}:t1:api:1', 1000005.0, 1000005.5)],
        )
        self.assertEqual(len(flags), 1, f'expected 1 completion: {flags!r}\n{out}')
        self.assertEqual(
            flags[0].get('--agentic-job-id'), 'tableforone_bsky_monitor_62c2',
            'a ROOT session\'s event must carry the job id resolved from the job '
            'marker written AFTER its task marker -- without this the metered row '
            'never links and `jobs roi` reports transactionCount 0'
        )

    def test_the_14_second_ordering_gap_is_not_an_obstacle(self):
        """The job marker lands ~14s AFTER the task marker in wall-clock and
        after it in file order. Resolution happens at report time, so the id
        need not have existed when the task marker was written."""
        sid = 'evt-root-late-job'
        flags, out = self._run_case(
            sid,
            [
                _task_marker(sid, 'social_mention_watch', 1000000.0),
                _job_marker(sid, 'late_job_9f3a', 1000014.0),
            ],
            [_event_record(sid, f'{sid}:t1:api:1', 1000000.5, 1000001.0)],
        )
        self.assertEqual(len(flags), 1, out)
        self.assertEqual(flags[0].get('--agentic-job-id'), 'late_job_9f3a')


class NearestPrecedingFallbackTests(EventPathOwningJobIdBase):
    """TRACE-FIX 2026-06-25's fallback: the classifier writes at most ONE job
    marker per session, EARLY, so in long-lived sessions later task markers
    accumulate BELOW it. A forward-only rule strands them -- the defect that
    note records as "shipping ~95% of completions with no --agentic-job-id"."""

    def test_task_markers_below_the_only_job_marker_still_bind_to_it(self):
        sid = 'evt-root-trailing'
        flags, out = self._run_case(
            sid,
            [
                _task_marker(sid, 'first_turn', 1000000.0),
                _job_marker(sid, 'early_job_c4d1', 1000010.0),
                _task_marker(sid, 'second_turn', 1000100.0),
                _task_marker(sid, 'third_turn', 1000200.0),
            ],
            [
                _event_record(sid, f'{sid}:t1:api:1', 1000005.0, 1000005.5),
                _event_record(sid, f'{sid}:t2:api:2', 1000150.0, 1000150.5),
                _event_record(sid, f'{sid}:t3:api:3', 1000250.0, 1000250.5),
            ],
        )
        self.assertEqual(len(flags), 3, f'expected 3 completions: {flags!r}\n{out}')
        for f in flags:
            self.assertEqual(
                f.get('--agentic-job-id'), 'early_job_c4d1',
                'every task marker on the session binds to the single job '
                f'marker, including those below it in file order: {f!r}'
            )

    def test_the_rule_is_file_position_not_timestamp(self):
        """A job marker whose `ts` is older than the task marker's but which
        sits LATER in the file still owns it. Timestamp and file order
        disagree here on purpose: legacy resolves by position, and the two
        paths must agree or a session whose ownership flips mid-run splits
        its transactions across job ids."""
        sid = 'evt-root-position-wins'
        flags, out = self._run_case(
            sid,
            [
                _task_marker(sid, 'the_task', 1000500.0),
                # Written later in the file, but carries an EARLIER ts.
                _job_marker(sid, 'position_wins_7b2c', 1000100.0),
            ],
            [_event_record(sid, f'{sid}:t1:api:1', 1000600.0, 1000600.5)],
        )
        self.assertEqual(len(flags), 1, out)
        self.assertEqual(flags[0].get('--agentic-job-id'), 'position_wins_7b2c')


class SubagentUnchangedTests(EventPathOwningJobIdBase):
    """hermes-report.sh refuses to ship a SUBAGENT's own owning id: JOB-02
    suppresses the job create for subagents, so the id would orphan-reference
    a Revenium job row that does not exist. The event path must refuse
    identically."""

    def test_subagent_session_does_not_ship_a_resolved_owner(self):
        child, root = 'evt-subagent-child', 'evt-subagent-root'
        flags, out = self._run_case(
            child,
            [
                _task_marker(child, 'delegated_work', 1000000.0),
                _job_marker(child, 'must_not_ship_1a2b', 1000014.0),
            ],
            [_event_record(child, f'{child}:t1:api:1', 1000005.0, 1000005.5)],
            sessions=[(root, None), (child, root)],
        )
        self.assertEqual(len(flags), 1, out)
        self.assertNotIn(
            '--agentic-job-id', flags[0],
            'a subagent session must not ship a RESOLVED owner -- JOB-02 '
            'suppressed the create, so the row would reference a job that '
            f'does not exist: {flags[0]!r}'
        )
        # Proves the session really was treated as a subagent, so the
        # assertion above cannot pass for the wrong reason.
        self.assertEqual(flags[0].get('--squad-role'), 'subagent')

    def test_subagent_marker_carrying_its_own_job_id_is_unchanged(self):
        """A subagent marker's OWN agentic_job_id names the ROOT's job and has
        always shipped. The resolution pass must not disturb it."""
        child, root = 'evt-subagent-own-child', 'evt-subagent-own-root'
        flags, out = self._run_case(
            child,
            [_task_marker(child, 'delegated_work', 1000000.0,
                          agentic_job_id='roots_job_d4e5')],
            [_event_record(child, f'{child}:t1:api:1', 1000005.0, 1000005.5)],
            sessions=[(root, None), (child, root)],
        )
        self.assertEqual(len(flags), 1, out)
        self.assertEqual(flags[0].get('--agentic-job-id'), 'roots_job_d4e5')


class NoJobMarkerUnchangedTests(EventPathOwningJobIdBase):
    """Backward compatibility: a session with no job marker meters exactly as
    it did before this change."""

    def test_session_with_no_job_marker_omits_the_flag(self):
        sid = 'evt-root-no-job'
        flags, out = self._run_case(
            sid,
            [_task_marker(sid, 'plain_chat', 1000000.0)],
            [_event_record(sid, f'{sid}:t1:api:1', 1000005.0, 1000005.5)],
        )
        self.assertEqual(len(flags), 1, out)
        self.assertNotIn('--agentic-job-id', flags[0])
        # The join itself is untouched -- job markers never entered the
        # window-boundary list, so task_type still comes from the task marker.
        self.assertEqual(flags[0].get('--task-type'), 'plain_chat')

    def test_a_job_marker_does_not_become_a_join_window_boundary(self):
        """The regression this guards: putting job markers into
        `window_markers` would move task_type/operation_type attribution for
        every event on the session. The event below sits AFTER the job marker
        in both time and file order, and must still take the task marker's
        label."""
        sid = 'evt-root-window-intact'
        flags, out = self._run_case(
            sid,
            [
                _task_marker(sid, 'social_mention_watch', 1000000.0),
                _job_marker(sid, 'window_job_5c6d', 1000010.0),
            ],
            [_event_record(sid, f'{sid}:t1:api:1', 1000050.0, 1000050.5)],
        )
        self.assertEqual(len(flags), 1, out)
        self.assertEqual(
            flags[0].get('--task-type'), 'social_mention_watch',
            'a job marker must never act as a join-window boundary'
        )
        self.assertEqual(flags[0].get('--operation-type'), 'CHAT')
        self.assertEqual(flags[0].get('--agentic-job-id'), 'window_job_5c6d')


if __name__ == '__main__':
    unittest.main()
