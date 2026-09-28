"""Phase 62 Plan 03 (SUB-05/07/08/11): auxiliary-path-specific behaviour that
doesn't belong in the shared four-run wiring proof
(tests/test_phase62_subscriber_wiring.py::AuxSubscriberWiringTests).

Covers, per 62-03-PLAN.md Task 1's <behavior>:

  - A session with three auxiliary rows and one resolved actor: all three
    `meter completion` calls carry the same key (AuxThreeRowSamenessTests).
  - The auxiliary ledger lines and transaction ids are unchanged in shape by
    the subscriber, so re-running the tick is still a no-op -- the key
    enters neither (AuxIdempotencyTests).
  - A run in which the cache and its parser agree produces no
    width-mismatch line in the log -- the aggregate line stays silent when
    there is nothing to say (AuxWidthMismatchSilenceTests).
  - A structural guard: the producer field count at BOTH append sites
    equals the parser's expected width, read from the script source --
    the guard that would have caught a missed producer (D-09)
    (AuxSessionCtxWidthStructuralTests).

Task 2 (SUB-11) adds, per 62-03-PLAN.md Task 2's <behavior>:

  - A session with a kanban ticket ships --ticket-id on its auxiliary rows;
    a session with a skill signal ships the same four skill flags the
    other three sites ship, in the same order, never --skill-kind or
    --skill-plugin-name (AuxTicketAndSkillWiringTests).
  - A session with three auxiliary rows invokes the ticket resolver ONCE
    and the skill resolver ONCE -- measured with a stdin-capturing `python3`
    shim, not asserted by inspection (AuxTicketAndSkillOnceInvocationTests).
  - A session with no ticket and no skill ships argv equal to the
    auxiliary golden's argv_order; a CLI advertising neither family ships
    the same list even when both would have resolved
    (AuxTicketAndSkillAbsentCaseTests).
  - A structural guard pinning the emit query's ORDER BY leading with
    session_id as the once-per-session memo's own dependency
    (AuxMemoOrderingDependencyTests).

Deliberately imports `_AuxMeteringTestCase` from
tests/test_phase55_auxiliary_metering.py rather than rebuilding its
fixture/tick harness (per 62-03-PLAN.md Task 1 step 5) -- that base class
carries no test_* methods of its own, so importing it by name does not
double-collect anything under `unittest discover` (contrast the
GoldenImmutabilityTests-by-name bug documented in 62-01-SUMMARY.md's
Deviations #3, which imported a class that DOES carry test methods).

`_build_board` is imported from tests/test_ticket_attribution.py (per
62-03-PLAN.md Task 2 step 6) rather than writing a second kanban-board
fixture builder.

`_AuxHarness` (tests/test_phase62_subscriber_wiring.py) is imported for the
structural test's script-source access only; the behavioural tests below
use `_AuxMeteringTestCase`'s own fixture builder so a subscriber-capable
shim and a populated `user_id` column can be layered on top of it exactly
as tests/test_phase62_subscriber_wiring.py::AuxSubscriberWiringTests
already does.
"""
import json
import os
import re
import shlex
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from tests._compat_helpers import (
    assert_argv_is_golden_argv_order,
    build_session_model_usage,
    build_shim,
    load_golden,
    run_script,
    seed_user_ids,
    SCRIPTS_DIR,
)
from tests.test_phase55_auxiliary_metering import _AuxMeteringTestCase
from tests.test_phase61_identity_resolution import _OLD_TS, _seed_sessions_db
from tests.test_phase62_subscriber_wiring import HERMES_REPORT_SH
from tests.test_ticket_attribution import _build_board


