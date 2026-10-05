"""llmOutcomeEvaluation.reportModelEstimates -- the explicit opt-in that lets a
MODEL_ESTIMATED_DEMO value onto the wire.

Phase 53 (ROI-01) withholds every model estimate's value at two enforcement
points: classifier.py, which writes reportability_status, and hermes-report.sh,
which re-checks the evidence class before shipping. An install with no
customer-supplied rates, revenue cards or confirmations therefore ships no value
at all. This switch admits the model class at both points, and only when it and
experimentalReportEstimates are both the literal JSON boolean true.

The default is unchanged: test_phase53_reportable_class_gate.py's hostile
configs, none of which name this key, still resolve to candidate.
"""
import json
import unittest

# Module imports, not class imports: a TestCase class bound at module level is
# collected and re-run by unittest discovery.
from tests import test_phase38_reporter_path as p38
from tests import test_phase53_reportable_class_gate as p53

MODEL = 'MODEL_ESTIMATED_DEMO'
OPTED_IN = {'experimentalReportEstimates': True, 'reportModelEstimates': True}


class ClassifierOptInTests(unittest.TestCase):
    """Enforcement point 1: classifier.py writes reportable only on the opt-in."""

    def setUp(self):
        self.mod = p53._load_classifier()

    def _status(self, cfg, abstained=False, evidence_class=MODEL):
        return self.mod._resolve_reportability_status(
            cfg, abstained, evidence_class=evidence_class)

    def test_both_switches_true_make_a_model_estimate_reportable(self):
        self.assertEqual(self.mod.REPORTABILITY_REPORTABLE, self._status(OPTED_IN))

    def test_reportModelEstimates_alone_is_not_enough(self):
        for cfg in (
            {'reportModelEstimates': True},
            {'reportModelEstimates': True, 'experimentalReportEstimates': False},
        ):
            with self.subTest(cfg=cfg):
                self.assertEqual(self.mod.REPORTABILITY_CANDIDATE, self._status(cfg))

    def test_near_miss_values_do_not_opt_in(self):
        for value in ('true', 1, 'yes', [True]):
            cfg = {'experimentalReportEstimates': True, 'reportModelEstimates': value}
            with self.subTest(value=value):
                self.assertEqual(self.mod.REPORTABILITY_CANDIDATE, self._status(cfg))

    def test_abstention_still_wins(self):
        self.assertEqual(
            self.mod.REPORTABILITY_CANDIDATE, self._status(OPTED_IN, abstained=True))

    def test_opt_in_admits_only_the_model_class(self):
        """Malformed and causal-impact classes stay refused under the opt-in."""
        for cls in (None, 'NOT_A_CLASS', 'EXPERIMENTAL_IMPACT', 'ASSOCIATIONAL'):
            with self.subTest(evidence_class=cls):
                self.assertEqual(
                    self.mod.REPORTABILITY_CANDIDATE,
                    self._status(OPTED_IN, evidence_class=cls))

    def test_permitted_set_itself_is_unchanged(self):
        self.assertNotIn(MODEL, self.mod._REPORTABLE_EVIDENCE_CLASSES)
        self.assertEqual(5, len(self.mod._REPORTABLE_EVIDENCE_CLASSES))


class ReporterOptInTests(unittest.TestCase):
    """Enforcement point 2: hermes-report.sh ships the value only on the opt-in,
    read from config.json at report time."""

    _run_one_outcome = p38.TestPhase38ReporterPath._run_one_outcome
    _metadata_value = staticmethod(p38.TestPhase38ReporterPath._metadata_value)

    def _run(self, job, config, reportability='reportable'):
        return self._run_one_outcome(
            f'{job}-sid', job, 'SUCCESS',
            sidecar=p38._sidecar_record(
                job, reportability_status=reportability, evidence_class=MODEL),
            config=config,
        )

    def test_opted_in_ships_the_low_bound_and_keeps_its_provenance(self):
        argv = self._run('rme-job-001', {'llmOutcomeEvaluation': OPTED_IN})
        self.assertEqual(argv[argv.index('--outcome-value') + 1], '446.25')
        self.assertEqual(argv[argv.index('--outcome-currency') + 1], 'USD')
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta.get('evidence_class'), MODEL)
        self.assertEqual(meta.get('value_low'), 446.25)

    def test_without_the_opt_in_the_value_is_withheld_but_provenance_ships(self):
        for config in (
            None,
            {'llmOutcomeEvaluation': {'experimentalReportEstimates': True}},
            {'llmOutcomeEvaluation': {'experimentalReportEstimates': True,
                                      'reportModelEstimates': 'true'}},
            {'reportModelEstimates': True, 'experimentalReportEstimates': True},
        ):
            with self.subTest(config=config):
                argv = self._run('rme-job-002', config)
                self.assertNotIn('--outcome-value', argv)
                self.assertNotIn('--outcome-currency', argv)
                meta = json.loads(self._metadata_value(argv))
                self.assertEqual(meta.get('evidence_class'), MODEL)
                self.assertNotIn('value_low', meta)

    def test_opt_in_does_not_promote_a_candidate_record(self):
        """The reporter only obeys reportability_status; the switch alone does
        not make a candidate record ship its value."""
        argv = self._run('rme-job-003', {'llmOutcomeEvaluation': OPTED_IN},
                         reportability='candidate')
        self.assertNotIn('--outcome-value', argv)


if __name__ == '__main__':
    unittest.main()
