"""Phase 54 Plan 01 — the revenue valuation boundary (ROI-05/ROI-06):
proving the whole revenue seam end to end on one thin path, and the
declaration contract it rests on.

A registrant declares, at register(), the set of economic mechanisms it is
ever permitted to assert (D-01); that set may contain only operator-only
mechanisms and is validated at import time (D-03); the mechanism attributed
to a given record is the one the registrant returned for THIS call,
re-checked by the caller against that registration-time ceiling, falling
back to the evaluator's own mechanism when the registrant declared or
returned none (D-02, D-14).

Requirements covered: ROI-05 (a configured revenue card prices a job with
no per-job CLI invocation), ROI-06 (the mechanism-precedence and
operator-bound-key edges).

Guarantee class: BEHAVIOURAL, matching every prior valuation-boundary test
module's own convention (test_phase45_valuation_boundary.py,
test_phase50_declaration_authority.py) -- these tests prove today's real
code's accept/reject verdicts, not an impossibility claim about future
edits.

Task 1: DerivationTests (the end-to-end tracer) and OperatorBoundKeyTests
(the ROI-06 selector-key proofs for this task's path).
Task 2: MechanismDeclarationTests (the declaration ceiling, the
cross-module drift guard, and the silence-is-identical contract test).
"""
import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'
HERMES_REPORT_SH = ROOT / 'skills' / 'revenium' / 'scripts' / 'hermes-report.sh'


