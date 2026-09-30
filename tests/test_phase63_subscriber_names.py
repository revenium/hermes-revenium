"""Phase 63 Plan 04 (SUB-09): skills/revenium/scripts/subscriber-names.sh.

A local, module-owned fixture builder is used throughout instead of
tests/_compat_helpers.py's build_state_db: this module adds a `user_id`,
`origin_json` and (for the display_name-disagreement arm) a `display_name`
column on top of build_state_db's own 13-column production schema, and
must not touch that shared file, so it can run in parallel with 63-02's
own test module in the same wave.

Every actor id and name used below is synthetic and `p63-`-prefixed;
nothing is copied from any reference host.

63-REVIEW.md gap closure (WR-01, WR-02) adds two more test classes at the
end of this module: `SubscriberIdCapabilityNoticeTests` (an old CLI with
no --subscriber-id must not let this script imply the ID column reflects
what actually ships) and `PerHomeSubscriberEmailModeTests` (each profile
home's own subscriberEmailMode governs that home's own rows, not the
process-wide/default-profile setting).
"""

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests._compat_helpers import build_shim

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
SCRIPT = SKILL / 'scripts' / 'subscriber-names.sh'


def _build_sessions_db(path, rows=(), user_id_column=True, origin_json_column=True,
                        display_name_column=False):
    """Create a `sessions` table matching build_state_db's production schema
    (tests/_compat_helpers.py:440-469 / test_repository.py:1042-1064), then
    layer `user_id` / `origin_json` / `display_name` columns on top per-arm.

    Each row dict may supply: id, source, user_id, user_name (convenience --
    wrapped into an `origin_json` blob as {"user_name": ...}), origin_json
    (raw override, takes precedence over user_name), display_name.
    """
    conn = sqlite3.connect(str(path))
    conn.execute(
        'CREATE TABLE sessions ('
        'id TEXT, model TEXT, source TEXT, '
        'input_tokens INTEGER, output_tokens INTEGER, '
        'cache_read_tokens INTEGER, cache_write_tokens INTEGER, '
        'reasoning_tokens INTEGER, estimated_cost_usd TEXT, '
        'api_call_count INTEGER, started_at REAL, ended_at REAL, '
        'billing_provider TEXT)'
    )
    if user_id_column:
        conn.execute('ALTER TABLE sessions ADD COLUMN user_id TEXT')
    if origin_json_column:
        conn.execute('ALTER TABLE sessions ADD COLUMN origin_json TEXT')
    if display_name_column:
        conn.execute('ALTER TABLE sessions ADD COLUMN display_name TEXT')

    base_cols = ['id', 'model', 'source', 'input_tokens', 'output_tokens',
                 'cache_read_tokens', 'cache_write_tokens', 'reasoning_tokens',
                 'estimated_cost_usd', 'api_call_count', 'started_at', 'ended_at',
                 'billing_provider']

    for i, row in enumerate(rows):
        cols = list(base_cols)
        vals = [
            row.get('id', f'p63-sid-{i}'), row.get('model', 'claude'),
            row.get('source', 'slack'), row.get('input_tokens', 1),
            row.get('output_tokens', 1), row.get('cache_read', 0),
            row.get('cache_write', 0), row.get('reasoning', 0),
            row.get('estimated_cost', '0'), row.get('api_calls', 1),
            row.get('started_at', 0), row.get('ended_at', 0),
            row.get('billing_provider', 'anthropic'),
        ]
        if user_id_column:
            cols.append('user_id')
            vals.append(row.get('user_id'))
        if origin_json_column:
            cols.append('origin_json')
            if 'origin_json' in row:
                vals.append(row['origin_json'])
            elif 'user_name' in row:
                vals.append(json.dumps({'user_name': row['user_name']}))
            else:
                vals.append(None)
        if display_name_column:
            cols.append('display_name')
            vals.append(row.get('display_name'))
        placeholders = ','.join('?' for _ in cols)
        conn.execute(
            f'INSERT INTO sessions ({",".join(cols)}) VALUES ({placeholders})',
            vals,
        )
    conn.commit()
    conn.close()


def _log_bytes(state_dir):
    log_path = Path(state_dir) / 'revenium-metering.log'
    if log_path.exists():
        return log_path.read_bytes()
    return None


