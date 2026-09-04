"""T-59-27 / T-59-28 (code review WR-01): the read-only sqlite URI must
survive a URI-significant character in a profile directory name.

Phase 59's option-b profile-home scan feeds a directory name ENUMERATED from
the filesystem -- `profiles_dir.iterdir()`, never validated -- into the
`file:...?mode=ro` URI both resolvers open their databases through. Raw
interpolation made that name part of the URI's syntax: a '#' truncates at the
fragment and discards `?mode=ro` along with it, so sqlite falls back to its
default READ-WRITE mode and CREATES the truncated path when absent. That is a
write, and this repo's standing invariant is that the skill never writes to
state.db (CLAUDE.md, "No writes to state.db").

These tests pin the encoding at the seam rather than the symptom, and assert
the two implementations stay in lockstep -- divergence between classifier.py
and resolve-markers-dir.py is the cross-profile hazard this repo has paid for
once already.
"""
import importlib.util
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
CLASSIFIER = SKILL / 'plugins' / 'revenium-classifier' / 'classifier.py'
SIDECAR = SKILL / 'scripts' / 'resolve-markers-dir.py'

# Names that are legal on POSIX but significant in a URI. '#' is the one that
# silently discards the query string; the others are pinned so a future
# "simplification" of the escaping cannot quietly narrow it to '#' alone.
HOSTILE_NAMES = ['pro#file', 'pro?file', 'pro%file', 'pro file', 'pro#a?b%c']


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RoUriEncodingTests(unittest.TestCase):
    """The URI keeps mode=ro no matter what the directory name contains."""

    def setUp(self):
        self.sidecar = _load(SIDECAR, 'rmd_under_test')

    def test_mode_ro_survives_every_hostile_name(self):
        for name in HOSTILE_NAMES:
            with self.subTest(name=name):
                uri = self.sidecar._ro_uri(f'/tmp/{name}/state.db')
                self.assertEqual(
                    urlsplit(uri).query, 'mode=ro',
                    f'{name!r} destroyed the query string: {uri!r} -- sqlite '
                    f'would open this READ-WRITE',
                )
                self.assertEqual(
                    urlsplit(uri).fragment, '',
                    f'{name!r} produced a URI fragment: {uri!r}',
                )

    def test_read_write_open_is_refused_and_creates_nothing(self):
        """The invariant that actually matters: no write, and no stray file."""
        for name in HOSTILE_NAMES:
            with self.subTest(name=name):
                tmp = tempfile.mkdtemp(prefix='gsd-p59-rouri-')
                os.makedirs(os.path.join(tmp, name))
                db = os.path.join(tmp, name, 'state.db')
                uri = self.sidecar._ro_uri(db)
                with self.assertRaises(
                    sqlite3.OperationalError,
                    msg=f'{name!r}: a write was permitted through {uri!r}',
                ):
                    conn = sqlite3.connect(uri, uri=True)
                    conn.execute('CREATE TABLE t (x)')
                    conn.commit()
                # Nothing may appear at the truncated path either.
                truncated = os.path.join(tmp, name.split('#')[0])
                if truncated != os.path.join(tmp, name):
                    self.assertFalse(
                        os.path.exists(truncated),
                        f'{name!r} created a stray file at {truncated!r}',
                    )

    def test_ordinary_path_round_trips_unchanged(self):
        """Fail-open: the common case must not regress into an unopenable URI."""
        uri = self.sidecar._ro_uri('/home/u/.hermes/profiles/gtm/state.db')
        self.assertEqual(
            uri, 'file:/home/u/.hermes/profiles/gtm/state.db?mode=ro',
            'an ordinary path must be byte-identical to the pre-fix URI',
        )

    def test_separators_are_not_escaped(self):
        """safe='/' is load-bearing -- an escaped separator resolves nowhere."""
        self.assertNotIn('%2F', self.sidecar._ro_uri('/a/b/c.db'))


class RoUriParityTests(unittest.TestCase):
    """Both implementations must encode identically. Divergence here is the
    cross-profile hazard, not a style difference."""

    def test_both_modules_agree_on_every_name(self):
        classifier = _load(CLASSIFIER, 'classifier_under_test')
        sidecar = _load(SIDECAR, 'rmd_parity')
        for name in HOSTILE_NAMES + ['plain']:
            with self.subTest(name=name):
                path = f'/home/u/.hermes/profiles/{name}/state.db'
                self.assertEqual(
                    classifier._ro_uri(path), sidecar._ro_uri(path),
                    f'{name!r}: classifier.py and resolve-markers-dir.py '
                    f'disagree on the read-only URI',
                )


class NoRawInterpolationRemainsTests(unittest.TestCase):
    """The seam, not the symptom: no file: URI may be built by raw f-string
    interpolation in either module, including at the fixed-STATE_DB sites --
    those are the ones a future caller would route a profile path through."""

    def test_no_raw_file_uri_interpolation(self):
        for path in (CLASSIFIER, SIDECAR):
            with self.subTest(path=path.name):
                src = path.read_text(encoding='utf-8')
                code = '\n'.join(
                    ln for ln in src.split('\n')
                    if 'sqlite3.connect' in ln or 'uri = ' in ln
                )
                self.assertNotIn(
                    'f"file:', code,
                    f'{path.name} still builds a file: URI by raw '
                    f'interpolation -- route it through _ro_uri()',
                )


if __name__ == '__main__':
    unittest.main()
