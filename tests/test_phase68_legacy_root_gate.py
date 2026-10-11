"""Phase 68 Plan 02 (D-17): the legacy reporter attributes a resolved job owner
only with POSITIVE root evidence.

`hermes-report.sh` used to decide "this session is a root" from
`root_sid == sid`. `get_root_session_id` fails OPEN (it returns the input sid
on a missing db, a missing row, a missing column, a sqlite error, and on cyclic
ancestry whose cycle length divides max_depth), so that test cannot tell "root"
from "could not tell". `api-event-report.sh` already requires the session row
to exist AND its `parent_session_id` to be NULL (`_is_confirmed_root`). D-17
carries the same evidence to the legacy per-marker ship site and to the
auxiliary cache.

What the gate withholds is the job DIMENSION (`--agentic-job-id` with its name
and type siblings). Never the completion (D-15), never `--transaction-id`, never
a jobs-create call.

Every arm drives the REAL `hermes-report.sh` against a synthetic `state.db`
through the same no-shift `revenium` shim the golden modules use, and asserts on
the captured argv (never on script text).
"""
import copy
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest

from tests._compat_helpers import (
    argv_to_flags,
    assert_argv_is_golden_argv_order,
    build_session_model_usage,
    build_shim,
    build_state_db,
    load_golden,
    SCRIPTS_DIR,
    seed_parent_session_ids,
)

ROOT_SID = 'compat-sid-001'
CHILD_SID = 'compat-child-001'
JOB_ID = 'compat-job-001'

_JOB_FLAGS = ('--agentic-job-id', '--agentic-job-name', '--agentic-job-type')


def _session(sid, tokens=True):
    return {
        'id': sid,
        'model': 'claude-sonnet-4-6',
        'source': 'test',
        'input_tokens': 100 if tokens else 0,
        'output_tokens': 50 if tokens else 0,
        'cache_read': 0,
        'cache_write': 0,
        'reasoning': 0,
        'estimated_cost': '0',
        'api_calls': 1,
        # Far in the past so the settle-window filter passes without a
        # `.ready` sentinel (same as the golden modules).
        'started_at': 1715514000.0,
        'ended_at': 1715514000.0,
        'billing_provider': 'anthropic',
    }


def _task_marker(sid, muid, ts=1715515000.5):
    return {
        'muid': muid, 'ts': ts, 'sid': sid,
        'task_type': 'code_review', 'operation_type': 'CHAT',
    }


def _job_marker(sid, job_id=JOB_ID, ts=1715515001.0):
    return {
        'kind': 'job', 'ts': ts, 'sid': sid,
        'agentic_job_id': job_id, 'job_name': 'COMPAT Test Job',
        'job_type': 'code_review', 'status': 'IN_PROGRESS',
    }


def _golden_minus_job_flags():
    """The golden `argv_order` with the three job flags and their values
    removed; every other token (including --transaction-id) stays in place."""
    golden = copy.deepcopy(load_golden('meter-completion.golden.json'))
    out = []
    order = golden['argv_order']
    i = 0
    while i < len(order):
        if order[i] in _JOB_FLAGS:
            i += 2
            continue
        out.append(order[i])
        i += 1
    golden['argv_order'] = out
    return golden


