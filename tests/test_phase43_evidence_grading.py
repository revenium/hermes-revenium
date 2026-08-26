"""Phase 43 Plans 01, 02 & 04 — the EGV-18 reportability gate, the EGV-10
nine-label evidence-class vocabulary, and EGV-11/EGV-13's two-instrument
promotion and non-inheritance proofs.

An estimate produced without explicit experimental opt-in is retained locally
as a candidate; its number never leaves the machine. Plan 01's classes test
the resolver classifier.py computes it with (`_resolve_reportability_status`)
and the fixture-fidelity guarantee that keeps the golden fixture honest.
Plan 02's classes (`LabelTests`, `LabelDriftTests`) test the nine EGV-10
claim labels themselves -- that they exist as one flat, unordered set, what
is genuinely impossible about that shape versus what is merely absent from
today's code, and that the hand-synced pair in classifier.py and
hermes-report.sh cannot drift apart silently. Plan 04's classes
(`PromotionTests`, `NonInheritanceTests`) prove EGV-11 twice, per D-04, and
EGV-13 once, per D-08/D-07 -- see each class's own docstring for exactly
which of the two instruments it is and what it does and does not claim.

Requirements covered:
  EGV-10 — the nine claim labels are representable as a flat, unordered set;
           customer confirmation, observation, and configuration are not
           comparable and must never be modelled as a confidence ladder.
  EGV-11 — a hostile evaluator response cannot promote its own claim
           strength, proven both behaviourally (the fixture) and
           structurally (the scoped ast-guard) -- D-04 requires BOTH.
  EGV-13 — a job referencing an impact study never inherits the study's
           evidence_class, strength, or validity scope.
  EGV-18 — reportability_status gates whether an estimate's VALUE (not its
           provenance) reaches Revenium.

Decisions this module exercises (43-CONTEXT.md):
  D-01 — the nine labels are a flat frozenset; ordering is not merely
         unused, it is unrepresentable as a type (not indexable) or absent
         from today's code (never sorted) -- the two are NOT the same
         guarantee and LabelTests says so explicitly.
  D-02 — the label list is a hand-synced pair (classifier.py /
         hermes-report.sh) with a drift test SUPPORTED_CURRENCIES' own
         hand-synced pair does not have today.
  D-03 — evidence_class is blocked by never consulting evaluator output
         for it -- there is no field to attack.
  D-04 — EGV-11 is proven twice: an adversarial fixture through the REAL
         construction path, AND a scoped ast-guard over classifier.py.
         The fixture proves today's code ignores the field; only the
         guard catches a future edit that starts reading it.
  D-05 — reportable | candidate; a candidate withholds value_low/value_base/
         value_high/bounds_source/currency/estimated_value/assumptions but
         keeps evidence_class/evaluator/evaluator_version/model/the version
         family.
  D-06 — a kind:"correction" record is reportable by construction, no
         config opt-in required.
  D-08 — a job references a study by id and version only; its own
         evidence_class is always set by its own source's forced constant.
  D-09 — reportability_status is a straight rename of Phase 42's
         REPORTABILITY_STATUS_DEFAULT placeholder; no migration shim.
  D-11 — reportability_status is deliberately NOT in the abstention omit
         family; an abstained record still carries the key, valued
         candidate.
  D-12 — the config key is llmOutcomeEvaluation.experimentalReportEstimates,
         literal-JSON-true only (mirrors ROI-01's "enabled" discipline).

Guarantee class (43-VALIDATION.md's honesty rule): Plan 01's classes
(ResolverTests, FixtureFidelityTests, AbstentionTests) are entirely
BEHAVIOURAL -- they prove the resolver and the reporter withhold the value
on the paths exercised here, no structural or impossibility claim. Plan 02's
LabelTests is MIXED and says which of its three tests is which kind in each
test's own docstring: not-indexable is IMPOSSIBLE-class (a frozenset has no
__getitem__), never-sorted is STATIC-class (proves absence in the two files
scanned today, not impossibility -- Python's str is orderable). LabelDriftTests
is BEHAVIOURAL: it proves the two live declarations agree right now, not that
they can never diverge in the future. Plan 04's PromotionTests is MIXED: its
seven attack methods and the closing key-set method are BEHAVIOURAL (today's
code ignores these keys); its two guard methods are STATIC, current-code-only
(no future edit that starts reading a forbidden key survives them, but
neither proves such an edit is impossible to write). NonInheritanceTests is
also MIXED, and its structural half is the STRONGEST claim in this whole
phase: with no import edge from classifier.py to impact_study.py (and no
dynamic-import escape), no code path in classifier.py can reach ANY field of
ANY study, full stop -- that one guard is entitled to say "impossible", not
merely "absent today", and its own docstring says so.
"""
import ast
import importlib.util
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'
CLASSIFIER_SOURCE_PATH = PLUGIN / 'classifier.py'
HERMES_REPORT_PATH = ROOT / 'skills' / 'revenium' / 'scripts' / 'hermes-report.sh'
IMPACT_STUDY_PATH = PLUGIN / 'impact_study.py'


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


