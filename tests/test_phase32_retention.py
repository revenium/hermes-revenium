"""Phase 32 Plan 04 (EVT-08/EVT-09, D-15) — retention for the new event
spool, the pre-existing tool-event spool (never pruned by any shipped
script before this change), and the new api_request_id-keyed ledger.

Threat T-32-20 is the load-bearing invariant under test: an `API:` ledger
line is removed only when it is BOTH past the retention cutoff AND its
session's spool file no longer exists. Removing an idempotency record ahead
of the data it protects is how a pruning change turns into a double-report.

Threat T-32-21: the frozen legacy `HERMES:` ledger is never touched by any
of the new passes.
"""
import json
import os
import shutil
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


class Phase32RetentionTestBase(unittest.TestCase):
    def _setup(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-retention-')
        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        spool_dir = os.path.join(state_dir, 'api-events')
        tool_events_dir = os.path.join(state_dir, 'tool-events')
        markers_dir = os.path.join(state_dir, 'markers')
        os.makedirs(spool_dir, mode=0o700)
        os.makedirs(tool_events_dir, mode=0o700)
        os.makedirs(markers_dir, mode=0o700)
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
            'spool_dir': spool_dir,
            'tool_events_dir': tool_events_dir,
            'markers_dir': markers_dir,
            'event_ledger': os.path.join(state_dir, 'revenium-api-events.ledger'),
            'tool_ledger': os.path.join(state_dir, 'revenium-tool-events.ledger'),
            'legacy_ledger': os.path.join(state_dir, 'revenium-hermes.ledger'),
            'log_file': os.path.join(state_dir, 'revenium-metering.log'),
        }
        return env, paths

    def _write_spool(self, path, sid):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(json.dumps({'sid': sid, 'v': 1}) + '\n')

    def _log_text(self, paths):
        """log()'s stderr mirror is TTY-gated (common.sh) — under a captured
        subprocess it never reaches stdout/stderr, so info/warn assertions
        must read the metering log file directly."""
        log_path = paths['log_file']
        if not os.path.exists(log_path):
            return ''
        with open(log_path, 'r', encoding='utf-8') as f:
            return f.read()


# ============================================================================
# Test 1/2/3 — the new event spool (EVENT_SPOOL_DIR)
# ============================================================================

class EventSpoolRetentionTests(Phase32RetentionTestBase):
    def test_fresh_event_spool_file_is_kept(self):
        env, p = self._setup()
        try:
            sid = 'fresh-event-sid'
            spool_path = os.path.join(p['spool_dir'], f'{sid}.jsonl')
            self._write_spool(spool_path, sid)
            fresh_ts = int(time.time())
            with open(p['event_ledger'], 'a') as f:
                f.write(f'API:arid-fresh|{sid}|{fresh_ts}\n')

            r = _run(env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.exists(spool_path), 'a fresh event spool file must be kept')
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)

    def test_event_spool_file_past_ledger_cutoff_is_removed(self):
        env, p = self._setup()
        try:
            sid = 'stale-event-sid'
            spool_path = os.path.join(p['spool_dir'], f'{sid}.jsonl')
            self._write_spool(spool_path, sid)
            old_ts = int(time.time()) - OLD_DAYS * 86400
            with open(p['event_ledger'], 'a') as f:
                f.write(f'API:arid-stale|{sid}|{old_ts}\n')
            # Age the file itself too. A session that shipped long ago and has
            # spooled nothing since has an OLD mtime as well as an old ledger
            # row -- writing the file moments ago while claiming its newest
            # shipment was weeks ago describes a state that cannot occur, and
            # is in fact the signature of the resumed-session case covered by
            # test_event_spool_with_fresh_events_and_stale_ledger_is_kept.
            os.utime(spool_path, (old_ts, old_ts))

            r = _run(env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(os.path.exists(spool_path),
                             'an event spool file whose newest ledger row AND mtime are past '
                             'the cutoff must be removed')
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)

    def test_event_spool_with_fresh_events_and_stale_ledger_is_kept(self):
        """Regression: a spool must age from the NEWER of its last shipment
        and its own mtime.

        A session that shipped weeks ago and then resumed carries an ancient
        ledger row alongside brand-new unshipped events in the same file.
        Ageing it from the ledger alone deletes billable records before they
        are ever reported -- revenue lost silently, with the ledger's own
        success entry as the thing that caused it.
        """
        env, p = self._setup()
        try:
            sid = 'resumed-event-sid'
            spool_path = os.path.join(p['spool_dir'], f'{sid}.jsonl')
            self._write_spool(spool_path, sid)          # fresh mtime = unshipped events
            old_ts = int(time.time()) - OLD_DAYS * 86400
            with open(p['event_ledger'], 'a') as f:
                f.write(f'API:arid-ancient|{sid}|{old_ts}\n')   # shipped long ago

            r = _run(env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.exists(spool_path),
                            'a spool carrying fresh unshipped events must survive, however '
                            'old its last successful shipment was')
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)

    def test_orphan_event_spool_file_removed_by_mtime(self):
        env, p = self._setup()
        try:
            sid = 'orphan-event-sid'
            spool_path = os.path.join(p['spool_dir'], f'{sid}.jsonl')
            self._write_spool(spool_path, sid)
            old_ts = int(time.time()) - OLD_DAYS * 86400
            os.utime(spool_path, (old_ts, old_ts))
            # No ledger row at all for this sid -- mtime fallback governs.

            r = _run(env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(os.path.exists(spool_path),
                             'an orphan event spool file older than the cutoff must be removed by mtime')
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)


