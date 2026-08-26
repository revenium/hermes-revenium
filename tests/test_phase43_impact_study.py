"""Phase 43 Plan 03 — the ImpactStudyResult contract (EGV-12).

Every test here runs OFFLINE. No provider, no network, no subprocess, and no
import of classifier.py -- impact_study.py is a stdlib-only contract module
and its tests exercise exactly that surface: validate()'s accept/reject
behavior (this module), plus the two ast-guards (import boundary, no
estimator) that prove the module's structural claims over the code as it
exists today (added in Task 3, below).
"""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'
IMPACT_STUDY_PATH = PLUGIN / 'impact_study.py'


def _load_impact_study():
    spec = importlib.util.spec_from_file_location(
        'phase43_impact_study', str(IMPACT_STUDY_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ContractShapeTests(unittest.TestCase):
    """Behavior 1 -- a fully-populated well-formed study round-trips."""

    def setUp(self):
        self.mod = _load_impact_study()

    def _study(self, **over):
        study = {
            'study_id': 'study-2026-08-code-review-001',
            'study_version': 1,
            'unit': 'agentic_job',
            'population': 'jobs of job_type=code_review in accounts on autonomousMode',
            'intervention': 'AI-assisted job completion',
            'comparator': 'unassisted human completion of the same job type',
            'estimand': (
                'ATE of AI assistance on downstream human review hours, '
                'per-protocol population'
            ),
            'identification_method': 'DID',
            'outcome': 'hours of downstream human review time',
            'observation_window_start': 1_756_000_000.0,
            'observation_window_end': 1_756_600_000.0,
            'value_low': 1.5,
            'value_base': 2.5,
            'value_high': 3.5,
            'assumptions': ['parallel trends hold pre-treatment'],
            'diagnostics': ['pre-trend plot shows no divergence'],
            'validity_scope': 'internal: cohort of N=140 jobs; external: unclaimed',
        }
        study.update(over)
        return study

    def test_well_formed_study_round_trips(self):
        got = self.mod.validate(self._study())
        self.assertIsNotNone(got)
        for key, value in self._study().items():
            self.assertEqual(value, got[key], f'{key} did not round-trip')

    def test_accept_path_key_set_matches_declared_contract_symmetrically(self):
        """Symmetric difference, not a subset check -- a dropped field and a
        surprise field must both be loud, matching
        test_phase42_assessment_contract.py's RecordShapeTests precedent."""
        got = self.mod.validate(self._study())
        self.assertIsNotNone(got)
        self.assertEqual(set(), set(got) ^ self.mod._REQUIRED_KEYS)


class RejectionTests(unittest.TestCase):
    """Behaviors 2-10, 12 -- one adversarial field, everything else nominal.

    One method per rejection reason, so a failure names the reason rather
    than a row index (test_phase36_evaluator_seam.py's RejectionMatrixTests
    style)."""

    def setUp(self):
        self.mod = _load_impact_study()

    def _study(self, **over):
        study = {
            'study_id': 'study-2026-08-code-review-001',
            'study_version': 1,
            'unit': 'agentic_job',
            'population': 'jobs of job_type=code_review',
            'intervention': 'AI-assisted job completion',
            'comparator': 'unassisted human completion',
            'estimand': 'ATE of AI assistance on review hours',
            'identification_method': 'DID',
            'outcome': 'hours of downstream human review time',
            'observation_window_start': 100.0,
            'observation_window_end': 200.0,
            'value_low': 1.0,
            'value_base': 2.0,
            'value_high': 3.0,
            'assumptions': ['parallel trends'],
            'diagnostics': ['pre-trend plot'],
            'validity_scope': 'internal: cohort N=50; external: unclaimed',
        }
        study.update(over)
        return study

    # Behavior 2 -----------------------------------------------------------

    def test_non_dict_input_returns_none(self):
        for bad in (None, [], 'a study', 42, 3.14, object()):
            with self.subTest(repr(bad)):
                self.assertIsNone(self.mod.validate(bad))

    # Behavior 3 -------------------------------------------------------------

    def test_any_missing_required_field_returns_none(self):
        for key in sorted(self.mod._REQUIRED_KEYS):
            with self.subTest(key=key):
                study = self._study()
                del study[key]
                self.assertIsNone(self.mod.validate(study))

    # Behavior 4 -------------------------------------------------------------

    def test_empty_or_non_string_study_id_returns_none(self):
        for bad in ('', '   ', None, 42, [], {}):
            with self.subTest(repr(bad)):
                self.assertIsNone(self.mod.validate(self._study(study_id=bad)))

    # Behavior 5 -------------------------------------------------------------

    def test_bad_study_version_returns_none(self):
        for bad in (True, False, 1.0, '1', 0, -1, None, []):
            with self.subTest(repr(bad)):
                self.assertIsNone(self.mod.validate(self._study(study_version=bad)))

    def test_study_version_at_least_one_is_accepted(self):
        self.assertIsNotNone(self.mod.validate(self._study(study_version=1)))
        self.assertIsNotNone(self.mod.validate(self._study(study_version=7)))

    # Behavior 6 -------------------------------------------------------------

    def test_identification_method_outside_vocabulary_returns_none(self):
        for bad in ('RANDOMIZED', 'did', 'rct', '', None, 42, 'PROPENSITY_SCORE'):
            with self.subTest(repr(bad)):
                self.assertIsNone(
                    self.mod.validate(self._study(identification_method=bad)))

    def test_every_identification_method_member_is_accepted(self):
        """Derived from the module's own declared frozenset, not retyped,
        so this test follows the code rather than the plan."""
        for method in sorted(self.mod.IDENTIFICATION_METHODS):
            with self.subTest(method=method):
                got = self.mod.validate(self._study(identification_method=method))
                self.assertIsNotNone(got)
                self.assertEqual(method, got['identification_method'])

    # Behavior 7 -------------------------------------------------------------

    def test_reversed_effect_interval_returns_none(self):
        for low, base, high in (
            (5.0, 2.0, 3.0),   # low above base
            (1.0, 5.0, 2.0),   # base above high
            (10.0, 1.0, 0.0),  # both reversed
        ):
            with self.subTest(low=low, base=base, high=high):
                self.assertIsNone(self.mod.validate(
                    self._study(value_low=low, value_base=base, value_high=high)))

    def test_flat_effect_interval_is_accepted(self):
        got = self.mod.validate(
            self._study(value_low=5.0, value_base=5.0, value_high=5.0))
        self.assertIsNotNone(got)
        self.assertEqual((5.0, 5.0, 5.0),
                         (got['value_low'], got['value_base'], got['value_high']))

    # Behavior 8 -------------------------------------------------------------

    def test_non_finite_effect_numbers_return_none(self):
        for field in ('value_low', 'value_base', 'value_high'):
            for bad in (float('nan'), float('inf'), float('-inf')):
                with self.subTest(field=field, value=repr(bad)):
                    self.assertIsNone(self.mod.validate(self._study(**{field: bad})))

    def test_bool_effect_number_is_rejected_not_coerced(self):
        """isinstance(True, int) is True in Python -- a naive check would
        silently price the interval off a type error."""
        for field in ('value_low', 'value_base', 'value_high'):
            with self.subTest(field=field):
                self.assertIsNone(self.mod.validate(self._study(**{field: True})))

    # Behavior 9 -------------------------------------------------------------

    def test_observation_window_end_before_start_returns_none(self):
        self.assertIsNone(self.mod.validate(self._study(
            observation_window_start=200.0, observation_window_end=100.0)))

    def test_observation_window_equal_bounds_are_accepted(self):
        got = self.mod.validate(self._study(
            observation_window_start=100.0, observation_window_end=100.0))
        self.assertIsNotNone(got)

    # Behavior 10 ------------------------------------------------------------

    def test_assumptions_or_diagnostics_not_a_list_of_strings_returns_none(self):
        for field in ('assumptions', 'diagnostics'):
            for bad in ('a string', 42, None, {}, [1, 2], ['ok', 3], [None]):
                with self.subTest(field=field, value=repr(bad)):
                    self.assertIsNone(self.mod.validate(self._study(**{field: bad})))

    def test_empty_assumptions_or_diagnostics_list_is_accepted(self):
        got = self.mod.validate(self._study(assumptions=[], diagnostics=[]))
        self.assertIsNotNone(got)
        self.assertEqual([], got['assumptions'])
        self.assertEqual([], got['diagnostics'])

    # Behavior 12 --------------------------------------------------------------

    def test_unknown_key_returns_none(self):
        study = self._study()
        study['effect_size'] = 1.0  # not a declared key
        self.assertIsNone(self.mod.validate(study))


class NarrativeClampTests(unittest.TestCase):
    """Behavior 11 -- an over-long narrative field is CLAMPED, not rejected."""

    def setUp(self):
        self.mod = _load_impact_study()

    def _study(self, **over):
        study = {
            'study_id': 'study-2026-08-code-review-001',
            'study_version': 1,
            'unit': 'agentic_job',
            'population': 'jobs of job_type=code_review',
            'intervention': 'AI-assisted job completion',
            'comparator': 'unassisted human completion',
            'estimand': 'ATE of AI assistance on review hours',
            'identification_method': 'DID',
            'outcome': 'hours of downstream human review time',
            'observation_window_start': 100.0,
            'observation_window_end': 200.0,
            'value_low': 1.0,
            'value_base': 2.0,
            'value_high': 3.0,
            'assumptions': ['parallel trends'],
            'diagnostics': ['pre-trend plot'],
            'validity_scope': 'internal: cohort N=50; external: unclaimed',
        }
        study.update(over)
        return study

    def test_over_long_narrative_field_is_clamped_not_rejected(self):
        overlong = 'x' * (self.mod.NARRATIVE_CLAMP_BYTES * 3)
        for field in ('unit', 'population', 'intervention', 'comparator',
                     'estimand', 'outcome', 'validity_scope', 'study_id'):
            with self.subTest(field=field):
                got = self.mod.validate(self._study(**{field: overlong}))
                self.assertIsNotNone(got, f'{field} should clamp, not reject')
                serialized = len(got[field].encode('utf-8'))
                self.assertLessEqual(serialized, self.mod.NARRATIVE_CLAMP_BYTES)
                self.assertLess(len(got[field]), len(overlong))


class NeverRaisesTests(unittest.TestCase):
    """Behavior 13 -- validate() never raises, for any adversarial input.

    Never-raising is a CONTRACT PROPERTY, not an incidental one: a future
    caller inside the classifier plugin runs under a rule that forbids
    propagating an exception (the same discipline
    classifier._validate_assessment and _build_job_assessment already
    observe), so a validator that can raise is not actually usable there.
    """

    def setUp(self):
        self.mod = _load_impact_study()

    def test_hostile_input_returns_none_rather_than_raising(self):
        hostile_values = [object(), object(), object(), object(), object(),
                          object(), object(), object(), object(), object(),
                          object(), object(), object(), object(), object(),
                          object(), object()]
        hostile = dict(zip(sorted(self.mod._REQUIRED_KEYS), hostile_values))
        try:
            got = self.mod.validate(hostile)
        except Exception as exc:  # pragma: no cover - the failure this proves against
            self.fail(f'validate() raised {exc!r} instead of returning None')
        self.assertIsNone(got)

    def test_deeply_wrong_types_across_every_field_return_none(self):
        wrong = {
            'study_id': [1, 2, 3],
            'study_version': 'one',
            'unit': 42,
            'population': None,
            'intervention': {'nested': True},
            'comparator': 3.14,
            'estimand': [],
            'identification_method': {},
            'outcome': object(),
            'observation_window_start': 'now',
            'observation_window_end': 'later',
            'value_low': 'low',
            'value_base': 'base',
            'value_high': 'high',
            'assumptions': 'not a list',
            'diagnostics': 42,
            'validity_scope': [],
        }
        self.assertEqual(set(wrong), self.mod._REQUIRED_KEYS)
        try:
            got = self.mod.validate(wrong)
        except Exception as exc:  # pragma: no cover
            self.fail(f'validate() raised {exc!r} instead of returning None')
        self.assertIsNone(got)
if __name__ == '__main__':  # pragma: no cover
    unittest.main()