def _load_impact_study():
    """Import impact_study.py fresh -- same not-imported-across-test-modules
    posture as _load_classifier above (matching tests/test_phase43_impact_
    study.py's own loader), used here only by NonInheritanceTests to build a
    REAL ImpactStudyResult through validate() rather than a hand-built dict.
    """
    spec = importlib.util.spec_from_file_location(
        'phase43_04_impact_study', str(IMPACT_STUDY_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


# -- Plan 43-04, Task 2: the adversarial evaluator response -----------------

def _hostile_evaluator_response():
    """One evaluator response, seven simultaneous promotion attempts
    (A1-A7 in 43-04-PLAN.md's Task 2 behavior list), layered ON TOP of the
    six legitimate keys _validate_assessment actually reads plus the two
    narrative keys _build_job_assessment reads directly off raw -- together
    enough for the assessment to be ACCEPTED, not abstained. Accepting
    matters: an attack that lands on the abstention path proves only that
    abstention works, not that acceptance resists promotion.

    This fixture fixes 43-RESEARCH.md's Open Question 1 (the adversarial
    fixture's exact key shape) in this ONE place -- Task 3's ast-guard
    forbidden-key set is derived from these same seven attacks, not
    guessed at separately.
    """
    return {
        # Legitimate keys, nominal in-bounds values -- the ACCEPT path.
        'inferred_role': 'senior engineer',
        'estimated_hours_saved': 3.0,
        'assumed_loaded_rate': 120.0,
        'currency': 'USD',
        'basis': 'time avoided reviewing a large diff',
        'confidence': 0.7,
        'candidate_downstream_outcome': 'PR merged to main',
        'counterfactual_assumption': 'a human reviewer would have taken the same time',
        # A1 -- direct label promotion: the strongest impact label.
        'evidence_class': 'EXPERIMENTAL_IMPACT',
        # A2 -- differently-named impact key.
        'impact_class': 'QUASI_EXPERIMENTAL_IMPACT',
        # A3 -- study-reference spoof (the D-08 inheritance vector).
        'study_id': 'attacker-injected-study',
        'study_version': 999,
        # A4 -- self-granted reportability.
        'reportability_status': 'reportable',
        # A5 -- evidence-pointer spoof, naming an impact label.
        'evidence_references': ['EXPERIMENTAL_IMPACT'],
        # A6 -- provenance spoof.
        'evaluator': 'attacker-controlled-evaluator',
        'evaluator_version': 'attacker-v99',
        'model': 'gpt-attacker-9000',
        # A7 -- value spoof, far above the derived hours*rate product (360.0).
        'estimated_value': 999999999.0,
    }


# -- Plan 43-04, Task 3: the scoped ast key-read guard ----------------------
#
# The forbidden-key set the guard below scans classifier.py for, taken
# VERBATIM from the seven attacks _hostile_evaluator_response() builds
# above -- the guard's coverage is derived from a concrete, reviewed attack
# shape, not guessed at. A3/A6 each contribute more than one key.
_PROMOTION_FORBIDDEN_KEYS = frozenset({
    'evidence_class', 'impact_class', 'study_id', 'study_version',
    'reportability_status', 'evidence_references',
    'evaluator', 'evaluator_version', 'model', 'estimated_value',
})

# The three functions that legitimately hold the untrusted evaluator
# response in scope, all under the SAME parameter name -- which is what
# lets one guard cover all three (confirmed against classifier.py at plan
# 43-04 execution time).
_SCOPED_FUNCTIONS = ('_validate_assessment', '_build_job_assessment', '_resolve_value_bounds')
_UNTRUSTED_PARAM_NAME = 'raw'


def _scoped_function_defs(tree):
    """Return {function_name: ast.FunctionDef} for each name in
    _SCOPED_FUNCTIONS found anywhere in `tree` -- classifier.py declares all
    three at module level, but ast.walk is used rather than assuming that
    stays true forever."""
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in _SCOPED_FUNCTIONS:
            found[node.name] = node
    return found


def _assert_functions_declare_untrusted_param(tree, filename):
    """Discovery step, run BEFORE the read-scan below. If any of the three
    scoped functions is missing, or no longer declares a parameter named
    _UNTRUSTED_PARAM_NAME (e.g. a rename), this guard's scoping has broken
    silently -- and a name-scoped guard that silently stops matching is
    worse than no guard at all, because it keeps passing while covering
    nothing. Returns a list of "file: ..." offense strings (empty means the
    guard's own scoping is intact), never a bool, so a failure names exactly
    which function/rename broke it."""
    found = _scoped_function_defs(tree)
    offenders = []
    for name in _SCOPED_FUNCTIONS:
        node = found.get(name)
        if node is None:
            offenders.append(
                f'{filename}: {name} not found -- guard scoping needs updating')
            continue
        arg_names = {a.arg for a in node.args.args}
        if _UNTRUSTED_PARAM_NAME not in arg_names:
            offenders.append(
                f'{filename}:{node.lineno}: {name} no longer declares a '
                f'parameter named {_UNTRUSTED_PARAM_NAME!r} -- guard scoping '
                'needs updating'
            )
    return offenders


def _constant_str_key(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _find_forbidden_raw_reads(tree, filename):
    """Walk ONLY inside the three scoped functions' bodies (per the
    discovery step above) for reads of a forbidden key off the
    _UNTRUSTED_PARAM_NAME-named variable, across every access idiom this
    codebase -- or an attacker's future edit -- could spell: subscript,
    the .get()/.pop()/.setdefault() dict-lookup methods (the two-argument
    default form of .get() is the SAME node shape and needs no special
    handling), the getattr() builtin, and dict-literal splat unpacking
    (**raw).

    Deliberately scoped to the `raw` NAME within these three functions, and
    to a NAMED forbidden-key set, not a blanket string match on the key
    names anywhere in the file: classifier.py legitimately WRITES several
    of these same key names as dict-LITERAL keys (e.g. "evidence_class":
    _forced_evidence_class() inside _build_job_assessment's own record
    literal), and later pipeline code legitimately reads these fields back
    off the ALREADY-CONSTRUCTED record -- a local variable this guard never
    scopes to. A blanket matcher would false-positive on that fully
    compliant code the day it shipped.

    The splat check is unconditional on key name (not just the forbidden
    set): a splat cannot be scoped to one key statically and would smuggle
    every forbidden key in at once -- the obvious way around a key-name
    matcher, and the reason the plan calls it out by name.

    Returns a list of "file:line: ..." offense strings.
    """
    found = _scoped_function_defs(tree)
    offenders = []
    for func_node in found.values():
        for node in ast.walk(func_node):
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id == _UNTRUSTED_PARAM_NAME
            ):
                key = _constant_str_key(node.slice)
                if key in _PROMOTION_FORBIDDEN_KEYS:
                    offenders.append(
                        f'{filename}:{node.lineno}: raw[{key!r}] subscript read')
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ('get', 'pop', 'setdefault')
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == _UNTRUSTED_PARAM_NAME
                and node.args
            ):
                key = _constant_str_key(node.args[0])
                if key in _PROMOTION_FORBIDDEN_KEYS:
                    offenders.append(
                        f'{filename}:{node.lineno}: raw.{node.func.attr}({key!r}, ...) read')
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == 'getattr'
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == _UNTRUSTED_PARAM_NAME
            ):
                key = _constant_str_key(node.args[1])
                if key in _PROMOTION_FORBIDDEN_KEYS:
                    offenders.append(
                        f'{filename}:{node.lineno}: getattr(raw, {key!r}, ...) read')
            if isinstance(node, ast.Dict):
                for dict_key, dict_value in zip(node.keys, node.values):
                    if (
                        dict_key is None
                        and isinstance(dict_value, ast.Name)
                        and dict_value.id == _UNTRUSTED_PARAM_NAME
                    ):
                        offenders.append(
                            f'{filename}:{node.lineno}: {{**raw, ...}} splat unpack')
    return offenders


