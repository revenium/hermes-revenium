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
fixed). Task 2 widens to the full register, AX-Q2 through AX-Q17, grouped
into classes by axis family (mirroring test_mode_aware_legacy_takeover.py's
convention) so a mutation to one guard fails its own class and only its own
class. AX-Q12 and AX-Q15 are STRUCTURAL/characterisation axes -- each still
gets a real, named, passing test here; they simply carry no mutation row in
tests/mutation_verify_legacy_claim_abstain.py (see that file's
STRUCTURAL_AXES list and each test's own docstring for why).
"""
import json
import os
import sqlite3
import subprocess
import time
import unittest
from pathlib import Path

from tests._compat_helpers import argv_to_flags, assert_argv_matches_golden, load_golden
from tests.test_drain_staleness import _write_drain_status_with_retained_for_ownership
from tests.test_mode_aware_legacy_takeover import _takeover_warns
from tests.test_session_ownership_record import (
    GOLDEN_SID,
    OLD_TS,
    OwnershipTestBase,
    SID,
    _session_row,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / 'skills' / 'revenium' / 'scripts'
HERMES_REPORT = SCRIPTS_DIR / 'hermes-report.sh'

SID_B = 'ownership-sid-002'


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


class SuppressedNonAbstainingLegsTests(OwnershipTestBase):
    """AX-Q2/Q3/Q4: the three suppressed legs that must NOT abstain, because
    the abstention predicate's other two conjuncts (legacy_rows_present,
    event_rows_present) are false. These prove the predicate is exact --
    suppression ALONE is not enough to trigger it."""

    def _abstain_log_lines(self, t):
        return [l for l in self._log_text(t).splitlines()
                if 'legacy declined to claim' in l]

    def test_q2_suppressed_with_legacy_rows_only_legacy_retains_ownership_and_does_not_abstain(self):
        """AX-Q2. Suppressed + LEGACY rows only. The resolution table's
        own-ledger predicate (legacy_rows_present) must keep this leg out of
        the abstain branch -- legacy already has a working delta baseline
        for this session and must retain ownership of it, even while THIS
        tick's emission is suppressed. A regression here would silently
        strip ownership from every already-legacy-owned session the moment
        an operator suppresses completions."""
        t = self._setup_tree()
        try:
            self._seed_legacy_ledger(t)
            # Engage OWNERSHIP_PROTOCOL_ACTIVE via the spool disjunct -- the
            # legacy ledger alone does not engage the protocol (E-8's
            # engagement gate reads EVENT_LEDGER_FILE / OWNERS_DIR / the
            # spool, never the legacy ledger), and this axis is about the
            # suppressed leg WITHIN an engaged protocol, not the separately
            # covered disengaged-install leg (AX-Q13).
            self._seed_spool(t)
            _write_drain_status_with_retained_for_ownership(
                t['state_dir'], drained=True, pending_count=0, retained=[])

            rc, out = self._run_legacy(t, extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})
            self.assertEqual(rc, 0, out)

            owner, _baseline = self._owner_record(t)
            self.assertEqual(owner, 'legacy',
                             'legacy already has rows for this session -- it must retain '
                             f'ownership, not abstain. record={owner!r}\n{out}')
            self.assertEqual(self._legacy_completions(t), [],
                             'emission stays suppressed this tick (unrelated to ownership)')
            self.assertEqual(self._abstain_log_lines(t), [],
                             'this leg must not fire the abstention aggregate at all')
        finally:
            self._teardown_tree(t)

    def test_q3_suppressed_with_event_rows_only_resolution_table_still_backfills_event(self):
        """AX-Q3. Suppressed + EVENT rows only. event_rows_present must keep
        this leg out of the abstain branch -- the resolution table's
        pre-existing backfill (event rows exist -> claim `event`) must still
        fire. A regression here would make legacy re-claim a session the
        event path already has billing history for."""
        t = self._setup_tree()
        try:
            self._seed_event_ledger(t)
            _write_drain_status_with_retained_for_ownership(
                t['state_dir'], drained=True, pending_count=0, retained=[])

            rc, out = self._run_legacy(t, extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})
            self.assertEqual(rc, 0, out)

            owner, _baseline = self._owner_record(t)
            self.assertEqual(owner, 'event',
                             f'the resolution table must still backfill `event`: {owner!r}\n{out}')
            self.assertEqual(self._legacy_completions(t), [])
            self.assertEqual(self._abstain_log_lines(t), [],
                             'this leg must not fire the abstention aggregate at all')
        finally:
            self._teardown_tree(t)

    def test_q4_suppressed_dual_ledger_still_resolves_to_legacy_with_its_catch_up_baseline_and_one_warn(self):
        """AX-Q4. Suppressed + DUAL ledger. PR #54's dual-ledger resolution
        (both ledgers present -> legacy, plus a catch-up baseline, plus a
        once-per-record warn) must be completely unaffected by suppression
        or by the new abstention predicate. A regression here would either
        abstain from a session with clear billing evidence on both sides, or
        drop the catch-up baseline and reintroduce a double-bill window."""
        t = self._setup_tree()
        try:
            self._seed_legacy_ledger(t)
            self._seed_event_ledger(t)
            _write_drain_status_with_retained_for_ownership(
                t['state_dir'], drained=True, pending_count=0, retained=[])

            rc, out = self._run_legacy(t, extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})
            self.assertEqual(rc, 0, out)

            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'legacy')
            self.assertEqual(baseline, '150',
                             'the catch-up baseline must equal the session total at claim instant')
            self.assertEqual(len(self._dual_ledger_warns(t)), 1,
                             'the once-per-record dual-ledger warn must fire exactly once')
            self.assertEqual(self._legacy_completions(t), [])
            self.assertEqual(self._abstain_log_lines(t), [],
                             'this leg must not fire the abstention aggregate at all')
        finally:
            self._teardown_tree(t)


class NotSuppressedByteIdenticalTests(OwnershipTestBase):
    """AX-Q5: not suppressed -- the overwhelming majority of every tick on
    every install. Byte-for-byte against the EXISTING golden, which does not
    move."""

    def test_q5_unsuppressed_claim_is_byte_identical_to_the_golden_even_with_the_protocol_engaged(self):
        """AX-Q5. What a regression here would look like in production: any
        change to the unsuppressed leg's wire output -- the leg every
        session takes on an install with no suppression configured at all.
        The protocol is deliberately ENGAGED (a spool file exists) so this
        test exercises the new hoisted code path, not the disengaged
        install's separate byte-identical guarantee (AX-Q13a)."""
        t = self._setup_tree(sessions=[_session_row(sid=GOLDEN_SID)])
        try:
            self._seed_spool(t, sid=GOLDEN_SID)

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            completions = self._legacy_completions(t)
            self.assertEqual(len(completions), 1, f'{completions!r}\n{out}')
            assert_argv_matches_golden(
                self, completions[0], load_golden('meter-completion-markerless.golden.json'))
            self.assertEqual(len(self._hermes_lines(t, GOLDEN_SID)), 1)
            owner, _baseline = self._owner_record(t, GOLDEN_SID)
            self.assertEqual(owner, 'legacy',
                             'unsuppressed claim resolves to legacy exactly as before this change')
        finally:
            self._teardown_tree(t)


