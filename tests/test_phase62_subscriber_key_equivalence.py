"""Phase 62 Plan 02 Task 2 (SUB-05/07/08, D-01/D-02): the equivalence gate
between the bash subscriber-key resolver (`resolve_subscriber_id` in
common.sh, Phase 61) and its second implementation, the Python
`resolve_subscriber_key` function api-event-report.sh's per-session map
heredoc carries (Phase 62 D-01) -- a deliberate duplication, not a shared
sourced helper, following the same precedent CLAUDE.md documents for
classifier.py: "the duplication is deliberate; the plugin must stay
importable without the skill's shell environment", extended here from
"importable without bash" to "no subshell fork per event record" (the cost
argument api-event-report.sh's own comments make about resolver spawns).

Following tests/test_root_sid_batch_equivalence.py's shape (its own
docstring's framing, borrowed verbatim): the gate here is equivalence, not
correctness-in-isolation -- every case in this module runs BOTH
implementations over the SAME inputs and asserts they agree. Two
implementations of one permanent wire format that silently disagree do not
make anything faster or safer; they silently re-attribute billing rows that
can never be amended.

Harness shape, differing from test_root_sid_batch_equivalence.py in one
way that must be stated here: that module's "batch" implementation is a
Python function, importable in-process via importlib. `resolve_subscriber_id`
is a bash SHELL FUNCTION and is not importable, so the bash side here is
driven as a subprocess through the same `bash -c` sourcing idiom
tests.test_phase61_identity_resolution.ResolveSubscriberIdUnitTests._call
uses. The Python side is sliced out of api-event-report.sh between the two
`SUBSCRIBER_KEY_BUILDER_START`/`_END` comment sentinels Task 1 added and
executed in a fresh namespace -- slicing the SHIPPED source is the point: a
test that re-implements the Python side proves only that the test agrees
with itself, which is the fixture-fidelity defect class this repo has hit
five times (CLAUDE.md, "Fixture fidelity defect").

Two loud failures, not skips, guard this module against silently stopping
to guard anything: if either sentinel goes missing from
api-event-report.sh, or the slice does not exec, or it does not define
`resolve_subscriber_key`, the affected test FAILS by name rather than
skipping -- a test that skips when its subject moves is a test that
stopped guarding (Phase 61 made this mistake and paid for it, per
62-CONTEXT.md D-13's note on test_boundary_files_unmodified_relative_to_merge_base).

Every assertion below is on ABSENCE, never an enumerated set of guessed bad
outputs: for a refused input, the assertion is "the Python key is empty AND
the bash status is not ok" -- never "the output does not equal this
specific fabricated string I guessed" (Phase 61 shipped exactly that
mistake once, per this module's docstring precedent).

MISSES, recorded here rather than only in SUMMARY.md: this proves the two
implementations agree on the KEY, not that either is semantically correct
-- Phase 61 owns "is this the right actor". It does not prove the bash
resolver is never called on the event path, or the Python builder never on
the completion path -- only that it would not matter if either were, since
both produce the identical key for identical inputs. It says nothing about
what Revenium does with the key once shipped.
"""
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
SCRIPTS_DIR = SKILL / 'scripts'
COMMON_SH = SCRIPTS_DIR / 'common.sh'
API_EVENT_REPORT_SH = SCRIPTS_DIR / 'api-event-report.sh'

_START_SENTINEL = '# === SUBSCRIBER_KEY_BUILDER_START'
_END_SENTINEL = '# === SUBSCRIBER_KEY_BUILDER_END ==='


