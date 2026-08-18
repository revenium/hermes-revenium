"""quick-260818-f1g -- per-axis assertions for drain-status.sh's staleness
route (STALE-01..06) and hermes-report.sh's per-session `legacyRetainedSids`
carve-out (STALE-07).

Thirty axes, thirty test methods, named exactly as the plan's axis register
("Named assertion" column). Each docstring states the axis ID and the
direction a regression must fail toward. `tests/mutation_verify_drain_staleness.py`
carries one mutation row per axis, each targeting the specific clause that
axis exists to defend.

`tests/test_phase32_drain_gate.py` is NOT modified by this module and its
continued passing is the regression proof that the pre-existing branches
(ended-past-settle, absent-from-state.db, the quiet-tick machinery) are
unchanged. AX-S15, AX-S16 and AX-S20 below assert verdict equality against
those same fixture SHAPES rebuilt locally here, rather than by editing that
file.

Two harness bases are used:
  - `DrainStalenessTestBase` -- drives `drain-status.sh` directly (AX-S01
    through AX-S23, AX-S26, AX-S27). Its own `_write_state_db` takes an
    explicit `with_activity_column` flag so one helper builds either of the
    two real schemas: WITH `last_activity_at` (a real Hermes state.db,
    `REAL` at ordinal 46) or WITHOUT it (every fixture in this repo's
    existing suite, and AX-S08's own scenario).
  - The consumer axes (AX-S24, S25, S28, S29, S30) reuse
    `HermesReportGuardTestBase` from `tests/test_phase32_drain_gate.py`
    (AX-S24 already required this) and, for AX-S30's takeover-branch
    assertion, `OwnershipTestBase` from `tests/test_session_ownership_record.py`
    -- the ownership machinery lives there and duplicating it here would
    drift.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from tests.test_phase32_drain_gate import HermesReportGuardTestBase, MUID, _OLD_TS as OLD_TS
from tests.test_session_ownership_record import OwnershipTestBase, SID

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / 'skills' / 'revenium' / 'scripts'

# Chosen so that with the DEFAULT REVENIUM_CRON_SETTLE_SECONDS (600), the
# floor (settle + 86400 = 87000) stays BELOW this value -- so setting
# REVENIUM_DRAIN_STALE_SECONDS to this constant makes the EFFECTIVE
# threshold equal to the CONFIGURED one, letting every axis reason about
# plain age offsets in seconds without waiting on a wall clock.
STALE_SECONDS = 100000.0


def _reject_json_constant(name):
    """Passed as json.loads(parse_constant=...) so NaN/Infinity/-Infinity —
    which json.loads otherwise accepts as a Python extension — raise instead
    of silently parsing. Without this the strict-JSON assertion would pass on
    a document no non-Python reader could load."""
    raise AssertionError(f'non-strict JSON constant in the status document: {name}')


def _ledger_line(sid, total_tokens, ts, muid=MUID):
    return f'HERMES:{sid}:{total_tokens}:{ts:.3f}:{muid}\n'


_TERMINAL_STALE_BLOCK = (
    'terminal = (\n'
    '                    stale_enabled\n'
    '                    and not refused\n'
    '                    and (now - last_seen) >= stale_seconds_effective\n'
    '                )'
)


def _extract_terminal_stale_expr():
    """Anti-drift extraction (mirrors test_mode_aware_legacy_takeover.py's
    `_extract_takeover_heredoc`): pull the REAL third-branch terminal
    expression out of drain-status.sh rather than hand-copying a
    reimplementation that could silently diverge from the shipped code.
    Returns the bare expression (the right-hand side of `terminal = `) as a
    string, ready for `eval()` against a controlled namespace."""
    text = (SCRIPTS_DIR / 'drain-status.sh').read_text()
    count = text.count(_TERMINAL_STALE_BLOCK)
    assert count == 1, (
        f'expected the terminal-computation block to appear exactly once in '
        f'drain-status.sh, found {count} -- extraction anchor likely drifted')
    # Strip the `terminal = ` prefix; re-wrap the inner lines in parens so
    # eval() can parse the multi-line expression regardless of indentation.
    inner = _TERMINAL_STALE_BLOCK[len('terminal = ('):-1]
    return '(' + inner + ')'


class DrainStalenessTestBase(unittest.TestCase):
    def _setup_tree(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-drain-staleness-')
        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        os.makedirs(state_dir, mode=0o700)
        return tmpdir, hermes_home, state_dir

    def _write_ledger(self, state_dir, lines):
        path = os.path.join(state_dir, 'revenium-hermes.ledger')
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        return path

    def _append_raw_ledger_line(self, state_dir, raw_line):
        """For AX-S11/S26/S27: append a LITERAL line, not necessarily a
        well-formed HERMES: record -- exercises the malformed-line paths."""
        path = os.path.join(state_dir, 'revenium-hermes.ledger')
        with open(path, 'a', encoding='utf-8') as f:
            f.write(raw_line if raw_line.endswith('\n') else raw_line + '\n')

    def _write_state_db(self, hermes_home, sessions, with_activity_column):
        """sessions: list of dicts with 'id', 'ended_at', and (only meaningful
        when with_activity_column=True) 'last_activity_at'. Builds ONE of the
        two real schemas: a real Hermes state.db declares `last_activity_at
        REAL` at ordinal 46; every pre-existing fixture in this repo lacks
        the column entirely (AX-S08's exact scenario)."""
        db_path = os.path.join(hermes_home, 'state.db')
        conn = sqlite3.connect(db_path)
        if with_activity_column:
            conn.execute('CREATE TABLE sessions (id TEXT, ended_at REAL, last_activity_at REAL)')
            for s in sessions:
                conn.execute(
                    'INSERT INTO sessions (id, ended_at, last_activity_at) VALUES (?, ?, ?)',
                    (s['id'], s.get('ended_at'), s.get('last_activity_at')),
                )
        else:
            conn.execute('CREATE TABLE sessions (id TEXT, ended_at REAL)')
            for s in sessions:
                conn.execute(
                    'INSERT INTO sessions (id, ended_at) VALUES (?, ?)',
                    (s['id'], s.get('ended_at')),
                )
        conn.commit()
        conn.close()
        return db_path

    def _write_corrupt_state_db(self, hermes_home):
        db_path = os.path.join(hermes_home, 'state.db')
        with open(db_path, 'wb') as f:
            f.write(b'not a real sqlite3 database file at all')
        return db_path

    def _run(self, hermes_home, state_dir, extra_env=None):
        env = {
            **os.environ,
            'HOME': hermes_home,
            'HERMES_HOME': hermes_home,
            'REVENIUM_STATE_DIR': state_dir,
            'PATH': os.environ.get('PATH', ''),
            'TZ': 'UTC',
        }
        if extra_env:
            env.update(extra_env)
        result = subprocess.run(
            ['bash', str(SCRIPTS_DIR / 'drain-status.sh'), '--json'],
            env=env, capture_output=True, text=True, timeout=30,
        )
        try:
            doc = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError) as exc:
            self.fail(
                f'drain-status.sh --json did not print valid JSON: {exc}\n'
                f'stdout={result.stdout!r} stderr={result.stderr!r}'
            )
        return result.returncode, doc, result.stdout, result.stderr

    def _run_n_times(self, hermes_home, state_dir, n, extra_env=None):
        rc = doc = out = err = None
        for _ in range(n):
            rc, doc, out, err = self._run(hermes_home, state_dir, extra_env=extra_env)
        return rc, doc, out, err