class PromotionTests(unittest.TestCase):
    """EGV-11 (D-04) -- proven twice, and both instruments live in this one
    class. The seven attack methods and the closing key-set method above
    are the BEHAVIOURAL half: they prove the code that exists TODAY
    ignores every one of these keys when a hostile response is fed through
    the REAL _validate_assessment -> _build_job_assessment construction
    path. They do NOT prove a future edit cannot start reading one of
    these keys -- that is what the two guard methods below
    (test_functions_declare_the_scoped_parameter,
    test_no_forbidden_key_is_read_off_the_untrusted_response) are for, and
    D-04 requires both: the fixture proves today's code is safe; the guard
    proves a future edit that starts reading a forbidden key turns red.
    Neither makes the other's claim -- a mutation that adds a fallback read
    (value if present, else the forced constant) turns the guard red
    without turning the fixture red, because the fallback still yields the
    same value on this fixture's inputs. That asymmetry is exactly why
    D-04 requires both instruments.
    """

    def setUp(self):
        self.mod = _load_classifier()
        self.raw = _hostile_evaluator_response()
        self.valid_job = {
            'agentic_job_id': 'promotion-job-001', 'job_type': 'code_review', 'status': 'SUCCESS',
        }
        # cfg carries NEITHER a study reference NOR the reporting opt-in --
        # the plan's own instruction for this fixture's config.
        self.cfg = {}
        self.validated = self.mod._validate_assessment(self.raw, self.cfg, 'stub-evaluator', 'v1')
        self.assertIsNotNone(
            self.validated,
            'the hostile fixture must be ACCEPTED for this test to be meaningful -- '
            'an attack that lands on the abstention path proves only that '
            'abstention works, not that acceptance resists promotion',
        )
        self.record = self.mod._build_job_assessment(
            self.valid_job, self.validated, self.raw, self.cfg, 'stub-evaluator', 'v1')
        self.assertIsNotNone(self.record)

    # -- A1-A7: one assertion method per attack, so a failure names the
    #    vector rather than a row number. --

    def test_a1_direct_label_promotion_is_ignored(self):
        self.assertEqual(self.record['evidence_class'], self.mod.EVIDENCE_CLASS_MODEL_ESTIMATED)

    def test_a2_differently_named_impact_key_does_not_exist_in_the_record(self):
        self.assertNotIn('impact_class', self.record)

    def test_a3_study_reference_spoof_stays_at_configured_defaults(self):
        # cfg carried no studyId/studyVersion above -- the configured
        # defaults ("" and 0) must win over the raw response's spoofed ones.
        self.assertEqual(self.record['study_id'], '')
        self.assertEqual(self.record['study_version'], 0)

    def test_a4_self_granted_reportability_is_ignored(self):
        self.assertEqual(self.record['reportability_status'], self.mod.REPORTABILITY_CANDIDATE)

    def test_a5_evidence_pointer_spoof_stays_empty(self):
        self.assertEqual(self.record['evidence_references'], [])

    def test_a6_provenance_spoof_keeps_caller_supplied_identity(self):
        # evaluator/evaluator_version come from the FUNCTION ARGUMENTS this
        # setUp passed ('stub-evaluator'/'v1'), never from raw -- the
        # attacker-controlled values inside raw are simply never consulted.
        self.assertEqual(self.record['evaluator'], 'stub-evaluator')
        self.assertEqual(self.record['evaluator_version'], 'v1')
        self.assertEqual(self.record['model'], self.mod.PROVENANCE_MODEL_UNKNOWN)

    def test_a7_value_spoof_ships_the_derived_product_not_the_supplied_total(self):
        self.assertEqual(self.record['estimated_value'], 360.0)  # 3.0 hours * 120.0 rate

    def test_record_key_set_matches_declared_contract_exactly(self):
        """The closing assertion: nothing was smuggled in under a key
        nobody thought to check -- an assertion that only checks the keys
        anyone thought of is exactly the "test proves less than it appears
        to" pattern this project keeps hitting. Imports
        RecordShapeTests.DECLARED_KEYS directly from
        test_phase42_assessment_contract.py rather than retyping it here,
        matching FixtureFidelityTests' own precedent (plan 43-01) of
        importing a plain name across test modules -- so the two key sets
        cannot silently drift apart from each other."""
        from tests.test_phase42_assessment_contract import RecordShapeTests

        got_keys = set(self.record.keys())
        declared_keys = RecordShapeTests.DECLARED_KEYS
        self.assertEqual(
            got_keys, declared_keys,
            f'record key set does not match the declared contract exactly -- '
            f'missing={declared_keys - got_keys!r}, extra={got_keys - declared_keys!r}',
        )

    # -- Guard one: the scoped ast key-read guard (43-04-PLAN.md Task 3). --

    def test_functions_declare_the_scoped_parameter(self):
        """Discovery step: if this fails, the guard below is scoped to a
        name that no longer exists on one of the three functions -- fix the
        guard's scoping, not this assertion."""
        tree = ast.parse(CLASSIFIER_SOURCE_PATH.read_text())
        offenders = _assert_functions_declare_untrusted_param(tree, 'classifier.py')
        self.assertEqual(offenders, [], f'guard scoping is broken: {offenders!r}')

    def test_no_forbidden_key_is_read_off_the_untrusted_response(self):
        """GUARD ONE (EGV-11's structural half). STATIC, current-code-only:
        proves no code path inside _validate_assessment, _build_job_
        assessment, or _resolve_value_bounds reads a forbidden key off the
        untrusted `raw` parameter TODAY, via subscript, .get()/.pop()/
        .setdefault(), getattr(), or dict-splat unpacking. It does NOT
        prove such a read is impossible to write -- that is a claim only
        NonInheritanceTests' import-boundary guard below is entitled to
        make, and only for a different question (whether a study's own
        fields can reach a job assessment at all). Paired with the seven
        behavioural attack methods above: the fixture proves today's code
        ignores these keys; this guard proves a future edit that starts
        reading one turns red.

        Deliberately scoped to reads on the untrusted evaluator-response
        parameter, not a blanket string match on the key names: the same
        file legitimately WRITES the forced label as a dict-literal key
        (e.g. "evidence_class": _forced_evidence_class()), and later
        pipeline code legitimately reads these fields back off the
        already-constructed record. A blanket matcher would fail on
        compliant code the day it shipped.
        """
        tree = ast.parse(CLASSIFIER_SOURCE_PATH.read_text())
        offenders = _find_forbidden_raw_reads(tree, 'classifier.py')
        self.assertEqual(offenders, [], f'forbidden read(s) of raw: {offenders!r}')


