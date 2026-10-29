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
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'

# The origin/main commit this branch was cut from. Immutable; moved only in a
# reviewed change. The no-retry cases are compared against this classifier.
BASELINE_SHA = '2f3a4f0dcc587cd14e264a7bd483d22d3b19ece0'

FROZEN_NOW = 1800000000.0
JOB_ID = 'cay-job-1'

_LOAD_SEQ = [0]
_BASELINE_DIR = [None]
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
    if _BASELINE_DIR[0] is not None:
        shutil.rmtree(_BASELINE_DIR[0].parent, ignore_errors=True)
        _BASELINE_DIR[0] = None


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



def _baseline_plugin_dir():
    """The plugin tree with classifier.py as it was at BASELINE_SHA.

    Fails loudly when the commit is unreachable; CI checks out with full history.
    """
    if _BASELINE_DIR[0] is None:
        old_classifier = subprocess.run(
            ['git', 'show', f'{BASELINE_SHA}:skills/revenium/plugins/revenium-classifier/classifier.py'],
            cwd=ROOT, check=True, capture_output=True).stdout
        target = Path(tempfile.mkdtemp(prefix='cay-baseline-')) / 'revenium-classifier'
        shutil.copytree(PLUGIN, target, ignore=shutil.ignore_patterns('__pycache__'))
        (target / 'classifier.py').write_bytes(old_classifier)
        _BASELINE_DIR[0] = target
    return _BASELINE_DIR[0]


def _scenario(first=None, *, steps=None, evaluator=None, cfg=None, baseline=False, job=None):
    """Run one attach and return (job, messages, calls).

    `steps` scripts the built-in evaluator's call_llm; `evaluator` is a
    (name, fn) pair registered in place of it. `calls` counts either.
    """
    cfg = cfg if cfg is not None else _eval_config()
    if evaluator is not None:
        cfg = {**cfg, 'evaluator': evaluator[0]}
    run = _Run(plugin_dir=_baseline_plugin_dir() if baseline else PLUGIN,
               prefix='cay_baseline_pkg' if baseline else 'cay_retry_pkg', cfg=cfg)
    try:
        if evaluator is not None:
            run.ev.register(evaluator[0], evaluator[1], version='v7')
            result = run.attach(None, job)
            return result + (None,)
        llm = _SequencedLLM(steps)
        result = run.attach(llm, job)
        return result + (len(llm.calls),)
    finally:
        run.close()


def _both(steps, **kw):
    """The same scenario against the current classifier and the baseline."""
    return _scenario(steps=steps, **kw), _scenario(steps=steps, baseline=True, **kw)


def _texts(messages):
    return [m for _, m in messages]


