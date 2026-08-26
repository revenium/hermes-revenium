"""Phase 43 Plan 01 — the EGV-18 resolver and the reporter gate it drives.

An estimate produced without explicit experimental opt-in is retained locally
as a candidate; its number never leaves the machine. This module tests the
resolver classifier.py computes it with (`_resolve_reportability_status`) and
the fixture-fidelity guarantee that keeps the golden fixture honest.

Requirements covered:
  EGV-18 — reportability_status gates whether an estimate's VALUE (not its
           provenance) reaches Revenium.

Decisions this module exercises (43-CONTEXT.md):
  D-05 — reportable | candidate; a candidate withholds value_low/value_base/
         value_high/bounds_source/currency/estimated_value/assumptions but
         keeps evidence_class/evaluator/evaluator_version/model/the version
         family.
  D-06 — a kind:"correction" record is reportable by construction, no
         config opt-in required.
  D-09 — reportability_status is a straight rename of Phase 42's
         REPORTABILITY_STATUS_DEFAULT placeholder; no migration shim.
  D-11 — reportability_status is deliberately NOT in the abstention omit
         family; an abstained record still carries the key, valued
         candidate.
  D-12 — the config key is llmOutcomeEvaluation.experimentalReportEstimates,
         literal-JSON-true only (mirrors ROI-01's "enabled" discipline).

Guarantee class (43-VALIDATION.md's honesty rule): every assertion in this
module is BEHAVIOURAL. It proves the resolver and the reporter withhold the
value on the paths exercised here. It makes no structural or impossibility
claim -- the structural guards (ast-based promotion/inheritance guards) land
in plans 43-02 and 43-03.
"""
import importlib.util
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'


