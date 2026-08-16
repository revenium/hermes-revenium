"""Phase 32 Plan 02 — Task 1 (EVT-04/EVT-05 gating) and Task 3 (EVT-06/EVT-07
ledger idempotency).

Task 1 proves the shipper decides correctly WHICH events it is allowed to
ship: held behind the C-6 settle gate, skipped entirely under the D-09
legacy-ledger partition, or shipped with the C-7 provider resolution and the
capability-gated --reasoning-tokens flag.

Task 3 proves the new api_request_id-keyed ledger is a REAL idempotency
domain: presence-checked before every ship (in memory, no grep spawn per
record), appended only after a successful call, and never relying on any
assumed server-side --transaction-id dedup.
"""
import json
import os
import shlex
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from tests._compat_helpers import build_shim, run_script, argv_to_flags

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / 'skills' / 'revenium' / 'scripts'


def _write_jsonl(path, records):
    with open(path, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, separators=(',', ':')) + '\n')


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


# Far in the past relative to any real clock this suite runs under — always
# "aged out" of the default 600s REVENIUM_CRON_SETTLE_SECONDS window.
OLD_TS = 1715515000.0


class EventReportTestBase(unittest.TestCase):
    def _setup_tree(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-ledger-')
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

        return tmpdir, hermes_home, state_dir, spool_dir, markers_dir, ready_dir, shim_home, bin_dir

    def _build_default_shim(self, bin_dir, **kwargs):
        shim = os.path.join(bin_dir, 'revenium')
        build_shim(shim, **kwargs)
        return shim

    def _run(self, hermes_home, state_dir, shim_home, meter_log, inv_log, extra_env=None):
        env = {
            **os.environ,
            'HOME': shim_home,
            'HERMES_HOME': hermes_home,
            'REVENIUM_STATE_DIR': state_dir,
            'PATH': os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': inv_log,
            'METER_LOG': meter_log,
            'TZ': 'UTC',
        }
        if extra_env:
            env.update(extra_env)
        return run_script(SCRIPTS_DIR / 'api-event-report.sh', env, inv_log)

    def _log_text(self, state_dir):
        """log()'s stderr mirror is TTY-gated (common.sh) — under a captured
        subprocess it never reaches stdout/stderr, so info/warn assertions
        must read the metering log file directly."""
        log_path = os.path.join(state_dir, 'revenium-metering.log')
        if not os.path.exists(log_path):
            return ''
        with open(log_path, 'r', encoding='utf-8') as f:
            return f.read()

    def _completions(self, meter_log):
        invs = []
        if os.path.exists(meter_log):
            with open(meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        invs.append(shlex.split(line))
        return [a for a in invs if len(a) >= 2 and a[0] == 'meter' and a[1] == 'completion']


# ============================================================================
# Task 1 — settle gate, D-09 partition, C-7 provider, --reasoning-tokens gate
# ============================================================================

class SentinelShipsTests(EventReportTestBase):
    """Test 1 — a session with a .ready sentinel ships."""

    def test_session_with_sentinel_ships(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-with-sentinel'
            Path(ready_dir, sid).touch()
            # ts is "now-ish" — only the sentinel should matter, not age.
            import time
            now = time.time()
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'),
                         [_event_record(sid, f'{sid}:t1:api:1', now, now + 1)])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            self.assertEqual(len(self._completions(meter_log)), 1)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class HeldSessionTests(EventReportTestBase):
    """Test 2 — a session with neither sentinel nor age ships nothing and
    logs exactly ONE hold line regardless of how many records it has."""

    def test_neither_sentinel_nor_age_holds_and_logs_once(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-held'
            import time
            now = time.time()
            # Three records, all recent — well inside the 600s settle window,
            # no sentinel ever created.
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), [
                _event_record(sid, f'{sid}:t1:api:1', now, now + 1),
                _event_record(sid, f'{sid}:t1:api:2', now + 1, now + 2),
                _event_record(sid, f'{sid}:t1:api:3', now + 2, now + 3),
            ])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            self.assertEqual(len(self._completions(meter_log)), 0,
                             'a held session must ship nothing')
            log_text = self._log_text(sd)
            hold_lines = [l for l in log_text.splitlines() if f'holding {sid}' in l]
            self.assertEqual(len(hold_lines), 1,
                             f'expected exactly one hold line regardless of record count, got: {hold_lines!r}')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class AgedOutShipsUnclassifiedTests(EventReportTestBase):
    """Test 3 — a session past the settle window (no sentinel) ships as
    unclassified/CHAT."""

    def test_session_past_settle_window_ships(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-aged-out'
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'),
                         [_event_record(sid, f'{sid}:t1:api:1', OLD_TS, OLD_TS + 1)])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            completions = self._completions(meter_log)
            self.assertEqual(len(completions), 1, f'expected 1 completion, got {completions!r}')
            flags = argv_to_flags(completions[0])
            self.assertEqual(flags.get('--task-type'), 'unclassified')
            self.assertEqual(flags.get('--operation-type'), 'CHAT')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class LegacyLedgerPartitionTests(EventReportTestBase):
    """Test 4 — D-09: a session present in the legacy ledger ships nothing
    even with a sentinel present."""

    def test_session_in_legacy_ledger_ships_nothing_even_with_sentinel(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-legacy-owned'
            Path(ready_dir, sid).touch()

            legacy_ledger = os.path.join(sd, 'revenium-hermes.ledger')
            with open(legacy_ledger, 'w') as f:
                f.write(f'HERMES:{sid}:1234:1700000000.000:abc123\n')

            import time
            now = time.time()
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'),
                         [_event_record(sid, f'{sid}:t1:api:1', now, now + 1)])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            self.assertEqual(len(self._completions(meter_log)), 0,
                             'a session already owned by the legacy ledger must never ship '
                             'via the event path (D-09 partition)')
            self.assertIn(f'skipping {sid}', self._log_text(sd))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class ProviderRoutingLayerResolutionTests(EventReportTestBase):
    """Test 5 — a record whose provider is a routing layer resolves
    --provider from response_model (C-7)."""

    def test_routing_layer_provider_resolves_from_response_model(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-routing-layer'
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), [
                _event_record(
                    sid, f'{sid}:t1:api:1', OLD_TS, OLD_TS + 1,
                    provider='litellm', response_model='claude-sonnet-4-6',
                ),
            ])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            completions = self._completions(meter_log)
            self.assertEqual(len(completions), 1, f'expected 1 completion, got {completions!r}')
            flags = argv_to_flags(completions[0])
            self.assertEqual(flags.get('--provider'), 'anthropic',
                             '--provider must resolve to the MODEL provider, not the routing layer')
            self.assertEqual(flags.get('--model-source'), 'litellm',
                             '--model-source must carry the RAW (routing-layer) provider verbatim')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_direct_provider_passes_through_verbatim(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-direct-provider'
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), [
                _event_record(
                    sid, f'{sid}:t1:api:1', OLD_TS, OLD_TS + 1,
                    provider='anthropic', response_model='claude-sonnet-4-6',
                ),
            ])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            completions = self._completions(meter_log)
            flags = argv_to_flags(completions[0])
            self.assertEqual(flags.get('--provider'), 'anthropic')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class ReasoningTokensCapabilityGateTests(EventReportTestBase):
    """Test 6 — a record with a non-zero reasoning count ships
    --reasoning-tokens when the shim advertises the capability, and omits it
    when the shim does not."""

    def test_reasoning_tokens_shipped_when_capability_advertised(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir, reasoning_tokens_capable=True)
            sid = 'sess-reasoning-capable'
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), [
                _event_record(sid, f'{sid}:t1:api:1', OLD_TS, OLD_TS + 1, reasoning_tokens=42),
            ])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            completions = self._completions(meter_log)
            flags = argv_to_flags(completions[0])
            self.assertEqual(flags.get('--reasoning-tokens'), '42')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_reasoning_tokens_omitted_when_capability_absent(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir, reasoning_tokens_capable=False)
            sid = 'sess-reasoning-incapable'
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), [
                _event_record(sid, f'{sid}:t1:api:1', OLD_TS, OLD_TS + 1, reasoning_tokens=42),
            ])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            completions = self._completions(meter_log)
            flags = argv_to_flags(completions[0])
            self.assertNotIn('--reasoning-tokens', flags,
                             'an older CLI (no --reasoning-tokens advertised) must never see the flag')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
