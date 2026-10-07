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
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys as _sys
import tempfile
import unittest
from pathlib import Path

from tests._compat_helpers import (
    ROOT,
    SCRIPTS_DIR,
    SKILL,
    build_shim,
    build_state_db,
    run_script,
)

HERMES_REPORT_SH = SCRIPTS_DIR / 'hermes-report.sh'
PRE_TOOL_CALL_SH = SCRIPTS_DIR / 'pre_tool_call.sh'
PLUGIN_DIR = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'


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


def _copied_tree_with_push_removed(anchor):
    """Copy the skill tree and replace the single line of the copy's
    hermes-report.sh containing `anchor` with a lone `:` at the same
    indentation. Returns (tmpdir, script_path, replaced_count). Removing one
    outcome-queue push isolates the OTHER producer; callers assert
    replaced_count == 1 so a moved anchor fails loudly."""
    tmpdir = tempfile.mkdtemp(prefix='gsd-phase66-tree-')
    tree = os.path.join(tmpdir, 'skill')
    shutil.copytree(str(SKILL), tree)
    script = os.path.join(tree, 'scripts', 'hermes-report.sh')
    with open(script) as f:
        lines = f.read().split('\n')
    replaced = 0
    for i, line in enumerate(lines):
        if anchor in line:
            indent = line[:len(line) - len(line.lstrip())]
            lines[i] = indent + ':'
            replaced += 1
    with open(script, 'w') as f:
        f.write('\n'.join(lines))
    return tmpdir, script, replaced


def _non_success_sidecar_record(job_id, execution_status='FAILED', **overrides):
    """The abstention sidecar record production writes for a FAILED or
    CANCELLED job -- duplicated from tests/test_phase44_economic_mechanisms.py."""
    record = {
        'kind': 'job_assessment',
        'ts': 1715516002.5,
        'agentic_job_id': job_id,
        'assessment_id': f'{job_id}:0',
        'assessment_schema_version': 1,
        'taxonomy_version': 1,
        'prompt_version': 1,
        'policy_version': 1,
        'model': 'unknown',
        'evaluator': 'llm',
        'evaluator_version': 'v1',
        'confidence': 0.0,
        'evidence_class': 'MODEL_ESTIMATED_DEMO',
        'execution_status': execution_status,
        'abstention_reason': 'not_evaluated_non_success',
        'reportability_status': 'candidate',
        'economic_mechanism': 'unknown',
        'supplied_costs': {'human_review': 10.0},
        'cost_coverage': {
            'included': ['human_review'],
            'known_zero': [],
            'unknown': ['rework_or_error', 'handoff', 'training_or_change'],
            'excluded': ['metered_ai_cost'],
        },
        'double_counting_group': 'ns66-sid-group',
    }
    record.update(overrides)
    return record


def _run_forwarder(body, env):
    """Execute the extracted heredoc body as a standalone python3 script
    against an explicit environment (OUTCOME_SOURCE / OUTCOME_STATUS /
    OUTCOME_BASIS / OUTCOME_FAILURE_REASON / ASSESSMENT_JSON)."""
    return subprocess.run(
        [_sys.executable, '-'], input=body, env=env,
        capture_output=True, text=True,
    )


def _forwarder_env(source='prod', status='CANCELLED', basis='undetermined',
                   failure_reason='', assessment=None):
    return {
        'OUTCOME_SOURCE': source,
        'OUTCOME_STATUS': status,
        'OUTCOME_BASIS': basis,
        'OUTCOME_FAILURE_REASON': failure_reason,
        'ASSESSMENT_JSON': json.dumps(assessment) if assessment is not None else '',
    }


def _over_ceiling_assessment():
    """A full-field assessment record that, with a ~3,800-byte source,
    exceeds the 4096-byte ceiling before any drop -- duplicated from
    tests/test_phase46_metadata_envelope.py."""
    return {
        'value_low': 10.5, 'value_base': 20.5, 'value_high': 30.5,
        'bounds_source': 'model_estimate',
        'net_value': 15.25,
        'assumptions': {'estimated_hours_saved': 3.5, 'assumed_loaded_rate': 150.0},
        'supplied_costs': {
            'human_review': 10.0, 'rework_or_error': 5.0,
            'handoff': 2.0, 'training_or_change': 1.0,
        },
        'cost_coverage': {
            'included': ['human_review', 'rework_or_error', 'handoff', 'training_or_change'],
            'known_zero': ['human_review', 'rework_or_error', 'handoff', 'training_or_change'],
            'unknown': [],
            'excluded': ['metered_ai_cost'],
        },
        'evaluator': 'naked-llm-evaluator-name', 'evaluator_version': 'v1.0.0',
        'model': 'some-model-string-id',
        'evidence_class': 'MODEL_ESTIMATED_DEMO', 'reportability_status': 'reportable',
        'confidence': 0.789, 'economic_mechanism': 'augmentation_capacity_expansion',
        'double_counting_group': 'g' * 64,
    }


