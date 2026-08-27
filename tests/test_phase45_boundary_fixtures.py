"""Phase 45 Plan 06 — the sixth boundary (evidence resolution and
reportability, EGV-01) and the phase's closing proof.

This file exists to make three claims executable that no other file in
this phase makes: no contract couples to the host (ImportGuardTests, over
all seven boundary-side files -- the shared registry helper plus the six
boundary modules), no contract takes the untrusted evaluator response
(UntrustedParameterTests), and the six fixtures born across this whole
phase are genuinely distinct and none of them masquerades as the naked-LLM
evaluator (FixtureMatrixTests). ReportabilityTests covers this plan's own
new boundary module, evidence.py, the same way
tests/test_phase45_valuation_boundary.py covers valuation.py.
PhaseGateTests records the phase gate procedure and re-verifies the
immutable goldens this plan must not have touched.

Every test here runs OFFLINE, matching tests/test_phase36_evaluator_seam.py's
own module docstring: no provider, no network, no subprocess.
"""

import ast
import hashlib
import importlib.util
import unittest
from pathlib import Path

from tests.test_phase43_evidence_grading import (
    _PROMOTION_FORBIDDEN_KEYS,
    _UNTRUSTED_PARAM_NAME,
)
from tests.test_phase45_contract_only_boundaries import GoldenImmutabilityTests

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'

# D-08's denylist -- none of the seven files below may import any of these.
_FORBIDDEN_IMPORTS = frozenset({
    'classifier', 'agent', 'os', 'pathlib', 'sqlite3', 'subprocess',
})

# The shared registry helper plus the six boundary modules -- the complete
# set ImportGuardTests and UntrustedParameterTests sweep, and the set
# FixtureMatrixTests' "same five free functions" assertion covers for the
# six boundary modules (the helper itself is a different shape).
_BOUNDARY_MODULE_FILENAMES = (
    'evaluators.py',
    'classification.py',
    'valuation.py',
    'evidence.py',
    'cohort_impact.py',
    'reporting.py',
)
_ALL_SEVEN_FILENAMES = ('boundary_registry.py',) + _BOUNDARY_MODULE_FILENAMES


