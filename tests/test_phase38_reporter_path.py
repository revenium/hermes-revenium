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
import asyncio
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys as _sys
import tempfile
import unittest

from tests._compat_helpers import (
    assert_argv_matches_golden,
    build_shim,
    build_state_db,
    load_golden,
    run_script,
    ROOT,
    SCRIPTS_DIR,
)

PLUGIN_DIR = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'

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
                          assessment=None, raw_agentic_job_id=None,
                          outcome_value_capable=True):
        """Drive hermes-report.sh for one job arc; return the parsed
        `jobs outcome` argv. Mirrors _run_one_outcome in
        tests/test_jobs_outcome_metadata.py, extended with an optional
        assessment payload on the job marker.

        job_id is the SANITIZED id (D-16): it is what the JOBS_LEDGER
        "created" line and the expected `jobs outcome <id>` argv use, since
        that is what hermes-report.sh's own job-scan always writes/queues.
        raw_agentic_job_id, when given, is written as the marker's raw
        (unsanitized) agentic_job_id instead of job_id -- this is CR-02's
        regression shape: a job id containing a colon/space/tab sanitizes to
        a different string than what the marker stores on disk.

        outcome_value_capable=False (CR-01/WR-03) builds the shim so `jobs
        outcome --help` omits --outcome-value/--outcome-currency, modelling
        an older revenium CLI that predates the two flags.
        """
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
                'agentic_job_id': raw_agentic_job_id if raw_agentic_job_id is not None else job_id,
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

            build_shim(shim, outcome_value_capable=outcome_value_capable)

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

    # -- CR-02 regression: sanitized queue id vs raw marker id ------------

    def test_assessment_lookup_survives_a_job_id_needing_sanitization(self):
        """CR-02: job_outcome_queue's outcome_id is SANITIZED (D-16, both
        push sites replace ':'/' '/'\\t'/'\\n'/'\\r' with '_' before pushing),
        but classifier.py writes the marker's agentic_job_id RAW (only
        .strip()'d). A job id containing a colon or space must still have
        its assessment resolved -- the lookup has to sanitize the marker's
        raw id the same way before comparing, or this silently drops the
        value for exactly the job ids most likely to need it (LLM-minted
        labels routinely contain ': ')."""
        raw_id = 'fix: auth regression_a1b2'
        clean_id = raw_id
        for bad in (':', ' ', '\t', '\n', '\r'):
            clean_id = clean_id.replace(bad, '_')
        self.assertNotEqual(raw_id, clean_id, 'fixture must actually need sanitizing')

        argv = self._run_one_outcome(
            'cr02-sid-001', clean_id, 'SUCCESS',
            assessment=ASSESSMENT_FIXTURE, raw_agentic_job_id=raw_id,
        )
        self.assertEqual(argv[2], clean_id, f'jobs outcome must target the sanitized id: {argv}')
        self.assertEqual(argv[argv.index('--outcome-value') + 1], '525.0')
        self.assertEqual(argv[argv.index('--outcome-currency') + 1], 'USD')
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta.get('evidence_class'), 'MODEL_ESTIMATED_DEMO')

    # -- WR-02: malformed value/currency must never reach the CLI ---------

    def test_non_numeric_estimated_value_omits_both_value_flags(self):
        """WR-02: estimated_value is shipped straight to --outcome-value
        with no numeric validation, unlike confidence/estimated_hours_saved/
        assumed_loaded_rate which are round-tripped through float(). A
        hand-edited or malformed marker with a non-numeric estimated_value
        must not ship a bad monetary value to the CLI -- both flags are
        omitted together (fail-open-and-omit-both), the same posture used
        when only one of the pair is present."""
        bad_assessment = dict(ASSESSMENT_FIXTURE, estimated_value='not-a-number')
        argv = self._run_one_outcome(
            'wr02-sid-001', 'wr02-job-001', 'SUCCESS', assessment=bad_assessment,
        )
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)
        # Provenance unrelated to the malformed value still ships.
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta.get('evidence_class'), 'MODEL_ESTIMATED_DEMO')

    def test_unsupported_currency_omits_both_value_flags(self):
        """WR-02: currency is never checked against SUPPORTED_CURRENCIES on
        read. An unsupported/malformed currency must drop both flags, not
        ship a bare unvalidated string as --outcome-currency."""
        bad_assessment = dict(ASSESSMENT_FIXTURE, currency='NOTACURRENCY')
        argv = self._run_one_outcome(
            'wr02-sid-002', 'wr02-job-002', 'SUCCESS', assessment=bad_assessment,
        )
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)

    # -- WR-03 / CR-01 regression: older CLI without the value flags ------

    def test_outcome_still_ships_when_cli_lacks_outcome_value_flags(self):
        """CR-01: an older `revenium` CLI predating --outcome-value /
        --outcome-currency must not have its ENTIRE `jobs outcome` call
        rejected -- it must ship with neither flag (fail open), and the
        ledger line must still be written (implied here by the shared
        helper's own "exactly 1 jobs outcome invocation" assertion). Without
        the capability probe, this shim (whose `jobs outcome --help` omits
        both flags) proves the bug: hermes-report.sh would still emit two
        flags this "CLI" never advertised support for."""
        argv = self._run_one_outcome(
            'cr01-sid-001', 'cr01-job-001', 'SUCCESS',
            assessment=ASSESSMENT_FIXTURE, outcome_value_capable=False,
        )
        self.assertEqual(argv[argv.index('--result') + 1], 'SUCCESS')
        self.assertEqual(argv[argv.index('--outcome-type') + 1], 'CONVERTED')
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)
        # Provenance (which does not depend on the CLI's flag support) still
        # rides in --metadata even though the value flags were omitted.
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta.get('evidence_class'), 'MODEL_ESTIMATED_DEMO')

    def test_outcome_omits_pair_when_cli_advertises_only_outcome_value(self):
        """greptile P2 on PR #90: the emission site sends --outcome-value and
        --outcome-currency together, so gating the pair on a probe of only the
        FIRST half reintroduces CR-01's wedge through the half nobody checked.
        A CLI advertising --outcome-value WITHOUT --outcome-currency must
        resolve the gate to false and ship neither flag -- not take the enabled
        branch and have the whole `jobs outcome` call rejected."""
        argv = self._run_one_outcome(
            'p2-sid-001', 'p2-job-001', 'SUCCESS',
            assessment=ASSESSMENT_FIXTURE, outcome_value_capable='value-only',
        )
        self.assertEqual(argv[argv.index('--result') + 1], 'SUCCESS')
        self.assertEqual(argv[argv.index('--outcome-type') + 1], 'CONVERTED')
        # Both halves omitted -- "both or neither" holds even when the CLI
        # advertises exactly one of them.
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta.get('evidence_class'), 'MODEL_ESTIMATED_DEMO')


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


