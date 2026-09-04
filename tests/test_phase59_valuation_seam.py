"""tests/test_phase59_valuation_seam.py — SSE-04: the valuation seam.

Every test in this module runs OFFLINE, matching
tests/test_phase36_evaluator_seam.py's own module docstring: no provider,
no network, no subprocess.

Registrant hygiene: `SeamTracerTests` (and, in later tasks,
`SourceSwapTests`/`SourceFailureFallbackTests`) drive the REAL classifier
module against a fresh classifier module per test (`_load_classifier`'s
own per-call `spec_from_file_location`), but the `valuation` and
`valuation_sources` modules those classifier loads resolve through are the
SHARED, bare-imported modules cached in `sys.modules` once `PLUGIN` is
placed on `sys.path` -- the exact convention
tests/test_phase54_revenue_valuation_boundary.py's own
`HostileRegistrantDistrustTests` already documents and relies on.
`last-registration-wins` is a documented property of the shared
`BoundaryRegistry` helper (`boundary_registry.py`), and every test that
registers a throwaway registrant or source into either shared module
cleans it up via `addCleanup` so it cannot leak into a later test.

`SourceContractTests`/`RegistryRoundTripTests` (Task 3) instead load
`valuation_sources.py` and `valuation.py` FRESH, by file path, with no
package parent and no `sys.path` entry -- the behavioural proof of the
dependency direction (D-01): a module that imported `classifier.py` could
not complete that load.
"""

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


