"""Phase 38 Plan 01 — the assessment reaches `revenium jobs outcome`.

Carries an accepted assessment (Phase 36/37's frozen nested object,
`job.get("assessment")`) from the session's job marker to the two
`jobs outcome` value flags plus provenance in `--metadata`.

Source-of-truth: skills/revenium/scripts/hermes-report.sh post-loop outcome
stage (job_outcome_queue push sites + the assessment resolver + the extended
--metadata heredoc).

Requirements covered:
  ROI-10 — the assessment reaches Revenium as --outcome-value/--outcome-currency
           plus provenance in --metadata, never as a sixth queue pipe field.
  ROI-12 — backward-compatible markers: a marker line with no "assessment" key
           at all still parses and reports normally.

Reuses the no-shift shim + synthetic state.db harness from _compat_helpers
(the same harness tests/test_compat_jobs_outcome.py and
tests/test_jobs_outcome_metadata.py already use for this exact stage).

Task 1: the sixth queue field (sid). Task 2: the assessment resolver and
the value + provenance flags. Task 3 (this commit): the new golden and
pre-v1.5 backward-compatibility coverage.

Plan 02 adds the two guarantees invisible in a single-tick test: idempotency
across ticks (deferred-create survival, the double-outcome/409 paths) and the
ROI-13 canary sweep across every persisted artifact — the marker, all three
ledgers, the log, and the argv itself, not just the marker Phase 37 checked.
"""
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest

from tests._compat_helpers import (
    assert_argv_matches_golden,
    build_shim,
    build_state_db,
    load_golden,
    run_script,
    SCRIPTS_DIR,
)

# The frozen assessment contract (classifier.py's _validate_assessment
# return shape). estimated_value = 3.5 * 150.0 = 525.0, matching what the
# evaluator itself would derive -- chosen here directly since these tests
# exercise hermes-report.sh's READ side, not the classifier's derivation.
ASSESSMENT_FIXTURE = {
    "estimated_value": 525.0,
    "currency": "USD",
    "basis": "3.5 hours of senior engineer review time",
    "assumptions": {
        "inferred_role": "senior software engineer",
        "estimated_hours_saved": 3.5,
        "assumed_loaded_rate": 150.0,
    },
    "confidence": 0.8,
    "evaluator": "llm",
    "evaluator_version": "v1",
    "evidence_class": "MODEL_ESTIMATED_DEMO",
}


