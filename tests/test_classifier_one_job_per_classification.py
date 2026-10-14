"""Regression tests for "one classification, one job" (diagnosed on the `ent`
profile, 2026-10-13: a job shown as "No traces found for this job", with no
total cost and no job value).

The defect: first-pass job inference (`run_classification_async` Step 7)
persisted EVERY arc the model reported. The reporter attributes spend
positionally -- a task marker belongs to the first job marker after it, else the
nearest one before it -- and a root session has exactly one classification (a
permanent latch) that is written BEFORE any job. So every task marker bound to
job #1, and jobs #2..N owned nothing: Revenium got a job with no traces, no cost
and, when SUCCESS, a second evaluator call that had nothing of its own to
value. The ent session wrote `revenium_x_intelligence_scan_9736` and
`update_x_radar_skill_848c` from one classification; every completion shipped
with the first.

The fix is at the producer. `_fold_jobs_into_one` reduces the validated jobs to
the FIRST one, which keeps its id, type and status; the other arcs' names ride in
its job name. The job's status is the primary arc's, whatever the siblings came
back as (diagnosed on `ent`, 2026-10-14: an earlier rule demoted a SUCCESS
primary to CANCELLED when any sibling was not a clear SUCCESS, so one
unconfirmed side task kept a finished job from being valued). Nothing in the
reporter or the marker schema changes.

Pinned here:
  * the fold itself (identity, name budget, status = the primary's, purity);
  * Step 7 end to end: the built-in LLM path AND a registered classification
    boundary implementation both yield one marker, one taxonomy entry and one
    evaluator call;
  * the fold log line carries the per-arc statuses (nothing else records them);
  * the re-judge sees the folded job as one arc, and is told its status is the
    main goal's, so it cannot hold the job back on a folded-in goal;
  * the whole chain with the REAL reporter: one `jobs create`, every shipped
    completion linked to that one job.

Own isolated-import idiom: `_LOAD_SEQ` / `_ENV_TOUCHED` / `_ENV_SAVED`,
`setUpModule`, `_restore_env`, `tearDownModule` and `_load_classifier` are
DUPLICATED, not imported, from tests/test_classifier_premature_cancel.py, for the
same reason that module gives (importing another module's copies couples this
one to its import-time env mutation). This module's prefix is `onejob_pkg`.
"""
import asyncio
import copy
import importlib.util
import json
import os
import shutil
import sqlite3
import sys as _sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests._compat_helpers import ROOT, argv_to_flags
# Module import, not class import: a TestCase class bound at module level is
# collected and re-run by unittest discovery.
from tests import test_job_lifecycle_phantom_jobs as lc

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
    for cached in [k for k in list(_sys.modules) if k.startswith('onejob_pkg')]:
        del _sys.modules[cached]


