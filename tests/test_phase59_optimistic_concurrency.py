"""Phase 59 Plan 02 -- SSE-05, criteria 3, 4 and 5: optimistic concurrency
on the correction path.

Every arm below drives the REAL `correct-assessment.sh` as a subprocess
against a CLI double (D-16) -- never a reimplementation of the script. The
double answers `--help` with `--expected-entity-version` present or absent,
serves a known `entityVersion` from `jobs get --output json`, and can be told
to answer `jobs outcome-update` with a `409` on a stale value.

D-16's stated trap, restated here because it is easy to get wrong a second
time: the stub `revenium` binary MUST live in a `.local/bin` under a
test-owned `HOME`. `ensure_path` (common.sh) prepends the real brew prefixes
onto `PATH`, and a stub placed anywhere else is shadowed by the genuine
`revenium` and `crontab` binaries -- which then mutate real state. This
module reuses `_build_correction_tree`'s existing placement
(`<tmpdir>/home/.local/bin/revenium`, with `HOME` overridden to that tree)
via its own `_build_versioned_correction_tree`, a copy rather than a
parameterization of the Phase 42 builder so that module stays untouched.

Requirements covered: SSE-05.
"""
import json
import os
import shutil
import tempfile
import unittest

from tests._compat_helpers import argv_to_flags, assert_argv_matches_golden, build_state_db, load_golden
from tests.test_phase42_assessment_contract import (
    _build_correction_tree,
    _jobs_log_invocations,
    _read_sidecar_lines,
    _run_correct_assessment,
    _tracer_assessment_record,
)


def _bash_single_quote(text):
    """Safely embed arbitrary text as a single-quoted bash literal.

    Standard escape for a literal single quote inside a single-quoted bash
    string: close the quote, emit an escaped quote, reopen the quote.
    """
    return "'" + text.replace("'", "'\\''") + "'"


def _build_versioned_correction_shim(shim_path, *, version_flag_capable,
                                      entity_version_json, outcome_update_result=None,
                                      jobs_get_exit=0):
    """revenium shim for the SSE-05 optimistic-concurrency test suite.

    Extends _build_correction_shim's design (three --help probes answered
    before the generic JOBS_LOG capture, so none of them is ever logged as a
    real invocation) with a FOURTH probe (`jobs outcome-update --help`'s
    --expected-entity-version line, gated on version_flag_capable) and a NEW
    `jobs get` branch that IS logged like any other real invocation --
    the negative-probe arm asserts it never happens and the positive-probe
    arm asserts it happens exactly once, so it cannot be answered in the
    pre-capture --help style the other three probes use.

    entity_version_json is the raw bytes `jobs get --output json` prints on
    stdout, embedded via _bash_single_quote so any fail-open shape (non-JSON,
    an object with no entityVersion, a boolean, a non-integer) can be served
    without further escaping by the caller. jobs_get_exit models a failed
    read.

    outcome_update_result is None for the ordinary success path (log, exit
    0) or a dict {'exit': <int>, 'stderr': <str>} to model a failure --
    including a 409 conflict, matched by correct-assessment.sh's own
    detection over the captured 2>&1 output.
    """
    version_help_line = (
        '      echo "--expected-entity-version int64   Expected entity version for optimistic concurrency"\n'
        if version_flag_capable else ''
    )
    entity_version_literal = _bash_single_quote(entity_version_json)
    if outcome_update_result is None:
        outcome_update_result = {'exit': 0, 'stderr': ''}
    ou_exit = outcome_update_result.get('exit', 0)
    ou_stderr = outcome_update_result.get('stderr', '')
    ou_stderr_line = (
        f'      printf "%s" {_bash_single_quote(ou_stderr)} >&2\n' if ou_stderr else ''
    )
    body = (
        '#!/usr/bin/env bash\n'
        'case "$1" in\n'
        '  config) exit 0 ;;\n'
        '  guardrails) exit 0 ;;\n'
        '  meter)\n'
        '    if [[ "$3" == "--help" ]]; then\n'
        '      echo "--agentic-job-id  Agentic job instance identifier"\n'
        '      exit 0\n'
        '    fi\n'
        '    case "$2" in\n'
        '      completion)\n'
        '        printf "%q " "$@" >> "${METER_LOG:-/dev/null}"\n'
        '        printf "\\n" >> "${METER_LOG:-/dev/null}"\n'
        '        ;;\n'
        '    esac\n'
        '    exit 0\n'
        '    ;;\n'
        '  jobs)\n'
        '    if [[ "$2" == "--help" ]]; then exit 0; fi\n'
        '    if [[ "$2" == "outcome" && "$3" == "--help" ]]; then\n'
        '      echo "--outcome-value string     Business outcome value"\n'
        '      echo "--outcome-currency string   Business outcome currency"\n'
        '      exit 0\n'
        '    fi\n'
        '    if [[ "$2" == "outcome-update" && "$3" == "--help" ]]; then\n'
        '      echo "--reason string    Reason for the update"\n'
        '      echo "--metadata string   Metadata JSON object"\n'
        + version_help_line +
        '      exit 0\n'
        '    fi\n'
        '    if [[ "$2" == "get" ]]; then\n'
        '      printf "%q " "$@" >> "${JOBS_LOG:-/dev/null}"\n'
        '      printf "\\n" >> "${JOBS_LOG:-/dev/null}"\n'
        f'      printf "%s" {entity_version_literal}\n'
        f'      exit {jobs_get_exit}\n'
        '    fi\n'
        '    if [[ "$2" == "outcome-update" ]]; then\n'
        '      printf "%q " "$@" >> "${JOBS_LOG:-/dev/null}"\n'
        '      printf "\\n" >> "${JOBS_LOG:-/dev/null}"\n'
        + ou_stderr_line +
        f'      exit {ou_exit}\n'
        '    fi\n'
        '    printf "%q " "$@" >> "${JOBS_LOG:-/dev/null}"\n'
        '    printf "\\n" >> "${JOBS_LOG:-/dev/null}"\n'
        '    exit 0\n'
        '    ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n'
    )
    with open(shim_path, 'w') as f:
        f.write(body)
    os.chmod(shim_path, 0o755)


