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


# Phase 42 (D-10): the job-assessments SIDECAR shape hermes-report.sh's
# outcome stage now reads value/provenance from -- the marker's
# ASSESSMENT_FIXTURE above no longer reaches a valued outcome (D-10). Bounds
# match _resolve_value_bounds's DERIVED_BOUND_SPREAD (0.15) applied to the
# same 3.5h * $150/h = $525.0 base ASSESSMENT_FIXTURE uses, so the two
# fixtures describe the same underlying estimate through the two different
# carriers: low = round(525.0 * 0.85, 2) = 446.25, high = round(525.0 * 1.15, 2)
# = 603.75. D-08: --outcome-value ships the LOW bound, not base.
def _sidecar_record(job_id, **overrides):
    record = {
        "kind": "job_assessment",
        "ts": 1715516002.5,
        "agentic_job_id": job_id,
        "assessment_id": f"{job_id}:0",
        "assessment_schema_version": 1,
        # WR-04: classifier.py's _build_job_assessment populates these four
        # UNCONDITIONALLY on every record it builds (TAXONOMY_VERSION,
        # PROMPT_VERSION, POLICY_VERSION, PROVENANCE_MODEL_UNKNOWN), and
        # Plan 42-05 made hermes-report.sh forward all four into --metadata.
        # Omitting them here let meter-completion-assessment.golden.json pin
        # a wire shape production never actually sends. Values mirror the
        # real constants so the fixture stays a faithful stand-in.
        "taxonomy_version": 1,
        "prompt_version": 1,
        "policy_version": 1,
        "model": "unknown",
        "value_low": 446.25,
        "value_base": 525.0,
        "value_high": 603.75,
        "bounds_source": "derived",
        "currency": "USD",
        "estimated_value": 525.0,
        "evaluator": "llm",
        "evaluator_version": "v1",
        "confidence": 0.8,
        "evidence_class": "MODEL_ESTIMATED_DEMO",
        "assumptions": {
            "estimated_hours_saved": 3.5,
            "assumed_loaded_rate": 150.0,
        },
        # Phase 43 (EGV-18, D-05/D-09): classifier.py's _build_job_assessment
        # populates this UNCONDITIONALLY on every record it builds (Phase 42
        # onward). Default here is the reportable literal so every existing
        # test in this file -- written before hermes-report.sh read this
        # field at all -- keeps describing a record that ships its value,
        # unless a test explicitly overrides it to exercise the gate.
        "reportability_status": "reportable",
    }
    record.update(overrides)
    return record


# Phase 43 Plan 05 (D-06): a correction sidecar line, shaped exactly like
# correct-assessment.sh's own `record = {...}` literal (Step 5) --
# tests/test_phase42_assessment_contract.py's SidecarBudgetTests extracts
# that exact field list from live source via _extract_correction_record_fields
# rather than a hand-typed guess; this fixture mirrors that list rather than
# inventing one. Deliberately carries NEITHER evidence_class NOR
# reportability_status: correct-assessment.sh has never written either, and a
# fixture that quietly added one would test a shape production never sends
# (Pitfall 3 in its exact recurring form) -- the whole point of the D-06
# tests below is that a correction lacking both still ships.
def _correction_sidecar_record(job_id, sequence=1, **overrides):
    record = {
        "kind": "correction",
        "ts": 1715516010.0,
        "agentic_job_id": job_id,
        "assessment_id": f"{job_id}:{sequence}",
        "sequence": sequence,
        "assessment_schema_version": 1,
        "prior_value_low": 446.25,
        "prior_value_base": 525.0,
        "prior_value_high": 603.75,
        "prior_currency": "USD",
        "value_low": 100.0,
        "value_base": 110.0,
        "value_high": 120.0,
        "currency": "USD",
        "reason": "operator correction",
    }
    record.update(overrides)
    return record


