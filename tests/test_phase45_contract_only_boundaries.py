"""Phase 45 Plan 03 Task 1 — the cohort-impact registry: empty, and
provably able to accept one.

Every test here runs OFFLINE, matching tests/test_phase36_evaluator_seam.py's
own module docstring: no provider, no network, no subprocess.
"""

import ast
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'


def _load_module(filename, modname):
    """Import a plugin module fresh by file path, no package parent, no
    sys.path entry -- the idiom tests/test_phase36_evaluator_seam.py's
    _load_evaluators() and tests/test_phase45_boundary_registry.py's own
    loaders use. A fresh module object per call means a fresh, empty
    `_REGISTRY` per call -- no cross-test registration leakage."""
    spec = importlib.util.spec_from_file_location(modname, str(PLUGIN / filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_cohort_impact():
    return _load_module('cohort_impact.py', 'phase45_cohort_impact')


def _load_impact_study():
    return _load_module('impact_study.py', 'phase45_impact_study')


def _load_boundary_registry():
    return _load_module('boundary_registry.py', 'phase45_boundary_registry_contract_only')


class EmptyRegistryTests(unittest.TestCase):
    """D-03: a freshly imported cohort_impact ships with ZERO registrants.
    Covers the first three behavior bullets of 45-03-PLAN.md Task 1.
    """

    def setUp(self):
        self.ci = _load_cohort_impact()

    def test_resolve_anything_is_none(self):
        self.assertIsNone(self.ci.resolve('anything'))

    def test_resolve_version_and_evidence_class_are_empty_string(self):
        self.assertEqual('', self.ci.resolve_version('anything'))
        self.assertEqual('', self.ci.resolve_evidence_class('anything'))

    def test_registered_is_empty_list(self):
        self.assertEqual([], self.ci.registered())


class CohortFixtureTests(unittest.TestCase):
    """The empty registry still accepts a registrant, and the registrant it
    accepts produces a result the REAL impact_study.validate() contract
    accepts. Covers the remaining behavior bullets of Task 1.
    """

    def setUp(self):
        self.ci = _load_cohort_impact()
        self.br = _load_boundary_registry()
        self.ci.register(
            'cohort_estimator_impact_fixture',
            self.ci._cohort_estimator_impact_fixture,
            self.ci.COHORT_FIXTURE_VERSION,
            evidence_class='QUASI_EXPERIMENTAL_IMPACT',
        )

    def test_registered_estimator_resolves_back(self):
        fn = self.ci.resolve('cohort_estimator_impact_fixture')
        self.assertIs(fn, self.ci._cohort_estimator_impact_fixture)
        self.assertEqual(
            'QUASI_EXPERIMENTAL_IMPACT',
            self.ci.resolve_evidence_class('cohort_estimator_impact_fixture'),
        )
        self.assertEqual(['cohort_estimator_impact_fixture'], self.ci.registered())

    def test_declared_label_is_not_the_masquerade_class(self):
        self.assertFalse(
            self.br.is_masquerading(self.ci._REGISTRY, 'cohort_estimator_impact_fixture')
        )

    def test_fixture_output_satisfies_the_real_impact_study_contract(self):
        istudy = _load_impact_study()
        cohort = {
            'population': 25,
            'treated_mean': 12.0,
            'control_mean': 8.0,
            'window_start': 1000.0,
            'window_end': 2000.0,
        }
        candidate = self.ci._cohort_estimator_impact_fixture(cohort, {'currency': 'USD'})
        self.assertIsInstance(candidate, dict)
        validated = istudy.validate(candidate)
        self.assertIsNotNone(
            validated,
            'the fixture must produce output the REAL impact_study contract '
            'accepts -- a fixture that only proves the registry stores a '
            'callable tests the registry, not the contract',
        )

    def test_fixture_abstains_on_non_dict_empty_and_reversed_interval(self):
        fn = self.ci._cohort_estimator_impact_fixture
        self.assertIsNone(fn('not a dict', {}))
        self.assertIsNone(fn({}, {}))
        # population <= 0 is rejected outright (never reaches the interval
        # math at all) -- covers the "empty cohort" bullet.
        self.assertIsNone(fn({'population': 0, 'treated_mean': 1.0, 'control_mean': 1.0}, {}))
        # A caller-supplied NEGATIVE interval_margin reverses value_low and
        # value_high (effect - margin > effect + margin), which is the
        # reversed-interval input the fixture's own abstention guard exists
        # to reject -- reached through legitimate cohort input, not a
        # synthetic call into an otherwise-unreachable branch.
        self.assertIsNone(fn(
            {'population': 10, 'treated_mean': 5.0, 'control_mean': 3.0, 'interval_margin': -1.0},
            {},
        ))

    def test_fixture_imports_no_network_or_clock_module(self):
        """'No model call, no network call and reads no clock' -- proven by
        the module's own import graph excluding every module that would
        make one possible."""
        tree = ast.parse((PLUGIN / 'cohort_impact.py').read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split('.')[0])
        forbidden = {'time', 'datetime', 'socket', 'requests', 'urllib', 'http', 'ssl'}
        self.assertEqual(set(), imported & forbidden)


class ImportGuardTests(unittest.TestCase):
    """D-08: an ast-based import-guard over this plan's new contract
    modules, extending tests/test_phase36_evaluator_seam.py's
    test_module_does_not_import_classifier and
    tests/test_phase43_impact_study.py's own copy of the same idiom.
    Parsed rather than grepped for the same reason both of those are: a
    substring search would match the very comment documenting the rule and
    fail on a compliant file.
    """

    _FORBIDDEN = frozenset({'classifier', 'agent', 'os', 'pathlib', 'sqlite3', 'subprocess'})

    @staticmethod
    def _imported_top_level_names(path):
        tree = ast.parse(path.read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split('.')[0])
        return imported

    def test_cohort_impact_does_not_import_forbidden_modules_or_impact_study(self):
        imported = self._imported_top_level_names(PLUGIN / 'cohort_impact.py')
        self.assertEqual(set(), imported & self._FORBIDDEN)
        # PA-10: cohort_impact.py must not import impact_study.py, because
        # that module's own load-bearing property is that NOTHING in the
        # shipped skill imports it.
        self.assertNotIn('impact_study', imported)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