def _build_flexible_shim(shim_path, outcome_value_capable=True):
    """revenium shim whose jobs-create / jobs-outcome exit codes and stdout are
    controlled per-run via JOBS_CREATE_EXIT_CODE / JOBS_CREATE_OUTPUT_TEXT /
    OUTCOME_EXIT_CODE / OUTCOME_OUTPUT_TEXT env vars (default: succeed silently).

    Full argv is logged NO-SHIFT (starting with the 'jobs' verb) to JOBS_LOG,
    matching build_shim's shape in _compat_helpers so ('jobs', 'create'/'outcome')
    filtering stays identical across this file. meter completion is logged the
    same way to METER_LOG; `meter completion --help` advertises
    --agentic-job-id so JOBS_CLI_CAPABLE resolves true, matching build_shim.

    outcome_value_capable mirrors build_shim's kwarg of the same name (Phase
    38 CR-01/WR-03): default True advertises --outcome-value/--outcome-currency
    on the `jobs outcome --help` probe; False omits them.
    """
    if outcome_value_capable == 'value-only':
        outcome_value_help_lines = (
            '      echo "--outcome-value string     Business outcome value"\n'
        )
    elif outcome_value_capable:
        outcome_value_help_lines = (
            '      echo "--outcome-value string     Business outcome value"\n'
            '      echo "--outcome-currency string   Business outcome currency"\n'
        )
    else:
        outcome_value_help_lines = ''
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
        # Phase 38 (CR-01): supports_flag "jobs outcome" "--outcome-value" calls
        # `revenium jobs outcome --help`. Answer it here, before the generic
        # JOBS_LOG capture below, so the probe is never logged as a real
        # "jobs outcome" invocation.
        '    if [[ "$2" == "outcome" && "$3" == "--help" ]]; then\n'
        + outcome_value_help_lines +
        '      exit 0\n'
        '    fi\n'
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