class SubscriberNamesScriptTestCase(unittest.TestCase):
    """Base class: builds an isolated HERMES_DEFAULT_HOME + REVENIUM_STATE_DIR
    per test, never touching the real host's ~/.hermes tree."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.home = self.tmp_path / 'home'
        self.home.mkdir(parents=True)
        self.state_dir = self.tmp_path / 'state'
        self.db_path = self.home / 'state.db'

    def tearDown(self):
        self._tmp.cleanup()

    def _env(self, extra=None):
        env = os.environ.copy()
        env.pop('HERMES_HOME', None)
        env.pop('REVENIUM_SUBSCRIBER_EMAIL_MODE', None)
        env['HERMES_DEFAULT_HOME'] = str(self.home)
        env['REVENIUM_STATE_DIR'] = str(self.state_dir)
        if extra:
            env.update(extra)
        return env

    def run_script(self, args=(), extra_env=None):
        result = subprocess.run(
            ['bash', str(SCRIPT), *args],
            env=self._env(extra_env),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result


class HappyPathTests(SubscriberNamesScriptTestCase):
    def setUp(self):
        super().setUp()
        _build_sessions_db(self.db_path, rows=[
            {'id': 'p63-s1', 'source': 'slack', 'user_id': 'p63-U001',
             'user_name': 'Jane Doe'},
            {'id': 'p63-s2', 'source': 'slack', 'user_id': 'p63-U002',
             'user_name': 'Bob Smith'},
            {'id': 'p63-s3', 'source': 'slack', 'user_id': 'p63-U003',
             'user_name': None},
        ])

    def test_named_actors_and_unnamed_actor_all_listed(self):
        result = self.run_script()
        self.assertIn('Jane Doe', result.stdout)
        self.assertIn('Bob Smith', result.stdout)
        self.assertIn('p63-U003', result.stdout)
        self.assertIn('UNRESOLVED', result.stdout)
        self.assertEqual(result.returncode, 10)

    def test_summary_unnamed_count_matches_row_count(self):
        result = self.run_script()
        unresolved_rows = [
            line for line in result.stdout.splitlines()
            if line.startswith('default\t') and 'UNRESOLVED' in line
        ]
        self.assertEqual(len(unresolved_rows), 1)
        m = re.search(r'Without a name\s*:\s*(\d+)', result.stdout)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), len(unresolved_rows))

    def test_quiet_mode_shape(self):
        result = self.run_script(args=['--quiet'])
        self.assertNotIn('PROFILE', result.stdout)
        self.assertNotIn('Actors listed', result.stdout)
        lines = [l for l in result.stdout.splitlines() if l]
        self.assertEqual(len(lines), 3)
        for line in lines:
            self.assertEqual(len(line.split('\t')), 2)

    def test_exit_code_10_when_unnamed_present(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 10)


class AllNamedExitZeroTests(SubscriberNamesScriptTestCase):
    def setUp(self):
        super().setUp()
        _build_sessions_db(self.db_path, rows=[
            {'id': 'p63-s1', 'source': 'slack', 'user_id': 'p63-U001',
             'user_name': 'Jane Doe'},
        ])

    def test_exit_code_0_when_every_actor_named(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0)
        self.assertIn('Jane Doe', result.stdout)


class DisplayNameNeverFallenBackTests(SubscriberNamesScriptTestCase):
    def setUp(self):
        super().setUp()
        _build_sessions_db(self.db_path, display_name_column=True, rows=[
            {'id': 'p63-s1', 'source': 'slack', 'user_id': 'p63-U777',
             'user_name': 'Real Human Name',
             'display_name': 'p63-CHANNEL-NOT-A-PERSON'},
        ])

    def test_user_name_present_display_name_absent(self):
        result = self.run_script()
        self.assertIn('Real Human Name', result.stdout)
        self.assertNotIn('p63-CHANNEL-NOT-A-PERSON', result.stdout)

    def test_script_never_selects_display_name_column(self):
        # Header prose legitimately explains WHY display_name is never
        # read (D-12) -- strip comment lines before asserting, the same
        # discipline the plan's own STATE_DIR grep gate uses, so this test
        # checks the SQL/active code, not the documentation of the guard.
        active_lines = [
            line for line in SCRIPT.read_text().splitlines()
            if not line.strip().startswith('#')
        ]
        self.assertNotIn('display_name', '\n'.join(active_lines))


class ErrPathNoSessionsTableTests(SubscriberNamesScriptTestCase):
    def setUp(self):
        super().setUp()
        # An empty state.db with no `sessions` table at all.
        conn = sqlite3.connect(str(self.db_path))
        conn.execute('CREATE TABLE unrelated (x TEXT)')
        conn.commit()
        conn.close()

    def test_exit_1_and_stderr_message(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr.strip() or 'skipped' in result.stdout)


class LogUntouchedTests(SubscriberNamesScriptTestCase):
    """D-11: revenium-metering.log is byte-identical before and after every
    run, and no file is written anywhere, whether the run succeeds, finds
    nothing, or fails.

    These three cases were ENVIRONMENT-DEPENDENT until the WR-01 regression
    exposed it, and that is the durable lesson worth keeping. WR-01 added a
    `supports_flag "meter completion" "--subscriber-id"` probe, and an
    INDETERMINATE probe (common.sh) appends a WARN line and drops a
    .probe-warn sentinel -- both forbidden here. A probe is indeterminate
    only when `revenium` cannot answer at all, so on any workstation with a
    real CLI on PATH these tests stayed green while CI, which has no
    `revenium` anywhere, went red on all three.

    `_unusable_cli_env` therefore reproduces CI's condition deterministically
    rather than inheriting the host's: a stub that exits non-zero with no
    output, placed in "${HOME}/.local/bin" with HOME redirected, because
    ensure_path (common.sh:495-510) prepends that directory FIRST and would
    otherwise let a homebrew revenium shadow the stub. Note the contrast with
    SubscriberIdCapabilityNoticeTests below: its build_shim shims ANSWER the
    probe, so they exercise a determinate NEGATIVE and by construction cannot
    catch this class of defect.
    """

    def _unusable_cli_env(self):
        """A `revenium` that fails silently -- the indeterminate-probe path."""
        fake_home = self.tmp_path / 'logfakehome'
        local_bin = fake_home / '.local' / 'bin'
        local_bin.mkdir(parents=True, exist_ok=True)
        stub = local_bin / 'revenium'
        stub.write_text('#!/bin/sh\nexit 127\n')
        stub.chmod(0o755)
        return {
            'HOME': str(fake_home),
            'PATH': f'{local_bin}{os.pathsep}{os.environ.get("PATH", "")}',
        }

    def _assert_log_untouched(self, args=(), extra_env=None):
        before = _log_bytes(self.state_dir)
        result = self.run_script(args=args, extra_env=extra_env)
        after = _log_bytes(self.state_dir)
        self.assertEqual(before, after, f'revenium-metering.log changed (exit={result.returncode})')
        # The sentinel is the second write the WARN path makes. Asserting only
        # the log would let a caller keep writing into STATE_DIR unnoticed.
        self.assertFalse(
            (Path(self.state_dir) / 'markers' / '.probe-warn').exists(),
            f'.probe-warn sentinel written (exit={result.returncode})',
        )
        return result

    def test_log_untouched_on_success(self):
        _build_sessions_db(self.db_path, rows=[
            {'id': 'p63-s1', 'source': 'slack', 'user_id': 'p63-U001',
             'user_name': 'Jane Doe'},
        ])
        result = self._assert_log_untouched()
        self.assertEqual(result.returncode, 0)

    def test_log_untouched_on_empty_result(self):
        _build_sessions_db(self.db_path, rows=[])
        result = self._assert_log_untouched()
        self.assertEqual(result.returncode, 0)

    def test_log_untouched_on_failure(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute('CREATE TABLE unrelated (x TEXT)')
        conn.commit()
        conn.close()
        result = self._assert_log_untouched()
        self.assertEqual(result.returncode, 1)

    def test_log_untouched_when_capability_probe_is_indeterminate(self):
        """The WR-01 regression itself, pinned. Fails on any host, not just
        one that happens to lack a revenium CLI."""
        _build_sessions_db(self.db_path, rows=[
            {'id': 'p63-s1', 'source': 'slack', 'user_id': 'p63-U001',
             'user_name': 'Jane Doe'},
        ])
        result = self._assert_log_untouched(extra_env=self._unusable_cli_env())
        # The finding is not swallowed -- suppressing the log line is only
        # legitimate because the same result reaches the operator on stderr.
        self.assertIn('does not advertise --subscriber-id', result.stderr)
        self.assertIn('Jane Doe', result.stdout)
        self.assertEqual(result.returncode, 0)


class SubscriberIdShippedFormTests(SubscriberNamesScriptTestCase):
    def setUp(self):
        super().setUp()
        _build_sessions_db(self.db_path, rows=[
            {'id': 'p63-s1', 'source': 'email', 'user_id': 'p63-jane@example.com',
             'user_name': 'Jane Example'},
        ])

    def test_plaintext_mode_shows_plaintext_key(self):
        result = self.run_script()
        self.assertIn('email:p63-jane@example.com', result.stdout)

    def test_obfuscated_mode_shows_64_hex_digest(self):
        digest = hashlib.sha256(b'p63-jane@example.com').hexdigest()
        result = self.run_script(extra_env={'REVENIUM_SUBSCRIBER_EMAIL_MODE': 'obfuscated'})
        self.assertIn(f'email:{digest}', result.stdout)
        self.assertNotIn('p63-jane@example.com', result.stdout)


class HelpTests(SubscriberNamesScriptTestCase):
    def test_help_exits_zero_and_names_flags_and_codes(self):
        result = self.run_script(args=['--help'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('--quiet', result.stdout)
        self.assertIn('--profile', result.stdout)
        self.assertIn('0', result.stdout)
        self.assertIn('10', result.stdout)
        self.assertIn('1', result.stdout)


# ---------------------------------------------------------------------------
# Task 2: the fleet walk, and the four edge-behaviour categories the
# deterministic edge probe named (adjacency, empty, encoding, ordering).
# ---------------------------------------------------------------------------

class FleetWalkTestCase(SubscriberNamesScriptTestCase):
    """Adds helpers for building extra profile homes under HOME/profiles/<name>/,
    matching hermes_profile_homes' own layout (common.sh:1241-1254)."""

    def _profile_db_path(self, name):
        profile_home = self.home / 'profiles' / name
        profile_home.mkdir(parents=True, exist_ok=True)
        return profile_home / 'state.db'

    def _data_rows(self, stdout):
        """Parse the PROFILE\tID\tNAME\tSESSIONS table rows out of stdout,
        skipping the header and the trailing note/summary lines."""
        rows = []
        for line in stdout.splitlines():
            if line in ('PROFILE\tID\tNAME\tSESSIONS', '') or line.startswith('Actors listed') \
                    or line.startswith('With a resolved name') or line.startswith('Without a name') \
                    or line.startswith('No shippable id'):
                continue
            parts = line.split('\t')
            if len(parts) == 4:
                rows.append(tuple(parts))
        return rows


