"""Phase 66, TRU-04 -- an undetermined CANCELLED job explains itself on the wire.

The classifier is told to use CANCELLED when it is not sure, and every
CANCELLED arc ships `--outcome-type UNSUCCESSFUL`. Without this phase an
"unsure" job and a job cut off by a guardrail halt are byte-identical on the
wire. The server's executionStatus enum is closed (SUCCESS, FAILED,
CANCELLED), so a distinct status is impossible; the one route left is a
populated reason, and with every released CLI the only wire-reachable carrier
is `--metadata`.

Success criteria proven here, against the REAL hermes-report.sh:
  SC1 -- an undetermined CANCELLED outcome ships `failure_reason` (the
         reporter-owned constant `_UNDETERMINED_OUTCOME_REASON`, never model
         text) and `outcome_basis: undetermined` in `--metadata`.
  SC2 -- the evaluator's conservative bias is untouched: the job-inference
         prompt and `_validate_job` still treat CANCELLED as the
         uncertainty catch-all.
  SC3 -- a genuine halt cancellation (`guardrail-halt-*` id, or job type
         `interrupted`, both written by pre_tool_call.sh) ships exactly the
         pre-phase argv: source-only metadata.

Source-of-truth: skills/revenium/scripts/hermes-report.sh -- the outcome
stage (the seven-field job_outcome_queue tuple, the `outcome_basis`
discriminator) and the `outcome_metadata` heredoc.

Fixtures are duplicated from tests/test_phase38_reporter_path.py and
tests/test_phase46_metadata_envelope.py rather than imported: importing the
latter reopens an os.environ-mutation-at-import env-bleed trap.
"""
import ast
import json
import os
import shlex
import shutil
import tempfile
import unittest

from tests._compat_helpers import (
    ROOT,
    SCRIPTS_DIR,
    SKILL,
    build_shim,
    build_state_db,
    run_script,
)

HERMES_REPORT_SH = SCRIPTS_DIR / 'hermes-report.sh'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _extract_outcome_metadata_heredoc(script_text):
    """Return the body of the `outcome_metadata=$(` python heredoc, or None
    (never a partial body) if either anchor has moved."""
    anchor = 'outcome_metadata=$('
    start = script_text.find(anchor)
    if start == -1:
        return None
    heredoc_start = script_text.find("<<'PY'", start)
    if heredoc_start == -1:
        return None
    body_start = script_text.find('\n', heredoc_start) + 1
    body_end = script_text.find('\nPY\n', body_start)
    if body_end == -1:
        return None
    return script_text[body_start:body_end]


def _reason_constant():
    """The `_UNDETERMINED_OUTCOME_REASON` str read out of the reporter's own
    heredoc source -- never retyped here, so it has exactly one authority.
    Returns None (never a guess) when absent."""
    body = _extract_outcome_metadata_heredoc(HERMES_REPORT_SH.read_text())
    if body is None:
        return None
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Name)
                        and target.id == '_UNDETERMINED_OUTCOME_REASON'
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)):
                    return node.value.value
    return None


def _metadata_value(argv):
    for i, tok in enumerate(argv):
        if tok == '--metadata' and i + 1 < len(argv):
            return argv[i + 1]
    return None


def _flag_set(argv):
    return {tok for tok in argv if tok.startswith('--')}


def _run_one_outcome(test, sid, job_id, status, job_type='code_review',
                     failure_reason='', source='test', sidecar=None,
                     script_path=None):
    """Drive hermes-report.sh for one job arc; return the parsed
    `jobs outcome` argv. Copied from
    TestPhase38ReporterPath._run_one_outcome with three changes: job_type is
    a parameter, failure_reason is written whatever the status, and the
    script under test is a parameter (so a copied skill tree can isolate one
    outcome-queue producer)."""
    tmpdir = tempfile.mkdtemp(prefix='gsd-phase66-')
    try:
        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        markers_dir = os.path.join(state_dir, 'markers')
        assessments_dir = os.path.join(state_dir, 'job-assessments')
        os.makedirs(markers_dir, mode=0o700)
        os.makedirs(assessments_dir, mode=0o700)
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

        # The created line is keyed by the SANITIZED id; the ids used here
        # contain nothing the sanitizer rewrites.
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
            'job_name': 'Phase 66 Test Job',
            'job_type': job_type,
            'status': status,
        }
        if failure_reason:
            job_marker['failure_reason'] = failure_reason
        with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
            f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
            f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

        if sidecar is not None:
            records = sidecar if isinstance(sidecar, list) else [sidecar]
            with open(os.path.join(assessments_dir, f'{job_id}.jsonl'), 'w') as f:
                for rec in records:
                    f.write(json.dumps(rec, separators=(',', ':')) + '\n')

        build_shim(shim, outcome_value_capable=True)

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
            script_path or HERMES_REPORT_SH, base_env, inv_log
        )
        test.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {output}')

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

        test.assertEqual(
            len(outcome_inv), 1,
            f'expected exactly 1 "jobs outcome" invocation, got {len(outcome_inv)}: '
            f'{outcome_inv!r}\nOutput: {output}'
        )
        return outcome_inv[0]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Task 2 -- the tracer: undetermined is labelled, a halt is not
