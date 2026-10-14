"""Regression tests for "a folded job ships CANCELLED and nothing says why"
(diagnosed on the `ent` profile, 2026-10-14, session 20261014_092806_53e18b: a
one-shot `hermes chat -Q` run with two goals, one folded job, shipped CANCELLED
with no value, and agent.log held no re-judge line at all).

What the evidence showed, and what is pinned here:

  1. The session-end hooks DID reach the re-judge. A one-shot run fires
     on_session_end after the turn and on_session_finalize after the transcript
     is flushed; in the incident both ran the classifier for seconds (the
     `markers/.ready/<sid>` sentinel was created at the end of the first and
     re-touched at the end of the second) and each made the re-judge's LLM call.
     "The trigger never ran" was the wrong reading. `SessionEndHooksReachTheRejudge`
     pins the real hook callbacks (`_on_session_end`, `_on_session_finalize`)
     through to the status-only call, the same-id marker, the sentinel, the
     REJUDGE_MAX_JOBS bound and the never-raise rule.

  2. A re-judge that moves nothing left no trace, so "ran and was told no" looked
     identical to "never ran". It now logs one INFO line per call with the
     verdicts it got, and a WARNING with the (escaped, truncated) model text when
     the answer holds no usable verdict. `RejudgeOutcomeIsVisibleTests`.

  3. The first pass never saw how the session ended. `_build_job_inference_prompt`
     cut the transcript with a bare `[:6000]` although the reader had sampled it
     head+tail (or, up to 8000 characters, returned it whole), so the last ~2000
     characters -- the final answer -- were dropped and the model, whose
     "uncertain" verdict is CANCELLED, said CANCELLED. In the incident the
     7958-character transcript lost its final 977-character answer. The same
     defect is why 186 of 271 long ent sessions came out CANCELLED at first
     pass against 10 of 28 short ones. `FirstPassSeesTheEndTests`.

Own isolated-import idiom (prefix `sendrj_pkg`): the module-scoped
`_LOAD_SEQ` / `_ENV_TOUCHED` / `_ENV_SAVED` globals, `setUpModule`,
`_restore_env`, `tearDownModule` and `_load_plugin` are DUPLICATED, not imported,
from tests/test_classifier_premature_cancel.py for the reason that module gives:
importing another module's copies would couple this one to its import-time env
mutation. `_load_plugin` also returns the PACKAGE, because the hook callbacks
live in its `__init__`.
"""
import contextlib
import importlib.util
import json
import logging
import os
import shutil
import sqlite3
import sys as _sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._compat_helpers import ROOT

PLUGIN_DIR = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'

_LOAD_SEQ = [0]
_ENV_TOUCHED = set()
_ENV_SAVED = {}
_ENV_KEYS = (
    'REVENIUM_STATE_DIR', 'REVENIUM_MARKERS_DIR', 'REVENIUM_CONFIG_FILE',
    'REVENIUM_TAXONOMY_FILE', 'REVENIUM_JOB_TAXONOMY_FILE', 'HERMES_HOME',
)


def setUpModule():
    for k in _ENV_KEYS:
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
    for cached in [k for k in list(_sys.modules) if k.startswith('sendrj_pkg')]:
        del _sys.modules[cached]