class FleetWalkOrderingTests(FleetWalkTestCase):
    def setUp(self):
        super().setUp()
        _build_sessions_db(self.db_path, rows=[
            {'id': 'p63-d1', 'source': 'slack', 'user_id': 'p63-Udef',
             'user_name': 'Default Actor'},
        ])
        _build_sessions_db(self._profile_db_path('alpha'), rows=[
            {'id': 'p63-a1', 'source': 'slack', 'user_id': 'p63-Ualpha',
             'user_name': 'Alpha Actor'},
        ])
        _build_sessions_db(self._profile_db_path('beta'), rows=[
            {'id': 'p63-b1', 'source': 'slack', 'user_id': 'p63-Ubeta',
             'user_name': 'Beta Actor'},
        ])

    def test_default_home_rows_appear_before_profile_homes(self):
        result = self.run_script()
        rows = self._data_rows(result.stdout)
        profiles_in_order = [r[0] for r in rows]
        self.assertEqual(profiles_in_order[0], 'default')
        self.assertIn('alpha', profiles_in_order)
        self.assertIn('beta', profiles_in_order)
        self.assertLess(profiles_in_order.index('alpha'), profiles_in_order.index('default') + 3)


class FleetWalkNoMergingTests(FleetWalkTestCase):
    def setUp(self):
        super().setUp()
        # The SAME subscriber id (slack:p63-Ushared) appears in both the
        # default home and the 'qa' profile home -- with different counts.
        _build_sessions_db(self.db_path, rows=[
            {'id': 'p63-d1', 'source': 'slack', 'user_id': 'p63-Ushared',
             'user_name': 'Shared Actor'},
        ])
        _build_sessions_db(self._profile_db_path('qa'), rows=[
            {'id': 'p63-q1', 'source': 'slack', 'user_id': 'p63-Ushared',
             'user_name': 'Shared Actor'},
            {'id': 'p63-q2', 'source': 'slack', 'user_id': 'p63-Ushared',
             'user_name': 'Shared Actor'},
        ])

    def test_same_id_in_two_homes_yields_two_unmerged_rows(self):
        result = self.run_script()
        rows = self._data_rows(result.stdout)
        matching = [r for r in rows if r[1] == 'slack:p63-Ushared']
        self.assertEqual(len(matching), 2)
        counts = sorted(int(r[3]) for r in matching)
        self.assertEqual(counts, [1, 2])
        # Neither row's count is the sum of the two (3) -- that would be the
        # merge this arm exists to rule out.
        self.assertNotIn('3', [r[3] for r in matching])


