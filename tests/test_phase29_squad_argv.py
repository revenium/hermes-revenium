"""Phase 29 (SQUAD-01/02/03): argv-shape proof for the squad attribution
flags (--squad-id/--squad-name/--squad-role) at BOTH hermes-report.sh emit
paths (marker-bearing and markerless).

Analog: tests/test_compat_meter_completion.py (the _compat_helpers PATH-shim
idiom) for single-session fixtures, and
tests/test_phase28_multiplex_trace.py's `_seed_sessions_db` (parent_session_id
column) for the root/subagent fixtures this module also needs.

Source-of-truth for the argv shape under test: skills/revenium/scripts/
hermes-report.sh's once-per-session root_agent_name resolution (just after
root_markers_dir) and the two squad-flag append blocks immediately following
the JOBS_CLI_CAPABLE block (marker-bearing path) and the TRACE_TYPE_CLI_CAPABLE
block (markerless path).

Every fixture uses build_shim(..., squad_capable=True) (the default) so
SQUAD_CLI_CAPABLE resolves true and the squad flags are always emitted here.
SQUAD-04's negative (capability-gated) proof lives in the sibling module
tests/test_phase29_squad_capability_gate.py.
"""
import json
import os
import shlex
import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from tests._compat_helpers import (
    argv_to_flags,
    build_shim,
    run_script,
    SCRIPTS_DIR,
)

# Fixed far-past epoch (matches test_compat_meter_completion.py) so every
# seeded session clears the settle-seconds filter regardless of
# REVENIUM_CRON_SETTLE_SECONDS, without needing a markers-ready sentinel.
_OLD_TS = 1715514000.0


def _seed_sessions_db(db_path, rows):
    """Create a sessions table WITH parent_session_id and insert one row per
    (sid, parent_sid_or_none, input_tokens, output_tokens) tuple. Mirrors
    tests/test_phase28_multiplex_trace.py's `_seed_sessions_db`, needed here
    (unlike _compat_helpers.build_state_db) because the subagent fixtures
    require a real parent_session_id column for get_root_session_id's
    sidecar query to resolve a root distinct from the child."""
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
                billing_provider TEXT, parent_session_id TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (sid, "claude-sonnet-4-6", "test", inp, out, 0, 0, 0,
                 0.0, 1, _OLD_TS, _OLD_TS, "anthropic", parent)
                for sid, parent, inp, out in rows
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _write_marker_lines(markers_dir, sid, records):
    """Write `records` (list of dicts) as one JSONL line each to
    markers_dir/{sid}.jsonl. Creates markers_dir if needed."""
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
    with this session's own completions."""
    result = []
    for argv in invocations:
        flags = argv_to_flags(argv)
        txn = flags.get('--transaction-id', '')
        if txn.startswith(sid + '-'):
            result.append(argv)
    return result


