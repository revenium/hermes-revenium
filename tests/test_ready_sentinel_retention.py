"""quick-261001-h5e -- prune the markers/.ready/<sid> sentinel directory
alongside the markers themselves.

The driver is diagnostic, not disk. A `.ready` sentinel with no marker file
is the exact on-disk shape of a genuine defect -- the classifier signalling
completion without ever writing markers. Because the marker pass
(test_phase32_retention.py's sibling) has pruned markers for years while
nothing has ever pruned `.ready`, that shape has been manufactured
artificially at scale: 2843 sentinels against 1112 marker files on the
reference host (Jupi, 2026-10-01), 1733 orphans, every one of them past the
30-day window. Reading that imbalance cold produced a confident, wrong
report of a systemic 70% classification failure in one session.

Task 1 of this plan wires a single end-to-end path (the todo's actual ask).
Task 2 adds the negative arms, the dry-run-fidelity arm, the belt arm, the
degradation arm, and the preflight arm -- see the per-class docstrings below
for which clause of `prune-markers.sh`'s `prune_ready_sentinels` predicate
each one pins.
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

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
PRUNE_SCRIPT = SKILL / 'scripts' / 'prune-markers.sh'

OLD_DAYS = 31  # past the default 30-day REVENIUM_MARKER_RETENTION_DAYS


def _run(env, *args):
    return subprocess.run(
        ['bash', str(PRUNE_SCRIPT), *args],
        env=env, capture_output=True, text=True, timeout=30,
    )


class ReadySentinelTestBase(unittest.TestCase):
    """Modelled on tests/test_phase32_retention.py's
    Phase32RetentionTestBase (_run/_setup/_log_text/OLD_DAYS), extended with
    the markers/.ready directory this plan adds a pruning pass for, plus a
    state.db seeding helper carrying a real `started_at` column (the type
    and units hermes-report.sh itself reads: unix seconds via
    `int(float(...))`)."""

    def _setup(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-ready-sentinel-')
        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        markers_dir = os.path.join(state_dir, 'markers')
        ready_dir = os.path.join(markers_dir, '.ready')
        os.makedirs(markers_dir, mode=0o700)
        os.makedirs(ready_dir, mode=0o700)
        env = {
            **os.environ,
            'HERMES_HOME': hermes_home,
            'REVENIUM_STATE_DIR': state_dir,
            'REVENIUM_MARKER_RETENTION_DAYS': '30',
            'TZ': 'UTC',
        }
        paths = {
            'tmpdir': tmpdir,
            'hermes_home': hermes_home,
            'state_dir': state_dir,
            'markers_dir': markers_dir,
            'ready_dir': ready_dir,
            'legacy_ledger': os.path.join(state_dir, 'revenium-hermes.ledger'),
            'log_file': os.path.join(state_dir, 'revenium-metering.log'),
            'state_db': os.path.join(hermes_home, 'state.db'),
        }
        return env, paths

    def _touch_sentinel(self, ready_dir, sid, age_days):
        """Seed a sentinel at `.ready/<sid>` (the plugin writes the raw
        session id with no sanitisation -- __init__.py:76), with mtime
        `age_days` in the past. Idiom from
        tests/test_bounded_logging.py:816-819."""
        p = os.path.join(ready_dir, sid)
        Path(p).touch()
        ts = time.time() - age_days * 86400
        os.utime(p, (ts, ts))
        return p

    def _write_marker(self, markers_dir, sid, ts=None):
        p = os.path.join(markers_dir, f'{sid}.jsonl')
        payload = {
            'muid': 'm-' + sid,
            'ts': ts if ts is not None else time.time(),
            'sid': sid,
            'task_type': 'research',
            'operation_type': 'CHAT',
        }
        with open(p, 'w', encoding='utf-8') as f:
            f.write(json.dumps(payload) + '\n')
        return p

    def _write_ledger_row(self, paths, sid, ts, muid):
        """Append a HERMES:<sid>:<total_tokens>:<unix_ts>:<muid> row (the
        marker pass's OWN staleness source, D-26) to the legacy ledger."""
        with open(paths['legacy_ledger'], 'a', encoding='utf-8') as f:
            f.write(f'HERMES:{sid}:1000:{int(ts)}:{muid}\n')

    def _seed_state_db(self, state_db, rows):
        """rows: {sid: started_at_or_None}. A real `started_at REAL` column
        -- a fixture with only an `id` column would exercise the
        except-to-None degradation path instead of the belt clause this
        helper exists to exercise."""
        os.makedirs(os.path.dirname(state_db), exist_ok=True)
        conn = sqlite3.connect(state_db)
        try:
            conn.execute('CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at REAL)')
            conn.executemany(
                'INSERT INTO sessions (id, started_at) VALUES (?, ?)',
                list(rows.items()),
            )
            conn.commit()
        finally:
            conn.close()

    def _log_text(self, paths):
        """log()'s stderr mirror is TTY-gated (common.sh) -- under a
        captured subprocess it never reaches stdout/stderr, so info/warn
        assertions must read the metering log file directly."""
        log_path = paths['log_file']
        if not os.path.exists(log_path):
            return ''
        with open(log_path, 'r', encoding='utf-8') as f:
            return f.read()


# ============================================================================
# Task 1 -- the single end-to-end arm (the todo's actual ask, wired on one
# real path: an orphan sentinel past the window, with no marker file, is
# removed by a live run).
# ============================================================================

class ReadySentinelEndToEndTests(ReadySentinelTestBase):
    def test_orphan_stale_sentinel_removed_and_summary_logged_in_order(self):
        env, p = self._setup()
        try:
            sid = 'orphan-stale-sid'
            sentinel_path = self._touch_sentinel(p['ready_dir'], sid, OLD_DAYS)
            # No markers/<sid>.jsonl at all -- the orphan shape.

            r = _run(env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(
                os.path.exists(sentinel_path),
                'a stale orphan .ready sentinel (mtime 31 days old, no marker file) '
                'must be removed by a live run',
            )

            log = self._log_text(p)
            self.assertIn('prune: ready summary, scanned=', log)

            # The existing prune: summary and prune: flags summary lines must
            # still appear, in their EXISTING order, ahead of the new one --
            # other tests assert on this log text and the plan forbids
            # reordering it.
            flags_idx = log.index('prune: flags summary, scanned=')
            marker_summary_idx = log.index('prune: summary, scanned=')
            ready_idx = log.index('prune: ready summary, scanned=')
            self.assertLess(
                flags_idx, marker_summary_idx,
                'prune: flags summary must still print before prune: summary',
            )
            self.assertLess(
                marker_summary_idx, ready_idx,
                'the new prune: ready summary must print after the existing prune: summary',
            )
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)


# ============================================================================
# Task 2, ARM 1 -- the INVARIANT (the todo's actual ask). Pins the predicate
# as a whole, walked off the filesystem after a live run -- no hardcoded
# count anywhere in the assertion.
# ============================================================================

class ReadySentinelInvariantTests(ReadySentinelTestBase):
    def test_no_survivor_is_both_aged_past_retention_and_markerless(self):
        env, p = self._setup()
        try:
            now = time.time()

            # orphan-stale: past retention, no marker file at all.
            orphan_stale = 'inv-orphan-stale'
            self._touch_sentinel(p['ready_dir'], orphan_stale, OLD_DAYS)

            # orphan-fresh: mtime now, no marker file at all.
            orphan_fresh = 'inv-orphan-fresh'
            self._touch_sentinel(p['ready_dir'], orphan_fresh, 0)

            # stale-sentinel-with-fresh-marker: sentinel 31d old, marker
            # survives the marker pass (fresh ledger row).
            coupled_fresh_marker = 'inv-coupled-fresh-marker'
            self._touch_sentinel(p['ready_dir'], coupled_fresh_marker, OLD_DAYS)
            self._write_marker(p['markers_dir'], coupled_fresh_marker, ts=now)
            self._write_ledger_row(p, coupled_fresh_marker, now, 'm-fresh')

            # stale-sentinel-with-stale-marker: both the marker and the
            # sentinel are past the window -- the marker pass removes the
            # marker in this SAME run, and the sentinel must go with it.
            coupled_stale_marker = 'inv-coupled-stale-marker'
            self._touch_sentinel(p['ready_dir'], coupled_stale_marker, OLD_DAYS)
            old_ts = now - OLD_DAYS * 86400
            self._write_marker(p['markers_dir'], coupled_stale_marker, ts=old_ts)
            self._write_ledger_row(p, coupled_stale_marker, old_ts, 'm-stale')

            r = _run(env)
            self.assertEqual(r.returncode, 0, r.stderr)

            cutoff_secs = 30 * 86400
            survivors = sorted(os.listdir(p['ready_dir']))
            self.assertTrue(survivors, 'sanity: at least one sentinel (orphan-fresh) must survive')
            for sid in survivors:
                sentinel_path = os.path.join(p['ready_dir'], sid)
                age_secs = time.time() - os.path.getmtime(sentinel_path)
                marker_path = os.path.join(p['markers_dir'], f'{sid}.jsonl')
                markerless = not os.path.isfile(marker_path)
                past_retention = age_secs >= cutoff_secs
                self.assertFalse(
                    past_retention and markerless,
                    f'{sid} survived the run while BOTH past retention AND markerless -- '
                    'the exact defect shape this pass exists to eliminate',
                )
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)