class AdjacencyTwoActorsSameNameTests(SubscriberNamesScriptTestCase):
    def setUp(self):
        super().setUp()
        _build_sessions_db(self.db_path, rows=[
            {'id': 'p63-s1', 'source': 'slack', 'user_id': 'p63-Uone',
             'user_name': 'Same Name'},
            {'id': 'p63-s2', 'source': 'slack', 'user_id': 'p63-Utwo',
             'user_name': 'Same Name'},
        ])

    def test_two_distinct_actors_one_shared_name_stay_two_rows(self):
        result = self.run_script()
        matches = [line for line in result.stdout.splitlines() if 'Same Name' in line]
        self.assertEqual(len(matches), 2)
        self.assertIn('slack:p63-Uone', result.stdout)
        self.assertIn('slack:p63-Utwo', result.stdout)


class AdjacencyOneActorTwoNamesTests(SubscriberNamesScriptTestCase):
    def setUp(self):
        super().setUp()
        _build_sessions_db(self.db_path, rows=[
            {'id': 'p63-s1', 'source': 'slack', 'user_id': 'p63-Umulti',
             'user_name': 'Name Alpha'},
            {'id': 'p63-s2', 'source': 'slack', 'user_id': 'p63-Umulti',
             'user_name': 'Name Beta'},
        ])

    def test_one_actor_two_names_lists_both_and_marks_ambiguous(self):
        result = self.run_script()
        rows = [line for line in result.stdout.splitlines() if line.startswith('default\t')]
        self.assertEqual(len(rows), 1)
        self.assertIn('Name Alpha', rows[0])
        self.assertIn('Name Beta', rows[0])
        self.assertIn('[AMBIGUOUS]', rows[0])

    def test_summary_counts_ambiguous_actor_as_named_once(self):
        result = self.run_script()
        m = re.search(r'With a resolved name\s*:\s*(\d+)', result.stdout)
        self.assertEqual(int(m.group(1)), 1)
        self.assertEqual(result.returncode, 0)