# ============================================================================
# AX-S01..S03 -- the threshold itself
# ============================================================================

class ThresholdBoundaryTests(DrainStalenessTestBase):
    def test_ax_s01_age_just_inside_threshold_blocks(self):
        """AX-S01. Fails toward: not drained. An age just under the
        threshold must never be judged stale."""
        now = time.time()
        tmp, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ax-s01-just-inside'
            ts = now - (STALE_SECONDS - 300)
            self._write_ledger(sd, [_ledger_line(sid, 100, ts)])
            self._write_state_db(hh, [{'id': sid, 'ended_at': None}], with_activity_column=False)
            extra_env = {'REVENIUM_DRAIN_STALE_SECONDS': str(STALE_SECONDS)}
            rc, doc, out, err = self._run(hh, sd, extra_env=extra_env)
            self.assertFalse(doc['pending'][0]['terminal'],
                              f'age just inside the threshold must NOT be stale: {doc!r}')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ax_s02_age_just_outside_threshold_drains(self):
        """AX-S02. Fails toward: drained (the new route). An age just past
        the threshold must reach a drained verdict via staleness."""
        now = time.time()
        tmp, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ax-s02-just-outside'
            ts = now - (STALE_SECONDS + 300)
            self._write_ledger(sd, [_ledger_line(sid, 100, ts)])
            self._write_state_db(hh, [{'id': sid, 'ended_at': None}], with_activity_column=False)
            extra_env = {'REVENIUM_DRAIN_STALE_SECONDS': str(STALE_SECONDS),
                         'REVENIUM_DRAIN_QUIET_TICKS': '1'}
            rc, doc, out, err = self._run_n_times(hh, sd, 2, extra_env=extra_env)
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertTrue(doc['drained'],
                             f'age just outside the threshold must drain via the new route: {doc!r}')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ax_s03_age_exactly_at_threshold_is_stale(self):
        """AX-S03. Fails toward: pins `>=`. A subprocess round-trip CANNOT
        pin `>=` against `>` here: real wall-clock time only advances
        between this test's `time.time()` capture and the script's OWN
        `time.time()` call, so an "exactly at the threshold" fixture is
        ALWAYS observed as very slightly past it by execution time --
        which a `>` mutation would also satisfy (empirically confirmed
        while building this test: a `>=` -> `>` mutation against a
        subprocess-timed fixture passed unnoticed).

        Extracts the REAL terminal-computation expression verbatim from
        drain-status.sh (the same anti-drift technique
        test_mode_aware_legacy_takeover.py already uses for its takeover
        heredoc) and evaluates it in-process with fully controlled
        operands, so `now - last_seen` can be made EXACTLY equal to
        `stale_seconds_effective` with no timing race at all."""
        expr = _extract_terminal_stale_expr()
        namespace = {
            'stale_enabled': True,
            'refused': False,
            'now': 1_000_000.0,
            'last_seen': 1_000_000.0 - STALE_SECONDS,
            'stale_seconds_effective': STALE_SECONDS,
        }
        self.assertTrue(eval(expr, {}, namespace),
                         f'age exactly at the threshold must be stale (pins >=, not >): {expr!r}')


# ============================================================================
# AX-S04..S06 -- resume / activity composition
# ============================================================================

