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
        """register(ctx) must bind ALL THREE hooks, and each hook name must be
        bound to its own dedicated callback (a runtime binding assertion,
        immune to how the file is commented)."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-register-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod = _load_plugin_module('phase29_register_test')

            registered = {}

            class StubCtx:
                def register_hook(self, name, cb):
                    registered[name] = cb

            mod.register(StubCtx())

            self.assertEqual(len(registered), 3,
                             'register(ctx) must call register_hook exactly three times')
            self.assertIs(registered['on_session_end'], mod._on_session_end)
            self.assertIs(registered['on_session_finalize'], mod._on_session_finalize,
                          'on_session_finalize must be bound to _on_session_finalize, '
                          'not _on_session_end')
            self.assertIs(registered['post_llm_call'], mod._on_post_llm_call,
                          'post_llm_call must be bound to _on_post_llm_call')
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


class HookRegistrationHardeningTests(unittest.TestCase):
    """Task 2 — proves the boundary callback against the shapes it actually
    meets in production: the three real `reason` values, the reset payload's
    extra identifiers, subagent inheritance, the halt gate, and the sentinel
    guarantee."""

    def test_reset_path_classifies_session_id_not_old_or_new(self):
        """on_session_finalize fires from gateway/slash_commands.py:215 with
        old_session_id / new_session_id present in the payload. The callback
        must classify the session_id it was handed — not either identifier."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-reset-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase29_reset_test'
            mod = _load_plugin_module(mod_name)
            classifier_sub = _classifier_submodule(mod_name)

            sid = 'reset-session-sid'
            old_sid = 'reset-old-sid'
            new_sid = 'reset-new-sid'
            _seed_substantive_session_jsonl(hh, sid)

            with unittest.mock.patch.object(classifier_sub, 'call_llm',
                                             return_value=_llm_response('planning')):
                mod._on_session_finalize(
                    session_id=sid,
                    platform='gateway',
                    reason='new_session',
                    old_session_id=old_sid,
                    new_session_id=new_sid,
                )

            self.assertTrue((classifier_sub.MARKERS_DIR / f'{sid}.jsonl').is_file(),
                            'the handed session_id must be classified')
            self.assertFalse((classifier_sub.MARKERS_DIR / f'{old_sid}.jsonl').exists(),
                             'old_session_id must NOT be classified')
            self.assertFalse((classifier_sub.MARKERS_DIR / f'{new_sid}.jsonl').exists(),
                             'new_session_id must NOT be classified')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_root_session_produces_exactly_one_job_marker(self):
        """For a root session (parent_session_id unset), the boundary callback
        must still drive Step 7 job inference and produce exactly one
        kind:"job" record."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-jobmarker-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase29_jobmarker_test'
            mod = _load_plugin_module(mod_name)
            classifier_sub = _classifier_submodule(mod_name)

            sid = 'root-session-job-sid'

            # Seed state.db with a root row (parent_session_id NULL) so
            # _walk_to_root_session resolves sid to itself deliberately,
            # not merely by fail-open on a missing db.
            state_db_path = os.path.join(hh, 'state.db')
            conn = sqlite3.connect(state_db_path)
            conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT)")
            conn.execute("INSERT INTO sessions VALUES (?, ?)", (sid, None))
            conn.commit()
            conn.close()

            task_resp = _llm_response('code_review')
            job_array_resp = _llm_response(json.dumps([
                {"agentic_job_id": "root_job_a1b2", "job_name": "Root job",
                 "job_type": "bug_fix", "status": "SUCCESS"},
            ]))
            fake_transcript = "user: fix the bug\nassistant: fixed it."

            with unittest.mock.patch.object(classifier_sub, 'call_llm',
                                             side_effect=[task_resp, job_array_resp]), \
                 unittest.mock.patch.object(classifier_sub, '_read_session_transcript',
                                            return_value=fake_transcript):
                mod._on_session_finalize(session_id=sid, platform='gateway', reason='shutdown')

            marker_path = classifier_sub.MARKERS_DIR / f'{sid}.jsonl'
            self.assertTrue(marker_path.is_file())
            recs = [json.loads(l) for l in marker_path.read_text(encoding='utf-8').splitlines()]
            job_recs = [r for r in recs if r.get('kind') == 'job']
            self.assertEqual(len(job_recs), 1,
                             f'expected exactly one job record, got {len(job_recs)}: {job_recs}')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_subagent_inheritance_still_short_circuits(self):
        """When triggered by the boundary hook, a subagent session whose root
        already carries a task_type must inherit it directly — no LLM call."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-subagent-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase29_subagent_test'
            mod = _load_plugin_module(mod_name)
            classifier_sub = _classifier_submodule(mod_name)

            root_sid = 'subagent-root-sid'
            child_sid = 'subagent-child-sid'

            state_db_path = os.path.join(hh, 'state.db')
            conn = sqlite3.connect(state_db_path)
            conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT)")
            conn.execute("INSERT INTO sessions VALUES (?, ?)", (root_sid, None))
            conn.execute("INSERT INTO sessions VALUES (?, ?)", (child_sid, root_sid))
            conn.commit()
            conn.close()

            root_marker = os.path.join(md, f'{root_sid}.jsonl')
            with open(root_marker, 'w', encoding='utf-8') as f:
                rec = {"muid": "a" * 33, "ts": 1.0, "sid": root_sid,
                       "task_type": "code_review", "operation_type": "GUARDRAIL"}
                f.write(json.dumps(rec, separators=(",", ":")) + "\n")
                f.write(json.dumps(dict(rec, operation_type="CHAT"), separators=(",", ":")) + "\n")

            with unittest.mock.patch.object(classifier_sub, 'call_llm') as mock_llm:
                mod._on_session_finalize(session_id=child_sid, platform='gateway', reason='shutdown')
                self.assertEqual(mock_llm.call_count, 0,
                                 'subagent inheritance must beat the LLM path via the boundary hook')

            child_marker = classifier_sub.MARKERS_DIR / f'{child_sid}.jsonl'
            self.assertTrue(child_marker.is_file())
            lines = child_marker.read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(lines), 2)
            recs = [json.loads(l) for l in lines]
            self.assertEqual({r['task_type'] for r in recs}, {'code_review'})
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_halt_gate_still_wins(self):
        """With guardrail-status.json halted, the boundary callback must write
        task_type=unclassified and never call the LLM."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-halt-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase29_halt_test'
            mod = _load_plugin_module(mod_name)
            classifier_sub = _classifier_submodule(mod_name)

            sid = 'halted-session-sid'
            guardrail_status_path = os.path.join(sd, 'guardrail-status.json')
            with open(guardrail_status_path, 'w', encoding='utf-8') as f:
                json.dump({"halted": True}, f)

            with unittest.mock.patch.object(classifier_sub, 'call_llm') as mock_llm:
                mod._on_session_finalize(session_id=sid, platform='gateway', reason='shutdown')
                self.assertEqual(mock_llm.call_count, 0,
                                 'call_llm must never be invoked while halted')

            marker_path = classifier_sub.MARKERS_DIR / f'{sid}.jsonl'
            self.assertTrue(marker_path.is_file())
            recs = [json.loads(l) for l in marker_path.read_text(encoding='utf-8').splitlines()]
            self.assertEqual({r['task_type'] for r in recs}, {'unclassified'})
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_sentinel_lands_when_classification_produces_nothing(self):
        """Even when run_classification returns normally after doing nothing
        useful, the sentinel must still be written — the cron's settle
        filter must not be left waiting."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-sentinel-noop-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        ready_dir = os.path.join(sd, 'markers', '.ready')
        prev_ready = os.environ.get('REVENIUM_MARKERS_READY_DIR')
        os.environ['REVENIUM_MARKERS_READY_DIR'] = ready_dir
        os.makedirs(ready_dir, mode=0o700, exist_ok=True)
        try:
            mod = _load_plugin_module('phase29_sentinel_noop_test')
            sid = 'sentinel-noop-sid'
            with unittest.mock.patch.object(mod, 'run_classification', return_value=None):
                mod._on_session_finalize(session_id=sid, platform='gateway', reason='shutdown')

            sentinel_path = os.path.join(ready_dir, sid)
            self.assertTrue(os.path.exists(sentinel_path),
                            'sentinel must be written even when classification produced nothing')
        finally:
            if prev_ready is None:
                os.environ.pop('REVENIUM_MARKERS_READY_DIR', None)
            else:
                os.environ['REVENIUM_MARKERS_READY_DIR'] = prev_ready
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)


