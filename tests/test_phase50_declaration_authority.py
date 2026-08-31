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
from tests.test_phase43_evidence_grading import _hostile_evaluator_response  # noqa: E402


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


# -- Plan 50-02, Task 1: Falsifier 1's adversarial fixture -----------------
#
# The volatile keys _build_job_assessment stamps from the clock at
# construction time -- excluded before comparing two records for equality,
# because two REAL calls a few microseconds apart will never agree on
# these even when every declaration-bearing field is identical. None of
# these keys is what DECL-03 is about; `job_started_at`/`job_ended_at` fall
# back to `time.time()` per _build_job_assessment's own docstring (and are
# copied verbatim into `observation_window_start`/`observation_window_end`
# in the record literal), and `ts` is stamped fresh on every call.
_VOLATILE_RECORD_KEYS = (
    'ts', 'job_started_at', 'job_ended_at',
    'observation_window_start', 'observation_window_end',
)


def _stable_record_view(record):
    return {k: v for k, v in record.items() if k not in _VOLATILE_RECORD_KEYS}


def _hostile_boundary_response():
    """`_hostile_evaluator_response()`'s eight attacks (imported, not
    copied -- a copied attack fixture is the fixture-fidelity defect this
    repo has hit four times in three phases) plus FIVE more attack keys
    named after the four-leg walk's own new inputs and its provenance
    output: `valuation_declared`, `evidence_declared`,
    `evidence_class_authority`, `boundaries`, `boundary_impl`. An attacker
    naming a key after a resolved-declaration parameter, or after the
    config surface that selects a boundary implementation, is exactly the
    "smuggle a declaration through raw" attack DECL-03 exists to refuse --
    none of these five keys is ever read off `raw` by the real
    implementation; they are attack surface, not configuration.
    """
    hostile = dict(_hostile_evaluator_response())
    hostile.update({
        'valuation_declared': 'EXPERIMENTAL_IMPACT',
        'evidence_declared': 'CUSTOMER_CONFIRMED',
        'evidence_class_authority': 'evidence',
        'boundaries': {'evidence': 'confirmation_workflow_evidence_fixture'},
        'boundary_impl': 'confirmation_workflow_evidence_fixture',
    })
    return hostile


# A throwaway valuation registrant declaring one of the three reserved
# causal-impact labels (Test 3 / A10) -- mirrors
# tests/test_phase45_valuation_boundary.py's own
# `_rate_card_valuation_fixture` shape exactly (same assumptions keys, same
# None-on-abstain contract) so the hostile fixture's hours/rate/currency
# price cleanly through it.
_CAUSAL_LABEL_THROWAWAY_SEQ = [0]


def _causal_label_valuation_fixture(assumptions: dict, config: dict):
    try:
        a = assumptions if isinstance(assumptions, dict) else {}
        hours = a.get('estimated_hours_saved')
        rate = a.get('assumed_loaded_rate')
        if not isinstance(hours, (int, float)) or not isinstance(rate, (int, float)):
            return None
        if isinstance(hours, bool) or isinstance(rate, bool) or hours <= 0 or rate <= 0:
            return None
        return {'estimated_value': round(hours * rate, 2), 'currency': a.get('currency')}
    except Exception:
        return None


