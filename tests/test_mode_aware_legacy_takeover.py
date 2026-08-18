"""quick-260818-0in (MODE-01..05) — mode-aware legacy skip for the
event-owned / mode-revert hazard.

PR #54 made session ownership durable: once a record says `event`, the
legacy path deferred to it FOREVER, regardless of whether the event path was
still actually shipping. That is correct while the event path is live, and a
silent, permanent under-bill the instant an operator reverts
`REVENIUM_EVENT_METERING_MODE` (or `eventMeteringMode`) from `live` back to
`shadow` (or the switch was never `live` and the record was merely
backfilled from stray ledger rows): the record still says `event`, so
legacy keeps deferring, and the event path ships nothing under `shadow` —
billing NEITHER path, permanently.

Operator decision (2026-08-18, recorded in
.planning/phases/32-event-driven-metering-on-post-api-request/.continue-here.md):
option (a), mode-aware legacy skip. The legacy path defers to an `event`
owner ONLY while the event path is actually live (MODE-01); otherwise it
takes the session over, records a catch-up floor at the takeover instant so
tokens the event path already shipped are never re-billed (MODE-02), and
flips the record to `legacy` durably and one-way so a later shadow->live
mode flip cannot resurrect a second biller (MODE-03). The liveness
predicate is resolved through the IDENTICAL resolve_switch_setting code,
config key and `shadow` default api-event-report.sh uses (MODE-04). No
takeover fires while legacy emission is itself disabled by the drain gate
(MODE-05).

This module widens across two tasks:
  Task 1 (this tracer) — one test per <behavior> bullet, named for its axis
    ID from PLAN.md's <axis_register>: A1 (mode live, unchanged defer),
    A2 (mode shadow, takeover), A6 (bill forward, never re-bill), A16 (the
    one-way flip survives a later live flip), A11 (no takeover while legacy
    emission is disabled), A21 (a disengaged install is unchanged).
  Task 2 — widens to the FULL axis register (A1 through A24), grouped by
    axis family, each test's docstring stating the axis, what it asserts,
    and what a production regression on it would look like.

Each test is named for the axis it covers, so a mutation to one guard fails
its own test and only its own test (see tests/mutation_verify_takeover.py).
Assertions are on the SHIPPING surfaces — captured argv, the ledger/owners
files on disk, and the metering log only where a log line IS the
deliverable (the once-per-record takeover warn) — reusing
OwnershipTestBase from test_session_ownership_record.py rather than
building a second harness.
"""
import json
import os
import unittest

from tests._compat_helpers import (
    argv_to_flags,
    assert_argv_matches_golden,
    load_golden,
)
from tests.test_session_ownership_record import (
    GOLDEN_SID,
    OLD_TS,
    OwnershipTestBase,
    SID,
    _session_row,
)