class _GateBase(unittest.TestCase):
    """One fixture per call: state.db + markers + a `revenium` shim in
    `$HOME/.local/bin` (ensure_path puts that directory first, so a stub here
    is never shadowed by a real binary)."""

    def _build(self, sessions, parents=None, markers=None, aux_rows=None):
        """`parents` is None for the column-ABSENT schema, otherwise a
        {sid: parent-or-None} mapping handed to seed_parent_session_ids."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase68-gate-')
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)

        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        markers_dir = os.path.join(state_dir, 'markers')
        os.makedirs(markers_dir, mode=0o700)
        state_db = os.path.join(hermes_home, 'state.db')
        shim_home = os.path.join(tmpdir, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)

        build_state_db(state_db, sessions)
        if parents is not None:
            seed_parent_session_ids(state_db, parents)
        if aux_rows is not None:
            build_session_model_usage(state_db, aux_rows)
        for sid, records in (markers or {}).items():
            with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
                for rec in records:
                    f.write(json.dumps(rec, separators=(',', ':')) + '\n')
        build_shim(os.path.join(bin_dir, 'revenium'))
        return {
            'tmpdir': tmpdir, 'hermes_home': hermes_home,
            'state_dir': state_dir, 'state_db': state_db,
            'shim_home': shim_home, 'bin_dir': bin_dir,
        }

    def _env(self, fx, tick=0, extra_env=None):
        env = {
            **os.environ,
            'HOME': fx['shim_home'],
            'HERMES_HOME': fx['hermes_home'],
            'REVENIUM_STATE_DIR': fx['state_dir'],
            'PATH': fx['bin_dir'] + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': os.path.join(fx['tmpdir'], f'inv-{tick}.log'),
            'METER_LOG': os.path.join(fx['tmpdir'], f'meter-{tick}.log'),
            'JOBS_LOG': os.path.join(fx['tmpdir'], f'jobs-{tick}.log'),
            'TZ': 'UTC',
            'REVENIUM_ORGANIZATION_NAME': '',
        }
        if extra_env:
            env.update(extra_env)
        return env

    @staticmethod
    def _install_sqlite_stub(fx, match, rc=5):
        """A `sqlite3` in $HOME/.local/bin that fails (exit `rc`, a lock-style
        message) for any invocation whose argv contains `match`, and otherwise
        defers to the real binary."""
        real = shutil.which('sqlite3')
        shim = os.path.join(fx['bin_dir'], 'sqlite3')
        with open(shim, 'w') as f:
            f.write(
                '#!/usr/bin/env bash\n'
                'case "$*" in\n'
                f'  *"{match}"*) echo "Error: database is locked" >&2; exit {rc} ;;\n'
                'esac\n'
                f'exec {shlex.quote(real)} "$@"\n'
            )
        os.chmod(shim, 0o755)
        return shim

    @staticmethod
    def _read_argv_log(path):
        out = []
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        out.append(shlex.split(line))
        return out

    def _tick(self, fx, tick=0, extra_env=None):
        env = self._env(fx, tick, extra_env)
        result = subprocess.run(
            ['bash', str(SCRIPTS_DIR / 'hermes-report.sh')],
            env=env, capture_output=True, text=True, timeout=120,
        )
        return {
            'rc': result.returncode,
            'output': result.stdout + result.stderr,
            'log_text': self._log_text(fx),
            'meter': self._read_argv_log(env['METER_LOG']),
            'jobs': self._read_argv_log(env['JOBS_LOG']),
        }

    @staticmethod
    def _log_text(fx):
        path = os.path.join(fx['state_dir'], 'revenium-metering.log')
        if os.path.exists(path):
            with open(path) as f:
                return f.read()
        return ''

    def _single_root_run(self, parents, extra_sessions=(), extra_env=None):
        """The canonical golden fixture (one root, one task marker, one job
        marker) under a chosen schema/parent arrangement. Returns the single
        `meter completion` argv for ROOT_SID plus the full result."""
        fx = self._build(
            [_session(ROOT_SID)] + [_session(s, tokens=False) for s in extra_sessions],
            parents=parents,
            markers={ROOT_SID: [_task_marker(ROOT_SID, 'compat-muid-001'), _job_marker(ROOT_SID)]},
        )
        res = self._tick(fx, 0, extra_env)
        self.assertEqual(res['rc'], 0, res['output'])
        self.assertEqual(len(res['meter']), 1, f"{res['meter']!r}\n{res['output']}")
        return fx, res['meter'][0], res


class LegacyRootGateTests(_GateBase):
    """The per-marker ship site. D-17 / T-68-04 / T-68-07."""

    def test_confirmed_root_ships_exact_golden_argv(self):
        _fx, argv, _res = self._single_root_run({ROOT_SID: None})
        assert_argv_is_golden_argv_order(
            self, argv, load_golden('meter-completion.golden.json'))

    def test_column_absent_omits_the_three_job_flags_and_keeps_the_rest(self):
        _fx, argv, _res = self._single_root_run(None)
        for flag in _JOB_FLAGS:
            self.assertNotIn(flag, argv)
        # Same --transaction-id as the golden: the completion is withheld from
        # nothing, only its job dimension is.
        self.assertEqual(
            argv_to_flags(argv)['--transaction-id'],
            'compat-sid-001-150-compat-muid-001')
        assert_argv_is_golden_argv_order(self, argv, _golden_minus_job_flags())

    def test_self_loop_parent_is_unconfirmed(self):
        _fx, argv, _res = self._single_root_run({ROOT_SID: ROOT_SID})
        assert_argv_is_golden_argv_order(self, argv, _golden_minus_job_flags())

    def test_two_cycle_ancestry_is_unconfirmed(self):
        """A<->B: the walk exhausts max_depth back on the input sid, so
        `root_sid == sid` -- the exact "could not tell" case."""
        _fx, argv, _res = self._single_root_run(
            {ROOT_SID: 'compat-other-001', 'compat-other-001': ROOT_SID},
            extra_sessions=('compat-other-001',),
        )
        assert_argv_is_golden_argv_order(self, argv, _golden_minus_job_flags())

    def _subagent_run(self, root_create_ledgered):
        fx = self._build(
            [_session('compat-root-001', tokens=False), _session(CHILD_SID)],
            parents={'compat-root-001': None, CHILD_SID: 'compat-root-001'},
            markers={
                'compat-root-001': [_job_marker('compat-root-001', 'root-job-777')],
                CHILD_SID: [_task_marker(CHILD_SID, 'compat-muid-child')],
            },
        )
        if root_create_ledgered:
            with open(os.path.join(fx['state_dir'], 'revenium-jobs.ledger'), 'w') as f:
                f.write('JOB:root-job-777:created:1715515002\n')
        res = self._tick(fx)
        self.assertEqual(res['rc'], 0, res['output'])
        self.assertEqual(len(res['meter']), 1, f"{res['meter']!r}\n{res['output']}")
        return argv_to_flags(res['meter'][0])

    def test_subagent_branch_is_unchanged(self):
        """A child whose root's job create is ledgered ships the ROOT's job id
        and no name/type siblings, exactly as before the gate."""
        flags = self._subagent_run(root_create_ledgered=True)
        self.assertEqual(flags.get('--agentic-job-id'), 'root-job-777')
        self.assertNotIn('--agentic-job-name', flags)
        self.assertNotIn('--agentic-job-type', flags)

    def test_subagent_ships_unlinked_when_its_roots_create_never_ran(self):
        """#152 RC-2 composes with the gate: a link to a job Revenium has not
        created would mint it nameless, so past the hold the child ships
        without the id."""
        flags = self._subagent_run(root_create_ledgered=False)
        for flag in _JOB_FLAGS:
            self.assertNotIn(flag, flags)

    def test_jobs_create_is_unchanged_for_a_column_absent_root(self):
        """The gate sits at the ship sites only. A fail-closed create would mean
        no job at all on a host without the column (T-68-07)."""
        _fx, _argv, res_absent = self._single_root_run(None)
        creates_absent = [a for a in res_absent['jobs'] if a[:2] == ['jobs', 'create']]
        self.assertEqual(len(creates_absent), 1, res_absent['jobs'])
        self.assertIn(JOB_ID, creates_absent[0])

        _fx2, _argv2, res_present = self._single_root_run({ROOT_SID: None})
        creates_present = [a for a in res_present['jobs'] if a[:2] == ['jobs', 'create']]
        self.assertEqual(creates_present, creates_absent)


class SessionIsConfirmedRootTests(_GateBase):
    """The bash helper in common.sh, called from a subshell that sources it."""

    def _call(self, fx, sid, remove_db=False):
        if remove_db:
            os.remove(fx['state_db'])
        env = {
            **os.environ,
            'HOME': fx['shim_home'],
            'HERMES_HOME': fx['hermes_home'],
            'REVENIUM_STATE_DIR': fx['state_dir'],
            'PATH': fx['bin_dir'] + os.pathsep + os.environ.get('PATH', ''),
        }
        script = (
            'source "$1/common.sh"; '
            'session_is_confirmed_root "$2"; '
            'case $? in 0) echo yes ;; 1) echo no ;; *) echo unknown ;; esac'
        )
        res = subprocess.run(
            ['bash', '-c', script, 'bash', str(SCRIPTS_DIR), sid],
            env=env, capture_output=True, text=True, timeout=30,
        )
        return res.stdout.strip(), res.stderr

    def _fx(self, parents):
        return self._build(
            [_session('root-a'), _session('child-b'), _session("it's")],
            parents=parents,
        )

    def test_null_parent_is_confirmed(self):
        fx = self._fx({'root-a': None, 'child-b': 'root-a', "it's": None})
        self.assertEqual(self._call(fx, 'root-a')[0], 'yes')

    def test_missing_row_is_not_confirmed(self):
        fx = self._fx({'root-a': None})
        self.assertEqual(self._call(fx, 'no-such-session')[0], 'no')

    def test_non_null_parent_is_not_confirmed(self):
        fx = self._fx({'root-a': None, 'child-b': 'root-a'})
        self.assertEqual(self._call(fx, 'child-b')[0], 'no')

    def test_missing_state_db_is_could_not_tell(self):
        fx = self._fx({'root-a': None})
        self.assertEqual(self._call(fx, 'root-a', remove_db=True)[0], 'unknown')

    def test_sqlite_failure_is_could_not_tell_not_not_a_root(self):
        """The CR-01 shape: a genuine NULL-parent root, but sqlite3 exits 5
        (busy/locked). That must never read as "confirmed not a root"."""
        fx = self._fx({'root-a': None})
        self._install_sqlite_stub(fx, 'parent_session_id IS NULL')
        self.assertEqual(self._call(fx, 'root-a')[0], 'unknown')

    def test_missing_column_exits_non_zero_yet_is_not_a_root_rather_than_unknown(self):
        """sqlite3 exits 1 on a missing column, like any fault. Reading that as
        "could not tell" would defer every job-bearing session on a host
        without the column, forever."""
        fx = self._fx(None)
        res = subprocess.run(
            ['sqlite3', '-readonly', fx['state_db'],
             "SELECT parent_session_id IS NULL FROM sessions WHERE id='root-a';"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertEqual(self._call(fx, 'root-a')[0], 'no')

    def test_column_absent_is_not_confirmed(self):
        fx = self._fx(None)
        out, _err = self._call(fx, 'root-a')
        self.assertEqual(out, 'no')

    def test_single_quote_id_is_not_confirmed_and_never_errors(self):
        """T-68-03: the id is never interpolated into SQL when it holds a quote,
        even though a row with exactly that id exists and is a root."""
        fx = self._fx({"it's": None})
        out, err = self._call(fx, "it's")
        self.assertEqual(out, 'no')
        self.assertEqual(err, '')


class GateCostTests(_GateBase):
    """T-68-06: at most one `sqlite3 -readonly` per session per tick."""

    def test_three_task_markers_and_one_job_marker_cost_one_query(self):
        real = shutil.which('sqlite3')
        self.assertIsNotNone(real, 'sqlite3 CLI required')
        fx = self._build(
            [_session(ROOT_SID)],
            parents={ROOT_SID: None},
            markers={ROOT_SID: [
                _task_marker(ROOT_SID, 'compat-muid-001', 1715515000.5),
                _task_marker(ROOT_SID, 'compat-muid-002', 1715515000.6),
                _task_marker(ROOT_SID, 'compat-muid-003', 1715515000.7),
                _job_marker(ROOT_SID),
            ]},
        )
        log = os.path.join(fx['tmpdir'], 'sqlite3-calls.log')
        shim = os.path.join(fx['bin_dir'], 'sqlite3')
        with open(shim, 'w') as f:
            f.write(
                '#!/usr/bin/env bash\n'
                f'printf \'%s\\n@@END@@\\n\' "$*" >> {shlex.quote(log)}\n'
                f'exec {shlex.quote(real)} "$@"\n'
            )
        os.chmod(shim, 0o755)

        res = self._tick(fx)
        self.assertEqual(res['rc'], 0, res['output'])
        self.assertEqual(len(res['meter']), 3, res['meter'])
        for argv in res['meter']:
            self.assertEqual(argv_to_flags(argv).get('--agentic-job-id'), JOB_ID)

        with open(log) as f:
            calls = [c for c in f.read().split('@@END@@\n') if c.strip()]
        gate_calls = [c for c in calls if 'parent_session_id IS NULL' in c]
        self.assertEqual(len(gate_calls), 1, gate_calls)
        self.assertIn('-readonly', gate_calls[0])


def _aux_row(sid):
    return {
        'session_id': sid, 'model': 'claude-3-5-haiku',
        'billing_provider': 'anthropic', 'billing_base_url': '',
        'billing_mode': '', 'task': 'approval', 'api_call_count': 3,
        'input_tokens': 40, 'output_tokens': 10, 'cache_read_tokens': 0,
        'cache_write_tokens': 0, 'estimated_cost_usd': 0.002,
        'first_seen': 1715514500.0, 'last_seen': 1715514600.0,
    }


def _split_meter(meter):
    """(main-loop argv flags, auxiliary argv flags) from a tick's meter log."""
    flags = [argv_to_flags(a) for a in meter]
    aux = [f for f in flags if f.get('--operation-type') == 'OTHER']
    main = [f for f in flags if f.get('--operation-type') != 'OTHER']
    return main, aux


