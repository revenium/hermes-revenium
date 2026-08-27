"""Phase 45 Plan 03 — the two boundaries with no live implementor, honestly:
cohort impact as a registry with zero registrants that provably accepts one,
and Revenium reporting as a contract with a conformance proof and no adapter.

This file exists to prove two things no other file does: a cohort
estimator's result can never be represented as individually-observed
causality (CohortNonPromotionTests), and a second reporter written blind
against reporting.py's own docstring produces argv the existing pinned
`jobs outcome` golden already accepts (ReportingConformanceTests). Every
other class here is supporting proof for those two claims, or the
cross-registry isolation the six-boundary design depends on.

Requirements covered: EGV-01, EGV-02, EGV-03.

Every test here runs OFFLINE, matching tests/test_phase36_evaluator_seam.py's
own module docstring: no provider, no network, no subprocess.
"""

import ast
import hashlib
import importlib.util
import unittest
from pathlib import Path

from tests._compat_helpers import assert_argv_matches_golden, load_golden

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'
FIXTURES_DIR = ROOT / 'tests' / 'fixtures' / 'compat'


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


def _load_reporting():
    return _load_module('reporting.py', 'phase45_reporting')


def _load_evaluators():
    """Byte-identical to tests/test_phase36_evaluator_seam.py's own
    _load_evaluators() and tests/test_phase45_boundary_registry.py's copy
    of it -- duplicated here (not imported) for the same reason: the
    452-line file this loader belongs to may not be edited, and importing
    a private helper from a sibling test module is a coupling this plan
    does not introduce."""
    return _load_module('evaluators.py', 'phase45_evaluators_contract_only')


def _load_boundary_registry():
    return _load_module('boundary_registry.py', 'phase45_boundary_registry_contract_only')


