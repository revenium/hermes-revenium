"""The event path resolves owning_job_id by FILE POSITION, like the legacy one.

Why this exists. `revenium jobs roi <id>` returned `transactionCount: 0,
totalCost: 0` for essentially every fleet job, while the rows themselves were
metered fine — they just carried no `--agentic-job-id`. Measured on the fleet
2026-09-16, two jobs, both ROOT cron sessions:

    patch_sentry_watch_..._ed4f  (legacy-shipped)     transactionCount 2, cost 0.063108
    tableforone_bsky_..._62c2    (event-path only)    transactionCount 0, cost 0

A root session's transactions DO link — when `hermes-report.sh` ships them. It
runs a deferred `owning_job_id` pass; `api-event-report.sh` never received one,
and additionally dropped job markers at the loader (`kind is not None`), so it
was structurally incapable of producing a job id for a root session. 27 of 28
recent job-bearing sessions were event-path-only, which is why this mattered.

The rule is FILE POSITION, not timestamp, and that is load-bearing: session
ownership can flip between the two paths mid-session, so a timestamp rule here
would disagree with the legacy pass on the same marker file and split one
session's transactions across job ids. These tests pin the agreement, not just
the presence of a flag.
"""
import json
import os
import shlex
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests._compat_helpers import argv_to_flags, build_shim, run_script

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / 'skills' / 'revenium' / 'scripts'

_OLD_TS = 1715514000.0

# Sentinel: default `created_jobs` to every job marker in the case.
_ALL_JOB_MARKERS = object()


def _write_jsonl(path, records):
    with open(path, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, separators=(',', ':')) + '\n')