def _load_shipped_python_builder():
    """Slice the REAL `resolve_subscriber_key` definition out of
    api-event-report.sh between its two fixed comment sentinels, and exec
    it in a fresh namespace. FAILS LOUDLY (never skips) if the sentinels or
    the callable are missing, per this module's docstring."""
    text = API_EVENT_REPORT_SH.read_text(encoding='utf-8')

    start_idx = text.find(_START_SENTINEL)
    if start_idx == -1:
        raise AssertionError(
            f'{API_EVENT_REPORT_SH.name} is missing the {_START_SENTINEL!r} '
            f'sentinel -- the equivalence gate cannot locate the shipped '
            f'Python subscriber-key builder to slice and exec. This is a '
            f'FAILURE, not a skip: a test that stops guarding when its '
            f'subject moves is worse than no test at all.'
        )
    end_idx = text.find(_END_SENTINEL, start_idx)
    if end_idx == -1:
        raise AssertionError(
            f'{API_EVENT_REPORT_SH.name} has the {_START_SENTINEL!r} '
            f'sentinel but not a matching {_END_SENTINEL!r} after it -- '
            f'the equivalence gate cannot find the end of the slice.'
        )
    end_of_line = text.find('\n', end_idx)
    if end_of_line == -1:
        end_of_line = len(text)
    slice_text = text[start_idx:end_of_line]

    namespace = {}
    try:
        exec(
            compile(
                slice_text,
                f'<sliced resolve_subscriber_key from {API_EVENT_REPORT_SH.name}>',
                'exec',
            ),
            namespace,
        )
    except Exception as exc:  # pragma: no cover - loud failure path
        raise AssertionError(
            f'the sliced Python between the sentinels in '
            f'{API_EVENT_REPORT_SH.name} failed to exec: {exc!r}\n'
            f'--- sliced text ---\n{slice_text}'
        ) from exc

    fn = namespace.get('resolve_subscriber_key')
    if fn is None:
        raise AssertionError(
            f'the sliced Python between the sentinels in '
            f'{API_EVENT_REPORT_SH.name} does not define '
            f'resolve_subscriber_key -- the equivalence gate has nothing '
            f'to compare against.\n--- sliced text ---\n{slice_text}'
        )
    return fn


