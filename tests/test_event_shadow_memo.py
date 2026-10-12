"""Shadow memo in api-event-report.sh (EVENT_SHADOW_MEMO_FILE).

In shadow mode every legacy-owned spool file was fully re-enriched on every
tick (about 8 python3 spawns) only to append the same comparison row again:
~6 minutes per tick on a host with ~700 spool files (measured 172s for one
pass on a copy of that host's state, 5s with the memo warm, with the log and
all 701 rows identical apart from their timestamps). These tests pin that a
reused row is the row a full pass would have produced, and that anything the
row is computed from invalidates it.
"""
import json
import os
import shutil
import unittest

from tests.test_phase32_shadow_readout import (
    OLD_TS,
    ShadowReadoutTestBase,
    _event_record,
    _session_row,
    _write_jsonl,
)

SID = 'sess-shadow-memo'


class EventShadowMemoTests(ShadowReadoutTestBase):

    def _tree(self):
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home, bin_dir = self._setup_tree()
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        self._build_default_shim(bin_dir)
        with open(os.path.join(sd, 'revenium-hermes.ledger'), 'w') as f:
            f.write(f'HERMES:{SID}:150:1700000000.000:abc123\n')
        self.spool = os.path.join(spool_dir, f'{SID}.jsonl')
        _write_jsonl(self.spool, [_event_record(SID, f'{SID}:t1:api:1', OLD_TS, OLD_TS + 1)])
        self._write_state_db(hh, [_session_row(SID, input_tokens=100, output_tokens=50)])
        self.args = (hh, sd, shim_home, os.path.join(tmpdir, 'meter.log'),
                     os.path.join(tmpdir, 'inv.log'))
        return sd

    def _tick(self, extra_env=None):
        rc, _invs, out = self._run(*self.args, extra_env=extra_env)
        self.assertEqual(rc, 0, out)

    @staticmethod
    def _without_ts(row):
        return {k: v for k, v in row.items() if k != 'ts'}

    def test_unchanged_spool_file_reuses_the_identical_row(self):
        sd = self._tree()
        self._tick()
        self._tick()
        rows = self._shadow_rows(sd)
        self.assertEqual(2, len(rows))
        self.assertEqual(self._without_ts(rows[0]), self._without_ts(rows[1]),
                         'a reused row must be the row the full pass produced')
        log = self._log_text(sd)
        self.assertIn('memo: reused 1 unchanged shadow comparison row(s)', log)
        self.assertEqual(2, log.count(f'shadow: {SID} is legacy-owned (D-09)'),
                         'a hit must log the same per-session line as a full pass')
        self.assertEqual(2, log.count('legacy-skipped-sessions=1'))
        self.assertEqual([], self._completions(self.args[3]))
        self.assertEqual([], self._ledger_lines(sd))

    def test_appended_event_recomputes_the_row(self):
        sd = self._tree()
        self._tick()
        with open(self.spool, 'a', encoding='utf-8') as f:
            f.write(json.dumps(_event_record(SID, f'{SID}:t2:api:2', OLD_TS + 2, OLD_TS + 3),
                               separators=(',', ':')) + '\n')
        self._tick()
        rows = self._shadow_rows(sd)
        self.assertEqual(1, rows[0]['event_rows'])
        self.assertEqual(2, rows[1]['event_rows'], 'a grown spool file must be re-enriched')
        self.assertNotIn('memo: reused', self._log_text(sd))

    def test_new_legacy_ledger_line_recomputes_the_row(self):
        sd = self._tree()
        self._tick()
        with open(os.path.join(sd, 'revenium-hermes.ledger'), 'a') as f:
            f.write(f'HERMES:{SID}:300:1700000100.000:def456\n')
        self._tick()
        rows = self._shadow_rows(sd)
        self.assertEqual(1, rows[0]['legacy_ledger_lines'])
        self.assertEqual(2, rows[1]['legacy_ledger_lines'])
        self.assertEqual(300, rows[1]['legacy_last_total_tokens'])

    def test_disabled_switch_writes_no_memo(self):
        sd = self._tree()
        self._tick({'REVENIUM_REPORTER_MEMO': 'disabled'})
        self._tick({'REVENIUM_REPORTER_MEMO': 'disabled'})
        self.assertFalse(os.path.exists(os.path.join(sd, 'event-shadow-memo.jsonl')))
        self.assertEqual(2, len(self._shadow_rows(sd)))

    def test_live_mode_never_consults_the_memo(self):
        sd = self._tree()
        self._tick({'REVENIUM_EVENT_METERING_MODE': 'live'})
        self._tick({'REVENIUM_EVENT_METERING_MODE': 'live'})
        self.assertFalse(os.path.exists(os.path.join(sd, 'event-shadow-memo.jsonl')))
        self.assertNotIn('memo:', self._log_text(sd))


if __name__ == '__main__':
    unittest.main()