class AuxThreeRowSamenessTests(_AuxMeteringTestCase):
    """A session with three auxiliary rows and one resolved actor ships the
    SAME subscriber key on all three `meter completion` calls -- the actor
    is a per-SESSION property, not a per-row one, exactly as
    MultiMarkerSubscriberSamenessTests already proves for the marker-split
    site."""

    def test_three_aux_rows_one_resolved_actor_all_carry_same_key(self):
        rows = [
            self._one_aux_row(
                model='claude-3-5-haiku', task='approval',
                api_call_count=1, input_tokens=10, output_tokens=5,
                estimated_cost_usd=0.001,
                first_seen=1715514500.0, last_seen=1715514550.0,
            ),
            self._one_aux_row(
                model='claude-3-5-sonnet', task='approval',
                api_call_count=1, input_tokens=20, output_tokens=8,
                estimated_cost_usd=0.002,
                first_seen=1715514600.0, last_seen=1715514650.0,
            ),
            self._one_aux_row(
                model='claude-3-opus', task='title_gen',
                api_call_count=1, input_tokens=30, output_tokens=12,
                estimated_cost_usd=0.003,
                first_seen=1715514700.0, last_seen=1715514750.0,
            ),
        ]
        fixture = self._setup_fixture([self._one_session()], aux_rows=rows)
        build_shim(
            os.path.join(fixture['bin_dir'], 'revenium'),
            subscriber_capable=True, squad_capable=True,
        )
        seed_user_ids(fixture['state_db'], {'aux-sid-001': 'p62-aux-three-actor'})

        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])

        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(
            len(aux_flags_list), 3,
            f'expected 3 aux invocations (one per row), got '
            f'{len(aux_flags_list)}: {result["meter_invocations"]!r}',
        )
        expected_key = 'test:p62-aux-three-actor'
        for flags in aux_flags_list:
            self.assertEqual(
                flags.get('--subscriber-id'), expected_key,
                f'every aux row of one session must carry the SAME key, '
                f'got {flags.get("--subscriber-id")!r} in {flags!r}',
            )


class AuxIdempotencyTests(_AuxMeteringTestCase):
    """The subscriber key enters neither --transaction-id nor the
    AUX_LEDGER_FILE line -- so a subscriber-capable, populated tick's
    ledger is byte-identical in SHAPE to the pre-subscriber ledger, and a
    second tick over the unchanged fixture is still a no-op."""

    def test_ledger_line_shape_unaffected_by_subscriber_key(self):
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        build_shim(
            os.path.join(fixture['bin_dir'], 'revenium'),
            subscriber_capable=True, squad_capable=True,
        )
        seed_user_ids(fixture['state_db'], {'aux-sid-001': 'p62-aux-idem-actor'})

        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])
        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(len(aux_flags_list), 1, aux_flags_list)
        self.assertEqual(
            aux_flags_list[0].get('--subscriber-id'), 'test:p62-aux-idem-actor'
        )

        ledger_path = self._aux_ledger_path(fixture)
        with open(ledger_path) as f:
            lines = [ln.rstrip('\n') for ln in f if ln.strip()]
        self.assertEqual(len(lines), 1, lines)
        parts = lines[0].split('|')
        self.assertEqual(
            len(parts), 8,
            f'ledger line shape must be unaffected by the resolved '
            f'subscriber key -- expected 8 pipe-delimited parts (the '
            f'pre-Phase-62 shape), got {len(parts)}: {parts!r}',
        )
        self.assertNotIn(
            'p62-aux-idem-actor', lines[0],
            'the resolved subscriber key must never enter the ledger line '
            '-- the aux ledger key is its own six-column cumulative '
            'identity, and adding a dimension to it would unmatch every '
            'existing line and re-ship everything',
        )

    def test_second_tick_over_unchanged_fixture_is_a_no_op(self):
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        build_shim(
            os.path.join(fixture['bin_dir'], 'revenium'),
            subscriber_capable=True, squad_capable=True,
        )
        seed_user_ids(fixture['state_db'], {'aux-sid-001': 'p62-aux-idem-actor'})

        self._tick(fixture, 0)
        ledger_path = self._aux_ledger_path(fixture)
        with open(ledger_path) as f:
            ledger_after_tick_1 = f.read()

        result_2 = self._tick(fixture, 1)
        aux_flags_list = self._find_aux_invocation(result_2['meter_invocations'])
        self.assertEqual(
            len(aux_flags_list), 0,
            'second tick over an unchanged fixture must ship zero aux '
            f'invocations, got {len(aux_flags_list)}',
        )
        with open(ledger_path) as f:
            ledger_after_tick_2 = f.read()
        self.assertEqual(
            ledger_after_tick_1, ledger_after_tick_2,
            'revenium-aux.ledger must be byte-identical across the no-op '
            'tick -- resolving a subscriber key must not change WHICH rows '
            'are considered already-shipped',
        )


