"""Phase 32 Plan 03, Task 1 (EVT-10/C-10) — the shadow-comparison readout.

Proves shadow mode is a NEGATIVE-proof feature, not a positive one: it must
demonstrably ship nothing (zero CLI invocations, zero ledger lines) while
still producing one per-session comparison row (event_shadow_report.jsonl)
plus a per-platform aggregate logged through info() — including a platform
bucket whose events are entirely absent, which is the empirical answer to
"does post_api_request fire on gateway turns" (constraint 5) once this runs
on a real fleet.

REVENIUM_EVENT_METERING_MODE defaults to "shadow" (C-9) — every test in this
module runs with NO override unless it is specifically testing the
env/config/default precedence or the invalid-value fallback, matching how a
freshly-deployed host actually behaves.
"""
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from tests._compat_helpers import build_shim, build_state_db, run_script

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / 'skills' / 'revenium' / 'scripts'

# Far in the past relative to any real clock this suite runs under — always
# "aged out" of the default 600s REVENIUM_CRON_SETTLE_SECONDS window, so a
# session ships as unclassified/CHAT without needing a marker file at all.
OLD_TS = 1715515000.0


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


def _session_row(sid, **overrides):
    row = {
        'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'cli',
        'input_tokens': 0, 'output_tokens': 0, 'cache_read': 0, 'cache_write': 0,
        'reasoning': 0, 'estimated_cost': '0', 'api_calls': 1,
        'started_at': OLD_TS, 'ended_at': OLD_TS + 5, 'billing_provider': '',
    }
    row.update(overrides)
    return row