def _top_level_imports(tree):
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split('.')[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split('.')[0])
    return imported


class NonInheritanceTests(unittest.TestCase):
    """EGV-13 (D-08, D-07) -- a job referencing an impact study never
    inherits the study's evidence_class, effect estimate, or validity
    scope.

    Two halves, and they are NOT the same kind of guarantee:

    test_referencing_the_strongest_study_leaves_the_jobs_own_label_unchanged
    is BEHAVIOURAL: it builds a REAL ImpactStudyResult via
    impact_study.validate() using the randomized-design identification
    method (RCT) -- the strongest in the vocabulary, and the study a naive
    consumer would be most tempted to treat as individually observed
    causality -- configures the classifier with that study's id/version,
    and proves the resulting job assessment's own evidence_class,
    confidence, and every other field carry no trace of the study's
    values, for the one study exercised here.

    test_classifier_does_not_import_impact_study_statically_or_dynamically
    is this PHASE's one genuine STRUCTURAL impossibility claim, stronger
    than every other guard in Plan 43-04: with no import edge from
    classifier.py to impact_study.py, and no dynamic-import escape via
    importlib, NO code in classifier.py can call ANYTHING impact_study.py
    defines -- full stop, for ANY study, not merely the one this test
    happens to construct. A study's strength is UNREACHABLE, not merely
    unread. This is the mirror half of impact_study.py's own ast-guard
    (tests/test_phase43_impact_study.py's ImportBoundaryTests), which
    proves the reverse edge is absent; together the two close the loop
    from both sides.
    """

    def test_referencing_the_strongest_study_leaves_the_jobs_own_label_unchanged(self):
        impact_study = _load_impact_study()
        study_candidate = {
            'study_id': 'randomized-onboarding-study-2026',
            'study_version': 3,
            'unit': 'individual contributor',
            'population': 'engineers using Hermes for code review',
            'intervention': 'agent-assisted review',
            'comparator': 'unassisted review',
            'estimand': 'average treatment effect of agent assistance on review time',
            'identification_method': 'RCT',
            'outcome': 'hours to complete review',
            'observation_window_start': 1700000000.0,
            'observation_window_end': 1700600000.0,
            'value_low': 1000.0,
            'value_base': 5000.0,
            'value_high': 9000.0,
            'assumptions': ['SUTVA holds', 'random assignment was honored'],
            'diagnostics': ['balance table shows no significant covariate imbalance'],
            'validity_scope': 'internal validity strong; external validity limited to this cohort',
        }
        study = impact_study.validate(study_candidate)
        self.assertIsNotNone(
            study, 'the study fixture itself must validate for this test to be meaningful')

        mod = _load_classifier()
        raw = {
            'inferred_role': 'engineer',
            'estimated_hours_saved': 2.0,
            'assumed_loaded_rate': 100.0,
            'currency': 'USD',
            'basis': 'time avoided',
            'confidence': 0.6,
        }
        cfg = {'studyId': study['study_id'], 'studyVersion': study['study_version']}
        assessment = mod._validate_assessment(raw, cfg, 'stub', '1')
        self.assertIsNotNone(assessment)
        valid_job = {
            'agentic_job_id': 'noninherit-job-001', 'job_type': 'code_review', 'status': 'SUCCESS',
        }
        record = mod._build_job_assessment(valid_job, assessment, raw, cfg, 'stub', '1')
        self.assertIsNotNone(record)

        # The job's own label is untouched by referencing an EXPERIMENTAL-
        # strength (RCT) study.
        self.assertEqual(record['evidence_class'], mod.EVIDENCE_CLASS_MODEL_ESTIMATED)
        # The reference itself IS carried, exactly as configured.
        self.assertEqual(record['study_id'], study['study_id'])
        self.assertEqual(record['study_version'], study['study_version'])

        # No other value from the study appears anywhere among the record's
        # values -- not the effect estimate, not validity_scope, not any
        # narrative field. String-compared so a numeric collision (e.g. an
        # unrelated field that happens to equal 1700000000.0) is still
        # caught.
        study_values_other_than_reference = {
            str(v) for k, v in study.items() if k not in ('study_id', 'study_version')
        }
        record_values_as_strings = {str(v) for v in record.values()}
        leaked = study_values_other_than_reference & record_values_as_strings
        self.assertEqual(
            leaked, set(),
            f'study value(s) leaked into the job assessment record: {leaked!r}',
        )

    def test_classifier_does_not_import_impact_study_statically_or_dynamically(self):
        tree = ast.parse(CLASSIFIER_SOURCE_PATH.read_text())
        imported = _top_level_imports(tree)
        self.assertNotIn(
            'impact_study', imported,
            'classifier.py imports impact_study.py -- this is the ONE genuinely '
            'structural guarantee this phase makes; an import edge here would '
            'give a study a code path into a job assessment',
        )
        # A dynamic import via importlib is the one way to reach a module
        # without a static import edge, and would silently defeat the
        # guarantee above.
        self.assertNotIn(
            'importlib', imported,
            'classifier.py imports importlib -- a dynamic import is the one way '
            'to reach impact_study.py without a static import edge',
        )