def _load_plugin(env=None):
    """Import the revenium-classifier plugin fresh; return (package, classifier,
    evaluators). The package carries the real Hermes hook callbacks."""
    for k, v in (env or {}).items():
        os.environ[k] = v
        _ENV_TOUCHED.add(k)
    _LOAD_SEQ[0] += 1
    name = f'sendrj_pkg_{_LOAD_SEQ[0]}'
    for cached in [k for k in _sys.modules if k.startswith('sendrj_pkg')]:
        del _sys.modules[cached]
    spec = importlib.util.spec_from_file_location(
        name, str(PLUGIN_DIR / '__init__.py'), submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    _sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod, _sys.modules[f'{name}.classifier'], _sys.modules[f'{name}.evaluators']


def _resp(content, model='gpt-5.6-sol'):
    """A call_llm return value with a REAL string `.model`."""
    r = mock.MagicMock()
    r.choices = [mock.MagicMock()]
    r.choices[0].message.content = content
    r.model = model
    return r


class _Calls:
    """A call_llm stand-in that serves `responses` in order and records every
    prompt. Out of responses it RAISES (not StopIteration, which asyncio.to_thread
    cannot deliver into its Future, so a regression making one call too many
    would hang the suite instead of failing)."""

    def __init__(self, responses):
        self.queue = list(responses)
        self.prompts = []

    def __call__(self, **kwargs):
        self.prompts.append(kwargs['messages'][-1]['content'])
        if not self.queue:
            raise RuntimeError('call_llm called more times than this trigger expects')
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _verdicts(*pairs):
    return json.dumps([{'index': i, 'status': s} for i, s in pairs])


def _read_jsonl(path):
    out = []
    if Path(path).is_file():
        for line in Path(path).read_text().splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


@contextlib.contextmanager
def _capture(level=logging.INFO):
    """Records the revenium_classifier logger emits, as LogRecords. Unlike
    assertLogs this tolerates a body that logs nothing, which several tests below
    assert on purpose."""
    lg = logging.getLogger('revenium_classifier')
    handler, prior = _Capture(), lg.level
    lg.addHandler(handler)
    lg.setLevel(level)
    try:
        yield handler.records
    finally:
        lg.removeHandler(handler)
        lg.setLevel(prior)


EVAL_PAYLOAD = {
    'economic_mechanism': 'labor_substitution', 'inferred_role': 'engineer',
    'estimated_hours_saved': 1.0, 'assumed_loaded_rate': 100.0, 'currency': 'USD',
    'basis': 'stub', 'confidence': 0.6,
}
EVAL_ON = {
    'enabled': True, 'evaluator': 'sendrj-stub', 'currency': 'USD',
    'experimentalReportEstimates': True, 'reportModelEstimates': True,
}
TRANSCRIPT = 'user: research and write a note\nassistant: done, both finished'
FOLDED_NAME = 'Research recent AI cost announcements (also: Draft Q4 agent budget check-in)'


class _Harness(unittest.TestCase):
    SID = 'sendrj-root-sid-0001'

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gsd-sendrj-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(_restore_env)
        self.hermes_home = os.path.join(self.tmp, 'hh')
        self.state_dir = os.path.join(self.hermes_home, 'state', 'revenium')
        self.markers_dir = os.path.join(self.state_dir, 'markers')
        self.ready_dir = os.path.join(self.markers_dir, '.ready')
        os.makedirs(self.markers_dir, mode=0o700)

    def _load(self, eval_cfg=EVAL_ON):
        cfg = {} if eval_cfg is None else {'llmOutcomeEvaluation': dict(eval_cfg)}
        with open(os.path.join(self.state_dir, 'config.json'), 'w') as f:
            json.dump(cfg, f)
        pkg, c, ev = _load_plugin({
            'HERMES_HOME': self.hermes_home, 'REVENIUM_STATE_DIR': self.state_dir})
        ev.register('sendrj-stub', lambda job, transcript, cfg: dict(EVAL_PAYLOAD))
        self.pkg, self.c = pkg, c
        return pkg, c

    def _marker_path(self, sid=None):
        return os.path.join(self.markers_dir, f'{sid or self.SID}.jsonl')

    def _job_markers(self, sid=None):
        return [r for r in _read_jsonl(self._marker_path(sid)) if r.get('kind') == 'job']

    def _sentinel(self, sid=None):
        return os.path.isfile(os.path.join(self.ready_dir, sid or self.SID))

    def _seed(self, jobs, sid=None):
        """A session the first pass already finished: its task pair, then `jobs`
        (dicts of agentic_job_id / job_name / status)."""
        sid = sid or self.SID
        records = [
            {'muid': f'm{op}', 'ts': 100.0, 'sid': sid, 'task_type': 'research',
             'operation_type': op, 'trace_id': sid}
            for op in ('GUARDRAIL', 'CHAT')
        ]
        for n, job in enumerate(jobs):
            records.append({
                'kind': 'job', 'ts': 110.0 + n, 'sid': sid,
                'agentic_job_id': job['agentic_job_id'],
                'job_name': job.get('job_name', FOLDED_NAME),
                'job_type': job.get('job_type', 'research'),
                'status': job.get('status', 'CANCELLED')})
        with open(self._marker_path(sid), 'w') as f:
            for rec in records:
                f.write(json.dumps(rec, separators=(',', ':')) + '\n')

    def _fire(self, hook, responses, transcript=TRANSCRIPT, sid=None):
        """Call the REAL plugin hook callback with call_llm and the transcript
        read stubbed. Returns the _Calls recorder."""
        sid = sid or self.SID
        calls = _Calls(responses)
        kwargs = {
            '_on_session_end': dict(session_id=sid, completed=True, interrupted=False,
                                    model='gpt-5.6-sol', platform='cli'),
            '_on_session_finalize': dict(session_id=sid, platform='cli', reason='shutdown'),
            '_on_post_llm_call': dict(session_id=sid, user_message='do both tasks',
                                      assistant_response='Both finished.',
                                      model='gpt-5.6-sol', platform='cli'),
        }[hook]
        with mock.patch.object(self.c, 'call_llm', side_effect=calls), \
             mock.patch.object(self.c, '_read_session_transcript', return_value=transcript):
            getattr(self.pkg, hook)(**kwargs)
        return calls


# ---------------------------------------------------------------------------
# 1. The session-end hooks reach the re-judge
# ---------------------------------------------------------------------------

class SessionEndHooksReachTheRejudge(_Harness):

    JOB = 'recent_ai_cost_announcements_7138'

    def _assert_rejudged_to_success(self, hook):
        self._load()
        self._seed([{'agentic_job_id': self.JOB}])
        calls = self._fire(hook, [_resp(_verdicts((1, 'SUCCESS')))])
        # ONE status-only call; the registered stub evaluator values the SUCCESS
        # without another LLM call.
        self.assertEqual(len(calls.prompts), 1, calls.prompts)
        self.assertIn('re-checking task arcs', calls.prompts[0])
        self.assertIn(FOLDED_NAME, calls.prompts[0])
        after = self._job_markers()
        self.assertEqual([r['status'] for r in after], ['CANCELLED', 'SUCCESS'])
        # The SAME job: a re-judge never mints an id (a new id is a new Revenium job).
        self.assertEqual({r['agentic_job_id'] for r in after}, {self.JOB})
        self.assertEqual({r['job_name'] for r in after}, {FOLDED_NAME})
        # The re-judged SUCCESS is valued exactly like a first-pass SUCCESS.
        self.assertIn('assessment', after[-1])
        # The hook still signals completion to the cron.
        self.assertTrue(self._sentinel())

    def test_on_session_end_rejudges_a_cancelled_root_job(self):
        self._assert_rejudged_to_success('_on_session_end')

    def test_on_session_finalize_rejudges_a_cancelled_root_job(self):
        self._assert_rejudged_to_success('_on_session_finalize')

    def test_the_oneshot_sequence_rejudges_at_both_session_end_hooks(self):
        """The incident's shape, in order: the first pass writes CANCELLED from
        post_llm_call, on_session_end re-judges (the model is still unsure),
        on_session_finalize re-judges again against the flushed transcript and
        finds SUCCESS. Neither hook runs task classification or job inference
        again, and no second job appears."""
        self._load()
        first = self._fire('_on_post_llm_call', [
            _resp('research_note_drafting'),
            _resp(json.dumps([{'agentic_job_id': 'recent_ai_cost_announcements',
                               'job_name': 'Research recent AI cost announcements',
                               'job_type': 'research', 'status': 'CANCELLED'}]))])
        self.assertEqual(len(first.prompts), 2, 'one task call + one job-inference call')
        [job] = self._job_markers()
        self.assertEqual(job['status'], 'CANCELLED')
        self.assertFalse(self._sentinel(), 'post_llm_call never writes the sentinel')

        ended = self._fire('_on_session_end', [_resp(_verdicts((1, 'CANCELLED')))])
        self.assertEqual(len(ended.prompts), 1)
        self.assertIn('re-checking task arcs', ended.prompts[0])
        self.assertEqual([r['status'] for r in self._job_markers()], ['CANCELLED'])
        self.assertTrue(self._sentinel())

        finalized = self._fire('_on_session_finalize', [_resp(_verdicts((1, 'SUCCESS')))])
        self.assertEqual(len(finalized.prompts), 1)
        after = self._job_markers()
        self.assertEqual([r['status'] for r in after], ['CANCELLED', 'SUCCESS'])
        self.assertEqual({r['agentic_job_id'] for r in after}, {job['agentic_job_id']})

    def test_a_session_still_cancelled_is_rejudged_at_each_session_end_hook(self):
        """'At least once' at session end, whatever the model says: each hook
        spends exactly one status-only call and appends nothing."""
        self._load()
        self._seed([{'agentic_job_id': self.JOB}])
        for hook in ('_on_session_end', '_on_session_finalize'):
            calls = self._fire(hook, [_resp(_verdicts((1, 'CANCELLED')))])
            self.assertEqual(len(calls.prompts), 1, hook)
        self.assertEqual([r['status'] for r in self._job_markers()], ['CANCELLED'])

    def test_a_success_or_failed_job_costs_the_session_end_hooks_nothing(self):
        self._load()
        self._seed([{'agentic_job_id': 'done_job_ab12', 'status': 'SUCCESS'},
                    {'agentic_job_id': 'broke_job_cd34', 'status': 'FAILED'}])
        for hook in ('_on_session_end', '_on_session_finalize'):
            self.assertEqual(self._fire(hook, []).prompts, [], hook)

    def test_the_guardrail_halt_cancel_is_not_rejudged_at_session_end(self):
        self._load()
        self._seed([{'agentic_job_id': 'guardrail-halt-ab12', 'job_name': 'Halted',
                     'job_type': 'guardrail_halt'}])
        for hook in ('_on_session_end', '_on_session_finalize'):
            self.assertEqual(self._fire(hook, []).prompts, [], hook)

    def test_at_most_rejudge_max_jobs_are_checked_per_hook(self):
        pkg, c = self._load()
        count = c.REJUDGE_MAX_JOBS + 3
        self._seed([{'agentic_job_id': f'job_number_{n:02d}_ab12',
                     'job_name': f'Job number {n:02d}'} for n in range(count)])
        calls = self._fire('_on_session_finalize', [_resp(_verdicts())])
        self.assertEqual(len(calls.prompts), 1)
        arcs = calls.prompts[0].split('Arcs to re-check:')[1].split('Output ONLY')[0]
        self.assertEqual(arcs.count('(type:'), c.REJUDGE_MAX_JOBS)

    def test_a_subagent_session_does_not_rejudge_its_roots_job(self):
        """Only the root session's own hooks re-judge: a delegated child's
        finalize must not."""
        self._load()
        self._seed([{'agentic_job_id': self.JOB}])
        child = 'sendrj-child-sid-0002'
        db = sqlite3.connect(os.path.join(self.hermes_home, 'state.db'))
        db.execute('CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT)')
        db.executemany('INSERT INTO sessions VALUES (?, ?)',
                       [(self.SID, None), (child, self.SID)])
        db.commit()
        db.close()
        # The child inherits the root's task label (no LLM call) and never re-judges.
        calls = self._fire('_on_session_finalize', [], sid=child)
        self.assertEqual(calls.prompts, [])
        self.assertEqual([r['status'] for r in self._job_markers()], ['CANCELLED'])

    def test_a_failing_llm_never_escapes_a_session_end_hook(self):
        self._load()
        self._seed([{'agentic_job_id': self.JOB}])
        for hook in ('_on_session_end', '_on_session_finalize'):
            calls = self._fire(hook, [RuntimeError('provider is down')])
            self.assertEqual(len(calls.prompts), 1, hook)
            self.assertTrue(self._sentinel(), hook)
        self.assertEqual([r['status'] for r in self._job_markers()], ['CANCELLED'])


# ---------------------------------------------------------------------------
# 2. A re-judge that moves nothing says so
# ---------------------------------------------------------------------------

class RejudgeOutcomeIsVisibleTests(_Harness):

    JOB = 'recent_ai_cost_announcements_7138'

    def _lines(self, records, needle):
        return [r.getMessage() for r in records if needle in r.getMessage()]

    def test_each_session_end_hook_logs_what_its_rejudge_found(self):
        self._load()
        self._seed([{'agentic_job_id': self.JOB}])
        with _capture() as records:
            self._fire('_on_session_end', [_resp(_verdicts((1, 'CANCELLED')))])
            self._fire('_on_session_finalize', [_resp(_verdicts((1, 'CANCELLED')))])
        lines = self._lines(records, 'job re-judge for sid=')
        self.assertEqual(lines, [
            f'revenium-classifier: job re-judge for sid={self.SID} checked 1 job(s), '
            'verdicts: 1=CANCELLED'] * 2)

    def test_a_moved_status_is_logged_with_its_verdict(self):
        self._load()
        self._seed([{'agentic_job_id': self.JOB}])
        with _capture() as records:
            self._fire('_on_session_finalize', [_resp(_verdicts((1, 'SUCCESS')))])
        self.assertEqual(
            self._lines(records, 'job re-judge for sid='),
            [f'revenium-classifier: job re-judge for sid={self.SID} checked 1 job(s), '
             'verdicts: 1=SUCCESS'])

    def test_an_unusable_answer_warns_with_the_escaped_model_text(self):
        """The raw text is untrusted: %r keeps a newline from forging a second
        log record (T-28-07), and it is cut short."""
        self._load()
        self._seed([{'agentic_job_id': self.JOB}])
        hostile = 'Probably done.\n[ERROR] revenium-classifier: forged record'
        with _capture() as records:
            self._fire('_on_session_finalize', [_resp(hostile)])
        [warning] = [r for r in records if r.levelno == logging.WARNING]
        msg = warning.getMessage()
        self.assertIn('job re-judge response had no usable verdict for 1 arc(s)', msg)
        self.assertIn('(finish_reason=unknown)', msg, 'a mock carries no real finish_reason')
        self.assertIn(repr(hostile), msg)
        self.assertNotIn('\n', msg)
        self.assertEqual(
            self._lines(records, 'job re-judge for sid='),
            [f'revenium-classifier: job re-judge for sid={self.SID} checked 1 job(s), '
             'verdicts: none'])
        self.assertEqual([r['status'] for r in self._job_markers()], ['CANCELLED'])

    def test_an_empty_answer_warns(self):
        self._load()
        self._seed([{'agentic_job_id': self.JOB}])
        with _capture() as records:
            self._fire('_on_session_end', [_resp('')])
        [warning] = [r for r in records if r.levelno == logging.WARNING]
        self.assertIn("for 1 arc(s) (finish_reason=unknown): ''", warning.getMessage())

    def test_a_cut_off_answer_says_so(self):
        """An empty answer that hit max_tokens (a reasoning model spending the
        whole budget thinking) must be tellable from one that stopped by itself."""
        self._load()
        self._seed([{'agentic_job_id': self.JOB}])
        cut_off = _resp('')
        cut_off.choices[0].finish_reason = 'length'
        with _capture() as records:
            self._fire('_on_session_end', [cut_off])
        [warning] = [r for r in records if r.levelno == logging.WARNING]
        self.assertIn("(finish_reason=length): ''", warning.getMessage())

    def test_the_logged_model_text_is_bounded(self):
        self._load()
        self._seed([{'agentic_job_id': self.JOB}])
        with _capture() as records:
            self._fire('_on_session_end', [_resp('x' * 5000)])
        [warning] = [r for r in records if r.levelno == logging.WARNING]
        msg = warning.getMessage()
        self.assertIn('x' * 200, msg)
        self.assertNotIn('x' * 201, msg)

    def test_a_usable_verdict_raises_no_warning(self):
        self._load()
        self._seed([{'agentic_job_id': self.JOB}])
        with _capture() as records:
            self._fire('_on_session_end', [_resp(_verdicts((1, 'CANCELLED')))])
        self.assertEqual([r for r in records if r.levelno >= logging.WARNING], [])

    def test_a_trigger_with_nothing_to_rejudge_logs_no_rejudge_line(self):
        self._load()
        self._seed([{'agentic_job_id': 'done_job_ab12', 'status': 'SUCCESS'}])
        with _capture() as records:
            self._fire('_on_session_finalize', [])
        self.assertEqual(self._lines(records, 'job re-judge'), [])


# ---------------------------------------------------------------------------
# 3. The first pass sees how the session ended
# ---------------------------------------------------------------------------

FINAL_ANSWER = 'FINAL_ANSWER_MARKER Both finished. ' + 'delivered summary text ' * 40
OPENING_REQUEST = 'OPENING_REQUEST_MARKER Two separate tasks, do both: research and write.'


def _incident_shaped_messages():
    """A transcript shaped like the incident's: it fits the reader's 8000-char
    budget (so it comes back WHOLE, unsampled), exceeds the prompt's 6000, and
    ends in a long final answer that the old head-only cut dropped."""
    rows = [('user', OPENING_REQUEST)]
    rows += [('tool', ('tool result %02d ' % n) + 'x' * 600) for n in range(13)]
    rows.append(('assistant', FINAL_ANSWER))
    return rows


class FirstPassSeesTheEndTests(_Harness):

    def _state_db(self, rows):
        db = sqlite3.connect(os.path.join(self.hermes_home, 'state.db'))
        db.execute('CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, '
                   'role TEXT, content TEXT, timestamp REAL)')
        for n, (role, content) in enumerate(rows):
            db.execute('INSERT INTO messages (session_id, role, content, timestamp) '
                       'VALUES (?, ?, ?, ?)', (self.SID, role, content, float(n)))
        db.commit()
        db.close()

    def test_the_fixture_has_the_incident_shape(self):
        """Guards the test below against drifting into a shape that never
        exercised the defect: whole-returned by the reader, longer than the
        prompt's budget, final answer past character 6000."""
        _pkg, c = self._load()
        self._state_db(_incident_shaped_messages())
        text = c._read_session_transcript(self.SID)
        self.assertGreater(len(text), 6000)
        self.assertLessEqual(len(text), 8000)
        self.assertNotIn('truncated', text, 'the reader returned it whole')
        self.assertGreater(text.index('FINAL_ANSWER_MARKER'), 6000)

    def test_the_first_pass_prompt_carries_the_final_answer(self):
        """End to end with the REAL transcript reader: the job-inference prompt
        the model receives holds the opening request AND the final answer."""
        _pkg, c = self._load()
        self._state_db(_incident_shaped_messages())
        calls = _Calls([_resp('research_note_drafting'), _resp('[]')])
        with mock.patch.object(c, 'call_llm', side_effect=calls):
            import asyncio
            asyncio.run(c.run_classification_async(
                session_id=self.SID, message='do both', response='Both finished.'))
        self.assertEqual(len(calls.prompts), 2)
        prompt = calls.prompts[1]
        self.assertIn('Session transcript:', prompt)
        self.assertIn('OPENING_REQUEST_MARKER', prompt)
        self.assertIn('FINAL_ANSWER_MARKER', prompt)
        self.assertIn('transcript truncated', prompt)
        body = prompt.split('Session transcript:\n')[1].rsplit('\n\nJSON array:', 1)[0]
        self.assertLessEqual(len(body), 6000)

    def test_a_transcript_within_the_budget_is_passed_through_untouched(self):
        _pkg, c = self._load()
        transcript = 'user: hello\nassistant: ' + 'a' * 5000
        prompt = c._build_job_inference_prompt(transcript, [])
        self.assertIn(transcript, prompt)
        self.assertNotIn('transcript truncated', prompt)

    def test_clip_head_tail_keeps_both_ends_and_the_larger_share_of_the_tail(self):
        _pkg, c = self._load()
        text = 'H' * 5000 + 'M' * 5000 + 'T' * 5000
        clipped = c._clip_head_tail(text, 6000)
        self.assertLessEqual(len(clipped), 6000)
        head, tail = clipped.split(c._TRANSCRIPT_ELISION_MARKER)
        self.assertTrue(head and set(head) == {'H'})
        self.assertTrue(tail and set(tail) == {'T'})
        self.assertGreater(len(tail), len(head))
        self.assertEqual(len(head) + len(c._TRANSCRIPT_ELISION_MARKER) + len(tail), 6000)

    def test_clip_head_tail_is_the_cut_the_rejudge_prompt_always_used(self):
        """Folding the re-judge's inline cut into the shared helper must not move
        a character of what it sends."""
        _pkg, c = self._load()
        limit = c._REJUDGE_TRANSCRIPT_CHARS
        marker = '\n... [transcript truncated — middle omitted] ...\n'
        for size in (limit, limit + 1, limit + 500, 9000, 20000):
            text = ''.join(chr(65 + (n % 26)) for n in range(size))
            budget = max(0, limit - len(marker))
            head = budget // 3
            old = text if size <= limit else text[:head] + marker + text[len(text) - (budget - head):]
            with self.subTest(size=size):
                self.assertEqual(c._clip_head_tail(text, limit), old)

    def test_clip_head_tail_tolerates_degenerate_input(self):
        _pkg, c = self._load()
        self.assertEqual(c._clip_head_tail('', 6000), '')
        self.assertEqual(c._clip_head_tail(None, 6000), '')
        # A limit smaller than the marker still returns a bounded string, no raise.
        out = c._clip_head_tail('z' * 100, 10)
        self.assertEqual(out, c._TRANSCRIPT_ELISION_MARKER)



# ---------------------------------------------------------------------------
# 4. The last answer is read whole (ent, 2026-10-14, 20261014_153448_cd754a)
# ---------------------------------------------------------------------------

# Shaped like the incident's final answer: three linked bullets in ~1000
# characters, the third bullet past character 500.
THREE_BULLETS = (
    'Research - three most recent verified announcements: '
    + ''.join('- BULLET_%d %s https://example.com/post-%d ' % (n, 'detail ' * 40, n)
              for n in (1, 2, 3))
)


class FinalAnswerIsReadWholeTests(_Harness):
    """The reader cut every message to 500 characters, the delivered answer
    included, so a re-judge saw two of three bullets and a half link and said
    FAILED. The last assistant message now keeps _FINAL_ASSISTANT_MSG_CHARS."""

    _state_db = FirstPassSeesTheEndTests._state_db

    def _rows(self, final=THREE_BULLETS, filler=13):
        rows = [('user', OPENING_REQUEST)]
        rows += [('assistant', 'EARLY_ASSISTANT ' + 'e' * 900)]
        rows += [('tool', ('tool result %02d ' % n) + 'x' * 600) for n in range(filler)]
        rows.append(('assistant', final))
        return rows

    def test_fixture_puts_the_third_bullet_past_the_per_message_cap(self):
        self.assertGreater(THREE_BULLETS.index('BULLET_3'), 500)
        self.assertLess(len(THREE_BULLETS), 2500)

    def test_the_reader_keeps_the_whole_last_answer(self):
        _pkg, c = self._load()
        self._state_db(self._rows())
        text = c._read_session_transcript(self.SID)
        self.assertIn('assistant: ' + THREE_BULLETS, text)

    def test_only_the_last_assistant_message_gets_the_larger_cap(self):
        _pkg, c = self._load()
        self._state_db(self._rows(filler=2))
        text = c._read_session_transcript(self.SID)
        self.assertIn('assistant: EARLY_ASSISTANT ' + 'e' * (500 - 16) + '\n', text)
        self.assertNotIn('e' * 501, text)
        for line in text.split('\n'):
            if line.startswith('tool: '):
                self.assertLessEqual(len(line), len('tool: ') + 500)

    def test_the_last_answer_is_still_bounded(self):
        _pkg, c = self._load()
        self._state_db(self._rows(final='F' * 9000, filler=0))
        text = c._read_session_transcript(self.SID)
        self.assertIn('assistant: ' + 'F' * c._FINAL_ASSISTANT_MSG_CHARS, text)
        self.assertNotIn('F' * (c._FINAL_ASSISTANT_MSG_CHARS + 1), text)

    def test_the_rejudge_budget_keeps_the_whole_last_answer(self):
        """The re-judge reads at 6000 through the head+tail sampler; a long
        session must still hand it all three bullets."""
        _pkg, c = self._load()
        self._state_db(self._rows(filler=30))
        text = c._read_session_transcript(self.SID, max_chars=c._REJUDGE_TRANSCRIPT_CHARS)
        self.assertIn('transcript truncated', text)
        self.assertLessEqual(len(text), c._REJUDGE_TRANSCRIPT_CHARS)
        self.assertIn(THREE_BULLETS, c._build_rejudge_prompt(text, [
            {'agentic_job_id': 'j_1', 'job_name': 'Research', 'job_type': 'research'}]))

    def test_the_first_pass_prompt_keeps_the_whole_last_answer(self):
        _pkg, c = self._load()
        self._state_db(self._rows(filler=30))
        prompt = c._build_job_inference_prompt(c._read_session_transcript(self.SID), [])
        self.assertIn('BULLET_3', prompt)
        self.assertIn(THREE_BULLETS, prompt)

    def test_the_evaluator_prompt_keeps_the_end_of_the_session(self):
        _pkg, c = self._load()
        transcript = 'user: OPENING\n' + 'm' * 9000 + '\nassistant: ' + THREE_BULLETS
        prompt = c._build_outcome_evaluation_prompt(
            {'job_type': 'research', 'job_name': 'Research'}, transcript, {})
        self.assertIn('OPENING', prompt)
        self.assertIn(THREE_BULLETS, prompt)
        self.assertNotIn('m' * 6000, prompt)



# ---------------------------------------------------------------------------
# 5. A failed task-label call is retried, not latched (ent, 2026-10-14,
#    20261014_165924_2f9664: the label call timed out, the session was written
#    "unclassified" for good, and the job call seven seconds later succeeded)
# ---------------------------------------------------------------------------

JOB_SUCCESS = json.dumps([{'agentic_job_id': 'recent_ai_cost_announcements',
                           'job_name': 'Research recent AI cost announcements',
                           'job_type': 'research', 'status': 'SUCCESS'}])


class FailedLabelCallIsRetriedTests(_Harness):

    def _task_markers(self):
        return [r for r in _read_jsonl(self._marker_path()) if r.get('kind') != 'job']

    def test_a_failed_label_call_writes_nothing_and_skips_job_inference(self):
        self._load()
        with _capture(logging.WARNING) as records:
            calls = self._fire('_on_post_llm_call', [TimeoutError('no output within 20s')])
        self.assertEqual(len(calls.prompts), 1, 'no job-inference call after a failed label call')
        self.assertEqual(_read_jsonl(self._marker_path()), [], 'no task pair, no job marker')
        self.assertTrue(any('writing nothing so a later trigger retries' in r.getMessage()
                            for r in records))

    def test_the_next_trigger_classifies_and_infers_the_job(self):
        """The incident's sequence with the fix: post_llm_call's label call
        fails, on_session_end retries and writes the real label, then the job."""
        self._load()
        self._fire('_on_post_llm_call', [ConnectionError('Connection error.')])
        ended = self._fire('_on_session_end', [_resp('llm_spend_research_note'), _resp(JOB_SUCCESS)])
        self.assertEqual(len(ended.prompts), 2)
        self.assertEqual([r['task_type'] for r in self._task_markers()],
                         ['llm_spend_research_note'] * 2)
        [job] = self._job_markers()
        self.assertEqual(job['status'], 'SUCCESS')
        lines = _read_jsonl(self._marker_path())
        self.assertNotEqual(lines[0].get('kind'), 'job', 'the task pair sits above the job')
        self.assertTrue(self._sentinel())

    def test_every_trigger_failing_leaves_the_session_markerless(self):
        """If no trigger ever reaches the model the session ships markerless,
        which the reporter labels "unclassified": the old outcome, not a worse one."""
        self._load()
        for hook in ('_on_post_llm_call', '_on_session_end', '_on_session_finalize'):
            self._fire(hook, [ConnectionError('Connection error.')])
        self.assertEqual(_read_jsonl(self._marker_path()), [])
        self.assertTrue(self._sentinel(), 'the session-end hooks still release the reporter')

    def test_an_invalid_label_still_writes_unclassified_and_latches(self):
        """Only a failed CALL is retried. A model that answered with a label the
        validator rejects keeps today's behaviour: "unclassified", once."""
        self._load()
        self._fire('_on_post_llm_call', [_resp('Hello there!'), _resp('[]')])
        self.assertEqual([r['task_type'] for r in self._task_markers()], ['unclassified'] * 2)
        again = self._fire('_on_session_end', [_resp('[]')])
        self.assertEqual(len(again.prompts), 1, 'no second label call: the session is latched')
        self.assertEqual(len(self._task_markers()), 2)

    def test_the_failure_sentinel_can_never_be_written_as_a_label(self):
        _pkg, c = self._load()
        self.assertIsNone(c.LABEL_RE.match(c.CLASSIFY_CALL_FAILED))
        self.assertEqual(c._validate_label(c.CLASSIFY_CALL_FAILED), 'unclassified')

    def test_the_label_call_gets_the_job_calls_twenty_second_budget(self):
        _pkg, c = self._load()
        seen = {}

        def fake(**kwargs):
            seen.update(kwargs)
            return _resp('code_review')

        import asyncio
        with mock.patch.object(c, 'call_llm', side_effect=fake):
            out = asyncio.run(c._classify_via_llm({'message': 'm'}, 'r', labels=[]))
        self.assertEqual(out, 'code_review')
        self.assertEqual(seen['timeout'], 20.0)
        self.assertEqual(c._CLASSIFY_TIMEOUT_SECONDS, 20.0)

    def test_classify_via_llm_reports_a_failed_call_distinctly(self):
        _pkg, c = self._load()
        import asyncio
        with mock.patch.object(c, 'call_llm', side_effect=RuntimeError('down')):
            out = asyncio.run(c._classify_via_llm({'message': 'm'}, 'r', labels=[]))
        self.assertEqual(out, c.CLASSIFY_CALL_FAILED)

    def test_no_llm_client_still_writes_unclassified(self):
        """call_llm is None means Hermes has no auxiliary client at all: a
        standing condition, not a transient one, so it keeps writing
        "unclassified" rather than retrying on every turn."""
        _pkg, c = self._load()
        import asyncio
        with mock.patch.object(c, 'call_llm', None):
            out = asyncio.run(c._classify_via_llm({'message': 'm'}, 'r', labels=[]))
        self.assertEqual(out, 'unclassified')


if __name__ == '__main__':
    unittest.main()
