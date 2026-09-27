"""Phase 61 Plan 01 (SUB-01..04): the identity-resolution seam.

Task 1 covers the unit-level contract of `resolve_subscriber_id` /
`mask_subscriber_for_log` in common.sh, and the end-to-end proof that a
session's OWN identity (source + user_id) reaches the `Reported:` log line
via the new 14th SELECT column — plus the backward-compatibility proof that
an install whose `sessions` table lacks the column (every fixture built by
tests/_compat_helpers.py::build_state_db) still meters, unchanged, with the
absent-column line logged exactly once.

Task 2 (added in a later commit in this same module) covers inheritance
through the existing root-walk, the child/root disagreement rule, and the
per-tick aggregate.

Harness mirrors tests/test_phase29_squad_argv.py: one temp HERMES_HOME, one
PATH-shim `revenium`, one meter log; `_seed_sessions_db` mirrors that
module's own local copy (WITH parent_session_id, needed for the root-walk)
plus the new `user_id` column, and a per-row dict so a test can omit either.
`tests/_compat_helpers.py::build_state_db` is deliberately NOT touched: its
139 call sites across 39 files are the absent-branch regression corpus this
phase's fail-open behavior depends on.
"""
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from tests._compat_helpers import (
    build_shim,
    build_state_db,
    run_script,
    SCRIPTS_DIR,
)

COMMON_SH = SCRIPTS_DIR / 'common.sh'

# Fixed far-past epoch (matches test_compat_meter_completion.py and
# test_phase29_squad_argv.py) so every seeded session clears the
# settle-seconds filter regardless of REVENIUM_CRON_SETTLE_SECONDS, without
# needing a markers-ready sentinel.
_OLD_TS = 1715514000.0


def _seed_sessions_db(db_path, rows):
    """Create a sessions table with the 13 production columns plus
    parent_session_id (needed for get_root_session_id's sidecar query to
    resolve a root distinct from a child — _compat_helpers.build_state_db
    omits it) plus the new Phase 61 user_id column.

    Each row is a dict; missing keys fall back to sensible defaults so a
    test can specify only what it cares about. `user_id` defaults to None
    (SQL NULL) — the 97%-of-sessions no-identity case.
    """
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
                billing_provider TEXT, parent_session_id TEXT, user_id TEXT
            )
            """
        )
        for r in rows:
            conn.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    r['id'],
                    r.get('model', 'claude-sonnet-4-6'),
                    r.get('source', 'slack'),
                    r.get('input_tokens', 100),
                    r.get('output_tokens', 50),
                    r.get('cache_read', 0),
                    r.get('cache_write', 0),
                    r.get('reasoning', 0),
                    r.get('estimated_cost', 0.0),
                    r.get('api_calls', 1),
                    r.get('started_at', _OLD_TS),
                    r.get('ended_at', _OLD_TS),
                    r.get('billing_provider', 'anthropic'),
                    r.get('parent_session_id'),
                    r.get('user_id'),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _write_marker_lines(markers_dir, sid, records):
    """Write `records` (list of dicts) as one JSONL line each to
    markers_dir/{sid}.jsonl. Creates markers_dir if needed. Mirrors
    test_phase29_squad_argv.py's helper of the same name."""
    os.makedirs(markers_dir, exist_ok=True)
    with open(os.path.join(markers_dir, f"{sid}.jsonl"), "w") as f:
        for rec in records:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")


def _task_marker(sid, muid, task_type="code_review", extra=None):
    rec = {
        "muid": muid,
        "ts": time.time(),
        "sid": sid,
        "task_type": task_type,
        "operation_type": "CHAT",
    }
    if extra:
        rec.update(extra)
    return rec


def _own_meter_invocations(invocations, sid):
    """argv lists (already shlex-split) whose --transaction-id belongs to
    `sid` specifically (transaction-id is always "{sid}-{total_tokens}..."),
    so a sibling session sharing --trace-id/--squad-id can't be confused
    with this session's own completions. Mirrors
    test_phase29_squad_argv.py's helper of the same name."""
    result = []
    for argv in invocations:
        txn = None
        for i, tok in enumerate(argv):
            if tok == '--transaction-id' and i + 1 < len(argv):
                txn = argv[i + 1]
                break
        if txn and txn.startswith(sid + '-'):
            result.append(argv)
    return result