class NonFiniteThresholdTests(DrainStalenessTestBase):
    """AX-S31 (found by review of PR #57). `float()` accepts 'nan' and 'inf',
    and the ValueError path does not catch either.

    Both are silently corrosive rather than unsafe: 'inf' means no finite age
    ever exceeds the threshold, and every comparison against 'nan' is False,
    so in both cases the staleness route can never grant terminal -- the exact
    deadlock this feature exists to remove, reintroduced by a typo and with no
    diagnosis. 'nan' additionally serialises as the bare token `NaN`, a Python
    extension to JSON that a stricter reader than ours would reject.

    A non-finite value is INVALID (falls back to the default), not a disable
    request: disabling has its own explicit spelling (`<= 0`), and honouring a
    malformed value as 'off' would hide the misconfiguration rather than
    survive it."""

    def _probe(self, raw):
        tmpdir, hh, sd = self._setup_tree()
        try:
            sid = 'sess-nonfinite'
            old_ts = time.time() - (10 * 86400)
            self._write_ledger(sd, [_ledger_line(sid, 100, old_ts)])
            # No activity column: the population the carve-out protects.
            self._write_state_db(hh, [{'id': sid, 'ended_at': None}], False)
            _rc, doc, _out, _err = self._run(hh, sd, extra_env={
                'REVENIUM_DRAIN_STALE_SECONDS': raw})
            return doc
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_ax_s31_nan_falls_back_to_the_default_and_is_flagged(self):
        doc = self._probe('nan')
        self.assertTrue(doc['staleEnabled'],
                        'nan must not silently disable the route')
        self.assertEqual(doc['staleSecondsConfigured'], 604800.0,
                         'nan must fall back to the default, not propagate')
        self.assertTrue(doc['staleSecondsInvalid'],
                        'the misconfiguration must be DIAGNOSABLE in the document')

    def test_ax_s31_positive_infinity_falls_back_and_is_flagged(self):
        doc = self._probe('inf')
        self.assertEqual(doc['staleSecondsConfigured'], 604800.0)
        self.assertTrue(doc['staleSecondsInvalid'])
        self.assertTrue(doc['staleEnabled'])

    def test_ax_s31_negative_infinity_falls_back_rather_than_reading_as_disable(self):
        """-inf is `<= 0` arithmetically, so without the finite check it would
        be read as an explicit disable request. It is a malformed value, not a
        deliberate opt-out, and must be reported as such."""
        doc = self._probe('-inf')
        self.assertEqual(doc['staleSecondsConfigured'], 604800.0)
        self.assertTrue(doc['staleSecondsInvalid'])
        self.assertTrue(doc['staleEnabled'],
                        '-inf must NOT be honoured as the <= 0 opt-out')

    def test_ax_s31_the_document_is_strict_json_under_nan(self):
        """`json.loads` accepts `NaN` as a Python extension, so our own reader
        would not have caught this. Assert the serialised bytes are valid
        STRICT JSON, which is what a non-Python consumer would require."""
        tmpdir, hh, sd = self._setup_tree()
        try:
            sid = 'sess-nonfinite-strict'
            old_ts = time.time() - (10 * 86400)
            self._write_ledger(sd, [_ledger_line(sid, 100, old_ts)])
            self._write_state_db(hh, [{'id': sid, 'ended_at': None}], False)
            self._run(hh, sd, extra_env={'REVENIUM_DRAIN_STALE_SECONDS': 'nan'})
            raw = open(os.path.join(sd, 'drain-status.json')).read()
            self.assertNotIn('NaN', raw,
                             'the bare token NaN is not valid JSON for a strict reader')
            json.loads(raw, parse_constant=_reject_json_constant)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_ax_s31_explicit_zero_still_disables(self):
        """The opt-out must survive the new validation — a regression here
        would remove the documented escape hatch."""
        doc = self._probe('0')
        self.assertFalse(doc['staleEnabled'])
        self.assertFalse(doc['staleSecondsInvalid'],
                         '0 is a deliberate opt-out, NOT a misconfiguration')


class ResumeAndActivityCompositionTests(DrainStalenessTestBase):
    def test_ax_s04_resume_via_activity_withdraws_drained_verdict(self):
        """AX-S04. Fails toward: not drained. Interleaves two states: the
        run that produced a drained verdict, and the run after
        `last_activity_at` moves to now. Asserts the FIRST state actually
        reached drained before testing the withdrawal."""
        now = time.time()
        tmp, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ax-s04-resume-activity'
            old_ts = now - (STALE_SECONDS + 300)
            self._write_ledger(sd, [_ledger_line(sid, 100, old_ts)])
            self._write_state_db(
                hh, [{'id': sid, 'ended_at': None, 'last_activity_at': None}],
                with_activity_column=True)
            extra_env = {'REVENIUM_DRAIN_STALE_SECONDS': str(STALE_SECONDS),
                         'REVENIUM_DRAIN_QUIET_TICKS': '1'}

            rc, doc, out, err = self._run_n_times(hh, sd, 2, extra_env=extra_env)
            self.assertEqual(rc, 0,
                              f'fixture: must reach drained before testing the resume; '
                              f'stdout={out!r} stderr={err!r}')
            self.assertTrue(doc['drained'])

            conn = sqlite3.connect(os.path.join(hh, 'state.db'))
            conn.execute('UPDATE sessions SET last_activity_at=? WHERE id=?', (now, sid))
            conn.commit()
            conn.close()

            rc, doc, out, err = self._run(hh, sd, extra_env=extra_env)
            self.assertFalse(doc['drained'],
                              'a fresh activity signal must withdraw the drained verdict '
                              'on the very next run')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ax_s05_resume_via_ledger_line_withdraws_drained_verdict(self):
        """AX-S05. Fails toward: not drained. Same two-state interleaving as
        AX-S04, but the resume signal is a fresh HERMES: ledger line rather
        than activity."""
        now = time.time()
        tmp, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ax-s05-resume-ledger'
            old_ts = now - (STALE_SECONDS + 300)
            self._write_ledger(sd, [_ledger_line(sid, 100, old_ts)])
            self._write_state_db(hh, [{'id': sid, 'ended_at': None}], with_activity_column=False)
            extra_env = {'REVENIUM_DRAIN_STALE_SECONDS': str(STALE_SECONDS),
                         'REVENIUM_DRAIN_QUIET_TICKS': '1'}

            rc, doc, out, err = self._run_n_times(hh, sd, 2, extra_env=extra_env)
            self.assertEqual(rc, 0,
                              f'fixture: must reach drained before testing the resume; '
                              f'stdout={out!r} stderr={err!r}')
            self.assertTrue(doc['drained'])

            self._write_ledger(sd, [
                _ledger_line(sid, 100, old_ts),
                _ledger_line(sid, 150, now),
            ])
            rc, doc, out, err = self._run(hh, sd, extra_env=extra_env)
            self.assertFalse(doc['drained'],
                              'a fresh ledger line must withdraw the drained verdict on '
                              'the very next run')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ax_s06_recent_activity_blocks_despite_ancient_ledger(self):
        """AX-S06. Fails toward: not drained. `last_seen` is the MAX of the
        two terms -- a recent activity value must block staleness even
        when the ledger term alone would be stale."""
        now = time.time()
        tmp, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ax-s06-recent-activity'
            ancient_ts = now - (STALE_SECONDS + 300)
            self._write_ledger(sd, [_ledger_line(sid, 100, ancient_ts)])
            self._write_state_db(
                hh, [{'id': sid, 'ended_at': None, 'last_activity_at': now - 50}],
                with_activity_column=True)
            extra_env = {'REVENIUM_DRAIN_STALE_SECONDS': str(STALE_SECONDS)}
            rc, doc, out, err = self._run(hh, sd, extra_env=extra_env)
            self.assertFalse(doc['pending'][0]['terminal'],
                              f'a recent activity signal must block staleness despite an '
                              f'ancient ledger line: {doc!r}')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ============================================================================
# AX-S07..S10 -- the activity term's edge shapes
# ============================================================================