# -- Plan 43-02, Task 3: EGV-10 label extraction helpers --------------------
#
# ast, never regex, for the same reason
# tests/test_phase42_assessment_contract.py's _extract_correction_record_fields
# abandoned a regex predecessor (that module's own docstring, and its
# Greptile P2 note): a regex recognising one quoting style silently
# under-matches a collection literal the moment its quoting style changes,
# leaving `fields`/labels non-empty and the caller none the wiser. Both
# extractors below REFUSE (return None) on anything but exactly one
# unambiguous match, so a moved or reshaped declaration fails the caller
# loudly instead of silently comparing a partial or stale set.

_ORDERING_BUILTINS = frozenset({'sorted', 'min', 'max'})
_ORDERING_COMPARISONS = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)


def _extract_frozenset_from_module(tree, target_name):
    """Read `target_name = frozenset({...})`'s string elements straight out
    of a parsed ast.Module -- the whole-module-parse half of D-02's
    extraction (classifier.py is ordinary Python end to end, so parsing the
    whole file and finding the one matching top-level assignment is the
    natural shape here; contrast
    _extract_frozenset_assignment_fragment below, used for hermes-report.sh,
    which is bash and cannot be parsed as a whole).

    Refuses (returns None) if there are zero or more than one matching
    assignment, or if any element is not a plain string constant.
    """
    matches = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        if node.targets[0].id != target_name:
            continue
        value = node.value
        if not (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == 'frozenset'
            and len(value.args) == 1
            and isinstance(value.args[0], ast.Set)
        ):
            continue
        matches.append(value.args[0])
    if len(matches) != 1:
        return None
    elements = []
    for elt in matches[0].elts:
        if not isinstance(elt, ast.Constant) or not isinstance(elt.value, str):
            return None
        elements.append(elt.value)
    return set(elements)