def _load_valuation():
    """Fresh valuation.py by file path, no package parent, no sys.path
    entry -- the idiom test_phase45_valuation_boundary.py's _load_valuation()
    uses. A fresh module object per call means a fresh, empty-but-for-the-
    shipped-fixtures `_REGISTRY`/`_MECHANISM_DECLARATIONS` per call -- no
    cross-test registration leakage."""
    spec = importlib.util.spec_from_file_location(
        'phase54_valuation', str(PLUGIN / 'valuation.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_classifier(env: "dict | None" = None):
    """Mirror of test_phase45_valuation_boundary.py's own _load_classifier,
    duplicated here for the same reason every other Phase 45+ test file's
    copy of it is (test fixtures do not share code with each other or with
    the producer). Loaded standalone (no package): classifier.py's own
    `from . import valuation` fallback then attempts a BARE `import
    valuation`, which only resolves when PLUGIN has been placed on
    sys.path (see _ValuationBoundaryTestCase.setUpClass below)."""
    env = env or {}
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(
            'phase54_classifier_revenue_valuation_boundary', str(PLUGIN / 'classifier.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _write_config(config_path: Path, boundaries=None, rate_card=None,
                   revenue_card=None, revenue_card_key=None, max_revenue_value=None):
    """Extends test_phase45_valuation_boundary.py's own _write_config with
    the three new Phase 54 keys -- all nested inside `llmOutcomeEvaluation`
    beside `rateCard`, NOT at the top level beside `boundaries` (that
    object follows a different placement rule; a production host that
    guessed wrong left 85 sessions unpriceable in Phase 53)."""
    cfg = {}
    if boundaries is not None:
        cfg['boundaries'] = boundaries
    outcome_eval = {}
    if rate_card is not None:
        outcome_eval['rateCard'] = rate_card
    if revenue_card is not None:
        outcome_eval['revenueCard'] = revenue_card
    if revenue_card_key is not None:
        outcome_eval['revenueCardKey'] = revenue_card_key
    if max_revenue_value is not None:
        outcome_eval['maxRevenueValue'] = max_revenue_value
    if outcome_eval:
        cfg['llmOutcomeEvaluation'] = outcome_eval
    config_path.write_text(json.dumps(cfg))


# ---------------------------------------------------------------------------
# --metadata forwarder extraction -- duplicated (not imported) from
# tests/test_phase46_metadata_envelope.py's own extraction shape, per this
# plan's own instruction: importing that module would reopen its
# documented env-mutation-at-import trap. Returns None -- never a partial
# or guessed body -- if the anchor has moved, so a real drift fails the
# caller loudly instead of silently testing a stale shape.
# ---------------------------------------------------------------------------
def _extract_outcome_metadata_heredoc(script_text):
    anchor = 'outcome_metadata=$('
    start = script_text.find(anchor)
    if start == -1:
        return None
    heredoc_start = script_text.find("<<'PY'", start)
    if heredoc_start == -1:
        return None
    body_start = script_text.find('\n', heredoc_start) + 1
    body_end = script_text.find('\nPY\n', body_start)
    if body_end == -1:
        return None
    return script_text[body_start:body_end]


def _run_forwarder(body, env):
    return subprocess.run(
        [sys.executable, '-'], input=body, env=env,
        capture_output=True, text=True,
    )


def _assessment_env(assessment=None, source='prod', status='SUCCESS', failure_reason=''):
    return {
        'OUTCOME_SOURCE': source,
        'OUTCOME_STATUS': status,
        'OUTCOME_FAILURE_REASON': failure_reason,
        'ASSESSMENT_JSON': json.dumps(assessment) if assessment is not None else '',
    }


class _ValuationBoundaryTestCase(unittest.TestCase):
    """Shared sys.path management and fixture helpers. No test_* methods
    of its own -- modelled on test_phase45_valuation_boundary.py's own
    base class."""

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
        self.tmp = tempfile.mkdtemp(prefix='gsd-p54-01-revenue-')
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

    def _load(self, boundaries=None, rate_card=None, revenue_card=None,
              revenue_card_key=None, max_revenue_value=None):
        _write_config(
            self.config_path, boundaries=boundaries, rate_card=rate_card,
            revenue_card=revenue_card, revenue_card_key=revenue_card_key,
            max_revenue_value=max_revenue_value,
        )
        return _load_classifier({'REVENIUM_CONFIG_FILE': str(self.config_path)})


class DerivationTests(_ValuationBoundaryTestCase):
    """The end-to-end tracer: a configured revenue card prices a booking
    through boundaries.valuation with no correct-assessment.sh invocation,
    and incremental_revenue reaches the persisted record and the
    --metadata envelope (ROI-05, D-01, D-02)."""

    def test_configured_revenue_card_prices_end_to_end(self):
        mod = self._load(
            boundaries={'valuation': 'revenue_card_valuation_fixture'},
            revenue_card={'hospitality-booking-agent': {'grossPerJob': 250.0}},
            revenue_card_key='hospitality-booking-agent',
        )
        cfg = mod._llm_evaluation_config()
        raw = self._raw()
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        self.assertEqual(250.0, validated['estimated_value'])
        self.assertEqual('incremental_revenue', validated['economic_mechanism'])

        valid_job = {
            'agentic_job_id': 'revenue-proof-001', 'job_type': 'booking_completion',
            'status': 'SUCCESS',
        }
        record = mod._build_job_assessment(valid_job, validated, raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(record)
        self.assertEqual(250.0, record['estimated_value'])
        self.assertEqual('incremental_revenue', record['economic_mechanism'])

        # Drive the SAME record through the REAL --metadata forwarder
        # heredoc extracted live from hermes-report.sh.
        script_text = HERMES_REPORT_SH.read_text()
        body = _extract_outcome_metadata_heredoc(script_text)
        self.assertIsNotNone(
            body, 'outcome_metadata heredoc anchor moved in hermes-report.sh')
        env = {**os.environ, **_assessment_env(assessment=record)}
        result = _run_forwarder(body, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        self.assertEqual(1, len(lines))
        meta = json.loads(lines[0])
        self.assertEqual('incremental_revenue', meta.get('economic_mechanism'))

    def test_default_install_unchanged(self):
        """With no `boundaries` object and no revenue card,
        _validate_assessment's returned dict has no economic_mechanism key
        at all, and _build_job_assessment's record carries
        _resolve_economic_mechanism(raw)'s answer, exactly as before this
        task (D-14)."""
        mod = self._load(boundaries=None, rate_card=None)
        cfg = mod._llm_evaluation_config()
        raw = self._raw(economic_mechanism='labor_substitution')
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        self.assertNotIn('economic_mechanism', validated)

        valid_job = {
            'agentic_job_id': 'default-install-001', 'job_type': 'code_review',
            'status': 'SUCCESS',
        }
        record = mod._build_job_assessment(valid_job, validated, raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(record)
        self.assertEqual(
            mod._resolve_economic_mechanism(raw), record['economic_mechanism'])
        self.assertEqual('labor_substitution', record['economic_mechanism'])


class OperatorBoundKeyTests(_ValuationBoundaryTestCase):
    """ROI-06/D-06 -- the card entry is selected by an operator-bound key,
    never by the model's own inferred_role, and never by dict order when
    no key is configured.

    DEVIATION from 54-01, recorded deliberately (Rule 1 -- these three
    tests asserted the PRE-D-04 behaviour): before Task 2's internal
    delegation, "nothing revenue-shaped to price" aborted the whole
    assessment. Task 2 changes that outcome on purpose (D-04) -- these
    three cases are exactly the "nothing revenue-shaped to price" class,
    so they now delegate to the built-in hours_times_rate derivation
    instead of aborting. What each test still proves is unchanged: the
    model's inferred_role and dict order never select a card entry. Only
    the no-selection OUTCOME changed, from "abstain" to "delegate".
    """

    def test_multi_entry_card_with_no_key_delegates_to_builtin(self):
        mod = self._load(
            boundaries={'valuation': 'revenue_card_valuation_fixture'},
            revenue_card={
                'hospitality-booking-agent': {'grossPerJob': 250.0},
                'car-rental-agent': {'grossPerJob': 90.0},
            },
            revenue_card_key=None,
        )
        cfg = mod._llm_evaluation_config()
        got = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertEqual(round(2.5 * 150.0, 2), got['estimated_value'])
        self.assertNotIn('economic_mechanism', got)

    def test_inferred_role_naming_a_card_entry_does_not_select_it(self):
        mod = self._load(
            boundaries={'valuation': 'revenue_card_valuation_fixture'},
            revenue_card={'hospitality-booking-agent': {'grossPerJob': 250.0}},
            revenue_card_key=None,
        )
        cfg = mod._llm_evaluation_config()
        got = mod._validate_assessment(
            self._raw(inferred_role='hospitality-booking-agent'), cfg, 'stub', 'v1')
        self.assertIsNotNone(got)
        # The model's inferred_role never selects a card entry -- the
        # fixture still delegates (hours x rate), not the card's 250.0.
        self.assertEqual(round(2.5 * 150.0, 2), got['estimated_value'])
        self.assertNotIn('economic_mechanism', got)

    def test_key_naming_an_absent_entry_delegates_to_builtin(self):
        mod = self._load(
            boundaries={'valuation': 'revenue_card_valuation_fixture'},
            revenue_card={'hospitality-booking-agent': {'grossPerJob': 250.0}},
            revenue_card_key='car-rental-agent',
        )
        cfg = mod._llm_evaluation_config()
        got = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertEqual(round(2.5 * 150.0, 2), got['estimated_value'])
        self.assertNotIn('economic_mechanism', got)

    # -- Task 1: the full rejection matrix, called directly on the
    # registrant through a freshly-loaded valuation module (not through
    # _validate_assessment -- this proves the registrant's OWN abstention
    # discipline, independent of the caller's re-checks). Modelled on
    # test_phase36_evaluator_seam.py's RejectionMatrixTests table shape.
    #
    # Each row: (label, assumptions, config). `_DISTINCTIVE_GROSS` is
    # embedded in every config that carries a real entry, so the redaction
    # proof below can assert it never appears in any captured log record.

    _DISTINCTIVE_GROSS = 4321.0

    def _rejection_matrix(self):
        gross = self._DISTINCTIVE_GROSS
        return [
            ('assumptions_none', None,
             {'revenueCard': {'k': {'grossPerJob': gross}}, 'revenueCardKey': 'k'}),
            ('assumptions_list', [],
             {'revenueCard': {'k': {'grossPerJob': gross}}, 'revenueCardKey': 'k'}),
            ('assumptions_string', 'not-a-dict',
             {'revenueCard': {'k': {'grossPerJob': gross}}, 'revenueCardKey': 'k'}),
            ('config_none', {'currency': 'USD'}, None),
            ('config_list', {'currency': 'USD'}, []),
            ('config_string', {'currency': 'USD'}, 'not-a-dict'),
            ('revenue_card_absent', {'currency': 'USD'}, {'revenueCardKey': 'k'}),
            ('revenue_card_none', {'currency': 'USD'},
             {'revenueCard': None, 'revenueCardKey': 'k'}),
            ('revenue_card_list', {'currency': 'USD'},
             {'revenueCard': [], 'revenueCardKey': 'k'}),
            ('revenue_card_string', {'currency': 'USD'},
             {'revenueCard': 'not-a-dict', 'revenueCardKey': 'k'}),
            ('revenue_card_empty', {'currency': 'USD'},
             {'revenueCard': {}, 'revenueCardKey': 'k'}),
            ('revenue_card_key_absent', {'currency': 'USD'},
             {'revenueCard': {'k': {'grossPerJob': gross}}}),
            ('revenue_card_key_empty_string', {'currency': 'USD'},
             {'revenueCard': {'k': {'grossPerJob': gross}}, 'revenueCardKey': ''}),
            ('revenue_card_key_non_string', {'currency': 'USD'},
             {'revenueCard': {'k': {'grossPerJob': gross}}, 'revenueCardKey': 42}),
            ('revenue_card_key_unmatched', {'currency': 'USD'},
             {'revenueCard': {'k': {'grossPerJob': gross}}, 'revenueCardKey': 'other'}),
            ('entry_not_dict', {'currency': 'USD'},
             {'revenueCard': {'k': gross}, 'revenueCardKey': 'k'}),
            ('gross_absent', {'currency': 'USD'},
             {'revenueCard': {'k': {}}, 'revenueCardKey': 'k'}),
            ('gross_string', {'currency': 'USD'},
             {'revenueCard': {'k': {'grossPerJob': str(gross)}}, 'revenueCardKey': 'k'}),
            ('gross_bool', {'currency': 'USD'},
             {'revenueCard': {'k': {'grossPerJob': True}}, 'revenueCardKey': 'k'}),
            ('gross_nan', {'currency': 'USD'},
             {'revenueCard': {'k': {'grossPerJob': float('nan')}}, 'revenueCardKey': 'k'}),
            ('gross_inf', {'currency': 'USD'},
             {'revenueCard': {'k': {'grossPerJob': float('inf')}}, 'revenueCardKey': 'k'}),
            ('gross_zero', {'currency': 'USD'},
             {'revenueCard': {'k': {'grossPerJob': 0}}, 'revenueCardKey': 'k'}),
            ('gross_negative', {'currency': 'USD'},
             {'revenueCard': {'k': {'grossPerJob': -gross}}, 'revenueCardKey': 'k'}),
        ]

    def test_rejection_matrix_every_row_abstains(self):
        rows = self._rejection_matrix()
        # A shrunken table would silently skip cases rather than fail
        # loudly -- assert the length first (acceptance criteria: >= 12).
        self.assertGreaterEqual(len(rows), 12)
        val = _load_valuation()
        for label, assumptions, config in rows:
            with self.subTest(label):
                self.assertIsNone(
                    val._revenue_card_valuation_fixture(assumptions, config))

    def test_happy_path_prices_and_emits_no_log(self):
        val = _load_valuation()
        with self.assertNoLogs('revenium_classifier.valuation', level='WARNING'):
            got = val._revenue_card_valuation_fixture(
                {'currency': 'USD'},
                {'revenueCard': {'k': {'grossPerJob': self._DISTINCTIVE_GROSS}},
                 'revenueCardKey': 'k'},
            )
        self.assertIsNotNone(got)
        self.assertEqual(self._DISTINCTIVE_GROSS, got['estimated_value'])

    # Branches where the card key is a meaningful, resolvable string --
    # the diagnostic must positively name it (mitigates T-54-02: proves
    # the log is useful, not merely empty).
    _KEY_RELATED_LABELS = frozenset({
        'revenue_card_key_unmatched', 'entry_not_dict', 'gross_absent',
        'gross_string', 'gross_bool', 'gross_nan', 'gross_inf',
        'gross_zero', 'gross_negative',
    })

    def test_redaction_no_abstain_branch_ever_logs_the_configured_gross(self):
        val = _load_valuation()
        gross_str = str(self._DISTINCTIVE_GROSS)
        for label, assumptions, config in self._rejection_matrix():
            with self.subTest(label):
                with self.assertLogs(
                        'revenium_classifier.valuation', level='WARNING') as cap:
                    got = val._revenue_card_valuation_fixture(assumptions, config)
                self.assertIsNone(got)
                self.assertGreaterEqual(len(cap.records), 1)
                for record in cap.records:
                    self.assertNotIn(gross_str, record.getMessage())
                    self.assertNotIn(gross_str, str(record))
                if label in self._KEY_RELATED_LABELS:
                    joined = ' '.join(r.getMessage() for r in cap.records)
                    self.assertIn('k', joined)


# ---------------------------------------------------------------------------
# Task 2 -- MechanismDeclarationTests
# ---------------------------------------------------------------------------

_THROWAWAY_SEQ = [0]


def _throwaway_registrant_name(prefix='p54_throwaway'):
    _THROWAWAY_SEQ[0] += 1
    return f'{prefix}_{_THROWAWAY_SEQ[0]}'


class MechanismDeclarationTests(_ValuationBoundaryTestCase):
    """D-03/ROI-06 -- the declaration ceiling refuses at import time, a
    returned mechanism outside it is discarded (not fatal) at call time,
    and a registrant that declares nothing produces a record identical to
    today's (D-14). Also holds the cross-module vocabulary sync test."""

    # -- 1. The ceiling refuses (D-03, ROI-06) -------------------------------

    def test_declarable_mechanisms_has_exactly_three_members(self):
        # A shrunken VALUATION_DECLARABLE_MECHANISMS would silently skip
        # cases below rather than fail loudly -- assert the count first.
        val = _load_valuation()
        self.assertEqual(3, len(val.VALUATION_DECLARABLE_MECHANISMS))

    def test_ceiling_refuses_every_evaluator_mechanism_and_malformed_shape(self):
        mod = _load_classifier({})
        cases = {
            'labor_substitution_is_evaluator_only': 'labor_substitution',
            'augmentation_capacity_expansion_is_evaluator_only':
                'augmentation_capacity_expansion',
            'newly_enabled_work_is_evaluator_only': 'newly_enabled_work',
            'unknown_string': 'not_a_real_mechanism',
        }
        for label, member in cases.items():
            with self.subTest(label):
                val = _load_valuation()
                with self.assertRaises(ValueError):
                    val.register(
                        _throwaway_registrant_name(), lambda a, c: None, '1',
                        economic_mechanisms={member},
                    )

        malformed_collections = {
            'empty_string_member': {''},
            'none_member': {None},
            'non_string_member': {42},
            'bare_string_not_a_collection': 'incremental_revenue',
            'non_iterable': 12345,
        }
        for label, value in malformed_collections.items():
            with self.subTest(label):
                val = _load_valuation()
                with self.assertRaises(ValueError):
                    val.register(
                        _throwaway_registrant_name(), lambda a, c: None, '1',
                        economic_mechanisms=value,
                    )

    def test_each_declarable_mechanism_registers_and_round_trips(self):
        val = _load_valuation()
        for mechanism in val.VALUATION_DECLARABLE_MECHANISMS:
            with self.subTest(mechanism):
                name = _throwaway_registrant_name()
                val.register(name, lambda a, c: None, '1',
                             economic_mechanisms={mechanism})
                self.assertEqual(
                    frozenset({mechanism}), val.resolve_declared_mechanisms(name))

    def test_refused_registration_leaves_no_half_state(self):
        val = _load_valuation()
        name = _throwaway_registrant_name()
        with self.assertRaises(ValueError):
            val.register(name, lambda a, c: None, '1',
                         economic_mechanisms={'labor_substitution'})
        self.assertIsNone(val.resolve('x-never-registered'))
        self.assertEqual(frozenset(), val.resolve_declared_mechanisms(name))

    # -- 2. The vocabulary cannot drift ---------------------------------------

    def test_vocabulary_cannot_drift_from_classifier_operator_only_mechanisms(self):
        val = _load_valuation()
        mod = _load_classifier({})
        self.assertEqual(
            val.VALUATION_DECLARABLE_MECHANISMS, mod.OPERATOR_ONLY_MECHANISMS,
            'valuation.py (VALUATION_DECLARABLE_MECHANISMS) and '
            'classifier.py (OPERATOR_ONLY_MECHANISMS) have drifted -- the '
            'duplication between these two files is deliberate (CLAUDE.md '
            'forbids sharing code between them), and this test is what '
            'keeps the two copies honest',
        )

    # -- 3. A returned mechanism outside the declared set is discarded ------

    def _register_and_load(self, fn, economic_mechanisms):
        """Register a throwaway implementation into the SHARED `valuation`
        module (bare `import valuation`, the same sys.modules entry
        classifier.py's own bare-import fallback resolves to once PLUGIN
        is on sys.path), so it is resolvable BY NAME from a standalone-
        loaded classifier module."""
        import valuation as val  # type: ignore
        name = _throwaway_registrant_name()
        val.register(name, fn, '1', evidence_class='CUSTOMER_CONFIGURED',
                     economic_mechanisms=economic_mechanisms)
        self.addCleanup(val._REGISTRY._entries.pop, name, None)
        self.addCleanup(val._MECHANISM_DECLARATIONS.pop, name, None)
        return name

    def test_mechanism_outside_declared_set_is_discarded_not_fatal(self):
        def _fn(a, c):
            return {'estimated_value': 42.0, 'currency': a.get('currency'),
                    'economic_mechanism': 'incremental_revenue'}
        name = self._register_and_load(_fn, {'risk_avoidance'})
        mod = self._load(boundaries={'valuation': name})
        cfg = mod._llm_evaluation_config()
        raw = self._raw(economic_mechanism='labor_substitution')
        got = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertEqual(42.0, got['estimated_value'])
        self.assertNotIn('economic_mechanism', got)

        record = mod._build_job_assessment(
            {'agentic_job_id': 'discard-001', 'job_type': 'code_review', 'status': 'SUCCESS'},
            got, raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(record)
        self.assertEqual(mod._resolve_economic_mechanism(raw), record['economic_mechanism'])
        self.assertEqual(42.0, record['estimated_value'])

    def test_non_string_and_empty_mechanism_are_discarded(self):
        for bad_value in (123, '', None, True):
            with self.subTest(bad_value=bad_value):
                def _fn(a, c, _bad=bad_value):
                    return {'estimated_value': 17.0, 'currency': a.get('currency'),
                            'economic_mechanism': _bad}
                name = self._register_and_load(_fn, {'incremental_revenue'})
                mod = self._load(boundaries={'valuation': name})
                cfg = mod._llm_evaluation_config()
                raw = self._raw(economic_mechanism='labor_substitution')
                got = mod._validate_assessment(raw, cfg, 'stub', 'v1')
                self.assertIsNotNone(got)
                self.assertNotIn('economic_mechanism', got)

    def test_mechanism_returned_by_registrant_declaring_nothing_is_discarded(self):
        def _fn(a, c):
            return {'estimated_value': 17.0, 'currency': a.get('currency'),
                    'economic_mechanism': 'incremental_revenue'}
        name = self._register_and_load(_fn, None)
        mod = self._load(boundaries={'valuation': name})
        cfg = mod._llm_evaluation_config()
        raw = self._raw(economic_mechanism='labor_substitution')
        got = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertNotIn('economic_mechanism', got)

    # -- 4. The contract test (assumption-delta checkpoint's companion) -----

    def test_every_declared_mechanism_round_trips_and_silence_is_identical(self):
        import valuation as val  # type: ignore
        for mechanism in val.VALUATION_DECLARABLE_MECHANISMS:
            with self.subTest(mechanism=mechanism):
                def _fn(a, c, _m=mechanism):
                    return {'estimated_value': 33.0, 'currency': a.get('currency'),
                            'economic_mechanism': _m}
                name = self._register_and_load(_fn, {mechanism})
                mod = self._load(boundaries={'valuation': name})
                cfg = mod._llm_evaluation_config()
                raw = self._raw(economic_mechanism='labor_substitution')
                validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
                self.assertIsNotNone(validated)
                self.assertEqual(mechanism, validated['economic_mechanism'])
                record = mod._build_job_assessment(
                    {'agentic_job_id': f'roundtrip-{mechanism}', 'job_type': 'code_review',
                     'status': 'SUCCESS'},
                    validated, raw, cfg, 'stub', 'v1')
                self.assertIsNotNone(record)
                self.assertEqual(mechanism, record['economic_mechanism'])

        # Silence: a registrant declaring nothing produces a record
        # identical, key for key and value for value, to the built-in
        # hours_times_rate path for the same input -- ts/job_started_at/
        # job_ended_at normalised since they read the clock.
        def _silent_fn(a, c):
            return None  # falls back to the built-in derivation

        name = self._register_and_load(_silent_fn, None)
        mod_a = self._load(boundaries={'valuation': name})
        mod_b = self._load(boundaries=None)
        raw = self._raw(economic_mechanism='labor_substitution')
        cfg_a = mod_a._llm_evaluation_config()
        cfg_b = mod_b._llm_evaluation_config()
        valid_a = mod_a._validate_assessment(raw, cfg_a, 'stub', 'v1')
        valid_b = mod_b._validate_assessment(raw, cfg_b, 'stub', 'v1')
        self.assertIsNotNone(valid_a)
        self.assertIsNotNone(valid_b)
        job = {'agentic_job_id': 'silence-001', 'job_type': 'code_review', 'status': 'SUCCESS'}
        record_a = mod_a._build_job_assessment(job, valid_a, raw, cfg_a, 'stub', 'v1')
        record_b = mod_b._build_job_assessment(job, valid_b, raw, cfg_b, 'stub', 'v1')
        self.assertIsNotNone(record_a)
        self.assertIsNotNone(record_b)
        for key in (
            'ts', 'job_started_at', 'job_ended_at',
            'observation_window_start', 'observation_window_end',
        ):
            record_a.pop(key, None)
            record_b.pop(key, None)
        self.assertEqual(record_a, record_b)

    # -- 5. D-12 is a no-op ----------------------------------------------------

    def test_hours_bound_still_gates_a_priced_revenue_record(self):
        mod = self._load(
            boundaries={'valuation': 'revenue_card_valuation_fixture'},
            revenue_card={'hospitality-booking-agent': {'grossPerJob': 250.0}},
            revenue_card_key='hospitality-booking-agent',
        )
        cfg = mod._llm_evaluation_config()
        got = mod._validate_assessment(
            self._raw(estimated_hours_saved=-1.0), cfg, 'stub', 'v1')
        self.assertIsNone(got, 'an out-of-bounds hours value must still abstain')

    def test_priced_revenue_record_retains_evaluator_hours_and_rate(self):
        mod = self._load(
            boundaries={'valuation': 'revenue_card_valuation_fixture'},
            revenue_card={'hospitality-booking-agent': {'grossPerJob': 250.0}},
            revenue_card_key='hospitality-booking-agent',
        )
        cfg = mod._llm_evaluation_config()
        raw = self._raw(estimated_hours_saved=3.0, assumed_loaded_rate=90.0)
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        self.assertEqual(250.0, validated['estimated_value'])
        self.assertEqual(3.0, validated['assumptions']['estimated_hours_saved'])
        self.assertEqual(90.0, validated['assumptions']['assumed_loaded_rate'])


# ---------------------------------------------------------------------------
# Task 2 -- DelegationTests
# ---------------------------------------------------------------------------

class DelegationTests(_ValuationBoundaryTestCase):
    """D-04/ROI-06 -- pointing an install at the revenue registrant no
    longer strips value from ordinary sessions; an unreadable card entry
    still abstains outright rather than delegating; and abstention still
    means abstention when the built-in cannot be resolved. One method per
    numbered case of 54-02-PLAN.md Task 2's own action section."""

    # -- 1. The four delegation cases: round(hours * rate, 2), no
    #    economic_mechanism key on the returned dict --------------------

    def test_no_revenue_card_configured_delegates(self):
        mod = self._load(boundaries={'valuation': 'revenue_card_valuation_fixture'})
        cfg = mod._llm_evaluation_config()
        got = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertEqual(round(2.5 * 150.0, 2), got['estimated_value'])
        self.assertNotIn('economic_mechanism', got)

    def test_empty_revenue_card_delegates(self):
        mod = self._load(
            boundaries={'valuation': 'revenue_card_valuation_fixture'},
            revenue_card={},
        )
        cfg = mod._llm_evaluation_config()
        got = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertEqual(round(2.5 * 150.0, 2), got['estimated_value'])
        self.assertNotIn('economic_mechanism', got)

    def test_revenue_card_present_no_key_configured_delegates(self):
        mod = self._load(
            boundaries={'valuation': 'revenue_card_valuation_fixture'},
            revenue_card={'hospitality-booking-agent': {'grossPerJob': 250.0}},
        )
        cfg = mod._llm_evaluation_config()
        got = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertEqual(round(2.5 * 150.0, 2), got['estimated_value'])
        self.assertNotIn('economic_mechanism', got)

    def test_key_naming_an_absent_entry_delegates(self):
        mod = self._load(
            boundaries={'valuation': 'revenue_card_valuation_fixture'},
            revenue_card={'hospitality-booking-agent': {'grossPerJob': 250.0}},
            revenue_card_key='car-rental-agent',
        )
        cfg = mod._llm_evaluation_config()
        got = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertEqual(round(2.5 * 150.0, 2), got['estimated_value'])
        self.assertNotIn('economic_mechanism', got)

    # -- 2. The malformed-entry case abstains, it does not delegate ------

    def test_malformed_entry_abstains_rather_than_delegating(self):
        mod = self._load(
            boundaries={'valuation': 'revenue_card_valuation_fixture'},
            revenue_card={'hospitality-booking-agent': {'grossPerJob': 'not-a-number'}},
            revenue_card_key='hospitality-booking-agent',
        )
        cfg = mod._llm_evaluation_config()
        got = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNone(got)

    # -- 3. A revenue-shaped job on the same config still prices ---------

    def test_revenue_shaped_job_on_same_install_still_prices_from_the_card(self):
        mod = self._load(
            boundaries={'valuation': 'revenue_card_valuation_fixture'},
            revenue_card={'hospitality-booking-agent': {'grossPerJob': 250.0}},
            revenue_card_key='hospitality-booking-agent',
        )
        cfg = mod._llm_evaluation_config()
        got = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertEqual(250.0, got['estimated_value'])
        self.assertEqual('incremental_revenue', got['economic_mechanism'])

    # -- 4. Standalone valuation.py (no classifier => no hours_times_rate) --

    def test_standalone_valuation_module_delegation_returns_none(self):
        val = _load_valuation()
        got = val._revenue_card_valuation_fixture({'currency': 'USD'}, {})
        self.assertIsNone(got)

    def test_registrant_never_delegates_to_itself(self):
        val = _load_valuation()
        # Simulate an operator pointing hours_times_rate's own registered
        # name at THIS very fixture -- last-registration-wins would
        # otherwise make the delegation call resolve right back to itself,
        # recursing until the interpreter's stack limit.
        val.register(
            'hours_times_rate', val._revenue_card_valuation_fixture, '1',
            evidence_class='CUSTOMER_CONFIGURED',
        )
        got = val._revenue_card_valuation_fixture({'currency': 'USD'}, {})
        self.assertIsNone(got)

    # -- 5. Whole-dict equality against the default install --------------

    def test_whole_dict_equality_against_default_install(self):
        mod_revenue = self._load(boundaries={'valuation': 'revenue_card_valuation_fixture'})
        mod_default = self._load(boundaries=None)
        raw = self._raw(economic_mechanism='labor_substitution')
        cfg_revenue = mod_revenue._llm_evaluation_config()
        cfg_default = mod_default._llm_evaluation_config()
        valid_revenue = mod_revenue._validate_assessment(raw, cfg_revenue, 'stub', 'v1')
        valid_default = mod_default._validate_assessment(raw, cfg_default, 'stub', 'v1')
        self.assertIsNotNone(valid_revenue)
        self.assertIsNotNone(valid_default)
        job = {'agentic_job_id': 'delegation-identity-001', 'job_type': 'code_review',
               'status': 'SUCCESS'}
        record_revenue = mod_revenue._build_job_assessment(
            job, valid_revenue, raw, cfg_revenue, 'stub', 'v1')
        record_default = mod_default._build_job_assessment(
            job, valid_default, raw, cfg_default, 'stub', 'v1')
        self.assertIsNotNone(record_revenue)
        self.assertIsNotNone(record_default)
        for key in (
            'ts', 'job_started_at', 'job_ended_at',
            'observation_window_start', 'observation_window_end',
        ):
            record_revenue.pop(key, None)
            record_default.pop(key, None)
        self.assertEqual(record_revenue, record_default)
