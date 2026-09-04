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


# ---------------------------------------------------------------------------
# Task 2 -- SourceSwapTests (D-07, criterion 2) and
# SourceFailureFallbackTests (D-03, all four failure shapes)
# ---------------------------------------------------------------------------

def _assert_skills_unchanged(testcase):
    """Phase 58's own idiom (its plans used this exact `git diff --quiet`
    assertion twelve times across three plans), lifted rather than
    reinvented: assert nothing under skills/ moved as a byte, with a
    failure message that runs `git status --porcelain -- skills/` so a
    real regression is diagnosable rather than a bare non-zero exit."""
    import subprocess
    result = subprocess.run(
        ['git', 'diff', '--quiet', '--', 'skills/'], cwd=str(ROOT),
    )
    if result.returncode != 0:
        status = subprocess.run(
            ['git', 'status', '--porcelain', '--', 'skills/'],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        testcase.fail(
            'git diff --quiet -- skills/ was dirty after driving the '
            'real classifier across both config arms:\n' + status.stdout
        )


_SOURCE_THROWAWAY_SEQ = [0]


def _throwaway_source_name(prefix: str) -> str:
    _SOURCE_THROWAWAY_SEQ[0] += 1
    return f'{prefix}_{_SOURCE_THROWAWAY_SEQ[0]}'


class SourceSwapTests(_ValuationSeamTestCase):
    """Task 2: criterion 2, demonstrated rather than described. A
    config-only swap of `boundaries.valuation` + `boundaries.valuationSource`
    moves where the number comes from, the number changes with it, and
    nothing under skills/ moved to make that happen."""

    def test_config_only_swap_changes_where_the_number_comes_from(self):
        # Arm A: neither new key configured.
        mod_a = self._load(boundaries=None)
        cfg_a = mod_a._llm_evaluation_config()
        result_a = mod_a._validate_assessment(self._raw(), cfg_a, 'stub', 'v1')
        self.assertIsNotNone(result_a)
        self.assertEqual(375.0, result_a['estimated_value'])  # 2.5 * 150.0

        # Arm B: both new keys configured, changing ONLY config.json.
        fixture_path = self._write_fixture_document()
        mod_b = self._load(
            boundaries={'valuation': 'baselines_valuation_fixture',
                        'valuationSource': 'baselines_file_source'},
            valuation_source_fixture_path=fixture_path,
        )
        cfg_b = mod_b._llm_evaluation_config()
        result_b = mod_b._validate_assessment(self._raw(), cfg_b, 'stub', 'v1')
        self.assertIsNotNone(result_b)
        # 30 / 60.0 * 200.0 == 100.0 -- the value the FETCHED figures
        # produce, not the value `assumptions` alone could have produced.
        self.assertEqual(100.0, result_b['estimated_value'])
        self.assertNotEqual(result_a['estimated_value'], result_b['estimated_value'])

        _assert_skills_unchanged(self)

    def test_arm_b_value_could_not_have_come_from_assumptions(self):
        # A comment, not just an assertion: a registrant SWAP alone
        # re-proves Phase 45 (a throwaway registrant reading `assumptions`
        # differently is nothing new). What makes THIS a seam
        # demonstration is that Arm B's value comes from somewhere the
        # CALLER resolved -- a fetched document -- not from the
        # `assumptions` dict the caller itself built. hours * rate
        # (2.5 * 150.0 == 375.0) and minutesPerUnit / 60.0 * hourlyRate
        # (30 / 60.0 * 200.0 == 100.0) are chosen far enough apart that
        # "close by rounding" cannot explain the difference.
        fixture_path = self._write_fixture_document()
        mod = self._load(
            boundaries={'valuation': 'baselines_valuation_fixture',
                        'valuationSource': 'baselines_file_source'},
            valuation_source_fixture_path=fixture_path,
        )
        cfg = mod._llm_evaluation_config()
        raw = self._raw()
        local_product = round(raw['estimated_hours_saved'] * raw['assumed_loaded_rate'], 2)
        result = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(result)
        self.assertEqual(100.0, result['estimated_value'])
        self.assertGreater(abs(result['estimated_value'] - local_product), 1.0)

    def test_stand_in_declares_model_estimated_demo_and_is_not_reportable(self):
        # D-05's membership assertions -- phrased as membership only, never
        # as one class being stronger or weaker than another (EGV-10).
        mod = self._load(boundaries=None)
        val_mod = mod._load_valuation_module()
        self.assertEqual(
            'MODEL_ESTIMATED_DEMO',
            val_mod.resolve_evidence_class('baselines_valuation_fixture'),
        )
        self.assertNotIn(
            val_mod.resolve_evidence_class('baselines_valuation_fixture'),
            mod._REPORTABLE_EVIDENCE_CLASSES,
        )


class SourceFailureFallbackTests(_ValuationSeamTestCase):
    """Task 2: D-03, all four failure shapes. Each configures
    `boundaries.valuation = 'baselines_valuation_fixture'` and a
    `boundaries.valuationSource` that cannot supply figures, drives the
    REAL `_validate_assessment`, and asserts the failure lands back on the
    built-in derivation through the EXISTING delegation-identity
    mechanism -- never a new branch."""

    def _assert_lands_on_builtin(self, mod, result):
        raw = self._raw()
        expected = round(raw['estimated_hours_saved'] * raw['assumed_loaded_rate'], 2)
        self.assertIsNotNone(result)
        self.assertEqual(expected, result['estimated_value'])
        self.assertEqual('MODEL_ESTIMATED_DEMO', result['evidence_class'])
        self.assertEqual(
            'hours_times_rate',
            mod._valuation_evidence_impl_name('baselines_valuation_fixture', False, True),
        )

    def test_source_name_unregistered(self):
        mod = self._load(
            boundaries={'valuation': 'baselines_valuation_fixture',
                        'valuationSource': 'nonexistent_source'},
        )
        cfg = mod._llm_evaluation_config()
        result = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self._assert_lands_on_builtin(mod, result)

    def test_source_raises(self):
        import valuation_sources as vsrc  # type: ignore -- shared, sys.path-resolved

        def _raising_source(config):
            raise RuntimeError('this source always raises')

        name = _throwaway_source_name('p59_raising_source')
        vsrc.register(name, _raising_source, '1')
        self.addCleanup(vsrc._REGISTRY._entries.pop, name, None)

        mod = self._load(
            boundaries={'valuation': 'baselines_valuation_fixture',
                        'valuationSource': name},
        )
        cfg = mod._llm_evaluation_config()
        # The source's failure costs the call its figures, never the
        # assessment: this call must complete rather than raise.
        result = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self._assert_lands_on_builtin(mod, result)

    def test_fixture_file_absent(self):
        mod = self._load(
            boundaries={'valuation': 'baselines_valuation_fixture',
                        'valuationSource': 'baselines_file_source'},
            valuation_source_fixture_path=str(Path(self.tmp) / 'does-not-exist.json'),
        )
        cfg = mod._llm_evaluation_config()
        result = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self._assert_lands_on_builtin(mod, result)

    def test_fixture_document_malformed_non_dict_top_level(self):
        malformed_path = Path(self.tmp) / 'malformed.json'
        malformed_path.write_text(json.dumps([1, 2, 3]))
        mod = self._load(
            boundaries={'valuation': 'baselines_valuation_fixture',
                        'valuationSource': 'baselines_file_source'},
            valuation_source_fixture_path=str(malformed_path),
        )
        cfg = mod._llm_evaluation_config()
        result = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self._assert_lands_on_builtin(mod, result)

    def test_no_second_mechanism_introduced(self):
        # D-02: the record produced with the stand-in configured and the
        # source unavailable carries no key whose name mentions a source,
        # and its key set is identical to the same assessment's key set on
        # a default-configured host -- nothing new determines the
        # recorded class beyond _valuation_evidence_impl_name.
        default_mod = self._load(boundaries=None)
        default_cfg = default_mod._llm_evaluation_config()
        default_result = default_mod._validate_assessment(self._raw(), default_cfg, 'stub', 'v1')

        failure_mod = self._load(
            boundaries={'valuation': 'baselines_valuation_fixture',
                        'valuationSource': 'nonexistent_source'},
        )
        failure_cfg = failure_mod._llm_evaluation_config()
        failure_result = failure_mod._validate_assessment(self._raw(), failure_cfg, 'stub', 'v1')

        self.assertIsNotNone(default_result)
        self.assertIsNotNone(failure_result)
        self.assertEqual(set(default_result.keys()), set(failure_result.keys()))
        for key in failure_result:
            self.assertNotIn('source', key.lower())


if __name__ == '__main__':
    unittest.main()
