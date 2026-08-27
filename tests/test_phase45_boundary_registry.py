"""Phase 45 Plan 01 — the shared BoundaryRegistry primitive, and the proof
it is right: migrating the one boundary that already worked (Phase 36's
evaluator seam) onto it with zero edits to tests/test_phase36_evaluator_seam.py,
then carrying a second, non-LLM implementation's own declared evidence_class
all the way to the persisted JobAssessment record.

Requirements covered: EGV-01, EGV-02, EGV-03.

Every test here runs OFFLINE, matching tests/test_phase36_evaluator_seam.py's
own module docstring: no provider, no network, no subprocess.
"""

import ast
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'
CLASSIFIER_SOURCE_PATH = PLUGIN / 'classifier.py'


def _load_boundary_registry():
    """Import boundary_registry.py fresh by file path, with no package
    parent and no sys.path entry -- the same idiom
    tests/test_phase36_evaluator_seam.py's _load_evaluators() uses, and the
    exact loading shape this module's own third import fallback exists to
    survive."""
    spec = importlib.util.spec_from_file_location(
        'phase45_boundary_registry', str(PLUGIN / 'boundary_registry.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_evaluators():
    """Byte-identical to tests/test_phase36_evaluator_seam.py's own
    _load_evaluators() -- duplicated here (not imported) because the 452-line
    file this loader belongs to may not be edited, and importing a private
    helper from a sibling test module is a coupling this plan does not
    introduce."""
    spec = importlib.util.spec_from_file_location(
        'phase45_evaluators', str(PLUGIN / 'evaluators.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_classifier(env: "dict | None" = None):
    """Mirror of tests/test_phase36_evaluator_seam.py's own _load_classifier,
    duplicated here for the same reason _load_evaluators() is above."""
    import os
    env = env or {}
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(
            'phase45_classifier', str(CLASSIFIER_SOURCE_PATH))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class RegistryPrimitiveTests(unittest.TestCase):
    """Every property the shared primitive must have, one assertion method
    per behavior bullet in 45-01-PLAN.md's Task 1, so a failure names the
    property rather than a row number."""

    def setUp(self):
        self.br = _load_boundary_registry()

    def test_fresh_registry_resolves_nothing(self):
        reg = self.br.BoundaryRegistry('x')
        self.assertIsNone(reg.resolve('anything'))
        self.assertEqual('', reg.resolve_version('anything'))
        self.assertEqual('', reg.resolve_evidence_class('anything'))
        self.assertEqual([], reg.registered())

    def test_registered_is_sorted_and_stable(self):
        reg = self.br.BoundaryRegistry('x')
        fn = lambda: None
        reg.register('b', fn)
        reg.register('a', fn)
        self.assertEqual(['a', 'b'], reg.registered())
        self.assertEqual(['a', 'b'], reg.registered())

    def test_re_registering_a_name_replaces_it_last_wins(self):
        reg = self.br.BoundaryRegistry('x')
        first = lambda: 'first'
        second = lambda: 'second'
        reg.register('dup', first, version='1')
        reg.register('dup', second, version='2')
        self.assertIs(reg.resolve('dup'), second)
        self.assertEqual('2', reg.resolve_version('dup'))
        self.assertEqual(['dup'], reg.registered())

    def test_non_str_name_returns_defaults_not_raises(self):
        reg = self.br.BoundaryRegistry('x')
        for bad in (None, 42, [], {}, 3.14, True):
            with self.subTest(repr(bad)):
                self.assertIsNone(reg.resolve(bad))
                self.assertEqual('', reg.resolve_version(bad))
                self.assertEqual('', reg.resolve_evidence_class(bad))

    def test_version_and_evidence_class_coerce_none_to_empty_string(self):
        reg = self.br.BoundaryRegistry('x')
        fn = lambda: None
        reg.register('n', fn, version=None, evidence_class=None)
        self.assertEqual('', reg.resolve_version('n'))
        self.assertEqual('', reg.resolve_evidence_class('n'))

    def test_two_registries_with_the_same_name_do_not_see_each_other(self):
        f1 = lambda: 'one'
        f2 = lambda: 'two'
        reg_a = self.br.BoundaryRegistry('a')
        reg_b = self.br.BoundaryRegistry('b')
        reg_a.register('shared', f1)
        reg_b.register('shared', f2)
        self.assertIs(reg_a.resolve('shared'), f1)
        self.assertIs(reg_b.resolve('shared'), f2)

    def test_boundary_attribute_records_the_registry_name(self):
        reg = self.br.BoundaryRegistry('output_assessment')
        self.assertEqual('output_assessment', reg.boundary)

    def test_loading_by_file_path_with_no_package_parent_succeeds(self):
        # If setUp() above raised, this test would never run -- but assert
        # something concrete beyond "an object exists" for its own sake.
        self.assertTrue(hasattr(self.br, 'BoundaryRegistry'))
        self.assertTrue(hasattr(self.br, 'MASQUERADE_CLASS'))
        self.assertTrue(hasattr(self.br, 'is_masquerading'))


class MasqueradeTests(unittest.TestCase):
    """is_masquerading()'s four cases."""

    def setUp(self):
        self.br = _load_boundary_registry()
        self.reg = self.br.BoundaryRegistry('x')
        fn = lambda: None
        self.reg.register('masquerader', fn, evidence_class=self.br.MASQUERADE_CLASS)
        self.reg.register('honest', fn, evidence_class='OUTCOME_OBSERVED')
        self.reg.register('undeclared', fn)

    def test_true_when_declared_class_is_the_masquerade_class(self):
        self.assertTrue(self.br.is_masquerading(self.reg, 'masquerader'))

    def test_false_for_unregistered_name(self):
        self.assertFalse(self.br.is_masquerading(self.reg, 'nope'))

    def test_false_for_empty_declaration(self):
        self.assertFalse(self.br.is_masquerading(self.reg, 'undeclared'))

    def test_false_for_any_other_label(self):
        self.assertFalse(self.br.is_masquerading(self.reg, 'honest'))


class BoundaryRegistryImportGuardTests(unittest.TestCase):
    """D-08/D-09/T-45-07: boundary_registry.py imports `logging` and nothing
    else -- no os, no pathlib, no sqlite3, no subprocess, no classifier, no
    Hermes-side `agent` module."""

    def test_module_scope_imports_only_logging(self):
        tree = ast.parse((PLUGIN / 'boundary_registry.py').read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split('.')[0])
        self.assertEqual({'logging'}, imported)


class SeamMigrationTests(unittest.TestCase):
    """Phase 45 Plan 01 Task 2 -- evaluators.py migrated onto BoundaryRegistry
    (D-04), and carries its first non-masquerading fixture (D-05/D-06 AMENDED).

    Deliberately scoped to evaluators.py alone, with NO classifier.py
    integration: `resolve_evidence_class('llm')`'s value depends on whether
    classifier.py's `_register_llm_evaluator` has pinned an explicit
    evidence_class, which is this plan's Task 3, not Task 2 -- asserting it
    here would make this test's pass/fail depend on task ORDER within the
    plan rather than on what Task 2 alone changed. The equivalent guarantee
    for 'llm' (that classifier._declared_evidence_class('llm') resolves to
    MODEL_ESTIMATED_DEMO) is Task 3's DeclaredEvidenceClassTests' job, and it
    exercises the real production code path (_declared_evidence_class), not
    a raw registry lookup.
    """

    def setUp(self):
        self.ev = _load_evaluators()

    def test_free_functions_still_exist_and_behave(self):
        self.assertIsNotNone(self.ev.resolve('stub'))
        self.assertIsNone(self.ev.resolve('nope'))
        self.assertIsNone(self.ev.resolve(None))
        self.assertIn('stub', self.ev.registered())

    def test_registry_is_a_boundary_registry_for_output_assessment(self):
        reg = self.ev._REGISTRY
        self.assertEqual('BoundaryRegistry', type(reg).__name__)
        self.assertEqual('output_assessment', reg.boundary)

    def test_stub_declares_the_masquerade_class(self):
        self.assertEqual('MODEL_ESTIMATED_DEMO', self.ev.resolve_evidence_class('stub'))

    def test_fixture_declares_outcome_observed_not_masquerade_class(self):
        got = self.ev.resolve_evidence_class('system_of_record_assessment_fixture')
        self.assertEqual('OUTCOME_OBSERVED', got)
        self.assertNotEqual('MODEL_ESTIMATED_DEMO', got)

    def test_fixture_abstains_on_failed_and_cancelled(self):
        fixture = self.ev.resolve('system_of_record_assessment_fixture')
        self.assertIsNotNone(fixture)
        self.assertIsNone(fixture({'status': 'FAILED'}, '', {}))
        self.assertIsNone(fixture({'status': 'CANCELLED'}, '', {}))

    def test_fixture_returns_a_dict_on_success(self):
        fixture = self.ev.resolve('system_of_record_assessment_fixture')
        got = fixture({'status': 'SUCCESS'}, '', {})
        self.assertIsInstance(got, dict)
        self.assertEqual('labor_substitution', got['economic_mechanism'])


class DeclaredEvidenceClassTests(unittest.TestCase):
    """Phase 45 Plan 01 Task 3 -- classifier._declared_evidence_class(evaluator)
    carries a registered implementation's own declared evidence_class into
    the persisted record, and a returned `evidence_class` key on the
    untrusted response is still ignored (D-06 AMENDED).

    PLUGIN is put on sys.path for this class only, so classifier.py's own
    `import evaluators as _ev` fallback (used by both _register_llm_evaluator
    and _declared_evidence_class) resolves to the SAME 'evaluators' module
    that registers 'stub' and 'system_of_record_assessment_fixture' at its
    own import time -- mirroring tests/test_repository.py's
    _setup_plugin_env/_restore_plugin_env pattern.
    """

    @classmethod
    def setUpClass(cls):
        import sys
        cls._path_added = str(PLUGIN) not in sys.path
        if cls._path_added:
            sys.path.insert(0, str(PLUGIN))

    @classmethod
    def tearDownClass(cls):
        import sys
        if cls._path_added and str(PLUGIN) in sys.path:
            sys.path.remove(str(PLUGIN))

    def setUp(self):
        self.mod = _load_classifier({})

    # 1. Every path that worked before this phase is unchanged.
    def test_llm_and_stub_are_both_model_estimated_demo(self):
        self.assertEqual('MODEL_ESTIMATED_DEMO', self.mod._declared_evidence_class('llm'))
        self.assertEqual('MODEL_ESTIMATED_DEMO', self.mod._declared_evidence_class('stub'))

    # 2. The registered non-LLM fixture's own declaration reaches through.
    def test_fixture_is_outcome_observed(self):
        self.assertEqual(
            'OUTCOME_OBSERVED',
            self.mod._declared_evidence_class('system_of_record_assessment_fixture'),
        )

    # 3. Every other outcome falls back to the forced constant.
    def test_unregistered_and_malformed_names_fall_back_to_forced(self):
        forced = self.mod._forced_evidence_class()
        self.assertEqual(forced, self.mod._declared_evidence_class('never-registered'))
        self.assertEqual(forced, self.mod._declared_evidence_class(None))
        self.assertEqual(forced, self.mod._declared_evidence_class(42))
        # A registrant deliberately registered with a label outside the nine.
        import evaluators as _ev
        _ev.register('out_of_set_fixture', lambda *a: None, '1',
                      evidence_class='NOT_A_REAL_LABEL')
        self.assertEqual(forced, self.mod._declared_evidence_class('out_of_set_fixture'))

    # 4. THE END-TO-END PROOF: real construction path, ACCEPTED not abstained.
    def test_end_to_end_record_carries_outcome_observed(self):
        import evaluators as _ev
        fixture = _ev.resolve('system_of_record_assessment_fixture')
        raw = fixture({'status': 'SUCCESS'}, '', {})
        self.assertIsNotNone(raw)

        valid_job = {
            'agentic_job_id': 'sor-proof-001', 'job_type': 'code_review', 'status': 'SUCCESS',
        }
        cfg = {}
        validated = self.mod._validate_assessment(
            raw, cfg, 'system_of_record_assessment_fixture', '1')
        self.assertIsNotNone(
            validated,
            'the fixture output must be ACCEPTED for this test to be meaningful',
        )
        self.assertEqual('OUTCOME_OBSERVED', validated['evidence_class'])

        record = self.mod._build_job_assessment(
            valid_job, validated, raw, cfg, 'system_of_record_assessment_fixture', '1')
        self.assertIsNotNone(record)
        self.assertEqual('OUTCOME_OBSERVED', record['evidence_class'])
        # `evaluator` is byte-clamped to 32 (_clamp_assessment_text, same as
        # every other evaluator name) -- 'system_of_record_assessment_fixture'
        # is 35 ASCII bytes, so the record legitimately carries the clamped
        # prefix, not the full registrant name.
        self.assertEqual(
            self.mod._clamp_assessment_text('system_of_record_assessment_fixture', 32),
            record['evaluator'],
        )

    # 5. THE ANTI-MASQUERADE PROOF: a returned key is ignored.
    def test_returned_evidence_class_key_is_ignored(self):
        import evaluators as _ev
        fixture = _ev.resolve('system_of_record_assessment_fixture')
        raw = fixture({'status': 'SUCCESS'}, '', {})
        raw = dict(raw, evidence_class='EXPERIMENTAL_IMPACT')

        valid_job = {
            'agentic_job_id': 'sor-proof-002', 'job_type': 'code_review', 'status': 'SUCCESS',
        }
        cfg = {}
        validated = self.mod._validate_assessment(
            raw, cfg, 'system_of_record_assessment_fixture', '1')
        self.assertIsNotNone(validated)
        record = self.mod._build_job_assessment(
            valid_job, validated, raw, cfg, 'system_of_record_assessment_fixture', '1')
        self.assertIsNotNone(record)
        self.assertEqual('OUTCOME_OBSERVED', record['evidence_class'])
        self.assertNotEqual('EXPERIMENTAL_IMPACT', record['evidence_class'])

    # 6. Phase 43's own static guard, re-run against this module unmodified.
    def test_phase43_static_guards_report_no_offenders(self):
        import ast
        from tests.test_phase43_evidence_grading import (
            _assert_functions_declare_untrusted_param,
            _find_forbidden_raw_reads,
        )
        tree = ast.parse(CLASSIFIER_SOURCE_PATH.read_text())
        param_offenders = _assert_functions_declare_untrusted_param(tree, 'classifier.py')
        self.assertEqual([], param_offenders)
        read_offenders = _find_forbidden_raw_reads(tree, 'classifier.py')
        self.assertEqual([], read_offenders)


if __name__ == '__main__':
    unittest.main()
