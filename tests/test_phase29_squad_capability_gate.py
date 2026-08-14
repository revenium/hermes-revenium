"""Phase 29 (SQUAD-04): capability-gate proof in BOTH directions.

Negative direction: against a CLI that does not advertise --squad-id in
`meter completion --help`, argv must be byte-identical to the pre-Phase-29
golden (tests/fixtures/compat/meter-completion.golden.json) — not one byte
different. Positive direction: against a CLI that does advertise it, argv is
the negative-gate argv plus exactly six appended tokens
(--squad-id <v> --squad-name <v> --squad-role <v>), in that fixed order,
appended strictly after every pre-existing token.

Analog: tests/test_compat_meter_completion.py (the golden-argv byte-shape
idiom) and tests/test_pagination_probe_scope.py (the Phase 26 lesson that a
capability probe must answer for the verb/flag it actually probed, not a
sibling).
"""
import json
import os
import shlex
import shutil
import tempfile
import unittest

from tests._compat_helpers import (
    argv_to_flags,
    assert_argv_matches_golden,
    build_shim,
    build_state_db,
    load_golden,
    run_script,
    SCRIPTS_DIR,
)

_OLD_TS = 1715514000.0

# Literal expected argv for the byte-identical negative-gate fixture below
# (compat-sid-001 / compat-muid-001 / compat-job-001, same inputs
# test_compat_meter_completion.py uses). request-time/completion-start-time/
# response-time are deterministic here because started_at == ended_at is a
# fixed past epoch (not wall-clock "now"), so this list is stable across
# runs. Asserted with assertEqual against the ORDERED list -- not a flag
# dict -- so a reordering of any existing flag would fail this even though
# the dict-based golden assert above it would not notice.
_EXPECTED_INCAPABLE_ARGV = [
    'meter', 'completion',
    '--model', 'claude-sonnet-4-6',
    '--provider', 'anthropic',
    '--input-tokens', '100',
    '--output-tokens', '50',
    '--cache-read-tokens', '0',
    '--cache-creation-tokens', '0',
    '--total-tokens', '150',
    '--stop-reason', 'END',
    '--request-time', '2024-05-12T11:40:00Z',
    '--completion-start-time', '2024-05-12T11:40:00Z',
    '--response-time', '2024-05-12T11:40:00Z',
    '--request-duration', '0',
    '--agent', 'Hermes',
    '--transaction-id', 'compat-sid-001-150-compat-muid-001',
    '--trace-id', 'compat-sid-001',
    '--is-streamed',
    '--quiet',
    '--task-type', 'code_review',
    '--operation-type', 'CHAT',
    '--model-source', 'anthropic',
    '--environment', 'test',
    '--agentic-job-id', 'compat-job-001',
    '--agentic-job-name', 'COMPAT Test Job',
    '--agentic-job-type', 'code_review',
]


def _write_shim_with_help_lines(shim_path, help_lines, jobs_capable=True):
    """Write a minimal revenium shim whose `meter completion --help` output
    is exactly `help_lines` (list of strings, each echoed as its own line)
    plus (optionally) the --agentic-job-id line LAST, matching the
    SIGPIPE-safe ordering _compat_helpers.build_shim uses (the probed flag
    is the final line written before exit 0, so a live `grep -q --` probe's
    early exit can never race a subsequent write on this writer)."""
    agentic_line = (
        '      echo "--agentic-job-id  Agentic job instance identifier"\n'
        if jobs_capable else ''
    )
    help_echoes = ''.join(f'      echo "{line}"\n' for line in help_lines)
    body = (
        '#!/usr/bin/env bash\n'
        'case "$1" in\n'
        '  config) exit 0 ;;\n'
        '  guardrails) exit 0 ;;\n'
        '  meter)\n'
        '    if [[ "$3" == "--help" ]]; then\n'
        + help_echoes
        + agentic_line
        + '      exit 0\n'
        '    fi\n'
        '    case "$2" in\n'
        '      completion)\n'
        '        printf "%q " "$@" >> "${METER_LOG:-${INVOCATIONS_LOG:-/dev/null}}"\n'
        '        printf "\\n"      >> "${METER_LOG:-${INVOCATIONS_LOG:-/dev/null}}"\n'
        '        ;;\n'
        '      *)\n'
        '        printf "%q " "$@" >> "${INVOCATIONS_LOG:-/dev/null}"\n'
        '        printf "\\n"      >> "${INVOCATIONS_LOG:-/dev/null}"\n'
        '        ;;\n'
        '    esac\n'
        '    exit 0\n'
        '    ;;\n'
        '  jobs)\n'
        f'    if [[ "$2" == "--help" ]]; then {"exit 0" if jobs_capable else "exit 1"}; fi\n'
        '    printf "%q " "$@" >> "${JOBS_LOG:-${INVOCATIONS_LOG:-/dev/null}}"\n'
        '    printf "\\n"      >> "${JOBS_LOG:-${INVOCATIONS_LOG:-/dev/null}}"\n'
        '    exit 0\n'
        '    ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n'
    )
    with open(shim_path, 'w') as f:
        f.write(body)
    os.chmod(shim_path, 0o755)