def _write_drain_status(state_dir, drained, pending_count=0):
    path = os.path.join(state_dir, 'drain-status.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'drained': drained, 'pendingCount': pending_count}, f)
    return path


def _takeover_warns(log_text, sid=SID):
    needle = 'session ownership taken over from the event path'
    return [l for l in log_text.splitlines() if needle in l and sid in l]


class ModeAwareTakeoverTracerTests(OwnershipTestBase):
    """Task 1's tracer: one axis per <behavior> bullet, proving the thin
    vertical slice end to end before Task 2 widens to the full register."""

    # --- AX-01: mode = live -------------------------------------------

    def test_a1_mode_live_event_owned_session_still_defers_unchanged(self):
        """AX-01. What a regression here would look like in production: a
        live event path stops being the sole biller for a session it is
        actively shipping — a double-bill, the exact class #54 exists to
        prevent."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event')

            rc, out = self._run_legacy(t, extra_env={'REVENIUM_EVENT_METERING_MODE': 'live'})
            self.assertEqual(rc, 0, out)

            self.assertEqual(self._legacy_completions(t), [],
                             'a live event owner must never be billed by the legacy path')
            self.assertEqual(self._hermes_lines(t), [],
                             'no HERMES: line may be written while the event path is live')
            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'event', 'byte-identical to today: no takeover')
            self.assertIsNone(baseline,
                              'a one-line record with no floor must stay one-line — mode '
                              '`live` must not touch the record at all')
        finally:
            self._teardown_tree(t)

    # --- AX-02: mode = shadow -------------------------------------------

    def test_a2_mode_shadow_takes_over_records_the_floor_and_ships_nothing_on_the_takeover_tick(self):
        """AX-02. What a regression here would look like in production: an
        operator reverts the mode to `shadow` and the session's growth is
        billed by NEITHER reporter forever — the exact hazard this quick
        task exists to close."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event')

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            self.assertEqual(self._legacy_completions(t), [],
                             f'the takeover tick must ship NOTHING: {out}')
            self.assertEqual(self._hermes_lines(t), [])
            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'legacy',
                             'mode=shadow (the default) must take the session over')
            self.assertEqual(baseline, '150',
                             'the recorded floor must equal the session cumulative total '
                             '(100 input + 50 output) at the takeover instant')
            warns = _takeover_warns(self._log_text(t))
            self.assertEqual(len(warns), 1,
                             f'exactly one takeover warn naming the session: {self._log_text(t)!r}')
        finally:
            self._teardown_tree(t)

    # --- AX-06: bill forward, never re-bill ------------------------------

    def test_a6_growth_after_takeover_bills_only_the_growth_not_the_cumulative_total(self):
        """AX-06. What a regression here would look like in production: the
        takeover's floor is ignored (or computed wrong) and the session's
        ENTIRE cumulative history is re-billed the first time it grows after
        the takeover — the load-bearing double-bill failure MODE-02 exists
        to prevent."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event')

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)
            self.assertEqual(self._owner_record(t), ('legacy', '150'), 'fixture: takeover landed')

            # 150 -> 300 (input 100->200, output 50->100): a clean 2x growth
            # so the ratio-scaled delta math (hermes-report.sh scales each
            # of input/output by (curr-prev)/curr, via int() truncation, not
            # round()) divides evenly and cannot mask a re-bill behind
            # floating-point truncation noise.
            growth = 150
            self._grow_state_db(t, input_tokens=200, output_tokens=100)
            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            completions = self._legacy_completions(t)
            self.assertEqual(len(completions), 1, f'{completions!r}\n{out}')
            flags = argv_to_flags(completions[0])
            self.assertEqual(
                flags.get('--total-tokens'), str(growth),
                'must bill the GROWTH (150) only — billing the 300-token cumulative total '
                f'means the 150 tokens the event path already shipped were re-billed. '
                f'argv: {completions[0]!r}')
        finally:
            self._teardown_tree(t)

    # --- AX-12 (in-tree proxy): the one-way flip survives a mode flip ----

    def test_a16_a_live_event_shipper_after_the_takeover_ships_nothing_the_flip_is_one_way(self):
        """AX-12/A16. What a regression here would look like in production:
        an operator flips the mode back to `live` after a takeover and the
        event path resumes shipping the SAME session the legacy path is now
        also billing — a double-bill reachable by one operator action, the
        exact failure F-3's one-way flip exists to prevent."""
        t = self._setup_tree()
        try:
            self._seed_spool(t)
            self._seed_ready(t)
            self._seed_owner(t, owner='event')

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)
            self.assertEqual(self._owner_record(t)[0], 'legacy', 'fixture: takeover landed')

            rc, out = self._run_event(t, mode='live')
            self.assertEqual(rc, 0, out)

            self.assertEqual(self._event_completions(t), [],
                             f'a shadow->live flip AFTER a takeover must produce ZERO event '
                             f'completions for this session: {out}')
            self.assertEqual(self._api_lines(t), [])
            self.assertEqual(self._owner_record(t)[0], 'legacy',
                             'the event path must never rewrite a legacy-owned record')
        finally:
            self._teardown_tree(t)

    # --- AX-08: legacy disabled by the drain gate ------------------------

    def test_a11_no_takeover_while_legacy_emission_is_disabled_record_untouched(self):
        """AX-08. What a regression here would look like in production: an
        operator who has disabled legacy emission (draining toward the
        event path) sees ownership flip to `legacy` anyway — converting a
        state that HEALS when the mode returns to `live` into one that
        cannot, because legacy is disabled AND the event path now defers
        forever."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event')
            _write_drain_status(t['state_dir'], drained=True)

            rc, out = self._run_legacy(t, extra_env={'REVENIUM_LEGACY_COMPLETIONS': 'disabled'})
            self.assertEqual(rc, 0, out)

            self.assertEqual(self._legacy_completions(t), [], out)
            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'event',
                             'no takeover fires while legacy emission is disabled, even '
                             'under mode=shadow (the default here)')
            self.assertIsNone(baseline)
        finally:
            self._teardown_tree(t)

    # --- AX-17 (golden half): a disengaged install is unchanged ----------

    def test_a21_disengaged_install_meters_byte_identically_and_creates_no_ownership_state(self):
        """AX-17 (golden half). What a regression here would look like in
        production: the overwhelming majority of installs — which have
        never heard of the event path — start spawning extra python3
        processes or emitting a different wire shape, purely because this
        quick task landed."""
        t = self._setup_tree(sessions=[_session_row(sid=GOLDEN_SID)])
        try:
            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            completions = self._legacy_completions(t)
            self.assertEqual(len(completions), 1, f'{completions!r}\n{out}')
            assert_argv_matches_golden(
                self, completions[0], load_golden('meter-completion-markerless.golden.json'))
            self.assertEqual(len(self._hermes_lines(t, GOLDEN_SID)), 1)
            self.assertFalse(os.path.exists(t['owners_dir']),
                             'a disengaged install must create NO ownership state — the '
                             'engagement gate keeps EVENT_PATH_LIVE unreachable')
        finally:
            self._teardown_tree(t)


if __name__ == '__main__':
    unittest.main()
