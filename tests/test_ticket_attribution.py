"""Ticket attribution (`--ticket-id`, revenium CLI 1.5.0).

`resolve_session_ticket` (common.sh) maps a Hermes session to the Hermes Kanban
ticket it ran under, so metered spend can be attributed to a ticket.

Two properties carry the weight here, and both are about what the resolver
REFUSES to do:

  1. **Exact keys only.** `task_runs.metadata ->> '$.worker_session_id'`, then
     `tasks.session_id`. A (profile, time-window) correlation between a run and
     a session also exists and is deliberately not used — a guessed ticket on a
     billing row is worse than an absent one. `test_never_matches_by_time_window`
     pins that: a run overlapping the session perfectly, carrying NO exact key,
     must still resolve to nothing.

  2. **Silence on every failure.** Enrichment must never cost a completion its
     metering, so a missing board pointer, a hostile board name, an absent DB,
     malformed JSON, or an older board schema all resolve to "" and the caller
     omits the flag.

The board DB fixtures here are built with the column set the REAL boards carry
(read off a live fleet host), not a minimal invention — `SidecarFixtureFidelityTests`
exists because fixtures that pin what the test produces rather than what
production emits have been got wrong repeatedly in this repo.
"""

import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON_SH = ROOT / 'skills' / 'revenium' / 'scripts' / 'common.sh'

# The real `tasks` / `task_runs` column sets, as observed on a live fleet board
# (`~/.hermes/kanban/boards/<board>/kanban.db`). Trimmed to the columns this
# resolver can see, but every name and order below is production's.
TASKS_DDL = (
    "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT, "
    "created_at INTEGER, session_id TEXT, current_run_id INTEGER)"
)
TASK_RUNS_DDL = (
    "CREATE TABLE task_runs (id INTEGER PRIMARY KEY, task_id TEXT, profile TEXT, "
    "status TEXT, started_at INTEGER, ended_at INTEGER, outcome TEXT, "
    "summary TEXT, metadata TEXT, error TEXT)"
)


def _build_board(root: Path, board: str = 'coder-tfo', *, runs=(), tasks=(),
                 current: str = None, schema: str = 'full') -> Path:
    """Create <root>/kanban/{current,boards/<board>/kanban.db}. Returns root."""
    kanban = root / 'kanban'
    bdir = kanban / 'boards' / board
    bdir.mkdir(parents=True, exist_ok=True)
    (kanban / 'current').write_text(
        (board if current is None else current) + "\n", encoding='utf-8')

    conn = sqlite3.connect(bdir / 'kanban.db')
    try:
        conn.execute(TASKS_DDL)
        if schema == 'full':
            conn.execute(TASK_RUNS_DDL)
        for tid, title, status, sid in tasks:
            conn.execute(
                "INSERT INTO tasks (id, title, status, created_at, session_id) "
                "VALUES (?,?,?,?,?)", (tid, title, status, 1789000000, sid))
        if schema == 'full':
            for rid, task_id, meta, started, ended in runs:
                conn.execute(
                    "INSERT INTO task_runs (id, task_id, profile, status, "
                    "started_at, ended_at, metadata) VALUES (?,?,?,?,?,?,?)",
                    (rid, task_id, 'coder', 'done', started, ended, meta))
        conn.commit()
    finally:
        conn.close()
    return root


def _resolve(hermes_home: Path, sid: str) -> str:
    """Call resolve_session_ticket with HERMES_HOME pointed at a fixture tree."""
    script = (
        'set -uo pipefail\n'
        'source "%s" >/dev/null 2>&1\n'
        'resolve_session_ticket "$1"\n' % COMMON_SH
    )
    proc = subprocess.run(
        ['bash', '-c', script, 'bash', sid],
        capture_output=True, text=True,
        env={'HERMES_HOME': str(hermes_home), 'PATH': '/usr/bin:/bin',
             'HOME': str(hermes_home)},
    )
    # The contract is "never blocks": a non-zero exit would abort a metering
    # tick under `set -e`, so assert it as part of every case.
    assert proc.returncode == 0, (proc.returncode, proc.stderr[:400])
    return proc.stdout.strip()


