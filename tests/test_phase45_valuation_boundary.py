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


# ---------------------------------------------------------------------------
# DerivationDelegationTests / BoundReassertionTests -- driving the REAL
# _validate_assessment end to end, with a resolvable registered valuation
# implementation. PLUGIN is placed on sys.path for this section only (class
# setUpClass/tearDownClass), so classifier.py's own `import valuation`
# fallback -- used by both _register_valuation_impl (at import time) and
# _validate_assessment's own resolve step -- resolves to the SAME cached
# 'valuation' module this section registers throwaway implementations into,
# mirroring tests/test_phase45_boundary_registry.py's
# DeclaredEvidenceClassTests.
# ---------------------------------------------------------------------------

_THROWAWAY_SEQ = [0]


def _shared_valuation_module():
    """Bare `import valuation` -- the SAME cached sys.modules entry
    classifier.py's own `_load_valuation_module()` bare-import fallback
    resolves to once PLUGIN is on sys.path. Registering a throwaway
    implementation here is what makes it resolvable BY NAME from the real
    _validate_assessment call inside a classifier module loaded standalone
    via _load_classifier()."""
    import valuation as _val  # type: ignore
    return _val


def _write_config(config_path: Path, boundaries=None, rate_card=None):
    cfg = {}
    if boundaries is not None:
        cfg['boundaries'] = boundaries
    if rate_card is not None:
        cfg['llmOutcomeEvaluation'] = {'rateCard': rate_card}
    config_path.write_text(json.dumps(cfg))


