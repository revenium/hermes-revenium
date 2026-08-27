"""Phase 45 Plan 05 — the economic valuation boundary (EGV-01): the step
that turns an assessment's assumptions into money becomes a named contract
with a registry, a built-in `hours_times_rate` implementation, and an
operator-configured rate card that displaces it.

Every test in ContractTests/RateCardFixtureTests runs OFFLINE, matching
tests/test_phase36_evaluator_seam.py's own module docstring: no provider,
no network, no subprocess.

Registrant hygiene: every test that registers a throwaway implementation
into the module-level `valuation._REGISTRY` (a module loaded fresh per test
via `_load_valuation()`, or the real classifier package loaded fresh per
test via `_load_plugin_module()`) gets its own fresh module/registry --
`last-registration-wins` is a documented property of the shared
BoundaryRegistry helper (boundary_registry.py), and a leaked registrant is
the obvious way these tests could start lying to each other.
"""

import ast
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'


def _load_valuation():
    """Fresh valuation.py by file path, no package parent, no sys.path
    entry -- the idiom tests/test_phase36_evaluator_seam.py's
    _load_evaluators() and tests/test_phase45_classification_boundary.py's
    _load_classification() both use. A fresh module object per call means a
    fresh, empty-but-for-the-shipped-fixture `_REGISTRY` per call -- no
    cross-test registration leakage."""
    spec = importlib.util.spec_from_file_location(
        'phase45_valuation', str(PLUGIN / 'valuation.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_boundary_registry():
    spec = importlib.util.spec_from_file_location(
        'phase45_boundary_registry_valuation', str(PLUGIN / 'boundary_registry.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_classifier(env: "dict | None" = None):
    """Mirror of tests/test_phase36_evaluator_seam.py's own _load_classifier,
    duplicated here for the same reason every other Phase 45 test file's
    copy of it is. Loaded standalone (no package): classifier.py's own
    `from . import valuation` fallback then attempts a BARE `import
    valuation`, which only resolves when PLUGIN has been placed on
    sys.path -- see DerivationDelegationTests/BoundReassertionTests below,
    which do that deliberately; the plain ValidateAssessmentTests-style
    callers in this file never need it because an unresolved valuation
    module is exactly the fail-open path under test."""
    env = env or {}
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(
            'phase45_classifier_valuation_boundary', str(PLUGIN / 'classifier.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class ContractTests(unittest.TestCase):
    """The registry surface itself, and the shipped fixture's declared
    identity."""

    def setUp(self):
        self.val = _load_valuation()
        self.br = _load_boundary_registry()

    def test_fresh_import_resolves_only_the_shipped_fixture(self):
        self.assertEqual(['rate_card_valuation_fixture'], self.val.registered())
        self.assertIsNotNone(self.val.resolve('rate_card_valuation_fixture'))
        self.assertIsNone(self.val.resolve('hours_times_rate'))

    def test_shipped_fixture_declares_customer_configured(self):
        self.assertEqual(
            'CUSTOMER_CONFIGURED',
            self.val.resolve_evidence_class('rate_card_valuation_fixture'),
        )

    def test_shipped_fixture_is_not_masquerading(self):
        self.assertFalse(
            self.br.is_masquerading(self.val._REGISTRY, 'rate_card_valuation_fixture')
        )

    def test_resolve_unknown_name_is_none_empty_empty(self):
        self.assertIsNone(self.val.resolve('nope'))
        self.assertEqual('', self.val.resolve_version('nope'))
        self.assertEqual('', self.val.resolve_evidence_class('nope'))

    def test_registry_boundary_name(self):
        self.assertEqual('valuation', self.val._REGISTRY.boundary)

    def test_module_loads_by_file_path_with_no_package_parent(self):
        # If the import fallback chain were broken this would raise during
        # _load_valuation() itself, above in setUp -- this test just names
        # the property explicitly.
        self.assertIsNotNone(self.val)

    def test_import_graph_excludes_host_and_classifier_modules(self):
        """D-08: parsed with ast, not grepped -- the module docstring
        DOCUMENTS the dependency-direction rule in prose, so a substring
        search for 'import classifier' matches the very comment explaining
        the invariant and fails on a compliant file."""
        tree = ast.parse((PLUGIN / 'valuation.py').read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split('.')[0])
        forbidden = {'classifier', 'agent', 'os', 'pathlib', 'sqlite3', 'subprocess'}
        self.assertEqual(set(), imported & forbidden)


class RateCardFixtureTests(unittest.TestCase):
    """One method per behavior bullet of 45-05-PLAN.md Task 1, including
    every abstention case named there: absent card, non-dict card, unknown
    role, non-finite amount, non-positive amount."""

    def setUp(self):
        self.val = _load_valuation()
        self.fn = self.val._rate_card_valuation_fixture

    def _assumptions(self, **over):
        base = {
            'estimated_hours_saved': 2.5,
            'assumed_loaded_rate': 150.0,
            'currency': 'USD',
            'economic_mechanism': 'labor_substitution',
            'inferred_role': 'senior_engineer',
        }
        base.update(over)
        return base

    def test_returns_configured_role_amount_with_assumptions_currency(self):
        config = {'rateCard': {'senior_engineer': 480.0}}
        result = self.fn(self._assumptions(), config)
        self.assertEqual({'estimated_value': 480.0, 'currency': 'USD'}, result)

    def test_currency_is_taken_from_assumptions_not_invented(self):
        config = {'rateCard': {'senior_engineer': 480.0}}
        result = self.fn(self._assumptions(currency='EUR'), config)
        self.assertEqual('EUR', result['currency'])

    def test_absent_rate_card_abstains(self):
        self.assertIsNone(self.fn(self._assumptions(), {}))

    def test_non_dict_rate_card_abstains(self):
        self.assertIsNone(self.fn(self._assumptions(), {'rateCard': 'not-a-dict'}))
        self.assertIsNone(self.fn(self._assumptions(), {'rateCard': ['a', 'list']}))
        self.assertIsNone(self.fn(self._assumptions(), {'rateCard': None}))

    def test_unknown_role_abstains(self):
        config = {'rateCard': {'junior_engineer': 100.0}}
        self.assertIsNone(self.fn(self._assumptions(inferred_role='senior_engineer'), config))

    def test_non_finite_amount_abstains(self):
        for bad in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(amount=bad):
                config = {'rateCard': {'senior_engineer': bad}}
                self.assertIsNone(self.fn(self._assumptions(), config))

    def test_non_positive_amount_abstains(self):
        for bad in (0.0, -1.0, -500.0):
            with self.subTest(amount=bad):
                config = {'rateCard': {'senior_engineer': bad}}
                self.assertIsNone(self.fn(self._assumptions(), config))

    def test_boolean_amount_rejected_not_coerced_to_one(self):
        """isinstance(True, int) is True in Python -- a naive read would
        coerce a rate card's `True` entry to the number 1 rather than
        rejecting it."""
        config = {'rateCard': {'senior_engineer': True}}
        self.assertIsNone(self.fn(self._assumptions(), config))

    def test_non_string_role_abstains(self):
        config = {'rateCard': {'senior_engineer': 480.0}}
        self.assertIsNone(self.fn(self._assumptions(inferred_role=None), config))
        self.assertIsNone(self.fn(self._assumptions(inferred_role=42), config))

    def test_missing_or_non_finite_hours_or_rate_abstains(self):
        config = {'rateCard': {'senior_engineer': 480.0}}
        for field, bad in (
            ('estimated_hours_saved', None),
            ('estimated_hours_saved', float('nan')),
            ('estimated_hours_saved', True),
            ('estimated_hours_saved', 0.0),
            ('estimated_hours_saved', -1.0),
            ('assumed_loaded_rate', None),
            ('assumed_loaded_rate', float('inf')),
            ('assumed_loaded_rate', True),
            ('assumed_loaded_rate', 0.0),
            ('assumed_loaded_rate', -1.0),
        ):
            with self.subTest(field=field, value=repr(bad)):
                self.assertIsNone(self.fn(self._assumptions(**{field: bad}), config))

    def test_non_dict_assumptions_never_raises(self):
        config = {'rateCard': {'senior_engineer': 480.0}}
        self.assertIsNone(self.fn('not a dict', config))
        self.assertIsNone(self.fn(None, config))
        self.assertIsNone(self.fn(123, config))

    def test_non_dict_config_never_raises(self):
        self.assertIsNone(self.fn(self._assumptions(), 'not a dict'))
        self.assertIsNone(self.fn(self._assumptions(), None))

    def test_makes_no_model_network_or_clock_call(self):
        """Proven by the module's own import graph excluding every module
        that would make a model, network, or clock call possible."""
        tree = ast.parse((PLUGIN / 'valuation.py').read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split('.')[0])
        forbidden = {'time', 'datetime', 'socket', 'requests', 'urllib', 'http', 'ssl',
                     'asyncio', 'agent'}
        self.assertEqual(set(), imported & forbidden)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
