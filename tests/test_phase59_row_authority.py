"""PR #122 P1: a found row is authoritative even when its value is NULL.

`b610232` restored the pre-Phase-59 `agent:<profile>:` id-namespace shape as a
fallback beneath option-b's row lookup. The fallback was correct in intent and
wrong in reach: `_row_lookup()` returned a bare `None` for four different
outcomes -- no row anywhere, a row whose `profile_name` is NULL, empty, or a
default slot -- so the fallback could not tell them apart and fired on all four.

For a legacy-shaped id like `agent:gtm:...` whose OWN row says
`profile_name IS NULL`, that handed the session to `gtm` when its stored row
said otherwise. D-18 fixes `sessions.profile_name` as the only source and makes
a NULL keep today's process-level fail-open, so this both broke a locked
decision and put the wrong profile on the billing path.

These tests pin the distinction the bare `None` erased. They drive the real
resolvers against real fixture databases -- not a reimplementation -- and they
assert BOTH directions, because a fix that simply disabled the fallback would
pass the first test and silently undo `b610232`.
"""
import importlib.util
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
CLASSIFIER = SKILL / 'plugins' / 'revenium-classifier' / 'classifier.py'
SIDECAR = SKILL / 'scripts' / 'resolve-markers-dir.py'

NAMESPACED_SID = 'agent:gtm:sess-p1-row-authority'


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_db(path, rows):
    """`rows` is a list of (id, profile_name). An empty list still creates the
    table -- 'table exists, row absent' must stay distinct from 'no table'."""
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE sessions (id TEXT PRIMARY KEY, profile_name TEXT)')
    conn.executemany('INSERT INTO sessions (id, profile_name) VALUES (?, ?)', rows)
    conn.commit()
    conn.close()


class RowAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gsd-p59-row-authority-')
        self.addCleanup(__import__('shutil').rmtree, self.tmp, ignore_errors=True)
        self.hermes = os.path.join(self.tmp, '.hermes')
        os.makedirs(self.hermes)
        self.db = os.path.join(self.hermes, 'state.db')

    def _resolve_both(self, sid):
        """Both implementations, same fixture. They must not diverge."""
        env = dict(os.environ, HERMES_HOME=self.hermes)
        old = os.environ.get('HERMES_HOME')
        os.environ['HERMES_HOME'] = self.hermes
        try:
            c = _load(CLASSIFIER, 'cls_row_auth')
            s = _load(SIDECAR, 'sc_row_auth')
            return c._profile_name_for_session(sid), s._profile_name_for_session(sid)
        finally:
            if old is None:
                os.environ.pop('HERMES_HOME', None)
            else:
                os.environ['HERMES_HOME'] = old

    def test_found_row_with_null_profile_beats_the_namespaced_identifier(self):
        """THE regression. The row exists and says NULL; the id says `gtm`.
        The row wins, and resolution falls open to process level (None)."""
        _build_db(self.db, [(NAMESPACED_SID, None)])
        got_c, got_s = self._resolve_both(NAMESPACED_SID)
        for name, got in (('classifier.py', got_c), ('resolve-markers-dir.py', got_s)):
            self.assertIsNone(
                got,
                f'{name}: a row exists for this session and authoritatively says '
                f'NULL, but the id-namespace fallback overruled it and returned '
                f'{got!r}. D-18 makes the row the only source and a NULL keeps '
                f'process-level fail-open -- the wrong profile would report this '
                f'session, on the billing path.',
            )

    def test_found_row_with_default_slot_also_beats_the_identifier(self):
        """Same rule for the default slots, which `_row_lookup` also
        collapsed into the bare None."""
        for slot in ('main', 'default', ''):
            with self.subTest(slot=slot):
                db = os.path.join(self.tmp, f'slot-{slot or "empty"}.db')
                hermes = os.path.join(self.tmp, f'h-{slot or "empty"}')
                os.makedirs(hermes, exist_ok=True)
                target = os.path.join(hermes, 'state.db')
                _build_db(target, [(NAMESPACED_SID, slot)])
                old = os.environ.get('HERMES_HOME')
                os.environ['HERMES_HOME'] = hermes
                try:
                    c = _load(CLASSIFIER, f'cls_slot_{slot or "e"}')
                    self.assertIsNone(
                        c._profile_name_for_session(NAMESPACED_SID),
                        f'a row saying {slot!r} is still a found row and must '
                        f'not be overruled by the identifier',
                    )
                finally:
                    if old is None:
                        os.environ.pop('HERMES_HOME', None)
                    else:
                        os.environ['HERMES_HOME'] = old

    def test_no_row_anywhere_still_falls_back_to_the_identifier(self):
        """The other direction, and the reason this is not just 'delete the
        fallback'. With NO row for this session in any database, b610232's
        fallback must still fire -- that is what closed CR-01's
        every-profile-owns-it double-ship."""
        _build_db(self.db, [('some-other-session', 'coder')])
        got_c, got_s = self._resolve_both(NAMESPACED_SID)
        for name, got in (('classifier.py', got_c), ('resolve-markers-dir.py', got_s)):
            self.assertEqual(
                got, 'gtm',
                f'{name}: no row exists for this session anywhere, so the '
                f'id-namespace fallback must still resolve it to gtm -- '
                f'disabling the fallback would silently undo b610232 and '
                f'reopen the CR-01 cross-profile double-ship',
            )

    def test_both_implementations_agree_on_every_arm(self):
        """Divergence between the two resolvers IS the cross-profile hazard."""
        cases = [
            ([(NAMESPACED_SID, None)], None),
            ([(NAMESPACED_SID, 'main')], None),
            ([('unrelated', 'coder')], 'gtm'),
            ([(NAMESPACED_SID, 'marketing')], 'marketing'),
        ]
        for i, (rows, expected) in enumerate(cases):
            with self.subTest(case=i):
                hermes = os.path.join(self.tmp, f'agree-{i}')
                os.makedirs(hermes, exist_ok=True)
                _build_db(os.path.join(hermes, 'state.db'), rows)
                old = os.environ.get('HERMES_HOME')
                os.environ['HERMES_HOME'] = hermes
                try:
                    c = _load(CLASSIFIER, f'cls_agree_{i}')
                    s = _load(SIDECAR, f'sc_agree_{i}')
                    gc, gs = (c._profile_name_for_session(NAMESPACED_SID),
                              s._profile_name_for_session(NAMESPACED_SID))
                finally:
                    if old is None:
                        os.environ.pop('HERMES_HOME', None)
                    else:
                        os.environ['HERMES_HOME'] = old
                self.assertEqual(gc, gs, f'case {i}: the two resolvers disagree')
                self.assertEqual(gc, expected, f'case {i}: expected {expected!r}')


if __name__ == '__main__':
    unittest.main()
