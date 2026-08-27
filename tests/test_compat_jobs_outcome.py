"""COMPAT-01: argv-shape golden for `revenium jobs outcome` SUCCESS path.

Analog: tests/test_repository.py::test_cron_outcome_is_idempotent (lines 6096-6334) —
  structural skeleton ONLY. The analog's SHIFTING shim at lines 6158-6199 MUST NOT
  be copied here.
Source-of-truth: skills/revenium/scripts/hermes-report.sh:1095-1106.
Golden fixture: tests/fixtures/compat/jobs-outcome.golden.json.
Decisions: D-01..D-04.

Critical no-shift override note: build_shim from _compat_helpers uses the no-shift
design (PATTERNS lines 202-226). Every captured invocations[N] line in jobs_log
starts with the verb token (`jobs outcome compat-job-001 ...`). After argv_to_flags,
__verb is 'jobs', __subcommand is 'outcome', __positional_args is ['compat-job-001'].
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys as _sys
import tempfile
import unittest
from pathlib import Path

from tests._compat_helpers import (
    argv_to_flags,
    assert_argv_matches_golden,
    build_shim,
    build_state_db,
    load_golden,
    run_script,
    SCRIPTS_DIR,
)


class TestCompatJobsOutcome(unittest.TestCase):
    def test_jobs_outcome_success_argv_matches_v12_golden(self):
        """One jobs outcome SUCCESS invocation must byte-match the golden.

        Pre-seeds the jobs ledger with JOB:compat-job-001:created:... so the outcome
        stage does not defer (OUTCOME-04 gate). Writes a job marker with status=SUCCESS.
        The shim captures all jobs invocations to jobs_log; we filter for outcome.
        """
        tmpdir = tempfile.mkdtemp(prefix='gsd-compat-jobs-outcome-')
        try:
            # --- Resolve paths ---
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')
            # Jobs ledger: JOBS_LEDGER_FILE = ${STATE_DIR}/revenium-jobs.ledger
            jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir, 'meter.log')
            jobs_log = os.path.join(tmpdir, 'jobs.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            shim = os.path.join(bin_dir, 'revenium')

            # --- Build synthetic state.db ---
            # started_at is far in the past so the session passes the settle-seconds
            # filter (age >= 120) without needing a markers-ready sentinel.
            build_state_db(state_db, [{
                'id': 'compat-sid-003',
                'model': 'claude-sonnet-4-6',
                'source': 'test',
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

            # --- Pre-seed the jobs ledger (OUTCOME-04 gate) ---
            # Without this, the outcome stage defers because JOB:...:created is absent.
            # The timestamp is a fixed past value to ensure the record passes the stale check.
            os.makedirs(os.path.dirname(jobs_ledger), exist_ok=True)
            with open(jobs_ledger, 'w') as f:
                f.write('JOB:compat-job-001:created:1715516001.000\n')

            # --- Write marker file: task marker + job marker with status=SUCCESS ---
            # Task marker gets owning_job_id = compat-job-001 via D-11 resolution.
            # Job marker status=SUCCESS populates the outcome queue (OUTCOME-05).
            task_marker = {
                'muid': 'compat-task-003',
                'ts': 1715516000.5,
                'sid': 'compat-sid-003',
                'task_type': 'code_review',
                'operation_type': 'CHAT',
            }
            job_marker = {
                'kind': 'job',
                'ts': 1715516002.0,
                'sid': 'compat-sid-003',
                'agentic_job_id': 'compat-job-001',
                'job_name': 'COMPAT Test Job',
                'job_type': 'code_review',
                'status': 'SUCCESS',
            }
            with open(os.path.join(markers_dir, 'compat-sid-003.jsonl'), 'w') as f:
                f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
                f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

            # --- Build no-shift shim ---
            build_shim(shim)

            # --- Env ---
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

            # --- Run hermes-report.sh ---
            rc, _ignored, output = run_script(
                SCRIPTS_DIR / 'hermes-report.sh', base_env, inv_log
            )

            self.assertEqual(
                rc, 0,
                f'hermes-report.sh failed (rc={rc}): {output}'
            )

            # --- Parse jobs_log and find the outcome invocation ---
            jobs_inv = []
            if os.path.exists(jobs_log):
                with open(jobs_log) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            jobs_inv.append(shlex.split(line))

            outcome_inv = [
                a for a in jobs_inv
                if len(a) >= 2 and a[0] == 'jobs' and a[1] == 'outcome'
            ]

            self.assertEqual(
                len(outcome_inv), 1,
                f'expected exactly 1 "jobs outcome" invocation, got {len(outcome_inv)}: '
                f'{outcome_inv!r}\nAll jobs_inv: {jobs_inv!r}\nOutput: {output}'
            )
            captured = outcome_inv[0]

            # --- No-shift contract: first three tokens must be 'jobs outcome compat-job-001' ---
            self.assertEqual(
                captured[0], 'jobs',
                f'COMPAT-01 no-shift violation: expected argv[0]="jobs" got '
                f'{captured[0]!r}\nFull argv: {captured}'
            )
            self.assertEqual(
                captured[1], 'outcome',
                f'COMPAT-01 no-shift violation: expected argv[1]="outcome" got '
                f'{captured[1]!r}\nFull argv: {captured}'
            )
            self.assertEqual(
                captured[2], 'compat-job-001',
                f'COMPAT-01 no-shift violation: expected argv[2]="compat-job-001" got '
                f'{captured[2]!r}\nFull argv: {captured}'
            )

            # --- Golden assert (exact_match + pattern + forbidden) ---
            # __positional_args = ['compat-job-001'] is asserted by the golden.
            assert_argv_matches_golden(
                self, captured, load_golden('jobs-outcome.golden.json')
            )

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Phase 46 Plan 03 (EGV-19, D-01/D-03): the truncated wire shape.
#
# Plan 46-01 gave the `outcome_metadata` heredoc a 4096-byte ceiling with a
# two-tier ordered drop (value family, then provenance); plan 46-02 grew the
# provenance tier by two locality keys. This class proves the truncation
# path is a DELIBERATE, PINNED wire shape -- not merely asserted in prose --
# by driving a real over-ceiling tick end to end and capturing its argv.
#
# The lever: 46-01 fixed failure_reason's clamp to be byte-safe, so it can
# no longer alone drive the envelope over the ceiling. What remains
# unclamped-by-bytes is every free-text field this heredoc slices by
# CHARACTER count (`source[:64]` at the session-read stage, `evaluator[:64]`,
# `model[:64]`, `double_counting_group[:64]`, `evaluator_version[:16]`,
# `bounds_source[:16]`, `inference_provider[:32]` in the forwarder itself):
# json.dumps' default ensure_ascii=True escapes a single astral codepoint
# (an emoji) to a 12-ASCII-byte \\uXXXX\\uXXXX surrogate-pair sequence, so a
# 64-CHARACTER slice of emoji becomes 768 BYTES on the wire -- the same
# under-count shape 46-01's own SUMMARY measured for failure_reason, now
# exercised at the fields that were never in scope for that fix. Field
# lengths below were tuned (not guessed) against the real forwarder so the
# combined record clears the ceiling before any drop and lands comfortably
# under it after the value-family tier alone is popped -- see
# _build_over_ceiling_sidecar_record's per-field byte budget below.
# ---------------------------------------------------------------------------

_EMOJI = '\U0001F600'  # a single astral codepoint: 1 Python character,
                       # 12 bytes once json.dumps(ensure_ascii=True) escapes it.

# Character counts, not byte counts -- these are what the forwarder's own
# [:N] slices accept. Tuned empirically (scratch harness driving the real
# extracted `outcome_metadata` heredoc) to land pre-drop ~4300-4400 bytes
# (comfortably over the 4096 ceiling) and post-tier-1-drop ~3700-3800 bytes
# (comfortably under it, so tier 2 never fires and every provenance key
# survives) -- not the absolute per-field maximum, which leaves too thin a
# margin against future incidental byte drift in this heredoc.
_MODEL_CHARS = 58
_EVALUATOR_CHARS = 58
_DOUBLE_COUNTING_GROUP_CHARS = 58
_INFERENCE_PROVIDER_CHARS = 29
_EVALUATOR_VERSION_CHARS = 15
_BOUNDS_SOURCE_CHARS = 15
_SOURCE_CHARS = 61


def _build_over_ceiling_sidecar_record(job_id):
    """A full Phase 42-45 job-assessment sidecar record whose free-text
    provenance fields are emoji-padded up to their forwarder's own
    character slice, driving the --metadata envelope over
    _METADATA_CEILING_BYTES (D-01/D-03) without inventing any field this
    heredoc does not already forward -- EGV-19's own constraint."""
    return {
        'kind': 'job_assessment',
        'ts': 1715516002.5,
        'agentic_job_id': job_id,
        'assessment_id': f'{job_id}:0',
        'assessment_schema_version': 1,
        'taxonomy_version': 1,
        'prompt_version': 1,
        'policy_version': 1,
        'model': _EMOJI * _MODEL_CHARS,
        'inference_provider': _EMOJI * _INFERENCE_PROVIDER_CHARS,
        'inference_address_class': 'private',
        'value_low': 100.25, 'value_base': 200.5, 'value_high': 300.75,
        'bounds_source': _EMOJI * _BOUNDS_SOURCE_CHARS,
        'currency': 'USD',
        'estimated_value': 200.5,
        'evaluator': _EMOJI * _EVALUATOR_CHARS,
        'evaluator_version': _EMOJI * _EVALUATOR_VERSION_CHARS,
        'confidence': 0.789,
        'evidence_class': 'MODEL_ESTIMATED_DEMO',
        'assumptions': {'estimated_hours_saved': 3.5, 'assumed_loaded_rate': 150.0},
        'economic_mechanism': 'augmentation_capacity_expansion',
        'net_value': 150.25,
        'supplied_costs': {
            'human_review': 10.0, 'rework_or_error': 5.0,
            'integration': 2.0, 'training_or_change': 1.0,
        },
        'cost_coverage': {
            'included': ['human_review', 'rework_or_error', 'integration', 'training_or_change'],
            'known_zero': ['human_review', 'rework_or_error', 'integration', 'training_or_change'],
            'unknown': [],
            'excluded': ['metered_ai_cost'],
        },
        'double_counting_group': _EMOJI * _DOUBLE_COUNTING_GROUP_CHARS,
        'reportability_status': 'reportable',
    }