class Phase29SquadArgvTestCase(unittest.TestCase):
    """Shared PATH-shim harness: one temp HERMES_HOME, one shim, one meter
    log. Each test seeds its own state.db + marker files."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gsd-phase29-squad-argv-")
        self.hermes_home = os.path.join(self.tmp, "hh")
        self.state_dir = os.path.join(self.hermes_home, "state", "revenium")
        self.markers_dir = os.path.join(self.state_dir, "markers")
        os.makedirs(self.markers_dir, mode=0o700)
        self.state_db = os.path.join(self.hermes_home, "state.db")

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
            # quick-260814-okp: explicitly neutralize REVENIUM_SQUAD_NAME so
            # an ambient export on the developer's or fleet host's shell
            # (this env dict starts from {**os.environ, ...}) can never
            # silently flip this module's --squad-name assertions. Empty
            # is treated as unset by the ${VAR:-...} resolution in
            # hermes-report.sh, so this preserves the pre-override
            # two-level fallback these tests assert against.
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

    # ---- Case 1: marker-bearing, root session, no agent field ----

    def test_marker_bearing_root_session_no_agent_field(self):
        sid = "sq-argv-root-1"
        _seed_sessions_db(self.state_db, [(sid, None, 100, 50)])
        _write_marker_lines(self.markers_dir, sid, [_task_marker(sid, "sq-muid-1")])

        invocations = self._run()
        own = _own_meter_invocations(invocations, sid)
        self.assertEqual(len(own), 1, f"expected exactly 1 completion for {sid}; got {own!r}")
        flags = argv_to_flags(own[0])

        self.assertEqual(flags.get('--squad-id'), sid)
        self.assertEqual(flags.get('--squad-role'), 'root')
        self.assertEqual(flags.get('--squad-name'), 'Hermes')

    # ---- Case 2: marker-bearing, subagent ----

    def test_marker_bearing_subagent(self):
        root_sid = "sq-argv-root-2"
        child_sid = "sq-argv-child-2"
        _seed_sessions_db(self.state_db, [
            (root_sid, None, 100, 50),
            (child_sid, root_sid, 200, 100),
        ])
        # Child has its own marker file (marker-bearing path). Root has none
        # — squad-name falls back to REVENIUM_AGENT_NAME, not asserted here.
        _write_marker_lines(self.markers_dir, child_sid, [_task_marker(child_sid, "sq-muid-2")])

        invocations = self._run()
        own = _own_meter_invocations(invocations, child_sid)
        self.assertEqual(len(own), 1, f"expected exactly 1 completion for {child_sid}; got {own!r}")
        argv = own[0]
        flags = argv_to_flags(argv)

        self.assertEqual(flags.get('--squad-id'), root_sid,
                          "subagent's --squad-id must be the ROOT id, not its own")
        self.assertEqual(flags.get('--squad-role'), 'subagent')
        # --trace-id must still be present as its own separate argv pair —
        # not merged with or replaced by --squad-id.
        self.assertIn('--trace-id', argv)
        self.assertEqual(flags.get('--trace-id'), root_sid)

    # ---- Case 3: markerless path ----

    def test_markerless_path_carries_squad_flags(self):
        sid = "sq-argv-markerless-1"
        _seed_sessions_db(self.state_db, [(sid, None, 100, 50)])
        # Deliberately no marker file at all for this sid.

        invocations = self._run()
        own = _own_meter_invocations(invocations, sid)
        self.assertEqual(len(own), 1, f"expected exactly 1 completion for {sid}; got {own!r}")
        flags = argv_to_flags(own[0])

        self.assertEqual(flags.get('--squad-id'), sid)
        self.assertEqual(flags.get('--squad-role'), 'root')
        self.assertEqual(flags.get('--squad-name'), 'Hermes')

    # ---- Case 4: adjacency / root case ----

    def test_root_session_squad_id_equals_trace_id_as_distinct_pairs(self):
        sid = "sq-argv-adjacency-1"
        _seed_sessions_db(self.state_db, [(sid, None, 100, 50)])
        _write_marker_lines(self.markers_dir, sid, [_task_marker(sid, "sq-muid-adj")])

        invocations = self._run()
        own = _own_meter_invocations(invocations, sid)
        self.assertEqual(len(own), 1)
        argv = own[0]
        flags = argv_to_flags(argv)

        self.assertEqual(flags.get('--squad-id'), flags.get('--trace-id'))
        # Assert on the RAW argv list — not only the flags dict — so a
        # collision that silently dropped one flag would fail this.
        self.assertIn('--squad-id', argv)
        self.assertIn('--trace-id', argv)
        squad_id_idx = argv.index('--squad-id')
        trace_id_idx = argv.index('--trace-id')
        self.assertNotEqual(squad_id_idx, trace_id_idx,
                             "--squad-id and --trace-id must be distinct argv positions")

    # ---- Case 5: ordering, both emit paths ----

    def test_squad_flag_ordering_marker_bearing_path(self):
        sid = "sq-argv-order-marker-1"
        _seed_sessions_db(self.state_db, [(sid, None, 100, 50)])
        _write_marker_lines(self.markers_dir, sid, [_task_marker(sid, "sq-muid-order")])

        invocations = self._run()
        own = _own_meter_invocations(invocations, sid)
        self.assertEqual(len(own), 1)
        argv = own[0]

        idx_id = argv.index('--squad-id')
        idx_name = argv.index('--squad-name')
        idx_role = argv.index('--squad-role')
        self.assertLess(idx_id, idx_name)
        self.assertLess(idx_name, idx_role)

    def test_squad_flag_ordering_markerless_path(self):
        sid = "sq-argv-order-markerless-1"
        _seed_sessions_db(self.state_db, [(sid, None, 100, 50)])
        # No marker file — markerless path.

        invocations = self._run()
        own = _own_meter_invocations(invocations, sid)
        self.assertEqual(len(own), 1)
        argv = own[0]

        idx_id = argv.index('--squad-id')
        idx_name = argv.index('--squad-name')
        idx_role = argv.index('--squad-role')
        self.assertLess(idx_id, idx_name)
        self.assertLess(idx_name, idx_role)

    # ---- Case 6: populated agent field, both paths ----

    def test_populated_root_agent_field_flows_to_both_paths(self):
        root_sid = "sq-argv-root-6"
        child_marker_sid = "sq-argv-child-marker-6"
        child_markerless_sid = "sq-argv-child-markerless-6"
        _seed_sessions_db(self.state_db, [
            (child_marker_sid, root_sid, 100, 50),
            (child_markerless_sid, root_sid, 100, 50),
        ])
        # Root has no row of its own in sessions — only its marker FILE
        # needs to exist on disk for root_agent_name resolution (the
        # get_root_session_id walk only needs the CHILD rows' own
        # parent_session_id, per common.sh:155-165).
        # No production writer populates 'agent' today (per
        # 29-02-PLAN.md's <agent_field_finding>) — this record is a test
        # fixture proving the resolution reads it when present.
        _write_marker_lines(self.markers_dir, root_sid, [
            {"kind": "agent_info", "agent": "Hermes-marketing"},
        ])
        # Child A: has its own marker (marker-bearing path), no 'agent' key
        # of its own — proves --squad-name reads root_agent_name, NOT the
        # per-marker m_agent value.
        _write_marker_lines(self.markers_dir, child_marker_sid, [
            _task_marker(child_marker_sid, "sq-muid-6a"),
        ])
        # Child B: no marker file at all (markerless path).

        invocations = self._run()

        own_a = _own_meter_invocations(invocations, child_marker_sid)
        self.assertEqual(len(own_a), 1, f"expected 1 completion for {child_marker_sid}; got {own_a!r}")
        flags_a = argv_to_flags(own_a[0])
        self.assertEqual(flags_a.get('--squad-name'), 'Hermes-marketing')

        own_b = _own_meter_invocations(invocations, child_markerless_sid)
        self.assertEqual(len(own_b), 1, f"expected 1 completion for {child_markerless_sid}; got {own_b!r}")
        flags_b = argv_to_flags(own_b[0])
        self.assertEqual(flags_b.get('--squad-name'), 'Hermes-marketing')

    # ---- Case 7: injection ----

    def test_root_agent_field_injection_cannot_forge_squad_name(self):
        root_sid = "sq-argv-root-7"
        child_sid = "sq-argv-child-7"
        _seed_sessions_db(self.state_db, [(child_sid, root_sid, 100, 50)])
        _write_marker_lines(self.markers_dir, root_sid, [
            {"kind": "agent_info", "agent": "evil\nROOT_AGENT=pwned"},
        ])

        invocations = self._run()
        own = _own_meter_invocations(invocations, child_sid)
        self.assertEqual(len(own), 1, f"expected 1 completion for {child_sid}; got {own!r}")
        flags = argv_to_flags(own[0])
        squad_name = flags.get('--squad-name', '')

        self.assertNotEqual(squad_name, 'pwned')
        self.assertNotIn('\n', squad_name)
        self.assertNotIn('ROOT_AGENT', squad_name)

    # ---- Case 8: empty root walk (belt fallback) ----

    def test_empty_root_walk_falls_back_to_own_sid(self):
        """No parent_session_id column at all (get_root_session_id's sidecar
        query hits sqlite.OperationalError and fails open to the input sid)
        — exercises the hermes-report.sh:300 belt
        (`[[ -z "${root_sid}" ]] && root_sid="${sid}"`) that pins root_sid
        (and therefore --squad-id) to a non-empty value."""
        from tests._compat_helpers import build_state_db
        sid = "sq-argv-empty-root-walk-1"
        build_state_db(self.state_db, [{
            'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
            'input_tokens': 100, 'output_tokens': 50, 'cache_read': 0,
            'cache_write': 0, 'reasoning': 0, 'estimated_cost': '0',
            'api_calls': 1, 'started_at': _OLD_TS, 'ended_at': _OLD_TS,
            'billing_provider': 'anthropic',
        }])

        invocations = self._run()
        own = _own_meter_invocations(invocations, sid)
        self.assertEqual(len(own), 1)
        flags = argv_to_flags(own[0])

        self.assertTrue(flags.get('--squad-id'), "expected a non-empty --squad-id")
        self.assertEqual(flags.get('--squad-id'), sid)


if __name__ == '__main__':
    unittest.main()
