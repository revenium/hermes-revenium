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
import ast
import asyncio
import importlib.util
import json
import os
import shlex
import shutil
import sys as _sys
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
PLUGIN_DIR = PLUGIN

# ---------------------------------------------------------------------------
# In-process classifier harness for driving _attach_assessment through a
# REGISTERED evaluator -- isolated-import pattern copied from
# tests/test_phase42_assessment_contract.py's own copy of it (a UNIQUE
# module name per call, since the classifier binds its path constants at
# import time and Python caches submodules by name). Restored per-test, not
# just at module teardown, in case a later class in this SAME run inherits
# a dangling env var. Distinct from _load_classifier above, which loads
# classifier.py directly (no evaluators submodule) for the pure-function
# resolver/prompt tests that need no evaluator registration.
# ---------------------------------------------------------------------------
_LOAD_SEQ = [0]
_ENV_TOUCHED = set()
_ENV_SAVED = {}


def setUpModule():
    for k in ('REVENIUM_STATE_DIR', 'REVENIUM_MARKERS_DIR', 'REVENIUM_CONFIG_FILE',
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
    for cached in [k for k in list(_sys.modules) if k.startswith('p44_pkg')]:
        del _sys.modules[cached]


def _load_classifier_package(env=None):
    """Import the revenium-classifier plugin (through __init__.py, so its
    `evaluators` submodule is reachable) fresh; return (classifier,
    evaluators)."""
    for k, v in (env or {}).items():
        os.environ[k] = v
        _ENV_TOUCHED.add(k)
    _LOAD_SEQ[0] += 1
    name = f'p44_pkg_{_LOAD_SEQ[0]}'
    for cached in [k for k in _sys.modules if k.startswith('p44_pkg')]:
        del _sys.modules[cached]
    spec = importlib.util.spec_from_file_location(
        name, str(PLUGIN_DIR / '__init__.py'), submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    _sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return _sys.modules[f'{name}.classifier'], _sys.modules[f'{name}.evaluators']


def _mechanism_shape_env(tmpdir, evaluator_name='p44-shape-stub'):
    """A minimal state tree with LLM outcome evaluation opted in for
    `evaluator_name` -- mirrors
    tests/test_phase42_assessment_contract.py::_p42_shape_env, used here to
    drive _attach_assessment directly."""
    state_dir = os.path.join(tmpdir, 'state')
    os.makedirs(state_dir, exist_ok=True)
    config_file = os.path.join(state_dir, 'config.json')
    with open(config_file, 'w') as f:
        json.dump({'llmOutcomeEvaluation': {
            'enabled': True, 'evaluator': evaluator_name, 'currency': 'USD',
        }}, f)
    return {
        'REVENIUM_STATE_DIR': state_dir,
        'REVENIUM_CONFIG_FILE': config_file,
    }


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


class PromptBranchTests(unittest.TestCase):
    """D-02 -- the three mechanism-labelled prompt branches, and the
    mechanism-independent shared text that must survive in every branch.
    Behavioural substring assertions over the string the model will
    actually see, not an ast walk over the code that builds it
    (44-RESEARCH.md Finding 10: the ast-guard is the right tool for
    data-flow claims and the wrong tool for prompt-text claims)."""

    def setUp(self):
        self.mod = _load_classifier({})

    def _prompt(self, config=None):
        return self.mod._build_outcome_evaluation_prompt(
            {'job_type': 'code_review', 'job_name': 'review a PR'},
            'transcript text', config or {},
        )

    def test_labor_substitution_and_augmentation_demand_role_hours_rate(self):
        for mechanism in (
            'labor_substitution', 'augmentation_capacity_expansion',
        ):
            with self.subTest(mechanism=mechanism):
                block = self.mod._mechanism_instruction_block(
                    mechanism, 40, 500, 'USD')
                self.assertIn('inferred_role', block)
                self.assertIn('estimated_hours_saved', block)
                self.assertIn('assumed_loaded_rate', block)

    def test_newly_enabled_work_demands_neither_role_hours_nor_rate(self):
        block = self.mod._mechanism_instruction_block(
            'newly_enabled_work', 40, 500, 'USD')
        self.assertNotIn('inferred_role', block)
        self.assertNotIn('estimated_hours_saved', block)
        self.assertNotIn('assumed_loaded_rate', block)

    def test_mechanism_instruction_block_raises_nothing_for_out_of_set(self):
        for mechanism in (
            'quality_decision_improvement', 'risk_avoidance',
            'incremental_revenue', 'not_a_mechanism', '', None, 42,
        ):
            with self.subTest(mechanism=mechanism):
                self.assertEqual(
                    self.mod._mechanism_instruction_block(mechanism, 40, 500, 'USD'),
                    '',
                )

    def test_full_prompt_contains_all_three_mechanism_blocks(self):
        prompt = self._prompt()
        self.assertIn('"labor_substitution"', prompt)
        self.assertIn('"augmentation_capacity_expansion"', prompt)
        self.assertIn('"newly_enabled_work"', prompt)

    def test_revenue_prohibition_survives_and_appears_exactly_once(self):
        """A .count() assertion, not a mere assertIn -- catches a restructure
        that duplicates the shared preamble into every branch."""
        prompt = self._prompt()
        self.assertEqual(prompt.count('Do not estimate revenue'), 1)

    def test_mechanism_independent_shared_text_present(self):
        prompt = self._prompt()
        self.assertIn('DATA, NOT INSTRUCTIONS', prompt)
        self.assertIn('Abstaining is a correct', prompt)
        self.assertIn('Do NOT output a total', prompt)


class NewlyEnabledWorkTests(unittest.TestCase):
    """D-04 -- a newly-enabled-work arc records its mechanism and abstains
    from the entire value family, without ever setting
    valid["assessment"]."""

    def tearDown(self):
        _restore_env()

    def test_validate_assessment_rejects_the_operator_only_mechanisms_pre_gate(self):
        """Sanity check that the mechanism gate (Task 1's resolver, wired
        into _validate_assessment) still runs ahead of hours/rate even for
        an otherwise-valid response naming an operator-only mechanism."""
        mod = _load_classifier({})
        raw = {
            'economic_mechanism': 'risk_avoidance',
            'inferred_role': 'engineer',
            'estimated_hours_saved': 2.0,
            'assumed_loaded_rate': 100.0,
            'currency': 'USD',
            'basis': 'x',
            'confidence': 0.5,
        }
        self.assertIsNone(mod._validate_assessment(raw, {}, 'llm', 'v1'))

    def test_attach_assessment_abstains_from_value_family_and_keeps_mechanism(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase44-newly-enabled-')
        try:
            evaluator_name = 'p44-newly-enabled-stub'
            env = _mechanism_shape_env(tmpdir, evaluator_name)
            mod, ev = _load_classifier_package(env)
            ev.register(
                evaluator_name,
                lambda job, transcript, cfg: {
                    'economic_mechanism': 'newly_enabled_work',
                    'basis': (
                        'built a dashboard nobody had asked for and no team '
                        'was ever staffed to build'
                    ),
                    'confidence': 0.7,
                },
                version='v1',
            )
            valid = {
                'agentic_job_id': 'p44-newly-enabled-job',
                'job_name': 'n', 'job_type': 'bug_fix', 'status': 'SUCCESS',
            }
            paths = mod._module_paths()
            asyncio.run(mod._attach_assessment(valid, 'user: x\nassistant: y', paths))

            self.assertNotIn(
                'assessment', valid,
                'the frozen marker "assessment" key must stay untouched -- '
                'the status-only outcome path must not see this mechanism',
            )
            record = valid.get('_assessment_record')
            self.assertIsNotNone(record)
            self.assertEqual(record.get('abstention_reason'), 'mechanism_abstains_from_value')
            self.assertEqual(record.get('economic_mechanism'), 'newly_enabled_work')
            for value_key in (
                'value_low', 'value_base', 'value_high', 'bounds_source',
                'currency', 'estimated_value', 'assumptions',
            ):
                self.assertNotIn(
                    value_key, record,
                    f'{value_key!r} must be ABSENT from a newly_enabled_work '
                    'abstention record, not merely null',
                )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


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


class MechanismAuthorityTests(unittest.TestCase):
    """D-01/D-03 -- the three OPERATOR_ONLY_MECHANISMS values are provably
    unreachable from evaluator output, over the REAL constructors
    (_validate_assessment and _build_job_assessment), not merely by
    inspecting _resolve_economic_mechanism in isolation."""

    def setUp(self):
        self.mod = _load_classifier({})

    def _otherwise_valid_raw(self, mechanism):
        return {
            'economic_mechanism': mechanism,
            'inferred_role': 'engineer',
            'estimated_hours_saved': 2.5,
            'assumed_loaded_rate': 150.0,
            'currency': 'USD',
            'basis': 'time avoided',
            'confidence': 0.5,
        }

    def test_each_operator_only_mechanism_is_rejected_by_validate_assessment(self):
        # A shrunken OPERATOR_ONLY_MECHANISMS would silently skip cases
        # below rather than fail loudly -- assert the count first.
        self.assertEqual(
            len(self.mod.OPERATOR_ONLY_MECHANISMS), 3,
            'OPERATOR_ONLY_MECHANISMS must have exactly 3 members for this '
            'test to cover all of D-01\'s operator-only mechanisms',
        )
        for mechanism in self.mod.OPERATOR_ONLY_MECHANISMS:
            with self.subTest(mechanism=mechanism):
                got = self.mod._validate_assessment(
                    self._otherwise_valid_raw(mechanism), {}, 'llm', 'v1')
                self.assertIsNone(
                    got,
                    f'{mechanism!r} is operator-only and must abstain even '
                    'when every other field is in-bounds',
                )

    def test_each_operator_only_mechanism_never_reaches_the_record(self):
        for mechanism in self.mod.OPERATOR_ONLY_MECHANISMS:
            with self.subTest(mechanism=mechanism):
                raw = self._otherwise_valid_raw(mechanism)
                valid = {
                    'agentic_job_id': f'auth-{mechanism}',
                    'job_type': 'code_review', 'status': 'SUCCESS',
                }
                # abstention_reason set directly (bypassing
                # _validate_assessment, which already proved None above) --
                # economic_mechanism is resolved unconditionally in
                # _build_job_assessment's record literal, ahead of the
                # abstention early return, so this still exercises the
                # resolution this test is about.
                record = self.mod._build_job_assessment(
                    valid, None, raw, {}, 'llm', 'v1',
                    abstention_reason='rejected',
                )
                self.assertIsNotNone(record)
                self.assertEqual(
                    record['economic_mechanism'], self.mod.ECONOMIC_MECHANISM_UNKNOWN,
                )
                self.assertNotEqual(
                    record['economic_mechanism'], mechanism,
                    f'record must never carry the operator-only value {mechanism!r} '
                    'the response named',
                )

    def test_whitespace_stripped_accepted_case_mismatch_rejected(self):
        """The resolver strips but does not case-fold -- coercion is what
        D-03 forbids."""
        self.assertEqual(
            self.mod._resolve_economic_mechanism(
                {'economic_mechanism': '  labor_substitution  '}),
            'labor_substitution',
        )
        self.assertEqual(
            self.mod._resolve_economic_mechanism(
                {'economic_mechanism': 'Labor_Substitution'}),
            self.mod.ECONOMIC_MECHANISM_UNKNOWN,
        )


class MechanismDriftTests(unittest.TestCase):
    """D-01/D-02 -- classifier.py's ECONOMIC_MECHANISMS and
    hermes-report.sh's _ECONOMIC_MECHANISMS are a HAND-SYNCED pair.
    CLAUDE.md names sharing code between classifier.py and the bash
    sidecars as an anti-pattern, so this test -- replicating
    tests/test_phase43_evidence_grading.py::LabelDriftTests' shape exactly
    -- is the only thing holding the two declarations equal. Deleting it
    silently re-opens the drift.

    Guarantee class: BEHAVIOURAL. This proves the two live declarations
    agree right now, read directly from source on every run -- not that
    they can never diverge in the future.
    """

    def test_classifier_and_reporter_mechanism_sets_agree(self):
        from tests.test_phase43_evidence_grading import (
            _extract_frozenset_assignment_fragment,
            _extract_frozenset_from_module,
        )

        classifier_tree = ast.parse(CLASSIFIER_SOURCE_PATH.read_text())
        classifier_mechanisms = _extract_frozenset_from_module(
            classifier_tree, 'ECONOMIC_MECHANISMS',
        )
        self.assertIsNotNone(
            classifier_mechanisms,
            'ECONOMIC_MECHANISMS could not be extracted from classifier.py '
            '-- the declaration moved and this extractor needs updating',
        )

        reporter_text = HERMES_REPORT_PATH.read_text()
        reporter_mechanisms = _extract_frozenset_assignment_fragment(
            reporter_text, '_ECONOMIC_MECHANISMS',
        )
        self.assertIsNotNone(
            reporter_mechanisms,
            '_ECONOMIC_MECHANISMS could not be extracted from '
            'hermes-report.sh -- the declaration moved and this extractor '
            'needs updating',
        )

        self.assertEqual(
            classifier_mechanisms, reporter_mechanisms,
            'classifier.py and hermes-report.sh have drifted on the '
            'six-mechanism set',
        )


class MechanismGuardScopeTests(unittest.TestCase):
    """D-03 -- economic_mechanism is deliberately ABSENT from
    tests/test_phase43_evidence_grading.py's _PROMOTION_FORBIDDEN_KEYS.
    D-03 PERMITS reading this key off `raw`; the guarantee is over the
    accepted VALUE SET (proven by MechanismAuthorityTests above), not over
    the key. Without this test a future reviewer "tightening" the guard by
    adding this key would silently break mechanism selection entirely, and
    the failure would look like an evaluator problem rather than a guard
    problem."""

    def test_economic_mechanism_is_not_a_promotion_forbidden_key(self):
        from tests.test_phase43_evidence_grading import _PROMOTION_FORBIDDEN_KEYS

        self.assertNotIn('economic_mechanism', _PROMOTION_FORBIDDEN_KEYS)


# ---------------------------------------------------------------------------
# Plan 44-02 — EGV-14 (net value across every supplied cost) and EGV-15
# (zero/unknown denominators explicit, no ratio ever emitted).
# ---------------------------------------------------------------------------


def _nv_raw(**over):
    raw = {
        'economic_mechanism': 'labor_substitution',
        'inferred_role': 'engineer', 'estimated_hours_saved': 3.5,
        'assumed_loaded_rate': 150.0, 'currency': 'USD',
        'basis': 'time avoided', 'confidence': 0.5,
    }
    raw.update(over)
    return raw


def _nv_valid(job_id, job_type='bug_fix'):
    return {'agentic_job_id': job_id, 'job_type': job_type, 'status': 'SUCCESS'}


class NetValueTests(unittest.TestCase):
    """EGV-14, D-06/D-08/D-09 -- net_value subtracts every supplied cost
    category (not AI cost alone), is absent from an abstained record while
    supplied_costs/cost_coverage remain present, is not clamped at zero,
    and no ratio is ever emitted alongside it. Exercised over the REAL
    _validate_assessment/_build_job_assessment constructors, never a
    hand-authored record literal."""

    def setUp(self):
        self.mod = _load_classifier({})

    def _record(self, job_id, cfg, job_type='bug_fix'):
        raw = _nv_raw()
        assessment = self.mod._validate_assessment(raw, cfg, 'llm', 'v1')
        self.assertIsNotNone(assessment, 'fixture must validate for this test to prove anything')
        rec = self.mod._build_job_assessment(
            _nv_valid(job_id, job_type), assessment, raw, cfg, 'llm', 'v1')
        self.assertIsNotNone(rec)
        return rec

    def test_no_costs_configured_net_value_equals_estimated_value(self):
        rec = self._record('nv44-job-001', {})
        self.assertEqual(rec['net_value'], rec['estimated_value'])
        self.assertEqual(rec['supplied_costs'], {})
        self.assertEqual(rec['cost_coverage']['included'], [])
        self.assertEqual(
            rec['cost_coverage']['unknown'], list(self.mod.COST_CATEGORIES))
        self.assertEqual(rec['cost_coverage']['excluded'], ['metered_ai_cost'])

    def test_partial_costs_subtract_only_the_supplied_categories(self):
        cfg = {'costs': {'bug_fix': {'human_review': 25, 'integration': 10}}}
        rec = self._record('nv44-job-002', cfg)
        self.assertEqual(
            rec['supplied_costs'], {'human_review': 25.0, 'integration': 10.0})
        self.assertEqual(rec['net_value'], round(rec['estimated_value'] - 35.0, 2))

    def test_costs_configured_for_a_different_job_type_do_not_apply(self):
        """PA-06: there is no fleet-wide default cost bucket -- an absent
        job-type key means every category is unknown for THIS job type,
        exactly as if no costs were configured at all."""
        cfg = {'costs': {'other_type': {'human_review': 999}}}
        rec = self._record('nv44-job-003', cfg, job_type='bug_fix')
        self.assertEqual(rec['supplied_costs'], {})
        self.assertEqual(
            rec['cost_coverage']['unknown'], list(self.mod.COST_CATEGORIES))

    def test_costs_exceeding_the_estimate_produce_a_negative_net_value_not_clamped(self):
        cfg = {'costs': {'bug_fix': {
            'human_review': 100000, 'rework_or_error': 100000,
            'integration': 100000, 'training_or_change': 100000,
        }}}
        rec = self._record('nv44-job-004', cfg)
        self.assertLess(rec['net_value'], 0)

    def test_no_ratio_field_is_ever_emitted(self):
        rec = self._record('nv44-job-005', {})
        for forbidden in ('roi', 'net_over_cost', 'roi_ratio', 'ratio'):
            self.assertNotIn(forbidden, rec)

    def test_net_value_absent_from_an_abstained_record_but_costs_present(self):
        valid = _nv_valid('nv44-job-006')
        cfg = {'costs': {'bug_fix': {'human_review': 25}}}
        rec = self.mod._build_job_assessment(
            valid, None, {}, cfg, 'llm', 'v1',
            abstention_reason='not_evaluated_non_success',
        )
        self.assertIsNotNone(rec)
        self.assertNotIn('net_value', rec)
        self.assertIn('supplied_costs', rec)
        self.assertIn('cost_coverage', rec)
        self.assertEqual(rec['supplied_costs'], {'human_review': 25.0})

    def test_malformed_cost_values_resolve_to_unknown_not_zero(self):
        bad_values = [-5, float('nan'), float('inf'), True, None, '25', {'x': 1}]
        for bad in bad_values:
            with self.subTest(value=bad):
                supplied, coverage = self.mod._resolve_supplied_costs(
                    {'costs': {'bug_fix': {'human_review': bad}}}, 'bug_fix')
                self.assertNotIn('human_review', supplied)
                self.assertIn('human_review', coverage['unknown'])
                self.assertNotIn('human_review', coverage['included'])
                self.assertNotIn('human_review', coverage['known_zero'])

    def test_unrecognised_cost_key_is_ignored_entirely(self):
        supplied, coverage = self.mod._resolve_supplied_costs(
            {'costs': {'bug_fix': {'made_up_category': 10}}}, 'bug_fix')
        self.assertNotIn('made_up_category', supplied)
        for lst in coverage.values():
            self.assertNotIn('made_up_category', lst)

    def test_resolve_supplied_costs_signature_has_no_raw_parameter(self):
        """T-44-06: structurally, not just by convention, the resolver
        cannot read evaluator output."""
        import inspect
        params = list(inspect.signature(self.mod._resolve_supplied_costs).parameters)
        self.assertNotIn('raw', params)


class DenominatorTests(unittest.TestCase):
    """EGV-15, D-09/D-10 -- a supplied 0 and an absent category are
    different and both explicit; no ratio is ever emitted so there is no
    denominator to be null."""

    def setUp(self):
        self.mod = _load_classifier({})

    def test_supplied_zero_distinguishable_from_absent_category(self):
        """The load-bearing negative check (44-02-PLAN.md warning 3): this
        assertion pair is what actually distinguishes D-10's two adjacent
        cases -- deleting the known-zero branch in _resolve_supplied_costs
        must make this test fail."""
        empty_supplied, empty_coverage = self.mod._resolve_supplied_costs({}, 'bug_fix')
        zero_supplied, zero_coverage = self.mod._resolve_supplied_costs(
            {'costs': {'bug_fix': {'human_review': 0}}}, 'bug_fix')

        self.assertEqual(empty_coverage['known_zero'], [])
        self.assertEqual(zero_coverage['known_zero'], ['human_review'])

        self.assertEqual(len(empty_coverage['unknown']), 4)
        self.assertEqual(len(zero_coverage['unknown']), 3)

        self.assertNotIn('human_review', empty_supplied)
        self.assertIn('human_review', zero_supplied)
        self.assertEqual(zero_supplied['human_review'], 0.0)
        self.assertIn('human_review', zero_coverage['included'])

    def test_no_ratio_is_emitted_anywhere_in_a_real_record(self):
        mod = self.mod
        raw = _nv_raw()
        valid = _nv_valid('dn44-job-001')
        assessment = mod._validate_assessment(raw, {}, 'llm', 'v1')
        self.assertIsNotNone(assessment)
        rec = mod._build_job_assessment(valid, assessment, raw, {}, 'llm', 'v1')
        self.assertIsNotNone(rec)
        for key in rec:
            self.assertNotIn('roi', key.lower())
            self.assertNotIn('ratio', key.lower())


class CoverageOrderTests(unittest.TestCase):
    """EGV-14 ordering probe edge -- coverage list member order IS
    specified and IS stable: the fixed COST_CATEGORIES declaration order,
    never dict/set iteration order, so two records built from the same
    config are byte-identical across interpreters."""

    def test_included_and_unknown_follow_cost_categories_declaration_order(self):
        mod = _load_classifier({})
        cfg = {'costs': {'bug_fix': {
            'training_or_change': 5, 'human_review': 10,
        }}}
        supplied, coverage = mod._resolve_supplied_costs(cfg, 'bug_fix')
        self.assertEqual(coverage['included'], ['human_review', 'training_or_change'])
        self.assertEqual(coverage['unknown'], ['rework_or_error', 'integration'])
        self.assertEqual(list(supplied.keys()), ['human_review', 'training_or_change'])

    def test_byte_identical_serialization_across_two_separate_module_loads(self):
        mod1 = _load_classifier({})
        mod2 = _load_classifier({})
        cfg = {'costs': {'bug_fix': {'human_review': 0, 'integration': 15}}}
        s1, c1 = mod1._resolve_supplied_costs(cfg, 'bug_fix')
        s2, c2 = mod2._resolve_supplied_costs(cfg, 'bug_fix')
        self.assertEqual(json.dumps(s1), json.dumps(s2))
        self.assertEqual(json.dumps(c1), json.dumps(c2))
        # And the exact expected order/content, not merely self-consistency.
        self.assertEqual(s1, {'human_review': 0.0, 'integration': 15.0})
        self.assertEqual(c1['included'], ['human_review', 'integration'])
        self.assertEqual(c1['known_zero'], ['human_review'])


# ---------------------------------------------------------------------------
# Plan 44-02, Task 3 -- the value-omit family extension and the operand
# forwarders, driven end to end through the real hermes-report.sh.
# ---------------------------------------------------------------------------


def _cost_sidecar_record(job_id, reportability_status='reportable',
                          evidence_class='MODEL_ESTIMATED_DEMO', **overrides):
    """Minimal job-assessments sidecar record for driving hermes-report.sh's
    --metadata forwarder end to end, with net_value/supplied_costs/
    cost_coverage as the fields under test. Mirrors this module's own
    _mechanism_sidecar_record (itself mirroring
    tests/test_phase38_reporter_path.py's _sidecar_record) -- not imported
    across test modules, per this repo's per-file self-containment
    convention."""
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
        'value_low': 100.0,
        'value_base': 110.0,
        'value_high': 120.0,
        'bounds_source': 'derived',
        'currency': 'USD',
        'estimated_value': 110.0,
        'evaluator': 'llm',
        'evaluator_version': 'v1',
        'confidence': 0.8,
        'evidence_class': evidence_class,
        'assumptions': {
            'estimated_hours_saved': 1.0,
            'assumed_loaded_rate': 110.0,
        },
        'reportability_status': reportability_status,
        'economic_mechanism': 'labor_substitution',
        'net_value': 85.0,
        'supplied_costs': {'human_review': 25.0},
        'cost_coverage': {
            'included': ['human_review'],
            'known_zero': [],
            'unknown': ['rework_or_error', 'integration', 'training_or_change'],
            'excluded': ['metered_ai_cost'],
        },
    }
    record.update(overrides)
    return record


class ReporterStripTests(unittest.TestCase):
    """D-07 end-to-end -- net_value is withheld from a candidate assessment
    through the single shared _strip_value_family stripper, while
    supplied_costs and cost_coverage ship regardless of reportability.
    Driven through the real hermes-report.sh via the no-shift shim +
    synthetic state.db harness (same shape as MechanismWireTests above)."""

    def _run_one_outcome(self, sid, job_id, record):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase44-strip-')
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
                'job_name': 'Phase 44 Cost Strip Test',
                'job_type': 'code_review',
                'status': 'SUCCESS',
            }
            with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
                f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
                f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

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

    def test_candidate_row_withholds_net_value_but_ships_costs(self):
        record = _cost_sidecar_record('rs44-job-001', reportability_status='candidate')
        argv = self._run_one_outcome('rs44-sid-001', 'rs44-job-001', record)
        meta = json.loads(self._metadata_value(argv))
        self.assertNotIn('net_value', meta)
        self.assertIn('supplied_costs', meta)
        self.assertIn('cost_coverage', meta)
        self.assertEqual(meta['supplied_costs'], {'human_review': 25.0})

    def test_reportable_row_ships_net_value_too(self):
        record = _cost_sidecar_record('rs44-job-002', reportability_status='reportable')
        argv = self._run_one_outcome('rs44-sid-002', 'rs44-job-002', record)
        meta = json.loads(self._metadata_value(argv))
        self.assertIn('net_value', meta)
        self.assertEqual(meta['net_value'], 85.0)
        self.assertIn('supplied_costs', meta)
        self.assertIn('cost_coverage', meta)

    def test_evidence_class_rejected_row_still_ships_costs_not_net_value(self):
        record = _cost_sidecar_record(
            'rs44-job-003', reportability_status='reportable',
            evidence_class='NOT_A_REAL_EVIDENCE_CLASS')
        argv = self._run_one_outcome('rs44-sid-003', 'rs44-job-003', record)
        meta = json.loads(self._metadata_value(argv))
        self.assertNotIn('net_value', meta)
        self.assertIn('supplied_costs', meta)
        self.assertIn('cost_coverage', meta)

    def test_unknown_cost_category_key_dropped_from_metadata(self):
        record = _cost_sidecar_record(
            'rs44-job-004', reportability_status='reportable',
            supplied_costs={'human_review': 25.0, 'made_up_category': 999.0})
        argv = self._run_one_outcome('rs44-sid-004', 'rs44-job-004', record)
        meta = json.loads(self._metadata_value(argv))
        self.assertNotIn('made_up_category', meta['supplied_costs'])
        self.assertIn('human_review', meta['supplied_costs'])

    def test_cost_coverage_unknown_category_entry_dropped(self):
        record = _cost_sidecar_record(
            'rs44-job-005', reportability_status='reportable',
            cost_coverage={
                'included': ['human_review'],
                'known_zero': [],
                'unknown': ['rework_or_error', 'not_a_real_category'],
                'excluded': ['metered_ai_cost', 'not_the_ai_literal'],
            })
        argv = self._run_one_outcome('rs44-sid-005', 'rs44-job-005', record)
        meta = json.loads(self._metadata_value(argv))
        self.assertNotIn('not_a_real_category', meta['cost_coverage']['unknown'])
        self.assertIn('rework_or_error', meta['cost_coverage']['unknown'])
        self.assertNotIn('not_the_ai_literal', meta['cost_coverage']['excluded'])
        self.assertIn('metered_ai_cost', meta['cost_coverage']['excluded'])

    def test_non_numeric_supplied_cost_value_dropped_without_crashing(self):
        record = _cost_sidecar_record(
            'rs44-job-006', reportability_status='reportable',
            supplied_costs={'human_review': 'not-a-number'})
        argv = self._run_one_outcome('rs44-sid-006', 'rs44-job-006', record)
        # the arc still reports -- exactly one jobs outcome invocation is
        # already asserted inside _run_one_outcome.
        meta = json.loads(self._metadata_value(argv))
        self.assertNotIn('supplied_costs', meta)


def _extract_tuple_from_module(tree, target_name):
    """Read `target_name = (...)`'s string elements straight out of a
    parsed ast.Module, preserving ORDER -- unlike
    tests.test_phase43_evidence_grading._extract_frozenset_from_module,
    which returns an unordered set. EGV-14's ordering probe edge requires
    COST_CATEGORIES' emission order to be part of the contract, so this
    drift check must compare sequences, not sets.

    Refuses (returns None) if there are zero or more than one matching
    assignment, or if any element is not a plain string constant.
    """
    matches = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        if node.targets[0].id != target_name:
            continue
        if not isinstance(node.value, ast.Tuple):
            continue
        matches.append(node.value)
    if len(matches) != 1:
        return None
    elements = []
    for elt in matches[0].elts:
        if not isinstance(elt, ast.Constant) or not isinstance(elt.value, str):
            return None
        elements.append(elt.value)
    return tuple(elements)


def _extract_tuple_assignment_fragment(text, target_name):
    """Isolate the ONE `target_name = (...)` assignment out of a larger text
    blob and parse it -- the tuple-typed, order-preserving counterpart to
    tests.test_phase43_evidence_grading._extract_frozenset_assignment_fragment,
    used here because hermes-report.sh is bash with embedded Python heredocs
    and cannot be ast.parse'd as a whole.

    Refuses (returns None) if the anchor text does not appear exactly once,
    or if the isolated fragment does not parse as a single `NAME = (...)`
    assignment of string constants.
    """
    anchor = f'{target_name} = ('
    occurrences = [i for i in range(len(text)) if text.startswith(anchor, i)]
    if len(occurrences) != 1:
        return None
    start = occurrences[0]
    end = text.find(')', start)
    if end == -1:
        return None
    fragment = text[start:end + 1]
    try:
        tree = ast.parse(fragment)
    except SyntaxError:
        return None
    return _extract_tuple_from_module(tree, target_name)


class CostCategoryDriftTests(unittest.TestCase):
    """EGV-14 -- classifier.py's COST_CATEGORIES and hermes-report.sh's
    _COST_CATEGORIES are a HAND-SYNCED pair, proven equal AND
    ORDER-EQUAL -- unlike MechanismDriftTests' set comparison, emission
    order is part of EGV-14's contract (the ordering probe edge), so this
    compares tuples positionally, not sets."""

    def test_classifier_and_reporter_cost_categories_agree_in_order(self):
        classifier_tree = ast.parse(CLASSIFIER_SOURCE_PATH.read_text())
        classifier_categories = _extract_tuple_from_module(
            classifier_tree, 'COST_CATEGORIES')
        self.assertIsNotNone(
            classifier_categories,
            'COST_CATEGORIES could not be extracted from classifier.py -- '
            'the declaration moved and this extractor needs updating',
        )

        reporter_text = HERMES_REPORT_PATH.read_text()
        reporter_categories = _extract_tuple_assignment_fragment(
            reporter_text, '_COST_CATEGORIES')
        self.assertIsNotNone(
            reporter_categories,
            '_COST_CATEGORIES could not be extracted from hermes-report.sh '
            '-- the declaration moved and this extractor needs updating',
        )

        self.assertIsInstance(classifier_categories, tuple)
        self.assertIsInstance(reporter_categories, tuple)
        self.assertEqual(
            classifier_categories, reporter_categories,
            'classifier.py and hermes-report.sh have drifted on the '
            'four-cost-category tuple, or their declared order differs',
        )


if __name__ == '__main__':
    unittest.main()
