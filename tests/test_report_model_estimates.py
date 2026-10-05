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
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

# Module imports, not class imports: a TestCase class bound at module level is
# collected and re-run by unittest discovery.
from tests import test_phase38_reporter_path as p38
from tests import test_phase53_reportable_class_gate as p53
from tests import test_outcome_metrics_report as om

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



def _multiplexed_state_db(profile_config):
    """A build_state_db stand-in that makes the session belong to profile
    `other` (sessions.profile_name, as Phase 59 resolves it) and gives that
    profile its own state dir: markers/ and job-assessments/ link to the
    fixture's, so the reporter finds the same marker and sidecar through the
    profile path, while config.json is the profile's own."""
    def build(path, sessions):
        hermes_home = os.path.dirname(path)
        process_state = os.path.join(hermes_home, 'state', 'revenium')
        profile_state = os.path.join(hermes_home, 'profiles', 'other', 'state', 'revenium')
        os.makedirs(profile_state)
        for sub in ('markers', 'job-assessments'):
            os.symlink(os.path.join(process_state, sub), os.path.join(profile_state, sub))
        if profile_config is not None:
            with open(os.path.join(profile_state, 'config.json'), 'w') as f:
                json.dump(profile_config, f)
        conn = sqlite3.connect(path)
        conn.execute(
            'CREATE TABLE sessions (id TEXT, model TEXT, source TEXT, '
            'input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, '
            'cache_write_tokens INTEGER, reasoning_tokens INTEGER, '
            'estimated_cost_usd TEXT, api_call_count INTEGER, started_at REAL, '
            'ended_at REAL, billing_provider TEXT, profile_name TEXT)')
        for row in sessions:
            conn.execute(
                'INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (row['id'], row['model'], row['source'], row['input_tokens'],
                 row['output_tokens'], row['cache_read'], row['cache_write'],
                 row['reasoning'], row['estimated_cost'], row['api_calls'],
                 row['started_at'], row['ended_at'], row['billing_provider'], 'other'))
        conn.commit()
        conn.close()
    return build


class OwningProfileOptInTests(unittest.TestCase):
    """On a multiplexed host the reporter reads the opt-in from the profile
    that owns the session, never from the reporting process's config.json."""

    _run_one_outcome = p38.TestPhase38ReporterPath._run_one_outcome

    def _run(self, job, process_config, profile_config):
        with mock.patch.object(p38, 'build_state_db', _multiplexed_state_db(profile_config)):
            return self._run_one_outcome(
                f'{job}-sid', job, 'SUCCESS',
                sidecar=p38._sidecar_record(
                    job, reportability_status='reportable', evidence_class=MODEL),
                config=process_config,
            )

    def test_owning_profile_opted_in_process_not(self):
        argv = self._run('rme-mux-001', None, {'llmOutcomeEvaluation': OPTED_IN})
        self.assertEqual(argv[argv.index('--outcome-value') + 1], '446.25')

    def test_process_opted_in_owning_profile_not(self):
        argv = self._run('rme-mux-002', {'llmOutcomeEvaluation': OPTED_IN},
                         {'llmOutcomeEvaluation': {'experimentalReportEstimates': True}})
        self.assertNotIn('--outcome-value', argv)


class OutcomeMetricsOptInTests(om._Base):
    """outcome-metrics-report.sh selects sidecars by their STORED
    reportability_status. A model estimate made reportable while the switch
    was on must not reach that permanent append once it is off."""

    def _run_stage(self, config):
        with tempfile.TemporaryDirectory(prefix='rme-om-') as tmp:
            env, state_dir, bin_dir = self._env(tmp)
            self._shim(bin_dir, has_verb=True)
            self._assessment(state_dir)
            sidecar = os.path.join(state_dir, 'job-assessments', 'job-1.jsonl')
            rec = json.loads(open(sidecar).read())
            rec['evidence_class'] = MODEL
            with open(sidecar, 'w') as f:
                f.write(json.dumps(rec) + '\n')
            if config is not None:
                with open(os.path.join(state_dir, 'config.json'), 'w') as f:
                    json.dump(config, f)
            r = self._run(env)
            self.assertEqual(0, r.returncode, r.stderr)
            return self._ledger(state_dir)

    def test_opted_in_model_estimate_appends(self):
        self.assertEqual(4, len(self._run_stage({'llmOutcomeEvaluation': OPTED_IN})))

    def test_switched_off_model_estimate_appends_nothing(self):
        for config in (None, {'llmOutcomeEvaluation': {'experimentalReportEstimates': True}}):
            with self.subTest(config=config):
                self.assertEqual([], self._run_stage(config))


if __name__ == '__main__':
    unittest.main()
