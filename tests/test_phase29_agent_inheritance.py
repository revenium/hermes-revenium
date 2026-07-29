"""Phase 29 (AGENT-01/02/03): root-inherited --agent at the markerless emit
path in hermes-report.sh.

Four groups of assertions, per 29-03-PLAN.md Task 2:

1. No observable change (byte-diff): the exact fixture used to capture
   tests/fixtures/compat/meter-completion-markerless.golden.json, re-run
   against the post-AGENT-01-edit script, must produce an argv token list
   that is EQUAL (element for element, in order) to the golden's
   `argv_order`. This is what makes docs/migration-agent-dimension.md's
   central claim falsifiable rather than asserted in prose — see
   <measured_finding> in 29-03-PLAN.md. If this test goes red, the change
   has stopped being a no-op and docs/migration-agent-dimension.md MUST be
   revisited.

2. Inheritance actually works (fail-first proof): a markerless SUBAGENT
   session whose ROOT has an explicit `agent` field in its marker file must
   inherit that value at --agent. Against the pre-AGENT-01-edit code this
   assertion fails (the markerless path hardcoded REVENIUM_AGENT_NAME) —
   that is what proves this change is real, not a no-op rename. No
   production writer populates the marker `agent` field today (per
   29-02-PLAN.md's <agent_field_finding>), so the fixture in this test is
   the only writer.

3. AGENT-02, no regression on the paths that already work — including the
   deliberate --agent (own marker) vs --squad-name (root marker) asymmetry
   this plan's D-01/D-03 combination introduces.

4. Injection at the --agent boundary: the same T-29-01 sanitizer control
   29-02 proves for --squad-name, re-asserted at this second consumer.

Analog: tests/test_phase29_squad_argv.py (the fixture-seeding shape this
module reuses verbatim — `_seed_sessions_db` with a `parent_session_id`
column, `_write_marker_lines`, `_task_marker`, `_own_meter_invocations`)
and tests/_compat_helpers.py (`build_shim`, `build_state_db`, `run_script`,
`argv_to_flags`).
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
    build_state_db,
    load_golden,
    run_script,
    SCRIPTS_DIR,
)

# Fixed far-past epoch (matches test_compat_meter_completion.py /
# test_phase29_squad_argv.py) so every seeded session clears the
# settle-seconds filter regardless of REVENIUM_CRON_SETTLE_SECONDS.
_OLD_TS = 1715514000.0


def _seed_sessions_db(db_path, rows):
    """Create a sessions table WITH parent_session_id and insert one row per
    (sid, parent_sid_or_none, input_tokens, output_tokens) tuple. Copied
    verbatim (same shape) from tests/test_phase29_squad_argv.py — needed
    here (unlike _compat_helpers.build_state_db) because the subagent
    fixtures require a real parent_session_id column for
    get_root_session_id's sidecar query to resolve a root distinct from
    the child."""
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


class Phase29AgentInheritanceTestCase(unittest.TestCase):
    """Shared PATH-shim harness: one temp HERMES_HOME, one shim, one meter
    log. Each test seeds its own state.db + marker files."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gsd-phase29-agent-inherit-")
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
            'REVENIUM_AGENT_NAME': 'Hermes',
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

    # ---- Group 1: no observable change (the byte-diff) ----

    def test_markerless_root_argv_byte_identical_to_pre_agent01_golden(self):
        """Re-run the EXACT fixture used to capture
        meter-completion-markerless.golden.json (one root session, no
        marker file, REVENIUM_AGENT_NAME=Hermes, squad_capable=True)
        against the post-edit script. The captured argv token list must
        equal the golden's argv_order list element for element.

        If this test fails, the AGENT-01 resolution has started producing
        a DIFFERENT value than REVENIUM_AGENT_NAME for a session whose
        root has no marker-derived agent value — the exact scenario
        docs/migration-agent-dimension.md declares impossible today. That
        document's central claim must be revisited before this test is
        allowed to go green again.
        """
        sid = "compat-sid-markerless-001"
        build_state_db(self.state_db, [{
            'id': sid,
            'model': 'claude-sonnet-4-6',
            'source': 'test',
            'input_tokens': 100,
            'output_tokens': 50,
            'cache_read': 0,
            'cache_write': 0,
            'reasoning': 0,
            'estimated_cost': '0',
            'api_calls': 1,
            'started_at': _OLD_TS,
            'ended_at': _OLD_TS,
            'billing_provider': 'anthropic',
        }])
        # Deliberately no marker file at all for this sid.

        invocations = self._run()
        own = _own_meter_invocations(invocations, sid)
        self.assertEqual(len(own), 1, f"expected exactly 1 completion for {sid}; got {own!r}")
        captured_argv = own[0]

        golden = load_golden('meter-completion-markerless.golden.json')
        self.assertEqual(
            captured_argv, golden['argv_order'],
            'AGENT-01 wire drift: markerless argv is no longer byte-identical to the '
            'pre-edit golden (tests/fixtures/compat/meter-completion-markerless.golden.json). '
            'docs/migration-agent-dimension.md must be revisited before this can go green.\n'
            f'Captured: {captured_argv}\nGolden:   {golden["argv_order"]}'
        )

    # ---- Group 2: inheritance actually works (fail-first proof) ----

    def test_markerless_subagent_inherits_root_agent_name(self):
        """A markerless subagent whose ROOT marker carries an explicit
        `agent` field must inherit that value at --agent. This assertion
        is RED against the pre-AGENT-01-edit code (which hardcoded
        REVENIUM_AGENT_NAME on this path) — proving the change is a real
        behavior change, not a no-op rename.

        No production code path writes the marker `agent` field today
        (29-02-PLAN.md's <agent_field_finding>); this fixture is the only
        writer, same as test_phase29_squad_argv.py's populated-agent-field
        cases.
        """
        root_sid = "agent-inherit-root-1"
        child_sid = "agent-inherit-child-1"
        _seed_sessions_db(self.state_db, [
            (child_sid, root_sid, 100, 50),
        ])
        _write_marker_lines(self.markers_dir, root_sid, [
            {"kind": "agent_info", "agent": "Hermes-marketing"},
        ])
        # child_sid has no marker file of its own -> markerless emit path.

        invocations = self._run()
        own = _own_meter_invocations(invocations, child_sid)
        self.assertEqual(len(own), 1, f"expected exactly 1 completion for {child_sid}; got {own!r}")
        flags = argv_to_flags(own[0])

        self.assertEqual(flags.get('--agent'), 'Hermes-marketing')

    # ---- Group 3: AGENT-02, no regression on the paths that already work ----

    def test_markerless_root_with_no_marker_falls_back_to_agent_name(self):
        sid = "agent-inherit-root-noop-1"
        build_state_db(self.state_db, [{
            'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
            'input_tokens': 100, 'output_tokens': 50, 'cache_read': 0,
            'cache_write': 0, 'reasoning': 0, 'estimated_cost': '0',
            'api_calls': 1, 'started_at': _OLD_TS, 'ended_at': _OLD_TS,
            'billing_provider': 'anthropic',
        }])
        # No marker file at all -> root_sid == sid, no root marker.

        invocations = self._run()
        own = _own_meter_invocations(invocations, sid)
        self.assertEqual(len(own), 1)
        flags = argv_to_flags(own[0])

        self.assertEqual(flags.get('--agent'), 'Hermes')

    def test_marker_bearing_agent_and_squad_name_asymmetry(self):
        """A marker-bearing session's own marker `agent` field wins for
        --agent (the m_agent path, unchanged by this plan), while
        --squad-name carries the ROOT's agent value. Pins the deliberate
        asymmetry between --agent (session's own marker) and --squad-name
        (root's marker) so a later refactor cannot silently collapse the
        two into one resolution."""
        root_sid = "agent-inherit-root-asym-1"
        child_sid = "agent-inherit-child-asym-1"
        _seed_sessions_db(self.state_db, [
            (child_sid, root_sid, 100, 50),
        ])
        _write_marker_lines(self.markers_dir, root_sid, [
            {"kind": "agent_info", "agent": "Hermes-root-value"},
        ])
        _write_marker_lines(self.markers_dir, child_sid, [
            _task_marker(child_sid, "asym-muid-1", extra={"agent": "Should-Not-Win"}),
        ])

        invocations = self._run()
        own = _own_meter_invocations(invocations, child_sid)
        self.assertEqual(len(own), 1, f"expected exactly 1 completion for {child_sid}; got {own!r}")
        flags = argv_to_flags(own[0])

        self.assertEqual(flags.get('--agent'), 'Should-Not-Win')
        self.assertEqual(flags.get('--squad-name'), 'Hermes-root-value')
        self.assertNotEqual(flags.get('--agent'), flags.get('--squad-name'))

    def test_markerless_subagent_root_marker_has_no_agent_key(self):
        """The ROOT marker file exists (so root_markers_dir resolution and
        the file-existence check both succeed) but carries no `agent` key
        at all -> root_agent_name resolves empty -> --agent falls back to
        REVENIUM_AGENT_NAME, exactly as before (D-02)."""
        root_sid = "agent-inherit-root-no-agent-key-1"
        child_sid = "agent-inherit-child-no-agent-key-1"
        _seed_sessions_db(self.state_db, [
            (child_sid, root_sid, 100, 50),
        ])
        # Root has a marker file, but its record carries no 'agent' key.
        _write_marker_lines(self.markers_dir, root_sid, [
            _task_marker(root_sid, "root-muid-1"),
        ])
        # child_sid has no marker file of its own -> markerless emit path.

        invocations = self._run()
        own = _own_meter_invocations(invocations, child_sid)
        self.assertEqual(len(own), 1, f"expected exactly 1 completion for {child_sid}; got {own!r}")
        flags = argv_to_flags(own[0])

        self.assertEqual(flags.get('--agent'), 'Hermes')

    # ---- Group 4: injection at the --agent boundary ----

    def test_root_agent_field_injection_cannot_forge_agent(self):
        """Same T-29-01 control 29-02 proves for --squad-name, re-asserted
        at the second consumer this plan adds: a hostile root `agent`
        value cannot forge a second ROOT_AGENT= heredoc line or leak its
        forged suffix into the emitted --agent value."""
        root_sid = "agent-inherit-root-injection-1"
        child_sid = "agent-inherit-child-injection-1"
        _seed_sessions_db(self.state_db, [
            (child_sid, root_sid, 100, 50),
        ])
        _write_marker_lines(self.markers_dir, root_sid, [
            {"kind": "agent_info", "agent": "evil\nROOT_AGENT=pwned"},
        ])

        invocations = self._run()
        own = _own_meter_invocations(invocations, child_sid)
        self.assertEqual(len(own), 1, f"expected exactly 1 completion for {child_sid}; got {own!r}")
        flags = argv_to_flags(own[0])
        agent_value = flags.get('--agent', '')

        self.assertNotEqual(agent_value, 'pwned')
        self.assertNotIn('\n', agent_value)
        self.assertNotIn('ROOT_AGENT', agent_value)


if __name__ == '__main__':
    unittest.main()