class ActivityTermEdgeShapeTests(DrainStalenessTestBase):
    def test_ax_s07_null_activity_falls_back_to_ledger_counted_and_retained(self):
        """AX-S07. Fails toward: drained + counted + RETAINED. A NULL
        `last_activity_at` falls back to the ledger term for the verdict,
        and (STALE-07) lands the sid on `legacyRetainedSids` since there is
        no corroborating signal."""
        now = time.time()
        tmp, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ax-s07-null-activity'
            ts = now - (STALE_SECONDS + 300)
            self._write_ledger(sd, [_ledger_line(sid, 100, ts)])
            self._write_state_db(
                hh, [{'id': sid, 'ended_at': None, 'last_activity_at': None}],
                with_activity_column=True)
            extra_env = {'REVENIUM_DRAIN_STALE_SECONDS': str(STALE_SECONDS),
                         'REVENIUM_DRAIN_QUIET_TICKS': '1'}
            rc, doc, out, err = self._run_n_times(hh, sd, 2, extra_env=extra_env)
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertTrue(doc['drained'], 'a NULL activity value must fall back to the ledger term')
            self.assertGreaterEqual(doc.get('staleWithoutActivitySignal', 0), 1)
            self.assertIn(sid, doc.get('legacyRetainedSids', []),
                          'a session drained on ledger evidence alone must be retained for legacy')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ax_s08_missing_activity_column_does_not_break_the_gate(self):
        """AX-S08. Fails toward: ledger-only. Every pre-existing fixture in
        this repo's suite lacks `last_activity_at` entirely -- the gate must
        keep working, ledger-only, exactly as before."""
        now = time.time()
        tmp, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ax-s08-no-column'
            ts = now - (STALE_SECONDS + 300)
            self._write_ledger(sd, [_ledger_line(sid, 100, ts)])
            self._write_state_db(hh, [{'id': sid, 'ended_at': None}], with_activity_column=False)
            extra_env = {'REVENIUM_DRAIN_STALE_SECONDS': str(STALE_SECONDS),
                         'REVENIUM_DRAIN_QUIET_TICKS': '1'}
            rc, doc, out, err = self._run_n_times(hh, sd, 2, extra_env=extra_env)
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertTrue(doc['drained'])
            self.assertFalse(doc.get('activityColumnPresent'))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ax_s09_unparseable_activity_refuses_staleness_for_that_session(self):
        """AX-S09. Fails toward: not drained. A present-but-unparseable
        activity value must REFUSE staleness for that session, never crash
        and never silently fall back."""
        now = time.time()
        tmp, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ax-s09-unparseable-activity'
            ts = now - (STALE_SECONDS + 300)
            self._write_ledger(sd, [_ledger_line(sid, 100, ts)])
            self._write_state_db(
                hh, [{'id': sid, 'ended_at': None, 'last_activity_at': 'not-a-number'}],
                with_activity_column=True)
            extra_env = {'REVENIUM_DRAIN_STALE_SECONDS': str(STALE_SECONDS)}
            rc, doc, out, err = self._run(hh, sd, extra_env=extra_env)
            self.assertFalse(doc['pending'][0]['terminal'],
                              f'an unparseable activity value must refuse staleness: {doc!r}')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ax_s10_future_dated_timestamp_is_never_stale(self):
        """AX-S10. Fails toward: not drained. Clock skew / a future-dated
        ledger timestamp yields a NEGATIVE age and must never be stale,
        with no special-casing (e.g. an `abs()` or a zero-floor) in the
        implementation. The offset is chosen comfortably larger than the
        settle-window floor (settle(600, default)+86400=87000) so an
        `abs()`-shaped mutation -- which would treat the negative age as
        if it were an equally large POSITIVE one -- is distinguishable
        from the correct signed comparison."""
        now = time.time()
        tmp, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ax-s10-future'
            future_ts = now + 200000
            self._write_ledger(sd, [_ledger_line(sid, 100, future_ts)])
            self._write_state_db(hh, [{'id': sid, 'ended_at': None}], with_activity_column=False)
            extra_env = {'REVENIUM_DRAIN_STALE_SECONDS': '1'}
            rc, doc, out, err = self._run(hh, sd, extra_env=extra_env)
            self.assertFalse(doc['pending'][0]['terminal'],
                              f'a future-dated timestamp must never be stale: {doc!r}')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ============================================================================
# AX-S11..S13, S26, S27 -- ledger corruption and unreadable sources
# ============================================================================

