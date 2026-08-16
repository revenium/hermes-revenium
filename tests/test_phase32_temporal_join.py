"""Phase 32 Plan 02, Task 2 (EVT-04/EVT-05) — the temporal marker join.

Proves contract C-5/C-5a/D-14: each event is attributed to the marker window
[marker_i.ts, marker_{i+1}.ts) containing the event's own timestamp; events
before the first WINDOW-OWNING marker extend that window backward. GUARDRAIL
records are excluded from the window-boundary list (C-5a: they are
classification bookkeeping written microseconds before their paired CHAT
record, sharing the identical task_type), so a real API call — always chat
completion work on this event path — lands on the CHAT window, including
events that precede the classification pair entirely. This is the
deterministic shape of every session's opening turn, not an edge case.

Every test in this module sets a `.ready/<sid>` sentinel so the C-6 settle
gate (tested separately in test_phase32_event_ledger_idempotency.py) never
interferes with what these tests are actually proving.
"""
import json
import os
import shlex
import shutil
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


def _muid(tag):
    """A 33-char lowercase-hex-shaped placeholder muid, distinct per tag."""
    base = f'{abs(hash(tag)):x}'
    return (base + '0' * 33)[:33]


def _marker_pair(sid, task_type, ts_g, ts_c, extra=None):
    g = {
        'muid': _muid(f'g{sid}{ts_g}'), 'ts': ts_g, 'sid': sid,
        'task_type': task_type, 'operation_type': 'GUARDRAIL', 'trace_id': sid,
    }
    c = {
        'muid': _muid(f'c{sid}{ts_c}'), 'ts': ts_c, 'sid': sid,
        'task_type': task_type, 'operation_type': 'CHAT', 'trace_id': sid,
    }
    if extra:
        g.update(extra)
        c.update(extra)
    return [g, c]


