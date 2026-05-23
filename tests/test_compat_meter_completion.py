"""COMPAT-01: argv-shape golden for `revenium meter completion`.

Analog: tests/test_repository.py::test_cron_marker_split_end_to_end (lines 1024-1417).
Source-of-truth for the argv shape: skills/revenium/scripts/hermes-report.sh:910-931
  (per-marker happy path) and conditional-append range 473-495.
Golden fixture: tests/fixtures/compat/meter-completion.golden.json.
Locked decisions: D-01 (golden-argv unit test), D-02 (reconstruct from script source),
  D-03 (one canonical happy-path golden per verb), D-04 (exact_match + pattern_fields
  allowlist).

Critical no-shift override note: build_shim from _compat_helpers uses the no-shift
design (PATTERNS lines 202-226). The analog's shim at test_repository.py:1116-1162
uses `shift; shift` (SHIFTING design) and is referenced for OVERALL test STRUCTURE
only. Every captured invocations[N] line starts with the verb token (`meter
completion ...`). After argv_to_flags(invocations[0]), __verb is 'meter' and
__subcommand is 'completion' — both asserted by the golden's exact_match_fields.
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tests._compat_helpers import (
    assert_argv_matches_golden,
    build_shim,
    build_state_db,
    load_golden,
    run_script,
    SCRIPTS_DIR,
)


class TestCompatMeterCompletion(unittest.TestCase):
    def test_meter_completion_per_marker_argv_matches_v12_golden(self):
        """One per-marker meter completion invocation must byte-match the golden.

        Exercises hermes-report.sh against a synthetic state.db with ONE session
        (compat-sid-001, 150 tokens) and ONE marker pinned to compat-muid-001 so
        --transaction-id is deterministic as compat-sid-001-150-compat-muid-001.
        The no-shift shim captures the full argv starting with 'meter completion'.
        """
        tmpdir = tempfile.mkdtemp(prefix='gsd-compat-meter-completion-')
        try:
            # --- Resolve paths ---
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')

            # Shim lives at ${shim_home}/.local/bin/revenium — ensure_path's last
            # prepend wins so the shim is first in PATH.
            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir, 'meter.log')
            jobs_log = os.path.join(tmpdir, 'jobs.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            shim = os.path.join(bin_dir, 'revenium')

            # --- Build synthetic state.db ---
            # started_at is far in the past so it passes the settle-seconds filter
            # (age >= 120) without needing a markers-ready sentinel.
            # started_at == ended_at so duration_ms = 0 (matching the golden).
            build_state_db(state_db, [{
                'id': 'compat-sid-001',
                'model': 'claude-sonnet-4-6',
                'source': 'test',
                'input_tokens': 100,
                'output_tokens': 50,
                'cache_read': 0,
                'cache_write': 0,
                'reasoning': 0,
                'estimated_cost': '0',
                'api_calls': 1,
                'started_at': 1715514000.0,
                'ended_at': 1715514000.0,
                'billing_provider': 'anthropic',
            }])

            # --- Write ONE task marker + ONE job marker ---
            # Per D-11/D-12: a task marker gets owning_job_id from the first job
            # marker appearing AFTER it in file order. The job marker must have
            # kind="job" and appear on a separate JSONL line after the task marker.
            # Pinned muid produces transaction-id compat-sid-001-150-compat-muid-001.
            task_marker = {
                'muid': 'compat-muid-001',
                'ts': 1715515000.5,
                'sid': 'compat-sid-001',
                'task_type': 'code_review',
                'operation_type': 'CHAT',
            }
            job_marker = {
                'kind': 'job',
                'ts': 1715515001.0,
                'sid': 'compat-sid-001',
                'agentic_job_id': 'compat-job-001',
                'job_name': 'COMPAT Test Job',
                'job_type': 'code_review',
                'status': 'IN_PROGRESS',
            }
            with open(os.path.join(markers_dir, 'compat-sid-001.jsonl'), 'w') as f:
                f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
                f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

            # --- Build no-shift shim ---
            build_shim(shim)

            # --- Env: METER_LOG and JOBS_LOG are separate so we can assert on meter only ---
            base_env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'INVOCATIONS_LOG': inv_log,
                'METER_LOG': meter_log,
                'JOBS_LOG': jobs_log,
                'TZ': 'UTC',
                # Suppress --organization-name conditional
                'REVENIUM_ORGANIZATION_NAME': '',
            }

            # --- Run hermes-report.sh ---
            rc, _ignored_inv, output = run_script(
                SCRIPTS_DIR / 'hermes-report.sh', base_env, inv_log
            )

            # --- Parse meter_log directly ---
            import shlex as _shlex
            meter_invocations = []
            if os.path.exists(meter_log):
                with open(meter_log) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            meter_invocations.append(_shlex.split(line))

            self.assertEqual(
                rc, 0,
                f'hermes-report.sh failed (rc={rc}): {output}'
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
                f'COMPAT-01 no-shift violation: expected argv[0]="meter" got '
                f'{captured[0]!r}\nFull argv: {captured}'
            )
            self.assertEqual(
                captured[1], 'completion',
                f'COMPAT-01 no-shift violation: expected argv[1]="completion" got '
                f'{captured[1]!r}\nFull argv: {captured}'
            )

            # --- Golden assert (exact_match + pattern + forbidden) ---
            assert_argv_matches_golden(
                self, captured, load_golden('meter-completion.golden.json')
            )

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
