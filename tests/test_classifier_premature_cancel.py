"""Regression tests for the premature-CANCELLED job verdict (diagnosed on the
`ent` profile, 2026-10-10).

The defect: `run_classification_async` Step 7 gated job inference on
`not _job_marker_exists(session_id)`, a permanent per-session latch, and Step 7
runs from `post_llm_call`, i.e. mid-session. The first turn's transcript
therefore decided the job's status for good, and the job prompt makes CANCELLED
the "uncertain" catch-all, so an arc that was merely still running was written
CANCELLED seconds in, while a subagent was still doing the work. Nothing ever
re-judged it. The reporter's open-session hold (job-lifecycle-phantom-jobs RC-3)
kept it PENDING only while the session stayed open; once the session ended it
shipped CANCELLED, and CANCELLED arcs are never evaluated, so the job never got
a value.

The fix has three parts, each pinned below:

  1. Classifier -- a CANCELLED verdict is re-judged on later triggers, against
     the full transcript as it then stands. The job id, name and type never
     change (a new id would be a new job). SUCCESS and FAILED stay latched, the
     guardrail-halt cancel is a real cancellation and is never re-judged, and
     the cost is at most one status-only LLM call per trigger, ending the
     moment the status leaves CANCELLED.
  2. Reporter -- with two markers for one job id the LATEST wins (marker ts,
     tie -> file order). Before, the first (CANCELLED) queue entry was reported
     and ledgered and the later SUCCESS was ignored for good.
  3. Sidecar -- the valued assessment a re-judged SUCCESS writes is the one the
     reporter reads (last-match-wins over the abstention the CANCELLED pass
     left), and an operator correction is never superseded by it.

Own isolated-import idiom: the module-scoped `_LOAD_SEQ` / `_ENV_TOUCHED` /
`_ENV_SAVED` globals, `setUpModule`, `_restore_env`, `tearDownModule` and
`_load_classifier` below are DUPLICATED, not imported, from
tests/test_phase47_end_to_end.py. Importing that module's copies would couple
this one to its import-time env mutation: `_restore_env` is also called from
each test's own cleanup because a REVENIUM_STATE_DIR left pointing at an
already-deleted tmpdir silently breaks every later class in the same
`unittest discover` process. This module's prefix is `pcancel_pkg`, distinct
from every other module's, so sys.modules keys cannot collide.
"""
import asyncio
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys as _sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests._compat_helpers import (
    argv_to_flags,
    build_shim,
    build_state_db,
    ROOT,
    SCRIPTS_DIR,
)
# Module imports, not class imports: a TestCase class bound at module level is
# collected and re-run by unittest discovery.
from tests import test_job_lifecycle_phantom_jobs as lc
from tests import test_phase38_reporter_path as p38

PLUGIN_DIR = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'
SKILL_DIR = ROOT / 'skills' / 'revenium'

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
    for cached in [k for k in list(_sys.modules) if k.startswith('pcancel_pkg')]:
        del _sys.modules[cached]


