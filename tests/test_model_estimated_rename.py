"""quick-261017-nck (LD-4): MODEL_ESTIMATED_DEMO was renamed MODEL_ESTIMATED.

Writers (the classifier package) emit only the new label. Readers
(hermes-report.sh, outcome-metrics-report.sh, BoundaryRegistry) accept both,
because job-assessments sidecars written before the rename are still on disk
and are hand-editable. The wire always carries the new label.

This module is the tracer slice: a legacy-label sidecar on disk goes through a
real hermes-report.sh tick and ships exactly what the new label ships. It
deliberately keeps the old label as a literal in exactly the places it puts a
legacy record on disk, and nowhere else.
"""
import ast
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Module imports, not class imports: a TestCase class bound at module level is
# collected and re-run by unittest discovery.
from tests import test_outcome_metrics_report as om
from tests import test_phase38_reporter_path as p38
from tests import test_phase53_reportable_class_gate as p53
from tests._compat_helpers import meta_path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'

NEW = 'MODEL_ESTIMATED'
LEGACY = 'MODEL_ESTIMATED_DEMO'
OPTED_IN = {'experimentalReportEstimates': True, 'reportModelEstimates': True}


def _wire_evidence(meta):
    """The evidence label as the --metadata blob carries it. The one place
    that knows the wire path of the label (v2: basis.evidence)."""
    return meta_path(meta, 'basis.evidence')


class _Runner:
    """Drive one real hermes-report.sh outcome tick and keep the cron log."""

    _run_one_outcome = p38.TestPhase38ReporterPath._run_one_outcome
    _metadata_value = staticmethod(p38.TestPhase38ReporterPath._metadata_value)

    def _tick(self, job, evidence_class, config, reportability='reportable'):
        """Return (argv, metering_log_text)."""
        logs = []
        real = p38.run_script

        def capturing(script_path, env, invocations_log):
            result = real(script_path, env, invocations_log)
            log_path = os.path.join(env['REVENIUM_STATE_DIR'], 'revenium-metering.log')
            try:
                with open(log_path) as f:
                    logs.append(f.read())
            except OSError:
                logs.append('')
            return result

        with mock.patch.object(p38, 'run_script', capturing):
            argv = self._run_one_outcome(
                f'{job}-sid', job, 'SUCCESS',
                sidecar=p38._sidecar_record(
                    job, reportability_status=reportability,
                    evidence_class=evidence_class),
                config=config,
            )
        return argv, '\n'.join(logs)


class LegacySidecarReaderTests(_Runner, unittest.TestCase):
    """hermes-report.sh reads a legacy-label sidecar exactly like a new one."""

    def test_legacy_label_opted_in_ships_value_and_the_new_label(self):
        argv, _ = self._tick('nck-job-001', LEGACY, {'llmOutcomeEvaluation': OPTED_IN})
        self.assertEqual(argv[argv.index('--outcome-value') + 1], '446.25')
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(_wire_evidence(meta), NEW)

    def test_legacy_and_new_label_ship_identical_argv(self):
        config = {'llmOutcomeEvaluation': OPTED_IN}
        legacy, _ = self._tick('nck-job-002', LEGACY, config)
        new, _ = self._tick('nck-job-002', NEW, config)
        self.assertEqual(legacy, new)

    def test_legacy_label_not_opted_in_withholds_value_but_keeps_provenance(self):
        argv, log = self._tick('nck-job-003', LEGACY, None)
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)
        meta = json.loads(self._metadata_value(argv))
        # Present, so the record was recognized, not refused as malformed.
        self.assertEqual(_wire_evidence(meta), NEW)
        self.assertIn('assessment unvalued (evidence_class_not_reportable)', log)
        self.assertNotIn('evidence_class unrecognized', log)

    def test_legacy_not_opted_in_matches_new_label_not_opted_in(self):
        legacy, _ = self._tick('nck-job-004', LEGACY, None)
        new, _ = self._tick('nck-job-004', NEW, None)
        self.assertEqual(legacy, new)

    def test_unhashable_evidence_class_is_rejected_without_crashing(self):
        argv, log = self._tick('nck-job-005', [LEGACY], {'llmOutcomeEvaluation': OPTED_IN})
        self.assertNotIn('--outcome-value', argv)
        self.assertIn('evidence_class unrecognized', log)

    def test_an_unknown_label_is_still_refused(self):
        argv, log = self._tick(
            'nck-job-006', 'MODEL_ESTIMATED_DEMO2', {'llmOutcomeEvaluation': OPTED_IN})
        self.assertNotIn('--outcome-value', argv)
        self.assertIn('evidence_class unrecognized', log)

    def test_legacy_label_on_a_candidate_record_still_ships_no_value(self):
        argv, _ = self._tick('nck-job-007', LEGACY, {'llmOutcomeEvaluation': OPTED_IN},
                             reportability='candidate')
        self.assertNotIn('--outcome-value', argv)


