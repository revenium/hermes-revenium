"""ADJUDICATION FIXTURE (uncommitted) — Greptile P1 on hermes-report.sh's
`_takeover_session_owner` os.replace.

Unlike test_a18, which seeds the post-takeover on-disk state and runs ONE
reporter (serialising the race by construction), these tests genuinely open
the window Greptile alleges: racer A is BLOCKED inside its own
_takeover_session_owner heredoc, after its claim already returned
OWNER=event, until racer B has run to completion. Both therefore observe
owner=event before either replaces, and both execute the unconditional
os.replace and receive TOOK_OVER=true.

The block is installed as a `python3` shim on the test PATH that stalls if
and only if TAKEOVER_SID is set in its environment (i.e. only the takeover
primitive's own heredoc), so every other python3 call in the run is
untouched.
"""
import os
import shlex
import subprocess
import sys
import threading
import time
import unittest

from tests._compat_helpers import run_script
from tests.test_session_ownership_record import (
    OwnershipTestBase,
    SCRIPTS_DIR,
    SID,
)

REAL_PYTHON = subprocess.run(['bash', '-lc', 'command -v python3'],
                             capture_output=True, text=True).stdout.strip() or sys.executable


class TakeoverRaceWindowTests(OwnershipTestBase):

    def _install_python_stall_shim(self, t, gate_path, release_path):
        """python3 wrapper that, only for the takeover heredoc, announces it
        has entered the primitive (touch gate_path) and then waits for
        release_path before exec'ing the real interpreter — so the replace
        happens strictly AFTER the other racer has finished."""
        path = os.path.join(t['bin_dir'], 'python3')
        with open(path, 'w') as f:
            f.write(
                '#!/usr/bin/env bash\n'
                'if [[ -n "${TAKEOVER_SID:-}" && -n "${STALL_GATE:-}" ]]; then\n'
                '  : > "${STALL_GATE}"\n'
                '  for _ in $(seq 1 600); do\n'
                '    [[ -e "${STALL_RELEASE}" ]] && break\n'
                '    sleep 0.05\n'
                '  done\n'
                'fi\n'
                f'exec {shlex.quote(REAL_PYTHON)} "$@"\n'
            )
        os.chmod(path, 0o755)
        return path

    def _run_legacy_with(self, t, meter_log, extra_env=None):
        env = self._base_env(t, meter_log, extra_env)
        return run_script(SCRIPTS_DIR / 'hermes-report.sh', env, t['inv_log'])

    def _completions_in(self, log):
        return self._completions(log)

    # ------------------------------------------------------------------
    def test_both_racers_observe_event_then_both_replace(self):
        """The window, forced open. Racer A stalls inside the takeover
        primitive until racer B has fully exited; both observed owner=event
        and both perform os.replace."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event')
            gate = os.path.join(t['tmpdir'], 'gate')
            release = os.path.join(t['tmpdir'], 'release')
            self._install_python_stall_shim(t, gate, release)

            a_log = os.path.join(t['tmpdir'], 'racerA-meter.log')
            b_log = os.path.join(t['tmpdir'], 'racerB-meter.log')

            result = {}

            def run_a():
                result['a'] = self._run_legacy_with(
                    t, a_log,
                    {'STALL_GATE': gate, 'STALL_RELEASE': release})

            ta = threading.Thread(target=run_a)
            ta.start()

            # Wait until racer A is provably inside _takeover_session_owner,
            # i.e. it has ALREADY observed owner=event and has NOT replaced.
            deadline = time.time() + 30
            while not os.path.exists(gate) and time.time() < deadline:
                time.sleep(0.02)
            self.assertTrue(os.path.exists(gate),
                            'racer A never entered the takeover primitive — '
                            'the window was not opened, the fixture is invalid')
            owner_mid, _ = self._owner_record(t)
            self.assertEqual(owner_mid, 'event',
                             'record must still say event while A is blocked '
                             'pre-replace — otherwise A already replaced and '
                             'the window is not open')

            # Racer B: a full out-of-band invocation, no stall (its own
            # takeover heredoc gets no STALL_GATE in env).
            rc_b, _inv_b, out_b = self._run_legacy_with(t, b_log)
            self.assertEqual(rc_b, 0, out_b)
            owner_b, baseline_b = self._owner_record(t)

            # Release A: it now performs its own unconditional os.replace.
            open(release, 'w').close()
            ta.join(timeout=60)
            rc_a, _inv_a, out_a = result['a']
            self.assertEqual(rc_a, 0, out_a)

            owner_f, baseline_f = self._owner_record(t)
            a_ships = self._completions_in(a_log)
            b_ships = self._completions_in(b_log)
            hermes_lines = self._hermes_lines(t)

            print('\n--- RACE OBSERVATION ---')
            print('B post-run record :', owner_b, baseline_b)
            print('final record      :', owner_f, baseline_f)
            print('racer A takeover warn:',
                  len([l for l in self._log_text(t).splitlines()
                       if 'taken over from the event path' in l]))
            print('racer A completions:', len(a_ships))
            print('racer B completions:', len(b_ships))
            print('HERMES ledger rows :', hermes_lines)
            print('--- END ---')

            self.assertEqual(
                len(a_ships) + len(b_ships), 0,
                'DOUBLE-BILL: a racer shipped a completion on its takeover tick')
            self.assertEqual(
                len(hermes_lines), 0,
                'DOUBLE-BILL: duplicate/any ledger rows written on the takeover tick')
        finally:
            self._teardown_tree(t)

    def test_growth_billed_between_the_two_replaces_is_not_rebilled(self):
        """The nastier shape: B takes over, a third legacy tick bills real
        growth, and only THEN does the stalled racer A land its replace with
        its own (now stale) requested baseline. If A's replace could lower
        the floor below what was already billed, the next tick re-bills."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event')
            gate = os.path.join(t['tmpdir'], 'gate')
            release = os.path.join(t['tmpdir'], 'release')
            self._install_python_stall_shim(t, gate, release)

            a_log = os.path.join(t['tmpdir'], 'racerA-meter.log')
            b_log = os.path.join(t['tmpdir'], 'racerB-meter.log')
            c_log = os.path.join(t['tmpdir'], 'racerC-meter.log')
            d_log = os.path.join(t['tmpdir'], 'racerD-meter.log')

            result = {}

            def run_a():
                result['a'] = self._run_legacy_with(
                    t, a_log, {'STALL_GATE': gate, 'STALL_RELEASE': release})

            ta = threading.Thread(target=run_a)
            ta.start()
            deadline = time.time() + 30
            while not os.path.exists(gate) and time.time() < deadline:
                time.sleep(0.02)
            self.assertTrue(os.path.exists(gate), 'window never opened')

            # B takes over at the ORIGINAL total (150), then the session
            # grows and a later tick (C) bills that growth for real.
            rc_b, _i, out_b = self._run_legacy_with(t, b_log)
            self.assertEqual(rc_b, 0, out_b)
            self._grow_state_db(t, input_tokens=200, output_tokens=100)  # 150 -> 300
            rc_c, _i, out_c = self._run_legacy_with(t, c_log)
            self.assertEqual(rc_c, 0, out_c)
            billed_c = self._completions_in(c_log)
            ledger_after_c = list(self._hermes_lines(t))

            open(release, 'w').close()
            ta.join(timeout=60)
            rc_a, _i, out_a = result['a']
            self.assertEqual(rc_a, 0, out_a)
            owner_f, baseline_f = self._owner_record(t)

            # One more tick after A's late replace: does anything re-bill?
            rc_d, _i, out_d = self._run_legacy_with(t, d_log)
            self.assertEqual(rc_d, 0, out_d)
            billed_d = self._completions_in(d_log)

            print('\n--- LATE-REPLACE OBSERVATION ---')
            print('C completions (legit growth):', len(billed_c),
                  [dict(zip(a[::2], a[1::2])).get('--input-tokens') for a in billed_c])
            print('ledger after C  :', ledger_after_c)
            print('record after A  :', owner_f, baseline_f)
            print('D completions (post late replace):', len(billed_d))
            print('ledger final    :', self._hermes_lines(t))
            print('--- END ---')

            self.assertEqual(len(billed_c), 1, 'C should bill the real growth once')
            self.assertEqual(
                len(billed_d), 0,
                'DOUBLE-BILL: a tick after the late replace re-billed already-billed growth')
        finally:
            self._teardown_tree(t)

    def test_late_replace_with_a_failed_ax21_reread_lowers_the_floor(self):
        """RESIDUAL HAZARD probe. Same open window, but A's AX-21 publish-
        instant re-read FAILS (state.db momentarily absent) while A's own
        snapshot is stale. A's replace then writes its stale total as the
        floor, LOWERING the floor the winning racer recorded. If the event
        path had already shipped the straddled tokens (no HERMES row exists
        to protect them), the next legacy tick re-bills them."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='event')
            # The event path really did bill this session: its rows are on
            # disk, and no HERMES row exists to protect those tokens.
            self._seed_event_ledger(t, count=2)
            gate = os.path.join(t['tmpdir'], 'gate')
            release = os.path.join(t['tmpdir'], 'release')
            self._install_python_stall_shim(t, gate, release)
            res = {}

            def run_a():
                res['a'] = self._run_legacy_with(
                    t, os.path.join(t['tmpdir'], 'ra.log'),
                    {'STALL_GATE': gate, 'STALL_RELEASE': release})

            ta = threading.Thread(target=run_a)
            ta.start()
            deadline = time.time() + 30
            while not os.path.exists(gate) and time.time() < deadline:
                time.sleep(0.02)
            self.assertTrue(os.path.exists(gate), 'window never opened')

            # The event path ships 150..300 out of band and state.db advances.
            self._grow_state_db(t, input_tokens=200, output_tokens=100)
            rc_b, _i, out_b = self._run_legacy_with(
                t, os.path.join(t['tmpdir'], 'rb.log'))
            self.assertEqual(rc_b, 0, out_b)
            owner_b, baseline_b = self._owner_record(t)

            # A's publish-instant re-read fails (db momentarily unavailable).
            stash = t['state_db'] + '.away'
            os.rename(t['state_db'], stash)
            open(release, 'w').close()
            ta.join(timeout=60)
            os.rename(stash, t['state_db'])
            owner_f, baseline_f = self._owner_record(t)

            rc_d, _i, out_d = self._run_legacy_with(
                t, os.path.join(t['tmpdir'], 'rd.log'))
            self.assertEqual(rc_d, 0, out_d)
            d_ships = self._completions(os.path.join(t['tmpdir'], 'rd.log'))

            print('\n--- RESIDUAL HAZARD OBSERVATION ---')
            print('after winning racer B :', owner_b, baseline_b)
            print('after late replace A  :', owner_f, baseline_f)
            print('next-tick completions :', len(d_ships))
            for argv in d_ships:
                f = dict(zip(argv[::2], argv[1::2]))
                print('   txid=', f.get('--transaction-id'),
                      'input=', f.get('--input-tokens'),
                      'output=', f.get('--output-tokens'))
            print('HERMES ledger:', self._hermes_lines(t))
            print('--- END ---')

            self.assertEqual(baseline_f, baseline_b,
                             'the late replace LOWERED the floor the winner recorded')
            self.assertEqual(len(d_ships), 0,
                             'RE-BILL: tokens already shipped by the event path were billed again')
        finally:
            self._teardown_tree(t)

    @unittest.expectedFailure
    def test_control_two_overlapping_runs_on_a_legacy_owned_growing_session(self):
        """CONTROL — no takeover involved at all. Two overlapping legacy runs
        on an ordinary legacy-owned session that has grown. Establishes
        whether concurrent out-of-band invocation double-bills GENERICALLY,
        independent of the contested takeover code.

        EXPECTED FAILURE, deliberately, and it is NOT this branch's defect.

        It fails byte-identically on `0251bcf` — the commit before this
        branch's three commits — verified by re-running it against a
        `git archive` of that tree. Two overlapping reporters both ship, with
        two identical `--transaction-id`s and two identical `HERMES:` ledger
        rows, because the `grep -q "^HERMES:${sid}:${total_tokens}:"` guard in
        hermes-report.sh is read-then-write and therefore not atomic against a
        concurrent reporter.

        It is recorded here as an expectedFailure rather than deleted because
        it documents a REAL, older, still-open exposure: the only thing
        standing between it and a live double-bill is Revenium-side dedupe on
        the identical transaction id — an assumption this repo makes and does
        not verify. Closing it needs a lock inside hermes-report.sh itself (or
        an explicit accepted-risk decision about transaction-id dedupe), which
        is a separate change with a separate blast radius and must not be
        folded into the takeover fix.

        If this test ever starts PASSING, that is a real signal, not noise:
        either someone added the lock, or the fixture stopped opening the
        window. Find out which before flipping the decorator."""
        t = self._setup_tree()
        try:
            self._seed_owner(t, owner='legacy')
            self._seed_legacy_ledger(t, totals=(150,))
            self._grow_state_db(t, input_tokens=200, output_tokens=100)  # 150 -> 300

            a_log = os.path.join(t['tmpdir'], 'ctlA-meter.log')
            b_log = os.path.join(t['tmpdir'], 'ctlB-meter.log')
            res = {}

            def run(tag, log):
                res[tag] = self._run_legacy_with(t, log)

            ta = threading.Thread(target=run, args=('a', a_log))
            tb = threading.Thread(target=run, args=('b', b_log))
            ta.start(); tb.start(); ta.join(60); tb.join(60)

            a_ships = self._completions_in(a_log)
            b_ships = self._completions_in(b_log)
            print('\n--- CONTROL (no takeover) ---')
            print('A completions:', len(a_ships), 'B completions:', len(b_ships))
            for tag, ships in (('A', a_ships), ('B', b_ships)):
                for argv in ships:
                    f = dict(zip(argv[::2], argv[1::2]))
                    print(tag, 'txid=', f.get('--transaction-id'),
                          'input=', f.get('--input-tokens'),
                          'output=', f.get('--output-tokens'))
            print('HERMES ledger rows:', self._hermes_lines(t))
            print('--- END ---')
            self.assertEqual(len(a_ships) + len(b_ships), 1,
                             'GENERIC concurrency double-bill (not takeover-specific)')
        finally:
            self._teardown_tree(t)


if __name__ == '__main__':
    unittest.main()
