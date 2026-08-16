"""Phase 29 Plan 04 (HOOK-03 / HOOK-04) — proves "exactly one classification
per session" as a property of the pipeline, not of any one registered
trigger, across every trigger, every firing order, and real elapsed time.

Load-bearing test-design constraint (see 29-04-PLAN.md's
<assumption_delta_decision> and 29-VALIDATION.md): a test that fires two
triggers back to back in the same wall-clock second passes against the
*unfixed* 30-second recency window and proves nothing about the permanent
latch this plan promotes. Every dedup case below backdates the written
marker records' `ts` field by 120 seconds between the first classification
and any subsequent trigger, so each case genuinely exercises the
>30-seconds-elapsed path rather than the same-turn race the old gate was
built for.

Every case patches `_classify_via_llm` / `_infer_jobs_via_llm` on the
plugin's own `classifier` SUBMODULE (bound at `f'{mod_name}.classifier'` by
the relative import in __init__.py) — patching a bare `classifier` module
would not be seen by the plugin's own module-global references. See
tests/test_phase29_hook_registration.py's `_classifier_submodule` docstring
for the same idiom.
"""
import asyncio
import itertools
import json
import shutil
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

from tests.test_repository import _setup_plugin_env, _restore_plugin_env
from tests.test_phase29_hook_registration import (
    _load_plugin_module,
    _classifier_submodule,
)


def _backdate_markers(markers_dir, sid, seconds=120.0):
    """Rewrite every record's `ts` field in <markers_dir>/<sid>.jsonl to
    `seconds` earlier than its current value. Used to simulate real elapsed
    time between a turn-time classification and a later trigger, WITHOUT
    depending on which module-level name (time.time vs a marker's own ts)
    the implementation happens to read — this exercises the real file the
    real gate reads."""
    marker_path = Path(markers_dir) / f'{sid}.jsonl'
    if not marker_path.is_file():
        return
    lines = marker_path.read_text(encoding='utf-8').splitlines()
    new_lines = []
    for line in lines:
        rec = json.loads(line)
        if 'ts' in rec and isinstance(rec['ts'], (int, float)):
            rec['ts'] = rec['ts'] - seconds
        new_lines.append(json.dumps(rec, separators=(',', ':')))
    marker_path.write_text(
        '\n'.join(new_lines) + ('\n' if new_lines else ''), encoding='utf-8'
    )


def _fake_job(agentic_job_id='fix_bug', job_type='bug_fix', status='SUCCESS'):
    """A minimal dict that survives classifier._validate_job unchanged in shape
    (agentic_job_id, job_type, status — the three required keys)."""
    return {
        'agentic_job_id': agentic_job_id,
        'job_name': 'Fix bug',
        'job_type': job_type,
        'status': status,
    }


def _register(mod):
    """Register the plugin's hooks against a recording stub and return the
    {hook_name: callback} map. Used by every case below instead of naming
    hooks literally, per the trigger-set invariant this module proves."""
    registered = {}

    class StubCtx:
        def register_hook(self, name, cb):
            registered[name] = cb

    mod.register(StubCtx())
    return registered