class ResolveSubscriberIdUnitTests(unittest.TestCase):
    """Unit-level contract of resolve_subscriber_id / mask_subscriber_for_log,
    exercised by sourcing common.sh in a bash subshell (the idiom at
    tests/test_phase42_assessment_contract.py:1443-1449) rather than through
    the full reporter. HERMES_HOME is redirected to a scratch tmpdir so
    common.sh's top-level `mkdir -p "${STATE_DIR}" ...` never touches the
    real $HOME.

    MISSES: this proves the function's own contract in isolation, not that
    hermes-report.sh's SELECT feeds it exactly this shape — the end-to-end
    tests below cover that.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gsd-phase61-unit-")
        self.hermes_home = os.path.join(self.tmp, "hh")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _call(self, fn, *args):
        quoted = ' '.join(shlex.quote(a) for a in args)
        expr = f'{fn} {quoted}'
        env = {**os.environ, 'HERMES_HOME': self.hermes_home}
        return subprocess.run(
            ['bash', '-c', f'source "{COMMON_SH}" >/dev/null 2>&1; {expr}'],
            env=env, capture_output=True, text=True, timeout=30,
        )

    def test_slack_resolves_ok(self):
        r = self._call('resolve_subscriber_id', 'slack', 'U02C12JG78F')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'ok|slack:U02C12JG78F')

    def test_email_resolves_ok(self):
        r = self._call('resolve_subscriber_id', 'email', 'jane@acme.example')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'ok|email:jane@acme.example')

    def test_webhook_resolves_ok(self):
        r = self._call('resolve_subscriber_id', 'webhook', 'spike-test')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'ok|webhook:spike-test')

    def test_empty_user_id_resolves_none(self):
        r = self._call('resolve_subscriber_id', 'cron', '')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'none|')

    def test_whitespace_only_user_id_resolves_none(self):
        r = self._call('resolve_subscriber_id', 'slack', '   ')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'none|')

    def test_bot_id_resolves_identically_to_human(self):
        """D-12: no bot/app special-casing whatsoever."""
        r = self._call('resolve_subscriber_id', 'slack', 'USLACKBOT')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'ok|slack:USLACKBOT')

    def test_unknown_source_no_allowlist(self):
        """D-06: the source column verbatim, no allowlist."""
        r = self._call(
            'resolve_subscriber_id', 'some_source_never_seen_before', 'U1'
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(
            r.stdout.strip(), 'ok|some_source_never_seen_before:U1'
        )

    def test_sentinel_value_rejected(self):
        """D-03: fail closed on the fixed transport-unsafe sentinel."""
        r = self._call(
            'resolve_subscriber_id', 'slack', '__revenium_unsafe_user_id__'
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'rejected|')

    def test_pipe_in_user_id_rejected(self):
        r = self._call('resolve_subscriber_id', 'slack', 'U|600')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'rejected|')

    def test_empty_source_rejected(self):
        r = self._call('resolve_subscriber_id', '', 'U1')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'rejected|')

    def test_mask_non_email_key_unchanged(self):
        r = self._call('mask_subscriber_for_log', 'slack:U02C12JG78F')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'slack:U02C12JG78F')

    def test_mask_email_key_masks_local_part(self):
        r = self._call('mask_subscriber_for_log', 'email:jane@acme.example')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'email:j***@acme.example')


class Phase61IdentityResolutionEndToEndTestCase(unittest.TestCase):
    """PATH-shim harness mirroring test_phase29_squad_argv.py: one temp
    HERMES_HOME, one revenium shim, one meter log. Each test seeds its own
    state.db (via the module-local _seed_sessions_db, or via
    _compat_helpers.build_state_db for the absent-column proof) plus marker
    files as needed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gsd-phase61-identity-")
        self.hermes_home = os.path.join(self.tmp, "hh")
        self.state_dir = os.path.join(self.hermes_home, "state", "revenium")
        self.markers_dir = os.path.join(self.state_dir, "markers")
        os.makedirs(self.markers_dir, mode=0o700)
        self.state_db = os.path.join(self.hermes_home, "state.db")
        self.log_file = os.path.join(self.state_dir, "revenium-metering.log")

        self.shim_home = os.path.join(self.tmp, "home")
        self.bin_dir = os.path.join(self.shim_home, ".local", "bin")
        os.makedirs(self.bin_dir)
        self.meter_log = os.path.join(self.tmp, "meter.log")
        self.jobs_log = os.path.join(self.tmp, "jobs.log")
        self.inv_log = os.path.join(self.tmp, "inv.log")
        self.shim = os.path.join(self.bin_dir, "revenium")
        build_shim(self.shim, squad_capable=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _base_env(self):
        return {
            **os.environ,
            'HOME': self.shim_home,
            'HERMES_HOME': self.hermes_home,
            'REVENIUM_STATE_DIR': self.state_dir,
            'PATH': self.bin_dir + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': self.inv_log,
            'METER_LOG': self.meter_log,
            'JOBS_LOG': self.jobs_log,
            'TZ': 'UTC',
            'REVENIUM_ORGANIZATION_NAME': '',
            'REVENIUM_SQUAD_NAME': '',
        }

    def _run(self):
        rc, _ignored_inv, output = run_script(
            SCRIPTS_DIR / 'hermes-report.sh', self._base_env(), self.inv_log
        )
        meter_invocations = []
        if os.path.exists(self.meter_log):
            with open(self.meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        meter_invocations.append(shlex.split(line))
        self.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {output}')
        return meter_invocations

    def _log_lines(self):
        if not os.path.exists(self.log_file):
            return []
        return Path(self.log_file).read_text().splitlines()

    def test_marker_bearing_session_own_identity_logs_subscriber(self):
        """A marker-bearing Slack session with its own user_id logs
        subscriber=slack:<id> on its own Reported: line.

        MISSES: says nothing about inheritance or the markerless path —
        both covered by Task 2's tests below.
        """
        sid = "p61-own-1"
        _seed_sessions_db(self.state_db, [
            {'id': sid, 'source': 'slack', 'user_id': 'U02C12JG78F'},
        ])
        _write_marker_lines(
            self.markers_dir, sid, [_task_marker(sid, "p61-muid-1")]
        )

        invocations = self._run()
        own = _own_meter_invocations(invocations, sid)
        self.assertEqual(
            len(own), 1, f"expected exactly 1 completion for {sid}; got {own!r}"
        )

        log_lines = self._log_lines()
        reported = [
            l for l in log_lines if f"Reported: session={sid} " in l
        ]
        self.assertEqual(
            len(reported), 1,
            f"expected exactly one Reported line for {sid}; got {reported!r}",
        )
        self.assertIn("subscriber=slack:U02C12JG78F", reported[0])

    def test_build_state_db_fixture_meters_unchanged_absent_column_logged_once(self):
        """The SAME markerless fixture shape built through
        _compat_helpers.build_state_db (no user_id column at all) still
        meters, still exits 0, and logs the absent-column line exactly
        once — the D-07/backward-compatibility proof.

        MISSES: does not prove the absent-column line is rate-limited
        ACROSS ticks (only within one run of hermes-report.sh); the probe
        is memoised per-process, so a single run can only ever log it once
        by construction — this test pins that construction, not a
        multi-tick rate limit.
        """
        sid = "p61-absent-col-1"
        build_state_db(self.state_db, [{
            'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
            'input_tokens': 100, 'output_tokens': 50,
            'cache_read': 0, 'cache_write': 0, 'reasoning': 0,
            'estimated_cost': 0.01, 'api_calls': 1,
            'started_at': _OLD_TS, 'ended_at': _OLD_TS,
            'billing_provider': 'anthropic',
        }])
        # No marker file: markerless path.
        invocations = self._run()
        own = _own_meter_invocations(invocations, sid)
        self.assertEqual(
            len(own), 1, f"expected exactly 1 completion for {sid}; got {own!r}"
        )

        log_lines = self._log_lines()
        absent_lines = [
            l for l in log_lines if "user_id column not present" in l
        ]
        self.assertEqual(
            len(absent_lines), 1,
            f"expected exactly one absent-column line; got {absent_lines!r}",
        )

    # -- Task 2: inheritance, the disagreement rule, the per-tick aggregate --

    def test_child_with_no_identity_inherits_root_slack_identity(self):
        """SUB-03/D-08: a child with no user_id of its own inherits its
        ROOT session's subscriber, resolved through the existing batched
        root-walk.

        MISSES: proves nothing about a root that is ABSENT from the
        token-filtered session list — the subscriber map is built from its
        own unfiltered query (build_subscriber_map selects straight from
        `sessions`, not from `${sessions}`), so a zero-token root is
        exactly the case PATTERNS.md's §3 proposal would have missed and
        this fixture does not exercise.
        """
        root_sid = "p61-root-a"
        child_sid = "p61-child-a"
        _seed_sessions_db(self.state_db, [
            {'id': root_sid, 'source': 'slack', 'user_id': 'U100'},
            {
                'id': child_sid, 'source': 'subagent', 'user_id': None,
                'parent_session_id': root_sid,
                'input_tokens': 200, 'output_tokens': 100,
            },
        ])
        _write_marker_lines(
            self.markers_dir, child_sid, [_task_marker(child_sid, "p61-muid-a")]
        )

        self._run()
        log_lines = self._log_lines()
        reported = [
            l for l in log_lines if f"Reported: session={child_sid} " in l
        ]
        self.assertEqual(len(reported), 1, reported)
        self.assertIn("subscriber=slack:U100", reported[0])

    def test_cron_child_with_cron_root_inherits_nothing(self):
        """D-11 negative arm: a homogeneous automation lineage (cron child,
        cron root, neither carrying identity) must inherit nothing —
        inheritance is provably additive, never a leak.

        MISSES: this fixture's root has NO identity at all, so it cannot
        distinguish "inheritance correctly propagated an empty key" from
        "inheritance was never attempted"; the aggregate assertion in
        test_aggregate_line_absent_when_no_identity_sessions below is what
        pins the latter.
        """
        root_sid = "p61-root-b"
        child_sid = "p61-child-b"
        _seed_sessions_db(self.state_db, [
            {'id': root_sid, 'source': 'cron', 'user_id': None},
            {
                'id': child_sid, 'source': 'cron', 'user_id': None,
                'parent_session_id': root_sid,
                'input_tokens': 200, 'output_tokens': 100,
            },
        ])
        self._run()
        log_lines = self._log_lines()
        reported = [
            l for l in log_lines if f"Reported: session={child_sid} " in l
        ]
        self.assertEqual(len(reported), 1, reported)
        self.assertNotIn("subscriber=", reported[0])

    def test_child_own_identity_wins_and_disagreement_logged_once(self):
        """D-10: where a child has its own user_id differing from its
        root's, the child's OWN identity wins, and the disagreement is
        counted and surfaced once per tick naming the offending triple.

        MISSES: proves the count and that exactly one line was emitted,
        not that the warn's exact wording is a stable/pinned contract —
        only the presence of the session id and both keys is asserted.
        """
        root_sid = "p61-root-c"
        child_sid = "p61-child-c"
        _seed_sessions_db(self.state_db, [
            {'id': root_sid, 'source': 'slack', 'user_id': 'U200'},
            {
                'id': child_sid, 'source': 'slack', 'user_id': 'U201',
                'parent_session_id': root_sid,
                'input_tokens': 200, 'output_tokens': 100,
            },
        ])
        self._run()
        log_lines = self._log_lines()
        reported = [
            l for l in log_lines if f"Reported: session={child_sid} " in l
        ]
        self.assertEqual(len(reported), 1, reported)
        self.assertIn("subscriber=slack:U201", reported[0])

        disagreement_lines = [
            l for l in log_lines if "subscriber identity disagreement" in l
        ]
        self.assertEqual(len(disagreement_lines), 1, disagreement_lines)
        self.assertIn(child_sid, disagreement_lines[0])
        self.assertIn("slack:U201", disagreement_lines[0])
        self.assertIn("slack:U200", disagreement_lines[0])

    def test_child_own_identity_matches_root_no_disagreement(self):
        """The observed-on-the-reference-host case (all 7 children): a
        child's own identity equals its root's — its key is its own, and
        no disagreement is ever logged.

        MISSES: does not prove the counter distinguishes "matched" from
        "never compared" — only that the warn line is absent either way.
        """
        root_sid = "p61-root-d"
        child_sid = "p61-child-d"
        _seed_sessions_db(self.state_db, [
            {'id': root_sid, 'source': 'slack', 'user_id': 'U300'},
            {
                'id': child_sid, 'source': 'slack', 'user_id': 'U300',
                'parent_session_id': root_sid,
                'input_tokens': 200, 'output_tokens': 100,
            },
        ])
        self._run()
        log_lines = self._log_lines()
        disagreement_lines = [
            l for l in log_lines if "subscriber identity disagreement" in l
        ]
        self.assertEqual(len(disagreement_lines), 0, disagreement_lines)

    def test_two_disagreeing_children_one_tick_one_line_count_two(self):
        """Two children disagreeing with the same root in one tick still
        produce exactly ONE disagreement warn line, and the aggregate
        reports a disagreement count of 2 — the rate-limit is per TICK,
        not per (session, reason) like the sibling sentinel-gated warns.

        MISSES: does not prove WHICH of the two disagreements is named in
        the single warn line (only that "first this tick" is recorded,
        per the action spec) — only the count and single-line-ness.
        """
        root_sid = "p61-root-e"
        child1 = "p61-child-e1"
        child2 = "p61-child-e2"
        _seed_sessions_db(self.state_db, [
            {'id': root_sid, 'source': 'slack', 'user_id': 'U400'},
            {
                'id': child1, 'source': 'slack', 'user_id': 'U401',
                'parent_session_id': root_sid,
                'input_tokens': 200, 'output_tokens': 100,
            },
            {
                'id': child2, 'source': 'slack', 'user_id': 'U402',
                'parent_session_id': root_sid,
                'input_tokens': 300, 'output_tokens': 150,
            },
        ])
        self._run()
        log_lines = self._log_lines()
        disagreement_lines = [
            l for l in log_lines if "subscriber identity disagreement" in l
        ]
        self.assertEqual(len(disagreement_lines), 1, disagreement_lines)

        aggregate_lines = [
            l for l in log_lines if "subscriber attribution:" in l
        ]
        self.assertEqual(len(aggregate_lines), 1, aggregate_lines)
        self.assertIn("disagreements=2", aggregate_lines[0])

    def test_root_session_with_own_identity_no_disagreement(self):
        """A root session (root_sid == sid) with its own identity: no
        disagreement line, and the own-identity path behaves exactly as
        Task 1 (this is also the markerless-path-carries-a-key proof,
        SUB-01 item 4, since this fixture writes no marker file).

        MISSES: does not directly instrument that no map lookup was
        PERFORMED for this session (the `root_sid != sid` gate is a code
        read, not something this black-box test can observe); it proves
        only the two externally-visible consequences — no disagreement
        line, and the own key still resolves.
        """
        sid = "p61-root-f"
        _seed_sessions_db(self.state_db, [
            {'id': sid, 'source': 'slack', 'user_id': 'U500'},
        ])
        self._run()
        log_lines = self._log_lines()
        reported = [
            l for l in log_lines if f"Reported: session={sid} " in l
        ]
        self.assertEqual(len(reported), 1, reported)
        self.assertIn("subscriber=slack:U500", reported[0])

        disagreement_lines = [
            l for l in log_lines if "subscriber identity disagreement" in l
        ]
        self.assertEqual(len(disagreement_lines), 0, disagreement_lines)

        aggregate_lines = [
            l for l in log_lines if "subscriber attribution:" in l
        ]
        self.assertEqual(len(aggregate_lines), 1, aggregate_lines)
        self.assertIn("own=1", aggregate_lines[0])

    def test_aggregate_line_absent_when_no_identity_sessions(self):
        """A tick with no resolved or rejected session emits NO aggregate
        line at all — the identical own=0/inherited=0/etc. silence
        discipline fallback_tick_count and its siblings already use.

        MISSES: only exercises the all-cron/no-identity shape; does not
        prove the converse threshold (exactly one non-zero counter is
        already enough to trigger the line) beyond what the other tests
        above already demonstrate individually.
        """
        sid = "p61-no-identity-g"
        _seed_sessions_db(self.state_db, [
            {'id': sid, 'source': 'cron', 'user_id': None},
        ])
        self._run()
        log_lines = self._log_lines()
        aggregate_lines = [
            l for l in log_lines if "subscriber attribution:" in l
        ]
        self.assertEqual(len(aggregate_lines), 0, aggregate_lines)

    def test_pipe_in_user_id_rejected_neighbouring_fields_intact(self):
        """T-61-02: a session whose user_id contains a pipe is sanitized by
        the SQL delimiter-safety CASE before it ever reaches the positional
        `read`, so it is counted as rejected, carries no key, and its
        neighbouring fields (billing_provider, started_at) are still read
        correctly — proven here by the reporter completing successfully
        and emitting exactly one completion and one rejected count.

        MISSES: does not independently verify billing_provider/started_at
        VALUES were parsed correctly (no downstream consumer of those two
        fields is asserted here) — only that the row was not corrupted
        badly enough to break the run, which a shifted-field row would
        have done (either a crash or a visibly wrong completion count).
        """
        sid = "p61-pipe-h"
        _seed_sessions_db(self.state_db, [
            {
                'id': sid, 'source': 'slack', 'user_id': 'U|600',
                'billing_provider': 'anthropic',
            },
        ])
        invocations = self._run()
        own = _own_meter_invocations(invocations, sid)
        self.assertEqual(
            len(own), 1, f"expected exactly 1 completion for {sid}; got {own!r}"
        )

        log_lines = self._log_lines()
        reported = [
            l for l in log_lines if f"Reported: session={sid} " in l
        ]
        self.assertEqual(len(reported), 1, reported)
        self.assertNotIn("subscriber=", reported[0])

        aggregate_lines = [
            l for l in log_lines if "subscriber attribution:" in l
        ]
        self.assertEqual(len(aggregate_lines), 1, aggregate_lines)
        self.assertIn("rejected=1", aggregate_lines[0])


if __name__ == '__main__':
    unittest.main()
