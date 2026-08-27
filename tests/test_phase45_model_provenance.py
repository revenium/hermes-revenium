"""Phase 45 Plan 02 — EGV-08: the deciding model, recorded and unspoofable.

D-10: the deciding model is read from response.model on the actual aux-LLM
response, failing open to PROVENANCE_MODEL_UNKNOWN. D-11: recorded verbatim,
clamped at PROVENANCE_MODEL_MAX_BYTES (64 bytes), not evaluator_version's
16-byte width. D-12: only the outcome-evaluation call populates the field; a
non-LLM evaluator, and every abstention/failure path, records the sentinel.

PA-07 (the security property this plan exists to protect): 'model' is a
member of Phase 43's _PROMOTION_FORBIDDEN_KEYS
(tests/test_phase43_evidence_grading.py) and its hostile fixture already
spoofs raw['model'] as 'gpt-attacker-9000'. The served model therefore never
travels to _build_job_assessment inside the untrusted `raw` dict -- it is an
explicit caller-supplied parameter, exactly like evaluator/evaluator_version,
carried from _evaluate_outcome_via_llm to _attach_assessment inside a
module-private _ServedModel instance that _attach_assessment POPS off raw
before raw ever reaches _validate_assessment or _build_job_assessment. A
JSON-parsed evaluator response cannot construct a _ServedModel, so a spoofed
plain string under the reserved key is structurally inert.

MANUAL, not covered by this file: response.model under a genuine live
provider failover cannot be triggered on demand (recorded in
45-VALIDATION.md) and is verified by observation, not by an automated test.

Every test here runs OFFLINE, same discipline as tests/test_phase37_llm_
evaluator.py and tests/test_phase39_log_taxonomy.py: no provider, no
network, no subprocess.
"""

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'


# ---------------------------------------------------------------------------
# Loader idiom copied from tests/test_phase37_llm_evaluator.py /
# tests/test_phase39_log_taxonomy.py: the FULL plugin package, via
# __init__.py, not classifier.py in isolation -- _attach_assessment (used by
# Task 3's classes below) does `from . import evaluators as _ev`, which
# requires package context to resolve. A unique module name per call is
# load-bearing, not a convenience: classifier.py binds STATE_DIR / MARKERS_DIR
# / CONFIG_FILE at import time, and Python caches submodules by name --
# reusing one name hands back a cached classifier still pointed at a
# previous test's tmpdir.
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
    for cached in [k for k in list(sys.modules) if k.startswith('p45_02_pkg')]:
        del sys.modules[cached]


