"""quick-260817-tfe (OWN-01..OWN-04) — the durable, atomically-claimed session
ownership record.

Two metering paths must partition sessions disjointly: hermes-report.sh (the
legacy per-session delta path) and api-event-report.sh (the per-API-call event
path). Before this change ownership was DERIVED — each path grepped the
other's BILLING ledger at an arbitrary instant — which conflated two different
facts and produced two P1 defects:

  P1-1 (atomicity).  The partition was order-dependent. On 2026-08-17 a real
    production session (`20260817_213057_3a319e` on profile `coder`) was
    billed by BOTH paths: the event shipper claimed it at 21:32:46 and the
    legacy stage billed it again at 21:33:28. See
    .planning/phases/32-event-driven-metering-on-post-api-request/32-CANARY-EVIDENCE.md.
  P1-2 (retention). The ownership signal lived in a ledger that
    prune-markers.sh prunes at MARKER_RETENTION_DAYS, so ~30 days on a
    still-live session erased its only ownership record and let the legacy
    path re-bill its entire cumulative token count from a ZERO baseline.

Ownership is now a fact established ONCE, by an O_EXCL create under
OWNERS_DIR, whose lifetime is keyed on presence in state.db rather than on the
billing ledgers' retention.

Each class covers ONE axis, so a mutation to one guard fails its own class and
only its own class:

  OrderingPartitionTests   — ordering + migration state (Task 1)
  RetentionOwnershipTests  — record lifetime vs billing-ledger retention (Task 2)
  AtomicClaimTests         — the exclusive create as the sole arbiter (Task 3)
  FailOpenAndCompatTests   — OWN-03 backward compat + OWN-04 fail direction (Task 3)

Assertions are on the SHIPPING surfaces — captured argv and the ledger/owners
files on disk — not on log prose, except where a log line IS the deliverable
(the once-per-record dual-ledger warn, and the fail-closed defer).
"""
import json
import os
import shlex
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from tests._compat_helpers import (
    argv_to_flags,
    assert_argv_matches_golden,
    build_shim,
    build_state_db,
    load_golden,
    run_script,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / 'skills' / 'revenium' / 'scripts'

SID = 'ownership-sid-001'

# Far enough in the past that hermes-report.sh's G-03 sentinel-or-aged filter
# and api-event-report.sh's C-6 settle gate both pass on AGE alone, with no
# .ready sentinel — the same 2024 timestamp the compat suites use for exactly
# this reason.
OLD_TS = 1715514000.0


def _write_jsonl(path, records):
    with open(path, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, separators=(',', ':')) + '\n')


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


def _session_row(sid=SID, input_tokens=100, output_tokens=50, **overrides):
    row = {
        'id': sid,
        'model': 'claude-sonnet-4-6',
        'source': 'test',
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'cache_read': 0,
        'cache_write': 0,
        'reasoning': 0,
        'estimated_cost': '0',
        'api_calls': 1,
        'started_at': OLD_TS,
        'ended_at': OLD_TS,
        'billing_provider': 'anthropic',
    }
    row.update(overrides)
    return row