def _extract_frozenset_assignment_fragment(text, target_name):
    """Isolate the ONE `target_name = frozenset({...})` assignment out of a
    larger text blob -- hermes-report.sh as a whole is bash with embedded
    Python heredocs, not directly ast.parse-able, so D-02's instruction is
    to isolate just this one assignment (not the whole heredoc) and parse
    that fragment on its own. Distinct from
    _extract_frozenset_from_module above, which parses classifier.py's
    entire module because that file IS ordinary Python throughout.

    Refuses (returns None) if the anchor text does not appear exactly
    once, or if the isolated fragment does not parse as a single
    `NAME = frozenset({...})` assignment of string constants.
    """
    anchor = f'{target_name} = frozenset({{'
    occurrences = [i for i in range(len(text)) if text.startswith(anchor, i)]
    if len(occurrences) != 1:
        return None
    start = occurrences[0]
    end = text.find('})', start)
    if end == -1:
        return None
    fragment = text[start:end + len('})')]
    try:
        tree = ast.parse(fragment)
    except SyntaxError:
        return None
    return _extract_frozenset_from_module(tree, target_name)


def _hermes_report_evidence_class_heredoc():
    """Isolate the ONE Python heredoc body in hermes-report.sh that declares
    _EVIDENCE_CLASSES, so it can be ast.parse'd as a self-contained
    fragment for the ordering-usage scan below. hermes-report.sh as a WHOLE
    is bash and cannot be ast.parse'd directly; this specific heredoc
    (the sidecar reader) was confirmed to compile standalone via
    `python3 -m py_compile` at Plan 43-02 execution time -- it is a
    complete, self-contained Python script embedded in the surrounding
    bash, not a fragment.

    _EVIDENCE_CLASSES is a local variable scoped to this one heredoc (bash
    heredocs share no Python namespace with each other), so scanning this
    single span for ordering usage of the name is equivalent to scanning
    "anywhere in hermes-report.sh" -- no other heredoc in the file can
    reference a name this one never exports.

    Refuses (returns None) if the anchor is not found in exactly one
    heredoc span.
    """
    text = HERMES_REPORT_PATH.read_text()
    anchor = '_EVIDENCE_CLASSES = frozenset({'
    spans = []
    pos = 0
    while True:
        start = text.find("<<'PY'", pos)
        if start == -1:
            break
        body_start = text.index('\n', start) + 1
        end = text.find('\nPY\n', body_start)
        if end == -1:
            break
        spans.append((body_start, end))
        pos = end + 1
    matching = [text[s:e] for s, e in spans if anchor in text[s:e]]
    if len(matching) != 1:
        return None
    return matching[0]