class PostLlmCallRegistrationTests(unittest.TestCase):
    """Task 2 (HOOK-02) — proves _on_post_llm_call's signature contract,
    never-raise discipline, no-sentinel omission, and turn-content
    pass-through. Mirrors HookRegistrationTests' on_session_finalize cases."""

    def test_signature_has_confirmed_kwargs_no_completed_interrupted(self):
        """Runtime-signature assertion: _on_post_llm_call must accept all
        eight confirmed kwargs, must NOT declare completed or interrupted,
        and must carry a **kwargs (VAR_KEYWORD) parameter."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-postllm-sig-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod = _load_plugin_module('phase29_postllm_sig_test')
            params = inspect.signature(mod._on_post_llm_call).parameters
            expected = {
                'session_id', 'task_id', 'turn_id', 'user_message',
                'assistant_response', 'conversation_history', 'model', 'platform',
            }
            self.assertTrue(expected <= set(params),
                            f'missing confirmed kwargs: {expected - set(params)}')
            self.assertNotIn('completed', params)
            self.assertNotIn('interrupted', params)
            self.assertTrue(
                any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()),
                '_on_post_llm_call must declare a **kwargs parameter for forward compatibility',
            )
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_no_typeerror_for_full_confirmed_kwarg_set(self):
        """Invoking with the full confirmed production kwarg set must not
        raise TypeError."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-postllm-full-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase29_postllm_full_test'
            mod = _load_plugin_module(mod_name)
            classifier_sub = _classifier_submodule(mod_name)
            try:
                with unittest.mock.patch.object(classifier_sub, 'call_llm',
                                                 return_value=_llm_response('code_review')):
                    mod._on_post_llm_call(
                        session_id='postllm-full-sid',
                        task_id='task-1',
                        turn_id='turn-1',
                        user_message='please review src/foo.py',
                        assistant_response='reviewed and looks good',
                        conversation_history=[],
                        model='claude-x',
                        platform='gateway',
                    )
            except TypeError as exc:
                self.fail(f'_on_post_llm_call raised TypeError for the full confirmed kwarg set: {exc}')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_no_typeerror_for_unknown_extra_kwarg(self):
        """**kwargs must absorb any future payload field without raising."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-postllm-extrakwarg-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod = _load_plugin_module('phase29_postllm_extrakwarg_test')
            try:
                mod._on_post_llm_call(
                    session_id='postllm-extrakwarg-sid',
                    user_message='hi',
                    assistant_response='hello',
                    some_future_field='unexpected-value',
                )
            except TypeError as exc:
                self.fail(f'_on_post_llm_call raised TypeError for an unknown extra kwarg: {exc}')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_never_raises_on_none_session_id(self):
        """D-04 belt: a falsy session_id must return normally, no exception."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-postllm-nonesid-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod = _load_plugin_module('phase29_postllm_nonesid_test')
            try:
                result = mod._on_post_llm_call(session_id=None, user_message='hi', assistant_response='hello')
            except Exception as exc:
                self.fail(f'_on_post_llm_call raised for session_id=None: {exc}')
            self.assertIsNone(result)
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_never_raises_when_run_classification_raises(self):
        """D-04 belt: an exploding run_classification must be swallowed, not
        propagated."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-postllm-explode-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod = _load_plugin_module('phase29_postllm_explode_test')
            with unittest.mock.patch.object(mod, 'run_classification',
                                             side_effect=RuntimeError('boom from run_classification')):
                try:
                    mod._on_post_llm_call(
                        session_id='postllm-explode-sid',
                        user_message='hi',
                        assistant_response='hello',
                    )
                except Exception as exc:
                    self.fail(f'_on_post_llm_call raised when run_classification exploded: {exc}')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_no_sentinel_written(self):
        """_on_post_llm_call must NOT call _write_sentinel and must leave no
        sentinel file behind — this is behavioral (not a source grep), since
        the omission is explained by a comment rather than being enforceable
        via grep."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-postllm-nosentinel-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        ready_dir = os.path.join(sd, 'markers', '.ready')
        prev_ready = os.environ.get('REVENIUM_MARKERS_READY_DIR')
        os.environ['REVENIUM_MARKERS_READY_DIR'] = ready_dir
        os.makedirs(ready_dir, mode=0o700, exist_ok=True)
        try:
            mod_name = 'phase29_postllm_nosentinel_test'
            mod = _load_plugin_module(mod_name)
            classifier_sub = _classifier_submodule(mod_name)
            sid = 'postllm-nosentinel-sid'
            with unittest.mock.patch.object(mod, '_write_sentinel') as mock_sentinel, \
                 unittest.mock.patch.object(classifier_sub, 'call_llm',
                                            return_value=_llm_response('code_review')):
                mod._on_post_llm_call(
                    session_id=sid,
                    user_message='please review src/foo.py',
                    assistant_response='reviewed and looks good',
                )
                self.assertEqual(mock_sentinel.call_count, 0,
                                 '_on_post_llm_call must never call _write_sentinel')

            sentinel_path = os.path.join(ready_dir, sid)
            self.assertFalse(os.path.exists(sentinel_path),
                             'no sentinel file must exist after _on_post_llm_call')
        finally:
            if prev_ready is None:
                os.environ.pop('REVENIUM_MARKERS_READY_DIR', None)
            else:
                os.environ['REVENIUM_MARKERS_READY_DIR'] = prev_ready
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_passes_turn_content_through_as_message_and_response(self):
        """The callback's own user_message/assistant_response must reach
        run_classification as message/response, by equality — not by
        assertIn — so turn-1 classification does not depend on state.db
        persistence timing."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-postllm-passthrough-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod = _load_plugin_module('phase29_postllm_passthrough_test')
            with unittest.mock.patch.object(mod, 'run_classification') as mock_run:
                mod._on_post_llm_call(
                    session_id='postllm-passthrough-sid',
                    task_id='task-9',
                    turn_id='turn-9',
                    user_message='please review src/foo.py',
                    assistant_response='reviewed and looks good',
                    conversation_history=[{'role': 'user', 'content': 'x'}],
                    model='claude-x',
                    platform='gateway',
                )
            self.assertEqual(mock_run.call_count, 1)
            _, kwargs = mock_run.call_args
            self.assertEqual(kwargs['message'], 'please review src/foo.py')
            self.assertEqual(kwargs['response'], 'reviewed and looks good')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
