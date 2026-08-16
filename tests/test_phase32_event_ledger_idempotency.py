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


# ============================================================================
# Task 3 — the new ledger as a real idempotency domain
# ============================================================================

def _build_failable_shim(shim_path, meter_log, fail_flag):
    """A minimal revenium shim whose `meter completion` branch fails (exit 1,
    no ledger-triggering output) whenever fail_flag exists on disk, and
    succeeds (capturing argv to meter_log) otherwise. Deliberately NOT
    routed through _compat_helpers.build_shim — failure simulation is
    specific to this idempotency proof and shouldn't grow a shared helper's
    surface for one caller."""
    body = f'''#!/usr/bin/env bash
case "$1" in
  config) exit 0 ;;
  guardrails) exit 0 ;;
  meter)
    if [[ "$3" == "--help" ]]; then
      echo "--agentic-job-id  Agentic job instance identifier"
      exit 0
    fi
    case "$2" in
      completion)
        if [[ -f "{fail_flag}" ]]; then
          echo "simulated failure" >&2
          exit 1
        fi
        printf "%q " "$@" >> "{meter_log}"
        printf "\\n"      >> "{meter_log}"
        ;;
    esac
    exit 0
    ;;
  jobs)
    if [[ "$2" == "--help" ]]; then exit 0; fi
    exit 0
    ;;
  *) exit 0 ;;
esac
'''
    with open(shim_path, 'w') as f:
        f.write(body)
    os.chmod(shim_path, 0o755)


