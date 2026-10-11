"""Regression tests for the three job-lifecycle defects diagnosed on the `ent`
profile on 2026-10-09 (phantom nameless PENDING jobs, lost job names, jobs
CANCELLED while their session was still open).

Each class drives the REAL hermes-report.sh against a synthetic state.db, a
PATH-shimmed `revenium`, and a hand-seeded jobs ledger / marker directory.
All invocations (jobs create, jobs outcome, meter completion) land in ONE
shared log so the tests can assert ORDER, which is the invariant RC-2 is
about: a completion must never reference a job id before `jobs create` for
that id has run.

RC-1  Auxiliary rows must not resurrect a closed (or never-created) job.
      The first tick after an upgrade backfills every session's cumulative
      auxiliary usage -- deliberately -- and each row used to carry the
      session's historical `--agentic-job-id`. Revenium auto-creates a job
      for an id it has never seen, so 151 September jobs reappeared as
      nameless PENDING rows. The link is now only attached when the job is
      created and either still open or closed within the last few minutes
      (the normal same-tick create+outcome+aux flow that Phase 56 pins).

RC-2  A subagent's completion must not reach Revenium before the root's
      `jobs create`. The session query is ORDER BY started_at DESC, so a
      child is always visited before its root; the child's completion
      carried the root's job id first, Revenium auto-created it nameless,
      and the root's later `jobs create` got a 409 (treated as success), so
      name and type were lost for good. The child is now held (no ledger
      write, retried next tick) until the create is ledgered, and ships
      WITHOUT the job id once the root has demonstrably had time to create
      it, so a root that never will (zero tokens, never settles) cannot
      strand the child's spend.

RC-3  A CANCELLED verdict is the classifier's uncertainty catch-all. It must
      not be reported while the session is still open (state.db
      sessions.ended_at IS NULL), because the arc may simply be unfinished.
      SUCCESS / FAILED (evidence-backed) and the deliberate guardrail-halt
      cancel are unaffected, and an abandoned session (open for longer than
      the idle bound) is reported rather than left PENDING forever.
"""
import glob
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
import time
import unittest

from tests._compat_helpers import (
    argv_to_flags,
    build_session_model_usage,
    build_shim,
    build_state_db,
    run_script,
    SCRIPTS_DIR,
    seed_parent_session_ids,
)

ROOT_SID = 'lc-root-sid-0001'
SUB_SID = 'lc-sub-sid-0001'
JOB_ID = 'fix_auth_regression_ab12'


