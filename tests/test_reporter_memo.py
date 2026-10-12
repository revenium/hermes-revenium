"""Cross-tick no-op memo in hermes-report.sh (REPORTER_MEMO_FILE).

Every tick visits every session with tokens. On a desktop host with ~1,200
historical sessions the visit of a long-finished session cost 5-8 python3
spawns just to reach the ledger skip, so hermes-report.sh ran ~6 minutes per
tick (measured: 200s for one pass on a copy of that host's state, 7s with the
memo warm). These tests pin that the memo skips only what a full pass would
also have skipped:

- a second tick over an unchanged session skips the per-session spawns;
- a job marker appended to a token-stable session still reaches jobs create
  (the WR-02 property tests/test_reporter_spawn_guards.py guards -- the memo
  keys on the marker file, not on the token total);
- token growth still meters;
- an outcome that is still pending is never memoized, so it is re-queued
  every tick until it lands;
- replacing or truncating the ledger drops the memo;
- REVENIUM_REPORTER_MEMO=disabled writes no memo at all.
"""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests.test_reporter_spawn_guards import (
    _build_spawn_fixture,
    _run_reporter,
    _seed_ledger_token_stable,
    _spawn_count,
)


def _memo_sids(state_dir):
    p = os.path.join(state_dir, 'reporter-memo.jsonl')
    if not os.path.exists(p):
        return None
    lines = Path(p).read_text().splitlines()
    return [json.loads(l)['sid'] for l in lines[1:] if l.strip()]


def _tick(scripts_dir, env, spawn_log):
    open(spawn_log, 'w').close()
    r = _run_reporter(scripts_dir, env)
    return r, _spawn_count(spawn_log)