def _references_name(node, names):
    return any(
        isinstance(sub, ast.Name) and sub.id in names
        for sub in ast.walk(node)
    )


def _find_label_ordering_offenses(tree, filename, names):
    """Walk `tree` for calls to sorted/min/max, or comparisons using an
    ordering operator (<, <=, >, >=), whose operands reference any name in
    `names` -- the label constant this test is proving is never ordered.
    Returns a list of human-readable "file:line: ..." offense strings, not
    just a count, per Task 3's instruction.

    Equality (==, !=) and membership (in, not in) are deliberately NOT
    flagged -- both are used legitimately throughout this codebase to check
    set membership (e.g. `x in EVIDENCE_CLASSES`), and neither imposes an
    order.
    """
    offenders = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _ORDERING_BUILTINS
            and any(_references_name(arg, names) for arg in node.args)
        ):
            offenders.append(
                f'{filename}:{getattr(node, "lineno", "?")}: '
                f'{node.func.id}(...) applied to {sorted(names)!r}'
            )
        if isinstance(node, ast.Compare) and any(
            isinstance(op, _ORDERING_COMPARISONS) for op in node.ops
        ):
            operands = [node.left] + list(node.comparators)
            if any(_references_name(operand, names) for operand in operands):
                offenders.append(
                    f'{filename}:{getattr(node, "lineno", "?")}: '
                    f'ordering comparison applied to {sorted(names)!r}'
                )
    return offenders