def _seed_sessions_db(db_path, rows, profile_name=None):
    """sessions table WITH parent_session_id (so get_root_session_id can
    resolve a root distinct from the child) and profile_name (the ONLY source
    `resolve-markers-dir.py` consults for the owning profile, per Phase 59
    D-18). Shape follows tests/test_phase29_agent_inheritance.py."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, model TEXT, source TEXT,
                input_tokens INTEGER, output_tokens INTEGER,
                cache_read_tokens INTEGER, cache_write_tokens INTEGER,
                reasoning_tokens INTEGER, estimated_cost_usd REAL,
                api_call_count INTEGER, started_at REAL, ended_at REAL,
                billing_provider TEXT, parent_session_id TEXT,
                profile_name TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (sid, "claude-sonnet-4-6", "test", 100, 50, 0, 0, 0,
                 0.0, 1, _OLD_TS, _OLD_TS, "anthropic", parent, profile_name)
                for sid, parent in rows
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _event_record(sid, arid, ts, ended_at, **overrides):
    rec = {
        'v': 1, 'sid': sid, 'api_request_id': arid,
        'ts': ts, 'ended_at': ended_at, 'duration_ms': 500,
        'platform': 'cli', 'model': 'claude-sonnet-4-6',
        'response_model': 'claude-sonnet-4-6', 'provider': 'anthropic',
        'base_url': 'https://api.anthropic.com', 'api_mode': 'anthropic_messages',
        'finish_reason': 'stop',
        'input_tokens': 100, 'output_tokens': 50,
        'cache_read_tokens': 0, 'cache_write_tokens': 0,
        'reasoning_tokens': 0, 'total_tokens': 150,
    }
    rec.update(overrides)
    return rec


def _muid(tag):
    base = f'{abs(hash(tag)):x}'
    return (base + '0' * 33)[:33]


def _task_marker(sid, task_type, ts, **extra):
    m = {
        'muid': _muid(f'{sid}{task_type}{ts}'), 'ts': ts, 'sid': sid,
        'task_type': task_type, 'operation_type': 'CHAT', 'trace_id': sid,
    }
    m.update(extra)
    return m


def _job_marker(sid, job_id, ts, status='SUCCESS'):
    return {
        'kind': 'job', 'ts': ts, 'sid': sid, 'agentic_job_id': job_id,
        'job_name': 'Monitor something', 'job_type': 'social_media_monitoring',
        'status': status,
    }


class EventPathOwningJobIdBase(unittest.TestCase):
    def _setup_tree(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-event-owning-job-')
        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        spool_dir = os.path.join(state_dir, 'api-events')
        markers_dir = os.path.join(state_dir, 'markers')
        ready_dir = os.path.join(markers_dir, '.ready')
        os.makedirs(spool_dir, mode=0o700)
        os.makedirs(markers_dir, mode=0o700)
        os.makedirs(ready_dir, mode=0o700)

        shim_home = os.path.join(tmpdir, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)
        build_shim(os.path.join(bin_dir, 'revenium'))

        return tmpdir, hermes_home, state_dir, spool_dir, markers_dir, ready_dir, shim_home

    def _run(self, hermes_home, state_dir, shim_home, meter_log, inv_log):
        env = {
            **os.environ,
            'HOME': shim_home,
            'HERMES_HOME': hermes_home,
            'REVENIUM_STATE_DIR': state_dir,
            'PATH': os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': inv_log,
            'METER_LOG': meter_log,
            'TZ': 'UTC',
            'REVENIUM_EVENT_METERING_MODE': 'live',
        }
        return run_script(SCRIPTS_DIR / 'api-event-report.sh', env, inv_log)

    def _completions(self, meter_log):
        invs = []
        if os.path.exists(meter_log):
            with open(meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        invs.append(shlex.split(line))
        return [a for a in invs if len(a) >= 2 and a[0] == 'meter' and a[1] == 'completion']

    def _run_case(self, sid, marker_records, events, sessions=None,
                  created_jobs=_ALL_JOB_MARKERS):
        """created_jobs: job ids to write into revenium-jobs.ledger as created.

        Defaults to every job id in `marker_records`, which is the steady state
        -- hermes-report.sh creates the job, and only then does this path have
        anything to attribute to. Pass [] to model the RACE: the event arriving
        before its job exists.
        """
        tmpdir, hh, sd, spool_dir, markers_dir, ready_dir, shim_home = self._setup_tree()
        try:
            Path(ready_dir, sid).touch()
            _write_jsonl(os.path.join(markers_dir, f'{sid}.jsonl'), marker_records)
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'), events)
            if sessions:
                _seed_sessions_db(os.path.join(hh, 'state.db'), sessions)

            if created_jobs is _ALL_JOB_MARKERS:
                created_jobs = [r['agentic_job_id'] for r in marker_records
                                if r.get('kind') == 'job' and r.get('agentic_job_id')]
            with open(os.path.join(sd, 'revenium-jobs.ledger'), 'w') as f:
                for jid in created_jobs:
                    f.write(f'JOB:{jid}:created:1715515200.0\n')

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)
            return [argv_to_flags(a) for a in self._completions(meter_log)], out
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class ForwardRuleTests(EventPathOwningJobIdBase):
    """Primary rule (D-08): a task marker is owned by the FIRST job marker
    BELOW it in file order. This is the ordinary arc shape, and the one the
    fleet's cron sessions produce."""

    def test_root_task_marker_binds_to_the_job_marker_written_after_it(self):
        sid = 'evt-root-forward'
        flags, out = self._run_case(
            sid,
            [
                _task_marker(sid, 'social_mention_watch', 1000000.0),
                _job_marker(sid, 'tableforone_bsky_monitor_62c2', 1000014.0),
            ],
            [_event_record(sid, f'{sid}:t1:api:1', 1000005.0, 1000005.5)],
            sessions=[(sid, None)],
        )
        self.assertEqual(len(flags), 1, f'expected 1 completion: {flags!r}\n{out}')
        self.assertEqual(
            flags[0].get('--agentic-job-id'), 'tableforone_bsky_monitor_62c2',
            'a ROOT session\'s event must carry the job id resolved from the job '
            'marker written AFTER its task marker -- without this the metered row '
            'never links and `jobs roi` reports transactionCount 0'
        )

    def test_the_14_second_ordering_gap_is_not_an_obstacle(self):
        """The job marker lands ~14s AFTER the task marker in wall-clock and
        after it in file order. Resolution happens at report time, so the id
        need not have existed when the task marker was written."""
        sid = 'evt-root-late-job'
        flags, out = self._run_case(
            sid,
            [
                _task_marker(sid, 'social_mention_watch', 1000000.0),
                _job_marker(sid, 'late_job_9f3a', 1000014.0),
            ],
            [_event_record(sid, f'{sid}:t1:api:1', 1000000.5, 1000001.0)],
            sessions=[(sid, None)],
        )
        self.assertEqual(len(flags), 1, out)
        self.assertEqual(flags[0].get('--agentic-job-id'), 'late_job_9f3a')


