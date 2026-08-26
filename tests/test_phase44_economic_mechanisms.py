"""Phase 44 Plan 01 — EGV-05's six economic mechanisms: representable,
authority-split, and proven end-to-end from evaluator prompt to
`revenium jobs outcome --metadata`.

Requirements covered:
  EGV-05 — all six economic mechanisms are representable as declared
           constants, including risk avoidance and incremental revenue,
           which today's hours-times-rate shape cannot express. The
           evaluator may select only the three EVALUATOR_MECHANISMS; the
           remaining three OPERATOR_ONLY_MECHANISMS are reachable only
           through operator configuration and are provably unreachable
           from evaluator output.

Decisions this module exercises (44-CONTEXT.md):
  D-01 — the authority split: revenue/risk-avoidance/quality-decision
         mechanisms are operator-declared, never model-asserted.
  D-02 — the evaluator is taught exactly three mechanisms, each with its
         own prompt branch (Task 2 extends this module with
         PromptBranchTests/NewlyEnabledWorkTests).
  D-03 — the model selects from the permitted set; anything else abstains,
         never clamps to a working default. Case-folding is coercion and
         is deliberately not applied.
  D-04 — a newly-enabled-work job records its mechanism and abstains from
         the whole value family (Task 2).

Guarantee class (44-VALIDATION.md's honesty rule, mirroring
43-VALIDATION.md's convention): MechanismSelectionTests is BEHAVIOURAL --
it proves the real resolver's accept/reject verdicts against live code
today, not an impossibility claim. MechanismWireTests is BEHAVIOURAL
end-to-end -- it drives the real hermes-report.sh over a synthetic
job-assessments sidecar and asserts on the real captured `jobs outcome`
argv, the same no-shift shim + synthetic state.db harness
tests/test_phase38_reporter_path.py and tests/test_jobs_outcome_metadata.py
already use for this stage.
"""
import importlib.util
import json
import os
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path

from tests._compat_helpers import (
    build_shim,
    build_state_db,
    run_script,
    SCRIPTS_DIR,
)

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'
CLASSIFIER_SOURCE_PATH = PLUGIN / 'classifier.py'
HERMES_REPORT_PATH = ROOT / 'skills' / 'revenium' / 'scripts' / 'hermes-report.sh'


def _load_classifier(env: "dict | None" = None):
    """Import classifier.py fresh under `env`.

    Copied from tests/test_phase43_evidence_grading.py's loader shape (per
    44-01-PLAN.md's Task 1 instruction), NOT imported across test modules --
    module-level path constants bind at import, so a test that changes
    REVENIUM_* must re-import rather than reassign.
    """
    env = env or {}
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(
            'phase44_classifier', str(CLASSIFIER_SOURCE_PATH))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class MechanismSelectionTests(unittest.TestCase):
    """D-01/D-03 -- _resolve_economic_mechanism's accept/reject verdicts,
    and that the resolved mechanism actually lands on the record
    _build_job_assessment constructs."""

    def setUp(self):
        self.mod = _load_classifier({})

    def test_each_evaluator_mechanism_is_accepted(self):
        for mechanism in (
            'labor_substitution',
            'augmentation_capacity_expansion',
            'newly_enabled_work',
        ):
            with self.subTest(mechanism=mechanism):
                self.assertEqual(
                    self.mod._resolve_economic_mechanism(
                        {'economic_mechanism': mechanism}),
                    mechanism,
                )

    def test_each_operator_only_mechanism_abstains(self):
        """The three OPERATOR_ONLY_MECHANISMS values are not selectable by
        the evaluator -- naming one resolves to the unknown sentinel, never
        to the value it named."""
        for mechanism in (
            'quality_decision_improvement',
            'risk_avoidance',
            'incremental_revenue',
        ):
            with self.subTest(mechanism=mechanism):
                self.assertEqual(
                    self.mod._resolve_economic_mechanism(
                        {'economic_mechanism': mechanism}),
                    self.mod.ECONOMIC_MECHANISM_UNKNOWN,
                )

    def test_malformed_and_hostile_inputs_abstain(self):
        cases = [
            'Labor_Substitution',  # wrong case -- .strip() but not .lower()
            'labour_substitution',  # mistyped spelling
            '',
            None,
            42,
            True,
            {'nested': 'dict'},
            'x' * 5000,
        ]
        for value in cases:
            with self.subTest(value=value):
                self.assertEqual(
                    self.mod._resolve_economic_mechanism(
                        {'economic_mechanism': value}),
                    self.mod.ECONOMIC_MECHANISM_UNKNOWN,
                )

    def test_non_dict_raw_abstains_without_raising(self):
        self.assertEqual(
            self.mod._resolve_economic_mechanism(None),
            self.mod.ECONOMIC_MECHANISM_UNKNOWN,
        )
        self.assertEqual(
            self.mod._resolve_economic_mechanism('not a dict'),
            self.mod.ECONOMIC_MECHANISM_UNKNOWN,
        )

    def test_record_built_from_raw_carries_the_resolved_mechanism(self):
        """A record built from a raw response naming a permitted mechanism
        carries that mechanism at record["economic_mechanism"] -- the whole
        prompt-to-record half of the carrier this plan's tracer proves."""
        raw = {
            'inferred_role': 'engineer',
            'estimated_hours_saved': 2.5,
            'assumed_loaded_rate': 150.0,
            'currency': 'USD',
            'basis': 'reviewed and merged a PR',
            'confidence': 0.5,
            'economic_mechanism': 'augmentation_capacity_expansion',
        }
        valid = {
            'agentic_job_id': 'msel-job-001',
            'job_type': 'code_review',
            'status': 'SUCCESS',
        }
        assessment = self.mod._validate_assessment(raw, {}, 'llm', 'v1')
        self.assertIsNotNone(assessment, 'fixture must validate for this test to prove anything')
        record = self.mod._build_job_assessment(
            valid, assessment, raw, {}, 'llm', 'v1')
        self.assertIsNotNone(record)
        self.assertEqual(
            record['economic_mechanism'], 'augmentation_capacity_expansion')