class MissingOriginJsonColumnTests(SubscriberNamesScriptTestCase):
    def setUp(self):
        super().setUp()
        _build_sessions_db(self.db_path, origin_json_column=False, rows=[
            {'id': 'p63-s1', 'source': 'slack', 'user_id': 'p63-Uno1'},
            {'id': 'p63-s2', 'source': 'slack', 'user_id': 'p63-Uno2'},
        ])

    def test_every_actor_listed_with_column_marker_and_exit_10(self):
        result = self.run_script()
        self.assertEqual(result.stdout.count('UNRESOLVED:no-origin_json-column'), 2)
        self.assertIn('slack:p63-Uno1', result.stdout)
        self.assertIn('slack:p63-Uno2', result.stdout)
        self.assertEqual(result.returncode, 10)


class ZeroIdentityBearingSessionsTests(SubscriberNamesScriptTestCase):
    def setUp(self):
        super().setUp()
        _build_sessions_db(self.db_path, rows=[])

    def test_one_explanatory_line_no_header_no_rows_exit_0(self):
        result = self.run_script()
        self.assertNotIn('PROFILE\tID\tNAME\tSESSIONS', result.stdout)
        self.assertIn('no identity-bearing sessions found', result.stdout)
        self.assertIn(str(self.db_path), result.stdout)
        self.assertEqual(result.returncode, 0)


class ThreeNoNameShapesTests(SubscriberNamesScriptTestCase):
    def setUp(self):
        super().setUp()
        _build_sessions_db(self.db_path, rows=[
            {'id': 'p63-s1', 'source': 'slack', 'user_id': 'p63-Unull',
             'origin_json': json.dumps({'user_name': None})},
            {'id': 'p63-s2', 'source': 'slack', 'user_id': 'p63-Uabsent',
             'origin_json': json.dumps({})},
            {'id': 'p63-s3', 'source': 'slack', 'user_id': 'p63-Ublank',
             'origin_json': json.dumps({'user_name': '   '})},
        ])

    def test_all_three_shapes_listed_as_unresolved(self):
        result = self.run_script()
        for uid in ('p63-Unull', 'p63-Uabsent', 'p63-Ublank'):
            row = [l for l in result.stdout.splitlines() if f'slack:{uid}' in l]
            self.assertEqual(len(row), 1)
            self.assertIn('UNRESOLVED', row[0])


class NoUserIdColumnHomeTests(SubscriberNamesScriptTestCase):
    def setUp(self):
        super().setUp()
        _build_sessions_db(self.db_path, user_id_column=False, rows=[
            {'id': 'p63-s1', 'source': 'slack'},
        ])

    def test_no_actor_can_be_resolved_reported_as_legible_answer_exit_0(self):
        result = self.run_script()
        self.assertNotIn('PROFILE\tID\tNAME\tSESSIONS', result.stdout)
        self.assertIn('no user_id column', result.stdout)
        self.assertEqual(result.returncode, 0)


