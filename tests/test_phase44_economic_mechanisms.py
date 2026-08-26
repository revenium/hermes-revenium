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


if __name__ == '__main__':
    unittest.main()