class SubscriberKeyEquivalenceTests(unittest.TestCase):
    """Every corpus row runs BOTH implementations and asserts they agree.

    The bash side returns (status, key) where status is one of
    ok/none/rejected (resolve_subscriber_id's own three outcomes); the
    Python side returns a bare key (empty string covering both bash's
    "none" and "rejected"). Agreement is defined as: bash status == 'ok'
    implies python_key == bash_key; bash status != 'ok' implies
    python_key == ''.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gsd-phase62-equiv-')
        self.hermes_home = os.path.join(self.tmp, 'hh')
        self.python_resolve = _load_shipped_python_builder()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _bash_status_and_key(self, source, user_id):
        quoted = ' '.join(shlex.quote(a) for a in (source, user_id))
        expr = f'resolve_subscriber_id {quoted}'
        # LC_ALL=C pins bash's [:space:] character class to plain ASCII.
        # DISCOVERED while writing this module: under en_US.UTF-8 (this
        # dev host's default locale), bash's [:space:] ALSO matches NBSP
        # (measured directly: a leading "\xc2\xa0" IS stripped by
        # resolve_subscriber_id's own trim under that locale) even though
        # 62-CONTEXT.md's D-12 states "bash's [:space:] trim does not"
        # strip it -- that claim holds only in a C/POSIX locale, not every
        # locale glibc ships. cron (the actual production caller,
        # install-cron.sh's crontab line) sets no LANG/LC_ALL and inherits
        # cron's minimal environment, which defaults to C/POSIX on this
        # class of host -- so C is the locale resolve_subscriber_id
        # actually runs under in production, and pinning it here makes
        # this test deterministic across dev/CI hosts with different
        # default locales rather than silently depending on whichever
        # locale happens to be active when the suite runs. \x1f is
        # unaffected either way (confirmed: never matched by [:space:] in
        # C or en_US.UTF-8).
        env = {**os.environ, 'HERMES_HOME': self.hermes_home, 'LC_ALL': 'C', 'LANG': 'C'}
        r = subprocess.run(
            ['bash', '-c', f'source "{COMMON_SH}" >/dev/null 2>&1; {expr}'],
            env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        # rstrip('\n') ONLY, never a bare .strip(): Python's default
        # strip() treats trailing NBSP as whitespace and would silently
        # eat it off the captured value -- this test's OWN harness would
        # then reproduce the exact trap this module exists to catch,
        # discovered while writing it (the trailing-NBSP corpus row failed
        # against this harness bug, not against the shipped code, until
        # this was narrowed to rstrip('\n')).
        out = r.stdout.rstrip('\n')
        status, _, key = out.partition('|')
        return status, key

    def _corpus(self):
        """(description, source, user_id) rows. Each comment names the
        branch this row targets -- the enumeration a second implementation
        is most likely to get wrong."""
        rows = [
            # --- ordinary resolvable shapes ---
            ('ordinary slack-shaped id', 'slack', 'U02C12JG78F'),
            ('email-shaped id', 'email', 'jane@acme.example'),
            ('source never seen before, no allowlist (D-06)', 'some_source_never_seen_before', 'U1'),
            ('system bot id, no shape special-casing (D-12)', 'slack', 'USLACKBOT'),

            # --- empty arms ---
            ('empty actor id', 'cron', ''),
            ('whitespace-only actor id', 'slack', '   '),
            ('empty source', '', 'U1'),
            ('whitespace-only source', '   ', 'U1'),

            # --- both fixed unsafe sentinel literals, each argument position ---
            ('unsafe user_id sentinel literal', 'slack', '__revenium_unsafe_user_id__'),
            ('unsafe source sentinel literal', '__revenium_unsafe_source__', 'U1'),

            # --- the five unsafe characters, in the user_id arm ---
            ('pipe in user_id', 'slack', 'U|600'),
            ('tab in user_id', 'slack', 'U9\t01'),
            ('carriage return in user_id', 'slack', 'U9\r01'),
            ('newline in user_id', 'slack', 'U9\n01'),
            ('unit separator in user_id (D-12)', 'slack', 'U9\x1f01'),

            # --- the same five unsafe characters, in the source arm ---
            ('pipe in source', 'sla|ck', 'U1'),
            ('tab in source', 'sla\tck', 'U1'),
            ('carriage return in source', 'sla\rck', 'U1'),
            ('newline in source', 'sla\nck', 'U1'),
            ('unit separator in source (D-12)', 'sla\x1fck', 'U1'),

            # --- colon in the namespace format's own separator position ---
            ('namespace itself contains a colon', 'ns:with:colon', 'U1'),
            ('actor id contains a colon', 'slack', 'U1:extra'),

            # --- whitespace-class traps: VT, FF, NBSP, leading/trailing/interior ---
            ('vertical tab leading in user_id', 'slack', '\x0bU1'),
            ('vertical tab trailing in user_id', 'slack', 'U1\x0b'),
            ('vertical tab interior in user_id', 'slack', 'U1\x0bx'),
            ('form feed leading in user_id', 'slack', '\x0cU1'),
            ('form feed trailing in user_id', 'slack', 'U1\x0c'),
            ('form feed interior in user_id', 'slack', 'U1\x0cx'),
            # NBSP (U+00A0): bash's [:space:] class does NOT include it, so
            # correct behaviour KEEPS it as part of the value on both
            # sides. Python's default str.strip() DOES treat NBSP as
            # whitespace (confirmed: '\xa0'.isspace() is True) and would
            # silently strip it here -- this is the specific row that
            # closes the loop on the whitespace trap (see the class
            # docstring and 62-02-SUMMARY.md's trim-loosening experiment):
            # reverting resolve_subscriber_key's explicit six-character
            # trim to Python's default .strip() makes THIS row disagree
            # (bash keeps the leading NBSP; a naively-stripped Python would
            # not), and no other row in this corpus depends on that
            # distinction.
            ('non-breaking space leading in user_id (THE trim trap)', 'slack', '\xa0U1'),
            ('non-breaking space trailing in user_id', 'slack', 'U1\xa0'),
            ('non-breaking space interior in user_id', 'slack', 'U1\xa0x'),
        ]
        return rows

    def test_corpus_is_non_empty_and_covers_every_named_branch(self):
        """Guards this whole module against vacuity: a future edit that
        deletes corpus rows must fail a COUNT assertion, not silently
        shrink the gate."""
        rows = self._corpus()
        self.assertTrue(rows, 'the corpus must not be empty')
        self.assertEqual(
            len(rows), 31,
            'the corpus row count changed -- if a row was deliberately '
            'added or removed, update this expected count deliberately; '
            'this assertion exists so a future edit cannot silently '
            'shrink the gate',
        )
        descriptions = [d for d, _, _ in rows]
        self.assertEqual(
            len(descriptions), len(set(descriptions)),
            'duplicate corpus row descriptions -- each row should target '
            'a distinct branch',
        )

    def test_bash_and_python_agree_across_the_full_corpus(self):
        for description, source, user_id in self._corpus():
            with self.subTest(description=description, source=repr(source), user_id=repr(user_id)):
                status, bash_key = self._bash_status_and_key(source, user_id)
                python_key = self.python_resolve(source, user_id)

                if status == 'ok':
                    self.assertEqual(
                        python_key, bash_key,
                        f'[{description}] bash resolved ok|{bash_key!r} but '
                        f'the Python builder returned {python_key!r} for '
                        f'source={source!r} user_id={user_id!r}',
                    )
                    self.assertNotEqual(
                        python_key, '',
                        f'[{description}] bash resolved a non-empty key but '
                        f'the Python builder returned an empty string',
                    )
                else:
                    # Assert on ABSENCE only: the bash status is not ok,
                    # therefore the Python key must be empty. Never assert
                    # against a specific guessed bad string.
                    self.assertEqual(
                        python_key, '',
                        f'[{description}] bash refused (status={status!r}) '
                        f'but the Python builder returned a NON-EMPTY key '
                        f'{python_key!r} for source={source!r} '
                        f'user_id={user_id!r} -- a refused input must never '
                        f'produce a plausible-looking key',
                    )

    def test_missing_start_sentinel_fails_loudly(self):
        """Proves the loud-failure contract itself: a script missing the
        start sentinel must raise, not skip or silently pass."""
        with tempfile.TemporaryDirectory(prefix='gsd-phase62-sentinel-') as tmp:
            fake = Path(tmp, 'api-event-report.sh')
            fake.write_text('#!/usr/bin/env bash\necho no sentinels here\n')
            import tests.test_phase62_subscriber_key_equivalence as _mod
            original = _mod.API_EVENT_REPORT_SH
            _mod.API_EVENT_REPORT_SH = fake
            try:
                with self.assertRaises(AssertionError) as ctx:
                    _load_shipped_python_builder()
                self.assertIn('SUBSCRIBER_KEY_BUILDER_START', str(ctx.exception))
            finally:
                _mod.API_EVENT_REPORT_SH = original

    def test_missing_end_sentinel_fails_loudly(self):
        with tempfile.TemporaryDirectory(prefix='gsd-phase62-sentinel-') as tmp:
            fake = Path(tmp, 'api-event-report.sh')
            fake.write_text(
                '#!/usr/bin/env bash\n'
                f'{_START_SENTINEL} ===\n'
                'echo no matching end\n'
            )
            import tests.test_phase62_subscriber_key_equivalence as _mod
            original = _mod.API_EVENT_REPORT_SH
            _mod.API_EVENT_REPORT_SH = fake
            try:
                with self.assertRaises(AssertionError) as ctx:
                    _load_shipped_python_builder()
                self.assertIn('SUBSCRIBER_KEY_BUILDER_END', str(ctx.exception))
            finally:
                _mod.API_EVENT_REPORT_SH = original

    def test_slice_not_defining_the_callable_fails_loudly(self):
        with tempfile.TemporaryDirectory(prefix='gsd-phase62-sentinel-') as tmp:
            fake = Path(tmp, 'api-event-report.sh')
            fake.write_text(
                '#!/usr/bin/env bash\n'
                f'{_START_SENTINEL} ===\n'
                '# def resolve_subscriber_key is missing on purpose\n'
                f'{_END_SENTINEL}\n'
            )
            import tests.test_phase62_subscriber_key_equivalence as _mod
            original = _mod.API_EVENT_REPORT_SH
            _mod.API_EVENT_REPORT_SH = fake
            try:
                with self.assertRaises(AssertionError) as ctx:
                    _load_shipped_python_builder()
                self.assertIn('does not define', str(ctx.exception))
            finally:
                _mod.API_EVENT_REPORT_SH = original


if __name__ == '__main__':
    unittest.main()