def _load_valuation_sources():
    """Fresh valuation_sources.py by file path, no package parent, no
    sys.path entry -- tests/test_phase45_valuation_boundary.py's
    _load_valuation() idiom, applied to the new source module. A fresh
    module object per call means a fresh, empty-but-for-the-shipped-source
    `_REGISTRY` per call -- no cross-test registration leakage."""
    spec = importlib.util.spec_from_file_location(
        'phase59_valuation_sources', str(PLUGIN / 'valuation_sources.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_valuation():
    """Fresh valuation.py by file path, no package parent, no sys.path
    entry -- same idiom, distinct sys.modules name."""
    spec = importlib.util.spec_from_file_location(
        'phase59_valuation', str(PLUGIN / 'valuation.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_classifier(env: "dict | None" = None):
    """Mirror of tests/test_phase54_revenue_valuation_boundary.py's own
    _load_classifier, duplicated here under a distinct sys.modules name.
    Loaded standalone (no package): classifier.py's own `from . import
    valuation`/`valuation_sources` fallbacks then attempt BARE imports,
    which only resolve when PLUGIN has been placed on sys.path -- see
    _ValuationSeamTestCase.setUpClass, below."""
    env = env or {}
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(
            'phase59_classifier', str(PLUGIN / 'classifier.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _write_config(config_path: Path, boundaries=None, valuation_source_fixture_path=None):
    """Writes `boundaries.valuation` / `boundaries.valuationSource` at the
    top level, and `valuationSourceFixturePath` inside
    `llmOutcomeEvaluation` -- the SAME placement rule
    tests/test_phase54_revenue_valuation_boundary.py's own _write_config
    already establishes for its own new keys (a production host that
    guessed wrong on this exact question left 85 sessions unpriceable in
    Phase 53)."""
    cfg = {}
    if boundaries is not None:
        cfg['boundaries'] = boundaries
    outcome_eval = {}
    if valuation_source_fixture_path is not None:
        outcome_eval['valuationSourceFixturePath'] = valuation_source_fixture_path
    if outcome_eval:
        cfg['llmOutcomeEvaluation'] = outcome_eval
    config_path.write_text(json.dumps(cfg))


_THROWAWAY_SEQ = [0]


def _throwaway_name(prefix: str) -> str:
    _THROWAWAY_SEQ[0] += 1
    return f'{prefix}_{_THROWAWAY_SEQ[0]}'


class _ValuationSeamTestCase(unittest.TestCase):
    """Shared sys.path management and fixture helpers, modelled on
    tests/test_phase54_revenue_valuation_boundary.py's own
    _ValuationBoundaryTestCase. No test_* methods of its own."""

    @classmethod
    def setUpClass(cls):
        cls._path_added = str(PLUGIN) not in sys.path
        if cls._path_added:
            sys.path.insert(0, str(PLUGIN))

    @classmethod
    def tearDownClass(cls):
        if cls._path_added and str(PLUGIN) in sys.path:
            sys.path.remove(str(PLUGIN))

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gsd-p59-01-seam-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.config_path = Path(self.tmp) / 'config.json'

    def _raw(self, **over):
        raw = {
            'economic_mechanism': 'labor_substitution',
            'inferred_role': 'senior_engineer',
            'estimated_hours_saved': 2.5,
            'assumed_loaded_rate': 150.0,
            'currency': 'USD',
            'basis': 'booking completed',
            'confidence': 0.5,
        }
        raw.update(over)
        return raw

    def _write_fixture_document(self, **over):
        """A `baselines`-shaped document whose fetched-figures value is
        arithmetically DISTINCT from the local `round(hours * rate, 2)`
        product this test case's `_raw()` produces (2.5 * 150.0 == 375.0):
        30 / 60.0 * 200.0 == 100.0."""
        doc = {'hourlyRate': 200.0, 'minutesPerUnit': 30.0, 'provenance': 'seam-fixture'}
        doc.update(over)
        path = Path(self.tmp) / 'baselines.json'
        path.write_text(json.dumps(doc))
        return str(path)

    def _load(self, boundaries=None, valuation_source_fixture_path=None):
        _write_config(
            self.config_path, boundaries=boundaries,
            valuation_source_fixture_path=valuation_source_fixture_path,
        )
        # HERMES_HOME pinned to this test's own tmp dir -- see
        # tests/test_phase54_revenue_valuation_boundary.py's own _load()
        # for why a real dev host's ~/.hermes/profiles must never leak in.
        return _load_classifier({
            'REVENIUM_CONFIG_FILE': str(self.config_path),
            'HERMES_HOME': self.tmp,
        })


class SeamTracerTests(_ValuationSeamTestCase):
    """Task 1: one path end to end -- config key, source resolution,
    fetch, validated hand-off, registrant, value."""

    def test_default_arm_hands_registrant_exactly_five_keys(self):
        import valuation as val  # type: ignore -- shared, sys.path-resolved
        captured = {}

        def _capture(assumptions, config):
            captured.update(assumptions)
            return {'estimated_value': 999.0, 'currency': assumptions.get('currency')}

        name = _throwaway_name('p59_capture')
        val.register(name, _capture, '1', evidence_class='CUSTOMER_CONFIGURED')
        self.addCleanup(val._REGISTRY._entries.pop, name, None)

        mod = self._load(boundaries={'valuation': name})
        cfg = mod._llm_evaluation_config()
        mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')

        self.assertEqual(
            {'estimated_hours_saved', 'assumed_loaded_rate', 'currency',
             'economic_mechanism', 'inferred_role'},
            set(captured.keys()),
            'default install: no sixth key when no source is configured',
        )

    def test_default_arm_value_unchanged(self):
        mod = self._load(boundaries=None)
        cfg = mod._llm_evaluation_config()
        result = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNotNone(result)
        self.assertEqual(375.0, result['estimated_value'])

    def test_configured_source_arm_hands_sixth_key_with_fetched_figures(self):
        import valuation as val  # type: ignore -- shared, sys.path-resolved
        captured = {}

        def _capture(assumptions, config):
            captured.update(assumptions)
            return {'estimated_value': 1.0, 'currency': assumptions.get('currency')}

        name = _throwaway_name('p59_capture')
        val.register(name, _capture, '1', evidence_class='CUSTOMER_CONFIGURED')
        self.addCleanup(val._REGISTRY._entries.pop, name, None)

        fixture_path = self._write_fixture_document()
        mod = self._load(
            boundaries={'valuation': name, 'valuationSource': 'baselines_file_source'},
            valuation_source_fixture_path=fixture_path,
        )
        cfg = mod._llm_evaluation_config()
        mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')

        self.assertIn('source_figures', captured)
        self.assertEqual(
            {'hourlyRate': 200.0, 'minutesPerUnit': 30.0,
             'provenance': 'seam-fixture', 'source': 'baselines_file_source'},
            captured['source_figures'],
        )

    def test_configured_source_and_registrant_price_from_fetched_figures(self):
        fixture_path = self._write_fixture_document()
        mod = self._load(
            boundaries={'valuation': 'baselines_valuation_fixture',
                        'valuationSource': 'baselines_file_source'},
            valuation_source_fixture_path=fixture_path,
        )
        cfg = mod._llm_evaluation_config()
        result = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNotNone(result)
        # 30 / 60.0 * 200.0 == 100.0 -- arithmetically distinct from the
        # local 2.5 * 150.0 == 375.0 product this same _raw() would price
        # through the built-in derivation. The whole point of this arm is
        # that the number could not have come from `assumptions` the
        # caller built.
        self.assertEqual(100.0, result['estimated_value'])
        self.assertNotEqual(375.0, result['estimated_value'])

    def test_unregistered_source_behaves_exactly_as_default_arm(self):
        mod = self._load(
            boundaries={'valuation': 'baselines_valuation_fixture',
                        'valuationSource': 'nonexistent_source'},
        )
        cfg = mod._llm_evaluation_config()
        result = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNotNone(result)
        self.assertEqual(375.0, result['estimated_value'])

    def test_baselines_file_source_never_raises_on_malformed_inputs(self):
        vs = _load_valuation_sources()
        fn = vs.resolve('baselines_file_source')
        self.assertIsNotNone(fn)

        nonexistent = str(Path(self.tmp) / 'does-not-exist.json')

        oversized_path = Path(self.tmp) / 'oversized.json'
        oversized_path.write_text(json.dumps({
            'hourlyRate': 1.0, 'minutesPerUnit': 1.0,
            'provenance': 'x' * (vs.MAX_SOURCE_DOCUMENT_BYTES + 10),
        }))

        non_json_path = Path(self.tmp) / 'not-json.json'
        non_json_path.write_text('not json{{{')

        non_dict_top_level_path = Path(self.tmp) / 'non-dict.json'
        non_dict_top_level_path.write_text(json.dumps([1, 2, 3]))

        missing_rate_path = Path(self.tmp) / 'missing-rate.json'
        missing_rate_path.write_text(json.dumps({'minutesPerUnit': 30.0}))

        non_positive_rate_path = Path(self.tmp) / 'non-positive-rate.json'
        non_positive_rate_path.write_text(
            json.dumps({'hourlyRate': -5.0, 'minutesPerUnit': 30.0}))

        missing_minutes_path = Path(self.tmp) / 'missing-minutes.json'
        missing_minutes_path.write_text(json.dumps({'hourlyRate': 100.0}))

        non_finite_minutes_path = Path(self.tmp) / 'non-finite-minutes.json'
        non_finite_minutes_path.write_text(
            json.dumps({'hourlyRate': 100.0, 'minutesPerUnit': 'nope'}))

        cases = [
            ('non_dict_config', 'not-a-dict'),
            ('absent_path_key', {}),
            ('non_string_path_key', {'valuationSourceFixturePath': 123}),
            ('nonexistent_file', {'valuationSourceFixturePath': nonexistent}),
            ('oversized_file', {'valuationSourceFixturePath': str(oversized_path)}),
            ('non_json_bytes', {'valuationSourceFixturePath': str(non_json_path)}),
            ('non_dict_top_level',
             {'valuationSourceFixturePath': str(non_dict_top_level_path)}),
            ('missing_hourly_rate',
             {'valuationSourceFixturePath': str(missing_rate_path)}),
            ('non_positive_hourly_rate',
             {'valuationSourceFixturePath': str(non_positive_rate_path)}),
            ('missing_minutes_per_unit',
             {'valuationSourceFixturePath': str(missing_minutes_path)}),
            ('non_finite_minutes_per_unit',
             {'valuationSourceFixturePath': str(non_finite_minutes_path)}),
        ]
        for label, config in cases:
            with self.subTest(label):
                self.assertIsNone(fn(config))

    def test_valuation_sources_loads_standalone(self):
        vs = _load_valuation_sources()
        self.assertEqual(['baselines_file_source'], vs.registered())


if __name__ == '__main__':
    unittest.main()