def _load_classifier(env: "dict | None" = None):
    """Mirror of tests/test_phase36_evaluator_seam.py's own _load_classifier,
    duplicated here for the same reason the loaders above are."""
    import os
    env = env or {}
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(
            'phase45_classifier_contract_only', str(PLUGIN / 'classifier.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _walk_values(obj):
    """Yield every leaf value in a nested dict/list structure, so a test
    can assert a label does not appear ANYWHERE in a record, not merely at
    its top level."""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_values(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_values(v)
    else:
        yield obj


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

    def test_reporting_does_not_import_forbidden_modules(self):
        imported = self._imported_top_level_names(PLUGIN / 'reporting.py')
        self.assertEqual(set(), imported & self._FORBIDDEN)

    def test_both_modules_load_by_file_path_with_no_package_parent(self):
        # If either module's import fallback chain were broken, this would
        # raise during loading rather than at some later call site.
        ci = _load_cohort_impact()
        rep = _load_reporting()
        self.assertEqual('cohort_impact', ci._REGISTRY.boundary)
        self.assertEqual('reporting', rep._REGISTRY.boundary)


class ReportingConformanceTests(unittest.TestCase):
    """D-02 AMENDED / D-07: reporting.py ships with zero registrants, and a
    second reporter written ONLY against its docstring and the golden's own
    declared field set produces argv the pinned `jobs outcome` wire shape
    already accepts.
    """

    def setUp(self):
        self.rep = _load_reporting()

    def test_ships_with_zero_registrants(self):
        fresh = _load_reporting()
        self.assertEqual([], fresh.registered())
        self.assertIsNone(fresh.resolve('anything'))

    def test_registered_fixture_resolves_back_with_empty_evidence_class(self):
        self.rep.register(
            'argv_conformance_reporting_fixture',
            self.rep._argv_conformance_reporting_fixture,
            self.rep.REPORTING_FIXTURE_VERSION,
            evidence_class='',
        )
        fn = self.rep.resolve('argv_conformance_reporting_fixture')
        self.assertIs(fn, self.rep._argv_conformance_reporting_fixture)
        self.assertEqual('', self.rep.resolve_evidence_class('argv_conformance_reporting_fixture'))

        br = _load_boundary_registry()
        self.assertFalse(br.is_masquerading(self.rep._REGISTRY, 'argv_conformance_reporting_fixture'))

    def test_argv_matches_the_pinned_jobs_outcome_golden(self):
        self.rep.register(
            'argv_conformance_reporting_fixture',
            self.rep._argv_conformance_reporting_fixture,
            self.rep.REPORTING_FIXTURE_VERSION,
            evidence_class='',
        )
        fn = self.rep.resolve('argv_conformance_reporting_fixture')
        record = {
            'agentic_job_id': 'compat-job-001',
            'execution_status': 'SUCCESS',
            'source': 'test',
        }
        argv = fn(record, {})
        self.assertIsNotNone(argv)
        golden = load_golden('jobs-outcome.golden.json')
        assert_argv_matches_golden(self, argv, golden)

    def test_declines_non_dict_empty_and_no_job_id_records(self):
        fn = self.rep._argv_conformance_reporting_fixture
        self.assertIsNone(fn('not a dict', {}))
        self.assertIsNone(fn({}, {}))
        self.assertIsNone(fn({'execution_status': 'SUCCESS'}, {}))

    def test_never_emits_a_forbidden_flag(self):
        fn = self.rep._argv_conformance_reporting_fixture
        record = {
            'agentic_job_id': 'compat-job-002',
            'execution_status': 'FAILED',
            'source': 'test',
            'failure_reason': 'timeout',
            # Adversarial keys shaped like the forbidden flags -- proves the
            # fixture never forwards an operator-supplied field as one of
            # the retired flag spellings, whatever the record contains.
            'budget_id': 'legacy-budget-001',
            'alert_id': 'legacy-alert-001',
        }
        argv = fn(record, {})
        self.assertIsNotNone(argv)
        self.assertNotIn('--budget-id', argv)
        self.assertNotIn('--alert-id', argv)


class GoldenImmutabilityTests(unittest.TestCase):
    """The reporting conformance proof above reads the four immutable v1.x
    goldens; it must never mutate them. Failure here means a golden was
    edited, which tests/fixtures/compat/README.md prohibits in capital
    letters -- the fix is to revert the golden, never to update the hash
    recorded below.
    """

    # Computed once when this class was written (sha256 over the raw file
    # bytes). See tests/fixtures/compat/README.md's "Immutability contract".
    _EXPECTED_SHA256 = {
        'meter-completion.golden.json':
            '52b70379be39b20c1f0142305de9cd03b4789e33fa16babcfe874ea2fcaf6f94',
        'jobs-create.golden.json':
            '70458b2e37a7adc2952cef277bb3bb4744b179e9216aad51f9eefc1dfdca9270',
        'jobs-outcome.golden.json':
            '761b9aa47420a7b07b807d9ef7c97a795725d0d3019bbdcb6e7220155a9dd204',
        'meter-tool-event.golden.json':
            'ebdcb8d83b1926dff65b287534282efd80af694eab1816573a8aba669e4404ee',
    }

    def test_four_v1x_goldens_are_byte_identical(self):
        for filename, expected in self._EXPECTED_SHA256.items():
            data = (FIXTURES_DIR / filename).read_bytes()
            actual = hashlib.sha256(data).hexdigest()
            self.assertEqual(
                expected, actual,
                f'{filename} has changed since this test was written -- if '
                'this is intentional, REVERT the golden (fixtures/compat/'
                'README.md\'s immutability contract), do not update this hash',
            )


class CohortNonPromotionTests(unittest.TestCase):
    """EGV-11/D-07, STRUCTURAL guarantee: a cohort registrant's declared
    evidence_class has no code path into any JobAssessment's own
    evidence_class, because classifier._declared_evidence_class consults
    ONLY the `output_assessment` boundary (evaluators.py) and never the
    `cohort_impact` boundary. Proven behaviourally, by driving the REAL
    _validate_assessment -> _build_job_assessment construction path with
    an evaluator name registered ONLY in the cohort registry -- not by a
    static guard -- because a future edit that taught the assessment path
    to also consult the cohort registry would turn THIS test red, which is
    exactly the property that matters.
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
        self.ci = _load_cohort_impact()
        self.ci.register(
            'cohort_estimator_impact_fixture',
            self.ci._cohort_estimator_impact_fixture,
            self.ci.COHORT_FIXTURE_VERSION,
            evidence_class='QUASI_EXPERIMENTAL_IMPACT',
        )

        self.raw = {
            'economic_mechanism': 'labor_substitution',
            'inferred_role': 'cohort estimator',
            'estimated_hours_saved': 2.0,
            'assumed_loaded_rate': 100.0,
            'currency': 'USD',
            'basis': 'cohort-level effect estimate',
            'confidence': 0.6,
            # A direct label-promotion attempt riding alongside the
            # legitimate keys, mirroring PromotionTests' own A1 attack --
            # this must not survive into the record either.
            'evidence_class': 'QUASI_EXPERIMENTAL_IMPACT',
        }
        self.cfg = {}
        self.valid_job = {
            'agentic_job_id': 'cohort-nonpromotion-job-001',
            'job_type': 'code_review',
            'status': 'SUCCESS',
        }
        self.validated = self.mod._validate_assessment(
            self.raw, self.cfg, 'cohort_estimator_impact_fixture',
            self.ci.COHORT_FIXTURE_VERSION,
        )
        self.assertIsNotNone(
            self.validated,
            'the input must be ACCEPTED for this test to be meaningful -- '
            'an attack that lands on the abstention path proves only that '
            'abstention works, not that acceptance resists promotion',
        )
        self.record = self.mod._build_job_assessment(
            self.valid_job, self.validated, self.raw, self.cfg,
            'cohort_estimator_impact_fixture', self.ci.COHORT_FIXTURE_VERSION,
        )
        self.assertIsNotNone(self.record)

    def test_record_evidence_class_is_the_forced_constant_not_the_cohort_label(self):
        self.assertEqual(self.record['evidence_class'], self.mod.EVIDENCE_CLASS_MODEL_ESTIMATED)

    def test_cohort_label_appears_nowhere_in_the_record(self):
        self.assertNotIn('QUASI_EXPERIMENTAL_IMPACT', list(_walk_values(self.record)))


class CrossRegistryIsolationTests(unittest.TestCase):
    """The executable answer to the adjacency question the assumption-delta
    checkpoint resolved during planning (PA-03 in 45-01-PLAN.md): six
    separate BoundaryRegistry instances cannot collide, even when a
    registrant name is reused across them -- and the readability
    requirement that resolution imposed (distinct, boundary-suffixed
    fixture names) is asserted here against the literal six-name list, so
    it stays enforced rather than merely remembered.
    """

    # The six fixture names declared across every Phase 45 plan's boundary
    # table (45-01-PLAN.md's summary table). A future rename that collides
    # with any of the other five turns this list's set-length assertion red.
    ALL_SIX_FIXTURE_NAMES = [
        'keyword_classification_fixture',
        'system_of_record_assessment_fixture',
        'rate_card_valuation_fixture',
        'confirmation_workflow_evidence_fixture',
        'cohort_estimator_impact_fixture',
        'argv_conformance_reporting_fixture',
    ]

    def test_six_fixture_names_are_pairwise_distinct(self):
        self.assertEqual(6, len(self.ALL_SIX_FIXTURE_NAMES))
        self.assertEqual(6, len(set(self.ALL_SIX_FIXTURE_NAMES)))

    def test_same_name_in_two_registries_resolves_to_two_different_callables(self):
        ev = _load_evaluators()
        ci = _load_cohort_impact()

        def f1(job, transcript, config):
            return None

        def f2(cohort, config):
            return None

        ev.register('shared_isolation_test_name', f1, '1')
        ci.register('shared_isolation_test_name', f2, '1')

        self.assertIs(ev.resolve('shared_isolation_test_name'), f1)
        self.assertIs(ci.resolve('shared_isolation_test_name'), f2)
        self.assertIsNot(
            ev.resolve('shared_isolation_test_name'),
            ci.resolve('shared_isolation_test_name'),
        )

    def test_same_name_two_registries_own_declared_evidence_class(self):
        ev = _load_evaluators()
        ci = _load_cohort_impact()

        ev.register('shared_isolation_evidence_test', lambda *a: None, '1',
                     evidence_class='OUTCOME_OBSERVED')
        ci.register('shared_isolation_evidence_test', lambda *a: None, '1',
                     evidence_class='QUASI_EXPERIMENTAL_IMPACT')

        self.assertEqual('OUTCOME_OBSERVED', ev.resolve_evidence_class('shared_isolation_evidence_test'))
        self.assertEqual(
            'QUASI_EXPERIMENTAL_IMPACT', ci.resolve_evidence_class('shared_isolation_evidence_test')
        )

    def test_is_masquerading_has_teeth(self):
        br = _load_boundary_registry()
        ci = _load_cohort_impact()
        rep = _load_reporting()

        ci.register(
            'cohort_estimator_impact_fixture', ci._cohort_estimator_impact_fixture,
            ci.COHORT_FIXTURE_VERSION, evidence_class='QUASI_EXPERIMENTAL_IMPACT',
        )
        rep.register(
            'argv_conformance_reporting_fixture', rep._argv_conformance_reporting_fixture,
            rep.REPORTING_FIXTURE_VERSION, evidence_class='',
        )
        self.assertFalse(br.is_masquerading(ci._REGISTRY, 'cohort_estimator_impact_fixture'))
        self.assertFalse(br.is_masquerading(rep._REGISTRY, 'argv_conformance_reporting_fixture'))

        # A deliberately masquerading throwaway registrant, to prove the
        # check has teeth rather than being vacuously satisfied.
        throwaway = _load_cohort_impact()
        throwaway.register(
            'throwaway_masquerade_registrant', lambda *a: None, '1',
            evidence_class=br.MASQUERADE_CLASS,
        )
        self.assertTrue(br.is_masquerading(throwaway._REGISTRY, 'throwaway_masquerade_registrant'))


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
