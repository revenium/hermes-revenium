"""COMPAT-01: argv-shape golden for `revenium meter tool-event` success path.

Analog: tests/test_repository.py::test_tool_event_reporter_reads_jsonl
  (lines 9331-9422) — structural skeleton ONLY. The analog's shim uses
  `printf "%s" "$*"` (lossy) and is NOT to be copied here.
Source-of-truth: skills/revenium/scripts/tool-event-report.sh:125-146.
Golden fixture: tests/fixtures/compat/meter-tool-event.golden.json.
Decisions: D-01..D-04.
Note: the tool-event analog uses `printf %s $*` (lossy) and may shift; this test
uses the no-shift `printf %q` body from PATTERNS lines 202-226 via build_shim
for round-trip safety and verb-token preservation.

Critical no-shift override note: build_shim from _compat_helpers uses the no-shift
design (PATTERNS lines 202-226). Every captured invocations[N] line in tool_log
starts with the verb token (`meter tool-event ...`). After argv_to_flags,
__verb is 'meter' and __subcommand is 'tool-event'.
"""
import json
import os
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path

from tests._compat_helpers import (
    argv_to_flags,
    assert_argv_matches_golden,
    build_shim,
    load_golden,
    run_script,
    SCRIPTS_DIR,
)


class TestCompatMeterToolEvent(unittest.TestCase):
    def test_meter_tool_event_success_argv_matches_v12_golden(self):
        """One meter tool-event success invocation must byte-match the golden.

        Exercises tool-event-report.sh with a synthetic tool-events JSONL containing
        ONE success record. The no-shift shim routes tool-event captures to TOOL_LOG.
        Asserts bare --success flag (not --success=true) and --error-message absent.
        """
        tmpdir = tempfile.mkdtemp(prefix='gsd-compat-tool-event-')
        try:
            # --- Resolve paths ---
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            # TOOL_EVENTS_DIR = ${STATE_DIR}/tool-events (common.sh:32)
            tool_events_dir = os.path.join(state_dir, 'tool-events')
            os.makedirs(tool_events_dir, mode=0o700)

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            tool_log = os.path.join(tmpdir, 'tool.log')
            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            shim = os.path.join(bin_dir, 'revenium')

            # --- Write success JSONL ---
            # sid used as --trace-id; tool is --tool-id; duration_ms is --duration-ms.
            # success=True triggers bare --success (no value) per tool-event-report.sh:136.
            event = {
                'sid': 'compat-sid-001',
                'ts': 1715515000.0,
                'tool': 'compat-tool',
                'tool_call_id': 'compat-tool-001',
                'duration_ms': 42,
                'success': True,
                'error': None,
            }
            with open(os.path.join(tool_events_dir, 'compat-sid-001.jsonl'), 'w') as f:
                f.write(json.dumps(event, separators=(',', ':')) + '\n')

            # --- Build no-shift shim ---
            build_shim(shim)

            # --- Env: TOOL_LOG routes meter tool-event captures ---
            base_env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'INVOCATIONS_LOG': inv_log,
                'TOOL_LOG': tool_log,
                'METER_LOG': meter_log,
                'TZ': 'UTC',
                'REVENIUM_ORGANIZATION_NAME': '',
            }

            # --- Run tool-event-report.sh ---
            rc, _ignored, output = run_script(
                SCRIPTS_DIR / 'tool-event-report.sh', base_env, inv_log
            )

            self.assertEqual(
                rc, 0,
                f'tool-event-report.sh failed (rc={rc}): {output}'
            )

            # --- Parse tool_log ---
            tool_inv = []
            if os.path.exists(tool_log):
                with open(tool_log) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            tool_inv.append(shlex.split(line))

            self.assertGreaterEqual(
                len(tool_inv), 1,
                f'expected at least one tool-event invocation in tool_log, '
                f'got 0\nOutput: {output}'
            )

            # --- Find the meter tool-event invocation ---
            tool_event_inv = [
                a for a in tool_inv
                if len(a) >= 2 and a[0] == 'meter' and a[1] == 'tool-event'
            ]
            self.assertGreaterEqual(
                len(tool_event_inv), 1,
                f'no "meter tool-event" argv found; captured: {tool_inv!r}'
            )
            captured = tool_event_inv[0]

            # --- No-shift contract: argv must begin with 'meter tool-event' ---
            self.assertEqual(
                captured[0], 'meter',
                f'COMPAT-01 no-shift violation: expected argv[0]="meter" got '
                f'{captured[0]!r}\nFull argv: {captured}'
            )
            self.assertEqual(
                captured[1], 'tool-event',
                f'COMPAT-01 no-shift violation: expected argv[1]="tool-event" got '
                f'{captured[1]!r}\nFull argv: {captured}'
            )

            # --- Golden assert (exact_match + pattern + forbidden) ---
            # Critical: --success is a bare flag (True), not --success=true (string).
            # The forbidden_fields check proves --error-message is absent on success path.
            assert_argv_matches_golden(
                self, captured, load_golden('meter-tool-event.golden.json')
            )

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