class AuxParityTests(_GateBase):
    """Phase 55 scope parity under the gate: an auxiliary row carries the same
    job dimension as its session's main-loop row."""

    def _run(self, parents, extra_env=None):
        fx = self._build(
            [_session(ROOT_SID)],
            parents=parents,
            markers={ROOT_SID: [_task_marker(ROOT_SID, 'compat-muid-001'), _job_marker(ROOT_SID)]},
            aux_rows=[_aux_row(ROOT_SID)],
        )
        res = self._tick(fx, 0, extra_env)
        self.assertEqual(res['rc'], 0, res['output'])
        main, aux = _split_meter(res['meter'])
        self.assertEqual(len(main), 1, res['meter'])
        self.assertEqual(len(aux), 1, res['meter'])
        return main[0], aux[0]

    def test_confirmed_root_aux_row_keeps_its_job_id(self):
        main, aux = self._run({ROOT_SID: None})
        self.assertEqual(main.get('--agentic-job-id'), JOB_ID)
        self.assertEqual(aux.get('--agentic-job-id'), JOB_ID)

    def test_column_absent_root_aux_row_omits_job_id_like_its_main_row(self):
        main, aux = self._run(None)
        self.assertNotIn('--agentic-job-id', main)
        self.assertNotIn('--agentic-job-id', aux)

    def test_self_loop_root_aux_row_omits_job_id_like_its_main_row(self):
        main, aux = self._run({ROOT_SID: ROOT_SID})
        self.assertNotIn('--agentic-job-id', main)
        self.assertNotIn('--agentic-job-id', aux)

    def _gate_queries(self, extra_env):
        """Session with a job marker and NO task marker: the markerless path
        never ships a job id, so the only possible gate caller is the auxiliary
        cache."""
        real = shutil.which('sqlite3')
        fx = self._build(
            [_session(ROOT_SID)],
            parents={ROOT_SID: None},
            markers={ROOT_SID: [_job_marker(ROOT_SID)]},
            aux_rows=[_aux_row(ROOT_SID)],
        )
        log = os.path.join(fx['tmpdir'], 'sqlite3-calls.log')
        shim = os.path.join(fx['bin_dir'], 'sqlite3')
        with open(shim, 'w') as f:
            f.write(
                '#!/usr/bin/env bash\n'
                f'printf \'%s\\n@@END@@\\n\' "$*" >> {shlex.quote(log)}\n'
                f'exec {shlex.quote(real)} "$@"\n'
            )
        os.chmod(shim, 0o755)
        res = self._tick(fx, 0, extra_env)
        self.assertEqual(res['rc'], 0, res['output'])
        if not os.path.exists(log):
            return 0
        with open(log) as f:
            calls = [c for c in f.read().split('@@END@@\n') if c.strip()]
        return len([c for c in calls if 'parent_session_id IS NULL' in c])

    def test_disabled_aux_pass_costs_no_gate_query(self):
        self.assertEqual(
            self._gate_queries({'REVENIUM_AUX_METERING': 'disabled'}), 0)

    def test_enabled_aux_pass_costs_one_gate_query(self):
        """Sanity: the instrument above can see the aux cache's query."""
        self.assertEqual(self._gate_queries(None), 1)


