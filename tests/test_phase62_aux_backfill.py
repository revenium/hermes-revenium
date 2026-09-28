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

Deliberately imports `_AuxMeteringTestCase` from
tests/test_phase55_auxiliary_metering.py rather than rebuilding its
fixture/tick harness (per 62-03-PLAN.md Task 1 step 5) -- that base class
carries no test_* methods of its own, so importing it by name does not
double-collect anything under `unittest discover` (contrast the
GoldenImmutabilityTests-by-name bug documented in 62-01-SUMMARY.md's
Deviations #3, which imported a class that DOES carry test methods).

`_AuxHarness` (tests/test_phase62_subscriber_wiring.py) is imported for the
structural test's script-source access only; the behavioural tests below
use `_AuxMeteringTestCase`'s own fixture builder so a subscriber-capable
shim and a populated `user_id` column can be layered on top of it exactly
as tests/test_phase62_subscriber_wiring.py::AuxSubscriberWiringTests
already does.
"""
import os
import re
import unittest

from tests._compat_helpers import build_shim, seed_user_ids
from tests.test_phase55_auxiliary_metering import _AuxMeteringTestCase
from tests.test_phase62_subscriber_wiring import HERMES_REPORT_SH


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


if __name__ == '__main__':
    unittest.main()
