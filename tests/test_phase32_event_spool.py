"""Phase 32 Plan 01 (EVT-01/EVT-02/EVT-03) — the tracer's proof.

One post_api_request event travels from the in-process spool writer
(api_event_spool.spool_api_request) through a spool file on disk, through
api-event-report.sh, out to a `revenium` CLI shim, and into a new
api_request_id-keyed ledger — end to end, on one path.

Mirrors the loading idiom established by tests/test_phase29_hook_registration.py
(_load_plugin_module / _classifier_submodule) since api_event_spool.py performs
a package-relative import (`from .classifier import ...`) and can only be
loaded as a submodule of the revenium_classifier package.
"""
import importlib
import importlib.util
import json
import os
import shlex
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_repository import _setup_plugin_env, _restore_plugin_env
from tests._compat_helpers import build_shim, run_script

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'
SCRIPTS_DIR = ROOT / 'skills' / 'revenium' / 'scripts'


def _load_plugin_module(mod_name):
    """Load the plugin package via spec_from_file_location, mirroring
    test_phase29_hook_registration.py's _load_plugin_module exactly.
    submodule_search_locations is required because __init__.py (and, as of
    Phase 32, api_event_spool.py) perform relative imports."""
    pkg_init = PLUGIN_DIR / '__init__.py'
    spec = importlib.util.spec_from_file_location(
        mod_name,
        str(pkg_init),
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _api_event_spool_submodule(mod_name):
    """The plugin's relative import binds a SUBMODULE named
    f'{mod_name}.api_event_spool' — import it directly so tests can call its
    internals without going through the __init__.py callback."""
    importlib.import_module(f'{mod_name}.api_event_spool')
    return sys.modules[f'{mod_name}.api_event_spool']


def _synthetic_payload(**overrides):
    """The confirmed test-fixture shape from RESEARCH.md Pattern 1
    (hermes_cli/hooks.py:198-214), extended with the timing/identifier
    kwargs the real call site (conversation_loop.py:5658-5691) also passes."""
    payload = dict(
        session_id='test-session',
        api_request_id='test-session:task-1:turn-1:api:1',
        started_at=1715515000.0,
        ended_at=1715515001.234,
        platform='cli',
        model='claude-sonnet-4-6',
        response_model='claude-sonnet-4-6',
        provider='anthropic',
        base_url='https://api.anthropic.com',
        api_mode='anthropic_messages',
        api_duration=1.234,
        finish_reason='stop',
        usage={
            'input_tokens': 2048, 'output_tokens': 512,
            'cache_read_tokens': 0, 'cache_write_tokens': 0,
            'reasoning_tokens': 0, 'request_count': 1,
            'prompt_tokens': 2048, 'total_tokens': 2560,
        },
    )
    payload.update(overrides)
    return payload


class SpoolApiRequestWriteTests(unittest.TestCase):
    """Task 1g test 1 — one synthetic payload produces one contract-C-2 record."""

    def test_synthetic_payload_produces_one_well_formed_record(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-spool-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase32_spool_write_test'
            _load_plugin_module(mod_name)
            spool_sub = _api_event_spool_submodule(mod_name)

            spool_sub.spool_api_request(**_synthetic_payload())

            event_path = Path(sd) / 'api-events' / 'test-session.jsonl'
            self.assertTrue(event_path.is_file(), f'no spool file at {event_path}')
            lines = event_path.read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(lines), 1, 'expected exactly one record')

            rec = json.loads(lines[0])
            self.assertEqual(rec['v'], 1)
            self.assertEqual(rec['sid'], 'test-session')
            self.assertEqual(rec['api_request_id'], 'test-session:task-1:turn-1:api:1')
            self.assertEqual(rec['ts'], 1715515000.0)
            self.assertEqual(rec['ended_at'], 1715515001.234)
            self.assertEqual(rec['duration_ms'], 1234)
            self.assertEqual(rec['input_tokens'], 2048)
            self.assertEqual(rec['output_tokens'], 512)
            self.assertEqual(rec['total_tokens'], 2560)
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)


