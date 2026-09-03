"""Phase 56 Plan 02 (ROI-12, D-13) -- the auxiliary submission atomicity
proof, closing WINDOWS entry 5.

Unlike a test that seeds pre/post ledger state and runs ONE reporter
(serialising the race by construction and proving nothing about
concurrency -- exactly the weaker shape this repo has already rejected once
for the sibling takeover race, see tests/test_ax14_takeover_race_window.py's
own module docstring), these tests genuinely OPEN the window: racer A is
BLOCKED inside report_auxiliary_usage's own critical section -- specifically
at the `revenium meter completion --operation-type AUX` emit call, AFTER the
AUX_LOCK_FILE exclusion has already been acquired and the ledger baseline
has already been read -- until racer B, contending for the SAME lock, has
had a genuine chance to block on it. Only then is A released.

The stall point is the `revenium` CLI itself (the emit step), deliberately,
not the python3 interpreter or the lock-acquisition heredoc: stalling at the
CLI proves the exclusion spans the WHOLE read-baseline -> emit -> append
sequence, not just the append. A test that stalled earlier (e.g. before the
baseline read) would only prove the two invocations do not start at the same
instant -- weaker evidence, and exactly the kind of narrowed-window argument
WINDOWS entry 5 explicitly rejects as a fix.

Technique modelled on tests/test_ax14_takeover_race_window.py -- the only
technique this repo has ever accepted as proof that a lock closes a race --
with a stalling `revenium` CLI wrapper standing in for that file's
python3-interpreter stall shim, since the auxiliary critical section's
stall-worthy call is a CLI invocation, not a Python heredoc.

A concurrency test that has never been shown to go RED against the unlocked
shape is not evidence either; that fail-first proof is
tests/mutation_verify_aux_atomicity.py's job, not this module's.
"""
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from tests._compat_helpers import (
    argv_to_flags,
    build_session_model_usage,
    build_shim,
    build_state_db,
    run_script,
    SCRIPTS_DIR,
)

REAL_PYTHON = subprocess.run(
    ['bash', '-lc', 'command -v python3'],
    capture_output=True, text=True,
).stdout.strip() or sys.executable