class PerSessionRetainedTests(OwnershipTestBase):
    """AX-Q6: the per-session-vs-global-boolean distinction #57 exists for,
    now proven against the abstention too."""

    def test_q6_two_sessions_one_run_retained_sid_is_claimed_the_other_abstains(self):
        """AX-Q6. Two sessions in ONE run: A is on legacyRetainedSids, B is
        not. A production regression here would mean the abstention reads
        the fleet-global LEGACY_COMPLETIONS_SKIP boolean instead of the
        per-session sid_legacy_suppressed local -- either abstaining for a
        session legacy is still actively emitting for (A), or failing to
        abstain for one it is not (B)."""
        t = self._setup_tree(sessions=[_session_row(sid=SID), _session_row(sid=SID_B)])
        try:
            self._seed_spool(t, sid=SID)
            _write_drain_status_with_retained_for_ownership(
                t['state_dir'], drained=True, pending_count=0, retained=[SID])

            rc, out = self._run_legacy(t, extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})
            self.assertEqual(rc, 0, out)

            owner_a, _ = self._owner_record(t, SID)
            self.assertEqual(owner_a, 'legacy',
                             f'A is retained -- legacy must claim and bill it: {out}')
            self.assertEqual(len(self._hermes_lines(t, SID)), 1)

            owner_b, _ = self._owner_record(t, SID_B)
            self.assertIsNone(owner_b,
                              f'B is NOT retained -- legacy must abstain, writing no record: {out}')
            self.assertEqual(self._hermes_lines(t, SID_B), [])
        finally:
            self._teardown_tree(t)