class ApiEventReportShipperTests(unittest.TestCase):
    """Task 1g tests 2/3 — one cron invocation ships one row and writes one
    ledger line; a second invocation over the same spool ships nothing."""

    def _run_once(self, tmpdir, hermes_home, state_dir, meter_log, inv_log, shim_home):
        base_env = {
            **os.environ,
            'HOME': shim_home,
            'HERMES_HOME': hermes_home,
            'REVENIUM_STATE_DIR': state_dir,
            'PATH': os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': inv_log,
            'METER_LOG': meter_log,
            'TZ': 'UTC',
        }
        return run_script(SCRIPTS_DIR / 'api-event-report.sh', base_env, inv_log)

    def test_one_event_ships_once_and_repeat_run_is_idempotent(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-shipper-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            spool_dir = os.path.join(state_dir, 'api-events')
            os.makedirs(spool_dir, mode=0o700)

            # Per Task 1g: place the shim at ${HOME}/.local/bin -- ensure_path
            # prepends this last, so it ends up FIRST on PATH regardless of
            # what else exists on the real PATH.
            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            shim = os.path.join(bin_dir, 'revenium')
            build_shim(shim)

            record = {
                'v': 1, 'sid': 'compat-sid-001',
                'api_request_id': 'compat-sid-001:task-1:turn-1:api:1',
                'ts': 1715515000.0, 'ended_at': 1715515001.234,
                'duration_ms': 1234, 'platform': 'cli',
                'model': 'claude-sonnet-4-6', 'response_model': 'claude-sonnet-4-6',
                'provider': 'anthropic', 'base_url': 'https://api.anthropic.com',
                'api_mode': 'anthropic_messages', 'finish_reason': 'stop',
                'input_tokens': 2048, 'output_tokens': 512,
                'cache_read_tokens': 0, 'cache_write_tokens': 0,
                'reasoning_tokens': 0, 'total_tokens': 2560,
            }
            with open(os.path.join(spool_dir, 'compat-sid-001.jsonl'), 'w') as f:
                f.write(json.dumps(record, separators=(',', ':')) + '\n')

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')

            rc1, invocations1, output1 = self._run_once(
                tmpdir, hermes_home, state_dir, meter_log, inv_log, shim_home
            )
            self.assertEqual(rc1, 0, f'api-event-report.sh failed (rc={rc1}): {output1}')

            meter_invocations = []
            if os.path.exists(meter_log):
                with open(meter_log) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            meter_invocations.append(shlex.split(line))
            completion_inv = [
                a for a in meter_invocations
                if len(a) >= 2 and a[0] == 'meter' and a[1] == 'completion'
            ]
            self.assertEqual(len(completion_inv), 1,
                             f'expected exactly one meter completion call, got: {meter_invocations!r}')

            ledger_path = os.path.join(state_dir, 'revenium-api-events.ledger')
            self.assertTrue(os.path.exists(ledger_path), 'ledger file not created')
            with open(ledger_path) as f:
                ledger_lines = [l for l in f.read().splitlines() if l]
            self.assertEqual(len(ledger_lines), 1, f'expected one ledger line, got {ledger_lines!r}')
            self.assertTrue(
                ledger_lines[0].startswith('API:compat-sid-001:task-1:turn-1:api:1|compat-sid-001|'),
                f'unexpected ledger line shape: {ledger_lines[0]!r}',
            )

            # --- Second invocation over the same spool: nothing new ships ---
            rc2, _ignored, output2 = self._run_once(
                tmpdir, hermes_home, state_dir, meter_log, inv_log, shim_home
            )
            self.assertEqual(rc2, 0, f'second api-event-report.sh run failed (rc={rc2}): {output2}')

            meter_invocations_2 = []
            if os.path.exists(meter_log):
                with open(meter_log) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            meter_invocations_2.append(shlex.split(line))
            completion_inv_2 = [
                a for a in meter_invocations_2
                if len(a) >= 2 and a[0] == 'meter' and a[1] == 'completion'
            ]
            self.assertEqual(len(completion_inv_2), 1,
                             'second run must not add a second meter completion invocation')

            with open(ledger_path) as f:
                ledger_lines_2 = [l for l in f.read().splitlines() if l]
            self.assertEqual(len(ledger_lines_2), 1,
                             'second run must not add a second ledger line')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class SpoolHardeningTests(unittest.TestCase):
    """Task 2 — proves the three ways the tracer's writer could be wrong or
    dangerous are actually closed: the usage fallback, identifier
    validation, and never-raise under malformed input."""

    # --- (a) usage fallback, proven not asserted ---

    def test_response_usage_key_conflict_kwarg_wins(self):
        """A `response` shaped exactly as Hermes builds it (a plain dict
        carrying a `usage` key whose values DIFFER from the top-level
        `usage` kwarg) must not influence the record — the top-level kwarg
        always wins, because this hook's `response` never carries a real
        `.usage` attribute (Contract C-3)."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-hardening-usage-conflict-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase32_hardening_usage_conflict_test'
            _load_plugin_module(mod_name)
            spool_sub = _api_event_spool_submodule(mod_name)

            conflicting_response = {
                'model': 'claude-sonnet-4-6', 'finish_reason': 'stop',
                'assistant_message': {'role': 'assistant', 'content': 'ignored'},
                'usage': {'input_tokens': 999999, 'output_tokens': 999999,
                          'total_tokens': 1999998},
            }
            payload = _synthetic_payload(response=conflicting_response)
            spool_sub.spool_api_request(**payload)

            event_path = Path(sd) / 'api-events' / 'test-session.jsonl'
            self.assertTrue(event_path.is_file())
            rec = json.loads(event_path.read_text(encoding='utf-8').splitlines()[0])
            self.assertEqual(rec['input_tokens'], 2048,
                             'input_tokens must come from the top-level usage kwarg')
            self.assertEqual(rec['output_tokens'], 512,
                             'output_tokens must come from the top-level usage kwarg')
            self.assertEqual(rec['total_tokens'], 2560,
                             'total_tokens must come from the top-level usage kwarg')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_response_present_but_usage_none_writes_nothing(self):
        """A `response` dict present alongside `usage=None` must write NO
        record — not a record of zeros."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-hardening-usage-none-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase32_hardening_usage_none_test'
            _load_plugin_module(mod_name)
            spool_sub = _api_event_spool_submodule(mod_name)

            payload = _synthetic_payload(
                response={'model': 'x', 'usage': {'input_tokens': 5}},
                usage=None,
            )
            spool_sub.spool_api_request(**payload)

            event_path = Path(sd) / 'api-events' / 'test-session.jsonl'
            self.assertFalse(event_path.exists(),
                             'usage=None must write no record, not a record of zeros')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_output_tokens_falls_back_to_completion_tokens(self):
        """output_tokens absent with completion_tokens present must populate
        output_tokens from completion_tokens (langfuse's own fallback)."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-hardening-completion-fallback-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase32_hardening_completion_fallback_test'
            _load_plugin_module(mod_name)
            spool_sub = _api_event_spool_submodule(mod_name)

            payload = _synthetic_payload(usage={
                'input_tokens': 100, 'completion_tokens': 77, 'total_tokens': 177,
            })
            spool_sub.spool_api_request(**payload)

            event_path = Path(sd) / 'api-events' / 'test-session.jsonl'
            rec = json.loads(event_path.read_text(encoding='utf-8').splitlines()[0])
            self.assertEqual(rec['output_tokens'], 77)
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    # --- (b) identifier validation before path construction ---

    def test_traversal_shaped_session_id_writes_nothing(self):
        """A traversal-shaped, non-namespaced session_id must fail the
        filename allowlist and write nothing — no fallback to a scan or a
        pseudo identifier."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-hardening-traversal-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase32_hardening_traversal_test'
            _load_plugin_module(mod_name)
            spool_sub = _api_event_spool_submodule(mod_name)

            payload = _synthetic_payload(session_id='../../../etc/passwd')
            spool_sub.spool_api_request(**payload)

            api_events_dir = Path(sd) / 'api-events'
            written = list(api_events_dir.glob('**/*.jsonl')) if api_events_dir.exists() else []
            self.assertEqual(written, [], f'expected no file written, found: {written}')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_traversal_shaped_namespaced_remainder_writes_nothing(self):
        """A namespaced identifier whose REMAINDER (after `agent:<profile>:`
        is consumed by per-profile resolution) is traversal-shaped must also
        write nothing — the allowlist applies to the filename component,
        not just the whole raw string."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-hardening-ns-traversal-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase32_hardening_ns_traversal_test'
            _load_plugin_module(mod_name)
            spool_sub = _api_event_spool_submodule(mod_name)

            payload = _synthetic_payload(session_id='agent:someprofile:../../evil')
            spool_sub.spool_api_request(**payload)

            state_root = Path(hh)
            written = list(state_root.glob('**/api-events/**/*.jsonl'))
            self.assertEqual(written, [], f'expected no file written, found: {written}')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_empty_api_request_id_after_sanitisation_writes_nothing(self):
        """An api_request_id that sanitises to empty (all forbidden chars)
        must write no record."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-hardening-empty-arid-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase32_hardening_empty_arid_test'
            _load_plugin_module(mod_name)
            spool_sub = _api_event_spool_submodule(mod_name)

            payload = _synthetic_payload(api_request_id='|||\n\r')
            spool_sub.spool_api_request(**payload)

            event_path = Path(sd) / 'api-events' / 'test-session.jsonl'
            self.assertFalse(event_path.exists())
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    # --- (c) never raise, under any input ---

    def test_usage_as_string_never_raises_and_writes_nothing(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-hardening-usage-string-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase32_hardening_usage_string_test'
            _load_plugin_module(mod_name)
            spool_sub = _api_event_spool_submodule(mod_name)

            payload = _synthetic_payload(usage='not-a-dict')
            try:
                result = spool_sub.spool_api_request(**payload)
            except Exception as exc:
                self.fail(f'spool_api_request raised for usage=string: {exc}')
            self.assertIsNone(result)

            event_path = Path(sd) / 'api-events' / 'test-session.jsonl'
            self.assertFalse(event_path.exists())
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_none_started_at_never_raises_and_writes_nothing(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-hardening-none-started-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase32_hardening_none_started_test'
            _load_plugin_module(mod_name)
            spool_sub = _api_event_spool_submodule(mod_name)

            payload = _synthetic_payload(started_at=None)
            try:
                spool_sub.spool_api_request(**payload)
            except Exception as exc:
                self.fail(f'spool_api_request raised for started_at=None: {exc}')

            event_path = Path(sd) / 'api-events' / 'test-session.jsonl'
            self.assertFalse(event_path.exists())
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_unwritable_spool_dir_never_raises_and_writes_nothing(self):
        """chmod the STATE_DIR (the spool dir's parent) to 0o500 so the
        spool subdirectory itself cannot be created — a leaf-directory chmod
        would be silently undone by the writer's own belt-and-suspenders
        chmod(0o700), so the parent is the correct failure point to force."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-hardening-unwritable-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase32_hardening_unwritable_test'
            _load_plugin_module(mod_name)
            spool_sub = _api_event_spool_submodule(mod_name)

            os.chmod(sd, 0o500)
            try:
                payload = _synthetic_payload()
                try:
                    spool_sub.spool_api_request(**payload)
                except Exception as exc:
                    self.fail(f'spool_api_request raised with an unwritable spool dir: {exc}')

                event_path = Path(sd) / 'api-events' / 'test-session.jsonl'
                self.assertFalse(event_path.exists())
            finally:
                os.chmod(sd, 0o700)
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_none_session_id_never_raises_and_writes_nothing(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-hardening-none-sid-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase32_hardening_none_sid_test'
            _load_plugin_module(mod_name)
            spool_sub = _api_event_spool_submodule(mod_name)

            payload = _synthetic_payload(session_id=None)
            try:
                result = spool_sub.spool_api_request(**payload)
            except Exception as exc:
                self.fail(f'spool_api_request raised for session_id=None: {exc}')
            self.assertIsNone(result)

            api_events_dir = Path(sd) / 'api-events'
            written = list(api_events_dir.glob('**/*.jsonl')) if api_events_dir.exists() else []
            self.assertEqual(written, [])
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    # --- record key-set exactness ---

    def test_record_key_set_equals_contract_c2_allowlist_exactly(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-hardening-keyset-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase32_hardening_keyset_test'
            _load_plugin_module(mod_name)
            spool_sub = _api_event_spool_submodule(mod_name)

            spool_sub.spool_api_request(**_synthetic_payload())

            event_path = Path(sd) / 'api-events' / 'test-session.jsonl'
            rec = json.loads(event_path.read_text(encoding='utf-8').splitlines()[0])
            self.assertEqual(set(rec.keys()), set(spool_sub._RECORD_KEYS))
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)


class SpoolDirResolutionParityTests(unittest.TestCase):
    """Task 3e — the plugin's _spool_dir_for_session and the cron-side
    sidecar's resolve_state_subdir(..., "api-events") must agree on every
    identifier shape below. The two implementations are deliberately NOT
    shared code (mirrors classifier.py / resolve-markers-dir.py's own
    documented split); this test is the only mechanism keeping them honest."""

    def _load_sidecar(self):
        sidecar_path = SCRIPTS_DIR / 'resolve-markers-dir.py'
        spec = importlib.util.spec_from_file_location(
            'phase32_spool_dir_sidecar', str(sidecar_path),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_plugin_and_sidecar_agree_on_every_identifier_shape(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-parity-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase32_parity_test'
            _load_plugin_module(mod_name)
            spool_sub = _api_event_spool_submodule(mod_name)
            sidecar = self._load_sidecar()

            # A real profile home so the "profile home exists" case is
            # genuine, not merely asserted.
            existing_profile_home = os.path.join(hh, 'profiles', 'coder')
            os.makedirs(existing_profile_home, exist_ok=True)

            cases = [
                'plain-session-id',                                  # non-namespaced
                'agent:coder:sess-with-existing-profile',             # profile home exists
                'agent:ghost-profile:sess-with-missing-profile',      # profile home missing
                'agent:default:sess-default-profile',                 # default-profile namespace
                '',                                                   # empty identifier
                'agent:../../evil:sess-traversal-profile',            # traversal-shaped profile segment
            ]

            for sid in cases:
                plugin_dir = str(spool_sub._spool_dir_for_session(sid))
                sidecar_dir = sidecar.resolve_state_subdir(sid, 'api-events')
                self.assertEqual(
                    plugin_dir, sidecar_dir,
                    f'plugin and sidecar disagree for sid={sid!r}: '
                    f'plugin={plugin_dir!r} sidecar={sidecar_dir!r}',
                )
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_resolve_markers_dir_still_byte_compatible_after_generalization(self):
        """The pre-existing resolve_markers_dir(session_id, override) public
        shape must be untouched by the resolve_state_subdir generalization —
        same positional signature, same return value, for both the
        namespaced and non-namespaced cases."""
        sidecar = self._load_sidecar()
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase32-markers-compat-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            os.makedirs(os.path.join(hermes_home, 'profiles', 'coder'), exist_ok=True)
            prev_home = os.environ.get('HERMES_HOME')
            os.environ['HERMES_HOME'] = hermes_home
            try:
                self.assertEqual(
                    sidecar.resolve_markers_dir('plain-sid'),
                    sidecar.resolve_state_subdir('plain-sid', 'markers'),
                )
                self.assertEqual(
                    sidecar.resolve_markers_dir('agent:coder:sess-1'),
                    sidecar.resolve_state_subdir('agent:coder:sess-1', 'markers'),
                )
            finally:
                if prev_home is None:
                    os.environ.pop('HERMES_HOME', None)
                else:
                    os.environ['HERMES_HOME'] = prev_home
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
