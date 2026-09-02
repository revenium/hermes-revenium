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
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._compat_helpers import build_shim, build_state_db, run_script, SCRIPTS_DIR

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
        # Phase 54 Task 3 (D-07): HERMES_HOME must be pinned to this test's
        # OWN tmp directory, not left to default to the real host's
        # ~/.hermes -- _revenue_profile_attribution_certain reads
        # HERMES_HOME/profiles LIVE, and a dev host that has ever run a
        # multiplexed install (this repo's own test/sandbox hosts do) has a
        # real profiles/ directory with real subdirectories sitting there.
        # Without this override every test in this module that reaches a
        # declared-and-accepted revenue mechanism would silently pick up
        # that unrelated host state and fail closed for a reason that has
        # nothing to do with what the test is proving. self.tmp has no
        # profiles/ subdirectory unless a test explicitly creates one
        # (see ProfileAttributionFenceTests), so this default keeps every
        # OTHER test's host correctly classified as NOT multiplexed.
        return _load_classifier({
            'REVENIUM_CONFIG_FILE': str(self.config_path),
            'HERMES_HOME': self.tmp,
        })


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


# ---------------------------------------------------------------------------
# Task 2 -- AttributionCouplingTests
# ---------------------------------------------------------------------------
#
# D-09/D-10/D-08, ROI-07. The registrant's OWN return dict is what these
# tests inspect for attribution_fraction/attribution_basis -- the caller
# (classifier.py's _validate_assessment) does not yet copy that pair onto
# its own frozen return dict or re-check it; that threading and the
# hostile-registrant re-check both land in 54-04 (see 54-03-PLAN.md Task 3's
# own instruction and the "for the caller to re-check in 54-04" key_link).
# `estimated_value` and `basis`, by contrast, DO already thread all the way
# through _validate_assessment and _build_job_assessment -- see D-08's own
# threading, added by this same task, in classifier.py.

def _serialized_len(s: str) -> int:
    """Same SERIALIZED-BYTES measurement _clamp_text/_clamp_assessment_text
    use internally (json.dumps(..., ensure_ascii=True), minus the two
    surrounding quote bytes) -- duplicated here rather than imported, per
    this module's own no-shared-code-with-the-producer convention."""
    return len(json.dumps(s, ensure_ascii=True).encode('utf-8')) - 2


