"""Phase 53 (ROI-01): the evidence-class gate on value reporting.

WHAT THIS PHASE CHANGED, and why it needed a gate at all.

`experimentalReportEstimates` used to be the whole reportability rule: set it
and a value crossed the wire. That was safe while nobody set it -- and nobody
ever did, on any live host, which is why no live record before this phase ever
carried a value. Turning it on for real exposed the actual problem:

`revenium jobs roi <id>` surfaces NO evidence_class, NO evaluator and NO
confidence, in either its JSON or its table output. That is established by live
verification against a real tenant and recorded in
docs/claim-distinctions-and-evidence-boundaries.md. A model-estimated value
displayed there is visually indistinguishable from a measured one.

So the gate: a value may reach the wire only when something other than a model
constituted it. `MODEL_ESTIMATED_DEMO` -- the one label meaning "a model guessed
this" -- is refused.

THIS IS A PARTITION, NOT A RANKING. EGV-10 (D-01) forbids treating the nine
labels as a confidence ladder and nothing here does. The five permitted classes
are not claimed to be stronger than each other, nor is the refused one claimed
to be weakest. The single property separating them is whether a model, and only
a model, is the basis -- a membership question, never an ordering one.

Guarantee class (43-VALIDATION.md's honesty rule): these tests are BEHAVIOURAL
except where a docstring says otherwise. They prove the two enforcement points
withhold the value on the paths exercised here. The divergence guard is
STATIC-class: it proves the two lists agree in today's source, not that they
cannot ever diverge.
"""

import importlib.util
import json
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'
HERMES_REPORT_PATH = ROOT / 'skills' / 'revenium' / 'scripts' / 'hermes-report.sh'