# ============================================================================
# Task 2, ARMs 2-4 -- the negative and coupling arms. A pass that deleted
# everything would satisfy ARM 1 trivially (an empty directory has no
# survivor to violate the invariant) while destroying the live gate; these
# arms are what catches that.
# ============================================================================

class ReadySentinelKeepRuleTests(ReadySentinelTestBase):
    def test_fresh_orphan_sentinel_is_kept(self):
        """ARM 2: clause (a) alone must protect a fresh orphan. The genuine
        defect shape -- classifier signalled ready, wrote no markers -- must
        stay visible INSIDE the retention window, which means this sentinel
        is exactly the one a correct pass must never touch yet."""
        env, p = self._setup()
        try:
            sid = 'fresh-orphan-sid'
            sentinel_path = self._touch_sentinel(p['ready_dir'], sid, 0)

            r = _run(env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(
                os.path.exists(sentinel_path),
                'a fresh orphan sentinel (mtime now, no marker) must be KEPT',
            )
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)

    def test_stale_sentinel_with_surviving_marker_is_kept(self):
        """ARM 3: lifetime coupling -- a stale sentinel whose marker file
        survives the marker pass (fresh ledger row) is kept, and so is the
        marker itself."""
        env, p = self._setup()
        try:
            sid = 'stale-sentinel-fresh-marker'
            sentinel_path = self._touch_sentinel(p['ready_dir'], sid, OLD_DAYS)
            now = time.time()
            marker_path = self._write_marker(p['markers_dir'], sid, ts=now)
            self._write_ledger_row(p, sid, now, 'muid-3')

            r = _run(env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.exists(marker_path), 'sanity: the marker itself must survive')
            self.assertTrue(
                os.path.exists(sentinel_path),
                'a stale sentinel whose marker half survives must be KEPT',
            )
            self.assertIn('kept_marker_present=1', self._log_text(p))
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)

    def test_stale_sentinel_with_stale_marker_both_removed(self):
        """ARM 4: coupling the other direction -- once the marker ages out
        in the SAME run, the sentinel goes with it."""
        env, p = self._setup()
        try:
            sid = 'stale-sentinel-stale-marker'
            sentinel_path = self._touch_sentinel(p['ready_dir'], sid, OLD_DAYS)
            old_ts = time.time() - OLD_DAYS * 86400
            marker_path = self._write_marker(p['markers_dir'], sid, ts=old_ts)
            self._write_ledger_row(p, sid, old_ts, 'muid-4')

            r = _run(env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(os.path.exists(marker_path), 'sanity: the marker itself must be pruned')
            self.assertFalse(
                os.path.exists(sentinel_path),
                'a stale sentinel whose marker is pruned in the SAME run must be removed too',
            )
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)