class ColumnAbsentWarnTests(_GateBase):
    """T-68-05: a host without `sessions.parent_session_id` says so ONCE, and
    only when the gate actually withheld an owner."""

    def _lines(self, fx):
        return [
            ln for ln in self._log_text(fx).splitlines()
            if 'parent_session_id' in ln
        ]

    def test_column_absent_with_a_job_marker_warns_exactly_once_across_runs(self):
        fx = self._build(
            [_session(ROOT_SID)],
            parents=None,
            markers={ROOT_SID: [_task_marker(ROOT_SID, 'compat-muid-001'), _job_marker(ROOT_SID)]},
            aux_rows=[_aux_row(ROOT_SID)],
        )
        r1 = self._tick(fx, 0)
        self.assertEqual(r1['rc'], 0, r1['output'])
        self.assertEqual(len(self._lines(fx)), 1, self._log_text(fx))
        r2 = self._tick(fx, 1)
        self.assertEqual(r2['rc'], 0, r2['output'])
        self.assertEqual(len(self._lines(fx)), 1, self._log_text(fx))
        sentinel = os.path.join(
            fx['state_dir'], 'markers', '.probe-warn',
            'sessions-parent_session_id-absent')
        self.assertTrue(os.path.exists(sentinel))

    def test_column_present_self_loop_never_warns(self):
        fx = self._build(
            [_session(ROOT_SID)],
            parents={ROOT_SID: ROOT_SID},
            markers={ROOT_SID: [_task_marker(ROOT_SID, 'compat-muid-001'), _job_marker(ROOT_SID)]},
        )
        res = self._tick(fx)
        self.assertEqual(res['rc'], 0, res['output'])
        self.assertEqual(self._lines(fx), [], self._log_text(fx))

    def test_column_absent_with_nothing_withheld_never_warns(self):
        fx = self._build(
            [_session(ROOT_SID)],
            parents=None,
            markers={ROOT_SID: [_task_marker(ROOT_SID, 'compat-muid-001')]},
        )
        res = self._tick(fx)
        self.assertEqual(res['rc'], 0, res['output'])
        self.assertEqual(self._lines(fx), [], self._log_text(fx))


