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
import shutil
import sqlite3
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

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

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / 'skills' / 'revenium' / 'scripts'
HERMES_REPORT = SCRIPTS_DIR / 'hermes-report.sh'


def _extract_takeover_heredoc():
    """Extract the `_takeover_session_owner` python3 heredoc body from
    hermes-report.sh, mirroring the extract-from-source idiom already used
    for the claim filename derivation (test_repository.py) and the
    model-cleaning equivalence — the anti-drift technique for exercising a
    heredoc's REAL behavior rather than a hand-copied re-implementation of
    it that could silently diverge from the shipped code."""
    lines = HERMES_REPORT.read_text().splitlines()
    fn_start = None
    for i, line in enumerate(lines):
        if '_takeover_session_owner() {' in line:
            fn_start = i
            break
    assert fn_start is not None, 'could not find _takeover_session_owner in hermes-report.sh'
    heredoc_start = None
    for i in range(fn_start, len(lines)):
        if "<<'PY' 2>/dev/null" in lines[i]:
            heredoc_start = i
            break
    assert heredoc_start is not None, "could not find the takeover primitive's heredoc opening"
    body = []
    for j in range(heredoc_start + 1, len(lines)):
        if lines[j].strip() == 'PY':
            break
        body.append(lines[j])
    assert body, 'extracted an empty heredoc body — extraction anchors likely drifted'
    return '\n'.join(body)


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


# ============================================================================
# Task 2 — the FULL axis register, A1 through A24 (AX-20 is argued
# structurally in the SUMMARY, not asserted here; A1/A2/A6/A11/A16/A21 are
# the tracer's own tests above and are not repeated).
# ============================================================================


