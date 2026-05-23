"""COMPAT-01: argv-shape golden for `revenium jobs create`.

Analog: tests/test_repository.py::test_jobs_create_loop_e2e (lines 4886-5135) —
  structural skeleton ONLY. The analog's shim at test_repository.py:4976-5006 uses
  `shift; shift` (SHIFTING design) and MUST NOT be copied here.
Source-of-truth: skills/revenium/scripts/hermes-report.sh:776-790.
Golden fixture: tests/fixtures/compat/jobs-create.golden.json.
Decisions: D-01..D-04.

Critical no-shift override note: build_shim from _compat_helpers uses the no-shift
design (PATTERNS lines 202-226). Every captured invocations[N] line in jobs_log
starts with the verb token (`jobs create ...`). After argv_to_flags, __verb is 'jobs'
and __subcommand is 'create' — both asserted by the golden's exact_match_fields.
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


class TestCompatJobsCreate(unittest.TestCase):
    def test_jobs_create_argv_matches_v12_golden(self):
        """One jobs create invocation must byte-match the golden.

        Exercises hermes-report.sh with ONE session (compat-sid-002) and a marker
        file containing a task marker followed by a job marker pinned to
        compat-job-001. The shim routes jobs captures to jobs_log and meter
        captures to meter_log so the assertion is unambiguous.
        """
        tmpdir = tempfile.mkdtemp(prefix='gsd-compat-jobs-create-')
        try:
            # --- Resolve paths ---
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')

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
            # source='test' supplies --environment test in both jobs create and
            # meter completion calls.
            build_state_db(state_db, [{
                'id': 'compat-sid-002',
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

            # --- Write marker file: task marker + job marker ---
            # The task marker (no kind field) gets owning_job_id from the job
            # marker that follows it in file order (D-11/D-12).
            # The job marker triggers a jobs create call (D-08/D-09).
            task_marker = {
                'muid': 'compat-task-001',
                'ts': 1715515100.5,
                'sid': 'compat-sid-002',
                'task_type': 'code_review',
                'operation_type': 'CHAT',
            }
            job_marker = {
                'kind': 'job',
                'ts': 1715515101.0,
                'sid': 'compat-sid-002',
                'agentic_job_id': 'compat-job-001',
                'job_name': 'COMPAT Test Job',
                'job_type': 'code_review',
                'status': 'IN_PROGRESS',
            }
            with open(os.path.join(markers_dir, 'compat-sid-002.jsonl'), 'w') as f:
                f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
                f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

            # --- Build no-shift shim ---
            build_shim(shim)

            # --- Env: separate JOBS_LOG and METER_LOG so we assert only on jobs ---
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

            # --- Parse jobs_log ---
            jobs_inv = []
            if os.path.exists(jobs_log):
                with open(jobs_log) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            jobs_inv.append(shlex.split(line))

            self.assertGreaterEqual(
                len(jobs_inv), 1,
                f'expected at least one jobs invocation in jobs_log, got 0\nOutput: {output}'
            )

            # --- No-shift contract: argv must begin with 'jobs create' ---
            # Find the jobs create invocation.
            jobs_create_inv = [
                a for a in jobs_inv
                if len(a) >= 2 and a[0] == 'jobs' and a[1] == 'create'
            ]
            self.assertGreaterEqual(
                len(jobs_create_inv), 1,
                f'no "jobs create" argv found in jobs_log; captured: {jobs_inv!r}'
            )
            captured = jobs_create_inv[0]

            self.assertEqual(
                captured[0], 'jobs',
                f'COMPAT-01 no-shift violation: expected argv[0]="jobs" got '
                f'{captured[0]!r}\nFull argv: {captured}'
            )
            self.assertEqual(
                captured[1], 'create',
                f'COMPAT-01 no-shift violation: expected argv[1]="create" got '
                f'{captured[1]!r}\nFull argv: {captured}'
            )

            # --- Golden assert (exact_match + pattern + forbidden) ---
            assert_argv_matches_golden(
                self, captured, load_golden('jobs-create.golden.json')
            )

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