class DifferentialBaselineTests(unittest.TestCase):
    def assert_identical_to_baseline(self, steps, expected_calls=1, **kw):
        (job, msgs, calls), (base_job, base_msgs, base_calls) = _both(steps, **kw)
        self.assertEqual(calls, expected_calls)
        self.assertEqual(base_calls, 1)
        self.assertNotIn('retrying once', ' '.join(_texts(msgs)))
        self.assertEqual(job.get('_assessment_record'), base_job.get('_assessment_record'))
        self.assertEqual(job.get('assessment'), base_job.get('assessment'))
        self.assertEqual(msgs, base_msgs)
        return job

    def test_first_answer_with_confidence_matches_the_baseline(self):
        job = self.assert_identical_to_baseline([(_answer(confidence=0.5), 'served-first')])
        self.assertEqual(job['assessment']['confidence'], 0.5)

    def test_present_but_invalid_confidence_is_not_retried(self):
        for label, confidence in (('out of range', 1.5), ('string', 'high'),
                                  ('bool', True), ('nan', float('nan'))):
            with self.subTest(label):
                job = self.assert_identical_to_baseline(
                    [(_answer(confidence=confidence), 'served-first')])
                self.assertEqual(job['_assessment_record']['abstention_reason'], 'rejected')

    def test_other_rejections_without_confidence_are_not_retried(self):
        cases = (
            ('negative hours', {'estimated_hours_saved': -1}, None),
            ('hours over default bound', {'estimated_hours_saved': 999}, None),
            ('rate over configured bound', {'assumed_loaded_rate': 80}, {'maxLoadedRate': 50}),
            ('unknown mechanism', {'economic_mechanism': 'made_up'}, None),
        )
        for label, overrides, cfg_extra in cases:
            with self.subTest(label):
                cfg = _eval_config(**(cfg_extra or {}))
                job = self.assert_identical_to_baseline(
                    [(_answer(confidence=_DROP, **overrides), 'served-first')], cfg=cfg)
                self.assertEqual(job['_assessment_record']['abstention_reason'], 'rejected')

    def test_newly_enabled_work_without_confidence_is_not_retried(self):
        job = self.assert_identical_to_baseline([(_answer(
            confidence=_DROP, economic_mechanism='newly_enabled_work'), 'served-first')])
        self.assertEqual(job['_assessment_record']['abstention_reason'],
                         'mechanism_abstains_from_value')

    def test_non_answers_are_not_retried(self):
        cases = (('prose', ('not json at all', None), 'invalid'),
                 ('timeout', TimeoutError('slow'), 'timed_out'),
                 ('null', ('null', None), 'abstained'))
        for label, step, reason in cases:
            with self.subTest(label):
                job = self.assert_identical_to_baseline([step])
                self.assertEqual(job['_assessment_record']['abstention_reason'], reason)

    def test_retry_that_does_not_help_leaves_the_baseline_record(self):
        omitted = (_answer(confidence=_DROP), 'served-first')
        cases = (
            ('still omits', (_answer(confidence=_DROP), 'served-retry')),
            ('timeout', TimeoutError('slow')),
            ('prose', ('not json at all', None)),
            ('null', ('null', None)),
            ('newly enabled work', (_answer(economic_mechanism='newly_enabled_work'), 'served-retry')),
            ('bad hours', (_answer(estimated_hours_saved=-1), 'served-retry')),
        )
        for label, second in cases:
            with self.subTest(label):
                (job, msgs, calls) = _scenario(steps=[omitted, second])
                (base_job, base_msgs, _) = _scenario(steps=[omitted], baseline=True)
                self.assertEqual(calls, 2)
                record = job['_assessment_record']
                self.assertEqual(record, base_job['_assessment_record'])
                self.assertEqual(record['abstention_reason'], 'rejected')
                self.assertEqual(record['model'], 'served-first')
                self.assertEqual(record['reportability_status'], 'candidate')
                self.assertNotIn('assessment', job)
                texts = _texts(msgs)
                self.assertEqual(sum('retrying once' in t for t in texts), 1)
                kept = [m for m in msgs if 'retrying once' not in m[1]]
                for message in base_msgs:
                    self.assertIn(message, kept)

    def test_second_instrument_record_follows_the_retry_line_when_still_omitted(self):
        omitted = (_answer(confidence=_DROP), 'served-first')
        _, msgs, _ = _scenario(steps=[omitted, omitted])
        _, base_msgs, _ = _scenario(steps=[omitted], baseline=True)
        instrument = next(i for i, (_, m) in enumerate(base_msgs)
                          if m.startswith('revenium-classifier: rejected assessment, confidence'))
        expected = (base_msgs[:instrument + 1]
                    + [('INFO', RETRY_LINE), base_msgs[instrument]]
                    + base_msgs[instrument + 1:])
        self.assertEqual(msgs, expected)


class RetryScopeTests(unittest.TestCase):
    def test_explicit_none_confidence_is_retried(self):
        _, _, calls = _scenario(steps=[(_answer(confidence=None), 'a'), (_answer(), 'b')])
        self.assertEqual(calls, 2)

    def test_configured_hours_bound_is_honoured(self):
        omitted = (_answer(confidence=_DROP, estimated_hours_saved=60), 'a')
        job, _, calls = _scenario(
            steps=[omitted, (_answer(estimated_hours_saved=60), 'b')],
            cfg=_eval_config(maxHoursSaved=100))
        self.assertEqual(calls, 2)
        self.assertIn('assessment', job)

    def test_the_retry_re_sends_identical_arguments(self):
        run = _Run()
        try:
            llm = _SequencedLLM([(_answer(confidence=_DROP), 'a'), (_answer(), 'b')])
            run.attach(llm)
            self.assertEqual(llm.calls[0], llm.calls[1])
        finally:
            run.close()

    def test_retry_applies_to_a_registered_evaluator(self):
        seen = []

        def evaluator(job, transcript, cfg):
            seen.append((job, transcript, cfg))
            return json.loads(_answer(confidence=_DROP if len(seen) == 1 else 0.7))

        job, _, _ = _scenario(evaluator=('cay_third_party', evaluator))
        self.assertEqual(len(seen), 2)
        self.assertIs(seen[0][0], seen[1][0])
        self.assertIs(seen[0][2], seen[1][2])
        self.assertEqual(seen[0][1], seen[1][1])
        self.assertEqual(job['assessment']['confidence'], 0.7)
        self.assertEqual(job['_assessment_record']['evaluator_version'], 'v7')
        self.assertEqual(job['_assessment_record']['model'], 'unknown')

    def test_registered_evaluator_failure_on_retry_stays_rejected(self):
        def raising(exc):
            calls = []

            def evaluator(job, transcript, cfg):
                calls.append(1)
                if len(calls) == 2:
                    raise exc
                return json.loads(_answer(confidence=_DROP))
            return evaluator

        def returns_list(job, transcript, cfg):
            returns_list.n += 1
            return json.loads(_answer(confidence=_DROP)) if returns_list.n == 1 else ['x']
        returns_list.n = 0

        for label, fn in (('runtime error', raising(RuntimeError('boom'))),
                          ('timeout', raising(asyncio.TimeoutError())),
                          ('list', returns_list)):
            with self.subTest(label):
                job, msgs, _ = _scenario(evaluator=('cay_third_party', fn))
                self.assertEqual(job['_assessment_record']['abstention_reason'], 'rejected')
                self.assertNotIn('assessment', job)
                self.assertFalse([m for m in _texts(msgs) if 'outcome evaluation failed' in m
                                  or 'timed-out' in m])

    def test_spoofed_served_model_on_a_registered_retry_is_ignored(self):
        calls = []

        def evaluator(job, transcript, cfg):
            calls.append(1)
            answer = json.loads(_answer(confidence=_DROP if len(calls) == 1 else 0.7))
            answer['_revenium_served_model'] = 'attacker-model'
            return answer

        job, _, _ = _scenario(evaluator=('cay_third_party', evaluator))
        self.assertEqual(job['_assessment_record']['model'], 'unknown')


