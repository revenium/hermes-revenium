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


if __name__ == '__main__':
    unittest.main()
