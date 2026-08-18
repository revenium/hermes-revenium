"""quick-260818-jbl (CLAIM-01..05) — legacy must not claim a session it will
never bill.

`hermes-report.sh` claims session ownership as `legacy` BY DEFAULT for a
session with rows in neither billing ledger. That default was correct when
legacy always billed. Since quick-260818-f1g (#57) legacy emission can be
SUPPRESSED per session while the claim still runs -- so on a brand-new
session under suppression, legacy claimed `legacy`, wrote a durable record,
and never emitted a completion for it. api-event-report.sh's total ship
predicate then deferred to that durable record forever, and the session was
billed by NEITHER path. Measured live: session 20260818_171928_2ba368 --
owner `legacy`, 0 HERMES: rows, 0 API: rows. Post-cutover that would be a
permanent silent under-bill for all new traffic.

Fix: legacy ABSTAINS from claiming when it is suppressed for a session and
neither ledger holds rows, leaving the atomic claim to whichever path is
actually live.

Three alternatives were considered and rejected, one line each:
  (ii)  claim `event` explicitly on the event path's own behalf -- false
        whenever the event path is shadow/off/uninstalled, and self-locking
        (the takeover branch defers with no takeover once suppressed).
  (iii) teach the event path that a zero-row `legacy` record is claimable --
        re-derives ownership from the peer's mutable, prunable BILLING
        ledger, exactly the TOCTOU shape PR #54 exists to delete.
  (i)   ABSTAIN -- chosen. Legacy writes no record; whichever path is
        actually live claims it atomically on its own next tick.

Each test is named for its axis ID from PLAN.md's <axis_register>, so a
mutation to one guard fails its own test and only its own test (see
tests/mutation_verify_legacy_claim_abstain.py). Assertions are on the
SHIPPING surfaces -- captured argv, the ledger/owners files on disk, and the
metering log only where a log line IS the deliverable (the per-tick
abstention aggregate) -- reusing OwnershipTestBase from
test_session_ownership_record.py and
_write_drain_status_with_retained_for_ownership from test_drain_staleness.py
rather than building a second harness.

Task 1 adds only the AX-Q1 tracer test (the live defect, reproduced and
fixed). Task 2 widens to the full register, AX-Q2 through AX-Q17.
"""
import os
import time
import unittest

from tests._compat_helpers import argv_to_flags, assert_argv_matches_golden, load_golden
from tests.test_drain_staleness import _write_drain_status_with_retained_for_ownership
from tests.test_session_ownership_record import (
    GOLDEN_SID,
    OLD_TS,
    OwnershipTestBase,
    SID,
    _session_row,
)


class LiveDefectTracerTests(OwnershipTestBase):
    """Task 1's tracer: the live defect, reproduced and fixed end to end."""

    def test_q1_suppressed_new_session_is_not_claimed_by_legacy_and_is_billed_by_the_event_path(self):
        """AX-Q1. The live defect. A brand-new session (rows in NEITHER
        ledger) with legacy emission suppressed must not be claimed
        `legacy` -- that durable claim would make the under-bill permanent
        (api-event-report.sh's ship predicate defers to any `legacy`
        record forever). It must be billed by EXACTLY ONE path: the event
        path, which claims it atomically on the same tick's event stage.

        What a regression here would look like in production: every new
        session created while legacy completions are suppressed and the
        event path is not yet fully live is billed by nobody, silently,
        forever -- this is the defect that blocked wave 7's fleet cutover.
        """
        t = self._setup_tree()
        try:
            self._seed_ready(t)
            self._seed_spool(t)
            _write_drain_status_with_retained_for_ownership(
                t['state_dir'], drained=True, pending_count=0, retained=[])

            # AX-Q16: run the legacy stage with the event path resolved
            # `live` for ITS OWN process too, so the per-tick abstention
            # aggregate fires at `info` severity (not `warn` -- that is
            # AX-Q16's own assertion) -- this is normal cutover flow: the
            # event path claims the session in the same tick.
            legacy_env = {
                'REVENIUM_LEGACY_COMPLETIONS': 'disabled',
                'REVENIUM_EVENT_METERING_MODE': 'live',
            }
            rc, out = self._run_legacy(t, extra_env=legacy_env)
            self.assertEqual(rc, 0, out)

            owner, _baseline = self._owner_record(t)
            self.assertNotEqual(
                owner, 'legacy',
                'legacy must ABSTAIN from claiming a session it will never bill -- '
                f'on the unfixed tree the record names `legacy` and nothing ever bills it. record={owner!r}\n{out}')
            self.assertEqual(self._legacy_completions(t), [],
                             f'legacy must ship nothing for a suppressed brand-new session: {out}')
            self.assertEqual(self._hermes_lines(t), [],
                             'no HERMES: ledger line may be written on the abstain path')

            # The once-per-tick aggregate is the audit record for the
            # abstention (T-jbl-03) -- it must fire exactly once, and at
            # `info` because the event path is live.
            log_text = self._log_text(t)
            abstain_lines = [l for l in log_text.splitlines()
                             if 'legacy declined to claim' in l]
            self.assertEqual(len(abstain_lines), 1,
                             f'expected exactly one per-tick abstention aggregate line, got {abstain_lines!r}')
            self.assertIn('[INFO ]', abstain_lines[0],
                            f'event path was live for this run -- severity must be info: {abstain_lines[0]!r}')
            self.assertNotIn(SID, abstain_lines[0],
                             'the aggregate must name counts only, never a sid (T-jbl-05)')

            rc, out = self._run_event(t, mode='live')
            self.assertEqual(rc, 0, out)

            event_completions = self._event_completions(t)
            self.assertEqual(len(event_completions), 1,
                             f'the event path must claim and bill the abstained session exactly once: {event_completions!r}\n{out}')
            api_lines = self._api_lines(t)
            self.assertEqual(len(api_lines), 1, f'{api_lines!r}')

            owner, _baseline = self._owner_record(t)
            self.assertEqual(owner, 'event',
                             'the event path must claim the session once legacy has abstained')

            # THE PROPERTY, stated as such: the session is billed by EXACTLY
            # ONE path -- never zero, never both. len(hermes_lines) is legacy's
            # ledger evidence, len(api_lines) is the event path's; the total
            # must be non-zero and must be entirely accounted to one side.
            legacy_billed = len(self._hermes_lines(t))
            event_billed = len(self._api_lines(t))
            self.assertEqual(legacy_billed + event_billed, 1,
                             f'exactly one billing ledger line total, got legacy={legacy_billed} event={event_billed}')
            self.assertEqual(legacy_billed, 0, 'legacy must never have billed this session')
            self.assertEqual(event_billed, 1, 'the event path must have billed this session exactly once')
        finally:
            self._teardown_tree(t)


if __name__ == '__main__':
    unittest.main()