class SettleGateTests(OwnershipTestBase):
    """AX-Q7: E-4's timeline, modeled directly -- the settle gate only
    DELAYS the claim; the abstention still fires on the tick that actually
    reaches it. States explicitly why a single-session canary is not valid
    evidence on this axis (E-4): legacy wins the COMMON case because it runs
    on a fixed schedule and the classifier's `.ready` sentinel lands after
    at least one legacy tick has already passed the session by."""

    def test_q7_a_session_deferred_by_the_settle_gate_still_abstains_on_the_tick_that_reaches_the_claim(self):
        """AX-Q7. Tick 1: session is inside the settle window with no
        sentinel -- deferred entirely, before the claim block is ever
        reached, so NO record is written. Tick 2: the sentinel lands and the
        tick reaches the claim -- it must still abstain. A regression here
        would mean the abstention only fires for sessions old enough to skip
        the settle gate outright, missing the common case E-4 measured live."""
        recent = time.time() - 2
        t = self._setup_tree(session_kwargs={'started_at': recent, 'ended_at': recent})
        try:
            self._seed_spool(t)
            _write_drain_status_with_retained_for_ownership(
                t['state_dir'], drained=True, pending_count=0, retained=[])
            legacy_env = {'REVENIUM_LEGACY_COMPLETIONS': 'disabled'}

            rc, out = self._run_legacy(t, extra_env=legacy_env)
            self.assertEqual(rc, 0, out)
            owner, _ = self._owner_record(t)
            self.assertIsNone(owner,
                              f'tick 1 must defer before ever reaching the claim: {out}')
            self.assertEqual(self._legacy_completions(t), [])

            self._seed_ready(t)
            rc, out = self._run_legacy(t, extra_env=legacy_env)
            self.assertEqual(rc, 0, out)
            owner, _ = self._owner_record(t)
            self.assertIsNone(owner,
                              f'tick 2 reaches the claim and must abstain, not claim `legacy`: {out}')
            self.assertEqual(self._legacy_completions(t), [])
        finally:
            self._teardown_tree(t)


class RecoveryAndModeRevertTests(OwnershipTestBase):
    """AX-Q8/Q9: what happens AFTER an abstention -- suppression later turns
    off (Route B), or the event path claims and later mode-reverts (#56
    interaction)."""

    def test_q8_re_enabling_legacy_after_an_abstention_claims_and_bills_from_a_clean_baseline(self):
        """AX-Q8. Route B of AX-Q16's recovery bound, proven directly: an
        abstained session (no record) has REVENIUM_LEGACY_COMPLETIONS
        re-enabled on a LATER tick. Legacy must claim it and bill from a
        zero baseline -- and that baseline must stay implicit (no second
        line), never a phantom non-zero floor. A regression here would mean
        the abstain-then-recover path either fails to claim at all, or
        writes a spurious floor that skips billable tokens forever."""
        t = self._setup_tree()
        try:
            self._seed_spool(t)
            _write_drain_status_with_retained_for_ownership(
                t['state_dir'], drained=True, pending_count=0, retained=[])

            rc, out = self._run_legacy(t, extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})
            self.assertEqual(rc, 0, out)
            owner, _ = self._owner_record(t)
            self.assertIsNone(owner, f'fixture: must abstain first: {out}')

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)
            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'legacy',
                             f're-enabling legacy must let it claim the abstained session: {out}')
            self.assertIsNone(baseline,
                              'no phantom baseline -- the record must stay one-line, exactly '
                              'as a fresh zero-row claim always has')
            completions = self._legacy_completions(t)
            self.assertEqual(len(completions), 1, f'{completions!r}\n{out}')
            self.assertEqual(
                argv_to_flags(completions[0]).get('--total-tokens'), '150',
                'nothing was billed before -- the full cumulative total bills exactly once, '
                'never twice')
        finally:
            self._teardown_tree(t)

    def test_q9_the_takeover_still_fires_with_its_floor_after_an_abstention(self):
        """AX-Q9. #56 interaction: legacy abstains, the event path claims
        and ships, and the mode later reverts to `shadow` with legacy
        re-enabled. The mode-aware takeover (#56) must fire exactly as it
        does when the event path was directly seeded as owner (the existing
        AX-02/AX-06 precedent) -- proving the takeover branch does not care
        HOW the `event` record got there. A regression here would mean an
        abstained-then-event-claimed session is invisible to the takeover,
        permanently under-billing it the moment an operator reverts the
        event mode."""
        t = self._setup_tree()
        try:
            self._seed_ready(t)
            self._seed_spool(t)
            _write_drain_status_with_retained_for_ownership(
                t['state_dir'], drained=True, pending_count=0, retained=[])

            rc, out = self._run_legacy(t, extra_env={
                'REVENIUM_LEGACY_COMPLETIONS': 'disabled',
                'REVENIUM_EVENT_METERING_MODE': 'live',
            })
            self.assertEqual(rc, 0, out)
            self.assertIsNone(self._owner_record(t)[0], f'fixture: must abstain first: {out}')

            rc, out = self._run_event(t, mode='live')
            self.assertEqual(rc, 0, out)
            self.assertEqual(self._owner_record(t)[0], 'event', f'fixture: event must claim: {out}')
            self.assertEqual(len(self._api_lines(t)), 1)

            # Mode reverts to shadow (the default), legacy re-enabled: the
            # takeover must fire on the very next legacy tick, shipping
            # NOTHING on the takeover tick itself and recording the floor at
            # the session's current cumulative total.
            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)
            self.assertEqual(self._legacy_completions(t), [],
                             f'the takeover tick must ship nothing: {out}')
            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'legacy')
            self.assertEqual(baseline, '150',
                             'the floor must equal the cumulative total already shipped by '
                             'the event path, never lower')
            self.assertEqual(len(_takeover_warns(self._log_text(t))), 1)

            # Bill forward only: growth after the takeover must ship ONLY
            # the growth, never a re-bill of the 150 the event path already
            # shipped.
            self._grow_state_db(t, input_tokens=200, output_tokens=100)
            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)
            completions = self._legacy_completions(t)
            self.assertEqual(len(completions), 1, f'{completions!r}\n{out}')
            self.assertEqual(argv_to_flags(completions[0]).get('--total-tokens'), '150',
                             'must bill only the 150-token growth (300 cumulative - 150 floor), '
                             'never the 300-token cumulative total')
        finally:
            self._teardown_tree(t)


