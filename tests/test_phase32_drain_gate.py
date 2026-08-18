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

from tests._compat_helpers import (
    argv_to_flags,
    build_shim,
    build_state_db,
    load_golden,
    run_script,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / 'skills' / 'revenium' / 'scripts'

MUID = 'a' * 33
# Matches test_phase29_agent_inheritance.py's own _OLD_TS: far enough in the
# past that the settle-seconds filter passes without needing a sentinel.
_OLD_TS = 1715514000.0


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
    """The retention filter bounds the quiet-tick map, but it must never be
    the reason an OPEN session escapes the terminal check.

    An earlier revision of this class asserted that a session past retention
    is "drained by definition" while its state.db row carried
    `ended_at = None` -- i.e. while it was still open. That pinned a real
    under-billing bug rather than a safety property: the gate would report
    drained, an operator would disable legacy completions, and the session's
    subsequent usage would be skipped by BOTH reporters (legacy because it is
    disabled, event because D-09 skips sessions present in the legacy
    ledger). The two cases are now separated -- ended sessions still age out
    of tracking, open ones never do.
    """

    def test_ended_session_older_than_retention_is_not_tracked_at_all(self):
        tmpdir, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ancient'
            # 10 days old; retention set to 1 day below -- well past.
            old_ts = time.time() - (10 * 86400)
            self._write_ledger(sd, [_ledger_line(sid, 1500, old_ts)])
            # ENDED long ago -- this is the case retention may legitimately
            # drop, because it can no longer accrue usage.
            self._write_state_db(hh, [(sid, old_ts)])

            rc, doc, out, err = self._run(hh, sd, extra_env={'REVENIUM_MARKER_RETENTION_DAYS': '1'})
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertTrue(doc['drained'],
                            'an ENDED session past retention is drained by definition')
            self.assertEqual(doc['ledgerSessionsTracked'], 0,
                             'an ended session past retention must not be tracked individually')
            self.assertNotIn(sid, doc['quietTicks'])
            self.assertEqual(doc['pending'], [])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_open_session_older_than_retention_is_still_tracked_and_blocks(self):
        """The regression this class exists for: ledger age must not let a
        live session slip past the gate.

        quick-260818-f1g: this test's fixture is 10 days old, which collides
        with the staleness route's 7d default. Staleness is opted OUT here
        (`REVENIUM_DRAIN_STALE_SECONDS=0`) so this class keeps testing the
        axis it was written for -- RETENTION -- without a second, unrelated
        feature deciding the outcome. Every assertion below is the original,
        byte-for-byte. The staleness-on behaviour of this same shape is
        asserted by its sibling below, deliberately as a separate test:
        folding them into one would leave neither axis cleanly pinned."""
        tmpdir, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ancient-but-open'
            old_ts = time.time() - (10 * 86400)
            self._write_ledger(sd, [_ledger_line(sid, 1500, old_ts)])
            # STILL OPEN (ended_at IS NULL) despite an ancient ledger line --
            # a long-lived gateway conversation, or one that resumed.
            self._write_state_db(hh, [(sid, None)])

            rc, doc, out, err = self._run(hh, sd, extra_env={
                'REVENIUM_MARKER_RETENTION_DAYS': '1',
                'REVENIUM_DRAIN_STALE_SECONDS': '0',
            })
            # C-11: exit 10 IS the not-drained verdict, not an error.
            self.assertEqual(rc, 10, f'stdout={out!r} stderr={err!r}')
            self.assertFalse(doc['drained'],
                             'an OPEN session must block the gate no matter how old its '
                             'newest ledger line is -- disabling legacy completions here '
                             'would leave its usage billed by neither reporter')
            self.assertEqual(doc['ledgerSessionsTracked'], 1,
                             'an open session is force-included past the retention filter')
            self.assertIn(sid, doc['quietTicks'])
            self.assertEqual([p['sid'] for p in doc['pending']], [sid])
            self.assertFalse(doc['pending'][0]['terminal'],
                             'the pending entry must record it as non-terminal')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_open_session_older_than_stale_threshold_is_terminal_but_retained(self):
        """The sibling of the test above, with staleness ENABLED — the same
        on-disk shape, asserting the property rather than the mechanism.

        The original test asserted `terminal is False`, and justified it as
        'disabling legacy completions here would leave its usage billed by
        neither reporter'. That JUSTIFICATION is the real invariant, and it
        still holds — but it is now delivered by a different mechanism. The
        session is terminal (it no longer blocks the gate), AND it appears in
        `legacyRetainedSids`, so legacy metering is NOT suppressed for it and
        its usage is still billed by exactly one reporter.

        The distinction matters: blocking was never the point, not-being-
        billed-by-nobody was. Pinning `terminal is False` pinned the old
        implementation of the guarantee, not the guarantee. Recorded here so
        it is not 'restored' by someone reading the old assertion as intent.

        This fixture's `sessions` table has no `last_activity_at` column at
        all, so there is no corroborating activity signal — which is exactly
        the population the carve-out exists to protect."""
        tmpdir, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ancient-but-open'
            old_ts = time.time() - (10 * 86400)
            self._write_ledger(sd, [_ledger_line(sid, 1500, old_ts)])
            self._write_state_db(hh, [(sid, None)])

            rc, doc, out, err = self._run(hh, sd, extra_env={
                'REVENIUM_MARKER_RETENTION_DAYS': '1',
                'REVENIUM_DRAIN_STALE_SECONDS': str(7 * 86400),
            })
            self.assertEqual(doc['ledgerSessionsTracked'], 1,
                             'staleness must not change tracking — an open session is '
                             'still force-included past the retention filter')
            self.assertIn(sid, doc.get('legacyRetainedSids', []),
                          'THE SAFETY PROPERTY: a session declared stale with no '
                          'corroborating activity signal must be carved out of legacy '
                          'suppression, so it is never billed by neither reporter')
            self.assertTrue(doc['pending'][0]['stale'],
                            'the quiet open session is recognised as stale')
            self.assertTrue(doc['pending'][0]['terminal'],
                            'staleness grants terminal — this is what the original '
                            'assertion pinned as False, and the deliberate change')
            # NOT asserted here: drained / rc == 0. Reaching `drained` needs the
            # quiet-tick conjunction on top of `terminal`, so a single run can
            # never drain no matter how stale the session is (this run reports
            # quietTicks=0). That conjunction is deliberately unchanged by
            # quick-260818-f1g and is covered by its own tests; asserting it
            # here would silently re-test a different axis and would have made
            # this test fail for a reason unrelated to what it is pinning.
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_stale_session_reaching_drained_still_carries_its_retention(self):
        """The carve-out must survive the quiet-tick conjunction, not just the
        first tick. A stale session that accumulates enough quiet ticks to
        actually flip `drained` must STILL be listed in `legacyRetainedSids` —
        otherwise the carve-out evaporates at exactly the moment it starts to
        matter, which is when an operator acts on `drained: true`."""
        tmpdir, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ancient-but-open'
            old_ts = time.time() - (10 * 86400)
            self._write_ledger(sd, [_ledger_line(sid, 1500, old_ts)])
            self._write_state_db(hh, [(sid, None)])
            env = {
                'REVENIUM_MARKER_RETENTION_DAYS': '1',
                'REVENIUM_DRAIN_STALE_SECONDS': str(7 * 86400),
                'REVENIUM_DRAIN_QUIET_TICKS': '1',
            }
            # First run establishes the quiet baseline; the second satisfies
            # the conjunction.
            self._run(hh, sd, extra_env=env)
            rc, doc, out, err = self._run(hh, sd, extra_env=env)
            self.assertTrue(doc['drained'],
                            f'expected drained once quiet ticks are satisfied; '
                            f'stdout={out!r} stderr={err!r}')
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertIn(sid, doc.get('legacyRetainedSids', []),
                          'THE SAFETY PROPERTY AT THE MOMENT IT MATTERS: the sid is '
                          'still carved out of legacy suppression on the very run that '
                          'reports drained: true')
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


# ============================================================================
# Task 3 — hermes-report.sh's own re-read of REVENIUM_LEGACY_COMPLETIONS +
# drain-status.json's `drained` field
# ============================================================================

def _task_marker(sid, muid=MUID, ts=_OLD_TS + 1000.5, **overrides):
    rec = {
        'muid': muid, 'ts': ts, 'sid': sid,
        'task_type': 'code_review', 'operation_type': 'CHAT',
    }
    rec.update(overrides)
    return rec


def _job_marker(sid, job_id='compat-job-001', ts=_OLD_TS + 1001.0, **overrides):
    rec = {
        'kind': 'job', 'ts': ts, 'sid': sid,
        'agentic_job_id': job_id, 'job_name': 'Guard Test Job',
        'job_type': 'code_review', 'status': 'IN_PROGRESS',
    }
    rec.update(overrides)
    return rec


class HermesReportGuardTestBase(unittest.TestCase):
    """Shared harness: one temp HERMES_HOME, one shim, separate meter/jobs
    logs, one session's state.db row. Each test seeds its own markers and
    drain-status.json (if any)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gsd-phase32-legacy-guard-')
        self.hermes_home = os.path.join(self.tmp, 'hh')
        self.state_dir = os.path.join(self.hermes_home, 'state', 'revenium')
        self.markers_dir = os.path.join(self.state_dir, 'markers')
        os.makedirs(self.markers_dir, mode=0o700)
        self.state_db = os.path.join(self.hermes_home, 'state.db')

        self.shim_home = os.path.join(self.tmp, 'home')
        self.bin_dir = os.path.join(self.shim_home, '.local', 'bin')
        os.makedirs(self.bin_dir)
        self.meter_log = os.path.join(self.tmp, 'meter.log')
        self.jobs_log = os.path.join(self.tmp, 'jobs.log')
        self.inv_log = os.path.join(self.tmp, 'inv.log')
        self.shim = os.path.join(self.bin_dir, 'revenium')
        build_shim(self.shim, squad_capable=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed_session(self, sid):
        build_state_db(self.state_db, [{
            'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
            'input_tokens': 100, 'output_tokens': 50, 'cache_read': 0,
            'cache_write': 0, 'reasoning': 0, 'estimated_cost': '0',
            'api_calls': 1, 'started_at': _OLD_TS, 'ended_at': _OLD_TS,
            'billing_provider': 'anthropic',
        }])

    def _write_markers(self, sid, records):
        with open(os.path.join(self.markers_dir, f'{sid}.jsonl'), 'w') as f:
            for rec in records:
                f.write(json.dumps(rec, separators=(',', ':')) + '\n')

    def _write_drain_status(self, drained, pending_count=0):
        path = os.path.join(self.state_dir, 'drain-status.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'drained': drained, 'pendingCount': pending_count}, f)
        return path

    def _write_malformed_drain_status(self):
        path = os.path.join(self.state_dir, 'drain-status.json')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('{not valid json at all')
        return path

    def _base_env(self, extra=None):
        env = {
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
        if extra:
            env.update(extra)
        return env

    def _run(self, extra_env=None):
        rc, _ignored_inv, output = run_script(
            SCRIPTS_DIR / 'hermes-report.sh', self._base_env(extra_env), self.inv_log
        )
        self.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {output}')
        return output

    def _log_text(self):
        log_path = os.path.join(self.state_dir, 'revenium-metering.log')
        if not os.path.exists(log_path):
            return ''
        with open(log_path) as f:
            return f.read()

    def _completions(self):
        import shlex
        invs = []
        if os.path.exists(self.meter_log):
            with open(self.meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        invs.append(shlex.split(line))
        return [a for a in invs if len(a) >= 2 and a[0] == 'meter' and a[1] == 'completion']

    def _jobs_creates(self):
        import shlex
        invs = []
        if os.path.exists(self.jobs_log):
            with open(self.jobs_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        invs.append(shlex.split(line))
        return [a for a in invs if len(a) >= 2 and a[0] == 'jobs' and a[1] == 'create']


class DefaultSettingByteIdenticalTests(HermesReportGuardTestBase):
    """Test 1 — with the setting at its default, the reporter meters exactly
    as it does today. Re-runs the EXACT markerless fixture
    test_phase29_agent_inheritance.py uses to pin
    meter-completion-markerless.golden.json, so this is the existing
    baseline, not a new one."""

    def test_default_setting_argv_byte_identical_to_markerless_golden(self):
        sid = 'compat-sid-markerless-001'
        self._seed_session(sid)
        # Deliberately no marker file -- the markerless emit path.

        self._run()
        completions = self._completions()
        self.assertEqual(len(completions), 1, f'expected 1 completion, got {completions!r}')

        golden = load_golden('meter-completion-markerless.golden.json')
        self.assertEqual(
            completions[0], golden['argv_order'],
            'the reporter default path is no longer byte-identical to the '
            'pre-Phase-32 markerless golden — REVENIUM_LEGACY_COMPLETIONS defaults '
            'to "enabled" and must never observably change default behavior.\n'
            f'Captured: {completions[0]}\nGolden:   {golden["argv_order"]}'
        )


class DisabledAndDrainedSkipsCompletionsTests(HermesReportGuardTestBase):
    """Test 2 — disabled + drain gate reports drained: no meter completion
    call, but jobs create still fires (D-10: the jobs half is unaffected)."""

    def test_disabled_and_drained_skips_completions_but_not_jobs(self):
        sid = 'sess-disabled-drained'
        self._seed_session(sid)
        self._write_markers(sid, [_task_marker(sid), _job_marker(sid)])
        self._write_drain_status(drained=True, pending_count=0)

        self._run(extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})

        self.assertEqual(self._completions(), [],
                         'a drained, disabled reporter must ship zero completions')
        jobs_creates = self._jobs_creates()
        self.assertEqual(len(jobs_creates), 1,
                         f'the jobs half must keep running even when completions are '
                         f'skipped (D-10): {jobs_creates!r}')


class DisabledButNotDrainedKeepsMeteringTests(HermesReportGuardTestBase):
    """Test 3 — disabled + drain gate reports NOT drained: completions are
    still metered, and exactly one warning is logged."""

    def test_disabled_but_not_drained_keeps_metering_and_warns_once(self):
        sid = 'sess-disabled-not-drained'
        self._seed_session(sid)
        self._write_drain_status(drained=False, pending_count=3)

        self._run(extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})

        completions = self._completions()
        self.assertEqual(len(completions), 1,
                         'a disable request must be REFUSED while the gate reports '
                         'not drained — completions keep metering')

        log_text = self._log_text()
        warn_lines = [
            l for l in log_text.splitlines()
            if 'refusing to disable' in l or 'NOT drained' in l
        ]
        self.assertEqual(len(warn_lines), 1,
                         f'expected exactly one warning about the refused disable, got: '
                         f'{warn_lines!r}')
        self.assertIn('pending=3', warn_lines[0])


class DisabledWithMissingOrMalformedStatusKeepsMeteringTests(HermesReportGuardTestBase):
    """Test 4 — disabled + drain-status.json missing OR malformed:
    completions are still metered. Both a missing file and an invalid-JSON
    file must resolve to "not drained" (fail-safe read)."""

    def test_disabled_with_missing_status_file_keeps_metering(self):
        sid = 'sess-disabled-missing-status'
        self._seed_session(sid)
        # Deliberately do not write drain-status.json at all.

        self._run(extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})

        self.assertEqual(len(self._completions()), 1,
                         'a missing drain-status.json must fail SAFE to not-drained, '
                         'keeping completions metering')

    def test_disabled_with_malformed_status_file_keeps_metering(self):
        sid = 'sess-disabled-malformed-status'
        self._seed_session(sid)
        self._write_malformed_drain_status()

        self._run(extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})

        self.assertEqual(len(self._completions()), 1,
                         'an invalid-JSON drain-status.json must fail SAFE to '
                         'not-drained, keeping completions metering')


if __name__ == '__main__':
    unittest.main()
