"""Phase 39 Plan 01 — the six ROI-14 outcome words, proven distinguishable.

ROI-14 requires `evaluated, abstained, invalid, timed-out, deferred, reported`
to be tellable apart in the log. This file covers the FOUR in-process words
(`evaluated`, `abstained`, `invalid`, `timed-out`) — `deferred`/`reported` are
cron-side (hermes-report.sh) and out of scope here.

Every row drives the REAL `_attach_assessment` path through `assertLogs`, never
by reading source. `invalid` and `timed-out` do not exist as distinct outcomes
before this plan: `abstained` is the only reachable word from a malformed or
timed-out response today. This file lands RED against unmodified classifier.py
on purpose — see 39-01-PLAN.md Task 1.
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


# ---------------------------------------------------------------------------
# Copied from tests/test_phase37_llm_evaluator.py's _load() harness, per the
# plan's explicit instruction: the unique-module-name-per-call detail is
# load-bearing, not a convenience. classifier.py binds STATE_DIR / MARKERS_DIR
# / CONFIG_FILE at import time, and Python caches submodules by name — reusing
# one name hands back a cached classifier still pointed at a previous test's
# tmpdir, so the gate silently reads someone else's config.json. That failure
# looks green.
# ---------------------------------------------------------------------------
_LOAD_SEQ = [0]
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
    for cached in [k for k in list(sys.modules) if k.startswith('p39_pkg')]:
        del sys.modules[cached]


def _load(env=None):
    """Import the plugin package fresh; return (classifier, evaluators)."""
    for k, v in (env or {}).items():
        os.environ[k] = v
        _ENV_TOUCHED.add(k)
    _LOAD_SEQ[0] += 1
    name = f'p39_pkg_{_LOAD_SEQ[0]}'
    for cached in [k for k in sys.modules if k.startswith('p39_pkg')]:
        del sys.modules[cached]
    spec = importlib.util.spec_from_file_location(
        name, str(PLUGIN / '__init__.py'), submodule_search_locations=[str(PLUGIN)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return sys.modules[f'{name}.classifier'], sys.modules[f'{name}.evaluators']


class _Recorder:
    """Stub call_llm that returns a scripted content or raises."""

    def __init__(self, content='{}', raises=None):
        self.calls = []
        self.content = content
        self.raises = raises

    def __call__(self, **kw):
        self.calls.append(kw)
        if self.raises:
            raise self.raises
        return {'choices': [{'message': {'content': self.content}}]}


class LogTaxonomyMatrixTests(unittest.TestCase):
    """Task 1 — the six-row matrix, driven by injection through
    `_attach_assessment`, never by reading source."""

    def _ctx(self, evaluator='llm'):
        tmp = tempfile.mkdtemp(prefix='gsd-p39-')
        env = {'REVENIUM_STATE_DIR': tmp,
               'REVENIUM_MARKERS_DIR': str(Path(tmp) / 'markers'),
               'REVENIUM_CONFIG_FILE': str(Path(tmp) / 'config.json')}
        Path(tmp, 'config.json').write_text(json.dumps(
            {'llmOutcomeEvaluation': {'enabled': True, 'evaluator': evaluator,
                                      'currency': 'USD'}}))
        c, ev = _load(env)
        return c, ev, tmp

    def _run(self, c):
        job = {'agentic_job_id': 'a_1', 'job_name': 'n', 'job_type': 'bug_fix',
               'status': 'SUCCESS'}
        with self.assertLogs('revenium_classifier', level='INFO') as cm:
            # ROI-08: must not raise, regardless of row.
            asyncio.run(c._attach_assessment(job, 'transcript', c._module_paths()))
        messages = [r.getMessage() for r in cm.records]
        # ROI-08: no assessment attached on any error/abstention row.
        self.assertNotIn('assessment', job)
        return messages

    def test_deliberate_abstention_is_the_only_abstained_row(self):
        """call_llm returns the literal `null` -> the existing abstention INFO
        line fires, and no line containing "invalid" or "timed-out" fires."""
        c, ev, tmp = self._ctx(evaluator='llm')
        c.call_llm = _Recorder(content='null')
        messages = self._run(c)
        self.assertTrue(
            any('outcome evaluation abstained for job=' in m for m in messages),
            f'expected the abstention line, got: {messages}')
        self.assertFalse(any('invalid' in m for m in messages), messages)
        self.assertFalse(any('timed-out' in m for m in messages), messages)

    def test_malformed_response_is_invalid_not_abstained(self):
        """call_llm returns prose with no JSON object -> a record whose message
        contains `outcome evaluation invalid for job=` fires, and "abstained"
        appears in NO record from that call."""
        c, ev, tmp = self._ctx(evaluator='llm')
        c.call_llm = _Recorder(content='Sorry, I cannot help with that request.')
        messages = self._run(c)
        self.assertTrue(
            any('outcome evaluation invalid for job=' in m for m in messages),
            f'expected the invalid line, got: {messages}')
        self.assertFalse(any('abstained' in m for m in messages), messages)

    def test_empty_response_is_invalid_not_abstained(self):
        """An empty body is a broken response, not the documented abstention
        token."""
        c, ev, tmp = self._ctx(evaluator='llm')
        c.call_llm = _Recorder(content='')
        messages = self._run(c)
        self.assertTrue(
            any('outcome evaluation invalid for job=' in m for m in messages),
            f'expected the invalid line, got: {messages}')
        self.assertFalse(any('abstained' in m for m in messages), messages)

    def test_non_object_json_is_invalid_not_abstained(self):
        c, ev, tmp = self._ctx(evaluator='llm')
        c.call_llm = _Recorder(content='[1, 2]')
        messages = self._run(c)
        self.assertTrue(
            any('outcome evaluation invalid for job=' in m for m in messages),
            f'expected the invalid line, got: {messages}')
        self.assertFalse(any('abstained' in m for m in messages), messages)

    def test_provider_timeout_is_timed_out_not_generic(self):
        """call_llm raises TimeoutError -> a record containing
        `outcome evaluation timed-out for job=` fires, and the generic
        "LLM call failed" line does not."""
        c, ev, tmp = self._ctx(evaluator='llm')
        c.call_llm = _Recorder(raises=TimeoutError())
        messages = self._run(c)
        self.assertTrue(
            any('outcome evaluation timed-out for job=' in m for m in messages),
            f'expected the timed-out line, got: {messages}')
        self.assertFalse(any('LLM call failed' in m for m in messages), messages)

    def test_evaluator_callable_timeout_is_timed_out_not_generic(self):
        """A registered evaluator raises `asyncio.TimeoutError` directly --
        never entering _evaluate_outcome_via_llm -- and still produces the same
        `timed-out` record. Second site: tests/test_phase37_llm_evaluator.py:253
        proves the job survives that path today; nothing proves the line is
        distinguishable."""
        c, ev, tmp = self._ctx(evaluator='raises-timeout')

        def raises_timeout(job, transcript, config):
            raise asyncio.TimeoutError()

        ev.register('raises-timeout', raises_timeout)
        messages = self._run(c)
        self.assertTrue(
            any('outcome evaluation timed-out for job=' in m for m in messages),
            f'expected the timed-out line, got: {messages}')
        self.assertFalse(any('LLM call failed' in m for m in messages), messages)

    def test_evaluator_generic_failure_regression_unchanged(self):
        """A registered evaluator raising a plain exception still produces the
        existing generic failure WARNING, unchanged."""
        c, ev, tmp = self._ctx(evaluator='raises-boom')

        class Boom(Exception):
            pass

        def raises_boom(job, transcript, config):
            raise Boom('evaluator exploded')

        ev.register('raises-boom', raises_boom)
        messages = self._run(c)
        self.assertTrue(
            any('outcome evaluation failed for job=' in m for m in messages),
            f'expected the generic failure line, got: {messages}')
        self.assertFalse(any('timed-out' in m for m in messages), messages)
        self.assertFalse(any('invalid' in m for m in messages), messages)


if __name__ == '__main__':
    unittest.main()
