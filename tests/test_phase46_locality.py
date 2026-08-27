"""Phase 46 Plan 02, Task 1 — the address-class derivation and the
profile-scoped config.yaml read (EGV-21, D-06/D-07, AMEND-D-07).

Source-of-truth: skills/revenium/plugins/revenium-classifier/classifier.py
`_address_class` (pure derivation) and `_resolve_inference_locality`
(profile-scoped config.yaml read, fail-open).

D-06: the skill records observable facts only, never a locality claim.
D-07: the facts are the resolved provider name plus a DERIVED address class
— never the raw base_url, which is discarded immediately after deriving the
class. D-12: exactly four address-class values (loopback/private/public/
unset) — no fifth "unknown" bucket. AMEND-D-07: the class reflects the
CONFIGURED model.base_url, not a verified connection — sourced from a
static, profile-scoped config.yaml read because no call_llm(...) site in
this module passes base_url=/provider=/model= (ROI-07), and the aux
client's response object never surfaces .base_url back to this module.

Own isolated-import idiom — own `_LOAD_SEQ` / `_ENV_SAVED` / `_ENV_TOUCHED`
module globals, own `p46loc_pkg_N` module-name prefix, `_restore_env()`
called from every `tearDown` — copied from
tests/test_phase38_reporter_path.py:1678-1719 rather than imported, matching
this repo's stated preference for duplication across fail-open in-session
vs. out-of-process reporter code (CLAUDE.md "Module design").
"""
import asyncio
import importlib.util
import json
import os
import sys as _sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests._compat_helpers import ROOT

PLUGIN_DIR = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'

_LOAD_SEQ = [0]
_ENV_TOUCHED = set()
_ENV_SAVED = {}


def setUpModule():
    for k in ('REVENIUM_STATE_DIR', 'REVENIUM_MARKERS_DIR', 'REVENIUM_CONFIG_FILE',
              'REVENIUM_TAXONOMY_FILE', 'REVENIUM_JOB_TAXONOMY_FILE', 'HERMES_HOME'):
        _ENV_SAVED[k] = os.environ.get(k)


def _restore_env():
    for k in _ENV_TOUCHED | set(_ENV_SAVED):
        prior = _ENV_SAVED.get(k)
        if prior is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = prior


def tearDownModule():
    _restore_env()
    for cached in [k for k in list(_sys.modules) if k.startswith('p46loc_pkg')]:
        del _sys.modules[cached]


