"""Phase 38 Plan 01 — the assessment reaches `revenium jobs outcome`.

Carries an accepted assessment (Phase 36/37's frozen nested object,
`job.get("assessment")`) from the session's job marker to the two
`jobs outcome` value flags plus provenance in `--metadata`.

Source-of-truth: skills/revenium/scripts/hermes-report.sh post-loop outcome
stage (job_outcome_queue push sites + the assessment resolver + the extended
--metadata heredoc).

Requirements covered:
  ROI-10 — the assessment reaches Revenium as --outcome-value/--outcome-currency
           plus provenance in --metadata, never as a sixth queue pipe field.
  ROI-12 — backward-compatible markers: a marker line with no "assessment" key
           at all still parses and reports normally.

Reuses the no-shift shim + synthetic state.db harness from _compat_helpers
(the same harness tests/test_compat_jobs_outcome.py and
tests/test_jobs_outcome_metadata.py already use for this exact stage).

Task 1: the sixth queue field (sid). Task 2 (this commit): the assessment
resolver and the value + provenance flags. Task 3 lands in a follow-up
commit and extends this file with golden and backward-compatibility
coverage.
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

# The frozen assessment contract (classifier.py's _validate_assessment
# return shape). estimated_value = 3.5 * 150.0 = 525.0, matching what the
# evaluator itself would derive -- chosen here directly since these tests
# exercise hermes-report.sh's READ side, not the classifier's derivation.
ASSESSMENT_FIXTURE = {
    "estimated_value": 525.0,
    "currency": "USD",
    "basis": "3.5 hours of senior engineer review time",
    "assumptions": {
        "inferred_role": "senior software engineer",
        "estimated_hours_saved": 3.5,
        "assumed_loaded_rate": 150.0,
    },
    "confidence": 0.8,
    "evaluator": "llm",
    "evaluator_version": "v1",
    "evidence_class": "MODEL_ESTIMATED_DEMO",
}


class TestPhase38ReporterPath(unittest.TestCase):
    def _run_one_outcome(self, sid, job_id, status, failure_reason='', source='test',
                          assessment=None):
        """Drive hermes-report.sh for one job arc; return the parsed
        `jobs outcome` argv. Mirrors _run_one_outcome in
        tests/test_jobs_outcome_metadata.py, extended with an optional
        assessment payload on the job marker."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase38-')
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
                'muid': f'{job_id}-task',
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
                'job_name': 'Phase 38 Test Job',
                'job_type': 'code_review',
                'status': status,
            }
            # The classifier only writes failure_reason for FAILED arcs; mirror that.
            if failure_reason:
                job_marker['failure_reason'] = failure_reason
            # ROI-12: when assessment is None, the key is simply absent -- the
            # same shape a pre-v1.5 marker line has.
            if assessment is not None:
                job_marker['assessment'] = assessment
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
        for i, tok in enumerate(argv):
            if tok == '--metadata' and i + 1 < len(argv):
                return argv[i + 1]
        return None

    # -- Task 1: sid as the sixth queue field must not shift anything -----

    def test_queue_unvalued_success_job_reports_outcome_unchanged(self):
        """T-38-01: a job with no assessment still reports its outcome
        exactly as before the sixth (sid) field was added."""
        argv = self._run_one_outcome('q38-sid-001', 'q38-job-001', 'SUCCESS')
        self.assertEqual(argv[argv.index('--result') + 1], 'SUCCESS')
        self.assertEqual(argv[argv.index('--outcome-type') + 1], 'CONVERTED')
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta, {'source': 'test'})

    def test_queue_field_addition_does_not_shift_failed_arc_metadata(self):
        """T-38-01: source/failure_reason must land in the same positions
        they always have -- a shifted tuple would corrupt these, not the new
        field, which is the failure mode this test is built to catch."""
        argv = self._run_one_outcome(
            'q38-sid-002', 'q38-job-002', 'FAILED', failure_reason='3 assertions failed',
        )
        self.assertEqual(argv[argv.index('--result') + 1], 'FAILED')
        self.assertNotIn('--outcome-type', argv)
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta.get('source'), 'test')
        self.assertEqual(meta.get('failure_reason'), '3 assertions failed')

    # -- Task 2: an accepted assessment ships as value + provenance -------

    def test_outcome_success_with_assessment_ships_value_and_provenance(self):
        argv = self._run_one_outcome(
            'o38-sid-001', 'o38-job-001', 'SUCCESS', assessment=ASSESSMENT_FIXTURE,
        )
        self.assertEqual(argv[argv.index('--outcome-value') + 1], '525.0')
        self.assertEqual(argv[argv.index('--outcome-currency') + 1], 'USD')
        self.assertEqual(argv[argv.index('--outcome-type') + 1], 'CONVERTED')

        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta.get('evidence_class'), 'MODEL_ESTIMATED_DEMO')
        self.assertEqual(meta.get('evaluator'), 'llm')
        self.assertEqual(meta.get('evaluator_version'), 'v1')
        self.assertEqual(meta.get('confidence'), 0.8)
        self.assertEqual(
            meta.get('assumptions'),
            {'estimated_hours_saved': 3.5, 'assumed_loaded_rate': 150.0},
        )
        # basis / inferred_role are not part of the provenance list this plan
        # names (evidence_class, evaluator, evaluator_version, confidence,
        # and the two numeric assumptions) -- they stay out of --metadata.
        self.assertNotIn('basis', meta)
        self.assertNotIn('inferred_role', meta)

    def test_outcome_success_without_assessment_ships_neither_value_flag(self):
        argv = self._run_one_outcome('o38-sid-002', 'o38-job-002', 'SUCCESS')
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta, {'source': 'test'})

    def test_outcome_failed_argv_unchanged_by_assessment_logic(self):
        """ROI-09: FAILED/CANCELLED are never evaluated by the classifier, so
        no real marker ever carries {status: FAILED, assessment: {...}}. This
        feeds that shape anyway to prove the outcome stage's OWN guard --
        not just the classifier's -- refuses to ship a value for a non-SUCCESS
        arc."""
        argv = self._run_one_outcome(
            'o38-sid-003', 'o38-job-003', 'FAILED',
            failure_reason='boom', assessment=ASSESSMENT_FIXTURE,
        )
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)
        self.assertNotIn('--outcome-type', argv)
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta.get('source'), 'test')
        self.assertEqual(meta.get('failure_reason'), 'boom')
        self.assertNotIn('evidence_class', meta)

    def test_outcome_cancelled_never_carries_a_value(self):
        argv = self._run_one_outcome(
            'o38-sid-004', 'o38-job-004', 'CANCELLED', assessment=ASSESSMENT_FIXTURE,
        )
        self.assertEqual(argv[argv.index('--result') + 1], 'CANCELLED')
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)
        self.assertNotIn('--outcome-type', argv)


if __name__ == '__main__':
    unittest.main()