# ============================================================================
# Test 4/5/6 — the SAME three cases for tool-events (never pruned before)
# ============================================================================

class ToolEventsSpoolRetentionTests(Phase32RetentionTestBase):
    def test_fresh_tool_events_spool_file_is_kept(self):
        env, p = self._setup()
        try:
            sid = 'fresh-tool-sid'
            spool_path = os.path.join(p['tool_events_dir'], f'{sid}.jsonl')
            self._write_spool(spool_path, sid)
            fresh_ts = int(time.time())
            with open(p['tool_ledger'], 'a') as f:
                f.write(f'TOOL:{sid}:tcid-1:{fresh_ts}\n')

            r = _run(env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.exists(spool_path), 'a fresh tool-events spool file must be kept')
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)

    def test_tool_events_spool_file_past_ledger_cutoff_is_removed(self):
        env, p = self._setup()
        try:
            sid = 'stale-tool-sid'
            spool_path = os.path.join(p['tool_events_dir'], f'{sid}.jsonl')
            self._write_spool(spool_path, sid)
            old_ts = int(time.time()) - OLD_DAYS * 86400
            with open(p['tool_ledger'], 'a') as f:
                f.write(f'TOOL:{sid}:tcid-1:{old_ts}\n')
            # Age the file too -- a spool is pruned on the NEWER of its last
            # shipment and its own mtime, so a fresh mtime means unshipped
            # records are present and the file must survive.
            os.utime(spool_path, (old_ts, old_ts))

            r = _run(env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(os.path.exists(spool_path),
                             'a tool-events spool file whose newest ledger row AND mtime are '
                             'past the cutoff must be removed')
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)

    def test_orphan_tool_events_spool_file_removed_by_mtime(self):
        env, p = self._setup()
        try:
            sid = 'orphan-tool-sid'
            spool_path = os.path.join(p['tool_events_dir'], f'{sid}.jsonl')
            self._write_spool(spool_path, sid)
            old_ts = int(time.time()) - OLD_DAYS * 86400
            os.utime(spool_path, (old_ts, old_ts))

            r = _run(env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(os.path.exists(spool_path),
                             'an orphan tool-events spool file older than the cutoff must be removed by mtime')
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)


# ============================================================================
# Test 7/8 — the new api_request_id-keyed ledger (T-32-20's own proof)
# ============================================================================

class EventLedgerRetentionTests(Phase32RetentionTestBase):
    def test_stale_ledger_line_kept_when_spool_file_survives(self):
        """A ledger line past the cutoff is kept when its session's spool
        file still exists. The spool file is kept alive by a SECOND, fresh
        ledger line for the same session (a different api_request_id) so
        this test isolates the LEDGER pass's own behavior from the spool
        pass's independent staleness decision for the same file."""
        env, p = self._setup()
        try:
            sid = 'ledger-survives-sid'
            spool_path = os.path.join(p['spool_dir'], f'{sid}.jsonl')
            self._write_spool(spool_path, sid)

            old_ts = int(time.time()) - OLD_DAYS * 86400
            fresh_ts = int(time.time())
            old_line = f'API:arid-old|{sid}|{old_ts}\n'
            fresh_line = f'API:arid-fresh|{sid}|{fresh_ts}\n'
            with open(p['event_ledger'], 'w') as f:
                f.write(old_line)
                f.write(fresh_line)

            r = _run(env)
            self.assertEqual(r.returncode, 0, r.stderr)

            self.assertTrue(os.path.exists(spool_path),
                            'the spool file must survive (kept fresh by the second ledger line)')
            with open(p['event_ledger']) as f:
                remaining = f.read().splitlines()
            self.assertIn(old_line.rstrip('\n'), remaining,
                          'a stale ledger line must be KEPT while its spool file survives (T-32-20)')
            self.assertIn(fresh_line.rstrip('\n'), remaining)
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)

    def test_stale_ledger_line_removed_when_no_spool_file(self):
        env, p = self._setup()
        try:
            sid = 'ledger-orphaned-sid'
            # No spool file at all for this sid.
            old_ts = int(time.time()) - OLD_DAYS * 86400
            old_line = f'API:arid-old|{sid}|{old_ts}\n'
            with open(p['event_ledger'], 'w') as f:
                f.write(old_line)

            r = _run(env)
            self.assertEqual(r.returncode, 0, r.stderr)

            with open(p['event_ledger']) as f:
                remaining = f.read().splitlines()
            self.assertNotIn(old_line.rstrip('\n'), remaining,
                             'a stale ledger line whose spool file no longer exists must be removed')
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)