class RetentionPruningTests(OwnershipTestBase):
    """AX-Q10: retention/pruning of the new record shape -- an abstention
    creates NOTHING to prune."""

    def _run_prune(self, t, *args):
        env = {
            **os.environ,
            'HOME': t['shim_home'],
            'HERMES_HOME': t['hermes_home'],
            'REVENIUM_STATE_DIR': t['state_dir'],
            'PATH': t['bin_dir'] + os.pathsep + os.environ.get('PATH', ''),
            'REVENIUM_MARKER_RETENTION_DAYS': '30',
            'TZ': 'UTC',
        }
        return subprocess.run(
            ['bash', str(SCRIPTS_DIR / 'prune-markers.sh'), *args],
            env=env, capture_output=True, text=True, timeout=60,
        )

    @staticmethod
    def _age_file(path, days):
        old = time.time() - days * 86400
        os.utime(path, (old, old))

    def test_q10_abstention_creates_nothing_to_prune_and_a_live_record_survives(self):
        """AX-Q10. Part 1: an abstained session leaves no owners-dir entry at
        all -- `prune_owners` has nothing to scan, and an absent record
        cannot be mis-pruned. Part 2 (regression guard, reusing the existing
        RetentionOwnershipTests precedent so the SAME live-set-insertion
        anchor is exercised through this axis's own named test): a record a
        LATER, non-abstained claim writes survives however old it is, and
        --dry-run removes nothing."""
        t = self._setup_tree(sessions=[_session_row(sid=SID), _session_row(sid=SID_B)])
        try:
            self._seed_spool(t)
            _write_drain_status_with_retained_for_ownership(
                t['state_dir'], drained=True, pending_count=0, retained=[])
            rc, out = self._run_legacy(t, extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})
            self.assertEqual(rc, 0, out)
            self.assertIsNone(self._owner_record(t)[0], f'fixture: must abstain: {out}')
            self.assertTrue(
                not os.path.isdir(t['owners_dir']) or os.listdir(t['owners_dir']) == [],
                'an abstained run must create no owners-dir entries at all')

            r = self._run_prune(t)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('scanned=0', self._log_text(t),
                          'nothing to prune -- the owners pass must scan zero entries '
                          '(prune-markers.sh writes through info(), which lands in the log '
                          'file, not subprocess stdout/stderr)')

            # Part 2: a live claim's record, however old, still survives.
            self._seed_owner(t, sid=SID_B, owner='legacy')
            self._age_file(self._owners_path(t, SID_B), 90)
            r = self._run_prune(t)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.exists(self._owners_path(t, SID_B)),
                            'a record for a session still in state.db must survive any age')

            r = self._run_prune(t, '--dry-run')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.exists(self._owners_path(t, SID_B)),
                            '--dry-run must remove nothing')
        finally:
            self._teardown_tree(t)


