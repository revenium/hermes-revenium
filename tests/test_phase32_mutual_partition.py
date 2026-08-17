"""quick-260817-pgg (EVT-07) — the D-09 legacy/event partition is MUTUAL.

The 2026-08-17 canary (32-CANARY-EVIDENCE.md) double-billed probe session
`20260817_213057_3a319e`: the event shipper claimed it at 21:32:46 and the
legacy stage billed it again at 21:33:28. The D-09 skip was not broken — it
fired correctly one tick later. It was one-DIRECTIONAL: api-event-report.sh
asked "does the legacy ledger own this session?", and hermes-report.sh never
asked the reciprocal question. The no-double-report guarantee therefore rested
on cron.sh's stage ordering (legacy line 97 before event line 103), which an
out-of-band shipper invocation defeats.

The invariant had been tested across TICKS and (since PR #52) across PROFILES,
but the ORDERING axis within a tick was assumed rather than asserted. This
module asserts it directly, in both directions:

  Case 1   — a session the EVENT ledger owns is never billed by the legacy
             completions path (the direction that broke).
  Case 1b  — that same session's jobs half still runs (D-10): the event path
             ships --agentic-job-id but never CREATES a job, so suppressing
             job creation would orphan every event row's job reference.
  Case 2   — a session the LEGACY ledger owns still ships nothing via the
             event path (the pre-existing direction, guarded against
             regression).
  Case 3   — with no event ledger (absent OR zero-byte), the legacy path
             bills exactly as it did before: one completion, one HERMES: line.
  Case 3b  — an event ledger holding only ANOTHER session's row does not
             suppress this session, even when that row's api_request_id
             CONTAINS this session's id as a substring.

Assertions are on the SHIPPING surfaces — captured argv in the meter/jobs logs
and the ledger files on disk — not on log prose, except where the existing
D-09 test already asserts `skipping <sid>` (case 2 keeps that).
"""
import os
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path

