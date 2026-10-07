"""Phase 67 (TRU-03): guards around the evaluator's `confidence` contract.

Proven here, before any experiment runs against the evaluator:

TRU-03, the instrument. A response whose `confidence` is absent, None, a
string, a bool, NaN, an infinity or outside [0,1] makes
`_validate_assessment` return None and log, on the `revenium_classifier`
logger, exactly one record whose format string is
`revenium-classifier: rejected assessment, confidence outside [0,1]: %r`.
That string is what Phase 70 greps in `agent.log`, and every historical
comparison (the baseline in docs/confidence-omission-experiment.md) depends on
it. 0.0 and 1.0 are accepted unchanged.

SC2, the no-workaround fence. A missing `confidence` is never made to pass: no
default on `raw.get('confidence')`, no other dict carrying a `confidence` key
beyond the validated value and the abstained-record 0.0, no store into a
`confidence` subscript, no `setdefault`, and the instrument string occurs once.
Each check is AST-based so a comment cannot satisfy it, and each has a negative
control: the same checker, fed a mutated copy of the source, must report a
violation. A guard that cannot fail is not a guard.

SC3, the AST pins. `LABEL_RE`, `TRIVIAL_BLOCKLIST`, the reportability gate, the
evidence-class tables and precedence walk, and the evaluator contract
(validator, parser, call budget, `PROMPT_VERSION`) are compared node by node
against `classifier.py` at the phase-start commit. The comparison runs
in-process against `git show` of an immutable `origin/main` commit. That is
deliberate. A hardcoded sha256 of `ast.dump` output would change with the
Python version (`ast.dump`'s defaults changed in 3.13), and a guard whose
verdict depends on the installed interpreter is not a guard.

Nothing here edits classifier.py. These tests only add guards around it.
"""
import ast
import importlib.util
import logging
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'
CLASSIFIER_PATH = PLUGIN_DIR / 'classifier.py'
CLASSIFIER_REL = 'skills/revenium/plugins/revenium-classifier/classifier.py'
RECORD_PATH = ROOT / 'docs' / 'confidence-omission-experiment.md'

# The phase-start commit: the `origin/main` commit Phase 67 branched from.
# Immutable by construction, and reachable after any merge style because it is
# already on main. Move it only deliberately, in a reviewed change.
_SC3_BASELINE_SHA = '8c4f9e01618388645ebb9f85a1b24caaebbc18db'

INSTRUMENT_FORMAT = (
    'revenium-classifier: rejected assessment, confidence outside [0,1]: %r'
)

_PINNED_NODES = (
    'LABEL_RE',
    'TRIVIAL_BLOCKLIST',
    'EVIDENCE_CLASSES',
    '_DECLARABLE_EVIDENCE_CLASSES',
    '_REPORTABLE_EVIDENCE_CLASSES',
    '_model_estimates_opted_in',
    '_resolve_reportability_status',
    '_evidence_class_precedence',
    '_validate_assessment',
    '_finite_number',
    '_parse_assessment_object',
    '_evaluate_outcome_via_llm',
    '_EVAL_MAX_TOKENS',
    '_EVAL_TIMEOUT_SECONDS',
    'PROMPT_VERSION',
)