# ============================================================================
# Task 2, ARM 5 -- dry-run fidelity. The arm that goes RED if clause (b) is
# implemented with a bare os.path.exists check instead of reading
# marker_pruned_sids: a dry run leaves the marker file ON DISK, so an
# existence test alone would preview "kept" for a sentinel a live run
# actually removes.
# ============================================================================

class ReadySentinelDryRunFidelityTests(ReadySentinelTestBase):
    def _seed_coupling_fixture(self, p):
        sid = 'dryrun-coupling-sid'
        self._touch_sentinel(p['ready_dir'], sid, OLD_DAYS)
        old_ts = time.time() - OLD_DAYS * 86400
        self._write_marker(p['markers_dir'], sid, ts=old_ts)
        self._write_ledger_row(p, sid, old_ts, 'muid-5')
        return sid

    @staticmethod
    def _ready_sids_from_log(log_text, action_marker):
        """Each line is replayed through info() (common.sh), which prepends
        a `[<ts>] [INFO ] [revenium] ` header before the `prune: ...` text
        this module prints -- so the marker is matched as a substring, never
        via str.startswith."""
        sids = set()
        for line in log_text.splitlines():
            if action_marker not in line:
                continue
            sids.add(line.split('sid=')[1].split(' ')[0])
        return sids

    def test_dry_run_names_exactly_what_a_live_run_removes(self):
        env, p = self._setup()
        try:
            sid = self._seed_coupling_fixture(p)

            dry = _run(env, '--dry-run')
            self.assertEqual(dry.returncode, 0, dry.stderr)
            sentinel_path = os.path.join(p['ready_dir'], sid)
            marker_path = os.path.join(p['markers_dir'], f'{sid}.jsonl')
            self.assertTrue(os.path.exists(sentinel_path), '--dry-run must not delete the sentinel')
            self.assertTrue(os.path.exists(marker_path), '--dry-run must not delete the marker')

            dry_ready_sids = self._ready_sids_from_log(
                self._log_text(p), 'prune: dry-run, would remove dir=ready'
            )
            self.assertEqual(dry_ready_sids, {sid}, 'dry-run must name the sentinel as a candidate')

            live = _run(env)
            self.assertEqual(live.returncode, 0, live.stderr)
            live_ready_sids = self._ready_sids_from_log(
                self._log_text(p), 'prune: removed dir=ready'
            )
            self.assertEqual(
                live_ready_sids, dry_ready_sids,
                'the set of sids a live run actually removes from .ready must equal '
                'the set --dry-run named as candidates (compared as SETS, not counts)',
            )
            self.assertFalse(os.path.exists(sentinel_path), 'sanity: the live run really removed it')
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)


