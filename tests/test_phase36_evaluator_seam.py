"""Phase 36 — the evaluator seam, the config gate, and the assessment contract.

Every test here runs OFFLINE. No provider, no network, no subprocess: the whole
point of phase 36 is that the contract and its validator exist and are exercised
before anything is able to call an LLM. A test in this file that needs a model
is a test in the wrong file.
"""

import importlib.util
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'


def _load_classifier(env: dict):
    """Import classifier.py fresh under `env`.

    Module-level path constants bind at import, so a test that changes
    REVENIUM_* must re-import rather than reassign — the same reason
    _module_paths() reads the globals live.
    """
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(
            'phase36_classifier', str(PLUGIN / 'classifier.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _load_evaluators():
    spec = importlib.util.spec_from_file_location(
        'phase36_evaluators', str(PLUGIN / 'evaluators.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GateTests(unittest.TestCase):
    """ROI-01 — the opt-in is off unless config.json says a literal true."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gsd-phase36-gate-')
        self.cfg = Path(self.tmp) / 'config.json'
        self.mod = _load_classifier({'REVENIUM_CONFIG_FILE': str(self.cfg)})

    def test_gate_fails_closed(self):
        """Every failure mode resolves to DISABLED.

        This is the deliberate inversion of _guardrail_halted, which fails OPEN
        so a never-installed cron never blocks work. Failing open here would
        estimate money by accident.
        """
        cases = [
            ('missing file', None),
            ('empty file', ''),
            ('invalid json', '{{{not json'),
            ('absent key', '{}'),
            ('null object', '{"llmOutcomeEvaluation":null}'),
            ('object not dict', '{"llmOutcomeEvaluation":"on"}'),
            ('enabled absent', '{"llmOutcomeEvaluation":{}}'),
            ('enabled false', '{"llmOutcomeEvaluation":{"enabled":false}}'),
            # Near-misses an operator could plausibly hand-edit. None may enable it.
            ('enabled "true" string', '{"llmOutcomeEvaluation":{"enabled":"true"}}'),
            ('enabled 1 int', '{"llmOutcomeEvaluation":{"enabled":1}}'),
            ('enabled "yes"', '{"llmOutcomeEvaluation":{"enabled":"yes"}}'),
        ]
        for name, body in cases:
            with self.subTest(name):
                if body is None:
                    if self.cfg.exists():
                        self.cfg.unlink()
                else:
                    self.cfg.write_text(body)
                self.assertFalse(
                    self.mod._llm_evaluation_enabled(),
                    f'{name} must NOT enable money estimation',
                )

    def test_gate_opens_only_on_literal_true(self):
        self.cfg.write_text('{"llmOutcomeEvaluation":{"enabled":true}}')
        self.assertTrue(self.mod._llm_evaluation_enabled())

    def test_config_object_is_returned_for_the_evaluator(self):
        self.cfg.write_text(
            '{"llmOutcomeEvaluation":{"enabled":true,"currency":"EUR","maxLoadedRate":200}}')
        cfg = self.mod._llm_evaluation_config()
        self.assertEqual('EUR', cfg.get('currency'))
        self.assertEqual(200, cfg.get('maxLoadedRate'))
        # A non-dict must degrade to {}, never raise into the caller.
        self.cfg.write_text('{"llmOutcomeEvaluation":[1,2,3]}')
        self.assertEqual({}, self.mod._llm_evaluation_config())


class PerProfileGateTests(unittest.TestCase):
    """ROI-01 — the gate resolves PER SESSION, not per process.

    _Paths is built positionally in _module_paths() and by keyword in
    _paths_for_session(). Adding config_file to only one of them regresses
    multiplexed profiles to the module paths with no error anywhere, which is
    exactly the failure this test exists to catch.
    """

    def test_profile_config_wins_over_module_config(self):
        tmp = tempfile.mkdtemp(prefix='gsd-phase36-profile-')
        home = Path(tmp) / '.hermes'
        module_state = home / 'state' / 'revenium'
        module_state.mkdir(parents=True)
        (module_state / 'config.json').write_text(
            '{"llmOutcomeEvaluation":{"enabled":false}}')

        profile_state = home / 'profiles' / 'gtm' / 'state' / 'revenium'
        profile_state.mkdir(parents=True)
        (profile_state / 'config.json').write_text(
            '{"llmOutcomeEvaluation":{"enabled":true}}')

        mod = _load_classifier({
            'HERMES_HOME': str(home),
            'REVENIUM_STATE_DIR': str(module_state),
            'REVENIUM_CONFIG_FILE': str(module_state / 'config.json'),
        })

        self.assertFalse(mod._llm_evaluation_enabled(),
                         'module-level config says false')
        paths = mod._paths_for_session('agent:gtm:sess-1')
        self.assertEqual(profile_state / 'config.json', paths.config_file,
                         'config_file must be populated by _paths_for_session')
        self.assertTrue(mod._llm_evaluation_enabled(paths=paths),
                        "the owning profile's config must win")


class RegistryTests(unittest.TestCase):
    """ROI-03 — a named evaluator resolves, with no LLM anywhere."""

    def setUp(self):
        self.ev = _load_evaluators()

    def test_resolve(self):
        self.assertIsNotNone(self.ev.resolve('stub'))
        self.assertIsNone(self.ev.resolve('nope'))
        self.assertIsNone(self.ev.resolve(None))
        self.assertIn('stub', self.ev.registered())

    def test_module_does_not_import_classifier(self):
        """The dependency runs one way so evaluators.py stays importable
        without Hermes' venv — the constraint that keeps call_llm lazy.

        Parsed with ast, not grepped. The module docstring DOCUMENTS this rule
        in prose ("must not import classifier.py"), so a substring search for
        'import classifier' matches the very comment explaining the invariant
        and fails on a compliant file.
        """
        import ast
        tree = ast.parse((PLUGIN / 'evaluators.py').read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split('.')[0])
        self.assertNotIn('classifier', imported)
        # The same rule that keeps call_llm lazy: no Hermes venv at module scope.
        self.assertNotIn('agent', imported)

    def test_stub_abstains_on_non_success(self):
        """ROI-09 — the caller short-circuits, but a boundary that cannot be
        trusted on its own is not much of a boundary."""
        stub = self.ev.resolve('stub')
        self.assertIsNone(stub({'status': 'FAILED'}, '', {}))
        self.assertIsNone(stub({'status': 'CANCELLED'}, '', {}))
        self.assertIsNotNone(stub({'status': 'SUCCESS'}, '', {}))


class ValidateAssessmentTests(unittest.TestCase):
    """ROI-04/ROI-05 — the contract, and the derivation."""

    def setUp(self):
        self.mod = _load_classifier({})

    def _raw(self, **over):
        raw = {
            'inferred_role': 'software engineer',
            'estimated_hours_saved': 2.5,
            'assumed_loaded_rate': 150.0,
            'currency': 'USD',
            'basis': 'engineer time avoided',
            'confidence': 0.5,
        }
        raw.update(over)
        return raw

    def test_accepts_and_derives(self):
        got = self.mod._validate_assessment(self._raw(), {}, 'stub', '1')
        self.assertEqual(375.0, got['estimated_value'])
        self.assertEqual('MODEL_ESTIMATED_DEMO', got['evidence_class'])
        self.assertEqual(2.5, got['assumptions']['estimated_hours_saved'])
        self.assertEqual('stub', got['evaluator'])

    def test_supplied_value_is_discarded(self):
        """ROI-05 — accepting a supplied total is the path that lets an
        unbounded number through while the bounds guard inputs nobody used."""
        got = self.mod._validate_assessment(
            self._raw(estimated_value=999999.0), {}, 'stub', '1')
        self.assertEqual(375.0, got['estimated_value'])

    def test_evidence_class_is_forced_not_read(self):
        """Provenance a model can assert is not provenance."""
        got = self.mod._validate_assessment(
            self._raw(evidence_class='CUSTOMER_CONFIRMED'), {}, 'stub', '1')
        self.assertEqual('MODEL_ESTIMATED_DEMO', got['evidence_class'])

    def test_bool_is_rejected_not_coerced(self):
        """isinstance(True, int) is True, so a naive check prices an hour of
        work off a type error."""
        self.assertIsNone(self.mod._validate_assessment(
            self._raw(estimated_hours_saved=True), {}, 'stub', '1'))

    def test_nan_and_inf_rejected(self):
        """`value > 0` is FALSE for NaN, so NaN slips any naive lower bound."""
        for bad in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(repr(bad)):
                self.assertIsNone(self.mod._validate_assessment(
                    self._raw(estimated_hours_saved=bad), {}, 'stub', '1'))
                self.assertIsNone(self.mod._validate_assessment(
                    self._raw(assumed_loaded_rate=bad), {}, 'stub', '1'))


class RejectionMatrixTests(unittest.TestCase):
    """ROI-06 — the full matrix. Every row must abstain."""

    def setUp(self):
        self.mod = _load_classifier({})

    def _raw(self, **over):
        raw = {'inferred_role': 'engineer', 'estimated_hours_saved': 2.5,
               'assumed_loaded_rate': 150.0, 'currency': 'USD',
               'basis': 'time avoided', 'confidence': 0.5}
        raw.update(over)
        return raw

    def test_numeric_field_matrix(self):
        bad = [float('nan'), float('inf'), float('-inf'), -1, 0,
               '2', True, False, None, [], {}]
        over = {'estimated_hours_saved': 41, 'assumed_loaded_rate': 501}
        for field in ('estimated_hours_saved', 'assumed_loaded_rate'):
            for v in bad + [over[field]]:
                with self.subTest(field=field, value=repr(v)):
                    self.assertIsNone(self.mod._validate_assessment(
                        self._raw(**{field: v}), {}, 'stub', '1'))

    def test_confidence_matrix(self):
        for v in (-0.01, 1.01, float('nan'), '0.5', None, True):
            with self.subTest(repr(v)):
                self.assertIsNone(self.mod._validate_assessment(
                    self._raw(confidence=v), {}, 'stub', '1'))

    def test_currency_matrix(self):
        for v, cfg, why in [
            ('US', {}, 'too short'),
            ('XYZ', {}, 'well-formed but not a real currency'),
            ('DOLLARS', {}, 'not a code'),
            (123, {}, 'not a string'),
            (None, {}, 'absent'),
            ('EUR', {'currency': 'USD'}, 'mismatches the configured currency'),
        ]:
            with self.subTest(f'{v!r} {why}'):
                self.assertIsNone(self.mod._validate_assessment(
                    self._raw(currency=v), cfg, 'stub', '1'))

    def test_currency_is_normalised_before_the_allow_list(self):
        """DEVIATION from the plan, recorded deliberately.

        The plan listed 'usd ' (whitespace) as a rejection row. Normalising
        first — strip + upper — then checking the allow-list is strictly safer
        than rejecting: the allow-list is the actual control, and refusing a
        whitespace-padded valid code buys nothing while making the demo brittle
        against a trailing space in a model response.
        """
        got = self.mod._validate_assessment(
            self._raw(currency=' usd '), {}, 'stub', '1')
        self.assertIsNotNone(got)
        self.assertEqual('USD', got['currency'])

    def test_structure_matrix(self):
        for v in (None, [], 'string', 42, {}, {'estimated_hours_saved': 2.5}):
            with self.subTest(repr(v)):
                self.assertIsNone(
                    self.mod._validate_assessment(v, {}, 'stub', '1'))

    def test_configured_bounds_override_defaults(self):
        cfg = {'maxHoursSaved': 1.0, 'maxLoadedRate': 100.0}
        self.assertIsNone(self.mod._validate_assessment(self._raw(), cfg, 'stub', '1'))
        ok = self.mod._validate_assessment(
            self._raw(estimated_hours_saved=0.5, assumed_loaded_rate=90.0),
            cfg, 'stub', '1')
        self.assertEqual(45.0, ok['estimated_value'])


class MarkerBudgetTests(unittest.TestCase):
    """ROI-12 — a maximally-clamped assessment marker fits the frozen budget."""

    def setUp(self):
        self.mod = _load_classifier({})

    def test_worst_case_marker_fits_1024_bytes(self):
        """Headroom is COMPUTED here, not hardcoded. If the base marker shape
        ever grows, this test must move with it rather than silently pass."""
        base = {'kind': 'job', 'ts': 1756000000.123456,
                'sid': '20260822_235959_' + 'a' * 8,
                'agentic_job_id': 'x' * 48 + '_a1b2',
                'job_name': 'y' * 60, 'job_type': 'bug_fix', 'status': 'SUCCESS'}
        base_bytes = len(json.dumps(base, separators=(',', ':'),
                                    ensure_ascii=True).encode()) + 1
        self.assertLess(base_bytes, 1024, 'base marker already over budget')

        worst = self.mod._validate_assessment({
            'inferred_role': 'r' * 200,          # over the clamp on purpose
            'estimated_hours_saved': 40.0,       # max bound
            'assumed_loaded_rate': 500.0,        # max bound
            'currency': 'USD',
            'basis': 'b' * 1000,                 # far over the clamp
            'confidence': 0.999999,
        }, {}, 'evaluator-name-long', 'version-long')
        self.assertIsNotNone(worst, 'max-bound inputs must be accepted, not rejected')

        full = dict(base, assessment=worst)
        total = len(json.dumps(full, separators=(',', ':'),
                               ensure_ascii=True).encode()) + 1
        self.assertLess(total, 1024,
                        f'marker with a maximally-clamped assessment is {total} bytes')
        # Record the margin so a future reader sees how much room is left.
        self.assertGreater(1024 - total, 100,
                           'under 100 bytes of margin — re-derive the clamps')

    def test_ifs_characters_are_stripped(self):
        """T-36-06 (high). Phase 38's outcome queue is IFS='|'-parsed; one pipe
        reaching that tuple shifts every following field. Mitigated at the
        producer, not at each consumer."""
        got = self.mod._validate_assessment({
            'inferred_role': 'a|b\nc\rd',
            'estimated_hours_saved': 2.0, 'assumed_loaded_rate': 100.0,
            'currency': 'USD', 'basis': 'x|y\nz', 'confidence': 0.5,
        }, {}, 'stub|evil', '1\n2')
        blob = json.dumps(got)
        for bad in ('|', '\\n', '\\r'):
            self.assertNotIn(bad, blob, f'{bad!r} survived into the assessment')


class DisabledPathTests(unittest.TestCase):
    """ROI-02 — with evaluation off, the marker is what it always was.

    Phase 36 wires no call site (that is phase 37), so this asserts the writer's
    output shape rather than an end-to-end flow. It is the tripwire that catches
    an `assessment` key leaking into a disabled-path marker later.
    """

    def test_job_marker_carries_no_assessment_key(self):
        tmp = tempfile.mkdtemp(prefix='gsd-phase36-disabled-')
        markers = Path(tmp) / 'markers'
        mod = _load_classifier({
            'REVENIUM_STATE_DIR': tmp,
            'REVENIUM_MARKERS_DIR': str(markers),
        })
        job = {'agentic_job_id': 'fix_thing_a1b2', 'job_name': 'Fix thing',
               'job_type': 'bug_fix', 'status': 'SUCCESS', 'failure_reason': ''}
        path = mod._write_job_marker('sess-1', job)
        record = json.loads(path.read_text().strip())

        self.assertNotIn('assessment', record,
                         'a disabled-path marker must not carry an assessment')
        self.assertEqual(
            {'kind', 'ts', 'sid', 'agentic_job_id', 'job_name', 'job_type', 'status'},
            set(record),
            'the frozen Phase 7 D-03 job-marker key set changed',
        )
        self.assertLess(len(path.read_text().encode()), 1024)


if __name__ == '__main__':
    unittest.main()
