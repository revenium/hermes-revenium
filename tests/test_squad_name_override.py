"""quick-260814-okp: REVENIUM_SQUAD_NAME operator override at --squad-name.

Proves the three-level resolution hermes-report.sh now applies at BOTH squad
emit sites: REVENIUM_SQUAD_NAME (operator override) > root_agent_name
(marker-derived) > REVENIUM_AGENT_NAME (fallback). Also pins:

- the unset case is byte-identical to the pre-change golden fixture
  (tests/fixtures/compat/meter-completion-markerless.golden.json);
- the override never leaks past the SQUAD_CLI_CAPABLE gate;
- --squad-id / --squad-role / flag order are unaffected by the override;
- --agent still inherits root_agent_name independently of --squad-name (the
  two flags diverge under an override — this is the assertion that proves
  the override did not leak into the AGENT dimension);
- REVENIUM_SQUAD_NAME is declared (assigned) in exactly one script,
  common.sh — the same locality discipline
  tests/test_repository.py::test_runtime_paths_are_hermes_native enforces
  for state paths.

Fixture-seeding helpers (`_seed_sessions_db`, `_write_marker_lines`,
`_task_marker`, `_own_meter_invocations`) and the harness shape are copied
verbatim (same convention test_phase29_agent_inheritance.py documents for
its own borrow) from tests/test_phase29_squad_argv.py. The incapable-shim
builder `_write_shim_with_help_lines` is imported directly from
tests/test_phase29_squad_capability_gate.py, the module that owns it.
"""
import json
import os
import re
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
from tests.test_phase29_squad_capability_gate import _write_shim_with_help_lines

# Fixed far-past epoch (matches test_compat_meter_completion.py /
# test_phase29_squad_argv.py) so every seeded session clears the
# settle-seconds filter regardless of REVENIUM_CRON_SETTLE_SECONDS.
_OLD_TS = 1715514000.0