class PromotionUnderPrecedenceTests(_DeclarationAuthorityTestCase):
    """Falsifier 1's adversarial fixture (docs/evidence-class-precedence.md
    :342-368), proven against the REAL `_validate_assessment` ->
    `_build_job_assessment` construction path under the four-leg
    precedence walk built in 50-01. Six cases: the base eight-attack
    fixture under the new rule (Test 1, A1), the same fixture additionally
    naming the walk's own new inputs as attack keys (Test 2, A9), a
    trusted registrant declaring a causal-impact label selected via
    `boundaries.valuation` (Test 3, A10), the authority field itself as an
    attack surface (Test 4), and the N=2 / N=3 state-carrying cases
    CONTEXT.md requires be written explicitly.

    This class COLLECTS EVIDENCE for the Task 3 checkpoint. It does not
    decide anything. If a test fails, the failure is Falsifier 1 firing --
    it is recorded verbatim in the SUMMARY and named in the checkpoint;
    no implementation file is edited in response to a failure here.
    """

    def _run_hostile(self, mod, raw, job_id='p50-hostile-001',
                      evaluator='stub-evaluator', version='v1'):
        """Mirrors PromotionTests.setUp's own shape
        (tests/test_phase43_evidence_grading.py:646-663): assert ACCEPTED
        before asserting anything about the record -- an attack that lands
        on the abstention path proves only that abstention works, not that
        acceptance resists promotion."""
        cfg = mod._llm_evaluation_config()
        validated = mod._validate_assessment(raw, cfg, evaluator, version)
        self.assertIsNotNone(
            validated,
            'the hostile fixture must be ACCEPTED for this test to be '
            'meaningful -- an attack that lands on the abstention path '
            'proves only that abstention works, not that acceptance '
            'resists promotion',
        )
        record = mod._build_job_assessment(
            self._valid_job(job_id), validated, raw, cfg, evaluator, version)
        self.assertIsNotNone(record)
        return record

    def _register_causal_label_valuation(self):
        _CAUSAL_LABEL_THROWAWAY_SEQ[0] += 1
        name = f'p50_causal_ceiling_{_CAUSAL_LABEL_THROWAWAY_SEQ[0]}'
        import valuation as val  # type: ignore  # PLUGIN is on sys.path (setUpClass)
        val.register(name, _causal_label_valuation_fixture, '1',
                      evidence_class='EXPERIMENTAL_IMPACT')
        self.addCleanup(val._REGISTRY._entries.pop, name, None)
        return name

    # -- Test 1 (A1 under the new rule) -------------------------------------

    def test_1_eight_attack_fixture_under_default_boundaries_is_forced(self):
        mod = self._load(boundaries=None)
        record = self._run_hostile(mod, _hostile_evaluator_response())
        self.assertEqual(record['evidence_class'], mod.EVIDENCE_CLASS_MODEL_ESTIMATED)

    # -- Test 2 (A9, new -- the walk's own new inputs as an attack surface) -

    def test_2_hostile_response_naming_the_walks_own_inputs_is_unchanged(self):
        mod = self._load(boundaries=None)
        baseline = self._run_hostile(
            mod, _hostile_evaluator_response(), job_id='p50-a9-shared-job-id')
        attacked = self._run_hostile(
            mod, _hostile_boundary_response(), job_id='p50-a9-shared-job-id')
        self.assertEqual(_stable_record_view(baseline), _stable_record_view(attacked))

    # -- Test 3 (A10, new -- the causal ceiling) -----------------------------

    def test_3_causal_impact_declaration_via_valuation_boundary_is_refused(self):
        name = self._register_causal_label_valuation()
        mod = self._load(boundaries={'valuation': name})
        record = self._run_hostile(mod, _hostile_evaluator_response())
        self.assertEqual('MODEL_ESTIMATED_DEMO', record['evidence_class'])
        # The all-forced fallback authority is 'evaluator' -- never
        # 'valuation' with a causal label smuggled through.
        self.assertEqual('evaluator', record['evidence_class_authority'])
        self.assertNotEqual('EXPERIMENTAL_IMPACT', record['evidence_class'])

    # -- Test 4 (the authority field is not an attack surface) --------------

    def test_4_authority_field_spoof_is_ignored_absent_a_real_declaration(self):
        mod = self._load(boundaries=None)
        record = self._run_hostile(mod, _hostile_boundary_response())
        self.assertEqual('evaluator', record['evidence_class_authority'])
        self.assertNotEqual('evidence', record['evidence_class_authority'])

    # -- Test 5 (N=2) ---------------------------------------------------------

    def test_5_two_hostile_responses_back_to_back_n2_no_cross_call_leak(self):
        mod_a = self._load(boundaries={'evidence': 'confirmation_workflow_evidence_fixture'})
        record_a = self._run_hostile(mod_a, _hostile_evaluator_response(), job_id='p50-n2-a')
        self.assertEqual('CUSTOMER_CONFIRMED', record_a['evidence_class'])
        self.assertEqual('evidence', record_a['evidence_class_authority'])

        second_config = Path(self.tmp) / 'config-n2-b.json'
        _write_config(second_config, boundaries=None)
        mod_b = _load_classifier({'REVENIUM_CONFIG_FILE': str(second_config)})
        record_b = self._run_hostile(mod_b, _hostile_evaluator_response(), job_id='p50-n2-b')
        self.assertEqual('MODEL_ESTIMATED_DEMO', record_b['evidence_class'])
        self.assertEqual('evaluator', record_b['evidence_class_authority'])
        self.assertNotEqual(record_a['evidence_class'], record_b['evidence_class'])

    # -- Test 6 (N=3) ---------------------------------------------------------

    def test_6_three_successive_hostile_responses_n3_each_gets_its_own_config(self):
        mod_evidence = self._load(
            boundaries={'evidence': 'confirmation_workflow_evidence_fixture'})
        record_1 = self._run_hostile(
            mod_evidence, _hostile_evaluator_response(), job_id='p50-n3-evidence')
        self.assertEqual('CUSTOMER_CONFIRMED', record_1['evidence_class'])
        self.assertEqual('evidence', record_1['evidence_class_authority'])

        valuation_config = Path(self.tmp) / 'config-n3-valuation.json'
        _write_config(
            valuation_config,
            boundaries={'valuation': 'rate_card_valuation_fixture'},
            # 'senior engineer' matches _hostile_evaluator_response()'s own
            # inferred_role value exactly.
            rate_card={'senior engineer': 480.0},
        )
        mod_valuation = _load_classifier({'REVENIUM_CONFIG_FILE': str(valuation_config)})
        record_2 = self._run_hostile(
            mod_valuation, _hostile_evaluator_response(), job_id='p50-n3-valuation')
        self.assertEqual('CUSTOMER_CONFIGURED', record_2['evidence_class'])
        self.assertEqual('valuation', record_2['evidence_class_authority'])

        evaluator_config = Path(self.tmp) / 'config-n3-evaluator.json'
        _write_config(evaluator_config, boundaries=None)
        mod_evaluator = _load_classifier({'REVENIUM_CONFIG_FILE': str(evaluator_config)})
        record_3 = self._run_hostile(
            mod_evaluator, _hostile_evaluator_response(), job_id='p50-n3-evaluator')
        self.assertEqual('MODEL_ESTIMATED_DEMO', record_3['evidence_class'])
        self.assertEqual('evaluator', record_3['evidence_class_authority'])

        # None of the three leaks into either of the others.
        self.assertNotEqual(record_1['evidence_class'], record_2['evidence_class'])
        self.assertNotEqual(record_2['evidence_class'], record_3['evidence_class'])
        self.assertNotEqual(record_1['evidence_class'], record_3['evidence_class'])