def _load(env=None):
    """Import the plugin package fresh; return (classifier, evaluators)."""
    for k, v in (env or {}).items():
        os.environ[k] = v
        _ENV_TOUCHED.add(k)
    _LOAD_SEQ[0] += 1
    name = f'p45_02_pkg_{_LOAD_SEQ[0]}'
    for cached in [k for k in sys.modules if k.startswith('p45_02_pkg')]:
        del sys.modules[cached]
    spec = importlib.util.spec_from_file_location(
        name, str(PLUGIN / '__init__.py'), submodule_search_locations=[str(PLUGIN)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return sys.modules[f'{name}.classifier'], sys.modules[f'{name}.evaluators']


class _Recorder:
    """Stub call_llm that scripts both the content AND the response's model.

    Extends tests/test_phase37_llm_evaluator.py's _Recorder shape (which
    scripts content only -- no test in that file's suite ever populated a
    model key, which is exactly why those tests still record the sentinel
    unmodified by this plan). `as_object=True` scripts an object-shaped
    response (a SimpleNamespace, mirroring the live aux client's
    _recover_aux_response_message SimpleNamespace recovery path) instead of
    the dict-shaped response every other test in this repo scripts --
    D-10's dual object/dict handling needs both shapes exercised.
    """

    def __init__(self, content='{}', model=None, raises=None, as_object=False):
        self.calls = []
        self.content = content
        self.model = model
        self.raises = raises
        self.as_object = as_object

    def __call__(self, **kw):
        self.calls.append(kw)
        if self.raises:
            raise self.raises
        if self.as_object:
            message = SimpleNamespace(content=self.content)
            choice = SimpleNamespace(message=message)
            response = SimpleNamespace(choices=[choice])
            if self.model is not None:
                response.model = self.model
            return response
        response = {'choices': [{'message': {'content': self.content}}]}
        if self.model is not None:
            response['model'] = self.model
        return response


class _RaisingModel:
    """An object whose .model PROPERTY itself raises on access -- distinct
    from a missing attribute (which getattr's default already handles).
    Exercises _resolve_served_model's outer try/except, not its getattr
    fallback."""

    choices = [SimpleNamespace(message=SimpleNamespace(content='{}'))]

    @property
    def model(self):
        raise ValueError('boom -- provider-side object misbehaving')


class ResolveServedModelTests(unittest.TestCase):
    """_resolve_served_model in isolation -- one method per behavior bullet
    in 45-02-PLAN.md Task 1."""

    def setUp(self):
        self.c, _ = _load()

    def test_dict_response_with_model_key_returns_it_verbatim(self):
        self.assertEqual(
            self.c._resolve_served_model({'model': 'claude-sonnet-4-5-20250929'}),
            'claude-sonnet-4-5-20250929',
        )

    def test_object_response_with_model_attribute_returns_it_verbatim(self):
        response = SimpleNamespace(model='gpt-4o-2024-08-06')
        self.assertEqual(self.c._resolve_served_model(response), 'gpt-4o-2024-08-06')

    def test_no_model_attribute_and_no_model_key_is_unknown(self):
        self.assertEqual(self.c._resolve_served_model({}), self.c.PROVENANCE_MODEL_UNKNOWN)
        self.assertEqual(
            self.c._resolve_served_model(SimpleNamespace()), self.c.PROVENANCE_MODEL_UNKNOWN)

    def test_none_model_value_is_unknown(self):
        self.assertEqual(
            self.c._resolve_served_model({'model': None}), self.c.PROVENANCE_MODEL_UNKNOWN)

    def test_non_string_model_value_is_unknown(self):
        self.assertEqual(
            self.c._resolve_served_model({'model': 12345}), self.c.PROVENANCE_MODEL_UNKNOWN)

    def test_empty_string_model_is_unknown(self):
        self.assertEqual(
            self.c._resolve_served_model({'model': ''}), self.c.PROVENANCE_MODEL_UNKNOWN)

    def test_whitespace_only_model_is_unknown(self):
        self.assertEqual(
            self.c._resolve_served_model({'model': '   \t  '}), self.c.PROVENANCE_MODEL_UNKNOWN)

    def test_none_response_is_unknown(self):
        self.assertEqual(self.c._resolve_served_model(None), self.c.PROVENANCE_MODEL_UNKNOWN)

    def test_model_property_that_raises_never_propagates(self):
        # getattr(obj, 'model', None) does NOT swallow an exception raised
        # BY the property getter -- only AttributeError from a genuinely
        # missing attribute. This proves the outer try/except is load-
        # bearing, not redundant with the getattr default.
        self.assertEqual(
            self.c._resolve_served_model(_RaisingModel()), self.c.PROVENANCE_MODEL_UNKNOWN)


class CarrierTests(unittest.TestCase):
    """_evaluate_outcome_via_llm's carrier attachment -- one method per
    behavior bullet in 45-02-PLAN.md Task 1 concerning the LLM call itself."""

    def setUp(self):
        self.c, _ = _load()

    def _job(self):
        return {'status': 'SUCCESS', 'job_type': 'bug_fix', 'job_name': 'x'}

    def _content(self):
        return json.dumps({
            'economic_mechanism': 'labor_substitution',
            'inferred_role': 'engineer', 'estimated_hours_saved': 2.0,
            'assumed_loaded_rate': 100.0, 'currency': 'USD',
            'basis': 'x', 'confidence': 0.5,
        })

    def test_dict_shaped_response_carries_served_model(self):
        self.c.call_llm = _Recorder(
            content=self._content(), model='claude-sonnet-4-5-20250929')
        result = asyncio.run(
            self.c._evaluate_outcome_via_llm(self._job(), 'transcript', {}))
        self.assertIsInstance(result, dict)
        carrier = result[self.c._SERVED_MODEL_KEY]
        self.assertIsInstance(carrier, self.c._ServedModel)
        self.assertEqual(carrier.value, 'claude-sonnet-4-5-20250929')

    def test_object_shaped_response_carries_served_model(self):
        self.c.call_llm = _Recorder(
            content=self._content(), model='gpt-4o-2024-08-06', as_object=True)
        result = asyncio.run(
            self.c._evaluate_outcome_via_llm(self._job(), 'transcript', {}))
        self.assertIsInstance(result, dict)
        carrier = result[self.c._SERVED_MODEL_KEY]
        self.assertIsInstance(carrier, self.c._ServedModel)
        self.assertEqual(carrier.value, 'gpt-4o-2024-08-06')

    def test_attacker_chosen_reserved_key_is_overwritten_by_the_served_value(self):
        # The assessment JSON ITSELF claims the reserved key. The trusted
        # assignment in _evaluate_outcome_via_llm is unconditional and lands
        # AFTER the parse, so this must be clobbered with the real carrier.
        hostile = json.loads(self._content())
        hostile[self.c._SERVED_MODEL_KEY] = 'attacker-plain-string-not-a-carrier'
        self.c.call_llm = _Recorder(
            content=json.dumps(hostile), model='claude-sonnet-4-5-20250929')
        result = asyncio.run(
            self.c._evaluate_outcome_via_llm(self._job(), 'transcript', {}))
        carrier = result[self.c._SERVED_MODEL_KEY]
        self.assertIsInstance(carrier, self.c._ServedModel)
        self.assertEqual(carrier.value, 'claude-sonnet-4-5-20250929')

    def test_abstention_null_carries_no_carrier(self):
        self.c.call_llm = _Recorder(content='null', model='claude-sonnet-4-5-20250929')
        result = asyncio.run(
            self.c._evaluate_outcome_via_llm(self._job(), 'transcript', {}))
        self.assertIsNone(result)

    def test_invalid_response_carries_no_carrier(self):
        self.c.call_llm = _Recorder(
            content='Sorry, I cannot help.', model='claude-sonnet-4-5-20250929')
        result = asyncio.run(
            self.c._evaluate_outcome_via_llm(self._job(), 'transcript', {}))
        self.assertIs(result, self.c._EVAL_INVALID)

    def test_timeout_carries_no_carrier(self):
        self.c.call_llm = _Recorder(raises=TimeoutError('boom'))
        result = asyncio.run(
            self.c._evaluate_outcome_via_llm(self._job(), 'transcript', {}))
        self.assertIs(result, self.c._EVAL_TIMED_OUT)


if __name__ == '__main__':
    unittest.main()