class ConcurrencyOrderingTests(OwnershipTestBase):
    """AX-Q11: the two stages, run in BOTH orders, must each yield exactly
    one biller, and the abstain branch must publish nothing in either
    order."""

    def test_q11_either_stage_order_yields_exactly_one_biller_and_the_abstain_branch_publishes_nothing(self):
        """AX-Q11. Interleaves the LEGACY claim and the EVENT claim in both
        possible orders for an otherwise-identical suppressed brand-new
        session. A regression here would mean the abstention's correctness
        depends on cron's fixed stage order rather than holding for either
        order -- a real risk if a future change reorders cron.sh's stages or
        runs the two reporters concurrently."""
        # Order 1: legacy first, then event.
        t = self._setup_tree()
        try:
            self._seed_ready(t)
            self._seed_spool(t)
            _write_drain_status_with_retained_for_ownership(
                t['state_dir'], drained=True, pending_count=0, retained=[])

            rc, out = self._run_legacy(t, extra_env={
                'REVENIUM_LEGACY_COMPLETIONS': 'disabled',
                'REVENIUM_EVENT_METERING_MODE': 'live',
            })
            self.assertEqual(rc, 0, out)
            self.assertIsNone(self._owner_record(t)[0], 'legacy must abstain, publishing nothing')

            rc, out = self._run_event(t, mode='live')
            self.assertEqual(rc, 0, out)

            self.assertEqual(len(self._hermes_lines(t)), 0)
            self.assertEqual(len(self._api_lines(t)), 1)
            self.assertEqual(self._owner_record(t)[0], 'event')
        finally:
            self._teardown_tree(t)

        # Order 2: event first, then legacy.
        t = self._setup_tree()
        try:
            self._seed_spool(t)
            _write_drain_status_with_retained_for_ownership(
                t['state_dir'], drained=True, pending_count=0, retained=[])

            rc, out = self._run_event(t, mode='live')
            self.assertEqual(rc, 0, out)
            self.assertEqual(self._owner_record(t)[0], 'event',
                             f'the event path claims first in this order: {out}')

            rc, out = self._run_legacy(t, extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})
            self.assertEqual(rc, 0, out)

            self.assertEqual(len(self._hermes_lines(t)), 0,
                             'legacy must never bill a session the event path already claimed')
            self.assertEqual(len(self._api_lines(t)), 1)
            self.assertEqual(self._owner_record(t)[0], 'event',
                             'the abstain branch must not overwrite an existing claim')
        finally:
            self._teardown_tree(t)


class MultiProfileTests(OwnershipTestBase):
    """AX-Q12. STRUCTURAL, argued in PLAN.md: the new code reads exactly
    three fixed, profile-scoped artifacts (LEDGER_FILE, EVENT_LEDGER_FILE,
    DRAIN_STATUS_FILE), each derived from HERMES_HOME/REVENIUM_STATE_DIR,
    with no glob, sweep or wildcard anywhere in the abstention. This test is
    the construction-based proof (mirroring test_a17's AX-13 precedent);
    tests/mutation_verify_legacy_claim_abstain.py's STRUCTURAL_AXES entry
    states plainly that no mutation was constructed for this axis, rather
    than fabricating one."""

    def test_q12_a_sibling_profiles_drain_status_and_owners_do_not_change_this_profiles_verdict(self):
        """AX-Q12. A production regression here would mean a multiplexed
        gateway host reads a SIBLING profile's drain-status.json or owners
        record when deciding whether THIS profile's session abstains --
        exactly the class of defect the Phase 32 cross-profile double-ship
        incident was."""
        t = self._setup_tree()
        try:
            self._seed_spool(t)
            _write_drain_status_with_retained_for_ownership(
                t['state_dir'], drained=True, pending_count=0, retained=[])

            other_state_dir = os.path.join(
                t['hermes_home'], 'profiles', 'otherprofile', 'state', 'revenium')
            other_owners_dir = os.path.join(other_state_dir, 'owners')
            os.makedirs(other_owners_dir, mode=0o700)
            # The sibling profile is NOT suppressed and already has a claim
            # for the SAME sid -- if this profile's abstention read the
            # sibling's state, it would see this and fail to abstain.
            _write_drain_status_with_retained_for_ownership(
                other_state_dir, drained=False, pending_count=1, retained=[SID])
            with open(os.path.join(other_owners_dir, SID), 'w', encoding='utf-8') as f:
                f.write('legacy\n999999\n')

            rc, out = self._run_legacy(t, extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})
            self.assertEqual(rc, 0, out)

            owner, _ = self._owner_record(t)
            self.assertIsNone(owner,
                              "this profile's OWN drain-status.json must decide the outcome, "
                              f"not the sibling's: {out}")

            with open(os.path.join(other_owners_dir, SID), encoding='utf-8') as f:
                self.assertEqual(f.read(), 'legacy\n999999\n',
                                 "the sibling profile's own record must be left untouched")
        finally:
            self._teardown_tree(t)


