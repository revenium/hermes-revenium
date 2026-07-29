"""Phase 29 Plan 01 (HOOK-01) — locks the on_session_finalize wiring end to end.

Mirrors the focused-per-phase-module convention established in
tests/test_phase28_classifier_reject_log.py so parallel plans in later
waves do not serialize on the monolithic tests/test_repository.py file.

The single load-bearing fact this module protects: on_session_finalize
carries session_id/platform/reason (NOT completed/interrupted). Binding
_on_session_end's signature to that hook raises TypeError on every real
invocation, and Hermes' invoke_hook swallows that into a bare
logger.warning — a silently-broken plugin that looks healthy. See
29-PATTERNS.md / 29-RESEARCH.md <hook_signature_contract>.
"""
import importlib.util
import inspect
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from tests.test_repository import _setup_plugin_env, _restore_plugin_env

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'


def _load_plugin_module(mod_name):
    """Load the plugin package via spec_from_file_location the same way the
    Hermes plugin manager loads plugins by path. submodule_search_locations
    is required because __init__.py performs a relative import
    (`from .classifier import ...`); a bare spec_from_file_location(name, path)
    would fail that import."""
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


def _classifier_submodule(mod_name):
    """The plugin's relative import binds a SUBMODULE named
    f'{mod_name}.classifier' — patch call_llm / helpers on that submodule
    object, not on a bare `classifier` module, or the mock will not be seen
    by the plugin's own module-global references."""
    return sys.modules[f'{mod_name}.classifier']


def _seed_substantive_session_jsonl(hermes_home, sid):
    """Seed <hermes_home>/sessions/<sid>.jsonl with a role:user + role:tool
    pair, mirroring test_repository.py's
    test_revenium_classifier_plugin_entrypoint idiom, so any turn-shape
    heuristic sees a substantive (not trivial) turn."""
    sessions_dir = os.path.join(hermes_home, 'sessions')
    os.makedirs(sessions_dir, exist_ok=True)
    with open(os.path.join(sessions_dir, f'{sid}.jsonl'), 'w', encoding='utf-8') as f:
        f.write(json.dumps({'role': 'user', 'content': 'Please review src/foo.py'}) + '\n')
        f.write(json.dumps({'role': 'tool', 'name': 'read_file'}) + '\n')


def _llm_response(content):
    resp = unittest.mock.MagicMock()
    resp.choices = [unittest.mock.MagicMock()]
    resp.choices[0].message.content = content
    return resp