class _LifecycleHarness(unittest.TestCase):
    """One tmp tree per test: state.db, shim, markers, jobs ledger, ONE log."""

    SETTLE_SECONDS = '120'

    def setUp(self):
        self.now = time.time()

    # -- fixture construction -------------------------------------------------

    def _session(self, sid, *, tokens=(100, 50), started_ago=3000.0,
                 ended_ago=2900.0, source='cli'):
        return {
            'id': sid, 'model': 'claude-sonnet-4-6', 'source': source,
            'input_tokens': tokens[0], 'output_tokens': tokens[1],
            'cache_read': 0, 'cache_write': 0, 'reasoning': 0,
            'estimated_cost': '0', 'api_calls': 1,
            'started_at': self.now - started_ago,
            'ended_at': None if ended_ago is None else self.now - ended_ago,
            'billing_provider': 'anthropic',
        }

    def _fixture(self, sessions, parents=None, aux_rows=None):
        tmp = tempfile.mkdtemp(prefix='gsd-job-lifecycle-')
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        hermes_home = os.path.join(tmp, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        markers_dir = os.path.join(state_dir, 'markers')
        os.makedirs(markers_dir, mode=0o700)
        state_db = os.path.join(hermes_home, 'state.db')
        shim_home = os.path.join(tmp, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)

        build_state_db(state_db, sessions)
        # Every measured install has sessions.parent_session_id, and without
        # it the phase-68 root gate cannot confirm a root, so its job link is
        # withheld for a reason unrelated to the lifecycle guards under test.
        seed_parent_session_ids(
            state_db,
            {s['id']: (parents or {}).get(s['id']) for s in sessions},
        )
        if aux_rows:
            build_session_model_usage(state_db, aux_rows)
        build_shim(os.path.join(bin_dir, 'revenium'))

        return {
            'tmp': tmp, 'hermes_home': hermes_home, 'state_dir': state_dir,
            'markers_dir': markers_dir, 'state_db': state_db,
            'shim_home': shim_home, 'bin_dir': bin_dir,
            'inv_log': os.path.join(tmp, 'inv.log'), 'seen': 0,
        }

    @staticmethod
    def _task_marker(sid, muid, ts, trace_id=None):
        rec = {
            'muid': muid, 'ts': ts, 'sid': sid, 'task_type': 'code_fix',
            'operation_type': 'CHAT',
        }
        if trace_id:
            rec['trace_id'] = trace_id
        return rec

    @staticmethod
    def _job_marker(sid, ts, job_id=JOB_ID, status='SUCCESS', job_type='code_fix',
                    job_name='Fix auth regression'):
        return {
            'kind': 'job', 'ts': ts, 'sid': sid, 'agentic_job_id': job_id,
            'job_name': job_name, 'job_type': job_type, 'status': status,
        }

    def _write_markers(self, fx, sid, records):
        path = os.path.join(fx['markers_dir'], f'{sid}.jsonl')
        with open(path, 'w') as f:
            for rec in records:
                f.write(json.dumps(rec, separators=(',', ':')) + '\n')

    def _seed_jobs_ledger(self, fx, lines):
        with open(os.path.join(fx['state_dir'], 'revenium-jobs.ledger'), 'w') as f:
            f.write(''.join(line + '\n' for line in lines))

    def _read_ledger(self, fx, name):
        path = os.path.join(fx['state_dir'], name)
        if not os.path.exists(path):
            return ''
        with open(path) as f:
            return f.read()

    def _read_log(self, fx):
        path = os.path.join(fx['state_dir'], 'revenium-metering.log')
        if not os.path.exists(path):
            return ''
        with open(path) as f:
            return f.read()

    def _make_job_create_fail(self, fx):
        """Wrap the shim so `revenium jobs create` exits 1 (a non-409 failure,
        so the reporter does NOT ledger the create) while every other verb --
        including the `jobs create --help` capability probe -- still reaches
        the real shim."""
        real = os.path.join(fx['bin_dir'], 'revenium')
        moved = real + '.real'
        os.rename(real, moved)
        with open(real, 'w') as f:
            f.write(
                '#!/usr/bin/env bash\n'
                'if [[ "$1" == "jobs" && "$2" == "create" && "$3" != "--help" ]]; then\n'
                '  printf "%q " "$@" >> "${INVOCATIONS_LOG:-/dev/null}"\n'
                '  printf "\\n" >> "${INVOCATIONS_LOG:-/dev/null}"\n'
                '  echo "Error: HTTP 500 internal error" >&2\n'
                '  exit 1\n'
                'fi\n'
                f'exec {shlex.quote(moved)} "$@"\n'
            )
        os.chmod(real, 0o755)

    # -- running + reading ----------------------------------------------------

    def _tick(self, fx, extra_env=None):
        env = {
            **os.environ,
            'HOME': fx['shim_home'],
            'HERMES_HOME': fx['hermes_home'],
            'REVENIUM_STATE_DIR': fx['state_dir'],
            'PATH': fx['bin_dir'] + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': fx['inv_log'],
            'REVENIUM_CRON_SETTLE_SECONDS': self.SETTLE_SECONDS,
            'TZ': 'UTC',
        }
        # ONE shared log: ordering across verbs is part of what is asserted.
        for k in ('METER_LOG', 'JOBS_LOG', 'TOOL_LOG'):
            env.pop(k, None)
        if extra_env:
            env.update(extra_env)
        rc, invocations, output = run_script(
            SCRIPTS_DIR / 'hermes-report.sh', env, fx['inv_log'])
        new = invocations[fx['seen']:]
        fx['seen'] = len(invocations)
        return {'rc': rc, 'output': output, 'all': invocations, 'new': new}

    @staticmethod
    def _is(argv, verb, sub):
        return len(argv) >= 2 and argv[0] == verb and argv[1] == sub

    def _completions(self, invocations):
        return [a for a in invocations if self._is(a, 'meter', 'completion')]

    def _main_completions_for(self, invocations, sid):
        """Main-loop completions of one session: transaction-id is sid-prefixed
        (auxiliary rows use an `aux-` prefix and are excluded)."""
        out = []
        for a in self._completions(invocations):
            tx = argv_to_flags(a).get('--transaction-id', '')
            if isinstance(tx, str) and tx.startswith(f'{sid}-'):
                out.append(a)
        return out

    def _aux_completions(self, invocations):
        return [
            a for a in self._completions(invocations)
            if argv_to_flags(a).get('--operation-type') == 'OTHER'
        ]

    def _job_creates(self, invocations):
        return [a for a in invocations if self._is(a, 'jobs', 'create')]

    def _job_outcomes(self, invocations):
        return [a for a in invocations if self._is(a, 'jobs', 'outcome')]

    def _assert_create_precedes_every_reference(self, invocations, job_id):
        """The RC-2 invariant, over the whole ordered log."""
        create_idx = None
        first_ref_idx = None
        for i, a in enumerate(invocations):
            flags = argv_to_flags(a)
            if self._is(a, 'jobs', 'create') and flags.get('--agentic-job-id') == job_id:
                if create_idx is None:
                    create_idx = i
            if self._is(a, 'meter', 'completion') and flags.get('--agentic-job-id') == job_id:
                if first_ref_idx is None:
                    first_ref_idx = i
        if first_ref_idx is None:
            return
        self.assertIsNotNone(
            create_idx,
            f'a completion referenced job {job_id!r} but `jobs create` never ran')
        self.assertLess(
            create_idx, first_ref_idx,
            f'a completion carried --agentic-job-id {job_id!r} (log index '
            f'{first_ref_idx}) BEFORE `jobs create` for it (index {create_idx}). '
            f'Revenium auto-creates an unseen job nameless and the later create '
            f'409s, losing name/type permanently.\nLog: {invocations}')


# ---------------------------------------------------------------------------
# RC-2
# ---------------------------------------------------------------------------

class SubagentCompletionWaitsForJobCreateTests(_LifecycleHarness):

    def _subagent_fixture(self, *, root_tokens=(100, 50), root_job_marker_ago=2980.0):
        sessions = [
            self._session(ROOT_SID, tokens=root_tokens, started_ago=3000.0, ended_ago=2900.0),
            # Started LATER than its root: ORDER BY started_at DESC visits it FIRST.
            self._session(SUB_SID, tokens=(200, 100), started_ago=2000.0, ended_ago=1900.0),
        ]
        fx = self._fixture(sessions, parents={SUB_SID: ROOT_SID})
        self._write_markers(fx, ROOT_SID, [
            self._task_marker(ROOT_SID, 'rootmuid0001', self.now - 2990.0),
            self._job_marker(ROOT_SID, self.now - root_job_marker_ago),
        ])
        self._write_markers(fx, SUB_SID, [
            self._task_marker(SUB_SID, 'submuid00001', self.now - 1990.0, trace_id=ROOT_SID),
        ])
        return fx

    def test_subagent_completion_is_held_until_the_root_job_is_created(self):
        fx = self._subagent_fixture()

        t1 = self._tick(fx)
        self.assertEqual(t1['rc'], 0, t1['output'])

        # The root's create ran this tick (name + type present: the create is
        # the only call that is guaranteed to carry them).
        creates = self._job_creates(t1['new'])
        self.assertEqual(len(creates), 1, t1['new'])
        cflags = argv_to_flags(creates[0])
        self.assertEqual(cflags.get('--agentic-job-id'), JOB_ID)
        self.assertEqual(cflags.get('--name'), 'Fix auth regression')
        self.assertEqual(cflags.get('--type'), 'code_fix')

        # The invariant itself: nothing referenced the job before the create.
        self._assert_create_precedes_every_reference(t1['all'], JOB_ID)

        # The child was HELD, not shipped-without-link: nothing metered for it,
        # nothing ledgered, so the next tick retries with the full delta.
        self.assertEqual(self._main_completions_for(t1['new'], SUB_SID), [], t1['new'])
        self.assertNotIn(f'HERMES:{SUB_SID}:', self._read_ledger(fx, 'revenium-hermes.ledger'))

        # The root itself still ships on tick 1, linked to its own job.
        root_c = self._main_completions_for(t1['new'], ROOT_SID)
        self.assertEqual(len(root_c), 1, t1['new'])
        self.assertEqual(argv_to_flags(root_c[0]).get('--agentic-job-id'), JOB_ID)

        # Tick 2: the create is ledgered, so the child ships WITH the link.
        t2 = self._tick(fx)
        self.assertEqual(t2['rc'], 0, t2['output'])
        sub_c = self._main_completions_for(t2['new'], SUB_SID)
        self.assertEqual(len(sub_c), 1, t2['new'])
        self.assertEqual(argv_to_flags(sub_c[0]).get('--agentic-job-id'), JOB_ID)
        self.assertEqual(self._job_creates(t2['new']), [], 'create must not repeat')
        self._assert_create_precedes_every_reference(t2['all'], JOB_ID)

        # Tick 3: idempotent -- nothing is reported twice.
        t3 = self._tick(fx)
        self.assertEqual(self._main_completions_for(t3['new'], SUB_SID), [], t3['new'])
        self.assertEqual(self._main_completions_for(t3['new'], ROOT_SID), [], t3['new'])

    def test_already_created_root_job_does_not_delay_the_subagent(self):
        fx = self._subagent_fixture()
        self._seed_jobs_ledger(fx, [f'JOB:{JOB_ID}:created:{self.now - 100:.3f}'])

        t1 = self._tick(fx)
        sub_c = self._main_completions_for(t1['new'], SUB_SID)
        self.assertEqual(len(sub_c), 1, t1['new'])
        self.assertEqual(argv_to_flags(sub_c[0]).get('--agentic-job-id'), JOB_ID)

    def test_unavailable_root_ships_without_the_link_once_it_is_clearly_stale(self):
        # Root has ZERO tokens: the session query never visits it, so nothing
        # will ever create its job. The child must not wait forever.
        fx = self._subagent_fixture(root_tokens=(0, 0), root_job_marker_ago=5000.0)

        t1 = self._tick(fx)
        self.assertEqual(t1['rc'], 0, t1['output'])
        self.assertEqual(self._job_creates(t1['all']), [])
        sub_c = self._main_completions_for(t1['new'], SUB_SID)
        self.assertEqual(len(sub_c), 1, f'spend must still ship: {t1["new"]}')
        self.assertNotIn(
            '--agentic-job-id', sub_c[0],
            'the root job was never created, so the child must not reference it '
            '(that is exactly what makes Revenium mint a nameless job)')
        self.assertIn(f'HERMES:{SUB_SID}:', self._read_ledger(fx, 'revenium-hermes.ledger'))

    def test_a_create_that_keeps_failing_cannot_strand_the_subagent(self):
        # The root IS visited every tick, but its `jobs create` fails every
        # time (e.g. a validation error), so the create is never ledgered. The
        # child must not wait forever for something that is not going to happen.
        fx = self._subagent_fixture()
        self._make_job_create_fail(fx)

        for n in (1, 2):
            t = self._tick(fx)
            self.assertEqual(t['rc'], 0, t['output'])
            self.assertEqual(
                self._main_completions_for(t['new'], SUB_SID), [],
                f'tick {n}: the child is still inside its wait budget: {t["new"]}')
        self.assertNotIn(f'JOB:{JOB_ID}:created:', self._read_ledger(fx, 'revenium-jobs.ledger'))
        # The budget is measured from the FIRST hold and survives across ticks
        # in a flag file; age it past the limit instead of sleeping.
        flags = glob.glob(os.path.join(
            fx['markers_dir'], '.outcome-warn', f'{JOB_ID}__child-hold-since.flag'))
        self.assertEqual(len(flags), 1, flags)
        with open(flags[0], 'w') as f:
            # Hold began long ago AND was renewed a moment ago: continuous.
            f.write(f'{int(self.now) - 100000}\n{int(self.now)}\n')

        t3 = self._tick(fx)
        self.assertEqual(t3['rc'], 0, t3['output'])
        sub_c = self._main_completions_for(t3['new'], SUB_SID)
        self.assertEqual(len(sub_c), 1, f'spend must ship once the wait is exhausted: {t3["new"]}')
        self.assertNotIn(
            '--agentic-job-id', sub_c[0],
            'the create never succeeded; linking would make Revenium mint a nameless job')
        self.assertIn(f'HERMES:{SUB_SID}:', self._read_ledger(fx, 'revenium-hermes.ledger'))
        self.assertIn('WITHOUT --agentic-job-id', self._read_log(fx))

        # And once shipped it is never shipped again.
        t4 = self._tick(fx)
        self.assertEqual(self._main_completions_for(t4['new'], SUB_SID), [], t4['new'])

    def test_a_gap_between_ticks_does_not_expire_the_wait(self):
        # Children are visited BEFORE their root, so on the first tick after a
        # long pause the root has not had its retry yet. A wall-clock budget
        # would expire right there and ship the child unlinked in the very tick
        # the root's create finally succeeds.
        fx = self._subagent_fixture()
        self._make_job_create_fail(fx)
        t1 = self._tick(fx)
        self.assertEqual(self._main_completions_for(t1['new'], SUB_SID), [], t1['new'])
        self.assertNotIn(f'JOB:{JOB_ID}:created:', self._read_ledger(fx, 'revenium-jobs.ledger'))

        # The machine "sleeps" for 15 minutes: nothing renewed the hold.
        flags = glob.glob(os.path.join(
            fx['markers_dir'], '.outcome-warn', f'{JOB_ID}__child-hold-since.flag'))
        self.assertEqual(len(flags), 1, flags)
        gone = int(self.now) - 900
        with open(flags[0], 'w') as f:
            f.write(f'{gone}\n{gone}\n')
        # ...and the API is healthy again when ticks resume.
        bin_dir = fx['bin_dir']
        os.replace(os.path.join(bin_dir, 'revenium.real'), os.path.join(bin_dir, 'revenium'))

        t2 = self._tick(fx)
        self.assertEqual(t2['rc'], 0, t2['output'])
        self.assertEqual(
            self._main_completions_for(t2['new'], SUB_SID), [],
            'the root has not had its turn yet; the child must still be held '
            f'rather than shipped unlinked: {t2["new"]}')
        self.assertEqual(len(self._job_creates(t2['new'])), 1, t2['new'])
        self.assertIn(f'JOB:{JOB_ID}:created:', self._read_ledger(fx, 'revenium-jobs.ledger'))

        t3 = self._tick(fx)
        sub_c = self._main_completions_for(t3['new'], SUB_SID)
        self.assertEqual(len(sub_c), 1, t3['new'])
        self.assertEqual(argv_to_flags(sub_c[0]).get('--agentic-job-id'), JOB_ID)
        self._assert_create_precedes_every_reference(t3['all'], JOB_ID)
        self.assertNotIn('WITHOUT --agentic-job-id', self._read_log(fx))

    def test_two_children_of_one_root_are_both_held_then_both_linked(self):
        sib = 'lc-sub-sid-0002'
        sessions = [
            self._session(ROOT_SID, started_ago=3000.0, ended_ago=2900.0),
            self._session(SUB_SID, tokens=(200, 100), started_ago=2000.0, ended_ago=1900.0),
            self._session(sib, tokens=(300, 150), started_ago=1500.0, ended_ago=1400.0),
        ]
        fx = self._fixture(sessions, parents={SUB_SID: ROOT_SID, sib: ROOT_SID})
        self._write_markers(fx, ROOT_SID, [
            self._task_marker(ROOT_SID, 'rootmuid0001', self.now - 2990.0),
            self._job_marker(ROOT_SID, self.now - 2980.0),
        ])
        for child, muid in ((SUB_SID, 'submuid00001'), (sib, 'submuid00002')):
            self._write_markers(fx, child, [
                self._task_marker(child, muid, self.now - 1990.0, trace_id=ROOT_SID),
            ])
        t1 = self._tick(fx)
        self.assertEqual(len(self._job_creates(t1['new'])), 1, t1['new'])
        self.assertEqual(self._main_completions_for(t1['new'], SUB_SID), [])
        self.assertEqual(self._main_completions_for(t1['new'], sib), [])
        t2 = self._tick(fx)
        for child in (SUB_SID, sib):
            c = self._main_completions_for(t2['new'], child)
            self.assertEqual(len(c), 1, f'{child}: {t2["new"]}')
            self.assertEqual(argv_to_flags(c[0]).get('--agentic-job-id'), JOB_ID)
        self.assertEqual(self._job_creates(t2['new']), [])
        self.assertEqual(self._read_log(fx).count('Subagent completions held'), 1)

    def test_wait_budget_is_configurable(self):
        fx = self._subagent_fixture()
        self._make_job_create_fail(fx)
        t = self._tick(fx, extra_env={'REVENIUM_JOBS_STALE_SECONDS': '0'})
        sub_c = self._main_completions_for(t['new'], SUB_SID)
        self.assertEqual(len(sub_c), 1, t['new'])
        self.assertNotIn('--agentic-job-id', sub_c[0])

    def test_the_hold_is_logged_once_not_every_tick(self):
        fx = self._subagent_fixture(root_tokens=(0, 0), root_job_marker_ago=30.0)
        for _ in range(3):
            self._tick(fx)
        self.assertEqual(self._read_log(fx).count('Subagent completions held'), 1,
                         self._read_log(fx))

    def test_unavailable_root_with_a_fresh_job_marker_is_still_held(self):
        fx = self._subagent_fixture(root_tokens=(0, 0), root_job_marker_ago=30.0)

        for _ in range(2):
            t = self._tick(fx)
            self.assertEqual(t['rc'], 0, t['output'])
            self.assertEqual(self._main_completions_for(t['new'], SUB_SID), [], t['new'])
        self.assertNotIn(f'HERMES:{SUB_SID}:', self._read_ledger(fx, 'revenium-hermes.ledger'))


# ---------------------------------------------------------------------------
# RC-1
# ---------------------------------------------------------------------------

class AuxiliaryRowsDoNotResurrectJobsTests(_LifecycleHarness):

    @staticmethod
    def _aux_row(sid):
        return {
            'session_id': sid, 'model': 'claude-3-5-haiku',
            'billing_provider': 'anthropic', 'billing_base_url': '',
            'billing_mode': '', 'task': 'approval', 'api_call_count': 3,
            'input_tokens': 40, 'output_tokens': 10, 'cache_read_tokens': 0,
            'cache_write_tokens': 0, 'estimated_cost_usd': 0.002,
            'first_seen': 1715514500.0, 'last_seen': 1715514600.0,
        }

    def _single_session_fixture(self, *, job_status='SUCCESS'):
        sid = 'lc-aux-sid-0001'
        fx = self._fixture([self._session(sid)], aux_rows=[self._aux_row(sid)])
        self._write_markers(fx, sid, [
            self._task_marker(sid, 'auxmuid00001', self.now - 2990.0),
            self._job_marker(sid, self.now - 2980.0, status=job_status),
        ])
        return fx, sid

    def _aux_flags(self, tick):
        aux = self._aux_completions(tick['new'])
        self.assertEqual(len(aux), 1, f'expected exactly one aux row: {tick["new"]}')
        return argv_to_flags(aux[0])

    def test_a_job_closed_long_ago_is_not_linked_from_an_aux_row(self):
        # The incident: ledger says created + outcome in September; the
        # first-tick backfill must not re-reference the id.
        fx, _sid = self._single_session_fixture()
        self._seed_jobs_ledger(fx, [
            f'JOB:{JOB_ID}:created:1600000000.000',
            f'JOB:{JOB_ID}:outcome:1600000100.000:SUCCESS',
        ])
        t = self._tick(fx)
        self.assertEqual(t['rc'], 0, t['output'])
        flags = self._aux_flags(t)
        self.assertNotIn(
            '--agentic-job-id', flags,
            'aux backfill carried the id of a long-closed job -- Revenium '
            'would auto-create it as a nameless PENDING job')
        # Spend is still shipped; only the link is withheld.
        self.assertEqual(flags.get('--input-tokens'), '40')
        self.assertEqual(flags.get('--task-type'), 'aux_approval')

    def test_a_job_closed_moments_ago_is_still_linked(self):
        # Phase 56 flow: create + outcome + aux all land in the same tick.
        fx, _sid = self._single_session_fixture()
        self._seed_jobs_ledger(fx, [
            f'JOB:{JOB_ID}:created:{self.now - 60:.3f}',
            f'JOB:{JOB_ID}:outcome:{self.now - 20:.3f}:SUCCESS',
        ])
        t = self._tick(fx)
        self.assertEqual(self._aux_flags(t).get('--agentic-job-id'), JOB_ID)

    def test_the_same_tick_create_and_outcome_flow_still_links_the_aux_row(self):
        fx, _sid = self._single_session_fixture()  # empty ledger, SUCCESS marker
        t = self._tick(fx)
        self.assertEqual(len(self._job_outcomes(t['new'])), 1, t['new'])
        self.assertEqual(self._aux_flags(t).get('--agentic-job-id'), JOB_ID)

    def test_an_open_job_is_linked(self):
        # IN_PROGRESS is not a reportable status, so no outcome is written.
        fx, _sid = self._single_session_fixture(job_status='IN_PROGRESS')
        self._seed_jobs_ledger(fx, [f'JOB:{JOB_ID}:created:1600000000.000'])
        t = self._tick(fx)
        self.assertEqual(self._job_outcomes(t['new']), [])
        self.assertEqual(self._aux_flags(t).get('--agentic-job-id'), JOB_ID)

    def test_first_tick_backfill_of_many_closed_jobs_mints_no_jobs(self):
        # The incident, replayed: several already-reported sessions whose jobs
        # are long closed in the ledger, each with accumulated auxiliary usage
        # the (empty) aux ledger has never shipped.
        sids = [f'lc-hist-sid-{i:04d}' for i in range(5)]
        fx = self._fixture(
            [self._session(sid) for sid in sids],
            aux_rows=[self._aux_row(sid) for sid in sids],
        )
        hermes_ledger = []
        jobs_ledger = []
        for i, sid in enumerate(sids):
            job_id = f'historic_job_{i:04d}'
            self._write_markers(fx, sid, [
                self._task_marker(sid, f'histmuid{i:05d}', self.now - 2990.0),
                self._job_marker(sid, self.now - 2980.0, job_id=job_id),
            ])
            hermes_ledger.append(f'HERMES:{sid}:150:1600000000:histmuid{i:05d}')
            jobs_ledger.append(f'JOB:{job_id}:created:1600000000.000')
            jobs_ledger.append(f'JOB:{job_id}:outcome:1600000100.000:SUCCESS')
        with open(os.path.join(fx['state_dir'], 'revenium-hermes.ledger'), 'w') as f:
            f.write(''.join(line + '\n' for line in hermes_ledger))
        self._seed_jobs_ledger(fx, jobs_ledger)

        t = self._tick(fx)
        self.assertEqual(t['rc'], 0, t['output'])
        aux = self._aux_completions(t['new'])
        self.assertEqual(len(aux), len(sids), f'every aux row still ships: {t["new"]}')
        for argv in aux:
            self.assertNotIn('--agentic-job-id', argv)
        self.assertEqual(self._job_creates(t['new']), [])
        self.assertEqual(self._job_outcomes(t['new']), [])
        self.assertEqual(self._main_completions_for(t['new'], sids[0]), [])
        self.assertIn(f'Aux job link withheld on {len(sids)} row(s)', self._read_log(fx))

        # Idempotent: the aux ledger now covers them, so nothing re-ships.
        t2 = self._tick(fx)
        self.assertEqual(self._aux_completions(t2['new']), [], t2['new'])

    def test_a_job_that_was_never_created_is_not_linked(self):
        # Child of a zero-token root: the root's job is resolved for the aux
        # row, but nothing ever created it.
        fx = self._fixture(
            [
                self._session(ROOT_SID, tokens=(0, 0), started_ago=3000.0, ended_ago=2900.0),
                self._session(SUB_SID, tokens=(200, 100), started_ago=2000.0, ended_ago=1900.0),
            ],
            parents={SUB_SID: ROOT_SID},
            aux_rows=[self._aux_row(SUB_SID)],
        )
        self._write_markers(fx, ROOT_SID, [
            self._job_marker(ROOT_SID, self.now - 5000.0),
        ])
        self._write_markers(fx, SUB_SID, [
            self._task_marker(SUB_SID, 'submuid00002', self.now - 1990.0, trace_id=ROOT_SID),
        ])
        t = self._tick(fx)
        self.assertEqual(t['rc'], 0, t['output'])
        self.assertNotIn('--agentic-job-id', self._aux_flags(t))
        self.assertEqual(self._job_creates(t['all']), [])


# ---------------------------------------------------------------------------
# RC-3
# ---------------------------------------------------------------------------

class OpenSessionCancelledOutcomeTests(_LifecycleHarness):

    SID = 'lc-open-sid-0001'

    def _fixture_with_job(self, *, status, job_id=JOB_ID, job_type='code_fix',
                          ended_ago=None, started_ago=3000.0, failure_reason=None):
        fx = self._fixture([
            self._session(self.SID, started_ago=started_ago, ended_ago=ended_ago),
        ])
        job = self._job_marker(self.SID, self.now - 2980.0, job_id=job_id,
                               status=status, job_type=job_type)
        if failure_reason:
            job['failure_reason'] = failure_reason
        self._write_markers(fx, self.SID, [
            self._task_marker(self.SID, 'openmuid0001', self.now - 2990.0),
            job,
        ])
        return fx

    def _close_session(self, fx):
        conn = sqlite3.connect(fx['state_db'])
        try:
            conn.execute('UPDATE sessions SET ended_at = ? WHERE id = ?',
                         (self.now - 10.0, self.SID))
            conn.commit()
        finally:
            conn.close()

    def test_cancelled_on_an_open_session_is_not_reported_until_it_ends(self):
        fx = self._fixture_with_job(status='CANCELLED')

        t1 = self._tick(fx)
        self.assertEqual(t1['rc'], 0, t1['output'])
        # Job creation and linking are unaffected: only the terminal outcome waits.
        self.assertEqual(len(self._job_creates(t1['new'])), 1, t1['new'])
        main_c = self._main_completions_for(t1['new'], self.SID)
        self.assertEqual(len(main_c), 1, t1['new'])
        self.assertEqual(argv_to_flags(main_c[0]).get('--agentic-job-id'), JOB_ID)
        self.assertEqual(
            self._job_outcomes(t1['new']), [],
            'CANCELLED is the classifier\'s "uncertain" verdict; closing the job '
            'while the session is still open is premature')
        self.assertNotIn(f'JOB:{JOB_ID}:outcome:', self._read_ledger(fx, 'revenium-jobs.ledger'))

        # Still open on the next tick: still deferred, and (retry is ungated)
        # nothing is double-created.
        t2 = self._tick(fx)
        self.assertEqual(self._job_outcomes(t2['new']), [])
        self.assertEqual(self._job_creates(t2['new']), [])

        # The session ends: the deferred outcome now goes out, exactly once.
        self._close_session(fx)
        t3 = self._tick(fx)
        outcomes = self._job_outcomes(t3['new'])
        self.assertEqual(len(outcomes), 1, t3['new'])
        self.assertEqual(outcomes[0][2], JOB_ID)
        self.assertEqual(argv_to_flags(outcomes[0]).get('--result'), 'CANCELLED')
        self.assertIn(f'JOB:{JOB_ID}:outcome:', self._read_ledger(fx, 'revenium-jobs.ledger'))
        t4 = self._tick(fx)
        self.assertEqual(self._job_outcomes(t4['new']), [])

    def test_cancelled_on_an_already_ended_session_is_reported_immediately(self):
        fx = self._fixture_with_job(status='CANCELLED', ended_ago=2900.0)
        t1 = self._tick(fx)
        outcomes = self._job_outcomes(t1['new'])
        self.assertEqual(len(outcomes), 1, t1['new'])
        self.assertEqual(argv_to_flags(outcomes[0]).get('--result'), 'CANCELLED')

    def test_success_on_an_open_session_is_reported_immediately(self):
        fx = self._fixture_with_job(status='SUCCESS')
        t1 = self._tick(fx)
        outcomes = self._job_outcomes(t1['new'])
        self.assertEqual(len(outcomes), 1, t1['new'])
        self.assertEqual(argv_to_flags(outcomes[0]).get('--result'), 'SUCCESS')

    def test_failed_on_an_open_session_is_reported_immediately(self):
        fx = self._fixture_with_job(status='FAILED', failure_reason='tests failed')
        t1 = self._tick(fx)
        outcomes = self._job_outcomes(t1['new'])
        self.assertEqual(len(outcomes), 1, t1['new'])
        self.assertEqual(argv_to_flags(outcomes[0]).get('--result'), 'FAILED')

    def test_guardrail_halt_cancel_on_an_open_session_is_reported_immediately(self):
        # pre_tool_call.sh writes this marker on purpose, mid-session: it is a
        # real cancellation, not an uncertainty guess.
        fx = self._fixture_with_job(
            status='CANCELLED', job_id='guardrail-halt-ab12', job_type='interrupted')
        t1 = self._tick(fx)
        outcomes = self._job_outcomes(t1['new'])
        self.assertEqual(len(outcomes), 1, t1['new'])
        self.assertEqual(outcomes[0][2], 'guardrail-halt-ab12')
        self.assertEqual(argv_to_flags(outcomes[0]).get('--result'), 'CANCELLED')

    def test_an_abandoned_open_session_is_not_left_pending_forever(self):
        # No ended_at because Hermes died, not because the user is still there.
        fx = self._fixture_with_job(status='CANCELLED', started_ago=4 * 86400.0)
        t1 = self._tick(fx)
        outcomes = self._job_outcomes(t1['new'])
        self.assertEqual(len(outcomes), 1, t1['new'])
        self.assertEqual(argv_to_flags(outcomes[0]).get('--result'), 'CANCELLED')

    def test_recent_activity_keeps_a_long_open_session_deferred(self):
        # Started days ago, but Hermes recorded activity minutes ago: this is
        # the idle clock the deferral is documented to use.
        fx = self._fixture_with_job(status='CANCELLED', started_ago=4 * 86400.0)
        conn = sqlite3.connect(fx['state_db'])
        try:
            conn.execute('ALTER TABLE sessions ADD COLUMN last_activity_at REAL')
            conn.execute('UPDATE sessions SET last_activity_at = ? WHERE id = ?',
                         (self.now - 300.0, self.SID))
            conn.commit()
        finally:
            conn.close()
        t1 = self._tick(fx)
        self.assertEqual(self._job_outcomes(t1['new']), [], t1['new'])

        conn = sqlite3.connect(fx['state_db'])
        try:
            conn.execute('UPDATE sessions SET last_activity_at = ? WHERE id = ?',
                         (self.now - 3 * 86400.0, self.SID))
            conn.commit()
        finally:
            conn.close()
        t2 = self._tick(fx)
        self.assertEqual(len(self._job_outcomes(t2['new'])), 1, t2['new'])

    def test_the_deferral_is_logged_once_not_every_tick(self):
        fx = self._fixture_with_job(status='CANCELLED')
        for _ in range(3):
            self._tick(fx)
        log = self._read_log(fx)
        self.assertEqual(log.count('outcome held while session open'), 1, log)
        # It is a distinct condition from "waiting on a create": the existing
        # `outcome deferred: id=` taxonomy (diagnose.sh counts it) is untouched.
        self.assertNotIn('outcome deferred: id=', log)

    def test_null_last_activity_falls_back_to_the_session_start(self):
        fx = self._fixture_with_job(status='CANCELLED', started_ago=4 * 86400.0)
        conn = sqlite3.connect(fx['state_db'])
        try:
            conn.execute('ALTER TABLE sessions ADD COLUMN last_activity_at REAL')
            conn.commit()
        finally:
            conn.close()
        t1 = self._tick(fx)
        self.assertEqual(len(self._job_outcomes(t1['new'])), 1, t1['new'])

    def test_zero_idle_bound_switches_the_deferral_off(self):
        fx = self._fixture_with_job(status='CANCELLED')
        t1 = self._tick(fx, extra_env={'REVENIUM_OPEN_SESSION_MAX_IDLE_SECONDS': '0'})
        self.assertEqual(len(self._job_outcomes(t1['new'])), 1, t1['new'])

    def test_idle_bound_is_configurable(self):
        fx = self._fixture_with_job(status='CANCELLED', started_ago=3000.0)
        t1 = self._tick(fx, extra_env={'REVENIUM_OPEN_SESSION_MAX_IDLE_SECONDS': '600'})
        self.assertEqual(len(self._job_outcomes(t1['new'])), 1, t1['new'])


# ---------------------------------------------------------------------------
# The shell predicates, exercised directly (including under macOS /bin/bash
# 3.2, which this repo's scripts must stay compatible with).
# ---------------------------------------------------------------------------

_PREDICATES = (
    '_job_ledger_id', '_job_create_ledgered', '_job_linkable_for_aux',
    '_open_session_defers_cancelled', '_job_child_hold_age',
)


def _function_source(name):
    text = (SCRIPTS_DIR / 'hermes-report.sh').read_text()
    m = re.search(rf'^{name}\(\) \{{\n.*?^\}}\n', text, re.S | re.M)
    assert m, f'{name} not found in hermes-report.sh'
    return m.group(0)


class ShellPredicateTests(unittest.TestCase):

    BASHES = ('/bin/bash', 'bash')

    def setUp(self):
        self.now = time.time()
        self.tmp = tempfile.mkdtemp(prefix='gsd-job-lifecycle-pred-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = os.path.join(self.tmp, 'state.db')
        self.ledger = os.path.join(self.tmp, 'jobs.ledger')
        conn = sqlite3.connect(self.db)
        conn.execute('CREATE TABLE sessions (id TEXT, started_at REAL, ended_at REAL)')
        conn.commit()
        conn.close()

    def _add_session(self, sid, started_ago, ended_ago=None):
        conn = sqlite3.connect(self.db)
        try:
            conn.execute(
                'INSERT INTO sessions VALUES (?,?,?)',
                (sid, self.now - started_ago,
                 None if ended_ago is None else self.now - ended_ago))
            conn.commit()
        finally:
            conn.close()

    def _call(self, bash, call, env=None, db=None):
        funcs = '\n'.join(_function_source(n) for n in _PREDICATES)
        script = f'{funcs}\n_SESSIONS_ACTIVITY_COL=""\n{call}\necho "rc=$?"\n'
        full_env = {
            **os.environ, 'STATE_DB': db or self.db, 'JOBS_LEDGER_FILE': self.ledger,
            **(env or {}),
        }
        out = subprocess.run([bash, '-c', script], env=full_env,
                             capture_output=True, text=True, timeout=30)
        m = re.search(r'rc=(\d+)\s*$', out.stdout)
        self.assertIsNotNone(m, out.stdout + out.stderr)
        return int(m.group(1)), out

    def _each_bash(self, call, expected_rc, **kw):
        for bash in self.BASHES:
            rc, out = self._call(bash, call, **kw)
            self.assertEqual(rc, expected_rc, f'{bash}: {call}\n{out.stdout}{out.stderr}')

    # -- _open_session_defers_cancelled --------------------------------------

    def test_open_session_defers(self):
        self._add_session('s-open', 3000.0)
        self._each_bash('_open_session_defers_cancelled s-open', 0)

    def test_ended_session_does_not_defer(self):
        self._add_session('s-ended', 3000.0, ended_ago=10.0)
        self._each_bash('_open_session_defers_cancelled s-ended', 1)

    def test_unknown_session_fails_open(self):
        self._each_bash('_open_session_defers_cancelled s-nobody', 1)

    def test_empty_sid_fails_open(self):
        self._each_bash('_open_session_defers_cancelled ""', 1)

    def test_missing_database_fails_open(self):
        self._each_bash('_open_session_defers_cancelled s-open', 1,
                        db=os.path.join(self.tmp, 'absent.db'))

    def test_unreadable_database_fails_open(self):
        junk = os.path.join(self.tmp, 'junk.db')
        with open(junk, 'wb') as f:
            f.write(b'this is not a sqlite database' * 100)
        self._each_bash('_open_session_defers_cancelled s-open', 1, db=junk)

    def test_a_quote_in_the_session_id_is_not_sql(self):
        self._add_session("o'brien", 3000.0)
        self._each_bash("_open_session_defers_cancelled \"o'brien\"", 0)
        # ...and an injection attempt matches nothing rather than everything.
        self._each_bash(
            "_open_session_defers_cancelled \"x' OR '1'='1\"", 1)

    def test_idle_bound_env_is_validated(self):
        self._add_session('s-open', 3000.0)
        self._each_bash('_open_session_defers_cancelled s-open', 0,
                        env={'REVENIUM_OPEN_SESSION_MAX_IDLE_SECONDS': 'banana'})
        self._each_bash('_open_session_defers_cancelled s-open', 1,
                        env={'REVENIUM_OPEN_SESSION_MAX_IDLE_SECONDS': '600'})

    def test_lock_contention_defers_rather_than_reporting(self):
        # An outcome cannot be taken back; a deferral costs one tick. The
        # database was readable moments ago (the main query ran), so a lock is
        # contention, not "state unknowable".
        self._add_session('s-ended', 3000.0, ended_ago=10.0)  # would report
        blocker = sqlite3.connect(self.db, isolation_level=None)
        self.addCleanup(blocker.close)
        blocker.execute('BEGIN EXCLUSIVE')
        self._each_bash('_open_session_defers_cancelled s-ended', 0)
        blocker.execute('ROLLBACK')
        self._each_bash('_open_session_defers_cancelled s-ended', 1)

    def test_a_locked_column_probe_defers_and_is_not_memoized(self):
        # Greptile P1 on #152: the PRAGMA probe used to fall back to started_at
        # on ANY failure and memoize that for the rest of the run. Once the lock
        # cleared, a long session that is still active (recent
        # last_activity_at) was judged idle on started_at and its CANCELLED
        # shipped permanently. A locked probe now defers and leaves the memo
        # empty, so the next call probes again.
        self._add_session('s-ended', 3000.0, ended_ago=10.0)  # would report
        blocker = sqlite3.connect(self.db, isolation_level=None)
        self.addCleanup(blocker.close)
        blocker.execute('BEGIN EXCLUSIVE')
        call = ('_open_session_defers_cancelled s-ended; r=$?; '
                'echo "memo=[${_SESSIONS_ACTIVITY_COL}]"; (exit $r)')
        for bash in self.BASHES:
            rc, out = self._call(bash, call)
            self.assertEqual(rc, 0, f'{bash}: {out.stdout}{out.stderr}')
            self.assertIn('memo=[]', out.stdout, bash)
        blocker.execute('ROLLBACK')

    def test_last_activity_keeps_a_long_open_session_held(self):
        # The case the memo bug broke: started two days ago, active seconds ago.
        db = os.path.join(self.tmp, 'activity.db')
        conn = sqlite3.connect(db)
        conn.execute('CREATE TABLE sessions (id TEXT, started_at REAL, '
                     'ended_at REAL, last_activity_at REAL)')
        conn.execute('INSERT INTO sessions VALUES (?,?,?,?)',
                     ('s-long', self.now - 2 * 86400, None, self.now - 10))
        conn.commit()
        conn.close()
        self._each_bash('_open_session_defers_cancelled s-long', 0, db=db)

    def test_an_unreadable_column_probe_fails_open_without_memoizing(self):
        junk = os.path.join(self.tmp, 'junk2.db')
        with open(junk, 'wb') as f:
            f.write(b'this is not a sqlite database' * 100)
        call = ('_open_session_defers_cancelled s-open; r=$?; '
                'echo "memo=[${_SESSIONS_ACTIVITY_COL}]"; (exit $r)')
        for bash in self.BASHES:
            rc, out = self._call(bash, call, db=junk)
            self.assertEqual(rc, 1, bash)
            self.assertIn('memo=[]', out.stdout, bash)

    # -- _job_child_hold_age ---------------------------------------------------

    def _flag_dir(self):
        d = os.path.join(self.tmp, 'outcome-warn')
        os.makedirs(d, exist_ok=True)
        return d

    def _hold_age(self, bash, flag_text=None, budget=600, flag_dir=None):
        d = flag_dir or self._flag_dir()
        flag = os.path.join(d, 'job_x__child-hold-since.flag')
        if flag_text is not None:
            with open(flag, 'w') as f:
                f.write(flag_text)
        rc, out = self._call(
            bash, f'age="$(_job_child_hold_age job_x {budget})"; echo "age=${{age}}"; (exit 0)',
            env={'OUTCOME_WARN_FLAGS_DIR': d})
        m = re.search(r'age=(\S*)', out.stdout)
        self.assertIsNotNone(m, out.stdout + out.stderr)
        return m.group(1), flag, out

    def test_hold_age_starts_at_zero_and_is_persisted(self):
        for bash in self.BASHES:
            age, flag, _ = self._hold_age(bash)
            self.assertEqual(age, '0', bash)
            began, renewed = open(flag).read().split()
            self.assertEqual(began, renewed)
            os.remove(flag)

    def test_hold_age_counts_continuous_holds(self):
        now = int(time.time())
        for bash in self.BASHES:
            age, _, _ = self._hold_age(bash, f'{now - 400}\n{now - 30}\n')
            self.assertIn(age, {'400', '401', '402'}, bash)

    def test_hold_age_restarts_after_a_gap(self):
        now = int(time.time())
        for bash in self.BASHES:
            # Last renewed 15 minutes ago: ticks stopped, the root had no turns.
            age, flag, _ = self._hold_age(bash, f'{now - 5000}\n{now - 900}\n')
            self.assertEqual(age, '0', bash)
            self.assertEqual(open(flag).read().split()[0], open(flag).read().split()[1])

    def test_hold_age_ignores_garbled_or_future_flags(self):
        now = int(time.time())
        for text in ('garbage\n', '', '123\n', f'{now + 9999}\n{now + 9999}\n',
                     f'{now - 100}\n{now + 500}\n', '-5\n-3\n'):
            for bash in self.BASHES:
                age, _, out = self._hold_age(bash, text)
                self.assertEqual(age, '0', f'{bash} {text!r}: {out.stdout}{out.stderr}')

    def test_hold_age_reads_zero_padded_numbers_as_decimal(self):
        now = int(time.time())
        for bash in self.BASHES:
            age, _, out = self._hold_age(bash, f'0{now - 100:012d}\n{now - 10:012d}\n'[1:])
            self.assertTrue(age.isdigit(), f'{bash}: {out.stdout}{out.stderr}')
            self.assertGreaterEqual(int(age), 100, bash)

    def test_hold_age_fails_when_state_cannot_be_persisted(self):
        # A bound that cannot be remembered is a hold that never ends: the
        # caller ships unlinked on a non-zero status.
        blocked = os.path.join(self.tmp, 'not-a-dir')
        with open(blocked, 'w') as f:
            f.write('x')
        for bash in self.BASHES:
            rc, out = self._call(
                bash, '_job_child_hold_age job_x 600 >/dev/null 2>&1',
                env={'OUTCOME_WARN_FLAGS_DIR': blocked})
            self.assertNotEqual(rc, 0, bash)
            self.assertNotIn('Permission denied', out.stderr)

    # -- ledger predicates ----------------------------------------------------

    def _ledger(self, *lines):
        with open(self.ledger, 'w') as f:
            f.write(''.join(line + '\n' for line in lines))

    def test_ledger_id_applies_the_writers_transform(self):
        for bash in self.BASHES:
            rc, out = self._call(bash, '_job_ledger_id "a:b c\td"; echo')
            self.assertIn('a_b_c_d', out.stdout, bash)

    def test_create_ledgered(self):
        self._ledger('JOB:job_a:created:1.000', 'JOB:job_b_c:created:1.000')
        self._each_bash('_job_create_ledgered job_a', 0)
        self._each_bash('_job_create_ledgered job_zzz', 1)
        self._each_bash('_job_create_ledgered "job_b:c"', 0)  # sanitised before lookup
        self._each_bash('_job_create_ledgered ""', 1)

    def test_prefix_of_another_job_id_is_not_a_match(self):
        self._ledger('JOB:job_abc:created:1.000')
        self._each_bash('_job_create_ledgered job_ab', 1)

    def test_missing_ledger_means_not_created(self):
        self._each_bash('_job_create_ledgered job_a', 1)
        self._each_bash('_job_linkable_for_aux job_a', 1)

    def test_linkable_open_job(self):
        self._ledger('JOB:job_a:created:1.000')
        self._each_bash('_job_linkable_for_aux job_a', 0)

    def test_linkable_recently_closed_job(self):
        self._ledger('JOB:job_a:created:1.000', f'JOB:job_a:outcome:{self.now - 30:.3f}:SUCCESS')
        self._each_bash('_job_linkable_for_aux job_a', 0)

    def test_not_linkable_long_closed_job(self):
        self._ledger('JOB:job_a:created:1.000', f'JOB:job_a:outcome:{self.now - 90000:.3f}:SUCCESS')
        self._each_bash('_job_linkable_for_aux job_a', 1)

    def test_closed_job_window_follows_the_stale_setting(self):
        self._ledger('JOB:job_a:created:1.000', f'JOB:job_a:outcome:{self.now - 90:.3f}:SUCCESS')
        self._each_bash('_job_linkable_for_aux job_a', 1,
                        env={'REVENIUM_JOBS_STALE_SECONDS': '30'})
        self._each_bash('_job_linkable_for_aux job_a', 0,
                        env={'REVENIUM_JOBS_STALE_SECONDS': '300'})

    def test_malformed_outcome_timestamp_withholds_the_link(self):
        self._ledger('JOB:job_a:created:1.000', 'JOB:job_a:outcome:garbage:SUCCESS')
        self._each_bash('_job_linkable_for_aux job_a', 1)

    def test_never_created_is_not_linkable_even_if_an_outcome_line_exists(self):
        self._ledger(f'JOB:job_a:outcome:{self.now - 5:.3f}:SUCCESS')
        self._each_bash('_job_linkable_for_aux job_a', 1)


if __name__ == '__main__':
    unittest.main()