class DisengagedInstallTests(OwnershipTestBase):
    """AX-Q13a/Q13b: the overwhelming majority of installs -- no event
    ledger, no owners entry, no spool file anywhere."""

    def test_q13a_disengaged_install_is_byte_identical_to_the_markerless_golden_and_creates_no_ownership_state(self):
        """AX-Q13a. OWNERSHIP_PROTOCOL_ACTIVE stays false -- the new hoisted
        `event_rows_present` / `claim_abstain` computation runs (a cheap `-s`
        test that spawns no python3, per the plan's engagement-gate cost
        argument) but the outer guard never reaches the claim block at all.
        A regression here would mean the abstention accidentally engages the
        ownership protocol on an install that has never heard of it."""
        t = self._setup_tree(sessions=[_session_row(sid=GOLDEN_SID)])
        try:
            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            completions = self._legacy_completions(t)
            self.assertEqual(len(completions), 1, f'{completions!r}\n{out}')
            assert_argv_matches_golden(
                self, completions[0], load_golden('meter-completion-markerless.golden.json'))
            self.assertFalse(os.path.exists(t['owners_dir']),
                             'no ownership state may be created on a disengaged install')
        finally:
            self._teardown_tree(t)

    def test_q13b_disengaged_and_suppressed_is_also_unchanged(self):
        """AX-Q13b. Disengaged AND suppressed: the outer guard's
        OWNERSHIP_PROTOCOL_ACTIVE conjunct is already false, so claim_abstain
        being true (it computes as true here) changes nothing -- the claim
        block never runs either way. The EMISSION guard's PRE-EXISTING
        suppression (#57, unrelated to this change) still applies: legacy
        ships nothing this tick, but for the drain-gate reason, not because
        of the new abstention code."""
        t = self._setup_tree()
        try:
            _write_drain_status_with_retained_for_ownership(
                t['state_dir'], drained=True, pending_count=0, retained=[])

            rc, out = self._run_legacy(t, extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})
            self.assertEqual(rc, 0, out)

            self.assertEqual(self._legacy_completions(t), [],
                             f'#57 suppression still applies: {out}')
            self.assertFalse(os.path.exists(t['owners_dir']),
                             'a disengaged install must never create ownership state, '
                             'suppressed or not')
        finally:
            self._teardown_tree(t)


class SourcePropertyTests(unittest.TestCase):
    """AX-Q14: the no-bill-by-construction coupling, checked as a SOURCE
    PROPERTY rather than pinned text -- a test that pins a mechanism defends
    the defective mechanism, and has already failed its own correct fix once
    on this phase (per PLAN.md's framing)."""

    def test_q14_the_abstain_predicate_and_the_emission_guard_read_the_same_local(self):
        """AX-Q14. Property: the abstention predicate's first conjunct and
        the emission guard both read the SAME local, sid_legacy_suppressed,
        declared exactly once per session. A regression that introduced a
        SECOND local (or read a different one, e.g. the fleet-global
        LEGACY_COMPLETIONS_SKIP) at either site would decouple the two and
        make the emission guard's suppression drift from the claim's
        abstention -- reopening exactly the hazard this quick task closes.
        Extracted, not assumed: this file's own critical-context establishes
        there are EXACTLY three read sites for this local -- the abstain
        predicate, the mode-revert takeover branch, and the emission guard
        -- and the new warn-severity branch deliberately reads
        EVENT_PATH_LIVE instead, adding no fourth read."""
        source = HERMES_REPORT.read_text()
        read_sites = [
            line for line in source.splitlines()
            if '${sid_legacy_suppressed}' in line and not line.strip().startswith('#')
        ]
        self.assertEqual(
            len(read_sites), 3,
            'expected exactly three non-comment read sites of sid_legacy_suppressed '
            f'(abstain predicate, takeover branch, emission guard); found {len(read_sites)}: {read_sites!r}')

        abstain_site = [l for l in read_sites if 'legacy_rows_present' in l]
        emission_site = [l for l in read_sites if 'session_event_owned' in l]
        self.assertEqual(len(abstain_site), 1, f'{read_sites!r}')
        self.assertEqual(len(emission_site), 1, f'{read_sites!r}')
        self.assertIn('${sid_legacy_suppressed}', abstain_site[0])
        self.assertIn('${sid_legacy_suppressed}', emission_site[0])