# -- Plan 50-02, Task 2: the replacement structural guarantee, made checkable --

class SignatureGuardTests(unittest.TestCase):
    """Task 2 -- the replacement structural guarantee (DECL-03 restated for
    the widened, four-parameter signature), made checkable by four
    independent static properties. Each has its own test method so a
    failure names the property, not a line number.

    Written against the LIVE tree, per this plan's own instruction to
    follow the tree rather than stale prose: 50-02-PLAN.md's Task 2 text
    describes `_evidence_class_precedence` as declaring its three new
    parameters "without defaults." The built function defaults all three
    to `""`, identically to `_declared_evidence_class`
    (classifier.py:1210-1278) -- its own docstring (D-03) explains this
    keeps `_declared_evidence_class` a call-compatible one-line delegator.
    Property 1 below asserts the parameter NAME list and ORDER exactly (an
    add, a rename, or a re-order turns it red); it does not assert the
    plan's now-superseded "no defaults" claim about
    `_evidence_class_precedence`, because that claim is false against the
    tree this task must guard.
    """

    EXPECTED_PARAM_ORDER = (
        'evaluator', 'valuation_declared', 'evidence_declared', 'classification_declared',
    )
    _RULE_FUNCTIONS = ('_declared_evidence_class', '_evidence_class_precedence')

    @staticmethod
    def _tree():
        return ast.parse(CLASSIFIER_SOURCE_PATH.read_text())

    @staticmethod
    def _func(tree, name):
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        return None

    @staticmethod
    def _ends_in_resolve_evidence_class_call(node):
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'resolve_evidence_class'
        )

    @classmethod
    def _is_boundary_declaration_expr(cls, value):
        """True when `value` is a Call ending in `.resolve_evidence_class(...)`,
        or the `X if Y is not None else ""` ternary idiom every call site in
        classifier.py uses to guard a possibly-None boundary module --
        `body` must be such a call and `orelse` must be the empty-string
        fallback, never anything else."""
        if cls._ends_in_resolve_evidence_class_call(value):
            return True
        if isinstance(value, ast.IfExp):
            return (
                cls._ends_in_resolve_evidence_class_call(value.body)
                and isinstance(value.orelse, ast.Constant)
                and value.orelse.value == ''
            )
        return False

    # -- Property 1: the parameter list is exactly what D-02 specified. -----

    def test_property_1_parameter_list_matches_d02_exactly_for_both_functions(self):
        tree = self._tree()
        for name in self._RULE_FUNCTIONS:
            func = self._func(tree, name)
            self.assertIsNotNone(func, f'{name} not found in classifier.py')
            arg_names = tuple(a.arg for a in func.args.args)
            self.assertEqual(
                self.EXPECTED_PARAM_ORDER, arg_names,
                f'{name} parameter list drifted from D-02\'s widened '
                f'signature: {arg_names!r}',
            )
            self.assertEqual(
                3, len(func.args.defaults),
                f'{name} must default its three new parameters to ""',
            )
            for default in func.args.defaults:
                self.assertIsInstance(default, ast.Constant)
                self.assertEqual('', default.value)

    # -- Property 2: neither function can see evaluator output. -------------

    def test_property_2_neither_function_declares_or_references_raw(self):
        tree = self._tree()
        for name in self._RULE_FUNCTIONS:
            func = self._func(tree, name)
            self.assertIsNotNone(func, f'{name} not found in classifier.py')
            arg_names = {a.arg for a in func.args.args}
            self.assertNotIn(
                'raw', arg_names,
                f'{name} must never declare a parameter named "raw"',
            )
            raw_name_refs = [
                node for node in ast.walk(func)
                if isinstance(node, ast.Name) and node.id == 'raw'
            ]
            self.assertEqual(
                [], raw_name_refs,
                f'{name} body contains a reference to a name literally called '
                '"raw" -- the untrusted evaluator response must never be in '
                'scope here',
            )

    # -- Property 3: every call-site argument traces to a name lookup or a --
    # -- registry lookup. -----------------------------------------------------

    def test_property_3_call_site_arguments_trace_to_a_name_or_a_boundary_lookup(self):
        tree = self._tree()
        for site_name in ('_validate_assessment', '_build_job_assessment'):
            func = self._func(tree, site_name)
            self.assertIsNotNone(func, f'{site_name} not found in classifier.py')
            enclosing_params = {a.arg for a in func.args.args}
            calls = [
                node for node in ast.walk(func)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == '_evidence_class_precedence'
            ]
            self.assertEqual(
                1, len(calls),
                f'{site_name} must call _evidence_class_precedence exactly '
                f'once, found {len(calls)}',
            )
            for arg in calls[0].args:
                self._assert_argument_traces_to_a_boundary_lookup(
                    arg, func, enclosing_params, site_name)

    def _assert_argument_traces_to_a_boundary_lookup(self, arg, func, enclosing_params, site_name):
        # Reject outright, anywhere inside the argument expression: a
        # subscript of `raw` or a `.get(...)` call on `raw` -- defense in
        # depth on top of the Name-only shape check below, matching the
        # plan's own explicit call-out of these two idioms.
        for node in ast.walk(arg):
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id == 'raw'
            ):
                self.fail(
                    f'{site_name}: an _evidence_class_precedence argument '
                    f'subscripts raw directly -- {ast.dump(arg)}')
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'get'
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == 'raw'
            ):
                self.fail(
                    f'{site_name}: an _evidence_class_precedence argument '
                    f'calls raw.get(...) directly -- {ast.dump(arg)}')

        if isinstance(arg, ast.Name) and arg.id == 'evaluator':
            self.assertIn(
                'evaluator', enclosing_params,
                f'{site_name} passes a Name "evaluator" that is not its own '
                'parameter',
            )
            return

        self.assertIsInstance(
            arg, ast.Name,
            f'{site_name}: _evidence_class_precedence argument is not a '
            f'plain name -- {ast.dump(arg)}',
        )
        assigns = [
            node for node in ast.walk(func)
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == arg.id for t in node.targets)
        ]
        self.assertTrue(
            assigns,
            f'{site_name}: no assignment found for local {arg.id!r} passed '
            'to _evidence_class_precedence',
        )
        for assign in assigns:
            self.assertTrue(
                self._is_boundary_declaration_expr(assign.value),
                f'{site_name}: {arg.id!r} is assigned from an expression '
                f'that is not a resolve_evidence_class(...) chain -- '
                f'{ast.dump(assign.value)}',
            )

    # -- Property 4: there is exactly one rule site. -------------------------

    def test_property_4_exactly_one_rule_site_and_no_shadow_walk_elsewhere(self):
        tree = self._tree()
        defs = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == '_evidence_class_precedence'
        ]
        self.assertEqual(1, len(defs), 'expected exactly one _evidence_class_precedence def')
        rule_site = defs[0]

        watch_names = {'evidence_declared', 'valuation_declared', 'evaluator'}
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node is rule_site:
                continue
            referenced = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Compare):
                    for operand in [sub.left] + list(sub.comparators):
                        for name_node in ast.walk(operand):
                            if isinstance(name_node, ast.Name):
                                referenced.add(name_node.id)
            if watch_names.issubset(referenced):
                offenders.append(node.name)
        self.assertEqual(
            [], offenders,
            f'function(s) {offenders!r} contain a comparison chain over all '
            f'three of {sorted(watch_names)} -- a second inlined precedence walk?',
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


# -- Plan 50-03, Task 2: conflict determinism at N=2/N=3, and every ---------
# -- Phase 48 boundary case --------------------------------------------------
#
# `_RATE_CARD_FOR_RAW` matches `_DeclarationAuthorityTestCase._raw()`'s own
# `inferred_role` value ('senior_engineer') exactly, so
# `rate_card_valuation_fixture` never abstains in any test below that
# configures it. `_causal_label_valuation_fixture` (defined above, for
# 50-02's Falsifier 3 fixture) is REUSED here rather than re-defined -- an
# unconditional hours*rate valuation fixture with no evidence_class opinion
# of its own, so it can be registered under whatever declared class a given
# boundary-case test needs, per this plan's own instruction not to retype a
# fixture that already exists in this file.

_RATE_CARD_FOR_RAW = {'senior_engineer': 480.0}

_THROWAWAY_REGISTRANT_SEQ = [0]


def _next_throwaway_name(prefix):
    _THROWAWAY_REGISTRANT_SEQ[0] += 1
    return f'{prefix}_{_THROWAWAY_REGISTRANT_SEQ[0]}'


class ConflictDeterminismTests(_DeclarationAuthorityTestCase):
    """ROADMAP criterion 4 / DECL-04 (adjacency, ordering): the conflict
    rule is deterministic at N=2 (all three pairings) and N=3, output does
    not depend on dict iteration order or call sequence, and the walk never
    sorts, ranks, or order-compares two label strings. Registers a
    throwaway valuation fixture declaring CUSTOMER_CONFIRMED for the
    identical-declarations style checks this class also needs, mirroring
    `PromotionUnderPrecedenceTests._register_causal_label_valuation`'s own
    register/addCleanup shape.
    """

    def _register_valuation_declaring(self, evidence_class):
        name = _next_throwaway_name('p50_03_conflict_valuation')
        import valuation as val  # type: ignore  # PLUGIN is on sys.path (setUpClass)
        val.register(name, _causal_label_valuation_fixture, '1', evidence_class=evidence_class)
        self.addCleanup(val._REGISTRY._entries.pop, name, None)
        return name

    # -- N=2, all three pairings (CONTEXT.md: write every pairing, not one) -

    def test_n2_case_a_evidence_beats_valuation(self):
        valuation_name = self._register_valuation_declaring('CUSTOMER_CONFIGURED')
        mod = self._load(
            boundaries={
                'evidence': 'confirmation_workflow_evidence_fixture',
                'valuation': valuation_name,
            },
        )
        got = mod._validate_assessment(self._raw(), mod._llm_evaluation_config(), 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertEqual('CUSTOMER_CONFIRMED', got['evidence_class'])
        self.assertEqual('evidence', got['evidence_class_authority'])

    def test_n2_case_b_valuation_beats_evaluator(self):
        mod = self._load(
            boundaries={'valuation': 'rate_card_valuation_fixture'},
            rate_card=_RATE_CARD_FOR_RAW,
        )
        got = mod._validate_assessment(
            self._raw(), mod._llm_evaluation_config(),
            'system_of_record_assessment_fixture', 'v1',
        )
        self.assertIsNotNone(got)
        self.assertEqual('CUSTOMER_CONFIGURED', got['evidence_class'])
        self.assertEqual('valuation', got['evidence_class_authority'])

    def test_n2_case_c_evidence_beats_evaluator(self):
        mod = self._load(boundaries={'evidence': 'confirmation_workflow_evidence_fixture'})
        got = mod._validate_assessment(
            self._raw(), mod._llm_evaluation_config(),
            'system_of_record_assessment_fixture', 'v1',
        )
        self.assertIsNotNone(got)
        self.assertEqual('CUSTOMER_CONFIRMED', got['evidence_class'])
        self.assertEqual('evidence', got['evidence_class_authority'])

    # -- N=3: all three declare different non-forced classes ----------------

    def test_n3_all_three_declare_different_classes_evidence_wins(self):
        mod = self._load(
            boundaries={
                'evidence': 'confirmation_workflow_evidence_fixture',
                'valuation': 'rate_card_valuation_fixture',
            },
            rate_card=_RATE_CARD_FOR_RAW,
        )
        validated = mod._validate_assessment(
            self._raw(), mod._llm_evaluation_config(),
            'system_of_record_assessment_fixture', 'v1',
        )
        self.assertIsNotNone(validated)
        record = mod._build_job_assessment(
            self._valid_job('p50-03-n3-job'), validated, self._raw(),
            mod._llm_evaluation_config(), 'system_of_record_assessment_fixture', 'v1',
        )
        self.assertIsNotNone(record)
        self.assertEqual('CUSTOMER_CONFIRMED', record['evidence_class'])
        self.assertEqual('evidence', record['evidence_class_authority'])
        # The two losing declarations appear NOWHERE in the record -- not
        # merely "did not win the evidence_class field."
        self.assertNotIn('CUSTOMER_CONFIGURED', record.values())
        self.assertNotIn('OUTCOME_OBSERVED', record.values())

    # -- Determinism: repeated runs and reversed config key order -----------

    def test_determinism_across_repeated_runs_and_reversed_config_key_order(self):
        boundaries = {
            'evidence': 'confirmation_workflow_evidence_fixture',
            'valuation': 'rate_card_valuation_fixture',
        }
        results = []
        for _ in range(3):
            mod = self._load(boundaries=boundaries, rate_card=_RATE_CARD_FOR_RAW)
            got = mod._validate_assessment(
                self._raw(), mod._llm_evaluation_config(),
                'system_of_record_assessment_fixture', 'v1',
            )
            self.assertIsNotNone(got)
            results.append((got['evidence_class'], got['evidence_class_authority']))
        self.assertEqual(1, len(set(results)), f'non-deterministic across repeated runs: {results}')

        reversed_boundaries = {
            'valuation': 'rate_card_valuation_fixture',
            'evidence': 'confirmation_workflow_evidence_fixture',
        }
        mod_rev = self._load(boundaries=reversed_boundaries, rate_card=_RATE_CARD_FOR_RAW)
        got_rev = mod_rev._validate_assessment(
            self._raw(), mod_rev._llm_evaluation_config(),
            'system_of_record_assessment_fixture', 'v1',
        )
        self.assertIsNotNone(got_rev)
        self.assertEqual(
            results[0], (got_rev['evidence_class'], got_rev['evidence_class_authority']),
            'result depends on the boundaries dict key order in config.json',
        )

    # -- No ordering: the walk never sorts, ranks, or order-compares labels -

    def test_no_ordering_or_ranking_of_label_strings_in_the_walk(self):
        tree = ast.parse(CLASSIFIER_SOURCE_PATH.read_text())
        func = _find_function_def(tree, '_evidence_class_precedence')
        self.assertIsNotNone(func, '_evidence_class_precedence not found in classifier.py')
        for node in ast.walk(func):
            if (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in ('sorted', 'max', 'min')
            ):
                self.fail(
                    f'_evidence_class_precedence calls {node.func.id}(...) -- '
                    'labels must never be sorted or ranked (classifier.py:1076-1099)'
                )
            if isinstance(node, ast.Compare):
                for op in node.ops:
                    if isinstance(op, (ast.Lt, ast.Gt, ast.LtE, ast.GtE)):
                        self.fail(
                            '_evidence_class_precedence contains an order comparison '
                            '(<, >, <=, >=) -- labels must never be order-compared '
                            '(classifier.py:1076-1099)'
                        )


class BoundaryCaseTests(_DeclarationAuthorityTestCase):
    """One test per Phase 48 'Boundary cases' named case
    (docs/evidence-class-precedence.md:296-320): identical declarations,
    the two absent-declaration shapes, all-absent, and exactly-one-
    declares. A failure here names the case, not a row number.
    """

    def _register_valuation_declaring(self, evidence_class):
        name = _next_throwaway_name('p50_03_boundarycase_valuation')
        import valuation as val  # type: ignore  # PLUGIN is on sys.path (setUpClass)
        val.register(name, _causal_label_valuation_fixture, '1', evidence_class=evidence_class)
        self.addCleanup(val._REGISTRY._entries.pop, name, None)
        return name

    def _register_evidence_declaring_empty(self):
        """Absent shape (b): a registrant declaring a literal '' -- Phase 48
        explicitly records no fixture in this tree has ever done this, so
        this test CREATES the case rather than finding it. The registered
        fn (the real confirmation-workflow fixture) is never called by
        `_validate_assessment`/`_build_job_assessment` for this boundary --
        only its registration-time declared class is resolved -- so reusing
        it here changes nothing observable but the declared label."""
        name = _next_throwaway_name('p50_03_boundarycase_evidence_empty')
        import evidence as evd  # type: ignore  # PLUGIN is on sys.path (setUpClass)
        evd.register(
            name, evd._confirmation_workflow_evidence_fixture, '1', evidence_class='',
        )
        self.addCleanup(evd._REGISTRY._entries.pop, name, None)
        return name

    # -- Identical declarations: not a conflict ------------------------------

    def test_identical_declarations_same_class_two_boundaries_not_a_conflict(self):
        """Two active boundaries (evidence, valuation) declare the SAME
        non-forced class (CUSTOMER_CONFIRMED) -- the walk stops at the
        higher-priority one (evidence), the recorded class is that shared
        value, and the recorded authority NAMES evidence, not valuation --
        asserted, not inferred."""
        valuation_name = self._register_valuation_declaring('CUSTOMER_CONFIRMED')
        mod = self._load(
            boundaries={
                'evidence': 'confirmation_workflow_evidence_fixture',
                'valuation': valuation_name,
            },
        )
        got = mod._validate_assessment(self._raw(), mod._llm_evaluation_config(), 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertEqual('CUSTOMER_CONFIRMED', got['evidence_class'])
        self.assertEqual('evidence', got['evidence_class_authority'])

    # -- Absent shape (a): an unregistered configured impl name --------------

    def test_absent_shape_a_unregistered_impl_name_casts_no_vote(self):
        mod = self._load(
            boundaries={
                'evidence': 'no_such_registrant_at_all_p50_03',
                'valuation': 'rate_card_valuation_fixture',
            },
            rate_card=_RATE_CARD_FOR_RAW,
        )
        got = mod._validate_assessment(self._raw(), mod._llm_evaluation_config(), 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertEqual('CUSTOMER_CONFIGURED', got['evidence_class'])
        self.assertEqual('valuation', got['evidence_class_authority'])

    # -- Absent shape (b): a registrant declaring a literal '' ---------------

    def test_absent_shape_b_registrant_declares_literal_empty_string_casts_no_vote(self):
        evidence_name = self._register_evidence_declaring_empty()
        mod = self._load(
            boundaries={
                'evidence': evidence_name,
                'valuation': 'rate_card_valuation_fixture',
            },
            rate_card=_RATE_CARD_FOR_RAW,
        )
        got = mod._validate_assessment(self._raw(), mod._llm_evaluation_config(), 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertEqual('CUSTOMER_CONFIGURED', got['evidence_class'])
        self.assertEqual('valuation', got['evidence_class_authority'])

    # -- All-absent: forced fallback, authority 'evaluator' -------------------

    def test_all_absent_no_boundary_votes_yields_forced_fallback(self):
        mod = self._load(boundaries=None)
        got = mod._validate_assessment(self._raw(), mod._llm_evaluation_config(), 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertEqual('MODEL_ESTIMATED_DEMO', got['evidence_class'])
        self.assertEqual('evaluator', got['evidence_class_authority'])

    # -- Exactly-one-declares: that class, that authority, no conflict shape -

    def test_exactly_one_declares_wins_outright_with_no_conflict_recorded(self):
        mod = self._load(boundaries={'evidence': 'confirmation_workflow_evidence_fixture'})
        got = mod._validate_assessment(self._raw(), mod._llm_evaluation_config(), 'stub', 'v1')
        self.assertIsNotNone(got)
        self.assertEqual('CUSTOMER_CONFIRMED', got['evidence_class'])
        self.assertEqual('evidence', got['evidence_class_authority'])
        # No conflict-shaped key exists on the record at all -- a single
        # declaration winning is not distinguished from a conflict by any
        # extra field, per D-03's shape (naming the authority IS the
        # legibility mechanism; there is no separate boolean).
        self.assertNotIn('conflict', got)
        self.assertNotIn('evidence_class_conflict', got)


if __name__ == '__main__':
    unittest.main()