class OutcomeMetricsDualReadTests(om._Base):
    """outcome-metrics-report.sh treats the two labels as one class."""

    def _stage(self, label, config):
        with tempfile.TemporaryDirectory(prefix='nck-om-') as tmp:
            env, state_dir, bin_dir = self._env(tmp)
            self._shim(bin_dir, has_verb=True)
            self._assessment(state_dir)
            sidecar = os.path.join(state_dir, 'job-assessments', 'job-1.jsonl')
            rec = json.loads(open(sidecar).read())
            rec['evidence_class'] = label
            with open(sidecar, 'w') as f:
                f.write(json.dumps(rec) + '\n')
            if config is not None:
                with open(os.path.join(state_dir, 'config.json'), 'w') as f:
                    json.dump(config, f)
            r = self._run(env)
            self.assertEqual(0, r.returncode, r.stderr)
            return self._ledger(state_dir)

    def test_opted_in_appends_for_both_labels_identically(self):
        config = {'llmOutcomeEvaluation': OPTED_IN}
        legacy = self._stage(LEGACY, config)
        new = self._stage(NEW, config)
        self.assertEqual(4, len(new))
        self.assertEqual(len(new), len(legacy))

    def test_not_opted_in_appends_nothing_for_either_label(self):
        for label in (LEGACY, NEW):
            with self.subTest(label=label):
                self.assertEqual([], self._stage(label, None))
                self.assertEqual([], self._stage(
                    label, {'llmOutcomeEvaluation': {'experimentalReportEstimates': True}}))


class ClassifierLabelTests(unittest.TestCase):
    """The classifier package writes only the new label."""

    @classmethod
    def setUpClass(cls):
        cls.mod = p53._load_classifier()

    def test_constants_are_the_new_label(self):
        self.assertEqual(NEW, self.mod.EVIDENCE_CLASS_MODEL_ESTIMATED)
        self.assertEqual(NEW, self.mod._LLM_EVIDENCE_CLASS_LITERAL)
        self.assertEqual(NEW, self.mod._forced_evidence_class())

    def test_class_sets_keep_their_sizes(self):
        self.assertEqual(9, len(self.mod.EVIDENCE_CLASSES))
        self.assertIn(NEW, self.mod.EVIDENCE_CLASSES)
        self.assertNotIn(LEGACY, self.mod.EVIDENCE_CLASSES)
        self.assertEqual(6, len(self.mod._DECLARABLE_EVIDENCE_CLASSES))
        self.assertEqual(5, len(self.mod._REPORTABLE_EVIDENCE_CLASSES))
        self.assertNotIn(NEW, self.mod._REPORTABLE_EVIDENCE_CLASSES)

    def test_no_plugin_string_constant_carries_the_old_label(self):
        """AST, so a comment cannot satisfy it and a docstring cannot hide.
        boundary_registry.py is the one sanctioned holder (it normalizes the
        legacy declaration)."""
        offenders = []
        for path in sorted(PLUGIN_DIR.glob('*.py')):
            if path.name == 'boundary_registry.py':
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and LEGACY in node.value):
                    offenders.append(f'{path.name}:{node.lineno}')
        self.assertEqual([], offenders)


class BoundaryRegistryLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'nck_boundary_registry', str(PLUGIN_DIR / 'boundary_registry.py'))
        cls.br = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.br)

    def test_masquerade_class_is_the_new_label(self):
        self.assertEqual(NEW, self.br.MASQUERADE_CLASS)
        self.assertEqual(LEGACY, self.br.LEGACY_MASQUERADE_CLASS)

    def test_a_registrant_declaring_the_old_label_resolves_to_the_new_one(self):
        reg = self.br.BoundaryRegistry('b')
        reg.register('old', lambda: None, evidence_class=LEGACY)
        reg.register('new', lambda: None, evidence_class=NEW)
        reg.register('honest', lambda: None, evidence_class='CUSTOMER_CONFIGURED')
        self.assertEqual(NEW, reg.resolve_evidence_class('old'))
        self.assertTrue(self.br.is_masquerading(reg, 'old'))
        self.assertTrue(self.br.is_masquerading(reg, 'new'))
        self.assertFalse(self.br.is_masquerading(reg, 'honest'))


class ReporterAliasPairTests(unittest.TestCase):
    """The reader keeps one hand-synced alias dict per heredoc; Task 2 adds the
    second one in the outcome_metadata heredoc. Here: the sidecar reader's."""

    def test_sidecar_reader_declares_the_one_entry_alias(self):
        src = (ROOT / 'skills' / 'revenium' / 'scripts' / 'hermes-report.sh').read_text()
        m = re.search(r"_LEGACY_EVIDENCE_CLASS_ALIASES = (\{[^}]*\})", src)
        self.assertIsNotNone(m)
        self.assertEqual({LEGACY: NEW}, ast.literal_eval(m.group(1)))


if __name__ == '__main__':
    unittest.main()