class OwnershipTestBase(unittest.TestCase):
    """One tree, BOTH scripts.

    The partition is a property of the two shippers TOGETHER, so a fixture
    that only one of them can see cannot assert it. This base builds a single
    state tree — one state.db, one markers dir, one spool dir, one set of
    ledgers, one owners dir — and gives each script invocation its OWN meter
    log so the two sides' completions stay attributable separately.

    The shim lives under the test HOME's .local/bin because ensure_path's LAST
    prepend is "${HOME}/.local/bin"; anywhere else and real system binaries
    shadow it.
    """

    def _setup_tree(self, sessions=None, session_kwargs=None, shim_kwargs=None):
        tmpdir = tempfile.mkdtemp(prefix='gsd-ownership-')
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
        build_shim(os.path.join(bin_dir, 'revenium'), **(shim_kwargs or {}))

        state_db = os.path.join(hermes_home, 'state.db')
        if sessions is None:
            sessions = [_session_row(**(session_kwargs or {}))]
        if sessions:
            build_state_db(state_db, sessions)

        return {
            'tmpdir': tmpdir,
            'hermes_home': hermes_home,
            'state_dir': state_dir,
            'spool_dir': spool_dir,
            'markers_dir': markers_dir,
            'ready_dir': ready_dir,
            'shim_home': shim_home,
            'bin_dir': bin_dir,
            'state_db': state_db,
            'owners_dir': os.path.join(state_dir, 'owners'),
            'legacy_ledger': os.path.join(state_dir, 'revenium-hermes.ledger'),
            'event_ledger': os.path.join(state_dir, 'revenium-api-events.ledger'),
            'legacy_meter_log': os.path.join(tmpdir, 'legacy-meter.log'),
            'event_meter_log': os.path.join(tmpdir, 'event-meter.log'),
            'jobs_log': os.path.join(tmpdir, 'jobs.log'),
            'inv_log': os.path.join(tmpdir, 'inv.log'),
            'log_file': os.path.join(state_dir, 'revenium-metering.log'),
        }

    def _teardown_tree(self, t):
        # Restore any mode we tightened, or rmtree cannot descend.
        for d in (t['owners_dir'],):
            if os.path.isdir(d):
                try:
                    os.chmod(d, 0o700)
                except OSError:
                    pass
        shutil.rmtree(t['tmpdir'], ignore_errors=True)

    def _base_env(self, t, meter_log, extra_env=None):
        env = {
            **os.environ,
            'HOME': t['shim_home'],
            'HERMES_HOME': t['hermes_home'],
            'REVENIUM_STATE_DIR': t['state_dir'],
            'PATH': t['bin_dir'] + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': t['inv_log'],
            'METER_LOG': meter_log,
            'JOBS_LOG': t['jobs_log'],
            'TZ': 'UTC',
        }
        if extra_env:
            env.update(extra_env)
        return env

    def _run_legacy(self, t, extra_env=None):
        env = self._base_env(t, t['legacy_meter_log'], extra_env)
        rc, _inv, out = run_script(SCRIPTS_DIR / 'hermes-report.sh', env, t['inv_log'])
        return rc, out

    def _run_event(self, t, mode='live', extra_env=None):
        env = self._base_env(t, t['event_meter_log'], extra_env)
        # The default is "shadow", which ships nothing and would make every
        # event-side assertion vacuous — opt in explicitly.
        env.setdefault('REVENIUM_EVENT_METERING_MODE', mode)
        env['REVENIUM_EVENT_METERING_MODE'] = mode
        rc, _inv, out = run_script(SCRIPTS_DIR / 'api-event-report.sh', env, t['inv_log'])
        return rc, out

    # --- shipping surfaces -------------------------------------------------

    @staticmethod
    def _invocations(log_path):
        invs = []
        if os.path.exists(log_path):
            with open(log_path) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        invs.append(shlex.split(line))
        return invs

    def _completions(self, log_path):
        return [a for a in self._invocations(log_path)
                if len(a) >= 2 and a[0] == 'meter' and a[1] == 'completion']

    def _legacy_completions(self, t):
        return self._completions(t['legacy_meter_log'])

    def _event_completions(self, t):
        return self._completions(t['event_meter_log'])

    def _job_creates(self, t):
        return [a for a in self._invocations(t['jobs_log'])
                if len(a) >= 2 and a[0] == 'jobs' and a[1] == 'create']

    @staticmethod
    def _hermes_lines(t, sid=SID):
        if not os.path.exists(t['legacy_ledger']):
            return []
        with open(t['legacy_ledger'], encoding='utf-8') as f:
            return [l for l in f.read().splitlines() if l.startswith(f'HERMES:{sid}:')]

    @staticmethod
    def _api_lines(t, sid=SID):
        if not os.path.exists(t['event_ledger']):
            return []
        with open(t['event_ledger'], encoding='utf-8') as f:
            return [l for l in f.read().splitlines()
                    if l.startswith('API:') and f'|{sid}|' in l]

    @staticmethod
    def _owners_path(t, sid=SID):
        return os.path.join(t['owners_dir'], sid.replace('/', '_')[:200])

    def _owner_record(self, t, sid=SID):
        """(owner, baseline) from the record, or (None, None) when absent."""
        path = self._owners_path(t, sid)
        if not os.path.exists(path):
            return None, None
        with open(path, encoding='utf-8') as f:
            lines = f.read().splitlines()
        owner = lines[0].strip() if lines else ''
        baseline = lines[1].strip() if len(lines) > 1 else None
        return owner, baseline

    @staticmethod
    def _log_text(t):
        """log()'s stderr mirror is TTY-gated (common.sh), so under a captured
        subprocess nothing reaches stdout/stderr — log assertions must read
        revenium-metering.log from disk."""
        if not os.path.exists(t['log_file']):
            return ''
        with open(t['log_file'], encoding='utf-8') as f:
            return f.read()

    def _dual_ledger_warns(self, t, sid=SID):
        needle = 'dual-ledger session claimed for the legacy path'
        return [l for l in self._log_text(t).splitlines()
                if needle in l and sid in l]

    # --- fixture seeding ---------------------------------------------------

    def _seed_spool(self, t, sid=SID, count=1, ts=OLD_TS):
        """api_request_id values deliberately embed COLONS (the real shape the
        shipper writes), so an implementation that tried to parse the event
        ledger by colon position cannot accidentally pass."""
        records = [
            _event_record(sid, f'{sid}:t1:api:{i + 1}', ts + i, ts + i + 1)
            for i in range(count)
        ]
        _write_jsonl(os.path.join(t['spool_dir'], f'{sid}.jsonl'), records)

    def _seed_ready(self, t, sid=SID):
        Path(t['ready_dir'], sid).touch()

    def _seed_event_ledger(self, t, sid=SID, count=1, ts=1700000000.0):
        with open(t['event_ledger'], 'a', encoding='utf-8') as f:
            for i in range(count):
                f.write(f'API:{sid}:t1:api:{i + 1}|{sid}|{ts + i}\n')

    def _seed_legacy_ledger(self, t, sid=SID, totals=(150,), ts=1700000000.0):
        with open(t['legacy_ledger'], 'a', encoding='utf-8') as f:
            for i, total in enumerate(totals):
                f.write(f'HERMES:{sid}:{total}:{ts + i}:unclassified-{int(ts) + i}\n')

    def _seed_owner(self, t, sid=SID, owner='event', baseline=None):
        os.makedirs(t['owners_dir'], mode=0o700, exist_ok=True)
        with open(self._owners_path(t, sid), 'w', encoding='utf-8') as f:
            f.write(owner + '\n')
            if baseline is not None:
                f.write(str(baseline) + '\n')

    def _seed_job_marker(self, t, sid=SID, job_id='ownership-job-001'):
        _write_jsonl(os.path.join(t['markers_dir'], f'{sid}.jsonl'), [{
            'kind': 'job',
            'ts': OLD_TS + 1,
            'sid': sid,
            'agentic_job_id': job_id,
            'job_name': 'Ownership Test Job',
            'job_type': 'code_review',
            'status': 'IN_PROGRESS',
        }])

    @staticmethod
    def _grow_state_db(t, sid=SID, input_tokens=0, output_tokens=0):
        conn = sqlite3.connect(t['state_db'])
        conn.execute(
            'UPDATE sessions SET input_tokens=?, output_tokens=? WHERE id=?',
            (input_tokens, output_tokens, sid),
        )
        conn.commit()
        conn.close()


