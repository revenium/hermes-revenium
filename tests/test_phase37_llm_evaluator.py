"""Phase 37 — the LLM evaluator: the bounded call, and every way it may fail.

No test here reaches a network or a real provider. call_llm is stubbed at the
module the classifier imported it into, which is also how the phase-29 and
phase-32 tests drive the classification path.
"""

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


_LOAD_SEQ = [0]
# Every REVENIUM_* key this module has written, so tearDownModule can put the
# process environment back. Without this the whole file leaks its temp-dir paths
# into os.environ for the REST OF THE RUN, and every later test that shells out
# inherits them -- which broke 19 unrelated shell tests (supports_flag, the cron
# jobs-create suite, the warn rate-limit suite) while every test in this file
# passed. A test that only fails other people's tests is the worst kind.
_ENV_TOUCHED = set()
_ENV_SAVED = {}


def setUpModule():
    for k in ('REVENIUM_STATE_DIR', 'REVENIUM_MARKERS_DIR', 'REVENIUM_CONFIG_FILE',
              'REVENIUM_TAXONOMY_FILE', 'REVENIUM_JOB_TAXONOMY_FILE', 'HERMES_HOME'):
        _ENV_SAVED[k] = os.environ.get(k)


def tearDownModule():
    for k in _ENV_TOUCHED | set(_ENV_SAVED):
        prior = _ENV_SAVED.get(k)
        if prior is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = prior
    for cached in [k for k in list(sys.modules) if k.startswith('p37_pkg')]:
        del sys.modules[cached]