class NearestPrecedingFallbackTests(EventPathOwningJobIdBase):
    """TRACE-FIX 2026-06-25's fallback: the classifier writes at most ONE job
    marker per session, EARLY, so in long-lived sessions later task markers
    accumulate BELOW it. A forward-only rule strands them -- the defect that
    note records as "shipping ~95% of completions with no --agentic-job-id"."""

    def test_task_markers_below_the_only_job_marker_still_bind_to_it(self):
        sid = 'evt-root-trailing'
        flags, out = self._run_case(
            sid,
            [
                _task_marker(sid, 'first_turn', 1000000.0),
                _job_marker(sid, 'early_job_c4d1', 1000010.0),
                _task_marker(sid, 'second_turn', 1000100.0),
                _task_marker(sid, 'third_turn', 1000200.0),
            ],
            [
                _event_record(sid, f'{sid}:t1:api:1', 1000005.0, 1000005.5),
                _event_record(sid, f'{sid}:t2:api:2', 1000150.0, 1000150.5),
                _event_record(sid, f'{sid}:t3:api:3', 1000250.0, 1000250.5),
            ],
            sessions=[(sid, None)],
        )
        self.assertEqual(len(flags), 3, f'expected 3 completions: {flags!r}\n{out}')
        for f in flags:
            self.assertEqual(
                f.get('--agentic-job-id'), 'early_job_c4d1',
                'every task marker on the session binds to the single job '
                f'marker, including those below it in file order: {f!r}'
            )

    def test_the_rule_is_file_position_not_timestamp(self):
        """A job marker whose `ts` is older than the task marker's but which
        sits LATER in the file still owns it. Timestamp and file order
        disagree here on purpose: legacy resolves by position, and the two
        paths must agree or a session whose ownership flips mid-run splits
        its transactions across job ids."""
        sid = 'evt-root-position-wins'
        flags, out = self._run_case(
            sid,
            [
                _task_marker(sid, 'the_task', 1000500.0),
                # Written later in the file, but carries an EARLIER ts.
                _job_marker(sid, 'position_wins_7b2c', 1000100.0),
            ],
            [_event_record(sid, f'{sid}:t1:api:1', 1000600.0, 1000600.5)],
            sessions=[(sid, None)],
        )
        self.assertEqual(len(flags), 1, out)
        self.assertEqual(flags[0].get('--agentic-job-id'), 'position_wins_7b2c')


class SubagentUnchangedTests(EventPathOwningJobIdBase):
    """hermes-report.sh refuses to ship a SUBAGENT's own owning id: JOB-02
    suppresses the job create for subagents, so the id would orphan-reference
    a Revenium job row that does not exist. The event path must refuse
    identically."""

    def test_subagent_session_does_not_ship_a_resolved_owner(self):
        child, root = 'evt-subagent-child', 'evt-subagent-root'
        flags, out = self._run_case(
            child,
            [
                _task_marker(child, 'delegated_work', 1000000.0),
                _job_marker(child, 'must_not_ship_1a2b', 1000014.0),
            ],
            [_event_record(child, f'{child}:t1:api:1', 1000005.0, 1000005.5)],
            sessions=[(root, None), (child, root)],
        )
        self.assertEqual(len(flags), 1, out)
        self.assertNotIn(
            '--agentic-job-id', flags[0],
            'a subagent session must not ship a RESOLVED owner -- JOB-02 '
            'suppressed the create, so the row would reference a job that '
            f'does not exist: {flags[0]!r}'
        )
        # Proves the session really was treated as a subagent, so the
        # assertion above cannot pass for the wrong reason.
        self.assertEqual(flags[0].get('--squad-role'), 'subagent')

    def test_subagent_marker_carrying_its_own_job_id_is_unchanged(self):
        """A subagent marker's OWN agentic_job_id names the ROOT's job and has
        always shipped. The resolution pass must not disturb it."""
        child, root = 'evt-subagent-own-child', 'evt-subagent-own-root'
        flags, out = self._run_case(
            child,
            [_task_marker(child, 'delegated_work', 1000000.0,
                          agentic_job_id='roots_job_d4e5')],
            [_event_record(child, f'{child}:t1:api:1', 1000005.0, 1000005.5)],
            sessions=[(root, None), (child, root)],
        )
        self.assertEqual(len(flags), 1, out)
        self.assertEqual(flags[0].get('--agentic-job-id'), 'roots_job_d4e5')