def _load_classifier(env=None):
    """Import the revenium-classifier plugin fresh; return (classifier, evaluators)."""
    for k, v in (env or {}).items():
        os.environ[k] = v
        _ENV_TOUCHED.add(k)
    _LOAD_SEQ[0] += 1
    name = f'onejob_pkg_{_LOAD_SEQ[0]}'
    for cached in [k for k in _sys.modules if k.startswith('onejob_pkg')]:
        del _sys.modules[cached]
    spec = importlib.util.spec_from_file_location(
        name, str(PLUGIN_DIR / '__init__.py'), submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    _sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return _sys.modules[f'{name}.classifier'], _sys.modules[f'{name}.evaluators']


def _resp(content, model='claude-sonnet-4-6'):
    """A call_llm return value: `.choices[0].message.content`, plus a REAL string
    `.model` (a MagicMock auto-attribute would not survive _resolve_served_model)."""
    r = mock.MagicMock()
    r.choices = [mock.MagicMock()]
    r.choices[0].message.content = content
    r.model = model
    return r


def _llm_patch(c, responses):
    """Patch `c.call_llm` to return `responses` in order. NOT a bare
    side_effect=list: an exhausted list raises StopIteration, which
    asyncio.to_thread cannot deliver into its Future, so a regression that makes
    one call too many would hang the suite instead of failing the test."""
    queue = list(responses)

    def next_response(**kwargs):
        if not queue:
            raise RuntimeError('call_llm called more times than this trigger expects')
        return queue.pop(0)

    return mock.patch.object(c, 'call_llm', side_effect=next_response)


def _read_jsonl(path):
    out = []
    if not Path(path).is_file():
        return out
    for line in Path(path).read_text().splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _arc(label, status='SUCCESS', job_type='research', name=None, **extra):
    """One arc as the MODEL reports it (pre-validation, no entropy suffix)."""
    return {'agentic_job_id': label,
            'job_name': label.replace('_', ' ').capitalize() if name is None else name,
            'job_type': job_type, 'status': status, **extra}


def _valid(label, status='SUCCESS', job_type='research', name=None, failure_reason=''):
    """One arc as _validate_job returns it (what _fold_jobs_into_one receives)."""
    return {'agentic_job_id': label + '_ab12',
            'job_name': label.replace('_', ' ').capitalize() if name is None else name,
            'job_type': job_type, 'status': status, 'failure_reason': failure_reason}


def _verdicts(*pairs):
    return json.dumps([{'index': i, 'status': s} for i, s in pairs])


EVAL_PAYLOAD = {
    'economic_mechanism': 'labor_substitution', 'inferred_role': 'engineer',
    'estimated_hours_saved': 1.0, 'assumed_loaded_rate': 100.0, 'currency': 'USD',
    'basis': 'stub', 'confidence': 0.6,
}
EVAL_ON = {
    'enabled': True, 'evaluator': 'onejob-stub', 'currency': 'USD',
    'experimentalReportEstimates': True, 'reportModelEstimates': True,
}
TRANSCRIPT = 'user: run the radar\nassistant: scanning and updating\ntool: done'

# The ent session's two arcs, as the model reported them.
SCAN_CANCELLED = _arc('revenium_x_intelligence_scan', 'CANCELLED', 'research',
                      'Scan X for Revenium market and competitive intelligence')
UPDATE_SUCCESS = _arc('update_x_radar_skill', 'SUCCESS', 'skill_authoring',
                      'Update the X intelligence radar skill')


def _serialized_len(value):
    return len(json.dumps(value, ensure_ascii=True).encode('utf-8')) - 2


# ---------------------------------------------------------------------------
# The fold, in isolation
# ---------------------------------------------------------------------------

class FoldJobsUnitTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.c, _ = _load_classifier({
            'HERMES_HOME': tempfile.mkdtemp(prefix='gsd-onejob-unit-'),
        })

    @classmethod
    def tearDownClass(cls):
        _restore_env()

    def test_no_jobs_stay_no_jobs(self):
        self.assertEqual(self.c._fold_jobs_into_one([]), [])

    def test_a_single_job_is_returned_untouched(self):
        """The overwhelmingly common verdict must be byte-identical to before the
        fold existed: the same list, the same dict, no name edit or clamp (not
        even of a `|` the reporter strips later)."""
        jobs = [_valid('only_arc', name='Has a | pipe and a very long name ' * 4)]
        result = self.c._fold_jobs_into_one(jobs)
        self.assertIs(result, jobs)
        self.assertEqual(result[0]['job_name'], 'Has a | pipe and a very long name ' * 4)

    def test_two_jobs_become_one_with_the_first_ones_identity(self):
        first, second = _valid('scan_x', 'SUCCESS', 'research', 'Scan X'), \
            _valid('update_skill', 'SUCCESS', 'skill_authoring', 'Update skill')
        [folded] = self.c._fold_jobs_into_one([first, second])
        self.assertEqual(folded['agentic_job_id'], first['agentic_job_id'])
        self.assertEqual(folded['job_type'], 'research')
        self.assertEqual(folded['status'], 'SUCCESS')
        self.assertEqual(folded['job_name'], 'Scan X (also: Update skill)')

    def test_the_first_arc_wins_not_the_most_successful_one(self):
        """The one classification describes the opening request, and the model
        lists arcs in transcript order: the first arc is primary even when a
        later one looks better."""
        [folded] = self.c._fold_jobs_into_one([
            _valid('opening_request', 'CANCELLED'), _valid('later_request', 'SUCCESS')])
        self.assertEqual(folded['agentic_job_id'], 'opening_request_ab12')

    def test_three_jobs_name_every_folded_arc_in_order(self):
        [folded] = self.c._fold_jobs_into_one([
            _valid('a', name='Alpha'), _valid('b', name='Beta'), _valid('c', name='Gamma')])
        self.assertEqual(folded['job_name'], 'Alpha (also: Beta; Gamma)')

    def test_the_input_is_not_mutated(self):
        jobs = [_valid('a', 'SUCCESS', name='Alpha'), _valid('b', 'FAILED', name='Beta',
                                                             failure_reason='boom')]
        before = copy.deepcopy(jobs)
        self.c._fold_jobs_into_one(jobs)
        self.assertEqual(jobs, before)

    def test_the_job_takes_the_primarys_status_whatever_the_siblings_are(self):
        """The folded-in arcs own cost and add a name; they never vote on the
        status. Every primary x sibling combination keeps the primary's."""
        for primary in ('SUCCESS', 'CANCELLED', 'FAILED'):
            for siblings in (('SUCCESS',), ('CANCELLED',), ('FAILED',),
                             ('SUCCESS', 'CANCELLED'), ('FAILED', 'FAILED', 'SUCCESS')):
                with self.subTest(primary=primary, siblings=siblings):
                    jobs = [_valid('p', primary, failure_reason='primary broke'
                                   if primary == 'FAILED' else '')]
                    jobs += [_valid('s%d' % i, s, failure_reason='sibling broke'
                                    if s == 'FAILED' else '') for i, s in enumerate(siblings)]
                    [folded] = self.c._fold_jobs_into_one(jobs)
                    self.assertEqual(folded['status'], primary)

    def test_a_success_primary_is_not_demoted_by_an_unconfirmed_sibling(self):
        """The incident rule, inverted. A SUCCESS primary with a CANCELLED or
        FAILED sibling used to become CANCELLED (never evaluated, so no value)."""
        for sibling in ('CANCELLED', 'FAILED'):
            with self.subTest(sibling=sibling):
                [folded] = self.c._fold_jobs_into_one([
                    _valid('p', 'SUCCESS', name='Main goal'),
                    _valid('s', sibling, name='Side task',
                           failure_reason='side task broke' if sibling == 'FAILED' else '')])
                self.assertEqual(folded['status'], 'SUCCESS')
                self.assertEqual(folded['job_name'], 'Main goal (also: Side task)')

    def test_a_failed_primary_keeps_its_own_reason(self):
        [folded] = self.c._fold_jobs_into_one([
            _valid('p', 'FAILED', failure_reason='tests failed'), _valid('s', 'SUCCESS')])
        self.assertEqual(folded['status'], 'FAILED')
        self.assertEqual(folded['failure_reason'], 'tests failed')

    def test_a_siblings_failure_reason_is_not_carried_onto_the_job(self):
        """A sibling's FAILED reason must not leak onto a job that is not FAILED:
        the reporter ships a SUCCESS or CANCELLED arc's own fixed explanation, and
        _validate_job's rule is that only a FAILED arc has a reason. The sibling
        is still named in the job name."""
        for primary in ('SUCCESS', 'CANCELLED'):
            with self.subTest(primary=primary):
                [folded] = self.c._fold_jobs_into_one([
                    _valid('p', primary, name='Main goal'),
                    _valid('s', 'FAILED', name='Side task', failure_reason='sibling broke')])
                self.assertEqual(folded['status'], primary)
                self.assertEqual(folded['failure_reason'], '')
                self.assertIn('Side task', folded['job_name'])

    def test_the_folded_name_never_exceeds_its_budget(self):
        budget = self.c.JOB_FOLD_NAME_MAX_BYTES
        names = ['Alpha arc ' + 'x' * 40, 'Beta arc ' + 'y' * 40, 'Gamma arc ' + 'z' * 40,
                 'Delta arc ' + 'w' * 40]
        [folded] = self.c._fold_jobs_into_one(
            [_valid('p', name='Primary arc')] + [_valid('e%d' % i, name=n)
                                                  for i, n in enumerate(names)])
        name = folded['job_name']
        self.assertLessEqual(_serialized_len(name), budget, name)
        self.assertTrue(name.startswith('Primary arc (also: '), name)
        # Trailing names are dropped WHOLE and the loss is counted, never cut.
        self.assertRegex(name, r'; \+\d+ more\)$')
        for kept in name[len('Primary arc (also: '):].split('; ')[:-1]:
            self.assertIn(kept, names)

    def test_a_primary_with_no_room_is_returned_unchanged(self):
        """Folding must never make a name worse than the model's own, and never
        truncates it."""
        long_primary = 'P' * (self.c.JOB_FOLD_NAME_MAX_BYTES + 10)
        [folded] = self.c._fold_jobs_into_one([
            _valid('p', name=long_primary), _valid('s', name='Second')])
        self.assertEqual(folded['job_name'], long_primary)

    def test_when_no_extra_name_fits_only_the_count_is_appended(self):
        primary = 'P' * (self.c.JOB_FOLD_NAME_MAX_BYTES - 15)
        [folded] = self.c._fold_jobs_into_one([
            _valid('p', name=primary), _valid('s1', name='S' * 50), _valid('s2', name='T' * 50)])
        self.assertEqual(folded['job_name'], primary + ' (+2 more)')

    def test_delimiters_in_a_folded_name_are_neutralised(self):
        """Folded names are model free text on the way into a job row the reporter
        parses with IFS='|': a pipe or newline must not survive."""
        [folded] = self.c._fold_jobs_into_one([
            _valid('p', name='Primary'), _valid('s', name='Sec|ond\nline\rhere')])
        for bad in ('|', '\n', '\r'):
            self.assertNotIn(bad, folded['job_name'])
        self.assertIn('Sec ond line here', folded['job_name'])

    def test_a_non_ascii_name_is_measured_as_it_is_serialized(self):
        """Marker lines are written ensure_ascii=True, so one CJK character costs
        six bytes: a character count would admit a name 6x over budget."""
        [folded] = self.c._fold_jobs_into_one([
            _valid('p', name='Primary'), _valid('s', name='漢' * 40)])
        self.assertLessEqual(_serialized_len(folded['job_name']), self.c.JOB_FOLD_NAME_MAX_BYTES)

    def test_a_restated_arc_is_not_named_twice(self):
        """A model that reports one arc twice gives two identical names; the job
        name says it once. Compared case-insensitively, primary included."""
        [folded] = self.c._fold_jobs_into_one([
            _valid('p', name='Scan X'), _valid('s1', name='scan x'),
            _valid('s2', name='Update skill'), _valid('s3', name='UPDATE SKILL')])
        self.assertEqual(folded['job_name'], 'Scan X (also: Update skill)')

    def test_folding_arcs_with_only_duplicate_names_leaves_the_name_alone(self):
        [folded] = self.c._fold_jobs_into_one([
            _valid('p', name='Scan X'), _valid('s', name='Scan X')])
        self.assertEqual(folded['job_name'], 'Scan X')
        self.assertEqual(folded['agentic_job_id'], 'p_ab12')

    def test_an_unnamed_arc_is_described_by_its_type(self):
        [folded] = self.c._fold_jobs_into_one([
            _valid('p', name='Primary'), _valid('s', job_type='skill_authoring', name='')])
        self.assertEqual(folded['job_name'], 'Primary (also: skill authoring)')

    def test_an_unnamed_primary_is_named_by_its_type(self):
        [folded] = self.c._fold_jobs_into_one([
            _valid('p', job_type='research', name=''), _valid('s', name='Second')])
        self.assertEqual(folded['job_name'], 'research (also: Second)')


# ---------------------------------------------------------------------------
# Step 7, through run_classification_async
# ---------------------------------------------------------------------------

class _Harness(unittest.TestCase):
    SID = 'onejob-root-sid-0001'

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gsd-onejob-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(_restore_env)
        self.hermes_home = os.path.join(self.tmp, 'hh')
        self.state_dir = os.path.join(self.hermes_home, 'state', 'revenium')
        self.markers_dir = os.path.join(self.state_dir, 'markers')
        self.assessments_dir = os.path.join(self.state_dir, 'job-assessments')
        os.makedirs(self.markers_dir, mode=0o700)

    def _load(self, eval_cfg=EVAL_ON):
        """Fresh classifier bound to this tmp tree, with a stub evaluator that
        records every job it is asked to value in `self.evaluated`."""
        cfg = {} if eval_cfg is None else {'llmOutcomeEvaluation': dict(eval_cfg)}
        with open(os.path.join(self.state_dir, 'config.json'), 'w') as f:
            json.dump(cfg, f)
        c, ev = _load_classifier({
            'HERMES_HOME': self.hermes_home, 'REVENIUM_STATE_DIR': self.state_dir,
        })
        self.evaluated = []

        def stub(job, transcript, cfg):
            self.evaluated.append(job['agentic_job_id'])
            return dict(EVAL_PAYLOAD)

        ev.register('onejob-stub', stub)
        return c

    def _trigger(self, c, responses, sid=None, transcript=TRANSCRIPT):
        sid = sid or self.SID
        with _llm_patch(c, responses) as llm, \
             mock.patch.object(c, '_read_session_transcript', return_value=transcript):
            asyncio.run(c.run_classification_async(
                session_id=sid, message='run the radar', response='on it'))
        return llm

    def _first_pass(self, c, arcs, sid=None):
        llm = self._trigger(c, [_resp('x_competitive_intelligence_scan'),
                                _resp(json.dumps(arcs))], sid=sid)
        return llm

    def _records(self, sid=None):
        return _read_jsonl(os.path.join(self.markers_dir, f'{sid or self.SID}.jsonl'))

    def _job_markers(self, sid=None):
        return [r for r in self._records(sid) if r.get('kind') == 'job']

    def _sidecar_records(self):
        out = []
        if os.path.isdir(self.assessments_dir):
            for name in sorted(os.listdir(self.assessments_dir)):
                out.extend(_read_jsonl(os.path.join(self.assessments_dir, name)))
        return out

    def _job_taxonomy_labels(self):
        path = os.path.join(self.state_dir, 'job-taxonomy.json')
        if not os.path.isfile(path):
            return set()
        with open(path) as f:
            return set(json.load(f).get('labels', {}))


class OneClassificationOneJobTests(_Harness):

    def test_the_ent_session_two_arcs_write_one_job_marker(self):
        """The incident, exactly: a CANCELLED scan and a SUCCESS skill update
        from one classification. Before the fix this wrote two markers and the
        second job owned nothing."""
        c = self._load()
        llm = self._first_pass(c, [SCAN_CANCELLED, UPDATE_SUCCESS])
        self.assertEqual(llm.call_count, 2, 'one task call + one job-inference call')

        [job] = self._job_markers()
        self.assertRegex(job['agentic_job_id'], r'^revenium_x_intelligence_scan_[0-9a-f]{4}$')
        self.assertEqual(job['job_type'], 'research')
        # CANCELLED primary stays CANCELLED: a sibling's SUCCESS never promotes it.
        self.assertEqual(job['status'], 'CANCELLED')
        self.assertEqual(
            job['job_name'],
            'Scan X for Revenium market and competitive intelligence '
            '(also: Update the X intelligence radar skill)')
        self.assertLessEqual(_serialized_len(job['job_name']), 120)

    def test_the_one_job_marker_sits_below_every_task_marker(self):
        """The property the reporter's positional rule needs: with every task
        marker above the one job, the forward rule binds all of them to it."""
        c = self._load()
        self._first_pass(c, [SCAN_CANCELLED, UPDATE_SUCCESS])
        records = self._records()
        job_at = [i for i, r in enumerate(records) if r.get('kind') == 'job']
        task_at = [i for i, r in enumerate(records) if r.get('kind') is None]
        self.assertEqual(len(job_at), 1)
        self.assertEqual(len(task_at), 2, 'the GUARDRAIL + CHAT pair')
        self.assertGreater(min(job_at), max(task_at))

    def test_two_success_arcs_are_valued_once(self):
        """The second job used to cost its own evaluator call, on the same
        transcript, and abstained (the ent 848c sidecar). One job, one call, one
        sidecar record."""
        c = self._load()
        self._first_pass(c, [_arc('first_report', name='First report'),
                             _arc('second_report', name='Second report')])
        [job] = self._job_markers()
        self.assertEqual(job['status'], 'SUCCESS')
        self.assertEqual(self.evaluated, [job['agentic_job_id']])
        sidecar = self._sidecar_records()
        self.assertEqual(len(sidecar), 1, sidecar)
        self.assertEqual(sidecar[0]['double_counting_group'], self.SID)
        self.assertIn('assessment', job)

    def test_a_success_primary_with_an_unconfirmed_sibling_is_valued_once(self):
        """The job is the primary's: SUCCESS with one evaluator call and one
        valued sidecar record, the sibling only named in the job name. (It used
        to be demoted to CANCELLED, which is never evaluated, and shipped with
        no value.)"""
        c = self._load()
        self._first_pass(c, [_arc('first_report', 'SUCCESS'),
                             _arc('second_report', 'CANCELLED')])
        [job] = self._job_markers()
        self.assertEqual(job['status'], 'SUCCESS')
        self.assertEqual(job['job_name'], 'First report (also: Second report)')
        self.assertEqual(self.evaluated, [job['agentic_job_id']])
        self.assertIn('assessment', job)
        [record] = self._sidecar_records()
        self.assertEqual(record['execution_status'], 'SUCCESS')
        self.assertEqual(record['abstention_reason'], '')
        self.assertEqual(record['value_base'], 100.0)

    def test_a_cancelled_primary_stays_cancelled_whatever_the_sibling_says(self):
        """The mirror: a sibling's SUCCESS never promotes a primary the model
        was not sure of. It is not evaluated; the re-judge settles it later."""
        c = self._load()
        self._first_pass(c, [_arc('first_report', 'CANCELLED'),
                             _arc('second_report', 'SUCCESS')])
        [job] = self._job_markers()
        self.assertEqual(job['status'], 'CANCELLED')
        self.assertEqual(self.evaluated, [])
        self.assertNotIn('assessment', job)
        [record] = self._sidecar_records()
        self.assertEqual(record['abstention_reason'], 'not_evaluated_non_success')

    def test_the_fold_log_line_carries_the_per_arc_statuses(self):
        """The fold takes the primary's status, so 'what did the model say for
        each arc' is the first question about a surprising job status, and no
        other record holds it (the ent incident could not be settled without it)."""
        c = self._load()
        with self.assertLogs('revenium_classifier', level='INFO') as logs:
            self._first_pass(c, [_arc('first_report', 'SUCCESS'),
                                 _arc('second_report', 'CANCELLED'),
                                 _arc('third_report', 'FAILED')])
        [line] = [m for m in logs.output if 'folded' in m]
        self.assertIn('folded 3 inferred arcs (statuses SUCCESS,CANCELLED,FAILED) '
                      'into one job (status SUCCESS)', line)

    def test_only_the_surviving_jobs_type_enters_the_job_taxonomy(self):
        """A type that labels no job is vocabulary noise."""
        c = self._load()
        self._first_pass(c, [SCAN_CANCELLED, UPDATE_SUCCESS])
        labels = self._job_taxonomy_labels()
        self.assertIn('research', labels)
        self.assertNotIn('skill_authoring', labels)

    def test_a_registered_classification_implementation_is_folded_too(self):
        """The invariant must not depend on WHO produced the list: a boundary
        implementation answering kind="jobs" can return any number."""
        c = self._load()
        calls = []

        def impl(request, cfg):
            calls.append(request['kind'])
            if request['kind'] == 'task_type':
                return {'task_type': 'x_competitive_intelligence_scan'}
            return {'jobs': [_arc('alpha_arc'), _arc('beta_arc'), _arc('gamma_arc')]}

        with mock.patch.object(c, '_resolve_classification_impl', return_value=(impl, 'fake')):
            self._trigger(c, [])
        self.assertEqual(calls, ['task_type', 'jobs'])
        [job] = self._job_markers()
        self.assertRegex(job['agentic_job_id'], r'^alpha_arc_[0-9a-f]{4}$')
        self.assertEqual(job['job_name'], 'Alpha arc (also: Beta arc; Gamma arc)')

    def test_the_first_VALID_arc_is_the_primary(self):
        """An arc that fails validation is dropped before the fold, so it can
        neither be primary nor take the slot of a valid one."""
        c = self._load()
        self._first_pass(c, [_arc('bad_type', job_type='Not A Valid Label!'),
                             _arc('good_one', job_type='research')])
        [job] = self._job_markers()
        self.assertRegex(job['agentic_job_id'], r'^good_one_[0-9a-f]{4}$')
        self.assertEqual(job['job_name'], 'Good one')

    def test_a_fold_failure_still_writes_exactly_one_job(self):
        """The invariant is what must hold; the folded name is polish. A fold
        that raises degrades to the first job alone, never to N and never to
        none, and never out of run_classification_async."""
        c = self._load()
        with mock.patch.object(c, '_fold_jobs_into_one', side_effect=RuntimeError('boom')):
            self._first_pass(c, [SCAN_CANCELLED, UPDATE_SUCCESS])
        [job] = self._job_markers()
        self.assertRegex(job['agentic_job_id'], r'^revenium_x_intelligence_scan_[0-9a-f]{4}$')

    def test_a_single_arc_marker_is_unchanged(self):
        """The common verdict: the same frozen marker shape, the model's own
        name, no fold."""
        c = self._load(eval_cfg=None)
        self._first_pass(c, [UPDATE_SUCCESS])
        [job] = self._job_markers()
        self.assertEqual(
            set(job),
            {'kind', 'ts', 'sid', 'agentic_job_id', 'job_name', 'job_type', 'status'})
        self.assertEqual(job['job_name'], 'Update the X intelligence radar skill')
        self.assertEqual(job['status'], 'SUCCESS')

    def test_feature_off_a_folded_job_writes_a_marker_and_no_sidecar(self):
        c = self._load(eval_cfg=None)
        self._first_pass(c, [_arc('first_report'), _arc('second_report')])
        self.assertEqual(len(self._job_markers()), 1)
        self.assertEqual(self._sidecar_records(), [])
        self.assertFalse(os.path.isdir(self.assessments_dir))

    def test_a_second_trigger_does_not_infer_jobs_again(self):
        """The once-per-session latch is what makes the first pass the only
        place jobs are created; a later trigger must not add one."""
        c = self._load()
        self._first_pass(c, [SCAN_CANCELLED, UPDATE_SUCCESS])
        with mock.patch.object(c, '_infer_jobs_via_llm',
                               new=mock.AsyncMock(return_value=[])) as infer:
            self._trigger(c, [_resp(_verdicts((1, 'CANCELLED')))])
        infer.assert_not_called()
        self.assertEqual(len(self._job_markers()), 1)

    def test_the_rejudge_sees_the_folded_job_as_one_arc_with_a_main_goal(self):
        """The folded name is what the re-judge shows the model, so it can see
        everything the job covers; and it is told the job's status is its MAIN
        goal's, so a folded-in goal it cannot verify does not hold a finished job
        at CANCELLED (the fold gives the job the primary's status, and the
        re-judge is the other writer of that status). It moves ONE job and mints
        no id."""
        c = self._load()
        self._first_pass(c, [SCAN_CANCELLED, UPDATE_SUCCESS])
        [first] = self._job_markers()
        prompts = []

        def spy(**kwargs):
            prompts.append(kwargs['messages'][-1]['content'])
            if len(prompts) == 1:
                return _resp(_verdicts((1, 'SUCCESS')))
            return _resp(json.dumps(EVAL_PAYLOAD))

        with mock.patch.object(c, 'call_llm', side_effect=spy), \
             mock.patch.object(c, '_read_session_transcript', return_value=TRANSCRIPT):
            asyncio.run(c.run_classification_async(
                session_id=self.SID, message='m', response='r'))

        arcs_block = prompts[0].split('Arcs to re-check:')[1].split('An arc whose name')[0]
        self.assertEqual(arcs_block.count('(type:'), 1, arcs_block)
        self.assertIn('Scan X for Revenium', arcs_block)
        self.assertIn('Update the X intelligence radar skill', arcs_block)
        self.assertIn('Decide such an arc\'s status from its main goal alone', prompts[0])
        after = self._job_markers()
        self.assertEqual([r['status'] for r in after], ['CANCELLED', 'SUCCESS'])
        self.assertEqual({r['agentic_job_id'] for r in after}, {first['agentic_job_id']})
        self.assertEqual(self.evaluated, [first['agentic_job_id']])


class FoldedNameDetectionTests(unittest.TestCase):
    """`_is_folded_job_name` recognises exactly the suffixes `_fold_job_name`
    writes, and the re-judge prompt carries its main-goal instruction only for
    such a name (a plain job's prompt is unchanged)."""

    @classmethod
    def setUpClass(cls):
        cls.c, _ = _load_classifier({
            'HERMES_HOME': tempfile.mkdtemp(prefix='gsd-onejob-names-'),
        })

    @classmethod
    def tearDownClass(cls):
        _restore_env()

    def test_every_suffix_the_fold_writes_is_recognised(self):
        c = self.c
        for names in (
            [_valid('p', name='Main goal'), _valid('s', name='Side task')],
            [_valid('p', name='Main goal'), _valid('a', name='A'), _valid('b', name='B')],
            [_valid('p', name='P' * (c.JOB_FOLD_NAME_MAX_BYTES - 15)),
             _valid('a', name='S' * 50), _valid('b', name='T' * 50)],  # "(+2 more)" only
            [_valid('p', name='Main goal')] + [
                _valid('e%d' % i, name='Extra arc number %d ' % i + 'x' * 40) for i in range(4)],
        ):
            [folded] = c._fold_jobs_into_one(names)
            with self.subTest(name=folded['job_name']):
                self.assertTrue(c._is_folded_job_name(folded['job_name']), folded['job_name'])

    def test_a_plain_or_unchanged_name_is_not_folded(self):
        c = self.c
        for name in ('Main goal', '', None, 42, 'Main goal (also:', 'Main goal (also: x',
                     'Fix the (also: shown) label in the footer, then more'):
            with self.subTest(name=name):
                self.assertFalse(c._is_folded_job_name(name))
        # A fold that leaves the name alone (duplicate names) is not folded either.
        [same] = c._fold_jobs_into_one([_valid('p', name='Scan X'), _valid('s', name='scan x')])
        self.assertFalse(c._is_folded_job_name(same['job_name']))

    def test_the_main_goal_instruction_appears_only_for_a_folded_arc(self):
        c = self.c
        plain = c._build_rejudge_prompt(TRANSCRIPT, [{
            'job_name': 'Scan X', 'job_type': 'research'}])
        folded = c._build_rejudge_prompt(TRANSCRIPT, [{
            'job_name': 'Scan X (also: Update the skill)', 'job_type': 'research'}])
        self.assertNotIn('main goal', plain)
        self.assertIn('Decide such an arc\'s status from its main goal alone', folded)
        # The instruction sits between the arc list and the output spec; nothing
        # else in the prompt moves.
        self.assertEqual(
            folded.replace(folded[folded.index('An arc whose name'):folded.index('Output ONLY')], '')
                  .replace('Scan X (also: Update the skill)', 'Scan X'),
            plain)

    def test_one_folded_arc_among_plain_ones_adds_the_instruction_once(self):
        prompt = self.c._build_rejudge_prompt(TRANSCRIPT, [
            {'job_name': 'Plain job', 'job_type': 'research'},
            {'job_name': 'Main (+3 more)', 'job_type': 'research'},
            {'job_name': 'Another (also: x)', 'job_type': 'research'},
        ])
        self.assertEqual(prompt.count('Decide such an arc\'s status from its main goal alone'), 1)


# ---------------------------------------------------------------------------
# The whole chain, with the real reporter
# ---------------------------------------------------------------------------

class OneJobEndToEndTests(lc._LifecycleHarness):
    """The ent-profile sequence with nothing hand-authored between the halves:
    the REAL classifier (only call_llm stubbed) writes the markers, a REAL
    hermes-report.sh tick reads them. Before the fix the first tick ran
    `jobs create` for two ids and every completion carried the first; the
    second job never owned a trace."""

    SID = 'onejob-e2e-sid-0001'
    CFG = {'llmOutcomeEvaluation': {
        'enabled': True, 'experimentalReportEstimates': True,
        'reportModelEstimates': True, 'currency': 'USD',
        'maxHoursSaved': 40, 'maxLoadedRate': 500,
    }}

    def _build(self):
        fx = self._fixture([self._session(self.SID, ended_ago=None)])
        conn = sqlite3.connect(fx['state_db'])
        try:
            conn.execute(
                'CREATE TABLE messages (session_id TEXT, role TEXT, content TEXT, '
                'tool_calls TEXT, timestamp INTEGER)')
            for i, (role, content) in enumerate((
                ('user', 'Run intelligence radar #4'),
                ('assistant', 'Scanning X and updating the radar skill.'),
                ('assistant', 'Done: scan complete, skill updated.'),
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
                session_id=self.SID, message='run the radar', response='on it'))
        return llm

    def _job_records(self, fx):
        path = os.path.join(fx['markers_dir'], f'{self.SID}.jsonl')
        return [r for r in _read_jsonl(path) if r.get('kind') == 'job']

    def test_one_classification_creates_one_job_and_every_completion_links_to_it(self):
        fx, c = self._build()
        llm = self._trigger(c, [_resp('x_competitive_intelligence_scan'),
                                _resp(json.dumps([SCAN_CANCELLED, UPDATE_SUCCESS]))])
        self.assertEqual(llm.call_count, 2)
        [marker] = self._job_records(fx)
        job_id = marker['agentic_job_id']

        t1 = self._tick(fx)
        self.assertEqual(t1['rc'], 0, t1['output'])
        created = [argv_to_flags(a).get('--agentic-job-id') for a in self._job_creates(t1['new'])]
        self.assertEqual(created, [job_id], 'exactly one Revenium job for one classification')
        self.assertEqual(
            argv_to_flags(self._job_creates(t1['new'])[0]).get('--name'),
            'Scan X for Revenium market and competitive intelligence '
            '(also: Update the X intelligence radar skill)')

        completions = self._main_completions_for(t1['new'], self.SID)
        self.assertGreaterEqual(len(completions), 1, t1['output'])
        for argv in completions:
            self.assertEqual(argv_to_flags(argv).get('--agentic-job-id'), job_id, argv)
        self._assert_create_precedes_every_reference(t1['all'], job_id)

    def test_the_rejudged_success_ships_one_outcome_with_a_value(self):
        """The incident session, end to end: the folded job is re-judged
        SUCCESS, valued once, and the closed session reports ONE outcome."""
        fx, c = self._build()
        self._trigger(c, [_resp('x_competitive_intelligence_scan'),
                          _resp(json.dumps([SCAN_CANCELLED, UPDATE_SUCCESS]))])
        [marker] = self._job_records(fx)
        job_id = marker['agentic_job_id']
        t1 = self._tick(fx)
        self.assertEqual(self._job_outcomes(t1['new']), [], 'CANCELLED is held while open')

        llm = self._trigger(c, [_resp(_verdicts((1, 'SUCCESS'))), _resp(json.dumps(EVAL_PAYLOAD))])
        self.assertEqual(llm.call_count, 2, 'status re-judge + ONE outcome evaluation')
        self.assertEqual([r['status'] for r in self._job_records(fx)], ['CANCELLED', 'SUCCESS'])

        conn = sqlite3.connect(fx['state_db'])
        try:
            conn.execute('UPDATE sessions SET ended_at = ? WHERE id = ?',
                         (self.now - 10.0, self.SID))
            conn.commit()
        finally:
            conn.close()
        t2 = self._tick(fx)
        self.assertEqual(t2['rc'], 0, t2['output'])
        [outcome] = self._job_outcomes(t2['new'])
        flags = argv_to_flags(outcome)
        self.assertEqual(outcome[2], job_id)
        self.assertEqual(flags.get('--result'), 'SUCCESS')
        self.assertIn('--outcome-value', flags)

        ledger = self._read_ledger(fx, 'revenium-jobs.ledger')
        self.assertEqual(ledger.count(':created:'), 1, ledger)
        self.assertEqual(ledger.count(':outcome:'), 1, ledger)


if __name__ == '__main__':
    unittest.main()