class AuxWidthMismatchSilenceTests(_AuxMeteringTestCase):
    """A tick in which every aux_session_ctx producer agrees with the
    parser's expected width (the normal, correct-code case) must produce NO
    width-mismatch line in the log -- the aggregate line is gated on a
    non-zero count and stays silent when there is nothing to say, matching
    every other once-per-tick aggregate this file already writes."""

    @staticmethod
    def _log_text(fixture):
        log_path = os.path.join(fixture['state_dir'], 'revenium-metering.log')
        if not os.path.exists(log_path):
            return ''
        with open(log_path) as f:
            return f.read()

    def test_no_mismatch_line_when_producers_and_parser_agree(self):
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        build_shim(
            os.path.join(fixture['bin_dir'], 'revenium'),
            subscriber_capable=True, squad_capable=True,
        )
        seed_user_ids(fixture['state_db'], {'aux-sid-001': 'p62-aux-silent-actor'})

        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])
        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(len(aux_flags_list), 1, aux_flags_list)

        log_text = self._log_text(fixture)
        self.assertNotIn('AUX_CTX_WIDTH_MISMATCH', log_text, log_text)
        self.assertNotIn('malformed line(s) this tick', log_text, log_text)


class AuxSessionCtxWidthStructuralTests(unittest.TestCase):
    """The guard that would have caught a missed producer (D-09): the
    literal field count at BOTH aux_session_ctx append sites must equal the
    parser's own expected width, read from the shipped script source --
    not asserted by inspection, counted.

    MISSES: this compares COUNTS, not that the fields are in the same ORDER
    at both producers (a transposed-but-same-length append would still pass
    this test); the behavioural proof that the RIGHT field carries the
    subscriber key is AuxThreeRowSamenessTests / AuxSubscriberWiringTests
    above, not this one.
    """

    def _producer_field_count(self, text, var_name):
        match = re.search(
            r'%s\+="([^"]*)"' % re.escape(var_name), text,
        )
        self.assertIsNotNone(
            match, f'could not find a `{var_name}+="..."` append in the '
            f'shipped script'
        )
        return match.group(1).count('|') + 1

    def test_both_producers_match_the_parsers_expected_width(self):
        text = HERMES_REPORT_SH.read_text(encoding='utf-8')

        session_loop_count = self._producer_field_count(text, 'aux_session_ctx')
        supplement_count = self._producer_field_count(text, 'augmented')

        width_match = re.search(r'if len\(_parts\) != (\d+):', text)
        self.assertIsNotNone(
            width_match,
            'could not find the parser\'s `if len(_parts) != N:` width '
            'check in the shipped script',
        )
        parser_width = int(width_match.group(1))

        self.assertEqual(
            session_loop_count, parser_width,
            f'the session-loop aux_session_ctx append writes '
            f'{session_loop_count} fields but the parser expects '
            f'{parser_width} -- a producer/parser mismatch silently drops '
            f'every session it touches (D-09)',
        )
        self.assertEqual(
            supplement_count, parser_width,
            f'the supplement\'s recovery append writes {supplement_count} '
            f'fields but the parser expects {parser_width} -- a '
            f'producer/parser mismatch silently drops every '
            f'supplement-recovered session (D-09)',
        )
        # Not asserted as a magic number by itself elsewhere -- both the
        # session-loop producer and the parser widened in this same plan
        # from 6 to 7 fields (the trailing subscriber_key). Pinning the
        # literal value here means a THIRD accidental width (e.g. a stray
        # extra field added by a future edit that also updates the parser
        # to match) still gets caught, because 7 is checked directly, not
        # merely "both producers agree with whatever the parser says".
        self.assertEqual(parser_width, 7, parser_width)


# ---------------------------------------------------------------------------
# Task 2 (SUB-11): ticket and skill attribution on the aux path.
# ---------------------------------------------------------------------------

# Real interpreter path, captured once at import time -- the capture shim
# execs THIS by absolute path, mirroring tests/test_reporter_spawn_guards.py's
# REAL_PYTHON3 idiom.
_REAL_PYTHON3 = sys.executable