class ShadowReadoutTestBase(unittest.TestCase):
    def _setup_tree(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-shadow-')
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

    def _write_state_db(self, hermes_home, sessions):
        build_state_db(os.path.join(hermes_home, 'state.db'), sessions)

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
        log_path = os.path.join(state_dir, 'revenium-metering.log')
        if not os.path.exists(log_path):
            return ''
        with open(log_path, 'r', encoding='utf-8') as f:
            return f.read()

    def _completions(self, meter_log):
        import shlex
        invs = []
        if os.path.exists(meter_log):
            with open(meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        invs.append(shlex.split(line))
        return [a for a in invs if len(a) >= 2 and a[0] == 'meter' and a[1] == 'completion']

    def _shadow_rows(self, state_dir):
        path = os.path.join(state_dir, 'event-shadow-report.jsonl')
        if not os.path.exists(path):
            return []
        rows = []
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
        return rows

    def _ledger_lines(self, state_dir):
        path = os.path.join(state_dir, 'revenium-api-events.ledger')
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [l for l in f.read().splitlines() if l]


class ShipsNothingButProducesOneRowPerSessionTests(ShadowReadoutTestBase):
    """Test 1 — shadow mode invokes the CLI zero times and writes zero
    ledger lines while producing one report row per session."""

    def test_shadow_mode_ships_nothing_and_writes_one_row_per_session(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid1, sid2 = 'sess-shadow-one', 'sess-shadow-two'
            _write_jsonl(os.path.join(spool_dir, f'{sid1}.jsonl'),
                         [_event_record(sid1, f'{sid1}:t1:api:1', OLD_TS, OLD_TS + 1)])
            _write_jsonl(os.path.join(spool_dir, f'{sid2}.jsonl'),
                         [_event_record(sid2, f'{sid2}:t1:api:1', OLD_TS, OLD_TS + 1)])
            self._write_state_db(hh, [_session_row(sid1), _session_row(sid2)])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            self.assertEqual(len(self._completions(meter_log)), 0,
                             'shadow mode must never invoke the revenium CLI')
            self.assertEqual(len(self._ledger_lines(sd)), 0,
                             'shadow mode must never write an api_request_id ledger line')

            rows = self._shadow_rows(sd)
            self.assertEqual(len(rows), 2, f'expected one shadow row per session, got {rows!r}')
            sids = {r['sid'] for r in rows}
            self.assertEqual(sids, {sid1, sid2})
            for row in rows:
                self.assertEqual(row['gate'], 'shipped')
                self.assertEqual(row['event_rows'], 1)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class CoverageRatioTests(ShadowReadoutTestBase):
    """Test 2 — coverage_ratio is 1.0 when constructed events exactly match
    database counters, and 0.0 when a session has database counters and no
    events (a held session)."""

    def test_coverage_ratio_one_when_event_matches_db_exactly(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-ratio-one'
            # _event_record defaults: input=100, output=50, cache_read=0,
            # cache_write=0 -> event usage total 150.
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'),
                         [_event_record(sid, f'{sid}:t1:api:1', OLD_TS, OLD_TS + 1)])
            self._write_state_db(hh, [_session_row(
                sid, input_tokens=100, output_tokens=50, cache_read=0, cache_write=0,
            )])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            rows = self._shadow_rows(sd)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['coverage_ratio'], 1.0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_coverage_ratio_zero_when_db_has_counters_and_no_events(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-ratio-zero'
            now = time.time()
            # Recent timestamp, no sentinel -> held (event_rows stays 0).
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'),
                         [_event_record(sid, f'{sid}:t1:api:1', now, now + 1)])
            self._write_state_db(hh, [_session_row(
                sid, input_tokens=200, output_tokens=100, cache_read=0, cache_write=0,
            )])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            rows = self._shadow_rows(sd)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['gate'], 'held')
            self.assertEqual(rows[0]['event_rows'], 0)
            self.assertEqual(rows[0]['coverage_ratio'], 0.0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class PlatformBucketingTests(ShadowReadoutTestBase):
    """Test 3 — rows are bucketed by platform, and a platform with sessions
    and no events appears in the aggregate rather than being absent from
    it."""

    def test_platform_with_zero_events_appears_in_aggregate(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)

            shipped_sid = 'sess-platform-cli'
            _write_jsonl(os.path.join(spool_dir, f'{shipped_sid}.jsonl'),
                         [_event_record(shipped_sid, f'{shipped_sid}:t1:api:1', OLD_TS, OLD_TS + 1,
                                        platform='cli')])

            held_sid = 'sess-platform-telegram'
            now = time.time()
            _write_jsonl(os.path.join(spool_dir, f'{held_sid}.jsonl'),
                         [_event_record(held_sid, f'{held_sid}:t1:api:1', now, now + 1,
                                        platform='telegram')])

            self._write_state_db(hh, [
                _session_row(shipped_sid, input_tokens=100, output_tokens=50),
                _session_row(held_sid, input_tokens=300, output_tokens=100),
            ])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            rows = self._shadow_rows(sd)
            self.assertEqual(len(rows), 2)
            by_sid = {r['sid']: r for r in rows}
            self.assertEqual(by_sid[held_sid]['platform'], 'telegram')
            self.assertEqual(by_sid[held_sid]['event_rows'], 0)
            self.assertGreater(by_sid[held_sid]['db_total'], 0)

            log_text = self._log_text(sd)
            self.assertIn('platform=telegram', log_text,
                          'a platform bucket with sessions and zero event rows must appear '
                          'in the aggregate, stated rather than inferred from an absence')
            self.assertIn('platform=cli', log_text)
            # The telegram bucket line itself must show event_rows=0, not be
            # silently dropped from the aggregate entirely.
            telegram_lines = [l for l in log_text.splitlines() if 'platform=telegram' in l]
            self.assertTrue(telegram_lines)
            self.assertIn('event_rows=0', telegram_lines[0])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class HeldAndLegacySkippedGateFieldsTests(ShadowReadoutTestBase):
    """Test 4 — held and legacy-skipped sessions appear with the right gate
    value and zeroed event fields."""

    def test_legacy_skipped_session_computes_would_be_rows_but_ships_nothing(self):
        """D-09 is a SHIPPING guard, and shadow mode does not ship.

        An earlier revision returned at the D-09 gate in every mode, which
        left the shadow readout structurally unable to produce its own
        deliverable. Legacy is still actively billing throughout the shadow
        window, so every session lands in the HERMES: ledger within a tick;
        skipping them all pinned every event-side field at zero and
        coverage_ratio at 0.0000 forever. Observed live on the fleet: an
        entire shadow report of `legacy_skip` rows with nothing in them.

        The gate label is still recorded — it is real information about what
        would happen in live mode — but the row now carries the values the
        event path WOULD have shipped, which is the comparison the stage
        exists to produce.
        """
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-legacy-skip-shadow'
            legacy_ledger = os.path.join(sd, 'revenium-hermes.ledger')
            with open(legacy_ledger, 'w') as f:
                f.write(f'HERMES:{sid}:1234:1700000000.000:abc123\n')

            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'),
                         [_event_record(sid, f'{sid}:t1:api:1', OLD_TS, OLD_TS + 1)])
            self._write_state_db(hh, [_session_row(sid, input_tokens=100, output_tokens=50)])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            # The safety property is unchanged and is what makes falling
            # through to enrichment legal in the first place.
            self.assertEqual(len(self._completions(meter_log)), 0,
                             'a legacy-owned session must still ship nothing in shadow mode')
            self.assertEqual(len(self._ledger_lines(sd)), 0,
                             'a legacy-owned session must still write no event ledger line')

            rows = self._shadow_rows(sd)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row['gate'], 'legacy_skip',
                             'the gate label must still say it would not have shipped live')
            self.assertEqual(row['legacy_ledger_lines'], 1)
            self.assertTrue(row['legacy_owned'],
                            'ownership is recorded in its own field, independent of gate')
            # The regression this test exists for: the event side is populated.
            self.assertEqual(row['event_rows'], 1,
                             'the would-be row must be computed, not zeroed by the skip')
            self.assertEqual(row['event_input'], 100)
            self.assertEqual(row['event_output'], 50)
            self.assertEqual(row['event_total'], 150)
            self.assertGreater(row['coverage_ratio'], 0.0,
                               'coverage must be measurable for a legacy-owned session — '
                               'a shadow window of these pinned at 0.0 is exactly the '
                               'failure that made the readout useless on the fleet')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_legacy_owned_session_inside_settle_window_keeps_ownership_signal(self):
        """Greptile P1 on #48: the settle gate must not erase legacy ownership.

        `gate` records what stopped the session on THIS tick and `held` is
        genuinely that — enrichment cannot run without a marker, so zeroed
        event fields are correct here. But ownership is permanent, and the
        first revision of the fallthrough let the hardcoded "held" label
        discard it, so the report lost the signal entirely for any
        legacy-owned session still inside its settle window.
        """
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-legacy-owned-and-held'
            with open(os.path.join(sd, 'revenium-hermes.ledger'), 'w') as f:
                f.write(f'HERMES:{sid}:1234:1700000000.000:abc123\n')

            # Fresh event, no .ready sentinel -> inside the settle window.
            fresh_ts = time.time()
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'),
                         [_event_record(sid, f'{sid}:t1:api:1', fresh_ts, fresh_ts + 1)])
            self._write_state_db(hh, [_session_row(sid, input_tokens=100, output_tokens=50)])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            rows = self._shadow_rows(sd)
            self.assertEqual(len(rows), 1, f'the session must still appear: {rows!r}')
            row = rows[0]
            self.assertEqual(row['gate'], 'held',
                             'held is what actually stopped it on this tick')
            self.assertTrue(row['legacy_owned'],
                            'ownership is permanent and must survive a held tick')
            self.assertEqual(len(self._completions(meter_log)), 0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_session_with_no_enrichable_events_still_appears_in_report(self):
        """Greptile P1 on #48: every exit must emit a row.

        A session can pass the cheap peek and then have every event fail the
        stricter enrichment validation, leaving `rows` empty. That exit
        previously returned without emitting, so the session vanished from
        the report AND from the per-platform aggregate. An empty gateway
        bucket reads as "post_api_request never fires on gateway" — a false
        negative on the one question the shadow stage exists to answer.
        """
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-no-enrichable-events'
            # Passes the peek (sid + api_request_id + ts present) but carries
            # an unparseable timestamp pair, so enrichment drops every event.
            rec = _event_record(sid, f'{sid}:t1:api:1', OLD_TS, OLD_TS + 1)
            rec['ended_at'] = 'not-a-timestamp'
            rec['ts'] = OLD_TS
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), [rec])
            os.makedirs(ready_dir, exist_ok=True)
            open(os.path.join(ready_dir, sid), 'w').close()
            self._write_state_db(hh, [_session_row(sid, input_tokens=100, output_tokens=50)])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            rows = self._shadow_rows(sd)
            self.assertEqual(len(rows), 1,
                             f'a session with no enrichable events must still be reported '
                             f'so its platform stays visible in the aggregate: {rows!r}')
            self.assertEqual(rows[0]['gate'], 'no_valid_events')
            self.assertEqual(rows[0]['platform'], 'cli',
                             'the platform must survive so the bucket is not silently lost')
            self.assertEqual(len(self._completions(meter_log)), 0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_legacy_skipped_session_is_skipped_absolutely_in_live_mode(self):
        """The D-09 partition itself is unchanged where it matters: in live
        mode a legacy-owned session is returned on, ships nothing, and
        produces no shadow row. Falling through is a shadow-only behavior."""
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-legacy-skip-live'
            with open(os.path.join(sd, 'revenium-hermes.ledger'), 'w') as f:
                f.write(f'HERMES:{sid}:1234:1700000000.000:abc123\n')

            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'),
                         [_event_record(sid, f'{sid}:t1:api:1', OLD_TS, OLD_TS + 1)])
            self._write_state_db(hh, [_session_row(sid, input_tokens=100, output_tokens=50)])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log,
                                       extra_env={'REVENIUM_EVENT_METERING_MODE': 'live'})
            self.assertEqual(rc, 0, out)
            self.assertEqual(len(self._completions(meter_log)), 0,
                             'D-09 must still skip a legacy-owned session absolutely in live mode')
            self.assertEqual(len(self._ledger_lines(sd)), 0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_held_session_appears_with_zeroed_fields(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-held-shadow'
            now = time.time()
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'),
                         [_event_record(sid, f'{sid}:t1:api:1', now, now + 1)])
            self._write_state_db(hh, [_session_row(sid)])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            rows = self._shadow_rows(sd)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row['gate'], 'held')
            self.assertEqual(row['event_rows'], 0)
            self.assertEqual(row['event_total'], 0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class ProviderComparisonTests(ShadowReadoutTestBase):
    """Test 5 — a session whose event provider is a routing layer records
    DIFFERENT values in provider_event and provider_legacy_would_be."""

    def test_routing_layer_event_provider_differs_from_legacy_inference(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-provider-compare'
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), [
                _event_record(sid, f'{sid}:t1:api:1', OLD_TS, OLD_TS + 1,
                              provider='litellm', response_model='claude-sonnet-4-6'),
            ])
            # Legacy side: billing_provider='openrouter', model='gpt-4o' ->
            # the legacy heredoc's own inference resolves this to 'openai'.
            self._write_state_db(hh, [_session_row(
                sid, model='gpt-4o', billing_provider='openrouter',
                input_tokens=100, output_tokens=50,
            )])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            rows = self._shadow_rows(sd)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row['provider_event'], 'anthropic',
                             'the event path resolves its routing-layer provider via C-7')
            self.assertEqual(row['provider_legacy_would_be'], 'openai',
                             'the legacy side infers from model+billing_provider independently')
            self.assertNotEqual(row['provider_event'], row['provider_legacy_would_be'])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class UnrecognisedModeFallsBackToShadowTests(ShadowReadoutTestBase):
    """Test 6 — an unrecognised REVENIUM_EVENT_METERING_MODE value falls back
    to shadow and warns."""

    def test_unrecognised_mode_value_falls_back_and_warns(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-bogus-mode'
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'),
                         [_event_record(sid, f'{sid}:t1:api:1', OLD_TS, OLD_TS + 1)])
            self._write_state_db(hh, [_session_row(sid, input_tokens=100, output_tokens=50)])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(
                hh, sd, shim_home, meter_log, inv_log,
                extra_env={'REVENIUM_EVENT_METERING_MODE': 'bogus'},
            )
            self.assertEqual(rc, 0, out)

            self.assertEqual(len(self._completions(meter_log)), 0,
                             'an invalid mode value must fall back to the safe shadow default')
            rows = self._shadow_rows(sd)
            self.assertEqual(len(rows), 1)

            log_text = self._log_text(sd)
            self.assertIn('unrecognised value', log_text)
            self.assertIn("falling back to 'shadow'", log_text)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class LiveModeUnchangedTests(ShadowReadoutTestBase):
    """Live mode must behave exactly as plans 32-01/32-02 built it: the CLI
    is invoked, a ledger line is written, and no shadow row is ever
    produced."""

    def test_live_mode_ships_and_writes_no_shadow_row(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        try:
            self._build_default_shim(bin_dir)
            sid = 'sess-live-mode'
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'),
                         [_event_record(sid, f'{sid}:t1:api:1', OLD_TS, OLD_TS + 1)])
            self._write_state_db(hh, [_session_row(sid, input_tokens=100, output_tokens=50)])

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(
                hh, sd, shim_home, meter_log, inv_log,
                extra_env={'REVENIUM_EVENT_METERING_MODE': 'live'},
            )
            self.assertEqual(rc, 0, out)

            self.assertEqual(len(self._completions(meter_log)), 1)
            self.assertEqual(len(self._ledger_lines(sd)), 1)
            self.assertEqual(self._shadow_rows(sd), [],
                             'live mode must never write a shadow-comparison row')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