class TemporalJoinTestBase(unittest.TestCase):
    def _setup_tree(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-join-')
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
        shim = os.path.join(bin_dir, 'revenium')
        build_shim(shim)

        return tmpdir, hermes_home, state_dir, spool_dir, markers_dir, ready_dir, shim_home

    def _run(self, hermes_home, state_dir, shim_home, meter_log, inv_log):
        env = {
            **os.environ,
            'HOME': shim_home,
            'HERMES_HOME': hermes_home,
            'REVENIUM_STATE_DIR': state_dir,
            'PATH': os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': inv_log,
            'METER_LOG': meter_log,
            'TZ': 'UTC',
            # Phase 32 Plan 03 (C-9): REVENIUM_EVENT_METERING_MODE now
            # defaults to "shadow" (ships nothing) — this module tests the
            # LIVE shipping/temporal-join behavior plans 32-01/32-02 built,
            # so it opts in explicitly rather than silently asserting on a
            # shadow run that ships zero completions.
            'REVENIUM_EVENT_METERING_MODE': 'live',
        }
        return run_script(SCRIPTS_DIR / 'api-event-report.sh', env, inv_log)

    def _completions(self, meter_log):
        invs = []
        if os.path.exists(meter_log):
            with open(meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        invs.append(shlex.split(line))
        return [a for a in invs if len(a) >= 2 and a[0] == 'meter' and a[1] == 'completion']


class SingleMarkerPairWindowTests(TemporalJoinTestBase):
    """Test 1 — a single GUARDRAIL+CHAT pair; events before, at, and after
    the pair's own timestamps all land on the CHAT window and carry its
    task_type, including the pre-classification (before ts_g) event."""

    def test_events_before_at_after_all_attribute_to_chat_window(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home = self._setup_tree()
        try:
            sid = 'sess-single-pair'
            Path(ready_dir, sid).touch()

            ts_g, ts_c = 1000000.0, 1000000.001
            _write_jsonl(
                os.path.join(markers_dir, f'{sid}.jsonl'),
                _marker_pair(sid, 'code_review', ts_g, ts_c),
            )

            events = [
                _event_record(sid, f'{sid}:t1:api:1', 999990.0, 999990.5),      # before ts_g
                _event_record(sid, f'{sid}:t1:api:2', ts_c, 1000000.6),          # exactly at ts_c
                _event_record(sid, f'{sid}:t1:api:3', 1000005.0, 1000005.5),     # after
            ]
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), events)

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            completions = self._completions(meter_log)
            self.assertEqual(len(completions), 3, f'expected 3 completions, got {completions!r}')
            for argv in completions:
                flags = argv_to_flags(argv)
                self.assertEqual(flags.get('--task-type'), 'code_review')
                self.assertEqual(flags.get('--operation-type'), 'CHAT',
                                 f'pre-classification/at/after event must land on the CHAT '
                                 f'window (C-5a), not GUARDRAIL: {argv}')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TwoMarkerPairsWindowTests(TemporalJoinTestBase):
    """Test 2 — two pairs written minutes apart; events between them take
    the first pair's label, events after take the second's."""

    def test_middle_and_trailing_events_attribute_to_the_correct_pair(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home = self._setup_tree()
        try:
            sid = 'sess-two-pairs'
            Path(ready_dir, sid).touch()

            ts_g1, ts_c1 = 1000000.0, 1000000.001
            ts_g2, ts_c2 = 1000180.0, 1000180.001  # 3 minutes later
            records = (
                _marker_pair(sid, 'research', ts_g1, ts_c1)
                + _marker_pair(sid, 'code_review', ts_g2, ts_c2)
            )
            _write_jsonl(os.path.join(markers_dir, f'{sid}.jsonl'), records)

            events = [
                _event_record(sid, f'{sid}:t1:api:1', 1000090.0, 1000090.5),   # between pairs
                _event_record(sid, f'{sid}:t2:api:1', 1000200.0, 1000200.5),   # after 2nd pair
            ]
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), events)

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            completions = self._completions(meter_log)
            self.assertEqual(len(completions), 2, f'expected 2 completions, got {completions!r}')

            by_arid = {}
            for argv in completions:
                flags = argv_to_flags(argv)
                by_arid[flags.get('--transaction-id')] = flags

            middle = by_arid[f'event:{sid}:t1:api:1']
            trailing = by_arid[f'event:{sid}:t2:api:1']
            self.assertEqual(middle.get('--task-type'), 'research',
                             'event between two pairs must take the FIRST pair\'s label')
            self.assertEqual(trailing.get('--task-type'), 'code_review',
                             'event after the second pair must take the SECOND pair\'s label')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class NoMarkersUnclassifiedTests(TemporalJoinTestBase):
    """Test 3 — an empty marker file and a missing marker file, both with a
    sentinel present, both fall back to unclassified/CHAT (C-5b)."""

    def _run_zero_marker_case(self, write_empty_file):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home = self._setup_tree()
        try:
            sid = 'sess-empty-markers' if write_empty_file else 'sess-missing-markers'
            Path(ready_dir, sid).touch()

            if write_empty_file:
                Path(markers_dir, f'{sid}.jsonl').touch()
            # else: no marker file at all — missing case.

            events = [_event_record(sid, f'{sid}:t1:api:1', 1000000.0, 1000000.5)]
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), events)

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

    def test_empty_marker_file_falls_back_to_unclassified(self):
        self._run_zero_marker_case(write_empty_file=True)

    def test_missing_marker_file_falls_back_to_unclassified(self):
        self._run_zero_marker_case(write_empty_file=False)