class MissingStateDbHomeTests(FleetWalkTestCase):
    def setUp(self):
        super().setUp()
        _build_sessions_db(self.db_path, rows=[
            {'id': 'p63-s1', 'source': 'slack', 'user_id': 'p63-Ugood',
             'user_name': 'Readable Actor'},
        ])
        # 'nodb' profile directory exists but has no state.db at all.
        (self.home / 'profiles' / 'nodb').mkdir(parents=True)

    def test_walk_continues_readable_home_present_exit_not_1(self):
        result = self.run_script()
        self.assertIn('Readable Actor', result.stdout)
        self.assertIn('nodb', result.stdout)
        self.assertIn('skipped', result.stdout)
        self.assertNotEqual(result.returncode, 1)


class UnknownProfileFlagTests(SubscriberNamesScriptTestCase):
    def test_unknown_profile_exits_1_with_known_profiles_on_stderr(self):
        (self.home / 'profiles' / 'qa').mkdir(parents=True)
        result = self.run_script(args=['--profile', 'p63-does-not-exist'])
        self.assertEqual(result.returncode, 1)
        self.assertIn('default', result.stderr)
        self.assertIn('qa', result.stderr)

    def test_unknown_profile_equals_form(self):
        result = self.run_script(args=['--profile=p63-nope'])
        self.assertEqual(result.returncode, 1)
        self.assertIn('default', result.stderr)


class OrderingStabilityTests(FleetWalkTestCase):
    def setUp(self):
        super().setUp()
        _build_sessions_db(self.db_path, rows=[
            {'id': 'p63-s1', 'source': 'slack', 'user_id': 'p63-Ustable',
             'user_name': 'Stable Actor'},
        ])
        _build_sessions_db(self._profile_db_path('qa'), rows=[
            {'id': 'p63-q1', 'source': 'slack', 'user_id': 'p63-Ustableqa',
             'user_name': 'Stable QA Actor'},
        ])

    def test_two_consecutive_runs_produce_byte_identical_stdout(self):
        result1 = self.run_script()
        result2 = self.run_script()
        self.assertEqual(result1.stdout, result2.stdout)


class EncodingNonAsciiNameTests(SubscriberNamesScriptTestCase):
    def setUp(self):
        super().setUp()
        _build_sessions_db(self.db_path, rows=[
            {'id': 'p63-s1', 'source': 'slack', 'user_id': 'p63-Uintl',
             'user_name': '日本語 Café Müller'},
        ])

    def test_non_ascii_name_passes_through_unchanged(self):
        result = self.run_script()
        self.assertIn('日本語 Café Müller', result.stdout)


class EncodingHostileNameTests(SubscriberNamesScriptTestCase):
    def setUp(self):
        super().setUp()
        hostile = 'Bad\tName\r\nWith|Pipe'
        _build_sessions_db(self.db_path, rows=[
            {'id': 'p63-s1', 'source': 'slack', 'user_id': 'p63-Ubefore',
             'user_name': 'Neighbour Before'},
            {'id': 'p63-s2', 'source': 'slack', 'user_id': 'p63-Uhostile',
             'user_name': hostile},
            {'id': 'p63-s3', 'source': 'slack', 'user_id': 'p63-Uafter',
             'user_name': 'Neighbour After'},
        ])

    def test_row_count_unchanged_neighbours_intact_altered_marker_present(self):
        result = self.run_script()
        data_rows = [
            line for line in result.stdout.splitlines()
            if line.startswith('default\t')
        ]
        self.assertEqual(len(data_rows), 3)
        neighbour_before = [r for r in data_rows if 'slack:p63-Ubefore' in r][0]
        neighbour_after = [r for r in data_rows if 'slack:p63-Uafter' in r][0]
        self.assertIn('Neighbour Before', neighbour_before)
        self.assertEqual(len(neighbour_before.split('\t')), 4)
        self.assertIn('Neighbour After', neighbour_after)
        self.assertEqual(len(neighbour_after.split('\t')), 4)
        hostile_row = [r for r in data_rows if 'slack:p63-Uhostile' in r][0]
        self.assertIn('[ALTERED]', hostile_row)
        self.assertNotIn('\t\t', hostile_row.replace('(n/a)', ''))
        # No raw tab/CR/LF/pipe survives inside the NAME field.
        self.assertNotIn('Bad\tName', result.stdout)
        self.assertNotIn('With|Pipe', result.stdout)