# ============================================================================
# Task 1 — ORDERING and MIGRATION STATE
# ============================================================================

class OrderingPartitionTests(OwnershipTestBase):

    # --- ordering, both directions ----------------------------------------

    def test_event_first_then_legacy_yields_exactly_one_event_completion(self):
        """The direction that broke on 2026-08-17: the event path reaches an
        unowned session first, and the legacy path must then defer to the
        durable record rather than to stage ordering."""
        t = self._setup_tree()
        try:
            self._seed_spool(t)
            self._seed_ready(t)

            rc, out = self._run_event(t)
            self.assertEqual(rc, 0, out)
            self.assertEqual(len(self._event_completions(t)), 1,
                             f'event path must ship this session: {out}')
            self.assertEqual(self._owner_record(t)[0], 'event')

            # quick-260818-0in (MODE-01/MODE-04): in real cron operation both
            # scripts resolve REVENIUM_EVENT_METERING_MODE from the SAME
            # config.json/env each tick, so a genuinely live event owner is
            # observed as live by both sides. Propagate the same mode this
            # test's _run_event call used, so this scenario models a
            # self-consistent operator configuration rather than the event
            # script running live while the legacy script independently
            # resolves the hard "shadow" default and takes the session over.
            rc, out = self._run_legacy(t, extra_env={'REVENIUM_EVENT_METERING_MODE': 'live'})
            self.assertEqual(rc, 0, out)
            self.assertEqual(self._legacy_completions(t), [],
                             'an event-owned session must never be billed by the legacy path')
            self.assertEqual(self._hermes_lines(t), [],
                             'no HERMES: line may be written for an event-owned session — '
                             'writing one would make it legacy-owned too and defeat the '
                             'partition from the other side')
            self.assertEqual(self._owner_record(t)[0], 'event',
                             'the losing side must never rewrite the record')
        finally:
            self._teardown_tree(t)

    def test_legacy_first_then_event_yields_exactly_one_legacy_completion(self):
        t = self._setup_tree()
        try:
            self._seed_spool(t)
            self._seed_ready(t)

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)
            self.assertEqual(len(self._legacy_completions(t)), 1,
                             f'legacy path must bill this session: {out}')
            self.assertEqual(len(self._hermes_lines(t)), 1)
            self.assertEqual(self._owner_record(t)[0], 'legacy')

            rc, out = self._run_event(t)
            self.assertEqual(rc, 0, out)
            self.assertEqual(self._event_completions(t), [],
                             'a legacy-owned session must never ship via the event path')
            self.assertEqual(self._api_lines(t), [])
            self.assertEqual(self._owner_record(t)[0], 'legacy')
        finally:
            self._teardown_tree(t)

    # --- D-10 preservation -------------------------------------------------

    def test_event_owned_session_still_creates_its_job_exactly_once(self):
        """api-event-report.sh SHIPS --agentic-job-id but contains zero `jobs
        create` calls — job creation is legacy-only (D-10). If the ownership
        suppression had become an early `continue` at the top of the session
        loop, every event row's job reference would be orphaned."""
        t = self._setup_tree()
        try:
            self._seed_event_ledger(t)
            self._seed_job_marker(t)

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            self.assertEqual(self._legacy_completions(t), [],
                             'completions must still be suppressed for an event-owned session')
            creates = self._job_creates(t)
            self.assertEqual(len(creates), 1,
                             'the jobs half must keep running for an event-owned session '
                             f'(D-10) — expected exactly one `jobs create`, got {creates!r}\n{out}')
            self.assertEqual(argv_to_flags(creates[0]).get('--agentic-job-id'),
                             'ownership-job-001')
        finally:
            self._teardown_tree(t)

    # --- migration, one ledger pre-existing --------------------------------

    def test_legacy_defers_and_backfills_an_event_owner(self):
        t = self._setup_tree()
        try:
            self._seed_event_ledger(t, count=4)

            # quick-260818-0in (MODE-01/MODE-04): API: ledger rows can only
            # exist because api-event-report.sh actually shipped them, which
            # only happens under EVENT_METERING_MODE=live (:1332's ledger
            # write sits inside the live-only shipping branch) — so their
            # presence is itself evidence the mode was live. Propagate that
            # here so the backfill claim is evaluated under the same
            # self-consistent configuration a real fleet host would have.
            rc, out = self._run_legacy(t, extra_env={'REVENIUM_EVENT_METERING_MODE': 'live'})
            self.assertEqual(rc, 0, out)

            self.assertEqual(self._legacy_completions(t), [], out)
            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'event',
                             'a session with API: rows and no owners record must be '
                             'BACKFILLED as event-owned, not merely skipped')
            self.assertIsNone(baseline,
                              'a non-dual claim must carry no catch-up baseline')
            self.assertIn('legacy completions suppressed for 1 session(s)', self._log_text(t))
        finally:
            self._teardown_tree(t)

    def test_event_skips_and_backfills_a_legacy_owner(self):
        t = self._setup_tree()
        try:
            self._seed_legacy_ledger(t)
            self._seed_spool(t)
            self._seed_ready(t)

            rc, out = self._run_event(t)
            self.assertEqual(rc, 0, out)

            self.assertEqual(self._event_completions(t), [], out)
            self.assertEqual(self._api_lines(t), [])
            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'legacy',
                             'a session with a HERMES: line and no owners record must be '
                             'BACKFILLED as legacy-owned')
            self.assertIsNone(baseline)
            self.assertEqual(self._dual_ledger_warns(t), [],
                             'a single-ledger session is not a dual-ledger session and '
                             'must not warn')
        finally:
            self._teardown_tree(t)

    # --- migration, DUAL ledger (the incident session's own shape) ---------

    # PROVENANCE — DO NOT "SIMPLIFY" THESE NUMBERS.
    # This is the literal on-disk state of session 20260817_213057_3a319e on
    # profile `coder`, re-queried from the fleet host on 2026-08-17 after the
    # canary halt: 2 HERMES: rows totalling 12,608 tokens and 4 API: rows, with
    # NO owners record. It is the highest-value fixture in this module
    # precisely because it is not synthetic — it is what a pre-fix double-bill
    # actually looks like on disk. A future reader who replaces it with
    # invented numbers loses that.
    INCIDENT_TOTAL = 12608
    INCIDENT_INPUT = 8608
    INCIDENT_OUTPUT = 4000
    INCIDENT_API_ROWS = 4

    def _seed_incident_dual_ledger(self, t):
        # Both HERMES: rows carry the session's FULL cumulative total, which is
        # why this fixture proves the RESOLUTION but cannot prove the catch-up
        # (its delta is already zero). The stale-baseline fixture below exists
        # for that, and must not be collapsed into this one.
        self._seed_legacy_ledger(t, totals=(self.INCIDENT_TOTAL, self.INCIDENT_TOTAL))
        self._seed_event_ledger(t, count=self.INCIDENT_API_ROWS)

    def _incident_tree(self):
        return self._setup_tree(session_kwargs={
            'input_tokens': self.INCIDENT_INPUT,
            'output_tokens': self.INCIDENT_OUTPUT,
        })

    def test_dual_ledger_resolves_to_legacy_from_the_legacy_entry_point(self):
        t = self._incident_tree()
        try:
            self._seed_incident_dual_ledger(t)
            self.assertIsNone(self._owner_record(t)[0], 'fixture: no owners record yet')

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'legacy',
                             'a session carrying rows in BOTH ledgers must resolve to the '
                             'LEGACY path — the event path may not even be enabled, and '
                             'ceding to it would bill the session with NEITHER path')
            self.assertEqual(baseline, str(self.INCIDENT_TOTAL),
                             'the dual claim must record the catch-up baseline')
            self.assertEqual(len(self._dual_ledger_warns(t)), 1,
                             'the dual-ledger warn must fire exactly once — it is evidence '
                             'of a past double-bill and must stay findable')
        finally:
            self._teardown_tree(t)

    def test_dual_ledger_resolves_to_legacy_from_the_event_entry_point(self):
        t = self._incident_tree()
        try:
            self._seed_incident_dual_ledger(t)
            self._seed_spool(t, count=self.INCIDENT_API_ROWS)
            self._seed_ready(t)

            rc, out = self._run_event(t)
            self.assertEqual(rc, 0, out)

            self.assertEqual(self._event_completions(t), [],
                             'the event path must ship nothing for a dual-ledger session')
            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'legacy',
                             'the resolution table is identical from either entry point')
            self.assertEqual(baseline, str(self.INCIDENT_TOTAL),
                             'the catch-up baseline must be written whichever process makes '
                             'the claim — otherwise the legacy path would still measure its '
                             'first post-claim delta from the stale HERMES: line')
            self.assertEqual(len(self._dual_ledger_warns(t)), 1)
        finally:
            self._teardown_tree(t)

    def test_dual_ledger_warn_fires_once_per_record_not_once_per_tick(self):
        """A dual-ledger session is a PERMANENT on-disk state that matches on
        every tick forever. An ungated warn here is the same unbounded
        per-tick warn this repo has already paid 9,039,937 lines in 27 days
        for (the reason WARN_FLAGS_DIR exists)."""
        t = self._incident_tree()
        try:
            self._seed_incident_dual_ledger(t)

            for _ in range(3):
                rc, out = self._run_legacy(t)
                self.assertEqual(rc, 0, out)

            self.assertEqual(len(self._dual_ledger_warns(t)), 1,
                             'three ticks over a permanent dual-ledger state must produce '
                             'exactly ONE warn — gated on the claim primitive\'s created flag')
        finally:
            self._teardown_tree(t)

    # --- migration, DUAL ledger with a STALE legacy baseline ---------------

    # The incident fixture above CANNOT prove the catch-up: its legacy line
    # already records the full cumulative total, so the delta is zero and the
    # re-bill never fires. A test built on it alone would pass trivially and be
    # decorative. These numbers make the bug REACHABLE: legacy's last line is
    # at 10,000 tokens, the event path shipped rows covering growth up to
    # 18,000, and state.db has since reached 20,000. Unfixed, the legacy path
    # bills a 10,000-token delta of which 8,000 were already metered by the
    # event path.
    STALE_LEDGER_TOTAL = 10000
    STALE_CLAIM_INPUT = 16000
    STALE_CLAIM_OUTPUT = 4000        # -> 20,000 at the claim instant
    STALE_GROWN_INPUT = 20000
    STALE_GROWN_OUTPUT = 5000        # -> 25,000 after further growth

    def test_dual_ledger_with_stale_baseline_ships_nothing_then_bills_the_growth_only(self):
        t = self._setup_tree(session_kwargs={
            'input_tokens': self.STALE_CLAIM_INPUT,
            'output_tokens': self.STALE_CLAIM_OUTPUT,
        })
        try:
            self._seed_legacy_ledger(t, totals=(self.STALE_LEDGER_TOTAL,))
            self._seed_event_ledger(t, count=4)

            # --- the claim tick: nothing may ship ---
            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)
            self.assertEqual(self._legacy_completions(t), [],
                             'the claim tick must ship NOTHING — the tokens between the '
                             'stale ledger line and the current total were already metered '
                             'by the event path and must never be re-billed')
            self.assertEqual(len(self._hermes_lines(t)), 1,
                             'only the seeded ledger line may exist after the claim tick')
            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'legacy')
            self.assertEqual(baseline, '20000')

            # --- further growth: only the growth bills ---
            self._grow_state_db(t, input_tokens=self.STALE_GROWN_INPUT,
                                output_tokens=self.STALE_GROWN_OUTPUT)
            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            completions = self._legacy_completions(t)
            self.assertEqual(len(completions), 1,
                             f'growth after the claim must bill exactly once: {out}')
            flags = argv_to_flags(completions[0])
            # Assert the TOKEN COUNTS, not merely the completion count: a
            # re-bill measured from the stale ledger line produces exactly ONE
            # completion too, so a count-only assertion cannot tell a correct
            # delta from a re-billed one.
            self.assertEqual(
                flags.get('--total-tokens'), '5000',
                'the delta must be measured from the CLAIM baseline (20,000), not from '
                'the stale ledger line (10,000) — a 15,000-token delta here means 10,000 '
                f'tokens the event path already metered were re-billed. argv: {completions[0]!r}')
            self.assertEqual(flags.get('--input-tokens'), '4000')
            self.assertEqual(flags.get('--output-tokens'), '1000')
        finally:
            self._teardown_tree(t)

    def test_dual_ledger_claim_never_re_bills_the_tokens_the_event_path_metered(self):
        """The same sequence, asserted ONLY on the total tokens billed across
        it. Deliberately makes no claim about the number of completions: a
        re-bill produces a perfectly ordinary-looking completion, and a
        count-only assertion would pass while the money went out twice. What
        distinguishes correct from re-billed is the TOKEN COUNT and nothing
        else."""
        t = self._setup_tree(session_kwargs={
            'input_tokens': self.STALE_CLAIM_INPUT,
            'output_tokens': self.STALE_CLAIM_OUTPUT,
        })
        try:
            self._seed_legacy_ledger(t, totals=(self.STALE_LEDGER_TOTAL,))
            self._seed_event_ledger(t, count=4)

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)
            self._grow_state_db(t, input_tokens=self.STALE_GROWN_INPUT,
                                output_tokens=self.STALE_GROWN_OUTPUT)
            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            billed = sum(int(argv_to_flags(c).get('--total-tokens', '0'))
                         for c in self._legacy_completions(t))
            self.assertEqual(
                billed, 5000,
                'the legacy path must bill exactly the 5,000 tokens of growth that '
                'occurred AFTER the claim. 15,000 means the 10,000-token overlap the '
                'event path had already metered was re-billed — the original defect\'s '
                'own class, reintroduced by the rule meant to close it. '
                f'Completions: {self._legacy_completions(t)!r}')
        finally:
            self._teardown_tree(t)

    # --- OWN-03: an install with no event path at all ----------------------

    def test_disengaged_install_bills_once_and_creates_no_ownership_state(self):
        """No event ledger, no owners directory, no spool files. The
        engagement gate must be false, so not one byte of ownership state is
        created and the wire output is unchanged."""
        t = self._setup_tree()
        try:
            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            completions = self._legacy_completions(t)
            self.assertEqual(len(completions), 1, f'{completions!r}\n{out}')
            self.assertEqual(argv_to_flags(completions[0]).get('--transaction-id'),
                             f'{SID}-150')
            self.assertEqual(len(self._hermes_lines(t)), 1)
            self.assertFalse(
                os.path.exists(t['owners_dir']),
                'an install with no event path in play must create NO ownership state — '
                'the lazy mkdir in the claim primitive is what makes this assertable')
            self.assertFalse(os.path.exists(t['event_ledger']),
                             'hermes-report.sh must never create the event ledger')
        finally:
            self._teardown_tree(t)