class ReporterMemoTests(unittest.TestCase):

    def _fixture(self, tmp, sid='sess-memo', marker_mode='absent', **kw):
        fx = _build_spawn_fixture(tmp, sid=sid, marker_mode=marker_mode, **kw)
        scripts_dir, state_dir, log_file, ledger_file, jobs_ledger_file, \
            invocations_log, spawn_log, env = fx
        _seed_ledger_token_stable(ledger_file, sid)
        return fx

    def test_second_tick_over_an_unchanged_session_skips_its_spawns(self):
        with tempfile.TemporaryDirectory(prefix='gsd-memo-hit-') as tmp:
            (scripts_dir, state_dir, log_file, ledger_file, jobs_ledger_file,
             invocations_log, spawn_log, env) = self._fixture(tmp)
            r1, spawns_1 = _tick(scripts_dir, env, spawn_log)
            self.assertEqual(0, r1.returncode, r1.stderr)
            self.assertEqual(['sess-memo'], _memo_sids(state_dir),
                             'a token-stable no-op session must be recorded')
            r2, spawns_2 = _tick(scripts_dir, env, spawn_log)
            self.assertEqual(0, r2.returncode, r2.stderr)
            self.assertLess(
                spawns_2, spawns_1,
                f'the warm tick must skip the per-session spawns '
                f'(cold={spawns_1}, warm={spawns_2})')
            self.assertIn('memo: skipped 1 unchanged session(s)',
                          Path(log_file).read_text())
            self.assertEqual('', Path(invocations_log).read_text().strip(),
                             'neither tick may re-meter a token-stable session')
            self.assertEqual(['sess-memo'], _memo_sids(state_dir),
                             'a hit must carry its record over')

    def test_job_marker_appended_after_memo_still_creates_the_job(self):
        with tempfile.TemporaryDirectory(prefix='gsd-memo-wr02-') as tmp:
            (scripts_dir, state_dir, log_file, ledger_file, jobs_ledger_file,
             invocations_log, spawn_log, env) = self._fixture(tmp)
            _tick(scripts_dir, env, spawn_log)
            self.assertEqual(['sess-memo'], _memo_sids(state_dir))
            with open(os.path.join(state_dir, 'markers', 'sess-memo.jsonl'), 'w') as f:
                f.write(json.dumps({
                    'kind': 'job', 'agentic_job_id': 'job-late',
                    'job_type': 'deploy_pipeline', 'job_name': 'deploy',
                    'status': 'SUCCESS',
                }) + '\n')
            r, _ = _tick(scripts_dir, env, spawn_log)
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertIn('JOB:job-late:created:', Path(jobs_ledger_file).read_text(),
                          'a marker change must invalidate the memo (WR-02)')

    def test_token_growth_still_meters(self):
        with tempfile.TemporaryDirectory(prefix='gsd-memo-growth-') as tmp:
            (scripts_dir, state_dir, log_file, ledger_file, jobs_ledger_file,
             invocations_log, spawn_log, env) = self._fixture(tmp)
            _tick(scripts_dir, env, spawn_log)
            conn = sqlite3.connect(os.path.join(tmp, 'state.db'))
            conn.execute("UPDATE sessions SET output_tokens = 90 WHERE id = 'sess-memo'")
            conn.commit()
            conn.close()
            r, _ = _tick(scripts_dir, env, spawn_log)
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertIn('HERMES:sess-memo:190:', Path(ledger_file).read_text())
            self.assertNotEqual('', Path(invocations_log).read_text().strip())

    def test_pending_outcome_is_never_memoized(self):
        with tempfile.TemporaryDirectory(prefix='gsd-memo-pending-') as tmp:
            (scripts_dir, state_dir, log_file, ledger_file, jobs_ledger_file,
             invocations_log, spawn_log, env) = self._fixture(tmp)
            with open(os.path.join(state_dir, 'markers', 'sess-memo.jsonl'), 'w') as f:
                f.write(json.dumps({
                    'kind': 'job', 'agentic_job_id': 'job-open',
                    'job_type': 'research', 'job_name': 'still running',
                    'status': 'CANCELLED', 'ts': 1.0,
                }) + '\n')
            conn = sqlite3.connect(os.path.join(tmp, 'state.db'))
            conn.execute("UPDATE sessions SET ended_at = NULL WHERE id = 'sess-memo'")
            conn.commit()
            conn.close()
            for _ in range(2):
                r, _ = _tick(scripts_dir, env, spawn_log)
                self.assertEqual(0, r.returncode, r.stderr)
                self.assertNotIn('sess-memo', _memo_sids(state_dir) or [],
                                 'a held outcome must be re-queued every tick')
            jobs = Path(jobs_ledger_file).read_text()
            self.assertIn('JOB:job-open:created:', jobs)
            self.assertNotIn('JOB:job-open:outcome:', jobs)
            # Lift the hold without touching the session row or its files: had
            # the session been memoized, nothing would re-queue the outcome
            # and it would never be reported.
            r, _ = _tick(scripts_dir, {**env, 'REVENIUM_OPEN_SESSION_MAX_IDLE_SECONDS': '0'},
                         spawn_log)
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertIn('JOB:job-open:outcome:', Path(jobs_ledger_file).read_text(),
                          'a pending outcome must be re-queued on every tick')

    def test_replaced_ledger_drops_the_memo(self):
        with tempfile.TemporaryDirectory(prefix='gsd-memo-ledger-') as tmp:
            (scripts_dir, state_dir, log_file, ledger_file, jobs_ledger_file,
             invocations_log, spawn_log, env) = self._fixture(tmp)
            _tick(scripts_dir, env, spawn_log)
            content = Path(ledger_file).read_text()
            os.remove(ledger_file)
            Path(ledger_file).write_text(content)
            open(log_file, 'w').close()
            r, _ = _tick(scripts_dir, env, spawn_log)
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertNotIn('memo: skipped', Path(log_file).read_text(),
                             'a new ledger inode must invalidate every record')

    def test_disabled_switch_writes_no_memo(self):
        with tempfile.TemporaryDirectory(prefix='gsd-memo-off-') as tmp:
            (scripts_dir, state_dir, log_file, ledger_file, jobs_ledger_file,
             invocations_log, spawn_log, env) = self._fixture(tmp)
            env = {**env, 'REVENIUM_REPORTER_MEMO': 'disabled'}
            for _ in range(2):
                r, _ = _tick(scripts_dir, env, spawn_log)
                self.assertEqual(0, r.returncode, r.stderr)
            self.assertIsNone(_memo_sids(state_dir))
            self.assertNotIn('memo:', Path(log_file).read_text())


if __name__ == '__main__':
    unittest.main()