def _build_versioned_correction_tree(sid, job_id, sidecar_lines=None, seed_outcome_line=False,
                                      version_flag_capable=True, entity_version_json='{}',
                                      outcome_update_result=None, jobs_get_exit=0):
    """Mirrors test_phase42_assessment_contract._build_correction_tree's tree
    shape byte-for-byte (state.db, jobs ledger seeded with a `created` line,
    marker pair, optional sidecar records, shim placement), substituting
    _build_versioned_correction_shim for _build_correction_shim.

    A COPY, not a parameterization of the Phase 42 builder -- per D-16 the
    Phase 42 module is left untouched, and the copy exists only so this
    module's shim can answer `jobs get` and a parameterised `jobs
    outcome-update` result that Phase 42's tree builder and shim have no
    reason to know about.

    Returns (tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger).
    """
    tmpdir = tempfile.mkdtemp(prefix='gsd-phase59-versioned-correction-')
    hermes_home = os.path.join(tmpdir, 'hh')
    state_dir = os.path.join(hermes_home, 'state', 'revenium')
    markers_dir = os.path.join(state_dir, 'markers')
    assessments_dir = os.path.join(state_dir, 'job-assessments')
    os.makedirs(markers_dir, mode=0o700)
    os.makedirs(assessments_dir, mode=0o700)
    state_db = os.path.join(hermes_home, 'state.db')
    jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')

    build_state_db(state_db, [{
        'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
        'input_tokens': 100, 'output_tokens': 50,
        'cache_read': 0, 'cache_write': 0, 'reasoning': 0,
        'estimated_cost': '0', 'api_calls': 1,
        'started_at': 1715514000.0, 'ended_at': 1715514000.0,
        'billing_provider': 'anthropic',
    }])

    ledger_lines = [f'JOB:{job_id}:created:1715516001.000\n']
    if seed_outcome_line:
        ledger_lines.append(f'JOB:{job_id}:outcome:1715516003.000:SUCCESS\n')
    with open(jobs_ledger, 'w') as f:
        f.writelines(ledger_lines)

    task_marker = {
        'muid': f'{job_id}-task', 'ts': 1715516000.5, 'sid': sid,
        'task_type': 'code_review', 'operation_type': 'CHAT',
    }
    job_marker = {
        'kind': 'job', 'ts': 1715516002.0, 'sid': sid,
        'agentic_job_id': job_id, 'job_name': 'Phase 59 Plan 02 Versioned Correction Job',
        'job_type': 'code_review', 'status': 'SUCCESS',
    }
    with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
        f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
        f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

    sidecar_path = os.path.join(assessments_dir, f'{job_id}.jsonl')
    if sidecar_lines:
        with open(sidecar_path, 'w') as f:
            for rec in sidecar_lines:
                f.write(json.dumps(rec, separators=(',', ':')) + '\n')

    shim_home = os.path.join(tmpdir, 'home')
    bin_dir = os.path.join(shim_home, '.local', 'bin')
    os.makedirs(bin_dir)
    meter_log = os.path.join(tmpdir, 'meter.log')
    jobs_log = os.path.join(tmpdir, 'jobs.log')
    shim = os.path.join(bin_dir, 'revenium')
    _build_versioned_correction_shim(
        shim, version_flag_capable=version_flag_capable,
        entity_version_json=entity_version_json,
        outcome_update_result=outcome_update_result,
        jobs_get_exit=jobs_get_exit,
    )

    env = {
        **os.environ,
        'HOME': shim_home,
        'HERMES_HOME': hermes_home,
        'REVENIUM_STATE_DIR': state_dir,
        'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
        'METER_LOG': meter_log,
        'JOBS_LOG': jobs_log,
        'TZ': 'UTC',
        'REVENIUM_ORGANIZATION_NAME': '',
    }
    return tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger


def _update_argv(invocations):
    for argv in invocations:
        if len(argv) >= 2 and argv[0] == 'jobs' and argv[1] == 'outcome-update':
            return argv
    return None


def _get_invocations(invocations):
    return [argv for argv in invocations if len(argv) >= 2 and argv[0] == 'jobs' and argv[1] == 'get']


class NegativeProbeByteIdentityTests(unittest.TestCase):
    """Criterion 3 and criterion 5: a CLI whose `jobs outcome-update --help`
    omits `--expected-entity-version` must make exactly the calls it made
    before this plan -- no `jobs get` invocation, and the `jobs
    outcome-update` argv matches the existing (untouched)
    jobs-outcome-update.golden.json byte for byte."""

    def test_negative_probe_ships_byte_identical_to_golden_and_makes_no_jobs_get_call(self):
        sid, job_id = 'p59c-sid-001', 'assess-42-correction-job'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_versioned_correction_tree(
                sid, job_id, sidecar_lines=[record],
                version_flag_capable=False, entity_version_json='{"entityVersion": 7}',
            )
        )
        try:
            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '525.0', '--currency', 'USD',
                '--reason', 'correction-golden-reason',
            ])
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')

            invocations = _jobs_log_invocations(jobs_log)
            self.assertEqual(
                _get_invocations(invocations), [],
                f'expected no jobs get invocation on a negative probe: {invocations}',
            )
            update_argv = _update_argv(invocations)
            self.assertIsNotNone(update_argv, f'expected an outcome-update invocation: {invocations}')
            assert_argv_matches_golden(
                self, update_argv, load_golden('jobs-outcome-update.golden.json'))
            self.assertNotIn(
                '--expected-entity-version', argv_to_flags(update_argv),
                'a negative probe must never append --expected-entity-version',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_missing_reason_refusal_unaffected_by_version_probe(self):
        """Step 7's existing fail-loud refusal (missing --reason on the
        base OUTCOME_UPDATE_CLI_CAPABLE conjunction) must still fire,
        unchanged, naming --reason -- the version probe has no effect on
        it. Reuses the Phase 42 shim/tree builder directly; the version
        probe there is negative by construction (the Phase 42 shim never
        advertises the flag), which is exactly the case being asserted."""
        sid, job_id = 'p59c-sid-002', 'p59c-missing-reason-job'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(sid, job_id, sidecar_lines=[record],
                                    outcome_update_capable=False)
        )
        try:
            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '100', '--currency', 'USD',
                '--reason', 'should be refused',
            ])
            self.assertEqual(rc, 1, f'stdout={out!r} stderr={err!r}')
            self.assertIn('--reason', err)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class PositiveProbeVersionTests(unittest.TestCase):
    """Criterion 4: a CLI whose help advertises the version flag reads the
    job's current entityVersion via `jobs get` and carries it into the
    `jobs outcome-update` argv, matching the new sibling golden."""

    def test_positive_probe_reads_version_and_ships_it(self):
        sid, job_id = 'p59c-sid-010', 'assess-59-versioned-job'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_versioned_correction_tree(
                sid, job_id, sidecar_lines=[record],
                version_flag_capable=True, entity_version_json='{"entityVersion": 7}',
            )
        )
        try:
            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '525.0', '--currency', 'USD',
                '--reason', 'correction-golden-reason-versioned',
            ])
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')

            invocations = _jobs_log_invocations(jobs_log)
            get_invocations = _get_invocations(invocations)
            self.assertEqual(
                len(get_invocations), 1,
                f'expected exactly one jobs get invocation: {invocations}',
            )
            self.assertIn(job_id, get_invocations[0])
            self.assertIn('--output', get_invocations[0])
            self.assertIn('json', get_invocations[0])

            update_argv = _update_argv(invocations)
            self.assertIsNotNone(update_argv, f'expected an outcome-update invocation: {invocations}')
            assert_argv_matches_golden(
                self, update_argv, load_golden('jobs-outcome-update-versioned.golden.json'))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class VersionUnreadableFailOpenTests(unittest.TestCase):
    """D-11: every way the `jobs get` read can fail to produce a usable
    version lands on shipping the correction WITHOUT
    `--expected-entity-version`, never on a refusal."""

    def _run_fail_open_arm(self, entity_version_json, jobs_get_exit=0):
        sid = f'p59c-failopen-sid-{abs(hash((entity_version_json, jobs_get_exit))) % 100000}'
        job_id = f'p59c-failopen-job-{abs(hash((entity_version_json, jobs_get_exit))) % 100000}'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_versioned_correction_tree(
                sid, job_id, sidecar_lines=[record],
                version_flag_capable=True, entity_version_json=entity_version_json,
                jobs_get_exit=jobs_get_exit,
            )
        )
        try:
            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '100', '--currency', 'USD',
                '--reason', 'fail-open arm',
            ])
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            invocations = _jobs_log_invocations(jobs_log)
            update_argv = _update_argv(invocations)
            self.assertIsNotNone(update_argv, f'expected an outcome-update invocation: {invocations}')
            self.assertNotIn(
                '--expected-entity-version', argv_to_flags(update_argv),
                f'expected no version flag on a fail-open arm: {update_argv}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_jobs_get_exits_nonzero(self):
        self._run_fail_open_arm('{"entityVersion": 7}', jobs_get_exit=1)

    def test_jobs_get_returns_non_json(self):
        self._run_fail_open_arm('not json at all')

    def test_jobs_get_returns_object_with_no_entity_version(self):
        self._run_fail_open_arm('{"status": "ok"}')

    def test_jobs_get_returns_entity_version_as_boolean(self):
        self._run_fail_open_arm('{"entityVersion": true}')

    def test_jobs_get_returns_entity_version_as_non_integer(self):
        self._run_fail_open_arm('{"entityVersion": "seven"}')


class ConflictMessageTests(unittest.TestCase):
    """D-12/D-13/D-14/D-15: a 409 gets a distinct, actionable message; the
    local correction line and the ledger entry both survive it; no
    automatic retry occurs; and everything that is NOT a conflict --
    including an error that merely embeds the digits 409 in a longer
    number -- still takes the existing generic path."""

    def test_409_conflict_names_the_conflict_and_preserves_local_state(self):
        sid, job_id = 'p59c-sid-020', 'p59c-conflict-job'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_versioned_correction_tree(
                sid, job_id, sidecar_lines=[record],
                version_flag_capable=True, entity_version_json='{"entityVersion": 3}',
                outcome_update_result={
                    'exit': 4,
                    'stderr': 'revenium: HTTP 409 Conflict: stale entityVersion',
                },
            )
        )
        try:
            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '650', '--currency', 'USD',
                '--reason', 'conflict arm',
            ])
            self.assertEqual(rc, 1, f'stdout={out!r} stderr={err!r}')
            self.assertNotIn(
                'may be re-run once the underlying issue is fixed', err,
                'a 409 must not carry the generic re-run advice',
            )
            self.assertIn('intact', err)
            self.assertIn('fresh correction', err.lower())

            lines = _read_sidecar_lines(sidecar_path)
            self.assertEqual(len(lines), 2, 'the local correction line must survive a 409')
            with open(jobs_ledger) as f:
                ledger_text = f.read()
            self.assertIn(f'JOB:{job_id}:correction:', ledger_text)

            invocations = _jobs_log_invocations(jobs_log)
            update_invocations = [
                argv for argv in invocations
                if len(argv) >= 2 and argv[0] == 'jobs' and argv[1] == 'outcome-update'
            ]
            self.assertEqual(
                len(update_invocations), 1,
                'no auto-retry: exactly one outcome-update call must be logged',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_non_409_failure_takes_the_generic_path(self):
        sid, job_id = 'p59c-sid-021', 'p59c-nonconflict-job'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_versioned_correction_tree(
                sid, job_id, sidecar_lines=[record],
                version_flag_capable=True, entity_version_json='{"entityVersion": 3}',
                outcome_update_result={'exit': 3, 'stderr': 'revenium: connection error'},
            )
        )
        try:
            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '650', '--currency', 'USD',
                '--reason', 'non-conflict failure arm',
            ])
            self.assertEqual(rc, 1, f'stdout={out!r} stderr={err!r}')
            self.assertIn('may be re-run once the underlying issue is fixed', err)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_embedded_number_does_not_trigger_conflict_branch(self):
        sid, job_id = 'p59c-sid-022', 'p59c-boundary-job'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_versioned_correction_tree(
                sid, job_id, sidecar_lines=[record],
                version_flag_capable=True, entity_version_json='{"entityVersion": 3}',
                outcome_update_result={
                    'exit': 3,
                    'stderr': 'revenium: error code 4409999 occurred',
                },
            )
        )
        try:
            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '650', '--currency', 'USD',
                '--reason', 'boundary arm',
            ])
            self.assertEqual(rc, 1, f'stdout={out!r} stderr={err!r}')
            self.assertIn(
                'may be re-run once the underlying issue is fixed', err,
                'an embedded 409-like number must not trip the conflict branch',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class DryRunReportingTests(unittest.TestCase):
    """--dry-run must report the version probe result and, when negative,
    state that no `jobs get` call will be made -- without performing any
    file, ledger, or CLI writes."""

    def test_dry_run_reports_negative_probe(self):
        sid, job_id = 'p59c-dryrun-001', 'p59c-dryrun-job-a'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_versioned_correction_tree(
                sid, job_id, sidecar_lines=[record],
                version_flag_capable=False, entity_version_json='{"entityVersion": 1}',
            )
        )
        try:
            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '10', '--currency', 'USD',
                '--reason', 'dry run probe', '--dry-run',
            ])
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertIn('does NOT support', out)
            self.assertIn('jobs get', out)
            self.assertEqual(_jobs_log_invocations(jobs_log), [])
            self.assertEqual(len(_read_sidecar_lines(sidecar_path)), 1, '--dry-run must write nothing to the sidecar')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_dry_run_reports_positive_probe(self):
        sid, job_id = 'p59c-dryrun-002', 'p59c-dryrun-job-b'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_versioned_correction_tree(
                sid, job_id, sidecar_lines=[record],
                version_flag_capable=True, entity_version_json='{"entityVersion": 1}',
            )
        )
        try:
            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '10', '--currency', 'USD',
                '--reason', 'dry run probe', '--dry-run',
            ])
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertIn('supports', out)
            self.assertEqual(_jobs_log_invocations(jobs_log), [])
            self.assertEqual(len(_read_sidecar_lines(sidecar_path)), 1, '--dry-run must write nothing to the sidecar')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