class TestPhase38ReporterPath(unittest.TestCase):
    def _run_one_outcome(self, sid, job_id, status, failure_reason='', source='test',
                          assessment=None):
        """Drive hermes-report.sh for one job arc; return the parsed
        `jobs outcome` argv. Mirrors _run_one_outcome in
        tests/test_jobs_outcome_metadata.py, extended with an optional
        assessment payload on the job marker."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase38-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')
            jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir, 'meter.log')
            jobs_log = os.path.join(tmpdir, 'jobs.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            shim = os.path.join(bin_dir, 'revenium')

            build_state_db(state_db, [{
                'id': sid,
                'model': 'claude-sonnet-4-6',
                'source': source,
                'input_tokens': 100,
                'output_tokens': 50,
                'cache_read': 0,
                'cache_write': 0,
                'reasoning': 0,
                'estimated_cost': '0',
                'api_calls': 1,
                'started_at': 1715514000.0,
                'ended_at': 1715514000.0,
                'billing_provider': 'anthropic',
            }])

            # Pre-seed created line so the outcome stage does not defer (OUTCOME-04).
            os.makedirs(os.path.dirname(jobs_ledger), exist_ok=True)
            with open(jobs_ledger, 'w') as f:
                f.write(f'JOB:{job_id}:created:1715516001.000\n')

            task_marker = {
                'muid': f'{job_id}-task',
                'ts': 1715516000.5,
                'sid': sid,
                'task_type': 'code_review',
                'operation_type': 'CHAT',
            }
            job_marker = {
                'kind': 'job',
                'ts': 1715516002.0,
                'sid': sid,
                'agentic_job_id': job_id,
                'job_name': 'Phase 38 Test Job',
                'job_type': 'code_review',
                'status': status,
            }
            # The classifier only writes failure_reason for FAILED arcs; mirror that.
            if failure_reason:
                job_marker['failure_reason'] = failure_reason
            # ROI-12: when assessment is None, the key is simply absent -- the
            # same shape a pre-v1.5 marker line has.
            if assessment is not None:
                job_marker['assessment'] = assessment
            with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
                f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
                f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

            build_shim(shim)

            base_env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'INVOCATIONS_LOG': inv_log,
                'METER_LOG': meter_log,
                'JOBS_LOG': jobs_log,
                'TZ': 'UTC',
                'REVENIUM_ORGANIZATION_NAME': '',
            }

            rc, _ignored, output = run_script(
                SCRIPTS_DIR / 'hermes-report.sh', base_env, inv_log
            )
            self.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {output}')

            outcome_inv = []
            if os.path.exists(jobs_log):
                with open(jobs_log) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if not line:
                            continue
                        argv = shlex.split(line)
                        if len(argv) >= 2 and argv[0] == 'jobs' and argv[1] == 'outcome':
                            outcome_inv.append(argv)

            self.assertEqual(
                len(outcome_inv), 1,
                f'expected exactly 1 "jobs outcome" invocation, got {len(outcome_inv)}: '
                f'{outcome_inv!r}\nOutput: {output}'
            )
            return outcome_inv[0]
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @staticmethod
    def _metadata_value(argv):
        for i, tok in enumerate(argv):
            if tok == '--metadata' and i + 1 < len(argv):
                return argv[i + 1]
        return None

    # -- Task 1: sid as the sixth queue field must not shift anything -----

    def test_queue_unvalued_success_job_reports_outcome_unchanged(self):
        """T-38-01: a job with no assessment still reports its outcome
        exactly as before the sixth (sid) field was added."""
        argv = self._run_one_outcome('q38-sid-001', 'q38-job-001', 'SUCCESS')
        self.assertEqual(argv[argv.index('--result') + 1], 'SUCCESS')
        self.assertEqual(argv[argv.index('--outcome-type') + 1], 'CONVERTED')
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta, {'source': 'test'})

    def test_queue_field_addition_does_not_shift_failed_arc_metadata(self):
        """T-38-01: source/failure_reason must land in the same positions
        they always have -- a shifted tuple would corrupt these, not the new
        field, which is the failure mode this test is built to catch."""
        argv = self._run_one_outcome(
            'q38-sid-002', 'q38-job-002', 'FAILED', failure_reason='3 assertions failed',
        )
        self.assertEqual(argv[argv.index('--result') + 1], 'FAILED')
        self.assertNotIn('--outcome-type', argv)
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta.get('source'), 'test')
        self.assertEqual(meta.get('failure_reason'), '3 assertions failed')

    # -- Task 2: an accepted assessment ships as value + provenance -------

    def test_outcome_success_with_assessment_ships_value_and_provenance(self):
        argv = self._run_one_outcome(
            'o38-sid-001', 'o38-job-001', 'SUCCESS', assessment=ASSESSMENT_FIXTURE,
        )
        self.assertEqual(argv[argv.index('--outcome-value') + 1], '525.0')
        self.assertEqual(argv[argv.index('--outcome-currency') + 1], 'USD')
        self.assertEqual(argv[argv.index('--outcome-type') + 1], 'CONVERTED')

        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta.get('evidence_class'), 'MODEL_ESTIMATED_DEMO')
        self.assertEqual(meta.get('evaluator'), 'llm')
        self.assertEqual(meta.get('evaluator_version'), 'v1')
        self.assertEqual(meta.get('confidence'), 0.8)
        self.assertEqual(
            meta.get('assumptions'),
            {'estimated_hours_saved': 3.5, 'assumed_loaded_rate': 150.0},
        )
        # basis / inferred_role are not part of the provenance list this plan
        # names (evidence_class, evaluator, evaluator_version, confidence,
        # and the two numeric assumptions) -- they stay out of --metadata.
        self.assertNotIn('basis', meta)
        self.assertNotIn('inferred_role', meta)

    def test_outcome_success_without_assessment_ships_neither_value_flag(self):
        argv = self._run_one_outcome('o38-sid-002', 'o38-job-002', 'SUCCESS')
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta, {'source': 'test'})

    def test_outcome_failed_argv_unchanged_by_assessment_logic(self):
        """ROI-09: FAILED/CANCELLED are never evaluated by the classifier, so
        no real marker ever carries {status: FAILED, assessment: {...}}. This
        feeds that shape anyway to prove the outcome stage's OWN guard --
        not just the classifier's -- refuses to ship a value for a non-SUCCESS
        arc."""
        argv = self._run_one_outcome(
            'o38-sid-003', 'o38-job-003', 'FAILED',
            failure_reason='boom', assessment=ASSESSMENT_FIXTURE,
        )
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)
        self.assertNotIn('--outcome-type', argv)
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta.get('source'), 'test')
        self.assertEqual(meta.get('failure_reason'), 'boom')
        self.assertNotIn('evidence_class', meta)

    def test_outcome_cancelled_never_carries_a_value(self):
        argv = self._run_one_outcome(
            'o38-sid-004', 'o38-job-004', 'CANCELLED', assessment=ASSESSMENT_FIXTURE,
        )
        self.assertEqual(argv[argv.index('--result') + 1], 'CANCELLED')
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)
        self.assertNotIn('--outcome-type', argv)

    # -- Task 3: the new golden, and pre-v1.5 backward compatibility ------

    def test_golden_valued_outcome_matches_new_fixture(self):
        argv = self._run_one_outcome(
            'g38-sid-002', 'assessment-golden-job', 'SUCCESS', assessment=ASSESSMENT_FIXTURE,
        )
        golden = load_golden('meter-completion-assessment.golden.json')
        assert_argv_matches_golden(self, argv, golden)

    def test_pre_v1_5_marker_with_no_assessment_key_parses_and_reports(self):
        """ROI-12: a marker line written before v1.5 -- literally no
        "assessment" key in the JSON object, not merely an empty one --
        still parses and reports its outcome with no value flags."""
        argv = self._run_one_outcome('bc38-sid-001', 'bc38-job-001', 'SUCCESS')
        self.assertEqual(argv[argv.index('--result') + 1], 'SUCCESS')
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta, {'source': 'test'})


# ---------------------------------------------------------------------------
# Plan 02, Tasks 1 & 2 — the two guarantees only visible across ticks.
# ---------------------------------------------------------------------------

def _outcome_invocations(jobs_invocations, verb):
    """Filter jobs_invocations (NO-SHIFT argv, first token 'jobs') by subcommand."""
    return [a for a in jobs_invocations if len(a) >= 2 and a[0] == 'jobs' and a[1] == verb]


def _metadata_of(argv):
    for i, tok in enumerate(argv):
        if tok == '--metadata' and i + 1 < len(argv):
            return argv[i + 1]
    return None


def _build_flexible_shim(shim_path):
    """revenium shim whose jobs-create / jobs-outcome exit codes and stdout are
    controlled per-run via JOBS_CREATE_EXIT_CODE / JOBS_CREATE_OUTPUT_TEXT /
    OUTCOME_EXIT_CODE / OUTCOME_OUTPUT_TEXT env vars (default: succeed silently).

    Full argv is logged NO-SHIFT (starting with the 'jobs' verb) to JOBS_LOG,
    matching build_shim's shape in _compat_helpers so ('jobs', 'create'/'outcome')
    filtering stays identical across this file. meter completion is logged the
    same way to METER_LOG; `meter completion --help` advertises
    --agentic-job-id so JOBS_CLI_CAPABLE resolves true, matching build_shim.
    """
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
        '    printf "%q " "$@" >> "${JOBS_LOG:-/dev/null}"\n'
        '    printf "\\n" >> "${JOBS_LOG:-/dev/null}"\n'
        '    if [[ "$2" == "create" ]]; then\n'
        '      if [[ -n "${JOBS_CREATE_OUTPUT_TEXT:-}" ]]; then echo "${JOBS_CREATE_OUTPUT_TEXT}"; fi\n'
        '      exit "${JOBS_CREATE_EXIT_CODE:-0}"\n'
        '    elif [[ "$2" == "outcome" ]]; then\n'
        '      if [[ -n "${OUTCOME_OUTPUT_TEXT:-}" ]]; then echo "${OUTCOME_OUTPUT_TEXT}"; fi\n'
        '      exit "${OUTCOME_EXIT_CODE:-0}"\n'
        '    fi\n'
        '    exit 0\n'
        '    ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n'
    )
    with open(shim_path, 'w') as f:
        f.write(body)
    os.chmod(shim_path, 0o755)


class TestPhase38MultiTick(unittest.TestCase):
    """Tasks 1 & 2 — the two guarantees only visible across ticks.

    Both tasks share one harness: a persistent tmpdir (jobs ledger NOT reset
    between runs, unlike the single-tick helper above) driven through a
    configurable shim so a given run's jobs-create / jobs-outcome exit code
    can be scripted per tick.
    """

    def _setup(self, sid, job_id, status='SUCCESS', assessment=None, seed_created=False):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase38-multitick-')
        hermes_home = os.path.join(tmpdir, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        markers_dir = os.path.join(state_dir, 'markers')
        os.makedirs(markers_dir, mode=0o700)
        state_db = os.path.join(hermes_home, 'state.db')
        jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')

        shim_home = os.path.join(tmpdir, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)
        meter_log = os.path.join(tmpdir, 'meter.log')
        jobs_log = os.path.join(tmpdir, 'jobs.log')
        shim = os.path.join(bin_dir, 'revenium')

        build_state_db(state_db, [{
            'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
            'input_tokens': 100, 'output_tokens': 50,
            'cache_read': 0, 'cache_write': 0, 'reasoning': 0,
            'estimated_cost': '0', 'api_calls': 1,
            'started_at': 1715514000.0, 'ended_at': 1715514000.0,
            'billing_provider': 'anthropic',
        }])

        task_marker = {
            'muid': f'{job_id}-task', 'ts': 1715516000.5, 'sid': sid,
            'task_type': 'code_review', 'operation_type': 'CHAT',
        }
        job_marker = {
            'kind': 'job', 'ts': 1715516002.0, 'sid': sid,
            'agentic_job_id': job_id, 'job_name': 'Phase 38 Multi-Tick Test',
            'job_type': 'code_review', 'status': status,
        }
        if assessment is not None:
            job_marker['assessment'] = assessment
        with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
            f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
            f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

        if seed_created:
            with open(jobs_ledger, 'w') as f:
                f.write(f'JOB:{job_id}:created:1715516001.000\n')

        _build_flexible_shim(shim)

        base_env = {
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
        return tmpdir, base_env, meter_log, jobs_log, jobs_ledger, state_dir

    def _run_tick(self, env, meter_log, jobs_log, state_dir):
        """Run hermes-report.sh once. meter_log/jobs_log are truncated first so
        each tick's return value covers only that tick's invocations; the jobs
        ledger and the marker file are left untouched -- persistence across
        ticks is the entire point of this harness."""
        for log in (meter_log, jobs_log):
            if os.path.exists(log):
                os.unlink(log)
            open(log, 'w').close()
        metering_log = os.path.join(state_dir, 'revenium-metering.log')
        if os.path.exists(metering_log):
            os.unlink(metering_log)
        result = subprocess.run(
            ['bash', str(SCRIPTS_DIR / 'hermes-report.sh')],
            env=env, capture_output=True, text=True, timeout=60,
        )

        def _parse(path):
            invocations = []
            if os.path.exists(path):
                with open(path) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            invocations.append(shlex.split(line))
            return invocations

        metering_content = open(metering_log).read() if os.path.exists(metering_log) else ''
        return (
            result.returncode,
            _parse(meter_log),
            _parse(jobs_log),
            result.stdout + result.stderr + metering_content,
        )

    # -- Task 1: the deferred-create path, across ticks --------------------

    def test_deferred_create_survives_to_next_tick_with_assessment_intact(self):
        """T-38-06 / the research doc's own deciding test: an assessment must
        still be reachable on the tick AFTER the one that inferred it, even
        when the create call that tick deferred on. OUTCOME-04 governs the
        defer; the precheck scan (not the token-gated main loop) is what
        re-reaches the job on tick 2."""
        sid = 'p38-defer-sid-001'
        job_id = 'p38-defer-job-001'
        tmpdir, env, meter_log, jobs_log, jobs_ledger, state_dir = self._setup(
            sid, job_id, status='SUCCESS', assessment=ASSESSMENT_FIXTURE, seed_created=False,
        )
        try:
            # Tick 1: jobs create fails (no 409 indicator) -> the outcome
            # stage's OUTCOME-04 gate finds no created line and defers.
            env1 = {**env, 'JOBS_CREATE_EXIT_CODE': '1'}
            rc1, meter_inv1, jobs_inv1, out1 = self._run_tick(env1, meter_log, jobs_log, state_dir)
            self.assertEqual(rc1, 0, f'tick 1 exit {rc1}: {out1}')
            self.assertEqual(
                len(_outcome_invocations(jobs_inv1, 'outcome')), 0,
                f'tick 1 must send no outcome (create failed, no created line): {jobs_inv1}',
            )
            self.assertTrue(
                'outcome deferred' in out1 or 'wedged job' in out1,
                f'expected an OUTCOME-04 defer warning in tick 1 output: {out1}',
            )
            self.assertFalse(
                os.path.exists(jobs_ledger) and 'created:' in open(jobs_ledger).read(),
                'no created line should exist after tick 1s failed create',
            )
            # First sighting of this session -> exactly one completion metered.
            self.assertEqual(len(meter_inv1), 1, f'tick 1 should meter the session once: {meter_inv1}')

            # Tick 2: same unchanged state.db (tokens have NOT grown); create
            # now succeeds, so the same-tick create+outcome ordering (D-01)
            # lets the deferred outcome ship immediately, with the assessment
            # still intact from the marker the classifier wrote once.
            env2 = {**env, 'JOBS_CREATE_EXIT_CODE': '0'}
            rc2, meter_inv2, jobs_inv2, out2 = self._run_tick(env2, meter_log, jobs_log, state_dir)
            self.assertEqual(rc2, 0, f'tick 2 exit {rc2}: {out2}')

            # The main loop's ledger gate (~:1810) must have skipped re-metering
            # this session -- direct proof its total_tokens did not grow between
            # ticks, which is the whole premise the precheck-scan carrier relies
            # on (38-RESEARCH.md).
            self.assertEqual(
                len(meter_inv2), 0,
                f'tick 2 must not re-meter a token-stable session: {meter_inv2}',
            )

            outcome_inv2 = _outcome_invocations(jobs_inv2, 'outcome')
            self.assertEqual(len(outcome_inv2), 1, f'tick 2 must ship exactly one outcome: {jobs_inv2}')
            argv2 = outcome_inv2[0]
            self.assertEqual(argv2[argv2.index('--outcome-value') + 1], '525.0')
            self.assertEqual(argv2[argv2.index('--outcome-currency') + 1], 'USD')
            meta2 = json.loads(_metadata_of(argv2))
            self.assertEqual(meta2.get('evidence_class'), 'MODEL_ESTIMATED_DEMO')
            self.assertEqual(meta2.get('evaluator'), 'llm')
            self.assertEqual(meta2.get('confidence'), 0.8)
            self.assertEqual(
                meta2.get('assumptions'),
                {'estimated_hours_saved': 3.5, 'assumed_loaded_rate': 150.0},
            )

            ledger_text = open(jobs_ledger).read()
            self.assertTrue(
                any(l.startswith(f'JOB:{job_id}:outcome:') for l in ledger_text.splitlines()),
                f'expected an outcome ledger line after tick 2: {ledger_text}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # -- Task 2: idempotency — no second outcome, no second value ----------

    def test_idempotent_rerun_produces_exactly_one_outcome_and_one_ledger_line(self):
        """Two full ticks against unchanged state: exactly one `jobs outcome`
        call total, exactly one ledger line, and the second tick attempts no
        `jobs create` either (the arc was already created before tick 1)."""
        sid = 'p38-idem-sid-001'
        job_id = 'p38-idem-job-001'
        tmpdir, env, meter_log, jobs_log, jobs_ledger, state_dir = self._setup(
            sid, job_id, status='SUCCESS', assessment=ASSESSMENT_FIXTURE, seed_created=True,
        )
        try:
            rc1, _m1, jobs_inv1, out1 = self._run_tick(env, meter_log, jobs_log, state_dir)
            self.assertEqual(rc1, 0, f'run 1 exit {rc1}: {out1}')
            outcome_inv1 = _outcome_invocations(jobs_inv1, 'outcome')
            self.assertEqual(len(outcome_inv1), 1, f'run 1 must ship exactly one outcome: {jobs_inv1}')

            rc2, _m2, jobs_inv2, out2 = self._run_tick(env, meter_log, jobs_log, state_dir)
            self.assertEqual(rc2, 0, f'run 2 exit {rc2}: {out2}')
            outcome_inv2 = _outcome_invocations(jobs_inv2, 'outcome')
            create_inv2 = _outcome_invocations(jobs_inv2, 'create')
            self.assertEqual(
                len(outcome_inv2), 0,
                f'idempotency violated: run 2 must ship zero outcomes (ledger-gated): {jobs_inv2}',
            )
            self.assertEqual(
                len(create_inv2), 0,
                f'run 2 must attempt zero creates (already created): {jobs_inv2}',
            )

            total_outcome = len(outcome_inv1) + len(outcome_inv2)
            self.assertEqual(total_outcome, 1, 'exactly one outcome call across both runs')

            ledger_text = open(jobs_ledger).read()
            outcome_lines = [
                l for l in ledger_text.splitlines() if l.startswith(f'JOB:{job_id}:outcome:')
            ]
            self.assertEqual(
                len(outcome_lines), 1, f'expected exactly one outcome ledger line, got: {outcome_lines}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_idempotent_409_is_success_equivalent_and_not_retried(self):
        """OUTCOME-03: a 409/already-exists response from `jobs outcome` is
        treated as success-equivalent -- the ledger line is written on that
        same run, and a later tick does not retry it."""
        sid = 'p38-idem409-sid-001'
        job_id = 'p38-idem409-job-001'
        tmpdir, env, meter_log, jobs_log, jobs_ledger, state_dir = self._setup(
            sid, job_id, status='SUCCESS', assessment=ASSESSMENT_FIXTURE, seed_created=True,
        )
        try:
            env1 = {
                **env,
                'OUTCOME_EXIT_CODE': '1',
                'OUTCOME_OUTPUT_TEXT': 'Error: HTTP 409 Conflict - outcome already recorded',
            }
            rc1, _m1, jobs_inv1, out1 = self._run_tick(env1, meter_log, jobs_log, state_dir)
            self.assertEqual(rc1, 0, f'409 run exit {rc1}: {out1}')
            outcome_inv1 = _outcome_invocations(jobs_inv1, 'outcome')
            self.assertEqual(
                len(outcome_inv1), 1, f'exactly one outcome attempt on the 409 run: {jobs_inv1}',
            )

            ledger_text = open(jobs_ledger).read()
            outcome_lines = [
                l for l in ledger_text.splitlines() if l.startswith(f'JOB:{job_id}:outcome:')
            ]
            self.assertEqual(
                len(outcome_lines), 1,
                f'OUTCOME-03: a 409 must write the ledger line as success-equivalent, got: {outcome_lines}',
            )

            # A later tick, even with the shim now returning a clean 0, must
            # not retry -- the ledger gate (OUTCOME-01) suppresses it.
            env2 = {**env, 'OUTCOME_EXIT_CODE': '0'}
            rc2, _m2, jobs_inv2, out2 = self._run_tick(env2, meter_log, jobs_log, state_dir)
            self.assertEqual(rc2, 0, f'retry-check run exit {rc2}: {out2}')
            outcome_inv2 = _outcome_invocations(jobs_inv2, 'outcome')
            self.assertEqual(
                len(outcome_inv2), 0, f'no retry expected after a 409-success: {jobs_inv2}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
