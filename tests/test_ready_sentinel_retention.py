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


if __name__ == '__main__':
    unittest.main()