_VALUE_FAMILY_META_KEYS = (
    'value_low', 'value_base', 'value_high', 'bounds_source',
    'net_value', 'assumptions', 'supplied_costs', 'cost_coverage',
)
_SURVIVING_PROVENANCE_META_KEYS = (
    'evaluator', 'evaluator_version', 'model', 'evidence_class',
    'reportability_status', 'inference_provider', 'inference_address_class',
)


def _extract_outcome_metadata_heredoc(script_text):
    """Duplicated (not imported) from
    tests/test_phase46_metadata_envelope.py's identical helper, per this
    repo's deliberate-duplication-for-isolation convention (CLAUDE.md) --
    importing across unrelated test modules would reopen that module's
    documented os.environ-mutation-at-import trap. Returns None, never a
    partial/guessed body, if the anchor has moved."""
    anchor = 'outcome_metadata=$('
    start = script_text.find(anchor)
    if start == -1:
        return None
    heredoc_start = script_text.find("<<'PY'", start)
    if heredoc_start == -1:
        return None
    body_start = script_text.find('\n', heredoc_start) + 1
    body_end = script_text.find('\nPY\n', body_start)
    if body_end == -1:
        return None
    return script_text[body_start:body_end]


class TestCompatJobsOutcomeMetadataTruncated(unittest.TestCase):
    """Phase 46 Plan 03 (EGV-19, D-01/D-03): the truncated `--metadata`
    wire shape is a deliberate, additive golden -- captured from a real
    driven tick, never hand-authored."""

    def _run_truncated_outcome(self):
        """Drive hermes-report.sh end to end for one SUCCESS job arc whose
        sidecar exceeds the metadata ceiling; return (argv, jobs_ledger_text).
        Structurally mirrors TestCompatJobsOutcome's fixture construction and
        tests/test_phase38_reporter_path.py's sidecar-writing harness."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-compat-jobs-outcome-trunc-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            assessments_dir = os.path.join(state_dir, 'job-assessments')
            os.makedirs(markers_dir, mode=0o700)
            os.makedirs(assessments_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')
            jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir, 'meter.log')
            jobs_log = os.path.join(tmpdir, 'jobs.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            shim = os.path.join(bin_dir, 'revenium')

            sid = 'compat-sid-trunc-001'
            job_id = 'compat-job-trunc-001'
            source = _EMOJI * _SOURCE_CHARS

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

            # Pre-seed the jobs ledger (OUTCOME-04 gate) so the outcome
            # stage does not defer.
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
                'job_name': 'Truncation Golden Job',
                'job_type': 'code_review',
                'status': 'SUCCESS',
            }
            with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
                f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
                f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

            # D-10: the job-assessments SIDECAR is the ONLY value/provenance
            # source the outcome stage reads -- never the marker's own
            # `assessment` key.
            record = _build_over_ceiling_sidecar_record(job_id)
            with open(os.path.join(assessments_dir, f'{job_id}.jsonl'), 'w') as f:
                f.write(json.dumps(record, separators=(',', ':')) + '\n')

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
            self.assertEqual(
                rc, 0, f'hermes-report.sh failed (rc={rc}): {output}'
            )

            jobs_inv = []
            if os.path.exists(jobs_log):
                with open(jobs_log) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            jobs_inv.append(shlex.split(line))

            outcome_inv = [
                a for a in jobs_inv
                if len(a) >= 2 and a[0] == 'jobs' and a[1] == 'outcome'
            ]
            self.assertEqual(
                len(outcome_inv), 1,
                f'expected exactly 1 "jobs outcome" invocation, got '
                f'{len(outcome_inv)}: {outcome_inv!r}\nOutput: {output}'
            )

            ledger_text = ''
            if os.path.exists(jobs_ledger):
                ledger_text = Path(jobs_ledger).read_text()

            return outcome_inv[0], ledger_text, job_id
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_truncated_outcome_argv_matches_golden(self):
        """Tests 1-3, 5, 6 (46-03-PLAN.md): a driven tick whose sidecar
        exceeds the ceiling emits exactly one `jobs outcome` invocation,
        matching the golden, carrying metadata_truncated=true, the base
        `source` key, and every surviving provenance key -- with the
        ledger outcome line still appended."""
        argv, ledger_text, job_id = self._run_truncated_outcome()

        # Test 2: matches the golden argv shape byte-for-byte.
        assert_argv_matches_golden(
            self, argv,
            load_golden('jobs-outcome-metadata-truncated.golden.json'),
        )

        flags = argv_to_flags(argv)
        meta = json.loads(flags['--metadata'])

        # Test 3: the truncation marker is the JSON boolean true.
        self.assertIs(
            meta.get('metadata_truncated'), True,
            f'expected metadata_truncated=true, got {meta!r}',
        )

        # Test 4: every value-family key was popped.
        for key in _VALUE_FAMILY_META_KEYS:
            self.assertNotIn(
                key, meta,
                f'{key} (value family) survived a truncation this test drove '
                f'the record to trigger',
            )

        # Test 5: base + surviving provenance keys are intact.
        self.assertIn('source', meta)
        for key in _SURVIVING_PROVENANCE_META_KEYS:
            self.assertIn(
                key, meta,
                f'{key} (provenance) was dropped when only the value family '
                f'should have yielded at this record\'s size',
            )

        # Test 6: the outcome ledger line was still appended -- a truncated
        # --metadata payload never blocks base metering.
        self.assertRegex(
            ledger_text, rf'JOB:{re.escape(job_id)}:outcome:[0-9.]+:SUCCESS',
            f'expected a JOB:...:outcome: ledger line for {job_id}, got: '
            f'{ledger_text!r}',
        )

    def test_untruncated_payload_for_same_record_would_have_exceeded_ceiling(self):
        """Guards against a vacuous pass (T-46-07): computed, not assumed.
        Runs the SAME real `outcome_metadata` heredoc -- extracted live from
        hermes-report.sh, with only its ceiling-check block skipped so the
        pre-drop blob prints -- against the exact env values the driven tick
        above produces for this record. If a future ceiling raise makes this
        record no longer exceed it, this assertion fails loudly instead of
        the truncation assertions above silently no-op'ing."""
        script_text = (SCRIPTS_DIR / 'hermes-report.sh').read_text()
        body = _extract_outcome_metadata_heredoc(script_text)
        self.assertIsNotNone(
            body,
            'outcome_metadata=$( ... <<\'PY\' ... \\nPY\\n anchor moved in '
            'hermes-report.sh -- update the extraction before trusting this test',
        )
        ceiling_match = re.search(r'_METADATA_CEILING_BYTES\s*=\s*(\d+)', body)
        self.assertIsNotNone(ceiling_match, '_METADATA_CEILING_BYTES not found')
        ceiling = int(ceiling_match.group(1))

        # Skip only the ceiling-check/drop block -- everything upstream of it
        # (the field-selection logic this test must not reimplement) is
        # untouched.
        anchor = "if meta:\n    blob = json.dumps(meta, separators=(',', ':')).encode('utf-8')\n"
        idx = body.find(anchor)
        self.assertNotEqual(idx, -1, 'ceiling-check anchor moved in hermes-report.sh')
        pre_drop_body = (
            body[:idx]
            + "if meta:\n    blob = json.dumps(meta, separators=(',', ':')).encode('utf-8')\n"
            + "    print(blob.decode('utf-8'))\n"
        )

        job_id = 'compat-job-trunc-001'
        record = _build_over_ceiling_sidecar_record(job_id)
        env = {
            'OUTCOME_SOURCE': _EMOJI * _SOURCE_CHARS,
            'OUTCOME_STATUS': 'SUCCESS',
            'OUTCOME_FAILURE_REASON': '',
            'ASSESSMENT_JSON': json.dumps(record),
        }
        result = subprocess.run(
            [_sys.executable, '-'], input=pre_drop_body, env=env,
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        pre_drop_bytes = len(result.stdout.strip().encode('utf-8'))
        self.assertGreater(
            pre_drop_bytes, ceiling,
            f'the untruncated payload for this record is {pre_drop_bytes} '
            f'bytes, not over the {ceiling}-byte ceiling -- this record no '
            f'longer proves truncation; retune the field lengths above',
        )


if __name__ == '__main__':
    unittest.main()
