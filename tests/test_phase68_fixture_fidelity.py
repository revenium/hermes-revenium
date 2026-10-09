"""Phase 68 fixture fidelity: the opt-in `parent_session_id` helper.

D-17 makes `hermes-report.sh` attribute a resolved owner only with positive
evidence that a session is a root: its `sessions` row exists AND
`parent_session_id` IS NULL. Every production host measured carries that
column; `build_state_db` deliberately does not (139+ callers are the
column-absent arm). `seed_parent_session_ids` is the opt-in arm, sibling of
`seed_user_ids`.
"""
import os
import shutil
import sqlite3
import tempfile
import unittest

from tests._compat_helpers import build_state_db, seed_parent_session_ids


def _session(sid):
    return {
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
        'started_at': 1715514000.0,
        'ended_at': 1715514000.0,
        'billing_provider': 'anthropic',
    }


def _columns(db):
    conn = sqlite3.connect(db)
    try:
        return [r[1] for r in conn.execute('PRAGMA table_info(sessions)').fetchall()]
    finally:
        conn.close()


def _parent(db, sid):
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            'SELECT parent_session_id FROM sessions WHERE id = ?', (sid,)
        ).fetchone()
        return row
    finally:
        conn.close()


class ParentSessionIdHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='gsd-phase68-fixture-')
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.db = os.path.join(self.tmpdir, 'state.db')
        build_state_db(self.db, [_session('a'), _session('b')])

    def test_build_state_db_stays_column_absent(self):
        self.assertNotIn('parent_session_id', _columns(self.db))

    def test_seed_adds_column_and_sets_values(self):
        seed_parent_session_ids(self.db, {'a': None, 'b': 'a'})
        self.assertIn('parent_session_id', _columns(self.db))
        self.assertEqual(_parent(self.db, 'a'), (None,))
        self.assertEqual(_parent(self.db, 'b'), ('a',))

    def test_second_call_is_idempotent(self):
        seed_parent_session_ids(self.db, {'a': None})
        seed_parent_session_ids(self.db, {'b': 'a'})
        cols = _columns(self.db)
        self.assertEqual(cols.count('parent_session_id'), 1)
        self.assertEqual(_parent(self.db, 'a'), (None,))
        self.assertEqual(_parent(self.db, 'b'), ('a',))

    def test_unknown_session_id_is_ignored(self):
        seed_parent_session_ids(self.db, {'does-not-exist': None})
        self.assertIn('parent_session_id', _columns(self.db))
        self.assertIsNone(_parent(self.db, 'does-not-exist'))

    def test_fresh_build_state_db_is_still_column_absent(self):
        seed_parent_session_ids(self.db, {'a': None})
        other = os.path.join(self.tmpdir, 'other.db')
        build_state_db(other, [_session('a')])
        self.assertNotIn('parent_session_id', _columns(other))


if __name__ == '__main__':
    unittest.main()
