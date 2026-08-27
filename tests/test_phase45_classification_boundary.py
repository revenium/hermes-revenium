"""Phase 45 Plan 04 — the classification boundary (EGV-01, D-13): one
contract covering BOTH turn-level task_type labelling and job/arc
inference, a registry, a deterministic non-LLM fixture that displaces the
built-in end to end, and the fail-open behaviour every way that could go
wrong is required to degrade to.

Every test here runs OFFLINE, matching tests/test_phase36_evaluator_seam.py's
own module docstring: no provider, no network, no subprocess -- the
DelegationTests class below proves the fixture ran precisely by making the
injected call_llm fail the test if it is ever invoked, never by asserting on
a return value alone.

Registrant hygiene: every test in this file that registers a throwaway
implementation into the module-level `classification._REGISTRY` (a module
loaded fresh per test via `_load_classification()`) gets its own fresh
module object, so registration in one test cannot leak into another --
`last-registration-wins` is a documented property of the shared
BoundaryRegistry helper (boundary_registry.py), and a leaked registrant is
the obvious way these tests could start lying to each other.
"""

import ast
import asyncio
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'


def _load_classification():
    """Fresh classification.py by file path, no package parent, no
    sys.path entry -- the idiom tests/test_phase36_evaluator_seam.py's
    _load_evaluators() and tests/test_phase45_contract_only_boundaries.py's
    _load_cohort_impact() both use. A fresh module object per call means a
    fresh, empty-but-for-the-shipped-fixture `_REGISTRY` per call -- no
    cross-test registration leakage."""
    spec = importlib.util.spec_from_file_location(
        'phase45_classification', str(PLUGIN / 'classification.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_boundary_registry():
    spec = importlib.util.spec_from_file_location(
        'phase45_boundary_registry_classification', str(PLUGIN / 'boundary_registry.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_classifier(env: "dict | None" = None):
    """Mirror of tests/test_phase36_evaluator_seam.py's own _load_classifier,
    duplicated here for the same reason every other Phase 45 test file's
    copy of it is."""
    env = env or {}
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(
            'phase45_classifier_classification_boundary', str(PLUGIN / 'classifier.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class ContractTests(unittest.TestCase):
    """The registry surface itself, and the shipped fixture's declared
    identity."""

    def setUp(self):
        self.cl = _load_classification()
        self.br = _load_boundary_registry()

    def test_fresh_import_resolves_only_the_shipped_fixture(self):
        self.assertEqual(['keyword_classification_fixture'], self.cl.registered())
        self.assertIsNotNone(self.cl.resolve('keyword_classification_fixture'))
        self.assertIsNone(self.cl.resolve('llm'))

    def test_shipped_fixture_declares_activity_measured(self):
        self.assertEqual(
            'ACTIVITY_MEASURED',
            self.cl.resolve_evidence_class('keyword_classification_fixture'),
        )

    def test_shipped_fixture_is_not_masquerading(self):
        self.assertFalse(
            self.br.is_masquerading(self.cl._REGISTRY, 'keyword_classification_fixture')
        )

    def test_resolve_unknown_name_is_none_empty_empty(self):
        self.assertIsNone(self.cl.resolve('nope'))
        self.assertEqual('', self.cl.resolve_version('nope'))
        self.assertEqual('', self.cl.resolve_evidence_class('nope'))

    def test_registry_boundary_name(self):
        self.assertEqual('classification', self.cl._REGISTRY.boundary)

    def test_module_loads_by_file_path_with_no_package_parent(self):
        # If the import fallback chain were broken this would raise during
        # _load_classification() itself, above in setUp -- this test just
        # names the property explicitly.
        self.assertIsNotNone(self.cl)

    def test_import_graph_excludes_host_and_classifier_modules(self):
        """D-08: parsed with ast, not grepped -- the module docstring
        DOCUMENTS the dependency-direction rule in prose, so a substring
        search for 'import classifier' matches the very comment explaining
        the invariant and fails on a compliant file."""
        tree = ast.parse((PLUGIN / 'classification.py').read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split('.')[0])
        forbidden = {'classifier', 'agent', 'os', 'pathlib', 'sqlite3', 'subprocess'}
        self.assertEqual(set(), imported & forbidden)


class KeywordFixtureTests(unittest.TestCase):
    """One method per behavior bullet of 45-04-PLAN.md Task 1."""

    def setUp(self):
        self.cl = _load_classification()
        self.fn = self.cl._keyword_classification_fixture

    def test_task_type_overlapping_label_is_returned(self):
        request = {
            'kind': 'task_type',
            'context': {'message': 'please review this pull request diff'},
            'response_preview': 'looked at the code review comments',
            'labels': ['code_review', 'database_migration'],
        }
        result = self.fn(request, {})
        self.assertEqual({'task_type': 'code_review'}, result)

    def test_task_type_no_overlap_abstains(self):
        request = {
            'kind': 'task_type',
            'context': {'message': 'completely unrelated words here'},
            'response_preview': 'nothing matches anything',
            'labels': ['code_review', 'database_migration'],
        }
        self.assertIsNone(self.fn(request, {}))

    def test_jobs_request_returns_validate_job_shaped_dicts(self):
        request = {
            'kind': 'jobs',
            'transcript': (
                'fixed the auth regression in the login module\n\n'
                'wrote tests for the auth regression fix'
            ),
            'labels': ['bug_fix', 'test_authoring'],
        }
        result = self.fn(request, {})
        self.assertIsNotNone(result)
        jobs = result['jobs']
        self.assertGreaterEqual(len(jobs), 1)
        for job in jobs:
            self.assertIn('agentic_job_id', job)
            self.assertIsInstance(job['agentic_job_id'], str)
            self.assertTrue(job['agentic_job_id'])
            self.assertIn('job_type', job)
            self.assertRegex(job['job_type'], r'^[a-z][a-z0-9_]{1,47}$')
            self.assertEqual('SUCCESS', job['status'])

    def test_jobs_request_empty_transcript_abstains(self):
        self.assertIsNone(self.fn({'kind': 'jobs', 'transcript': '', 'labels': []}, {}))

    def test_jobs_request_non_string_transcript_abstains(self):
        self.assertIsNone(self.fn({'kind': 'jobs', 'transcript': None, 'labels': []}, {}))
        self.assertIsNone(self.fn({'kind': 'jobs', 'transcript': 12345, 'labels': []}, {}))

    def test_unrecognised_kind_returns_none(self):
        self.assertIsNone(self.fn({'kind': 'something_else'}, {}))

    def test_missing_kind_returns_none(self):
        self.assertIsNone(self.fn({}, {}))

    def test_non_dict_request_never_raises(self):
        self.assertIsNone(self.fn('not a dict', {}))
        self.assertIsNone(self.fn(None, {}))
        self.assertIsNone(self.fn(123, {}))

    def test_non_dict_config_never_raises(self):
        request = {
            'kind': 'task_type',
            'context': {'message': 'review this code review diff'},
            'response_preview': '',
            'labels': ['code_review'],
        }
        result = self.fn(request, 'not a dict')
        self.assertEqual({'task_type': 'code_review'}, result)
        result2 = self.fn(request, None)
        self.assertEqual({'task_type': 'code_review'}, result2)

    def test_makes_no_model_network_or_clock_call(self):
        """Proven by the module's own import graph excluding every module
        that would make a model, network, or clock call possible."""
        tree = ast.parse((PLUGIN / 'classification.py').read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split('.')[0])
        forbidden = {'time', 'datetime', 'socket', 'requests', 'urllib', 'http', 'ssl',
                     'asyncio', 'agent'}
        self.assertEqual(set(), imported & forbidden)


# ---------------------------------------------------------------------------
# DelegationTests / FailOpenTests -- driving the REAL run_classification_async
# end to end. Both classes load the whole plugin PACKAGE (not classifier.py
# alone), the same idiom tests/test_phase29_hook_dedup.py and
# tests/test_phase39_log_taxonomy.py both use, because classifier.py's own
# `from . import classification as _cl` relative import only resolves when
# classifier.py is loaded AS a submodule of a real package (submodule_search_
# locations set) -- loading classifier.py alone by file path (ContractTests'
# and KeywordFixtureTests' idiom above) leaves that relative import with no
# parent package to resolve against.
#
# A fresh, uniquely-named package per test (via _load_plugin_module with a
# counter-suffixed name) means each test gets its OWN classification._REGISTRY
# -- no throwaway registrant registered in one test can be resolved by
# another, so no explicit tearDown/registry-restore is required. This is the
# "reload the module" half of the registrant-hygiene rule stated in this
# file's own module docstring.
# ---------------------------------------------------------------------------

_PKG_SEQ = [0]


def _load_plugin_module():
    """Load the plugin package fresh, under a name unique to this call --
    duplicated from tests/test_phase29_hook_registration.py's own
    _load_plugin_module (not imported, per this phase's established
    duplicate-not-import discipline for test infra that must stay
    self-contained). submodule_search_locations is required because
    __init__.py performs a relative import (`from .classifier import ...`);
    a bare spec_from_file_location(name, path) would fail that import."""
    _PKG_SEQ[0] += 1
    mod_name = f'phase45_classification_delegation_{_PKG_SEQ[0]}'
    pkg_init = PLUGIN / '__init__.py'
    spec = importlib.util.spec_from_file_location(
        mod_name, str(pkg_init), submodule_search_locations=[str(PLUGIN)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod_name, mod


def _classifier_submodule(mod_name):
    """The plugin's relative import binds a SUBMODULE named
    f'{mod_name}.classifier' -- patch call_llm / helpers on THAT submodule
    object, not on a bare `classifier` module, or the patch will not be seen
    by the plugin's own module-global references (same rule
    tests/test_phase29_hook_registration.py's own copy documents)."""
    return sys.modules[f'{mod_name}.classifier']


def _classification_submodule(mod_name):
    """The SAME classification.py instance classifier_submodule's own
    `from . import classification` bound -- register a throwaway
    implementation HERE for it to be resolvable by name from the real
    run_classification_async call sites."""
    return sys.modules[f'{mod_name}.classification']


def _write_state_db(hermes_home: Path, session_id: str, transcript_paragraphs):
    """A minimal state.db with the `messages` table
    classifier._read_session_transcript reads -- schema and idiom mirror
    tests/test_repository.py's own state.db fixture for that function.
    Absent entirely, _read_session_transcript fails open to "" (D-04), which
    is exactly what the task-type-only delegation test below relies on by
    NOT calling this helper at all."""
    hermes_home.mkdir(parents=True, exist_ok=True)
    db_path = hermes_home / 'state.db'
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        'CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, '
        'role TEXT, content TEXT, timestamp REAL)'
    )
    ts = 0.0
    for para in transcript_paragraphs:
        conn.execute(
            'INSERT INTO messages (session_id, role, content, timestamp) '
            'VALUES (?, ?, ?, ?)',
            (session_id, 'user', para, ts),
        )
        ts += 1.0
    conn.commit()
    conn.close()


def _write_config(state_dir: Path, boundaries=None):
    cfg = {}
    if boundaries is not None:
        cfg['boundaries'] = boundaries
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / 'config.json').write_text(json.dumps(cfg))


def _write_taxonomy(state_dir: Path, filename: str, labels):
    state_dir.mkdir(parents=True, exist_ok=True)
    data = {'labels': {label: {} for label in labels}}
    (state_dir / filename).write_text(json.dumps(data))


class _FailIfCalled:
    """A call_llm stand-in that fails the enclosing TestCase if it is ever
    invoked -- DelegationTests' central instrument: "the fixture ran" is
    proven by the model call never happening, not by inspecting a return
    value."""

    def __init__(self, test_case):
        self._test_case = test_case

    def __call__(self, **kwargs):
        self._test_case.fail(
            'call_llm must not be invoked when the classification boundary '
            'resolved to a non-LLM implementation -- the fixture failed to '
            'displace the built-in'
        )


class _ScriptedRecorder:
    """A call_llm stand-in returning a fixed, openai-SDK-shaped response.
    Records every call so a fallback-to-built-in test can assert the
    built-in path really ran, not merely that the recorded label matches."""

    def __init__(self, content: str):
        self.content = content
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return {'choices': [{'message': {'content': self.content}}]}


def _task_records(markers_path: Path) -> list:
    if not markers_path.is_file():
        return []
    recs = [json.loads(l) for l in markers_path.read_text(encoding='utf-8').splitlines()]
    return [r for r in recs if 'operation_type' in r]


def _job_records(markers_path: Path) -> list:
    if not markers_path.is_file():
        return []
    recs = [json.loads(l) for l in markers_path.read_text(encoding='utf-8').splitlines()]
    return [r for r in recs if r.get('kind') == 'job']


class DelegationTests(unittest.TestCase):
    """The REAL run_classification_async, end to end, with a classifier
    that has never seen a model. One method per positive behavior bullet of
    45-04-PLAN.md Task 3."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gsd-p45-04-delegation-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.hermes_home = Path(self.tmp) / 'hh'
        self.state_dir = self.hermes_home / 'state' / 'revenium'
        self.markers_dir = self.state_dir / 'markers'
        self.markers_dir.mkdir(parents=True)

    def _env(self):
        return {
            'HERMES_HOME': str(self.hermes_home),
            'REVENIUM_STATE_DIR': str(self.state_dir),
            'REVENIUM_MARKERS_DIR': str(self.markers_dir),
        }

    def test_fixture_displaces_builtin_for_task_type(self):
        _write_config(self.state_dir, boundaries={'classification': 'keyword_classification_fixture'})
        _write_taxonomy(self.state_dir, 'task-taxonomy.json', ['code_review', 'database_migration'])
        sid = 'delegation-task-type-sid'

        for k, v in self._env().items():
            os.environ[k] = v
        try:
            mod_name, _ = _load_plugin_module()
            classifier_sub = _classifier_submodule(mod_name)
            classifier_sub.call_llm = _FailIfCalled(self)

            asyncio.run(classifier_sub.run_classification_async(
                session_id=sid,
                message='please review this code review diff',
                response='looked at the pull request comments',
            ))
        finally:
            for k in self._env():
                os.environ.pop(k, None)

        records = _task_records(self.markers_dir / f'{sid}.jsonl')
        self.assertTrue(records, 'no task marker pair was written')
        task_types = {r.get('task_type') for r in records}
        self.assertEqual({'code_review'}, task_types)

    def test_job_inference_also_runs_through_the_fixture_and_validates(self):
        _write_config(self.state_dir, boundaries={'classification': 'keyword_classification_fixture'})
        _write_taxonomy(self.state_dir, 'task-taxonomy.json', ['code_review'])
        _write_taxonomy(self.state_dir, 'job-taxonomy.json', ['bug_fix', 'test_authoring'])
        sid = 'delegation-jobs-sid'
        _write_state_db(self.hermes_home, sid, [
            'fixed the authentication regression in the login module',
            'wrote tests for the authentication regression fix',
        ])

        for k, v in self._env().items():
            os.environ[k] = v
        try:
            mod_name, _ = _load_plugin_module()
            classifier_sub = _classifier_submodule(mod_name)
            classifier_sub.call_llm = _FailIfCalled(self)

            asyncio.run(classifier_sub.run_classification_async(
                session_id=sid,
                message='please fix the bug',
                response='fixed it and added tests',
            ))
        finally:
            for k in self._env():
                os.environ.pop(k, None)

        jobs = _job_records(self.markers_dir / f'{sid}.jsonl')
        self.assertTrue(jobs, 'no job markers were written')
        for job in jobs:
            self.assertIn('agentic_job_id', job)
            self.assertTrue(job['agentic_job_id'])
            self.assertRegex(job['job_type'], r'^[a-z][a-z0-9_]{1,47}$')
            self.assertEqual('SUCCESS', job['status'])

    def test_boundaries_absent_uses_builtin_unchanged(self):
        _write_config(self.state_dir, boundaries=None)
        _write_taxonomy(self.state_dir, 'task-taxonomy.json', [])
        sid = 'delegation-builtin-sid'
        recorder = _ScriptedRecorder('database_migration')

        for k, v in self._env().items():
            os.environ[k] = v
        try:
            mod_name, _ = _load_plugin_module()
            classifier_sub = _classifier_submodule(mod_name)
            classifier_sub.call_llm = recorder

            asyncio.run(classifier_sub.run_classification_async(
                session_id=sid,
                message='please migrate the users table',
                response='ran the migration',
            ))
        finally:
            for k in self._env():
                os.environ.pop(k, None)

        self.assertTrue(recorder.calls, 'the built-in llm classifier must have run')
        records = _task_records(self.markers_dir / f'{sid}.jsonl')
        task_types = {r.get('task_type') for r in records}
        self.assertEqual({'database_migration'}, task_types)


class FailOpenTests(unittest.TestCase):
    """Every way classification could go wrong degrades to today's
    behaviour. One method per negative behavior bullet of 45-04-PLAN.md
    Task 3."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gsd-p45-04-failopen-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.hermes_home = Path(self.tmp) / 'hh'
        self.state_dir = self.hermes_home / 'state' / 'revenium'
        self.markers_dir = self.state_dir / 'markers'
        self.markers_dir.mkdir(parents=True)

    def _env(self):
        return {
            'HERMES_HOME': str(self.hermes_home),
            'REVENIUM_STATE_DIR': str(self.state_dir),
            'REVENIUM_MARKERS_DIR': str(self.markers_dir),
        }

    def _run(self, sid, message='hello world', response='hi there'):
        mod_name, _ = _load_plugin_module()
        classifier_sub = _classifier_submodule(mod_name)
        return mod_name, classifier_sub

    def test_unresolved_name_falls_back_to_builtin_and_completes(self):
        _write_config(self.state_dir, boundaries={'classification': 'no_such_implementation'})
        _write_taxonomy(self.state_dir, 'task-taxonomy.json', [])
        sid = 'failopen-unresolved-sid'
        recorder = _ScriptedRecorder('database_migration')

        for k, v in self._env().items():
            os.environ[k] = v
        try:
            mod_name, classifier_sub = self._run(sid)
            classifier_sub.call_llm = recorder
            asyncio.run(classifier_sub.run_classification_async(
                session_id=sid, message='migrate the schema', response='done',
            ))
        finally:
            for k in self._env():
                os.environ.pop(k, None)

        self.assertTrue(recorder.calls, 'an unresolved name must fall back to the built-in')
        records = _task_records(self.markers_dir / f'{sid}.jsonl')
        task_types = {r.get('task_type') for r in records}
        self.assertEqual({'database_migration'}, task_types)

    def test_raising_implementation_falls_back_to_builtin_and_completes(self):
        _write_config(self.state_dir, boundaries={'classification': 'throwaway_raiser_fixture'})
        _write_taxonomy(self.state_dir, 'task-taxonomy.json', [])
        sid = 'failopen-raising-sid'
        recorder = _ScriptedRecorder('database_migration')

        def _raiser(request, config):
            raise RuntimeError('boom -- this implementation always raises')

        for k, v in self._env().items():
            os.environ[k] = v
        try:
            mod_name, classifier_sub = self._run(sid)
            classification_sub = _classification_submodule(mod_name)
            classification_sub.register('throwaway_raiser_fixture', _raiser, '1', evidence_class='')
            classifier_sub.call_llm = recorder
            asyncio.run(classifier_sub.run_classification_async(
                session_id=sid, message='migrate the schema', response='done',
            ))
        finally:
            for k in self._env():
                os.environ.pop(k, None)

        self.assertTrue(recorder.calls, 'a raising implementation must fall back to the built-in')
        records = _task_records(self.markers_dir / f'{sid}.jsonl')
        task_types = {r.get('task_type') for r in records}
        self.assertEqual({'database_migration'}, task_types)

    def test_rejected_label_becomes_unclassified_and_never_reaches_taxonomy(self):
        _write_config(self.state_dir, boundaries={'classification': 'throwaway_bad_label_fixture'})
        _write_taxonomy(self.state_dir, 'task-taxonomy.json', [])
        sid = 'failopen-rejected-label-sid'
        bad_label = 'BAD LABEL!! not snake_case'

        def _bad_labeler(request, config):
            return {'task_type': bad_label}

        for k, v in self._env().items():
            os.environ[k] = v
        try:
            mod_name, classifier_sub = self._run(sid)
            classification_sub = _classification_submodule(mod_name)
            classification_sub.register(
                'throwaway_bad_label_fixture', _bad_labeler, '1', evidence_class='')
            # Must NOT be invoked: the throwaway implementation resolves and
            # succeeds (it returns, it does not raise), so no fallback to
            # the built-in should ever be attempted.
            classifier_sub.call_llm = _FailIfCalled(self)
            asyncio.run(classifier_sub.run_classification_async(
                session_id=sid, message='irrelevant', response='irrelevant',
            ))
        finally:
            for k in self._env():
                os.environ.pop(k, None)

        records = _task_records(self.markers_dir / f'{sid}.jsonl')
        task_types = {r.get('task_type') for r in records}
        self.assertEqual({'unclassified'}, task_types)

        taxonomy_path = self.state_dir / 'task-taxonomy.json'
        on_disk = taxonomy_path.read_text(encoding='utf-8') if taxonomy_path.is_file() else ''
        self.assertNotIn(bad_label, on_disk)
        self.assertNotIn('BAD LABEL', on_disk)

    def test_rejection_is_logged_with_repr_of_the_label(self):
        _write_config(self.state_dir, boundaries={'classification': 'throwaway_bad_label_fixture_2'})
        _write_taxonomy(self.state_dir, 'task-taxonomy.json', [])
        sid = 'failopen-rejected-label-logged-sid'
        bad_label = 'BAD LABEL!! not snake_case'

        def _bad_labeler(request, config):
            return {'task_type': bad_label}

        for k, v in self._env().items():
            os.environ[k] = v
        try:
            mod_name, classifier_sub = self._run(sid)
            classification_sub = _classification_submodule(mod_name)
            classification_sub.register(
                'throwaway_bad_label_fixture_2', _bad_labeler, '1', evidence_class='')
            classifier_sub.call_llm = _FailIfCalled(self)
            with self.assertLogs('revenium_classifier', level='WARNING') as cm:
                asyncio.run(classifier_sub.run_classification_async(
                    session_id=sid, message='irrelevant', response='irrelevant',
                ))
        finally:
            for k in self._env():
                os.environ.pop(k, None)

        messages = [r.getMessage() for r in cm.records]
        self.assertTrue(
            any(repr(bad_label) in m for m in messages),
            f'expected a log line rendering the rejected label with %r, got: {messages}',
        )

    def test_running_this_module_twice_is_stable(self):
        """The set-length half of registrant hygiene: driving the SAME
        fail-open scenario twice in one process (two fresh packages, two
        fresh classification._REGISTRY instances) produces the identical
        result both times -- nothing leaked from the first run into the
        second."""
        results = []
        for i in range(2):
            _write_config(self.state_dir, boundaries={'classification': 'no_such_implementation'})
            _write_taxonomy(self.state_dir, 'task-taxonomy.json', [])
            sid = f'failopen-stability-sid-{i}'
            recorder = _ScriptedRecorder('database_migration')
            for k, v in self._env().items():
                os.environ[k] = v
            try:
                mod_name, classifier_sub = self._run(sid)
                classifier_sub.call_llm = recorder
                asyncio.run(classifier_sub.run_classification_async(
                    session_id=sid, message='migrate the schema', response='done',
                ))
            finally:
                for k in self._env():
                    os.environ.pop(k, None)
            records = _task_records(self.markers_dir / f'{sid}.jsonl')
            results.append({r.get('task_type') for r in records})
        self.assertEqual(results[0], results[1])
        self.assertEqual({'database_migration'}, results[0])


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