def _mechanism_sidecar_record(job_id, economic_mechanism):
    """Minimal reportable job-assessments sidecar record for driving
    hermes-report.sh's --metadata forwarder end-to-end, with
    economic_mechanism as the one field under test.

    Mirrors tests/test_phase38_reporter_path.py::_sidecar_record's shape --
    not imported across test modules, per this repo's per-file
    self-containment convention (module-level constants bind at import;
    each phase test file stays independently runnable).
    """
    return {
        'kind': 'job_assessment',
        'ts': 1715516002.5,
        'agentic_job_id': job_id,
        'assessment_id': f'{job_id}:0',
        'assessment_schema_version': 1,
        'taxonomy_version': 1,
        'prompt_version': 1,
        'policy_version': 1,
        'model': 'unknown',
        'value_low': 100.0,
        'value_base': 110.0,
        'value_high': 120.0,
        'bounds_source': 'derived',
        'currency': 'USD',
        'estimated_value': 110.0,
        'evaluator': 'llm',
        'evaluator_version': 'v1',
        'confidence': 0.8,
        'evidence_class': 'MODEL_ESTIMATED_DEMO',
        'assumptions': {
            'estimated_hours_saved': 1.0,
            'assumed_loaded_rate': 110.0,
        },
        'reportability_status': 'reportable',
        'economic_mechanism': economic_mechanism,
    }


class MechanismWireTests(unittest.TestCase):
    """T-44-02 -- the selected (or rejected) mechanism travels sidecar to
    `revenium jobs outcome --metadata`, driven end-to-end through the real
    hermes-report.sh via the no-shift shim + synthetic state.db harness."""

    def _run_one_outcome(self, sid, job_id, economic_mechanism):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase44-')
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

            # Pre-seed created line so the outcome stage does not defer.
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
                'job_name': 'Phase 44 Mechanism Wire Test',
                'job_type': 'code_review',
                'status': 'SUCCESS',
            }
            with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
                f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
                f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

            record = _mechanism_sidecar_record(job_id, economic_mechanism)
            with open(os.path.join(assessments_dir, f'{job_id}.jsonl'), 'w') as f:
                f.write(json.dumps(record, separators=(',', ':')) + '\n')

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
                SCRIPTS_DIR / 'hermes-report.sh', base_env, inv_log)
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
                f'expected exactly 1 "jobs outcome" invocation, got '
                f'{len(outcome_inv)}: {outcome_inv!r}\nOutput: {output}'
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

    def test_in_set_mechanism_forwards_to_metadata(self):
        argv = self._run_one_outcome(
            'mw44-sid-001', 'mw44-job-001', 'augmentation_capacity_expansion')
        self.assertIn('--result', argv)
        self.assertEqual(argv[argv.index('--result') + 1], 'SUCCESS')
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(
            meta.get('economic_mechanism'), 'augmentation_capacity_expansion')

    def test_out_of_set_mechanism_is_dropped_but_arc_still_reports(self):
        """T-44-02: a hand-edited or corrupt sidecar naming a value outside
        the six produces --metadata with no economic_mechanism key at all
        -- not a rejected record, not a dropped arc. --result still ships."""
        argv = self._run_one_outcome(
            'mw44-sid-002', 'mw44-job-002', 'not_a_real_mechanism')
        self.assertIn('--result', argv)
        self.assertEqual(argv[argv.index('--result') + 1], 'SUCCESS')
        meta = json.loads(self._metadata_value(argv))
        self.assertNotIn('economic_mechanism', meta)
        # The rest of the record still ships -- an out-of-set mechanism is
        # not treated like an out-of-set evidence_class (which strips the
        # whole value family); only the mechanism key itself is withheld.
        self.assertIn('value_low', meta)


if __name__ == '__main__':
    unittest.main()