# ---------------------------------------------------------------------------
class UndeterminedLabelTests(unittest.TestCase):
    """SC1: an undetermined CANCELLED arc carries the reporter constant and
    `outcome_basis: undetermined` through the real reporter."""

    def test_reason_constant_is_defined_in_the_reporter(self):
        reason = _reason_constant()
        self.assertIsNotNone(
            reason, '_UNDETERMINED_OUTCOME_REASON is not assigned in the outcome_metadata heredoc')
        self.assertTrue(reason.strip())

    def test_undetermined_cancelled_ships_the_label(self):
        reason = _reason_constant()
        self.assertIsNotNone(reason)
        argv = _run_one_outcome(
            self, 'p66-sid-001', 'p66-undetermined-001', 'CANCELLED', job_type='code_review')
        self.assertEqual(argv[argv.index('--result') + 1], 'CANCELLED')
        self.assertEqual(argv[argv.index('--outcome-type') + 1], 'UNSUCCESSFUL')
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)
        meta = json.loads(_metadata_value(argv))
        self.assertEqual(meta, {
            'source': 'test',
            'failure_reason': reason,
            'outcome_basis': 'undetermined',
        })

    def test_marker_failure_reason_never_reaches_the_label(self):
        reason = _reason_constant()
        self.assertIsNotNone(reason)
        argv = _run_one_outcome(
            self, 'p66-sid-002', 'p66-undetermined-002', 'CANCELLED',
            failure_reason='model supplied text')
        meta = json.loads(_metadata_value(argv))
        self.assertEqual(meta.get('failure_reason'), reason)
        self.assertNotIn('model supplied text', _metadata_value(argv))
        self.assertEqual(meta.get('outcome_basis'), 'undetermined')

    def test_lowercase_cancelled_status_is_labelled_the_same_way(self):
        reason = _reason_constant()
        self.assertIsNotNone(reason)
        argv = _run_one_outcome(
            self, 'p66-sid-003', 'p66-undetermined-003', 'cancelled')
        self.assertEqual(argv[argv.index('--result') + 1], 'CANCELLED')
        meta = json.loads(_metadata_value(argv))
        self.assertEqual(meta.get('failure_reason'), reason)
        self.assertEqual(meta.get('outcome_basis'), 'undetermined')

    def test_undetermined_argv_adds_no_flag_over_the_halt_argv(self):
        """T-66-04: no new CLI flag, so no CLI can reject the call and wedge
        the job in the outcome retry loop."""
        undetermined = _run_one_outcome(
            self, 'p66-sid-004', 'p66-undetermined-004', 'CANCELLED')
        halt = _run_one_outcome(
            self, 'p66-sid-005', 'guardrail-halt-ab12', 'CANCELLED', job_type='interrupted')
        self.assertEqual(_flag_set(undetermined), _flag_set(halt))


class GenuineCancelUnchangedTests(unittest.TestCase):
    """SC3: a genuine halt cancellation, SUCCESS and FAILED ship exactly as
    they did before this phase."""

    def test_halt_marker_ships_source_only_metadata(self):
        argv = _run_one_outcome(
            self, 'p66-sid-010', 'guardrail-halt-ab12', 'CANCELLED', job_type='interrupted')
        self.assertEqual(argv[argv.index('--result') + 1], 'CANCELLED')
        self.assertEqual(argv[argv.index('--outcome-type') + 1], 'UNSUCCESSFUL')
        self.assertEqual(json.loads(_metadata_value(argv)), {'source': 'test'})

    def test_halt_id_prefix_alone_is_exempt(self):
        argv = _run_one_outcome(
            self, 'p66-sid-011', 'guardrail-halt-cd34', 'CANCELLED', job_type='code_review')
        self.assertEqual(json.loads(_metadata_value(argv)), {'source': 'test'})

    def test_interrupted_job_type_alone_is_exempt(self):
        argv = _run_one_outcome(
            self, 'p66-sid-012', 'p66-user-cancel-001', 'CANCELLED', job_type='interrupted')
        self.assertEqual(json.loads(_metadata_value(argv)), {'source': 'test'})

    def test_interrupted_cancelled_marker_with_own_reason_stays_source_only(self):
        argv = _run_one_outcome(
            self, 'p66-sid-013', 'guardrail-halt-ef56', 'CANCELLED', job_type='interrupted',
            failure_reason='halted by guardrail')
        self.assertEqual(json.loads(_metadata_value(argv)), {'source': 'test'})

    def test_success_ships_converted_and_source_only(self):
        argv = _run_one_outcome(self, 'p66-sid-014', 'p66-success-001', 'SUCCESS')
        self.assertEqual(argv[argv.index('--result') + 1], 'SUCCESS')
        self.assertEqual(argv[argv.index('--outcome-type') + 1], 'CONVERTED')
        self.assertEqual(json.loads(_metadata_value(argv)), {'source': 'test'})

    def test_failed_keeps_its_own_reason_and_no_outcome_basis(self):
        argv = _run_one_outcome(
            self, 'p66-sid-015', 'p66-failed-001', 'FAILED',
            failure_reason='3 assertions failed')
        self.assertEqual(argv[argv.index('--result') + 1], 'FAILED')
        self.assertEqual(json.loads(_metadata_value(argv)), {
            'source': 'test', 'failure_reason': '3 assertions failed'})


if __name__ == '__main__':
    unittest.main()
