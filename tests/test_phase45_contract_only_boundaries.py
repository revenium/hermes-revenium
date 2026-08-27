"""Phase 45 Plan 03 Tasks 1 & 2 — the cohort-impact registry (empty, and
provably able to accept one) and the Revenium reporting contract (a second
reporter, written blind against the docstring, matching the pinned
`jobs outcome` wire shape).

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


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
