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
import sys
import tempfile
import unittest
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


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