def _add_skill_messages(db_path, sid, rows):
    """rows: list of (tool_name, payload_str, timestamp). Mirrors
    tests/test_skill_attribution.py's add_skill_messages, parameterised on
    `sid` (that module hardcodes a single module-level SID) so this can
    target the aux fixture's own session id."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        'CREATE TABLE IF NOT EXISTS messages '
        '(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, '
        'tool_calls TEXT, tool_name TEXT, timestamp REAL)'
    )
    for tool_name, payload, ts in rows:
        conn.execute(
            'INSERT INTO messages (session_id, role, content, tool_name, timestamp) '
            'VALUES (?,?,?,?,?)', (sid, 'tool', payload, tool_name, ts))
    conn.commit()
    conn.close()


def _patch_shim_for_ticket_capability(shim_path):
    """tests/_compat_helpers.py's build_shim has no ticket_capable
    parameter -- TICKET_CLI_CAPABLE is probed the same way
    (supports_flag "meter completion" "--ticket-id"), so advertising it
    just needs one more `echo` line in the shim's `--help` branch. Patches
    the ALREADY-WRITTEN shim file in place rather than touching
    _compat_helpers.py (outside this plan's files_modified list).

    Inserted immediately BEFORE the --agentic-job-id echo, for the SAME
    reason build_shim's own docstring gives for --subscriber-id: that echo
    is deliberately the LAST line written before `exit 0` (a recorded
    SIGPIPE-ordering fix), and a line written after it would reopen the
    race the ordering closes.
    """
    with open(shim_path) as f:
        text = f.read()
    anchor = '      echo "--agentic-job-id  Agentic job instance identifier"\n'
    assert anchor in text, (
        'build_shim output shape changed -- update this patch to match'
    )
    text = text.replace(
        anchor,
        '      echo "--ticket-id string   Kanban ticket identifier"\n'
        + anchor,
        1,
    )
    with open(shim_path, 'w') as f:
        f.write(text)


def _write_capture_shim(bin_dir, capture_dir):
    """Fake `python3` that captures the FULL stdin of every heredoc
    invocation (`python3 -`) to its own file under capture_dir, then execs
    the REAL interpreter transparently -- the technique
    tests/test_reporter_spawn_guards.py's _write_python_spawn_shim uses for
    counting spawns, extended here to capture CONTENT so a specific
    resolver's heredoc can be told apart from every other python3 call this
    script makes.

    Capture is gated on `"$1" = "-"` (heredoc invocations only, e.g.
    `python3 - <<'PY'`) -- a `python3 -c "..."` call (aux_now_ts) takes no
    stdin at all and inherits whatever the CALLER's stdin happens to be. In
    this script that caller is the aux emit loop's own
    `while IFS='|' read -r ... done <<< "${aux_query_output}"`, whose
    remaining unread rows live on that SAME file descriptor. An earlier,
    naive version of this shim `cat`-captured stdin unconditionally for
    EVERY invocation including `-c` calls, which drained the while loop's
    own here-string out from under it and silently truncated a 3-aux-row
    tick down to 1 row -- gating on `-` is what avoids ever touching stdin
    for a call that never redirected it in the first place.
    """
    os.makedirs(capture_dir, exist_ok=True)
    shim = os.path.join(bin_dir, 'python3')
    with open(shim, 'w') as f:
        f.write(
            '#!/bin/sh\n'
            'if [ "$1" = "-" ]; then\n'
            f'  f="$(mktemp "{capture_dir}/cap.XXXXXX")"\n'
            '  cat > "$f" 2>/dev/null\n'
            f'  exec {_REAL_PYTHON3} "$@" < "$f"\n'
            'else\n'
            f'  exec {_REAL_PYTHON3} "$@"\n'
            'fi\n'
        )
    os.chmod(shim, 0o755)


def _count_resolver_invocations(capture_dir):
    """Return (skill_count, ticket_count): how many captured heredoc
    bodies belong to resolve_session_skill (its SQL names all three skill
    tool_name values in one IN (...) clause) vs resolve_session_ticket (its
    SQL names worker_session_id) -- distinct, unambiguous substrings unique
    to each resolver's own heredoc body, not shared with resolve_skill_
    provenance's or _clean_model_name's or _infer_provider's."""
    skill_count = 0
    ticket_count = 0
    for name in os.listdir(capture_dir):
        with open(os.path.join(capture_dir, name)) as f:
            text = f.read()
        if "'skill_view','skill_manage','skills_list'" in text:
            skill_count += 1
        if 'worker_session_id' in text:
            ticket_count += 1
    return skill_count, ticket_count


class AuxTicketAndSkillWiringTests(_AuxMeteringTestCase):
    """A session with a kanban ticket ships --ticket-id on its auxiliary
    rows; a session with a skill signal ships the same four skill flags
    the other three sites ship, in the same order, and never the two that
    are deliberately never emitted anywhere."""

    def test_ships_ticket_id_matching_the_kanban_board(self):
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        shim_path = os.path.join(fixture['bin_dir'], 'revenium')
        build_shim(shim_path, subscriber_capable=False, squad_capable=True)
        _patch_shim_for_ticket_capability(shim_path)
        _build_board(
            Path(fixture['hermes_home']),
            tasks=[('t_p62_aux', 'title', 'done', 'aux-sid-001')],
        )

        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])
        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(len(aux_flags_list), 1, aux_flags_list)
        self.assertEqual(aux_flags_list[0].get('--ticket-id'), 't_p62_aux')

    def test_ships_skill_flags_never_kind_or_plugin_name(self):
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        shim_path = os.path.join(fixture['bin_dir'], 'revenium')
        build_shim(
            shim_path, subscriber_capable=False, squad_capable=True,
            skill_capable=True,
        )
        _add_skill_messages(
            fixture['state_db'], 'aux-sid-001',
            [('skill_view', json.dumps({'name': 'revenium'}), 1715514000.0)],
        )

        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])
        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(len(aux_flags_list), 1, aux_flags_list)
        flags = aux_flags_list[0]
        self.assertEqual(flags.get('--skill-name'), 'revenium')
        self.assertEqual(flags.get('--skill-invocation-trigger'), 'skill_view')
        self.assertNotIn('--skill-kind', flags, flags)
        self.assertNotIn('--skill-plugin-name', flags, flags)


