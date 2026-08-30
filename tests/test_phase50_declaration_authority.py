"""Phase 50 Plan 01 -- Declaration Authority: the cross-boundary
evidence_class precedence walk (DECL-01/DECL-02/DECL-05), proven end to
end from a configured boundary declaration through to the `--metadata`
wire, plus the walk's own behavior at both record sites.

Task 1 checkpoint decision "option-b" (recorded in 50-01-SUMMARY.md, see
also the dated amendment 50-04 owes to docs/evidence-class-precedence.md):
the walk is FOUR legs, fixed order `evidence` > `valuation` >
`classification` > `evaluator` -- not the three-leg walk
docs/evidence-class-precedence.md originally locked. Two facts drove the
widening: (1) the evidence boundary's own built-in default registrant
always declares the forced constant (classifier.py, `config_opt_in`),
which masked every lower-priority boundary on 100% of installs under a
literal "first non-empty" reading; (2) `ACTIVITY_MEASURED` is declared
only on the `classification` boundary (classification.py), which the
locked three-boundary rule never consulted at all.

`TracerEndToEndTests` proves the whole vertical slice: a configured
boundary declaration reaches classifier.py's `_build_job_assessment`
record, and that record's `evidence_class_authority` survives into the
REAL `hermes-report.sh` `outcome_metadata` heredoc's `--metadata` object
-- reusing tests/test_phase46_metadata_envelope.py's own extraction
harness rather than reimplementing it, per this plan's own instruction.

`PrecedenceWalkTests` proves the walk's behavior at record site 1
(`_validate_assessment`), including the N=2 successive-config
state-non-carrying case and the single-resolution property DECL-02
requires, plus the static call-site-count backstop for the single-rule-site
property.

Every test here runs OFFLINE, matching every other Phase 45/46 test
module's own posture: no provider, no network, no subprocess except the
one real python3 subprocess `TracerEndToEndTests` spawns to run the
extracted heredoc body (mirroring test_phase46_metadata_envelope.py's own
`_run_forwarder`).
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
HERMES_REPORT_SH = ROOT / 'skills' / 'revenium' / 'scripts' / 'hermes-report.sh'
CLASSIFIER_SOURCE_PATH = PLUGIN / 'classifier.py'

from tests.test_phase46_metadata_envelope import (  # noqa: E402
    _assessment_env,
    _extract_outcome_metadata_heredoc,
    _run_forwarder,
)


def _load_classifier(env: "dict | None" = None):
    """Mirror of every other Phase 45 test file's own `_load_classifier`
    (test_phase45_valuation_boundary.py, test_phase45_boundary_registry.py,
    etc.) -- duplicated here, not imported, because the loader mutates
    `os.environ` around a fresh module load and each file owns its own
    copy rather than sharing one across modules."""
    env = env or {}
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(
            'phase50_classifier_declaration_authority', str(CLASSIFIER_SOURCE_PATH))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _write_config(config_path: Path, boundaries=None, rate_card=None):
    cfg = {}
    if boundaries is not None:
        cfg['boundaries'] = boundaries
    if rate_card is not None:
        cfg['llmOutcomeEvaluation'] = {'rateCard': rate_card}
    config_path.write_text(json.dumps(cfg))


def _find_function_def(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _count_boundary_impl_name_calls(func_node, boundary_key):
    """Count calls to `_boundary_impl_name(boundary_key, ...)` inside
    `func_node`'s own body (ast.walk includes nested nodes but this file
    declares no nested function defs inside either record site, so this
    stays scoped to the one function)."""
    count = 0
    for node in ast.walk(func_node):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == '_boundary_impl_name'
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == boundary_key
        ):
            count += 1
    return count


class _DeclarationAuthorityTestCase(unittest.TestCase):
    """Shared sys.path management and fixture helpers -- mirrors
    tests/test_phase45_valuation_boundary.py's `_ValuationBoundaryTestCase`
    exactly: PLUGIN on sys.path so classifier.py's bare `import valuation`/
    `import evidence`/`import classification`/`import evaluators` fallback
    (the standalone-load path every Phase 45 test file already exercises)
    resolves to the real shipped fixtures."""

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
        self.tmp = tempfile.mkdtemp(prefix='gsd-p50-01-declaration-authority-')
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

    def _valid_job(self, job_id='p50-job-001'):
        return {
            'agentic_job_id': job_id, 'job_name': 'n', 'job_type': 'bug_fix',
            'status': 'SUCCESS',
        }


class TracerEndToEndTests(_DeclarationAuthorityTestCase):
    """DECL-01/DECL-02/DECL-05, Task 2 <behavior> -- the whole vertical
    slice, config to wire, on ONE configuration before any horizontal
    expansion (per this plan's own objective)."""

    def test_configured_evidence_boundary_reaches_the_record_with_its_authority(self):
        mod = self._load(boundaries={'evidence': 'confirmation_workflow_evidence_fixture'})
        cfg = mod._llm_evaluation_config()
        raw = self._raw()
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        record = mod._build_job_assessment(
            self._valid_job('p50-evidence-001'), validated, raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(record)
        self.assertEqual('CUSTOMER_CONFIRMED', record['evidence_class'])
        self.assertEqual('evidence', record['evidence_class_authority'])

    def test_no_boundaries_object_is_model_estimated_demo_with_evaluator_authority(self):
        mod = self._load(boundaries=None)
        cfg = mod._llm_evaluation_config()
        raw = self._raw()
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        record = mod._build_job_assessment(
            self._valid_job('p50-default-001'), validated, raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(record)
        self.assertEqual('MODEL_ESTIMATED_DEMO', record['evidence_class'])
        # Task 2 <behavior> pin: the all-forced fallback authority is
        # 'evaluator', asserted explicitly so the default arm is pinned
        # rather than incidental.
        self.assertEqual('evaluator', record['evidence_class_authority'])

    def test_evidence_class_authority_survives_into_the_real_metadata_wire(self):
        mod = self._load(boundaries={'evidence': 'confirmation_workflow_evidence_fixture'})
        cfg = mod._llm_evaluation_config()
        raw = self._raw()
        validated = mod._validate_assessment(raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(validated)
        record = mod._build_job_assessment(
            self._valid_job('p50-wire-001'), validated, raw, cfg, 'stub', 'v1')
        self.assertIsNotNone(record)

        script_text = HERMES_REPORT_SH.read_text()
        body = _extract_outcome_metadata_heredoc(script_text)
        self.assertIsNotNone(body, 'the outcome_metadata heredoc anchor moved')
        result = _run_forwarder(body, _assessment_env(record))
        self.assertEqual(0, result.returncode, result.stderr)
        meta = json.loads(result.stdout.strip())
        self.assertEqual('evidence', meta.get('evidence_class_authority'))
        self.assertEqual('CUSTOMER_CONFIRMED', meta.get('evidence_class'))

    def test_out_of_set_evidence_class_authority_is_dropped_not_forwarded(self):
        script_text = HERMES_REPORT_SH.read_text()
        body = _extract_outcome_metadata_heredoc(script_text)
        self.assertIsNotNone(body)
        record = {
            'evidence_class': 'MODEL_ESTIMATED_DEMO',
            'evidence_class_authority': 'attacker-supplied',
        }
        result = _run_forwarder(body, _assessment_env(record))
        self.assertEqual(0, result.returncode, result.stderr)
        meta = json.loads(result.stdout.strip())
        self.assertNotIn('evidence_class_authority', meta)
        # The record's evidence_class itself still ships -- an out-of-set
        # authority word is a correctness bug in ONE field, not a reason to
        # withhold the rest of the row.
        self.assertEqual('MODEL_ESTIMATED_DEMO', meta.get('evidence_class'))

    def test_absent_evidence_class_authority_key_adds_no_key_to_metadata(self):
        script_text = HERMES_REPORT_SH.read_text()
        body = _extract_outcome_metadata_heredoc(script_text)
        self.assertIsNotNone(body)
        record = {'evidence_class': 'MODEL_ESTIMATED_DEMO'}
        result = _run_forwarder(body, _assessment_env(record))
        self.assertEqual(0, result.returncode, result.stderr)
        meta = json.loads(result.stdout.strip())
        self.assertNotIn('evidence_class_authority', meta)

    def test_declared_evidence_class_single_argument_calls_unchanged(self):
        """The five calls tests/test_phase45_boundary_registry.py:264-284
        asserts, byte-identical after the widened signature -- the three
        new parameters all default to "" so a one-argument call is
        unaffected (D-02's explicit compatibility requirement)."""
        mod = self._load(boundaries=None)
        forced = mod._forced_evidence_class()
        self.assertEqual('MODEL_ESTIMATED_DEMO', mod._declared_evidence_class('llm'))
        self.assertEqual('MODEL_ESTIMATED_DEMO', mod._declared_evidence_class('stub'))
        self.assertEqual(forced, mod._declared_evidence_class('never-registered'))
        self.assertEqual(forced, mod._declared_evidence_class(None))
        self.assertEqual(forced, mod._declared_evidence_class(42))


class PrecedenceWalkTests(_DeclarationAuthorityTestCase):
    """DECL-01/DECL-02, Task 3 <behavior> -- the walk's behavior at record
    site 1 (`_validate_assessment`), the N=2 successive-config case, and
    the single-resolution / single-rule-site backstops."""

    def test_evidence_boundary_wins_outright(self):
        mod = self._load(boundaries={'evidence': 'confirmation_workflow_evidence_fixture'})
        cfg = mod._llm_evaluation_config()
        got = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertEqual('CUSTOMER_CONFIRMED', got['evidence_class'])
        self.assertEqual('evidence', got['evidence_class_authority'])

    def test_valuation_boundary_wins_when_evidence_is_at_its_default(self):
        """Fact 1's masking is actually gone: the evidence boundary's
        built-in default declares the forced constant (no vote), so the
        walk falls through to valuation, which is not forced."""
        mod = self._load(
            boundaries={'valuation': 'rate_card_valuation_fixture'},
            rate_card={'senior_engineer': 480.0},
        )
        cfg = mod._llm_evaluation_config()
        got = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertEqual('CUSTOMER_CONFIGURED', got['evidence_class'])
        self.assertEqual('valuation', got['evidence_class_authority'])

    def test_no_boundaries_object_is_byte_identical_to_pre_phase_50(self):
        mod = self._load(boundaries=None)
        cfg = mod._llm_evaluation_config()
        got = mod._validate_assessment(self._raw(), cfg, 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertEqual('MODEL_ESTIMATED_DEMO', got['evidence_class'])

    def test_validate_assessment_resolves_valuation_impl_name_exactly_once(self):
        """Task 3 Test 4: the existing resolution at _validate_assessment's
        own valuation-derivation step is REUSED for the precedence walk,
        never re-resolved -- DECL-02's single-resolution intent for this
        function. AST-counted, not grepped, so a comment mentioning the
        boundary key cannot produce a false pass or fail."""
        tree = ast.parse(CLASSIFIER_SOURCE_PATH.read_text())
        func = _find_function_def(tree, '_validate_assessment')
        self.assertIsNotNone(func, '_validate_assessment not found in classifier.py')
        count = _count_boundary_impl_name_calls(func, 'valuation')
        self.assertEqual(
            1, count,
            f'_validate_assessment calls _boundary_impl_name("valuation", ...) '
            f'{count} times; expected exactly 1 -- the resolution must be reused, '
            'not duplicated',
        )

    def test_two_successive_calls_with_different_boundaries_configs_n2_no_cross_call_state(self):
        """N=2, state-carrying case (CONTEXT.md's own constraint): two
        successive _validate_assessment calls in the SAME process, the
        second with a DIFFERENT boundaries config, each return the class
        matching their OWN config -- no value is cached across calls."""
        mod_a = self._load(boundaries={'evidence': 'confirmation_workflow_evidence_fixture'})
        cfg_a = mod_a._llm_evaluation_config()
        got_a = mod_a._validate_assessment(self._raw(), cfg_a, 'stub', 'v1')
        self.assertIsNotNone(got_a)
        self.assertEqual('CUSTOMER_CONFIRMED', got_a['evidence_class'])

        # A second, freshly-loaded module (a distinct config.json, a
        # distinct boundaries object) -- proves no module-level or
        # process-level cache carries the first call's winner forward.
        second_config = Path(self.tmp) / 'config2.json'
        _write_config(second_config, boundaries=None)
        mod_b = _load_classifier({'REVENIUM_CONFIG_FILE': str(second_config)})
        cfg_b = mod_b._llm_evaluation_config()
        got_b = mod_b._validate_assessment(self._raw(), cfg_b, 'stub', 'v1')
        self.assertIsNotNone(got_b)
        self.assertEqual('MODEL_ESTIMATED_DEMO', got_b['evidence_class'])
        self.assertNotEqual(got_a['evidence_class'], got_b['evidence_class'])

        # And the FIRST module, called again with the SAME config, still
        # returns its own answer unchanged -- the walk is a pure function
        # of its inputs, not of call order.
        got_a_again = mod_a._validate_assessment(self._raw(), cfg_a, 'stub', 'v1')
        self.assertIsNotNone(got_a_again)
        self.assertEqual(got_a['evidence_class'], got_a_again['evidence_class'])
        self.assertEqual(
            got_a['evidence_class_authority'], got_a_again['evidence_class_authority'])

    def test_evidence_class_precedence_call_site_count_is_stable(self):
        """DECL-02 backstop (must_haves precision item): the single-rule-
        site property survives a future edit -- exactly ONE FunctionDef
        named _evidence_class_precedence, and exactly THREE call sites
        (the delegation inside _declared_evidence_class, plus one call at
        EACH of the two record sites). A third record site calling this
        function, or a second inline walk, would change this count and
        fail this test loudly rather than silently drift."""
        tree = ast.parse(CLASSIFIER_SOURCE_PATH.read_text())
        defs = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == '_evidence_class_precedence'
        ]
        self.assertEqual(1, len(defs), 'expected exactly one _evidence_class_precedence def')
        calls = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == '_evidence_class_precedence'
        ]
        self.assertEqual(
            3, len(calls),
            f'expected 3 call sites (the _declared_evidence_class delegation '
            f'plus one at each of the two record sites), found {len(calls)}',
        )


class AuthorityWordClampTests(unittest.TestCase):
    """DECL-05 precision backstop (must_haves): the 16-byte clamp on
    evidence_class_authority (hermes-report.sh's forwarder) cannot truncate
    a legal value. Asserted against classifier.py's own live
    _EVIDENCE_CLASS_AUTHORITIES enum, never against a hardcoded width --
    if a future fifth authority word is added, this test fails loudly
    rather than letting the wire silently truncate it.

    Under the Task 1 "option-b" decision the longest member is
    'classification' at 14 bytes -- 2 bytes of headroom under the 16-byte
    clamp. That margin is intentionally noted here as thin: a sixth
    boundary joining the walk with a name longer than 16 bytes would need
    either a shorter authority word or a widened clamp, not a silent
    truncation.
    """

    def test_every_authority_word_fits_the_16_byte_clamp(self):
        mod = _load_classifier()
        authorities = mod._EVIDENCE_CLASS_AUTHORITIES
        self.assertEqual(4, len(authorities), 'option-b widens the walk to four authorities')
        longest = max(authorities, key=lambda w: len(w.encode('utf-8')))
        self.assertLessEqual(
            len(longest.encode('utf-8')), 16,
            f'{longest!r} ({len(longest.encode("utf-8"))} bytes) would be truncated by '
            "hermes-report.sh's 16-byte evidence_class_authority clamp",
        )

    def test_declarable_evidence_classes_excludes_the_three_causal_impact_labels(self):
        mod = _load_classifier()
        for reserved in ('ASSOCIATIONAL', 'QUASI_EXPERIMENTAL_IMPACT', 'EXPERIMENTAL_IMPACT'):
            self.assertNotIn(reserved, mod._DECLARABLE_EVIDENCE_CLASSES)
        self.assertEqual(6, len(mod._DECLARABLE_EVIDENCE_CLASSES))


if __name__ == '__main__':
    unittest.main()