class ModeResolutionTests(OwnershipTestBase):
    """AX-03, AX-04, AX-05: the liveness predicate's resolution precedence
    (env > config.json > hard "shadow" default) and its fallback-and-warn
    behaviour on an invalid value — the SAME resolve_switch_setting contract
    api-event-report.sh already relies on, exercised from the legacy side."""

    def test_a3_mode_unset_no_env_no_config_resolves_to_shadow_and_takes_over(self):
        """AX-03. A production regression here means a fresh install with no
        operator-set mode at all (the overwhelmingly common case for any
        install that has an event-owned record but never explicitly touched
        the switch) never takes an event-owned session over."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event')
            self.assertFalse(os.path.exists(os.path.join(t['state_dir'], 'config.json')),
                             'fixture: no config.json')

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'legacy')
            self.assertEqual(baseline, '150')
        finally:
            self._teardown_tree(t)

    def test_a4_mode_invalid_falls_back_to_shadow_takes_over_and_warns_once(self):
        """AX-04. A production regression here means a typo'd mode value
        either silently starts billing twice (if it fell back to "live") or
        an operator gets no signal that their setting was ignored."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event')

            rc, out = self._run_legacy(t, extra_env={'REVENIUM_EVENT_METERING_MODE': 'bogus-value'})
            self.assertEqual(rc, 0, out)

            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'legacy', 'an unrecognised value must fall back to shadow')
            self.assertEqual(baseline, '150')
            warns = [l for l in self._log_text(t).splitlines()
                     if 'REVENIUM_EVENT_METERING_MODE/eventMeteringMode had an unrecognised value' in l]
            self.assertEqual(len(warns), 1,
                             f'must warn exactly once per run, never silently: {self._log_text(t)!r}')
        finally:
            self._teardown_tree(t)

    def test_a5_mode_from_config_json_env_unset_a_config_sourced_live_defers(self):
        """AX-05. Proves the config.json precedence leg is actually
        reachable, not merely the environment leg wearing a different name —
        a production regression here means an operator who sets
        eventMeteringMode in config.json (rather than the env var) gets no
        effect at all, and the legacy path silently takes over a live
        session."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event')
            config_path = os.path.join(t['state_dir'], 'config.json')
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump({'eventMeteringMode': 'live'}, f)

            rc, out = self._run_legacy(t)  # env deliberately left unset
            self.assertEqual(rc, 0, out)

            self.assertEqual(self._legacy_completions(t), [], out)
            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'event',
                             'a config.json-sourced live must defer, exactly like an '
                             'env-sourced live')
            self.assertIsNone(baseline)
        finally:
            self._teardown_tree(t)


class BillForwardAndFloorTests(OwnershipTestBase):
    """AX-06, AX-07: the takeover bills forward only, and the floor is a
    max(), never an assignment, read fresh from the durable record on every
    tick rather than cached or special-cased to the claim tick."""

    def test_a7_a_second_growth_after_the_first_bills_only_that_growth_too(self):
        """AX-06. A production regression here means the floor is a
        one-time snapshot rather than a durable re-basis — the SECOND
        post-takeover tick re-bills from the original catch-up point instead
        of from the ledger's own running total."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event')
            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)
            self.assertEqual(self._owner_record(t), ('legacy', '150'), 'fixture: takeover landed')

            self._grow_state_db(t, input_tokens=200, output_tokens=100)  # 150 -> 300
            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)
            first = self._legacy_completions(t)
            self.assertEqual(len(first), 1, f'{first!r}\n{out}')
            self.assertEqual(argv_to_flags(first[0]).get('--total-tokens'), '150')

            # 300 -> 600: a clean ratio (growth/curr = 300/600 = 0.5, exact in
            # binary floating point) so the ratio-scaled delta math cannot
            # mask a re-bill behind truncation noise (a 2/7-style ratio here
            # measurably undershoots by 1-2 tokens per field via int(), not
            # round() — see the A6 tracer test's identical note).
            self._grow_state_db(t, input_tokens=400, output_tokens=200)
            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)
            completions = self._legacy_completions(t)
            self.assertEqual(len(completions), 2, f'{completions!r}\n{out}')
            self.assertEqual(
                argv_to_flags(completions[1]).get('--total-tokens'), '300',
                'the SECOND growth must bill only its own 300-token delta, not 450 '
                '(600 minus the ORIGINAL 150 floor) — the floor is a one-time catch-up, '
                f'never a permanent re-basis. argv: {completions[1]!r}')
        finally:
            self._teardown_tree(t)

    def test_a8_the_floor_is_read_fresh_from_the_durable_record_on_every_later_tick(self):
        """AX-07. A production regression here means the floor only applies
        on the exact tick the takeover happened — a restart, a prune of
        unrelated markers, or simply the next cron tick would re-open the
        re-bill this quick task exists to close."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event')
            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)
            self.assertEqual(self._owner_record(t), ('legacy', '150'))

            for _ in range(3):
                rc, out = self._run_legacy(t)
                self.assertEqual(rc, 0, out)
            self.assertEqual(self._legacy_completions(t), [],
                             'three further ticks with no growth must ship nothing')
            self.assertEqual(self._owner_record(t), ('legacy', '150'),
                             'the floor must still be exactly what the takeover recorded')
        finally:
            self._teardown_tree(t)

    def test_a9_a_corrupt_second_line_yields_a_floor_equal_to_the_session_total_never_lower(self):
        """AX-07. A production regression here means a truncated or
        corrupted floor silently degrades to a LOWER value than the session
        actually had, re-opening exactly the re-bill window MODE-02 closes."""
        t = self._setup_tree()
        try:
            os.makedirs(t['owners_dir'], mode=0o700, exist_ok=True)
            with open(self._owners_path(t), 'w', encoding='utf-8') as f:
                f.write('event\n')
                f.write('not-a-number\n')

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'legacy')
            self.assertEqual(baseline, '150',
                             'an unparseable prior baseline must never LOWER the floor '
                             'below the session total at the takeover instant')
        finally:
            self._teardown_tree(t)

    def test_a10_a_higher_pre_existing_floor_is_preserved_after_the_flip(self):
        """AX-07. A production regression here means the never-lower rule is
        implemented as an assignment rather than a max() — a takeover would
        LOWER an already-correct floor (e.g. one recorded by a prior
        dual-ledger claim), reopening a re-bill window that was already
        closed."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event', baseline=99999)

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'legacy')
            self.assertEqual(baseline, '99999',
                             'the never-lower rule must preserve a pre-existing floor '
                             'higher than the session total at the takeover instant')
        finally:
            self._teardown_tree(t)