class UnparseableMarkerLineToleranceTests(TemporalJoinTestBase):
    """Test 4 — a marker file with one unparseable line among good ones;
    the good ones still drive the join."""

    def test_one_bad_line_does_not_break_the_join_for_good_lines(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home = self._setup_tree()
        try:
            sid = 'sess-bad-line'
            Path(ready_dir, sid).touch()

            ts_g, ts_c = 1000000.0, 1000000.001
            good = _marker_pair(sid, 'planning', ts_g, ts_c)
            marker_path = os.path.join(markers_dir, f'{sid}.jsonl')
            with open(marker_path, 'w', encoding='utf-8') as f:
                f.write(json.dumps(good[0], separators=(',', ':')) + '\n')
                f.write('{not valid json at all\n')
                f.write(json.dumps(good[1], separators=(',', ':')) + '\n')

            events = [_event_record(sid, f'{sid}:t1:api:1', 1000005.0, 1000005.5)]
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), events)

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            completions = self._completions(meter_log)
            self.assertEqual(len(completions), 1, f'expected 1 completion, got {completions!r}')
            flags = argv_to_flags(completions[0])
            self.assertEqual(flags.get('--task-type'), 'planning')
            self.assertEqual(flags.get('--operation-type'), 'CHAT')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class SubagentAgenticJobIdTests(TemporalJoinTestBase):
    """Test 5 — a subagent marker carrying agentic_job_id; the flag reaches
    argv when the shim advertises --agentic-job-id capability (default)."""

    def test_agentic_job_id_from_matched_marker_reaches_argv(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home = self._setup_tree()
        try:
            sid = 'sess-subagent-job'
            Path(ready_dir, sid).touch()

            ts_g, ts_c = 1000000.0, 1000000.001
            records = _marker_pair(
                sid, 'bug_fix', ts_g, ts_c, extra={'agentic_job_id': 'fix_auth_a1b2'},
            )
            _write_jsonl(os.path.join(markers_dir, f'{sid}.jsonl'), records)

            events = [_event_record(sid, f'{sid}:t1:api:1', 1000005.0, 1000005.5)]
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), events)

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            completions = self._completions(meter_log)
            self.assertEqual(len(completions), 1, f'expected 1 completion, got {completions!r}')
            flags = argv_to_flags(completions[0])
            self.assertEqual(flags.get('--agentic-job-id'), 'fix_auth_a1b2')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class C5aConsequenceTests(TemporalJoinTestBase):
    """The explicit C-5a consequence test named at the end of Task 2: one
    classification plus three events produces three `meter completion`
    calls, all `--operation-type CHAT`, whose token sums equal the three
    events' token sums exactly. This is what makes the row-count and
    operation-type change a recorded decision rather than a surprise."""

    def test_one_classification_three_events_three_chat_rows_conserved_tokens(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home = self._setup_tree()
        try:
            sid = 'sess-c5a'
            Path(ready_dir, sid).touch()

            ts_g, ts_c = 1000000.0, 1000000.001
            _write_jsonl(
                os.path.join(markers_dir, f'{sid}.jsonl'),
                _marker_pair(sid, 'code_review', ts_g, ts_c),
            )

            events = [
                _event_record(sid, f'{sid}:t1:api:1', 999995.0, 999995.5,
                              input_tokens=100, output_tokens=20, total_tokens=120),
                _event_record(sid, f'{sid}:t1:api:2', 1000001.0, 1000001.5,
                              input_tokens=200, output_tokens=40, total_tokens=240),
                _event_record(sid, f'{sid}:t2:api:1', 1000010.0, 1000010.5,
                              input_tokens=300, output_tokens=60, total_tokens=360),
            ]
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), events)

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)

            completions = self._completions(meter_log)
            self.assertEqual(len(completions), 3, f'expected 3 completions, got {completions!r}')

            shipped_total = 0
            for argv in completions:
                flags = argv_to_flags(argv)
                self.assertEqual(flags.get('--operation-type'), 'CHAT')
                shipped_total += int(flags.get('--total-tokens'))

            expected_total = sum(e['total_tokens'] for e in events)
            self.assertEqual(shipped_total, expected_total,
                             'token sums across shipped rows must equal the events\' sums exactly')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