class TicketResolutionTests(unittest.TestCase):
    """The two exact keys, and only those."""

    def test_resolves_via_worker_session_id(self):
        with tempfile.TemporaryDirectory() as td:
            home = _build_board(
                Path(td),
                runs=[(77, 't_b520f031', json.dumps(
                    {"artifacts": ["/x/pr.md"],
                     "worker_session_id": "20260901_143705_75d6f9"}),
                    1788000000, 1788000400)],
                tasks=[('t_b520f031', 'ops thing', 'blocked', None)],
            )
            self.assertEqual(
                _resolve(home, '20260901_143705_75d6f9'), 't_b520f031')

    def test_resolves_via_tasks_session_id_when_no_run_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            home = _build_board(
                Path(td),
                runs=[(1, 't_other', None, 1788000000, 1788000400)],
                tasks=[('t_4fa6336e', 'landing', 'blocked',
                        '20260912_081941_fdd2b3')],
            )
            self.assertEqual(
                _resolve(home, '20260912_081941_fdd2b3'), 't_4fa6336e')

    def test_worker_session_id_wins_over_tasks_session_id(self):
        """Run metadata is stamped by the worker itself, so it is the more
        authoritative of the two keys and is consulted first."""
        with tempfile.TemporaryDirectory() as td:
            home = _build_board(
                Path(td),
                runs=[(5, 't_from_run', json.dumps(
                    {"worker_session_id": "sid_both"}), 1788000000, 1788000400)],
                tasks=[('t_from_task', 'x', 'done', 'sid_both')],
            )
            self.assertEqual(_resolve(home, 'sid_both'), 't_from_run')

    def test_most_recent_run_wins_for_a_reused_session(self):
        with tempfile.TemporaryDirectory() as td:
            home = _build_board(
                Path(td),
                runs=[(10, 't_old', json.dumps({"worker_session_id": "sid_x"}),
                       1788000000, 1788000100),
                      (11, 't_new', json.dumps({"worker_session_id": "sid_x"}),
                       1788000200, 1788000300)],
            )
            self.assertEqual(_resolve(home, 'sid_x'), 't_new')

    def test_never_matches_by_time_window(self):
        """THE load-bearing refusal. A run that overlaps the session exactly,
        on the same profile, but carries neither exact key, must resolve to
        nothing rather than be correlated by time."""
        with tempfile.TemporaryDirectory() as td:
            home = _build_board(
                Path(td),
                runs=[(77, 't_tempting', None, 1788000000, 1788000400)],
                tasks=[('t_tempting', 'ops thing', 'blocked', None)],
            )
            self.assertEqual(_resolve(home, '20260901_143705_75d6f9'), '')

    def test_unknown_session_resolves_to_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            home = _build_board(
                Path(td),
                runs=[(1, 't_a', json.dumps({"worker_session_id": "sid_a"}),
                       1788000000, 1788000400)],
            )
            self.assertEqual(_resolve(home, 'sid_absent'), '')


