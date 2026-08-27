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
import shutil
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


# ---------------------------------------------------------------------------
# Task 3 — the whole path, driven through the REAL _attach_assessment,
# never a mock of it. Analog: tests/test_phase39_log_taxonomy.py's _ctx
# temp-state-dir helper and the asyncio.run(c._attach_assessment(...))
# driving idiom; tests/test_phase42_assessment_contract.py's
# _p42_shape_env for the config-file shape.
# ---------------------------------------------------------------------------

def _job():
    return {'agentic_job_id': 'p45-02-job', 'job_name': 'n',
            'job_type': 'bug_fix', 'status': 'SUCCESS'}


def _success_content():
    return json.dumps({
        'economic_mechanism': 'labor_substitution',
        'inferred_role': 'engineer', 'estimated_hours_saved': 2.0,
        'assumed_loaded_rate': 100.0, 'currency': 'USD',
        'basis': 'x', 'confidence': 0.5,
    })


def _ctx(evaluator='llm'):
    """A minimal state tree with LLM outcome evaluation opted in for
    `evaluator` -- mirrors tests/test_phase42_assessment_contract.py's
    _p42_shape_env / tests/test_phase39_log_taxonomy.py's _ctx shape.
    Caller owns cleanup of the returned tmpdir."""
    tmp = tempfile.mkdtemp(prefix='gsd-p45-02-')
    state_dir = os.path.join(tmp, 'state')
    os.makedirs(state_dir, exist_ok=True)
    config_file = os.path.join(state_dir, 'config.json')
    with open(config_file, 'w') as f:
        json.dump({'llmOutcomeEvaluation': {
            'enabled': True, 'evaluator': evaluator, 'currency': 'USD',
        }}, f)
    c, ev = _load({'REVENIUM_STATE_DIR': state_dir, 'REVENIUM_CONFIG_FILE': config_file})
    return c, ev, tmp


def _run_attach(c, job=None):
    job = job if job is not None else _job()
    asyncio.run(c._attach_assessment(job, 'transcript', c._module_paths()))
    return job


class RecordProvenanceTests(unittest.TestCase):
    """End-to-end through the REAL _attach_assessment path -- one method per
    behavior bullet in 45-02-PLAN.md Task 3 concerning the happy path, the
    clamp, and evaluator/evaluator_version's independence from `model`."""

    def test_dated_model_identifier_survives_verbatim_unclamped(self):
        c, ev, tmp = _ctx(evaluator='llm')
        try:
            model = 'claude-sonnet-4-5-20250929'
            self.assertEqual(len(model), 26, 'fixture sanity: this dated snapshot identifier is 26 characters, well under the 64-byte clamp')
            c.call_llm = _Recorder(content=_success_content(), model=model)
            job = _run_attach(c)
            self.assertEqual(job['_assessment_record']['model'], model)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_evaluator_and_evaluator_version_are_independent_of_model(self):
        c, ev, tmp = _ctx(evaluator='llm')
        try:
            c.call_llm = _Recorder(
                content=_success_content(), model='claude-sonnet-4-5-20250929')
            job = _run_attach(c)
            record = job['_assessment_record']
            self.assertEqual(record['evaluator'], 'llm')
            self.assertEqual(record['evaluator_version'], c.LLM_EVALUATOR_VERSION)
            # The two provenance sources are independent: swapping the
            # scripted model does not touch evaluator/evaluator_version.
            self.assertEqual(record['model'], 'claude-sonnet-4-5-20250929')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_overlength_model_identifier_is_clamped_byte_based(self):
        c, ev, tmp = _ctx(evaluator='llm')
        try:
            long_model = 'x' * 100
            c.call_llm = _Recorder(content=_success_content(), model=long_model)
            job = _run_attach(c)
            record_model = job['_assessment_record']['model']
            self.assertEqual(record_model, 'x' * c.PROVENANCE_MODEL_MAX_BYTES)
            self.assertEqual(len(record_model), c.PROVENANCE_MODEL_MAX_BYTES)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_frozen_nested_marker_assessment_object_has_no_model_key(self):
        c, ev, tmp = _ctx(evaluator='llm')
        try:
            c.call_llm = _Recorder(
                content=_success_content(), model='claude-sonnet-4-5-20250929')
            job = _run_attach(c)
            self.assertIn('assessment', job)
            self.assertNotIn(
                'model', job['assessment'],
                'this phase changed the sidecar record only -- the frozen '
                'nested marker `assessment` object has never carried model')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ScopeBoundaryTests(unittest.TestCase):
    """The negative half -- D-12's non-LLM-evaluator case, the reserved-key
    spoof, the four abstention/failure paths, and the frozen marker check."""

    def test_non_llm_evaluator_records_unknown_model(self):
        # D-12: system_of_record_assessment_fixture (registered in
        # skills/revenium/plugins/revenium-classifier/evaluators.py by
        # 45-01) makes no model call at all.
        c, ev, tmp = _ctx(evaluator='system_of_record_assessment_fixture')
        try:
            job = _run_attach(c)
            self.assertEqual(job['_assessment_record']['model'], c.PROVENANCE_MODEL_UNKNOWN)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_reserved_key_spoof_by_a_registered_evaluator_is_rejected(self):
        # A registered (non-LLM) evaluator that returns an otherwise-valid
        # assessment carrying a PLAIN STRING under the reserved key -- the
        # carrier's TYPE is the gate, not the key's mere presence.
        c, ev, tmp = _ctx(evaluator='throwaway_spoof_evaluator')
        try:
            def _spoof_fn(job, transcript, config):
                if not isinstance(job, dict) or job.get('status') != 'SUCCESS':
                    return None
                record = json.loads(_success_content())
                record[c._SERVED_MODEL_KEY] = 'attacker-plain-string-not-a-carrier'
                return record

            ev.register('throwaway_spoof_evaluator', _spoof_fn, '1',
                         evidence_class='OUTCOME_OBSERVED')
            job = _run_attach(c)
            self.assertEqual(job['_assessment_record']['model'], c.PROVENANCE_MODEL_UNKNOWN)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_abstained_path_records_unknown_model(self):
        c, ev, tmp = _ctx(evaluator='llm')
        try:
            c.call_llm = _Recorder(content='null', model='claude-sonnet-4-5-20250929')
            job = _run_attach(c)
            self.assertEqual(job['_assessment_record']['model'], c.PROVENANCE_MODEL_UNKNOWN)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_invalid_path_records_unknown_model(self):
        c, ev, tmp = _ctx(evaluator='llm')
        try:
            c.call_llm = _Recorder(
                content='Sorry, I cannot help.', model='claude-sonnet-4-5-20250929')
            job = _run_attach(c)
            self.assertEqual(job['_assessment_record']['model'], c.PROVENANCE_MODEL_UNKNOWN)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_timed_out_path_records_unknown_model(self):
        c, ev, tmp = _ctx(evaluator='llm')
        try:
            c.call_llm = _Recorder(raises=TimeoutError('boom'))
            job = _run_attach(c)
            self.assertEqual(job['_assessment_record']['model'], c.PROVENANCE_MODEL_UNKNOWN)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_unknown_evaluator_path_records_unknown_model(self):
        c, ev, tmp = _ctx(evaluator='definitely_not_registered_xyz')
        try:
            job = _run_attach(c)
            self.assertEqual(job['_assessment_record']['model'], c.PROVENANCE_MODEL_UNKNOWN)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