class LedgerCorruptionAndUnreadableSourceTests(DrainStalenessTestBase):
    def test_ax_s11_unparsed_ledger_lines_are_counted_not_silent(self):
        """AX-S11. Fails toward: counted. Every malformed line -- whether or
        not a sid is recoverable from it -- must increment
        `ledgerUnparsedLines`, never be silently dropped."""
        tmp, hh, sd = self._setup_tree()
        try:
            self._append_raw_ledger_line(sd, 'HERMES:short')
            self._append_raw_ledger_line(sd, 'not a hermes line at all')
            rc, doc, out, err = self._run(hh, sd)
            self.assertGreaterEqual(doc.get('ledgerUnparsedLines', 0), 2,
                                     f'both malformed lines must be counted: {doc!r}')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ax_s12_unreadable_ledger_still_exits_1_and_staleness_unreachable(self):
        """AX-S12. Fails toward: exit 1. An unreadable (not merely missing)
        ledger is the same "cannot determine" shape as an unreadable
        state.db -- never assume drained on doubt, and staleness is
        unreachable on this path."""
        tmp, hh, sd = self._setup_tree()
        try:
            ledger_path = os.path.join(sd, 'revenium-hermes.ledger')
            os.makedirs(ledger_path)  # a directory where a file is expected
            rc, doc, out, err = self._run(hh, sd)
            self.assertEqual(rc, 1, f'stdout={out!r} stderr={err!r}')
            self.assertFalse(doc['drained'])
            self.assertFalse(doc['determined'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ax_s13_unreadable_state_db_still_exits_1_and_staleness_unreachable(self):
        """AX-S13. Fails toward: exit 1. An unreadable state.db leaves
        openness (and therefore staleness) indeterminate. Deliberately an
        EMPTY ledger: with any ledger line present, `tracked` stays
        non-empty and the SEPARATE ended_at-query guard (section 2) also
        independently fails closed on the same corrupt file, making a
        mutation of the open_sids guard (section 1) alone unobservable. An
        empty ledger makes section 1 the SOLE decisive guard, since section
        2 is unreachable when `tracked` is empty."""
        tmp, hh, sd = self._setup_tree()
        try:
            self._write_corrupt_state_db(hh)
            rc, doc, out, err = self._run(hh, sd)
            self.assertEqual(rc, 1, f'stdout={out!r} stderr={err!r}')
            self.assertFalse(doc['drained'])
            self.assertFalse(doc['determined'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ax_s26_unparseable_ts_on_an_attributable_line_refuses_staleness_for_that_sid(self):
        """AX-S26 (route 1a). Fails toward: not stale, that sid only. A
        HERMES: line whose sid splits cleanly but whose ts does not parse
        refuses staleness for exactly that sid, even though the SAME sid's
        other ledger line is old enough to otherwise be stale."""
        now = time.time()
        tmp, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ax-s26-attributable-corrupt'
            old_ts = now - (STALE_SECONDS + 300)
            self._write_ledger(sd, [_ledger_line(sid, 100, old_ts)])
            self._append_raw_ledger_line(sd, f'HERMES:{sid}:100:not-a-number:{MUID}')
            self._write_state_db(hh, [{'id': sid, 'ended_at': None}], with_activity_column=False)
            extra_env = {'REVENIUM_DRAIN_STALE_SECONDS': str(STALE_SECONDS)}
            rc, doc, out, err = self._run(hh, sd, extra_env=extra_env)
            self.assertFalse(doc['pending'][0]['terminal'],
                              f'an attributable ledger-ts parse failure must refuse '
                              f'staleness for that sid: {doc!r}')
            self.assertGreaterEqual(doc.get('ledgerUnparsedLines', 0), 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ax_s27_unattributable_corruption_retains_every_stale_session_without_closing_the_gate(self):
        """AX-S27 (route 1b). Fails toward: drained AND all-retained -- BOTH
        halves in one run. An unrelated unattributable garbage line must
        WIDEN the carve-out to every staleness-granted sid (even one with a
        corroborating activity value, which AX-S07 alone would NOT retain)
        and must NEVER close the gate."""
        now = time.time()
        tmp, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ax-s27-widened-by-corruption'
            old_ts = now - (STALE_SECONDS + 300)
            self._write_ledger(sd, [_ledger_line(sid, 100, old_ts)])
            self._append_raw_ledger_line(sd, 'HERMES:onlyonefield')
            self._write_state_db(
                hh, [{'id': sid, 'ended_at': None, 'last_activity_at': old_ts}],
                with_activity_column=True)
            extra_env = {'REVENIUM_DRAIN_STALE_SECONDS': str(STALE_SECONDS),
                         'REVENIUM_DRAIN_QUIET_TICKS': '1'}
            rc, doc, out, err = self._run_n_times(hh, sd, 2, extra_env=extra_env)
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertTrue(doc['drained'], 'unattributable corruption must never close the gate')
            self.assertIn(sid, doc.get('legacyRetainedSids', []),
                          'corruption must widen the carve-out to every staleness-granted '
                          'sid, even one with a corroborating activity value')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ============================================================================
# AX-S14..S18 -- precedence, unchanged branches, and quiet-tick composition
# ============================================================================

class PrecedenceAndUnchangedBranchTests(DrainStalenessTestBase):
    def test_ax_s14_stale_but_recently_ended_still_blocked_by_settle_window(self):
        """AX-S14. Fails toward: not drained. Staleness must NEVER override
        the settle window -- a session that ended recently is governed
        exclusively by the second branch, regardless of how ancient its
        ledger line is."""
        now = time.time()
        tmp, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ax-s14-ended-recently'
            old_ts = now - (STALE_SECONDS + 300)
            self._write_ledger(sd, [_ledger_line(sid, 100, old_ts)])
            self._write_state_db(hh, [{'id': sid, 'ended_at': now - 10}], with_activity_column=False)
            extra_env = {'REVENIUM_DRAIN_STALE_SECONDS': str(STALE_SECONDS)}
            rc, doc, out, err = self._run(hh, sd, extra_env=extra_env)
            self.assertEqual(rc, 10, f'stdout={out!r} stderr={err!r}')
            self.assertFalse(doc['drained'])
            self.assertFalse(doc['pending'][0]['terminal'],
                              'staleness must never override the settle window')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ax_s15_ended_past_settle_branch_verdict_unchanged(self):
        """AX-S15. Fails toward: unchanged. Replicates
        EnoughQuietChecksDrainedTests' shape locally -- the ended-branch
        verdict must be byte-identical to pre-change."""
        now = time.time()
        tmp, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ax-s15-ended-past-settle'
            self._write_ledger(sd, [_ledger_line(sid, 1500, now)])
            self._write_state_db(hh, [{'id': sid, 'ended_at': now - 3600}], with_activity_column=False)
            extra_env = {'REVENIUM_CRON_SETTLE_SECONDS': '60', 'REVENIUM_DRAIN_QUIET_TICKS': '3'}
            rc, doc, out, err = self._run_n_times(hh, sd, 4, extra_env=extra_env)
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertTrue(doc['drained'])
            self.assertEqual(doc['drainedCount'], 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ax_s16_absent_from_state_db_branch_verdict_unchanged(self):
        """AX-S16. Fails toward: unchanged. Replicates AbsentFromStateDbTests'
        shape locally -- the absent-from-db branch is untouched by this
        change."""
        now = time.time()
        tmp, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ax-s16-absent'
            self._write_ledger(sd, [_ledger_line(sid, 1500, now)])
            self._write_state_db(
                hh, [{'id': 'some-other-session', 'ended_at': now - 10}],
                with_activity_column=False)
            extra_env = {'REVENIUM_DRAIN_QUIET_TICKS': '2'}
            rc, doc, out, err = self._run_n_times(hh, sd, 3, extra_env=extra_env)
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertTrue(doc['drained'])
            self.assertEqual(doc['drainedCount'], 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ax_s17_open_session_absent_from_ledger_is_not_tracked(self):
        """AX-S17. Fails toward: not tracked. `tracked` is keyed on the
        ledger; a session legacy has never billed is not legacy's
        responsibility, so it is not tracked in the first place -- unchanged
        by this plan."""
        tmp, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ax-s17-no-ledger-row'
            self._write_state_db(hh, [{'id': sid, 'ended_at': None}], with_activity_column=False)
            rc, doc, out, err = self._run(hh, sd)
            self.assertEqual(doc['ledgerSessionsTracked'], 0)
            self.assertNotIn(sid, doc['quietTicks'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ax_s18_stale_session_still_requires_quiet_ticks(self):
        """AX-S18. Fails toward: not drained. Staleness grants `terminal`,
        never `drained` directly -- the quiet-tick requirement composes
        exactly as it does for every other terminal route."""
        now = time.time()
        tmp, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ax-s18-quiet-ticks'
            old_ts = now - (STALE_SECONDS + 300)
            self._write_ledger(sd, [_ledger_line(sid, 100, old_ts)])
            self._write_state_db(hh, [{'id': sid, 'ended_at': None}], with_activity_column=False)
            extra_env = {'REVENIUM_DRAIN_STALE_SECONDS': str(STALE_SECONDS),
                         'REVENIUM_DRAIN_QUIET_TICKS': '3'}
            rc, doc, out, err = self._run(hh, sd, extra_env=extra_env)
            self.assertEqual(rc, 10, f'stdout={out!r} stderr={err!r}')
            self.assertFalse(doc['drained'], 'staleness alone must not grant drained')
            self.assertTrue(doc['pending'][0]['terminal'])
            self.assertLess(doc['quietTicks'][sid], 3)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ============================================================================
# AX-S19..S23 -- the tunable's own behaviour and status-document shape
# ============================================================================

class TunableAndDocumentShapeTests(DrainStalenessTestBase):
    def test_ax_s19_configured_threshold_is_floored_above_the_settle_window(self):
        """AX-S19. Fails toward: not drained. Asserts the EFFECTIVE seconds
        via the status document itself, plus a verdict at an age between
        the configured value and the floor -- not the arithmetic."""
        now = time.time()
        tmp, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ax-s19-floored'
            old_ts = now - 500  # > configured(100), far below the floor(87000)
            self._write_ledger(sd, [_ledger_line(sid, 100, old_ts)])
            self._write_state_db(hh, [{'id': sid, 'ended_at': None}], with_activity_column=False)
            extra_env = {'REVENIUM_DRAIN_STALE_SECONDS': '100'}
            rc, doc, out, err = self._run(hh, sd, extra_env=extra_env)
            self.assertEqual(doc.get('staleSecondsEffective'), 87000.0,
                              f'effective threshold must be floored at settle+86400: {doc!r}')
            self.assertFalse(doc['pending'][0]['terminal'],
                              'age exceeds the configured value but is far below the floor '
                              '-- must NOT be stale')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ax_s20_zero_threshold_restores_pre_change_behaviour(self):
        """AX-S20. Fails toward: not drained. `REVENIUM_DRAIN_STALE_SECONDS
        <= 0` must reproduce the pre-change verdict exactly -- an open
        session is NEVER terminal, no matter how ancient its ledger line."""
        now = time.time()
        tmp, hh, sd = self._setup_tree()
        try:
            sid = 'sess-ax-s20-opt-out'
            old_ts = now - (10 * 86400)
            self._write_ledger(sd, [_ledger_line(sid, 1500, old_ts)])
            self._write_state_db(hh, [{'id': sid, 'ended_at': None}], with_activity_column=False)
            extra_env = {'REVENIUM_DRAIN_STALE_SECONDS': '0', 'REVENIUM_MARKER_RETENTION_DAYS': '1'}
            rc, doc, out, err = self._run(hh, sd, extra_env=extra_env)
            self.assertEqual(rc, 10, f'stdout={out!r} stderr={err!r}')
            self.assertFalse(doc.get('staleEnabled'))
            self.assertFalse(doc['pending'][0]['terminal'],
                              'the opt-out must restore the pre-change behaviour exactly')
            self.assertEqual(doc['ledgerSessionsTracked'], 1,
                              'still force-included past retention -- unrelated to staleness')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ax_s21_two_profiles_have_independent_stale_verdicts(self):
        """AX-S21. Fails toward: independent. Two independent axes of
        "independence": (1) two SEPARATE trees (profiles/processes) must
        never leak state into each other -- run BOTH and assert both
        verdicts; (2) TWO SIDS WITHIN THE SAME RUN must each be judged from
        their OWN ledger/activity data, not from a value hoisted out of the
        per-session loop (e.g. a `max()` taken across every tracked sid
        instead of the current one) -- both halves asserted, so a mutation
        collapsing either is visible."""
        now = time.time()
        tmp_a, hh_a, sd_a = self._setup_tree()
        tmp_b, hh_b, sd_b = self._setup_tree()
        try:
            sid_a = 'sess-ax-s21-profile-a-stale'
            sid_a2 = 'sess-ax-s21-profile-a-fresh'
            sid_b = 'sess-ax-s21-profile-b'
            # Tree A: TWO sids in the SAME run -- one ancient, one fresh.
            self._write_ledger(sd_a, [
                _ledger_line(sid_a, 100, now - (STALE_SECONDS + 300)),
                _ledger_line(sid_a2, 100, now - 50),
            ])
            self._write_state_db(
                hh_a, [{'id': sid_a, 'ended_at': None}, {'id': sid_a2, 'ended_at': None}],
                with_activity_column=False)
            # Tree B: a wholly separate process/state tree, fresh only.
            self._write_ledger(sd_b, [_ledger_line(sid_b, 100, now - 50)])
            self._write_state_db(hh_b, [{'id': sid_b, 'ended_at': None}], with_activity_column=False)

            extra_env = {'REVENIUM_DRAIN_STALE_SECONDS': str(STALE_SECONDS)}
            rc_a, doc_a, out_a, err_a = self._run(hh_a, sd_a, extra_env=extra_env)
            rc_b, doc_b, out_b, err_b = self._run(hh_b, sd_b, extra_env=extra_env)

            pending_a_by_sid = {p['sid']: p for p in doc_a['pending']}
            self.assertTrue(pending_a_by_sid[sid_a]['terminal'],
                             f'sid_a must be judged stale on its OWN data: {doc_a!r}')
            self.assertFalse(pending_a_by_sid[sid_a2]['terminal'],
                              f'sid_a2, in the SAME run, must not inherit sid_a\'s '
                              f'staleness: {doc_a!r}')
            self.assertFalse(doc_b['pending'][0]['terminal'],
                              f'tree B must NOT leak tree A\'s staleness: {doc_b!r}')
        finally:
            shutil.rmtree(tmp_a, ignore_errors=True)
            shutil.rmtree(tmp_b, ignore_errors=True)

    def test_ax_s22_pending_cap_still_caps_at_50_and_carries_stale_key(self):
        """AX-S22. Fails toward: capped. The PENDING_CAP=50 preview path
        must stay capped, and every pending entry must now carry the new
        `stale` boolean."""
        now = time.time()
        tmp, hh, sd = self._setup_tree()
        try:
            lines = [_ledger_line(f'sess-ax-s22-{i:03d}', 100, now) for i in range(55)]
            self._write_ledger(sd, lines)
            rc, doc, out, err = self._run(hh, sd)
            self.assertEqual(len(doc['pending']), 50, f'PENDING_CAP=50 must still cap: {doc!r}')
            self.assertTrue(all('stale' in p for p in doc['pending']),
                             'every pending entry must carry the new stale key')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ax_s23_status_document_keeps_every_preexisting_key(self):
        """AX-S23. Fails toward: additive. Every key `_finish` wrote before
        this change must still be present."""
        tmp, hh, sd = self._setup_tree()
        try:
            rc, doc, out, err = self._run(hh, sd)
            old_keys = {
                'lastChecked', 'ledgerSessionsTracked', 'drainedCount', 'pendingCount',
                'pending', 'quietTicks', 'sessionLastSeenTs', 'drained', 'determined',
            }
            missing = old_keys - set(doc.keys())
            self.assertEqual(missing, set(), f'pre-existing keys must never be removed: {doc!r}')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ============================================================================
# AX-S24 -- the consumer, end to end, driven by a REAL drain-status.sh-
# produced document (the one axis that is NOT hand-crafted JSON)
# ============================================================================

class ConsumerEndToEndTests(HermesReportGuardTestBase):
    def _run_drain_status(self, extra_env=None):
        env = {
            **os.environ,
            'HOME': self.shim_home,
            'HERMES_HOME': self.hermes_home,
            'REVENIUM_STATE_DIR': self.state_dir,
            'PATH': os.environ.get('PATH', ''),
            'TZ': 'UTC',
        }
        if extra_env:
            env.update(extra_env)
        result = subprocess.run(
            ['bash', str(SCRIPTS_DIR / 'drain-status.sh'), '--json'],
            env=env, capture_output=True, text=True, timeout=30,
        )
        try:
            doc = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError) as exc:
            self.fail(f'drain-status.sh --json did not print valid JSON: {exc}\n'
                      f'stdout={result.stdout!r} stderr={result.stderr!r}')
        return result.returncode, doc

    def _seed_open_session_with_activity(self, sid, last_activity_at=None,
                                          input_tokens=100, output_tokens=50):
        conn = sqlite3.connect(self.state_db)
        conn.execute(
            'CREATE TABLE IF NOT EXISTS sessions ('
            'id TEXT, model TEXT, source TEXT, '
            'input_tokens INTEGER, output_tokens INTEGER, '
            'cache_read_tokens INTEGER, cache_write_tokens INTEGER, '
            'reasoning_tokens INTEGER, estimated_cost_usd TEXT, '
            'api_call_count INTEGER, started_at REAL, ended_at REAL, '
            'billing_provider TEXT, last_activity_at REAL)'
        )
        conn.execute(
            'INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (sid, 'claude-sonnet-4-6', 'test', input_tokens, output_tokens, 0, 0, 0, '0', 1,
             OLD_TS, None, 'anthropic', last_activity_at),
        )
        conn.commit()
        conn.close()

    def _write_legacy_ledger_line(self, sid, total_tokens, ts):
        path = os.path.join(self.state_dir, 'revenium-hermes.ledger')
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f'HERMES:{sid}:{total_tokens}:{ts:.3f}:{MUID}\n')

    def test_ax_s24_hermes_report_honours_then_refuses_a_staleness_verdict(self):
        """AX-S24. Fails toward: refuse. Drives hermes-report.sh with
        REVENIUM_LEGACY_COMPLETIONS=disabled against a staleness-PRODUCED
        status document (via a real drain-status.sh run): first drained
        (completions skipped), then with the verdict withdrawn (completions
        metered, exactly one warning) -- proving the consumer honours the
        new route on both sides."""
        sid = 'sess-ax-s24-consumer-e2e'
        now = time.time()
        old_ts = now - (STALE_SECONDS + 300)
        self._seed_open_session_with_activity(sid, last_activity_at=old_ts)
        self._write_legacy_ledger_line(sid, 100, old_ts)

        drain_env = {'REVENIUM_DRAIN_STALE_SECONDS': str(STALE_SECONDS),
                     'REVENIUM_DRAIN_QUIET_TICKS': '1'}
        self._run_drain_status(extra_env=drain_env)
        rc, doc = self._run_drain_status(extra_env=drain_env)
        self.assertEqual(rc, 0, f'fixture: the gate must actually be drained before '
                                 f'testing the consumer: {doc!r}')
        self.assertTrue(doc['drained'])
        self.assertNotIn(sid, doc.get('legacyRetainedSids', []),
                          'fixture: this sid has a corroborating activity value and must '
                          'NOT be retained, or the "skip" half below is untestable')

        # 1. Drained + not retained -> completions SKIPPED.
        self._run(extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})
        self.assertEqual(self._completions(), [],
                          'a genuinely-drained, non-retained sid must be skipped')

        # 2. Resume: last_activity_at moves to now -> the verdict withdraws.
        conn = sqlite3.connect(self.state_db)
        conn.execute('UPDATE sessions SET last_activity_at=? WHERE id=?', (now, sid))
        conn.commit()
        conn.close()
        rc, doc = self._run_drain_status(extra_env=drain_env)
        self.assertFalse(doc['drained'], 'a fresh activity signal must withdraw the verdict')

        # 3. Not drained -> hermes-report.sh REFUSES the disable; completions
        # keep metering (real growth: state.db total=150, ledger's last
        # recorded total=100).
        self._run(extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})
        completions = self._completions()
        self.assertEqual(len(completions), 1,
                          f'a withdrawn verdict must resume metering: {completions!r}')
        warn_lines = [l for l in self._log_text().splitlines()
                      if 'refusing to disable' in l or 'NOT drained' in l]
        self.assertEqual(len(warn_lines), 1,
                          f'expected exactly one refusal warning: {warn_lines!r}')


# ============================================================================
# AX-S25, S28, S29 -- the consumer's INTERPRETATION of legacyRetainedSids,
# driven by hand-crafted status documents (these pin the consumer's own
# logic, not the producer's document generation)
# ============================================================================

class ConsumerCarveOutInterpretationTests(HermesReportGuardTestBase):
    def _write_legacy_ledger_line(self, sid, total_tokens, ts):
        path = os.path.join(self.state_dir, 'revenium-hermes.ledger')
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f'HERMES:{sid}:{total_tokens}:{ts:.3f}:{MUID}\n')

    def _write_drain_status_with_retained(self, drained, pending_count=0, retained=None):
        path = os.path.join(self.state_dir, 'drain-status.json')
        doc = {'drained': drained, 'pendingCount': pending_count,
               'legacyRetainedSids': list(retained or [])}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(doc, f)
        return path

    @staticmethod
    def _billed_sids(completions):
        billed = set()
        for argv in completions:
            for i, tok in enumerate(argv):
                if tok == '--transaction-id' and i + 1 < len(argv):
                    billed.add(argv[i + 1])
        return billed

    def test_ax_s25_ledger_only_stale_session_is_retained_while_the_gate_reports_drained(self):
        """AX-S25 -- the axis this revision exists to close. Fails toward:
        retained (legacy keeps metering). MUST be a two-session assertion in
        ONE run: session A named on legacyRetainedSids, session B not, both
        with real growth, both under REVENIUM_LEGACY_COMPLETIONS=disabled.
        A single-session version would pass under a mutation that flips
        suppression globally in either direction -- exactly the defect
        being closed."""
        from tests._compat_helpers import build_state_db

        sid_a = 'sess-ax-s25-retained'
        sid_b = 'sess-ax-s25-not-retained'
        row = {
            'model': 'claude-sonnet-4-6', 'source': 'test',
            'input_tokens': 100, 'output_tokens': 50, 'cache_read': 0, 'cache_write': 0,
            'reasoning': 0, 'estimated_cost': '0', 'api_calls': 1,
            'started_at': OLD_TS, 'ended_at': OLD_TS, 'billing_provider': 'anthropic',
        }
        build_state_db(self.state_db, [
            {'id': sid_a, **row},
            {'id': sid_b, **row},
        ])
        self._write_legacy_ledger_line(sid_a, 100, OLD_TS)
        self._write_legacy_ledger_line(sid_b, 100, OLD_TS)
        self._write_drain_status_with_retained(drained=True, pending_count=0, retained=[sid_a])

        self._run(extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})
        billed = self._billed_sids(self._completions())

        self.assertTrue(any(tid.startswith(sid_a + '-') for tid in billed),
                         f'sid A is on legacyRetainedSids -- legacy must keep metering it: {billed!r}')
        self.assertFalse(any(tid.startswith(sid_b + '-') for tid in billed),
                          f'sid B is NOT retained -- legacy must suppress it: {billed!r}')

    def test_ax_s28_absent_retained_list_reproduces_todays_global_suppression(self):
        """AX-S28. Fails toward: suppress all (back-compat). A status
        document with NO legacyRetainedSids key at all must suppress every
        session exactly as before this change -- catches a "retain on
        doubt" mutation that would silently disable the cutover."""
        sid = 'sess-ax-s28-no-retained-key'
        self._seed_session(sid)
        self._write_legacy_ledger_line(sid, 100, OLD_TS)
        self._write_drain_status(drained=True, pending_count=0)  # no legacyRetainedSids key

        self._run(extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})
        self.assertEqual(self._completions(), [],
                          'a document with no legacyRetainedSids key must suppress every '
                          'session exactly as before this change')

    def test_ax_s29_a_session_not_on_the_retained_list_is_still_suppressed(self):
        """AX-S29. Fails toward: suppressed (wave 7 unblocked). A sid
        absent from legacyRetainedSids -- including a brand-new session
        that has never appeared in the legacy ledger at all -- must still
        be suppressed. Catches a "retain unless proven drained" mutation
        that would re-block the event path's takeover of new sessions."""
        sid = 'sess-ax-s29-brand-new-never-ledgered'
        self._seed_session(sid)
        # Deliberately NO ledger line at all for this sid.
        self._write_drain_status_with_retained(drained=True, pending_count=0, retained=[])

        self._run(extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})
        self.assertEqual(self._completions(), [],
                          'a sid absent from legacyRetainedSids must still be suppressed, '
                          'even one that has never appeared in the legacy ledger')