class _AuxAtomicityTestBase(unittest.TestCase):
    """Fixture harness duplicated from test_phase55_auxiliary_metering's
    _AuxMeteringTestCase (this repo's no-shared-test-code rule), extended
    with a stalling `revenium` CLI wrapper so a test can genuinely hold the
    auxiliary exclusion open while a second racer contends for it."""

    def _setup_fixture(self, sessions, aux_rows=None):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase56-aux-atomicity-')
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)

        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        markers_dir = os.path.join(state_dir, 'markers')
        os.makedirs(markers_dir, mode=0o700)
        state_db = os.path.join(hermes_home, 'state.db')

        # ensure_path's LAST prepend is "${HOME}/.local/bin" -- anywhere
        # else and real system binaries shadow the shim (T-56-05), silently
        # exercising production tooling instead of the shim under test.
        shim_home = os.path.join(tmpdir, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)

        build_state_db(state_db, sessions)
        if aux_rows is not None:
            build_session_model_usage(state_db, aux_rows)

        real_shim = os.path.join(bin_dir, 'revenium.real')
        build_shim(real_shim)
        self._install_stall_wrapper(bin_dir, real_shim)

        return {
            'tmpdir': tmpdir,
            'hermes_home': hermes_home,
            'state_dir': state_dir,
            'state_db': state_db,
            'shim_home': shim_home,
            'bin_dir': bin_dir,
        }

    @staticmethod
    def _install_stall_wrapper(bin_dir, real_shim):
        """`revenium` wrapper that stalls if and only if AUX_STALL_GATE is
        set in its environment AND the call is the auxiliary emit
        (`--operation-type AUX` present in argv) -- so a non-aux completion
        (the main loop's own row) and every other racer's call are
        untouched, and only the racer that carries AUX_STALL_GATE ever
        stalls. Delegates to the REAL shim afterward (by exec, so the same
        process continues) so the invocation is still recorded in the meter
        log exactly as an unstalled call would be."""
        path = os.path.join(bin_dir, 'revenium')
        with open(path, 'w') as f:
            f.write(
                '#!/usr/bin/env bash\n'
                'prev=""\n'
                'is_aux=0\n'
                'for arg in "$@"; do\n'
                '  if [[ "$prev" == "--operation-type" && "$arg" == "AUX" ]]; then\n'
                '    is_aux=1\n'
                '  fi\n'
                '  prev="$arg"\n'
                'done\n'
                'if [[ -n "${AUX_STALL_GATE:-}" && "$is_aux" == "1" ]]; then\n'
                '  : > "${AUX_STALL_GATE}"\n'
                '  for _ in $(seq 1 600); do\n'
                '    [[ -e "${AUX_STALL_RELEASE:-}" ]] && break\n'
                '    sleep 0.05\n'
                '  done\n'
                'fi\n'
                f'exec {shlex.quote(real_shim)} "$@"\n'
            )
        os.chmod(path, 0o755)
        return path

    def _run(self, fixture, tag, extra_env=None):
        meter_log = os.path.join(fixture['tmpdir'], f'{tag}-meter.log')
        jobs_log = os.path.join(fixture['tmpdir'], f'{tag}-jobs.log')
        inv_log = os.path.join(fixture['tmpdir'], f'{tag}-inv.log')
        env = {
            **os.environ,
            'HOME': fixture['shim_home'],
            'HERMES_HOME': fixture['hermes_home'],
            'REVENIUM_STATE_DIR': fixture['state_dir'],
            'PATH': fixture['bin_dir'] + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': inv_log,
            'METER_LOG': meter_log,
            'JOBS_LOG': jobs_log,
            'TZ': 'UTC',
        }
        if extra_env:
            env.update(extra_env)
        rc, _ignored, output = run_script(
            SCRIPTS_DIR / 'hermes-report.sh', env, inv_log
        )
        meter_invocations = []
        if os.path.exists(meter_log):
            with open(meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        meter_invocations.append(shlex.split(line))
        return {'rc': rc, 'output': output, 'meter_invocations': meter_invocations}

    @staticmethod
    def _aux_ledger_path(fixture):
        return os.path.join(fixture['state_dir'], 'revenium-aux.ledger')

    @classmethod
    def _aux_ledger_lines(cls, fixture, sid='aux-sid-001'):
        path = cls._aux_ledger_path(fixture)
        if not os.path.exists(path):
            return []
        with open(path, encoding='utf-8') as f:
            return [l for l in f.read().splitlines() if l.startswith(f'AUX:{sid}|')]

    @staticmethod
    def _lock_path(fixture):
        return os.path.join(fixture['state_dir'], 'aux.lock')

    @staticmethod
    def _log_text(fixture):
        """log()'s stderr mirror is TTY-gated (common.sh), so under a
        captured subprocess nothing reaches stdout/stderr -- warn assertions
        must read revenium-metering.log from disk (matches
        OwnershipTestBase._log_text's own rationale)."""
        path = os.path.join(fixture['state_dir'], 'revenium-metering.log')
        if not os.path.exists(path):
            return ''
        with open(path, encoding='utf-8') as f:
            return f.read()

    @staticmethod
    def _one_session(**overrides):
        base = {
            'id': 'aux-sid-001',
            'model': 'claude-sonnet-4-6',
            'source': 'test',
            'input_tokens': 100,
            'output_tokens': 50,
            'cache_read': 0,
            'cache_write': 0,
            'reasoning': 0,
            'estimated_cost': '0',
            'api_calls': 1,
            # Far in the past so the G-03 sentinel-or-aged filter passes
            # without a markers-ready sentinel (matches the compat harness).
            'started_at': 1715514000.0,
            'ended_at': 1715514000.0,
            'billing_provider': 'anthropic',
        }
        base.update(overrides)
        return base

    @staticmethod
    def _one_aux_row(**overrides):
        base = {
            'session_id': 'aux-sid-001',
            'model': 'claude-3-5-haiku',
            'billing_provider': 'anthropic',
            'billing_base_url': '',
            'billing_mode': '',
            'task': 'approval',
            'api_call_count': 3,
            'input_tokens': 40,
            'output_tokens': 10,
            'cache_read_tokens': 0,
            'cache_write_tokens': 0,
            'estimated_cost_usd': 0.002,
            'first_seen': 1715514500.0,
            'last_seen': 1715514600.0,
        }
        base.update(overrides)
        return base

    @staticmethod
    def _find_aux_invocations(meter_invocations):
        return [
            argv_to_flags(inv) for inv in meter_invocations
            if argv_to_flags(inv).get('--operation-type') == 'AUX'
        ]

    def _run_race(self):
        """Shared race orchestration for AuxAtomicityRaceTests.

        Stall racer A inside the auxiliary emit call, holding AUX_LOCK_FILE;
        confirm the window is genuinely open (gate exists, ledger still
        empty); start racer B on its own thread so it genuinely contends for
        the same lock; give B a real window to reach and block on it; THEN
        release A; join both. Returns (fixture, result_a, result_b).
        """
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        gate = os.path.join(fixture['tmpdir'], 'gate')
        release = os.path.join(fixture['tmpdir'], 'release')

        result = {}

        def run_a():
            result['a'] = self._run(fixture, 'racerA', {
                'AUX_STALL_GATE': gate,
                'AUX_STALL_RELEASE': release,
            })

        ta = threading.Thread(target=run_a)
        ta.start()

        deadline = time.time() + 30
        while not os.path.exists(gate) and time.time() < deadline:
            time.sleep(0.02)
        self.assertTrue(
            os.path.exists(gate),
            'racer A never entered the auxiliary emit call -- the window '
            'was never opened, the fixture is invalid'
        )
        # A is provably pre-append: stalled INSIDE the CLI call, before the
        # zero-exit branch that writes the AUX: ledger line.
        self.assertEqual(
            self._aux_ledger_lines(fixture), [],
            'the ledger already carries a line for this identity while A '
            'is still stalled pre-append -- the fixture did not open the '
            'window'
        )

        result_b = {}

        def run_b():
            result_b['b'] = self._run(fixture, 'racerB')

        tb = threading.Thread(target=run_b)
        tb.start()
        # Give B a real chance to reach and block on AUX_LOCK_FILE (held by
        # A). Under the fix it blocks; without exclusion it would race
        # ahead and ship its own delta here instead of waiting.
        time.sleep(1.5)

        open(release, 'w').close()
        ta.join(timeout=60)
        tb.join(timeout=60)

        self.assertIn('a', result, 'racer A thread did not finish')
        self.assertIn('b', result_b, 'racer B thread did not finish')

        return fixture, result['a'], result_b['b']


class AuxAtomicityRaceTests(_AuxAtomicityTestBase):
    """The window, forced open. Racer A is stalled inside the auxiliary
    emit call, holding AUX_LOCK_FILE, until racer B has had a genuine chance
    to block on the SAME lock. Only then is A released -- both racers
    therefore provably compete for one exclusion, not two independent runs
    whose ordering was decided by test construction."""

    def test_exactly_one_aux_ledger_line_across_both_racers(self):
        fixture, _result_a, _result_b = self._run_race()
        aux_lines = self._aux_ledger_lines(fixture)
        self.assertEqual(
            len(aux_lines), 1,
            f'expected exactly one AUX: ledger line for the identity, '
            f'got {aux_lines}'
        )

    def test_exactly_one_operation_type_aux_invocation_across_both_racers(self):
        fixture, result_a, result_b = self._run_race()
        a_aux = self._find_aux_invocations(result_a['meter_invocations'])
        b_aux = self._find_aux_invocations(result_b['meter_invocations'])
        self.assertEqual(
            len(a_aux) + len(b_aux), 1,
            'expected exactly one --operation-type AUX invocation across '
            f'both racers\' meter logs, got A={a_aux} B={b_aux}'
        )

    def test_racer_b_exit_status_is_zero_exclusion_serialises_not_errors(self):
        fixture, result_a, result_b = self._run_race()
        self.assertEqual(result_a['rc'], 0, result_a['output'])
        self.assertEqual(
            result_b['rc'], 0,
            f'exclusion must serialise racer B, not error it: {result_b["output"]}'
        )


class AuxLockFailClosedTests(_AuxAtomicityTestBase):
    """Racer A holds AUX_LOCK_FILE well past a SHORT
    AUX_LOCK_TIMEOUT_SECONDS given to racer B: B must fail CLOSED -- zero
    auxiliary invocations, zero ledger appends, exit 0, and a deferral
    warning on disk -- rather than wait it out or error."""

    def test_timeout_defers_racer_b_with_zero_emit_zero_append_exit_zero(self):
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        gate = os.path.join(fixture['tmpdir'], 'gate')
        release = os.path.join(fixture['tmpdir'], 'release')

        result = {}

        def run_a():
            result['a'] = self._run(fixture, 'racerA', {
                'AUX_STALL_GATE': gate,
                'AUX_STALL_RELEASE': release,
            })

        ta = threading.Thread(target=run_a)
        ta.start()

        deadline = time.time() + 30
        while not os.path.exists(gate) and time.time() < deadline:
            time.sleep(0.02)
        self.assertTrue(
            os.path.exists(gate),
            'racer A never entered the auxiliary emit call -- the window '
            'was never opened, the fixture is invalid'
        )

        try:
            # Racer B's own timeout (1s) is far shorter than A's stall
            # (which is not released until well after B returns), so B must
            # give up and defer rather than wait it out. This call runs to
            # completion in the foreground: B's own bounded retry loop
            # guarantees it returns within ~1s regardless of A's hold.
            result_b = self._run(fixture, 'racerB', {
                'REVENIUM_AUX_LOCK_TIMEOUT_SECONDS': '1',
            })

            self.assertEqual(result_b['rc'], 0, result_b['output'])
            b_aux = self._find_aux_invocations(result_b['meter_invocations'])
            self.assertEqual(
                b_aux, [],
                f'racer B must ship zero auxiliary invocations on '
                f'timeout, got {b_aux}'
            )
            self.assertEqual(
                self._aux_ledger_lines(fixture), [],
                'racer B must append zero ledger lines on timeout'
            )
            self.assertIn(
                'auxiliary usage metering deferred this tick',
                self._log_text(fixture),
                f'racer B must log the deferral warning, got: '
                f'{self._log_text(fixture)!r}'
            )
        finally:
            open(release, 'w').close()
            ta.join(timeout=60)

        self.assertEqual(result['a']['rc'], 0, result['a']['output'])
        self.assertEqual(
            len(self._aux_ledger_lines(fixture)), 1,
            'racer A should still successfully ship once released'
        )


class AuxLockDisabledArmTests(_AuxAtomicityTestBase):
    """A tick with the metering tunable resolved to `disabled` must create
    no auxiliary lock state at all -- report_auxiliary_usage returns before
    ever reaching `exec 8>` when AUX_METERING_ENABLED is false."""

    def test_disabled_arm_creates_no_lock_file(self):
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        result = self._run(fixture, 'solo', {
            'REVENIUM_AUX_METERING': 'disabled',
        })
        self.assertEqual(result['rc'], 0, result['output'])
        self.assertEqual(
            self._find_aux_invocations(result['meter_invocations']), [],
            'disabled arm must ship zero auxiliary invocations'
        )
        self.assertFalse(
            os.path.exists(self._lock_path(fixture)),
            'disabled arm must not create AUX_LOCK_FILE at all'
        )


if __name__ == '__main__':
    unittest.main()