def _load_module(filename, modname):
    """Import a plugin module fresh by file path, no package parent, no
    sys.path entry -- the idiom tests/test_phase36_evaluator_seam.py's
    _load_evaluators() and tests/test_phase45_contract_only_boundaries.py's
    _load_cohort_impact() both use. A fresh module object per call means a
    fresh registry per call for the four modules that register at import
    time -- no cross-test registration leakage."""
    spec = importlib.util.spec_from_file_location(modname, str(PLUGIN / filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_boundary_registry():
    return _load_module('boundary_registry.py', 'phase45_06_boundary_registry')


def _load_evaluators():
    return _load_module('evaluators.py', 'phase45_06_evaluators')


def _load_classification():
    return _load_module('classification.py', 'phase45_06_classification')


def _load_valuation():
    return _load_module('valuation.py', 'phase45_06_valuation')


def _load_evidence():
    return _load_module('evidence.py', 'phase45_06_evidence')


def _load_cohort_impact():
    return _load_module('cohort_impact.py', 'phase45_06_cohort_impact')


def _load_reporting():
    return _load_module('reporting.py', 'phase45_06_reporting')


class ReportabilityTests(unittest.TestCase):
    """Task 1 -- evidence.py: the confirmation-workflow fixture and the
    resolve_declared_class allow-list rule, one method per behavior bullet.
    """

    def setUp(self):
        self.ev = _load_evidence()
        self.fixture = self.ev._confirmation_workflow_evidence_fixture

    # -- _confirmation_workflow_evidence_fixture -----------------------

    def test_reportable_when_not_abstained_and_job_id_confirmed(self):
        result = self.fixture(
            {'abstained': False, 'agentic_job_id': 'job-1', 'job_type': 'code_review'},
            {'confirmations': ['job-1', 'job-2']},
        )
        self.assertEqual(result, {'reportability_status': self.ev.REPORTABILITY_REPORTABLE})

    def test_candidate_when_job_id_absent_from_confirmations(self):
        result = self.fixture(
            {'abstained': False, 'agentic_job_id': 'job-9', 'job_type': 'code_review'},
            {'confirmations': ['job-1', 'job-2']},
        )
        self.assertEqual(result, {'reportability_status': self.ev.REPORTABILITY_CANDIDATE})

    def test_candidate_when_confirmations_missing(self):
        result = self.fixture(
            {'abstained': False, 'agentic_job_id': 'job-1', 'job_type': 'code_review'},
            {},
        )
        self.assertEqual(result, {'reportability_status': self.ev.REPORTABILITY_CANDIDATE})

    def test_candidate_when_confirmations_not_a_list(self):
        result = self.fixture(
            {'abstained': False, 'agentic_job_id': 'job-1', 'job_type': 'code_review'},
            {'confirmations': 'job-1'},
        )
        self.assertEqual(result, {'reportability_status': self.ev.REPORTABILITY_CANDIDATE})

    def test_candidate_when_request_is_abstained_even_if_confirmed(self):
        result = self.fixture(
            {'abstained': True, 'agentic_job_id': 'job-1', 'job_type': 'code_review'},
            {'confirmations': ['job-1']},
        )
        self.assertEqual(result, {'reportability_status': self.ev.REPORTABILITY_CANDIDATE})

    def test_none_for_non_dict_request(self):
        self.assertIsNone(self.fixture('not-a-dict', {'confirmations': ['job-1']}))

    def test_none_for_non_dict_config(self):
        self.assertIsNone(self.fixture(
            {'abstained': False, 'agentic_job_id': 'job-1'}, 'not-a-dict',
        ))

    def test_fixture_is_deterministic_no_clock_no_model_no_network(self):
        request = {'abstained': False, 'agentic_job_id': 'job-1', 'job_type': 'code_review'}
        config = {'confirmations': ['job-1']}
        first = self.fixture(request, config)
        second = self.fixture(request, config)
        self.assertEqual(first, second)

    def test_registered_evidence_class_is_customer_confirmed_and_not_masquerading(self):
        self.assertEqual(
            'CUSTOMER_CONFIRMED',
            self.ev.resolve_evidence_class('confirmation_workflow_evidence_fixture'),
        )
        br = _load_boundary_registry()
        self.assertFalse(
            br.is_masquerading(self.ev._REGISTRY, 'confirmation_workflow_evidence_fixture')
        )

    # -- resolve_declared_class -----------------------------------------

    def test_resolve_declared_class_returns_declared_label_when_a_member(self):
        self.assertEqual(
            'OUTCOME_OBSERVED',
            self.ev.resolve_declared_class('OUTCOME_OBSERVED', {'OUTCOME_OBSERVED'}, 'DEFAULT'),
        )

    def test_resolve_declared_class_returns_default_for_label_outside_allow_list(self):
        self.assertEqual(
            'DEFAULT',
            self.ev.resolve_declared_class('NOPE', {'OUTCOME_OBSERVED'}, 'DEFAULT'),
        )

    def test_resolve_declared_class_returns_default_for_non_string(self):
        self.assertEqual(
            'DEFAULT',
            self.ev.resolve_declared_class(7, {'OUTCOME_OBSERVED'}, 'DEFAULT'),
        )

    def test_resolve_declared_class_returns_default_for_empty_string(self):
        self.assertEqual(
            'DEFAULT',
            self.ev.resolve_declared_class('', {'OUTCOME_OBSERVED'}, 'DEFAULT'),
        )

    def test_resolve_declared_class_returns_default_for_non_iterable_allowed(self):
        self.assertEqual(
            'DEFAULT',
            self.ev.resolve_declared_class('OUTCOME_OBSERVED', 7, 'DEFAULT'),
        )

    def test_resolve_declared_class_never_raises_on_internal_failure(self):
        class _HostileAllowed:
            def __contains__(self, item):
                raise RuntimeError('boom')

        self.assertEqual(
            'DEFAULT',
            self.ev.resolve_declared_class('OUTCOME_OBSERVED', _HostileAllowed(), 'DEFAULT'),
        )


class ImportGuardTests(unittest.TestCase):
    """D-08: the shared registry helper plus all six boundary modules stay
    host-agnostic. Parsed with ast, not grepped -- exactly
    tests/test_phase36_evaluator_seam.py::test_module_does_not_import_classifier's
    own reasoning, which applies with more force here: six module
    docstrings now document the rule in prose, so a substring search for
    e.g. 'import classifier' would match the very comment explaining the
    invariant and fail on a compliant file.
    """

    def test_no_boundary_side_file_imports_a_forbidden_module(self):
        for filename in _ALL_SEVEN_FILENAMES:
            with self.subTest(filename=filename):
                tree = ast.parse((PLUGIN / filename).read_text())
                imported = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported.update(a.name.split('.')[0] for a in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imported.add(node.module.split('.')[0])
                offenders = imported & _FORBIDDEN_IMPORTS
                self.assertEqual(
                    set(), offenders,
                    f'{filename} imports forbidden module(s): {sorted(offenders)}',
                )

    def test_every_boundary_side_file_loads_by_file_path_with_no_package_parent(self):
        for filename in _ALL_SEVEN_FILENAMES:
            with self.subTest(filename=filename):
                mod = _load_module(filename, f'phase45_06_loadcheck_{filename}')
                self.assertIsNotNone(mod)


class UntrustedParameterTests(unittest.TestCase):
    """No boundary-side file declares a parameter named _UNTRUSTED_PARAM_NAME
    ('raw') on any function, at any nesting depth -- the untrusted evaluator
    response classifier.py holds in scope (tests/test_phase43_evidence_grading.py's
    _SCOPED_FUNCTIONS) is never handed across a boundary. _UNTRUSTED_PARAM_NAME
    and _PROMOTION_FORBIDDEN_KEYS are imported from
    tests.test_phase43_evidence_grading rather than retyped, per this plan's
    own instruction.

    GUARANTEE CLASS: this is STATIC over the code that exists TODAY. It
    proves no boundary module takes the untrusted response now; it does not
    make such a parameter impossible to add later. A future edit that
    introduces a same-named parameter on a boundary function would turn
    this test red, which is the point -- but nothing here prevents the
    edit from being written in the first place.
    """

    def _function_defs(self, tree):
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield node

    def test_no_function_declares_the_untrusted_parameter_name(self):
        for filename in _ALL_SEVEN_FILENAMES:
            with self.subTest(filename=filename):
                tree = ast.parse((PLUGIN / filename).read_text())
                offenders = []
                for node in self._function_defs(tree):
                    arg_names = {a.arg for a in node.args.args}
                    arg_names |= {a.arg for a in node.args.kwonlyargs}
                    if node.args.vararg:
                        arg_names.add(node.args.vararg.arg)
                    if node.args.kwarg:
                        arg_names.add(node.args.kwarg.arg)
                    if _UNTRUSTED_PARAM_NAME in arg_names:
                        offenders.append(f'{filename}:{node.lineno}:{node.name}')
                self.assertEqual(
                    [], offenders,
                    f'function(s) declare a parameter named '
                    f'{_UNTRUSTED_PARAM_NAME!r}: {offenders}',
                )

    def test_forbidden_key_read_scan_is_vacuous_today_by_construction(self):
        """Runs Phase 43's forbidden-key read-scan idiom, scoped to any
        function that DOES declare a parameter named _UNTRUSTED_PARAM_NAME
        across the seven boundary-side files. Vacuous today, because the
        test above proves no such function exists -- and that vacuity is
        the point, not an oversight: this test exists so a future edit that
        introduces such a parameter is ALSO caught by the key-read check,
        not merely by the parameter-name check above.
        """
        scoped_functions = []
        for filename in _ALL_SEVEN_FILENAMES:
            tree = ast.parse((PLUGIN / filename).read_text())
            for node in self._function_defs(tree):
                arg_names = {a.arg for a in node.args.args}
                if _UNTRUSTED_PARAM_NAME in arg_names:
                    scoped_functions.append((filename, node))
        self.assertEqual(
            [], scoped_functions,
            'expected zero functions scoped for the forbidden-key read scan '
            'today; found some -- update this test to actually scan them',
        )
        # The scan itself, over an empty scope today: for each (hypothetical)
        # scoped function, walk its body for raw.get('key')/raw['key']/
        # getattr(raw, 'key') reads of a _PROMOTION_FORBIDDEN_KEYS member.
        # Mirrors tests/test_phase43_evidence_grading.py's own read-scan
        # shape so the two guards stay recognisably the same check.
        offenders = []
        for filename, node in scoped_functions:  # pragma: no cover - empty today
            for sub in ast.walk(node):
                key = None
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == 'get'
                        and isinstance(sub.func.value, ast.Name)
                        and sub.func.value.id == _UNTRUSTED_PARAM_NAME
                        and sub.args and isinstance(sub.args[0], ast.Constant)):
                    key = sub.args[0].value
                elif (isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Name)
                        and sub.value.id == _UNTRUSTED_PARAM_NAME):
                    idx = sub.slice
                    if isinstance(idx, ast.Constant):
                        key = idx.value
                if key in _PROMOTION_FORBIDDEN_KEYS:
                    offenders.append(f'{filename}:{sub.lineno}: reads raw[{key!r}]')
        self.assertEqual([], offenders)


class FixtureMatrixTests(unittest.TestCase):
    """The properties that only make sense once all six boundaries exist:
    the fixture names are pairwise distinct, the declared classes among the
    four that have one are pairwise distinct and each a member of the nine,
    none of the six masquerades (and the check has teeth), and all six
    boundary modules expose the same five free functions (D-01's
    uniform-shape decision made executable).
    """

    ALL_SIX_FIXTURE_NAMES = [
        'keyword_classification_fixture',
        'system_of_record_assessment_fixture',
        'rate_card_valuation_fixture',
        'confirmation_workflow_evidence_fixture',
        'cohort_estimator_impact_fixture',
        'argv_conformance_reporting_fixture',
    ]

    # The four boundaries that declare an evidence_class at registration
    # (D-07: the other two -- cohort impact and reporting -- carry a
    # different property instead, proven in
    # tests/test_phase45_contract_only_boundaries.py).
    FOUR_DECLARED_CLASSES = [
        'ACTIVITY_MEASURED', 'OUTCOME_OBSERVED', 'CUSTOMER_CONFIGURED',
        'CUSTOMER_CONFIRMED',
    ]

    EVIDENCE_CLASSES = frozenset({
        'ACTIVITY_MEASURED', 'OUTPUT_OBSERVED', 'OUTCOME_OBSERVED',
        'MODEL_ESTIMATED_DEMO', 'CUSTOMER_CONFIGURED', 'CUSTOMER_CONFIRMED',
        'ASSOCIATIONAL', 'QUASI_EXPERIMENTAL_IMPACT', 'EXPERIMENTAL_IMPACT',
    })

    def setUp(self):
        self.br = _load_boundary_registry()
        self.classification = _load_classification()
        self.evaluators = _load_evaluators()
        self.valuation = _load_valuation()
        self.evidence = _load_evidence()
        self.cohort_impact = _load_cohort_impact()
        self.reporting = _load_reporting()

        # cohort_impact.py and reporting.py ship with ZERO registrants by
        # design (D-03/D-02 AMENDED) -- register their own shipped fixture
        # functions here, under their own declared version and class,
        # mirroring tests/test_phase45_contract_only_boundaries.py's
        # CrossRegistryIsolationTests.test_is_masquerading_has_teeth. This
        # is the ONLY mutation this class performs on either registry;
        # tearDown restores nothing further because each module object is
        # freshly loaded per test via setUp, per _load_module's own
        # registrant-hygiene contract.
        self.cohort_impact.register(
            'cohort_estimator_impact_fixture',
            self.cohort_impact._cohort_estimator_impact_fixture,
            self.cohort_impact.COHORT_FIXTURE_VERSION,
            evidence_class='QUASI_EXPERIMENTAL_IMPACT',
        )
        self.reporting.register(
            'argv_conformance_reporting_fixture',
            self.reporting._argv_conformance_reporting_fixture,
            self.reporting.REPORTING_FIXTURE_VERSION,
            evidence_class='',
        )

        self.six_modules = {
            'keyword_classification_fixture': self.classification,
            'system_of_record_assessment_fixture': self.evaluators,
            'rate_card_valuation_fixture': self.valuation,
            'confirmation_workflow_evidence_fixture': self.evidence,
            'cohort_estimator_impact_fixture': self.cohort_impact,
            'argv_conformance_reporting_fixture': self.reporting,
        }

    def tearDown(self):
        # Every module in self.six_modules was freshly loaded in setUp, so
        # there is nothing process-global to restore -- stated explicitly
        # per this plan's own instruction, rather than a silent no-op.
        pass

    def test_six_fixture_names_are_pairwise_distinct(self):
        self.assertEqual(6, len(self.ALL_SIX_FIXTURE_NAMES))
        self.assertEqual(6, len(set(self.ALL_SIX_FIXTURE_NAMES)))

    def test_literal_name_list_matches_what_the_six_registries_actually_report(self):
        for name, mod in self.six_modules.items():
            with self.subTest(name=name):
                self.assertIn(
                    name, mod.registered(),
                    f'{name!r} is not registered in its own module -- a '
                    'rename in one place and not the other',
                )

    def test_four_declared_classes_are_pairwise_distinct_and_members_of_the_nine(self):
        self.assertEqual(4, len(self.FOUR_DECLARED_CLASSES))
        self.assertEqual(4, len(set(self.FOUR_DECLARED_CLASSES)))
        for cls in self.FOUR_DECLARED_CLASSES:
            with self.subTest(cls=cls):
                self.assertIn(cls, self.EVIDENCE_CLASSES)
                self.assertNotEqual(self.br.MASQUERADE_CLASS, cls)

    def test_four_declared_classes_match_what_the_four_registries_actually_declare(self):
        expectations = {
            'keyword_classification_fixture': ('ACTIVITY_MEASURED', self.classification),
            'system_of_record_assessment_fixture': ('OUTCOME_OBSERVED', self.evaluators),
            'rate_card_valuation_fixture': ('CUSTOMER_CONFIGURED', self.valuation),
            'confirmation_workflow_evidence_fixture': ('CUSTOMER_CONFIRMED', self.evidence),
        }
        for name, (expected, mod) in expectations.items():
            with self.subTest(name=name):
                self.assertEqual(expected, mod.resolve_evidence_class(name))

    def test_cohort_fixture_declares_impact_label_reporting_fixture_declares_nothing(self):
        """D-07: the two boundaries with no evidence_class of their own get
        the property that actually matters for them instead -- proven
        elsewhere (CohortNonPromotionTests, ReportingConformanceTests in
        tests/test_phase45_contract_only_boundaries.py). Here: the
        declared-class SHAPE matches that assignment."""
        self.assertEqual(
            'QUASI_EXPERIMENTAL_IMPACT',
            self.cohort_impact.resolve_evidence_class('cohort_estimator_impact_fixture'),
        )
        self.assertEqual(
            '',
            self.reporting.resolve_evidence_class('argv_conformance_reporting_fixture'),
        )

    def test_none_of_the_six_fixtures_is_masquerading(self):
        for name, mod in self.six_modules.items():
            with self.subTest(name=name):
                self.assertFalse(self.br.is_masquerading(mod._REGISTRY, name))

    def test_masquerade_check_has_teeth_on_a_deliberately_masquerading_registrant(self):
        throwaway = _load_cohort_impact()
        throwaway.register(
            'throwaway_masquerade_registrant_45_06', lambda *a: None, '1',
            evidence_class=self.br.MASQUERADE_CLASS,
        )
        self.assertTrue(
            self.br.is_masquerading(throwaway._REGISTRY, 'throwaway_masquerade_registrant_45_06')
        )

    def test_all_six_boundary_modules_expose_the_same_five_free_functions(self):
        expected = {'register', 'resolve', 'resolve_version', 'resolve_evidence_class', 'registered'}
        for filename in _BOUNDARY_MODULE_FILENAMES:
            with self.subTest(filename=filename):
                mod = _load_module(filename, f'phase45_06_shapecheck_{filename}')
                for fn_name in expected:
                    self.assertTrue(
                        callable(getattr(mod, fn_name, None)),
                        f'{filename} is missing callable {fn_name!r}',
                    )


class PhaseGateTests(unittest.TestCase):
    """The phase gate, recorded as a documented procedure rather than run
    from inside this test (a full-suite run inside a single test would
    itself take ~11 minutes and defeats the purpose of a targeted run).

    THE GATE, run manually and synchronously, never backgrounded:

        NO_COLOR=1 python3 -m unittest tests.test_phase45_boundary_fixtures -v \\
            > /tmp/45-06-t3.log 2>&1; echo "exit=$?"
        grep -aE '^(Ran |OK|FAILED)' /tmp/45-06-t3.log

        NO_COLOR=1 python3 -m unittest discover -s tests -p 'test_*.py' -v \\
            > /tmp/45-06-gate.log 2>&1; echo "exit=$?"
        grep -aE '^(OK|FAILED)' /tmp/45-06-gate.log

    NO_COLOR=1 is required: Python 3.13+ colorizes unittest's own summary
    line with ANSI escapes by default, which defeats a bare grep for
    '^OK'/'^FAILED' (this is what defeated Phase 44's gate). Redirect to a
    file and read the status line out of the file; do not pipe the run
    itself through `tail`, because `tail` can exit 0 on a truncated stream
    that never reached the status line.

    A log with NO '^OK' and NO '^FAILED' line is a FAILURE, not a pass,
    whatever the shell's own $? appears to say -- the run may have been
    killed, timed out, or crashed the interpreter before unittest ever
    printed its summary.

    The expected-failure count must be RE-VERIFIED at gate time, never
    assumed to still be the value recorded in an earlier plan's SUMMARY.md
    (it was 1 as of 45-05; that is a fact about the past, not a promise
    about now). If the full-suite status line reads
    'OK (expected failures=N)' with N different from the last-recorded
    value, identify which test newly became an expected failure and why
    before accepting the gate -- a silently GROWING expected-failure count
    is exactly how a real regression hides.
    """

    def test_four_immutable_v1x_goldens_are_byte_identical(self):
        """Imports the recorded hashes from
        tests.test_phase45_contract_only_boundaries.GoldenImmutabilityTests
        by name, rather than retyping them, per this plan's own
        instruction. This is the same check that module already runs;
        re-running it here makes the phase-closing test module able to
        prove the claim on its own, without relying on test execution
        order across files."""
        expected = GoldenImmutabilityTests._EXPECTED_SHA256
        fixtures_dir = ROOT / 'tests' / 'fixtures' / 'compat'
        for filename, expected_hash in expected.items():
            with self.subTest(filename=filename):
                data = (fixtures_dir / filename).read_bytes()
                actual = hashlib.sha256(data).hexdigest()
                self.assertEqual(expected_hash, actual)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