# ---------------------------------------------------------------------------
# Plan 02, Task 3 — the ROI-13 canary sweep.
#
# Copies the isolated-import pattern from tests/test_phase37_llm_evaluator.py
# (a UNIQUE module name per call, because the classifier binds its path
# constants at import time and Python caches submodules by name — reusing one
# name would return a classifier still bound to a PRIOR test's temp
# directory). Restoring only at tearDownModule (module-scoped, once for the
# WHOLE file) is not enough here: this file's OTHER classes
# (TestPhase38ReporterPath, TestPhase38MultiTick) spawn hermes-report.sh with
# `**os.environ`, so a REVENIUM_STATE_DIR left pointing at a canary test's
# already-deleted tmpdir silently breaks every later class in the SAME run.
# _restore_env is therefore also called from TestPhase38Canary.tearDown, per
# test, not just at module teardown.
# ---------------------------------------------------------------------------
_LOAD_SEQ = [0]
_ENV_TOUCHED = set()
_ENV_SAVED = {}


def setUpModule():
    for k in ('REVENIUM_STATE_DIR', 'REVENIUM_MARKERS_DIR', 'REVENIUM_CONFIG_FILE',
              'REVENIUM_TAXONOMY_FILE', 'REVENIUM_JOB_TAXONOMY_FILE', 'HERMES_HOME'):
        _ENV_SAVED[k] = os.environ.get(k)


def _restore_env():
    for k in _ENV_TOUCHED | set(_ENV_SAVED):
        prior = _ENV_SAVED.get(k)
        if prior is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = prior


def tearDownModule():
    _restore_env()
    for cached in [k for k in list(_sys.modules) if k.startswith('p38_pkg')]:
        del _sys.modules[cached]