def _load_classifier(env=None):
    """Import the revenium-classifier plugin fresh; return (classifier, evaluators)."""
    for k, v in (env or {}).items():
        os.environ[k] = v
        _ENV_TOUCHED.add(k)
    _LOAD_SEQ[0] += 1
    name = f'p46loc_pkg_{_LOAD_SEQ[0]}'
    for cached in [k for k in _sys.modules if k.startswith('p46loc_pkg')]:
        del _sys.modules[cached]
    spec = importlib.util.spec_from_file_location(
        name, str(PLUGIN_DIR / '__init__.py'), submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    _sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return _sys.modules[f'{name}.classifier'], _sys.modules[f'{name}.evaluators']


def _build_paths(classifier_mod, home: Path):
    """Build a _Paths namedtuple rooted at `home`, mirroring _module_paths'
    shape but pointed at a tmpdir profile home rather than the process env."""
    state_dir = home / 'state' / 'revenium'
    markers_dir = state_dir / 'markers'
    return classifier_mod._Paths(
        hermes_home=home,
        state_dir=state_dir,
        markers_dir=markers_dir,
        markers_ready_dir=markers_dir / '.ready',
        taxonomy_file=state_dir / 'task-taxonomy.json',
        job_taxonomy_file=state_dir / 'job-taxonomy.json',
        guardrail_status_file=state_dir / 'guardrail-status.json',
        config_file=state_dir / 'config.json',
        state_db=home / 'state.db',
        job_assessments_dir=state_dir / 'job-assessments',
    )


class AddressClassTests(unittest.TestCase):
    """Behaviors 1-7 — `_address_class`'s pure derivation. No fixture/env
    needed; the function under test performs no I/O."""

    @classmethod
    def setUpClass(cls):
        cls.classifier, cls.evaluators = _load_classifier({})

    def tearDown(self):
        _restore_env()

    # Behavior 1: loopback (IPv4, IPv6, IPv4-mapped IPv6).
    def test_loopback_ipv4(self):
        self.assertEqual(self.classifier._address_class('http://127.0.0.1:8080/v1'), 'loopback')

    def test_loopback_ipv6(self):
        self.assertEqual(self.classifier._address_class('http://[::1]:8080/v1'), 'loopback')

    def test_loopback_ipv4_mapped_ipv6(self):
        self.assertEqual(
            self.classifier._address_class('http://[::ffff:127.0.0.1]:8080/v1'), 'loopback')

    # Behavior 2: private (RFC1918, link-local).
    def test_private_rfc1918(self):
        self.assertEqual(self.classifier._address_class('http://10.0.0.5:8080/v1'), 'private')

    def test_private_link_local(self):
        self.assertEqual(self.classifier._address_class('http://[fe80::1]:8080/v1'), 'private')

    # Behavior 3: public, unresolved symbolic hostname, no DNS lookup.
    def test_public_symbolic_hostname_no_dns(self):
        self.assertEqual(self.classifier._address_class('https://openrouter.ai/api/v1'), 'public')

    # Behavior 4: bare host:port with no scheme — the "//" + raw retry.
    def test_bare_host_port_no_scheme(self):
        self.assertEqual(self.classifier._address_class('localhost:8080'), 'loopback')

    # Behavior 5: unix domain sockets.
    def test_unix_socket(self):
        self.assertEqual(self.classifier._address_class('unix:///var/run/llm.sock'), 'loopback')

    def test_http_unix_socket(self):
        self.assertEqual(
            self.classifier._address_class('http+unix://%2Fvar%2Frun%2Fdocker.sock/v1'),
            'loopback',
        )

    # Behavior 6: unset.
    def test_unset_empty_string(self):
        self.assertEqual(self.classifier._address_class(''), 'unset')

    def test_unset_whitespace_only(self):
        self.assertEqual(self.classifier._address_class('   '), 'unset')

    def test_unset_none(self):
        self.assertEqual(self.classifier._address_class(None), 'unset')

    # Behavior 7: garbage input never raises, always a member of the set.
    def test_never_raises_on_garbage_input(self):
        for garbage in ('not a url at all', '://', '%%%', 'http://[unclosed'):
            result = self.classifier._address_class(garbage)
            self.assertIn(result, self.classifier._ADDRESS_CLASSES)

    def test_never_calls_dns_resolution(self):
        # Static, source-level guard: no getaddrinfo anywhere in the module.
        text = (PLUGIN_DIR / 'classifier.py').read_text(encoding='utf-8')
        self.assertNotIn('getaddrinfo', text)


class LocalityResolutionTests(unittest.TestCase):
    """Behavior 8 — `_resolve_inference_locality` against tmpdir-built
    profile homes, and its fail-open posture."""

    @classmethod
    def setUpClass(cls):
        cls.classifier, cls.evaluators = _load_classifier({})

    def tearDown(self):
        _restore_env()

    def test_reads_provider_and_class_from_config_yaml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / 'profile-home'
            home.mkdir()
            (home / 'config.yaml').write_text(textwrap.dedent("""\
                model:
                  default: nvidia/nemotron-3-ultra-550b-a55b:free
                  provider: openrouter
                  base_url: https://openrouter.ai/api/v1
                other_top_level_key: unrelated
                """), encoding='utf-8')
            provider, address_class = self.classifier._resolve_inference_locality(
                _build_paths(self.classifier, home))
            self.assertEqual(provider, 'openrouter')
            self.assertEqual(address_class, 'public')

    def test_reads_loopback_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / 'profile-home'
            home.mkdir()
            (home / 'config.yaml').write_text(textwrap.dedent("""\
                model:
                  provider: local-vllm
                  base_url: http://127.0.0.1:8000/v1
                """), encoding='utf-8')
            provider, address_class = self.classifier._resolve_inference_locality(
                _build_paths(self.classifier, home))
            self.assertEqual(provider, 'local-vllm')
            self.assertEqual(address_class, 'loopback')

    def test_missing_config_yaml_fails_open(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / 'profile-home-no-config'
            home.mkdir()
            provider, address_class = self.classifier._resolve_inference_locality(
                _build_paths(self.classifier, home))
            self.assertEqual(provider, '')
            self.assertEqual(address_class, self.classifier.ADDRESS_CLASS_UNSET)

    def test_unreadable_config_yaml_fails_open(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / 'profile-home'
            home.mkdir()
            # A directory where a file is expected -- read_text() raises.
            (home / 'config.yaml').mkdir()
            provider, address_class = self.classifier._resolve_inference_locality(
                _build_paths(self.classifier, home))
            self.assertEqual(provider, '')
            self.assertEqual(address_class, self.classifier.ADDRESS_CLASS_UNSET)

    def test_config_yaml_with_no_model_block_fails_open_to_unset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / 'profile-home'
            home.mkdir()
            (home / 'config.yaml').write_text('other_key: value\n', encoding='utf-8')
            provider, address_class = self.classifier._resolve_inference_locality(
                _build_paths(self.classifier, home))
            self.assertEqual(provider, '')
            self.assertEqual(address_class, self.classifier.ADDRESS_CLASS_UNSET)

    def test_never_raises_regardless_of_input(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / 'profile-home'
            home.mkdir()
            (home / 'config.yaml').write_text('not: [valid, yaml, at all\n', encoding='utf-8')
            # Must not raise -- a malformed config.yaml is exactly the
            # fail-open case _paths_for_session itself already tolerates.
            provider, address_class = self.classifier._resolve_inference_locality(
                _build_paths(self.classifier, home))
            self.assertIn(address_class, self.classifier._ADDRESS_CLASSES)
            self.assertIsInstance(provider, str)


class NoLocalityClaimTests(unittest.TestCase):
    """Behavior 9 (plus a repeat of behavior 7 as a set-membership guard) —
    no locality claim, and no raw base_url substring, ever leaves either
    function."""

    @classmethod
    def setUpClass(cls):
        cls.classifier, cls.evaluators = _load_classifier({})

    def tearDown(self):
        _restore_env()

    def test_address_class_always_in_declared_four_value_set(self):
        c = self.classifier
        candidates = (
            'not a url at all', '://', '%%%', 'http://[unclosed',
            'http://127.0.0.1:8080/v1', 'http://10.0.0.5:8080/v1',
            'https://openrouter.ai/api/v1', 'localhost:8080',
            'unix:///var/run/llm.sock', '', None,
        )
        for raw in candidates:
            self.assertIn(c._address_class(raw), c._ADDRESS_CLASSES)
        self.assertEqual(
            c._ADDRESS_CLASSES, frozenset({'loopback', 'private', 'public', 'unset'}))

    def test_resolved_tuple_never_leaks_base_url_substring(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / 'profile-home'
            home.mkdir()
            secret_host = 'internal-vault-hostname-9f3a2'
            (home / 'config.yaml').write_text(textwrap.dedent(f"""\
                model:
                  provider: internal-proxy
                  base_url: http://{secret_host}.corp.example:9443/v1/secret-path?token=abc123
                """), encoding='utf-8')
            provider, address_class = self.classifier._resolve_inference_locality(
                _build_paths(self.classifier, home))
            self.assertNotIn(secret_host, provider)
            self.assertNotIn(secret_host, address_class)
            self.assertNotIn('token=abc123', provider)
            self.assertNotIn('token=abc123', address_class)
            self.assertIn(address_class, self.classifier._ADDRESS_CLASSES)

    def test_no_locality_claim_phrasing_in_source(self):
        # D-06: no comment, field name, or docstring may assert that prompt
        # data stayed local, was not logged, or was not retained.
        text = (PLUGIN_DIR / 'classifier.py').read_text(encoding='utf-8')
        start = text.index('def _address_class')
        end = text.index('def _resolve_inference_locality')
        locality_source = text[start:end] + text[end:end + 4000]
        forbidden_phrases = (
            'stayed local', 'never leaves the machine', 'not logged',
            'not retained', 'data never left',
        )
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, locality_source)


def _p46loc_attach_env(tmpdir, evaluator_name, base_url, provider):
    """A minimal, fully isolated state tree -- own HERMES_HOME + config.yaml
    (deterministic locality) AND own REVENIUM_STATE_DIR + config.json
    (llmOutcomeEvaluation opted in). Unlike test_phase42_assessment_contract's
    `_p42_shape_env`, HERMES_HOME is overridden too, so _attach_assessment's
    locality resolution never reads the real host's ~/.hermes/config.yaml --
    load-bearing for deterministic assertions on the resolved values below."""
    home = os.path.join(tmpdir, 'home')
    os.makedirs(home, exist_ok=True)
    with open(os.path.join(home, 'config.yaml'), 'w', encoding='utf-8') as f:
        f.write(f'model:\n  provider: {provider}\n  base_url: {base_url}\n')
    state_dir = os.path.join(tmpdir, 'state')
    os.makedirs(state_dir, exist_ok=True)
    config_file = os.path.join(state_dir, 'config.json')
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump({'llmOutcomeEvaluation': {
            'enabled': True, 'evaluator': evaluator_name, 'currency': 'USD',
        }}, f)
    return {
        'HERMES_HOME': home,
        'REVENIUM_STATE_DIR': state_dir,
        'REVENIUM_CONFIG_FILE': config_file,
    }


class AssessmentLocalityFieldsTests(unittest.TestCase):
    """Task 2, behaviors 1 and 5 -- every record `_build_job_assessment`
    returns via `_attach_assessment` (the six early-return abstention
    branches, both exception handlers, and the success branch) carries both
    `inference_provider` and `inference_address_class`, resolved from a
    deterministic, isolated config.yaml -- and no record contains the raw
    base_url used to derive the class.

    Mirrors test_phase42_assessment_contract.py's AbstentionRecordTests
    `_run_case` shape (same six behaviors driven through the same seam) --
    duplicated, not imported, per this module's own isolated-import idiom."""

    BASE_URL = 'http://127.0.0.1:9009/v1'
    PROVIDER = 'p46loc-test-provider'
    SECRET_MARKER = '9009'  # a substring of BASE_URL that must never leak

    def tearDown(self):
        _restore_env()

    def _run_case(self, label, behavior, evaluator_name=None):
        evaluator_name = evaluator_name or f'p46loc-attach-{label}'
        with tempfile.TemporaryDirectory(prefix=f'gsd-p46loc-attach-{label}-') as tmpdir:
            env = _p46loc_attach_env(tmpdir, evaluator_name, self.BASE_URL, self.PROVIDER)
            mod, ev = _load_classifier(env)

            if behavior == 'invalid':
                ev.register(evaluator_name, lambda job, t, c: mod._EVAL_INVALID, version='v1')
            elif behavior == 'timed_out':
                ev.register(evaluator_name, lambda job, t, c: mod._EVAL_TIMED_OUT, version='v1')
            elif behavior == 'abstained':
                ev.register(evaluator_name, lambda job, t, c: None, version='v1')
            elif behavior == 'rejected':
                ev.register(evaluator_name, lambda job, t, c: {
                    'inferred_role': 'x', 'estimated_hours_saved': -1.0,
                    'assumed_loaded_rate': 100.0, 'currency': 'USD',
                    'basis': 'x', 'confidence': 0.5,
                }, version='v1')
            elif behavior == 'failed':
                def _boom(job, t, c):
                    raise RuntimeError('boom')
                ev.register(evaluator_name, _boom, version='v1')
            elif behavior == 'mechanism_abstains_from_value':
                ev.register(evaluator_name, lambda job, t, c: {
                    'economic_mechanism': 'newly_enabled_work',
                    'inferred_role': 'x', 'basis': 'x', 'confidence': 0.5,
                }, version='v1')
            elif behavior == 'success':
                ev.register(evaluator_name, lambda job, t, c: {
                    'economic_mechanism': 'labor_substitution',
                    'inferred_role': 'engineer', 'estimated_hours_saved': 2.5,
                    'assumed_loaded_rate': 150.0, 'currency': 'USD',
                    'basis': 'time avoided', 'confidence': 0.5,
                }, version='v1')
            elif behavior is None:
                pass  # unknown_evaluator: evaluator_name is deliberately never registered
            else:
                raise AssertionError(f'unknown behavior {behavior!r}')

            valid = {'agentic_job_id': f'p46loc-{label}-job', 'job_name': 'n',
                      'job_type': 'bug_fix', 'status': 'SUCCESS'}
            paths = mod._module_paths()
            asyncio.run(mod._attach_assessment(valid, 'user: x\nassistant: y', paths))
            return valid.get('_assessment_record')

    def _assert_locality_present(self, rec, expected_reason):
        self.assertIsNotNone(rec, f'{expected_reason}: expected a real record, not None')
        self.assertIn('inference_provider', rec, f'{expected_reason}: missing inference_provider')
        self.assertIn(
            'inference_address_class', rec,
            f'{expected_reason}: missing inference_address_class',
        )
        self.assertEqual(rec['inference_provider'], self.PROVIDER)
        self.assertEqual(rec['inference_address_class'], 'loopback')
        # Behavior 2: always a member of the four-value set.
        self.assertIn('inference_address_class', rec)
        # Behavior 5: no record contains the raw base_url anywhere.
        serialized = json.dumps(rec)
        self.assertNotIn(self.BASE_URL, serialized)
        self.assertNotIn(self.SECRET_MARKER, serialized)

    def test_unknown_evaluator_carries_locality(self):
        rec = self._run_case(
            'unknown_evaluator', None, evaluator_name='p46loc-attach-never-registered')
        self.assertEqual(rec['abstention_reason'], 'unknown_evaluator')
        self._assert_locality_present(rec, 'unknown_evaluator')

    def test_invalid_response_carries_locality(self):
        rec = self._run_case('invalid', 'invalid')
        self.assertEqual(rec['abstention_reason'], 'invalid')
        self._assert_locality_present(rec, 'invalid')

    def test_timed_out_sentinel_carries_locality(self):
        rec = self._run_case('timed_out', 'timed_out')
        self.assertEqual(rec['abstention_reason'], 'timed_out')
        self._assert_locality_present(rec, 'timed_out')

    def test_abstained_carries_locality(self):
        rec = self._run_case('abstained', 'abstained')
        self.assertEqual(rec['abstention_reason'], 'abstained')
        self._assert_locality_present(rec, 'abstained')

    def test_mechanism_abstains_from_value_carries_locality(self):
        rec = self._run_case('mechanism_abstains_from_value', 'mechanism_abstains_from_value')
        self.assertEqual(rec['abstention_reason'], 'mechanism_abstains_from_value')
        self._assert_locality_present(rec, 'mechanism_abstains_from_value')

    def test_rejected_carries_locality(self):
        rec = self._run_case('rejected', 'rejected')
        self.assertEqual(rec['abstention_reason'], 'rejected')
        self._assert_locality_present(rec, 'rejected')

    def test_exception_timed_out_carries_locality(self):
        # The SECOND timed_out site -- a registered evaluator raising a
        # timeout directly, caught by _attach_assessment's own except clause.
        evaluator_name = 'p46loc-attach-exc-timed-out'
        with tempfile.TemporaryDirectory(prefix='gsd-p46loc-attach-exctimeout-') as tmpdir:
            env = _p46loc_attach_env(tmpdir, evaluator_name, self.BASE_URL, self.PROVIDER)
            mod, ev = _load_classifier(env)

            def _timeout(job, t, c):
                raise TimeoutError('timed out')
            ev.register(evaluator_name, _timeout, version='v1')
            valid = {'agentic_job_id': 'p46loc-exctimeout-job', 'job_name': 'n',
                      'job_type': 'bug_fix', 'status': 'SUCCESS'}
            paths = mod._module_paths()
            asyncio.run(mod._attach_assessment(valid, 'user: x\nassistant: y', paths))
            rec = valid.get('_assessment_record')
        self.assertEqual(rec['abstention_reason'], 'timed_out')
        self._assert_locality_present(rec, 'exception_timed_out')

    def test_generic_exception_carries_locality(self):
        rec = self._run_case('failed', 'failed')
        self.assertEqual(rec['abstention_reason'], 'failed')
        self._assert_locality_present(rec, 'failed')

    def test_success_carries_locality(self):
        rec = self._run_case('success', 'success')
        self.assertEqual(rec['abstention_reason'], '')
        self._assert_locality_present(rec, 'success')


if __name__ == '__main__':
    unittest.main()