class AuxTicketAndSkillOnceInvocationTests(_AuxMeteringTestCase):
    """A session with three auxiliary rows invokes the ticket resolver
    ONCE and the skill resolver ONCE -- MEASURED with a stdin-capturing
    python3 shim, not asserted by reading the code.

    Uses an auxiliary-ONLY session (zero main-loop tokens, matching
    tests/test_phase59_aux_zero_token.py's recovered-session shape) so the
    main session loop's OWN skill/ticket resolution (sites 1/2, which
    never run at all here because the session never reaches the main
    loop's token filter) cannot contribute a second invocation that would
    make a per-row aux bug indistinguishable from correct once-per-session
    behaviour."""

    def test_three_aux_rows_resolve_skill_per_window_and_ticket_once(self):
        zero_session = self._one_session(input_tokens=0, output_tokens=0)
        rows = [
            self._one_aux_row(
                model='claude-3-5-haiku', task='approval',
                api_call_count=1, input_tokens=10, output_tokens=5,
                estimated_cost_usd=0.001,
                first_seen=1715514500.0, last_seen=1715514550.0,
            ),
            self._one_aux_row(
                model='claude-3-5-sonnet', task='approval',
                api_call_count=1, input_tokens=20, output_tokens=8,
                estimated_cost_usd=0.002,
                first_seen=1715514600.0, last_seen=1715514650.0,
            ),
            self._one_aux_row(
                model='claude-3-opus', task='title_gen',
                api_call_count=1, input_tokens=30, output_tokens=12,
                estimated_cost_usd=0.003,
                first_seen=1715514700.0, last_seen=1715514750.0,
            ),
        ]
        fixture = self._setup_fixture([zero_session], aux_rows=rows)
        shim_path = os.path.join(fixture['bin_dir'], 'revenium')
        build_shim(
            shim_path, subscriber_capable=False, squad_capable=True,
            skill_capable=True,
        )
        _patch_shim_for_ticket_capability(shim_path)
        capture_dir = os.path.join(fixture['tmpdir'], 'pycap')
        _write_capture_shim(fixture['bin_dir'], capture_dir)

        _add_skill_messages(
            fixture['state_db'], 'aux-sid-001',
            [('skill_view', json.dumps({'name': 'revenium'}), 1715514000.0)],
        )
        _build_board(
            Path(fixture['hermes_home']),
            tasks=[('t_p62_aux_once', 'title', 'done', 'aux-sid-001')],
        )

        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])
        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(
            len(aux_flags_list), 3,
            f'expected 3 aux invocations (one per row), got '
            f'{len(aux_flags_list)}: {result["meter_invocations"]!r}',
        )
        for flags in aux_flags_list:
            self.assertEqual(flags.get('--skill-name'), 'revenium')
            self.assertEqual(flags.get('--ticket-id'), 't_p62_aux_once')

        skill_count, ticket_count = _count_resolver_invocations(capture_dir)

        # CORRECTED: this test previously asserted skill_count == 1 and so
        # encoded a DEFECT as the expected behaviour (found by PR review on
        # #136). resolve_session_skill is time-WINDOWED on the row's own
        # window end; the three rows above deliberately carry three DISTINCT
        # last_seen values. A session-keyed memo returned the FIRST row's
        # skill for all three, so a skill opened after row 1's window but
        # inside row 3's was silently omitted from row 3 -- and because the
        # rows are ordered by model rather than by time, which row "wins" was
        # arbitrary.
        #
        # The real invariant is per-DEPENDENCY, not per-session: one skill
        # resolution per distinct (session, window end), and one ticket
        # resolution per session because resolve_session_ticket takes no
        # window. D-08's forbidden shape is a fork per RECORD; a fork per
        # distinct window is the minimum correctness costs, and the
        # shared-window case below proves the memo still eliminates the
        # redundant ones.
        self.assertEqual(
            skill_count, 3,
            f'expected resolve_session_skill invoked once per DISTINCT window '
            f'end (3 rows, 3 distinct last_seen values), got {skill_count}. '
            f'A count of 1 means the memo is replaying one window\'s skill '
            f'across rows whose own windows differ.',
        )
        self.assertEqual(
            ticket_count, 1,
            f'expected resolve_session_ticket invoked exactly ONCE for a '
            f'3-row single session, got {ticket_count} -- it takes no window, '
            f'so a per-row resolution (D-08\'s forbidden shape) would be 3',
        )

    # GAP, named rather than shipped broken: a companion test proving the memo
    # still COLLAPSES redundant lookups (two rows sharing one window end must
    # cost ONE skill resolution, not two) was attempted and withdrawn -- the
    # fixture produced zero skill resolutions, so it was passing/failing for a
    # reason unrelated to the property. Without it, the corrected count above
    # could in principle be satisfied by deleting the memo entirely, which
    # would restore D-08's forbidden per-record fork. The memo's collapsing
    # behaviour is currently asserted only indirectly, by the ticket count
    # remaining 1 across three rows.


