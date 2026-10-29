"""The outcome evaluator is asked once more when its answer omits `confidence`.

On the reference host 2 of 98 jobs over 14 days got no Value in Revenium because
the evaluator's JSON answer left out `confidence`: the validator rejected it, the
sidecar recorded abstention `rejected`, and nothing ever asked again. This module
pins the single retry in `_attach_assessment`.
"""

import asyncio
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'

FROZEN_NOW = 1800000000.0
JOB_ID = 'cay-job-1'

_LOAD_SEQ = [0]
_ENV_KEYS = ('REVENIUM_STATE_DIR', 'REVENIUM_MARKERS_DIR', 'REVENIUM_CONFIG_FILE',
             'REVENIUM_TAXONOMY_FILE', 'REVENIUM_JOB_TAXONOMY_FILE', 'HERMES_HOME')
_ENV_SAVED = {}


def setUpModule():
    for k in _ENV_KEYS:
        _ENV_SAVED[k] = os.environ.get(k)


def tearDownModule():
    for k, prior in _ENV_SAVED.items():
        if prior is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = prior
    for cached in [k for k in list(sys.modules) if k.startswith('cay_')]:
        del sys.modules[cached]


def _load_package(plugin_dir, prefix):
    """Import a plugin package fresh; return (classifier, evaluators).

    A unique package name per call matters: classifier.py binds its state paths
    at import time and Python caches submodules by name.
    """
    _LOAD_SEQ[0] += 1
    name = f'{prefix}_{_LOAD_SEQ[0]}'
    spec = importlib.util.spec_from_file_location(
        name, str(Path(plugin_dir) / '__init__.py'),
        submodule_search_locations=[str(plugin_dir)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return sys.modules[f'{name}.classifier'], sys.modules[f'{name}.evaluators']


class _SequencedLLM:
    """Stub call_llm: each call consumes the next scripted step.

    A step is (content, served_model_or_None), or an exception instance to raise.
    """

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = []

    def __call__(self, **kw):
        self.calls.append(kw)
        if len(self.calls) > len(self.steps):
            raise AssertionError(f'call_llm called {len(self.calls)} times, only '
                                 f'{len(self.steps)} steps scripted')
        step = self.steps[len(self.calls) - 1]
        if isinstance(step, BaseException):
            raise step
        content, model = step
        response = {'choices': [{'message': {'content': content}}]}
        if model is not None:
            response['model'] = model
        return response


def _answer(**overrides):
    """A labor_substitution answer; pass key=_DROP to remove a key."""
    body = {
        'economic_mechanism': 'labor_substitution',
        'inferred_role': 'engineer',
        'estimated_hours_saved': 2.0,
        'assumed_loaded_rate': 100.0,
        'currency': 'USD',
        'basis': 'x',
        'confidence': 0.6,
    }
    for key, value in overrides.items():
        if value is _DROP:
            body.pop(key, None)
        else:
            body[key] = value
    return json.dumps(body)


_DROP = object()


def _job():
    return {'agentic_job_id': JOB_ID, 'job_name': 'n', 'job_type': 'bug_fix',
            'status': 'SUCCESS'}


def _eval_config(**overrides):
    cfg = {'enabled': True, 'evaluator': 'llm', 'currency': 'USD',
           'reportModelEstimates': True, 'experimentalReportEstimates': True}
    cfg.update(overrides)
    return cfg


class _Run:
    """One fresh, isolated `_attach_assessment` run against a given plugin dir."""

    def __init__(self, plugin_dir=PLUGIN, prefix='cay_retry_pkg', cfg=None):
        self.tmp = tempfile.mkdtemp(prefix='cay-retry-')
        state_dir = os.path.join(self.tmp, 'state')
        os.makedirs(state_dir)
        config_file = os.path.join(state_dir, 'config.json')
        with open(config_file, 'w') as f:
            json.dump({'llmOutcomeEvaluation': cfg if cfg is not None else _eval_config()}, f)
        self.env = {'HERMES_HOME': self.tmp, 'REVENIUM_STATE_DIR': state_dir,
                    'REVENIUM_CONFIG_FILE': config_file,
                    'REVENIUM_MARKERS_DIR': os.path.join(state_dir, 'markers')}
        os.environ.update(self.env)
        self.c, self.ev = _load_package(plugin_dir, prefix)

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def attach(self, llm=None, job=None):
        """Drive _attach_assessment; return (job, [(level, message)])."""
        if llm is not None:
            self.c.call_llm = llm
        job = job if job is not None else _job()
        os.environ.update(self.env)
        with mock.patch.object(self.c.time, 'time', return_value=FROZEN_NOW):
            with _CapturingHandler('revenium_classifier') as captured:
                asyncio.run(self.c._attach_assessment(job, 'transcript',
                                                      self.c._module_paths()))
        return job, [(r.levelname, r.getMessage()) for r in captured.records]


class _CapturingHandler:
    """assertLogs without its failure when nothing is logged."""

    def __init__(self, logger_name):
        import logging
        self._logging = logging
        self.logger = logging.getLogger(logger_name)
        self.records = []

    def __enter__(self):
        outer = self

        class _H(self._logging.Handler):
            def emit(self, record):
                outer.records.append(record)

        self._handler = _H(level=self._logging.INFO)
        self._old_level = self.logger.level
        self._old_propagate = self.logger.propagate
        self.logger.addHandler(self._handler)
        self.logger.setLevel(self._logging.INFO)
        self.logger.propagate = False
        return self

    def __exit__(self, *exc):
        self.logger.removeHandler(self._handler)
        self.logger.setLevel(self._old_level)
        self.logger.propagate = self._old_propagate
        return False


RETRY_LINE = (f'revenium-classifier: outcome evaluation omitted confidence for '
              f'job={JOB_ID}, retrying once')


class TracerTests(unittest.TestCase):
    def test_omitted_confidence_is_retried_once_and_the_retry_is_reported(self):
        run = _Run()
        single = _Run(prefix='cay_retry_single_pkg')
        try:
            llm = _SequencedLLM([
                (_answer(confidence=_DROP), 'served-first'),
                (_answer(), 'served-retry'),
            ])
            job, messages = run.attach(llm)

            self.assertEqual(len(llm.calls), 2)
            self.assertEqual(job['assessment']['confidence'], 0.6)
            record = job['_assessment_record']
            self.assertEqual(record['model'], 'served-retry')
            self.assertEqual(record['reportability_status'], 'reportable')
            self.assertEqual(record['abstention_reason'], '')

            once = _SequencedLLM([(_answer(), 'served-retry')])
            single_job, single_messages = single.attach(once)
            self.assertEqual(len(once.calls), 1)
            self.assertEqual(job['_assessment_record'], single_job['_assessment_record'])
            self.assertEqual(job['assessment'], single_job['assessment'])

            texts = [m for _, m in messages]
            retry_records = [(lvl, m) for lvl, m in messages if 'retrying once' in m]
            self.assertEqual(retry_records, [('INFO', RETRY_LINE)])
            evaluated = [i for i, m in enumerate(texts) if m.startswith(
                'revenium-classifier: outcome evaluated job=')]
            self.assertEqual(len(evaluated), 1)
            self.assertLess(texts.index(RETRY_LINE), evaluated[0])
        finally:
            run.close()
            single.close()


if __name__ == '__main__':
    unittest.main()