class LabelTests(unittest.TestCase):
    """EGV-10 (D-01) -- the nine claim labels, as a flat, unordered
    frozenset. Behaviors 1-3 from 43-02-PLAN.md's Task 3.

    Guarantee-class honesty (43-VALIDATION.md): test_labels_are_not_indexable
    proves a genuine type-level IMPOSSIBILITY -- a frozenset has no
    __getitem__ at all. test_labels_never_sorted_in_source proves only that
    an ordering operation is ABSENT from the two files this guard scans
    TODAY (STATIC-class) -- Python's str is orderable, so nothing in the
    language prevents a future edit from sorting these labels; this guard
    would catch such an edit only within the files it scans.
    43-VALIDATION.md's honesty rule and 42-LEARNINGS' three
    narrowed-not-closed failures both exist because a green test was once
    read as a stronger guarantee than it was -- these docstrings are
    deliberately not softened.
    """

    def setUp(self):
        self.mod = _load_classifier()

    def test_labels_are_exactly_the_nine_egv_10_strings(self):
        """Behavior 1: EVIDENCE_CLASSES holds exactly the nine EGV-10
        strings, COMPARED AS A SET -- deliberately `set(...)`-cast rather
        than compared directly, so this test isolates CONTENT (are these
        the right nine strings) from CONTAINER TYPE (which
        test_labels_are_not_indexable below owns). A direct `assertEqual`
        against a set literal would also fail if the container were ever
        changed to something merely order-preserving but still unindexable
        -- conflating this test's failure with that one's, exactly what the
        mutation check in 43-02-PLAN.md's verification section (c) is
        built to keep separate."""
        self.assertEqual(
            set(self.mod.EVIDENCE_CLASSES),
            {
                'ACTIVITY_MEASURED', 'OUTPUT_OBSERVED', 'OUTCOME_OBSERVED',
                'MODEL_ESTIMATED_DEMO', 'CUSTOMER_CONFIGURED', 'CUSTOMER_CONFIRMED',
                'ASSOCIATIONAL', 'QUASI_EXPERIMENTAL_IMPACT', 'EXPERIMENTAL_IMPACT',
            },
        )

    def test_labels_are_not_indexable(self):
        """Behavior 2. IMPOSSIBLE-class: a frozenset has no __getitem__ at
        all, so a subscript raises from the type system itself, not from a
        check anyone wrote -- this test is entitled to claim impossibility.
        Both the raise AND the missing attribute are asserted: the attribute
        check is what keeps this test meaningful if the container type is
        ever changed to something ordered whose __getitem__ happens to also
        raise for an out-of-range index (a bare raise-only assertion would
        stay green through that regression)."""
        self.assertFalse(hasattr(self.mod.EVIDENCE_CLASSES, '__getitem__'))
        with self.assertRaises(TypeError):
            self.mod.EVIDENCE_CLASSES[0]

    def test_labels_never_sorted_in_source(self):
        """Behavior 3. STATIC-class, honestly labelled: this proves an
        ordering operation is ABSENT FROM THE CODE THAT EXISTS TODAY in
        classifier.py and hermes-report.sh's _EVIDENCE_CLASSES heredoc --
        NOT that ordering these labels is impossible. Python's str is
        orderable, so nothing prevents a future edit from sorting,
        ranking, or min/max-ing this set; this guard catches such an edit
        only within the two files and the one heredoc region it scans.

        ast, never a substring scan: EVIDENCE_CLASSES' own explanatory
        comment in classifier.py states in prose that the labels are never
        ordered, so a text search for e.g. "sorted" near the constant would
        match that very comment and fail on a fully compliant file --
        the same trap tests/test_phase36_evaluator_seam.py's
        test_module_does_not_import_classifier names for its own ast-vs-grep
        choice."""
        offenders = []

        classifier_tree = ast.parse(CLASSIFIER_SOURCE_PATH.read_text())
        offenders.extend(_find_label_ordering_offenses(
            classifier_tree, 'classifier.py', frozenset({'EVIDENCE_CLASSES'}),
        ))

        heredoc_text = _hermes_report_evidence_class_heredoc()
        self.assertIsNotNone(
            heredoc_text,
            'the _EVIDENCE_CLASSES heredoc in hermes-report.sh could not be '
            'isolated -- the declaration or its heredoc moved and this '
            'extractor needs updating, not this assertion',
        )
        heredoc_tree = ast.parse(heredoc_text)
        offenders.extend(_find_label_ordering_offenses(
            heredoc_tree, 'hermes-report.sh', frozenset({'_EVIDENCE_CLASSES'}),
        ))

        self.assertEqual(
            offenders, [],
            f'ordering operation(s) applied to the label constant: {offenders!r}',
        )


class LabelDriftTests(unittest.TestCase):
    """D-02 -- the hand-synced label pair (classifier.py's EVIDENCE_CLASSES,
    hermes-report.sh's _EVIDENCE_CLASSES) must never drift silently apart.
    This is the drift test SUPPORTED_CURRENCIES' otherwise-identical
    hand-synced pair (classifier.py's SUPPORTED_CURRENCIES /
    hermes-report.sh's _SUPPORTED_CURRENCIES) does NOT have today -- Phase
    43 closes that gap for the new pair rather than reproducing it.

    Guarantee class: BEHAVIOURAL. This proves the two live declarations
    agree right now, read directly from source on every run -- not that
    they can never diverge in the future. A future hand-edit to either side
    alone is exactly what this test exists to catch, on its next run.
    """

    def test_classifier_and_reporter_label_sets_agree(self):
        """Behavior 4: extract classifier.py's EVIDENCE_CLASSES by
        ast-parsing the whole module, extract hermes-report.sh's
        _EVIDENCE_CLASSES by isolating and ast-parsing just that one
        assignment, and compare. Either extractor returning None means the
        declaration moved -- fail loudly and say so, rather than silently
        comparing an empty/stale set (matching
        _extract_correction_record_fields's refuse-rather-than-under-match
        discipline)."""
        classifier_tree = ast.parse(CLASSIFIER_SOURCE_PATH.read_text())
        classifier_labels = _extract_frozenset_from_module(
            classifier_tree, 'EVIDENCE_CLASSES',
        )
        self.assertIsNotNone(
            classifier_labels,
            'EVIDENCE_CLASSES could not be extracted from classifier.py -- '
            'the declaration moved and this extractor needs updating',
        )

        reporter_text = HERMES_REPORT_PATH.read_text()
        reporter_labels = _extract_frozenset_assignment_fragment(
            reporter_text, '_EVIDENCE_CLASSES',
        )
        self.assertIsNotNone(
            reporter_labels,
            '_EVIDENCE_CLASSES could not be extracted from hermes-report.sh '
            '-- the declaration moved and this extractor needs updating',
        )

        self.assertEqual(
            classifier_labels, reporter_labels,
            'classifier.py and hermes-report.sh have drifted on the '
            'nine-label set',
        )


if __name__ == '__main__':
    unittest.main()
