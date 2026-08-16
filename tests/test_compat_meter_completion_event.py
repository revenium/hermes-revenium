"""COMPAT-02: argv-shape golden for the event-driven `revenium meter
completion` call shipped by skills/revenium/scripts/api-event-report.sh.

Sibling to tests/test_compat_meter_completion.py (COMPAT-01), per the process
tests/fixtures/compat/README.md already prescribes for a wire-shape change: a
NEW golden fixture and a NEW test class, leaving the four v1.x fixtures and
their runners byte-for-byte untouched (32-04-PLAN.md Task 1; 32-RESEARCH.md
Pitfall 6). This fixture is ADDITIVE to the v1.x contract, not a replacement —
it pins the event path's own argv shape, which is deliberately different in
several dimensions (see the golden's forbidden_fields).

Source-of-truth for the argv shape: skills/revenium/scripts/api-event-report.sh
(the `cmd=(...)` array construction and its conditional appends), as landed by
Phase 32 plans 32-01/32-02/32-03.

Golden fixture: tests/fixtures/compat/meter-completion-event.golden.json.
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


def _write_jsonl(path, records):
    with open(path, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, separators=(',', ':')) + '\n')


class TestCompatMeterCompletionEvent(unittest.TestCase):
    def test_event_meter_completion_argv_matches_golden(self):
        """One event-path `meter completion` invocation must byte-match the
        golden, and --model must be proven to come from the record's
        response_model field, not its (deliberately differing) model field.

        Exercises api-event-report.sh in live mode against a synthetic spool
        record + a paired GUARDRAIL/CHAT marker (the CHAT record carrying
        agentic_job_id) with a .ready sentinel already present, so the
        settle gate is satisfied by presence rather than age and the
        temporal join attributes the event to a real task/job.
        """
        tmpdir = tempfile.mkdtemp(prefix='gsd-compat-meter-completion-event-')
        try:
            # --- Resolve paths ---
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
            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            shim = os.path.join(bin_dir, 'revenium')

            sid = 'compat-event-sid-001'
            arid = 'compat-event-arid-001'

            # --- Settle gate satisfied by the sentinel, not by age ---
            Path(ready_dir, sid).touch()

            # --- One contract-C-2 spool record. `model` and `response_model`
            # are DELIBERATELY different — the falsifiable proof (ROADMAP
            # success criterion 4) that --model ships from response_model
            # (the model that actually served), never the record's `model`
            # field. ---
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), [{
                'v': 1, 'sid': sid, 'api_request_id': arid,
                'ts': 1715514000.5, 'ended_at': 1715514001.0,
                'duration_ms': 500, 'platform': 'cli',
                'model': 'compat-session-model-should-not-ship',
                'response_model': 'claude-sonnet-4-6',
                'provider': 'anthropic',
                'base_url': 'https://api.anthropic.com',
                'api_mode': 'anthropic_messages',
                'finish_reason': 'stop',
                'input_tokens': 100, 'output_tokens': 50,
                'cache_read_tokens': 10, 'cache_write_tokens': 5,
                'reasoning_tokens': 0, 'total_tokens': 165,
            }])

            # --- One GUARDRAIL + CHAT marker pair. The CHAT record carries
            # agentic_job_id directly (temporal join reads it from the
            # attributing marker itself, not from a separate job marker —
            # job markers carry kind="job" and are excluded from the
            # window-boundary list entirely). GUARDRAIL is excluded from the
            # window-boundary array per contract C-5a, so only the CHAT
            # window governs attribution. ---
            _write_jsonl(os.path.join(markers_dir, f'{sid}.jsonl'), [
                {'muid': 'compat-event-muid-001', 'ts': 1715513900.0,
                 'sid': sid, 'task_type': 'code_review',
                 'operation_type': 'GUARDRAIL'},
                {'muid': 'compat-event-muid-002', 'ts': 1715513900.5,
                 'sid': sid, 'task_type': 'code_review',
                 'operation_type': 'CHAT',
                 'agentic_job_id': 'compat-event-job-001'},
            ])

            # --- Build no-shift shim (default: squad-capable, so the squad
            # triple and --agentic-job-id are both advertised). ---
            build_shim(shim)

            base_env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'INVOCATIONS_LOG': inv_log,
                'METER_LOG': meter_log,
                'TZ': 'UTC',
                # Shadow is the C-9 default (ships nothing) — this test
                # exercises the LIVE argv construction, so it opts in
                # explicitly.
                'REVENIUM_EVENT_METERING_MODE': 'live',
            }

            # --- Run api-event-report.sh ---
            rc, _ignored_inv, output = run_script(
                SCRIPTS_DIR / 'api-event-report.sh', base_env, inv_log
            )

            # --- Parse meter_log directly ---
            meter_invocations = []
            if os.path.exists(meter_log):
                with open(meter_log) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            meter_invocations.append(shlex.split(line))

            self.assertEqual(
                rc, 0,
                f'api-event-report.sh failed (rc={rc}): {output}'
            )
            self.assertEqual(
                len(meter_invocations), 1,
                f'expected 1 meter completion invocation, got {len(meter_invocations)}: '
                f'{meter_invocations[:3]!r}\nOutput: {output}'
            )

            # --- No-shift contract: argv must begin with 'meter completion' ---
            captured = meter_invocations[0]
            self.assertEqual(
                captured[0], 'meter',
                f'COMPAT-02 no-shift violation: expected argv[0]="meter" got '
                f'{captured[0]!r}\nFull argv: {captured}'
            )
            self.assertEqual(
                captured[1], 'completion',
                f'COMPAT-02 no-shift violation: expected argv[1]="completion" got '
                f'{captured[1]!r}\nFull argv: {captured}'
            )

            # --- Golden assert (exact_match + pattern + forbidden) ---
            golden = load_golden('meter-completion-event.golden.json')
            assert_argv_matches_golden(self, captured, golden)

            # --- ROADMAP success criterion 4, made falsifiable directly
            # from this fixture: --model comes from response_model. ---
            flags = argv_to_flags(captured)
            self.assertEqual(
                flags.get('--model'), 'claude-sonnet-4-6',
                '--model must ship the RESPONSE model (the model that actually '
                'served this API call), not the record\'s session-level `model` '
                'field — the multi-model misattribution fix the event path exists to make.'
            )
            self.assertNotEqual(
                flags.get('--model'), 'compat-session-model-should-not-ship',
                '--model must NOT ship the record\'s `model` field verbatim'
            )

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