_GATE_QUERY = 'parent_session_id IS NULL'
_DEFER_WARN = 'root gate could not read state.db'


class GateFaultDefersTests(_GateBase):
    """CR-01: a gate that could not read state.db is not "not a root". The
    session defers -- no completion ships, no ledger line is written -- and the
    next tick with a working sqlite ships it WITH its job id, exactly once."""

    @staticmethod
    def _ledger_lines(fx, name, sid=ROOT_SID):
        path = os.path.join(fx['state_dir'], name)
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [ln for ln in f.read().splitlines() if sid in ln]

    def _build_root(self, task_muids=('compat-muid-001',), aux=False):
        markers = [
            _task_marker(ROOT_SID, m, 1715515000.5 + i * 0.1)
            for i, m in enumerate(task_muids)
        ] + [_job_marker(ROOT_SID)]
        return self._build(
            [_session(ROOT_SID)],
            parents={ROOT_SID: None},
            markers={ROOT_SID: markers},
            aux_rows=[_aux_row(ROOT_SID)] if aux else None,
        )

    def _warns(self, res):
        return [ln for ln in res['log_text'].splitlines() if _DEFER_WARN in ln]

    def test_faulting_gate_ships_nothing_and_writes_no_ledger_line(self):
        fx = self._build_root()
        self._install_sqlite_stub(fx, _GATE_QUERY)
        res = self._tick(fx, 0)
        self.assertEqual(res['rc'], 0, res['output'])
        self.assertEqual(res['meter'], [], res['meter'])
        self.assertEqual(self._ledger_lines(fx, 'revenium-hermes.ledger'), [])

    def test_job_is_still_created_while_the_ship_is_deferred(self):
        """The gate sits at the ship sites only; creation is not deferred."""
        fx = self._build_root()
        self._install_sqlite_stub(fx, _GATE_QUERY)
        res = self._tick(fx, 0)
        creates = [a for a in res['jobs'] if a[:2] == ['jobs', 'create']]
        self.assertEqual(len(creates), 1, res['jobs'])

    def test_next_tick_with_working_sqlite_ships_with_the_job_id_exactly_once(self):
        fx = self._build_root()
        shim = self._install_sqlite_stub(fx, _GATE_QUERY)
        self.assertEqual(self._tick(fx, 0)['meter'], [])
        os.remove(shim)

        recovered = self._tick(fx, 1)
        self.assertEqual(recovered['rc'], 0, recovered['output'])
        self.assertEqual(len(recovered['meter']), 1, recovered['meter'])
        self.assertEqual(
            argv_to_flags(recovered['meter'][0]).get('--agentic-job-id'), JOB_ID)
        self.assertEqual(len(self._ledger_lines(fx, 'revenium-hermes.ledger')), 1)

        again = self._tick(fx, 2)
        self.assertEqual(again['meter'], [], again['meter'])
        self.assertEqual(len(self._ledger_lines(fx, 'revenium-hermes.ledger')), 1)

    def test_deferral_warns_once_per_tick_however_many_markers_wait(self):
        fx = self._build_root(
            task_muids=('compat-muid-001', 'compat-muid-002', 'compat-muid-003'),
            aux=True,
        )
        self._install_sqlite_stub(fx, _GATE_QUERY)
        res = self._tick(fx, 0)
        self.assertEqual(len(self._warns(res)), 1, res['log_text'])
        res = self._tick(fx, 1)
        self.assertEqual(len(self._warns(res)), 2, res['log_text'])

    def test_a_healthy_gate_never_warns(self):
        fx = self._build_root()
        res = self._tick(fx, 0)
        self.assertEqual(self._warns(res), [], res['log_text'])

    def test_faulting_gate_defers_the_auxiliary_row_with_its_main_row(self):
        fx = self._build_root(aux=True)
        shim = self._install_sqlite_stub(fx, _GATE_QUERY)
        res = self._tick(fx, 0)
        self.assertEqual(res['rc'], 0, res['output'])
        main, aux = _split_meter(res['meter'])
        self.assertEqual((main, aux), ([], []), res['meter'])
        self.assertEqual(self._ledger_lines(fx, 'revenium-aux.ledger'), [])
        os.remove(shim)

        recovered = self._tick(fx, 1)
        main, aux = _split_meter(recovered['meter'])
        self.assertEqual(len(main), 1, recovered['meter'])
        self.assertEqual(len(aux), 1, recovered['meter'])
        self.assertEqual(main[0].get('--agentic-job-id'), JOB_ID)
        self.assertEqual(aux[0].get('--agentic-job-id'), JOB_ID)

        again = self._tick(fx, 2)
        self.assertEqual(again['meter'], [], again['meter'])

    def test_auxiliary_row_of_a_markerless_ship_is_deferred_not_supplemented_bare(self):
        """A job marker and no task marker: the markerless path never ships a
        job id, so the auxiliary cache is the only gate caller. A deferred
        session must not be recovered by the supplement with an empty job id."""
        fx = self._build(
            [_session(ROOT_SID)],
            parents={ROOT_SID: None},
            markers={ROOT_SID: [_job_marker(ROOT_SID)]},
            aux_rows=[_aux_row(ROOT_SID)],
        )
        shim = self._install_sqlite_stub(fx, _GATE_QUERY)
        res = self._tick(fx, 0)
        self.assertEqual(res['rc'], 0, res['output'])
        _main, aux = _split_meter(res['meter'])
        self.assertEqual(aux, [], res['meter'])
        self.assertEqual(self._ledger_lines(fx, 'revenium-aux.ledger'), [])
        os.remove(shim)

        recovered = self._tick(fx, 1)
        _main, aux = _split_meter(recovered['meter'])
        self.assertEqual(len(aux), 1, recovered['meter'])
        self.assertEqual(aux[0].get('--agentic-job-id'), JOB_ID)

    def test_session_without_a_job_marker_is_not_deferred_by_a_faulting_gate(self):
        """No owner, so the gate is never asked and the fault cannot matter."""
        fx = self._build(
            [_session(ROOT_SID)],
            parents={ROOT_SID: None},
            markers={ROOT_SID: [_task_marker(ROOT_SID, 'compat-muid-001')]},
        )
        self._install_sqlite_stub(fx, _GATE_QUERY)
        res = self._tick(fx, 0)
        self.assertEqual(len(res['meter']), 1, res['meter'])
        self.assertNotIn('--agentic-job-id', argv_to_flags(res['meter'][0]))
        self.assertEqual(self._warns(res), [], res['log_text'])