class MigrationCharacterisationTests(OwnershipTestBase):
    """AX-Q15. STRUCTURAL/characterisation: a `legacy` record with no second
    line and zero legacy rows can only have been written by the PRE-FIX
    defect -- a migration state, not a steady state this change produces.
    This diff does not fix it retroactively; the operator remedy (delete
    `owners/<sid>` while the event path is live) is documented in Task 3."""

    def test_q15_a_record_written_by_the_defect_is_characterised_and_the_operator_remedy_is_documented(self):
        """AX-Q15. What a regression here would look like in production: a
        session already stranded by the pre-fix defect (durable `legacy`
        record, zero rows on either ledger) is silently mishandled by the
        fix -- either double-billed, or left permanently unrecoverable with
        no documented remedy. This test characterises the state; the doc
        remedy is verified separately by the docs assertions in Task 3."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='legacy')  # no baseline line -- the defect's exact shape
            # The defect's live signature is a `legacy` record for a session
            # legacy's OWN emission guard is suppressing -- without
            # suppression, legacy's zero-baseline delta billing ships from
            # its ledger regardless of the (irrelevant, to that path) owner
            # record, which would not characterise the stranded state.
            _write_drain_status_with_retained_for_ownership(
                t['state_dir'], drained=True, pending_count=0, retained=[])

            rc, out = self._run_legacy(t, extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})
            self.assertEqual(rc, 0, out)
            self.assertEqual(self._legacy_completions(t), [],
                             'a `legacy`-owned record keeps legacy off the session even '
                             'with no billing evidence')

            rc, out = self._run_event(t, mode='live')
            self.assertEqual(rc, 0, out)
            self.assertEqual(self._event_completions(t), [],
                             f'the event path must still defer to the durable legacy record: {out}')

            owner, baseline = self._owner_record(t)
            self.assertEqual((owner, baseline), ('legacy', None),
                             'the defective record is left exactly as found -- both paths stay '
                             'off the session until an operator applies the documented remedy')
        finally:
            self._teardown_tree(t)


class BoundedRecoveryWarnTests(OwnershipTestBase):
    """AX-Q16: the recoverability window is BOUNDED, and an unclaimable
    abstention is announced. Two halves, one covered by mutation (the warn
    branch), one a characterisation of pre-existing prune_spool_dir
    behaviour (E-14) -- see this test's own docstring for which is which."""

    def test_q16_abstention_recovery_is_bounded_by_spool_retention_and_warns_while_the_event_path_is_not_live(self):
        """AX-Q16. Warn half (mutation-covered): abstain with the event path
        in shadow -- the per-tick aggregate must fire at WARN, exactly once,
        naming counts and never a sid. Contrast with the event path live,
        where it must be INFO (already proven directly by AX-Q1; repeated
        here for contrast within the same axis). Retention half
        (characterisation of pre-existing prune_spool_dir behaviour, NOT
        mutation-covered -- would pass with the abstention removed
        entirely, per E-14): age the abstained session's spool file past
        REVENIUM_MARKER_RETENTION_DAYS, run prune-markers.sh, and prove
        Route A (flip to live) is now closed while Route B (re-enable
        legacy, AX-Q8) still bills the session from state.db. Production
        reading: an operator who leaves the event path in shadow with
        legacy suppressed for longer than the retention window loses the
        event-path recovery route silently, which is why the warn exists."""
        t = self._setup_tree()
        try:
            self._seed_spool(t)
            _write_drain_status_with_retained_for_ownership(
                t['state_dir'], drained=True, pending_count=0, retained=[])

            # --- warn half: event path NOT live -----------------------------
            rc, out = self._run_legacy(t, extra_env={
                'REVENIUM_LEGACY_COMPLETIONS': 'disabled',
                'REVENIUM_EVENT_METERING_MODE': 'shadow',
            })
            self.assertEqual(rc, 0, out)
            self.assertIsNone(self._owner_record(t)[0], f'fixture: must abstain: {out}')

            log_text = self._log_text(t)
            abstain_lines = [l for l in log_text.splitlines() if 'legacy declined to claim' in l]
            self.assertEqual(len(abstain_lines), 1, f'{abstain_lines!r}')
            self.assertIn('[WARN ]', abstain_lines[0],
                          'the event path is NOT live -- nobody claims this tick, so the '
                          f'aggregate must be a warn: {abstain_lines[0]!r}')
            self.assertNotIn(SID, abstain_lines[0], 'names counts only, never a sid')

            # --- retention half: age the spool, prune, close Route A -------
            spool_path = os.path.join(t['spool_dir'], f'{SID}.jsonl')
            self.assertTrue(os.path.exists(spool_path), 'fixture: spool file must exist')
            old = time.time() - 31 * 86400
            os.utime(spool_path, (old, old))

            prune_env = {
                **os.environ,
                'HOME': t['shim_home'],
                'HERMES_HOME': t['hermes_home'],
                'REVENIUM_STATE_DIR': t['state_dir'],
                'PATH': t['bin_dir'] + os.pathsep + os.environ.get('PATH', ''),
                'REVENIUM_MARKER_RETENTION_DAYS': '30',
                'TZ': 'UTC',
            }
            r = subprocess.run(
                ['bash', str(SCRIPTS_DIR / 'prune-markers.sh')],
                env=prune_env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(os.path.exists(spool_path),
                             'Route A input (the spool file) must be pruned past retention')

            rc, out = self._run_event(t, mode='live')
            self.assertEqual(rc, 0, out)
            self.assertEqual(self._event_completions(t), [],
                             'Route A is closed -- flipping to live recovers nothing once the '
                             f'spool is gone: {out}')

            # Route B still works: state.db was never pruned.
            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)
            completions = self._legacy_completions(t)
            self.assertEqual(len(completions), 1,
                             f'Route B must still bill from state.db: {completions!r}\n{out}')
            self.assertEqual(argv_to_flags(completions[0]).get('--total-tokens'), '150',
                             'zero-baseline claim bills the full cumulative total, per E-5 '
                             'correct-by-design, not an over-bill')
        finally:
            self._teardown_tree(t)