class HookRegistrationTests(unittest.TestCase):
    def test_register_wires_on_session_end_and_on_session_finalize(self):
        """register(ctx) must bind BOTH hooks, and on_session_finalize must be
        bound to _on_session_finalize specifically (a runtime binding
        assertion, immune to how the file is commented)."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-register-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod = _load_plugin_module('phase29_register_test')

            registered = {}

            class StubCtx:
                def register_hook(self, name, cb):
                    registered[name] = cb

            mod.register(StubCtx())

            self.assertEqual(len(registered), 2,
                             'register(ctx) must call register_hook exactly twice')
            self.assertIs(registered['on_session_end'], mod._on_session_end)
            self.assertIs(registered['on_session_finalize'], mod._on_session_finalize,
                          'on_session_finalize must be bound to _on_session_finalize, '
                          'not _on_session_end')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_end_to_end_classifies_and_writes_marker_pair(self):
        """The tracer's proof: registering on_session_finalize and invoking the
        recorded callback with the confirmed production kwargs
        (session_id, platform, reason) drives run_classification to
        completion and lands a GUARDRAIL+CHAT marker pair on disk."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-e2e-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase29_e2e_test'
            mod = _load_plugin_module(mod_name)
            classifier_sub = _classifier_submodule(mod_name)

            registered = {}

            class StubCtx:
                def register_hook(self, name, cb):
                    registered[name] = cb

            mod.register(StubCtx())

            sid = 'gw-session-e2e-001'
            _seed_substantive_session_jsonl(hh, sid)

            with unittest.mock.patch.object(classifier_sub, 'call_llm',
                                             return_value=_llm_response('code_review')):
                registered['on_session_finalize'](
                    session_id=sid,
                    platform='gateway',
                    reason='shutdown',
                )

            marker_path = classifier_sub.MARKERS_DIR / f'{sid}.jsonl'
            self.assertTrue(marker_path.is_file(),
                            f'on_session_finalize did not produce marker file at {marker_path}')
            lines = marker_path.read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(lines), 2,
                             'on_session_finalize must write exactly one GUARDRAIL + one CHAT record')
            recs = [json.loads(l) for l in lines]
            self.assertEqual({r['task_type'] for r in recs}, {'code_review'})
            self.assertEqual({r['operation_type'] for r in recs}, {'GUARDRAIL', 'CHAT'})
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_signature_has_correct_kwargs_no_completed_interrupted(self):
        """Runtime-signature assertion (not source text): _on_session_finalize
        must accept session_id/platform/reason, must NOT declare completed or
        interrupted, and must carry a **kwargs (VAR_KEYWORD) parameter."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-sig-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod = _load_plugin_module('phase29_sig_test')
            params = inspect.signature(mod._on_session_finalize).parameters
            self.assertTrue({'session_id', 'platform', 'reason'} <= set(params))
            self.assertNotIn('completed', params)
            self.assertNotIn('interrupted', params)
            self.assertTrue(
                any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()),
                '_on_session_finalize must declare a **kwargs parameter for forward compatibility',
            )
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_no_typeerror_for_session_expired_reason(self):
        """gateway/run.py:8585 fires reason='session_expired' with no
        completed/interrupted kwarg — must not raise TypeError."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-expired-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod = _load_plugin_module('phase29_expired_test')
            try:
                mod._on_session_finalize(session_id='x', platform='gateway', reason='session_expired')
            except TypeError as exc:
                self.fail(f'_on_session_finalize raised TypeError for reason=session_expired: {exc}')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_no_typeerror_for_new_session_reason(self):
        """gateway/slash_commands.py:215 fires reason='new_session' — must not
        raise TypeError."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-newsession-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod = _load_plugin_module('phase29_newsession_test')
            try:
                mod._on_session_finalize(session_id='x', platform='gateway', reason='new_session')
            except TypeError as exc:
                self.fail(f'_on_session_finalize raised TypeError for reason=new_session: {exc}')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_no_typeerror_for_unknown_extra_kwarg(self):
        """**kwargs must absorb any future payload field without raising."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-extrakwarg-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod = _load_plugin_module('phase29_extrakwarg_test')
            try:
                mod._on_session_finalize(
                    session_id='x', platform='gateway', reason='shutdown',
                    some_future_field='unexpected-value',
                )
            except TypeError as exc:
                self.fail(f'_on_session_finalize raised TypeError for an unknown extra kwarg: {exc}')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_never_raises_on_none_session_id(self):
        """D-04 belt: a falsy session_id must return normally, no exception."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-nonesid-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod = _load_plugin_module('phase29_nonesid_test')
            try:
                result = mod._on_session_finalize(session_id=None, platform='gateway', reason='shutdown')
            except Exception as exc:
                self.fail(f'_on_session_finalize raised for session_id=None: {exc}')
            self.assertIsNone(result)
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_never_raises_when_run_classification_raises_and_still_writes_sentinel(self):
        """D-04 belt: an exploding run_classification must be swallowed AND the
        except-path sentinel write must still land, mirroring
        _on_session_end's D-21 discipline."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-explode-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        ready_dir = os.path.join(sd, 'markers', '.ready')
        prev_ready = os.environ.get('REVENIUM_MARKERS_READY_DIR')
        os.environ['REVENIUM_MARKERS_READY_DIR'] = ready_dir
        os.makedirs(ready_dir, mode=0o700, exist_ok=True)
        try:
            mod = _load_plugin_module('phase29_explode_test')
            sid = 'explode-sid'
            with unittest.mock.patch.object(mod, 'run_classification',
                                             side_effect=RuntimeError('boom from run_classification')):
                try:
                    mod._on_session_finalize(session_id=sid, platform='gateway', reason='shutdown')
                except Exception as exc:
                    self.fail(f'_on_session_finalize raised when run_classification exploded: {exc}')

            sentinel_path = os.path.join(ready_dir, sid)
            self.assertTrue(os.path.exists(sentinel_path),
                            'sentinel must still be written on the exception path')
        finally:
            if prev_ready is None:
                os.environ.pop('REVENIUM_MARKERS_READY_DIR', None)
            else:
                os.environ['REVENIUM_MARKERS_READY_DIR'] = prev_ready
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_never_raises_when_sentinel_dir_unwritable(self):
        """D-04 belt: even if the sentinel write itself cannot succeed (parent
        directory unwritable), _on_session_finalize must still return
        normally — _write_sentinel's own try/except is the swallow point."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-unwritable-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod = _load_plugin_module('phase29_unwritable_test')
            # Remove write permission on the markers dir so mkdir('.ready') fails.
            os.chmod(md, 0o500)
            try:
                mod._on_session_finalize(session_id='unwritable-sid', platform='gateway', reason='shutdown')
            except Exception as exc:
                self.fail(f'_on_session_finalize raised with an unwritable sentinel dir: {exc}')
        finally:
            os.chmod(md, 0o700)
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_sentinel_written_zero_byte_on_success(self):
        """After a successful invocation the sentinel file
        <REVENIUM_MARKERS_READY_DIR>/<sid> exists and is zero bytes."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-sentinelok-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        ready_dir = os.path.join(sd, 'markers', '.ready')
        prev_ready = os.environ.get('REVENIUM_MARKERS_READY_DIR')
        os.environ['REVENIUM_MARKERS_READY_DIR'] = ready_dir
        os.makedirs(ready_dir, mode=0o700, exist_ok=True)
        try:
            mod = _load_plugin_module('phase29_sentinelok_test')
            sid = 'sentinel-ok-sid'
            with unittest.mock.patch.object(mod, 'run_classification', return_value=None):
                mod._on_session_finalize(session_id=sid, platform='gateway', reason='shutdown')

            sentinel_path = os.path.join(ready_dir, sid)
            self.assertTrue(os.path.exists(sentinel_path), 'sentinel not written on success')
            self.assertEqual(os.path.getsize(sentinel_path), 0, 'sentinel must be zero-byte')
        finally:
            if prev_ready is None:
                os.environ.pop('REVENIUM_MARKERS_READY_DIR', None)
            else:
                os.environ['REVENIUM_MARKERS_READY_DIR'] = prev_ready
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
