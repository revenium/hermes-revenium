"""Phase 63 Plan 01 (SUB-06): the wire-pair chokepoint proof.

Wires `resolve_subscriber_email_mode` and `resolve_subscriber_wire_pair`
(both new in `common.sh`) end-to-end through hermes-report.sh's two
`meter completion` emission sites: Task 2 covers the MARKERLESS site
(`MarkerlessSubscriberEmailWiringTests`); Task 3 extends this module with
the MARKER-SPLIT site (`MarkerSplitSubscriberEmailWiringTests`), the
multi-marker sameness proof (`MultiMarkerSubscriberEmailSamenessTests`),
and the structural guard (`SubscriberEmailWiringStructuralTests`).

Phase 63 Plan 02 Task 1 (SUB-06, the THIRD site -- hermes-report.sh's
auxiliary-usage pass) extends this module further with
`AuxSubscriberEmailWiringTests` (Run E/F/G/H against
`meter-completion-aux.golden.json`, mirroring the markerless/marker-split
Run E/F/G/H above), `AuxCrossPathSubscriberEmailSamenessTests` (the
load-bearing new proof: one email-source session's main-loop completion
and its auxiliary completion carry the byte-identical `--subscriber-id`
value under obfuscation -- the arm that fails if the auxiliary path
re-hashes the already-wire-transformed `aux_session_ctx` cache value
instead of passing it through `resolve_subscriber_wire_pair`'s idempotent
branch), and `AuxCacheWidthMismatchTests` (a six-field and an eight-field
`aux_session_ctx` row are both still skipped, never mis-parsed, while the
neighbouring seven-field row still ships -- driven against the REAL,
unmodified `report_auxiliary_usage` function with `main()`'s trailing
invocation stripped, because every real producer always emits exactly
seven fields by construction and no DB-driven scenario through the normal
session loop can manufacture a width mismatch). `SubscriberEmailWiringStructuralTests`'
`EXPECTED_SUBSCRIBER_EMAIL_EMISSION_SITE_COUNT` moves from 2 to 3.

Phase 63 Plan 02 Task 2 (SUB-06, the FOURTH and last site --
api-event-report.sh's event path) extends this module once more with
`EventSubscriberEmailWiringTests` (Run E/F/G/H against
`meter-completion-event.golden.json`, plus the absent-arm and
pipe-in-`user_id` regression arms, reusing
`tests.test_phase62_subscriber_wiring._EventHarness`),
`EventThreeRecordSubscriberEmailSamenessTests` (a session with THREE
event records ships three `meter completion` calls all carrying the
identical `--subscriber-id`/`--subscriber-email` values -- the wire pair
is resolved ONCE per session, above the per-record loop, like
`source_env` and `subscriber_key` already are), and
`EventShadowModeSubscriberEmailTests` (under `EVENT_METERING_MODE=shadow`
the constructed argv still carries the pair -- proven structurally,
since shadow mode never logs anything to inspect at runtime -- and the
run still ships nothing). `EXPECTED_SUBSCRIBER_EMAIL_EMISSION_SITE_COUNT`
moves from 3 to 4 and `SCRIPTS_WITH_SUBSCRIBER_EMAIL_PROBE` gains
`api-event-report.sh`.

Unit coverage (`ResolveSubscriberEmailModeUnitTests`,
`ResolveSubscriberWirePairUnitTests`) exercises both new common.sh
functions in isolation, sourcing common.sh in a bash subshell exactly as
`tests.test_phase61_identity_resolution.ResolveSubscriberIdUnitTests` does
for `resolve_subscriber_id` / `mask_subscriber_for_log`.

End-to-end coverage (`MarkerlessSubscriberEmailWiringTests`) reuses
`tests.test_phase62_subscriber_wiring.MarkerlessSubscriberWiringTests`'
exact `test_phase29_agent_inheritance` fixture (same sid, model, tokens,
timestamps) so the deterministic values baked into
`meter-completion-markerless.golden.json`'s `argv_order` still hold,
changing only `sessions.source` (to `email`) and the actor id (a synthetic
`p63-`-prefixed address on the `.example` TLD):

    - Run E -- plaintext, both flags CLI-capable: argv equals the golden
      plus exactly FOUR trailing tokens (`--subscriber-id`, `email:<addr>`,
      `--subscriber-email`, `<addr>`).
    - Run F -- obfuscated, both flags CLI-capable: argv equals the golden
      plus exactly TWO trailing tokens (`--subscriber-id`, `email:<64hex>`),
      and `--subscriber-email` is absent from the WHOLE captured argv (D-06).
    - Run G (SUB-07) -- plaintext, `--subscriber-id` capable but
      `--subscriber-email` NOT advertised: argv equals the golden plus
      exactly the `--subscriber-id` pair, and the meter call still
      succeeds.
    - Run H -- either mode, a `slack`-source session: argv is byte-identical
      between plaintext and obfuscated (D-02 -- the switch never touches a
      non-email source).
    - Absent-arm regression -- the golden's own untouched fixture (no
      `user_id` column at all), mode `obfuscated`: argv equals `argv_order`
      exactly, proving the switch is a no-op for the 97% no-actor case.

Every actor id/address in this module is synthetic and `p63-`-prefixed on
the `.example` TLD; no value is copied from any reference host.
"""
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest

from tests._compat_helpers import (
    assert_argv_is_golden_argv_order,
    build_session_model_usage,
    build_shim,
    build_state_db,
    load_golden,
    run_script,
    seed_user_ids,
    ROOT,
    SCRIPTS_DIR,
)
from tests.test_phase61_identity_resolution import (
    _OLD_TS,
    _own_meter_invocations,
    _task_marker,
    _write_marker_lines,
)
from tests.test_phase61_subscriber_boundary import _assert_argv_equal_modulo_timestamps
# _EventHarness / _write_jsonl / EVENT_REPORT_SH are plain helpers (no
# test_* methods), imported by NAME exactly like _own_meter_invocations /
# _task_marker / _write_marker_lines above -- safe from unittest discovery's
# re-collection trap, which only bites a TestCase subclass imported by name
# (see the _test_ticket_attribution module-reference comment just below).
from tests.test_phase62_subscriber_wiring import (
    _EventHarness,
    _write_jsonl,
    EVENT_REPORT_SH,
)
# Imported as a MODULE reference (not `from ... import TicketWiringTests`)
# deliberately, mirroring tests.test_phase62_subscriber_wiring's own
# comment on this: importing the TestCase class by name would bind it into
# THIS module's globals, and unittest's discovery/loadTestsFromModule would
# then re-collect and re-run it a second time here.
import tests.test_ticket_attribution as _test_ticket_attribution

HERMES_REPORT_SH = SCRIPTS_DIR / 'hermes-report.sh'
COMMON_SH = SCRIPTS_DIR / 'common.sh'