class TicketFailOpenTests(unittest.TestCase):
    """Every failure is silent — enrichment never costs a completion."""

    def _one_run_home(self, td, **kw):
        return _build_board(
            Path(td),
            runs=[(1, 't_ok', json.dumps({"worker_session_id": "sid_ok"}),
                   1788000000, 1788000400)],
            **kw)

    def test_missing_current_pointer(self):
        with tempfile.TemporaryDirectory() as td:
            home = self._one_run_home(td)
            (home / 'kanban' / 'current').unlink()
            self.assertEqual(_resolve(home, 'sid_ok'), '')

    def test_no_kanban_tree_at_all(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(_resolve(Path(td), 'sid_ok'), '')

    def test_board_directory_missing(self):
        with tempfile.TemporaryDirectory() as td:
            home = self._one_run_home(td, current='no-such-board')
            self.assertEqual(_resolve(home, 'sid_ok'), '')

    def test_empty_board_pointer(self):
        with tempfile.TemporaryDirectory() as td:
            home = self._one_run_home(td, current='')
            self.assertEqual(_resolve(home, 'sid_ok'), '')

    def test_malformed_run_metadata_is_skipped(self):
        """json_extract on non-JSON must not abort the lookup."""
        with tempfile.TemporaryDirectory() as td:
            home = _build_board(
                Path(td),
                runs=[(1, 't_bad', 'not json at all', 1788000000, 1788000400)],
                tasks=[('t_good', 'x', 'done', 'sid_ok')],
            )
            # Falls through to the tasks.session_id key rather than erroring.
            self.assertEqual(_resolve(home, 'sid_ok'), 't_good')

    def test_junk_row_does_not_hide_a_valid_worker_session_id(self):
        """Regression, PR #123 P1.

        sqlite's json_extract RAISES on the first unparseable row it scans,
        aborting the WHOLE query — so one junk metadata row, written by any
        other tool for any unrelated task, used to cost EVERY session its
        run-based ticket. The failure was silent: the handler fell through to
        the weaker tasks.session_id key, so a session with a perfectly good
        worker_session_id row resolved to the wrong ticket, or to none.

        The original version of this suite encoded that behaviour as correct
        (see the test above, which is still right on its own terms: there the
        valid row genuinely IS the tasks one). This case is the one that
        distinguishes them — a valid run row AND a junk row together.
        """
        with tempfile.TemporaryDirectory() as td:
            home = _build_board(
                Path(td),
                runs=[
                    (1, 't_from_run', json.dumps(
                        {"worker_session_id": "sid_ok"}), 1788000000, 1788000400),
                    # Higher id, so a DESC scan reaches it first.
                    (2, 't_junk', 'not json at all', 1788000500, 1788000600),
                ],
                tasks=[('t_from_task', 'x', 'done', 'sid_ok')],
            )
            self.assertEqual(_resolve(home, 'sid_ok'), 't_from_run')

    def test_null_metadata_rows_are_not_treated_as_malformed(self):
        """NULL is the common case — most runs carry no metadata at all."""
        with tempfile.TemporaryDirectory() as td:
            home = _build_board(
                Path(td),
                runs=[(1, 't_from_run', json.dumps(
                    {"worker_session_id": "sid_ok"}), 1788000000, 1788000400),
                      (2, 't_null', None, 1788000500, 1788000600)],
            )
            self.assertEqual(_resolve(home, 'sid_ok'), 't_from_run')

    def test_older_board_schema_without_task_runs(self):
        """A board predating task_runs must fall through, not crash."""
        with tempfile.TemporaryDirectory() as td:
            home = _build_board(
                Path(td), schema='tasks-only',
                tasks=[('t_legacy', 'x', 'done', 'sid_ok')],
            )
            self.assertEqual(_resolve(home, 'sid_ok'), 't_legacy')

    def test_corrupt_database_is_silent(self):
        with tempfile.TemporaryDirectory() as td:
            home = self._one_run_home(td)
            db = home / 'kanban' / 'boards' / 'coder-tfo' / 'kanban.db'
            db.write_bytes(b'this is not a sqlite database at all')
            self.assertEqual(_resolve(home, 'sid_ok'), '')


class TicketBoardNameSafetyTests(unittest.TestCase):
    """`current` is host-writable and is interpolated into a path."""

    HOSTILE = [
        '../../../../etc',
        '/absolute/path',
        'coder-tfo/../../x',
        'a\\b',
        '.',
        '..',
        'x' * 65,          # over the 64-char cap
        'semi;colon',
        'dollar$sign',
    ]

    def test_hostile_board_names_are_rejected(self):
        for name in self.HOSTILE:
            with self.subTest(board=name), tempfile.TemporaryDirectory() as td:
                home = _build_board(
                    Path(td),
                    runs=[(1, 't_ok', json.dumps(
                        {"worker_session_id": "sid_ok"}), 1, 2)],
                    current=name)
                self.assertEqual(_resolve(home, 'sid_ok'), '')


class TicketSanitizationTests(unittest.TestCase):
    """The event path reads a pipe-delimited record; a separator inside a
    ticket id would desync that read."""

    def test_pipe_and_newline_are_stripped(self):
        with tempfile.TemporaryDirectory() as td:
            home = _build_board(
                Path(td),
                runs=[(1, 't_a|b\nc', json.dumps(
                    {"worker_session_id": "sid_ok"}), 1, 2)],
            )
            got = _resolve(home, 'sid_ok')
            self.assertNotIn('|', got)
            self.assertNotIn('\n', got)
            self.assertEqual(got, 't_a_b c')

    def test_clamped_to_256_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            home = _build_board(
                Path(td),
                runs=[(1, 't_' + 'x' * 400, json.dumps(
                    {"worker_session_id": "sid_ok"}), 1, 2)],
            )
            self.assertEqual(len(_resolve(home, 'sid_ok')), 256)


class TicketWiringTests(unittest.TestCase):
    """Both emit paths carry the flag, gated and ordered identically."""

    HERMES_REPORT = ROOT / 'skills' / 'revenium' / 'scripts' / 'hermes-report.sh'
    API_EVENT = ROOT / 'skills' / 'revenium' / 'scripts' / 'api-event-report.sh'

    def test_both_scripts_probe_the_flag(self):
        for script in (self.HERMES_REPORT, self.API_EVENT):
            with self.subTest(script=script.name):
                text = script.read_text()
                self.assertIn('TICKET_CLI_CAPABLE=false', text)
                self.assertIn(
                    'supports_flag "meter completion" "--ticket-id"', text)

    # How far back an emission may sit from its guard. The blocks are a handful
    # of lines; 12 leaves room for a comment without letting an unguarded
    # emission hide behind an unrelated earlier probe.
    GUARD_LOOKBACK = 12

    def test_emission_is_gated_on_the_probe(self):
        """A CLI without the flag must meter byte-identically to before.

        The guard is never on the emitting line itself — it opens a block a few
        lines above — so this walks backwards from each emission rather than
        matching within the line.
        """
        for script in (self.HERMES_REPORT, self.API_EVENT):
            with self.subTest(script=script.name):
                lines = script.read_text().splitlines()
                emissions = [i for i, l in enumerate(lines)
                             if '--ticket-id "' in l]
                self.assertTrue(
                    emissions, "%s emits --ticket-id nowhere" % script.name)
                for i in emissions:
                    window = lines[max(0, i - self.GUARD_LOOKBACK):i]
                    self.assertTrue(
                        any('TICKET_CLI_CAPABLE' in w for w in window),
                        "%s:%d emits --ticket-id with no TICKET_CLI_CAPABLE "
                        "guard within %d lines above it"
                        % (script.name, i + 1, self.GUARD_LOOKBACK))

    def test_completion_path_emits_at_both_sites(self):
        """hermes-report.sh has a marker-split and a markerless emit path; the
        flag must ride both or a markerless session silently loses it."""
        text = self.HERMES_REPORT.read_text()
        self.assertEqual(text.count('cmd+=(--ticket-id "${ticket_id}")'), 2)

    def test_resolver_lives_in_common_sh_only(self):
        """One definition, shared — not duplicated per script."""
        common = COMMON_SH.read_text()
        self.assertIn('resolve_session_ticket() {', common)
        for script in (self.HERMES_REPORT, self.API_EVENT):
            self.assertNotIn(
                'resolve_session_ticket() {', script.read_text(),
                "%s redefines the resolver instead of using common.sh's"
                % script.name)

    def test_event_record_field_count_is_consistent(self):
        """The event path threads a pipe-delimited record across a Python ->
        bash boundary. The producer, the reader and the shadow aggregator must
        agree on the field count or argv silently corrupts."""
        text = self.API_EVENT.read_text()
        self.assertIn('if len(fields) != 24:', text)
        self.assertIn('ticket_id_r; do', text)
        self.assertIn('_ticket_id,', text)


if __name__ == '__main__':
    unittest.main()