def _load_classifier():
    spec = importlib.util.spec_from_file_location(
        'phase53_classifier', str(PLUGIN / 'classifier.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PermittedSetTests(unittest.TestCase):
    """The set itself: derived, five members, and refusing the right one."""

    def setUp(self):
        self.mod = _load_classifier()

    def test_permitted_set_is_exactly_the_declarable_six_minus_the_forced_constant(self):
        """The set is DERIVED, never hand-listed.

        Load-bearing: a hand-listed copy is a third list to keep in sync in a
        codebase that already hand-syncs two, and it can silently drift from
        the vocabulary. Deriving means a change to the declarable set
        propagates instead of rotting.
        """
        expected = (
            self.mod._DECLARABLE_EVIDENCE_CLASSES
            - {self.mod.EVIDENCE_CLASS_MODEL_ESTIMATED}
        )
        self.assertEqual(expected, self.mod._REPORTABLE_EVIDENCE_CLASSES)

    def test_the_five_permitted_members(self):
        self.assertEqual(
            {'ACTIVITY_MEASURED', 'OUTPUT_OBSERVED', 'OUTCOME_OBSERVED',
             'CUSTOMER_CONFIGURED', 'CUSTOMER_CONFIRMED'},
            set(self.mod._REPORTABLE_EVIDENCE_CLASSES),
        )

    def test_model_estimated_demo_is_refused(self):
        self.assertNotIn(
            self.mod.EVIDENCE_CLASS_MODEL_ESTIMATED,
            self.mod._REPORTABLE_EVIDENCE_CLASSES,
        )

    def test_causal_impact_labels_are_absent(self):
        """Already undeclarable; a record carrying one is malformed, and a
        malformed record must not ship a value either."""
        for label in ('ASSOCIATIONAL', 'QUASI_EXPERIMENTAL_IMPACT',
                      'EXPERIMENTAL_IMPACT'):
            with self.subTest(label=label):
                self.assertNotIn(label, self.mod._REPORTABLE_EVIDENCE_CLASSES)

    def test_no_config_key_can_widen_the_set(self):
        """D-02: not operator-widenable, by construction.

        A value-reporting gate an operator can configure away is not a gate.
        Every permitted class must resolve reportable and MODEL_ESTIMATED_DEMO
        must not, under configs that variously try to widen it.
        """
        hostile_cfgs = (
            {'experimentalReportEstimates': True},
            {'experimentalReportEstimates': True,
             'reportableEvidenceClasses': ['MODEL_ESTIMATED_DEMO']},
            {'experimentalReportEstimates': True,
             'reportable_evidence_classes': ['MODEL_ESTIMATED_DEMO']},
            {'experimentalReportEstimates': True,
             'evidenceClasses': ['MODEL_ESTIMATED_DEMO']},
        )
        for cfg in hostile_cfgs:
            with self.subTest(cfg=cfg):
                self.assertEqual(
                    self.mod.REPORTABILITY_CANDIDATE,
                    self.mod._resolve_reportability_status(
                        cfg, False, evidence_class='MODEL_ESTIMATED_DEMO'),
                )


class ClassifierGateTests(unittest.TestCase):
    """Enforcement point 1: the classifier refuses to WRITE reportable."""

    def setUp(self):
        self.mod = _load_classifier()
        self.cfg = {'experimentalReportEstimates': True}

    def test_each_permitted_class_reaches_reportable(self):
        for cls in sorted(self.mod._REPORTABLE_EVIDENCE_CLASSES):
            with self.subTest(evidence_class=cls):
                self.assertEqual(
                    self.mod.REPORTABILITY_REPORTABLE,
                    self.mod._resolve_reportability_status(
                        self.cfg, False, evidence_class=cls),
                )

    def test_model_estimated_demo_does_not(self):
        self.assertEqual(
            self.mod.REPORTABILITY_CANDIDATE,
            self.mod._resolve_reportability_status(
                self.cfg, False, evidence_class='MODEL_ESTIMATED_DEMO'),
        )

    def test_omitted_evidence_class_fails_closed(self):
        """Fail-CLOSED, deliberately against this module's usual posture.

        Everywhere else a missing input degrades to "no enforcement". Here
        degrading would mean shipping a value onto a surface that cannot say
        where it came from, so the safe direction is to withhold. Nothing is
        lost but the value: `candidate` still ships full provenance.
        """
        self.assertEqual(
            self.mod.REPORTABILITY_CANDIDATE,
            self.mod._resolve_reportability_status(self.cfg, False),
        )

    def test_abstention_still_wins_and_runs_first(self):
        """Composition with the pre-existing abstention rule.

        Phase 52 found LIVE that a rejected record still carries an evidence
        class -- CUSTOMER_CONFIGURED with estimated_value None. Both rules now
        apply to such a record; abstention must still decide it.
        """
        self.assertEqual(
            self.mod.REPORTABILITY_CANDIDATE,
            self.mod._resolve_reportability_status(
                self.cfg, True, evidence_class='CUSTOMER_CONFIGURED'),
        )

    def test_a_registered_boundary_cannot_return_its_way_past_the_gate(self):
        """THE ADVERSARIAL CASE (ROI-01's prohibition).

        A registered evidence implementation that returns `reportable` for a
        MODEL_ESTIMATED_DEMO record must not obtain it. This is the
        elevation-of-privilege the gate's position exists to prevent: it is
        checked unconditionally BEFORE any implementation is consulted, so a
        registrant has no path to it.
        """
        mod = self.mod
        # classifier.py imports evidence.py via a relative-then-absolute
        # two-step that only resolves when the plugin dir is importable.
        # Loading it directly here mirrors what the classifier gets at
        # runtime; the test is about the gate, not about that import dance.
        spec = importlib.util.spec_from_file_location(
            'phase53_evidence', str(PLUGIN / 'evidence.py'))
        evidence_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(evidence_mod)
        self.assertIsNotNone(evidence_mod, 'evidence module must load')

        def _hostile(request, config):
            return {'reportability_status': 'reportable'}

        evidence_mod.register('phase53_hostile', _hostile, version='v1')
        original = mod._boundary_impl_name
        original_loader = mod._load_evidence_module
        try:
            mod._boundary_impl_name = (
                lambda kind, default, paths=None:
                'phase53_hostile' if kind == 'evidence' else default)
            mod._load_evidence_module = lambda: evidence_mod
            self.assertEqual(
                mod.REPORTABILITY_CANDIDATE,
                mod._resolve_reportability_status(
                    self.cfg, False, evidence_class='MODEL_ESTIMATED_DEMO'),
                'a registered implementation obtained reportable for a '
                'model-estimated record -- the gate was reached around',
            )
            # Control: the same hostile impl on a PERMITTED class still works,
            # proving the refusal above came from the class gate and not from
            # the hostile registration simply failing to resolve.
            self.assertEqual(
                mod.REPORTABILITY_REPORTABLE,
                mod._resolve_reportability_status(
                    self.cfg, False, evidence_class='CUSTOMER_CONFIGURED'),
            )
        finally:
            mod._boundary_impl_name = original
            mod._load_evidence_module = original_loader

    def test_end_to_end_record_construction_refuses_the_naked_llm_path(self):
        """Through the REAL construction path, not the resolver alone.

        The naked-LLM evaluator forces MODEL_ESTIMATED_DEMO, so a record built
        this way can never be reportable however the config is set.
        """
        mod = self.mod
        raw = {
            'economic_mechanism': 'labor_substitution',
            'inferred_role': 'senior software engineer',
            'estimated_hours_saved': 3.5,
            'assumed_loaded_rate': 150.0,
            'currency': 'USD',
            'basis': '3.5 hours of senior engineer review time',
            'confidence': 0.8,
            'candidate_downstream_outcome': 'PR merged to main',
            'counterfactual_assumption': 'a human would have taken the same time',
        }
        valid = {'agentic_job_id': 'p53-gate-001', 'job_type': 'code_review',
                 'status': 'SUCCESS'}
        assessment = mod._validate_assessment(raw, {}, 'llm', 'v1')
        self.assertIsNotNone(assessment)
        record = mod._build_job_assessment(
            valid, assessment, raw, {'experimentalReportEstimates': True},
            'llm', 'v1')
        self.assertIsNotNone(record)
        self.assertEqual('MODEL_ESTIMATED_DEMO', record['evidence_class'])
        self.assertEqual(mod.REPORTABILITY_CANDIDATE,
                         record['reportability_status'])
        # Provenance is KEPT. Withholding the value must not withhold the fact
        # that an estimate happened.
        self.assertEqual('llm', record['evaluator'])
        self.assertIn('evidence_class', record)


class ReporterGateTests(unittest.TestCase):
    """Enforcement point 2, and the divergence guard (D-01)."""

    def setUp(self):
        self.source = HERMES_REPORT_PATH.read_text()
        self.mod = _load_classifier()

    def test_reporter_declares_its_own_permitted_set(self):
        self.assertIn('_REPORTABLE_EVIDENCE_CLASSES = frozenset({', self.source)

    def test_the_two_enforcement_points_do_not_diverge(self):
        """STATIC-class guard (D-01): one rule, two enforcement points.

        The reporter cannot import from classifier.py -- the plugin/script
        boundary forbids it, which is why this file's own C-02 comment accepts
        a duplication. A duplication that can drift silently is worse than no
        duplication at all, so this test is what makes the pair safe: it fails
        the moment the two lists disagree.
        """
        block = re.search(
            r'_REPORTABLE_EVIDENCE_CLASSES = frozenset\(\{(.*?)\}\)',
            self.source, re.S)
        self.assertIsNotNone(block, 'reporter permitted set not found')
        reporter_set = set(re.findall(r"'([A-Z_]+)'", block.group(1)))
        self.assertEqual(
            set(self.mod._REPORTABLE_EVIDENCE_CLASSES), reporter_set,
            'hermes-report.sh and classifier.py disagree about which evidence '
            'classes may carry a value onto the wire',
        )

    def test_recognized_but_unreportable_class_keeps_its_provenance(self):
        """The asymmetry between the two refusal branches is deliberate.

        An UNRECOGNIZED class is evidence of a malformed record, so the claim
        itself is popped. A model-estimated class is an honest claim that may
        not carry a value -- so evidence_class is KEPT and only the value is
        stripped. A branch that popped it would destroy provenance the
        milestone depends on.
        """
        branch = self.source[self.source.index(
            "elif _raw_evidence_class not in _REPORTABLE_EVIDENCE_CLASSES:"):]
        branch = branch[:branch.index('# Phase 42 (C-04)')]
        self.assertIn('_strip_value_family(found)', branch)
        self.assertIn("_not_reportable_reason = 'evidence_class_not_reportable'",
                      branch)
        self.assertNotIn("found.pop('evidence_class'", branch)


if __name__ == '__main__':
    unittest.main()