class JobMustExistBeforeAttributionTests(EventPathOwningJobIdBase):
    """Production regression, 2026-09-17, one day after the resolution pass
    shipped: job Name and Type stopped being set reliably.

    `hermes-report.sh` is the ONLY creator of job rows and the only caller that
    passes --name/--type. Once this path also began sending --agentic-job-id,
    the two raced. When a transaction carrying an id Revenium has not seen
    arrives FIRST, the platform auto-creates a BARE job row; hermes-report.sh's
    later `jobs create` then gets a 409, which it treats as success by design
    (D-09) and ledgers — so name and type are dropped silently and for good
    (`revenium jobs update` can restore a name and has no --type at all).

    Measured both directions within hours on the fleet:

        table_for_one_mention_check_7488  create 07:09:02Z, event 07:13:42Z -> metadata KEPT
        reddit_opportunity_scan_sept17_f7be  event 14:06:54Z, create 14:07:03Z -> metadata LOST

    4 of the 5 jobs created that day lost it. So: never attribute to a job that
    does not exist locally yet."""

    def test_event_arriving_before_its_job_exists_omits_the_id(self):
        """The losing side of the race. The id must NOT ship, because shipping
        it is what auto-creates the bare row that costs the job its name."""
        sid = 'evt-job-not-yet-created'
        flags, out = self._run_case(
            sid,
            [
                _task_marker(sid, 'social_mention_watch', 1000000.0),
                _job_marker(sid, 'not_yet_created_4f2a', 1000014.0),
            ],
            [_event_record(sid, f'{sid}:t1:api:1', 1000005.0, 1000005.5)],
            sessions=[(sid, None)],
            created_jobs=[],  # hermes-report.sh has not created it yet
        )
        self.assertEqual(len(flags), 1, out)
        self.assertNotIn(
            '--agentic-job-id', flags[0],
            'the job does not exist yet, so shipping its id would let the '
            'platform auto-create a BARE job row and permanently cost it the '
            f'--name/--type that only `jobs create` supplies: {flags[0]!r}'
        )

    def test_the_event_itself_still_ships(self):
        """The gate withholds the DIMENSION, never the event. A job that is
        never created (a markerless session) must not strand its events —
        deferring them would lose real metered spend."""
        sid = 'evt-still-ships'
        flags, out = self._run_case(
            sid,
            [
                _task_marker(sid, 'social_mention_watch', 1000000.0),
                _job_marker(sid, 'never_created_8c1d', 1000014.0),
            ],
            [
                _event_record(sid, f'{sid}:t1:api:1', 1000005.0, 1000005.5),
                _event_record(sid, f'{sid}:t2:api:2', 1000006.0, 1000006.5),
            ],
            sessions=[(sid, None)],
            created_jobs=[],
        )
        self.assertEqual(
            len(flags), 2,
            f'both events must still be metered, only the job id withheld: {flags!r}\n{out}'
        )
        for f in flags:
            self.assertEqual(f.get('--task-type'), 'social_mention_watch')
            self.assertEqual(f.get('--input-tokens'), '100')

    def test_once_the_job_exists_the_id_ships(self):
        """The winning side: hermes-report.sh created the job first, so the row
        already carries its name and type and attribution is safe."""
        sid = 'evt-job-exists'
        flags, out = self._run_case(
            sid,
            [
                _task_marker(sid, 'social_mention_watch', 1000000.0),
                _job_marker(sid, 'already_created_9e3b', 1000014.0),
            ],
            [_event_record(sid, f'{sid}:t1:api:1', 1000005.0, 1000005.5)],
            sessions=[(sid, None)],
            created_jobs=['already_created_9e3b'],
        )
        self.assertEqual(len(flags), 1, out)
        self.assertEqual(flags[0].get('--agentic-job-id'), 'already_created_9e3b')

    def test_a_different_job_in_the_ledger_does_not_authorise_this_one(self):
        """The gate matches the resolved id exactly — a populated ledger is not
        a blanket pass."""
        sid = 'evt-other-job-ledgered'
        flags, out = self._run_case(
            sid,
            [
                _task_marker(sid, 'social_mention_watch', 1000000.0),
                _job_marker(sid, 'this_one_5a7c', 1000014.0),
            ],
            [_event_record(sid, f'{sid}:t1:api:1', 1000005.0, 1000005.5)],
            sessions=[(sid, None)],
            created_jobs=['some_other_job_1b2c'],
        )
        self.assertEqual(len(flags), 1, out)
        self.assertNotIn('--agentic-job-id', flags[0])


