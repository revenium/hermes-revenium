"""Behavioral coverage for the --metadata flag on `revenium jobs outcome`.

quick-260531-n4i: every job outcome ships a --metadata JSON carrying the session
`source` (deployment environment); a FAILED arc additionally carries the
classifier-supplied `failure_reason`. SUCCESS/CANCELLED arcs carry source only —
that side is locked by tests/fixtures/compat/jobs-outcome.golden.json (anchored
^{"source":"test"}$).

Source-of-truth: skills/revenium/scripts/hermes-report.sh post-loop outcome stage.
Reuses the no-shift shim + synthetic state.db harness from _compat_helpers.
"""
import json
import os
import shlex
import shutil
import tempfile
import unittest

from tests._compat_helpers import (
    build_shim,
    build_state_db,
    run_script,
    SCRIPTS_DIR,
)


class TestJobsOutcomeMetadata(unittest.TestCase):
    def _run_one_outcome(self, status, failure_reason, source):
        """Drive hermes-report.sh for a single job arc and return the parsed
        `jobs outcome` argv (or None). Caller asserts on the --metadata value."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-outcome-meta-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')
            jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir, 'meter.log')
            jobs_log = os.path.join(tmpdir, 'jobs.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            shim = os.path.join(bin_dir, 'revenium')

            sid = 'meta-sid-001'
            job_id = 'meta-job-001'

            build_state_db(state_db, [{
                'id': sid,
                'model': 'claude-sonnet-4-6',
                'source': source,
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

            # Pre-seed created line so the outcome stage does not defer (OUTCOME-04).
            os.makedirs(os.path.dirname(jobs_ledger), exist_ok=True)
            with open(jobs_ledger, 'w') as f:
                f.write(f'JOB:{job_id}:created:1715516001.000\n')

            task_marker = {
                'muid': 'meta-task-001',
                'ts': 1715516000.5,
                'sid': sid,
                'task_type': 'code_review',
                'operation_type': 'CHAT',
            }
            job_marker = {
                'kind': 'job',
                'ts': 1715516002.0,
                'sid': sid,
                'agentic_job_id': job_id,
                'job_name': 'Metadata Test Job',
                'job_type': 'code_review',
                'status': status,
            }
            # The classifier only writes failure_reason for FAILED arcs; mirror that.
            if failure_reason:
                job_marker['failure_reason'] = failure_reason
            with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
                f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
                f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

            build_shim(shim)

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

            rc, _ignored, output = run_script(
                SCRIPTS_DIR / 'hermes-report.sh', base_env, inv_log
            )
            self.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {output}')

            outcome_inv = []
            if os.path.exists(jobs_log):
                with open(jobs_log) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if not line:
                            continue
                        argv = shlex.split(line)
                        if len(argv) >= 2 and argv[0] == 'jobs' and argv[1] == 'outcome':
                            outcome_inv.append(argv)

            self.assertEqual(
                len(outcome_inv), 1,
                f'expected exactly 1 "jobs outcome" invocation, got {len(outcome_inv)}: '
                f'{outcome_inv!r}\nOutput: {output}'
            )
            return outcome_inv[0]
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @staticmethod
    def _metadata_value(argv):
        """Pull the token following --metadata, or None."""
        for i, tok in enumerate(argv):
            if tok == '--metadata' and i + 1 < len(argv):
                return argv[i + 1]
        return None

    def test_failed_outcome_metadata_carries_source_and_reason(self):
        reason = 'tests failed: 3 assertion errors in auth module'
        argv = self._run_one_outcome('FAILED', reason, source='production')

        self.assertIn('--result', argv)
        self.assertEqual(argv[argv.index('--result') + 1], 'FAILED')

        raw = self._metadata_value(argv)
        self.assertIsNotNone(raw, f'--metadata missing on FAILED outcome: {argv!r}')
        meta = json.loads(raw)
        self.assertEqual(meta.get('source'), 'production')
        self.assertEqual(meta.get('failure_reason'), reason)

    def test_failed_metadata_is_valid_json_with_pipe_in_reason(self):
        # A reason containing pipe/newline must survive the IFS='|' transport
        # (sanitized to spaces) and still be valid JSON via json.dumps.
        reason = 'step a | step b failed\nstack overflow'
        argv = self._run_one_outcome('FAILED', reason, source='staging')

        raw = self._metadata_value(argv)
        self.assertIsNotNone(raw, f'--metadata missing: {argv!r}')
        meta = json.loads(raw)  # must not raise
        self.assertEqual(meta.get('source'), 'staging')
        self.assertIn('failure_reason', meta)
        # Pipe and newline are stripped to spaces before transport.
        self.assertNotIn('|', meta['failure_reason'])
        self.assertNotIn('\n', meta['failure_reason'])

    def test_success_outcome_metadata_has_source_only(self):
        argv = self._run_one_outcome('SUCCESS', failure_reason='', source='production')

        self.assertEqual(argv[argv.index('--result') + 1], 'SUCCESS')
        raw = self._metadata_value(argv)
        self.assertIsNotNone(raw, f'--metadata missing on SUCCESS outcome: {argv!r}')
        meta = json.loads(raw)
        self.assertEqual(meta, {'source': 'production'})


if __name__ == '__main__':
    unittest.main()