# ============================================================================
# Test 9 — --dry-run removes nothing, reports what it would
# ============================================================================

class DryRunTests(Phase32RetentionTestBase):
    def test_dry_run_removes_nothing_across_all_four_passes(self):
        env, p = self._setup()
        try:
            event_sid = 'dryrun-event-sid'
            tool_sid = 'dryrun-tool-sid'
            ledger_only_sid = 'dryrun-ledger-only-sid'

            event_spool_path = os.path.join(p['spool_dir'], f'{event_sid}.jsonl')
            self._write_spool(event_spool_path, event_sid)
            old_ts = int(time.time()) - OLD_DAYS * 86400
            with open(p['event_ledger'], 'w') as f:
                f.write(f'API:arid-1|{event_sid}|{old_ts}\n')
                f.write(f'API:arid-2|{ledger_only_sid}|{old_ts}\n')

            tool_spool_path = os.path.join(p['tool_events_dir'], f'{tool_sid}.jsonl')
            self._write_spool(tool_spool_path, tool_sid)
            with open(p['tool_ledger'], 'w') as f:
                f.write(f'TOOL:{tool_sid}:tcid-1:{old_ts}\n')

            with open(p['event_ledger']) as f:
                event_ledger_before = f.read()

            r = _run(env, '--dry-run')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('dry-run, would remove', self._log_text(p))

            self.assertTrue(os.path.exists(event_spool_path), '--dry-run must not delete the event spool file')
            self.assertTrue(os.path.exists(tool_spool_path), '--dry-run must not delete the tool-events spool file')
            with open(p['event_ledger']) as f:
                event_ledger_after = f.read()
            self.assertEqual(event_ledger_before, event_ledger_after,
                             '--dry-run must not rewrite the event ledger')
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)


# ============================================================================
# Test 10 — the frozen legacy HERMES: ledger is never touched (T-32-21)
# ============================================================================

class LegacyLedgerUntouchedTests(Phase32RetentionTestBase):
    def test_legacy_hermes_ledger_byte_identical_after_run(self):
        env, p = self._setup()
        try:
            legacy_content = 'HERMES:some-old-session:1000:1700000000.000:aaa\n'
            with open(p['legacy_ledger'], 'w') as f:
                f.write(legacy_content)

            # Also exercise the new passes in the same run, so this proves
            # the legacy ledger survives ALONGSIDE real pruning activity,
            # not just in a no-op run.
            stale_sid = 'legacy-untouched-companion-sid'
            spool_path = os.path.join(p['spool_dir'], f'{stale_sid}.jsonl')
            self._write_spool(spool_path, stale_sid)
            old_ts = int(time.time()) - OLD_DAYS * 86400
            with open(p['event_ledger'], 'w') as f:
                f.write(f'API:arid-1|{stale_sid}|{old_ts}\n')
            # Stale in BOTH senses, so the companion is genuinely prunable
            # and this test keeps exercising a real pruning run.
            os.utime(spool_path, (old_ts, old_ts))

            r = _run(env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(os.path.exists(spool_path), 'sanity: the companion stale spool file was pruned')

            with open(p['legacy_ledger']) as f:
                legacy_after = f.read()
            self.assertEqual(legacy_content, legacy_after,
                             'the frozen legacy HERMES: ledger must be byte-identical after a prune run (T-32-21)')
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)


# ============================================================================
# Test 11 — an invalid retention setting refuses to prune anything
# ============================================================================

class InvalidRetentionSettingTests(Phase32RetentionTestBase):
    def test_invalid_retention_days_prunes_nothing_across_new_passes_either(self):
        env, p = self._setup()
        try:
            env['REVENIUM_MARKER_RETENTION_DAYS'] = 'not-a-number'

            event_sid = 'invalid-retention-event-sid'
            tool_sid = 'invalid-retention-tool-sid'
            event_spool_path = os.path.join(p['spool_dir'], f'{event_sid}.jsonl')
            self._write_spool(event_spool_path, event_sid)
            tool_spool_path = os.path.join(p['tool_events_dir'], f'{tool_sid}.jsonl')
            self._write_spool(tool_spool_path, tool_sid)

            old_ts = int(time.time()) - OLD_DAYS * 86400
            with open(p['event_ledger'], 'w') as f:
                f.write(f'API:arid-1|{event_sid}|{old_ts}\n')
            with open(p['tool_ledger'], 'w') as f:
                f.write(f'TOOL:{tool_sid}:tcid-1:{old_ts}\n')

            r = _run(env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('invalid', self._log_text(p).lower())

            self.assertTrue(os.path.exists(event_spool_path),
                            'an invalid retention setting must refuse to prune the event spool')
            self.assertTrue(os.path.exists(tool_spool_path),
                            'an invalid retention setting must refuse to prune the tool-events spool')
            with open(p['event_ledger']) as f:
                self.assertIn(f'API:arid-1|{event_sid}|{old_ts}', f.read())
        finally:
            shutil.rmtree(p['tmpdir'], ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
