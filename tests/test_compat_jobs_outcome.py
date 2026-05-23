"""COMPAT-01: argv-shape golden for `revenium jobs outcome` SUCCESS path.

Analog: tests/test_repository.py::test_cron_outcome_is_idempotent (lines 6096-6334) —
  structural skeleton ONLY. The analog's SHIFTING shim at lines 6158-6199 MUST NOT
  be copied here.
Source-of-truth: skills/revenium/scripts/hermes-report.sh:1095-1106.
Golden fixture: tests/fixtures/compat/jobs-outcome.golden.json.
Decisions: D-01..D-04.

Critical no-shift override note: build_shim from _compat_helpers uses the no-shift
design (PATTERNS lines 202-226). Every captured invocations[N] line in jobs_log
starts with the verb token (`jobs outcome compat-job-001 ...`). After argv_to_flags,
__verb is 'jobs', __subcommand is 'outcome', __positional_args is ['compat-job-001'].
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
    build_state_db,
    load_golden,
    run_script,
    SCRIPTS_DIR,
)


class TestCompatJobsOutcome(unittest.TestCase):
    def test_jobs_outcome_success_argv_matches_v12_golden(self):
        """One jobs outcome SUCCESS invocation must byte-match the golden.

        Pre-seeds the jobs ledger with JOB:compat-job-001:created:... so the outcome
        stage does not defer (OUTCOME-04 gate). Writes a job marker with status=SUCCESS.
        The shim captures all jobs invocations to jobs_log; we filter for outcome.
        """
        tmpdir = tempfile.mkdtemp(prefix='gsd-compat-jobs-outcome-')
        try:
            # --- Resolve paths ---
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')
            # Jobs ledger: JOBS_LEDGER_FILE = ${STATE_DIR}/revenium-jobs.ledger
            jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir, 'meter.log')
            jobs_log = os.path.join(tmpdir, 'jobs.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            shim = os.path.join(bin_dir, 'revenium')

            # --- Build synthetic state.db ---
            # started_at is far in the past so the session passes the settle-seconds
            # filter (age >= 120) without needing a markers-ready sentinel.
            build_state_db(state_db, [{
                'id': 'compat-sid-003',
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

            # --- Pre-seed the jobs ledger (OUTCOME-04 gate) ---
            # Without this, the outcome stage defers because JOB:...:created is absent.
            # The timestamp is a fixed past value to ensure the record passes the stale check.
            os.makedirs(os.path.dirname(jobs_ledger), exist_ok=True)
            with open(jobs_ledger, 'w') as f:
                f.write('JOB:compat-job-001:created:1715516001.000\n')

            # --- Write marker file: task marker + job marker with status=SUCCESS ---
            # Task marker gets owning_job_id = compat-job-001 via D-11 resolution.
            # Job marker status=SUCCESS populates the outcome queue (OUTCOME-05).
            task_marker = {
                'muid': 'compat-task-003',
                'ts': 1715516000.5,
                'sid': 'compat-sid-003',
                'task_type': 'code_review',
                'operation_type': 'CHAT',
            }
            job_marker = {
                'kind': 'job',
                'ts': 1715516002.0,
                'sid': 'compat-sid-003',
                'agentic_job_id': 'compat-job-001',
                'job_name': 'COMPAT Test Job',
                'job_type': 'code_review',
                'status': 'SUCCESS',
            }
            with open(os.path.join(markers_dir, 'compat-sid-003.jsonl'), 'w') as f:
                f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
                f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

            # --- Build no-shift shim ---
            build_shim(shim)

            # --- Env ---
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
                'REVENIUM_ORGANIZATION_NAME': '',
            }

            # --- Run hermes-report.sh ---
            rc, _ignored, output = run_script(
                SCRIPTS_DIR / 'hermes-report.sh', base_env, inv_log
            )

            self.assertEqual(
                rc, 0,
                f'hermes-report.sh failed (rc={rc}): {output}'
            )

            # --- Parse jobs_log and find the outcome invocation ---
            jobs_inv = []
            if os.path.exists(jobs_log):
                with open(jobs_log) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            jobs_inv.append(shlex.split(line))

            outcome_inv = [
                a for a in jobs_inv
                if len(a) >= 2 and a[0] == 'jobs' and a[1] == 'outcome'
            ]

            self.assertEqual(
                len(outcome_inv), 1,
                f'expected exactly 1 "jobs outcome" invocation, got {len(outcome_inv)}: '
                f'{outcome_inv!r}\nAll jobs_inv: {jobs_inv!r}\nOutput: {output}'
            )
            captured = outcome_inv[0]

            # --- No-shift contract: first three tokens must be 'jobs outcome compat-job-001' ---
            self.assertEqual(
                captured[0], 'jobs',
                f'COMPAT-01 no-shift violation: expected argv[0]="jobs" got '
                f'{captured[0]!r}\nFull argv: {captured}'
            )
            self.assertEqual(
                captured[1], 'outcome',
                f'COMPAT-01 no-shift violation: expected argv[1]="outcome" got '
                f'{captured[1]!r}\nFull argv: {captured}'
            )
            self.assertEqual(
                captured[2], 'compat-job-001',
                f'COMPAT-01 no-shift violation: expected argv[2]="compat-job-001" got '
                f'{captured[2]!r}\nFull argv: {captured}'
            )

            # --- Golden assert (exact_match + pattern + forbidden) ---
            # __positional_args = ['compat-job-001'] is asserted by the golden.
            assert_argv_matches_golden(
                self, captured, load_golden('jobs-outcome.golden.json')
            )

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