class AuxTicketAndSkillAbsentCaseTests(_AuxMeteringTestCase):
    """A session with no ticket and no skill ships argv equal to the
    auxiliary golden's argv_order -- the absent case stays the absent
    case. A CLI advertising neither family ships that same list even when
    both would have resolved."""

    def test_no_ticket_no_skill_matches_golden_argv_order(self):
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])
        aux = [
            inv for inv in result['meter_invocations']
            if '--operation-type' in inv
            and inv[inv.index('--operation-type') + 1] == 'OTHER'
        ]
        self.assertEqual(len(aux), 1, aux)
        golden = load_golden('meter-completion-aux.golden.json')
        assert_argv_is_golden_argv_order(self, aux[0], golden)

    def test_incapable_cli_ships_neither_family_even_with_signal_present(self):
        """A CLI that advertises neither --skill-name nor --ticket-id
        ships argv equal to the golden's argv_order exactly, even though a
        skill signal AND a kanban ticket both exist for this session --
        the probe, not the resolved value, gates emission."""
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        # build_shim's default (skill_capable=False, no ticket patch) is
        # the incapable arm for both families simultaneously.
        _add_skill_messages(
            fixture['state_db'], 'aux-sid-001',
            [('skill_view', json.dumps({'name': 'revenium'}), 1715514000.0)],
        )
        _build_board(
            Path(fixture['hermes_home']),
            tasks=[('t_p62_incapable', 'title', 'done', 'aux-sid-001')],
        )

        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])
        aux = [
            inv for inv in result['meter_invocations']
            if '--operation-type' in inv
            and inv[inv.index('--operation-type') + 1] == 'OTHER'
        ]
        self.assertEqual(len(aux), 1, aux)
        golden = load_golden('meter-completion-aux.golden.json')
        assert_argv_is_golden_argv_order(self, aux[0], golden)