class Phase29SquadCapabilityGateTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gsd-phase29-squad-gate-")
        self.hermes_home = os.path.join(self.tmp, "hh")
        self.state_dir = os.path.join(self.hermes_home, "state", "revenium")
        self.markers_dir = os.path.join(self.state_dir, "markers")
        os.makedirs(self.markers_dir, mode=0o700)
        self.state_db = os.path.join(self.hermes_home, "state.db")

        self.shim_home = os.path.join(self.tmp, "home")
        self.bin_dir = os.path.join(self.shim_home, ".local", "bin")
        os.makedirs(self.bin_dir)
        self.meter_log = os.path.join(self.tmp, "meter.log")
        self.jobs_log = os.path.join(self.tmp, "jobs.log")
        self.inv_log = os.path.join(self.tmp, "inv.log")
        self.shim = os.path.join(self.bin_dir, "revenium")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed_single_session(self, sid, with_marker):
        build_state_db(self.state_db, [{
            'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
            'input_tokens': 100, 'output_tokens': 50, 'cache_read': 0,
            'cache_write': 0, 'reasoning': 0, 'estimated_cost': '0',
            'api_calls': 1, 'started_at': _OLD_TS, 'ended_at': _OLD_TS,
            'billing_provider': 'anthropic',
        }])
        if with_marker:
            marker = {
                'muid': 'gate-muid-001', 'ts': _OLD_TS + 100, 'sid': sid,
                'task_type': 'code_review', 'operation_type': 'CHAT',
            }
            os.makedirs(self.markers_dir, exist_ok=True)
            with open(os.path.join(self.markers_dir, f'{sid}.jsonl'), 'w') as f:
                f.write(json.dumps(marker, separators=(',', ':')) + '\n')

    def _base_env(self):
        return {
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
            'REVENIUM_SQUAD_NAME': '',
        }

    def _run_and_capture_meter_argv(self):
        rc, _ignored, output = run_script(
            SCRIPTS_DIR / 'hermes-report.sh', self._base_env(), self.inv_log
        )
        self.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {output}')
        invocations = []
        if os.path.exists(self.meter_log):
            with open(self.meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        invocations.append(shlex.split(line))
        return invocations

    # ---- 1 + 2: negative gate — no flags, byte-identical to golden ----

    def test_negative_gate_no_squad_flags_marker_bearing(self):
        sid = 'gate-neg-marker-1'
        self._seed_single_session(sid, with_marker=True)
        _write_shim_with_help_lines(self.shim, help_lines=[])

        invocations = self._run_and_capture_meter_argv()
        self.assertEqual(len(invocations), 1, invocations)
        argv = invocations[0]
        for flag in ('--squad-id', '--squad-name', '--squad-role'):
            self.assertNotIn(flag, argv, f'{flag} must not appear: {argv}')

    def test_negative_gate_no_squad_flags_markerless(self):
        sid = 'gate-neg-markerless-1'
        self._seed_single_session(sid, with_marker=False)
        _write_shim_with_help_lines(self.shim, help_lines=[])

        invocations = self._run_and_capture_meter_argv()
        self.assertEqual(len(invocations), 1, invocations)
        argv = invocations[0]
        for flag in ('--squad-id', '--squad-name', '--squad-role'):
            self.assertNotIn(flag, argv, f'{flag} must not appear: {argv}')

    def test_negative_gate_byte_identical_to_golden(self):
        """The exact fixture test_compat_meter_completion.py uses, run
        against a squad-incapable shim, must still byte-match the
        pre-Phase-29 golden — the ordered token list, not just a flag dict,
        via assert_argv_matches_golden's exact_match/pattern/forbidden
        allowlist AND an explicit list-equality check below."""
        sid = 'compat-sid-001'
        os.makedirs(self.markers_dir, exist_ok=True)
        task_marker = {
            'muid': 'compat-muid-001', 'ts': 1715515000.5, 'sid': sid,
            'task_type': 'code_review', 'operation_type': 'CHAT',
        }
        job_marker = {
            'kind': 'job', 'ts': 1715515001.0, 'sid': sid,
            'agentic_job_id': 'compat-job-001', 'job_name': 'COMPAT Test Job',
            'job_type': 'code_review', 'status': 'IN_PROGRESS',
        }
        with open(os.path.join(self.markers_dir, f'{sid}.jsonl'), 'w') as f:
            f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
            f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')
        build_state_db(self.state_db, [{
            'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
            'input_tokens': 100, 'output_tokens': 50, 'cache_read': 0,
            'cache_write': 0, 'reasoning': 0, 'estimated_cost': '0',
            'api_calls': 1, 'started_at': 1715514000.0, 'ended_at': 1715514000.0,
            'billing_provider': 'anthropic',
        }])
        # squad_capable=False here is the whole point of this test: the
        # installed CLI predates v1.3.0's squad flags.
        build_shim(self.shim, squad_capable=False)

        invocations = self._run_and_capture_meter_argv()
        self.assertEqual(len(invocations), 1, invocations)
        captured = invocations[0]

        assert_argv_matches_golden(
            self, captured, load_golden('meter-completion.golden.json')
        )
        # Ordered-list equality — a reordering of existing flags would fail
        # this even where the dict-based golden assert above would not.
        self.assertEqual(captured, _EXPECTED_INCAPABLE_ARGV)
        for flag in ('--squad-id', '--squad-name', '--squad-role'):
            self.assertNotIn(flag, captured, f'{flag} leaked into byte-identical argv: {captured}')

    # ---- 3: positive gate — exactly six appended tokens, in order ----

    def test_positive_gate_appends_exactly_six_tokens_in_order(self):
        sid = 'gate-pos-1'
        self._seed_single_session(sid, with_marker=True)

        # Incapable run first (own shim instance).
        _write_shim_with_help_lines(self.shim, help_lines=[])
        incapable_argv = self._run_and_capture_meter_argv()[0]

        # Reset logs/ledger for a clean second run against a capable shim.
        for f in (self.meter_log, self.jobs_log, self.inv_log):
            if os.path.exists(f):
                os.remove(f)
        ledger = os.path.join(self.state_dir, 'revenium-hermes.ledger')
        if os.path.exists(ledger):
            os.remove(ledger)

        build_shim(self.shim, squad_capable=True)
        capable_argv = self._run_and_capture_meter_argv()[0]

        self.assertEqual(
            len(capable_argv) - len(incapable_argv), 6,
            f'expected exactly 6 appended tokens; incapable={incapable_argv!r} '
            f'capable={capable_argv!r}'
        )
        self.assertEqual(
            capable_argv[:len(incapable_argv)], incapable_argv,
            'capable argv must be a strict prefix-preserving superset — the '
            'incapable argv unchanged, with squad tokens appended AFTER it'
        )
        appended = capable_argv[len(incapable_argv):]
        self.assertEqual(appended[0], '--squad-id')
        self.assertEqual(appended[2], '--squad-name')
        self.assertEqual(appended[4], '--squad-role')

    # ---- 4: probe scope — squad probe independent of jobs probe ----

    def test_squad_probe_independent_of_jobs_probe(self):
        """A shim advertising squad flags but NOT --agentic-job-id: squad
        flags must still appear, and JOBS_CLI_CAPABLE-gated flags must NOT
        (each probe answers only for its own flag/verb — Phase 26 lesson,
        tests/test_pagination_probe_scope.py)."""
        sid = 'gate-scope-1'
        self._seed_single_session(sid, with_marker=True)
        _write_shim_with_help_lines(
            self.shim,
            help_lines=[
                '--squad-id string        Squad (root session) identifier',
                '--squad-name string       Squad (root session) display name',
                '--squad-role string       Squad role: root or subagent',
            ],
            jobs_capable=False,
        )

        argv = self._run_and_capture_meter_argv()[0]
        flags = argv_to_flags(argv)
        self.assertIn('--squad-id', flags)
        self.assertIn('--squad-name', flags)
        self.assertIn('--squad-role', flags)
        self.assertNotIn('--agentic-job-id', flags,
                          'JOBS_CLI_CAPABLE-gated flag must not appear when its '
                          'own probe (bare `revenium jobs --help`) fails')

    # ---- 5: probe robustness — no false-positive on a longer sibling flag ----

    def test_probe_does_not_false_positive_on_longer_sibling_flag(self):
        sid = 'gate-sibling-1'
        self._seed_single_session(sid, with_marker=True)
        _write_shim_with_help_lines(
            self.shim,
            help_lines=['--squad-identifier string  a fabricated longer sibling flag'],
        )

        argv = self._run_and_capture_meter_argv()[0]
        self.assertNotIn('--squad-id', argv,
                          'a probe for --squad-id must not match the longer '
                          'sibling --squad-identifier (unanchored-grep regression)')
        self.assertNotIn('--squad-name', argv)
        self.assertNotIn('--squad-role', argv)


if __name__ == '__main__':
    unittest.main()
