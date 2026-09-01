"""Phase 53-04 — gap closure on 53-03's finding.

Two regression guards:

1. `_EVAL_MAX_TOKENS` stays at the re-sized value (512, from the measured
   evaluator responses recorded in classifier.py's own comment) and does not
   silently revert to the stale 256. Asserted as a concrete literal here —
   unlike test_phase37_llm_evaluator.py's BudgetTests, which asserts the call
   site passes the module's OWN constant (wiring correctness), this file is
   the one place that pins the VALUE itself.
2. `_resolve_finish_reason` and the truncation-diagnostic log line at the
   evaluator call site: distinguishable from the malformed-response path,
   and provably never-raises (D-04/ROI-08) on a response object that lacks
   finish_reason entirely.

No test here reaches a network or a real provider — call_llm is stubbed at
the module the classifier imported it into, same harness as
test_phase37_llm_evaluator.py and test_phase39_log_taxonomy.py.
"""

import asyncio
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'


# ---------------------------------------------------------------------------
# Copied from tests/test_phase37_llm_evaluator.py's _load() harness. The
# unique-module-name-per-call detail is load-bearing, not a convenience:
# classifier.py binds STATE_DIR / MARKERS_DIR / CONFIG_FILE at import time,
# and Python caches submodules by name — reusing one name hands back a
# cached classifier still pointed at a previous test's tmpdir.
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
    for cached in [k for k in list(sys.modules) if k.startswith('p53t4_pkg')]:
        del sys.modules[cached]