# ============================================================================
# Task 2 — RETENTION: the record's lifetime is decoupled from the ledgers'
# ============================================================================

class RetentionOwnershipTests(OwnershipTestBase):
    """P1-2's own proof. The ownership signal used to live in the API: ledger,
    which prune-markers.sh prunes at MARKER_RETENTION_DAYS — so ~30 days on a
    STILL-LIVE session erased the only record of who owned it and let the
    legacy path re-bill its whole cumulative total from a zero baseline. The
    owners record's staleness rule is presence in state.db and nothing else."""

    def _run_prune(self, t, *args):
        env = {
            **os.environ,
            'HOME': t['shim_home'],
            'HERMES_HOME': t['hermes_home'],
            'REVENIUM_STATE_DIR': t['state_dir'],
            'PATH': t['bin_dir'] + os.pathsep + os.environ.get('PATH', ''),
            'REVENIUM_MARKER_RETENTION_DAYS': '30',
            'TZ': 'UTC',
        }
        return subprocess.run(
            ['bash', str(SCRIPTS_DIR / 'prune-markers.sh'), *args],
            env=env, capture_output=True, text=True, timeout=60,
        )

    @staticmethod
    def _age_file(path, days):
        old = time.time() - days * 86400
        os.utime(path, (old, old))

    def test_record_for_a_live_session_survives_however_old_it_is(self):
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event')
            # 90 days — three times the default window, so ANY age-keyed rule
            # would have removed it.
            self._age_file(self._owners_path(t), 90)

            r = self._run_prune(t)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(
                os.path.exists(self._owners_path(t)),
                'an ownership record whose session is still in state.db must survive '
                'regardless of mtime — keying this pass on MARKER_RETENTION_DAYS is '
                'exactly the P1-2 defect')
            self.assertEqual(self._owner_record(t)[0], 'event')
        finally:
            self._teardown_tree(t)

    def test_record_for_a_session_absent_from_state_db_is_removed(self):
        t = self._setup_tree()
        try:
            self._seed_owner(t, sid='gone-from-state-db', owner='event')
            self._seed_owner(t, sid=SID, owner='legacy')

            r = self._run_prune(t)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(os.path.exists(self._owners_path(t, 'gone-from-state-db')),
                             'a record whose session is absent from state.db must be removed')
            self.assertTrue(os.path.exists(self._owners_path(t, SID)),
                            'the live session\'s record must be untouched in the same run')
            self.assertIn('absent_from_state_db', self._log_text(t))
        finally:
            self._teardown_tree(t)

    def test_dry_run_removes_nothing(self):
        t = self._setup_tree()
        try:
            self._seed_owner(t, sid='gone-from-state-db', owner='event')

            r = self._run_prune(t, '--dry-run')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.exists(self._owners_path(t, 'gone-from-state-db')),
                            '--dry-run must delete nothing')
            self.assertIn('dry-run, would remove', self._log_text(t))
        finally:
            self._teardown_tree(t)

    def test_missing_state_db_removes_nothing_and_says_so(self):
        t = self._setup_tree(sessions=[])
        try:
            self.assertFalse(os.path.exists(t['state_db']), 'fixture: no state.db')
            self._seed_owner(t, sid='would-look-orphaned', owner='event')
            self._age_file(self._owners_path(t, 'would-look-orphaned'), 90)

            r = self._run_prune(t)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(
                os.path.exists(self._owners_path(t, 'would-look-orphaned')),
                'a missing state.db must remove NOTHING — deleting an ownership record '
                'on doubt is how a pruning change becomes a double-bill')
            self.assertIn('owners pass skipped', self._log_text(t))
        finally:
            self._teardown_tree(t)

    def test_unreadable_state_db_removes_nothing_and_says_so(self):
        t = self._setup_tree()
        try:
            # Not a database: sqlite raises on the first query.
            with open(t['state_db'], 'wb') as f:
                f.write(b'not a sqlite database at all\n')
            self._seed_owner(t, sid='would-look-orphaned', owner='event')

            r = self._run_prune(t)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.exists(self._owners_path(t, 'would-look-orphaned')))
            self.assertIn('owners pass skipped', self._log_text(t))
        finally:
            self._teardown_tree(t)

    def test_post_prune_event_owned_session_is_still_not_billed_by_legacy(self):
        """The exact post-prune state that broke P1-2: the session is still
        live in state.db, the ownership record names the event path, and its
        API: rows have already been pruned out of the event ledger. Assert the
        ABSENCE of any completion rather than a particular token count, so the
        test cannot pass on a re-bill that happens to differ in shape."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event')
            # The event ledger exists but no longer carries this session's rows
            # — precisely what the retention pass leaves behind.
            open(t['event_ledger'], 'w').close()

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            self.assertEqual(
                self._legacy_completions(t), [],
                'an event-owned session whose API: rows have been pruned must NOT be '
                're-billed — and specifically not from a zero baseline, which is what '
                f'the derived partition did. Got: {self._legacy_completions(t)!r}')
            self.assertEqual(self._hermes_lines(t), [])
        finally:
            self._teardown_tree(t)


# ============================================================================
# Task 3 — ATOMICITY: the exclusive create is the sole arbiter
# ============================================================================

class AtomicClaimTests(OwnershipTestBase):
    """The concurrency axis, driven DETERMINISTICALLY and never on real thread
    timing.

    A lost race and a pre-existing record are the SAME on-disk state: the
    other claimant's file is already there when this claimant's exclusive
    create runs. Pre-seeding the record is therefore a faithful simulation of
    the other side winning between this side's precondition check and its own
    claim — the interleaving the 2026-08-17 double-bill actually took.
    """

    def test_legacy_losing_the_race_ships_nothing(self):
        """Both ledgers are EMPTY, so nothing but the record can stop the
        legacy path. Its own precondition check would say "no event rows,
        claim as legacy" — and the file wins anyway."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event')
            self.assertEqual(self._hermes_lines(t), [], 'fixture: legacy ledger empty')
            self.assertEqual(self._api_lines(t), [], 'fixture: event ledger empty')

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            self.assertEqual(self._legacy_completions(t), [],
                             'the O_EXCL create is the SOLE arbiter — losing the race must '
                             'suppress billing even when this side\'s own precondition '
                             f'check says it should claim. Output: {out}')
            self.assertEqual(self._hermes_lines(t), [])
        finally:
            self._teardown_tree(t)

    def test_event_losing_the_race_ships_nothing(self):
        """The legacy ledger is EMPTY, so the D-09 precondition passes and
        only the record can stop the event path."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='legacy')
            self._seed_spool(t)
            self._seed_ready(t)
            self.assertEqual(self._hermes_lines(t), [], 'fixture: legacy ledger empty')

            rc, out = self._run_event(t)
            self.assertEqual(rc, 0, out)

            self.assertEqual(self._event_completions(t), [],
                             f'losing the race must suppress the event ship. Output: {out}')
            self.assertEqual(self._api_lines(t), [])
        finally:
            self._teardown_tree(t)

    def test_legacy_does_not_clobber_a_record_it_lost(self):
        """A truncating open would silently rewrite the winner's record and
        still pass every sequential case — this is the assertion that makes
        the atomicity claim non-vacuous from the legacy side."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event', baseline=4242)
            with open(self._owners_path(t), 'rb') as f:
                before = f.read()

            # quick-260818-0in (MODE-01/MODE-04): this fixture asserts the
            # atomicity property under a currently-live event owner (a
            # pre-existing baseline is exactly what a live, dual-ledger-aware
            # claim looks like) — propagate mode=live so the scenario models
            # a self-consistent config rather than exercising the new
            # mode-revert takeover this quick task adds (that behavior has
            # its own dedicated coverage in test_mode_aware_legacy_takeover.py).
            rc, out = self._run_legacy(t, extra_env={'REVENIUM_EVENT_METERING_MODE': 'live'})
            self.assertEqual(rc, 0, out)

            with open(self._owners_path(t), 'rb') as f:
                after = f.read()
            self.assertEqual(before, after,
                             'the losing side must not rewrite, repair or truncate the '
                             'winner\'s record')
        finally:
            self._teardown_tree(t)

    def test_event_does_not_clobber_a_record_it_lost(self):
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='legacy', baseline=4242)
            self._seed_spool(t)
            self._seed_ready(t)
            with open(self._owners_path(t), 'rb') as f:
                before = f.read()

            rc, out = self._run_event(t)
            self.assertEqual(rc, 0, out)

            with open(self._owners_path(t), 'rb') as f:
                after = f.read()
            self.assertEqual(before, after)
        finally:
            self._teardown_tree(t)

    def test_winner_uniqueness_event_first(self):
        t = self._setup_tree()
        try:
            self._seed_spool(t)
            self._seed_ready(t)

            rc, out = self._run_event(t)
            self.assertEqual(rc, 0, out)
            # quick-260818-0in (MODE-01/MODE-04): propagate the same live
            # mode this test's _run_event call used — see the identical note
            # on test_event_first_then_legacy_yields_exactly_one_event_completion.
            rc, out = self._run_legacy(t, extra_env={'REVENIUM_EVENT_METERING_MODE': 'live'})
            self.assertEqual(rc, 0, out)

            self.assertEqual(sorted(os.listdir(t['owners_dir'])), [SID],
                             'exactly one ownership record for one session')
            self.assertEqual(self._owner_record(t)[0], 'event',
                             'the record names whichever side ran first')
            total = len(self._event_completions(t)) + len(self._legacy_completions(t))
            self.assertEqual(total, 1,
                             f'exactly ONE completion across both paths, got {total}')
        finally:
            self._teardown_tree(t)

    def test_winner_uniqueness_legacy_first(self):
        t = self._setup_tree()
        try:
            self._seed_spool(t)
            self._seed_ready(t)

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)
            rc, out = self._run_event(t)
            self.assertEqual(rc, 0, out)

            self.assertEqual(sorted(os.listdir(t['owners_dir'])), [SID])
            self.assertEqual(self._owner_record(t)[0], 'legacy')
            total = len(self._event_completions(t)) + len(self._legacy_completions(t))
            self.assertEqual(total, 1,
                             f'exactly ONE completion across both paths, got {total}')
        finally:
            self._teardown_tree(t)

    def test_both_claim_sites_publish_the_record_atomically_with_its_content(self):
        """Static, so the atomicity claim cannot be vacuously true. Comment
        lines are stripped before matching — a primitive that appears only in
        prose proves nothing.

        This asserts the PROPERTY, not a mechanism. It previously pinned the
        literal flags `os.O_CREAT | os.O_EXCL | os.O_WRONLY`, and PR #54's
        review showed that mechanism to be insufficient: O_EXCL makes the
        CREATE exclusive but leaves the file empty until the write lands, and a
        concurrent reader inside that window reads an empty owner, resolves
        "not owned", and bills — while the creator finishes writing and bills
        too. A test that pins the weaker mechanism would have blocked its own
        fix, which is this repo's recorded "test defending the current
        behaviour rather than a property" trap.

        The property that actually matters: a claim must be atomic, exclusive,
        and never observable without its content — because no lock is held
        anywhere on either shipper. `os.link()` supplies all three: it is
        atomic, it raises FileExistsError if the target exists, and it
        publishes a file that already has its payload.
        """
        for script in ('hermes-report.sh', 'api-event-report.sh'):
            text = (SCRIPTS_DIR / script).read_text()
            code = '\n'.join(ln for ln in text.splitlines()
                             if not ln.lstrip().startswith('#'))
            self.assertIn(
                'os.link(', code,
                f'{script} must publish the ownership record with an atomic '
                'exclusive link — no lock is held on either shipper, so the '
                'publish itself is the whole of the cross-process atomicity')
            self.assertIn(
                'tempfile.mkstemp(', code,
                f'{script} must build the record out of line before publishing '
                'it, so the record is never visible without its content')
            link_at = code.index('os.link(')
            write_at = code.index('_tfh.write(')
            self.assertLess(
                write_at, link_at,
                f'{script} must write the payload BEFORE the link that '
                'publishes it — publishing first reintroduces the empty-record '
                'window that PR #54 review found')