class GuardCompositionTests(OwnershipTestBase):
    """AX-09: a takeover write failure must defer, never bill from a zero
    baseline — asserted both directly on the extracted primitive (the
    strong proof) and structurally on the branch that consumes its output
    (the weaker, but independently reachable, proof)."""

    def test_a12a_the_takeover_primitive_prints_nothing_on_a_write_failure(self):
        """AX-09 (strong half). Runs the REAL heredoc body, extracted
        verbatim from hermes-report.sh, standalone against a directory it
        cannot write to — proving the primitive's own contract rather than a
        hand-copied re-implementation of it."""
        code = _extract_takeover_heredoc()
        tmp = tempfile.mkdtemp(prefix='gsd-ax09-')
        try:
            owners_dir = os.path.join(tmp, 'owners')
            os.makedirs(owners_dir, mode=0o500)
            try:
                env = {
                    **os.environ,
                    'OWNERS_DIR': owners_dir,
                    'STATE_DB': '',
                    'TAKEOVER_SID': SID,
                    'TAKEOVER_REQUESTED_BASELINE': '150',
                    'TAKEOVER_KNOWN_BASELINE': '0',
                }
                result = subprocess.run(
                    ['python3', '-c', code], env=env,
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(
                    result.stdout, '',
                    f'the primitive must print NOTHING on a write failure: '
                    f'stdout={result.stdout!r} stderr={result.stderr!r}')
            finally:
                os.chmod(owners_dir, 0o700)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipIf(os.geteuid() == 0, 'root defeats mode bits')
    def test_a12b_the_branch_that_consumes_empty_takeover_output_defers_rather_than_bills(self):
        """AX-09 (structural half, weaker by design — the plan says so and
        this is why). MEASURED, not assumed: an owners_dir permission
        failure does NOT isolate a takeover-specific failure from a
        claim failure. `_claim_session_owner` optimistically attempts its
        OWN mkstemp-based create on every call, even when the record
        already exists (the FileExistsError read-path only triggers once
        os.link finds the target already present) — so an unwritable
        owners_dir breaks mkstemp inside the CLAIM first, well before the
        takeover is ever reached, and the claim's own OWN-04 fail-open
        (legacy bills) fires instead. Confirmed empirically: the naive
        version of this fixture (seed a record, chmod the dir read-only,
        run legacy, expect a defer) instead shipped a completion — proving
        the empty-takeover-output branch is genuinely NOT reachable
        end-to-end through the public surface with a simple permission
        fixture, exactly as the plan warned. This is therefore a STATIC
        assertion on the source instead: the code that consumes empty
        takeover output must defer (increment takeover_unavailable_count,
        leave session_event_owned true) and must not fall through to any
        billing path — paired with A12a's dynamic proof that the primitive
        itself produces empty output on a real write failure."""
        text = HERMES_REPORT.read_text()
        stripped = '\n'.join(ln for ln in text.splitlines() if not ln.lstrip().startswith('#'))
        marker = 'if [[ -z "${takeover_output}" ]]; then'
        self.assertIn(marker, stripped,
                      'could not find the empty-takeover-output branch — extraction '
                      'anchor likely drifted')
        idx = stripped.index(marker)
        branch = stripped[idx:idx + 900]
        self.assertIn('((takeover_unavailable_count++))', branch,
                      'empty takeover output must increment takeover_unavailable_count')
        self.assertIn('session_event_owned="true"', branch,
                      'empty takeover output must defer (session_event_owned stays true), '
                      'never fall through to a billing path')
        else_idx = branch.index('else')
        self.assertLess(
            branch.index('session_event_owned="true"'), else_idx,
            'the defer must be in the empty-output branch, not the success branch')


class OrderingTicksOscillationTests(OwnershipTestBase):
    """AX-10, AX-11: the guard behaves identically regardless of which
    script cron happens to run first in a tick, and repeated ticks over a
    permanent state never double-ship or double-warn."""

    def test_a13_mode_live_cron_order_still_yields_exactly_one_biller_for_a_fresh_session(self):
        """AX-10. A production regression here means the mode-aware guard
        introduces non-determinism into the base #54 partition for a
        session with no prior owner — cron always runs the legacy stage
        before the event stage, and that ordering must keep producing
        exactly one biller regardless of EVENT_PATH_LIVE."""
        t = self._setup_tree()
        try:
            self._seed_spool(t)
            self._seed_ready(t)

            rc, out = self._run_legacy(t, extra_env={'REVENIUM_EVENT_METERING_MODE': 'live'})
            self.assertEqual(rc, 0, out)
            rc, out = self._run_event(t, mode='live')
            self.assertEqual(rc, 0, out)

            total = len(self._legacy_completions(t)) + len(self._event_completions(t))
            self.assertEqual(total, 1, f'exactly one biller, got {total}')
        finally:
            self._teardown_tree(t)

    def test_a14_mode_shadow_cron_order_takes_over_and_still_yields_exactly_one_biller(self):
        """AX-10. The mode-revert scenario framed as cron's own fixed stage
        order: legacy takes over first (shipping nothing on the takeover
        tick), then the event stage runs in the SAME tick under the SAME
        reverted mode and must not also ship."""
        t = self._setup_tree()
        try:
            self._seed_spool(t)
            self._seed_ready(t)
            self._seed_owner(t, owner='event')

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)
            rc, out = self._run_event(t, mode='shadow')
            self.assertEqual(rc, 0, out)

            self.assertEqual(self._owner_record(t)[0], 'legacy')
            total = len(self._legacy_completions(t)) + len(self._event_completions(t))
            self.assertEqual(total, 0,
                             f'the takeover tick ships nothing and shadow mode ships '
                             f'nothing — exactly zero completions, got {total}')
        finally:
            self._teardown_tree(t)

    def test_a15_repeated_ticks_over_a_taken_over_record_ship_nothing_extra_and_warn_once(self):
        """AX-11. A production regression here means a taken-over session
        re-warns (or worse, re-bills) on every subsequent cron tick forever
        — the same unbounded per-tick-warn defect this repo has already
        paid millions of log lines for, reintroduced on a new code path."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event')

            for _ in range(3):
                rc, out = self._run_legacy(t)
                self.assertEqual(rc, 0, out)

            self.assertEqual(self._legacy_completions(t), [])
            self.assertEqual(sorted(os.listdir(t['owners_dir'])), [SID])
            warns = _takeover_warns(self._log_text(t))
            self.assertEqual(len(warns), 1,
                             f'three ticks over a permanent taken-over record must produce '
                             f'exactly ONE takeover warn: {self._log_text(t)!r}')
        finally:
            self._teardown_tree(t)


class ProfilesConcurrencyRetentionTests(OwnershipTestBase):
    """AX-13, AX-14, AX-15, AX-21: the guard is scoped to one profile's own
    state by construction, a racing legacy-vs-legacy interleaving conserves
    (at most one ship, floor never lower), the record's retention lifetime
    is unaffected, and a straddling out-of-band live shipment cannot be
    re-billed."""

    def test_a17_a_sibling_profiles_config_and_owners_do_not_affect_this_profile(self):
        """AX-13. hermes-report.sh has no cross-profile read path anywhere
        in the mode resolution or the takeover — HERMES_HOME/
        REVENIUM_STATE_DIR scope every file this run touches to one
        profile's own home. A production regression here would mean a
        multiplexed gateway host reading a SIBLING profile's config or
        owners record, exactly the class of defect the Phase 32 cross-
        profile double-ship incident was."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event')

            other_state_dir = os.path.join(
                t['hermes_home'], 'profiles', 'otherprofile', 'state', 'revenium')
            other_owners_dir = os.path.join(other_state_dir, 'owners')
            os.makedirs(other_owners_dir, mode=0o700)
            with open(os.path.join(other_state_dir, 'config.json'), 'w', encoding='utf-8') as f:
                json.dump({'eventMeteringMode': 'live'}, f)
            other_record_path = os.path.join(other_owners_dir, SID)
            with open(other_record_path, 'w', encoding='utf-8') as f:
                f.write('legacy\n999999\n')

            rc, out = self._run_legacy(t)  # this profile's own env: mode unset -> shadow
            self.assertEqual(rc, 0, out)

            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'legacy',
                             "this profile's own resolution (shadow) must decide the "
                             "outcome, not the sibling profile's config.json saying live")
            self.assertEqual(baseline, '150')

            with open(other_record_path, encoding='utf-8') as f:
                self.assertEqual(f.read(), 'legacy\n999999\n',
                                 "the sibling profile's own record must be left untouched")
        finally:
            self._teardown_tree(t)

    def test_a18_two_legacy_runs_racing_an_event_owned_session_in_shadow_conserve(self):
        """AX-14. Driven deterministically per AtomicClaimTests' own idiom:
        a lost race and a pre-existing record are the SAME on-disk state, so
        seeding the record as the state it would be in immediately after
        ONE racer's takeover already landed faithfully simulates the
        interleaving without depending on real thread timing. The
        conservation property (floor never lower, at most one ship) is what
        actually matters — a takeover tick can never itself bill (its own
        floor is always >= its own total), so a second racer converging on
        an already-taken-over record ships nothing and cannot lower the
        floor the first racer recorded."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='legacy', baseline=150)

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            self.assertEqual(self._legacy_completions(t), [],
                             'at most one completion between two racers — here, zero, '
                             'since the floor already equals the pre-takeover total')
            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'legacy')
            self.assertEqual(int(baseline), 150,
                             'the floor must never be LOWER than the pre-takeover total '
                             'the other racer already recorded')
        finally:
            self._teardown_tree(t)

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

    def test_a19_after_a_takeover_the_owners_dir_holds_one_entry_pruned_by_state_db_presence(self):
        """AX-15. A production regression here means a taken-over record
        either vanishes while the session is still live (P1-2's own class of
        defect) or accumulates forever after the session is gone."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event')
            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)
            self.assertEqual(self._owner_record(t)[0], 'legacy')
            self.assertEqual(sorted(os.listdir(t['owners_dir'])), [SID])

            old = time.time() - 90 * 86400
            os.utime(self._owners_path(t), (old, old))
            r = self._run_prune(t)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.exists(self._owners_path(t)),
                            'a live session (still in state.db) must survive pruning '
                            'however old its record is')

            conn = sqlite3.connect(t['state_db'])
            conn.execute('DELETE FROM sessions WHERE id=?', (SID,))
            conn.commit()
            conn.close()
            r = self._run_prune(t)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(os.path.exists(self._owners_path(t)),
                             'once absent from state.db, the record must be removed')
        finally:
            self._teardown_tree(t)

    def test_a25_a_stale_snapshot_baseline_is_floored_out_by_the_publish_instant_reread(self):
        """AX-21. Deterministic fixture, not a race: `requested` below
        stands in for hermes-report.sh's own possibly-stale total_tokens
        (main() takes ONE sqlite3 snapshot at process start and carries it
        down the whole per-session loop), while state.db is set to a
        HIGHER, ADVANCED value — standing in for an out-of-band `live`
        api-event-report.sh invocation that shipped the difference and
        updated `sessions` between the snapshot and this takeover. A
        production regression here means a session is billed twice for the
        straddled tokens, invisible in both ledgers because each side's own
        idempotency record stays intact. The residual — tokens not yet in
        `sessions` at publish, or shipped after the replace — is accepted,
        bounded exposure, not something this test (or the guard) closes."""
        code = _extract_takeover_heredoc()
        tmp = tempfile.mkdtemp(prefix='gsd-ax21-')
        try:
            owners_dir = os.path.join(tmp, 'owners')
            os.makedirs(owners_dir, mode=0o700)
            state_db = os.path.join(tmp, 'state.db')
            conn = sqlite3.connect(state_db)
            conn.execute(
                'CREATE TABLE sessions (id TEXT, input_tokens INTEGER, output_tokens INTEGER)')
            conn.execute('INSERT INTO sessions VALUES (?, ?, ?)', (SID, 400, 100))  # 500
            conn.commit()
            conn.close()

            env = {
                **os.environ,
                'OWNERS_DIR': owners_dir,
                'STATE_DB': state_db,
                'TAKEOVER_SID': SID,
                'TAKEOVER_REQUESTED_BASELINE': '150',  # the STALE snapshot value
                'TAKEOVER_KNOWN_BASELINE': '0',
            }
            result = subprocess.run(
                ['python3', '-c', code], env=env,
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            out_fields = dict(
                l.split('=', 1) for l in result.stdout.splitlines() if '=' in l)
            self.assertEqual(out_fields.get('OWNER'), 'legacy')
            self.assertEqual(
                out_fields.get('BASELINE'), '500',
                'the published floor must equal the ADVANCED state.db total (500), not '
                'the stale requested snapshot (150) — otherwise the straddled 350 tokens '
                'an out-of-band live shipper already invoiced would be re-billed on the '
                f'next tick. stdout={result.stdout!r}')

            t = self._setup_tree(session_kwargs={'input_tokens': 400, 'output_tokens': 100})
            try:
                self._seed_owner(t, owner='legacy', baseline=500)
                self._grow_state_db(t, input_tokens=450, output_tokens=150)  # 500 -> 600
                rc, out = self._run_legacy(t)
                self.assertEqual(rc, 0, out)
                completions = self._legacy_completions(t)
                self.assertEqual(len(completions), 1, f'{completions!r}\n{out}')
                self.assertEqual(
                    argv_to_flags(completions[0]).get('--total-tokens'), '100',
                    'must bill only the 100-token growth above the advanced floor '
                    '(600-500), never re-billing the straddled 350')
            finally:
                self._teardown_tree(t)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class RegressionGuardTests(OwnershipTestBase):
    """AX-16, AX-18, AX-19: three properties this quick task must NOT
    disturb — the #54 dual-ledger migration, OWN-04's asymmetric fail
    direction, and the structural one-way-flip invariant that no test
    driving a specific scenario can prove on its own."""

    INCIDENT_TOTAL = 12608

    def test_a20_the_54_dual_ledger_migration_is_unchanged(self):
        """AX-16. The dual-ledger resolution table (both ledgers present ->
        legacy, plus a catch-up baseline and a once-per-record warn) is
        entirely #54's own code path and must never route through the new
        takeover branch — a regression here would mean the two features'
        code paths have become entangled."""
        t = self._setup_tree(session_kwargs={'input_tokens': 8608, 'output_tokens': 4000})
        try:
            self._seed_legacy_ledger(t, totals=(self.INCIDENT_TOTAL, self.INCIDENT_TOTAL))
            self._seed_event_ledger(t, count=4)

            rc, out = self._run_legacy(t)
            self.assertEqual(rc, 0, out)

            owner, baseline = self._owner_record(t)
            self.assertEqual(owner, 'legacy')
            self.assertEqual(baseline, str(self.INCIDENT_TOTAL))
            self.assertEqual(len(self._dual_ledger_warns(t)), 1)
        finally:
            self._teardown_tree(t)

    @unittest.skipIf(os.geteuid() == 0, 'root defeats mode bits')
    def test_a23_own_04_claim_fail_direction_is_unchanged_by_the_takeover(self):
        """AX-18. The takeover is downstream of the CLAIM primitive, which
        this quick task does not modify — legacy must still fail OPEN
        (bill) and the event path must still fail CLOSED (defer) when the
        owners directory itself is unusable, exactly as #54 established."""
        t = self._setup_tree()
        try:
            with open(t['event_ledger'], 'w', encoding='utf-8') as f:
                f.write('API:decoy:t1:api:1|other-session|1700000000.000\n')
            os.makedirs(t['owners_dir'], mode=0o700, exist_ok=True)
            os.chmod(t['owners_dir'], 0o500)
            try:
                rc, out = self._run_legacy(t)
                self.assertEqual(rc, 0, out)
                self.assertEqual(len(self._legacy_completions(t)), 1,
                                 f'OWN-04 unchanged: legacy still fails OPEN. {out}')
            finally:
                os.chmod(t['owners_dir'], 0o700)
        finally:
            self._teardown_tree(t)

        t2 = self._setup_tree()
        try:
            self._seed_spool(t2)
            self._seed_ready(t2)
            os.makedirs(t2['owners_dir'], mode=0o700, exist_ok=True)
            os.chmod(t2['owners_dir'], 0o500)
            try:
                rc, out = self._run_event(t2)
                self.assertEqual(rc, 0, out)
                self.assertEqual(self._event_completions(t2), [],
                                 f'OWN-04 unchanged: event still fails CLOSED. {out}')
            finally:
                os.chmod(t2['owners_dir'], 0o700)
        finally:
            self._teardown_tree(t2)

    def test_a24_the_takeover_primitive_can_only_ever_write_the_legacy_literal(self):
        """AX-19. Legitimately a MECHANISM assertion — the plan's one
        documented exception — because the one-way property is not
        otherwise observable: every scenario-driven test above proves the
        flip holds for the SPECIFIC case it constructs, but none of them
        can prove NO code path anywhere writes the `event` literal over an
        existing record. Only reading the source can. `os.replace` must be
        confined to exactly one call site (the takeover); `os.link` remains
        the claim's sole publication primitive (asserted already, statically,
        by test_session_ownership_record.py's AtomicClaimTests)."""
        text = HERMES_REPORT.read_text()
        code = '\n'.join(ln for ln in text.splitlines() if not ln.lstrip().startswith('#'))

        self.assertEqual(
            code.count('os.replace('), 1,
            'os.replace must appear EXACTLY ONCE, confined to the takeover — a second '
            'occurrence means some other code path can also flip an existing record')
        self.assertIn('os.link(', code,
                      "the claim's sole publication primitive must be untouched")

        fn_idx = code.index('_takeover_session_owner')
        body_from_fn = code[fn_idx:]
        replace_idx = body_from_fn.index('os.replace(')
        takeover_fn_body = body_from_fn[:replace_idx + len('os.replace(')]
        self.assertIn('"legacy\\n"', takeover_fn_body,
                      'the takeover must write the legacy literal')
        self.assertNotIn('"event"', takeover_fn_body,
                         'no argument, branch or environment variable inside the takeover '
                         'may reach the event literal — it is one-way by construction')

        api_text = (SCRIPTS_DIR / 'api-event-report.sh').read_text()
        api_code = '\n'.join(ln for ln in api_text.splitlines() if not ln.lstrip().startswith('#'))
        self.assertEqual(
            api_code.count('os.replace('), 0,
            'api-event-report.sh must gain no replace-based write path to the owners '
            'record')


if __name__ == '__main__':
    unittest.main()