class MultiplexedProfileLedgerTests(EventPathOwningJobIdBase):
    """PR #126 review (P2). `_jobs_ledger_for_markers_dir` has a second branch
    for a session whose markers live under a NAMED profile, and the cases above
    only ever exercise the process-level one.

    That branch is exactly where a silent regression would hide: on a
    multiplexed host each profile keeps its own ledger, and consulting the
    process-level one would ask the WRONG profile whether the job exists —
    removing job attribution for every named profile while every
    process-level test stayed green.

    So both directions are asserted: the owning profile's sibling ledger
    authorises the id, and the process-level ledger does NOT."""

    def _run_multiplexed(self, profile, sid, job_id,
                         in_profile_ledger, in_process_ledger):
        tmpdir, hh, sd, spool_dir, _markers_dir, _ready_dir, shim_home = self._setup_tree()
        try:
            # The session's markers live under the NAMED profile, resolved from
            # sessions.profile_name (Phase 59 D-18). The spool stays
            # process-level: the multi-profile spool sweep was deliberately
            # removed (the cross-profile double-ship fix), so this is the real
            # multiplexed shape.
            p_state = os.path.join(hh, 'profiles', profile, 'state', 'revenium')
            p_markers = os.path.join(p_state, 'markers')
            os.makedirs(os.path.join(p_markers, '.ready'), mode=0o700)
            Path(p_markers, '.ready', sid).touch()

            _write_jsonl(os.path.join(p_markers, f'{sid}.jsonl'), [
                _task_marker(sid, 'social_mention_watch', 1000000.0),
                _job_marker(sid, job_id, 1000014.0),
            ])
            _write_jsonl(os.path.join(spool_dir, f'{sid}.jsonl'),
                         [_event_record(sid, f'{sid}:t1:api:1', 1000005.0, 1000005.5)])

            _seed_sessions_db(os.path.join(hh, 'state.db'), [(sid, None)],
                              profile_name=profile)

            for path, present in ((os.path.join(p_state, 'revenium-jobs.ledger'),
                                   in_profile_ledger),
                                  (os.path.join(sd, 'revenium-jobs.ledger'),
                                   in_process_ledger)):
                with open(path, 'w') as f:
                    if present:
                        f.write(f'JOB:{job_id}:created:1715515200.0\n')

            meter_log = os.path.join(tmpdir, 'meter.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            rc, _invs, out = self._run(hh, sd, shim_home, meter_log, inv_log)
            self.assertEqual(rc, 0, out)
            comps = self._completions(meter_log)
            return [argv_to_flags(a) for a in comps], out
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_owning_profiles_ledger_authorises_the_id(self):
        flags, out = self._run_multiplexed(
            'marketing', 'evt-mux-owned', 'mux_job_7d3e',
            in_profile_ledger=True, in_process_ledger=False,
        )
        self.assertEqual(len(flags), 1, out)
        self.assertEqual(
            flags[0].get('--agentic-job-id'), 'mux_job_7d3e',
            'the job IS created in the owning profile\'s ledger; reading only '
            'the process-level one would silently drop attribution for every '
            f'named profile: {flags[0]!r}\n{out}'
        )

    def test_process_level_ledger_does_not_authorise_another_profiles_job(self):
        """The negative that proves it asks the RIGHT ledger rather than any
        reachable one."""
        flags, out = self._run_multiplexed(
            'marketing', 'evt-mux-wrong', 'mux_job_9f1a',
            in_profile_ledger=False, in_process_ledger=True,
        )
        self.assertEqual(len(flags), 1, out)
        self.assertNotIn(
            '--agentic-job-id', flags[0],
            'the owning profile has not created this job — a hit in the '
            f'process-level ledger must not stand in for it: {flags[0]!r}'
        )


class UnresolvableAncestryTests(EventPathOwningJobIdBase):
    """PR #125 review (P1). `get_root_session_id` fails OPEN: it returns the
    INPUT sid when state.db is missing, when sqlite errors, and when the
    sessions table simply has no row. So `root_sid == sid` cannot tell
    "genuinely root" from "could not tell", and a subagent whose ancestry did
    not resolve would be treated as root — shipping a resolved owner for a job
    row JOB-02 never created.

    The resolved owner therefore requires POSITIVE evidence of rootness: the
    row exists AND its parent_session_id is NULL. Everything else omits the
    flag, which is byte-identical to the behaviour before the pass existed.

    This costs nothing in production: on the fleet 2026-09-16 every session had
    a row (marketing 385/385, gtm 90/90, devops 1981/1981), all root."""

    def test_no_state_db_at_all_omits_the_resolved_owner(self):
        sid = 'evt-no-statedb'
        flags, out = self._run_case(
            sid,
            [
                _task_marker(sid, 'some_work', 1000000.0),
                _job_marker(sid, 'unprovable_owner_8a1f', 1000014.0),
            ],
            [_event_record(sid, f'{sid}:t1:api:1', 1000005.0, 1000005.5)],
            sessions=None,
        )
        self.assertEqual(len(flags), 1, out)
        self.assertNotIn(
            '--agentic-job-id', flags[0],
            'rootness was unprovable (no state.db), so the resolved owner must '
            f'not ship: {flags[0]!r}'
        )

    def test_session_missing_from_the_sessions_table_omits_the_resolved_owner(self):
        """The exact review case: the db exists and is readable, but this
        session has no row — so `get_root_session_id` hands back the input sid
        and the naive test would call it root."""
        sid = 'evt-row-missing'
        flags, out = self._run_case(
            sid,
            [
                _task_marker(sid, 'some_work', 1000000.0),
                _job_marker(sid, 'unprovable_owner_3c9d', 1000014.0),
            ],
            [_event_record(sid, f'{sid}:t1:api:1', 1000005.0, 1000005.5)],
            sessions=[('some-other-session', None)],
        )
        self.assertEqual(len(flags), 1, out)
        self.assertNotIn(
            '--agentic-job-id', flags[0],
            'the session has no row, so rootness is unproven and the resolved '
            f'owner must not ship: {flags[0]!r}'
        )


class NoJobMarkerUnchangedTests(EventPathOwningJobIdBase):
    """Backward compatibility: a session with no job marker meters exactly as
    it did before this change."""

    def test_session_with_no_job_marker_omits_the_flag(self):
        sid = 'evt-root-no-job'
        flags, out = self._run_case(
            sid,
            [_task_marker(sid, 'plain_chat', 1000000.0)],
            [_event_record(sid, f'{sid}:t1:api:1', 1000005.0, 1000005.5)],
        )
        self.assertEqual(len(flags), 1, out)
        self.assertNotIn('--agentic-job-id', flags[0])
        # The join itself is untouched -- job markers never entered the
        # window-boundary list, so task_type still comes from the task marker.
        self.assertEqual(flags[0].get('--task-type'), 'plain_chat')

    def test_a_job_marker_does_not_become_a_join_window_boundary(self):
        """The regression this guards: putting job markers into
        `window_markers` would move task_type/operation_type attribution for
        every event on the session. The event below sits AFTER the job marker
        in both time and file order, and must still take the task marker's
        label."""
        sid = 'evt-root-window-intact'
        flags, out = self._run_case(
            sid,
            [
                _task_marker(sid, 'social_mention_watch', 1000000.0),
                _job_marker(sid, 'window_job_5c6d', 1000010.0),
            ],
            [_event_record(sid, f'{sid}:t1:api:1', 1000050.0, 1000050.5)],
            sessions=[(sid, None)],
        )
        self.assertEqual(len(flags), 1, out)
        self.assertEqual(
            flags[0].get('--task-type'), 'social_mention_watch',
            'a job marker must never act as a join-window boundary'
        )
        self.assertEqual(flags[0].get('--operation-type'), 'CHAT')
        self.assertEqual(flags[0].get('--agentic-job-id'), 'window_job_5c6d')


if __name__ == '__main__':
    unittest.main()