def _load_classifier(env: dict | None = None):
    """Import classifier.py fresh under `env`.

    Copied from tests/test_phase36_evaluator_seam.py's loader shape (per
    43-01-PLAN.md's Task 1 instruction), NOT imported across test modules --
    module-level path constants bind at import, so a test that changes
    REVENIUM_* must re-import rather than reassign.
    """
    env = env or {}
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(
            'phase43_classifier', str(PLUGIN / 'classifier.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class ResolverTests(unittest.TestCase):
    """EGV-18 -- _resolve_reportability_status(cfg, abstained) is a pure,
    never-raising function. Behaviors 1-6 from 43-01-PLAN.md's Task 1."""

    def setUp(self):
        self.mod = _load_classifier()

    def test_literal_true_config_and_not_abstained_is_reportable(self):
        """Behavior 1: cfg {"experimentalReportEstimates": True}, abstained
        False -> "reportable"."""
        status = self.mod._resolve_reportability_status(
            {'experimentalReportEstimates': True}, False)
        self.assertEqual(status, self.mod.REPORTABILITY_REPORTABLE)

    def test_empty_config_is_candidate(self):
        """Behavior 2: cfg {} -> "candidate"."""
        status = self.mod._resolve_reportability_status({}, False)
        self.assertEqual(status, self.mod.REPORTABILITY_CANDIDATE)

    def test_string_true_is_not_a_literal_true(self):
        """Behavior 3: cfg {"experimentalReportEstimates": "true"} ->
        "candidate" -- a string is not literal True (D-12, mirrors ROI-01's
        "enabled" discipline)."""
        status = self.mod._resolve_reportability_status(
            {'experimentalReportEstimates': 'true'}, False)
        self.assertEqual(status, self.mod.REPORTABILITY_CANDIDATE)

    def test_int_one_is_not_a_literal_true(self):
        """Behavior 4: cfg {"experimentalReportEstimates": 1} ->
        "candidate" -- an int is not literal True."""
        status = self.mod._resolve_reportability_status(
            {'experimentalReportEstimates': 1}, False)
        self.assertEqual(status, self.mod.REPORTABILITY_CANDIDATE)

    def test_abstained_overrides_a_reportable_config(self):
        """Behavior 5: cfg {"experimentalReportEstimates": True}, abstained
        True -> "candidate". D-05: an abstained assessment is never
        reportable, whatever the config says -- checked first,
        unconditionally."""
        status = self.mod._resolve_reportability_status(
            {'experimentalReportEstimates': True}, True)
        self.assertEqual(status, self.mod.REPORTABILITY_CANDIDATE)

    def test_non_dict_or_none_config_fails_closed_to_candidate(self):
        """Behavior 6: cfg None or a non-dict -> "candidate", never raises."""
        for bad_cfg in (None, [], 'not-a-dict', 42, ()):
            with self.subTest(cfg=bad_cfg):
                status = self.mod._resolve_reportability_status(bad_cfg, False)
                self.assertEqual(status, self.mod.REPORTABILITY_CANDIDATE)

    def test_never_raises_for_pathological_config_values(self):
        """D-04-style never-raise guarantee, exercised directly (not just
        implied by the behaviors above): a cfg whose experimentalReportEstimates
        value is itself an exotic object must not raise -- it simply fails
        the `is True` identity check and resolves to candidate."""
        pathological_cfgs = (
            {'experimentalReportEstimates': object()},
            {'experimentalReportEstimates': None},
            {'experimentalReportEstimates': [True]},
            {'experimentalReportEstimates': {'nested': True}},
        )
        for cfg in pathological_cfgs:
            with self.subTest(cfg=cfg):
                try:
                    status = self.mod._resolve_reportability_status(cfg, False)
                except Exception as exc:  # pragma: no cover -- this IS the assertion
                    self.fail(f'_resolve_reportability_status raised {exc!r} for cfg={cfg!r}')
                self.assertEqual(status, self.mod.REPORTABILITY_CANDIDATE)

    def test_two_locked_values_are_the_only_possible_return(self):
        """D-05: exactly two values exist. A richer value set was rejected
        as more states than EGV-18 requires."""
        self.assertEqual(self.mod.REPORTABILITY_REPORTABLE, 'reportable')
        self.assertEqual(self.mod.REPORTABILITY_CANDIDATE, 'candidate')


class FixtureFidelityTests(unittest.TestCase):
    """Task 2 -- the direct answer to 42-LEARNINGS' "a golden fixture can pin
    what the TEST produces, not what production sends": tests/test_phase38_
    reporter_path.py's _sidecar_record() hand-written fixture and a REAL
    record built through classifier.py's own construction path can no
    longer drift apart silently, because this test compares one against
    the other on every run.

    Guarantee class: BEHAVIOURAL -- this proves the fixture's key set is a
    subset of what production emits and that the two governed values agree,
    for the inputs exercised here. It does not prove no other divergence is
    possible.
    """

    def test_sidecar_record_fixture_key_set_is_a_subset_of_the_real_record(self):
        # Imported here, not at module scope, matching this module's own
        # "not imported across test modules for the loader" posture for the
        # classifier import -- but _sidecar_record is a plain fixture
        # builder (no module-level path constants), so importing IT across
        # modules is the point: the same function both files' assertions
        # are built against.
        from tests.test_phase38_reporter_path import _sidecar_record

        mod = _load_classifier()
        raw = {
            'inferred_role': 'senior software engineer',
            'estimated_hours_saved': 3.5,
            'assumed_loaded_rate': 150.0,
            'currency': 'USD',
            'basis': '3.5 hours of senior engineer review time',
            'confidence': 0.8,
            'candidate_downstream_outcome': 'PR merged to main',
            'counterfactual_assumption': 'a human reviewer would have taken the same time',
        }
        valid = {
            'agentic_job_id': 'fidelity-job-001', 'job_type': 'code_review', 'status': 'SUCCESS',
        }
        assessment = mod._validate_assessment(raw, {}, 'llm', 'v1')
        self.assertIsNotNone(assessment, 'fixture raw input must validate for this test to be meaningful')
        real_record = mod._build_job_assessment(
            valid, assessment, raw, {'experimentalReportEstimates': True}, 'llm', 'v1')
        self.assertIsNotNone(real_record, 'real construction must succeed for this test to be meaningful')

        fixture_record = _sidecar_record('fidelity-job-001')

        missing = set(fixture_record.keys()) - set(real_record.keys())
        self.assertEqual(
            missing, set(),
            f'_sidecar_record carries keys production does not emit: {missing} -- '
            'the fixture must describe a subset of the real wire shape, never a superset.',
        )
        # The two values this phase's gate is actually built on must agree
        # between the hand-written fixture and the real constructor, under
        # the SAME (reportable) config the fixture's default represents.
        self.assertEqual(
            fixture_record['reportability_status'], real_record['reportability_status'],
            'fixture and real record disagree on reportability_status',
        )
        self.assertEqual(
            fixture_record['evidence_class'], real_record['evidence_class'],
            'fixture and real record disagree on evidence_class',
        )


class AbstentionTests(unittest.TestCase):
    """Task 3 -- D-05: an abstained assessment is never reportable, whatever
    the config says. Driven through the REAL construction path
    (_build_job_assessment with abstention_reason set), not the resolver
    directly -- proving bool(abstention_reason) is actually wired at the
    single consumer site inside classifier.py, not merely available."""

    def test_abstained_record_is_candidate_even_under_a_reportable_config(self):
        mod = _load_classifier()
        valid = {
            'agentic_job_id': 'abstain-job-001', 'job_type': 'code_review', 'status': 'SUCCESS',
        }
        record = mod._build_job_assessment(
            valid, None, None, {'experimentalReportEstimates': True}, 'llm', 'v1',
            abstention_reason='abstained',
        )
        self.assertIsNotNone(record)
        self.assertEqual(
            record['reportability_status'], mod.REPORTABILITY_CANDIDATE,
            'an abstained record must be candidate even when the config opts in',
        )
        # D-11: the abstention omit family stays absent -- reportability_status
        # is deliberately NOT in it (present, valued candidate), but the
        # value-bearing fields it withholds must still be entirely missing.
        for omitted_key in (
            'value_low', 'value_base', 'value_high', 'bounds_source',
            'currency', 'estimated_value', 'assumptions',
        ):
            self.assertNotIn(
                omitted_key, record,
                f'D-11 omit family key {omitted_key!r} must be absent on an abstained record',
            )
        self.assertEqual(record['abstention_reason'], 'abstained')


if __name__ == '__main__':
    unittest.main()