class EncodingHostileUserIdTests(SubscriberNamesScriptTestCase):
    def setUp(self):
        super().setUp()
        _build_sessions_db(self.db_path, rows=[
            {'id': 'p63-s1', 'source': 'slack', 'user_id': 'p63-Ubefore2',
             'user_name': 'Neighbour Before'},
            {'id': 'p63-s2', 'source': 'slack', 'user_id': 'p63-Uhostile|pipe',
             'user_name': 'Should Not Appear'},
            {'id': 'p63-s3', 'source': 'slack', 'user_id': 'p63-Uafter2',
             'user_name': 'Neighbour After'},
        ])

    def test_hostile_user_id_reports_no_id_marker_and_count_neighbours_intact(self):
        result = self.run_script()
        self.assertIn('NO-ID:unsafe', result.stdout)
        self.assertNotIn('p63-Uhostile|pipe', result.stdout)
        self.assertNotIn('Should Not Appear', result.stdout)
        self.assertIn('Neighbour Before', result.stdout)
        self.assertIn('Neighbour After', result.stdout)


class MalformedOriginJsonTests(SubscriberNamesScriptTestCase):
    def setUp(self):
        super().setUp()
        _build_sessions_db(self.db_path, rows=[
            {'id': 'p63-s1', 'source': 'slack', 'user_id': 'p63-Umixed',
             'origin_json': '{not valid json at all'},
            {'id': 'p63-s2', 'source': 'slack', 'user_id': 'p63-Umixed',
             'user_name': 'Recovered Name'},
            {'id': 'p63-s3', 'source': 'slack', 'user_id': 'p63-Uother',
             'user_name': 'Untouched Actor'},
        ])

    def test_malformed_row_does_not_cost_actor_or_others_their_name(self):
        result = self.run_script()
        self.assertIn('Recovered Name', result.stdout)
        self.assertIn('Untouched Actor', result.stdout)
        row = [l for l in result.stdout.splitlines() if 'slack:p63-Umixed' in l][0]
        self.assertIn('2', row.split('\t')[-1])


# ---------------------------------------------------------------------------
# Task 3: the four D-10 shipped-surface properties, asserted independently
# so a future edit that breaks one names exactly which property broke.
# Each is parsed/measured directly rather than by importing and running
# tests.test_repository, per the plan's own instruction.
# ---------------------------------------------------------------------------