class JobsGatingTests(OwnershipTestBase):
    """AX-Q17: the jobs-create / jobs-outcome gating for an abstained
    session must be unmoved -- mirroring
    test_event_owned_session_still_creates_its_job_exactly_once, the same
    assertion for the event-owned leg."""

    def test_q17_abstention_does_not_change_job_creation_or_outcome_gating(self):
        """AX-Q17. What a regression here would look like in production: a
        future refactor adds an early `continue` on the abstain path
        (modelling "why do work for a session we do not own"), which would
        orphan the session's `--agentic-job-id` reference in every event row
        the event path later ships -- while EVERY billing axis, including
        AX-Q1, would still pass, because the event path still bills the
        session correctly. AX-Q17 is the only axis that catches this. The
        jobs stages sit OUTSIDE the ownership guard for the measured D-10
        reason recorded at hermes-report.sh:2197-2213 (api-event-report.sh
        ships --agentic-job-id but contains zero `jobs create` calls)."""
        t = self._setup_tree()
        try:
            self._seed_spool(t)
            self._seed_job_marker(t)
            _write_drain_status_with_retained_for_ownership(
                t['state_dir'], drained=True, pending_count=0, retained=[])

            rc, out = self._run_legacy(t, extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})
            self.assertEqual(rc, 0, out)

            self.assertIsNone(self._owner_record(t)[0], f'fixture: must abstain: {out}')
            self.assertEqual(self._legacy_completions(t), [],
                             'completions must stay suppressed on the abstain path')

            creates = self._job_creates(t)
            self.assertEqual(len(creates), 1,
                             'the jobs half must keep running for an abstained session (D-10) '
                             f'-- expected exactly one `jobs create`, got {creates!r}\n{out}')
            self.assertEqual(argv_to_flags(creates[0]).get('--agentic-job-id'),
                             'ownership-job-001')

            # No `_job_outcomes` helper exists in the harness (per PLAN.md's
            # read_first note) -- filter outcomes from the raw invocation
            # log directly. The job marker never signals completion, so
            # outcome gating stays exactly as unmoved as job creation.
            outcomes = [a for a in self._invocations(t['jobs_log'])
                       if len(a) >= 2 and a[0] == 'jobs' and a[1] == 'outcome']
            self.assertEqual(outcomes, [],
                             'outcome gating is unmoved -- no completion signal was seeded, '
                             'so no outcome call fires, on the abstain path exactly as before it')
        finally:
            self._teardown_tree(t)


if __name__ == '__main__':
    unittest.main()