class AuxMemoOrderingDependencyTests(unittest.TestCase):
    """Structural guard: the aux emit query's ORDER BY must lead with
    session_id, because the once-per-session skill/ticket memo is correct
    ONLY as long as one session's rows arrive contiguously. If a future
    edit reorders that SELECT, the memo degrades from "resolve once per
    session" to "resolve once per row" -- still correct (a session-id
    change is detected either way), but re-resolving on every row is
    exactly the per-record subshell cost D-08 forbids, and a silent
    performance regression is worse than a named, deliberate failure."""

    def test_emit_query_order_by_leads_with_session_id(self):
        # The query text is split across two adjacent Python string
        # literals in the source (concatenated at parse time, but NOT
        # adjacent in the raw file text), so this checks the two lines
        # separately rather than one continuous substring.
        text = HERMES_REPORT_SH.read_text(encoding='utf-8')
        self.assertIn(
            "ORDER BY session_id, model, billing_provider, billing_base_url, ",
            text,
            'the aux emit query\'s ORDER BY must lead with session_id -- '
            'the once-per-session skill/ticket memo '
            '(_aux_attr_memo_sid) depends on this exact ordering to keep '
            'one session\'s rows contiguous',
        )
        self.assertIn(
            '"billing_mode, task"',
            text,
            'the aux emit query\'s ORDER BY clause got truncated or reshaped',
        )


# ---------------------------------------------------------------------------
# Task 3 (SUB-05): the supplement path's own actor -- the auxiliary-only
# session that the supplement exists to recover.
# ---------------------------------------------------------------------------


class AuxOnlySessionOwnActorTests(_AuxMeteringTestCase):
    """A session with auxiliary spend and NO main-loop tokens -- the shape
    the supplement exists to recover -- ships its auxiliary rows with its
    own resolved key in the seventh cache field. Fixture shape reused from
    tests/test_phase59_aux_zero_token.py::AuxOnlySessionRecoveryTests (per
    62-03-PLAN.md Task 3 step 5)."""

    def test_recovered_session_ships_its_own_resolved_key(self):
        fixture = self._setup_fixture(
            [self._one_session(input_tokens=0, output_tokens=0)],
            aux_rows=[self._one_aux_row()],
        )
        build_shim(
            os.path.join(fixture['bin_dir'], 'revenium'),
            subscriber_capable=True, squad_capable=True,
        )
        seed_user_ids(fixture['state_db'], {'aux-sid-001': 'p62-recovered-actor'})

        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])
        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(len(aux_flags_list), 1, aux_flags_list)
        self.assertEqual(
            aux_flags_list[0].get('--subscriber-id'), 'test:p62-recovered-actor'
        )


class AuxOnlySessionUnsafeActorTests(_AuxMeteringTestCase):
    """A recovered session whose stored actor id contains a delimiter ships
    NO subscriber token, and its environment dimension and token values on
    that same row are unaffected -- the unsafe value is REFUSED (via the
    supplement's own delimiter-safety CASE, T-62-15), not sanitised into a
    plausible different key."""

    def test_pipe_in_user_id_ships_no_token_environment_and_tokens_intact(self):
        fixture = self._setup_fixture(
            [self._one_session(input_tokens=0, output_tokens=0)],
            aux_rows=[self._one_aux_row()],
        )
        build_shim(
            os.path.join(fixture['bin_dir'], 'revenium'),
            subscriber_capable=True, squad_capable=True,
        )
        seed_user_ids(fixture['state_db'], {'aux-sid-001': 'U|600'})

        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])
        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(len(aux_flags_list), 1, aux_flags_list)
        flags = aux_flags_list[0]
        self.assertNotIn('--subscriber-id', flags, flags)
        self.assertEqual(flags.get('--environment'), 'test')
        self.assertEqual(flags.get('--total-tokens'), '50')


class AuxOnlySessionColumnAbsentTests(_AuxMeteringTestCase):
    """On an install with no identity column at all, the supplement still
    recovers the session and still ships its auxiliary row -- the widened
    recovery SELECT's schema-probe boolean handoff did not break the
    recovery query itself (T-62-14: an unguarded column reference would
    raise inside the surrounding swallow and silently stop recovering
    EVERY auxiliary-only session, not just lose the subscriber
    dimension)."""

    def test_column_absent_install_still_recovers_and_ships(self):
        fixture = self._setup_fixture(
            [self._one_session(input_tokens=0, output_tokens=0)],
            aux_rows=[self._one_aux_row()],
        )
        # Deliberately NO seed_user_ids call -- the column-absent arm.
        build_shim(
            os.path.join(fixture['bin_dir'], 'revenium'),
            subscriber_capable=True, squad_capable=True,
        )

        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])
        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(len(aux_flags_list), 1, aux_flags_list)
        flags = aux_flags_list[0]
        self.assertNotIn('--subscriber-id', flags, flags)
        self.assertEqual(flags.get('--environment'), 'test')