_PRAGMA = 'PRAGMA table_info(sessions)'


class ColumnProbeTests(_GateBase):
    """WR-02: `sessions_has_parent_session_id` separates "the PRAGMA saw the
    schema and the column is missing" from "the PRAGMA failed", and only the
    first may become a warn plus a permanent sentinel."""

    def _probe(self, fx, script_tail, remove_db=False):
        if remove_db:
            os.remove(fx['state_db'])
        env = {
            **os.environ,
            'HOME': fx['shim_home'],
            'HERMES_HOME': fx['hermes_home'],
            'REVENIUM_STATE_DIR': fx['state_dir'],
            'PATH': fx['bin_dir'] + os.pathsep + os.environ.get('PATH', ''),
        }
        script = 'source "$1/common.sh"; ' + script_tail
        res = subprocess.run(
            ['bash', '-c', script, 'bash', str(SCRIPTS_DIR)],
            env=env, capture_output=True, text=True, timeout=30,
        )
        return res.stdout.split()

    _RC = 'sessions_has_parent_session_id; echo $?; '

    def test_column_present_is_zero(self):
        fx = self._build([_session(ROOT_SID)], parents={ROOT_SID: None})
        self.assertEqual(self._probe(fx, self._RC), ['0'])

    def test_successful_pragma_without_the_column_is_one(self):
        fx = self._build([_session(ROOT_SID)], parents=None)
        self.assertEqual(self._probe(fx, self._RC), ['1'])

    def test_failed_pragma_is_two(self):
        fx = self._build([_session(ROOT_SID)], parents={ROOT_SID: None})
        self._install_sqlite_stub(fx, _PRAGMA)
        self.assertEqual(self._probe(fx, self._RC), ['2'])

    def test_missing_state_db_is_two_and_is_not_created(self):
        fx = self._build([_session(ROOT_SID)], parents={ROOT_SID: None})
        self.assertEqual(self._probe(fx, self._RC, remove_db=True), ['2'])
        self.assertFalse(os.path.exists(fx['state_db']))

    def test_a_failed_probe_is_not_memoised_as_absent(self):
        """First call fails (stub on PATH), second succeeds in the SAME shell:
        a memoised "no" would answer 1 here."""
        fx = self._build([_session(ROOT_SID)], parents={ROOT_SID: None})
        stub_dir = os.path.join(fx['tmpdir'], 'stubbin')
        os.makedirs(stub_dir)
        shutil.move(self._install_sqlite_stub(fx, _PRAGMA),
                    os.path.join(stub_dir, 'sqlite3'))
        tail = (
            f'PATH={shlex.quote(stub_dir)}:"$PATH"; hash -r; '
            f'{self._RC}'
            f'PATH="${{PATH#{shlex.quote(stub_dir)}:}}"; hash -r; '
            f'{self._RC}'
        )
        self.assertEqual(self._probe(fx, tail), ['2', '0'])

    def test_failed_pragma_never_writes_the_absent_sentinel_or_warns(self):
        """A withheld owner on a column-absent host reaches the warn; a PRAGMA
        that cannot be read must not turn that into a permanent false claim."""
        fx = self._build(
            [_session(ROOT_SID)],
            parents=None,
            markers={ROOT_SID: [_task_marker(ROOT_SID, 'compat-muid-001'), _job_marker(ROOT_SID)]},
        )
        self._install_sqlite_stub(fx, _PRAGMA)
        sentinel = os.path.join(
            fx['state_dir'], 'markers', '.probe-warn',
            'sessions-parent_session_id-absent')

        res = self._tick(fx, 0)
        self.assertEqual(res['rc'], 0, res['output'])
        self.assertEqual(len(res['meter']), 1, res['meter'])
        self.assertNotIn('--agentic-job-id', argv_to_flags(res['meter'][0]))
        self.assertFalse(os.path.exists(sentinel))
        self.assertNotIn('no sessions.parent_session_id column', res['log_text'])


if __name__ == '__main__':
    unittest.main()
