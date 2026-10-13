"""tool-event-report.sh must not pay the root-session lookup for ledgered rows.

Regression for 2026-10-10: on a profile with ~40k ledgered tool events the
reporter resolved get_root_session_id (a python3 + state.db spawn) for every
row before its per-row ledger grep, so a tick that shipped nothing took 52
minutes and blocked every later cron stage.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
REPORTER = SKILL / 'scripts' / 'tool-event-report.sh'


class ToolEventLedgerPrefilterTests(unittest.TestCase):

    def _run(self, records, ledger_lines, files=None):
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, True)
        state_dir = os.path.join(tmpdir, 'state', 'revenium')
        tool_events_dir = os.path.join(state_dir, 'tool-events')
        os.makedirs(tool_events_dir)
        for name, recs in (files or {'sess_abc.jsonl': records}).items():
            with open(os.path.join(tool_events_dir, name), 'w') as f:
                for r in recs:
                    f.write(json.dumps(r) + '\n')
        ledger_path = os.path.join(state_dir, 'revenium-tool-events.ledger')
        with open(ledger_path, 'w') as f:
            f.writelines(line + '\n' for line in ledger_lines)

        bin_dir = os.path.join(tmpdir, 'home', '.local', 'bin')
        os.makedirs(bin_dir)
        capture_log = os.path.join(tmpdir, 'capture.log')
        python_log = os.path.join(tmpdir, 'python.log')
        with open(os.path.join(bin_dir, 'revenium'), 'w') as f:
            f.write('#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  meter) printf "%s\\n" "$*" >> "$CAPTURE_LOG" ;;\n'
                    'esac\n'
                    'exit 0\n')
        # python3 shim: log argv, then exec the real interpreter.
        real_python = shutil.which('python3')
        with open(os.path.join(bin_dir, 'python3'), 'w') as f:
            f.write('#!/usr/bin/env bash\n'
                    'printf "%s\\n" "$*" >> "$PYTHON_LOG"\n'
                    f'exec "{real_python}" "$@"\n')
        for name in ('revenium', 'python3'):
            os.chmod(os.path.join(bin_dir, name), 0o755)

        env = {
            **os.environ,
            'HOME': os.path.join(tmpdir, 'home'),
            'HERMES_HOME': os.path.join(tmpdir, 'hh'),
            'REVENIUM_STATE_DIR': state_dir,
            'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            'CAPTURE_LOG': capture_log,
            'PYTHON_LOG': python_log,
        }
        result = subprocess.run(['bash', str(REPORTER)], env=env,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        def lines(path):
            if not os.path.exists(path):
                return []
            with open(path) as fh:
                return [l.strip() for l in fh if l.strip()]

        with open(os.path.join(state_dir, 'revenium-metering.log')) as fh:
            log = fh.read()
        return lines(capture_log), lines(python_log), lines(ledger_path), log

    @staticmethod
    def _record(tcid):
        return {"sid": "sess_abc", "ts": 1747700000.0, "tool": "terminal",
                "tool_call_id": tcid, "duration_ms": 10, "success": True,
                "error": None}

    def test_ledgered_rows_skip_root_session_lookup(self):
        ledgered = [f'toolu_{i:03d}' for i in range(50)]
        records = [self._record(t) for t in ledgered] + [self._record('toolu_new')]
        ledger = [f'TOOL:sess_abc:{t}:1747700000.0' for t in ledgered]

        meter_calls, python_calls, ledger_after, log = self._run(records, ledger)

        root_lookups = [c for c in python_calls if 'get-root-session-id.py' in c]
        self.assertLessEqual(len(root_lookups), 1,
                             f'root lookup must run only for the new row; got {root_lookups}')
        self.assertEqual(len(meter_calls), 1, meter_calls)
        self.assertTrue(any(l.startswith('TOOL:sess_abc:toolu_new:') for l in ledger_after),
                        ledger_after[-3:])
        self.assertIn('Reported 1, skipped 50', log)
        self.assertEqual(len(ledger_after), 51)

    def test_same_run_duplicate_ships_once(self):
        # The pre-filter snapshot cannot see lines appended during the run;
        # the per-row grep guard must still stop a duplicate in the same file.
        records = [self._record('toolu_dup'), self._record('toolu_dup')]

        meter_calls, _, ledger_after, log = self._run(records, [])

        self.assertEqual(len(meter_calls), 1, meter_calls)
        self.assertEqual(len([l for l in ledger_after if l.startswith('TOOL:sess_abc:toolu_dup:')]), 1)
        self.assertIn('Reported 1, skipped 1', log)

    def test_spool_files_share_one_python_pass(self):
        # Regression for 2026-10-12: one interpreter per spool file, each
        # re-reading the whole TOOL ledger, cost 55s a tick on 676 files.
        files = {f'sess_{i:02d}.jsonl': [self._record(f'toolu_{i:02d}')] for i in range(20)}
        ledger = [f'TOOL:sess_abc:toolu_{i:02d}:1747700000.0' for i in range(20)]
        files = {name: [dict(recs[0], sid='sess_abc')] for name, recs in files.items()}

        meter_calls, python_calls, _, log = self._run([], ledger, files=files)

        heredoc_passes = [c for c in python_calls if c == '-']
        self.assertEqual(len(heredoc_passes), 1,
                         f'all spool files must be read in one pass; got {len(heredoc_passes)}')
        self.assertEqual(meter_calls, [])
        self.assertIn('Reported 0, skipped 20', log)

    def test_a_file_that_raises_does_not_stop_the_files_after_it(self):
        # A non-numeric duration_ms raises inside the pass. It used to end only
        # its own file's interpreter; with one pass for every file it must
        # still end only its own file.
        bad = dict(self._record('toolu_bad'), duration_ms='not-a-number')
        files = {
            'a_bad.jsonl': [self._record('toolu_a1'), bad, self._record('toolu_a2')],
            'b_good.jsonl': [self._record('toolu_b1')],
        }

        meter_calls, _, ledger_after, _ = self._run([], [], files=files)

        shipped = [l.split(':')[2] for l in ledger_after]
        self.assertIn('toolu_a1', shipped, 'rows before the bad line still ship')
        self.assertNotIn('toolu_a2', shipped, 'the rest of the bad file is dropped, as before')
        self.assertIn('toolu_b1', shipped, 'a later file must not be dropped with it')
        self.assertEqual(len(meter_calls), 2, meter_calls)


if __name__ == '__main__':
    unittest.main()