# ============================================================================
# Task 3 — OWN-03 backward compatibility and OWN-04 fail direction
# ============================================================================

GOLDEN_SID = 'compat-sid-markerless-001'


class FailOpenAndCompatTests(OwnershipTestBase):

    def test_no_event_path_meters_byte_identically_to_the_markerless_golden(self):
        """The overwhelming majority of installs. Checked against the EXISTING
        markerless golden, which is not edited."""
        t = self._setup_tree(sessions=[_session_row(sid=GOLDEN_SID)])
        try:
            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            completions = self._legacy_completions(t)
            self.assertEqual(len(completions), 1, f'{completions!r}\n{out}')
            assert_argv_matches_golden(
                self, completions[0], load_golden('meter-completion-markerless.golden.json'))
            self.assertEqual(len(self._hermes_lines(t, GOLDEN_SID)), 1)
            self.assertFalse(os.path.exists(t['owners_dir']),
                             'no ownership state may be created on a disengaged install')
        finally:
            self._teardown_tree(t)

    def test_zero_byte_event_ledger_and_empty_spool_reach_the_same_outcome(self):
        """Same outcome by a DIFFERENT route through the engagement gate: the
        ledger exists but is zero-byte (so `-s` is false) and the spool
        directory exists but holds no .jsonl (so the glob stays literal)."""
        t = self._setup_tree(sessions=[_session_row(sid=GOLDEN_SID)])
        try:
            open(t['event_ledger'], 'w').close()
            self.assertEqual(os.listdir(t['spool_dir']), [], 'fixture: empty spool dir')

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            completions = self._legacy_completions(t)
            self.assertEqual(len(completions), 1, f'{completions!r}\n{out}')
            assert_argv_matches_golden(
                self, completions[0], load_golden('meter-completion-markerless.golden.json'))
            self.assertFalse(os.path.exists(t['owners_dir']))
        finally:
            self._teardown_tree(t)

    def test_a_decoy_event_row_for_another_session_does_not_suppress_billing(self):
        """The match is on the pipe-delimited SESSION field, not a loose
        substring. The decoy's api_request_id deliberately CONTAINS this
        session's id — a bare `grep -q "${sid}"` would false-positive on it and
        silently stop billing a session the event path never claimed."""
        t = self._setup_tree()
        try:
            with open(t['event_ledger'], 'w', encoding='utf-8') as f:
                f.write(f'API:{SID}-shadow:t1:api:1|other-session|1700000000.000\n')
                f.write('API:unrelated:t1:api:1|unrelated-session|1700000001.000\n')

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            completions = self._legacy_completions(t)
            self.assertEqual(len(completions), 1,
                             f'a decoy row belonging to another session must not suppress '
                             f'this one: {completions!r}\n{out}')
            self.assertEqual(argv_to_flags(completions[0]).get('--transaction-id'),
                             f'{SID}-150')
            self.assertEqual(self._owner_record(t)[0], 'legacy')
        finally:
            self._teardown_tree(t)

    @unittest.skipIf(os.geteuid() == 0, 'root defeats mode bits')
    def test_legacy_fails_open_when_the_owners_directory_is_unwritable(self):
        t = self._setup_tree()
        try:
            # Engage the protocol without owning THIS session: a decoy row
            # makes the event ledger non-empty, so the gate is true and the
            # claim is genuinely attempted.
            with open(t['event_ledger'], 'w', encoding='utf-8') as f:
                f.write('API:decoy:t1:api:1|other-session|1700000000.000\n')
            os.makedirs(t['owners_dir'], mode=0o700, exist_ok=True)
            os.chmod(t['owners_dir'], 0o500)

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            self.assertEqual(len(self._legacy_completions(t)), 1,
                             'OWN-04: the legacy path fails OPEN — an unusable sentinel '
                             'must leave exactly one biller, and legacy is the incumbent '
                             f'every install depends on. Output: {out}')
            self.assertEqual(len(self._hermes_lines(t)), 1)
            self.assertIn('session ownership record unavailable', self._log_text(t))
        finally:
            self._teardown_tree(t)

    @unittest.skipIf(os.geteuid() == 0, 'root defeats mode bits')
    def test_event_fails_closed_when_the_owners_directory_is_unwritable(self):
        t = self._setup_tree()
        try:
            self._seed_spool(t)
            self._seed_ready(t)
            os.makedirs(t['owners_dir'], mode=0o700, exist_ok=True)
            os.chmod(t['owners_dir'], 0o500)

            rc, out = self._run_event(t)
            self.assertEqual(rc, 0, out)

            self.assertEqual(self._event_completions(t), [],
                             'OWN-04: the event path fails CLOSED — deferring costs a '
                             'delay, while failing open here alongside the legacy path\'s '
                             'own fail-open would DOUBLE-bill under one shared directory '
                             f'failure. Output: {out}')
            self.assertEqual(self._api_lines(t), [])
            self.assertIn('deferring this session (fail-closed)', self._log_text(t))
        finally:
            self._teardown_tree(t)

    def test_a_corrupt_non_utf8_record_leaves_exactly_one_biller(self):
        """Bytes that are not valid UTF-8 raise inside the EXISTS branch, not
        the create — which is why that branch carries its own handler. It must
        degrade to empty output rather than crash the heredoc, and neither
        side may repair or overwrite a record it could not read."""
        t = self._setup_tree()
        try:
            self._seed_spool(t)
            self._seed_ready(t)
            os.makedirs(t['owners_dir'], mode=0o700, exist_ok=True)
            corrupt = b'\xff\xfe\x80\x00not-utf8\n\xc3\x28\n'
            with open(self._owners_path(t), 'wb') as f:
                f.write(corrupt)

            rc_legacy, out_legacy = self._run_legacy(t)
            rc_event, out_event = self._run_event(t)

            self.assertEqual(rc_legacy, 0, out_legacy)
            self.assertEqual(rc_event, 0, out_event)

            self.assertEqual(len(self._legacy_completions(t)), 1,
                             f'legacy fails OPEN on an unreadable record: {out_legacy}')
            self.assertEqual(self._event_completions(t), [],
                             f'the event path fails CLOSED on the same record: {out_event}')

            with open(self._owners_path(t), 'rb') as f:
                self.assertEqual(f.read(), corrupt,
                                 'neither side may repair or overwrite a record it could '
                                 'not read')
        finally:
            self._teardown_tree(t)


if __name__ == '__main__':
    unittest.main()
