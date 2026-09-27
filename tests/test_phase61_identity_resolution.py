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


if __name__ == '__main__':
    unittest.main()