from tests._compat_helpers import argv_to_flags, build_shim, build_state_db, run_script
from tests.test_phase32_event_ledger_idempotency import (
    EventReportTestBase,
    _event_record,
    _write_jsonl,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / 'skills' / 'revenium' / 'scripts'

SID = 'partition-sid-001'
# Far enough in the past that the G-03 sentinel-or-aged filter passes on age
# alone, with no .ready sentinel — the same 2024 timestamp the compat suites
# use for exactly this reason.
OLD_STARTED_AT = 1715514000.0

# A realistic event-ledger row for SID. The api_request_id deliberately embeds
# COLONS (`<sid>:t1:api:1`, the real shape api-event-report.sh writes), so an
# implementation that tried to parse this line by colon position — the
# `^HERMES:<sid>:` idiom used elsewhere in hermes-report.sh — cannot
# accidentally pass this test.
EVENT_ROW = f'API:{SID}:t1:api:1|{SID}|1700000000.000\n'


class MutualPartitionBase(unittest.TestCase):
    """Drives hermes-report.sh with the test_compat_meter_completion idiom:
    a synthetic state.db, a no-shift shim under ${HOME}/.local/bin so
    ensure_path's last prepend wins, and separate METER_LOG / JOBS_LOG so
    completions and job calls are assertable independently."""

    def _setup_tree(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-mutual-')
        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        markers_dir = os.path.join(state_dir, 'markers')
        os.makedirs(markers_dir, mode=0o700)

        shim_home = os.path.join(tmpdir, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)
        build_shim(os.path.join(bin_dir, 'revenium'))

        build_state_db(os.path.join(hermes_home, 'state.db'), [{
            'id': SID,
            'model': 'claude-sonnet-4-6',
            'source': 'test',
            'input_tokens': 100,
            'output_tokens': 50,
            'cache_read': 0,
            'cache_write': 0,
            'reasoning': 0,
            'estimated_cost': '0',
            'api_calls': 1,
            'started_at': OLD_STARTED_AT,
            'ended_at': OLD_STARTED_AT,
            'billing_provider': 'anthropic',
        }])

        return tmpdir, hermes_home, state_dir, markers_dir, shim_home, bin_dir

    def _run(self, tmpdir, hermes_home, state_dir, shim_home, extra_env=None):
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        meter_log = os.path.join(tmpdir, 'meter.log')
        jobs_log = os.path.join(tmpdir, 'jobs.log')
        inv_log = os.path.join(tmpdir, 'inv.log')
        env = {
            **os.environ,
            'HOME': shim_home,
            'HERMES_HOME': hermes_home,
            'REVENIUM_STATE_DIR': state_dir,
            'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': inv_log,
            'METER_LOG': meter_log,
            'JOBS_LOG': jobs_log,
            'TZ': 'UTC',
            'REVENIUM_ORGANIZATION_NAME': '',
        }
        if extra_env:
            env.update(extra_env)
        rc, _inv, out = run_script(SCRIPTS_DIR / 'hermes-report.sh', env, inv_log)
        return rc, out, meter_log, jobs_log

    @staticmethod
    def _invocations(log_path):
        invs = []
        if os.path.exists(log_path):
            with open(log_path) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        invs.append(shlex.split(line))
        return invs

    def _completions(self, meter_log):
        return [a for a in self._invocations(meter_log)
                if len(a) >= 2 and a[0] == 'meter' and a[1] == 'completion']

    def _job_creates(self, jobs_log):
        return [a for a in self._invocations(jobs_log)
                if len(a) >= 2 and a[0] == 'jobs' and a[1] == 'create']

    @staticmethod
    def _legacy_ledger_lines(state_dir, sid=SID):
        path = os.path.join(state_dir, 'revenium-hermes.ledger')
        if not os.path.exists(path):
            return []
        with open(path, encoding='utf-8') as f:
            return [l for l in f.read().splitlines() if l.startswith(f'HERMES:{sid}:')]

    @staticmethod
    def _event_ledger_path(state_dir):
        return os.path.join(state_dir, 'revenium-api-events.ledger')

    @staticmethod
    def _log_text(state_dir):
        """log()'s stderr mirror is TTY-gated (common.sh), so under a captured
        subprocess nothing reaches stdout/stderr — log assertions must read
        revenium-metering.log from disk."""
        path = os.path.join(state_dir, 'revenium-metering.log')
        if not os.path.exists(path):
            return ''
        with open(path, encoding='utf-8') as f:
            return f.read()


# ============================================================================
# Case 1 / 1b — the direction that broke on 2026-08-17
# ============================================================================

class EventOwnedSessionNotBilledByLegacyTests(MutualPartitionBase):

    def test_event_owned_session_produces_no_legacy_completion(self):
        """Case 1: the event ledger owns this session, so the legacy path must
        neither ship a completion nor append a HERMES: ledger line."""
        tmpdir, hh, sd, _markers_dir, shim_home, _bin_dir = self._setup_tree()
        try:
            os.makedirs(sd, exist_ok=True)
            with open(self._event_ledger_path(sd), 'w', encoding='utf-8') as f:
                f.write(EVENT_ROW)

            rc, out, meter_log, _jobs_log = self._run(tmpdir, hh, sd, shim_home)
            self.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {out}')

            completions = self._completions(meter_log)
            self.assertEqual(
                completions, [],
                'a session already owned by the event ledger must never be billed '
                'by the legacy completions path (EVT-07 / D-09 reciprocal). '
                f'Got: {completions!r}'
            )
            self.assertEqual(
                self._legacy_ledger_lines(sd), [],
                'no HERMES: ledger line may be written for an event-owned session — '
                'writing one would also make the session legacy-owned and defeat '
                'the partition from the other side'
            )
            # T-PGG-03: the suppression must be visible to an operator, via the
            # per-tick aggregate (never a per-session line — see the code comment).
            self.assertIn('legacy completions suppressed for 1 session(s)',
                          self._log_text(sd))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_event_owned_session_still_creates_its_job(self):
        """Case 1b (D-10): suppressing completions must NOT suppress job
        creation. api-event-report.sh ships --agentic-job-id but never calls
        `revenium jobs create` — that call lives only in hermes-report.sh, so
        an early loop `continue` here would orphan every event row's job
        reference."""
        tmpdir, hh, sd, markers_dir, shim_home, _bin_dir = self._setup_tree()
        try:
            os.makedirs(sd, exist_ok=True)
            with open(self._event_ledger_path(sd), 'w', encoding='utf-8') as f:
                f.write(EVENT_ROW)

            _write_jsonl(os.path.join(markers_dir, f'{SID}.jsonl'), [{
                'kind': 'job',
                'ts': OLD_STARTED_AT + 1,
                'sid': SID,
                'agentic_job_id': 'partition-job-001',
                'job_name': 'Partition Test Job',
                'job_type': 'code_review',
                'status': 'IN_PROGRESS',
            }])

            rc, out, meter_log, jobs_log = self._run(tmpdir, hh, sd, shim_home)
            self.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {out}')

            self.assertEqual(
                self._completions(meter_log), [],
                'completions must still be suppressed for an event-owned session'
            )

            creates = self._job_creates(jobs_log)
            self.assertEqual(
                len(creates), 1,
                'the jobs half must keep running for an event-owned session (D-10) — '
                f'expected exactly one `jobs create`, got {creates!r}\nOutput: {out}'
            )
            self.assertEqual(
                argv_to_flags(creates[0]).get('--agentic-job-id'),
                'partition-job-001',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================================
# Case 2 — the pre-existing direction, guarded against regression
# ============================================================================

class LegacyOwnedSessionNotShippedByEventPathTests(EventReportTestBase):
    """Case 2: the original D-09 direction. Mirrors
    test_phase32_event_ledger_idempotency.LegacyLedgerPartitionTests so the
    two halves of the partition are asserted side by side in one module —
    a regression on either side fails here."""

    def test_legacy_owned_session_ships_nothing_via_event_path(self):
        tmpdir, hh, sd, spool_dir, _markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'partition-legacy-owned'
            Path(ready_dir, sid).touch()

            with open(os.path.join(sd, 'revenium-hermes.ledger'), 'w') as f:
                f.write(f'HERMES:{sid}:1234:1700000000.000:abc123\n')

            import time
            now = time.time()
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'),
                         [_event_record(sid, f'{sid}:t1:api:1', now, now + 1)])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            # REVENIUM_EVENT_METERING_MODE=live is set by _run: the default is
            # "shadow", which ships nothing and would make this assertion vacuous.
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            self.assertEqual(
                len(self._completions(meter_log)), 0,
                'a session already owned by the legacy HERMES: ledger must never '
                'ship via the event path (D-09 partition)'
            )
            self.assertIn(f'skipping {sid}', self._log_text(sd))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================================
# Case 3 / 3b — fail-open, and no cross-session false positive
# ============================================================================

class FailOpenTests(MutualPartitionBase):
    """The overwhelming majority of installs have no event path at all. They
    must meter byte-identically to before: same argv, same ledger line, same
    count. `[[ -s ]]` false and `grep` finding nothing are different code
    paths through the guard, so both are asserted."""

    def _assert_billed_exactly_once(self, sd, meter_log, out):
        completions = self._completions(meter_log)
        self.assertEqual(
            len(completions), 1,
            f'expected exactly one legacy completion, got {completions!r}\nOutput: {out}'
        )
        flags = argv_to_flags(completions[0])
        self.assertEqual(flags.get('--transaction-id'), f'{SID}-150')
        self.assertEqual(flags.get('--task-type'), 'unclassified')
        self.assertEqual(
            len(self._legacy_ledger_lines(sd)), 1,
            'exactly one HERMES: ledger line must be appended'
        )

    def test_no_event_ledger_file_bills_exactly_as_before(self):
        """Case 3: no event ledger on disk at all — the `[[ -s ]]` pre-test is
        false and no grep is ever spawned."""
        tmpdir, hh, sd, _markers_dir, shim_home, _bin_dir = self._setup_tree()
        try:
            rc, out, meter_log, _jobs_log = self._run(tmpdir, hh, sd, shim_home)
            self.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {out}')
            self.assertFalse(
                os.path.exists(self._event_ledger_path(sd)),
                'hermes-report.sh must never create the event ledger as a side effect'
            )
            self._assert_billed_exactly_once(sd, meter_log, out)
            self.assertNotIn('legacy completions suppressed', self._log_text(sd))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_zero_byte_event_ledger_bills_exactly_as_before(self):
        """Case 3, sibling: a present-but-empty event ledger. `-s` is false for
        a zero-byte file, so this is the same fail-open outcome by a different
        route than 'file absent'."""
        tmpdir, hh, sd, _markers_dir, shim_home, _bin_dir = self._setup_tree()
        try:
            os.makedirs(sd, exist_ok=True)
            open(self._event_ledger_path(sd), 'w').close()

            rc, out, meter_log, _jobs_log = self._run(tmpdir, hh, sd, shim_home)
            self.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {out}')
            self._assert_billed_exactly_once(sd, meter_log, out)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_other_sessions_event_row_does_not_suppress_this_session(self):
        """Case 3b: the match is on the pipe-delimited SESSION field, not a
        loose substring. The decoy row's api_request_id deliberately CONTAINS
        this session's id — a bare `grep -q "${sid}"` would false-positive on
        it and silently stop billing a session the event path never claimed."""
        tmpdir, hh, sd, _markers_dir, shim_home, _bin_dir = self._setup_tree()
        try:
            os.makedirs(sd, exist_ok=True)
            with open(self._event_ledger_path(sd), 'w', encoding='utf-8') as f:
                f.write(f'API:{SID}-shadow:t1:api:1|other-session|1700000000.000\n')
                f.write('API:unrelated:t1:api:1|unrelated-session|1700000001.000\n')

            rc, out, meter_log, _jobs_log = self._run(tmpdir, hh, sd, shim_home)
            self.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {out}')
            self._assert_billed_exactly_once(sd, meter_log, out)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
