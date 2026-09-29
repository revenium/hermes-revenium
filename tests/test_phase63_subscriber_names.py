"""Phase 63 Plan 04 (SUB-09): skills/revenium/scripts/subscriber-names.sh.

A local, module-owned fixture builder is used throughout instead of
tests/_compat_helpers.py's build_state_db: this module adds a `user_id`,
`origin_json` and (for the display_name-disagreement arm) a `display_name`
column on top of build_state_db's own 13-column production schema, and
must not touch that shared file, so it can run in parallel with 63-02's
own test module in the same wave.

Every actor id and name used below is synthetic and `p63-`-prefixed;
nothing is copied from any reference host.
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
    def _assert_log_untouched(self, args=()):
        before = _log_bytes(self.state_dir)
        result = self.run_script(args=args)
        after = _log_bytes(self.state_dir)
        self.assertEqual(before, after, f'revenium-metering.log changed (exit={result.returncode})')
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


if __name__ == '__main__':
    unittest.main()