def _load_classifier(env=None):
    """Import the revenium-classifier plugin fresh; return (classifier, evaluators)."""
    for k, v in (env or {}).items():
        os.environ[k] = v
        _ENV_TOUCHED.add(k)
    _LOAD_SEQ[0] += 1
    name = f'pcancel_pkg_{_LOAD_SEQ[0]}'
    for cached in [k for k in _sys.modules if k.startswith('pcancel_pkg')]:
        del _sys.modules[cached]
    spec = importlib.util.spec_from_file_location(
        name, str(PLUGIN_DIR / '__init__.py'), submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    _sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return _sys.modules[f'{name}.classifier'], _sys.modules[f'{name}.evaluators']


def _resp(content, model='claude-sonnet-4-6'):
    """A call_llm return value: `.choices[0].message.content`, plus a REAL
    string `.model` (a MagicMock auto-attribute would not survive
    _resolve_served_model)."""
    r = mock.MagicMock()
    r.choices = [mock.MagicMock()]
    r.choices[0].message.content = content
    r.model = model
    return r


def _llm_patch(c, responses):
    """Patch `c.call_llm` to return `responses` in order.

    NOT a bare side_effect=list: an exhausted list raises StopIteration, which
    asyncio.to_thread cannot deliver into its Future -- the awaiting coroutine
    then hangs forever, so a regression that makes one call too many would stall
    the whole suite instead of failing the test. A RuntimeError is caught by the
    classifier, logged, and left for the call_count assertion.
    """
    queue = list(responses)

    def next_response(**kwargs):
        if not queue:
            raise RuntimeError('call_llm called more times than this trigger expects')
        return queue.pop(0)

    return mock.patch.object(c, 'call_llm', side_effect=next_response)


def _job(label='write_and_verify_report', status='CANCELLED', job_type='documentation',
         name='Write and verify the report', **extra):
    return {'agentic_job_id': label, 'job_name': name, 'job_type': job_type,
            'status': status, **extra}


def _verdicts(*pairs):
    """A re-judge response body: `_verdicts((1, 'SUCCESS'), (2, 'CANCELLED'))`."""
    out = []
    for idx, status in pairs:
        rec = {'index': idx, 'status': status}
        out.append(rec)
    return json.dumps(out)


EVAL_PAYLOAD = {
    'economic_mechanism': 'labor_substitution', 'inferred_role': 'engineer',
    'estimated_hours_saved': 1.0, 'assumed_loaded_rate': 100.0, 'currency': 'USD',
    'basis': 'stub', 'confidence': 0.6,
}
TRANSCRIPT = 'user: write the report\nassistant: delegating\ntool: subagent wrote and verified it'

# The opt-ins under which a MODEL_ESTIMATED_DEMO value is reportable.
EVAL_ON = {
    'enabled': True, 'evaluator': 'pcancel-stub', 'currency': 'USD',
    'experimentalReportEstimates': True, 'reportModelEstimates': True,
}


def _read_jsonl(path):
    out = []
    if not Path(path).is_file():
        return out
    for line in Path(path).read_text().splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


# ---------------------------------------------------------------------------
# Part 1 -- the classifier
# ---------------------------------------------------------------------------

class _ClassifierHarness(unittest.TestCase):
    """One tmp tree per test, a freshly imported classifier bound to it, and a
    registered stub evaluator so a SUCCESS arc yields a VALUED sidecar record
    without a third LLM call."""

    SID = 'pcancel-root-sid-0001'

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gsd-pcancel-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(_restore_env)
        self.hermes_home = os.path.join(self.tmp, 'hh')
        self.state_dir = os.path.join(self.hermes_home, 'state', 'revenium')
        self.markers_dir = os.path.join(self.state_dir, 'markers')
        self.assessments_dir = os.path.join(self.state_dir, 'job-assessments')
        os.makedirs(self.markers_dir, mode=0o700)

    def _load(self, eval_cfg=EVAL_ON):
        """Fresh classifier bound to this tmp tree. `eval_cfg=None` writes no
        llmOutcomeEvaluation at all (the feature-off install)."""
        cfg = {} if eval_cfg is None else {'llmOutcomeEvaluation': dict(eval_cfg)}
        with open(os.path.join(self.state_dir, 'config.json'), 'w') as f:
            json.dump(cfg, f)
        c, ev = _load_classifier({
            'HERMES_HOME': self.hermes_home, 'REVENIUM_STATE_DIR': self.state_dir,
        })
        ev.register('pcancel-stub', lambda job, transcript, cfg: dict(EVAL_PAYLOAD))
        return c

    def _trigger(self, c, responses, sid=None, transcript=TRANSCRIPT):
        """One plugin trigger (post_llm_call / session end / finalize all reach
        run_classification_async the same way). `responses` is the ordered
        list of call_llm return values this trigger may consume. Returns the
        call_llm mock so a test can count the calls."""
        sid = sid or self.SID
        with _llm_patch(c, responses) as llm, \
             mock.patch.object(c, '_read_session_transcript', return_value=transcript):
            asyncio.run(c.run_classification_async(
                session_id=sid, message='write the report', response='on it'))
        return llm

    def _first_pass(self, c, jobs, sid=None):
        """Trigger 1: classify the turn, then infer `jobs`. Returns the ids the
        classifier minted, in marker order."""
        llm = self._trigger(c, [_resp('code_review'), _resp(json.dumps(jobs))], sid=sid)
        self.assertEqual(llm.call_count, 2, 'first pass = one task call + one job call')
        return [r['agentic_job_id'] for r in self._job_markers(sid)]

    def _marker_path(self, sid=None):
        return os.path.join(self.markers_dir, f'{sid or self.SID}.jsonl')

    def _job_markers(self, sid=None):
        return [r for r in _read_jsonl(self._marker_path(sid)) if r.get('kind') == 'job']

    def _sidecar(self, job_id):
        return _read_jsonl(os.path.join(self.assessments_dir, f'{job_id}.jsonl'))

    def _seed_markers(self, records, sid=None):
        with open(self._marker_path(sid), 'w') as f:
            for rec in records:
                f.write(json.dumps(rec, separators=(',', ':')) + '\n')

    @staticmethod
    def _task_pair(sid, ts):
        return [
            {'muid': f'm{op}', 'ts': ts, 'sid': sid, 'task_type': 'code_review',
             'operation_type': op, 'trace_id': sid}
            for op in ('GUARDRAIL', 'CHAT')
        ]


class CancelledVerdictIsRejudgedTests(_ClassifierHarness):

    def test_early_cancelled_then_later_success_appends_a_marker_for_the_same_job(self):
        c = self._load()
        [job_id] = self._first_pass(c, [_job()])
        before = self._job_markers()
        self.assertEqual([r['status'] for r in before], ['CANCELLED'])

        llm = self._trigger(c, [_resp(_verdicts((1, 'SUCCESS')))])

        # One status-only call, and neither a task call (already classified)
        # nor a job-inference call (the arc is not re-inferred).
        self.assertEqual(llm.call_count, 1)
        after = self._job_markers()
        self.assertEqual([r['status'] for r in after], ['CANCELLED', 'SUCCESS'])
        first, second = after
        # SAME job: a new id would be a new Revenium job.
        self.assertEqual(second['agentic_job_id'], job_id)
        self.assertEqual(second['job_name'], first['job_name'])
        self.assertEqual(second['job_type'], first['job_type'])
        self.assertGreaterEqual(second['ts'], first['ts'])
        # The id still carries exactly the one entropy suffix the first pass minted.
        self.assertRegex(job_id, r'^write_and_verify_report_[0-9a-f]{4}$')
        # No second job came into being.
        self.assertEqual({r['agentic_job_id'] for r in after}, {job_id})

    def test_rejudge_does_not_rerun_job_inference(self):
        c = self._load()
        self._first_pass(c, [_job()])
        with mock.patch.object(c, '_infer_jobs_via_llm', new=mock.AsyncMock(return_value=[])) as infer:
            self._trigger(c, [_resp(_verdicts((1, 'SUCCESS')))])
        infer.assert_not_called()

    def test_success_is_latched_once_a_rejudge_lands(self):
        c = self._load()
        self._first_pass(c, [_job()])
        self._trigger(c, [_resp(_verdicts((1, 'SUCCESS')))])
        self.assertEqual(len(self._job_markers()), 2)

        # Third and fourth triggers: the status has left CANCELLED, so no LLM
        # call at all and no further marker.
        for _ in range(2):
            llm = self._trigger(c, [])
            self.assertEqual(llm.call_count, 0)
        self.assertEqual(len(self._job_markers()), 2)

    def test_a_first_pass_success_is_never_rejudged(self):
        c = self._load()
        self._first_pass(c, [_job(status='SUCCESS')])
        llm = self._trigger(c, [])
        self.assertEqual(llm.call_count, 0)
        self.assertEqual([r['status'] for r in self._job_markers()], ['SUCCESS'])

    def test_a_first_pass_failed_is_never_rejudged(self):
        c = self._load()
        self._first_pass(c, [_job(status='FAILED', failure_reason='tests failed')])
        llm = self._trigger(c, [])
        self.assertEqual(llm.call_count, 0)
        [rec] = self._job_markers()
        self.assertEqual(rec['status'], 'FAILED')
        self.assertEqual(rec['failure_reason'], 'tests failed')

    def test_the_guardrail_halt_cancel_is_never_rejudged(self):
        c = self._load()
        # What pre_tool_call.sh writes on a halt: a deliberate, real cancellation.
        self._seed_markers(self._task_pair(self.SID, time.time() - 30) + [{
            'kind': 'job', 'ts': time.time() - 20, 'sid': self.SID,
            'agentic_job_id': 'guardrail-halt-ab12',
            'job_name': 'Arc interrupted by guardrail halt',
            'job_type': 'interrupted', 'status': 'CANCELLED',
        }])
        llm = self._trigger(c, [])
        self.assertEqual(llm.call_count, 0)
        self.assertEqual(len(self._job_markers()), 1)

    def test_a_halt_cancel_does_not_shield_a_classifier_cancelled_job(self):
        """The two are different jobs: only the guardrail-halt-* id is exempt."""
        c = self._load()
        [job_id] = self._first_pass(c, [_job()])
        with open(self._marker_path(), 'a') as f:
            f.write(json.dumps({
                'kind': 'job', 'ts': time.time(), 'sid': self.SID,
                'agentic_job_id': 'guardrail-halt-ab12', 'job_name': 'halt',
                'job_type': 'interrupted', 'status': 'CANCELLED'}) + '\n')
        llm = self._trigger(c, [_resp(_verdicts((1, 'SUCCESS')))])
        self.assertEqual(llm.call_count, 1)
        latest = {r['agentic_job_id']: r['status'] for r in self._job_markers()}
        self.assertEqual(latest[job_id], 'SUCCESS')
        self.assertEqual(latest['guardrail-halt-ab12'], 'CANCELLED')

    def test_still_cancelled_appends_nothing_and_costs_one_call_per_trigger(self):
        c = self._load()
        self._first_pass(c, [_job()])
        for _ in range(3):
            llm = self._trigger(c, [_resp(_verdicts((1, 'CANCELLED')))])
            self.assertEqual(llm.call_count, 1, 'at most one re-judge call per trigger')
        self.assertEqual([r['status'] for r in self._job_markers()], ['CANCELLED'])

    def test_rejudge_to_failed_keeps_the_reason_and_records_an_abstention(self):
        c = self._load()
        [job_id] = self._first_pass(c, [_job()])
        body = json.dumps([{'index': 1, 'status': 'FAILED',
                            'failure_reason': 'verification step errored | twice'}])
        self._trigger(c, [_resp(body)])
        last = self._job_markers()[-1]
        self.assertEqual(last['status'], 'FAILED')
        self.assertEqual(last['agentic_job_id'], job_id)
        # The producer-side IFS strip _validate_job applies to a first-pass reason.
        self.assertEqual(last['failure_reason'], 'verification step errored   twice')
        # FAILED is never evaluated (ROI-09): an abstention record, not a value.
        record = self._sidecar(job_id)[-1]
        self.assertEqual(record['abstention_reason'], 'not_evaluated_non_success')
        self.assertNotIn('value_low', record)

    def test_a_failure_reason_on_a_non_failed_verdict_is_dropped(self):
        c = self._load()
        self._first_pass(c, [_job()])
        body = json.dumps([{'index': 1, 'status': 'SUCCESS', 'failure_reason': 'nope'}])
        self._trigger(c, [_resp(body)])
        self.assertNotIn('failure_reason', self._job_markers()[-1])

    def test_a_guardrail_halted_session_is_not_rejudged(self):
        c = self._load()
        self._first_pass(c, [_job()])
        with open(os.path.join(self.state_dir, 'guardrail-status.json'), 'w') as f:
            json.dump({'halted': True}, f)
        llm = self._trigger(c, [_resp(_verdicts((1, 'SUCCESS')))])
        self.assertEqual(llm.call_count, 0)
        self.assertEqual(len(self._job_markers()), 1)

    def test_multiple_cancelled_jobs_share_one_call(self):
        c = self._load()
        ids = self._first_pass(c, [
            _job('first_report', name='First report'),
            _job('second_report', name='Second report', job_type='research'),
        ])
        self.assertEqual(len(ids), 2)
        llm = self._trigger(c, [_resp(_verdicts((1, 'SUCCESS'), (2, 'CANCELLED')))])
        self.assertEqual(llm.call_count, 1, 'one status-only call covers every candidate')
        latest = {}
        for rec in self._job_markers():
            latest[rec['agentic_job_id']] = rec['status']
        self.assertEqual(latest, {ids[0]: 'SUCCESS', ids[1]: 'CANCELLED'})
        # ...and only the one that moved gained a marker.
        self.assertEqual(len(self._job_markers()), 3)

    def test_only_the_job_whose_latest_status_is_cancelled_is_a_candidate(self):
        c = self._load()
        ids = self._first_pass(c, [
            _job('done_job', status='SUCCESS', name='Done job'),
            _job('open_job', name='Open job'),
        ])
        prompts = []

        def spy(**kwargs):
            prompts.append(kwargs['messages'][-1]['content'])
            return _resp(_verdicts((1, 'SUCCESS')))

        with mock.patch.object(c, 'call_llm', side_effect=spy), \
             mock.patch.object(c, '_read_session_transcript', return_value=TRANSCRIPT):
            asyncio.run(c.run_classification_async(
                session_id=self.SID, message='m', response='r'))
        self.assertEqual(len(prompts), 1)
        self.assertIn('Open job', prompts[0])
        self.assertNotIn('Done job', prompts[0])
        statuses = {}
        for rec in self._job_markers():
            statuses[rec['agentic_job_id']] = rec['status']
        self.assertEqual(statuses[ids[0]], 'SUCCESS')
        self.assertEqual(statuses[ids[1]], 'SUCCESS')

    def test_feature_off_a_rejudged_success_writes_a_marker_and_no_sidecar(self):
        c = self._load(eval_cfg=None)
        [job_id] = self._first_pass(c, [_job()])
        llm = self._trigger(c, [_resp(_verdicts((1, 'SUCCESS')))])
        self.assertEqual(llm.call_count, 1)
        self.assertEqual([r['status'] for r in self._job_markers()], ['CANCELLED', 'SUCCESS'])
        self.assertEqual(self._sidecar(job_id), [])
        self.assertFalse(os.path.isdir(self.assessments_dir))

    def test_an_empty_transcript_costs_nothing(self):
        c = self._load()
        self._first_pass(c, [_job()])
        llm = self._trigger(c, [], transcript='')
        self.assertEqual(llm.call_count, 0)
        self.assertEqual(len(self._job_markers()), 1)

    def test_a_subagent_session_never_rejudges_its_roots_job(self):
        c = self._load()
        root, child = 'pcancel-root-sid-0002', 'pcancel-child-sid-0002'
        state_db = os.path.join(self.hermes_home, 'state.db')
        build_state_db(state_db, [
            {'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'cli',
             'input_tokens': 1, 'output_tokens': 1, 'cache_read': 0, 'cache_write': 0,
             'reasoning': 0, 'estimated_cost': '0', 'api_calls': 1,
             'started_at': time.time() - 100, 'ended_at': None,
             'billing_provider': 'anthropic'}
            for sid in (root, child)
        ])
        conn = sqlite3.connect(state_db)
        try:
            conn.execute('ALTER TABLE sessions ADD COLUMN parent_session_id TEXT')
            conn.execute('UPDATE sessions SET parent_session_id = ? WHERE id = ?', (root, child))
            conn.commit()
        finally:
            conn.close()
        self._first_pass(c, [_job()], sid=root)
        llm = self._trigger(c, [_resp(_verdicts((1, 'SUCCESS')))], sid=child)
        self.assertEqual(llm.call_count, 0)
        self.assertEqual([r['status'] for r in self._job_markers(root)], ['CANCELLED'])

    def test_marker_lines_stay_inside_the_frozen_byte_budget(self):
        c = self._load()
        self._first_pass(c, [_job(name='n' * 60)])
        body = json.dumps([{'index': 1, 'status': 'FAILED', 'failure_reason': '漢' * 400}])
        self._trigger(c, [_resp(body)])
        for line in Path(self._marker_path()).read_text().splitlines():
            self.assertLess(len(line.encode('utf-8')), 1024, line)


class RejudgeSidecarTests(_ClassifierHarness):
    """Fix 3: the record the reporter reads is the valued one."""

    def test_the_valued_record_follows_the_abstention_and_is_the_last_match(self):
        c = self._load()
        [job_id] = self._first_pass(c, [_job()])
        [abstention] = self._sidecar(job_id)
        self.assertEqual(abstention['abstention_reason'], 'not_evaluated_non_success')
        self.assertNotIn('value_low', abstention)

        self._trigger(c, [_resp(_verdicts((1, 'SUCCESS')))])

        records = self._sidecar(job_id)
        self.assertEqual(len(records), 2, records)
        # The reporter keeps the LAST job_assessment/correction line for the id
        # (hermes-report.sh: "Deliberate: no break"), so order is the contract.
        self.assertEqual(records[0], abstention)
        valued = records[-1]
        self.assertEqual(valued['kind'], 'job_assessment')
        self.assertEqual(valued['agentic_job_id'], job_id)
        self.assertIn('value_low', valued)
        # A valued record carries the key empty; an abstention carries the reason.
        self.assertEqual(valued.get('abstention_reason', ''), '')
        self.assertEqual(valued['reportability_status'], 'reportable')
        # It is the same job, so the group id the first pass chose is unchanged.
        self.assertEqual(valued['double_counting_group'], abstention['double_counting_group'])

    def test_sidecar_is_written_before_the_marker(self):
        """Phase 42 D-12, preserved on the re-judge path: a crash between the
        two appends must leave an orphan sidecar, never a valueless marker."""
        c = self._load()
        [job_id] = self._first_pass(c, [_job()])
        order = []
        real_sidecar, real_marker = c._write_job_assessment, c._write_job_marker
        with mock.patch.object(c, '_write_job_assessment',
                               side_effect=lambda *a, **k: (order.append('sidecar'), real_sidecar(*a, **k))[1]), \
             mock.patch.object(c, '_write_job_marker',
                               side_effect=lambda *a, **k: (order.append('marker'), real_marker(*a, **k))[1]):
            self._trigger(c, [_resp(_verdicts((1, 'SUCCESS')))])
        self.assertEqual(order, ['sidecar', 'marker'])

    def test_an_operator_correction_is_not_superseded_by_the_model_estimate(self):
        c = self._load()
        [job_id] = self._first_pass(c, [_job()])
        correction = {
            'kind': 'correction', 'ts': time.time(), 'agentic_job_id': job_id,
            'assessment_schema_version': 1, 'value_low': 900.0, 'value_base': 900.0,
            'value_high': 900.0, 'currency': 'USD', 'reason': 'operator priced it',
        }
        os.makedirs(self.assessments_dir, exist_ok=True)
        with open(os.path.join(self.assessments_dir, f'{job_id}.jsonl'), 'a') as f:
            f.write(json.dumps(correction, separators=(',', ':')) + '\n')

        llm = self._trigger(c, [_resp(_verdicts((1, 'SUCCESS')))])

        # No evaluator call (the only call is the status re-judge) and no new
        # sidecar line: the correction is still the last match.
        self.assertEqual(llm.call_count, 1)
        self.assertEqual(self._sidecar(job_id)[-1], correction)
        # The status itself still moves.
        self.assertEqual(self._job_markers()[-1]['status'], 'SUCCESS')


class GreptileReviewFixesTests(_ClassifierHarness):
    """Greptile P1 findings on #152: the correction race and the stuck window."""

    def _evaluators(self, c):
        return _sys.modules[c.__name__.rsplit('.', 1)[0] + '.evaluators']

    def test_a_correction_filed_while_the_evaluator_runs_is_not_superseded(self):
        c = self._load()
        [job_id] = self._first_pass(c, [_job()])
        correction = {
            'kind': 'correction', 'ts': time.time(), 'agentic_job_id': job_id,
            'assessment_schema_version': 1, 'value_low': 900.0, 'value_base': 900.0,
            'value_high': 900.0, 'currency': 'USD', 'reason': 'operator priced it',
        }
        sidecar_path = os.path.join(self.assessments_dir, f'{job_id}.jsonl')

        def evaluator(job, transcript, cfg):
            # The operator files the correction while the evaluation is in
            # flight, AFTER the re-judge's pre-check saw no correction.
            os.makedirs(self.assessments_dir, exist_ok=True)
            with open(sidecar_path, 'a') as f:
                f.write(json.dumps(correction, separators=(',', ':')) + '\n')
            return dict(EVAL_PAYLOAD)

        self._evaluators(c).register('pcancel-stub', evaluator)
        self._trigger(c, [_resp(_verdicts((1, 'SUCCESS')))])
        self.assertEqual(self._sidecar(job_id)[-1], correction)
        self.assertEqual(self._job_markers()[-1]['status'], 'SUCCESS')

    def test_write_job_assessment_refuses_only_when_asked(self):
        c = self._load()
        os.makedirs(self.assessments_dir, exist_ok=True)
        path = os.path.join(self.assessments_dir, 'job_x.jsonl')
        with open(path, 'w') as f:
            f.write(json.dumps({'kind': 'correction', 'agentic_job_id': 'job_x'}) + '\n')
        rec = {'agentic_job_id': 'job_x', 'value_base': 1.0}
        self.assertIsNone(c._write_job_assessment(rec, refuse_if_corrected=True))
        self.assertEqual(len(_read_jsonl(path)), 1)
        self.assertIsNotNone(c._write_job_assessment(rec))
        self.assertEqual(len(_read_jsonl(path)), 2)

    def test_more_than_the_cap_rotates_so_every_job_is_rechecked(self):
        c = self._load()
        n = c.REJUDGE_MAX_JOBS + 2
        names = [f'Arc {chr(ord("A") + i)} work' for i in range(n)]
        records = self._task_pair(self.SID, time.time() - 100)
        for i, name in enumerate(names):
            records.append({
                'kind': 'job', 'ts': time.time() - 50 + i, 'sid': self.SID,
                'agentic_job_id': f'arc_{i:02d}_abcd', 'job_name': name,
                'job_type': 'documentation', 'status': 'CANCELLED',
            })
        self._seed_markers(records)
        prompts = []

        def spy(**kwargs):
            prompts.append(kwargs['messages'][-1]['content'])
            return _resp(_verdicts())

        for _ in range(2):
            with mock.patch.object(c, 'call_llm', side_effect=spy), \
                 mock.patch.object(c, '_read_session_transcript', return_value=TRANSCRIPT):
                asyncio.run(c.run_classification_async(
                    session_id=self.SID, message='m', response='r'))
        self.assertEqual(len(prompts), 2, 'one call per trigger')
        first = {name for name in names if name in prompts[0]}
        self.assertEqual(len(first), c.REJUDGE_MAX_JOBS)
        covered = {name for name in names if any(name in pr for pr in prompts)}
        self.assertEqual(covered, set(names),
                         'the second trigger must reach the jobs past the cap')


class RejudgeNeverRaisesTests(_ClassifierHarness):

    def _assert_unchanged_after(self, c, responses, **kw):
        before = Path(self._marker_path()).read_bytes()
        sidecar_before = self._sidecar(self._job_markers()[0]['agentic_job_id'])
        self._trigger(c, responses, **kw)  # must not raise
        self.assertEqual(Path(self._marker_path()).read_bytes(), before)
        self.assertEqual(
            self._sidecar(self._job_markers()[0]['agentic_job_id']), sidecar_before)

    def test_garbage_and_unusable_verdicts_leave_the_job_cancelled(self):
        c = self._load()
        self._first_pass(c, [_job()])
        for label, body in (
            ('not json', 'the job looks done to me'),
            ('empty', ''),
            ('empty array', '[]'),
            ('unknown index', _verdicts((7, 'SUCCESS'))),
            ('zero index', _verdicts((0, 'SUCCESS'))),
            ('bad status', _verdicts((1, 'DONE'))),
            ('non-dict items', '["SUCCESS"]'),
            ('bool index', json.dumps([{'index': True, 'status': 'SUCCESS'}])),
            ('no index', json.dumps([{'status': 'SUCCESS'}])),
        ):
            with self.subTest(label):
                self._assert_unchanged_after(c, [_resp(body)])

    def test_a_fenced_response_is_accepted(self):
        c = self._load()
        self._first_pass(c, [_job()])
        self._trigger(c, [_resp('```json\n' + _verdicts((1, 'SUCCESS')) + '\n```')])
        self.assertEqual(self._job_markers()[-1]['status'], 'SUCCESS')

    def test_the_first_verdict_for_an_index_wins(self):
        c = self._load()
        self._first_pass(c, [_job()])
        self._trigger(c, [_resp(_verdicts((1, 'CANCELLED'), (1, 'SUCCESS')))])
        self.assertEqual(self._job_markers()[-1]['status'], 'CANCELLED')

    def test_an_llm_that_raises_changes_nothing(self):
        c = self._load()
        self._first_pass(c, [_job()])
        before = Path(self._marker_path()).read_bytes()
        with mock.patch.object(c, 'call_llm', side_effect=RuntimeError('provider down')), \
             mock.patch.object(c, '_read_session_transcript', return_value=TRANSCRIPT):
            asyncio.run(c.run_classification_async(
                session_id=self.SID, message='m', response='r'))
        self.assertEqual(Path(self._marker_path()).read_bytes(), before)

    def test_no_llm_available_changes_nothing(self):
        c = self._load()
        self._first_pass(c, [_job()])
        before = Path(self._marker_path()).read_bytes()
        with mock.patch.object(c, 'call_llm', new=None), \
             mock.patch.object(c, '_read_session_transcript', return_value=TRANSCRIPT):
            asyncio.run(c.run_classification_async(
                session_id=self.SID, message='m', response='r'))
        self.assertEqual(Path(self._marker_path()).read_bytes(), before)

    def test_an_exploding_helper_never_escapes_run_classification_async(self):
        c = self._load()
        self._first_pass(c, [_job()])
        for name in ('_latest_job_markers', '_rejudge_status_via_llm', '_build_rejudge_prompt'):
            with self.subTest(name):
                with mock.patch.object(c, name, side_effect=RuntimeError('boom')):
                    self._trigger(c, [_resp(_verdicts((1, 'SUCCESS')))])
        # And the sync wrapper the plugin entrypoint uses.
        with mock.patch.object(c, '_rejudge_cancelled_jobs',
                               new=mock.AsyncMock(side_effect=RuntimeError('boom'))):
            c.run_classification(session_id=self.SID, message='m', response='r')

    def test_a_failing_sidecar_write_does_not_stop_the_status_change(self):
        c = self._load()
        self._first_pass(c, [_job()])
        with mock.patch.object(c, '_write_job_assessment', side_effect=OSError('disk full')):
            self._trigger(c, [_resp(_verdicts((1, 'SUCCESS')))])
        self.assertEqual(self._job_markers()[-1]['status'], 'SUCCESS')

    def test_a_corrupt_job_type_in_the_existing_marker_is_skipped_not_fatal(self):
        c = self._load()
        self._seed_markers(self._task_pair(self.SID, time.time() - 5) + [{
            'kind': 'job', 'ts': time.time(), 'sid': self.SID,
            'agentic_job_id': 'odd_job_ab12', 'job_name': 'odd',
            'job_type': 'NOT A LABEL!', 'status': 'CANCELLED'}])
        llm = self._trigger(c, [_resp(_verdicts((1, 'SUCCESS')))])
        self.assertEqual(llm.call_count, 0, 'nothing valid to re-judge, so nothing to pay for')
        self.assertEqual(len(self._job_markers()), 1)


class LatestJobMarkerResolutionTests(_ClassifierHarness):
    """`_latest_job_markers` applies the reporter's rule: latest marker ts,
    a tie going to the later line in the file."""

    def _latest(self, records):
        c = self._load()
        self._seed_markers(records)
        return {r['agentic_job_id']: r['status'] for r in c._latest_job_markers(self.SID)}

    @staticmethod
    def _m(job_id, status, ts):
        return {'kind': 'job', 'ts': ts, 'sid': 'x', 'agentic_job_id': job_id,
                'job_name': 'n', 'job_type': 'code_fix', 'status': status}

    def test_later_ts_wins_regardless_of_file_order(self):
        got = self._latest([self._m('a', 'SUCCESS', 200.0), self._m('a', 'CANCELLED', 100.0)])
        self.assertEqual(got, {'a': 'SUCCESS'})

    def test_a_ts_tie_goes_to_the_later_line(self):
        got = self._latest([self._m('a', 'SUCCESS', 100.0), self._m('a', 'CANCELLED', 100.0)])
        self.assertEqual(got, {'a': 'CANCELLED'})

    def test_ids_are_tracked_independently_and_in_first_seen_order(self):
        c = self._load()
        self._seed_markers([
            self._m('a', 'CANCELLED', 1.0), self._m('b', 'SUCCESS', 2.0),
            self._m('a', 'SUCCESS', 3.0)])
        got = [(r['agentic_job_id'], r['status']) for r in c._latest_job_markers(self.SID)]
        self.assertEqual(got, [('a', 'SUCCESS'), ('b', 'SUCCESS')])

    def test_tolerates_missing_file_torn_lines_and_non_job_records(self):
        c = self._load()
        self.assertEqual(c._latest_job_markers('no-such-session'), [])
        with open(self._marker_path(), 'w') as f:
            f.write('{"torn":\n')
            f.write('[1,2]\n')
            f.write(json.dumps({'muid': 'm', 'ts': 1, 'sid': 's', 'task_type': 't',
                                'operation_type': 'CHAT'}) + '\n')
            f.write(json.dumps(self._m('a', 'CANCELLED', 5.0)) + '\n')
            f.write(json.dumps({'kind': 'job', 'status': 'SUCCESS'}) + '\n')  # no id
            f.write(json.dumps({**self._m('b', 'CANCELLED', 'soon')}) + '\n')  # bad ts
        got = {r['agentic_job_id'] for r in c._latest_job_markers(self.SID)}
        self.assertEqual(got, {'a', 'b'})


class RejudgePromptTests(_ClassifierHarness):

    def test_the_prompt_names_the_arcs_and_asks_for_status_only(self):
        c = self._load()
        prompt = c._build_rejudge_prompt(TRANSCRIPT, [
            {'job_name': 'Write the report', 'job_type': 'documentation'},
            {'job_name': 'Audit the config', 'job_type': 'security_review'},
        ])
        self.assertIn('1. Write the report', prompt)
        self.assertIn('2. Audit the config', prompt)
        self.assertIn('documentation', prompt)
        self.assertIn(TRANSCRIPT, prompt)
        for status in ('SUCCESS', 'FAILED', 'CANCELLED'):
            self.assertIn(status, prompt)
        # It must not invite the model to mint or rename a job.
        self.assertNotIn('Mint', prompt)
        self.assertNotIn('agentic_job_id', prompt)

    def test_a_long_transcript_keeps_its_ending(self):
        """The completion evidence is at the END of a long session, which is
        exactly what a head-only cut throws away."""
        c = self._load()
        ending = 'FINAL-EVIDENCE-the-subagent-verified-the-file'
        transcript = 'user: start\n' + ('assistant: working ...\n' * 2000) + ending
        prompt = c._build_rejudge_prompt(transcript, [{'job_name': 'j', 'job_type': 'code_fix'}])
        self.assertIn(ending, prompt)
        self.assertIn('user: start', prompt)
        self.assertLess(len(prompt), 12000)

    def test_the_call_uses_the_users_main_model(self):
        """Same contract as job inference: NO `task=` kwarg, so the call stays
        on the provider and model the user configured (ROI-07)."""
        c = self._load()
        [rec] = [{'job_name': 'j', 'job_type': 'code_fix'}]
        with mock.patch.object(c, 'call_llm', return_value=_resp(_verdicts((1, 'SUCCESS')))) as llm:
            got = asyncio.run(c._rejudge_status_via_llm(TRANSCRIPT, [rec]))
        self.assertEqual(got, {1: {'status': 'SUCCESS', 'failure_reason': ''}})
        _, kwargs = llm.call_args
        self.assertNotIn('task', kwargs)
        self.assertEqual(kwargs['temperature'], 0.0)
        self.assertLessEqual(kwargs['max_tokens'], 512)
        self.assertEqual(kwargs['messages'][0]['role'], 'system')

    def test_the_transcript_is_read_with_the_rejudge_budget(self):
        c = self._load()
        self._first_pass(c, [_job()])
        with mock.patch.object(c, 'call_llm', return_value=_resp(_verdicts((1, 'CANCELLED')))), \
             mock.patch.object(c, '_read_session_transcript', return_value=TRANSCRIPT) as read:
            asyncio.run(c.run_classification_async(
                session_id=self.SID, message='m', response='r'))
        self.assertEqual(read.call_count, 1)
        self.assertLessEqual(read.call_args.kwargs['max_chars'], 6000)


# ---------------------------------------------------------------------------
# Part 2 -- the reporter
# ---------------------------------------------------------------------------

JOB = lc.JOB_ID


class _ReporterBase(lc._LifecycleHarness):

    SID = 'pcancel-rep-sid-0001'

    def _fixture_with_markers(self, markers, *, ended_ago=2900.0, created=True,
                              extra_ledger=(), config=None, sidecar=None, job_id=JOB):
        fx = self._fixture([self._session(self.SID, ended_ago=ended_ago)])
        self._write_markers(
            fx, self.SID,
            [self._task_marker(self.SID, 'rep-muid-0001', self.now - 2995.0)] + list(markers))
        ledger = []
        if created:
            ledger.append(f'JOB:{job_id}:created:{self.now - 2900.0:.0f}.000')
        ledger.extend(extra_ledger)
        if ledger:
            self._seed_jobs_ledger(fx, ledger)
        if config is not None:
            with open(os.path.join(fx['state_dir'], 'config.json'), 'w') as f:
                json.dump(config, f)
        if sidecar is not None:
            adir = os.path.join(fx['state_dir'], 'job-assessments')
            os.makedirs(adir, mode=0o700, exist_ok=True)
            with open(os.path.join(adir, f'{job_id}.jsonl'), 'w') as f:
                for rec in sidecar:
                    f.write(json.dumps(rec, separators=(',', ':')) + '\n')
        return fx

    def _m(self, status, ago, job_id=JOB, failure_reason=None, **extra):
        rec = self._job_marker(self.SID, self.now - ago, job_id=job_id, status=status, **extra)
        if failure_reason:
            rec['failure_reason'] = failure_reason
        return rec

    def _results(self, outcomes):
        return [(o[2], argv_to_flags(o).get('--result')) for o in outcomes]


class ReporterLatestMarkerWinsTests(_ReporterBase):

    def test_a_later_success_replaces_the_earlier_cancelled(self):
        fx = self._fixture_with_markers([self._m('CANCELLED', 2990.0), self._m('SUCCESS', 2000.0)])
        t1 = self._tick(fx)
        self.assertEqual(t1['rc'], 0, t1['output'])
        self.assertEqual(self._results(self._job_outcomes(t1['new'])), [(JOB, 'SUCCESS')])
        ledger = self._read_ledger(fx, 'revenium-jobs.ledger')
        self.assertEqual(ledger.count(f'JOB:{JOB}:outcome:'), 1, ledger)
        self.assertTrue(ledger.strip().endswith('SUCCESS'), ledger)
        # Idempotent: the next tick reports nothing.
        t2 = self._tick(fx)
        self.assertEqual(self._job_outcomes(t2['new']), [])

    def test_the_marker_ts_decides_not_the_position_in_the_file(self):
        fx = self._fixture_with_markers([self._m('SUCCESS', 2000.0), self._m('CANCELLED', 2990.0)])
        t1 = self._tick(fx)
        self.assertEqual(self._results(self._job_outcomes(t1['new'])), [(JOB, 'SUCCESS')])

    def test_a_ts_tie_goes_to_the_later_line(self):
        fx = self._fixture_with_markers([self._m('SUCCESS', 2500.0), self._m('CANCELLED', 2500.0)])
        t1 = self._tick(fx)
        self.assertEqual(self._results(self._job_outcomes(t1['new'])), [(JOB, 'CANCELLED')])

    def test_a_later_cancelled_does_not_override_an_earlier_success(self):
        """The rule is latest-wins, not success-wins: a classifier that wrote
        SUCCESS and then something else is reported as the something else."""
        fx = self._fixture_with_markers([self._m('SUCCESS', 2990.0), self._m('FAILED', 2000.0,
                                                                              failure_reason='broke')])
        t1 = self._tick(fx)
        self.assertEqual(self._results(self._job_outcomes(t1['new'])), [(JOB, 'FAILED')])

    def test_on_an_open_session_the_rejudged_success_is_reported_at_once(self):
        fx = self._fixture_with_markers(
            [self._m('CANCELLED', 2990.0), self._m('SUCCESS', 2000.0)], ended_ago=None)
        t1 = self._tick(fx)
        self.assertEqual(self._results(self._job_outcomes(t1['new'])), [(JOB, 'SUCCESS')])
        self.assertNotIn('outcome held while session open', self._read_log(fx))

    def test_a_held_cancelled_is_released_as_success_when_the_rejudge_lands(self):
        """The real sequence on the ent profile: CANCELLED is written seconds in
        and held while the session is open; the re-judge then appends SUCCESS."""
        fx = self._fixture_with_markers([self._m('CANCELLED', 2990.0)], ended_ago=None)
        t1 = self._tick(fx)
        self.assertEqual(self._job_outcomes(t1['new']), [], 'CANCELLED is held while open')
        self.assertIn('outcome held while session open', self._read_log(fx))

        with open(os.path.join(fx['markers_dir'], f'{self.SID}.jsonl'), 'a') as f:
            f.write(json.dumps(self._m('SUCCESS', 1.0), separators=(',', ':')) + '\n')
        t2 = self._tick(fx)
        self.assertEqual(self._results(self._job_outcomes(t2['new'])), [(JOB, 'SUCCESS')])

    def test_a_cancelled_outcome_already_ledgered_is_final(self):
        """Idempotency is untouched: once an outcome is ledgered, a later marker
        for the id cannot re-report it."""
        fx = self._fixture_with_markers(
            [self._m('CANCELLED', 2990.0), self._m('SUCCESS', 2000.0)],
            extra_ledger=[f'JOB:{JOB}:outcome:{self.now - 100:.0f}.000:CANCELLED'])
        t1 = self._tick(fx)
        self.assertEqual(self._job_outcomes(t1['new']), [])

    def test_distinct_jobs_in_one_session_are_reduced_independently(self):
        other = 'second_job_cd34'
        fx = self._fixture_with_markers([
            self._m('CANCELLED', 2990.0),
            self._m('SUCCESS', 2980.0, job_id=other, job_name='Second job'),
            self._m('SUCCESS', 2000.0),
        ])
        self._seed_jobs_ledger(fx, [
            f'JOB:{JOB}:created:{self.now - 2900:.0f}.000',
            f'JOB:{other}:created:{self.now - 2900:.0f}.000',
        ])
        t1 = self._tick(fx)
        self.assertEqual(
            sorted(self._results(self._job_outcomes(t1['new']))),
            sorted([(JOB, 'SUCCESS'), (other, 'SUCCESS')]))

    def test_a_single_marker_session_is_unchanged(self):
        fx = self._fixture_with_markers([self._m('CANCELLED', 2990.0)])
        t1 = self._tick(fx)
        self.assertEqual(self._results(self._job_outcomes(t1['new'])), [(JOB, 'CANCELLED')])

    def test_the_halt_cancel_is_still_reported_immediately(self):
        fx = self._fixture_with_markers(
            [self._m('CANCELLED', 2990.0, job_id='guardrail-halt-ab12', job_type='interrupted')],
            ended_ago=None, job_id='guardrail-halt-ab12')
        t1 = self._tick(fx)
        self.assertEqual(
            self._results(self._job_outcomes(t1['new'])), [('guardrail-halt-ab12', 'CANCELLED')])


def _abstention(job_id):
    """The sidecar record the CANCELLED pass leaves: identity and provenance
    kept, every value-bearing key gone, and a reason."""
    rec = p38._sidecar_record(job_id, reportability_status='candidate')
    for k in ('value_low', 'value_base', 'value_high', 'bounds_source', 'currency',
              'estimated_value', 'assumptions', 'net_value'):
        rec.pop(k, None)
    rec['abstention_reason'] = 'not_evaluated_non_success'
    return rec


class ReporterReadsTheValuedRecordTests(_ReporterBase):

    CFG = {'llmOutcomeEvaluation': {
        'enabled': True, 'experimentalReportEstimates': True, 'reportModelEstimates': True}}

    def _one_outcome(self, fx):
        t = self._tick(fx)
        self.assertEqual(t['rc'], 0, t['output'])
        [argv] = self._job_outcomes(t['new'])
        return argv_to_flags(argv)

    def test_the_valued_record_after_the_abstention_ships_its_value(self):
        fx = self._fixture_with_markers(
            [self._m('CANCELLED', 2990.0), self._m('SUCCESS', 2000.0)],
            config=self.CFG,
            sidecar=[_abstention(JOB),
                     p38._sidecar_record(JOB, reportability_status='reportable')])
        flags = self._one_outcome(fx)
        self.assertEqual(flags.get('--result'), 'SUCCESS')
        self.assertEqual(flags.get('--outcome-value'), '446.25')
        self.assertEqual(flags.get('--outcome-currency'), 'USD')

    def test_control_the_abstention_alone_ships_no_value(self):
        """Without the valued line the SUCCESS goes out unvalued, so the value
        above really does come from the re-judge's record."""
        fx = self._fixture_with_markers(
            [self._m('CANCELLED', 2990.0), self._m('SUCCESS', 2000.0)],
            config=self.CFG, sidecar=[_abstention(JOB)])
        flags = self._one_outcome(fx)
        self.assertEqual(flags.get('--result'), 'SUCCESS')
        self.assertNotIn('--outcome-value', flags)

    def test_the_abstention_does_not_mask_the_valued_record_when_written_second(self):
        """Documents the ordering contract the classifier relies on: the reader
        is last-match-wins, so an abstention appended AFTER the valued record
        would hide it. The re-judge never does that (CANCELLED -> SUCCESS only,
        and the valued record is appended last)."""
        fx = self._fixture_with_markers(
            [self._m('SUCCESS', 2000.0)], config=self.CFG,
            sidecar=[p38._sidecar_record(JOB, reportability_status='reportable'),
                     _abstention(JOB)])
        flags = self._one_outcome(fx)
        self.assertNotIn('--outcome-value', flags)


class RejudgeEndToEndTests(lc._LifecycleHarness):
    """The whole chain, nothing hand-authored between the two halves: the REAL
    classifier (only call_llm stubbed, transcript read from a real state.db)
    writes the markers and the sidecar, and a REAL hermes-report.sh tick reads
    them. This is the ent-profile sequence: CANCELLED written seconds in and
    held while the session is open, the arc finished by a subagent, a later
    trigger re-judging it, then the session closing.

    Without the reporter half the closed-session tick below reports the
    superseded CANCELLED; without the classifier half there is never a SUCCESS.
    """

    SID = 'pcancel-e2e-sid-0001'
    CFG = {'llmOutcomeEvaluation': {
        'enabled': True, 'experimentalReportEstimates': True,
        'reportModelEstimates': True, 'currency': 'USD',
        'maxHoursSaved': 40, 'maxLoadedRate': 500,
    }}

    def _build(self):
        fx = self._fixture([self._session(self.SID, ended_ago=None)])
        conn = sqlite3.connect(fx['state_db'])
        try:
            conn.execute('ALTER TABLE sessions ADD COLUMN parent_session_id TEXT')
            conn.execute(
                'CREATE TABLE messages (session_id TEXT, role TEXT, content TEXT, '
                'tool_calls TEXT, timestamp INTEGER)')
            for i, (role, content) in enumerate((
                ('user', 'Write and verify a file listing my five largest downloads'),
                ('assistant', 'Delegating to a subagent.'),
                ('tool', 'subagent: wrote ~/largest.txt and verified it matches du output'),
                ('assistant', 'Done: the file is written and verified.'),
            )):
                conn.execute('INSERT INTO messages VALUES (?,?,?,?,?)',
                             (self.SID, role, content, None, 1000 + i))
            conn.commit()
        finally:
            conn.close()
        with open(os.path.join(fx['state_dir'], 'config.json'), 'w') as f:
            json.dump(self.CFG, f)
        for name in ('task-taxonomy.json', 'job-taxonomy.json'):
            shutil.copy(SKILL_DIR / name, os.path.join(fx['state_dir'], name))
        self.addCleanup(_restore_env)
        c, _ev = _load_classifier({
            'HERMES_HOME': fx['hermes_home'], 'REVENIUM_STATE_DIR': fx['state_dir']})
        return fx, c

    def _trigger(self, c, responses):
        with _llm_patch(c, responses) as llm:
            asyncio.run(c.run_classification_async(
                session_id=self.SID, message='write the file', response='on it'))
        return llm

    def _close_session(self, fx):
        conn = sqlite3.connect(fx['state_db'])
        try:
            conn.execute('UPDATE sessions SET ended_at = ? WHERE id = ?',
                         (self.now - 10.0, self.SID))
            conn.commit()
        finally:
            conn.close()

    def _job_records(self, fx):
        path = os.path.join(fx['markers_dir'], f'{self.SID}.jsonl')
        return [r for r in _read_jsonl(path) if r.get('kind') == 'job']

    def test_a_premature_cancelled_is_corrected_and_ships_success_with_a_value(self):
        fx, c = self._build()

        # 24 seconds in: the first pass sees an unfinished arc -> CANCELLED.
        job = _job(status='CANCELLED')
        llm = self._trigger(c, [_resp('documentation'), _resp(json.dumps([job]))])
        self.assertEqual(llm.call_count, 2)
        [first] = self._job_records(fx)
        job_id = first['agentic_job_id']
        self.assertEqual(first['status'], 'CANCELLED')

        # The reporter creates the job and holds the CANCELLED: session is open.
        t1 = self._tick(fx)
        self.assertEqual(t1['rc'], 0, t1['output'])
        self.assertEqual(
            [argv_to_flags(a).get('--agentic-job-id') for a in self._job_creates(t1['new'])],
            [job_id])
        self.assertEqual(self._job_outcomes(t1['new']), [])

        # A later trigger, the subagent's work now in the transcript: re-judge
        # (one status call) then the evaluator call for the SUCCESS.
        llm = self._trigger(c, [
            _resp(_verdicts((1, 'SUCCESS'))),
            _resp(json.dumps(EVAL_PAYLOAD)),
        ])
        self.assertEqual(llm.call_count, 2, 'status re-judge + outcome evaluation')
        statuses = [r['status'] for r in self._job_records(fx)]
        self.assertEqual(statuses, ['CANCELLED', 'SUCCESS'])
        sidecar = _read_jsonl(os.path.join(fx['state_dir'], 'job-assessments', f'{job_id}.jsonl'))
        self.assertEqual(len(sidecar), 2, sidecar)
        self.assertIn('value_low', sidecar[-1])

        # The session closes. Before the fix this tick reported the stale
        # CANCELLED -- the first queue entry -- and ledgered it for good.
        self._close_session(fx)
        t2 = self._tick(fx)
        self.assertEqual(t2['rc'], 0, t2['output'])
        [outcome] = self._job_outcomes(t2['new'])
        flags = argv_to_flags(outcome)
        self.assertEqual(outcome[2], job_id)
        self.assertEqual(flags.get('--result'), 'SUCCESS')
        # The value on the wire is the valued record's low bound, read off disk.
        self.assertEqual(float(flags['--outcome-value']), sidecar[-1]['value_low'])
        self.assertEqual(flags.get('--outcome-currency'), 'USD')

        t3 = self._tick(fx)
        self.assertEqual(self._job_outcomes(t3['new']), [])
        ledger = self._read_ledger(fx, 'revenium-jobs.ledger')
        self.assertEqual(ledger.count(f'JOB:{job_id}:outcome:'), 1, ledger)

    def test_a_job_that_stays_cancelled_still_reports_cancelled_once_the_session_ends(self):
        """The fix must not make CANCELLED unreachable: an arc the re-judge
        still cannot confirm ships CANCELLED, exactly as before."""
        fx, c = self._build()
        self._trigger(c, [_resp('documentation'), _resp(json.dumps([_job()]))])
        t1 = self._tick(fx)
        self.assertEqual(self._job_outcomes(t1['new']), [])
        llm = self._trigger(c, [_resp(_verdicts((1, 'CANCELLED')))])
        self.assertEqual(llm.call_count, 1)
        self.assertEqual(len(self._job_records(fx)), 1)

        self._close_session(fx)
        t2 = self._tick(fx)
        [outcome] = self._job_outcomes(t2['new'])
        self.assertEqual(argv_to_flags(outcome).get('--result'), 'CANCELLED')
        self.assertNotIn('--outcome-value', argv_to_flags(outcome))


_REDUCER = '_reduce_job_outcome_queue'


class QueueReducerTests(unittest.TestCase):
    """The reduction itself, under the system bash (3.2 on macOS) and `bash`."""

    BASHES = ('/bin/bash', 'bash')

    def _reduce(self, bash, entries):
        text = (SCRIPTS_DIR / 'hermes-report.sh').read_text()
        m = re.search(rf'^{_REDUCER}\(\) \{{\n.*?^\}}\n', text, re.S | re.M)
        self.assertIsNotNone(m, f'{_REDUCER} not found in hermes-report.sh')
        script = m.group(0) + f'\nprintf "%s\\n" "$@" | {_REDUCER}\n'
        out = subprocess.run([bash, '-c', script, 'x'] + entries, capture_output=True,
                             text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.splitlines()

    def _each(self, entries, expected):
        for bash in self.BASHES:
            self.assertEqual(self._reduce(bash, entries), expected, bash)

    def test_latest_ts_wins(self):
        self._each(['a|CANCELLED|s|100.5||sid', 'a|SUCCESS|s|200.25||sid'],
                   ['a|SUCCESS|s|200.25||sid'])

    def test_ts_beats_queue_position(self):
        self._each(['a|SUCCESS|s|200||sid', 'a|CANCELLED|s|100||sid'],
                   ['a|SUCCESS|s|200||sid'])

    def test_a_tie_goes_to_the_later_entry(self):
        self._each(['a|SUCCESS|s|100||sid', 'a|CANCELLED|s|100||sid'],
                   ['a|CANCELLED|s|100||sid'])

    def test_first_seen_order_of_ids_is_kept(self):
        self._each(
            ['b|SUCCESS|s|1||sid', 'a|CANCELLED|s|2||sid', 'b|FAILED|s|3|why|sid'],
            ['b|FAILED|s|3|why|sid', 'a|CANCELLED|s|2||sid'])

    def test_unparseable_ts_sorts_oldest_and_never_crashes(self):
        self._each(['a|SUCCESS|s|garbage||sid', 'a|CANCELLED|s|5||sid', 'a|FAILED|s|nan||sid'],
                   ['a|CANCELLED|s|5||sid'])

    def test_blank_lines_and_empty_ids_are_dropped(self):
        self._each(['', '|SUCCESS|s|1||sid', 'a|SUCCESS|s|1||sid'], ['a|SUCCESS|s|1||sid'])


if __name__ == '__main__':
    unittest.main()


class ReporterJobOwnershipTests(_ReporterBase):
    """Greptile P1 on #152, legacy path: a re-judge marker for job A appended
    after job B's marker must not take task markers away from B."""

    def test_a_task_after_job_b_stays_with_b_when_job_a_is_rejudged(self):
        job_b = 'second_job_b_2222'
        fx = self._fixture_with_markers(
            [
                self._m('CANCELLED', 2990.0),
                self._m('SUCCESS', 2985.0, job_id=job_b),
                self._task_marker(self.SID, 'rep-muid-after-b', self.now - 2980.0),
                self._m('SUCCESS', 2000.0),
            ],
            extra_ledger=(f'JOB:{job_b}:created:{self.now - 2900.0:.0f}.000',),
        )
        t1 = self._tick(fx)
        self.assertEqual(t1['rc'], 0, t1['output'])
        owners = {}
        for argv in self._main_completions_for(t1['new'], self.SID):
            flags = argv_to_flags(argv)
            # --transaction-id is <sid>-<total_tokens>-<muid>; muids contain '-'.
            muid = flags['--transaction-id'][len(self.SID) + 1:].split('-', 1)[1]
            owners[muid] = flags.get('--agentic-job-id')
        self.assertEqual(owners.get('rep-muid-after-b'), job_b, f"{owners!r}\n{t1['output']}")
        self.assertEqual(owners.get('rep-muid-0001'), JOB, owners)