# ============================================================================
# AX-S30 -- the takeover branch resolves per-session, not off the
# fleet-global boolean
# ============================================================================

def _write_drain_status_with_retained_for_ownership(state_dir, drained, pending_count=0, retained=None):
    path = os.path.join(state_dir, 'drain-status.json')
    doc = {'drained': drained, 'pendingCount': pending_count,
           'legacyRetainedSids': list(retained or [])}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(doc, f)
    return path


class TakeoverPerSessionSuppressionTests(OwnershipTestBase):
    def test_ax_s30_takeover_branch_uses_the_per_session_suppression_not_the_global_boolean(self):
        """AX-S30. Fails toward: takeover permitted for a retained sid. The
        takeover branch (hermes-report.sh's single ownership-resolution
        site) must resolve suppression PER SESSION -- a sid on
        legacyRetainedSids must be allowed to take over even while the
        fleet-global LEGACY_COMPLETIONS_SKIP boolean is true, because
        legacy is still emitting for THIS session."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event')
            _write_drain_status_with_retained_for_ownership(
                t['state_dir'], drained=True, pending_count=0, retained=[SID])

            rc, out = self._run_legacy(t, extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})
            self.assertEqual(rc, 0, out)

            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'legacy',
                              'SID is on legacyRetainedSids -- the takeover must fire even '
                              'though LEGACY_COMPLETIONS_SKIP is globally true')
            self.assertEqual(baseline, '150',
                              'the recorded floor must equal the session cumulative total '
                              '(100 input + 50 output) at the takeover instant')
        finally:
            self._teardown_tree(t)


if __name__ == '__main__':
    unittest.main()