class TestPhase38ReporterPath(unittest.TestCase):
    def _run_one_outcome(self, sid, job_id, status, failure_reason='', source='test',
                          assessment=None, raw_agentic_job_id=None,
                          outcome_value_capable=True, sidecar=None):
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

        sidecar (Phase 42, D-10), when given, is one record dict or a list
        of them, written to ${state_dir}/job-assessments/<job_id>.jsonl --
        the ONLY value/provenance source the outcome stage reads from
        (never the marker's own `assessment` key, even when both are
        present in the same fixture).
        """
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase38-')
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

            # Phase 42 (D-10): the sidecar is the ONLY value/provenance
            # source the outcome stage reads -- written here, independent
            # of job_marker['assessment'] above, so a fixture can assert
            # the marker plays no part even when both are present.
            if sidecar is not None:
                sidecar_records = sidecar if isinstance(sidecar, list) else [sidecar]
                with open(os.path.join(assessments_dir, f'{job_id}.jsonl'), 'w') as f:
                    for _rec in sidecar_records:
                        f.write(json.dumps(_rec, separators=(',', ':')) + '\n')

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
        """Phase 42 (D-08/D-10): value and provenance are resolved from the
        job-assessments SIDECAR only -- this fixture writes a REAL sidecar
        record (as classifier.py's _write_job_assessment would) alongside
        the marker's own 9-key `assessment` summary, proving the marker
        plays no part even when both carry a plausible, DIFFERENT number
        (ASSESSMENT_FIXTURE's 525.0 vs the sidecar's 446.25 low bound).
        --outcome-value ships the LOW bound (D-08), and the full bound
        family plus its source rides in --metadata alongside the existing
        provenance fields."""
        argv = self._run_one_outcome(
            'o38-sid-001', 'o38-job-001', 'SUCCESS', assessment=ASSESSMENT_FIXTURE,
            sidecar=_sidecar_record('o38-job-001'),
        )
        self.assertEqual(argv[argv.index('--outcome-type') + 1], 'CONVERTED')
        self.assertEqual(argv[argv.index('--outcome-value') + 1], '446.25')
        self.assertEqual(argv[argv.index('--outcome-currency') + 1], 'USD')

        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta.get('source'), 'test')
        self.assertEqual(meta.get('evidence_class'), 'MODEL_ESTIMATED_DEMO')
        self.assertEqual(meta.get('evaluator'), 'llm')
        self.assertEqual(meta.get('evaluator_version'), 'v1')
        self.assertEqual(meta.get('confidence'), 0.8)
        self.assertEqual(
            meta.get('assumptions'),
            {'estimated_hours_saved': 3.5, 'assumed_loaded_rate': 150.0},
        )
        self.assertEqual(meta.get('value_low'), 446.25)
        self.assertEqual(meta.get('value_base'), 525.0)
        self.assertEqual(meta.get('value_high'), 603.75)
        self.assertEqual(meta.get('bounds_source'), 'derived')
        self.assertEqual(meta.get('assessment_schema_version'), 1)
        # D-08 executable proof: the shipped value is the LOW bound, never
        # the marker's estimated_value (525.0) or the sidecar's own base.
        self.assertNotEqual(argv[argv.index('--outcome-value') + 1], '525.0')

    def test_candidate_reportability_ships_no_value_but_keeps_provenance(self):
        """Phase 43 (EGV-18, D-05 clarification, T-43-01) -- behavior 7 of
        43-01-PLAN.md's Task 1. A sidecar record whose reportability_status
        is "candidate" (an estimate computed without the experimental
        opt-in) must not let its number leave the machine: the constructed
        `jobs outcome` argv carries neither --outcome-value nor
        --outcome-currency, and --metadata carries none of the value-bearing
        keys either -- not just the two flags. The value stays local; the
        fact that an estimate happened does not (D-05): evidence_class,
        evaluator, evaluator_version, model, and the four version fields
        still ship."""
        argv = self._run_one_outcome(
            'c43-sid-001', 'c43-job-001', 'SUCCESS', assessment=ASSESSMENT_FIXTURE,
            sidecar=_sidecar_record('c43-job-001', reportability_status='candidate'),
        )
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)

        meta = json.loads(self._metadata_value(argv))
        # T-43-01: sanitized from the transported blob, not merely
        # unforwarded -- these keys must be entirely absent from --metadata,
        # including the assumptions object whose
        # estimated_hours_saved * assumed_loaded_rate product IS the
        # estimate this gate exists to withhold.
        for stripped_key in (
            'value_low', 'value_base', 'value_high', 'bounds_source',
            'currency', 'estimated_value', 'assumptions',
        ):
            self.assertNotIn(stripped_key, meta, f'{stripped_key!r} must not cross the wire on a candidate record')
        # D-05: provenance still ships even though the value did not.
        self.assertEqual(meta.get('evidence_class'), 'MODEL_ESTIMATED_DEMO')
        self.assertEqual(meta.get('evaluator'), 'llm')
        self.assertEqual(meta.get('evaluator_version'), 'v1')
        self.assertEqual(meta.get('model'), 'unknown')
        self.assertEqual(meta.get('assessment_schema_version'), 1)
        self.assertEqual(meta.get('taxonomy_version'), 1)
        self.assertEqual(meta.get('prompt_version'), 1)
        self.assertEqual(meta.get('policy_version'), 1)
        # T-43-04: the reportability decision itself rides in --metadata too
        # -- a withheld row must be distinguishable from a row dropped for
        # bounds or schema reasons.
        self.assertEqual(meta.get('reportability_status'), 'candidate')

    def test_reportable_reportability_ships_exactly_as_before(self):
        """Phase 43 (EGV-18): a record whose reportability_status is
        "reportable" ships exactly as the pre-Phase-43 behavior did --
        same flags, same --metadata provenance, plus reportability_status
        itself (Task 2, Test 1)."""
        argv = self._run_one_outcome(
            'r43-sid-001', 'r43-job-001', 'SUCCESS', assessment=ASSESSMENT_FIXTURE,
            sidecar=_sidecar_record('r43-job-001'),
        )
        self.assertEqual(argv[argv.index('--outcome-value') + 1], '446.25')
        self.assertEqual(argv[argv.index('--outcome-currency') + 1], 'USD')
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta.get('value_low'), 446.25)
        self.assertEqual(meta.get('value_base'), 525.0)
        self.assertEqual(meta.get('value_high'), 603.75)
        self.assertEqual(meta.get('bounds_source'), 'derived')
        self.assertEqual(
            meta.get('assumptions'),
            {'estimated_hours_saved': 3.5, 'assumed_loaded_rate': 150.0},
        )
        self.assertEqual(meta.get('evidence_class'), 'MODEL_ESTIMATED_DEMO')
        self.assertEqual(meta.get('reportability_status'), 'reportable')

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

    # -- Plan 43-02 Task 2: the reporter's own evidence_class allow-list --

    def test_evidence_class_outside_the_nine_is_not_forwarded(self):
        """Plan 43-02, Task 2, behavior 1 (CF-2 reject, D-11 exercised): a
        sidecar record identical to the nominal fixture except that
        evidence_class holds a value outside the nine labels must not have
        that value forwarded into --metadata, and takes both value flags
        down with it. Single-adversarial-field style, matching
        test_negative_low_bound_ships_no_value /
        test_non_numeric_bound_ships_no_value in
        tests/test_phase42_assessment_contract.py -- everything except
        evidence_class stays exactly what _sidecar_record's nominal
        default sends, so a failure here is attributable to this one
        field. Asserted on the PARSED --metadata object, never a raw
        string search -- a substring match on the rejected label would
        pass for the wrong reason if it happened to appear anywhere else
        in the payload.

        Guarantee class: BEHAVIOURAL. A runtime membership check over
        untrusted sidecar content, proven on the paths exercised here --
        not a structural or impossibility claim."""
        argv = self._run_one_outcome(
            'ec43-sid-001', 'ec43-job-001', 'SUCCESS', assessment=ASSESSMENT_FIXTURE,
            sidecar=_sidecar_record('ec43-job-001', evidence_class='ANECDOTAL_VIBES'),
        )
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)
        meta = json.loads(self._metadata_value(argv))
        self.assertNotIn('evidence_class', meta)

    def test_evidence_class_non_string_is_not_forwarded(self):
        """Behavior 2: a numeric evidence_class is rejected the same way a
        misspelled string one is -- the allow-list checks isinstance(str)
        before membership, not membership alone (a bare `in` test against
        a frozenset of strings would already reject a non-string via
        __eq__/__hash__ mismatch, but the explicit isinstance keeps the
        rejection reason legible rather than incidental)."""
        argv = self._run_one_outcome(
            'ec43-sid-002', 'ec43-job-002', 'SUCCESS', assessment=ASSESSMENT_FIXTURE,
            sidecar=_sidecar_record('ec43-job-002', evidence_class=7),
        )
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)
        meta = json.loads(self._metadata_value(argv))
        self.assertNotIn('evidence_class', meta)

    def test_rejected_evidence_class_also_withholds_the_value_family(self):
        """CR-01 (43-REVIEW.md): a record REJECTED by the allow-list must
        withhold the estimate itself, not merely the two CLI scalars.

        The two refusal gates in hermes-report.sh are independent: the
        reportability gate strips the value family from the transported
        record, while the allow-list originally cleared only value_out /
        currency_out. So a record that was `reportable` but carried an
        out-of-set evidence_class -- a hand-edited sidecar, precisely the
        threat CF-2 exists to catch -- had its flags refused while
        value_low/value_base/value_high, bounds_source and the assumptions
        object still rode out in --metadata. assumptions is the sharpest
        part: estimated_hours_saved * assumed_loaded_rate IS the estimate.

        The two tests above assert only flag and evidence_class absence,
        which is why this shipped untested -- an assertion that checks the
        fields anyone thought of, again.

        BEHAVIOURAL, on real constructed argv. Not an impossibility claim."""
        argv = self._run_one_outcome(
            'ec43-sid-003', 'ec43-job-003', 'SUCCESS', assessment=ASSESSMENT_FIXTURE,
            sidecar=_sidecar_record(
                'ec43-job-003',
                evidence_class='ANECDOTAL_VIBES',
                reportability_status='reportable',
            ),
        )
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)
        meta = json.loads(self._metadata_value(argv))
        self.assertNotIn('evidence_class', meta)
        for leaked in ('value_low', 'value_base', 'value_high',
                       'bounds_source', 'currency', 'estimated_value',
                       'assumptions'):
            self.assertNotIn(
                leaked, meta,
                f'CR-01: {leaked!r} rode into --metadata on a record the '
                f'allow-list rejected -- the value was refused at the flags '
                f'and shipped in the blob: {meta}',
            )

    def test_absent_evidence_class_is_not_a_rejection(self):
        """Behavior 3 -- the trap this check exists to avoid inverting
        (D-11's note, and the reporter-side echo of 43-CONTEXT's absent-
        vs-invalid distinction): a kind:"correction" record carries NO
        evidence_class key at all, because correct-assessment.sh has never
        written one. This test pins that absence is permissible on the
        sidecar-record path directly (a check that rejected absence would
        silently downgrade every human-authorised correction, and
        test_last_match_wins_ships_newest_correction_low_bound in
        tests/test_phase42_assessment_contract.py -- run alongside this
        module per the plan's own verification list -- would go red).
        Whether the value ships is decided by reportability_status alone,
        unaffected by this check."""
        record = _sidecar_record('ec43-job-003')
        del record['evidence_class']
        argv = self._run_one_outcome(
            'ec43-sid-003', 'ec43-job-003', 'SUCCESS', assessment=ASSESSMENT_FIXTURE,
            sidecar=record,
        )
        self.assertEqual(argv[argv.index('--outcome-value') + 1], '446.25')
        self.assertEqual(argv[argv.index('--outcome-currency') + 1], 'USD')
        meta = json.loads(self._metadata_value(argv))
        self.assertNotIn('evidence_class', meta)

    def test_nominal_evidence_class_still_ships_unaffected_by_the_new_check(self):
        """Behavior 4, the accept-branch regression pin: the nominal
        fixture's MODEL_ESTIMATED_DEMO still forwards both value flags and
        the label itself, unchanged by the new allow-list. Tests 3 and 4
        are not padding -- they are what stops Test 1 from being satisfied
        by an over-broad check that rejects everything, including absence
        and the nominal case."""
        argv = self._run_one_outcome(
            'ec43-sid-004', 'ec43-job-004', 'SUCCESS', assessment=ASSESSMENT_FIXTURE,
            sidecar=_sidecar_record('ec43-job-004'),
        )
        self.assertEqual(argv[argv.index('--outcome-value') + 1], '446.25')
        self.assertEqual(argv[argv.index('--outcome-currency') + 1], 'USD')
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta.get('evidence_class'), 'MODEL_ESTIMATED_DEMO')

    # -- Task 3: the new golden, and pre-v1.5 backward compatibility ------

    def test_golden_valued_outcome_matches_new_fixture(self):
        """Phase 42 (D-08/D-10): meter-completion-assessment.golden.json
        pins the wire shape a SIDECAR-sourced valued outcome produces --
        this fixture writes a real sidecar record (D-10: the marker is
        never the value source) and asserts the resulting argv against the
        golden, closing the coverage gap plan 42-02 opened when the
        marker-only scenario could no longer reach this golden's shape.
        The golden's own pin moved deliberately with this change: the
        value from the marker-derived 525.0 point estimate to the
        sidecar's 446.25 low bound (D-08), and the --metadata pattern to
        the full bound family + bounds_source + assessment_schema_version
        (D-10, since the record now comes from the sidecar's richer
        shape, not the marker's frozen 9 keys)."""
        argv = self._run_one_outcome(
            'g38-sid-002', 'assessment-golden-job', 'SUCCESS',
            sidecar=_sidecar_record('assessment-golden-job'),
        )
        # CF-1: the genuine call site (kept on one line so it is grep-able
        # as a pair with the golden's own filename, closing the gap plan
        # 42-02's SUMMARY deferred -- an existence pin in test_repository.py
        # alone does not prove the wire shape is actually asserted).
        assert_argv_matches_golden(self, argv, load_golden('meter-completion-assessment.golden.json'))

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
        its assessment resolved.

        Phase 42 (D-10): this lookup now happens against the job-assessments
        SIDECAR, not the marker -- this fixture writes only a marker
        `assessment`, so under D-10 it ships no value regardless of the
        job id's shape. The sanitize-before-compare concern this test was
        built to catch now applies to the SIDECAR's own join (a fourth
        independent copy of the same transform, in hermes-report.sh's
        sidecar reader and in classifier.py's `_sidecar_filename_component`)
        and is covered by
        tests/test_phase42_assessment_contract.py::PathMirrorParityTests
        and the writer/reader transform's shared unit coverage, not here."""
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
        self.assertNotIn('--outcome-value', argv)
        self.assertNotIn('--outcome-currency', argv)

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
        # Phase 42 (D-10): this fixture is marker-only (no sidecar file), so
        # under D-10 no provenance ships either -- the marker's assessment
        # (malformed or not) no longer feeds --metadata at all.
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta, {'source': 'test'})

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
        # Phase 42 (D-10): this fixture is marker-only (no sidecar file), so
        # no provenance rides in --metadata regardless of CLI capability --
        # provenance now comes exclusively from the sidecar.
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta, {'source': 'test'})

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
        # Phase 42 (D-10): marker-only fixture -- no provenance either.
        meta = json.loads(self._metadata_value(argv))
        self.assertEqual(meta, {'source': 'test'})

    # -- Plan 05 (D-06): a correction stays reportable and says so ---------

    def test_correction_ships_its_own_low_bound_with_no_reporting_opt_in(self):
        """D-06, behavior 1. The original assessment is written CANDIDATE --
        the shape classifier.py produces with no experimentalReportEstimates
        opt-in configured -- and a correction line follows it. Scan-to-end
        (41-CARRIER-DECISION.md Part 2) resolves `found` to the correction
        record alone, and the correction carve-out at the reader (D-06) never
        consults reportability_status at all, so both value flags ship
        carrying the correction's OWN low bound (100.0) -- never the
        original's candidate-withheld 446.25."""
        job_id = 'd06-job-001'
        argv = self._run_one_outcome(
            'd06-sid-001', job_id, 'SUCCESS', assessment=ASSESSMENT_FIXTURE,
            sidecar=[
                _sidecar_record(job_id, reportability_status='candidate'),
                _correction_sidecar_record(job_id),
            ],
        )
        self.assertEqual(argv[argv.index('--outcome-value') + 1], '100.0')
        self.assertEqual(argv[argv.index('--outcome-currency') + 1], 'USD')

    def test_correction_metadata_carries_corrected_marker_and_sequence(self):
        """D-06, behavior 2. The same invocation as the prior test's
        --metadata carries the corrected marker plus the correction's own
        sequence -- the only signal on the customer's tenant distinguishing
        this value from an original, since `jobs roi` surfaces neither
        (Finding 4 / C-06)."""
        job_id = 'd06-job-002'
        argv = self._run_one_outcome(
            'd06-sid-002', job_id, 'SUCCESS', assessment=ASSESSMENT_FIXTURE,
            sidecar=[
                _sidecar_record(job_id, reportability_status='candidate'),
                _correction_sidecar_record(job_id, sequence=1),
            ],
        )
        meta = json.loads(self._metadata_value(argv))
        self.assertIs(meta.get('corrected'), True)
        self.assertEqual(meta.get('correction_sequence'), 1)

    def test_ordinary_assessment_metadata_carries_neither_correction_key(self):
        """D-06, behavior 3. An ORIGINAL assessment (no correction line at
        all) must not carry a marker saying it is one -- the corrected
        marker and sequence are emitted ONLY when the resolved record's kind
        is a correction."""
        job_id = 'd06-job-003'
        argv = self._run_one_outcome(
            'd06-sid-003', job_id, 'SUCCESS', assessment=ASSESSMENT_FIXTURE,
            sidecar=_sidecar_record(job_id),
        )
        meta = json.loads(self._metadata_value(argv))
        self.assertNotIn('corrected', meta)
        self.assertNotIn('correction_sequence', meta)

    def test_correction_ships_even_when_the_reportability_gate_is_closed(self):
        """D-06, behavior 4 -- the test that would have caught the
        regression this plan exists to prevent. Plan 43-01 introduced a
        reportability gate whose DEFAULT is to withhold an ordinary
        estimate's value; a correction is precisely the record that must
        not be caught by it. The gate is framed as explicitly CLOSED here
        (reportability_status='candidate' on the original, not merely
        absent/unset), so a future change to the resolver's default cannot
        make this assertion vacuous. The gate and the correction path do
        not interact: the correction ships regardless of what the gate
        would have done to an ordinary estimate in the same sidecar."""
        job_id = 'd06-job-004'
        argv = self._run_one_outcome(
            'd06-sid-004', job_id, 'SUCCESS', assessment=ASSESSMENT_FIXTURE,
            sidecar=[
                _sidecar_record(job_id, reportability_status='candidate'),
                _correction_sidecar_record(job_id, sequence=2, value_low=50.0),
            ],
        )
        self.assertEqual(argv[argv.index('--outcome-value') + 1], '50.0')
        self.assertEqual(argv[argv.index('--outcome-currency') + 1], 'USD')
        meta = json.loads(self._metadata_value(argv))
        self.assertIs(meta.get('corrected'), True)
        self.assertEqual(meta.get('correction_sequence'), 2)


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


# Phase 42 Plan 05 (EGV-07) -- a full EGV-04 sidecar record, built through
# the REAL classifier construction path (_validate_assessment then
# _build_job_assessment), never a hand-written dict. C-04 is explicit that
# Phase 38's deferral proof does not extend to this schema unless the test
# exercises real construction, not a plan's idea of the shape. hours=3.5,
# rate=150.0 -> base=525.0, matching ASSESSMENT_FIXTURE/_sidecar_record's
# shared arithmetic so the low/base/high bounds this fixture produces
# (446.25/525.0/603.75) line up with the rest of this file's fixtures.
#
# Phase 43 (EGV-18): this helper's callers assert a VALUED outcome (deferred
# create/retry, provenance forwarding) -- orthogonal to the reportability
# gate itself. _build_job_assessment's cfg carries the reportable opt-in so
# those pre-existing assertions keep describing a shipped value; a test that
# wants to exercise the candidate/withheld path builds its own record via
# _sidecar_record or calls _build_job_assessment directly with a different
# cfg, not through this helper.
_REPORTABLE_CFG = {'experimentalReportEstimates': True}


def _build_real_sidecar_record(job_id):
    c, _ev = _load_classifier({})
    raw = {
        'inferred_role': 'senior software engineer',
        'estimated_hours_saved': 3.5,
        'assumed_loaded_rate': 150.0,
        'currency': 'USD',
        'basis': '3.5 hours of senior engineer review time',
        'confidence': 0.8,
        'candidate_downstream_outcome': 'PR merged to main',
        'counterfactual_assumption': 'a human reviewer would have taken the same time',
    }
    valid = {'agentic_job_id': job_id, 'job_type': 'code_review', 'status': 'SUCCESS'}
    assessment = c._validate_assessment(raw, {}, 'llm', 'v1')
    record = c._build_job_assessment(valid, assessment, raw, _REPORTABLE_CFG, 'llm', 'v1')
    return c, record


class TestPhase38MultiTick(unittest.TestCase):
    """Tasks 1 & 2 — the two guarantees only visible across ticks.

    Both tasks share one harness: a persistent tmpdir (jobs ledger NOT reset
    between runs, unlike the single-tick helper above) driven through a
    configurable shim so a given run's jobs-create / jobs-outcome exit code
    can be scripted per tick.
    """

    def _setup(self, sid, job_id, status='SUCCESS', assessment=None, seed_created=False,
               sidecar=None):
        """sidecar (Phase 42 Plan 05, EGV-07), when given, is one record dict
        or a list of them, written to ${state_dir}/job-assessments/<component>.jsonl
        where <component> is produced by the classifier's OWN
        _sidecar_filename_component transform (imported fresh via
        _load_classifier, never a hand-written string) -- so the fixture's
        filename can never silently drift from the real writer's. Additive
        to the existing `assessment` (marker-embedded) parameter; both may
        be supplied together, exactly like TestPhase38ReporterPath's
        _run_one_outcome already allows."""
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

        if sidecar is not None:
            assessments_dir = os.path.join(state_dir, 'job-assessments')
            os.makedirs(assessments_dir, mode=0o700, exist_ok=True)
            _classifier_mod, _ev_mod = _load_classifier({})
            component = _classifier_mod._sidecar_filename_component(job_id)
            sidecar_records = sidecar if isinstance(sidecar, list) else [sidecar]
            with open(os.path.join(assessments_dir, f'{component}.jsonl'), 'w') as f:
                for _rec in sidecar_records:
                    f.write(json.dumps(_rec, separators=(',', ':')) + '\n')

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
        """T-38-06 / the research doc's own deciding test: an outcome must
        still be reachable on the tick AFTER the one that inferred it, even
        when the create call that tick deferred on. OUTCOME-04 governs the
        defer; the precheck scan (not the token-gated main loop) is what
        re-reaches the job on tick 2.

        Phase 42 (D-10): this harness seeds only a marker-embedded
        `assessment`, no sidecar file, so under D-10 tick 2's outcome ships
        with no value flags and no provenance -- the deferred-create
        survival property under test here (the outcome itself still ships,
        exactly once, on tick 2) is unchanged; what changed is that a
        marker-only assessment no longer produces a VALUED outcome. The
        real sidecar-sourced deferral-survival proof (EGV-07: provenance
        surviving a real deferred create through the sidecar re-read) is a
        later plan's scope, extending this same harness with a real sidecar
        fixture."""
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
            # Phase 42 (D-10): marker-only fixture -- tick 2 ships status-only,
            # no value flags, no provenance (see docstring above).
            self.assertNotIn('--outcome-value', argv2)
            self.assertNotIn('--outcome-currency', argv2)
            meta2 = json.loads(_metadata_of(argv2))
            self.assertEqual(meta2, {'source': 'test'})

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

    # -- Plan 05 (EGV-07): provenance survives a REAL deferred create -----

    def test_provenance_survives_deferred_create_and_retry(self):
        """EGV-07, and the roadmap's own wording verbatim: "Model, prompt,
        taxonomy, policy and schema versions survive a deferred create and
        a retry -- the phase-38 deferral path is the test, not a mock."

        C-04 is explicit Phase 38's deferral proof does not extend to this
        schema: the matching logic is schema-agnostic but the field
        extraction was not, and Phase 42 replaced the extraction wholesale.
        This test rebuilds the proof on the real harness this class already
        uses for the marker-only deferral guarantee
        (test_deferred_create_survives_to_next_tick_with_assessment_intact):
        a real `jobs create` failure in tick 1 (JOBS_CREATE_EXIT_CODE=1,
        via a real `bash hermes-report.sh` subprocess through _run_tick),
        a real second subprocess run in tick 2, and a real sidecar file
        persisted on disk between them -- never a mock of the extraction
        logic.

        Every provenance field EGV-07 names by word (model, prompt,
        taxonomy, policy, schema) plus the evaluator/evaluator-version pair
        is captured from the ON-DISK sidecar file before tick 1 (not the
        in-memory record, so serialization is covered too) and asserted
        field-for-field, per-field message, against tick 2's --metadata --
        a dict-equality assertion would tell the reader nothing about which
        link in the provenance chain broke.
        """
        sid = 'p42-05-prov-sid-001'
        job_id = 'p42-05-prov-job-001'
        c, record = _build_real_sidecar_record(job_id)
        tmpdir, env, meter_log, jobs_log, jobs_ledger, state_dir = self._setup(
            sid, job_id, status='SUCCESS', assessment=ASSESSMENT_FIXTURE,
            seed_created=False, sidecar=record,
        )
        try:
            component = c._sidecar_filename_component(job_id)
            sidecar_path = os.path.join(state_dir, 'job-assessments', f'{component}.jsonl')

            # Read the provenance fields back OUT OF THE FILE ON DISK,
            # before tick 1 even runs -- proving serialization survived,
            # not just the in-memory dict the fixture built.
            with open(sidecar_path) as f:
                on_disk_before = json.loads(f.read().strip())
            provenance_fields = (
                'assessment_schema_version', 'taxonomy_version', 'prompt_version',
                'policy_version', 'model', 'evaluator', 'evaluator_version',
            )
            expected = {field: on_disk_before[field] for field in provenance_fields}

            # Tick 1: jobs create fails -> OUTCOME-04's defer branch. No
            # outcome ships; the sidecar file is untouched by this tick
            # (proven separately, byte-for-byte, in the next test).
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

            # Tick 2: jobs create succeeds -> the deferred outcome ships,
            # via a REAL second `bash hermes-report.sh` subprocess re-
            # reading the SAME sidecar file tick 1 left on disk.
            env2 = {**env, 'JOBS_CREATE_EXIT_CODE': '0'}
            rc2, meter_inv2, jobs_inv2, out2 = self._run_tick(env2, meter_log, jobs_log, state_dir)
            self.assertEqual(rc2, 0, f'tick 2 exit {rc2}: {out2}')

            outcome_inv2 = _outcome_invocations(jobs_inv2, 'outcome')
            self.assertEqual(
                len(outcome_inv2), 1, f'tick 2 must ship exactly one outcome: {jobs_inv2}',
            )
            argv2 = outcome_inv2[0]

            # D-08's meaning survives the deferral too: --outcome-value
            # carries the LOW bound the sidecar held before tick 1.
            self.assertIn(
                '--outcome-value', argv2, f'expected --outcome-value in tick 2 argv: {argv2}',
            )
            self.assertEqual(
                argv2[argv2.index('--outcome-value') + 1], str(on_disk_before['value_low']),
                'the LOW bound must survive the deferral onto --outcome-value unchanged',
            )

            meta2 = json.loads(_metadata_of(argv2))
            for field in provenance_fields:
                self.assertIn(
                    field, meta2,
                    f'provenance field {field!r} is missing from tick 2 --metadata: {meta2}',
                )
                self.assertEqual(
                    meta2[field], expected[field],
                    f'provenance field {field!r} changed across the deferral: '
                    f'sidecar held {expected[field]!r} before tick 1, '
                    f'tick 2 shipped {meta2[field]!r}',
                )

            ledger_text = open(jobs_ledger).read()
            self.assertTrue(
                any(l.startswith(f'JOB:{job_id}:outcome:') for l in ledger_text.splitlines()),
                f'expected an outcome ledger line after tick 2: {ledger_text}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_sidecar_record_unmodified_by_a_deferred_tick(self):
        """The reporter is a PURE READER of the sidecar; if a future change
        ever makes it a writer, this is the test that says so. Hashes the
        sidecar file's bytes before tick 1 and after tick 2 and asserts
        identity. Also re-asserts the marker file's own bytes are
        unchanged across both ticks -- the existing EGV-22 guarantee
        (test_deferred_create_survives_to_next_tick_with_assessment_intact)
        restated at the file level rather than the field level, now
        alongside the new sidecar carrier."""
        sid = 'p42-05-unmod-sid-001'
        job_id = 'p42-05-unmod-job-001'
        c, record = _build_real_sidecar_record(job_id)
        tmpdir, env, meter_log, jobs_log, jobs_ledger, state_dir = self._setup(
            sid, job_id, status='SUCCESS', assessment=ASSESSMENT_FIXTURE,
            seed_created=False, sidecar=record,
        )
        try:
            component = c._sidecar_filename_component(job_id)
            sidecar_path = os.path.join(state_dir, 'job-assessments', f'{component}.jsonl')
            marker_path = os.path.join(state_dir, 'markers', f'{sid}.jsonl')

            with open(sidecar_path, 'rb') as f:
                sidecar_bytes_before = f.read()
            with open(marker_path, 'rb') as f:
                marker_bytes_before = f.read()

            env1 = {**env, 'JOBS_CREATE_EXIT_CODE': '1'}
            rc1, _m1, jobs_inv1, out1 = self._run_tick(env1, meter_log, jobs_log, state_dir)
            self.assertEqual(rc1, 0, f'tick 1 exit {rc1}: {out1}')
            self.assertEqual(
                len(_outcome_invocations(jobs_inv1, 'outcome')), 0,
                f'tick 1 must send no outcome: {jobs_inv1}',
            )

            env2 = {**env, 'JOBS_CREATE_EXIT_CODE': '0'}
            rc2, _m2, jobs_inv2, out2 = self._run_tick(env2, meter_log, jobs_log, state_dir)
            self.assertEqual(rc2, 0, f'tick 2 exit {rc2}: {out2}')
            self.assertEqual(
                len(_outcome_invocations(jobs_inv2, 'outcome')), 1,
                f'tick 2 must ship exactly one outcome: {jobs_inv2}',
            )

            with open(sidecar_path, 'rb') as f:
                sidecar_bytes_after = f.read()
            with open(marker_path, 'rb') as f:
                marker_bytes_after = f.read()

            self.assertEqual(
                sidecar_bytes_before, sidecar_bytes_after,
                'the sidecar file must be byte-identical across a deferred tick and its '
                'retry -- the reporter is a pure reader of it',
            )
            self.assertEqual(
                marker_bytes_before, marker_bytes_after,
                'EGV-22 at the file level: the marker file must also be byte-identical '
                'across a deferred tick and its retry',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_rerun_after_a_valued_outcome_reports_exactly_once(self):
        """Idempotency with a sidecar present. Three ticks against a state
        that never changes must produce exactly one `jobs outcome`
        invocation total and exactly one `JOB:<id>:outcome:` ledger line
        total -- the idempotency edge this repo has been bitten by twice
        (the phase-32 cross-profile double-ship; the legacy-reporter race
        still carried as an @expectedFailure).
        test_idempotent_rerun_produces_exactly_one_outcome_and_one_ledger_line
        already covers this for the marker-sourced path; this test covers
        it with a real sidecar record present, over three ticks instead of
        two.

        This test asserts EXACTLY-ONCE. It never asserts, and must never be
        read as demonstrating, that a job id CAN be reported twice through
        the ordinary `job_outcome_queue` path -- that is the regression
        this design exists to avoid, not a feature.
        """
        sid = 'p42-05-rerun-sid-001'
        job_id = 'p42-05-rerun-job-001'
        c, record = _build_real_sidecar_record(job_id)
        tmpdir, env, meter_log, jobs_log, jobs_ledger, state_dir = self._setup(
            sid, job_id, status='SUCCESS', assessment=ASSESSMENT_FIXTURE,
            seed_created=True, sidecar=record,
        )
        try:
            total_outcome_invocations = 0
            for tick_num in (1, 2, 3):
                rc, _m, jobs_inv, out = self._run_tick(env, meter_log, jobs_log, state_dir)
                self.assertEqual(rc, 0, f'tick {tick_num} exit {rc}: {out}')
                total_outcome_invocations += len(_outcome_invocations(jobs_inv, 'outcome'))

            self.assertEqual(
                total_outcome_invocations, 1,
                'exactly one jobs outcome invocation across three ticks against unchanged '
                'state, with a sidecar present',
            )

            ledger_text = open(jobs_ledger).read()
            outcome_lines = [
                l for l in ledger_text.splitlines() if l.startswith(f'JOB:{job_id}:outcome:')
            ]
            self.assertEqual(
                len(outcome_lines), 1,
                f'exactly one outcome ledger line across three ticks, got: {outcome_lines}',
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
    # Phase 42 Plan 05 -- the sidecar's other two narrative fields
    # (candidate_downstream_outcome, counterfactual_assumption), each
    # clamped to its own 500-byte NARRATIVE_CLAMP_BYTES budget, distinct
    # from the marker's basis (200 bytes). The marker's `basis` and the
    # sidecar's `basis` share ONE canary (EVALUATOR_BASIS_CANARY) because
    # they are the SAME field surviving through two different carriers with
    # two different clamps -- these two fields exist only in the sidecar.
    EVALUATOR_OUTCOME_CANARY = 'SSCANARY-c31d5-OUTCOME-PROSE'
    EVALUATOR_COUNTERFACTUAL_CANARY = 'TTCANARY-d42e6-COUNTERFACTUAL-PROSE'
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
        # Phase 42 Plan 05 -- the sidecar's other two narrative fields, each
        # over their own 500-byte NARRATIVE_CLAMP_BYTES budget and carrying
        # pipe/newline/CR so the same IFS-cleanliness assertion the marker's
        # basis/inferred_role already get can be repeated against them.
        outcome_raw = (
            self.EVALUATOR_OUTCOME_CANARY + '|outcome|pipe\nbreak\r' + ('W' * 600)
        )
        counterfactual_raw = (
            self.EVALUATOR_COUNTERFACTUAL_CANARY + '|cf|pipe\nbreak\r' + ('V' * 600)
        )
        return {
            'inferred_role': role_raw,
            'estimated_hours_saved': 2.0,
            'assumed_loaded_rate': 100.0,
            'currency': 'USD',
            'basis': basis_raw,
            'confidence': 0.6,
            'candidate_downstream_outcome': outcome_raw,
            'counterfactual_assumption': counterfactual_raw,
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
        # Phase 42 Plan 05: also produce a sidecar record through the REAL
        # write path (_write_job_assessment), mirroring the D-12 ordering
        # (sidecar first, then the marker) the real caller in
        # run_classification_async uses -- the sidecar is a NEW persisted
        # artifact the existing canary sweep enumerated by name and did not
        # know about; a fixture that skips writing it would leave that hole
        # unexercised rather than closing it.
        assessment_record = job.pop('_assessment_record', None)
        sidecar_path = None
        if isinstance(assessment_record, dict) and assessment_record:
            sidecar_path = c._write_job_assessment(assessment_record, c._module_paths())
            self.assertIsNotNone(sidecar_path, 'the canary fixture must produce a real sidecar write')
        marker_path = c._write_job_marker(sid, job, c._module_paths())
        return job, marker_path, sidecar_path

    def test_canary_evaluator_prose_persists_clamped_and_ifs_clean(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-p38-canary-')
        try:
            state_dir = os.path.join(tmpdir, 'state')
            markers_dir = os.path.join(state_dir, 'markers')
            sid = 'p38-canary-sid-001'
            job_id = 'p38-canary-job-001'
            job, marker_path, sidecar_path = self._attach_and_write(sid, job_id, state_dir, markers_dir)

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

            # Phase 42 Plan 05 -- the same clamping and IFS-cleanliness
            # guarantees, now for all THREE narrative fields in the SIDECAR
            # record (basis, candidate_downstream_outcome,
            # counterfactual_assumption), against the sidecar's OWN 500-byte
            # NARRATIVE_CLAMP_BYTES budget -- not the marker's 200.
            self.assertIsNotNone(sidecar_path, 'the canary fixture must have produced a sidecar record')
            sidecar_lines = sidecar_path.read_text().strip().splitlines()
            self.assertEqual(len(sidecar_lines), 1, f'expected exactly one sidecar line: {sidecar_lines}')
            sidecar_record = json.loads(sidecar_lines[0])

            sidecar_basis = sidecar_record['basis']
            sidecar_outcome = sidecar_record['candidate_downstream_outcome']
            sidecar_counterfactual = sidecar_record['counterfactual_assumption']

            for field_name, value, canary in (
                ('basis', sidecar_basis, self.EVALUATOR_BASIS_CANARY),
                ('candidate_downstream_outcome', sidecar_outcome, self.EVALUATOR_OUTCOME_CANARY),
                ('counterfactual_assumption', sidecar_counterfactual, self.EVALUATOR_COUNTERFACTUAL_CANARY),
            ):
                for bad in ('|', '\n', '\r'):
                    self.assertNotIn(
                        bad, value, f'sidecar {field_name} must be IFS-clean: {value!r}',
                    )
                self.assertIn(canary, value, f'sidecar {field_name} must carry its own canary')
                self.assertLessEqual(
                    len(json.dumps(value).encode('utf-8')) - 2, 500,
                    f'sidecar {field_name} must be clamped to its 500-byte serialized budget',
                )

            self.assertNotIn(
                self.TRANSCRIPT_CANARY, sidecar_path.read_text(),
                'the transcript canary must never reach the sidecar',
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

            _job, _marker_path, _sidecar_path = self._attach_and_write(
                sid, job_id, state_dir, markers_dir,
            )

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

            # Phase 42 Plan 05: the sidecar is a NEW persisted artifact the
            # checks above -- enumerated by name -- do not know about. A
            # recursive walk of the whole temp tree covers it (and every
            # FUTURE new artifact) automatically instead of needing another
            # hand-listed edit. This is additive to the named checks above,
            # not a replacement -- their per-artifact failure messages stay
            # useful for triage; the walk is the safety net that catches
            # what a hand-listed set would miss.
            self.assertTrue(_sidecar_path is not None and _sidecar_path.exists(),
                             'the fixture must have produced a real sidecar file for this sweep to mean anything')
            swept_files = []
            for root, _dirs, files in os.walk(tmpdir):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    swept_files.append(fpath)
                    try:
                        with open(fpath, 'rb') as f:
                            raw_bytes = f.read()
                    except OSError:
                        continue
                    try:
                        text = raw_bytes.decode('utf-8')
                    except UnicodeDecodeError:
                        # No text artifact this pipeline writes is expected
                        # to be non-UTF-8 (every JSONL/ledger/log write in
                        # this codebase is ensure_ascii=True text); a binary
                        # file here is out of scope for a text canary sweep.
                        continue
                    self.assertNotIn(
                        canary, text,
                        f'{fpath} must not carry the transcript canary (recursive sweep)',
                    )
            self.assertIn(
                str(_sidecar_path), swept_files,
                'the recursive walk must have actually visited the sidecar file, or this '
                'sweep proves nothing about the NEW artifact it exists to cover',
            )
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

            # Phase 42 Plan 05 (D-11): an abstention is now a REAL sidecar
            # record -- the raw model output was in scope moments before
            # this record was built, so it is exactly where a leak would
            # land. Sweep it for both canaries.
            record = job.get('_assessment_record')
            self.assertIsInstance(record, dict, 'D-11: a rejected evaluation must still produce a record')
            self.assertEqual(
                record.get('abstention_reason'), 'invalid',
                'the abstention record must carry the reason word this rejection produced',
            )
            for absent_key in (
                'value_low', 'value_base', 'value_high', 'bounds_source',
                'currency', 'estimated_value', 'assumptions',
            ):
                self.assertNotIn(
                    absent_key, record,
                    f'D-11: an abstention record must OMIT {absent_key!r}, not null it',
                )
            sidecar_path = c._write_job_assessment(record, c._module_paths())
            self.assertIsNotNone(sidecar_path, 'the abstention record must write successfully')
            sidecar_text = sidecar_path.read_text()
            self.assertNotIn(
                self.TRANSCRIPT_CANARY, sidecar_text,
                'the transcript canary must never reach the abstention sidecar record',
            )
            self.assertNotIn(
                response_canary, sidecar_text,
                'the raw response body must never reach the abstention sidecar record',
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

            # Phase 42 Plan 05 (D-11): same abstention-sidecar sweep as the
            # invalid-line test, for the timed-out path.
            record = job.get('_assessment_record')
            self.assertIsInstance(record, dict, 'D-11: a timed-out evaluation must still produce a record')
            self.assertEqual(record.get('abstention_reason'), 'timed_out')
            for absent_key in (
                'value_low', 'value_base', 'value_high', 'bounds_source',
                'currency', 'estimated_value', 'assumptions',
            ):
                self.assertNotIn(absent_key, record)
            sidecar_path = c._write_job_assessment(record, c._module_paths())
            self.assertIsNotNone(sidecar_path, 'the abstention record must write successfully')
            self.assertNotIn(
                self.TRANSCRIPT_CANARY, sidecar_path.read_text(),
                'the transcript canary must never reach the abstention sidecar record',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