# ============================================================================
# Task 2, ARM 6 -- the belt is wired into the predicate, not dead code.
# ============================================================================

class ReadySentinelBeltTests(ReadySentinelTestBase):
    def test_session_db_row_pending_keeps_markerless_stale_sentinel(self):
        """ARM 6.

        MANDATORY HONESTY NOTE: mtime(sentinel) >= started_at(session)
        ALWAYS holds in production -- the sentinel's only writer touches it
        during the session it names -- so a 31-day-old sentinel whose
        state.db row says started_at=now is a combination that CANNOT occur
        on a real host. This fixture exists anyway because it is the ONLY
        one that can distinguish the belt (clause c) from the age rule
        (clause a) in isolation: clause (a) is already production-sufficient
        on its own, so every other arm in this suite would still pass if
        clause (c) were silently deleted. Without this arm, that deletion
        would go unnoticed. This is a synthetic fixture proving a code path
        exists and is wired, not a claim about production behaviour -- do
        not read it as one, and do not "fix" it by making it more realistic
        (there is no realistic version of this combination).
        """
        env, p = self._setup()
        try:
            sid = 'belt-pending-sid'
            sentinel_path = self._touch_sentinel(p['ready_dir'], sid, OLD_DAYS)
            # No marker file at all -- clauses (a) and (b) are both already
            # satisfied; only the belt (c) can save this sentinel.
            self._seed_state_db(p['state_db'], {sid: time.time()})

            r = _run(env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(
                os.path.exists(sentinel_path),
                'a sentinel whose session row is still within the settle window must be '
                'KEPT by the belt, even though (a) and (b) both already say remove',
            )
            self.assertIn('kept_session_pending=1', self._log_text(p))
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)