def _seed_sessions_db(db_path, rows):
    """Create a sessions table WITH parent_session_id and insert one row per
    (sid, parent_sid_or_none, input_tokens, output_tokens) tuple. Copied
    verbatim from tests/test_phase29_squad_argv.py."""
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
    `sid` specifically."""
    result = []
    for argv in invocations:
        flags = argv_to_flags(argv)
        txn = flags.get('--transaction-id', '')
        if txn.startswith(sid + '-'):
            result.append(argv)
    return result


class SquadNameOverrideTestCase(unittest.TestCase):
    """Shared PATH-shim harness: one temp HERMES_HOME, one shim, one meter
    log. Each test seeds its own state.db + marker files."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gsd-squad-name-override-")
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

    def _base_env(self, squad_name=''):
        # squad_name defaults to '' (explicitly set, not omitted) so an
        # ambient export on the developer's or fleet host's shell can never
        # silently change a baseline assertion — same idiom as the existing
        # 'REVENIUM_ORGANIZATION_NAME': '' entry.
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
            'REVENIUM_SQUAD_NAME': squad_name,
        }

    def _run(self, squad_name=''):
        rc, _ignored_inv, output = run_script(
            SCRIPTS_DIR / 'hermes-report.sh', self._base_env(squad_name), self.inv_log
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

    # ---- Baselines: REVENIUM_SQUAD_NAME empty, unchanged behavior ----

    def test_baseline_markerless_squad_name_is_hermes(self):
        sid = "sqno-baseline-markerless-1"
        _seed_sessions_db(self.state_db, [(sid, None, 100, 50)])
        # No marker file at all.

        invocations = self._run(squad_name='')
        own = _own_meter_invocations(invocations, sid)
        self.assertEqual(len(own), 1, f"expected exactly 1 completion for {sid}; got {own!r}")
        flags = argv_to_flags(own[0])

        self.assertEqual(flags.get('--squad-name'), 'Hermes')

    def test_baseline_marker_bearing_squad_name_is_hermes(self):
        sid = "sqno-baseline-marker-1"
        _seed_sessions_db(self.state_db, [(sid, None, 100, 50)])
        _write_marker_lines(self.markers_dir, sid, [_task_marker(sid, "sqno-muid-1")])

        invocations = self._run(squad_name='')
        own = _own_meter_invocations(invocations, sid)
        self.assertEqual(len(own), 1, f"expected exactly 1 completion for {sid}; got {own!r}")
        flags = argv_to_flags(own[0])

        self.assertEqual(flags.get('--squad-name'), 'Hermes')

    # ---- Override wins at both emit paths ----

    def test_override_marker_bearing_squad_name_wins(self):
        sid = "sqno-override-marker-1"
        _seed_sessions_db(self.state_db, [(sid, None, 100, 50)])
        _write_marker_lines(self.markers_dir, sid, [_task_marker(sid, "sqno-muid-2")])

        invocations = self._run(squad_name='GTM')
        own = _own_meter_invocations(invocations, sid)
        self.assertEqual(len(own), 1, f"expected exactly 1 completion for {sid}; got {own!r}")
        flags = argv_to_flags(own[0])

        self.assertEqual(flags.get('--squad-name'), 'GTM')
        # Neighbours undisturbed: --squad-id is still the root sid (this
        # session IS the root) and --squad-role is still 'root'.
        self.assertEqual(flags.get('--squad-id'), sid)
        self.assertEqual(flags.get('--squad-role'), 'root')

    def test_override_markerless_squad_name_wins(self):
        sid = "sqno-override-markerless-1"
        _seed_sessions_db(self.state_db, [(sid, None, 100, 50)])
        # No marker file at all.

        invocations = self._run(squad_name='GTM')
        own = _own_meter_invocations(invocations, sid)
        self.assertEqual(len(own), 1, f"expected exactly 1 completion for {sid}; got {own!r}")
        flags = argv_to_flags(own[0])

        self.assertEqual(flags.get('--squad-name'), 'GTM')
        self.assertEqual(flags.get('--squad-id'), sid)
        self.assertEqual(flags.get('--squad-role'), 'root')

    def test_override_beats_root_inheritance_while_agent_still_inherits(self):
        """The override outranks root_agent_name at --squad-name, while
        --agent (a DIFFERENT consumer of the same root_agent_name) still
        inherits it unchanged. The two flags must diverge in the same argv
        — this is the assertion that proves the override did not leak into
        the AGENT dimension."""
        root_sid = "sqno-override-inherit-root-1"
        child_sid = "sqno-override-inherit-child-1"
        _seed_sessions_db(self.state_db, [
            (child_sid, root_sid, 100, 50),
        ])
        _write_marker_lines(self.markers_dir, root_sid, [
            {"kind": "agent_info", "agent": "Hermes-marketing"},
        ])
        # child_sid has no marker file of its own -> markerless emit path.

        invocations = self._run(squad_name='GTM')
        own = _own_meter_invocations(invocations, child_sid)
        self.assertEqual(len(own), 1, f"expected exactly 1 completion for {child_sid}; got {own!r}")
        flags = argv_to_flags(own[0])

        self.assertEqual(flags.get('--squad-name'), 'GTM')
        self.assertEqual(flags.get('--agent'), 'Hermes-marketing')
        self.assertNotEqual(flags.get('--squad-name'), flags.get('--agent'))
        # Neighbours undisturbed: --squad-id is the ROOT id, --squad-role is
        # 'subagent' since this is a dispatched child.
        self.assertEqual(flags.get('--squad-id'), root_sid)
        self.assertEqual(flags.get('--squad-role'), 'subagent')

    # ---- Flag order under override, both emit paths ----

    def test_flag_order_under_override_marker_bearing_path(self):
        sid = "sqno-order-marker-1"
        _seed_sessions_db(self.state_db, [(sid, None, 100, 50)])
        _write_marker_lines(self.markers_dir, sid, [_task_marker(sid, "sqno-muid-order")])

        invocations = self._run(squad_name='GTM')
        own = _own_meter_invocations(invocations, sid)
        self.assertEqual(len(own), 1)
        argv = own[0]

        idx_id = argv.index('--squad-id')
        idx_name = argv.index('--squad-name')
        idx_role = argv.index('--squad-role')
        self.assertLess(idx_id, idx_name)
        self.assertLess(idx_name, idx_role)

    def test_flag_order_under_override_markerless_path(self):
        sid = "sqno-order-markerless-1"
        _seed_sessions_db(self.state_db, [(sid, None, 100, 50)])
        # No marker file at all.

        invocations = self._run(squad_name='GTM')
        own = _own_meter_invocations(invocations, sid)
        self.assertEqual(len(own), 1)
        argv = own[0]

        idx_id = argv.index('--squad-id')
        idx_name = argv.index('--squad-name')
        idx_role = argv.index('--squad-role')
        self.assertLess(idx_id, idx_name)
        self.assertLess(idx_name, idx_role)

    # ---- Capability gate under override: an override must never bypass the probe ----

    def test_capability_gate_under_override_no_leak(self):
        sid = "sqno-gate-1"
        _seed_sessions_db(self.state_db, [(sid, None, 100, 50)])
        _write_marker_lines(self.markers_dir, sid, [_task_marker(sid, "sqno-gate-muid")])
        # Overwrite setUp's capable shim with one that advertises NONE of
        # the three squad flags.
        _write_shim_with_help_lines(self.shim, help_lines=[])

        invocations = self._run(squad_name='GTM')
        own = _own_meter_invocations(invocations, sid)
        self.assertEqual(len(own), 1, f"expected exactly 1 completion for {sid}; got {own!r}")
        argv = own[0]

        for flag in ('--squad-id', '--squad-name', '--squad-role'):
            self.assertNotIn(flag, argv, f'{flag} must not appear against an incapable CLI: {argv}')
        self.assertNotIn('GTM', argv, f'override value must not leak past the capability gate: {argv}')

    # ---- Unset-case byte-identity against the shipped golden ----

    def test_unset_byte_identical_to_shipped_golden(self):
        """Reproduces the exact fixture used to capture
        meter-completion-markerless.golden.json, with REVENIUM_SQUAD_NAME
        explicitly empty. The captured argv token list must equal the
        golden's argv_order element for element — proving the unset case
        is byte-identical to today, not merely 'close'."""
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

        env = self._base_env(squad_name='')
        env['REVENIUM_AGENT_NAME'] = 'Hermes'
        rc, _ignored_inv, output = run_script(
            SCRIPTS_DIR / 'hermes-report.sh', env, self.inv_log
        )
        self.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {output}')
        meter_invocations = []
        if os.path.exists(self.meter_log):
            with open(self.meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        meter_invocations.append(shlex.split(line))
        own = _own_meter_invocations(meter_invocations, sid)
        self.assertEqual(len(own), 1, f"expected exactly 1 completion for {sid}; got {own!r}")
        captured_argv = own[0]

        golden = load_golden('meter-completion-markerless.golden.json')
        self.assertEqual(
            captured_argv, golden['argv_order'],
            'REVENIUM_SQUAD_NAME wire drift: unset-case markerless argv is no longer '
            'byte-identical to the shipped golden '
            '(tests/fixtures/compat/meter-completion-markerless.golden.json).\n'
            f'Captured: {captured_argv}\nGolden:   {golden["argv_order"]}'
        )

    # ---- Repository invariant: REVENIUM_SQUAD_NAME assigned in exactly one script ----

    def test_squad_name_declared_only_in_common_sh(self):
        """Mirrors the locality discipline
        tests/test_repository.py::test_runtime_paths_are_hermes_native
        enforces for state paths: REVENIUM_SQUAD_NAME must be ASSIGNED
        (`REVENIUM_SQUAD_NAME=...`) in exactly one script, common.sh. Reads
        of the variable (`${REVENIUM_SQUAD_NAME:-...}`) are expected
        elsewhere and must not trip this — the assignment-form regex below
        never matches a `${...}` expansion."""
        scripts_dir = SCRIPTS_DIR
        assign_re = re.compile(r'(?<!\$\{)\bREVENIUM_SQUAD_NAME=')
        assigning_files = []
        for script in sorted(scripts_dir.glob('*.sh')):
            text = script.read_text()
            if assign_re.search(text):
                assigning_files.append(script.name)

        self.assertEqual(
            assigning_files, ['common.sh'],
            f'REVENIUM_SQUAD_NAME must be assigned in common.sh only; found in: {assigning_files!r}'
        )


if __name__ == '__main__':
    unittest.main()
