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
    no key is configured."""

    def test_multi_entry_card_with_no_key_selects_nothing(self):
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
        self.assertIsNone(got)

    def test_inferred_role_naming_a_card_entry_does_not_select_it(self):
        mod = self._load(
            boundaries={'valuation': 'revenue_card_valuation_fixture'},
            revenue_card={'hospitality-booking-agent': {'grossPerJob': 250.0}},
            revenue_card_key=None,
        )
        cfg = mod._llm_evaluation_config()
        got = mod._validate_assessment(
            self._raw(inferred_role='hospitality-booking-agent'), cfg, 'stub', 'v1')
        self.assertIsNone(got)

    def test_key_naming_an_absent_entry_abstains(self):
        mod = self._load(
            boundaries={'valuation': 'revenue_card_valuation_fixture'},
            revenue_card={'hospitality-booking-agent': {'grossPerJob': 250.0}},
            revenue_card_key='car-rental-agent',
        )
        cfg = mod._llm_evaluation_config()
        got = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNone(got)

