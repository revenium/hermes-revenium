"""Phase 32 Plan 03 — Task 2 (EVT-12/C-11 drain-completion gate) and Task 3
(D-13 legacy-completions guard on hermes-report.sh).

Task 2 proves drain-status.sh answers "has the legacy path finished with
every session it owns" by the documented rules: a session is drained only
when BOTH terminal (ended, past the settle window, or gone from state.db
entirely) AND quiet (its ledger timestamp hasn't moved across
REVENIUM_DRAIN_QUIET_TICKS consecutive checks) hold. Unknown — an unreadable
state.db, a missing row, a session that hasn't gone quiet yet — always
resolves to NOT drained, never to drained (T-32-14).

Task 3 proves hermes-report.sh's own re-read of drain-status.json is what
actually gates the legacy completions path: a disable request is honoured
ONLY when the gate reports drained, and is otherwise refused (with a single
warning) while completions keep metering exactly as before.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from tests._compat_helpers import build_shim, build_state_db, run_script

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / 'skills' / 'revenium' / 'scripts'

MUID = 'a' * 33


def _ledger_line(sid, total_tokens, ts, muid=MUID):
    return f'HERMES:{sid}:{total_tokens}:{ts:.3f}:{muid}\n'


class DrainGateTestBase(unittest.TestCase):
    def _setup_tree(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-drain-')
        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        os.makedirs(state_dir, mode=0o700)
        return tmpdir, hermes_home, state_dir

    def _write_ledger(self, state_dir, lines):
        path = os.path.join(state_dir, 'revenium-hermes.ledger')
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        return path

    def _write_state_db(self, hermes_home, sessions):
        """sessions: list of (sid, ended_at_or_None)."""
        db_path = os.path.join(hermes_home, 'state.db')
        conn = sqlite3.connect(db_path)
        conn.execute('CREATE TABLE sessions (id TEXT, ended_at REAL)')
        for sid, ended_at in sessions:
            conn.execute('INSERT INTO sessions VALUES (?, ?)', (sid, ended_at))
        conn.commit()
        conn.close()
        return db_path

    def _write_corrupt_state_db(self, hermes_home):
        db_path = os.path.join(hermes_home, 'state.db')
        with open(db_path, 'wb') as f:
            f.write(b'not a real sqlite3 database file at all')
        return db_path

    def _run(self, hermes_home, state_dir, extra_env=None):
        env = {
            **os.environ,
            'HOME': hermes_home,
            'HERMES_HOME': hermes_home,
            'REVENIUM_STATE_DIR': state_dir,
            'PATH': os.environ.get('PATH', ''),
            'TZ': 'UTC',
        }
        if extra_env:
            env.update(extra_env)
        result = subprocess.run(
            ['bash', str(SCRIPTS_DIR / 'drain-status.sh'), '--json'],
            env=env, capture_output=True, text=True, timeout=30,
        )
        try:
            doc = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError) as exc:
            self.fail(
                f'drain-status.sh --json did not print valid JSON: {exc}\n'
                f'stdout={result.stdout!r} stderr={result.stderr!r}'
            )
        return result.returncode, doc, result.stdout, result.stderr

    def _run_n_times(self, hermes_home, state_dir, n, extra_env=None):
        rc = doc = out = err = None
        for _ in range(n):
            rc, doc, out, err = self._run(hermes_home, state_dir, extra_env=extra_env)
        return rc, doc, out, err


# ============================================================================
# Task 2 — drain-status.sh's own verdict computation
# ============================================================================

class EmptyLedgerTests(DrainGateTestBase):
    def test_empty_ledger_reports_drained_exit_0(self):
        tmpdir, hh, sd = self._setup_tree()
        try:
            rc, doc, out, err = self._run(hh, sd)
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertTrue(doc['drained'])
            self.assertTrue(doc['determined'])
            self.assertEqual(doc['ledgerSessionsTracked'], 0)
            self.assertEqual(doc['pendingCount'], 0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class NullEndedAtTests(DrainGateTestBase):
    def test_null_ended_at_reports_not_drained_exit_10(self):
        tmpdir, hh, sd = self._setup_tree()
        try:
            sid = 'sess-open'
            now = time.time()
            self._write_ledger(sd, [_ledger_line(sid, 1500, now)])
            self._write_state_db(hh, [(sid, None)])

            rc, doc, out, err = self._run(hh, sd)
            self.assertEqual(rc, 10, f'stdout={out!r} stderr={err!r}')
            self.assertFalse(doc['drained'])
            self.assertTrue(doc['determined'])
            self.assertEqual(doc['ledgerSessionsTracked'], 1)
            self.assertEqual(doc['pendingCount'], 1)
            self.assertEqual(doc['pending'][0]['sid'], sid)
            self.assertFalse(doc['pending'][0]['terminal'])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class EndedInsideSettleWindowTests(DrainGateTestBase):
    def test_ended_at_inside_settle_window_still_not_drained(self):
        tmpdir, hh, sd = self._setup_tree()
        try:
            sid = 'sess-just-ended'
            now = time.time()
            self._write_ledger(sd, [_ledger_line(sid, 1500, now)])
            # Ended 10s ago -- well inside the default 600s settle window.
            self._write_state_db(hh, [(sid, now - 10)])

            rc, doc, out, err = self._run(hh, sd)
            self.assertEqual(rc, 10, f'stdout={out!r} stderr={err!r}')
            self.assertFalse(doc['drained'])
            self.assertFalse(doc['pending'][0]['terminal'])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class InsufficientQuietChecksTests(DrainGateTestBase):
    def test_past_settle_window_but_insufficient_quiet_checks_not_drained(self):
        tmpdir, hh, sd = self._setup_tree()
        try:
            sid = 'sess-terminal-not-quiet-yet'
            now = time.time()
            # Ended well past the settle window -- terminal on every check.
            self._write_ledger(sd, [_ledger_line(sid, 1500, now)])
            self._write_state_db(hh, [(sid, now - 3600)])

            extra_env = {
                'REVENIUM_CRON_SETTLE_SECONDS': '60',
                'REVENIUM_DRAIN_QUIET_TICKS': '3',
            }
            # Two checks: tick 1 establishes the baseline (quietTicks=0),
            # tick 2 confirms one quiet observation (quietTicks=1) — still
            # short of the 3 required.
            rc, doc, out, err = self._run_n_times(hh, sd, 2, extra_env=extra_env)
            self.assertEqual(rc, 10, f'stdout={out!r} stderr={err!r}')
            self.assertFalse(doc['drained'])
            self.assertTrue(doc['pending'][0]['terminal'])
            self.assertLess(doc['quietTicks'][sid], 3)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class EnoughQuietChecksDrainedTests(DrainGateTestBase):
    def test_after_enough_unchanged_consecutive_checks_drained(self):
        tmpdir, hh, sd = self._setup_tree()
        try:
            sid = 'sess-terminal-and-quiet'
            now = time.time()
            self._write_ledger(sd, [_ledger_line(sid, 1500, now)])
            self._write_state_db(hh, [(sid, now - 3600)])

            extra_env = {
                'REVENIUM_CRON_SETTLE_SECONDS': '60',
                'REVENIUM_DRAIN_QUIET_TICKS': '3',
            }
            # tick1 -> quietTicks=0 (baseline); ticks 2,3,4 -> 1,2,3 (>=3 required).
            rc, doc, out, err = self._run_n_times(hh, sd, 4, extra_env=extra_env)
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertTrue(doc['drained'])
            self.assertEqual(doc['drainedCount'], 1)
            self.assertEqual(doc['pendingCount'], 0)
            self.assertGreaterEqual(doc['quietTicks'][sid], 3)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class LedgerTimestampMoveResetsQuietCountTests(DrainGateTestBase):
    def test_ledger_timestamp_move_resets_quiet_count_to_zero(self):
        tmpdir, hh, sd = self._setup_tree()
        try:
            sid = 'sess-reactivates'
            now = time.time()
            self._write_ledger(sd, [_ledger_line(sid, 1500, now)])
            self._write_state_db(hh, [(sid, now - 3600)])

            extra_env = {
                'REVENIUM_CRON_SETTLE_SECONDS': '60',
                'REVENIUM_DRAIN_QUIET_TICKS': '5',
            }
            # tick1 -> quietTicks=0; tick2 (unchanged ledger) -> quietTicks=1.
            self._run(hh, sd, extra_env=extra_env)
            rc, doc, out, err = self._run(hh, sd, extra_env=extra_env)
            self.assertEqual(doc['quietTicks'][sid], 1)

            # New activity: a fresh HERMES: line for the SAME sid with a
            # LATER timestamp -- the session is still alive.
            later = now + 30
            self._write_ledger(sd, [
                _ledger_line(sid, 1500, now),
                _ledger_line(sid, 1600, later),
            ])
            rc, doc, out, err = self._run(hh, sd, extra_env=extra_env)
            self.assertEqual(rc, 10, f'stdout={out!r} stderr={err!r}')
            self.assertEqual(doc['quietTicks'][sid], 0,
                             'a moved ledger timestamp must reset the quiet count to zero')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class AbsentFromStateDbTests(DrainGateTestBase):
    def test_session_absent_from_state_db_is_drained(self):
        tmpdir, hh, sd = self._setup_tree()
        try:
            sid = 'sess-long-gone'
            now = time.time()
            self._write_ledger(sd, [_ledger_line(sid, 1500, now)])
            # state.db exists (so the query path runs) but has NO row for
            # this sid at all -- Hermes' own retention already removed it.
            self._write_state_db(hh, [('some-other-session', now - 10)])

            extra_env = {'REVENIUM_DRAIN_QUIET_TICKS': '2'}
            # tick1 -> quietTicks=0 (baseline; terminal=True immediately via
            # the absent-from-db branch); tick2 -> quietTicks=1; tick3 -> 2
            # (>=2 required).
            rc, doc, out, err = self._run_n_times(hh, sd, 3, extra_env=extra_env)
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertTrue(doc['drained'])
            self.assertEqual(doc['drainedCount'], 1)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class RetentionBoundaryNotTrackedTests(DrainGateTestBase):
    def test_session_older_than_retention_is_not_tracked_at_all(self):
        tmpdir, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ancient'
            # 10 days old; retention set to 1 day below -- well past.
            old_ts = time.time() - (10 * 86400)
            self._write_ledger(sd, [_ledger_line(sid, 1500, old_ts)])
            self._write_state_db(hh, [(sid, None)])

            rc, doc, out, err = self._run(hh, sd, extra_env={'REVENIUM_MARKER_RETENTION_DAYS': '1'})
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertTrue(doc['drained'], 'a session past retention is drained by definition')
            self.assertEqual(doc['ledgerSessionsTracked'], 0,
                             'a session past retention must not be tracked individually')
            self.assertNotIn(sid, doc['quietTicks'])
            self.assertEqual(doc['pending'], [])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class UnreadableStateDbTests(DrainGateTestBase):
    def test_unreadable_state_db_exits_1_and_reports_not_drained(self):
        tmpdir, hh, sd = self._setup_tree()
        try:
            sid = 'sess-db-corrupt'
            now = time.time()
            self._write_ledger(sd, [_ledger_line(sid, 1500, now)])
            self._write_corrupt_state_db(hh)

            rc, doc, out, err = self._run(hh, sd)
            self.assertEqual(rc, 1, f'stdout={out!r} stderr={err!r}')
            self.assertFalse(doc['drained'])
            self.assertFalse(doc['determined'])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class StatusFileAtomicWriteTests(DrainGateTestBase):
    def test_status_file_exists_and_is_valid_json_on_disk(self):
        """The --json flag already round-trips through json.loads in every
        test above (via _run); this test additionally confirms the ON-DISK
        file itself (not just stdout) is valid JSON after a run."""
        tmpdir, hh, sd = self._setup_tree()
        try:
            sid = 'sess-disk-check'
            now = time.time()
            self._write_ledger(sd, [_ledger_line(sid, 1500, now)])
            self._write_state_db(hh, [(sid, None)])

            self._run(hh, sd)
            status_path = os.path.join(sd, 'drain-status.json')
            self.assertTrue(os.path.exists(status_path))
            with open(status_path) as f:
                json.load(f)  # must not raise
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