_FUNCTION_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _load_classifier():
    """Fresh classifier.py by file path, module name `phase67_classifier`, no
    sys.modules registration -- mirrors tests/test_inferred_role_vocabulary.py's
    `_load_classifier`."""
    spec = importlib.util.spec_from_file_location(
        'phase67_classifier', str(CLASSIFIER_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_SOURCE_CACHE = {}


def _source_at(sha):
    """classifier.py at `sha`, via `git show`, memoized per test process."""
    if sha not in _SOURCE_CACHE:
        _SOURCE_CACHE[sha] = subprocess.run(
            ['git', 'show', f'{sha}:{CLASSIFIER_REL}'],
            cwd=str(ROOT), capture_output=True, text=True, check=True,
        ).stdout
    return _SOURCE_CACHE[sha]


def _top_level_nodes(source):
    """Map name -> list of top-level nodes defining it (a list, so a duplicate
    definition is visible rather than silently shadowed)."""
    found = {}
    for node in ast.parse(source).body:
        names = []
        if isinstance(node, _FUNCTION_TYPES):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                names = [node.targets[0].id]
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                names = [node.target.id]
        for name in names:
            found.setdefault(name, []).append(node)
    return found


def _pin_violations(current_source, baseline_source, names):
    """Sorted names whose AST dump differs between the two sources, or that
    are missing or duplicated on either side."""
    current = _top_level_nodes(current_source)
    baseline = _top_level_nodes(baseline_source)
    bad = set()
    for name in names:
        cur = current.get(name, [])
        base = baseline.get(name, [])
        if len(cur) != 1 or len(base) != 1:
            bad.add(name)
        elif ast.dump(cur[0]) != ast.dump(base[0]):
            bad.add(name)
    return sorted(bad)


def _function_def(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, _FUNCTION_TYPES) and node.name == name:
            return node
    return None


def _is_confidence_const(node):
    return isinstance(node, ast.Constant) and node.value == 'confidence'


def _confidence_get_violations(source):
    """Every `<x>.get('confidence')` call inside `_validate_assessment` must
    take exactly one argument and no keyword. A subscript load of
    `raw['confidence']` is also a violation (it changes the missing-key path).
    At least one such call must exist, so the check cannot pass vacuously."""
    tree = ast.parse(source)
    func = _function_def(tree, '_validate_assessment')
    if func is None:
        return ['_validate_assessment not found']
    violations = []
    calls = 0
    for node in ast.walk(func):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'get'
                and node.args and _is_confidence_const(node.args[0])):
            calls += 1
            if len(node.args) != 1 or node.keywords:
                violations.append(
                    f"line {node.lineno}: .get('confidence') takes a default "
                    f"or keyword")
        if (isinstance(node, ast.Subscript)
                and isinstance(node.ctx, ast.Load)
                and _is_confidence_const(node.slice)):
            violations.append(f"line {node.lineno}: subscript load of 'confidence'")
    if calls == 0:
        violations.append("no .get('confidence') call found in _validate_assessment")
    return violations


class _DictKeyCollector(ast.NodeVisitor):
    """Collect every dict literal with a 'confidence' key, with the name of
    the innermost enclosing function."""

    def __init__(self):
        self.stack = []
        self.found = []

    def _enter(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = _enter
    visit_AsyncFunctionDef = _enter

    def visit_Dict(self, node):
        for key, value in zip(node.keys, node.values):
            if key is not None and _is_confidence_const(key):
                self.found.append(
                    (self.stack[-1] if self.stack else '<module>', value))
        self.generic_visit(node)


_ABSTAINED_TEST = ast.dump(
    ast.parse('isinstance(assessment, dict)', mode='eval').body)


def _confidence_key_violations(source):
    """Dict literals keyed 'confidence' occur exactly twice: the validated
    value in `_validate_assessment` and the abstained-record 0.0 branch in
    `_build_job_assessment`. Also rejects `dict(confidence=...)` calls."""
    tree = ast.parse(source)
    collector = _DictKeyCollector()
    collector.visit(tree)
    violations = []
    if len(collector.found) != 2:
        violations.append(
            f"expected exactly 2 dict keys named 'confidence', found "
            f"{len(collector.found)}")
    validated = [v for fn, v in collector.found if fn == '_validate_assessment']
    abstained = [v for fn, v in collector.found if fn == '_build_job_assessment']
    others = [fn for fn, _ in collector.found
              if fn not in ('_validate_assessment', '_build_job_assessment')]
    if others:
        violations.append(f"'confidence' dict key in unexpected scope(s): {others}")
    if len(validated) != 1 or not (
            isinstance(validated[0], ast.Name) and validated[0].id == 'confidence'):
        violations.append(
            "_validate_assessment's 'confidence' value is not the Name 'confidence'")
    if len(abstained) != 1:
        violations.append("_build_job_assessment lacks its one 'confidence' key")
    else:
        v = abstained[0]
        ok = (isinstance(v, ast.IfExp)
              and ast.dump(v.test) == _ABSTAINED_TEST
              and isinstance(v.orelse, ast.Constant)
              and isinstance(v.orelse.value, float)
              and v.orelse.value == 0.0)
        if not ok:
            violations.append(
                "_build_job_assessment's 'confidence' is not the abstained "
                "IfExp with a 0.0 orelse")
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == 'dict'
                and any(k.arg == 'confidence' for k in node.keywords)):
            violations.append(f"line {node.lineno}: dict(confidence=...) call")
    return violations


def _confidence_store_violations(source):
    """No store into a 'confidence' subscript, no setdefault('confidence', ...)
    and no update(confidence=...) anywhere in the module."""
    tree = ast.parse(source)
    violations = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Subscript)
                and isinstance(node.ctx, (ast.Store, ast.Del))
                and _is_confidence_const(node.slice)):
            violations.append(f"line {node.lineno}: store into ['confidence']")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (node.func.attr == 'setdefault'
                    and node.args and _is_confidence_const(node.args[0])):
                violations.append(f"line {node.lineno}: setdefault('confidence', ...)")
            if (node.func.attr == 'update'
                    and any(k.arg == 'confidence' for k in node.keywords)):
                violations.append(f"line {node.lineno}: update(confidence=...)")
    return violations