class ShippedSurfaceConformanceTests(unittest.TestCase):
    def test_pinned_in_test_repository_expected_files_list(self):
        text = (ROOT / 'tests' / 'test_repository.py').read_text()
        self.assertIn("SKILL / 'scripts' / 'subscriber-names.sh'", text)

    def test_owner_execute_bit_set(self):
        mode = SCRIPT.stat().st_mode
        self.assertTrue(mode & 0o100, 'owner-execute bit not set on subscriber-names.sh')

    def test_sources_common_sh(self):
        text = SCRIPT.read_text()
        self.assertIn('source "${SCRIPT_DIR}/common.sh"', text)

    def test_bash_syntax_check_passes(self):
        result = subprocess.run(['bash', '-n', str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


# ---------------------------------------------------------------------------
# 63-REVIEW.md gap closure.
# ---------------------------------------------------------------------------

class SubscriberIdCapabilityNoticeTests(SubscriberNamesScriptTestCase):
    """WR-01: subscriber-names.sh never probed --subscriber-id capability,
    so on a host whose CLI predates the flag it printed ids as though they
    shipped when NOTHING ships (SUB-07's fail-open contract on all four
    production emission sites). It must now probe, matching the reporters'
    own idiom, and say so on stderr when the probe is negative -- without
    dropping any actor row.

    ensure_path (common.sh:495-510) prepends candidate PATH directories in
    an order that puts "${HOME}/.local/bin" FIRST in the final PATH ahead
    of any real system revenium (e.g. a homebrew install) -- so the shim
    must live there, with HOME redirected to a throwaway directory, exactly
    like tests.test_phase63_subscriber_email._Harness.base_env() does for
    hermes-report.sh's own equivalent probe.
    """

    def setUp(self):
        super().setUp()
        _build_sessions_db(self.db_path, rows=[
            {'id': 'p63-s1', 'source': 'slack', 'user_id': 'p63-Ucap',
             'user_name': 'Capability Actor'},
        ])
        self.fake_home = self.tmp_path / 'fakehome'
        self.local_bin = self.fake_home / '.local' / 'bin'
        self.local_bin.mkdir(parents=True)

    def _shim_env(self, subscriber_capable):
        shim = self.local_bin / 'revenium'
        build_shim(str(shim), subscriber_capable=subscriber_capable)
        return {
            'HOME': str(self.fake_home),
            'PATH': f'{self.local_bin}{os.pathsep}{os.environ.get("PATH", "")}',
        }

    def test_incapable_cli_prints_stderr_notice_and_still_lists_actor(self):
        result = self.run_script(extra_env=self._shim_env(subscriber_capable=False))
        self.assertIn('does not advertise --subscriber-id', result.stderr)
        self.assertIn('Capability Actor', result.stdout)
        self.assertIn('slack:p63-Ucap', result.stdout)
        # The notice is informational only -- exit code semantics are
        # unchanged (every actor here has a resolved name).
        self.assertEqual(result.returncode, 0)

    def test_capable_cli_prints_no_notice(self):
        result = self.run_script(extra_env=self._shim_env(subscriber_capable=True))
        self.assertNotIn('does not advertise', result.stderr)
        self.assertIn('Capability Actor', result.stdout)


class PerHomeSubscriberEmailModeTests(FleetWalkTestCase):
    """WR-02: subscriberEmailMode was resolved ONCE, from the process/
    default-profile config, then applied to every profile home walked --
    showing the wrong wire form for any profile whose own config.json
    disagrees. Each profile home must resolve its OWN mode from its OWN
    config.json, mirroring db_path's own per-home derivation."""

    def setUp(self):
        super().setUp()
        _build_sessions_db(self.db_path, rows=[
            {'id': 'p63-d1', 'source': 'email', 'user_id': 'p63-default@example.com',
             'user_name': 'Default Actor'},
        ])
        _build_sessions_db(self._profile_db_path('obfus'), rows=[
            {'id': 'p63-o1', 'source': 'email', 'user_id': 'p63-profileb@example.com',
             'user_name': 'Profile B Actor'},
        ])
        # Default profile's own config.json is left absent (plaintext by
        # default); the 'obfus' profile sets its OWN config.json to
        # obfuscated -- entirely independent of the default profile.
        profile_config_dir = self.home / 'profiles' / 'obfus' / 'state' / 'revenium'
        profile_config_dir.mkdir(parents=True, exist_ok=True)
        (profile_config_dir / 'config.json').write_text(
            json.dumps({'subscriberEmailMode': 'obfuscated'})
        )

    @staticmethod
    def _digest(addr):
        return hashlib.sha256(addr.encode('utf-8')).hexdigest()

    def test_fleet_wide_run_shows_each_profiles_own_mode(self):
        digest = self._digest('p63-profileb@example.com')
        result = self.run_script()
        # Default profile has no config.json of its own -- plaintext.
        self.assertIn('email:p63-default@example.com', result.stdout)
        # 'obfus' profile's OWN config.json says obfuscated -- its actor's
        # plaintext address must never appear on stdout.
        self.assertIn(f'email:{digest}', result.stdout)
        self.assertNotIn('p63-profileb@example.com', result.stdout)

    def test_profile_flag_resolves_that_profiles_own_mode_too(self):
        # Finding item 2: even a targeted --profile run must redirect the
        # MODE resolution, not just the db_path.
        digest = self._digest('p63-profileb@example.com')
        result = self.run_script(args=['--profile', 'obfus'])
        self.assertIn(f'email:{digest}', result.stdout)
        self.assertNotIn('p63-profileb@example.com', result.stdout)

    def test_default_profile_still_honours_env_var_override(self):
        # The env var must keep winning over every home's own config.json,
        # including the profile that has its own obfuscated setting --
        # here forced to plaintext via the env var, which must apply
        # process-wide exactly as it did before this fix.
        result = self.run_script(extra_env={'REVENIUM_SUBSCRIBER_EMAIL_MODE': 'plaintext'})
        self.assertIn('email:p63-default@example.com', result.stdout)
        self.assertIn('email:p63-profileb@example.com', result.stdout)


class InvalidPerHomeSubscriberEmailModeTests(FleetWalkTestCase):
    """An unrecognised subscriberEmailMode value in one profile's own
    config.json must not spam a warning per actor -- one legible note per
    affected home, falling back to plaintext for that home only."""

    def setUp(self):
        super().setUp()
        _build_sessions_db(self._profile_db_path('bad'), rows=[
            {'id': 'p63-b1', 'source': 'email', 'user_id': 'p63-bad@example.com',
             'user_name': 'Bad Config Actor'},
        ])
        profile_config_dir = self.home / 'profiles' / 'bad' / 'state' / 'revenium'
        profile_config_dir.mkdir(parents=True, exist_ok=True)
        (profile_config_dir / 'config.json').write_text(
            json.dumps({'subscriberEmailMode': 'not-a-real-mode'})
        )

    def test_falls_back_to_plaintext_with_one_note(self):
        result = self.run_script()
        self.assertIn('email:p63-bad@example.com', result.stdout)
        self.assertEqual(
            result.stdout.count('subscriberEmailMode') +
            result.stderr.count('subscriberEmailMode'),
            1,
        )


if __name__ == '__main__':
    unittest.main()