def _load(env=None):
    """Import the plugin package fresh; return (classifier, evaluators)."""
    for k, v in (env or {}).items():
        os.environ[k] = v
        _ENV_TOUCHED.add(k)
    _LOAD_SEQ[0] += 1
    name = f'p53t4_pkg_{_LOAD_SEQ[0]}'
    for cached in [k for k in sys.modules if k.startswith('p53t4_pkg')]:
        del sys.modules[cached]
    spec = importlib.util.spec_from_file_location(
        name, str(PLUGIN / '__init__.py'), submodule_search_locations=[str(PLUGIN)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return sys.modules[f'{name}.classifier'], sys.modules[f'{name}.evaluators']


class _Recorder:
    """Stub call_llm that records kwargs and returns a scripted content and
    finish_reason, dict-shaped like the real call_llm return value."""

    def __init__(self, content='{}', finish_reason='stop', raises=None):
        self.calls = []
        self.content = content
        self.finish_reason = finish_reason
        self.raises = raises

    def __call__(self, **kw):
        self.calls.append(kw)
        if self.raises:
            raise self.raises
        return {'choices': [{
            'message': {'content': self.content},
            'finish_reason': self.finish_reason,
        }]}


_VALID_ASSESSMENT = json.dumps({
    'economic_mechanism': 'labor_substitution',
    'inferred_role': 'engineer',
    'estimated_hours_saved': 2.0,
    'assumed_loaded_rate': 100.0,
    'currency': 'USD',
    'basis': 'x',
    'confidence': 0.5,
})


class TokenBudgetValueTests(unittest.TestCase):
    """Guard 1 — the concrete re-sized value, not just the wiring."""

    def setUp(self):
        self.c, _ = _load()

    def test_eval_max_tokens_is_512_not_the_stale_256(self):
        # 53-03 (2026-08-31) measured a Phase 37 worst-case of ~149 tokens
        # under 256 (~1.7x margin) and left it unchanged after 85 live
        # rejections. 53-04 (2026-09-01) measured the actual worst COMPLETE
        # response at 86 tokens across 8 real+synthetic calls (both capped
        # and uncapped, finish_reason "stop" throughout) and re-sized to
        # 512 -- _infer_jobs_via_llm's own already-shipped budget for a
        # structurally similar call, not a freshly invented number.
        self.assertEqual(512, self.c._EVAL_MAX_TOKENS,
                          'the re-sized value must not silently revert')

    def test_eval_timeout_seconds_unchanged(self):
        # 53-04 measured that capped and uncapped runs produce the same
        # completion_tokens (latency is bound by tokens generated, not the
        # ceiling), so the timeout was deliberately NOT moved.
        self.assertEqual(15.0, self.c._EVAL_TIMEOUT_SECONDS)

    def test_eval_max_tokens_matches_infer_jobs_budget_reference(self):
        """512 was chosen BECAUSE it equals _infer_jobs_via_llm's own
        max_tokens=512 literal (structurally similar one-shot JSON call,
        strictly larger array-of-jobs output) -- not a coincidence to
        silently drift apart from in a future edit to either call site."""
        import inspect
        src = inspect.getsource(self.c._infer_jobs_via_llm)
        self.assertIn('max_tokens=512', src)
        self.assertEqual(512, self.c._EVAL_MAX_TOKENS)


class FinishReasonResolverTests(unittest.TestCase):
    """Guard 2a — _resolve_finish_reason's own never-raises contract,
    independent of the call site."""

    def setUp(self):
        self.c, _ = _load()

    def test_dict_shaped_response_with_length(self):
        resp = {'choices': [{'finish_reason': 'length'}]}
        self.assertEqual('length', self.c._resolve_finish_reason(resp))

    def test_dict_shaped_response_with_stop(self):
        resp = {'choices': [{'finish_reason': 'stop'}]}
        self.assertEqual('stop', self.c._resolve_finish_reason(resp))

    def test_object_shaped_response(self):
        class Choice:
            finish_reason = 'length'

        class Response:
            choices = [Choice()]

        self.assertEqual('length', self.c._resolve_finish_reason(Response()))

    def test_response_missing_finish_reason_falls_through_to_sentinel(self):
        """The never-raises contract's core case: a response object shaped
        like a real one but genuinely lacking finish_reason (a third-party
        evaluator, a stub, a future SDK shape) must not raise, and must not
        be mistaken for a truncation signal."""
        class BareChoice:
            pass

        class Response:
            choices = [BareChoice()]

        self.assertEqual(self.c._FINISH_REASON_UNKNOWN,
                          self.c._resolve_finish_reason(Response()))

    def test_response_where_choices_access_itself_raises(self):
        class HostileResponse:
            @property
            def choices(self):
                raise RuntimeError('boom')

        self.assertEqual(self.c._FINISH_REASON_UNKNOWN,
                          self.c._resolve_finish_reason(HostileResponse()))

    def test_none_response(self):
        self.assertEqual(self.c._FINISH_REASON_UNKNOWN,
                          self.c._resolve_finish_reason(None))

    def test_empty_dict_response(self):
        self.assertEqual(self.c._FINISH_REASON_UNKNOWN,
                          self.c._resolve_finish_reason({}))

    def test_non_string_finish_reason_falls_through_to_sentinel(self):
        resp = {'choices': [{'finish_reason': 42}]}
        self.assertEqual(self.c._FINISH_REASON_UNKNOWN,
                          self.c._resolve_finish_reason(resp))


class CallSiteDiagnosticTests(unittest.TestCase):
    """Guard 2b — the diagnostic log line at _evaluate_outcome_via_llm's own
    call site, driven through the REAL function, never by reading source."""

    def setUp(self):
        self.c, _ = _load()

    def _run(self, rec):
        self.c.call_llm = rec
        return asyncio.run(self.c._evaluate_outcome_via_llm(
            {'agentic_job_id': 'job_1', 'status': 'SUCCESS',
             'job_type': 'bug_fix', 'job_name': 'x'},
            'transcript', {}))

    def test_length_finish_reason_logs_the_distinct_truncation_line(self):
        rec = _Recorder(content=_VALID_ASSESSMENT, finish_reason='length')
        with self.assertLogs('revenium_classifier', level='WARNING') as cm:
            self._run(rec)
        joined = '\n'.join(cm.output)
        self.assertIn('truncated', joined)
        self.assertIn('finish_reason=length', joined)
        self.assertIn('job_1', joined)

    def test_stop_finish_reason_does_not_log_truncation(self):
        rec = _Recorder(content=_VALID_ASSESSMENT, finish_reason='stop')
        # No assertLogs wrapper needed for absence -- assert directly on a
        # captured log, using a sentinel INFO line so assertLogs has
        # something to see (it errors if nothing at all is logged).
        with self.assertLogs('revenium_classifier', level='DEBUG') as cm:
            self.c.logger.debug('sentinel')
            self._run(rec)
        for line in cm.output:
            self.assertNotIn('truncated', line)

    def test_missing_finish_reason_does_not_log_truncation_and_does_not_raise(self):
        """The never-raises contract, exercised through the real call site:
        a call_llm stub whose dict has NO finish_reason key at all (a
        provider shape variance, or a third-party evaluator's return value)
        must fall through to today's behavior exactly -- no truncation log,
        no exception, and the parsed assessment still comes back."""
        class NoFinishReasonRecorder:
            def __init__(self, content):
                self.content = content
                self.calls = []

            def __call__(self, **kw):
                self.calls.append(kw)
                return {'choices': [{'message': {'content': self.content}}]}

        rec = NoFinishReasonRecorder(_VALID_ASSESSMENT)
        with self.assertLogs('revenium_classifier', level='DEBUG') as cm:
            self.c.logger.debug('sentinel')
            result = self._run(rec)
        for line in cm.output:
            self.assertNotIn('truncated', line)
        self.assertIsInstance(result, dict)
        self.assertEqual('labor_substitution', result.get('economic_mechanism'))

    def test_diagnostic_does_not_change_the_return_value(self):
        """A truncation-flagged response still returns the SAME parsed dict
        a non-flagged one would -- this is a diagnostic, not a control-flow
        change. _EVAL_INVALID still means invalid; this test proves the new
        branch never substitutes for it."""
        rec_length = _Recorder(content=_VALID_ASSESSMENT, finish_reason='length')
        rec_stop = _Recorder(content=_VALID_ASSESSMENT, finish_reason='stop')
        result_length = self._run(rec_length)
        # Fresh classifier import for the second call so call counts / state
        # cannot leak between them.
        self.c, _ = _load()
        result_stop = self._run(rec_stop)
        self.assertEqual(
            {k: v for k, v in result_length.items() if not k.startswith('_')},
            {k: v for k, v in result_stop.items() if not k.startswith('_')},
        )

    def test_uses_the_module_constant_not_a_copied_literal(self):
        """Regression guard mirroring test_phase37_llm_evaluator.py's
        BudgetTests: the real call site must pass _EVAL_MAX_TOKENS, not a
        value someone inlined to match it by coincidence (512 also happens
        to equal _infer_jobs_via_llm's own literal)."""
        rec = _Recorder(content=_VALID_ASSESSMENT, finish_reason='stop')
        self._run(rec)
        self.assertEqual(1, len(rec.calls))
        self.assertEqual(self.c._EVAL_MAX_TOKENS, rec.calls[0]['max_tokens'])


if __name__ == '__main__':
    unittest.main()