def _instrument_constant_violations(source):
    """The instrument format string occurs exactly once among the module's AST
    constants, and inside `_validate_assessment`."""
    tree = ast.parse(source)
    hits = [n for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and n.value == INSTRUMENT_FORMAT]
    violations = []
    if len(hits) != 1:
        violations.append(
            f"instrument format string occurs {len(hits)} times, expected 1")
        return violations
    func = _function_def(tree, '_validate_assessment')
    inside = func is not None and any(n is hits[0] for n in ast.walk(func))
    if not inside:
        violations.append(
            "instrument format string is not inside _validate_assessment")
    return violations


def _valid_raw(**overrides):
    """A counterfactual raw evaluator response that validates under `{}`."""
    raw = {
        'economic_mechanism': 'labor_substitution',
        'estimated_hours_saved': 2.0,
        'assumed_loaded_rate': 100.0,
        'currency': 'USD',
        'inferred_role': 'engineer',
        'basis': 'reviewed and merged the change',
        'confidence': 0.5,
    }
    raw.update(overrides)
    return raw


class _IsolatedClassifierCase(unittest.TestCase):
    """Load the classifier with HERMES_HOME and REVENIUM_STATE_DIR pointed at a
    temp dir, so a developer's real ~/.hermes/state/revenium/config.json cannot
    change a verdict."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='phase67-')
        self._saved = {k: os.environ.get(k)
                       for k in ('HERMES_HOME', 'REVENIUM_STATE_DIR')}
        os.environ['HERMES_HOME'] = self._tmp
        os.environ['REVENIUM_STATE_DIR'] = os.path.join(self._tmp, 'state')
        self.mod = _load_classifier()

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self._tmp, ignore_errors=True)


class InstrumentTests(_IsolatedClassifierCase):
    """TRU-03: the confidence gate and the exact string Phase 70 greps."""

    _REJECTED = (
        ('none', None),
        ('string', '0.5'),
        ('true', True),
        ('false', False),
        ('nan', float('nan')),
        ('inf', float('inf')),
        ('neg-inf', float('-inf')),
        ('just-below-zero', -0.0001),
        ('just-above-one', 1.0001),
    )

    def _assert_rejected_with_instrument(self, raw):
        with self.assertLogs('revenium_classifier', 'WARNING') as cm:
            result = self.mod._validate_assessment(raw, {}, 'llm', '1')
        self.assertIsNone(result)
        self.assertEqual(len(cm.records), 1, cm.output)
        record = cm.records[0]
        self.assertEqual(record.msg, INSTRUMENT_FORMAT)
        self.assertEqual(len(record.args), 1)
        self.assertEqual(repr(record.args[0]), repr(raw.get('confidence')))

    def test_rejected_values_return_none_and_log_the_instrument(self):
        for label, value in self._REJECTED:
            with self.subTest(value=label):
                self._assert_rejected_with_instrument(_valid_raw(confidence=value))

    def test_absent_key_is_rejected_and_renders_as_none(self):
        raw = _valid_raw()
        del raw['confidence']
        self._assert_rejected_with_instrument(raw)
        with self.assertLogs('revenium_classifier', 'WARNING') as cm:
            self.mod._validate_assessment(raw, {}, 'llm', '1')
        self.assertEqual(
            cm.records[0].getMessage(),
            'revenium-classifier: rejected assessment, confidence outside '
            '[0,1]: None')

    def test_exactly_zero_is_accepted_unchanged(self):
        result = self.mod._validate_assessment(
            _valid_raw(confidence=0.0), {}, 'llm', '1')
        self.assertIsInstance(result, dict)
        self.assertEqual(result['confidence'], 0.0)

    def test_exactly_one_is_accepted_unchanged(self):
        result = self.mod._validate_assessment(
            _valid_raw(confidence=1.0), {}, 'llm', '1')
        self.assertIsInstance(result, dict)
        self.assertEqual(result['confidence'], 1.0)

    def test_mid_range_value_is_accepted_sanity_arm(self):
        result = self.mod._validate_assessment(
            _valid_raw(confidence=0.5), {}, 'llm', '1')
        self.assertIsInstance(result, dict)
        self.assertEqual(result['confidence'], 0.5)

    def test_instrument_format_matches_the_source_constant(self):
        source = CLASSIFIER_PATH.read_text()
        self.assertEqual(_instrument_constant_violations(source), [])


class NoWorkaroundFenceTests(unittest.TestCase):
    """SC2: a missing confidence is never made to pass. Each checker is paired
    with a negative control proving it can fail."""

    @classmethod
    def setUpClass(cls):
        cls.source = CLASSIFIER_PATH.read_text()

    def test_confidence_get_takes_no_default(self):
        self.assertEqual(_confidence_get_violations(self.source), [])

    def test_confidence_get_check_reports_an_injected_default(self):
        needle = 'raw.get("confidence")'
        self.assertIn(needle, self.source)
        mutated = self.source.replace(needle, 'raw.get("confidence", 0.5)', 1)
        self.assertNotEqual(mutated, self.source)
        self.assertTrue(_confidence_get_violations(mutated))

    def test_confidence_get_check_reports_a_subscript_load(self):
        needle = 'confidence = _finite_number(raw.get("confidence"))'
        self.assertIn(needle, self.source)
        mutated = self.source.replace(
            needle, 'confidence = _finite_number(raw["confidence"])', 1)
        violations = _confidence_get_violations(mutated)
        self.assertTrue(any('subscript load' in v for v in violations), violations)

    def test_exactly_two_confidence_dict_keys(self):
        self.assertEqual(_confidence_key_violations(self.source), [])

    def test_confidence_key_check_reports_a_third_dict(self):
        mutated = self.source + "\n_control = {'confidence': 0.7}\n"
        self.assertTrue(_confidence_key_violations(mutated))

    def test_confidence_key_check_reports_a_rewritten_abstained_value(self):
        needle = 'assessment.get("confidence") if isinstance(assessment, dict) else 0.0'
        self.assertIn(needle, self.source)
        mutated = self.source.replace(
            needle,
            'assessment.get("confidence") if isinstance(assessment, dict) else 0.5',
            1)
        self.assertTrue(_confidence_key_violations(mutated))

    def test_no_confidence_store_or_setdefault(self):
        self.assertEqual(_confidence_store_violations(self.source), [])

    def test_confidence_store_check_reports_a_subscript_store(self):
        mutated = self.source + "\n_control = {}\n_control['confidence'] = 0.5\n"
        self.assertTrue(_confidence_store_violations(mutated))

    def test_confidence_store_check_reports_a_setdefault(self):
        mutated = self.source + "\n_control = {}\n_control.setdefault('confidence', 0.5)\n"
        self.assertTrue(_confidence_store_violations(mutated))

    def test_instrument_string_occurs_once_inside_the_validator(self):
        self.assertEqual(_instrument_constant_violations(self.source), [])

    def test_instrument_check_reports_a_reworded_string(self):
        literal = '"' + INSTRUMENT_FORMAT + '"'
        self.assertEqual(self.source.count(literal), 1)
        mutated = self.source.replace(
            literal, '"' + INSTRUMENT_FORMAT.replace('outside', 'not in') + '"')
        self.assertNotEqual(mutated, self.source)
        self.assertTrue(_instrument_constant_violations(mutated))

    def test_instrument_check_reports_a_duplicate(self):
        mutated = self.source + f"\n_CONTROL = {INSTRUMENT_FORMAT!r}\n"
        self.assertTrue(_instrument_constant_violations(mutated))


class ContractPinTests(unittest.TestCase):
    """SC3 and the evaluator contract, against the phase-start commit."""

    @classmethod
    def setUpClass(cls):
        cls.current = CLASSIFIER_PATH.read_text()
        cls.baseline = _source_at(_SC3_BASELINE_SHA)

    def test_fifteen_pinned_names(self):
        self.assertEqual(len(_PINNED_NODES), 15)
        self.assertEqual(len(set(_PINNED_NODES)), 15)

    def test_each_pinned_node_resolves_once_on_both_sides(self):
        current = _top_level_nodes(self.current)
        baseline = _top_level_nodes(self.baseline)
        for name in _PINNED_NODES:
            with self.subTest(name=name):
                self.assertEqual(len(current.get(name, [])), 1)
                self.assertEqual(len(baseline.get(name, [])), 1)

    def test_pinned_nodes_are_ast_identical_to_the_phase_start_commit(self):
        self.assertEqual(
            _pin_violations(self.current, self.baseline, _PINNED_NODES), [])

    def test_pin_check_reports_a_defaulted_confidence(self):
        needle = 'confidence = _finite_number(raw.get("confidence"))'
        self.assertIn(needle, self.current)
        mutated = self.current.replace(
            needle, 'confidence = _finite_number(raw.get("confidence", 0.5))', 1)
        self.assertEqual(
            _pin_violations(mutated, self.baseline, _PINNED_NODES),
            ['_validate_assessment'])

    def test_pin_check_reports_a_changed_label_regex(self):
        needle = 'r"^[a-z][a-z0-9_]{1,47}$"'
        self.assertIn(needle, self.current)
        mutated = self.current.replace(needle, 'r"^[a-z][a-z0-9_]{1,63}$"', 1)
        self.assertEqual(
            _pin_violations(mutated, self.baseline, _PINNED_NODES), ['LABEL_RE'])

    def test_pin_check_reports_a_missing_node(self):
        mutated = self.current.replace('PROMPT_VERSION = 1', 'PROMPT_VER = 1', 1)
        self.assertIn('PROMPT_VERSION', _pin_violations(
            mutated, self.baseline, _PINNED_NODES))

    def test_baseline_source_is_the_genuine_pre_experiment_module(self):
        nodes = _top_level_nodes(self.baseline)
        self.assertIn('_validate_assessment', nodes)
        self.assertIn('_rate_card_role_vocabulary', nodes)

    def test_baseline_sha_is_a_forty_hex_commit(self):
        self.assertRegex(_SC3_BASELINE_SHA, r'^[0-9a-f]{40}$')


class ExperimentRecordShapeTests(unittest.TestCase):
    """The tracked record exists and keeps its shape. Shape only, never the
    conclusion: the verdicts change as the phase's plans land."""

    H1 = ('# Can a prompt change make the evaluator supply confidence? '
          'The Phase 67 experiment')

    @classmethod
    def setUpClass(cls):
        cls.text = RECORD_PATH.read_text(encoding='utf-8')
        cls.lines = cls.text.splitlines()

    def _section(self, heading):
        start = self.lines.index(heading)
        end = len(self.lines)
        for i in range(start + 1, len(self.lines)):
            if self.lines[i].startswith('## '):
                end = i
                break
        return self.lines[start + 1:end]

    def test_opens_with_the_title_and_a_back_link(self):
        self.assertEqual(self.lines[0], self.H1)
        self.assertIn('[← Back to the docs index](README.md)', self.lines[:5])

    def test_verdict_table_has_exactly_three_sourced_rows(self):
        rows = self._section('## Verdict, up front — every criterion, in one table')
        sources = []
        for line in rows:
            m = re.match(r'^\|\s*\d+\s*\|.*\|\s*([^|]+?)\s*\|[^|]*\|\s*$', line)
            if m:
                sources.append(m.group(1))
        self.assertEqual(sources, ['TRU-03 / SC1', 'TRU-03 / SC2', 'SC3'])

    def test_baseline_has_a_glm_5_2_row(self):
        rows = self._section('## The baseline')
        self.assertTrue(
            any(line.startswith('| `z-ai/glm-5.2` |') for line in rows))


if __name__ == '__main__':
    unittest.main()