class AttributionCouplingTests(_ValuationBoundaryTestCase):
    """D-09/D-10 (ROI-07): the card may carry a gross AND a fraction; the
    skill multiplies; only the product ever leaves. D-08: the producing
    boundary authors the `basis` that explains the number it derived."""

    _DISTINCTIVE_GROSS = 4321.0

    def _entry(self, gross=None, fraction=None, basis=None):
        entry = {'grossPerJob': self._DISTINCTIVE_GROSS if gross is None else gross}
        if fraction is not None:
            entry['attributionFraction'] = fraction
        if basis is not None:
            entry['attributionBasis'] = basis
        return entry

    # -- 1. The product, not the gross ---------------------------------------

    def test_product_not_gross_reaches_the_record(self):
        val = _load_valuation()
        derived = val._revenue_card_valuation_fixture(
            {'currency': 'USD'},
            {'revenueCard': {'k': self._entry(
                fraction=0.15, basis='loyalty capture rate, Q3 pricing review')},
             'revenueCardKey': 'k'},
        )
        self.assertIsNotNone(derived)
        self.assertEqual(648.15, derived['estimated_value'])
        self.assertEqual(0.15, derived['attribution_fraction'])
        serialized = json.dumps(derived)
        self.assertNotIn('4321', serialized, 'the gross literal must never appear')

        # estimated_value threads all the way through the real caller --
        # this half does NOT require the registrant's return dict directly.
        mod = self._load(
            boundaries={'valuation': 'revenue_card_valuation_fixture'},
            revenue_card={'hospitality-booking-agent': self._entry(
                fraction=0.15, basis='loyalty capture rate, Q3 pricing review')},
            revenue_card_key='hospitality-booking-agent',
        )
        cfg = mod._llm_evaluation_config()
        raw = self._raw()
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        self.assertEqual(648.15, validated['estimated_value'])
        self.assertNotIn('4321', json.dumps(validated))

        valid_job = {'agentic_job_id': 'attribution-proof-001',
                     'job_type': 'booking_completion', 'status': 'SUCCESS'}
        record = mod._build_job_assessment(valid_job, validated, raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(record)
        self.assertEqual(648.15, record['estimated_value'])
        self.assertNotIn('4321', json.dumps(record))

    # -- 2. Endpoints ---------------------------------------------------------

    def test_endpoints_zero_and_one_both_legal(self):
        val = _load_valuation()
        zero = val._revenue_card_valuation_fixture(
            {'currency': 'USD'},
            {'revenueCard': {'k': self._entry(fraction=0.0, basis='floor case')},
             'revenueCardKey': 'k'},
        )
        self.assertIsNotNone(zero)
        self.assertEqual(0.0, zero['estimated_value'])
        self.assertEqual(0.0, zero['attribution_fraction'])

        one = val._revenue_card_valuation_fixture(
            {'currency': 'USD'},
            {'revenueCard': {'k': self._entry(fraction=1.0, basis='ceiling case')},
             'revenueCardKey': 'k'},
        )
        self.assertIsNotNone(one)
        self.assertEqual(self._DISTINCTIVE_GROSS, one['estimated_value'])
        self.assertEqual(1.0, one['attribution_fraction'])

    # -- 3. The rejection table for the fraction -------------------------------

    def _fraction_rejection_table(self):
        return [
            ('negative', -0.01),
            ('above_one', 1.01),
            ('nan', float('nan')),
            ('inf', float('inf')),
            ('neg_inf', float('-inf')),
            ('boolean_true', True),
            ('boolean_false', False),
            ('non_numeric_string', '0.5'),
            ('none_explicit', None),
        ]

    def test_fraction_rejection_table(self):
        rows = self._fraction_rejection_table()
        self.assertGreaterEqual(len(rows), 8)
        val = _load_valuation()
        for label, fraction in rows:
            with self.subTest(label):
                config = {'revenueCard': {'k': self._entry(
                    fraction=fraction, basis='some basis')},
                    'revenueCardKey': 'k'}
                got = val._revenue_card_valuation_fixture({'currency': 'USD'}, config)
                self.assertIsNone(got, f'{label} must abstain')

    # -- 4. Travel-as-a-set, both directions -----------------------------------

    def test_fraction_with_no_basis_abstains(self):
        val = _load_valuation()
        for bad_basis in (None, '', '   ', 42, ['not', 'a', 'string']):
            with self.subTest(bad_basis=bad_basis):
                entry = {'grossPerJob': self._DISTINCTIVE_GROSS,
                         'attributionFraction': 0.5}
                if bad_basis is not None:
                    entry['attributionBasis'] = bad_basis
                got = val._revenue_card_valuation_fixture(
                    {'currency': 'USD'},
                    {'revenueCard': {'k': entry}, 'revenueCardKey': 'k'},
                )
                self.assertIsNone(got)

    def test_basis_with_no_fraction_abstains(self):
        val = _load_valuation()
        entry = {'grossPerJob': self._DISTINCTIVE_GROSS,
                 'attributionBasis': 'a basis with nothing to attribute'}
        got = val._revenue_card_valuation_fixture(
            {'currency': 'USD'},
            {'revenueCard': {'k': entry}, 'revenueCardKey': 'k'},
        )
        self.assertIsNone(got)

    def test_neither_key_prices_plain_gross_with_no_attribution_keys(self):
        val = _load_valuation()
        got = val._revenue_card_valuation_fixture(
            {'currency': 'USD'},
            {'revenueCard': {'k': {'grossPerJob': self._DISTINCTIVE_GROSS}},
             'revenueCardKey': 'k'},
        )
        self.assertIsNotNone(got)
        self.assertEqual(self._DISTINCTIVE_GROSS, got['estimated_value'])
        self.assertNotIn('attribution_fraction', got)
        self.assertNotIn('attribution_basis', got)

    # -- 5. Coupling: the fraction and the amount cannot disagree -------------

    def test_coupling_across_three_pairs(self):
        val = _load_valuation()
        for gross, fraction in ((1000.0, 0.25), (77.77, 0.6), (999999.99, 0.01)):
            with self.subTest(gross=gross, fraction=fraction):
                got = val._revenue_card_valuation_fixture(
                    {'currency': 'USD'},
                    {'revenueCard': {'k': {
                        'grossPerJob': gross,
                        'attributionFraction': fraction,
                        'attributionBasis': 'coupling proof',
                    }}, 'revenueCardKey': 'k'},
                )
                self.assertIsNotNone(got)
                self.assertEqual(round(gross * fraction, 2), got['estimated_value'])
                self.assertEqual(fraction, got['attribution_fraction'])

    # -- 6. The authored basis --------------------------------------------------

    def test_authored_basis_reaches_validate_assessment_and_the_record(self):
        mod = self._load(
            boundaries={'valuation': 'revenue_card_valuation_fixture'},
            revenue_card={'hospitality-booking-agent': self._entry(
                fraction=0.15, basis='loyalty capture rate, Q3 pricing review')},
            revenue_card_key='hospitality-booking-agent',
        )
        cfg = mod._llm_evaluation_config()
        raw = self._raw(basis='the evaluator said something else entirely')
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        self.assertIn('attribution', validated['basis'])
        self.assertIn('0.15', validated['basis'])
        self.assertNotIn('evaluator said something else', validated['basis'])
        self.assertLessEqual(_serialized_len(validated['basis']), 200)
        self.assertNotIn('4321', validated['basis'])

        job = {'agentic_job_id': 'basis-proof-001', 'job_type': 'booking_completion',
               'status': 'SUCCESS'}
        record = mod._build_job_assessment(job, validated, raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(record)
        self.assertEqual(validated['basis'], record['basis'])
        self.assertLessEqual(_serialized_len(record['basis']), 200)

    def test_authored_basis_bound_across_a_wide_fraction_sample(self):
        val = _load_valuation()
        for fraction in (0.0, 1.0, 0.123456789012345, 1e-10, 0.999999999999999):
            with self.subTest(fraction=fraction):
                got = val._revenue_card_valuation_fixture(
                    {'currency': 'USD'},
                    {'revenueCard': {'k': {
                        'grossPerJob': self._DISTINCTIVE_GROSS,
                        'attributionFraction': fraction,
                        'attributionBasis': 'bound proof',
                    }}, 'revenueCardKey': 'k'},
                )
                self.assertIsNotNone(got)
                self.assertLessEqual(_serialized_len(got['basis']), 200)
                self.assertNotIn('4321', got['basis'])

    def test_delegated_call_and_default_install_both_keep_evaluators_basis(self):
        raw = self._raw(basis='the evaluator wrote this basis')

        # Delegated: revenue registrant configured but nothing revenue-
        # shaped to price -- falls through to hours_times_rate, which
        # never returns a basis of its own.
        mod_delegated = self._load(
            boundaries={'valuation': 'revenue_card_valuation_fixture'})
        cfg_delegated = mod_delegated._llm_evaluation_config()
        validated_delegated = mod_delegated._validate_assessment(
            raw, cfg_delegated, 'stub', 'v1')
        self.assertIsNotNone(validated_delegated)
        self.assertEqual(
            mod_delegated._clamp_assessment_text(raw.get('basis'), 200),
            validated_delegated['basis'],
        )

        # Default install: no boundaries object at all.
        mod_default = self._load(boundaries=None)
        cfg_default = mod_default._llm_evaluation_config()
        validated_default = mod_default._validate_assessment(raw, cfg_default, 'stub', 'v1')
        self.assertIsNotNone(validated_default)
        self.assertEqual(validated_delegated['basis'], validated_default['basis'])
        self.assertEqual(raw['basis'], validated_default['basis'])

    # -- 7. The caller's own rejection table (54-04 Task 1) -------------------
    # The rows above all drive the WELL-BEHAVED shipped
    # `revenue_card_valuation_fixture`, which enforces every one of these
    # rules itself before ever returning a key -- so none of them can prove
    # the CALLER (`_validate_assessment`) re-checks anything. This table
    # registers a THROWAWAY registrant (the same shape
    # HostileRegistrantDistrustTests uses) that returns an already-malformed
    # pair directly, proving the caller's own re-check catches what a
    # hostile registrant's output would otherwise ship unchecked.

    def _register_throwaway(self, fn, economic_mechanisms=None):
        import valuation as val  # type: ignore -- shared, sys.path-resolved
        name = f'p54_attribution_caller_check_{id(fn)}'
        val.register(name, fn, '1', evidence_class='CUSTOMER_CONFIGURED',
                     economic_mechanisms=economic_mechanisms)
        self.addCleanup(val._REGISTRY._entries.pop, name, None)
        self.addCleanup(val._MECHANISM_DECLARATIONS.pop, name, None)
        return name

    def test_caller_rejects_a_non_string_empty_or_whitespace_basis(self):
        for label, bad_basis in (
            ('non_string', 12345), ('empty', ''), ('whitespace', '   '),
        ):
            with self.subTest(label):
                name = self._register_throwaway(
                    lambda a, c, _b=bad_basis: {
                        'estimated_value': 42.0, 'currency': a.get('currency'),
                        'economic_mechanism': 'incremental_revenue',
                        'attribution_fraction': 0.5, 'attribution_basis': _b,
                    },
                    economic_mechanisms={'incremental_revenue'},
                )
                mod = self._load(boundaries={'valuation': name})
                cfg = mod._llm_evaluation_config()
                validated = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
                self.assertIsNotNone(validated)
                self.assertEqual(42.0, validated['estimated_value'])
                self.assertNotIn('attribution_fraction', validated)
                self.assertNotIn('attribution_basis', validated)

    def test_caller_clamps_rather_than_rejects_an_overlong_basis(self):
        huge = 'y' * 10_000
        name = self._register_throwaway(
            lambda a, c: {
                'estimated_value': 42.0, 'currency': a.get('currency'),
                'economic_mechanism': 'incremental_revenue',
                'attribution_fraction': 0.5, 'attribution_basis': huge,
            },
            economic_mechanisms={'incremental_revenue'},
        )
        mod = self._load(boundaries={'valuation': name})
        cfg = mod._llm_evaluation_config()
        validated = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        self.assertEqual(0.5, validated['attribution_fraction'])
        self.assertIn('attribution_basis', validated)
        self.assertLessEqual(_serialized_len(validated['attribution_basis']), 500)

    def test_caller_discards_the_pair_when_the_mechanism_is_not_declared(self):
        name = self._register_throwaway(
            lambda a, c: {
                'estimated_value': 42.0, 'currency': a.get('currency'),
                'attribution_fraction': 0.5, 'attribution_basis': 'undeclared claim',
            },
            economic_mechanisms=None,
        )
        mod = self._load(boundaries={'valuation': name})
        cfg = mod._llm_evaluation_config()
        validated = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        self.assertEqual(42.0, validated['estimated_value'])
        self.assertNotIn('attribution_fraction', validated)
        self.assertNotIn('attribution_basis', validated)


# ---------------------------------------------------------------------------
# Task 1 -- RevenuePathFidelityTests: the relocated coverage
# ---------------------------------------------------------------------------
# tests/test_phase38_reporter_path.py::SidecarFixtureFidelityTests'
# _NON_DEFAULT_ARM_KEYS exempts attribution_fraction/attribution_basis from
# its hand-authored, DEFAULT-arm _sidecar_record() fixture -- correctly,
# since that arm never carries them. This class is where that exemption's
# own comment says the second producer's fidelity coverage lives: it drives
# the REAL _build_job_assessment on a CONFIGURED-REVENUE arm and proves both
# keys ARE produced there, are absent from an abstained record and from a
# default install's record, and are forwardable end to end.

def _extract_forwarder_record_keys(script_text):
    """Duplicated (not imported) from
    tests/test_phase38_reporter_path.py::_extract_forwarder_record_keys --
    this module's own no-shared-code-with-the-producer-or-with-each-other's-
    test-fixtures convention. See that function's docstring for the
    LOWER BOUND caveat (the value_low/base/high loop-variable-keyed
    forwarder is invisible to this literal-argument ast walk)."""
    anchor = 'outcome_metadata=$('
    start_marker = script_text.find(anchor)
    if start_marker == -1:
        return None
    heredoc_start = script_text.find("<<'PY'", start_marker)
    if heredoc_start == -1:
        return None
    body_start = script_text.find('\n', heredoc_start) + 1
    body_end = script_text.find('\nPY\n', body_start)
    if body_end == -1:
        return None
    body = script_text[body_start:body_end]
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return None
    keys = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'get'
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == 'record'
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.append(node.args[0].value)
    return keys


class RevenuePathFidelityTests(_ValuationBoundaryTestCase):
    """The relocated fidelity coverage
    SidecarFixtureFidelityTests'_NON_DEFAULT_ARM_KEYS comment names by
    path (see this plan's own <validation_deviation>)."""

    def _revenue_record(self, fraction=0.2, basis='q3 loyalty capture rate'):
        mod = self._load(
            boundaries={'valuation': 'revenue_card_valuation_fixture'},
            revenue_card={'hospitality-booking-agent': {
                'grossPerJob': 500.0,
                'attributionFraction': fraction,
                'attributionBasis': basis,
            }},
            revenue_card_key='hospitality-booking-agent',
        )
        cfg = mod._llm_evaluation_config()
        raw = self._raw()
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        job = {'agentic_job_id': 'revenue-fidelity-001',
               'job_type': 'booking_completion', 'status': 'SUCCESS'}
        record = mod._build_job_assessment(job, validated, raw, cfg, 'stub', 'v1')
        return mod, cfg, raw, validated, record

    def test_configured_revenue_arm_produces_both_attribution_keys(self):
        _, _, _, validated, record = self._revenue_record()
        self.assertIsNotNone(validated)
        self.assertEqual(0.2, validated['attribution_fraction'])
        self.assertEqual('q3 loyalty capture rate', validated['attribution_basis'])
        self.assertIsNotNone(record)
        self.assertEqual(0.2, record['attribution_fraction'])
        self.assertEqual('q3 loyalty capture rate', record['attribution_basis'])

    def test_abstained_record_carries_neither_key(self):
        mod = self._load(boundaries=None)
        job = {'agentic_job_id': 'abstain-fidelity-001',
               'job_type': 'code_review', 'status': 'FAILED'}
        record = mod._build_job_assessment(
            job, None, {}, {}, 'stub', 'v1', abstention_reason='no_evaluation')
        self.assertIsNotNone(record)
        self.assertNotIn('attribution_fraction', record)
        self.assertNotIn('attribution_basis', record)

    def test_default_install_record_carries_neither_key(self):
        mod = self._load(boundaries=None)
        cfg = mod._llm_evaluation_config()
        raw = self._raw()
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        self.assertNotIn('attribution_fraction', validated)
        self.assertNotIn('attribution_basis', validated)
        job = {'agentic_job_id': 'default-fidelity-001',
               'job_type': 'code_review', 'status': 'SUCCESS'}
        record = mod._build_job_assessment(job, validated, raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(record)
        self.assertNotIn('attribution_fraction', record)
        self.assertNotIn('attribution_basis', record)

    def test_every_forwardable_key_this_arm_can_produce_is_present(self):
        """Mirrors test_phase47_end_to_end.py's own
        test_produced_sidecar_carries_every_literally_keyed_forwarder_key
        finding for the naked-LLM path: on the configured-revenue arm, the
        empirical exemption set is EMPTY -- every literally-keyed forwarder
        key, attribution_fraction/attribution_basis included, is actually
        present on this arm's produced record."""
        script_text = HERMES_REPORT_SH.read_text()
        keys = _extract_forwarder_record_keys(script_text)
        self.assertIsNotNone(
            keys,
            'could not extract record.get(...) keys from hermes-report.sh '
            '-- the --metadata forwarder heredoc moved and '
            '_extract_forwarder_record_keys needs updating',
        )
        self.assertTrue(keys, 'extracted zero forwarder keys')
        _, _, _, _, record = self._revenue_record()
        self.assertIsNotNone(record)
        missing = set(keys) - set(record.keys())
        self.assertEqual(
            missing, set(),
            f'the configured-revenue arm is missing forwardable keys: '
            f'{missing} -- record={record!r}',
        )

    def test_attribution_pair_forwards_through_the_real_metadata_heredoc(self):
        _, _, _, _, record = self._revenue_record()
        self.assertIsNotNone(record)
        script_text = HERMES_REPORT_SH.read_text()
        body = _extract_outcome_metadata_heredoc(script_text)
        self.assertIsNotNone(body)
        env = {**os.environ, **_assessment_env(assessment=record)}
        result = _run_forwarder(body, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        self.assertEqual(1, len(lines))
        meta = json.loads(lines[0])
        self.assertEqual(0.2, meta.get('attribution_fraction'))
        self.assertEqual('q3 loyalty capture rate', meta.get('attribution_basis'))

    def test_representation_parity_with_the_cli_path(self):
        """The record's two keys are byte-comparable with the pair
        correct-assessment.sh writes for the same values -- both producers
        run the same shape of validation (finite float in [0.0, 1.0]; a
        non-empty basis clamped to 500 serialized bytes with '|'/'\\n'/'\\r'
        replaced by a space) even though the two implementations are
        deliberately NOT shared code (CLAUDE.md's duplication-over-coupling
        rule for this module family)."""
        basis_with_pipe = 'q3 | loyalty\ncapture\rrate'
        _, _, _, validated, record = self._revenue_record(
            fraction=0.4, basis=basis_with_pipe)
        # The CLI path's own _clamp_reason: strip, replace '|'/'\n'/'\r'
        # with a space, then clamp to 500 serialized bytes.
        cli_basis = basis_with_pipe.strip()
        for bad in ('|', '\n', '\r'):
            cli_basis = cli_basis.replace(bad, ' ')
        self.assertEqual(
            json.dumps(cli_basis), json.dumps(record['attribution_basis']),
            'the configured path and the CLI path must serialize the same '
            'attribution_basis text identically',
        )
        self.assertEqual(
            json.dumps(float(0.4)), json.dumps(record['attribution_fraction']))


def _extract_value_omit_family(script_text):
    """Extract `_VALUE_OMIT_FAMILY`'s member list from the live
    hermes-report.sh text rather than retyping it, so a future edit to that
    tuple cannot silently desync from this plan's intent. Duplicated
    (not imported) from tests/test_phase46_metadata_envelope.py's own
    helper of the same name, per this module's own no-shared-code-between-
    test-fixtures convention."""
    import re
    match = re.search(r'_VALUE_OMIT_FAMILY\s*=\s*\(([^)]*)\)', script_text, re.DOTALL)
    if not match:
        return None
    return re.findall(r"'([^']*)'", match.group(1))


# ---------------------------------------------------------------------------
# Task 1 (Plan 06) -- AttributionSheddingTests (T-54-05, ROI-08)
# ---------------------------------------------------------------------------

class AttributionSheddingTests(_ValuationBoundaryTestCase):
    """T-54-05: a not-reportable job_assessment record sheds
    attribution_fraction/attribution_basis TOGETHER with the value they
    describe. Proven by driving the REAL hermes-report.sh outcome stage end
    to end -- not the extracted --metadata heredoc alone (that heredoc runs
    downstream of the branch under test and would only prove the forwarder
    has no `kind` guard, not that the reportability gate sheds the pair).

    Duplicates TestPhase38ReporterPath._run_one_outcome / _metadata_value
    from tests/test_phase38_reporter_path.py into this module rather than
    importing it, per this repo's fixtures-do-not-share-code-with-each-
    other-or-with-the-producer convention (stated explicitly by that
    module's own docstring and by test_phase46_metadata_envelope.py's own
    duplication of the same shape)."""

    def _run_one_outcome(self, sid, job_id, sidecar):
        """Drive hermes-report.sh for one job arc; return the parsed
        `jobs outcome` argv. Narrowed to this class's own needs relative to
        test_phase38's copy: always exactly one sidecar record, always a
        SUCCESS job marker, no marker-side `assessment` key."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-p54-06-outcome-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            assessments_dir = os.path.join(state_dir, 'job-assessments')
            os.makedirs(markers_dir, mode=0o700)
            os.makedirs(assessments_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')
            jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir, 'meter.log')
            jobs_log = os.path.join(tmpdir, 'jobs.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            shim = os.path.join(bin_dir, 'revenium')

            build_state_db(state_db, [{
                'id': sid,
                'model': 'claude-sonnet-4-6',
                'source': 'test',
                'input_tokens': 100,
                'output_tokens': 50,
                'cache_read': 0,
                'cache_write': 0,
                'reasoning': 0,
                'estimated_cost': '0',
                'api_calls': 1,
                'started_at': 1715514000.0,
                'ended_at': 1715514000.0,
                'billing_provider': 'anthropic',
            }])

            # Pre-seed created line so the outcome stage does not defer.
            os.makedirs(os.path.dirname(jobs_ledger), exist_ok=True)
            with open(jobs_ledger, 'w') as f:
                f.write(f'JOB:{job_id}:created:1715516001.000\n')

            task_marker = {
                'muid': f'{job_id}-task', 'ts': 1715516000.5, 'sid': sid,
                'task_type': 'code_review', 'operation_type': 'CHAT',
            }
            job_marker = {
                'kind': 'job', 'ts': 1715516002.0, 'sid': sid,
                'agentic_job_id': job_id,
                'job_name': 'Phase 54 Plan 06 Attribution Shedding Test Job',
                'job_type': 'booking_completion', 'status': 'SUCCESS',
            }
            with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
                f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
                f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

            # Phase 42 (D-10): the sidecar is the ONLY value/provenance
            # source the outcome stage reads.
            with open(os.path.join(assessments_dir, f'{job_id}.jsonl'), 'w') as f:
                f.write(json.dumps(sidecar, separators=(',', ':')) + '\n')

            build_shim(shim, outcome_value_capable=True)

            base_env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'INVOCATIONS_LOG': inv_log,
                'METER_LOG': meter_log,
                'JOBS_LOG': jobs_log,
                'TZ': 'UTC',
                'REVENIUM_ORGANIZATION_NAME': '',
            }

            rc, _ignored, output = run_script(
                SCRIPTS_DIR / 'hermes-report.sh', base_env, inv_log
            )
            self.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {output}')

            outcome_inv = []
            if os.path.exists(jobs_log):
                with open(jobs_log) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if not line:
                            continue
                        argv = shlex.split(line)
                        if len(argv) >= 2 and argv[0] == 'jobs' and argv[1] == 'outcome':
                            outcome_inv.append(argv)

            self.assertEqual(
                len(outcome_inv), 1,
                f'expected exactly 1 "jobs outcome" invocation, got {len(outcome_inv)}: '
                f'{outcome_inv!r}\nOutput: {output}'
            )
            return outcome_inv[0]
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @staticmethod
    def _metadata_value(argv):
        for i, tok in enumerate(argv):
            if tok == '--metadata' and i + 1 < len(argv):
                return argv[i + 1]
        return None

    def _revenue_sidecar(self, job_id, reportability_status, evidence_class,
                          fraction=0.2, basis='q3 loyalty capture rate'):
        """A job_assessment sidecar record shaped like
        tests/test_phase38_reporter_path.py::_sidecar_record, with the
        evidence_class/reportability_status pair overridden per case and
        the Phase 54 attribution pair always present -- the shape
        _build_job_assessment's success path actually produces for a
        configured-revenue arm (RevenuePathFidelityTests proves the
        producer side; this class proves the reporter's consumption of it)."""
        return {
            'kind': 'job_assessment',
            'ts': 1715516002.5,
            'agentic_job_id': job_id,
            'assessment_id': f'{job_id}:0',
            'assessment_schema_version': 1,
            'taxonomy_version': 1,
            'prompt_version': 1,
            'policy_version': 1,
            'model': 'unknown',
            'inference_provider': '',
            'inference_address_class': 'unset',
            'value_low': 340.0,
            'value_base': 400.0,
            'value_high': 460.0,
            'bounds_source': 'derived',
            'currency': 'USD',
            'estimated_value': 400.0,
            'evaluator': 'llm',
            'evaluator_version': 'v1',
            'confidence': 0.5,
            'evidence_class': evidence_class,
            'evidence_class_authority': 'boundary:revenue_card_valuation_fixture',
            'assumptions': {
                'estimated_hours_saved': 2.5,
                'assumed_loaded_rate': 150.0,
            },
            'economic_mechanism': 'incremental_revenue',
            'net_value': 400.0,
            'supplied_costs': {},
            'cost_coverage': {
                'included': [], 'known_zero': [], 'unknown': [],
                'excluded': ['metered_ai_cost'],
            },
            'double_counting_group': job_id,
            'reportability_status': reportability_status,
            'attribution_fraction': fraction,
            'attribution_basis': basis,
        }

    def test_candidate_revenue_record_sheds_attribution_pair_with_the_value(self):
        """Behavior 1: reportability_status="candidate" -- the reportability
        gate's own refusal branch -- sheds both attribution keys AND every
        other value-family key."""
        record = self._revenue_sidecar(
            'p54-06-cand-001', 'candidate', 'CUSTOMER_CONFIGURED')
        argv = self._run_one_outcome('p54-06-sid-cand', 'p54-06-cand-001', record)
        meta = json.loads(self._metadata_value(argv))
        self.assertNotIn('attribution_fraction', meta)
        self.assertNotIn('attribution_basis', meta)
        self.assertNotIn('value_low', meta)
        self.assertNotIn('estimated_value', meta)

    def test_reportable_revenue_record_ships_attribution_pair(self):
        """Behavior 2: reportability_status="reportable" with a permitted
        evidence_class ships both attribution keys unchanged."""
        record = self._revenue_sidecar(
            'p54-06-rep-001', 'reportable', 'CUSTOMER_CONFIGURED')
        argv = self._run_one_outcome('p54-06-sid-rep', 'p54-06-rep-001', record)
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(0.2, meta.get('attribution_fraction'))
        self.assertEqual('q3 loyalty capture rate', meta.get('attribution_basis'))

    def test_evidence_class_refused_record_sheds_attribution_pair(self):
        """Behavior 3: a record refused by the SECOND refusal branch (a
        recognized-but-not-reportable evidence_class, e.g.
        MODEL_ESTIMATED_DEMO) also sheds both keys, regardless of
        reportability_status."""
        record = self._revenue_sidecar(
            'p54-06-mod-001', 'reportable', 'MODEL_ESTIMATED_DEMO')
        argv = self._run_one_outcome('p54-06-sid-mod', 'p54-06-mod-001', record)
        meta = json.loads(self._metadata_value(argv))
        self.assertNotIn('attribution_fraction', meta)
        self.assertNotIn('attribution_basis', meta)

    def test_correction_record_still_ships_attribution_pair_unchanged(self):
        """Behavior 4: a kind:"correction" record carrying the pair still
        ships both, unchanged -- `_reportable` is true by construction for
        a correction, so `_strip_value_family` is never reached on that
        path. Shaped like
        tests/test_phase38_reporter_path.py::_correction_sidecar_record."""
        job_id = 'p54-06-corr-001'
        correction = {
            'kind': 'correction',
            'ts': 1715516010.0,
            'agentic_job_id': job_id,
            'assessment_id': f'{job_id}:1',
            'sequence': 1,
            'assessment_schema_version': 1,
            'prior_value_low': 340.0,
            'prior_value_base': 400.0,
            'prior_value_high': 460.0,
            'prior_currency': 'USD',
            'value_low': 100.0,
            'value_base': 110.0,
            'value_high': 120.0,
            'currency': 'USD',
            'reason': 'operator correction',
            'attribution_fraction': 0.15,
            'attribution_basis': '15% per policy REV-2024-03',
        }
        argv = self._run_one_outcome('p54-06-sid-corr', job_id, correction)
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(0.15, meta.get('attribution_fraction'))
        self.assertEqual('15% per policy REV-2024-03', meta.get('attribution_basis'))

    def test_revenue_configured_install_with_report_estimates_off_is_reachable_and_sheds(self):
        """Behavior 5: establishing reachability by reading, not assuming.
        _resolve_reportability_status's evidence-class gate (classifier.py)
        admits CUSTOMER_CONFIGURED -- the class a configured revenue
        registrant's record carries -- into the resolution step; with no
        registered evidence boundary overriding it and
        experimentalReportEstimates NOT set to True, the inline fallback
        rule resolves REPORTABILITY_CANDIDATE. This drives that exact case
        through the REAL classifier (not a hand-built record) and confirms
        the resulting record is a `candidate`, THEN feeds that same record
        through the real reporter and confirms the shed."""
        mod = self._load(
            boundaries={'valuation': 'revenue_card_valuation_fixture'},
            revenue_card={'hospitality-booking-agent': {
                'grossPerJob': 500.0,
                'attributionFraction': 0.2,
                'attributionBasis': 'q3 loyalty capture rate',
            }},
            revenue_card_key='hospitality-booking-agent',
        )
        cfg = mod._llm_evaluation_config()
        self.assertIsNot(
            cfg.get('experimentalReportEstimates'), True,
            'test setup invalid: experimentalReportEstimates must be off '
            'for this to exercise the candidate case',
        )
        raw = self._raw()
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        job_id = 'p54-06-driven-001'
        job = {'agentic_job_id': job_id, 'job_type': 'booking_completion',
               'status': 'SUCCESS'}
        record = mod._build_job_assessment(job, validated, raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(record)
        self.assertEqual(
            'CUSTOMER_CONFIGURED', record.get('evidence_class'),
            'test setup invalid: expected the configured-revenue arm to '
            'produce CUSTOMER_CONFIGURED',
        )
        self.assertEqual(
            'candidate', record.get('reportability_status'),
            'the not-reportable revenue case is unreachable under this '
            'configuration -- re-derive the test setup rather than assume',
        )
        self.assertIn('attribution_fraction', record)
        self.assertIn('attribution_basis', record)

        argv = self._run_one_outcome('p54-06-sid-driven', job_id, record)
        meta = json.loads(self._metadata_value(argv))
        self.assertNotIn('attribution_fraction', meta)
        self.assertNotIn('attribution_basis', meta)
        self.assertNotIn('value_low', meta)

    def test_value_omit_family_contains_the_attribution_pair(self):
        """Drift guard: extract `_VALUE_OMIT_FAMILY` from the live script
        text rather than retyping it, so a future edit to that tuple cannot
        silently desync from this plan's intent."""
        script_text = HERMES_REPORT_SH.read_text()
        family = _extract_value_omit_family(script_text)
        self.assertIsNotNone(
            family,
            '_VALUE_OMIT_FAMILY anchor moved in hermes-report.sh -- update '
            'the extraction before trusting this test',
        )
        self.assertIn('attribution_fraction', family)
        self.assertIn('attribution_basis', family)


# ---------------------------------------------------------------------------
# Task 2 -- CeilingSelectionTests (D-08/D-12/D-13)
# ---------------------------------------------------------------------------

class CeilingSelectionTests(_ValuationBoundaryTestCase):
    """D-13: the ceiling is `maxRevenueValue` only when a declared
    operator-only mechanism was accepted for this call AND the configured
    value is finite and positive; otherwise the existing labor ceiling
    (`round(maxHoursSaved * maxLoadedRate, 2)`) applies, byte for byte.
    D-12: the hours/rate bound checks are untouched by any of this. D-08:
    the producer-authored `basis` is gated on the same mechanism
    acceptance the ceiling is."""

    def _register(self, fn, economic_mechanisms=None):
        import valuation as val  # type: ignore -- shared, sys.path-resolved
        name = f'p54_ceiling_{id(fn)}_{id(economic_mechanisms)}'
        val.register(name, fn, '1', evidence_class='CUSTOMER_CONFIGURED',
                     economic_mechanisms=economic_mechanisms)
        self.addCleanup(val._REGISTRY._entries.pop, name, None)
        self.addCleanup(val._MECHANISM_DECLARATIONS.pop, name, None)
        return name

    def _write_full_config(self, boundaries=None, max_revenue_value=None,
                            max_hours_saved=None, max_loaded_rate=None):
        outcome_eval = {}
        if max_revenue_value is not None:
            outcome_eval['maxRevenueValue'] = max_revenue_value
        if max_hours_saved is not None:
            outcome_eval['maxHoursSaved'] = max_hours_saved
        if max_loaded_rate is not None:
            outcome_eval['maxLoadedRate'] = max_loaded_rate
        cfg = {}
        if boundaries is not None:
            cfg['boundaries'] = boundaries
        if outcome_eval:
            cfg['llmOutcomeEvaluation'] = outcome_eval
        self.config_path.write_text(json.dumps(cfg))
        # See _ValuationBoundaryTestCase._load's own comment: HERMES_HOME
        # must be pinned to this test's tmp dir, never left to the real
        # host default, or _revenue_profile_attribution_certain reads
        # whatever unrelated profiles/ directory the host happens to have.
        return _load_classifier({
            'REVENIUM_CONFIG_FILE': str(self.config_path),
            'HERMES_HOME': self.tmp,
        })

    def _declared_registrant(self, estimated_value, basis=None):
        result = {'estimated_value': estimated_value, 'currency': 'USD',
                  'economic_mechanism': 'incremental_revenue'}
        if basis is not None:
            result['basis'] = basis
        return self._register(
            lambda a, c, _r=result: dict(_r),
            economic_mechanisms={'incremental_revenue'},
        )

    # -- 1. maxRevenueValue ceiling: exact acceptance, one cent over abstains

    def test_amount_exactly_at_max_revenue_value_is_accepted(self):
        name = self._declared_registrant(700.00)
        mod = self._write_full_config(
            boundaries={'valuation': name}, max_revenue_value=700)
        cfg = mod._llm_evaluation_config()
        validated = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        self.assertEqual(700.00, validated['estimated_value'])

    def test_one_cent_over_max_revenue_value_abstains(self):
        name = self._declared_registrant(700.01)
        mod = self._write_full_config(
            boundaries={'valuation': name}, max_revenue_value=700)
        cfg = mod._llm_evaluation_config()
        validated = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNone(validated)

    # -- 2. Absent maxRevenueValue: the labor ceiling, exact and one over ----

    def test_amount_exactly_at_labor_ceiling_is_accepted_with_no_max_revenue_value(self):
        # maxHoursSaved=10, maxLoadedRate=200 -> labor ceiling = 2000.00.
        # (maxLoadedRate must stay >= the raw fixture's 150.0 rate, or the
        # upstream hours/rate bound check abstains before the ceiling this
        # test targets is ever reached.)
        name = self._declared_registrant(2000.00)
        mod = self._write_full_config(
            boundaries={'valuation': name},
            max_hours_saved=10, max_loaded_rate=200,
        )
        cfg = mod._llm_evaluation_config()
        validated = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        self.assertEqual(2000.00, validated['estimated_value'])

    def test_one_cent_over_labor_ceiling_abstains_with_no_max_revenue_value(self):
        name = self._declared_registrant(2000.01)
        mod = self._write_full_config(
            boundaries={'valuation': name},
            max_hours_saved=10, max_loaded_rate=200,
        )
        cfg = mod._llm_evaluation_config()
        validated = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNone(validated)

    # -- 3. A malformed maxRevenueValue never widens the labor ceiling ------

    def test_malformed_max_revenue_value_falls_back_to_labor_ceiling(self):
        rows = [
            ('zero', 0), ('negative', -700), ('non_numeric', '700'),
            ('boolean', True), ('nan', float('nan')), ('inf', float('inf')),
        ]
        for label, bad_value in rows:
            with self.subTest(label):
                # 2000.01 exceeds the labor ceiling (2000.00) -- a widened
                # bound would accept it; the labor ceiling must still refuse.
                name = self._declared_registrant(2000.01)
                mod = self._write_full_config(
                    boundaries={'valuation': name},
                    max_revenue_value=bad_value,
                    max_hours_saved=10, max_loaded_rate=200,
                )
                cfg = mod._llm_evaluation_config()
                validated = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
                self.assertIsNone(
                    validated,
                    f'{label}: a malformed maxRevenueValue must not widen '
                    f'the labor ceiling')

    # -- 4. maxRevenueValue is ignored when no mechanism was declared -------

    def test_max_revenue_value_ignored_when_mechanism_not_declared(self):
        # No economic_mechanisms declared at all -- the registrant returns
        # an amount between the (tiny) labor ceiling and the (generous)
        # configured maxRevenueValue. If maxRevenueValue leaked through
        # despite no declared mechanism, this would be accepted; it must
        # abstain against the labor ceiling instead.
        name = self._register(
            lambda a, c: {'estimated_value': 2000.01, 'currency': 'USD'},
            economic_mechanisms=None,
        )
        mod = self._write_full_config(
            boundaries={'valuation': name},
            max_revenue_value=1_000_000,
            max_hours_saved=10, max_loaded_rate=200,
        )
        cfg = mod._llm_evaluation_config()
        validated = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNone(
            validated,
            'distrust rule: maxRevenueValue must never apply to a call '
            'whose mechanism was not declared-and-accepted')

    # -- 5. D-12: the hours/rate gate is untouched on a revenue-configured --
    # install -- already covered end to end by
    # MechanismDeclarationTests.test_hours_bound_still_gates_a_priced_revenue_record
    # and .test_priced_revenue_record_retains_evaluator_hours_and_rate; this
    # is the SAME claim, proven again here with a configured
    # maxRevenueValue in play (a ceiling this large would otherwise mask an
    # hours/rate bound failure if the two gates were ever accidentally
    # merged).

    def test_hours_rate_bound_still_gates_even_with_a_generous_max_revenue_value(self):
        name = self._declared_registrant(50.0)
        mod = self._write_full_config(
            boundaries={'valuation': name}, max_revenue_value=1_000_000)
        cfg = mod._llm_evaluation_config()
        raw = self._raw(estimated_hours_saved=999.0)  # exceeds DEFAULT_MAX_HOURS_SAVED
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNone(
            validated,
            'D-12: the hours/rate bound gate must fire BEFORE the '
            'valuation boundary ever runs, regardless of maxRevenueValue')

    # -- 6. The basis source, across all four combinations ------------------

    def test_basis_switches_source_across_the_four_combinations(self):
        registrant_basis = 'registrant-authored caveat'
        evaluator_basis = 'evaluator-authored caveat'
        raw = self._raw(basis=evaluator_basis)

        # (authored=True, declared=True) -> registrant's basis wins.
        name = self._register(
            lambda a, c: {'estimated_value': 42.0, 'currency': a.get('currency'),
                          'economic_mechanism': 'incremental_revenue',
                          'basis': registrant_basis},
            economic_mechanisms={'incremental_revenue'},
        )
        mod = self._load(boundaries={'valuation': name})
        cfg = mod._llm_evaluation_config()
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        self.assertEqual(registrant_basis, validated['basis'])

        # (authored=True, declared=False) -> evaluator's basis wins; the
        # registrant's own text is discarded along with its mechanism.
        name = self._register(
            lambda a, c: {'estimated_value': 42.0, 'currency': a.get('currency'),
                          'basis': registrant_basis},
            economic_mechanisms=None,
        )
        mod = self._load(boundaries={'valuation': name})
        cfg = mod._llm_evaluation_config()
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        self.assertEqual(evaluator_basis, validated['basis'])

        # (authored=False, declared=True) -> registrant said nothing;
        # evaluator's basis wins even though the mechanism WAS accepted.
        name = self._register(
            lambda a, c: {'estimated_value': 42.0, 'currency': a.get('currency'),
                          'economic_mechanism': 'incremental_revenue'},
            economic_mechanisms={'incremental_revenue'},
        )
        mod = self._load(boundaries={'valuation': name})
        cfg = mod._llm_evaluation_config()
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        self.assertEqual(evaluator_basis, validated['basis'])

        # (authored=False, declared=False) -> evaluator's basis wins, the
        # unmodified default-install shape.
        name = self._register(
            lambda a, c: {'estimated_value': 42.0, 'currency': a.get('currency')},
            economic_mechanisms=None,
        )
        mod = self._load(boundaries={'valuation': name})
        cfg = mod._llm_evaluation_config()
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        self.assertEqual(evaluator_basis, validated['basis'])


# ---------------------------------------------------------------------------
# Task 3 -- HostileRegistrantDistrustTests
# ---------------------------------------------------------------------------
#
# The caller's distrust of registered code, proven against a HOSTILE
# registrant for every field the revenue path adds -- not only against the
# well-behaved shipped `revenue_card_valuation_fixture`. Modelled on
# tests/test_phase45_valuation_boundary.py's BoundReassertionTests (the
# adversarial half of that phase's own boundary tests) and
# tests/test_phase50_declaration_authority.py's `_register_causal_label_
# valuation` throwaway-registration shape.
#
# 54-03 shipped attribution_fraction/attribution_basis threading as a
# VERBATIM, deliberately unchecked pass-through of whatever a resolved
# registrant returns, with NO bounds check and NO travel-as-a-set re-check
# of its own -- a real, then-open gap for a THIRD-PARTY registrant, proven
# with two `@unittest.expectedFailure` cases naming this plan. Phase 54
# Task 1 closes that gap (classifier.py's own D-10 comment carries the
# validation rules); both cases below now pass as ordinary tests, unmarked.

_HOSTILE_THROWAWAY_SEQ = [0]


def _hostile_registrant_name():
    _HOSTILE_THROWAWAY_SEQ[0] += 1
    return f'p54_hostile_{_HOSTILE_THROWAWAY_SEQ[0]}'


class HostileRegistrantDistrustTests(_ValuationBoundaryTestCase):
    """Task 3: the caller's distrust of registered code, adversarially, in
    one table. Each case registers a THROWAWAY implementation (unique name
    per case) into the SHARED bare-imported `valuation` module --
    last-registration-wins is documented, and a leaked registrant would
    let these tests lie to each other -- then drives it through a FRESH
    classifier module per case, never reusing one across subtests."""

    def _register(self, fn, economic_mechanisms=None):
        import valuation as val  # type: ignore -- shared, sys.path-resolved
        name = _hostile_registrant_name()
        val.register(name, fn, '1', evidence_class='CUSTOMER_CONFIGURED',
                     economic_mechanisms=economic_mechanisms)
        self.addCleanup(val._REGISTRY._entries.pop, name, None)
        self.addCleanup(val._MECHANISM_DECLARATIONS.pop, name, None)
        return name

    def _validate(self, name, raw=None):
        mod = self._load(boundaries={'valuation': name})
        cfg = mod._llm_evaluation_config()
        raw = raw if raw is not None else self._raw()
        return mod, cfg, raw, mod._validate_assessment(raw, cfg, 'stub', 'v1')

    # -- 1. Ceiling refusal (mitigates T-54-06; ALREADY real -- no marker) --

    def test_gross_sized_amount_above_ceiling_is_refused(self):
        name = self._register(
            lambda a, c: {'estimated_value': 10_000_000.0, 'currency': a.get('currency')})
        _, _, _, validated = self._validate(name)
        self.assertIsNone(
            validated,
            'distrust rule: a registrant cannot widen the configured ceiling')

    # -- 2. Malformed attribution_fraction discarded, amount still ships ----

    def _malformed_fraction_table(self):
        return [
            ('above_one', 1.5), ('negative', -0.5), ('nan', float('nan')),
            ('inf', float('inf')), ('boolean', True), ('string', '0.5'),
        ]

    def test_malformed_attribution_fraction_is_discarded_amount_still_ships(self):
        # Declares AND returns a legitimate operator-only mechanism, so the
        # caller's mechanism gate accepts it -- this test is specifically
        # about the ATTRIBUTION re-check, not about the mechanism gate
        # rejecting an undeclared one (that is
        # test_undeclared_economic_mechanism_is_discarded, below).
        rows = self._malformed_fraction_table()
        self.assertGreaterEqual(len(rows), 6)
        for label, fraction in rows:
            with self.subTest(label):
                name = self._register(
                    lambda a, c, _f=fraction: {
                        'estimated_value': 42.0, 'currency': a.get('currency'),
                        'economic_mechanism': 'incremental_revenue',
                        'attribution_fraction': _f, 'attribution_basis': 'hostile basis',
                    },
                    economic_mechanisms={'incremental_revenue'},
                )
                _, _, _, validated = self._validate(name)
                self.assertIsNotNone(
                    validated,
                    'distrust rule: a malformed OPTIONAL field must never '
                    'abstain the whole assessment')
                self.assertEqual(42.0, validated['estimated_value'])
                self.assertEqual('incremental_revenue', validated['economic_mechanism'])
                self.assertNotIn(
                    'attribution_fraction', validated,
                    'distrust rule: a malformed fraction must be discarded, '
                    'not shipped')
                self.assertNotIn('attribution_basis', validated)

    # -- 3. attribution_fraction with no attribution_basis -- both discarded -

    def test_fraction_with_no_basis_from_hostile_registrant_discards_both(self):
        name = self._register(
            lambda a, c: {'estimated_value': 42.0, 'currency': a.get('currency'),
                          'economic_mechanism': 'incremental_revenue',
                          'attribution_fraction': 0.5},
            economic_mechanisms={'incremental_revenue'},
        )
        _, _, _, validated = self._validate(name)
        self.assertIsNotNone(validated)
        self.assertEqual('incremental_revenue', validated['economic_mechanism'])
        self.assertNotIn(
            'attribution_fraction', validated,
            'distrust rule: travel-as-a-set applies at the caller too, not '
            "only inside a well-behaved registrant")
        self.assertNotIn('attribution_basis', validated)

    # -- 4. basis: non-string discarded, unbounded string clamped -----------
    # (ALREADY real -- Task 2's D-08 threading type-checks and clamps; no
    # marker needed for either row.)

    def test_non_string_basis_falls_back_to_evaluators_own(self):
        # Declares AND returns an accepted mechanism -- D-08's basis
        # authoring is gated on that acceptance (Task 2), so this case must
        # clear that gate to exercise the TYPE check on basis specifically,
        # not merely the mechanism gate.
        name = self._register(
            lambda a, c: {'estimated_value': 42.0, 'currency': a.get('currency'),
                          'economic_mechanism': 'incremental_revenue',
                          'basis': 12345},
            economic_mechanisms={'incremental_revenue'},
        )
        _, _, raw, validated = self._validate(name)
        self.assertIsNotNone(validated)
        self.assertEqual('incremental_revenue', validated['economic_mechanism'])
        self.assertIsInstance(validated['basis'], str)
        self.assertEqual(raw['basis'], validated['basis'])

    def test_10000_char_basis_is_clamped_never_unbounded(self):
        huge = 'x' * 10_000
        name = self._register(
            lambda a, c, _b=huge: {'estimated_value': 42.0, 'currency': a.get('currency'),
                                    'economic_mechanism': 'incremental_revenue',
                                    'basis': _b},
            economic_mechanisms={'incremental_revenue'},
        )
        _, _, _, validated = self._validate(name)
        self.assertIsNotNone(validated)
        self.assertEqual('incremental_revenue', validated['economic_mechanism'])
        self.assertIsInstance(validated['basis'], str)
        self.assertLessEqual(_serialized_len(validated['basis']), 200)
        # Proves the clamp actually engaged on the REGISTRANT's text, not a
        # silent fallback to the (short) evaluator basis.
        self.assertTrue(validated['basis'].startswith('x'))

    # -- 5. undeclared economic_mechanism is discarded (ALREADY real) -------

    def test_undeclared_economic_mechanism_is_discarded(self):
        name = self._register(
            lambda a, c: {'estimated_value': 42.0, 'currency': a.get('currency'),
                          'economic_mechanism': 'incremental_revenue'},
            economic_mechanisms=None,  # declares NOTHING
        )
        raw = self._raw(economic_mechanism='labor_substitution')
        _, cfg, raw, validated = self._validate(name, raw=raw)
        self.assertIsNotNone(validated)
        self.assertNotIn(
            'economic_mechanism', validated,
            'distrust rule: a registrant may assert only a mechanism it '
            'declared at registration')
        mod = self._load(boundaries={'valuation': name})
        record = mod._build_job_assessment(
            {'agentic_job_id': 'hostile-mechanism-001', 'job_type': 'code_review',
             'status': 'SUCCESS'}, validated, raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(record)
        self.assertEqual(mod._resolve_economic_mechanism(raw), record['economic_mechanism'])

    # -- PA-15: the registrant never sees `raw`, only the caller-constructed -
    # `assumptions` dict (mitigates T-54-03) -------------------------------

    def test_registrant_never_sees_raw_only_the_five_caller_constructed_keys(self):
        captured = {}

        def _capture(assumptions, config):
            captured.update(assumptions)
            return None  # abstain -- this test only cares what it was HANDED

        name = self._register(_capture)
        mod = self._load(boundaries={'valuation': name})
        cfg = mod._llm_evaluation_config()
        raw = self._raw(
            a_forbidden_key='should never reach the registrant',
            estimated_value=999999.0,
            model='gpt-attacker-9000',
        )
        mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertEqual(
            {'estimated_hours_saved', 'assumed_loaded_rate', 'currency',
             'economic_mechanism', 'inferred_role'},
            set(captured.keys()),
            'PA-15: assumptions is caller-constructed from already-'
            'validated fields; raw must never be threaded through',
        )


# ---------------------------------------------------------------------------
# Task 3 -- ProfileAttributionFenceTests (D-07, T-54-04)
# ---------------------------------------------------------------------------
# Seven cases, one per <behavior> bullet. Host shapes are built with
# tempfile directories and HERMES_HOME/REVENIUM_CONFIG_FILE env overrides in
# the module's own _load_classifier idiom -- CONFIG_FILE and HERMES_HOME
# resolve INDEPENDENTLY (classifier.py:41-53), so a test can put the config
# anywhere while controlling only whether HERMES_HOME/profiles/ looks
# multiplexed.

class ProfileAttributionFenceTests(_ValuationBoundaryTestCase):
    """T-54-04: a host whose owning profile cannot be attributed abstains
    from pricing revenue rather than pricing from the root config's card;
    an ordinary non-revenue session on the same host is unaffected."""

    def _classifier_with_home(self, hermes_home):
        return _load_classifier({
            'HERMES_HOME': str(hermes_home),
            'REVENIUM_CONFIG_FILE': str(self.config_path),
        })

    # -- 1. No profiles/ directory at all -> True ----------------------------

    def test_no_profiles_directory_returns_true(self):
        home = Path(self.tmp) / 'no-profiles'
        home.mkdir()
        mod = self._classifier_with_home(home)
        self.assertTrue(mod._revenue_profile_attribution_certain(None))

    # -- 2. profiles/ exists but holds no subdirectory -> True ---------------

    def test_empty_profiles_directory_returns_true(self):
        home = Path(self.tmp) / 'empty-profiles'
        (home / 'profiles').mkdir(parents=True)
        mod = self._classifier_with_home(home)
        self.assertTrue(mod._revenue_profile_attribution_certain(None))

    # -- 3. Multiplexed, resolution NOT engaged (identical paths) -> False --

    def test_multiplexed_and_not_engaged_returns_false(self):
        home = Path(self.tmp) / 'multiplexed-not-engaged'
        (home / 'profiles' / 'acme').mkdir(parents=True)
        mod = self._classifier_with_home(home)
        # paths=None -- the caller's own default -- falls back to
        # _module_paths() internally, so resolution provably never engaged.
        self.assertFalse(mod._revenue_profile_attribution_certain(None))
        # The same outcome holds when a caller explicitly hands back the
        # module's OWN paths object, not just the None default.
        self.assertFalse(
            mod._revenue_profile_attribution_certain(mod._module_paths()))

    # -- 4. Multiplexed, resolution ENGAGED (a distinct config_file) -> True -

    def test_multiplexed_and_engaged_returns_true(self):
        home = Path(self.tmp) / 'multiplexed-engaged'
        (home / 'profiles' / 'acme').mkdir(parents=True)
        mod = self._classifier_with_home(home)
        module_paths = mod._module_paths()
        distinct = module_paths._replace(
            config_file=home / 'profiles' / 'acme' / 'state' / 'revenium'
            / 'config.json')
        self.assertTrue(mod._revenue_profile_attribution_certain(distinct))

    # -- 5. Any exception inside the fence -> False --------------------------

    def test_exception_inside_the_fence_returns_false(self):
        home = Path(self.tmp) / 'exception-case'
        (home / 'profiles' / 'acme').mkdir(parents=True)
        mod = self._classifier_with_home(home)

        class _RaisingPaths:
            @property
            def config_file(self):
                raise RuntimeError('boom -- attribute access must not escape')

        self.assertFalse(
            mod._revenue_profile_attribution_certain(_RaisingPaths()))

    # -- 6. False + a declared, accepted mechanism -> abstains, distinctly --

    def test_false_fence_with_declared_mechanism_abstains_with_distinct_reason(self):
        home = Path(self.tmp) / 'multiplexed-abstain'
        (home / 'profiles' / 'acme').mkdir(parents=True)
        _write_config(
            self.config_path,
            boundaries={'valuation': 'revenue_card_valuation_fixture'},
            revenue_card={'hospitality-booking-agent': {'grossPerJob': 250.0}},
            revenue_card_key='hospitality-booking-agent',
        )
        mod = self._classifier_with_home(home)
        cfg = mod._llm_evaluation_config()
        raw = self._raw()

        with self.assertLogs('revenium_classifier', level='WARNING') as cm:
            validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')

        self.assertIsNone(validated)
        fence_lines = [l for l in cm.output if 'owning profile' in l]
        self.assertEqual(
            1, len(fence_lines),
            'exactly one fence-abstention warning must fire; '
            f'got: {cm.output}')
        # Distinct from every OTHER abstention wording this function can
        # emit -- a human reading the log must be able to tell this
        # abstention reason apart from the others.
        other_lines = [l for l in cm.output if 'owning profile' not in l]
        for line in other_lines:
            self.assertNotIn('owning profile', line)

    # -- 7. False fence + NO declared mechanism -> non-revenue path unaffected

    def test_false_fence_does_not_touch_the_non_revenue_path(self):
        home = Path(self.tmp) / 'multiplexed-non-revenue'
        (home / 'profiles' / 'acme').mkdir(parents=True)
        # No boundaries object at all -- an ordinary, non-revenue session.
        mod = self._classifier_with_home(home)
        cfg = mod._llm_evaluation_config()
        raw = self._raw()
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        self.assertEqual(round(2.5 * 150.0, 2), validated['estimated_value'])


# ---------------------------------------------------------------------------
# Task 2 (Plan 06) -- GrossLeakFixtureTests (D-11, T-54-02)
# ---------------------------------------------------------------------------

class GrossLeakFixtureTests(_ValuationBoundaryTestCase):
    """D-11's adversarial fixture: a configured business gross must never
    appear on any of four named surfaces -- the persisted sidecar record,
    the `meter`/`outcome` argv, the `--metadata` envelope, and
    `revenium-metering.log` -- on the happy path AND on every path where
    the registrant read the configured gross (or the raw config value that
    would have BECOME the gross had it been well-formed) and refused it.

    Each scenario drives the REAL pipeline end to end in one isolated
    per-scenario HERMES_HOME: config -> the real
    `revenue_card_valuation_fixture` registrant via `_validate_assessment`
    -> `_build_job_assessment` -> the REAL `_write_job_assessment` sidecar
    writer (surface 1, read back from disk) -> the REAL hermes-report.sh
    outcome stage against that SAME persisted file (surfaces 2-4).

    WHAT THIS FIXTURE PROVES, AND WHAT WOULD MAKE IT A LIE: it proves
    absence across these four named surfaces for ONE configured gross
    value on ONE code path (the shipped `revenue_card_valuation_fixture`
    registrant), driven for real rather than asserted from the shape of
    the code. It does NOT prove no future surface could carry the gross --
    FA-03 in 54-06-PLAN.md's flagged assumptions names the two candidates
    this fixture does not cover (a traceback frame local surviving an
    outer `except`, and an operator's own config.json backup or fleet copy).

    CORRECTED READING (54-06-PLAN.md's own "read, not assume" instruction,
    applied to this task's own behavior list): the plan's behavior bullet
    7 states the product is present on "each of the four surfaces" on the
    happy path. Reading every `log`/`info`/`warn` call site on
    hermes-report.sh's outcome path (and confirming empirically by driving
    a real tick) shows NONE of them ever references the resolved value --
    only job ids, exit codes and status words. `revenium-metering.log`
    therefore never carries the PRODUCT either, by the same design that
    keeps the GROSS off it -- verified, not merely assumed, and the
    absence is intentional (D-11/ROI-08 forbid a business figure appearing
    there at all). The positive control for the log surface is therefore
    the job id appearing in its one "Outcome reported" line -- proof the
    driven tick actually processed this scenario's job -- rather than the
    unobtainable literal product. The other three surfaces (record, argv,
    metadata) all carry the real product and are asserted directly.
    """

    GROSS = 4321.0
    FRACTION = 0.15
    PRODUCT = 648.15  # round(4321.0 * 0.15, 2)
    CARD_KEY = 'hospitality-booking-agent'

    @staticmethod
    def _forbidden_forms(value):
        """Every representation of `value` this fixture checks for,
        built programmatically from `value` itself rather than
        hand-typed. repr() and json.dumps() of a Python float are
        byte-identical (CPython's json encoder calls float.__repr__
        internally), so a hex representation is added defensively --
        both a genuinely distinct fifth form and a legitimate extra
        guard against an even more exotic accidental serialization."""
        forms = {
            str(int(value)),
            '{:.2f}'.format(value),
            repr(float(value)),
            json.dumps(float(value)),
            float(value).hex(),
        }
        return sorted(forms)

    def test_forbidden_forms_are_independent_of_unrelated_defaults(self):
        """A later fixture edit that accidentally makes the gross a
        substring of the product, the default bounds, or the default
        ceilings must not silently turn every absence assertion in this
        class into a tautology."""
        forms = self._forbidden_forms(self.GROSS)
        self.assertGreaterEqual(
            len(forms), 4,
            f'need at least 4 distinct forbidden forms, got {forms!r}',
        )
        unrelated = [
            repr(self.PRODUCT), json.dumps(self.PRODUCT),
            '{:.2f}'.format(self.PRODUCT),
            repr(40.0), repr(500.0), repr(round(40.0 * 500.0, 2)),
            '2.5', '150.0', repr(round(2.5 * 150.0, 2)),
            '1715516000.5', '1715516001.000', '1715516002.0',
        ]
        for form in forms:
            for u in unrelated:
                self.assertNotIn(
                    form, u,
                    f'forbidden form {form!r} is a substring of unrelated '
                    f'value {u!r} -- choose a different GROSS/FRACTION',
                )

    @staticmethod
    def _metadata_value(argv):
        for i, tok in enumerate(argv):
            if tok == '--metadata' and i + 1 < len(argv):
                return argv[i + 1]
        return None

    def _run_reporter_stage(self, hermes_home, job_id):
        """Drive the REAL hermes-report.sh outcome stage against
        `hermes_home`, which already holds the classifier's real sidecar
        write for `job_id` -- proving surfaces 2-4 against the SAME
        persisted bytes surface 1 read, not a second, hand-built record."""
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        markers_dir = os.path.join(state_dir, 'markers')
        os.makedirs(markers_dir, mode=0o700, exist_ok=True)
        state_db = os.path.join(hermes_home, 'state.db')
        jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')

        shim_home = os.path.join(hermes_home, 'shim-home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir, exist_ok=True)
        meter_log = os.path.join(hermes_home, 'meter.log')
        jobs_log = os.path.join(hermes_home, 'jobs.log')
        inv_log = os.path.join(hermes_home, 'inv.log')
        shim = os.path.join(bin_dir, 'revenium')

        sid = f'{job_id}-sid'
        build_state_db(state_db, [{
            'id': sid,
            'model': 'claude-sonnet-4-6',
            'source': 'test',
            'input_tokens': 100,
            'output_tokens': 50,
            'cache_read': 0,
            'cache_write': 0,
            'reasoning': 0,
            'estimated_cost': '0',
            'api_calls': 1,
            'started_at': 1715514000.0,
            'ended_at': 1715514000.0,
            'billing_provider': 'anthropic',
        }])
        with open(jobs_ledger, 'w') as f:
            f.write(f'JOB:{job_id}:created:1715516001.000\n')

        task_marker = {
            'muid': f'{job_id}-task', 'ts': 1715516000.5, 'sid': sid,
            'task_type': 'code_review', 'operation_type': 'CHAT',
        }
        job_marker = {
            'kind': 'job', 'ts': 1715516002.0, 'sid': sid,
            'agentic_job_id': job_id,
            'job_name': 'Phase 54 Plan 06 Gross Leak Test Job',
            'job_type': 'booking_completion', 'status': 'SUCCESS',
        }
        with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
            f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
            f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

        build_shim(shim, outcome_value_capable=True)
        base_env = {
            **os.environ,
            'HOME': shim_home,
            'HERMES_HOME': hermes_home,
            'REVENIUM_STATE_DIR': state_dir,
            'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': inv_log,
            'METER_LOG': meter_log,
            'JOBS_LOG': jobs_log,
            'TZ': 'UTC',
            'REVENIUM_ORGANIZATION_NAME': '',
        }
        rc, _ignored, output = run_script(
            SCRIPTS_DIR / 'hermes-report.sh', base_env, inv_log
        )
        self.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {output}')

        outcome_inv = []
        if os.path.exists(jobs_log):
            with open(jobs_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if not line:
                        continue
                    argv = shlex.split(line)
                    if len(argv) >= 2 and argv[0] == 'jobs' and argv[1] == 'outcome':
                        outcome_inv.append(argv)
        self.assertEqual(
            len(outcome_inv), 1,
            f'expected exactly 1 "jobs outcome" invocation, got {len(outcome_inv)}: '
            f'{outcome_inv!r}\nOutput: {output}'
        )
        argv = outcome_inv[0]

        log_path = os.path.join(state_dir, 'revenium-metering.log')
        log_bytes = b''
        if os.path.exists(log_path):
            log_bytes = Path(log_path).read_bytes()
        return argv, log_bytes

    def _drive_scenario(self, entry, job_id, reportable=False):
        """Config -> the REAL registrant -> the REAL record ->
        the REAL sidecar write -> the REAL hermes-report.sh outcome stage,
        all rooted at one fresh, isolated HERMES_HOME.

        `reportable=True` sets `experimentalReportEstimates: true` so the
        happy path's CUSTOMER_CONFIGURED record actually resolves to
        `reportable` rather than `candidate` -- otherwise the reportability
        gate Task 1 hardened would strip the value before it ever reached
        argv/metadata, and this class's own positive control would fail
        for the wrong reason (a shed value, not a harness bug)."""
        run_home = tempfile.mkdtemp(prefix='gsd-p54-06-leak-')
        self.addCleanup(shutil.rmtree, run_home, ignore_errors=True)
        config_path = Path(run_home) / 'config.json'
        cfg_dict = {
            'boundaries': {'valuation': 'revenue_card_valuation_fixture'},
            'llmOutcomeEvaluation': {
                'revenueCard': {self.CARD_KEY: entry},
                'revenueCardKey': self.CARD_KEY,
            },
        }
        if reportable:
            cfg_dict['llmOutcomeEvaluation']['experimentalReportEstimates'] = True
        config_path.write_text(json.dumps(cfg_dict))
        mod = _load_classifier({
            'REVENIUM_CONFIG_FILE': str(config_path),
            'HERMES_HOME': run_home,
        })
        cfg = mod._llm_evaluation_config()
        raw = self._raw()
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        job = {'agentic_job_id': job_id, 'job_type': 'booking_completion',
               'status': 'SUCCESS'}
        if validated is not None:
            record = mod._build_job_assessment(job, validated, raw, cfg, 'stub', 'v1')
        else:
            record = mod._build_job_assessment(
                job, None, raw, cfg, 'stub', 'v1', abstention_reason='no_evaluation')
        self.assertIsNotNone(
            record, 'record construction must succeed regardless of abstention')

        sidecar_path = mod._write_job_assessment(record, paths=mod._module_paths())
        self.assertIsNotNone(
            sidecar_path,
            'the real sidecar writer must succeed for this fixture to be non-trivial')
        persisted_bytes = Path(sidecar_path).read_bytes()

        argv, log_bytes = self._run_reporter_stage(run_home, job_id)
        metadata_raw = self._metadata_value(argv) or ''
        try:
            metadata_reserialized = json.dumps(
                json.loads(metadata_raw), sort_keys=True) if metadata_raw else ''
        except ValueError:
            metadata_reserialized = metadata_raw

        return {
            'record': record,
            'validated': validated,
            'persisted': persisted_bytes.decode('utf-8', errors='replace'),
            'argv': ' '.join(argv),
            'metadata': metadata_reserialized,
            'log': log_bytes.decode('utf-8', errors='replace'),
        }

    def _assert_forms_absent(self, forms, surfaces):
        for surface_name, haystack in surfaces.items():
            for form in forms:
                self.assertNotIn(
                    form, haystack,
                    f'forbidden form {form!r} leaked on surface {surface_name!r}: '
                    f'{haystack!r}',
                )

    def _surfaces(self, result):
        return {
            'persisted_record': result['persisted'],
            'meter_outcome_argv': result['argv'],
            'metadata_envelope': result['metadata'],
            'revenium_metering_log': result['log'],
        }

    def test_happy_path_positive_control_and_gross_absence(self):
        """The product ships on three of the four surfaces (record, argv,
        metadata); the log carries neither the gross nor the product, by
        design (see class docstring). The gross itself is absent from all
        four -- 4 of this class's 16 absence assertions."""
        entry = {
            'grossPerJob': self.GROSS,
            'attributionFraction': self.FRACTION,
            'attributionBasis': 'q3 loyalty capture rate',
        }
        result = self._drive_scenario(entry, 'p54-06-leak-happy-001', reportable=True)
        self.assertIsNotNone(
            result['validated'],
            'test setup invalid: the happy path must be accepted, not abstained')
        self.assertEqual(self.PRODUCT, result['record'].get('estimated_value'))
        self.assertEqual(self.PRODUCT, result['validated'].get('estimated_value'))

        product_form = repr(self.PRODUCT)
        surfaces = self._surfaces(result)
        for name in ('persisted_record', 'meter_outcome_argv', 'metadata_envelope'):
            self.assertIn(
                product_form, surfaces[name],
                f'positive control failed: product {product_form!r} missing '
                f'from surface {name!r} -- a harness producing nothing would '
                f'otherwise pass every absence assertion below',
            )
        # revenium-metering.log positive control: the job id, not the
        # product (see class docstring's "CORRECTED READING").
        self.assertIn(
            'p54-06-leak-happy-001', surfaces['revenium_metering_log'],
            'positive control failed: the driven job id is missing from '
            'revenium-metering.log -- the tick may not have processed '
            'this scenario at all',
        )

        forms = self._forbidden_forms(self.GROSS)
        self._assert_forms_absent(forms, surfaces)

    def test_malformed_entry_abstains_and_gross_is_absent(self):
        """The card entry is a bare number, not a dict -- `malformed_entry`.
        The literal value sat in the raw config the registrant inspected
        (isinstance(entry, dict) is checked before grossPerJob is ever
        read) even though it was never extracted into a `gross` variable;
        4 more of this class's 16 absence assertions."""
        result = self._drive_scenario(self.GROSS, 'p54-06-leak-entry-001')
        self.assertIsNone(
            result['validated'],
            'test setup invalid: a non-dict entry must abstain the whole assessment')
        self.assertNotIn('attribution_fraction', result['record'])
        self.assertNotIn('estimated_value', result['record'])

        forms = self._forbidden_forms(self.GROSS)
        self._assert_forms_absent(forms, self._surfaces(result))

    def test_out_of_range_fraction_abstains_and_gross_is_absent(self):
        """The registrant reads a VALID gross, then reads an
        out-of-[0.0, 1.0] fraction and abstains (`malformed_attribution`)
        -- the registrant read the gross and is now explaining why it
        refused the entry; 4 more of this class's 16 absence assertions."""
        entry = {
            'grossPerJob': self.GROSS,
            'attributionFraction': 1.5,
            'attributionBasis': 'q3 loyalty capture rate',
        }
        result = self._drive_scenario(entry, 'p54-06-leak-fraction-001')
        self.assertIsNone(
            result['validated'],
            'test setup invalid: an out-of-range fraction must abstain the whole assessment')
        self.assertNotIn('attribution_fraction', result['record'])
        self.assertNotIn('estimated_value', result['record'])

        forms = self._forbidden_forms(self.GROSS)
        self._assert_forms_absent(forms, self._surfaces(result))

    def test_fraction_with_no_basis_abstains_and_gross_is_absent(self):
        """The registrant reads a VALID gross and a valid fraction, then
        finds no basis and abstains (`malformed_attribution`, travel-as-a-
        set direction 1) -- the final 4 of this class's 16 absence
        assertions."""
        entry = {
            'grossPerJob': self.GROSS,
            'attributionFraction': self.FRACTION,
        }
        result = self._drive_scenario(entry, 'p54-06-leak-basis-001')
        self.assertIsNone(
            result['validated'],
            'test setup invalid: a fraction with no basis must abstain the whole assessment')
        self.assertNotIn('attribution_fraction', result['record'])
        self.assertNotIn('estimated_value', result['record'])

        forms = self._forbidden_forms(self.GROSS)
        self._assert_forms_absent(forms, self._surfaces(result))


def _extract_ceiling_bytes(body):
    """Read `_METADATA_CEILING_BYTES` out of the extracted heredoc source
    rather than retyping 4096 in this test, so the constant has exactly
    one authority (the heredoc itself). Duplicated (not imported) from
    tests/test_phase46_metadata_envelope.py's own helper of the same
    name, per this module's own no-shared-code-between-test-fixtures
    convention."""
    import re
    match = re.search(r'_METADATA_CEILING_BYTES\s*=\s*(\d+)', body)
    if not match:
        return None
    return int(match.group(1))


# ---------------------------------------------------------------------------
# Task 3 (Plan 06) -- RevenueArmEnvelopeBudgetTests (D-10, 51-CONTEXT.md D-09)
# ---------------------------------------------------------------------------

class RevenueArmEnvelopeBudgetTests(_ValuationBoundaryTestCase):
    """51-CONTEXT.md D-09's ceiling-margin requirement, discharged as the
    named task it asks for. The tier-1 shed content grew in this phase --
    a job_assessment record can now carry attribution_fraction,
    attribution_basis and a declared economic_mechanism -- and Phase 46's
    worst-case measurement (MetadataEnvelopeBudgetTests) was taken before
    any of that was possible.

    Mirrors tests/test_phase46_metadata_envelope.py::MetadataEnvelopeBudgetTests
    method for method against the REVENUE arm's own worst case: compute the
    worst case PROGRAMMATICALLY from the real clamps, call the REAL
    constructors, assert acceptance before measuring, serialize exactly as
    the writer does, assert under the extracted ceiling AND a stated
    MARGIN_BYTES, and sweep the same five encodings.

    CORRECTED READING (54-06-PLAN.md's own "read, not assume" instruction):
    the plan's own acceptance criterion states attribution_basis "measures
    exactly at the 500-byte serialized clamp." Reading
    `_clamp_assessment_text` shows its binary search truncates on a WHOLE
    code-point boundary, never splitting a surrogate pair -- so a
    multi-byte encoding undershoots the 500-byte budget whenever 500 does
    not divide evenly by that encoding's escaped-character width (6 bytes
    for accented/CJK, 12 for emoji). Only ASCII (and any width dividing
    500 evenly, which "mixed" happens to hit by coincidence of its 4-char,
    25-byte cycle) lands at exactly 500. Every existing clamp assertion in
    this repo (test_phase46_metadata_envelope.py's own) uses
    assertLessEqual for exactly this reason; this class follows the same
    convention rather than asserting an equality that is only true for
    some encodings."""

    MARGIN_BYTES = 1024
    CARD_KEY = 'hospitality-booking-agent'

    # The fraction with the longest legal serialized form among a small,
    # explicit candidate set -- computed, not guessed, so a future
    # candidate that serializes even longer is one line to add rather
    # than a silent gap. Floating-point representation error (0.1 + 0.2)
    # beats the "obvious" repeating-decimal candidates (1/3, 2/3) by one
    # character, which is exactly the kind of worst case a hand-picked
    # value would miss.
    _FRACTION_CANDIDATES = (
        0.1 + 0.2, 1.0 / 3.0, 2.0 / 3.0, 0.1, 0.9999999999999999,
        1e-16, 0.1234567890123456,
    )
    WORST_CASE_FRACTION = max(_FRACTION_CANDIDATES, key=lambda f: len(repr(f)))

    def setUp(self):
        super().setUp()
        self.script_text = HERMES_REPORT_SH.read_text()
        self.body = _extract_outcome_metadata_heredoc(self.script_text)
        self.assertIsNotNone(
            self.body,
            "outcome_metadata=$( ... <<'PY' ... \\nPY\\n anchor moved in "
            'hermes-report.sh -- update the extraction before trusting this test',
        )
        self.ceiling = _extract_ceiling_bytes(self.body)
        self.assertIsNotNone(
            self.ceiling,
            '_METADATA_CEILING_BYTES not found in the extracted heredoc body',
        )

    # -- worst-case JobAssessment construction, mirroring
    # MetadataEnvelopeBudgetTests method for method, plus the revenue
    # card's own config-on-disk (boundaries.valuation is read from the
    # config FILE, never from the in-memory cfg argument) --

    def _worst_case_valid(self, job_id):
        return {
            'agentic_job_id': job_id,
            'job_type': 'a' + 'b' * 46 + 'c',
            'status': 'FAILED',
        }

    def _worst_case_raw(self, narrative_char='n'):
        return {
            'economic_mechanism': 'augmentation_capacity_expansion',
            'inferred_role': narrative_char * 60,
            'estimated_hours_saved': 40.0,
            'assumed_loaded_rate': 500.0,
            'currency': 'USD',
            'basis': narrative_char * 1000,
            'confidence': 0.999999,
            'candidate_downstream_outcome': narrative_char * 1000,
            'counterfactual_assumption': narrative_char * 1000,
        }

    def _write_revenue_config(self, mod, job_type, narrative_char):
        cfg_dict = {
            'boundaries': {'valuation': 'revenue_card_valuation_fixture'},
            'llmOutcomeEvaluation': {
                'revenueCard': {
                    self.CARD_KEY: {
                        # Overlong on purpose -- the registrant's own
                        # NARRATIVE_CLAMP_BYTES (500) clamp is the real
                        # ceiling being measured, not a value this test
                        # guessed.
                        'grossPerJob': 1000.0,
                        'attributionFraction': self.WORST_CASE_FRACTION,
                        'attributionBasis': narrative_char * 1000,
                    },
                },
                'revenueCardKey': self.CARD_KEY,
                # Every cost category as a literal 0 -- lands in BOTH
                # "included" and "known_zero" simultaneously, which costs
                # MORE serialized bytes than a large nonzero value would
                # (SidecarBudgetTests' own D-10 finding, reused here for
                # the same reason Phase 46 reused it).
                'costs': {job_type: {cat: 0 for cat in mod.COST_CATEGORIES}},
            },
        }
        self.config_path.write_text(json.dumps(cfg_dict))

    def _worst_case_record(self, mod, job_id, narrative_char='n'):
        raw = self._worst_case_raw(narrative_char)
        valid = self._worst_case_valid(job_id)
        self._write_revenue_config(mod, valid['job_type'], narrative_char)
        cfg = mod._llm_evaluation_config()
        # Evaluator/model overlong on purpose -- _build_job_assessment's
        # own internal clamps (32/16/64 bytes respectively) are the real
        # ceilings; passing something longer proves those internal
        # clamps, not a value this test guessed, are what bounds the
        # record.
        evaluator = 'e' * 100
        evaluator_version = 'v' * 100
        model = 'm' * 100
        assessment = mod._validate_assessment(raw, cfg, evaluator, evaluator_version)
        self.assertIsNotNone(
            assessment,
            'max-bound revenue-arm inputs must be accepted, not rejected')
        self.assertEqual(
            'incremental_revenue', assessment.get('economic_mechanism'),
            'test setup invalid: expected the revenue registrant\'s '
            'declared mechanism to be accepted')
        self.assertIn('attribution_fraction', assessment)
        self.assertIn('attribution_basis', assessment)
        # Behavior: attribution_basis measures AT OR UNDER the 500-byte
        # serialized clamp -- asserted here, not assumed, and never over
        # (that would be the actual clamp failing). NOT asserted equal to
        # exactly 500: _clamp_assessment_text truncates on a WHOLE
        # code-point boundary (never splitting a surrogate pair), so a
        # multi-byte encoding can undershoot the byte budget by up to
        # (bytes-per-char - 1) when 500 does not divide evenly by that
        # width -- e.g. accented/cjk (6 bytes/escaped char) land at 498,
        # emoji (12 bytes/escaped char) at 492. Every existing precedent
        # in this repo (test_phase46_metadata_envelope.py's own clamp
        # assertions) uses assertLessEqual for exactly this reason; only
        # ASCII (and any width that divides 500 evenly) reaches exactly
        # 500. See this class's docstring for the corrected reading.
        basis_serialized = len(
            json.dumps(assessment['attribution_basis'], ensure_ascii=True)
            .encode('utf-8')) - 2
        self.assertLessEqual(
            basis_serialized, mod.NARRATIVE_CLAMP_BYTES,
            f'attribution_basis worst case measured {basis_serialized} '
            f'serialized bytes, over the {mod.NARRATIVE_CLAMP_BYTES}-byte clamp',
        )
        rec = mod._build_job_assessment(
            valid, assessment, raw, cfg, evaluator, evaluator_version,
            double_counting_group='g' * 100, model=model)
        self.assertIsNotNone(rec, 'worst-case revenue-arm record construction must succeed')
        self.assertIn('attribution_fraction', rec)
        self.assertIn('attribution_basis', rec)
        self.assertEqual('incremental_revenue', rec.get('economic_mechanism'))
        return rec

    def _measure(self, mod, narrative_char):
        rec = self._worst_case_record(
            mod, job_id=f'p54-06-budget-{narrative_char!r}', narrative_char=narrative_char)
        failure_reason = mod._clamp_assessment_text(
            narrative_char * 1000, mod.FAILURE_REASON_CLAMP_BYTES)
        env = _assessment_env(
            assessment=rec, source='prod', status='FAILED', failure_reason=failure_reason)
        result = _run_forwarder(self.body, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout.strip()
        json.loads(out)  # must parse
        return len(out.encode('utf-8'))

    _ENCODINGS = (('ascii', 'n'), ('accented', 'é'), ('cjk', '漢'), ('emoji', '😀'), ('mixed', 'a😀é漢'))

    def test_worst_case_swept_across_encodings_stays_under_ceiling(self):
        """Behavior 1."""
        mod = self._load(boundaries={'valuation': 'revenue_card_valuation_fixture'})
        for label, ch in self._ENCODINGS:
            with self.subTest(label):
                measured = self._measure(mod, ch)
                self.assertLessEqual(
                    measured, self.ceiling,
                    f'{label} revenue-arm worst case is {measured} bytes, '
                    f'over the {self.ceiling}-byte ceiling',
                )
                print(f'[54-06 RevenueArmEnvelopeBudgetTests] {label} '
                      f'worst-case envelope: {measured} bytes')

    def test_margin_asserted_not_assumed(self):
        """Behavior 2: the largest measured revenue-arm worst case plus
        MARGIN_BYTES is still at or under the ceiling -- the headroom is
        asserted, not assumed."""
        mod = self._load(boundaries={'valuation': 'revenue_card_valuation_fixture'})
        largest = max(self._measure(mod, ch) for _label, ch in self._ENCODINGS)
        self.assertLessEqual(
            largest + self.MARGIN_BYTES, self.ceiling,
            f'largest measured revenue-arm worst case ({largest} bytes) + '
            f'{self.MARGIN_BYTES}-byte margin exceeds the {self.ceiling}-byte '
            'ceiling -- re-derive the ceiling or the clamps',
        )
        print(f'[54-06 RevenueArmEnvelopeBudgetTests] largest worst-case '
              f'revenue-arm envelope: {largest} bytes, margin {self.ceiling - largest}')