# ============================================================================
# Task 2, ARM 7 -- degradation. No state.db at all (the shape every existing
# prune fixture in this repo has) must still remove the stale orphan, with
# the fallback named in the log rather than silently skipping clause (c).
# ============================================================================

class ReadySentinelDegradationTests(ReadySentinelTestBase):
    def test_no_state_db_still_removes_stale_orphan_with_fallback_logged(self):
        env, p = self._setup()
        try:
            self.assertFalse(os.path.exists(p['state_db']), 'sanity: no state.db in this fixture')
            sid = 'degraded-orphan-sid'
            sentinel_path = self._touch_sentinel(p['ready_dir'], sid, OLD_DAYS)

            r = _run(env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(
                os.path.exists(sentinel_path),
                'a stale orphan sentinel must still be removed when state.db is entirely absent',
            )
            self.assertIn('state.db unavailable, falling back to', self._log_text(p))
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)


# ============================================================================
# Task 2, ARM 8 -- preflight. Mirrors
# test_phase32_retention.InvalidRetentionSettingTests: the new pass is gated
# by the SAME marker_retention_ok preflight as its five siblings, not a
# separate (and possibly forgotten) check of its own.
# ============================================================================

class ReadySentinelPreflightTests(ReadySentinelTestBase):
    def test_invalid_retention_days_prunes_nothing_from_ready_either(self):
        env, p = self._setup()
        env['REVENIUM_MARKER_RETENTION_DAYS'] = 'not-a-number'
        try:
            sid = 'invalid-retention-ready-sid'
            sentinel_path = self._touch_sentinel(p['ready_dir'], sid, OLD_DAYS)

            r = _run(env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('invalid', self._log_text(p).lower())
            self.assertTrue(
                os.path.exists(sentinel_path),
                'an invalid retention setting must refuse to prune .ready too',
            )
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)


if __name__ == '__main__':
    unittest.main()