# Classifier loader, duplicated from tests/test_phase46_metadata_envelope.py
# (importing that module reopens its env-bleed trap). A UNIQUE package name
# per call because the classifier binds its path constants at import time.
_LOAD_SEQ = [0]
_ENV_TOUCHED = set()
_ENV_SAVED = {}


def setUpModule():
    for k in ('REVENIUM_STATE_DIR', 'REVENIUM_MARKERS_DIR', 'REVENIUM_CONFIG_FILE',
              'REVENIUM_TAXONOMY_FILE', 'REVENIUM_JOB_TAXONOMY_FILE',
              'REVENIUM_JOB_ASSESSMENTS_DIR', 'HERMES_HOME'):
        _ENV_SAVED[k] = os.environ.get(k)


def _restore_env():
    for k in _ENV_TOUCHED | set(_ENV_SAVED):
        prior = _ENV_SAVED.get(k)
        if prior is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = prior


def tearDownModule():
    _restore_env()
    for cached in [k for k in list(_sys.modules) if k.startswith('p66env_pkg')]:
        del _sys.modules[cached]


def _load_classifier(env=None):
    """Import the revenium-classifier plugin fresh; return the classifier module."""
    for k, v in (env or {}).items():
        os.environ[k] = v
        _ENV_TOUCHED.add(k)
    _LOAD_SEQ[0] += 1
    name = f'p66env_pkg_{_LOAD_SEQ[0]}'
    for cached in [k for k in _sys.modules if k.startswith('p66env_pkg')]:
        del _sys.modules[cached]
    spec = importlib.util.spec_from_file_location(
        name, str(PLUGIN_DIR / '__init__.py'), submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    _sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return _sys.modules[f'{name}.classifier']


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



# ---------------------------------------------------------------------------
# Task 3 -- guards
# ---------------------------------------------------------------------------
class QueueShiftGuardTests(unittest.TestCase):
    """T-66-01: job_type is appended LAST and already pipe-stripped, so a
    hostile value cannot shift source, failure_reason or the sid lookup."""

    def test_pipe_in_job_type_does_not_shift_a_failed_arc(self):
        argv = _run_one_outcome(
            self, 'p66-sid-020', 'p66-failed-020', 'FAILED', job_type='code|review',
            failure_reason='3 assertions failed')
        self.assertEqual(argv[argv.index('--result') + 1], 'FAILED')
        self.assertEqual(json.loads(_metadata_value(argv)), {
            'source': 'test', 'failure_reason': '3 assertions failed'})

    def test_pipe_in_job_type_cannot_forge_the_interrupted_exemption(self):
        """`inter|rupted` sanitizes to `inter_rupted`, which is not the
        exempt literal, so the arc is labelled and `source` stays in place."""
        reason = _reason_constant()
        self.assertIsNotNone(reason)
        argv = _run_one_outcome(
            self, 'p66-sid-021', 'p66-undetermined-021', 'CANCELLED', job_type='inter|rupted')
        meta = json.loads(_metadata_value(argv))
        self.assertEqual(meta, {
            'source': 'test', 'failure_reason': reason, 'outcome_basis': 'undetermined'})

    def test_sidecar_lookup_still_resolves_with_the_seventh_field(self):
        """Field 6 (sid) still locates the sidecar: a CANCELLED arc with an
        abstention sidecar still ships supplied_costs, and no value flag."""
        reason = _reason_constant()
        self.assertIsNotNone(reason)
        job_id = 'p66-undetermined-022'
        argv = _run_one_outcome(
            self, 'p66-sid-022', job_id, 'CANCELLED', job_type='code_review',
            sidecar=_non_success_sidecar_record(job_id, execution_status='CANCELLED'))
        self.assertNotIn('--outcome-value', argv)
        meta = json.loads(_metadata_value(argv))
        self.assertIn('supplied_costs', meta)
        self.assertEqual(meta.get('failure_reason'), reason)
        self.assertEqual(meta.get('outcome_basis'), 'undetermined')

    def _assert_producer_isolated(self, anchor):
        reason = _reason_constant()
        self.assertIsNotNone(reason)
        tmpdir, script, replaced = _copied_tree_with_push_removed(anchor)
        try:
            self.assertEqual(
                replaced, 1, f'anchor {anchor!r} moved: {replaced} lines replaced, expected 1')
            labelled = _run_one_outcome(
                self, 'p66-sid-023', 'p66-undetermined-023', 'CANCELLED',
                script_path=Path(script))
            self.assertEqual(json.loads(_metadata_value(labelled)), {
                'source': 'test', 'failure_reason': reason, 'outcome_basis': 'undetermined'})
            halt = _run_one_outcome(
                self, 'p66-sid-024', 'guardrail-halt-ab12', 'CANCELLED', job_type='interrupted',
                script_path=Path(script))
            self.assertEqual(json.loads(_metadata_value(halt)), {'source': 'test'})
            # The id prefix alone exempts the halt shape above, so it cannot
            # prove job_type reached the consumer. This arc is exempt ONLY by
            # job_type: if the surviving producer dropped field 7 it would be
            # wrongly labelled.
            interrupted = _run_one_outcome(
                self, 'p66-sid-025', 'p66-user-cancel-025', 'CANCELLED', job_type='interrupted',
                script_path=Path(script))
            self.assertEqual(json.loads(_metadata_value(interrupted)), {'source': 'test'})
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_precheck_producer_alone_carries_job_type(self):
        # Removing the in-loop push leaves the precheck producer.
        self._assert_producer_isolated('job_outcome_queue+=("${clean_job_id}|')

    def test_in_loop_producer_alone_carries_job_type(self):
        # Removing the precheck push leaves the in-loop producer.
        self._assert_producer_isolated('job_outcome_queue+=("${precheck_clean_job_id}|')


class CeilingTests(unittest.TestCase):
    """T-66-04: the two new keys are base metering -- small, and never shed
    by the 4096-byte --metadata ceiling."""

    @classmethod
    def setUpClass(cls):
        cls.body = _extract_outcome_metadata_heredoc(HERMES_REPORT_SH.read_text())
        cls.reason = _reason_constant()

    def _ceiling(self):
        m = re.search(r'_METADATA_CEILING_BYTES\s*=\s*(\d+)', self.body)
        self.assertIsNotNone(m)
        return int(m.group(1))

    def test_heredoc_and_constant_are_extractable(self):
        self.assertIsNotNone(self.body)
        self.assertIsNotNone(self.reason)

    def test_small_undetermined_object_is_under_the_ceiling_untruncated(self):
        env = {**os.environ, **_forwarder_env(source='s' * 64)}
        res = _run_forwarder(self.body, env)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = res.stdout.strip()
        self.assertLessEqual(len(out.encode('utf-8')), self._ceiling())
        meta = json.loads(out)
        self.assertNotIn('metadata_truncated', meta)
        self.assertEqual(set(meta), {'source', 'failure_reason', 'outcome_basis'})

    def _unshed_size(self, env):
        """Byte size of the payload with the ceiling lifted, so a fixture
        that shrinks below the real ceiling fails loudly instead of letting
        a shed-tier test pass without any tier running."""
        lifted = self.body.replace(
            '_METADATA_CEILING_BYTES = %d' % self._ceiling(),
            '_METADATA_CEILING_BYTES = 10 ** 9')
        self.assertNotEqual(lifted, self.body)
        res = _run_forwarder(lifted, env)
        self.assertEqual(res.returncode, 0, res.stderr)
        return len(res.stdout.strip().encode('utf-8'))

    def _shed_case(self, source_len):
        env = {**os.environ, **_forwarder_env(
            source='s' * source_len, assessment=_over_ceiling_assessment())}
        self.assertGreater(self._unshed_size(env), self._ceiling())
        res = _run_forwarder(self.body, env)
        self.assertEqual(res.returncode, 0, res.stderr)
        meta = json.loads(res.stdout.strip())
        self.assertLessEqual(len(res.stdout.strip().encode('utf-8')), self._ceiling())
        return meta

    def test_new_keys_survive_the_shed_tiers(self):
        # Tier 1 only: the value family is shed, provenance survives.
        meta = self._shed_case(3400)
        self.assertTrue(meta.get('metadata_truncated'))
        self.assertNotIn('net_value', meta)
        self.assertIn('evaluator', meta)
        self.assertEqual(meta.get('outcome_basis'), 'undetermined')
        self.assertEqual(meta.get('failure_reason'), self.reason)

        # Tier 2: still over the ceiling after tier 1, so the provenance
        # family is shed too. The two Phase 66 keys must still survive.
        meta = self._shed_case(3800)
        self.assertTrue(meta.get('metadata_truncated'))
        self.assertNotIn('net_value', meta)
        self.assertNotIn('evaluator', meta)
        self.assertNotIn('model', meta)
        self.assertEqual(meta.get('outcome_basis'), 'undetermined')
        self.assertEqual(meta.get('failure_reason'), self.reason)

    def test_new_keys_are_in_neither_shed_tuple(self):
        tree = ast.parse(self.body)
        shed = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (isinstance(target, ast.Name)
                            and target.id in ('_VALUE_FAMILY_META_KEYS',
                                              '_PROVENANCE_FAMILY_META_KEYS')):
                        shed[target.id] = {
                            e.value for e in node.value.elts if isinstance(e, ast.Constant)}
        self.assertEqual(set(shed), {'_VALUE_FAMILY_META_KEYS', '_PROVENANCE_FAMILY_META_KEYS'})
        for name, keys in shed.items():
            self.assertNotIn('outcome_basis', keys, name)
            self.assertNotIn('failure_reason', keys, name)

    def test_constant_is_ascii_and_under_200_bytes(self):
        self.assertTrue(self.reason.isascii())
        self.assertLess(len(self.reason.encode('utf-8')), 200)
        self.assertNotIn('"', self.reason)
        self.assertNotIn("'", self.reason)

    def test_failed_status_never_gets_outcome_basis(self):
        env = {**os.environ, **_forwarder_env(
            status='FAILED', basis='undetermined', failure_reason='boom')}
        res = _run_forwarder(self.body, env)
        self.assertEqual(res.returncode, 0, res.stderr)
        meta = json.loads(res.stdout.strip())
        self.assertNotIn('outcome_basis', meta)
        self.assertEqual(meta.get('failure_reason'), 'boom')


class BiasUnchangedTests(unittest.TestCase):
    """SC2 / Known Risk 4: the evaluator is not made more decisive."""

    def tearDown(self):
        _restore_env()

    def _classifier(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase66-cls-')
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        return _load_classifier({
            'HERMES_HOME': tmpdir,
            'REVENIUM_STATE_DIR': os.path.join(tmpdir, 'state'),
        })

    def test_prompt_keeps_the_uncertainty_bias_lines_verbatim(self):
        prompt = self._classifier()._build_job_inference_prompt('t', [])
        self.assertIn(
            'CANCELLED: use when uncertain \u2014 this is the uncertainty-bias catch-all.', prompt)
        self.assertIn('OMIT this field for SUCCESS and CANCELLED.', prompt)

    def test_validate_job_still_blanks_failure_reason_for_cancelled(self):
        job = self._classifier()._validate_job({
            'agentic_job_id': 'some_job', 'job_type': 'code_review',
            'status': 'CANCELLED', 'failure_reason': 'model supplied text'})
        self.assertIsNotNone(job)
        self.assertEqual(job['status'], 'CANCELLED')
        self.assertEqual(job['failure_reason'], '')


class HaltIdDriftTests(unittest.TestCase):
    """SC3 / T-66-05: the reporter's exemption literals are read out of
    pre_tool_call.sh, so drift in the hook fails the build."""

    @classmethod
    def setUpClass(cls):
        cls.hook = PRE_TOOL_CALL_SH.read_text()
        cls.reporter = HERMES_REPORT_SH.read_text()

    def test_halt_id_prefix_matches_the_hook(self):
        m = re.search(r'"agentic_job_id":\s*"([^"]+)"\s*\+', self.hook)
        self.assertIsNotNone(m, 'pre_tool_call.sh no longer builds the halt job id as prefix + token')
        self.assertEqual(m.group(1), 'guardrail-halt-')
        self.assertIn('!= ' + m.group(1) + '*', self.reporter)

    def test_halt_job_type_matches_the_hook(self):
        m = re.search(r'"job_type":\s*"([a-z_]+)"', self.hook)
        self.assertIsNotNone(m, 'pre_tool_call.sh no longer writes a literal job_type')
        self.assertEqual(m.group(1), 'interrupted')
        self.assertIn('"${outcome_job_type}" != "' + m.group(1) + '"', self.reporter)

    def test_halt_marker_status_is_cancelled(self):
        self.assertRegex(self.hook, r'"status":\s*"CANCELLED"')


if __name__ == '__main__':
    unittest.main()