def _kwargs_for_hook(name, sid):
    """Build the confirmed production kwarg set for one registered hook
    name, keyed off the hook's own real signature (not a shared shape)."""
    if name == 'on_session_end':
        return dict(session_id=sid, completed=True, interrupted=False,
                    model=None, platform='gateway')
    if name == 'on_session_finalize':
        return dict(session_id=sid, platform='gateway', reason='shutdown')
    if name == 'post_llm_call':
        return dict(
            session_id=sid, task_id='t1', turn_id='turn-1',
            user_message='please fix the bug', assistant_response='fixed the bug',
            conversation_history=[], model=None, platform='gateway',
        )
    if name == 'post_api_request':
        # Phase 32 (D-02): the fourth trigger, unrelated to the
        # classification pipeline this module proves dedup over (it calls
        # api_event_spool.spool_api_request, never _classify_via_llm) — its
        # inclusion here must leave every classify-count assertion in this
        # module unchanged, which is exactly what this companion invariant
        # test is designed to catch if that ever stops being true.
        now = time.time()
        return dict(
            session_id=sid, api_request_id=f'{sid}:task-1:turn-1:api:1',
            task_id='t1', turn_id='turn-1', platform='gateway',
            model='claude-sonnet-4-6', provider='anthropic',
            base_url='https://api.anthropic.com', api_mode='anthropic_messages',
            api_call_count=1, api_duration=1.234,
            started_at=now, ended_at=now + 1.234,
            finish_reason='stop', message_count=1,
            response_model='claude-sonnet-4-6',
            usage={'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150},
        )
    raise AssertionError(
        f'no kwarg builder registered for hook {name!r} — a fourth trigger '
        'was added without extending this test'
    )


class HookDedupTests(unittest.TestCase):

    def test_hook03_spend_does_not_scale_with_turn_count(self):
        """Case 1 (HOOK-03): N simulated turns for one session id produce
        exactly one _classify_via_llm invocation, and the total mocked-LLM
        call count is identical for N=1 and N=5 — spend does not grow with
        turn count."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-dedup-hook03-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase29_dedup_hook03_test'
            mod = _load_plugin_module(mod_name)
            classifier_sub = _classifier_submodule(mod_name)
            post_llm_call = _register(mod)['post_llm_call']

            totals = {}
            for n in (1, 5):
                sid = f'hook03-turncount-sid-n{n}'
                with unittest.mock.patch.object(
                        classifier_sub, '_classify_via_llm',
                        new_callable=unittest.mock.AsyncMock,
                        return_value='code_review') as mock_classify, \
                     unittest.mock.patch.object(
                        classifier_sub, '_infer_jobs_via_llm',
                        new_callable=unittest.mock.AsyncMock,
                        return_value=[_fake_job()]) as mock_infer, \
                     unittest.mock.patch.object(
                        classifier_sub, '_read_session_transcript',
                        return_value='user: fix the bug\nassistant: fixed it.'):
                    for i in range(n):
                        post_llm_call(
                            session_id=sid, task_id=f'task-{i}', turn_id=f'turn-{i}',
                            user_message='please fix the bug',
                            assistant_response='fixed the bug',
                            conversation_history=[], model=None, platform='gateway',
                        )
                        if i == 0:
                            _backdate_markers(classifier_sub.MARKERS_DIR, sid, seconds=120.0)

                    self.assertEqual(
                        mock_classify.call_count, 1,
                        f'N={n}: task classification must run exactly once across {n} turns')
                    totals[n] = mock_classify.call_count + mock_infer.call_count

            self.assertEqual(
                totals[1], totals[5],
                f'spend must not scale with turn count: N=1 total={totals[1]}, '
                f'N=5 total={totals[5]}')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_elapsed_time_case_fails_against_old_recency_gate(self):
        """Case 2: the fail-first proof for Task 1. A GUARDRAIL+CHAT pair
        timestamped 120 seconds in the past — well outside the OLD 30-second
        _recent_marker_pair_exists window, but still current for the
        promoted permanent latch — must gate Step 3. mock_classify.call_count
        must be a strict zero.

        Confirmed RED against the pre-promotion gate: reverting classifier.py
        to its pre-Task-1 state (`_recent_marker_pair_exists` as the Step 3
        gate) makes this case fail, because that gate returns False once
        `now - ts > 30`, so Steps 4-6 run again and call_classify fires a
        second time. See 29-04-SUMMARY.md for the recorded failure output
        from that swap.
        """
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-dedup-elapsed-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase29_dedup_elapsed_test'
            mod = _load_plugin_module(mod_name)
            classifier_sub = _classifier_submodule(mod_name)

            sid = 'elapsed-past-sid'
            classifier_sub.MARKERS_DIR.mkdir(parents=True, exist_ok=True)
            marker_path = classifier_sub.MARKERS_DIR / f'{sid}.jsonl'
            now = time.time()
            rec1 = {'muid': 'a' * 33, 'ts': now - 120.0, 'sid': sid,
                     'task_type': 'code_review', 'operation_type': 'GUARDRAIL'}
            rec2 = dict(rec1, muid='b' * 33, ts=now - 119.5, operation_type='CHAT')
            with open(marker_path, 'w', encoding='utf-8') as f:
                f.write(json.dumps(rec1, separators=(',', ':')) + '\n')
                f.write(json.dumps(rec2, separators=(',', ':')) + '\n')

            with unittest.mock.patch.object(
                    classifier_sub, '_classify_via_llm',
                    new_callable=unittest.mock.AsyncMock,
                    return_value='research') as mock_classify:
                asyncio.run(classifier_sub.run_classification_async(
                    session_id=sid,
                    message='a fresh unrelated question',
                    response='a fresh unrelated answer',
                ))

            self.assertEqual(
                mock_classify.call_count, 0,
                'a marker pair older than 30s must still gate Step 3 under the '
                'promoted permanent latch')
            recs = [json.loads(l) for l in marker_path.read_text(encoding='utf-8').splitlines()]
            op_recs = [r for r in recs if 'operation_type' in r]
            self.assertEqual(
                len(op_recs), 2,
                'no second task pair may be written for an already-classified session')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_hook04_turn_first_boundary_must_not_reclassify(self):
        """Case 3a (HOOK-04): turn-time classification wins. A boundary
        trigger arriving more than 30 seconds after a turn-time
        classification must not re-classify, and Step 7 job inference must
        still have produced exactly one kind:"job" record on the turn-time
        pass."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-dedup-hook04-turnfirst-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase29_dedup_hook04_turnfirst_test'
            mod = _load_plugin_module(mod_name)
            classifier_sub = _classifier_submodule(mod_name)
            registered = _register(mod)
            post_llm_call = registered['post_llm_call']
            on_session_finalize = registered['on_session_finalize']

            sid = 'hook04-turn-first-sid'
            with unittest.mock.patch.object(
                    classifier_sub, '_classify_via_llm',
                    new_callable=unittest.mock.AsyncMock,
                    return_value='code_review') as mock_classify, \
                 unittest.mock.patch.object(
                    classifier_sub, '_infer_jobs_via_llm',
                    new_callable=unittest.mock.AsyncMock,
                    return_value=[_fake_job()]), \
                 unittest.mock.patch.object(
                    classifier_sub, '_read_session_transcript',
                    return_value='user: fix the bug\nassistant: fixed it.'):
                post_llm_call(**_kwargs_for_hook('post_llm_call', sid))
                _backdate_markers(classifier_sub.MARKERS_DIR, sid, seconds=120.0)
                on_session_finalize(**_kwargs_for_hook('on_session_finalize', sid))

                self.assertEqual(
                    mock_classify.call_count, 1,
                    'the boundary hook must not re-classify after a turn-time '
                    'classification already ran')

            recs = [json.loads(l) for l in
                    (classifier_sub.MARKERS_DIR / f'{sid}.jsonl').read_text(encoding='utf-8').splitlines()]
            op_recs = [r for r in recs if 'operation_type' in r]
            job_recs = [r for r in recs if r.get('kind') == 'job']
            self.assertEqual(len(op_recs), 2, 'no second GUARDRAIL+CHAT pair')
            self.assertEqual(len(job_recs), 1, 'exactly one kind:"job" record')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_hook04_boundary_only_classifies_when_nothing_else_did(self):
        """Case 3b (HOOK-04): the boundary trigger DOES classify a session
        when it is the only trigger that ever fired."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-dedup-hook04-boundaryonly-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase29_dedup_hook04_boundaryonly_test'
            mod = _load_plugin_module(mod_name)
            classifier_sub = _classifier_submodule(mod_name)
            on_session_finalize = _register(mod)['on_session_finalize']

            sid = 'hook04-boundary-only-sid'
            with unittest.mock.patch.object(
                    classifier_sub, '_classify_via_llm',
                    new_callable=unittest.mock.AsyncMock,
                    return_value='planning') as mock_classify:
                on_session_finalize(**_kwargs_for_hook('on_session_finalize', sid))
                self.assertEqual(
                    mock_classify.call_count, 1,
                    'the boundary trigger must classify when nothing else did')
            marker_path = classifier_sub.MARKERS_DIR / f'{sid}.jsonl'
            self.assertTrue(marker_path.is_file())
            recs = [json.loads(l) for l in marker_path.read_text(encoding='utf-8').splitlines()]
            op_recs = [r for r in recs if 'operation_type' in r]
            self.assertEqual(len(op_recs), 2)
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_hook04_interrupted_turn1_still_classified_at_boundary(self):
        """Case 3c (HOOK-04): the case CONTEXT.md D-06 names as the boundary
        hook's reason to exist. Simulate the `if final_response and not
        interrupted:` upstream guard (agent/turn_finalizer.py) by simply
        never invoking post_llm_call for this session at all — the boundary
        hook must still classify it."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-dedup-hook04-interrupted-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase29_dedup_hook04_interrupted_test'
            mod = _load_plugin_module(mod_name)
            classifier_sub = _classifier_submodule(mod_name)
            on_session_finalize = _register(mod)['on_session_finalize']

            sid = 'hook04-interrupted-turn1-sid'
            with unittest.mock.patch.object(
                    classifier_sub, '_classify_via_llm',
                    new_callable=unittest.mock.AsyncMock,
                    return_value='debugging') as mock_classify:
                on_session_finalize(**_kwargs_for_hook('on_session_finalize', sid))
                self.assertEqual(
                    mock_classify.call_count, 1,
                    'a session whose turn 1 was interrupted must still be '
                    'classified at the session boundary')
            marker_path = classifier_sub.MARKERS_DIR / f'{sid}.jsonl'
            self.assertTrue(marker_path.is_file())
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_unclassified_latch_persists_across_triggers(self):
        """Case 4: a TRIVIAL_BLOCKLIST label validates to "unclassified", and
        that value is treated as classified for the session's lifetime — a
        subsequent trigger, even well past 30 seconds later, performs zero
        further classifications and the label stays "unclassified"."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-dedup-unclassified-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase29_dedup_unclassified_test'
            mod = _load_plugin_module(mod_name)
            classifier_sub = _classifier_submodule(mod_name)
            registered = _register(mod)
            post_llm_call = registered['post_llm_call']
            on_session_finalize = registered['on_session_finalize']

            sid = 'unclassified-latch-sid'
            with unittest.mock.patch.object(
                    classifier_sub, '_classify_via_llm',
                    new_callable=unittest.mock.AsyncMock,
                    return_value='greeting'):
                post_llm_call(
                    session_id=sid, task_id='t1', turn_id='turn-1',
                    user_message='hi', assistant_response='hello there',
                    conversation_history=[], model=None, platform='gateway',
                )

            self.assertEqual(
                classifier_sub._read_latest_task_type(sid), 'unclassified',
                'a TRIVIAL_BLOCKLIST label must validate to "unclassified"')

            _backdate_markers(classifier_sub.MARKERS_DIR, sid, seconds=120.0)

            with unittest.mock.patch.object(
                    classifier_sub, '_classify_via_llm',
                    new_callable=unittest.mock.AsyncMock,
                    return_value='code_review') as mock_classify_second:
                on_session_finalize(session_id=sid, platform='gateway', reason='shutdown')
                self.assertEqual(
                    mock_classify_second.call_count, 0,
                    'an already-unclassified session must not pay a second inference')

            self.assertEqual(
                classifier_sub._read_latest_task_type(sid), 'unclassified',
                '"unclassified" must persist as the session label for its lifetime')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_trigger_set_invariant_across_every_permutation(self):
        """Case 5 (companion invariant): discover the trigger set from the
        recorded registration map — never by naming hooks literally — and
        prove that every permutation of firing order yields exactly one task
        classification for one session id. Goes red the day a fourth trigger
        is registered without extending this test's kwarg builder."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-dedup-permutation-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase29_dedup_permutation_test'
            mod = _load_plugin_module(mod_name)
            classifier_sub = _classifier_submodule(mod_name)
            registered = _register(mod)

            self.assertGreaterEqual(
                len(registered), 3,
                'register(ctx) must bind at least three triggers for this '
                'invariant to be meaningful')

            items = sorted(registered.items())
            with unittest.mock.patch.object(
                    classifier_sub, '_classify_via_llm',
                    new_callable=unittest.mock.AsyncMock,
                    return_value='code_review') as mock_classify:
                for perm_idx, ordering in enumerate(itertools.permutations(items)):
                    sid = f'permutation-sid-{perm_idx}'
                    mock_classify.reset_mock()
                    for step, (name, callback) in enumerate(ordering):
                        callback(**_kwargs_for_hook(name, sid))
                        if step < len(ordering) - 1:
                            _backdate_markers(classifier_sub.MARKERS_DIR, sid, seconds=120.0)
                    self.assertEqual(
                        mock_classify.call_count, 1,
                        f'firing order {[n for n, _ in ordering]} must yield '
                        'exactly one classification')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_ledger_file_never_written_by_hook_paths(self):
        """Case 6: no code path any registered hook drives writes to
        revenium-hermes.ledger. HOOK-04 requires the cron's transaction-id
        contract to be unaffected by hook coverage, and the plugin has no
        ledger write path to begin with."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase29-dedup-ledger-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            mod_name = 'phase29_dedup_ledger_test'
            mod = _load_plugin_module(mod_name)
            classifier_sub = _classifier_submodule(mod_name)
            registered = _register(mod)

            with unittest.mock.patch.object(
                    classifier_sub, '_classify_via_llm',
                    new_callable=unittest.mock.AsyncMock,
                    return_value='code_review'):
                registered['post_llm_call'](
                    session_id='ledger-sid-1', user_message='hi', assistant_response='hello',
                )
                _backdate_markers(classifier_sub.MARKERS_DIR, 'ledger-sid-1', seconds=120.0)
                registered['on_session_finalize'](
                    session_id='ledger-sid-1', platform='gateway', reason='shutdown')
                registered['on_session_end'](
                    session_id='ledger-sid-2', completed=True, interrupted=False)

            ledger_path = Path(sd) / 'revenium-hermes.ledger'
            self.assertFalse(
                ledger_path.exists(),
                'no code path this plan touches may write revenium-hermes.ledger')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
