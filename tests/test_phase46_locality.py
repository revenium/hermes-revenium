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
import importlib.util
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
    """Import the revenium-classifier plugin fresh; return the classifier module."""
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
    return _sys.modules[f'{name}.classifier']


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
        cls.classifier = _load_classifier({})

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
        cls.classifier = _load_classifier({})

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
        cls.classifier = _load_classifier({})

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


if __name__ == '__main__':
    unittest.main()