class LogHygieneTests(unittest.TestCase):
    def test_model_text_never_reaches_a_log_record(self):
        token = 'CAYTOKEN-9f3b7c'
        omitted = (_answer(confidence=_DROP, basis=token, inferred_role=token), 'a')
        _, msgs, calls = _scenario(steps=[omitted, omitted])
        self.assertEqual(calls, 2)
        texts = _texts(msgs)
        self.assertFalse([t for t in texts if token in t])
        retry = [t for t in texts if 'retrying once' in t]
        self.assertEqual(len(retry), 1)
        self.assertIn(JOB_ID, retry[0])


class PredicateParityTests(unittest.TestCase):
    """_confidence_omission_retryable must agree with what _validate_assessment rejects."""

    INSTRUMENT = 'revenium-classifier: rejected assessment, confidence outside [0,1]: %r'

    def test_predicate_is_true_exactly_when_the_confidence_check_rejects(self):
        c, _ = _load_package(PLUGIN, 'cay_parity_pkg')
        default = {}
        cases = []
        for confidence in (_DROP, None, 0.5, 1.5, -0.1, 'high', True, float('nan'), 0, 1):
            for overrides, cfg in (
                ({}, default),
                ({'estimated_hours_saved': -1}, default),
                ({'estimated_hours_saved': 0}, default),
                ({'estimated_hours_saved': 999}, default),
                ({'estimated_hours_saved': 60}, {'maxHoursSaved': 100}),
                ({'estimated_hours_saved': None}, default),
                ({'estimated_hours_saved': 'two'}, default),
                ({'assumed_loaded_rate': 80}, {'maxLoadedRate': 50}),
                ({'assumed_loaded_rate': 0}, default),
                ({'economic_mechanism': 'made_up'}, default),
                ({'economic_mechanism': _DROP}, default),
            ):
                body = json.loads(_answer(confidence=0.5))
                body.pop('confidence')
                if confidence is not _DROP:
                    body['confidence'] = confidence
                for key, value in overrides.items():
                    if value is _DROP:
                        body.pop(key, None)
                    else:
                        body[key] = value
                cases.append((body, cfg))
        retryable_seen = False
        for body, cfg in cases:
            with self.subTest(body=body, cfg=cfg):
                import logging
                with _CapturingHandler('revenium_classifier') as captured:
                    logging.getLogger('revenium_classifier').info('sentinel')
                    verdict = c._validate_assessment(dict(body), cfg, 'llm', '1')
                warnings = [r for r in captured.records if r.levelno >= logging.WARNING]
                confidence_rejected = (
                    verdict is None and bool(warnings)
                    and warnings[0].msg == self.INSTRUMENT and warnings[0].args == (None,))
                self.assertEqual(c._confidence_omission_retryable(dict(body), cfg),
                                 confidence_rejected)
                retryable_seen = retryable_seen or confidence_rejected
        self.assertTrue(retryable_seen)

    def test_predicate_is_false_for_non_dicts(self):
        c, _ = _load_package(PLUGIN, 'cay_parity_pkg')
        for value in (None, [], 'x', 3):
            self.assertFalse(c._confidence_omission_retryable(value, {}))


if __name__ == '__main__':
    unittest.main()