class _ValuationBoundaryTestCase(unittest.TestCase):
    """Shared sys.path management and fixture helpers for the two classes
    below. No test_* methods of its own."""

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
        self.tmp = tempfile.mkdtemp(prefix='gsd-p45-05-valuation-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.config_path = Path(self.tmp) / 'config.json'

    def _raw(self, **over):
        raw = {
            'economic_mechanism': 'labor_substitution',
            'inferred_role': 'senior_engineer',
            'estimated_hours_saved': 2.5,
            'assumed_loaded_rate': 150.0,
            'currency': 'USD',
            'basis': 'time avoided',
            'confidence': 0.5,
        }
        raw.update(over)
        return raw

    def _load(self, boundaries=None, rate_card=None):
        _write_config(self.config_path, boundaries=boundaries, rate_card=rate_card)
        return _load_classifier({'REVENIUM_CONFIG_FILE': str(self.config_path)})


class DerivationDelegationTests(_ValuationBoundaryTestCase):
    """The REAL _validate_assessment, end to end, with a temp state dir and
    a config.json carrying the `boundaries` object and the rate card. One
    method per positive behavior bullet of 45-05-PLAN.md Task 3."""

    def test_rate_card_displaces_the_hours_times_rate_product(self):
        mod = self._load(
            boundaries={'valuation': 'rate_card_valuation_fixture'},
            rate_card={'senior_engineer': 480.0},
        )
        cfg = mod._llm_evaluation_config()
        got = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertEqual(480.0, got['estimated_value'])
        self.assertNotEqual(round(2.5 * 150.0, 2), got['estimated_value'])

    def test_role_the_card_does_not_name_abstains(self):
        mod = self._load(
            boundaries={'valuation': 'rate_card_valuation_fixture'},
            rate_card={'junior_engineer': 100.0},
        )
        cfg = mod._llm_evaluation_config()
        got = mod._validate_assessment(
            self._raw(inferred_role='senior_engineer'), cfg, 'stub', 'v1')
        self.assertIsNone(got)

    def test_boundaries_absent_is_byte_identical_to_before_this_plan(self):
        mod = self._load(boundaries=None, rate_card=None)
        cfg = mod._llm_evaluation_config()
        got = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertEqual(375.0, got['estimated_value'])

    def test_value_reaches_the_sidecar_record_through_build_job_assessment(self):
        mod = self._load(
            boundaries={'valuation': 'rate_card_valuation_fixture'},
            rate_card={'senior_engineer': 480.0},
        )
        cfg = mod._llm_evaluation_config()
        raw = self._raw()
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        valid_job = {
            'agentic_job_id': 'valuation-proof-001', 'job_type': 'code_review',
            'status': 'SUCCESS',
        }
        record = mod._build_job_assessment(valid_job, validated, raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(record)
        self.assertEqual(480.0, record['estimated_value'])


class BoundReassertionTests(_ValuationBoundaryTestCase):
    """The adversarial half. These are BEHAVIOURAL proofs that today's code
    refuses each of these returns; they do not prove a future edit cannot
    remove the re-check, and no static guard here claims otherwise.

    Every test registers a throwaway implementation into the shared
    'valuation' module's registry under a name unique to this call (via
    _THROWAWAY_SEQ) and restores it in tearDown, for the same reason
    45-04-PLAN.md requires it: last-registration-wins means a leaked
    registrant would let these tests lie to each other.
    """

    def _register_throwaway(self, fn):
        _THROWAWAY_SEQ[0] += 1
        name = f'throwaway_bound_reassertion_{_THROWAWAY_SEQ[0]}'
        val = _shared_valuation_module()
        val.register(name, fn, '1', evidence_class='CUSTOMER_CONFIGURED')
        self.addCleanup(val._REGISTRY._entries.pop, name, None)
        return name

    def _run(self, name):
        mod = self._load(boundaries={'valuation': name})
        cfg = mod._llm_evaluation_config()
        return mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')

    def _default_ceiling(self):
        mod = self._load(boundaries=None)
        return round(mod.DEFAULT_MAX_HOURS_SAVED * mod.DEFAULT_MAX_LOADED_RATE, 2)

    def test_amount_above_ceiling_abstains(self):
        name = self._register_throwaway(
            lambda a, c: {'estimated_value': 10_000_000.0, 'currency': 'USD'})
        self.assertIsNone(self._run(name))

    def test_zero_amount_abstains(self):
        name = self._register_throwaway(
            lambda a, c: {'estimated_value': 0.0, 'currency': 'USD'})
        self.assertIsNone(self._run(name))

    def test_negative_amount_abstains(self):
        name = self._register_throwaway(
            lambda a, c: {'estimated_value': -50.0, 'currency': 'USD'})
        self.assertIsNone(self._run(name))

    def test_non_finite_amount_abstains(self):
        name = self._register_throwaway(
            lambda a, c: {'estimated_value': float('nan'), 'currency': 'USD'})
        self.assertIsNone(self._run(name))

    def test_boolean_amount_abstains(self):
        """isinstance(True, int) is True in Python -- a naive read would
        coerce a returned `True` to the number 1 rather than rejecting
        it."""
        name = self._register_throwaway(
            lambda a, c: {'estimated_value': True, 'currency': 'USD'})
        self.assertIsNone(self._run(name))

    def test_non_dict_return_abstains(self):
        name = self._register_throwaway(lambda a, c: 'not-a-dict')
        self.assertIsNone(self._run(name))

    def test_foreign_currency_abstains(self):
        name = self._register_throwaway(
            lambda a, c: {'estimated_value': 100.0, 'currency': 'EUR'})
        self.assertIsNone(self._run(name))

    def test_raising_implementation_falls_back_to_builtin(self):
        def _raiser(a, c):
            raise RuntimeError('boom -- this implementation always raises')

        name = self._register_throwaway(_raiser)
        got = self._run(name)
        self.assertIsNotNone(got)
        self.assertEqual(375.0, got['estimated_value'])

    def test_unregistered_name_falls_back_to_builtin(self):
        got = self._run('no_such_valuation_implementation')
        self.assertIsNotNone(got)
        self.assertEqual(375.0, got['estimated_value'])

    def test_amount_exactly_at_ceiling_is_accepted(self):
        ceiling = self._default_ceiling()
        name = self._register_throwaway(
            lambda a, c: {'estimated_value': ceiling, 'currency': 'USD'})
        got = self._run(name)
        self.assertIsNotNone(got)
        self.assertEqual(ceiling, got['estimated_value'])

    def test_amount_one_cent_above_ceiling_abstains(self):
        over = round(self._default_ceiling() + 0.01, 2)
        name = self._register_throwaway(
            lambda a, c: {'estimated_value': over, 'currency': 'USD'})
        self.assertIsNone(self._run(name))

    def test_refusal_log_line_is_distinguishable_and_uses_repr(self):
        refused = {'estimated_value': -999.0, 'currency': 'USD'}
        name = self._register_throwaway(lambda a, c: dict(refused))
        mod = self._load(boundaries={'valuation': name})
        cfg = mod._llm_evaluation_config()
        with self.assertLogs('revenium_classifier', level='WARNING') as cm:
            got = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNone(got)
        messages = [r.getMessage() for r in cm.records]
        self.assertFalse(
            any('bound exceeded' in m for m in messages),
            'the valuation refusal log line must be distinguishable from '
            'the hours/rate bound abstention above it',
        )
        self.assertTrue(
            any('valuation' in m and 'out-of-bounds' in m for m in messages),
            f'expected a distinct valuation-refusal log line, got: {messages}',
        )
        self.assertTrue(
            any(repr(refused) in m for m in messages),
            f'expected the refused value rendered with %r, got: {messages}',
        )


if __name__ == '__main__':  # pragma: no cover
    unittest.main()


class ZeroRoundingBackCompatTests(unittest.TestCase):
    """CR-01 (phase-45 code review): a hours*rate product that ROUNDS to
    $0.00 must still produce a record, not an abstention.

    Why this exists as a standing test rather than a one-line fix: the
    built-in `hours_times_rate` derivation is ITSELF a registrant, so the
    default, unconfigured path runs through the valuation boundary's
    post-call re-check. That re-check originally used a strict `0 < amount`
    lower bound, which silently abstained a case `main` shipped -- its
    derivation was an unconditional `round(hours * rate, 2)` with no lower
    bound at all.

    Two project rules make the abstention wrong, not merely different:
    CLAUDE.md requires a feature-off install to meter byte-identically to
    before, and EGV-17 requires zero and negative work to stay VISIBLE with
    its cost rather than disappear. An abstention hides it.

    The upper bound is what the re-check is actually for -- an
    implementation handing back an unbounded number -- and a zero is not
    that. A NEGATIVE amount is still refused, because the skill must never
    assert a negative value it never measured (phase 44 D-14).
    """

    def setUp(self):
        self.cls = _load_classifier()

    def _raw(self, hours, rate):
        return {
            'economic_mechanism': 'labor_substitution',
            'inferred_role': 'engineer',
            'estimated_hours_saved': hours,
            'assumed_loaded_rate': rate,
            'currency': 'USD',
            'basis': 'rounds-to-zero back-compat case',
            'confidence': 0.5,
        }

    def test_product_rounding_to_zero_still_produces_a_record(self):
        # Passes every input gate: 0 < hours <= max and 0 < rate <= max.
        # round(0.001 * 1.0, 2) == 0.0.
        result = self.cls._validate_assessment(self._raw(0.001, 1.0), {})
        self.assertIsNotNone(
            result,
            'a hours*rate product that rounds to $0.00 must still produce a '
            'record -- main shipped one, and abstaining here breaks both the '
            'byte-identical feature-off invariant and EGV-17',
        )
        self.assertEqual(0.0, result['estimated_value'])
        self.assertEqual('USD', result['currency'])

    def test_matches_mains_unconditional_rounding_across_several_pairs(self):
        for hours, rate in ((0.001, 1.0), (0.0001, 10.0), (0.004, 1.0),
                            (0.01, 0.4), (2.5, 150.0), (1.0, 0.01)):
            with self.subTest(hours=hours, rate=rate):
                result = self.cls._validate_assessment(self._raw(hours, rate), {})
                self.assertIsNotNone(result, 'no valid input pair may abstain here')
                self.assertEqual(round(hours * rate, 2), result['estimated_value'])

    def test_negative_amount_from_an_implementation_is_still_refused(self):
        # The lower bound was widened to accept zero, NOT to accept negatives.
        val = _load_valuation()
        self.assertIsNone(
            val._rate_card_valuation_fixture(
                {
                    'estimated_hours_saved': 1.0,
                    'assumed_loaded_rate': 1.0,
                    'currency': 'USD',
                    'inferred_role': 'engineer',
                },
                {'rateCard': {'engineer': -5.0}},
            ),
            'a negative rate-card amount must still abstain',
        )