class RepeatWithinRunDedupTests(EventReportTestBase):
    """Test 1/2 — the same spool file shipped twice (separate runs) produces
    one call and one ledger line; a spool file containing the same
    api_request_id TWICE (one run) also produces exactly one call."""

    def test_same_spool_shipped_twice_produces_one_call_and_one_ledger_line(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-repeat-across-runs'
            arid = f'{sid}:t1:api:1'
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'),
                         [_event_record(sid, arid, OLD_TS, OLD_TS + 1)])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')

            rc1, _i1, out1 = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc1, 0, out1)
            self.assertEqual(len(self._completions(meter_log)), 1)

            ledger_path = os.path.join(sd, 'revenium-api-events.ledger')
            with open(ledger_path) as f:
                ledger_lines_1 = [l for l in f.read().splitlines() if l]
            self.assertEqual(len(ledger_lines_1), 1)

            rc2, _i2, out2 = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc2, 0, out2)
            self.assertEqual(len(self._completions(meter_log)), 1,
                             'second run over the same spool must not add a second call')

            with open(ledger_path) as f:
                ledger_lines_2 = [l for l in f.read().splitlines() if l]
            self.assertEqual(len(ledger_lines_2), 1,
                             'second run must not add a second ledger line')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_duplicate_api_request_id_within_one_spool_file_ships_once(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-dup-within-run'
            arid = f'{sid}:t1:api:1'
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), [
                _event_record(sid, arid, OLD_TS, OLD_TS + 1),
                _event_record(sid, arid, OLD_TS + 5, OLD_TS + 6),  # same arid again
            ])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            self.assertEqual(len(self._completions(meter_log)), 1,
                             'two records sharing one api_request_id must ship exactly once')

            ledger_path = os.path.join(sd, 'revenium-api-events.ledger')
            with open(ledger_path) as f:
                ledger_lines = [l for l in f.read().splitlines() if l]
            self.assertEqual(len(ledger_lines), 1)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class FailedCallLeavesNoLedgerLineTests(EventReportTestBase):
    """Test 3 — a shim forced to exit non-zero produces a call attempt and
    NO ledger line; the next run retries and succeeds."""

    def test_failed_call_retries_on_next_run(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            shim = os.path.join(bin_dir, 'revenium')
            meter_log = os.path.join(tmpdir, 'meter.log')
            fail_flag = os.path.join(tmpdir, 'FAIL')
            Path(fail_flag).touch()
            _build_failable_shim(shim, meter_log, fail_flag)

            sid = 'sess-fails-then-retries'
            arid = f'{sid}:t1:api:1'
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'),
                         [_event_record(sid, arid, OLD_TS, OLD_TS + 1)])

            inv_log = os.path.join(tmpdir, 'inv.log')
            rc1, _i1, out1 = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc1, 0, out1)
            self.assertEqual(len(self._completions(meter_log)), 0,
                             'a failed call must not be captured as a successful invocation')
            self.assertIn('Failed:', self._log_text(sd))

            ledger_path = os.path.join(sd, 'revenium-api-events.ledger')
            if os.path.exists(ledger_path):
                with open(ledger_path) as f:
                    ledger_lines = [l for l in f.read().splitlines() if l]
                self.assertEqual(len(ledger_lines), 0,
                                 'a failed call must leave NO ledger line')

            # Clear the failure and re-run — the retry must now succeed.
            os.remove(fail_flag)
            rc2, _i2, out2 = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc2, 0, out2)
            self.assertEqual(len(self._completions(meter_log)), 1,
                             'the retry must succeed once the failure is cleared')
            with open(ledger_path) as f:
                ledger_lines = [l for l in f.read().splitlines() if l]
            self.assertEqual(len(ledger_lines), 1)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class PreSeededLedgerTests(EventReportTestBase):
    """Test 4 — a ledger pre-seeded with the identifier produces no call."""

    def test_preseeded_ledger_entry_produces_no_call(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-preseeded'
            arid = f'{sid}:t1:api:1'

            ledger_path = os.path.join(sd, 'revenium-api-events.ledger')
            with open(ledger_path, 'w') as f:
                f.write(f'API:{arid}|{sid}|1700000000.000\n')

            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'),
                         [_event_record(sid, arid, OLD_TS, OLD_TS + 1)])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            self.assertEqual(len(self._completions(meter_log)), 0,
                             'a pre-seeded ledger entry must suppress the ship entirely')

            with open(ledger_path) as f:
                ledger_lines = [l for l in f.read().splitlines() if l]
            self.assertEqual(len(ledger_lines), 1, 'no NEW ledger line should be appended')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class IdentifierShapeRoundTripTests(EventReportTestBase):
    """Test 5/6 — an api_request_id containing colons round-trips correctly
    through the presence check; one containing a pipe character is
    sanitised such that the line stays parseable and the check still
    matches on the next run."""

    def test_colon_bearing_api_request_id_round_trips(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-colon-arid'
            arid = f'{sid}:task-7:turn-3:api:9'  # structural colons, preserved per C-4
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'),
                         [_event_record(sid, arid, OLD_TS, OLD_TS + 1)])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')

            rc1, _i1, out1 = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc1, 0, out1)
            self.assertEqual(len(self._completions(meter_log)), 1)

            ledger_path = os.path.join(sd, 'revenium-api-events.ledger')
            with open(ledger_path) as f:
                ledger_line = f.read().splitlines()[0]
            self.assertTrue(ledger_line.startswith(f'API:{arid}|{sid}|'),
                            f'unexpected ledger line shape: {ledger_line!r}')

            rc2, _i2, out2 = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc2, 0, out2)
            self.assertEqual(len(self._completions(meter_log)), 1,
                             'a colon-bearing identifier must still dedup correctly on re-run')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_pipe_bearing_api_request_id_sanitised_and_still_dedups(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-pipe-arid'
            raw_arid = f'{sid}:t1|api|1'  # pipe chars — must not survive into the ledger row
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'),
                         [_event_record(sid, raw_arid, OLD_TS, OLD_TS + 1)])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')

            rc1, _i1, out1 = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc1, 0, out1)
            self.assertEqual(len(self._completions(meter_log)), 1)

            ledger_path = os.path.join(sd, 'revenium-api-events.ledger')
            with open(ledger_path) as f:
                ledger_lines = [l for l in f.read().splitlines() if l]
            self.assertEqual(len(ledger_lines), 1)
            # Exactly 3 pipe-delimited fields — a stray '|' from the raw
            # identifier would have produced a 4th field and broken parsing.
            self.assertEqual(len(ledger_lines[0].split('|')), 3,
                             f'pipe character leaked into the ledger row: {ledger_lines[0]!r}')

            rc2, _i2, out2 = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc2, 0, out2)
            self.assertEqual(len(self._completions(meter_log)), 1,
                             'the sanitised identifier must still dedup correctly on re-run')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class ThreeConsecutiveRunsByteIdenticalLedgerTests(EventReportTestBase):
    """Explicit fixture-level analogue of the forced-re-run proof: three
    consecutive runs over a fixed spool leave the ledger file's bytes
    identical after runs two and three."""

    def test_three_runs_leave_ledger_byte_identical_after_the_first(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-three-runs'
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), [
                _event_record(sid, f'{sid}:t1:api:1', OLD_TS, OLD_TS + 1),
                _event_record(sid, f'{sid}:t1:api:2', OLD_TS + 1, OLD_TS + 2),
            ])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            ledger_path = os.path.join(sd, 'revenium-api-events.ledger')

            rc1, _i1, out1 = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc1, 0, out1)
            self.assertEqual(len(self._completions(meter_log)), 2)
            with open(ledger_path, 'rb') as f:
                bytes_after_run1 = f.read()

            rc2, _i2, out2 = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc2, 0, out2)
            with open(ledger_path, 'rb') as f:
                bytes_after_run2 = f.read()
            self.assertEqual(bytes_after_run1, bytes_after_run2,
                             'ledger bytes must be identical after run 2')

            rc3, _i3, out3 = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc3, 0, out3)
            with open(ledger_path, 'rb') as f:
                bytes_after_run3 = f.read()
            self.assertEqual(bytes_after_run1, bytes_after_run3,
                             'ledger bytes must be identical after run 3')

            self.assertEqual(len(self._completions(meter_log)), 2,
                             'only the first run\'s two calls should ever be captured')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