def _load_classifier(env=None):
    """Import the revenium-classifier plugin fresh; return (classifier, evaluators)."""
    for k, v in (env or {}).items():
        os.environ[k] = v
        _ENV_TOUCHED.add(k)
    _LOAD_SEQ[0] += 1
    name = f'p38_pkg_{_LOAD_SEQ[0]}'
    for cached in [k for k in _sys.modules if k.startswith('p38_pkg')]:
        del _sys.modules[cached]
    spec = importlib.util.spec_from_file_location(
        name, str(PLUGIN_DIR / '__init__.py'), submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    _sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return _sys.modules[f'{name}.classifier'], _sys.modules[f'{name}.evaluators']


class TestPhase38Canary(unittest.TestCase):
    """Task 3 — the ROI-13 canary, across every persisted artifact.

    Two canaries, deliberately kept distinct:

      TRANSCRIPT_CANARY  lives in the transcript fed to the evaluator. The
                          evaluator SEES it (proven by an assertion inside the
                          stub itself) but is never asked to echo it back, so
                          it must be absent from every persisted artifact --
                          the marker, all three ledgers, the log, and the
                          jobs-outcome / meter-completion argv.

      EVALUATOR_*_CANARY lives in the evaluator's OWN prose output (basis,
                          inferred_role). This is model-controlled but
                          legitimate content -- it is MEANT to reach the
                          marker. What is under test there is not its
                          absence but that it survives IFS-stripped and
                          clamped to its byte budget (_clamp_assessment_text,
                          200 bytes for basis / 60 for inferred_role).
    """

    TRANSCRIPT_CANARY = 'ZZCANARY-7f3a9-SECRET-SENTINEL'
    EVALUATOR_BASIS_CANARY = 'QQCANARY-b21c4-MODEL-PROSE'
    EVALUATOR_ROLE_CANARY = 'RRCANARY-99f2-ROLE'
    # 39-01 Task 3 -- the malformed response BODY itself, for the `invalid`
    # line's own canary sweep. Deliberately its own constant, not a reuse of
    # EVALUATOR_BASIS_CANARY: that one is MEANT to reach the marker (a
    # presence assertion), and reusing it here for an absence assertion
    # would make the two tests contradict each other.
    RESPONSE_BODY_CANARY = 'MMCANARY-9d21f-BROKEN-RESPONSE'

    def tearDown(self):
        # _load_classifier touches REVENIUM_STATE_DIR/MARKERS_DIR/CONFIG_FILE
        # as PROCESS env vars pointing into this test's tmpdir, which is
        # rmtree'd in the test's own finally block. Restoring per-test (not
        # just at module teardown) keeps TestPhase38ReporterPath and
        # TestPhase38MultiTick -- which spawn hermes-report.sh with
        # `**os.environ` -- from inheriting a dangling path when this class
        # runs earlier in the same module (alphabetical test discovery).
        _restore_env()

    def _canary_evaluator(self, job, transcript, cfg):
        # Proves the evaluator really did receive the transcript canary --
        # the interesting claim is that it is never asked to, and does not,
        # echo it back into its own output.
        self.assertIn(self.TRANSCRIPT_CANARY, transcript)
        basis_raw = (
            self.EVALUATOR_BASIS_CANARY + '|has|pipes\nand\rnewlines then filler-'
            + ('Z' * 300)
        )
        role_raw = self.EVALUATOR_ROLE_CANARY + '|role|pipe\nbreak\r' + ('Y' * 100)
        return {
            'inferred_role': role_raw,
            'estimated_hours_saved': 2.0,
            'assumed_loaded_rate': 100.0,
            'currency': 'USD',
            'basis': basis_raw,
            'confidence': 0.6,
        }

    def _attach_and_write(self, sid, job_id, state_dir, markers_dir):
        os.makedirs(state_dir, exist_ok=True)
        config_file = os.path.join(state_dir, 'config.json')
        with open(config_file, 'w') as f:
            json.dump({'llmOutcomeEvaluation': {
                'enabled': True, 'evaluator': 'p38-canary', 'currency': 'USD',
            }}, f)
        env = {
            'REVENIUM_STATE_DIR': state_dir,
            'REVENIUM_MARKERS_DIR': markers_dir,
            'REVENIUM_CONFIG_FILE': config_file,
        }
        c, ev = _load_classifier(env)
        ev.register('p38-canary', self._canary_evaluator)

        job = {
            'agentic_job_id': job_id, 'job_name': 'Phase 38 Canary Job',
            'job_type': 'code_review', 'status': 'SUCCESS',
        }
        transcript = (
            f'user: please review this PR\n{self.TRANSCRIPT_CANARY}\nassistant: done'
        )
        asyncio.run(c._attach_assessment(job, transcript, c._module_paths()))
        self.assertIn('assessment', job, 'the canary evaluator must produce an accepted assessment')
        marker_path = c._write_job_marker(sid, job, c._module_paths())
        return job, marker_path

    def test_canary_evaluator_prose_persists_clamped_and_ifs_clean(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-p38-canary-')
        try:
            state_dir = os.path.join(tmpdir, 'state')
            markers_dir = os.path.join(state_dir, 'markers')
            sid = 'p38-canary-sid-001'
            job_id = 'p38-canary-job-001'
            job, marker_path = self._attach_and_write(sid, job_id, state_dir, markers_dir)

            basis = job['assessment']['basis']
            role = job['assessment']['assumptions']['inferred_role']

            for bad in ('|', '\n', '\r'):
                self.assertNotIn(bad, basis, f'basis must be IFS-clean: {basis!r}')
                self.assertNotIn(bad, role, f'inferred_role must be IFS-clean: {role!r}')

            self.assertIn(self.EVALUATOR_BASIS_CANARY, basis)
            self.assertIn(self.EVALUATOR_ROLE_CANARY, role)

            self.assertLessEqual(
                len(json.dumps(basis).encode('utf-8')) - 2, 200,
                'basis must be clamped to its 200-byte serialized budget',
            )
            self.assertLessEqual(
                len(json.dumps(role).encode('utf-8')) - 2, 60,
                'inferred_role must be clamped to its 60-byte serialized budget',
            )

            self.assertNotIn(
                self.TRANSCRIPT_CANARY, marker_path.read_text(),
                'the transcript canary must never reach the marker',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_canary_transcript_text_absent_from_every_persisted_artifact(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-p38-canary-full-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')
            jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')
            sid = 'p38-canary-sid-002'
            job_id = 'p38-canary-job-002'

            self._attach_and_write(sid, job_id, state_dir, markers_dir)

            # Prepend the CHAT/task marker line the classifier's OTHER write
            # path produces (_write_job_marker above wrote only the job line) --
            # hermes-report.sh's session loop needs a task_type row to meter.
            task_marker = {
                'muid': f'{job_id}-task', 'ts': 1715516000.5, 'sid': sid,
                'task_type': 'code_review', 'operation_type': 'CHAT',
            }
            marker_file = os.path.join(markers_dir, f'{sid}.jsonl')
            existing = open(marker_file).read()
            with open(marker_file, 'w') as f:
                f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
                f.write(existing)

            build_state_db(state_db, [{
                'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
                'input_tokens': 100, 'output_tokens': 50,
                'cache_read': 0, 'cache_write': 0, 'reasoning': 0,
                'estimated_cost': '0', 'api_calls': 1,
                'started_at': 1715514000.0, 'ended_at': 1715514000.0,
                'billing_provider': 'anthropic',
            }])
            with open(jobs_ledger, 'w') as f:
                f.write(f'JOB:{job_id}:created:1715516001.000\n')

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir, 'meter.log')
            jobs_log = os.path.join(tmpdir, 'jobs.log')
            shim = os.path.join(bin_dir, 'revenium')
            build_shim(shim)

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
            result = subprocess.run(
                ['bash', str(SCRIPTS_DIR / 'hermes-report.sh')],
                env=base_env, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(
                result.returncode, 0,
                f'hermes-report.sh failed: {result.stdout}{result.stderr}',
            )

            canary = self.TRANSCRIPT_CANARY

            marker_text = open(marker_file).read()
            self.assertNotIn(canary, marker_text, 'marker must not carry the transcript canary')

            meter_text = open(meter_log).read() if os.path.exists(meter_log) else ''
            self.assertNotIn(canary, meter_text, 'meter completion argv must not carry the canary')

            jobs_text = open(jobs_log).read() if os.path.exists(jobs_log) else ''
            self.assertNotIn(
                canary, jobs_text,
                'jobs create/outcome argv (incl. --metadata) must not carry the canary',
            )

            for ledger_name in (
                'revenium-hermes.ledger', 'revenium-jobs.ledger', 'revenium-tool-events.ledger',
            ):
                ledger_path = os.path.join(state_dir, ledger_name)
                if os.path.exists(ledger_path):
                    self.assertNotIn(
                        canary, open(ledger_path).read(), f'{ledger_name} must not carry the canary',
                    )

            metering_log = os.path.join(state_dir, 'revenium-metering.log')
            if os.path.exists(metering_log):
                self.assertNotIn(canary, open(metering_log).read(), 'log must not carry the canary')

            self.assertNotIn(canary, result.stdout)
            self.assertNotIn(canary, result.stderr)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _load_llm_evaluator_classifier(self, state_dir, markers_dir):
        """Load the classifier configured for the built-in `llm` evaluator --
        distinct from _attach_and_write's registered `p38-canary` evaluator,
        because the invalid/timed-out lines are produced only on the `llm`
        path (_evaluate_outcome_via_llm / _parse_assessment_object)."""
        os.makedirs(state_dir, exist_ok=True)
        config_file = os.path.join(state_dir, 'config.json')
        with open(config_file, 'w') as f:
            json.dump({'llmOutcomeEvaluation': {
                'enabled': True, 'evaluator': 'llm', 'currency': 'USD',
            }}, f)
        env = {
            'REVENIUM_STATE_DIR': state_dir,
            'REVENIUM_MARKERS_DIR': markers_dir,
            'REVENIUM_CONFIG_FILE': config_file,
        }
        return _load_classifier(env)

    def test_invalid_line_carries_neither_transcript_nor_response_body_canary(self):
        """39-01 Task 3 -- extends the ROI-13 canary sweep over the new
        `invalid` line. The malformed response body carries its OWN fresh
        canary (RESPONSE_BODY_CANARY); the transcript carries the class's
        existing TRANSCRIPT_CANARY. The invalid record must fire (so this
        proves the new path actually ran, not a path that never fired) and
        NEITHER canary may appear in any captured record."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-p38-canary-invalid-')
        try:
            state_dir = os.path.join(tmpdir, 'state')
            markers_dir = os.path.join(state_dir, 'markers')
            c, ev = self._load_llm_evaluator_classifier(state_dir, markers_dir)

            response_canary = self.RESPONSE_BODY_CANARY

            def _broken_call_llm(**kw):
                return {'choices': [{'message': {
                    'content': f'Sorry, I cannot comply -- {response_canary} --',
                }}]}

            c.call_llm = _broken_call_llm

            job = {
                'agentic_job_id': 'p38-canary-invalid-job', 'job_name': 'n',
                'job_type': 'code_review', 'status': 'SUCCESS',
            }
            transcript = (
                f'user: please review this PR\n{self.TRANSCRIPT_CANARY}\nassistant: done'
            )
            with self.assertLogs('revenium_classifier', level='INFO') as cm:
                asyncio.run(c._attach_assessment(job, transcript, c._module_paths()))

            messages = [r.getMessage() for r in cm.records]
            self.assertTrue(
                any('outcome evaluation invalid for job=' in m for m in messages),
                f'the invalid record must fire before the canary sweep means anything, got: {messages}',
            )
            self.assertNotIn('assessment', job)
            for message in messages:
                self.assertNotIn(
                    self.TRANSCRIPT_CANARY, message,
                    'the transcript canary must never reach a log record',
                )
                self.assertNotIn(
                    response_canary, message,
                    'the rejected response body must never reach the invalid log record',
                )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_timed_out_line_carries_no_transcript_canary(self):
        """39-01 Task 3 -- extends the ROI-13 canary sweep over the new
        `timed-out` line."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-p38-canary-timeout-')
        try:
            state_dir = os.path.join(tmpdir, 'state')
            markers_dir = os.path.join(state_dir, 'markers')
            c, ev = self._load_llm_evaluator_classifier(state_dir, markers_dir)

            def _timing_out_call_llm(**kw):
                raise TimeoutError()

            c.call_llm = _timing_out_call_llm

            job = {
                'agentic_job_id': 'p38-canary-timeout-job', 'job_name': 'n',
                'job_type': 'code_review', 'status': 'SUCCESS',
            }
            transcript = (
                f'user: please review this PR\n{self.TRANSCRIPT_CANARY}\nassistant: done'
            )
            with self.assertLogs('revenium_classifier', level='INFO') as cm:
                asyncio.run(c._attach_assessment(job, transcript, c._module_paths()))

            messages = [r.getMessage() for r in cm.records]
            self.assertTrue(
                any('outcome evaluation timed-out for job=' in m for m in messages),
                f'the timed-out record must fire before the canary sweep means anything, got: {messages}',
            )
            self.assertNotIn('assessment', job)
            for message in messages:
                self.assertNotIn(
                    self.TRANSCRIPT_CANARY, message,
                    'the transcript canary must never reach a log record',
                )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