class _CommonShUnitHarness:
    """bash-subshell caller for common.sh functions, mirroring
    tests.test_phase61_identity_resolution.ResolveSubscriberIdUnitTests'
    `_call` idiom: HERMES_HOME redirected to a scratch tmpdir so common.sh's
    top-level `mkdir -p "${STATE_DIR}" ...` never touches the real $HOME.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gsd-phase63-unit-')
        self.hermes_home = os.path.join(self.tmp, 'hh')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_config(self, config):
        state_dir = os.path.join(self.hermes_home, 'state', 'revenium')
        os.makedirs(state_dir, exist_ok=True)
        with open(os.path.join(state_dir, 'config.json'), 'w') as f:
            json.dump(config, f)

    def _call(self, fn, *args, env_extra=None, config=None):
        if config is not None:
            self._write_config(config)
        quoted = ' '.join(shlex.quote(a) for a in args)
        expr = f'{fn} {quoted}'
        env = {**os.environ, 'HERMES_HOME': self.hermes_home}
        # Absent-by-default: a caller that wants the "operator left it
        # unset" arm must not inherit whatever the outer test-runner
        # process happens to have exported.
        env.pop('REVENIUM_SUBSCRIBER_EMAIL_MODE', None)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            ['bash', '-c', f'source "{COMMON_SH}" >/dev/null 2>&1; {expr}'],
            env=env, capture_output=True, text=True, timeout=30,
        )


class ResolveSubscriberEmailModeUnitTests(_CommonShUnitHarness, unittest.TestCase):
    """DD-1: env > config.json > "plaintext" default, one warn on a typo."""

    def test_env_wins_over_config(self):
        r = self._call(
            'resolve_subscriber_email_mode',
            env_extra={'REVENIUM_SUBSCRIBER_EMAIL_MODE': 'obfuscated'},
            config={'subscriberEmailMode': 'plaintext'},
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'obfuscated\nfalse')

    def test_config_alone_honoured_when_env_unset(self):
        r = self._call(
            'resolve_subscriber_email_mode',
            config={'subscriberEmailMode': 'obfuscated'},
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'obfuscated\nfalse')

    def test_unrecognised_env_value_falls_back_to_plaintext_and_warns(self):
        r = self._call(
            'resolve_subscriber_email_mode',
            env_extra={'REVENIUM_SUBSCRIBER_EMAIL_MODE': 'garbage'},
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'plaintext\ntrue')

    def test_absent_env_and_config_resolves_plaintext_no_warn(self):
        r = self._call('resolve_subscriber_email_mode')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'plaintext\nfalse')


class ResolveSubscriberWirePairUnitTests(_CommonShUnitHarness, unittest.TestCase):
    """D-01/D-02/D-04/D-05/D-06 and the idempotency/injectivity proofs
    DD-2's chokepoint depends on."""

    @staticmethod
    def _digest(addr):
        return hashlib.sha256(addr.encode('utf-8')).hexdigest()

    def test_email_plaintext_verbatim_pair(self):
        r = self._call(
            'resolve_subscriber_wire_pair', 'email:jane@acme.example', 'plaintext'
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(
            r.stdout.strip(), 'email:jane@acme.example|jane@acme.example'
        )

    def test_email_obfuscated_hashes_to_64_hex_no_email_field(self):
        r = self._call(
            'resolve_subscriber_wire_pair', 'email:jane@acme.example', 'obfuscated'
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        expected_digest = self._digest('jane@acme.example')
        self.assertRegex(expected_digest, r'^[0-9a-f]{64}$')
        self.assertEqual(r.stdout.strip(), f'email:{expected_digest}|')

    def test_non_email_namespace_verbatim_in_both_modes(self):
        for mode in ('plaintext', 'obfuscated'):
            with self.subTest(mode=mode):
                r = self._call(
                    'resolve_subscriber_wire_pair', 'slack:U02C12JG78F', mode
                )
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout.strip(), 'slack:U02C12JG78F|')

    def test_empty_key_prints_bare_pipe(self):
        r = self._call('resolve_subscriber_wire_pair', '', 'obfuscated')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), '|')

    def test_idempotent_second_obfuscated_pass_over_own_output(self):
        """The property the auxiliary path (63-02-PLAN.md) depends on: it
        re-derives an already wire-transformed key from aux_session_ctx and
        calls this helper on it a second time. A second pass must not
        double-hash."""
        r1 = self._call(
            'resolve_subscriber_wire_pair', 'email:jane@acme.example', 'obfuscated'
        )
        self.assertEqual(r1.returncode, 0, r1.stderr)
        wire_id = r1.stdout.strip().split('|', 1)[0]
        self.assertRegex(wire_id, r'^email:[0-9a-f]{64}$')
        r2 = self._call('resolve_subscriber_wire_pair', wire_id, 'obfuscated')
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertEqual(r2.stdout.strip(), f'{wire_id}|')

    def test_three_case_variant_addresses_yield_three_distinct_keys(self):
        """No case-fold, no Unicode normalisation (D-04/D-05): the plaintext
        key count must equal the obfuscated key count."""
        addrs = ['Jane@acme.example', 'jane@acme.example', 'JANE@acme.example']
        plaintext_keys = {f'email:{a}' for a in addrs}
        self.assertEqual(len(plaintext_keys), 3, plaintext_keys)
        obfuscated_keys = set()
        for addr in addrs:
            r = self._call(
                'resolve_subscriber_wire_pair', f'email:{addr}', 'obfuscated'
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            obfuscated_keys.add(r.stdout.strip().split('|', 1)[0])
        self.assertEqual(len(obfuscated_keys), 3, obfuscated_keys)


class _Harness:
    """One temp HERMES_HOME + PATH-shim `revenium` + one meter log,
    mirroring tests.test_phase62_subscriber_wiring._Harness but
    parameterised additionally on `subscriber_email_capable` (the shim's
    --subscriber-email --help advertisement) and `email_mode` (threaded as
    REVENIUM_SUBSCRIBER_EMAIL_MODE, absent by default so the harness proves
    nothing about the switch unless a test explicitly asks it to).
    """

    def __init__(self, subscriber_capable=True, subscriber_email_capable=True,
                 email_mode=None, prefix='gsd-phase63-wiring-'):
        self.tmp = tempfile.mkdtemp(prefix=prefix)
        self.hermes_home = os.path.join(self.tmp, 'hh')
        self.state_dir = os.path.join(self.hermes_home, 'state', 'revenium')
        self.markers_dir = os.path.join(self.state_dir, 'markers')
        os.makedirs(self.markers_dir, mode=0o700)
        self.state_db = os.path.join(self.hermes_home, 'state.db')
        self.log_file = os.path.join(self.state_dir, 'revenium-metering.log')

        self.shim_home = os.path.join(self.tmp, 'home')
        self.bin_dir = os.path.join(self.shim_home, '.local', 'bin')
        os.makedirs(self.bin_dir)
        self.meter_log = os.path.join(self.tmp, 'meter.log')
        self.jobs_log = os.path.join(self.tmp, 'jobs.log')
        self.inv_log = os.path.join(self.tmp, 'inv.log')
        self.shim = os.path.join(self.bin_dir, 'revenium')
        build_shim(
            self.shim, squad_capable=True,
            subscriber_capable=subscriber_capable,
            subscriber_email_capable=subscriber_email_capable,
        )
        self.email_mode = email_mode

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def base_env(self):
        env = {
            **os.environ,
            'HOME': self.shim_home,
            'HERMES_HOME': self.hermes_home,
            'REVENIUM_STATE_DIR': self.state_dir,
            'PATH': self.bin_dir + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': self.inv_log,
            'METER_LOG': self.meter_log,
            'JOBS_LOG': self.jobs_log,
            'TZ': 'UTC',
            'REVENIUM_ORGANIZATION_NAME': '',
            'REVENIUM_AGENT_NAME': 'Hermes',
            'REVENIUM_SQUAD_NAME': '',
        }
        env.pop('REVENIUM_SUBSCRIBER_EMAIL_MODE', None)
        if self.email_mode is not None:
            env['REVENIUM_SUBSCRIBER_EMAIL_MODE'] = self.email_mode
        return env

    def run(self):
        rc, _ignored_inv, output = run_script(
            HERMES_REPORT_SH, self.base_env(), self.inv_log
        )
        meter_invocations = []
        if os.path.exists(self.meter_log):
            with open(self.meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        meter_invocations.append(shlex.split(line))
        if rc != 0:
            raise AssertionError(f'hermes-report.sh failed (rc={rc}): {output}')
        return meter_invocations


class MarkerlessSubscriberEmailWiringTests(unittest.TestCase):
    """Task 2: markerless-site end-to-end proof for --subscriber-email."""

    SID = 'compat-sid-markerless-001'
    ACTOR = 'p63-markerless-actor@acme.example'

    def _seed(self, source, subscriber_capable, subscriber_email_capable,
              email_mode, user_id_mapping=None):
        tree = _Harness(
            subscriber_capable=subscriber_capable,
            subscriber_email_capable=subscriber_email_capable,
            email_mode=email_mode,
        )
        build_state_db(tree.state_db, [{
            'id': self.SID,
            'model': 'claude-sonnet-4-6',
            'source': source,
            'input_tokens': 100,
            'output_tokens': 50,
            'cache_read': 0,
            'cache_write': 0,
            'reasoning': 0,
            'estimated_cost': '0',
            'api_calls': 1,
            'started_at': _OLD_TS,
            'ended_at': _OLD_TS,
            'billing_provider': 'anthropic',
        }])
        if user_id_mapping is not None:
            seed_user_ids(tree.state_db, user_id_mapping)
        return tree

    def test_run_e_plaintext_both_capable_four_trailing_tokens(self):
        tree = self._seed(
            source='email', subscriber_capable=True,
            subscriber_email_capable=True, email_mode='plaintext',
            user_id_mapping={self.SID: self.ACTOR},
        )
        try:
            invocations = tree.run()
            own = _own_meter_invocations(invocations, self.SID)
            self.assertEqual(len(own), 1, own)
            golden = load_golden('meter-completion-markerless.golden.json')
            expected_key = f'email:{self.ACTOR}'
            assert_argv_is_golden_argv_order(
                self, own[0], golden,
                value_overrides={'--environment': 'email'},
                extra_tail=(
                    '--subscriber-id', expected_key,
                    '--subscriber-email', self.ACTOR,
                ),
            )
        finally:
            tree.cleanup()

    def test_run_f_obfuscated_both_capable_two_trailing_tokens_no_email_flag(self):
        tree = self._seed(
            source='email', subscriber_capable=True,
            subscriber_email_capable=True, email_mode='obfuscated',
            user_id_mapping={self.SID: self.ACTOR},
        )
        try:
            invocations = tree.run()
            own = _own_meter_invocations(invocations, self.SID)
            self.assertEqual(len(own), 1, own)
            argv = own[0]
            self.assertNotIn('--subscriber-email', argv, argv)
            self.assertIn('--subscriber-id', argv, argv)
            idx = argv.index('--subscriber-id')
            wire_id = argv[idx + 1]
            self.assertRegex(wire_id, r'^email:[0-9a-f]{64}$')
            golden = load_golden('meter-completion-markerless.golden.json')
            assert_argv_is_golden_argv_order(
                self, argv, golden,
                value_overrides={'--environment': 'email'},
                extra_tail=('--subscriber-id', wire_id),
            )
        finally:
            tree.cleanup()

    def test_run_g_id_capable_email_not_capable_meter_call_succeeds(self):
        """SUB-07: a CLI advertising --subscriber-id but NOT
        --subscriber-email emits --subscriber-id and omits
        --subscriber-email, and the meter call still succeeds (hermes-
        report.sh's own rc==0 assertion inside `_Harness.run` is itself
        that proof -- a non-zero rc raises before this method ever
        inspects argv)."""
        tree = self._seed(
            source='email', subscriber_capable=True,
            subscriber_email_capable=False, email_mode='plaintext',
            user_id_mapping={self.SID: self.ACTOR},
        )
        try:
            invocations = tree.run()
            own = _own_meter_invocations(invocations, self.SID)
            self.assertEqual(len(own), 1, own)
            golden = load_golden('meter-completion-markerless.golden.json')
            expected_key = f'email:{self.ACTOR}'
            assert_argv_is_golden_argv_order(
                self, own[0], golden,
                value_overrides={'--environment': 'email'},
                extra_tail=('--subscriber-id', expected_key),
            )
        finally:
            tree.cleanup()

    def test_run_h_slack_source_argv_byte_identical_both_modes(self):
        sid = 'p63-sid-slack-markerless'
        actor = 'p63-slack-actor'

        def _run(mode):
            tree = _Harness(
                subscriber_capable=True, subscriber_email_capable=True,
                email_mode=mode,
            )
            try:
                build_state_db(tree.state_db, [{
                    'id': sid,
                    'model': 'claude-sonnet-4-6',
                    'source': 'slack',
                    'input_tokens': 100,
                    'output_tokens': 50,
                    'cache_read': 0,
                    'cache_write': 0,
                    'reasoning': 0,
                    'estimated_cost': '0',
                    'api_calls': 1,
                    'started_at': _OLD_TS,
                    'ended_at': _OLD_TS,
                    'billing_provider': 'anthropic',
                }])
                seed_user_ids(tree.state_db, {sid: actor})
                invocations = tree.run()
                own = _own_meter_invocations(invocations, sid)
                self.assertEqual(len(own), 1, own)
                return own[0]
            finally:
                tree.cleanup()

        argv_plain = _run('plaintext')
        argv_obf = _run('obfuscated')
        self.assertNotIn('--subscriber-email', argv_plain, argv_plain)
        self.assertNotIn('--subscriber-email', argv_obf, argv_obf)
        self.assertIn('--subscriber-id', argv_plain, argv_plain)
        self.assertIn('--subscriber-id', argv_obf, argv_obf)
        _assert_argv_equal_modulo_timestamps(
            self, argv_plain, argv_obf, 'slack-source markerless'
        )

    def test_absent_arm_obfuscated_no_user_id_column_matches_golden(self):
        """Turning the switch on must not perturb the 97% no-actor case:
        the golden's own untouched fixture (source='test', no `user_id`
        column at all), mode obfuscated, still equals argv_order exactly."""
        tree = _Harness(
            subscriber_capable=True, subscriber_email_capable=True,
            email_mode='obfuscated',
        )
        try:
            build_state_db(tree.state_db, [{
                'id': self.SID,
                'model': 'claude-sonnet-4-6',
                'source': 'test',
                'input_tokens': 100,
                'output_tokens': 50,
                'cache_read': 0,
                'cache_write': 0,
                'reasoning': 0,
                'estimated_cost': '0',
                'api_calls': 1,
                'started_at': _OLD_TS,
                'ended_at': _OLD_TS,
                'billing_provider': 'anthropic',
            }])
            invocations = tree.run()
            own = _own_meter_invocations(invocations, self.SID)
            self.assertEqual(len(own), 1, own)
            golden = load_golden('meter-completion-markerless.golden.json')
            assert_argv_is_golden_argv_order(self, own[0], golden)
        finally:
            tree.cleanup()


class MarkerSplitSubscriberEmailWiringTests(unittest.TestCase):
    """Task 3: marker-split-site end-to-end proof for --subscriber-email,
    mirroring MarkerlessSubscriberEmailWiringTests' four runs but against
    `meter-completion.golden.json` (which carries `argv_order_pattern_
    sentinel`, so `assert_argv_is_golden_argv_order` normalises the three
    timestamp values before comparing -- unlike the markerless golden,
    which has no sentinel and compares literal timestamps).

    Reuses tests.test_phase62_subscriber_wiring.MarkerSplitSubscriberWiringTests'
    exact fixture (sid, muid, job id, model, tokens) so the deterministic
    values baked into meter-completion.golden.json's argv_order still
    hold; only sessions.source (to 'email') and the actor id (a synthetic
    p63- address) differ.
    """

    SID = 'compat-sid-001'
    MUID = 'compat-muid-001'
    ACTOR = 'p63-marker-actor@acme.example'

    def _seed(self, source, subscriber_capable, subscriber_email_capable,
              email_mode, user_id_mapping=None):
        tree = _Harness(
            subscriber_capable=subscriber_capable,
            subscriber_email_capable=subscriber_email_capable,
            email_mode=email_mode,
        )
        build_state_db(tree.state_db, [{
            'id': self.SID,
            'model': 'claude-sonnet-4-6',
            'source': source,
            'input_tokens': 100,
            'output_tokens': 50,
            'cache_read': 0,
            'cache_write': 0,
            'reasoning': 0,
            'estimated_cost': '0',
            'api_calls': 1,
            'started_at': _OLD_TS,
            'ended_at': _OLD_TS,
            'billing_provider': 'anthropic',
        }])
        if user_id_mapping is not None:
            seed_user_ids(tree.state_db, user_id_mapping)
        task_marker = {
            'muid': self.MUID,
            'ts': 1715515000.5,
            'sid': self.SID,
            'task_type': 'code_review',
            'operation_type': 'CHAT',
        }
        job_marker = {
            'kind': 'job',
            'ts': 1715515001.0,
            'sid': self.SID,
            'agentic_job_id': 'compat-job-001',
            'job_name': 'COMPAT Test Job',
            'job_type': 'code_review',
            'status': 'IN_PROGRESS',
        }
        _write_marker_lines(tree.markers_dir, self.SID, [task_marker, job_marker])
        return tree

    def test_run_e_plaintext_both_capable_four_trailing_tokens(self):
        tree = self._seed(
            source='email', subscriber_capable=True,
            subscriber_email_capable=True, email_mode='plaintext',
            user_id_mapping={self.SID: self.ACTOR},
        )
        try:
            invocations = tree.run()
            own = _own_meter_invocations(invocations, self.SID)
            self.assertEqual(len(own), 1, own)
            golden = load_golden('meter-completion.golden.json')
            expected_key = f'email:{self.ACTOR}'
            assert_argv_is_golden_argv_order(
                self, own[0], golden,
                value_overrides={'--environment': 'email'},
                extra_tail=(
                    '--subscriber-id', expected_key,
                    '--subscriber-email', self.ACTOR,
                ),
            )
        finally:
            tree.cleanup()

    def test_run_f_obfuscated_both_capable_two_trailing_tokens_no_email_flag(self):
        tree = self._seed(
            source='email', subscriber_capable=True,
            subscriber_email_capable=True, email_mode='obfuscated',
            user_id_mapping={self.SID: self.ACTOR},
        )
        try:
            invocations = tree.run()
            own = _own_meter_invocations(invocations, self.SID)
            self.assertEqual(len(own), 1, own)
            argv = own[0]
            self.assertNotIn('--subscriber-email', argv, argv)
            self.assertIn('--subscriber-id', argv, argv)
            idx = argv.index('--subscriber-id')
            wire_id = argv[idx + 1]
            self.assertRegex(wire_id, r'^email:[0-9a-f]{64}$')
            golden = load_golden('meter-completion.golden.json')
            assert_argv_is_golden_argv_order(
                self, argv, golden,
                value_overrides={'--environment': 'email'},
                extra_tail=('--subscriber-id', wire_id),
            )
        finally:
            tree.cleanup()

    def test_run_g_id_capable_email_not_capable_meter_call_succeeds(self):
        tree = self._seed(
            source='email', subscriber_capable=True,
            subscriber_email_capable=False, email_mode='plaintext',
            user_id_mapping={self.SID: self.ACTOR},
        )
        try:
            invocations = tree.run()
            own = _own_meter_invocations(invocations, self.SID)
            self.assertEqual(len(own), 1, own)
            golden = load_golden('meter-completion.golden.json')
            expected_key = f'email:{self.ACTOR}'
            assert_argv_is_golden_argv_order(
                self, own[0], golden,
                value_overrides={'--environment': 'email'},
                extra_tail=('--subscriber-id', expected_key),
            )
        finally:
            tree.cleanup()

    def test_run_h_slack_source_argv_byte_identical_both_modes(self):
        sid = 'p63-sid-slack-marker'
        muid = 'p63-muid-slack-marker'
        actor = 'p63-slack-marker-actor'

        def _run(mode):
            tree = _Harness(
                subscriber_capable=True, subscriber_email_capable=True,
                email_mode=mode,
            )
            try:
                build_state_db(tree.state_db, [{
                    'id': sid,
                    'model': 'claude-sonnet-4-6',
                    'source': 'slack',
                    'input_tokens': 100,
                    'output_tokens': 50,
                    'cache_read': 0,
                    'cache_write': 0,
                    'reasoning': 0,
                    'estimated_cost': '0',
                    'api_calls': 1,
                    'started_at': _OLD_TS,
                    'ended_at': _OLD_TS,
                    'billing_provider': 'anthropic',
                }])
                seed_user_ids(tree.state_db, {sid: actor})
                _write_marker_lines(
                    tree.markers_dir, sid, [_task_marker(sid, muid)]
                )
                invocations = tree.run()
                own = _own_meter_invocations(invocations, sid)
                self.assertEqual(len(own), 1, own)
                return own[0]
            finally:
                tree.cleanup()

        argv_plain = _run('plaintext')
        argv_obf = _run('obfuscated')
        self.assertNotIn('--subscriber-email', argv_plain, argv_plain)
        self.assertNotIn('--subscriber-email', argv_obf, argv_obf)
        self.assertIn('--subscriber-id', argv_plain, argv_plain)
        self.assertIn('--subscriber-id', argv_obf, argv_obf)
        _assert_argv_equal_modulo_timestamps(
            self, argv_plain, argv_obf, 'slack-source marker-split'
        )


class _AuxEmailHarness:
    """Plan 02 Task 1: hermes-report.sh's auxiliary-usage pass,
    reproducing tests.test_phase62_subscriber_wiring._AuxHarness's own
    fixture shape (SID='aux-sid-001', the _one_session()/_one_aux_row()
    default fixture meter-completion-aux.golden.json's argv_order was
    captured against -- see that golden's own 'captured' provenance note)
    but parameterised additionally on `source` (default 'email',
    overriding _AuxHarness's own 'test'), `subscriber_email_capable` and
    `email_mode` -- the three axes SUB-06 needs that _AuxHarness has no
    reason to carry (a later plan's job per that class's own module
    docstring). Reproduced locally rather than imported: this plan's
    files_modified list does not touch
    tests/test_phase62_subscriber_wiring.py.
    """

    SID = 'aux-sid-001'

    def __init__(self, source='email', subscriber_capable=True,
                 subscriber_email_capable=True, email_mode=None,
                 prefix='gsd-phase63-aux-'):
        self.tmp = tempfile.mkdtemp(prefix=prefix)
        self.hermes_home = os.path.join(self.tmp, 'hh')
        self.state_dir = os.path.join(self.hermes_home, 'state', 'revenium')
        self.markers_dir = os.path.join(self.state_dir, 'markers')
        os.makedirs(self.markers_dir, mode=0o700)
        self.state_db = os.path.join(self.hermes_home, 'state.db')
        self.log_file = os.path.join(self.state_dir, 'revenium-metering.log')

        self.shim_home = os.path.join(self.tmp, 'home')
        self.bin_dir = os.path.join(self.shim_home, '.local', 'bin')
        os.makedirs(self.bin_dir)
        self.meter_log = os.path.join(self.tmp, 'meter.log')
        self.jobs_log = os.path.join(self.tmp, 'jobs.log')
        self.inv_log = os.path.join(self.tmp, 'inv.log')
        self.shim = os.path.join(self.bin_dir, 'revenium')
        build_shim(
            self.shim, squad_capable=True, subscriber_capable=subscriber_capable,
            subscriber_email_capable=subscriber_email_capable,
        )
        self.email_mode = email_mode

        build_state_db(self.state_db, [{
            'id': self.SID,
            'model': 'claude-sonnet-4-6',
            'source': source,
            'input_tokens': 100,
            'output_tokens': 50,
            'cache_read': 0,
            'cache_write': 0,
            'reasoning': 0,
            'estimated_cost': '0',
            'api_calls': 1,
            'started_at': _OLD_TS,
            'ended_at': _OLD_TS,
            'billing_provider': 'anthropic',
        }])
        build_session_model_usage(self.state_db, [{
            'session_id': self.SID,
            'model': 'claude-3-5-haiku',
            'billing_provider': 'anthropic',
            'task': 'approval',
            'api_call_count': 3,
            'input_tokens': 40,
            'output_tokens': 10,
            'estimated_cost_usd': 0.002,
            'first_seen': _OLD_TS + 500.0,
            'last_seen': _OLD_TS + 600.0,
        }])

    def seed_user_id(self, mapping):
        seed_user_ids(self.state_db, mapping)

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def base_env(self):
        env = {
            **os.environ,
            'HOME': self.shim_home,
            'HERMES_HOME': self.hermes_home,
            'REVENIUM_STATE_DIR': self.state_dir,
            'PATH': self.bin_dir + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': self.inv_log,
            'METER_LOG': self.meter_log,
            'JOBS_LOG': self.jobs_log,
            'TZ': 'UTC',
            'REVENIUM_ORGANIZATION_NAME': '',
            'REVENIUM_AGENT_NAME': 'Hermes',
            'REVENIUM_SQUAD_NAME': '',
        }
        env.pop('REVENIUM_SUBSCRIBER_EMAIL_MODE', None)
        if self.email_mode is not None:
            env['REVENIUM_SUBSCRIBER_EMAIL_MODE'] = self.email_mode
        return env

    def run(self):
        rc, _ignored_inv, output = run_script(
            HERMES_REPORT_SH, self.base_env(), self.inv_log
        )
        meter_invocations = []
        if os.path.exists(self.meter_log):
            with open(self.meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        meter_invocations.append(shlex.split(line))
        if rc != 0:
            raise AssertionError(f'hermes-report.sh failed (rc={rc}): {output}')
        return meter_invocations

    @staticmethod
    def aux_invocation(invocations):
        """Return the single invocation carrying --operation-type OTHER, or
        raise if there isn't exactly one -- the aux row, distinguished from
        the main-loop CHAT invocation the same tick also ships."""
        aux = [
            inv for inv in invocations
            if '--operation-type' in inv
            and inv[inv.index('--operation-type') + 1] == 'OTHER'
        ]
        if len(aux) != 1:
            raise AssertionError(
                f'expected exactly 1 aux (--operation-type OTHER) invocation, '
                f'got {len(aux)}: {invocations!r}'
            )
        return aux[0]

    @staticmethod
    def main_loop_invocation(invocations):
        """The non-aux `meter completion` call the SAME tick's main session
        loop ships for this harness's own session (the markerless site,
        since no markers are seeded here) -- the cross-path sameness
        arm's other half."""
        main = [
            inv for inv in invocations
            if not ('--operation-type' in inv
                    and inv[inv.index('--operation-type') + 1] == 'OTHER')
        ]
        if len(main) != 1:
            raise AssertionError(
                f'expected exactly 1 main-loop invocation, got {len(main)}: '
                f'{invocations!r}'
            )
        return main[0]


class AuxSubscriberEmailWiringTests(unittest.TestCase):
    """Plan 02 Task 1: the four-run proof for the THIRD emission site --
    hermes-report.sh's auxiliary-usage pass -- against
    meter-completion-aux.golden.json's argv_order, mirroring
    MarkerlessSubscriberEmailWiringTests' / MarkerSplitSubscriberEmailWiringTests'
    own Run E/F/G/H above. `--environment` is overridden to 'email' the
    same way, since the aux golden's own fixture is captured with
    source='test'."""

    ACTOR = 'p63-aux-actor@acme.example'

    def test_run_e_plaintext_both_capable_four_trailing_tokens(self):
        tree = _AuxEmailHarness(
            source='email', subscriber_capable=True,
            subscriber_email_capable=True, email_mode='plaintext',
        )
        try:
            tree.seed_user_id({_AuxEmailHarness.SID: self.ACTOR})
            invocations = tree.run()
            aux = tree.aux_invocation(invocations)
            golden = load_golden('meter-completion-aux.golden.json')
            expected_key = f'email:{self.ACTOR}'
            assert_argv_is_golden_argv_order(
                self, aux, golden,
                value_overrides={'--environment': 'email'},
                extra_tail=(
                    '--subscriber-id', expected_key,
                    '--subscriber-email', self.ACTOR,
                ),
            )
        finally:
            tree.cleanup()

    def test_run_f_obfuscated_both_capable_two_trailing_tokens_no_email_flag(self):
        tree = _AuxEmailHarness(
            source='email', subscriber_capable=True,
            subscriber_email_capable=True, email_mode='obfuscated',
        )
        try:
            tree.seed_user_id({_AuxEmailHarness.SID: self.ACTOR})
            invocations = tree.run()
            aux = tree.aux_invocation(invocations)
            self.assertNotIn('--subscriber-email', aux, aux)
            self.assertIn('--subscriber-id', aux, aux)
            idx = aux.index('--subscriber-id')
            wire_id = aux[idx + 1]
            self.assertRegex(wire_id, r'^email:[0-9a-f]{64}$')
            golden = load_golden('meter-completion-aux.golden.json')
            assert_argv_is_golden_argv_order(
                self, aux, golden,
                value_overrides={'--environment': 'email'},
                extra_tail=('--subscriber-id', wire_id),
            )
        finally:
            tree.cleanup()

    def test_run_g_id_capable_email_not_capable_meter_call_succeeds(self):
        """SUB-07: a CLI advertising --subscriber-id but NOT
        --subscriber-email emits --subscriber-id and omits
        --subscriber-email, and the meter call still succeeds."""
        tree = _AuxEmailHarness(
            source='email', subscriber_capable=True,
            subscriber_email_capable=False, email_mode='plaintext',
        )
        try:
            tree.seed_user_id({_AuxEmailHarness.SID: self.ACTOR})
            invocations = tree.run()
            aux = tree.aux_invocation(invocations)
            golden = load_golden('meter-completion-aux.golden.json')
            expected_key = f'email:{self.ACTOR}'
            assert_argv_is_golden_argv_order(
                self, aux, golden,
                value_overrides={'--environment': 'email'},
                extra_tail=('--subscriber-id', expected_key),
            )
        finally:
            tree.cleanup()

    def test_run_h_slack_source_argv_byte_identical_both_modes(self):
        actor = 'p63-aux-slack-actor'

        def _run(mode):
            tree = _AuxEmailHarness(
                source='slack', subscriber_capable=True,
                subscriber_email_capable=True, email_mode=mode,
            )
            try:
                tree.seed_user_id({_AuxEmailHarness.SID: actor})
                invocations = tree.run()
                return tree.aux_invocation(invocations)
            finally:
                tree.cleanup()

        argv_plain = _run('plaintext')
        argv_obf = _run('obfuscated')
        self.assertNotIn('--subscriber-email', argv_plain, argv_plain)
        self.assertNotIn('--subscriber-email', argv_obf, argv_obf)
        self.assertIn('--subscriber-id', argv_plain, argv_plain)
        self.assertIn('--subscriber-id', argv_obf, argv_obf)
        _assert_argv_equal_modulo_timestamps(
            self, argv_plain, argv_obf, 'slack-source aux'
        )

    def test_absent_arm_obfuscated_no_user_id_column_matches_golden(self):
        """Turning the switch on must not perturb the 97% no-actor case:
        the golden's own untouched fixture (source='test', no `user_id`
        column at all), mode obfuscated, still equals argv_order exactly."""
        tree = _AuxEmailHarness(
            source='test', subscriber_capable=True,
            subscriber_email_capable=True, email_mode='obfuscated',
        )
        try:
            invocations = tree.run()
            aux = tree.aux_invocation(invocations)
            golden = load_golden('meter-completion-aux.golden.json')
            assert_argv_is_golden_argv_order(self, aux, golden)
        finally:
            tree.cleanup()


class AuxCrossPathSubscriberEmailSamenessTests(unittest.TestCase):
    """Plan 02 Task 1 <behavior>, the load-bearing arm: one email-source
    session's markerless main-loop completion and its auxiliary completion
    carry the BYTE-IDENTICAL --subscriber-id value under obfuscation. This
    is the arm that fails if the auxiliary path re-hashes the already-
    wire-transformed aux_session_ctx cache value instead of passing it
    through resolve_subscriber_wire_pair's idempotent branch -- every
    single-path arm above (Run F, Run G) still passes even if the digest
    were computed twice, because each only inspects ONE emission site in
    isolation."""

    ACTOR = 'p63-aux-crosspath-actor@acme.example'

    def test_main_loop_and_aux_share_one_obfuscated_key(self):
        tree = _AuxEmailHarness(
            source='email', subscriber_capable=True,
            subscriber_email_capable=True, email_mode='obfuscated',
        )
        try:
            tree.seed_user_id({_AuxEmailHarness.SID: self.ACTOR})
            invocations = tree.run()
            aux = tree.aux_invocation(invocations)
            main_loop = tree.main_loop_invocation(invocations)
            self.assertIn('--subscriber-id', aux, aux)
            self.assertIn('--subscriber-id', main_loop, main_loop)
            aux_id = aux[aux.index('--subscriber-id') + 1]
            main_id = main_loop[main_loop.index('--subscriber-id') + 1]
            self.assertRegex(aux_id, r'^email:[0-9a-f]{64}$')
            self.assertEqual(aux_id, main_id)
        finally:
            tree.cleanup()

    def test_main_loop_and_aux_share_one_plaintext_email(self):
        tree = _AuxEmailHarness(
            source='email', subscriber_capable=True,
            subscriber_email_capable=True, email_mode='plaintext',
        )
        try:
            tree.seed_user_id({_AuxEmailHarness.SID: self.ACTOR})
            invocations = tree.run()
            aux = tree.aux_invocation(invocations)
            main_loop = tree.main_loop_invocation(invocations)
            self.assertIn('--subscriber-email', aux, aux)
            self.assertIn('--subscriber-email', main_loop, main_loop)
            aux_email = aux[aux.index('--subscriber-email') + 1]
            main_email = main_loop[main_loop.index('--subscriber-email') + 1]
            self.assertEqual(aux_email, self.ACTOR)
            self.assertEqual(aux_email, main_email)
        finally:
            tree.cleanup()


def _hermes_report_body_without_main_invocation():
    """hermes-report.sh's full source with its trailing `main "$@"`
    invocation stripped, so its real function definitions -- including
    report_auxiliary_usage, completely unmodified -- can be sourced and
    called directly without running the whole session-loop pipeline.
    Fails loudly (an assertion, never a silent stale-body match) if the
    trailing invocation has moved, mirroring
    tests.test_phase55_aux_edges._extract_infer_provider_function's own
    fail-loud discipline for a live-extracted function body."""
    text = HERMES_REPORT_SH.read_text()
    anchor = '\nmain "$@"\n'
    assert text.endswith(anchor), (
        'hermes-report.sh no longer ends with the expected `main "$@"` '
        'trailing invocation -- update this extraction before trusting '
        'anything that depends on it'
    )
    return text[:-len(anchor)]


def _run_report_auxiliary_usage_directly(ctx_string, env):
    """Source the REAL hermes-report.sh definitions (main() invocation
    stripped, see above) and call report_auxiliary_usage with a
    hand-crafted `ctx_string` -- the ONLY way to drive a malformed
    aux_session_ctx row through the real parser: every real producer
    always emits exactly seven pipe-delimited fields by construction (the
    session loop's own cache append, and _supplement_aux_session_ctx's
    recovery append), so no DB-driven scenario through the normal session
    loop can manufacture a width mismatch.

    The temp script is written INSIDE skills/revenium/scripts/ (not a
    system tmpdir) so hermes-report.sh's own `SCRIPT_DIR="$(cd "$(dirname
    "${BASH_SOURCE[0]}")" && pwd)"` still resolves to the real scripts
    directory and its `source "${SCRIPT_DIR}/common.sh"` line keeps
    working -- a tmpdir copy would source nothing and every function below
    that line would be undefined.
    """
    body = _hermes_report_body_without_main_invocation()
    tmp_script_path = os.path.join(str(SCRIPTS_DIR), '.tmp-p63-ctxwidth.sh')
    with open(tmp_script_path, 'w') as f:
        f.write(body)
    os.chmod(tmp_script_path, 0o755)
    try:
        script = f'source {shlex.quote(tmp_script_path)}; report_auxiliary_usage "$1"'
        return subprocess.run(
            ['bash', '-c', script, '_', ctx_string],
            env=env, capture_output=True, text=True, timeout=30,
        )
    finally:
        os.unlink(tmp_script_path)


class AuxCacheWidthMismatchTests(unittest.TestCase):
    """Plan 02 Task 1 <behavior>: a six-field and an eight-field
    aux_session_ctx row are both still skipped rather than mis-parsed
    (Phase 62 D-09's existing counted-mismatch behaviour, unchanged by
    this plan), and the neighbouring seven-field row still ships.

    Driven against the REAL, unmodified report_auxiliary_usage function
    (see _run_report_auxiliary_usage_directly) rather than through the
    full harness: every real producer always emits exactly seven fields
    by construction, so no DB-driven scenario through the normal session
    loop can manufacture a width mismatch to assert against."""

    SID_SIX = 'p63-ctxwidth-six'
    SID_EIGHT = 'p63-ctxwidth-eight'
    SID_GOOD = 'p63-ctxwidth-good'

    def test_six_and_eight_field_rows_skipped_seven_field_row_ships(self):
        tmp = tempfile.mkdtemp(prefix='gsd-phase63-ctxwidth-')
        try:
            hermes_home = os.path.join(tmp, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            os.makedirs(state_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')

            shim_home = os.path.join(tmp, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmp, 'meter.log')
            shim = os.path.join(bin_dir, 'revenium')
            build_shim(
                shim, squad_capable=True, subscriber_capable=True,
                subscriber_email_capable=True,
            )

            common_row = {
                'model': 'claude-3-5-haiku', 'billing_provider': 'anthropic',
                'task': 'approval', 'api_call_count': 1,
                'input_tokens': 10, 'output_tokens': 5,
                'estimated_cost_usd': 0.001,
                'first_seen': _OLD_TS, 'last_seen': _OLD_TS + 10.0,
            }
            build_session_model_usage(state_db, [
                {**common_row, 'session_id': self.SID_SIX},
                {**common_row, 'session_id': self.SID_EIGHT},
                {**common_row, 'session_id': self.SID_GOOD},
            ])

            ctx_lines = [
                # SIX fields -- missing the trailing subscriber_key field.
                f'{self.SID_SIX}|{self.SID_SIX}|Hermes|CHAT|_none_|test',
                # EIGHT fields -- one field too many.
                f'{self.SID_EIGHT}|{self.SID_EIGHT}|Hermes|CHAT|_none_|test|subkey8|extra8',
                # SEVEN fields -- the well-formed neighbour.
                f'{self.SID_GOOD}|{self.SID_GOOD}|Hermes|CHAT|_none_|test|',
            ]
            ctx_string = '\n'.join(ctx_lines) + '\n'

            env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'METER_LOG': meter_log,
                'TZ': 'UTC',
                'REVENIUM_ORGANIZATION_NAME': '',
                'REVENIUM_AGENT_NAME': 'Hermes',
                'REVENIUM_SQUAD_NAME': '',
            }
            env.pop('REVENIUM_SUBSCRIBER_EMAIL_MODE', None)

            result = _run_report_auxiliary_usage_directly(ctx_string, env)
            self.assertEqual(result.returncode, 0, result.stderr)

            log_file = os.path.join(state_dir, 'revenium-metering.log')
            log_text = ''
            if os.path.exists(log_file):
                log_text = open(log_file).read()
            self.assertIn(
                'auxiliary session context cache: 2 malformed line(s)',
                log_text, log_text,
            )

            meter_invocations = []
            if os.path.exists(meter_log):
                with open(meter_log) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            meter_invocations.append(shlex.split(line))

            shipped_sids = set()
            for inv in meter_invocations:
                if '--trace-id' in inv:
                    shipped_sids.add(inv[inv.index('--trace-id') + 1])
            self.assertIn(self.SID_GOOD, shipped_sids, meter_invocations)
            self.assertNotIn(self.SID_SIX, shipped_sids, meter_invocations)
            self.assertNotIn(self.SID_EIGHT, shipped_sids, meter_invocations)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class MultiMarkerSubscriberEmailSamenessTests(unittest.TestCase):
    """Task 3 <behavior>: a session with THREE task markers and ONE
    resolved email actor ships three `meter completion` calls. Under
    obfuscation all three carry the IDENTICAL email:<64hex> value -- the
    digest is computed ONCE per session, at the chokepoint above the
    per-marker loop, never once per marker, so three markers cannot
    produce three spellings of one actor (the load-bearing new proof: a
    per-marker digest would still pass every single-marker Run F/G arm
    above). The plaintext arm proves the identical sameness property for
    --subscriber-email's own value.
    """

    SID = 'p63-multi-marker-email'
    ACTOR = 'p63-multi-actor@acme.example'

    def _seed(self, email_mode):
        tree = _Harness(
            subscriber_capable=True, subscriber_email_capable=True,
            email_mode=email_mode,
        )
        build_state_db(tree.state_db, [{
            'id': self.SID,
            'model': 'claude-sonnet-4-6',
            'source': 'email',
            'input_tokens': 300,
            'output_tokens': 150,
            'cache_read': 0,
            'cache_write': 0,
            'reasoning': 0,
            'estimated_cost': '0',
            'api_calls': 1,
            'started_at': _OLD_TS,
            'ended_at': _OLD_TS,
            'billing_provider': 'anthropic',
        }])
        seed_user_ids(tree.state_db, {self.SID: self.ACTOR})
        _write_marker_lines(tree.markers_dir, self.SID, [
            _task_marker(self.SID, 'p63-muid-1'),
            _task_marker(self.SID, 'p63-muid-2'),
            _task_marker(self.SID, 'p63-muid-3'),
        ])
        return tree

    def test_three_markers_obfuscated_all_calls_carry_same_digest(self):
        tree = self._seed(email_mode='obfuscated')
        try:
            invocations = tree.run()
            own = _own_meter_invocations(invocations, self.SID)
            self.assertEqual(len(own), 3, own)
            wire_ids = set()
            for argv in own:
                self.assertNotIn('--subscriber-email', argv, argv)
                self.assertIn('--subscriber-id', argv, argv)
                idx = argv.index('--subscriber-id')
                wire_id = argv[idx + 1]
                self.assertRegex(wire_id, r'^email:[0-9a-f]{64}$')
                wire_ids.add(wire_id)
            self.assertEqual(len(wire_ids), 1, wire_ids)
            expected_digest = 'email:' + hashlib.sha256(
                self.ACTOR.encode('utf-8')
            ).hexdigest()
            self.assertEqual(wire_ids, {expected_digest})
        finally:
            tree.cleanup()

    def test_three_markers_plaintext_all_calls_carry_same_email_value(self):
        tree = self._seed(email_mode='plaintext')
        try:
            invocations = tree.run()
            own = _own_meter_invocations(invocations, self.SID)
            self.assertEqual(len(own), 3, own)
            emails = set()
            for argv in own:
                self.assertIn('--subscriber-email', argv, argv)
                idx = argv.index('--subscriber-email')
                emails.add(argv[idx + 1])
            self.assertEqual(emails, {self.ACTOR})
        finally:
            tree.cleanup()


class EventSubscriberEmailWiringTests(unittest.TestCase):
    """Plan 02 Task 2: the four-run proof for the FOURTH and last emission
    site -- api-event-report.sh's event path -- against
    meter-completion-event.golden.json's argv_order, mirroring the three
    hermes-report.sh sites' own Run E/F/G/H, plus the absent-arm and
    pipe-in-user_id regression arms this site's own Phase 62 coverage
    already carries (EventSubscriberWiringTests in
    tests.test_phase62_subscriber_wiring), re-run here under the email
    dimension. Reuses _EventHarness (imported, not duplicated)."""

    ACTOR = 'p63-event-actor@acme.example'

    def test_run_e_plaintext_both_capable_four_trailing_tokens(self):
        tree = _EventHarness(
            subscriber_capable=True, subscriber_email_capable=True,
            email_mode='plaintext',
        )
        try:
            tree.seed_session(
                source='email', user_id_mapping={_EventHarness.SID: self.ACTOR}
            )
            invocations = tree.run()
            self.assertEqual(len(invocations), 1, invocations)
            golden = load_golden('meter-completion-event.golden.json')
            expected_key = f'email:{self.ACTOR}'
            assert_argv_is_golden_argv_order(
                self, invocations[0], golden,
                value_overrides={'--environment': 'email'},
                extra_tail=(
                    '--subscriber-id', expected_key,
                    '--subscriber-email', self.ACTOR,
                ),
            )
        finally:
            tree.cleanup()

    def test_run_f_obfuscated_both_capable_two_trailing_tokens_no_email_flag(self):
        tree = _EventHarness(
            subscriber_capable=True, subscriber_email_capable=True,
            email_mode='obfuscated',
        )
        try:
            tree.seed_session(
                source='email', user_id_mapping={_EventHarness.SID: self.ACTOR}
            )
            invocations = tree.run()
            self.assertEqual(len(invocations), 1, invocations)
            argv = invocations[0]
            self.assertNotIn('--subscriber-email', argv, argv)
            self.assertIn('--subscriber-id', argv, argv)
            wire_id = argv[argv.index('--subscriber-id') + 1]
            self.assertRegex(wire_id, r'^email:[0-9a-f]{64}$')
            golden = load_golden('meter-completion-event.golden.json')
            assert_argv_is_golden_argv_order(
                self, argv, golden,
                value_overrides={'--environment': 'email'},
                extra_tail=('--subscriber-id', wire_id),
            )
        finally:
            tree.cleanup()

    def test_run_g_id_capable_email_not_capable_meter_call_succeeds(self):
        """SUB-07: a CLI advertising --subscriber-id but NOT
        --subscriber-email emits --subscriber-id and omits
        --subscriber-email, and the meter call still succeeds."""
        tree = _EventHarness(
            subscriber_capable=True, subscriber_email_capable=False,
            email_mode='plaintext',
        )
        try:
            tree.seed_session(
                source='email', user_id_mapping={_EventHarness.SID: self.ACTOR}
            )
            invocations = tree.run()
            self.assertEqual(len(invocations), 1, invocations)
            golden = load_golden('meter-completion-event.golden.json')
            expected_key = f'email:{self.ACTOR}'
            assert_argv_is_golden_argv_order(
                self, invocations[0], golden,
                value_overrides={'--environment': 'email'},
                extra_tail=('--subscriber-id', expected_key),
            )
        finally:
            tree.cleanup()

    def test_run_h_slack_source_argv_byte_identical_both_modes(self):
        actor = 'p63-event-slack-actor'

        def _run(mode):
            tree = _EventHarness(
                subscriber_capable=True, subscriber_email_capable=True,
                email_mode=mode,
            )
            try:
                tree.seed_session(
                    source='slack', user_id_mapping={_EventHarness.SID: actor}
                )
                invocations = tree.run()
                self.assertEqual(len(invocations), 1, invocations)
                return invocations[0]
            finally:
                tree.cleanup()

        argv_plain = _run('plaintext')
        argv_obf = _run('obfuscated')
        self.assertNotIn('--subscriber-email', argv_plain, argv_plain)
        self.assertNotIn('--subscriber-email', argv_obf, argv_obf)
        self.assertIn('--subscriber-id', argv_plain, argv_plain)
        self.assertIn('--subscriber-id', argv_obf, argv_obf)
        _assert_argv_equal_modulo_timestamps(
            self, argv_plain, argv_obf, 'slack-source event'
        )

    def test_absent_arm_obfuscated_no_user_id_column_matches_golden(self):
        """Turning the switch on must not perturb the 97% no-actor case:
        the golden's own untouched fixture (source='test', no `user_id`
        column at all), mode obfuscated, still equals argv_order exactly."""
        tree = _EventHarness(
            subscriber_capable=True, subscriber_email_capable=True,
            email_mode='obfuscated',
        )
        try:
            tree.seed_session()
            invocations = tree.run()
            self.assertEqual(len(invocations), 1, invocations)
            golden = load_golden('meter-completion-event.golden.json')
            assert_argv_is_golden_argv_order(self, invocations[0], golden)
        finally:
            tree.cleanup()

    def test_pipe_in_user_id_obfuscated_ships_no_subscriber_token_environment_and_tokens_intact(self):
        """T-63-12: a transport-unsafe (pipe-bearing) actor id resolves to
        no key at all -- neither subscriber flag appears, --environment
        and --total-tokens on the same row are unaffected, and no digest
        is computed for a rejected actor."""
        tree = _EventHarness(
            subscriber_capable=True, subscriber_email_capable=True,
            email_mode='obfuscated',
        )
        try:
            tree.seed_session(user_id_mapping={_EventHarness.SID: 'U|600'})
            invocations = tree.run()
            self.assertEqual(len(invocations), 1, invocations)
            argv = invocations[0]
            self.assertNotIn('--subscriber-id', argv, argv)
            self.assertNotIn('--subscriber-email', argv, argv)
            golden = load_golden('meter-completion-event.golden.json')
            assert_argv_is_golden_argv_order(self, argv, golden)
            idx = argv.index('--total-tokens')
            self.assertEqual(argv[idx + 1], '165', argv)
        finally:
            tree.cleanup()


def _three_event_records(sid):
    """Three spool records sharing the default _EventHarness fixture's
    CHAT marker window (the marker pair's second entry, ts=1715513900.5,
    is the last marker in the file -- an open-ended window with no
    successor to bound it), differing only in api_request_id and
    timestamp, so all three ship as separate, unledgered `meter
    completion` calls."""
    base_ts = 1715514000.5
    return [
        {
            'v': 1, 'sid': sid, 'api_request_id': f'p63-event-3rec-arid-{i}',
            'ts': base_ts + i, 'ended_at': base_ts + i + 0.5,
            'duration_ms': 500, 'platform': 'cli',
            'model': 'compat-session-model-should-not-ship',
            'response_model': 'claude-sonnet-4-6',
            'provider': 'anthropic',
            'base_url': 'https://api.anthropic.com',
            'api_mode': 'anthropic_messages',
            'finish_reason': 'stop',
            'input_tokens': 100, 'output_tokens': 50,
            'cache_read_tokens': 10, 'cache_write_tokens': 5,
            'reasoning_tokens': 0, 'total_tokens': 165,
        }
        for i in range(3)
    ]


class EventThreeRecordSubscriberEmailSamenessTests(unittest.TestCase):
    """Plan 02 Task 2 <behavior>: a session with THREE event records ships
    three `meter completion` calls, all carrying the IDENTICAL
    --subscriber-id and --subscriber-email values -- the wire pair is
    resolved ONCE per session, above the per-record loop, exactly like
    source_env and subscriber_key already are."""

    ACTOR = 'p63-event-3record-actor@acme.example'

    def test_three_records_obfuscated_all_calls_share_one_digest(self):
        tree = _EventHarness(
            subscriber_capable=True, subscriber_email_capable=True,
            email_mode='obfuscated',
        )
        try:
            _write_jsonl(
                os.path.join(tree.spool_dir, f'{_EventHarness.SID}.jsonl'),
                _three_event_records(_EventHarness.SID),
            )
            tree.seed_session(
                source='email', user_id_mapping={_EventHarness.SID: self.ACTOR}
            )
            invocations = tree.run()
            self.assertEqual(len(invocations), 3, invocations)
            wire_ids = set()
            for argv in invocations:
                self.assertNotIn('--subscriber-email', argv, argv)
                self.assertIn('--subscriber-id', argv, argv)
                wire_ids.add(argv[argv.index('--subscriber-id') + 1])
            self.assertEqual(len(wire_ids), 1, wire_ids)
            expected_digest = 'email:' + hashlib.sha256(
                self.ACTOR.encode('utf-8')
            ).hexdigest()
            self.assertEqual(wire_ids, {expected_digest})
        finally:
            tree.cleanup()

    def test_three_records_plaintext_all_calls_share_one_email(self):
        tree = _EventHarness(
            subscriber_capable=True, subscriber_email_capable=True,
            email_mode='plaintext',
        )
        try:
            _write_jsonl(
                os.path.join(tree.spool_dir, f'{_EventHarness.SID}.jsonl'),
                _three_event_records(_EventHarness.SID),
            )
            tree.seed_session(
                source='email', user_id_mapping={_EventHarness.SID: self.ACTOR}
            )
            invocations = tree.run()
            self.assertEqual(len(invocations), 3, invocations)
            emails = set()
            for argv in invocations:
                self.assertIn('--subscriber-email', argv, argv)
                emails.add(argv[argv.index('--subscriber-email') + 1])
            self.assertEqual(emails, {self.ACTOR})
        finally:
            tree.cleanup()


class EventShadowModeSubscriberEmailTests(unittest.TestCase):
    """Plan 02 Task 2 <behavior>: under EVENT_METERING_MODE=shadow the
    constructed argv still carries the subscriber-id/subscriber-email pair
    (source order: both appends sit BEFORE the shadow branch's own
    `continue` -- api-event-report.sh's own comment on the append records
    this) and the run still ships nothing at all -- C-10's existing
    shadow-mode contract, unperturbed by this plan."""

    ACTOR = 'p63-event-shadow-actor@acme.example'

    def test_shadow_mode_ships_nothing(self):
        tree = _EventHarness(
            subscriber_capable=True, subscriber_email_capable=True,
            email_mode='plaintext', event_metering_mode='shadow',
        )
        try:
            tree.seed_session(
                source='email', user_id_mapping={_EventHarness.SID: self.ACTOR}
            )
            invocations = tree.run()
            self.assertEqual(invocations, [], invocations)
        finally:
            tree.cleanup()

    def test_subscriber_email_append_precedes_shadow_branch_in_source(self):
        """Structural companion to the runtime arm above: proves argv
        construction order directly from source, since a shadow-mode run
        never logs anything to inspect at runtime."""
        text = EVENT_REPORT_SH.read_text()
        email_idx = text.index('--subscriber-email "')
        shadow_idx = text.index(
            '"${EVENT_METERING_MODE}" == "shadow"', email_idx
        )
        self.assertGreater(
            shadow_idx, email_idx,
            'the --subscriber-email append must sit BEFORE the per-record '
            'shadow-mode branch check in source order',
        )


class PythonSubscriberKeyMirrorUnperturbedTests(unittest.TestCase):
    """Plan 02 Task 2 acceptance criterion: `git diff 8246499 --
    skills/revenium/scripts/api-event-report.sh` must show no line added
    inside the `def resolve_subscriber_key` body in the Python heredoc --
    the whole reason the wire-pair transform was done on the bash side,
    once, rather than adding hashing to this mirror (Phase 62 D-01/D-02's
    equivalence proof, tests/test_phase62_subscriber_key_equivalence.py,
    stays valid only if this body never changes). Extracts the
    SUBSCRIBER_KEY_BUILDER_START/END-delimited block -- the function's own
    self-describing anchors -- from the current tree and from the
    baseline commit, and asserts they are byte-identical."""

    START_MARKER = '# === SUBSCRIBER_KEY_BUILDER_START'
    END_MARKER = '# === SUBSCRIBER_KEY_BUILDER_END ==='
    BASELINE_COMMIT = '8246499'

    @classmethod
    def _extract_block(cls, text):
        start = text.index(cls.START_MARKER)
        end = text.index(cls.END_MARKER, start) + len(cls.END_MARKER)
        return text[start:end]

    def test_resolve_subscriber_key_body_byte_identical_to_baseline(self):
        current_block = self._extract_block(EVENT_REPORT_SH.read_text())

        baseline = subprocess.run(
            ['git', 'show',
             f'{self.BASELINE_COMMIT}:skills/revenium/scripts/api-event-report.sh'],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(baseline.returncode, 0, baseline.stderr)
        baseline_block = self._extract_block(baseline.stdout)

        self.assertEqual(
            current_block, baseline_block,
            'the resolve_subscriber_key Python mirror body has changed '
            'since the baseline commit -- the wire-pair transform must '
            'live on the bash side only, never inside this heredoc',
        )


# How many `meter completion` emission SITES across hermes-report.sh and
# api-event-report.sh are expected to append --subscriber-email at the end
# of THIS commit (Plan 02 Task 2): the markerless site (Plan 01 Task 2),
# the marker-split site (Plan 01 Task 3), the auxiliary site (Plan 02 Task
# 1), and the event site (Plan 02 Task 2, this task) -- all four sites, at
# last. Confirmed by grep, never by arithmetic:
# `grep -v '^[[:space:]]*#' skills/revenium/scripts/hermes-report.sh
#  skills/revenium/scripts/api-event-report.sh | grep -c -- '--subscriber-email "'` = 4.
EXPECTED_SUBSCRIBER_EMAIL_EMISSION_SITE_COUNT = 4
SCRIPTS_WITH_SUBSCRIBER_EMAIL_PROBE = (HERMES_REPORT_SH, EVENT_REPORT_SH)


class SubscriberEmailWiringStructuralTests(unittest.TestCase):
    """Structural guards mirroring
    tests.test_phase62_subscriber_wiring.SubscriberWiringStructuralTests,
    scoped to --subscriber-email. As of Plan 02 Task 2 (this commit) all
    FOUR sites are covered: hermes-report.sh's markerless, marker-split
    and auxiliary sites, plus api-event-report.sh's event site --
    SCRIPTS_WITH_SUBSCRIBER_EMAIL_PROBE and
    EXPECTED_SUBSCRIBER_EMAIL_EMISSION_SITE_COUNT both reflect the final
    state."""

    GUARD_LOOKBACK = _test_ticket_attribution.TicketWiringTests.GUARD_LOOKBACK

    def test_probe_declared_with_subcommand_scoped_supports_flag(self):
        for script in SCRIPTS_WITH_SUBSCRIBER_EMAIL_PROBE:
            with self.subTest(script=script.name):
                text = script.read_text()
                self.assertIn('SUBSCRIBER_EMAIL_CLI_CAPABLE=false', text)
                self.assertIn(
                    'supports_flag "meter completion" "--subscriber-email"',
                    text,
                )

    def test_each_emission_guarded_within_lookback_and_count_matches_constant(self):
        """Mirrors SubscriberWiringStructuralTests' own method of the same
        name: walks BACKWARDS from each --subscriber-email emission line to
        confirm a SUBSCRIBER_EMAIL_CLI_CAPABLE guard sits within
        GUARD_LOOKBACK lines above it (never on the emitting line itself),
        and asserts the total emission count against the module constant."""
        total = 0
        for script in SCRIPTS_WITH_SUBSCRIBER_EMAIL_PROBE:
            lines = script.read_text().splitlines()
            emissions = [
                i for i, l in enumerate(lines) if '--subscriber-email "' in l
            ]
            with self.subTest(script=script.name):
                self.assertTrue(
                    emissions,
                    f'{script.name} emits --subscriber-email nowhere',
                )
                for i in emissions:
                    window = lines[max(0, i - self.GUARD_LOOKBACK):i]
                    self.assertTrue(
                        any('SUBSCRIBER_EMAIL_CLI_CAPABLE' in w for w in window),
                        f'{script.name}:{i + 1} emits --subscriber-email with '
                        f'no SUBSCRIBER_EMAIL_CLI_CAPABLE guard within '
                        f'{self.GUARD_LOOKBACK} lines above it',
                    )
            total += len(emissions)
        self.assertEqual(total, EXPECTED_SUBSCRIBER_EMAIL_EMISSION_SITE_COUNT)

    def test_email_append_immediately_follows_id_append_at_each_site(self):
        """At each site, in each script, the --subscriber-email append
        immediately follows the --subscriber-id append with no other
        cmd+= line between them. Pairs each --subscriber-email line with
        the NEAREST preceding --subscriber-id line (rather than zipping
        the two lists positionally) because hermes-report.sh has a THIRD
        --subscriber-id site (the aux path) that now HAS a
        --subscriber-email counterpart as of Plan 02 Task 1, so the
        nearest-preceding pairing is what generalises correctly to all
        three of that file's sites without positional drift."""
        for script in SCRIPTS_WITH_SUBSCRIBER_EMAIL_PROBE:
            with self.subTest(script=script.name):
                lines = script.read_text().splitlines()
                id_lines = [
                    i for i, l in enumerate(lines) if '--subscriber-id "' in l
                ]
                email_lines = [
                    i for i, l in enumerate(lines) if '--subscriber-email "' in l
                ]
                self.assertTrue(
                    email_lines,
                    f'{script.name}: no --subscriber-email emission lines found',
                )
                for email_i in email_lines:
                    preceding_id_lines = [i for i in id_lines if i < email_i]
                    self.assertTrue(
                        preceding_id_lines,
                        f'{script.name}: --subscriber-email at line '
                        f'{email_i + 1} has no preceding --subscriber-id '
                        f'emission line in this file',
                    )
                    id_i = max(preceding_id_lines)
                    between = lines[id_i + 1:email_i]
                    self.assertFalse(
                        any('cmd+=' in l for l in between),
                        f'{script.name}: a cmd+= line sits between '
                        f'--subscriber-id ({id_i + 1}) and --subscriber-email '
                        f'({email_i + 1}): {between}',
                    )


if __name__ == '__main__':
    unittest.main()