class AuxOnlySessionNoInheritanceTests(unittest.TestCase):
    """A recovered session does NOT inherit a root's key; it carries its
    own or none. Inheritance lives in the main session loop and reaches
    through the batched root map built for THAT loop's sid set (Phase 61);
    reproducing it here would be a second inheritance implementation for
    the one population that has no main-loop work to inherit from.

    Uses tests.test_phase61_identity_resolution._seed_sessions_db (the
    15-column schema carrying parent_session_id, which
    tests._compat_helpers.build_state_db and _AuxMeteringTestCase's own
    fixture builder both omit) rather than _AuxMeteringTestCase, because
    proving no-inheritance requires an actual root/child relationship.
    """

    def test_recovered_child_does_not_inherit_its_roots_subscriber(self):
        root_sid = 'p62-root-noinherit'
        child_sid = 'p62-child-noinherit'

        tmp = tempfile.mkdtemp(prefix='gsd-p62-noinherit-')
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        hermes_home = os.path.join(tmp, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        markers_dir = os.path.join(state_dir, 'markers')
        os.makedirs(markers_dir, mode=0o700)
        state_db = os.path.join(hermes_home, 'state.db')
        shim_home = os.path.join(tmp, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)
        meter_log = os.path.join(tmp, 'meter.log')
        jobs_log = os.path.join(tmp, 'jobs.log')
        inv_log = os.path.join(tmp, 'inv.log')
        build_shim(
            os.path.join(bin_dir, 'revenium'),
            subscriber_capable=True, squad_capable=True,
        )

        _seed_sessions_db(state_db, [
            {
                'id': root_sid, 'source': 'slack', 'user_id': 'U100',
                'input_tokens': 100, 'output_tokens': 50,
                'started_at': _OLD_TS, 'ended_at': _OLD_TS,
            },
            {
                # The would-be-inherited-from child: zero main-loop tokens
                # (so it is recovered by the supplement, not the main
                # loop), no user_id of its own.
                'id': child_sid, 'source': 'subagent', 'user_id': None,
                'parent_session_id': root_sid,
                'input_tokens': 0, 'output_tokens': 0,
                'started_at': _OLD_TS, 'ended_at': _OLD_TS,
            },
        ])
        build_session_model_usage(state_db, [{
            'session_id': child_sid, 'model': 'claude-3-5-haiku',
            'billing_provider': 'anthropic', 'task': 'approval',
            'api_call_count': 1, 'input_tokens': 10, 'output_tokens': 5,
            'estimated_cost_usd': 0.001,
            'first_seen': _OLD_TS + 500.0, 'last_seen': _OLD_TS + 600.0,
        }])

        env = {
            **os.environ,
            'HOME': shim_home, 'HERMES_HOME': hermes_home,
            'REVENIUM_STATE_DIR': state_dir,
            'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': inv_log, 'METER_LOG': meter_log,
            'JOBS_LOG': jobs_log, 'TZ': 'UTC',
        }
        rc, _inv, output = run_script(
            SCRIPTS_DIR / 'hermes-report.sh', env, inv_log
        )
        self.assertEqual(rc, 0, output)

        with open(meter_log) as f:
            invocations = [shlex.split(ln) for ln in f if ln.strip()]
        aux = [
            inv for inv in invocations
            if '--operation-type' in inv
            and inv[inv.index('--operation-type') + 1] == 'OTHER'
        ]
        self.assertEqual(len(aux), 1, invocations)
        argv = aux[0]
        self.assertNotIn(
            '--subscriber-id', argv,
            f'a recovered child must NOT inherit its root\'s subscriber '
            f'key -- inheritance is a main-loop-only mechanism, and this '
            f'child never reaches the main loop (zero tokens): {argv!r}',
        )
        # The root-walk (get_root_session_id) still resolves correctly --
        # --trace-id is the ROOT's sid, proving the child's OTHER
        # attribution is intact even though subscriber is correctly absent.
        self.assertEqual(argv[argv.index('--trace-id') + 1], root_sid, argv)


if __name__ == '__main__':
    unittest.main()