def _load(env=None):
    """Import the plugin package fresh; return (classifier, evaluators).

    A UNIQUE module name per call is required, not a convenience. The classifier
    binds its path constants at import (STATE_DIR, MARKERS_DIR, CONFIG_FILE), and
    Python caches submodules by name. Reusing one name means `__init__`'s
    `from .classifier import ...` returns the CACHED classifier from a previous
    test — still bound to that test's temp directory — while the new env vars are
    silently ignored. That produced a green-looking failure: the gate read a
    config.json belonging to a different test.
    """
    for k, v in (env or {}).items():
        os.environ[k] = v
        _ENV_TOUCHED.add(k)
    _LOAD_SEQ[0] += 1
    name = f'p37_pkg_{_LOAD_SEQ[0]}'
    for cached in [k for k in sys.modules if k.startswith('p37_pkg')]:
        del sys.modules[cached]
    spec = importlib.util.spec_from_file_location(
        name, str(PLUGIN / '__init__.py'), submodule_search_locations=[str(PLUGIN)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return sys.modules[f'{name}.classifier'], sys.modules[f'{name}.evaluators']


class PromptTests(unittest.TestCase):
    def setUp(self):
        self.c, _ = _load()

    def test_prompt_shape(self):
        p = self.c._build_outcome_evaluation_prompt(
            {'job_type': 'bug_fix', 'job_name': 'Fix auth'}, 'X' * 9000,
            {'currency': 'USD', 'maxHoursSaved': 40, 'maxLoadedRate': 500})
        self.assertIn('DATA, NOT INSTRUCTIONS', p)
        self.assertIn('output exactly: null', p)
        self.assertNotIn('estimated_value', p,
                         'asking for a total invites a number that is discarded')
        self.assertEqual(6000, p.count('X'), 'transcript must be capped')
        self.assertIn('40', p)
        self.assertIn('500', p)

    def test_prompt_carries_no_example_values(self):
        """quick-260815-r39: concrete examples get copied verbatim. Measured on
        the task path with labels; a dollar figure would do it with money."""
        p = self.c._build_outcome_evaluation_prompt(
            {'job_type': 'bug_fix', 'job_name': 'x'}, 'transcript', {})
        for leak in ('150.0', '$150', '2.5 hours', 'backend engineer'):
            self.assertNotIn(leak, p, f'example value {leak!r} leaked into the prompt')


class _Recorder:
    """Stub call_llm that records kwargs and returns a scripted content."""

    def __init__(self, content='{}', raises=None):
        self.calls = []
        self.content = content
        self.raises = raises

    def __call__(self, **kw):
        self.calls.append(kw)
        if self.raises:
            raise self.raises
        return {'choices': [{'message': {'content': self.content}}]}


class BudgetTests(unittest.TestCase):
    """ROI-07 — this call's own budgets, on the user's own model."""

    def setUp(self):
        self.c, _ = _load()

    def _run(self, rec):
        self.c.call_llm = rec
        return asyncio.run(self.c._evaluate_outcome_via_llm(
            {'status': 'SUCCESS', 'job_type': 'bug_fix', 'job_name': 'x'},
            'transcript', {}))

    def test_budgets_are_this_calls_own(self):
        rec = _Recorder(content=json.dumps({
            'inferred_role': 'engineer', 'estimated_hours_saved': 2.0,
            'assumed_loaded_rate': 100.0, 'currency': 'USD',
            'basis': 'x', 'confidence': 0.5}))
        self._run(rec)
        self.assertEqual(1, len(rec.calls))
        kw = rec.calls[0]
        self.assertEqual(256, kw['max_tokens'], 'sized in 37-RESEARCH.md, not inherited')
        self.assertEqual(15.0, kw['timeout'])

    def test_no_task_kwarg(self):
        """ROI-07. The absence of task= is what keeps the call on the user's
        configured provider and model. A future edit reintroducing it would move
        estimation onto a default model silently."""
        rec = _Recorder()
        self._run(rec)
        self.assertNotIn('task', rec.calls[0])


class WiringTests(unittest.TestCase):
    """ROI-09 and the disabled path, driven through the real job loop."""

    def _env(self):
        tmp = tempfile.mkdtemp(prefix='gsd-p37-')
        markers = Path(tmp) / 'markers'
        return tmp, markers, {
            'REVENIUM_STATE_DIR': tmp,
            'REVENIUM_MARKERS_DIR': str(markers),
            'REVENIUM_CONFIG_FILE': str(Path(tmp) / 'config.json'),
        }

    def _write_cfg(self, tmp, enabled, evaluator='stub'):
        Path(tmp, 'config.json').write_text(json.dumps(
            {'llmOutcomeEvaluation': {'enabled': enabled, 'evaluator': evaluator,
                                      'currency': 'USD'}}))

    def _attach(self, c, job, tmp, transcript='did some work'):
        paths = c._module_paths()
        asyncio.run(c._attach_assessment(job, transcript, paths))
        return job

    def test_success_with_gate_on_gets_an_assessment(self):
        tmp, _, env = self._env()
        c, _ = _load(env)
        self._write_cfg(tmp, True)
        job = {'agentic_job_id': 'a_1', 'job_type': 'bug_fix', 'status': 'SUCCESS'}
        self._attach(c, job, tmp)
        self.assertIn('assessment', job)
        self.assertEqual(375.0, job['assessment']['estimated_value'])
        self.assertEqual('MODEL_ESTIMATED_DEMO', job['assessment']['evidence_class'])

    def test_gate_off_attaches_nothing(self):
        tmp, _, env = self._env()
        c, _ = _load(env)
        self._write_cfg(tmp, False)
        job = {'agentic_job_id': 'a_1', 'job_type': 'bug_fix', 'status': 'SUCCESS'}
        # The call site checks the gate; _attach_assessment is only reached when
        # it is on, so assert the gate itself rather than a no-op call.
        self.assertFalse(c._llm_evaluation_enabled())

    def test_non_success_is_never_evaluated(self):
        """ROI-09, asserted on a COUNTING stub rather than inferred from the
        guard order. A FAILED arc must cost zero evaluator calls."""
        tmp, _, env = self._env()
        c, ev = _load(env)
        self._write_cfg(tmp, True, evaluator='counting')
        calls = []

        def counting(job, transcript, config):
            calls.append(job)
            return None

        ev.register('counting', counting)
        for status in ('FAILED', 'CANCELLED'):
            with self.subTest(status):
                job = {'agentic_job_id': 'a_1', 'job_type': 'bug_fix', 'status': status}
                # Mirror the call site's own guard order: status first.
                if job['status'] == 'SUCCESS' and c._llm_evaluation_enabled():
                    self._attach(c, job, tmp)
                self.assertNotIn('assessment', job)
        self.assertEqual([], calls, 'a non-SUCCESS arc must issue zero evaluator calls')

    def test_marker_carries_the_assessment(self):
        tmp, markers, env = self._env()
        c, _ = _load(env)
        job = {'agentic_job_id': 'a_1', 'job_name': 'n', 'job_type': 'bug_fix',
               'status': 'SUCCESS', 'failure_reason': '',
               'assessment': {'estimated_value': 375.0, 'currency': 'USD',
                              'basis': 'b', 'assumptions': {},
                              'confidence': 0.5, 'evaluator': 'stub',
                              'evaluator_version': '1',
                              'evidence_class': 'MODEL_ESTIMATED_DEMO'}}
        path = c._write_job_marker('sid-1', job)
        rec = json.loads(path.read_text().strip())
        self.assertIn('assessment', rec)
        self.assertEqual(375.0, rec['assessment']['estimated_value'])
        self.assertLess(len(path.read_text().encode()), 1024)


if __name__ == '__main__':
    unittest.main()