class ReadySentinelReviewHardeningTests(ReadySentinelTestBase):
    """ARMs 9-11: the three defects external review found on PR #139.

    Each of these survived the original 8-arm matrix, which is the point of
    recording them here: the matrix proved the PREDICATE, and all three of
    these are failures of the pass's ENVELOPE -- what happens when a tunable
    is hostile, when the directory cannot be read, and when two independent
    tunables are configured into an order the design argued could not occur.
    """

    def test_settle_window_longer_than_retention_keeps_the_sentinel(self):
        """ARM 9 (clause (a) is config-dependent, not absolute).

        The original docstring argued clause (a) was airtight from a '4,320x
        margin -- 30 days against the 600-second default'. That margin is a
        DEFAULT, not an invariant: REVENIUM_MARKER_RETENTION_DAYS and
        REVENIUM_CRON_SETTLE_SECONDS are independent operator tunables. With
        retention=1d and settle=2d the implication inverts, and a sentinel
        past the cutoff still belongs to a session the reporter considers
        young -- deleting it DEFERS a session the sentinel would have
        released, which is the exact BUG-1 job-orphaning hazard this pass
        exists not to cause.

        Catches: the pre-fix pass, which compared against cutoff_secs alone.
        """
        env, p = self._setup()
        try:
            sid = 'sess-settle-inversion'
            # 1-day retention, 2-day settle: the inversion.
            env['REVENIUM_MARKER_RETENTION_DAYS'] = '1'
            env['REVENIUM_CRON_SETTLE_SECONDS'] = str(2 * 86400)
            # Sentinel is 1.5 days old: past retention, inside settle.
            sentinel = self._touch_sentinel(p['ready_dir'], sid, 1.5)
            r = _run(env, '--dry-run')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(
                os.path.exists(sentinel),
                'a sentinel inside the settle window must be KEPT even when it '
                'is past marker retention -- the reporter can still consult it',
            )
            log = self._log_text(p)
            self.assertNotIn(
                sid, log.split('ready summary')[0].split('dir=ready')[-1]
                if 'dir=ready' in log else '',
                'the sentinel must not be named as a removal candidate',
            )
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)

    def test_infinite_settle_override_does_not_kill_the_run(self):
        """ARM 10 (a hostile tunable must fail open, not abort).

        int(float('inf')) raises OverflowError, which is NOT a ValueError.
        Before the fix, REVENIUM_CRON_SETTLE_SECONDS=inf aborted the whole
        interpreter before ANY retention pass ran -- marker, flags, ready,
        spool, ledger and owners alike -- over a tunable this script only
        reads as a safety belt. The code's own comment already promised a
        garbage override would 'fail open to that default rather than crash
        the whole prune run'; this arm is what makes that true.

        Catches: an except tuple of (TypeError, ValueError) only.
        """
        env, p = self._setup()
        try:
            sid = 'sess-inf-settle'
            self._touch_sentinel(p['ready_dir'], sid, OLD_DAYS)
            env['REVENIUM_CRON_SETTLE_SECONDS'] = 'inf'
            r = _run(env, '--dry-run')
            self.assertEqual(
                r.returncode, 0,
                'an invalid settle override must fail open to the 600s '
                f'default, not abort the prune run. stderr={r.stderr}',
            )
            self.assertIn(
                'prune: summary', self._log_text(p),
                'the marker pass must still have run and summarised',
            )
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)

    def test_unreadable_ready_dir_skips_only_this_pass(self):
        """ARM 11 (one unreadable dir must not cancel every later pass).

        prune_spool_dir, prune_event_ledger and the owners pass all run
        LATER in the same interpreter. os.listdir on an existing-but-
        unreadable .ready raises PermissionError -- an OSError sibling that
        a bare `except FileNotFoundError` does not catch -- so before the fix
        a single chmod 000 cancelled the spool, ledger and owners cleanup
        too. Mirrors the owners pass's own 'dir unreadable' skip precedent.

        Catches: `except FileNotFoundError` alone on the listdir.
        """
        env, p = self._setup()
        try:
            self._touch_sentinel(p['ready_dir'], 'sess-unreadable', OLD_DAYS)
            os.chmod(p['ready_dir'], 0o000)
            try:
                if os.access(p['ready_dir'], os.R_OK):
                    self.skipTest('running as root: chmod 000 is not enforced')
                r = _run(env, '--dry-run')
                self.assertEqual(
                    r.returncode, 0,
                    f'an unreadable .ready must skip this pass only. stderr={r.stderr}',
                )
                log = self._log_text(p)
                self.assertIn('ready pass skipped', log)
                self.assertIn(
                    'prune: summary', log,
                    'the marker pass summary must still be present',
                )
            finally:
                os.chmod(p['ready_dir'], 0o700)
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)
