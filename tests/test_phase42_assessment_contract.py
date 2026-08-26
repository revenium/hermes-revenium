"""Phase 42 Plan 01 — the correction ledger prefix, proven unmatchable first.

`41-ARCHITECTURE.md` names this in as many words: "phase 42 should treat 'the
prefix really is unmatchable' as its own first test, not an assumption
inherited from this document." `42-CONTEXT.md`'s `<specifics>` repeats it
verbatim. This module is that test, written and passing BEFORE any
correction-authoring code exists.

Requirements covered:
  EGV-09 — corrections append; the original assessment and its complete
           history are preserved, never destructively replaced. This module
           proves the mechanism that makes that safe: a `JOB:<id>:correction:
           <seq>:<ts>` ledger line can neither forge an "already reported"
           verdict (OUTCOME-01) nor a "create confirmed" verdict (OUTCOME-04)
           against the ordinary per-tick `job_outcome_queue` path.

Decision defended:
  D-01 (42-CONTEXT.md) — Phase 42 builds the full C-06 correction path with
  its own distinct ledger prefix, deliberately disjoint from the two grep
  gates `hermes-report.sh`'s post-loop outcome stage already relies on for
  idempotency. This module is the proof that disjointness holds against a
  real ledger file, through the real `grep` engine the production gate uses
  -- not `re.match`, and not an assumption carried over from `41-ARCHITECTURE.md`.

Every test in this module runs OFFLINE: no network, no revenium CLI, no
subprocess other than a real `grep` invocation against a real temp file.
"""
import ast
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
SCRIPTS_DIR = SKILL / 'scripts'

HERMES_REPORT_SH = SCRIPTS_DIR / 'hermes-report.sh'

# The exact gate-comment anchors in hermes-report.sh's post-loop outcome
# stage, copied verbatim from the live source (not retyped from the plan).
OUTCOME_01_GATE_COMMENT = '# OUTCOME-01 gate:'
OUTCOME_04_GATE_COMMENT = '# OUTCOME-04 gate:'


def _extract_grep_pattern(script_text, gate_comment, job_id):
    """Pull the grep -q pattern immediately following `gate_comment`.

    Reads the LIVE hermes-report.sh source rather than hardcoding the
    pattern from the plan -- if the gate has moved or been reworded, this
    returns None and the caller must fail loudly (a silently-skipped
    extraction would turn this proof into a no-op, per Task 1's own
    instruction).
    """
    idx = script_text.find(gate_comment)
    if idx == -1:
        return None
    window = script_text[idx:idx + 400]
    match = re.search(r'grep -q "([^"]+)"', window)
    if not match:
        return None
    return match.group(1).replace('${outcome_id}', job_id)


def _extract_correction_record_fields(script_text):
    """Pull the correction record's key names, in source order, straight out
    of correct-assessment.sh's own `record = {...}` dict literal (Step 5) --
    the same "read the live source, don't retype the plan" discipline
    `_extract_grep_pattern` uses above for the ledger gate patterns (IN-01,
    42-REVIEW.md). Returns None -- never a partial or guessed list -- if the
    block has moved or no longer parses as expected, so a real drift fails
    the caller loudly instead of silently testing a stale shape again.
    """
    # Greptile P2 (PR #96): the first version scanned for `'(\w+)':` with a
    # regex, which recognised single-quoted keys only and returned whatever
    # subset it happened to match. A double-quoted key -- a pure formatting
    # change -- would have been dropped silently, leaving `fields` non-empty
    # and the byte-budget test measuring a SMALLER record while still
    # passing. An extractor that can quietly under-match defeats the whole
    # point of reading the live source instead of retyping it.
    #
    # Parsing the literal with `ast` removes the quoting question entirely:
    # the keys come from the parse tree, so any valid Python spelling is
    # read correctly or the parse fails outright. `ast.literal_eval` is not
    # usable here -- the values are live expressions like
    # `_num(os.environ.get(...))` -- but `ast.parse` handles them fine, and
    # only the keys are read.
    occurrences = [
        i for i in range(len(script_text))
        if script_text.startswith('record = {', i)
    ]
    if len(occurrences) != 1:
        # Zero: the block moved. More than one: which is the correction
        # record is now ambiguous. Either way, refuse rather than guess.
        return None
    start = occurrences[0]
    end = script_text.find('\n    }', start)
    if end == -1:
        return None

    literal = script_text[start:end] + '\n    }'
    try:
        tree = ast.parse(literal)
    except SyntaxError:
        return None
    if not tree.body or not isinstance(tree.body[0], ast.Assign):
        return None
    node = tree.body[0].value
    if not isinstance(node, ast.Dict):
        return None

    fields = []
    for key in node.keys:
        # A non-constant or non-str key (e.g. `**spread`, which parses as a
        # None key) means the shape is no longer a flat literal this test
        # can reason about -- refuse loudly rather than silently skip it.
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        fields.append(key.value)
    return fields or None


def _grep_matching_lines(pattern, ledger_path):
    """Run `pattern` through a REAL grep subprocess against `ledger_path`.

    Deliberately not re.match: the production gate is `grep -q "<pattern>"
    "${JOBS_LEDGER_FILE}"`, and EGV-09/D-01's proof must exercise the same
    matching engine the live code depends on, not a Python re-implementation
    that could silently diverge from grep's own BRE semantics.
    """
    result = subprocess.run(
        ['grep', pattern, str(ledger_path)],
        capture_output=True, text=True,
    )
    if result.returncode not in (0, 1):
        raise AssertionError(
            f'EGV-09/D-01: grep exited {result.returncode} unexpectedly for '
            f'pattern {pattern!r} against {ledger_path}: {result.stderr}'
        )
    return [line for line in result.stdout.splitlines() if line]


class LedgerPrefixDisjointnessTests(unittest.TestCase):
    """EGV-09/D-01 -- the correction prefix is unmatchable by construction.

    Proves, against a real jobs-ledger fixture through a real `grep`
    subprocess, that `JOB:<id>:correction:<seq>:<ts>` satisfies neither
    OUTCOME-01 (`^JOB:${outcome_id}:outcome:`) nor OUTCOME-04
    (`^JOB:${outcome_id}:created:`) -- the two grep gates
    `hermes-report.sh`'s post-loop outcome stage relies on for idempotency
    and deferred-create retry.
    """

    JOB_ID = 'assess-42-job-001'
    OTHER_JOB_ID = 'assess-42-job-002'

    def setUp(self):
        self.script_text = HERMES_REPORT_SH.read_text()
        self.outcome_01_pattern = _extract_grep_pattern(
            self.script_text, OUTCOME_01_GATE_COMMENT, self.JOB_ID)
        self.outcome_04_pattern = _extract_grep_pattern(
            self.script_text, OUTCOME_04_GATE_COMMENT, self.JOB_ID)
        if self.outcome_01_pattern is None:
            self.fail(
                'EGV-09/D-01: OUTCOME-01 gate comment '
                f'{OUTCOME_01_GATE_COMMENT!r} not found (or its grep pattern '
                'not extractable) in hermes-report.sh -- the gate moved and '
                'this proof must be updated, not silently skipped.'
            )
        if self.outcome_04_pattern is None:
            self.fail(
                'EGV-09/D-01: OUTCOME-04 gate comment '
                f'{OUTCOME_04_GATE_COMMENT!r} not found (or its grep pattern '
                'not extractable) in hermes-report.sh -- the gate moved and '
                'this proof must be updated, not silently skipped.'
            )

        self.tmpdir = tempfile.mkdtemp(prefix='gsd-phase42-ledger-')
        self.full_ledger = Path(self.tmpdir) / 'revenium-jobs-full.ledger'
        self.full_ledger.write_text(
            f'JOB:{self.JOB_ID}:created:1755999000\n'
            f'JOB:{self.JOB_ID}:outcome:1755999005:SUCCESS\n'
            f'JOB:{self.JOB_ID}:correction:1:1755999100\n'
            f'JOB:{self.OTHER_JOB_ID}:created:1755999200\n'
            f'JOB:{self.OTHER_JOB_ID}:outcome:1755999205:SUCCESS\n'
            f'JOB:{self.OTHER_JOB_ID}:correction:1:1755999300\n'
        )

        # Deferred-then-corrected shape: a correction filed while the job's
        # outcome was still deferred (no `outcome:` line ever written for
        # this job id). This is the fixture assertion 2 depends on -- the
        # correction line must not be able to forge an "already reported"
        # verdict in the ABSENCE of a real outcome line either.
        self.deferred_then_corrected_ledger = (
            Path(self.tmpdir) / 'revenium-jobs-deferred.ledger'
        )
        self.deferred_then_corrected_ledger.write_text(
            f'JOB:{self.JOB_ID}:created:1755999000\n'
            f'JOB:{self.JOB_ID}:correction:1:1755999100\n'
        )

    def test_outcome_01_matches_exactly_the_outcome_line(self):
        matches = _grep_matching_lines(self.outcome_01_pattern, self.full_ledger)
        self.assertEqual(
            len(matches), 1,
            'EGV-09/D-01: OUTCOME-01 must match exactly one line for a job '
            f'id with created+outcome+correction lines, got {matches!r}'
        )
        self.assertEqual(
            matches[0], f'JOB:{self.JOB_ID}:outcome:1755999005:SUCCESS',
            'EGV-09/D-01: OUTCOME-01\'s one match must be the outcome line, '
            f'not the correction line -- got {matches[0]!r}'
        )

    def test_outcome_01_does_not_match_deferred_then_corrected_shape(self):
        """A correction filed before any outcome line must not forge OUTCOME-01.

        This is the assertion that a `JOB:<id>:correction:` line cannot make
        the ordinary per-tick outcome stage believe a job was already
        reported when it never was.
        """
        matches = _grep_matching_lines(
            self.outcome_01_pattern, self.deferred_then_corrected_ledger)
        self.assertEqual(
            matches, [],
            'EGV-09/D-01: OUTCOME-01 must match ZERO lines when a ledger '
            'holds only created+correction lines for a job id -- a '
            f'correction line must never forge "already reported", got {matches!r}'
        )

    def test_outcome_04_matches_exactly_the_created_line(self):
        matches = _grep_matching_lines(self.outcome_04_pattern, self.full_ledger)
        self.assertEqual(
            len(matches), 1,
            'EGV-09/D-01: OUTCOME-04 must match exactly one line for a job '
            f'id with created+outcome+correction lines, got {matches!r}'
        )
        self.assertEqual(
            matches[0], f'JOB:{self.JOB_ID}:created:1755999000',
            'EGV-09/D-01: OUTCOME-04\'s one match must be the created line, '
            f'not the correction line -- got {matches[0]!r}'
        )

    def test_outcome_04_never_satisfied_by_a_correction_line(self):
        matches = _grep_matching_lines(
            self.outcome_04_pattern, self.deferred_then_corrected_ledger)
        self.assertEqual(
            len(matches), 1,
            'EGV-09/D-01: OUTCOME-04 must still match the created line alone '
            f'in the deferred-then-corrected shape, got {matches!r}'
        )
        self.assertEqual(
            matches[0], f'JOB:{self.JOB_ID}:created:1755999000',
            'EGV-09/D-01: a correction line must never satisfy OUTCOME-04 -- '
            f'got {matches[0]!r}'
        )

    def test_correction_prefix_matches_only_its_own_line_job_id_scoped(self):
        """Proves the patterns are job-id-scoped, not merely word-scoped.

        Greps for the correction prefix itself (both job ids share the
        `correction:` word) and asserts it matches exactly the ONE line for
        JOB_ID, never OTHER_JOB_ID's correction line and never either job's
        created/outcome lines.
        """
        correction_pattern = f'^JOB:{self.JOB_ID}:correction:'
        matches = _grep_matching_lines(correction_pattern, self.full_ledger)
        self.assertEqual(
            matches, [f'JOB:{self.JOB_ID}:correction:1:1755999100'],
            'EGV-09/D-01: the correction prefix must match exactly the one '
            f'correction line for this job id, got {matches!r}'
        )


class OrdinaryPathDoubleReportGuardTests(unittest.TestCase):
    """EGV-09/D-01 -- the ordinary path must remain gated.

    This class exists to prevent a future test from drifting into asserting
    that the ordinary `job_outcome_queue` path may report a job id twice
    through `revenium jobs outcome`. Any such assertion IS the regression
    D-01's correction-path design exists to avoid, not a feature to
    preserve -- 42-RESEARCH.md's Pitfall 4 and 42-CONTEXT.md's `<specifics>`
    section both name this exact review warning sign verbatim: "a new test
    asserting a job id can be reported twice through the ordinary
    `job_outcome_queue` path... is the regression this design exists to
    avoid, not a feature."
    """

    JOB_ID = 'assess-42-guard-001'

    def setUp(self):
        self.script_text = HERMES_REPORT_SH.read_text()
        self.outcome_01_pattern = _extract_grep_pattern(
            self.script_text, OUTCOME_01_GATE_COMMENT, self.JOB_ID)
        if self.outcome_01_pattern is None:
            self.fail(
                'EGV-09/D-01: OUTCOME-01 gate comment '
                f'{OUTCOME_01_GATE_COMMENT!r} not found in hermes-report.sh '
                '-- update the extraction anchor before trusting this proof.'
            )
        self.tmpdir = tempfile.mkdtemp(prefix='gsd-phase42-guard-')

    def test_ordinary_path_still_gated_once_outcome_reported(self):
        ledger = Path(self.tmpdir) / 'revenium-jobs.ledger'
        ledger.write_text(
            f'JOB:{self.JOB_ID}:created:1755999000\n'
            f'JOB:{self.JOB_ID}:outcome:1755999005:SUCCESS\n'
        )
        matches = _grep_matching_lines(self.outcome_01_pattern, ledger)
        self.assertEqual(
            len(matches), 1,
            'EGV-09/D-01: the ordinary per-tick path must remain gated by '
            'OUTCOME-01 once a real outcome line exists -- a job id must '
            f'never be reportable twice through job_outcome_queue, got {matches!r}'
        )

    def test_ordinary_path_ungated_before_any_outcome_reported(self):
        """Sanity complement: OUTCOME-01 must NOT block a genuinely-unreported job."""
        ledger = Path(self.tmpdir) / 'revenium-jobs-unreported.ledger'
        ledger.write_text(f'JOB:{self.JOB_ID}:created:1755999000\n')
        matches = _grep_matching_lines(self.outcome_01_pattern, ledger)
        self.assertEqual(
            matches, [],
            'EGV-09/D-01: OUTCOME-01 must not block a job id that has never '
            f'been reported -- got {matches!r}'
        )


# ---------------------------------------------------------------------------
# Plan 02 — the tracer: a JobAssessment written to the sidecar, re-read by a
# real `bash hermes-report.sh` subprocess, reaching --outcome-value.
#
# Requirements covered:
#   EGV-04 — the sidecar carrier (a narrow tracer slice of the full field
#            shape; 42-03 expands it).
#   EGV-07 — provenance (evaluator/evaluator_version/confidence) survives the
#            sidecar round trip intact.
#   EGV-06 (partial) — value bounds are carried, though the abstain-on-
#            disorder rule itself is 42-03/42-04 scope.
# ---------------------------------------------------------------------------
import asyncio
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys as _sys
import tempfile
import textwrap
import time
import unittest.mock

from tests._compat_helpers import (
    assert_argv_matches_golden, build_shim, build_state_db, load_golden,
)

PLUGIN_DIR = SKILL / 'plugins' / 'revenium-classifier'


def _run_hermes_report(env, jobs_log):
    """Run hermes-report.sh once as a REAL subprocess; return
    (returncode, jobs_invocations, combined_output). jobs_invocations is a
    list of shlex.split argv lists starting with the 'jobs' verb."""
    result = subprocess.run(
        ['bash', str(SCRIPTS_DIR / 'hermes-report.sh')],
        env=env, capture_output=True, text=True, timeout=60,
    )
    invocations = []
    if os.path.exists(jobs_log):
        with open(jobs_log) as f:
            for line in f:
                line = line.rstrip('\n')
                if line:
                    invocations.append(shlex.split(line))
    return result.returncode, invocations, result.stdout + result.stderr


def _outcome_argv(jobs_invocations):
    for argv in jobs_invocations:
        if len(argv) >= 2 and argv[0] == 'jobs' and argv[1] == 'outcome':
            return argv
    return None


def _metadata_of(argv):
    for i, tok in enumerate(argv):
        if tok == '--metadata' and i + 1 < len(argv):
            return argv[i + 1]
    return None


def _tracer_assessment_record(job_id, **overrides):
    """The tracer's own narrow JobAssessment shape (Task 1's action text):
    identity, schema version, one bound family (a zero-width band), currency,
    and provenance. 42-03 replaces the zero-width band with real bound
    derivation and adds the remaining EGV-04 fields.

    Phase 43 (EGV-18, D-05/D-09): classifier.py's _build_job_assessment
    populates reportability_status UNCONDITIONALLY on every record it
    builds. Defaulted here to the reportable literal so every test in this
    module -- written before hermes-report.sh read this field at all --
    keeps describing a record that ships its value, unless a test
    explicitly overrides it to exercise the EGV-18 gate itself."""
    record = {
        'kind': 'job_assessment',
        # WR-02: classifier.py's _forced_evidence_class() populates this
        # UNCONDITIONALLY on every job_assessment, exactly as it does
        # reportability_status. A fixture without it tested a state
        # production cannot produce -- and the reporter now refuses an
        # absent evidence_class on a job_assessment, which is what
        # surfaced the gap.
        'evidence_class': 'MODEL_ESTIMATED_DEMO',
        'ts': 1715516002.5,
        'agentic_job_id': job_id,
        'assessment_id': f'{job_id}:0',
        'assessment_schema_version': 1,
        'value_low': 525.0,
        'value_base': 525.0,
        'value_high': 525.0,
        'bounds_source': 'derived',
        'currency': 'USD',
        'estimated_value': 525.0,
        'evaluator': 'llm',
        'evaluator_version': 'v1',
        'confidence': 0.8,
        'reportability_status': 'reportable',
    }
    record.update(overrides)
    return record


class SidecarTracerTests(unittest.TestCase):
    """The tracer's own end-to-end proof: a JobAssessment written to
    ${STATE_DIR}/job-assessments/<job_id>.jsonl is re-read by a REAL
    `bash hermes-report.sh` subprocess and reaches the `revenium jobs
    outcome` argv, with the job marker's own 9-key `assessment` summary
    playing no part (D-10)."""

    def _build_tree(self, sid, job_id, sidecar_lines=None, marker_assessment=None):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase42-tracer-')
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

        # Pre-seed created line so the outcome stage does not defer (OUTCOME-04).
        with open(jobs_ledger, 'w') as f:
            f.write(f'JOB:{job_id}:created:1715516001.000\n')

        task_marker = {
            'muid': f'{job_id}-task', 'ts': 1715516000.5, 'sid': sid,
            'task_type': 'code_review', 'operation_type': 'CHAT',
        }
        job_marker = {
            'kind': 'job', 'ts': 1715516002.0, 'sid': sid,
            'agentic_job_id': job_id, 'job_name': 'Phase 42 Tracer Job',
            'job_type': 'code_review', 'status': 'SUCCESS',
        }
        if marker_assessment is not None:
            job_marker['assessment'] = marker_assessment
        with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
            f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
            f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

        if sidecar_lines:
            # A plain-word job id needs no sanitizing -- the component IS
            # the job id, matching _sidecar_filename_component's no-op case.
            with open(os.path.join(assessments_dir, f'{job_id}.jsonl'), 'w') as f:
                for rec in sidecar_lines:
                    f.write(json.dumps(rec, separators=(',', ':')) + '\n')

        shim_home = os.path.join(tmpdir, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir)
        meter_log = os.path.join(tmpdir, 'meter.log')
        jobs_log = os.path.join(tmpdir, 'jobs.log')
        shim = os.path.join(bin_dir, 'revenium')
        build_shim(shim)

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
        return tmpdir, env, jobs_log

    def test_sidecar_value_reaches_jobs_outcome_argv(self):
        sid, job_id = 'p42-tracer-sid-001', 'p42-tracer-job-001'
        tmpdir, env, jobs_log = self._build_tree(
            sid, job_id, sidecar_lines=[_tracer_assessment_record(job_id)],
        )
        try:
            rc, invocations, out = _run_hermes_report(env, jobs_log)
            self.assertEqual(rc, 0, f'hermes-report.sh failed: {out}')
            argv = _outcome_argv(invocations)
            self.assertIsNotNone(argv, f'expected a jobs outcome invocation: {invocations}')
            self.assertEqual(argv[argv.index('--outcome-value') + 1], '525.0')
            self.assertEqual(argv[argv.index('--outcome-currency') + 1], 'USD')
            meta = json.loads(_metadata_of(argv))
            self.assertEqual(meta.get('evaluator'), 'llm')
            self.assertEqual(meta.get('evaluator_version'), 'v1')
            self.assertEqual(meta.get('confidence'), 0.8)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_no_sidecar_ships_no_value_even_with_marker_assessment(self):
        """D-10: the job marker's own 9-key `assessment` summary must NEVER
        be used as a fallback for value, even though it is present and
        carries a plausible number."""
        sid, job_id = 'p42-tracer-sid-002', 'p42-tracer-job-002'
        marker_assessment = {
            'estimated_value': 999.0, 'currency': 'USD', 'basis': 'x',
            'assumptions': {'inferred_role': 'x', 'estimated_hours_saved': 1.0,
                             'assumed_loaded_rate': 999.0},
            'confidence': 0.9, 'evaluator': 'llm', 'evaluator_version': 'v1',
            'evidence_class': 'MODEL_ESTIMATED_DEMO',
        }
        tmpdir, env, jobs_log = self._build_tree(
            sid, job_id, sidecar_lines=None, marker_assessment=marker_assessment,
        )
        try:
            rc, invocations, out = _run_hermes_report(env, jobs_log)
            self.assertEqual(rc, 0, f'hermes-report.sh failed: {out}')
            argv = _outcome_argv(invocations)
            self.assertIsNotNone(argv, f'expected a jobs outcome invocation: {invocations}')
            self.assertNotIn('--outcome-value', argv)
            self.assertNotIn('--outcome-currency', argv)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_oversized_sidecar_line_is_skipped(self):
        sid, job_id = 'p42-tracer-sid-003', 'p42-tracer-job-003'
        huge = _tracer_assessment_record(job_id, padding='z' * 9000)
        tmpdir, env, jobs_log = self._build_tree(sid, job_id, sidecar_lines=[huge])
        try:
            rc, invocations, out = _run_hermes_report(env, jobs_log)
            self.assertEqual(rc, 0, f'hermes-report.sh failed: {out}')
            argv = _outcome_argv(invocations)
            self.assertIsNotNone(argv, f'expected a jobs outcome invocation: {invocations}')
            self.assertNotIn('--outcome-value', argv)
            self.assertNotIn('--outcome-currency', argv)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_two_lines_for_one_job_id_resolve_to_the_last(self):
        """The deliberate no-`break` scan: a later line for the same job id
        must supersede an earlier one -- the shape a `kind:"correction"`
        line will use once 42-06 ships."""
        sid, job_id = 'p42-tracer-sid-004', 'p42-tracer-job-004'
        first = _tracer_assessment_record(
            job_id, value_low=100.0, value_base=100.0, value_high=100.0, estimated_value=100.0,
        )
        second = _tracer_assessment_record(
            job_id, assessment_id=f'{job_id}:1',
            value_low=200.0, value_base=200.0, value_high=200.0, estimated_value=200.0,
        )
        tmpdir, env, jobs_log = self._build_tree(sid, job_id, sidecar_lines=[first, second])
        try:
            rc, invocations, out = _run_hermes_report(env, jobs_log)
            self.assertEqual(rc, 0, f'hermes-report.sh failed: {out}')
            argv = _outcome_argv(invocations)
            self.assertIsNotNone(argv, f'expected a jobs outcome invocation: {invocations}')
            self.assertEqual(argv[argv.index('--outcome-value') + 1], '200.0')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# In-process classifier harness -- isolated-import pattern copied from
# tests/test_phase38_reporter_path.py (a UNIQUE module name per call, since
# the classifier binds its path constants at import time and Python caches
# submodules by name). Restored per-test, not just at module teardown, in
# case a later class in this SAME run inherits a dangling env var.
# ---------------------------------------------------------------------------
_LOAD_SEQ = [0]
_ENV_TOUCHED = set()
_ENV_SAVED = {}


def setUpModule():
    for k in ('REVENIUM_STATE_DIR', 'REVENIUM_MARKERS_DIR', 'REVENIUM_CONFIG_FILE',
              'REVENIUM_JOB_ASSESSMENTS_DIR', 'HERMES_HOME'):
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
    for cached in [k for k in list(_sys.modules) if k.startswith('p42_pkg')]:
        del _sys.modules[cached]


def _load_classifier(env=None):
    """Import the revenium-classifier plugin fresh; return (classifier, evaluators)."""
    for k, v in (env or {}).items():
        os.environ[k] = v
        _ENV_TOUCHED.add(k)
    _LOAD_SEQ[0] += 1
    name = f'p42_pkg_{_LOAD_SEQ[0]}'
    for cached in [k for k in _sys.modules if k.startswith('p42_pkg')]:
        del _sys.modules[cached]
    spec = importlib.util.spec_from_file_location(
        name, str(PLUGIN_DIR / '__init__.py'), submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    _sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return _sys.modules[f'{name}.classifier'], _sys.modules[f'{name}.evaluators']


class SidecarWriteOrderingTests(unittest.TestCase):
    """The executable form of D-12: sidecar FIRST, then the job marker.

    With `_write_job_marker` monkeypatched to raise, drives the real job-
    loop seam via `run_classification_async` and asserts the sidecar record
    is present on disk while the marker file carries no `kind:"job"` line
    for that job -- proving a crash between the two appends orphans only
    the marker, never the assessment's value. This is also the INTERRUPTED
    half of the EGV-07 concurrency question ("if interrupted or run in
    parallel, what is guaranteed?"); SidecarConcurrentWriterTests below
    answers the PARALLEL half.
    """

    def tearDown(self):
        _restore_env()

    def test_sidecar_persists_when_write_job_marker_raises(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase42-order-')
        try:
            state_dir = os.path.join(tmpdir, 'state')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(state_dir, exist_ok=True)
            config_file = os.path.join(state_dir, 'config.json')
            with open(config_file, 'w') as f:
                json.dump({'llmOutcomeEvaluation': {
                    'enabled': True, 'evaluator': 'p42-order-stub', 'currency': 'USD',
                }}, f)

            env = {
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_MARKERS_DIR': markers_dir,
                'REVENIUM_CONFIG_FILE': config_file,
            }
            c, ev = _load_classifier(env)
            ev.register('p42-order-stub', lambda job, transcript, cfg: {
                'inferred_role': 'engineer', 'estimated_hours_saved': 2.0,
                'assumed_loaded_rate': 100.0, 'currency': 'USD',
                'basis': 'stub', 'confidence': 0.7,
            })

            sid = 'p42-order-sid-001'
            job_id = 'p42-order-job-001'

            task_resp = unittest.mock.MagicMock()
            task_resp.choices = [unittest.mock.MagicMock()]
            task_resp.choices[0].message.content = 'code_review'
            job_array_resp = unittest.mock.MagicMock()
            job_array_resp.choices = [unittest.mock.MagicMock()]
            job_array_resp.choices[0].message.content = json.dumps([
                {'agentic_job_id': job_id, 'job_name': 'n', 'job_type': 'bug_fix', 'status': 'SUCCESS'}
            ])

            with unittest.mock.patch.object(c, 'call_llm', side_effect=[task_resp, job_array_resp]), \
                 unittest.mock.patch.object(c, '_read_session_transcript',
                                             return_value='user: fix\nassistant: done'), \
                 unittest.mock.patch.object(c, '_write_job_marker', side_effect=RuntimeError('boom')):
                asyncio.run(c.run_classification_async(
                    session_id=sid, message='fix the bug', response='fixed',
                ))

            # DECLARE-02: _validate_job unconditionally appends a
            # secrets.token_hex(2) entropy suffix to the LLM-supplied
            # agentic_job_id, so the real id on disk is "<job_id>_<4hex>",
            # not job_id itself. Glob for it rather than assuming the exact
            # filename.
            assessments_dir = Path(state_dir) / 'job-assessments'
            candidates = sorted(assessments_dir.glob(f'{job_id}_*.jsonl'))
            self.assertEqual(
                len(candidates), 1,
                f'D-12: expected exactly one sidecar file for {job_id}_*, '
                f'got {candidates} even though _write_job_marker raised',
            )
            sidecar_path = candidates[0]
            sidecar_lines = [l for l in sidecar_path.read_text().splitlines() if l.strip()]
            self.assertEqual(len(sidecar_lines), 1, sidecar_lines)
            rec = json.loads(sidecar_lines[0])
            self.assertEqual(rec['kind'], 'job_assessment')
            self.assertTrue(rec['agentic_job_id'].startswith(job_id))

            marker_path = Path(markers_dir) / f'{sid}.jsonl'
            marker_text = marker_path.read_text() if marker_path.exists() else ''
            for line in marker_text.splitlines():
                if not line.strip():
                    continue
                m_rec = json.loads(line)
                self.assertNotEqual(
                    m_rec.get('kind'), 'job',
                    'D-12: no kind:"job" line may exist -- _write_job_marker raised',
                )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class SidecarConcurrentWriterTests(unittest.TestCase):
    """The PARALLEL half of the EGV-07 concurrency question, answered only
    by construction until proven here: two REAL processes (not threads --
    `fcntl.flock` is a per-open-file lock, so a threaded test sharing one
    descriptor would prove nothing) appending to the SAME job's sidecar
    file, driven through the real `_write_job_assessment`.

    Mutation check (run manually, not committed as an automated assertion
    per this plan's own acceptance criteria): temporarily removing the
    `fcntl.flock(f, fcntl.LOCK_EX)` call from `_write_job_assessment` must
    make at least one test below FAIL; reverting restores a clean pass.
    """

    _DRIVER = textwrap.dedent('''\
        import json
        import os
        import sys
        import time
        import importlib.util

        plugin_dir = sys.argv[1]
        job_id = sys.argv[2]
        n = int(sys.argv[3])
        writer_id = sys.argv[4]
        kind = sys.argv[5]

        spec = importlib.util.spec_from_file_location(
            'p42_driver_classifier', os.path.join(plugin_dir, 'classifier.py'))
        c = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(c)

        paths = c._module_paths()
        for i in range(n):
            rec = {
                'kind': kind,
                'ts': time.time(),
                'agentic_job_id': job_id,
                'assessment_id': f'{job_id}:{writer_id}-{i}',
                'assessment_schema_version': 1,
                'value_low': float(i), 'value_base': float(i), 'value_high': float(i),
                'bounds_source': 'derived', 'currency': 'USD', 'estimated_value': float(i),
                'evaluator': 'llm', 'evaluator_version': 'v1', 'confidence': 0.5,
                'writer': writer_id,
            }
            c._write_job_assessment(rec, paths)
        ''')

    def _run_two_writers(self, job_id, n, kind_a, kind_b, state_dir):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase42-concurrent-driver-')
        driver_path = os.path.join(tmpdir, 'driver.py')
        with open(driver_path, 'w') as f:
            f.write(self._DRIVER)
        env = {**os.environ, 'REVENIUM_STATE_DIR': state_dir}
        try:
            args_a = ['python3', driver_path, str(PLUGIN_DIR), job_id, str(n), 'A', kind_a]
            args_b = ['python3', driver_path, str(PLUGIN_DIR), job_id, str(n), 'B', kind_b]
            proc_a = subprocess.Popen(args_a, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            proc_b = subprocess.Popen(args_b, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out_a, err_a = proc_a.communicate(timeout=60)
            out_b, err_b = proc_b.communicate(timeout=60)
            self.assertEqual(proc_a.returncode, 0, err_a.decode())
            self.assertEqual(proc_b.returncode, 0, err_b.decode())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _assert_no_torn_lines(self, sidecar_path, n):
        self.assertTrue(sidecar_path.exists(), 'sidecar file must exist after both writers ran')
        lines = [l for l in sidecar_path.read_text().splitlines() if l.strip()]
        self.assertEqual(
            len(lines), 2 * n,
            f'expected exactly {2 * n} lines (no torn/lost writes), got {len(lines)}',
        )
        ids = set()
        for line in lines:
            rec = json.loads(line)  # a torn line fails to parse and raises here
            ids.add(rec['assessment_id'])
        self.assertEqual(
            len(ids), 2 * n,
            'every assessment_id must be unique -- a collision means one writer '
            'stomped another\'s line rather than appending cleanly',
        )
        expected_ids = {f'{rec_job}:{w}-{i}' for w in ('A', 'B') for i in range(n)
                         for rec_job in [sidecar_path.stem]}
        self.assertEqual(ids, expected_ids)

    def test_two_assessment_writers_produce_no_torn_lines(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase42-concurrent-')
        try:
            state_dir = os.path.join(tmpdir, 'state')
            job_id = 'p42-concurrent-job-001'
            n = 300
            self._run_two_writers(job_id, n, 'job_assessment', 'job_assessment', state_dir)
            sidecar_path = Path(state_dir) / 'job-assessments' / f'{job_id}.jsonl'
            self._assert_no_torn_lines(sidecar_path, n)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_mixed_assessment_and_correction_writer_pair_produce_no_torn_lines(self):
        """The classifier and the (later, plan 42-06) operator CLI are
        precisely the two writers that can contend in production."""
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase42-concurrent-mixed-')
        try:
            state_dir = os.path.join(tmpdir, 'state')
            job_id = 'p42-concurrent-job-002'
            n = 300
            self._run_two_writers(job_id, n, 'job_assessment', 'correction', state_dir)
            sidecar_path = Path(state_dir) / 'job-assessments' / f'{job_id}.jsonl'
            self._assert_no_torn_lines(sidecar_path, n)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class BoundsOrderingTests(unittest.TestCase):
    """EGV-06 / D-09 site one: `_validate_assessment`'s abstain-on-disorder
    gate for the sidecar's low/base/high value band, exercised through
    hand-constructed adversarial raw dicts. Table-driven, mirroring
    `tests.test_phase36_evaluator_seam.RejectionMatrixTests`' own shape --
    per 42-CONTEXT.md's Flagged Assumption 1, EGV-06's abstain-on-disorder
    rule needs a hand-constructed adversarial INPUT to exercise, because a
    purely-derived band can never be reversed by construction.
    """

    def setUp(self):
        self.mod, self.ev = _load_classifier({})
        # Baseline key set for the frozen marker `assessment` dict, computed
        # once from a no-bounds (derived) call -- never hardcoded, so a
        # future field addition/removal to _validate_assessment's return
        # shape is caught here rather than silently tolerated.
        baseline = self.mod._validate_assessment(self._raw(), {}, 'stub', '1')
        self.assertIsNotNone(baseline, 'baseline call must be accepted')
        self.baseline_keys = set(baseline.keys())

    def tearDown(self):
        _restore_env()

    def _raw(self, **over):
        raw = {
            'inferred_role': 'engineer', 'estimated_hours_saved': 2.5,
            'assumed_loaded_rate': 150.0, 'currency': 'USD',
            'basis': 'time avoided', 'confidence': 0.5,
        }
        raw.update(over)
        return raw

    def test_bounds_ordering_matrix(self):
        cases = [
            ('no_bounds_supplied_derives', {}, True),
            ('all_three_ordered_accepted', {
                'value_low': 300.0, 'value_base': 375.0, 'value_high': 450.0,
            }, True),
            # Non-strict ordering is load-bearing: plan 42-06's operator
            # point correction writes low == base == high, and that record
            # must be accepted, not rejected.
            ('equal_bounds_accepted_for_42_06_point_corrections', {
                'value_low': 375.0, 'value_base': 375.0, 'value_high': 375.0,
            }, True),
            ('low_gt_base_abstains', {
                'value_low': 400.0, 'value_base': 375.0, 'value_high': 450.0,
            }, False),
            ('base_gt_high_abstains', {
                'value_low': 300.0, 'value_base': 460.0, 'value_high': 450.0,
            }, False),
            ('low_gt_high_abstains', {
                'value_low': 500.0, 'value_base': 375.0, 'value_high': 450.0,
            }, False),
            ('negative_low_abstains', {
                'value_low': -1.0, 'value_base': 375.0, 'value_high': 450.0,
            }, False),
            ('negative_base_abstains', {
                'value_low': 300.0, 'value_base': -1.0, 'value_high': 450.0,
            }, False),
            ('negative_high_abstains', {
                'value_low': 300.0, 'value_base': 375.0, 'value_high': -1.0,
            }, False),
            ('nan_bound_abstains', {
                'value_low': float('nan'), 'value_base': 375.0, 'value_high': 450.0,
            }, False),
            ('inf_bound_abstains', {
                'value_low': 300.0, 'value_base': 375.0, 'value_high': float('inf'),
            }, False),
            ('bool_bound_abstains', {
                'value_low': True, 'value_base': 375.0, 'value_high': 450.0,
            }, False),
            ('string_bound_abstains', {
                'value_low': '300', 'value_base': 375.0, 'value_high': 450.0,
            }, False),
            ('one_of_three_supplied_abstains', {
                'value_low': 300.0,
            }, False),
            ('two_of_three_supplied_abstains', {
                'value_low': 300.0, 'value_base': 375.0,
            }, False),
        ]
        self.assertGreaterEqual(len(cases), 9, 'need at least 9 subtests per plan 42-03')
        for label, overrides, expect_accepted in cases:
            with self.subTest(label):
                got = self.mod._validate_assessment(self._raw(**overrides), {}, 'stub', '1')
                if expect_accepted:
                    self.assertIsNotNone(got, f'{label}: expected acceptance')
                    self.assertEqual(
                        set(got.keys()), self.baseline_keys,
                        f'{label}: the frozen marker assessment dict gained or lost a key',
                    )
                else:
                    self.assertIsNone(got, f'{label}: expected abstention')

    def test_derived_bounds_are_a_symmetric_spread_around_the_point_estimate(self):
        low, base, high, source = self.mod._resolve_value_bounds(self._raw(), 2.5, 150.0)
        self.assertEqual(source, self.mod.BOUNDS_SOURCE_DERIVED)
        self.assertEqual(base, 375.0)
        self.assertLess(low, base)
        self.assertGreater(high, base)

    def test_evaluator_supplied_bounds_used_verbatim(self):
        low, base, high, source = self.mod._resolve_value_bounds(
            self._raw(value_low=300.0, value_base=375.0, value_high=450.0), 2.5, 150.0,
        )
        self.assertEqual((low, base, high), (300.0, 375.0, 450.0))
        self.assertEqual(source, self.mod.BOUNDS_SOURCE_EVALUATOR)

    def test_out_of_bounds_hours_abstains_for_its_original_reason(self):
        """The bounds gate is placed AFTER the hours/rate bound check, so an
        hours value over the configured max still abstains there -- not at
        the (also-failing, since no bounds are supplied) bounds gate."""
        got = self.mod._validate_assessment(
            self._raw(estimated_hours_saved=999.0), {}, 'stub', '1')
        self.assertIsNone(got)


def _p42_shape_env(tmpdir, evaluator_name='p42-shape-stub'):
    """A minimal state tree with LLM outcome evaluation opted in for
    `evaluator_name` -- used by RecordShapeTests/AbstentionRecordTests to
    drive _attach_assessment directly (bypassing the full session
    classification pipeline, which SidecarWriteOrderingTests already
    covers end to end)."""
    state_dir = os.path.join(tmpdir, 'state')
    os.makedirs(state_dir, exist_ok=True)
    config_file = os.path.join(state_dir, 'config.json')
    with open(config_file, 'w') as f:
        json.dump({'llmOutcomeEvaluation': {
            'enabled': True, 'evaluator': evaluator_name, 'currency': 'USD',
        }}, f)
    return {
        'REVENIUM_STATE_DIR': state_dir,
        'REVENIUM_CONFIG_FILE': config_file,
    }


class SidecarBudgetTests(unittest.TestCase):
    """Phase 42 Task 3: the sidecar's own 8,192-byte per-record ceiling.

    Mirrors tests.test_phase36_evaluator_seam.MarkerBudgetTests method for
    method, against SIDECAR_LINE_MAX_BYTES (8192) rather than the marker's
    1024: compute the worst case PROGRAMMATICALLY (never a hardcoded byte
    count), call the REAL constructor, assert acceptance before measuring,
    serialize exactly as the writer does (compact separators,
    ensure_ascii=True, + 1 trailing-newline byte), assert under budget AND
    a stated minimum margin, and cover non-ASCII input -- the exact
    regression class (a character clamp under-counting by up to 12x under
    ensure_ascii=True) that produced a real 3,638-byte marker overrun,
    found only in Phase 36 review.

    41-CARRIER-DECISION.md Part 3 measured a ~2,707-byte worst case with a
    projected 5,485-byte margin for an earlier field count; this class
    measures the REAL number against the REAL constructor and prints it so
    a future reader can compare against that projection.
    """

    # 12.5% of the 8192-byte ceiling -- proportionally close to
    # MarkerBudgetTests' own 100-of-1024 (~9.8%) margin, and comfortably
    # inside 41-03's projected 5,485-byte margin, so a failure here means a
    # real regression rather than a tight fit.
    MARGIN_BYTES = 1024

    def tearDown(self):
        _restore_env()

    def _worst_case_valid(self, job_id):
        return {
            'agentic_job_id': job_id,
            # job_type is LABEL_RE-bounded to 48 chars in production
            # (_validate_job); this is that real ceiling, not an invented one.
            'job_type': 'a' + 'b' * 46 + 'c',
            'status': 'SUCCESS',
        }

    def _worst_case_raw(self, narrative_char='n'):
        return {
            'inferred_role': narrative_char * 60,
            'estimated_hours_saved': 40.0,   # DEFAULT_MAX_HOURS_SAVED, the real bound
            'assumed_loaded_rate': 500.0,    # DEFAULT_MAX_LOADED_RATE, the real bound
            'currency': 'USD',
            'basis': narrative_char * 1000,                          # far over the marker's 200-byte clamp
            'confidence': 0.999999,
            'candidate_downstream_outcome': narrative_char * 1000,   # far over the 500-byte clamp
            'counterfactual_assumption': narrative_char * 1000,      # far over the 500-byte clamp
        }

    def _worst_case_record(self, mod, job_id, narrative_char='n',
                            evaluator='evaluator-name-that-is-fairly-long',
                            evaluator_version='version-string-also-long'):
        raw = self._worst_case_raw(narrative_char)
        assessment = mod._validate_assessment(raw, {}, evaluator, evaluator_version)
        self.assertIsNotNone(assessment, 'max-bound inputs must be accepted, not rejected')
        rec = mod._build_job_assessment(
            self._worst_case_valid(job_id), assessment, raw, {}, evaluator, evaluator_version)
        self.assertIsNotNone(rec, 'worst-case record construction must succeed')
        return rec

    def _serialized_bytes(self, rec):
        # Exactly the writer's own encoding (_write_job_assessment): compact
        # separators, ensure_ascii=True, UTF-8, plus the trailing newline byte.
        return len(json.dumps(rec, separators=(',', ':'), ensure_ascii=True).encode('utf-8')) + 1

    def test_worst_case_full_field_record_fits_8192_bytes_with_margin(self):
        mod, _ev = _load_classifier({})
        rec = self._worst_case_record(mod, job_id='x' * 48 + '_a1b2')
        total = self._serialized_bytes(rec)
        self.assertLess(total, 8192, f'worst-case sidecar record is {total} bytes')
        margin = 8192 - total
        self.assertGreater(
            margin, self.MARGIN_BYTES,
            f'only {margin} bytes of margin (need > {self.MARGIN_BYTES}) -- re-derive the clamps',
        )
        print(f'[42-03 SidecarBudgetTests] worst-case ASCII record: {total} bytes, margin {margin} '
              f'(41-03 projected ~2,707 bytes worst-case / 5,485 bytes margin for an earlier field count)')

    def test_worst_case_record_fits_with_non_ascii(self):
        """Greptile P2 on PR #87's regression class, re-proven for the
        sidecar: markers/sidecar lines are written with ensure_ascii=True,
        so every non-ASCII code point is escaped -- "e"-with-accent and a
        CJK character serialize to 6 bytes each, an emoji to 12. A
        character-based clamp under-counts by up to 12x."""
        mod, _ev = _load_classifier({})
        for label, ch in (('accented', 'é'), ('cjk', '漢'), ('emoji', '😀'), ('mixed', 'a😀é漢')):
            with self.subTest(label):
                rec = self._worst_case_record(
                    mod, job_id=f'job-{label}-' + ch * 10, narrative_char=ch)
                total = self._serialized_bytes(rec)
                self.assertLess(total, 8192, f'{label} record is {total} bytes')
                margin = 8192 - total
                self.assertGreater(
                    margin, self.MARGIN_BYTES,
                    f'{label}: only {margin} bytes of margin (need > {self.MARGIN_BYTES})',
                )
                print(f'[42-03 SidecarBudgetTests] worst-case {label} record: {total} bytes, margin {margin}')

    def test_worst_case_correction_line_fits_8192_bytes_with_margin(self):
        """The REAL kind:"correction" shape correct-assessment.sh's Step 5
        writes -- as of plan 42-06 shipping, that script exists, so this
        test now reads its field list straight from the shipped source
        (_extract_correction_record_fields) rather than hand-retyping a
        plan sketch. IN-01 (42-REVIEW.md): the sketch this replaced used
        new_value_low/new_value_base/new_value_high and an `operator` field
        that never shipped, and omitted assessment_id/
        assessment_schema_version/prior_currency, which did -- this
        extraction makes that drift impossible to reintroduce silently: a
        field correct-assessment.sh writes but this test has no worst-case
        value for fails loudly (see the `missing` assertion below) instead
        of quietly measuring the wrong shape.

        Values themselves are still hand-picked worst cases (deriving those
        from source too would require re-implementing correct-assessment.sh's
        own validation/clamping in Python, which is what CLAUDE.md's
        no-shared-code rule already argues against) -- reason is real-clamped
        via NARRATIVE_CLAMP_BYTES, job id and sequence match the ceiling
        `SidecarBudgetTests._worst_case_valid` uses for the ordinary
        job_assessment shape. Shape per 41-CARRIER-DECISION.md Part 3: job
        id, timestamp, a 500-byte reason, and prior/new bound values --
        measured there at 672 bytes for a much smaller reason; this is the
        WORST case.
        """
        script_text = CORRECT_ASSESSMENT_SH.read_text()
        fields = _extract_correction_record_fields(script_text)
        self.assertIsNotNone(
            fields,
            'IN-01: could not extract the correction record fields from '
            "correct-assessment.sh's `record = {...}` block -- it moved or "
            'changed shape; update the extraction before trusting this test.',
        )

        mod, _ev = _load_classifier({})
        reason = mod._clamp_assessment_text('r' * 2000, mod.NARRATIVE_CLAMP_BYTES)
        job_id = 'x' * 48 + '_a1b2'
        worst_case_values = {
            'kind': 'correction',
            'ts': 1756000000.123456,
            'agentic_job_id': job_id,
            'assessment_id': f'{job_id}:999',
            'sequence': 999,
            'assessment_schema_version': 1,
            'prior_value_low': 999999.99,
            'prior_value_base': 999999.99,
            'prior_value_high': 999999.99,
            'prior_currency': 'USD',
            'value_low': 999999.99,
            'value_base': 999999.99,
            'value_high': 999999.99,
            'currency': 'USD',
            'reason': reason,
        }
        missing = [k for k in fields if k not in worst_case_values]
        self.assertEqual(
            missing, [],
            'IN-01: correct-assessment.sh writes a field this test has no '
            f'worst-case value for: {missing!r} -- add one before trusting '
            'the byte budget.',
        )
        correction = {k: worst_case_values[k] for k in fields}

        total = len(json.dumps(correction, separators=(',', ':'), ensure_ascii=True).encode('utf-8')) + 1
        self.assertLess(total, 8192, f'worst-case correction line is {total} bytes')
        margin = 8192 - total
        self.assertGreater(
            margin, self.MARGIN_BYTES,
            f'only {margin} bytes of margin for a correction line (need > {self.MARGIN_BYTES})',
        )
        print(f'[42-03 SidecarBudgetTests] worst-case correction line: {total} bytes, margin {margin}')

    def test_narrative_fields_never_split_a_surrogate_pair_and_strip_ifs_characters(self):
        mod, _ev = _load_classifier({})
        raw = self._worst_case_raw()
        raw['candidate_downstream_outcome'] = '😀' * 400
        raw['counterfactual_assumption'] = 'a|b\nc\rd'
        raw['basis'] = 'x|y\nz'
        assessment = mod._validate_assessment(raw, {}, 'stub', '1')
        self.assertIsNotNone(assessment)
        rec = mod._build_job_assessment(
            self._worst_case_valid('p42-budget-ifs-job'), assessment, raw, {}, 'stub', '1')
        self.assertIsNotNone(rec)

        # Slicing a Python str slices code points, so an emoji is never
        # halved -- asserted, not assumed.
        out = rec['candidate_downstream_outcome']
        self.assertEqual(out, '😀' * len(out))
        json.dumps(out)  # must not raise on a lone surrogate

        blob = json.dumps(rec)
        for bad in ('|', '\\n', '\\r'):
            self.assertNotIn(bad, blob, f'{bad!r} survived into the sidecar record')


class RecordShapeTests(unittest.TestCase):
    """EGV-04: every declared field family is present in a successfully
    constructed record, and the record round-trips byte-for-byte through
    the REAL sidecar writer plus a plain json.loads of the file's last
    line -- not a hand-copied literal."""

    # The full EGV-04 shape this plan declares (D-06): carrier/identity,
    # job identity/boundaries, the state quartet, the three narrative
    # fields, economics, the value family, assumptions, the observation
    # window, evidence, provenance, and judgement. Compared as a SET
    # against the constructed record's key set so both a missing field and
    # a surprise field are loud (symmetric difference, not a subset check).
    DECLARED_KEYS = {
        'kind', 'ts', 'assessment_id', 'sequence', 'agentic_job_id',
        'assessment_schema_version',
        'job_type', 'taxonomy_version', 'job_started_at', 'job_ended_at',
        'execution_status', 'output_status', 'acceptance_status', 'adoption_status',
        'candidate_downstream_outcome', 'counterfactual_assumption', 'basis',
        'economic_mechanism',
        'value_low', 'value_base', 'value_high', 'bounds_source', 'currency',
        'estimated_value', 'assumptions',
        'observation_window_start', 'observation_window_end',
        'evidence_references', 'evidence_class',
        # Phase 43 (EGV-13, D-08): the study reference a job assessment may
        # carry -- sourced from operator configuration only, never from
        # evaluator output. Added deliberately here, not discovered by a
        # failing test: this comment IS the intent, matching D-02's own
        # "not a test bent to fit code" instruction.
        'study_id', 'study_version',
        'evaluator', 'evaluator_version', 'model', 'prompt_version', 'policy_version',
        'confidence', 'abstention_reason', 'reportability_status',
    }

    def tearDown(self):
        _restore_env()

    def _raw(self, **over):
        raw = {
            'inferred_role': 'engineer', 'estimated_hours_saved': 2.5,
            'assumed_loaded_rate': 150.0, 'currency': 'USD',
            'basis': 'time avoided', 'confidence': 0.5,
            'candidate_downstream_outcome': 'shipped a fix to production',
            'counterfactual_assumption': 'an engineer would have done this manually',
        }
        raw.update(over)
        return raw

    def _valid_job(self, job_id):
        return {'agentic_job_id': job_id, 'job_name': 'n', 'job_type': 'bug_fix', 'status': 'SUCCESS'}

    def test_successful_record_has_every_declared_key(self):
        mod, _ev = _load_classifier({})
        raw = self._raw()
        assessment = mod._validate_assessment(raw, {}, 'stub', '1')
        self.assertIsNotNone(assessment)
        rec = mod._build_job_assessment(
            self._valid_job('p42-shape-001'), assessment, raw, {}, 'stub', '1')
        self.assertIsNotNone(rec)
        got_keys = set(rec.keys())
        missing = self.DECLARED_KEYS - got_keys
        extra = got_keys - self.DECLARED_KEYS
        self.assertEqual(missing, set(), f'record missing declared EGV-04 fields: {missing}')
        self.assertEqual(extra, set(), f'record carries undeclared fields: {extra}')
        # A spot check that narrative/economic/provenance fields carry real
        # values, not placeholders, on the success path.
        self.assertEqual(rec['candidate_downstream_outcome'], raw['candidate_downstream_outcome'])
        self.assertEqual(rec['counterfactual_assumption'], raw['counterfactual_assumption'])
        self.assertEqual(rec['bounds_source'], mod.BOUNDS_SOURCE_DERIVED)
        self.assertEqual(rec['abstention_reason'], '')

    def test_write_then_read_round_trip_equals_constructed_record(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase42-shape-roundtrip-')
        try:
            mod, _ev = _load_classifier({'REVENIUM_JOB_ASSESSMENTS_DIR': tmpdir})
            raw = self._raw()
            assessment = mod._validate_assessment(raw, {}, 'stub', '1')
            self.assertIsNotNone(assessment)
            job_id = 'p42-shape-roundtrip-001'
            rec = mod._build_job_assessment(
                self._valid_job(job_id), assessment, raw, {}, 'stub', '1')
            self.assertIsNotNone(rec)

            written_path = mod._write_job_assessment(rec)
            self.assertIsNotNone(written_path)
            lines = [l for l in written_path.read_text().splitlines() if l.strip()]
            self.assertEqual(len(lines), 1, lines)
            read_back = json.loads(lines[0])
            self.assertEqual(read_back, rec, 'round trip must equal the constructed record field for field')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class AbstentionRecordTests(unittest.TestCase):
    """D-11: all SIX of _attach_assessment's early-return paths persist a
    real sidecar record onto valid["_assessment_record"] -- a distinct
    abstention_reason, every value field ABSENT (not null), full identity
    and provenance kept -- rather than leaving `valid` untouched as before
    this plan. One test method per path (not subTest) so each is
    independently visible in `-v` output."""

    VALUE_KEYS = frozenset({'value_low', 'value_base', 'value_high', 'bounds_source',
                             'currency', 'estimated_value', 'assumptions'})
    IDENTITY_PROVENANCE_KEYS = frozenset({
        'assessment_id', 'ts', 'agentic_job_id', 'assessment_schema_version',
        'evaluator', 'evaluator_version', 'execution_status',
    })

    def tearDown(self):
        _restore_env()

    def _run_case(self, label, behavior, evaluator_name='p42-shape-stub'):
        tmpdir = tempfile.mkdtemp(prefix=f'gsd-phase42-abstain-{label}-')
        try:
            env = _p42_shape_env(tmpdir, evaluator_name)
            mod, ev = _load_classifier(env)
            if behavior == 'invalid':
                ev.register(evaluator_name, lambda job, t, c: mod._EVAL_INVALID, version='v1')
            elif behavior == 'timed_out':
                ev.register(evaluator_name, lambda job, t, c: mod._EVAL_TIMED_OUT, version='v1')
            elif behavior == 'abstained':
                ev.register(evaluator_name, lambda job, t, c: None, version='v1')
            elif behavior == 'rejected':
                ev.register(evaluator_name, lambda job, t, c: {
                    'inferred_role': 'x', 'estimated_hours_saved': -1.0,
                    'assumed_loaded_rate': 100.0, 'currency': 'USD',
                    'basis': 'x', 'confidence': 0.5,
                }, version='v1')
            elif behavior == 'failed':
                def _boom(job, t, c):
                    raise RuntimeError('boom')
                ev.register(evaluator_name, _boom, version='v1')
            elif behavior is None:
                pass  # unknown_evaluator: evaluator_name is deliberately never registered
            else:
                raise AssertionError(f'unknown behavior {behavior!r}')

            valid = {'agentic_job_id': 'p42-abstain-job', 'job_name': 'n',
                      'job_type': 'bug_fix', 'status': 'SUCCESS'}
            paths = mod._module_paths()
            asyncio.run(mod._attach_assessment(valid, 'user: x\nassistant: y', paths))
            return valid.get('_assessment_record')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _assert_abstention_shape(self, rec, expected_reason):
        self.assertIsNotNone(rec, f'{expected_reason}: expected a real abstention record, not None')
        self.assertEqual(rec.get('abstention_reason'), expected_reason)
        self.assertEqual(
            set(rec.keys()) & self.VALUE_KEYS, set(),
            f'{expected_reason}: value fields must be ABSENT, not null: {set(rec.keys()) & self.VALUE_KEYS}',
        )
        for key in self.IDENTITY_PROVENANCE_KEYS:
            self.assertIn(key, rec, f'{expected_reason}: missing identity/provenance key {key!r}')
        self.assertEqual(rec['execution_status'], 'SUCCESS')

    def test_unknown_evaluator_persists_abstention_record(self):
        rec = self._run_case('unknown_evaluator', None, evaluator_name='p42-shape-never-registered')
        self._assert_abstention_shape(rec, 'unknown_evaluator')

    def test_invalid_response_persists_abstention_record(self):
        rec = self._run_case('invalid', 'invalid')
        self._assert_abstention_shape(rec, 'invalid')

    def test_timed_out_sentinel_persists_abstention_record(self):
        rec = self._run_case('timed_out', 'timed_out')
        self._assert_abstention_shape(rec, 'timed_out')

    def test_raw_none_abstained_persists_abstention_record(self):
        rec = self._run_case('abstained', 'abstained')
        self._assert_abstention_shape(rec, 'abstained')

    def test_validate_assessment_rejection_persists_abstention_record(self):
        rec = self._run_case('rejected', 'rejected')
        self._assert_abstention_shape(rec, 'rejected')

    def test_generic_exception_persists_abstention_record(self):
        rec = self._run_case('failed', 'failed')
        self._assert_abstention_shape(rec, 'failed')


class PathMirrorParityTests(unittest.TestCase):
    """The only mechanism keeping the three hand-maintained path mirrors
    (common.sh, resolve-markers-dir.py, classifier.py's _Paths) honest:
    under one identical environment, including a REVENIUM_JOB_ASSESSMENTS_DIR
    override, all three must resolve to the same absolute path."""

    def tearDown(self):
        _restore_env()

    def test_three_mirrors_agree_under_override(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-phase42-parity-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            override_dir = os.path.join(tmpdir, 'custom-assessments')
            env = {**os.environ, 'HERMES_HOME': hermes_home,
                   'REVENIUM_JOB_ASSESSMENTS_DIR': override_dir}
            env.pop('REVENIUM_STATE_DIR', None)

            bash_out = subprocess.run(
                ['bash', '-c',
                 f'source "{SCRIPTS_DIR}/common.sh" >/dev/null 2>&1; printf "%s" "$JOB_ASSESSMENTS_DIR"'],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(bash_out.returncode, 0, bash_out.stderr)
            common_sh_path = bash_out.stdout.strip()

            py_out = subprocess.run(
                ['python3', str(SCRIPTS_DIR / 'resolve-markers-dir.py'),
                 'some-nonnamespaced-sid', 'job-assessments'],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(py_out.returncode, 0, py_out.stderr)
            resolver_path = py_out.stdout.strip()

            c, _ev = _load_classifier({
                'HERMES_HOME': hermes_home,
                'REVENIUM_JOB_ASSESSMENTS_DIR': override_dir,
            })
            classifier_path = str(c._module_paths().job_assessments_dir)

            self.assertEqual(common_sh_path, override_dir, 'common.sh mirror disagrees')
            self.assertEqual(resolver_path, override_dir, 'resolve-markers-dir.py mirror disagrees')
            self.assertEqual(classifier_path, override_dir, 'classifier.py mirror disagrees')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Plan 42-04 -- D-07 (schema version fail-closed), D-10 (sidecar-unavailable
# fail-closed, plus the rolling-upgrade diagnostic reason), D-09 site two
# (independent bounds re-check immediately before --outcome-value), and D-08
# (the low bound ships, not base). Shared tree builder mirrors
# SidecarTracerTests._build_tree above; kept separate (rather than promoted
# to a shared method) because these tests also need sidecar-file permission
# control and a failure-injecting shim the tracer tests never needed.
# ---------------------------------------------------------------------------

def _read_log(state_dir):
    log_path = os.path.join(state_dir, 'revenium-metering.log')
    if not os.path.exists(log_path):
        return ''
    with open(log_path) as f:
        return f.read()


def _build_fail_once_shim(shim_path, jobs_log, fail_marker):
    """A `jobs outcome` shim whose FIRST call fails (exit 1, no ledger
    write) and every call after succeeds -- lets a two-tick test genuinely
    re-run the assessment resolution on tick 2, since OUTCOME-01's ledger
    gate never fires while the job stays unreported. Every other verb
    behaves exactly like the reusable build_shim (config/guardrails/meter
    --help probes, bare `jobs --help`, and the `jobs outcome --help`
    capability probe)."""
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
        '    exit 0\n'
        '    ;;\n'
        '  jobs)\n'
        '    if [[ "$2" == "--help" ]]; then exit 0; fi\n'
        '    if [[ "$2" == "outcome" && "$3" == "--help" ]]; then\n'
        '      echo "--outcome-value string     Business outcome value"\n'
        '      echo "--outcome-currency string   Business outcome currency"\n'
        '      exit 0\n'
        '    fi\n'
        '    if [[ "$2" == "outcome" ]]; then\n'
        f'      if [[ ! -e "{fail_marker}" ]]; then\n'
        f'        touch "{fail_marker}"\n'
        '        echo "test-injected transient outcome failure, retry expected" >&2\n'
        '        exit 1\n'
        '      fi\n'
        f'      printf "%q " "$@" >> "{jobs_log}"\n'
        f'      printf "\\n"      >> "{jobs_log}"\n'
        '      exit 0\n'
        '    fi\n'
        '    exit 0\n'
        '    ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n'
    )
    with open(shim_path, 'w') as f:
        f.write(body)
    os.chmod(shim_path, 0o755)


def _build_outcome_tree(sid, job_id, sidecar_lines=None, marker_assessment=None,
                         sidecar_mode=None, fail_outcome_once=False):
    """Build a tmp HERMES_HOME tree for one job arc against the outcome
    stage's D-07/D-09/D-10 fail-closed paths. Returns
    (tmpdir, env, jobs_log, state_dir).

    sidecar_lines: list of dict records written to
        job-assessments/<job_id>.jsonl, or None to leave the sidecar file
        absent entirely (D-10's "absent" case).
    marker_assessment: when given, written as the job marker's own
        `assessment` key (C-01's demoted pointer-and-summary object) --
        present ALONGSIDE, never instead of, the sidecar.
    sidecar_mode: chmod applied to the sidecar file after writing (e.g.
        0o000 to simulate D-10's "unreadable" case). Ignored when
        sidecar_lines is None.
    fail_outcome_once: builds a shim whose FIRST `jobs outcome` call fails
        so the job stays unreported after tick 1 -- required for a genuine
        two-tick rate-limit proof (see _build_fail_once_shim).
    """
    tmpdir = tempfile.mkdtemp(prefix='gsd-phase42-failclosed-')
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

    # Pre-seed created line so the outcome stage does not defer (OUTCOME-04).
    with open(jobs_ledger, 'w') as f:
        f.write(f'JOB:{job_id}:created:1715516001.000\n')

    task_marker = {
        'muid': f'{job_id}-task', 'ts': 1715516000.5, 'sid': sid,
        'task_type': 'code_review', 'operation_type': 'CHAT',
    }
    job_marker = {
        'kind': 'job', 'ts': 1715516002.0, 'sid': sid,
        'agentic_job_id': job_id, 'job_name': 'Phase 42 Plan 04 Fail-Closed Job',
        'job_type': 'code_review', 'status': 'SUCCESS',
    }
    if marker_assessment is not None:
        job_marker['assessment'] = marker_assessment
    with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
        f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
        f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

    if sidecar_lines is not None:
        sidecar_path = os.path.join(assessments_dir, f'{job_id}.jsonl')
        with open(sidecar_path, 'w') as f:
            for rec in sidecar_lines:
                f.write(json.dumps(rec, separators=(',', ':')) + '\n')
        if sidecar_mode is not None:
            os.chmod(sidecar_path, sidecar_mode)

    shim_home = os.path.join(tmpdir, 'home')
    bin_dir = os.path.join(shim_home, '.local', 'bin')
    os.makedirs(bin_dir)
    meter_log = os.path.join(tmpdir, 'meter.log')
    jobs_log = os.path.join(tmpdir, 'jobs.log')
    shim = os.path.join(bin_dir, 'revenium')

    if fail_outcome_once:
        fail_marker = os.path.join(tmpdir, 'outcome-fail-marker')
        _build_fail_once_shim(shim, jobs_log, fail_marker)
    else:
        build_shim(shim)

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
    return tmpdir, env, jobs_log, state_dir


class FailClosedTests(unittest.TestCase):
    """Phase 42 Plan 04 -- D-07 (unrecognized schema version) and D-10
    (unavailable sidecar) both fail closed: the outcome stage reports
    status-only, never falls back to the marker's 9-key `assessment`
    summary, and logs exactly once per (outcome_id, reason) through the
    SAME OUTCOME_WARN_FLAGS_DIR sentinel the deferred/wedged block already
    uses (T-42-04-02, T-42-04-03, T-42-04-04, T-42-04-05)."""

    def test_unrecognized_schema_version_ships_no_value_and_logs_once(self):
        sid, job_id = 'p42-fc-sid-001', 'p42-fc-job-001'
        record = _tracer_assessment_record(job_id, assessment_schema_version=99)
        tmpdir, env, jobs_log, state_dir = _build_outcome_tree(
            sid, job_id, sidecar_lines=[record],
        )
        try:
            rc, invocations, out = _run_hermes_report(env, jobs_log)
            self.assertEqual(rc, 0, f'hermes-report.sh failed: {out}')
            argv = _outcome_argv(invocations)
            self.assertIsNotNone(argv, f'expected a jobs outcome invocation: {invocations}')
            self.assertNotIn('--outcome-value', argv)
            self.assertNotIn('--outcome-currency', argv)
            meta = json.loads(_metadata_of(argv))
            self.assertNotIn('evidence_class', meta)
            self.assertNotIn('value_low', meta)
            self.assertNotIn('assessment_schema_version', meta)
            log_content = _read_log(state_dir)
            self.assertEqual(
                log_content.count('schema unrecognized'), 1,
                f'expected exactly one schema_unrecognized warn:\n{log_content}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_recognized_current_version_still_values_normally(self):
        sid, job_id = 'p42-fc-sid-002', 'p42-fc-job-002'
        record = _tracer_assessment_record(job_id)  # assessment_schema_version: 1
        tmpdir, env, jobs_log, state_dir = _build_outcome_tree(
            sid, job_id, sidecar_lines=[record],
        )
        try:
            rc, invocations, out = _run_hermes_report(env, jobs_log)
            self.assertEqual(rc, 0, f'hermes-report.sh failed: {out}')
            argv = _outcome_argv(invocations)
            self.assertIsNotNone(argv, f'expected a jobs outcome invocation: {invocations}')
            self.assertEqual(argv[argv.index('--outcome-value') + 1], '525.0')
            self.assertEqual(argv[argv.index('--outcome-currency') + 1], 'USD')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_missing_sidecar_ships_no_value_and_logs_sidecar_unavailable(self):
        sid, job_id = 'p42-fc-sid-003', 'p42-fc-job-003'
        tmpdir, env, jobs_log, state_dir = _build_outcome_tree(
            sid, job_id, sidecar_lines=None,
        )
        try:
            rc, invocations, out = _run_hermes_report(env, jobs_log)
            self.assertEqual(rc, 0, f'hermes-report.sh failed: {out}')
            argv = _outcome_argv(invocations)
            self.assertIsNotNone(argv, f'expected a jobs outcome invocation: {invocations}')
            self.assertNotIn('--outcome-value', argv)
            self.assertNotIn('--outcome-currency', argv)
            log_content = _read_log(state_dir)
            self.assertEqual(
                log_content.count('sidecar unavailable, reporting'), 1, log_content,
            )
            self.assertNotIn('rolling-upgrade window', log_content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_unreadable_sidecar_ships_no_value_and_logs_sidecar_unavailable(self):
        sid, job_id = 'p42-fc-sid-004', 'p42-fc-job-004'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir = _build_outcome_tree(
            sid, job_id, sidecar_lines=[record], sidecar_mode=0o000,
        )
        try:
            rc, invocations, out = _run_hermes_report(env, jobs_log)
            self.assertEqual(rc, 0, f'hermes-report.sh failed: {out}')
            argv = _outcome_argv(invocations)
            self.assertIsNotNone(argv, f'expected a jobs outcome invocation: {invocations}')
            self.assertNotIn('--outcome-value', argv)
            self.assertNotIn('--outcome-currency', argv)
            log_content = _read_log(state_dir)
            self.assertEqual(
                log_content.count('sidecar unavailable, reporting'), 1, log_content,
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_oversized_line_ships_no_value_and_logs_sidecar_unavailable(self):
        sid, job_id = 'p42-fc-sid-005', 'p42-fc-job-005'
        huge = _tracer_assessment_record(job_id, padding='z' * 9000)
        tmpdir, env, jobs_log, state_dir = _build_outcome_tree(
            sid, job_id, sidecar_lines=[huge],
        )
        try:
            rc, invocations, out = _run_hermes_report(env, jobs_log)
            self.assertEqual(rc, 0, f'hermes-report.sh failed: {out}')
            argv = _outcome_argv(invocations)
            self.assertIsNotNone(argv, f'expected a jobs outcome invocation: {invocations}')
            self.assertNotIn('--outcome-value', argv)
            self.assertNotIn('--outcome-currency', argv)
            log_content = _read_log(state_dir)
            self.assertEqual(
                log_content.count('sidecar unavailable, reporting'), 1, log_content,
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_missing_sidecar_beside_marker_assessment_logs_diagnostic_reason(self):
        sid, job_id = 'p42-fc-sid-006', 'p42-fc-job-006'
        marker_assessment = {
            'estimated_value': 999.0, 'currency': 'USD', 'basis': 'x',
            'assumptions': {'inferred_role': 'x', 'estimated_hours_saved': 1.0,
                             'assumed_loaded_rate': 999.0},
            'confidence': 0.9, 'evaluator': 'llm', 'evaluator_version': 'v1',
            'evidence_class': 'MODEL_ESTIMATED_DEMO',
        }
        tmpdir, env, jobs_log, state_dir = _build_outcome_tree(
            sid, job_id, sidecar_lines=None, marker_assessment=marker_assessment,
        )
        try:
            rc, invocations, out = _run_hermes_report(env, jobs_log)
            self.assertEqual(rc, 0, f'hermes-report.sh failed: {out}')
            argv = _outcome_argv(invocations)
            self.assertIsNotNone(argv, f'expected a jobs outcome invocation: {invocations}')
            self.assertNotIn('--outcome-value', argv)
            self.assertNotIn('--outcome-currency', argv)
            log_content = _read_log(state_dir)
            self.assertEqual(log_content.count('rolling-upgrade window'), 1, log_content)
            # Distinct from the generic reason -- must not ALSO log the
            # generic message for the same job.
            self.assertEqual(log_content.count('sidecar unavailable, reporting'), 0, log_content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_warn_fires_once_across_two_ticks(self):
        """T-42-04-04: the deferred/wedged rate-limit pattern reused -- the
        SAME unavailable-sidecar condition, re-evaluated every tick because
        the job's own outcome report fails on tick 1 (so OUTCOME-01 never
        ledger-gates it out), warns once on tick 1 and stays silent on
        tick 2. The rate limit is the assertion, not a comment."""
        sid, job_id = 'p42-fc-sid-007', 'p42-fc-job-007'
        tmpdir, env, jobs_log, state_dir = _build_outcome_tree(
            sid, job_id, sidecar_lines=None, fail_outcome_once=True,
        )
        try:
            rc1, _inv1, out1 = _run_hermes_report(env, jobs_log)
            self.assertEqual(rc1, 0, f'tick 1 failed: {out1}')
            log_after_tick1 = _read_log(state_dir)
            self.assertEqual(
                log_after_tick1.count('sidecar unavailable, reporting'), 1, log_after_tick1,
            )

            rc2, _inv2, out2 = _run_hermes_report(env, jobs_log)
            self.assertEqual(rc2, 0, f'tick 2 failed: {out2}')
            log_after_tick2 = _read_log(state_dir)
            self.assertEqual(
                log_after_tick2.count('sidecar unavailable, reporting'), 1,
                f'warn must not repeat on tick 2:\n{log_after_tick2}',
            )

            # The sentinel flag is the ENTIRE mechanism preventing tick 2
            # from re-warning -- assert it exists, not just the log count.
            flag_dir = os.path.join(state_dir, 'markers', '.outcome-warn')
            flags = os.listdir(flag_dir) if os.path.isdir(flag_dir) else []
            matching = [
                f for f in flags
                if f.startswith(job_id) and f.endswith('__sidecar_unavailable.flag')
            ]
            self.assertEqual(len(matching), 1, f'expected one sentinel flag, found: {flags}')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class SecondSiteBoundsTests(unittest.TestCase):
    """Phase 42 Plan 04 -- D-09 site two: an INDEPENDENT re-check of the
    three bounds immediately before --outcome-value is constructed (same
    shape and reasoning as C-02's evidence_class allow-list), and D-08:
    the value that ships on the wire is the LOW bound, never base
    (T-42-04-01)."""

    def test_reversed_bounds_ship_no_value_but_outcome_still_reports(self):
        sid, job_id = 'p42-b2-sid-001', 'p42-b2-job-001'
        record = _tracer_assessment_record(
            job_id, value_low=600.0, value_base=500.0, value_high=700.0,
        )
        tmpdir, env, jobs_log, state_dir = _build_outcome_tree(
            sid, job_id, sidecar_lines=[record],
        )
        try:
            rc, invocations, out = _run_hermes_report(env, jobs_log)
            self.assertEqual(rc, 0, f'hermes-report.sh failed: {out}')
            argv = _outcome_argv(invocations)
            self.assertIsNotNone(argv, f'expected a jobs outcome invocation: {invocations}')
            self.assertEqual(argv[argv.index('--result') + 1], 'SUCCESS')
            self.assertNotIn('--outcome-value', argv)
            self.assertNotIn('--outcome-currency', argv)
            log_content = _read_log(state_dir)
            self.assertIn('bounds reversed', log_content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_negative_low_bound_ships_no_value(self):
        sid, job_id = 'p42-b2-sid-002', 'p42-b2-job-002'
        record = _tracer_assessment_record(
            job_id, value_low=-10.0, value_base=100.0, value_high=200.0,
        )
        tmpdir, env, jobs_log, state_dir = _build_outcome_tree(
            sid, job_id, sidecar_lines=[record],
        )
        try:
            rc, invocations, out = _run_hermes_report(env, jobs_log)
            self.assertEqual(rc, 0, f'hermes-report.sh failed: {out}')
            argv = _outcome_argv(invocations)
            self.assertIsNotNone(argv, f'expected a jobs outcome invocation: {invocations}')
            self.assertNotIn('--outcome-value', argv)
            self.assertNotIn('--outcome-currency', argv)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_non_numeric_bound_ships_no_value(self):
        sid, job_id = 'p42-b2-sid-003', 'p42-b2-job-003'
        record = _tracer_assessment_record(
            job_id, value_low=100.0, value_base='not-a-number', value_high=200.0,
        )
        tmpdir, env, jobs_log, state_dir = _build_outcome_tree(
            sid, job_id, sidecar_lines=[record],
        )
        try:
            rc, invocations, out = _run_hermes_report(env, jobs_log)
            self.assertEqual(rc, 0, f'hermes-report.sh failed: {out}')
            argv = _outcome_argv(invocations)
            self.assertIsNotNone(argv, f'expected a jobs outcome invocation: {invocations}')
            self.assertNotIn('--outcome-value', argv)
            self.assertNotIn('--outcome-currency', argv)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_well_formed_bounds_ship_value_low_and_full_range_in_metadata(self):
        sid, job_id = 'p42-b2-sid-004', 'p42-b2-job-004'
        record = _tracer_assessment_record(
            job_id, value_low=446.25, value_base=525.0, value_high=603.75,
        )
        tmpdir, env, jobs_log, state_dir = _build_outcome_tree(
            sid, job_id, sidecar_lines=[record],
        )
        try:
            rc, invocations, out = _run_hermes_report(env, jobs_log)
            self.assertEqual(rc, 0, f'hermes-report.sh failed: {out}')
            argv = _outcome_argv(invocations)
            self.assertIsNotNone(argv, f'expected a jobs outcome invocation: {invocations}')
            self.assertEqual(argv[argv.index('--outcome-value') + 1], '446.25')
            self.assertEqual(argv[argv.index('--outcome-currency') + 1], 'USD')
            meta = json.loads(_metadata_of(argv))
            self.assertEqual(meta.get('value_low'), 446.25)
            self.assertEqual(meta.get('value_base'), 525.0)
            self.assertEqual(meta.get('value_high'), 603.75)
            self.assertEqual(meta.get('bounds_source'), 'derived')
            self.assertEqual(meta.get('assessment_schema_version'), 1)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_shipped_value_is_never_value_base(self):
        """D-08's executable proof: a later refactor that quietly reverts
        to shipping the base estimate must fail this test loudly."""
        sid, job_id = 'p42-b2-sid-005', 'p42-b2-job-005'
        record = _tracer_assessment_record(
            job_id, value_low=446.25, value_base=525.0, value_high=603.75,
        )
        tmpdir, env, jobs_log, state_dir = _build_outcome_tree(
            sid, job_id, sidecar_lines=[record],
        )
        try:
            rc, invocations, out = _run_hermes_report(env, jobs_log)
            self.assertEqual(rc, 0, f'hermes-report.sh failed: {out}')
            argv = _outcome_argv(invocations)
            self.assertIsNotNone(argv, f'expected a jobs outcome invocation: {invocations}')
            shipped = argv[argv.index('--outcome-value') + 1]
            self.assertEqual(shipped, '446.25')
            self.assertNotEqual(shipped, '525.0')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Plan 06 — the operator correction script itself: correct-assessment.sh
# appends locally, appends to the jobs ledger with a disjoint prefix, and
# ships to Revenium via `jobs outcome-update` when the CLI supports it.
#
# Requirements covered:
#   EGV-09 — the correction appends; the original assessment and the full
#            correction history are preserved, never destructively replaced,
#            and the newest correction is what the reader resolves.
# ---------------------------------------------------------------------------

CORRECT_ASSESSMENT_SH = SCRIPTS_DIR / 'correct-assessment.sh'
PRUNE_MARKERS_SH = SCRIPTS_DIR / 'prune-markers.sh'


def _build_correction_shim(shim_path, outcome_update_capable=True,
                            config_show_fails=False):
    """revenium shim for the correction-path test suite.

    Extends build_shim's `jobs)` branch with a THIRD --help probe --
    `jobs outcome-update --help` (D-04's OUTCOME_UPDATE_CLI_CAPABLE probe,
    resolved by correct-assessment.sh) -- alongside the existing `jobs
    outcome --help` (hermes-report.sh's CR-01 probe) and bare `meter
    completion --help` (JOBS_CLI_CAPABLE). All three probes are answered
    BEFORE the generic JOBS_LOG capture, so none of them is ever logged as
    a real invocation -- matching build_shim's own no-shift design.

    outcome_update_capable=False omits --reason from the outcome-update
    probe's help text, modelling the older-CLI D-04 fail-loud branch.

    config_show_fails=True (WR-03) makes `revenium config show` -- the
    call inside resolve_team_id's pipeline, a DIFFERENT call from the
    `jobs outcome-update --help` probe above -- exit non-zero with output
    on stderr only, modelling a transient auth/network failure that lands
    strictly AFTER the local correction and ledger line are already saved.
    """
    if outcome_update_capable:
        outcome_update_help_lines = (
            '      echo "--reason string    Reason for the update"\n'
        )
    else:
        outcome_update_help_lines = ''
    if config_show_fails:
        config_branch = (
            '  config) echo "revenium: connection error" >&2; exit 3 ;;\n'
        )
    else:
        config_branch = '  config) exit 0 ;;\n'
    body = (
        '#!/usr/bin/env bash\n'
        'case "$1" in\n'
        + config_branch +
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
        + outcome_update_help_lines +
        '      exit 0\n'
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


def _build_correction_tree(sid, job_id, sidecar_lines=None, seed_outcome_line=False,
                            outcome_update_capable=True, config_show_fails=False):
    """Build a tmp HERMES_HOME tree for the correction-path test suite.

    Mirrors _build_outcome_tree's shape (state.db, jobs ledger seeded with a
    `created` line, marker pair, optional sidecar records) but uses
    _build_correction_shim so BOTH `bash correct-assessment.sh` and `bash
    hermes-report.sh` can be run as real subprocesses against the SAME
    state dir -- required by the last-match-wins and ordinary-path-stays-
    gated tests, which exercise both scripts in sequence.

    Returns (tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger).
    """
    tmpdir = tempfile.mkdtemp(prefix='gsd-phase42-correction-')
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
        'agentic_job_id': job_id, 'job_name': 'Phase 42 Plan 06 Correction Job',
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
    _build_correction_shim(
        shim, outcome_update_capable=outcome_update_capable,
        config_show_fails=config_show_fails,
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


def _run_correct_assessment(env, args):
    """Run correct-assessment.sh as a REAL subprocess; return
    (returncode, stdout, stderr)."""
    result = subprocess.run(
        ['bash', str(CORRECT_ASSESSMENT_SH)] + list(args),
        env=env, capture_output=True, text=True, timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


def _read_sidecar_lines(sidecar_path):
    if not os.path.exists(sidecar_path):
        return []
    with open(sidecar_path, 'rb') as f:
        return [line for line in f.read().split(b'\n') if line]


def _jobs_log_invocations(jobs_log):
    if not os.path.exists(jobs_log):
        return []
    invocations = []
    with open(jobs_log) as f:
        for line in f:
            line = line.rstrip('\n')
            if line:
                invocations.append(shlex.split(line))
    return invocations


def _build_toctou_race_shim(shim_path, entered_file, release_file):
    """WR-02 (42-REVIEW.md) race-reproduction shim.

    correct-assessment.sh's Step 4 (`supports_flag "jobs outcome-update"
    "--reason"`) calls `revenium jobs outcome-update --help` -- the LAST
    thing the script does before Step 5 opens the sidecar file. Blocking
    right there gives the test a deterministic hook between Step 1+2's
    unlocked D-14 existence check (far above) and Step 5's append: touch
    `entered_file` so the test knows the script is paused at that exact
    point, then poll for `release_file` before answering the probe. The
    test deletes the sidecar in between -- a real interleaving, not a
    pre-script deletion (which would only exercise the ALREADY-WORKING
    D-14 refusal for a record that was never found in the first place).

    The wait is bounded (10s) so a broken test fails fast instead of
    hanging the suite if the release signal never arrives.
    """
    body = (
        '#!/usr/bin/env bash\n'
        'case "$1" in\n'
        '  config) exit 0 ;;\n'
        '  guardrails) exit 0 ;;\n'
        '  jobs)\n'
        '    if [[ "$2" == "outcome-update" && "$3" == "--help" ]]; then\n'
        f'      : > "{entered_file}"\n'
        '      for _ in $(seq 1 200); do\n'
        f'        [[ -e "{release_file}" ]] && break\n'
        '        sleep 0.05\n'
        '      done\n'
        '      echo "--reason string    Reason for the update"\n'
        '      exit 0\n'
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


def _sidecar_component_for(job_id):
    """Run the REAL `_sidecar_filename_component` transform, extracted
    verbatim from correct-assessment.sh's own source (not retyped) --
    same extraction technique
    `test_path_traversal_job_id_creates_no_file_outside_assessments_dir`
    uses. Lets a fixture using a punctuated job id name its sidecar file
    exactly as the shipped script would resolve it, without hand-
    duplicating the transform and risking it silently drifting from the
    source it is meant to mirror."""
    script_text = CORRECT_ASSESSMENT_SH.read_text()
    func_src = script_text[
        script_text.index('def _clean(v):'):
        script_text.index('component = _sidecar_filename_component(raw_job_id)')
    ]
    probe = (
        'import re, sys\n' + func_src +
        '\nprint(_sidecar_filename_component(sys.argv[1]))\n'
    )
    result = subprocess.run(
        ['python3', '-c', probe, job_id],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise AssertionError(
            f'_sidecar_filename_component probe failed for {job_id!r}: '
            f'{result.stderr}'
        )
    return result.stdout.strip()


class CorrectionAppendTests(unittest.TestCase):
    """Phase 42 Plan 06 -- EGV-09/D-01/D-02/D-03/D-04/D-14: correct-assessment.sh
    appends a `kind:"correction"` sidecar line, never destructively rewrites
    the original or any earlier correction, appends a ledger line proven
    disjoint from both outcome-stage grep gates, validates operator input
    before any write, and fails loudly (never silently) when the CLI
    cannot ship the correction or when the target record is absent."""

    def test_original_byte_identical_after_one_correction(self):
        sid, job_id = 'p42c-sid-001', 'p42c-job-001'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(sid, job_id, sidecar_lines=[record])
        )
        try:
            lines_before = _read_sidecar_lines(sidecar_path)
            self.assertEqual(len(lines_before), 1)

            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '400', '--currency', 'USD',
                '--reason', 'first correction',
            ])
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')

            lines_after = _read_sidecar_lines(sidecar_path)
            self.assertEqual(len(lines_after), 2)
            self.assertEqual(
                lines_after[0], lines_before[0],
                'EGV-09: the original job_assessment line must be '
                'byte-identical after a correction -- a correction must '
                'append, never rewrite.',
            )
            second = json.loads(lines_after[1])
            self.assertEqual(second['kind'], 'correction')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_original_and_first_correction_byte_identical_after_second_correction(self):
        sid, job_id = 'p42c-sid-002', 'p42c-job-002'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(sid, job_id, sidecar_lines=[record])
        )
        try:
            rc1, out1, err1 = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '400', '--currency', 'USD',
                '--reason', 'first correction',
            ])
            self.assertEqual(rc1, 0, f'stdout={out1!r} stderr={err1!r}')
            lines_after_first = _read_sidecar_lines(sidecar_path)
            self.assertEqual(len(lines_after_first), 2)

            rc2, out2, err2 = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '300', '--currency', 'USD',
                '--reason', 'second correction',
            ])
            self.assertEqual(rc2, 0, f'stdout={out2!r} stderr={err2!r}')
            lines_after_second = _read_sidecar_lines(sidecar_path)
            self.assertEqual(len(lines_after_second), 3)

            self.assertEqual(
                lines_after_second[0], lines_after_first[0],
                'EGV-09: the original must stay byte-identical across TWO '
                'corrections, not just one.',
            )
            self.assertEqual(
                lines_after_second[1], lines_after_first[1],
                'EGV-09: the FIRST correction must also stay byte-identical '
                'after a second correction is filed -- the complete '
                'history is preserved, not just the original.',
            )
            third = json.loads(lines_after_second[2])
            self.assertEqual(third['kind'], 'correction')
            self.assertEqual(third['sequence'], 2)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_correction_line_shape_and_bare_value_equal_bounds(self):
        sid, job_id = 'p42c-sid-003', 'p42c-job-003'
        record = _tracer_assessment_record(
            job_id, value_low=446.25, value_base=525.0, value_high=603.75,
        )
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(sid, job_id, sidecar_lines=[record])
        )
        try:
            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '400', '--currency', 'gbp',
                '--reason', 'shape check',
            ])
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')

            lines = _read_sidecar_lines(sidecar_path)
            correction = json.loads(lines[1])
            self.assertEqual(correction['kind'], 'correction')
            self.assertEqual(correction['sequence'], 1)
            self.assertEqual(correction['assessment_id'], f'{job_id}:1')
            self.assertEqual(correction['agentic_job_id'], job_id)
            self.assertEqual(correction['prior_value_low'], 446.25)
            self.assertEqual(correction['prior_value_base'], 525.0)
            self.assertEqual(correction['prior_value_high'], 603.75)
            self.assertEqual(correction['prior_currency'], 'USD')
            # A bare --value with no range flags produces equal bounds (D-03).
            self.assertEqual(correction['value_low'], 400.0)
            self.assertEqual(correction['value_base'], 400.0)
            self.assertEqual(correction['value_high'], 400.0)
            self.assertEqual(correction['currency'], 'GBP')
            self.assertEqual(correction['reason'], 'shape check')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_original_stays_readable_by_index_and_assessment_id_after_three_corrections(self):
        sid, job_id = 'p42c-sid-004', 'p42c-job-004'
        record = _tracer_assessment_record(
            job_id, value_low=446.25, value_base=525.0, value_high=603.75,
        )
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(sid, job_id, sidecar_lines=[record])
        )
        try:
            for i, value in enumerate((400, 300, 200), start=1):
                rc, out, err = _run_correct_assessment(env, [
                    '--job-id', job_id, '--value', str(value),
                    '--currency', 'USD', '--reason', f'correction {i}',
                ])
                self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')

            lines = _read_sidecar_lines(sidecar_path)
            self.assertEqual(len(lines), 4)

            by_index = json.loads(lines[0])
            self.assertEqual(by_index['kind'], 'job_assessment')
            self.assertEqual(by_index['assessment_id'], f'{job_id}:0')
            self.assertEqual(by_index['value_low'], 446.25)
            self.assertEqual(by_index['value_base'], 525.0)
            self.assertEqual(by_index['value_high'], 603.75)
            self.assertEqual(by_index['currency'], 'USD')
            self.assertEqual(by_index['evaluator'], 'llm')
            self.assertEqual(by_index['evaluator_version'], 'v1')
            self.assertEqual(by_index['confidence'], 0.8)

            by_assessment_id = {
                json.loads(line)['assessment_id']: json.loads(line)
                for line in lines
            }
            self.assertEqual(by_assessment_id[f'{job_id}:0'], by_index)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_last_match_wins_ships_newest_correction_low_bound(self):
        sid, job_id = 'p42c-sid-005', 'p42c-job-005'
        record = _tracer_assessment_record(
            job_id, value_low=446.25, value_base=525.0, value_high=603.75,
        )
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(sid, job_id, sidecar_lines=[record])
        )
        try:
            rc1, out1, err1 = _run_correct_assessment(env, [
                '--job-id', job_id, '--value-low', '100', '--value', '110',
                '--value-high', '120', '--currency', 'USD',
                '--reason', 'first',
            ])
            self.assertEqual(rc1, 0, f'stdout={out1!r} stderr={err1!r}')
            rc2, out2, err2 = _run_correct_assessment(env, [
                '--job-id', job_id, '--value-low', '50', '--value', '60',
                '--value-high', '70', '--currency', 'USD',
                '--reason', 'second, newest',
            ])
            self.assertEqual(rc2, 0, f'stdout={out2!r} stderr={err2!r}')

            rc, invocations, out = _run_hermes_report(env, jobs_log)
            self.assertEqual(rc, 0, f'hermes-report.sh failed: {out}')
            argv = _outcome_argv(invocations)
            self.assertIsNotNone(argv, f'expected a jobs outcome invocation: {invocations}')
            self.assertEqual(
                argv[argv.index('--outcome-value') + 1], '50.0',
                'EGV-09: the reader must resolve the NEWEST correction '
                '(low bound 50.0), not the original (446.25) or the first '
                'correction (100.0) -- scan-to-end, deliberate.',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_ledger_line_written_and_disjoint_from_both_gates(self):
        sid, job_id = 'p42c-sid-006', 'p42c-job-006'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(sid, job_id, sidecar_lines=[record])
        )
        try:
            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '400', '--currency', 'USD',
                '--reason', 'ledger disjointness',
            ])
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')

            with open(jobs_ledger) as f:
                ledger_content = f.read()
            self.assertIn(f'JOB:{job_id}:correction:1:', ledger_content)

            script_text = HERMES_REPORT_SH.read_text()
            outcome_01_pattern = _extract_grep_pattern(
                script_text, OUTCOME_01_GATE_COMMENT, job_id)
            outcome_04_pattern = _extract_grep_pattern(
                script_text, OUTCOME_04_GATE_COMMENT, job_id)
            self.assertIsNotNone(outcome_01_pattern)
            self.assertIsNotNone(outcome_04_pattern)

            outcome_01_matches = _grep_matching_lines(
                outcome_01_pattern, Path(jobs_ledger))
            self.assertEqual(
                outcome_01_matches, [],
                'EGV-09/D-01: OUTCOME-01 must not match the REAL writer\'s '
                f'correction line, got {outcome_01_matches!r}',
            )
            outcome_04_matches = _grep_matching_lines(
                outcome_04_pattern, Path(jobs_ledger))
            self.assertEqual(
                len(outcome_04_matches), 1,
                'EGV-09/D-01: OUTCOME-04 must match only the pre-seeded '
                f'created line, never the correction line, got {outcome_04_matches!r}',
            )
            self.assertTrue(outcome_04_matches[0].startswith(f'JOB:{job_id}:created:'))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_correction_ledger_line_shares_id_with_ordinary_path_for_punctuated_job_id(self):
        """WR-01 (42-REVIEW.md): the ledger-line id must track the ordinary
        path's narrow five-character transform, not the fuller filename-safe
        COMPONENT.

        Uses a job id carrying an apostrophe and parentheses -- punctuation
        outside hermes-report.sh's `_bad_chars` list (`:`, ` `, tab, `\\n`,
        `\\r`) but inside `_sidecar_filename_component`'s A-Za-z0-9._-
        filename-safety pass, so the two transforms disagree by construction.
        Before the WR-01 fix, the correction line's `<id>` substring diverged
        from the ordinary path's `created:` line for this same job,
        silently breaking a `^JOB:<id>:` grep for the job's full history.
        """
        sid = 'p42c-sid-012'
        job_id = "p42c-job-012's(x)"

        tmpdir = tempfile.mkdtemp(prefix='gsd-phase42-correction-punct-')
        try:
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

            # The ordinary path's `created:` line keeps punctuation
            # verbatim -- job_id has no colon/space/tab/newline/CR, so
            # hermes-report.sh's narrow transform is a no-op, matching
            # clean_id/outcome_id there exactly.
            with open(jobs_ledger, 'w') as f:
                f.write(f'JOB:{job_id}:created:1715516001.000\n')

            # The sidecar FILENAME must use the filename-safe COMPONENT
            # transform -- extracted from the shipped script (see
            # _sidecar_component_for), not retyped, so this fixture stays
            # correct even if the transform's exact substitution changes.
            component = _sidecar_component_for(job_id)
            sidecar_path = os.path.join(assessments_dir, f'{component}.jsonl')
            record = _tracer_assessment_record(job_id)
            with open(sidecar_path, 'w') as f:
                f.write(json.dumps(record, separators=(',', ':')) + '\n')

            task_marker = {
                'muid': f'{component}-task', 'ts': 1715516000.5, 'sid': sid,
                'task_type': 'code_review', 'operation_type': 'CHAT',
            }
            job_marker = {
                'kind': 'job', 'ts': 1715516002.0, 'sid': sid,
                'agentic_job_id': job_id, 'job_name': 'Punctuated job id',
                'job_type': 'code_review', 'status': 'SUCCESS',
            }
            with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
                f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
                f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir, 'meter.log')
            jobs_log = os.path.join(tmpdir, 'jobs.log')
            shim = os.path.join(bin_dir, 'revenium')
            _build_correction_shim(shim)

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

            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '400', '--currency', 'USD',
                '--reason', 'punctuated job id correlation',
            ])
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')

            with open(jobs_ledger) as f:
                ledger_lines = [line.rstrip('\n') for line in f if line.strip()]

            created_lines = [l for l in ledger_lines if ':created:' in l]
            correction_lines = [l for l in ledger_lines if ':correction:' in l]
            self.assertEqual(len(created_lines), 1, ledger_lines)
            self.assertEqual(len(correction_lines), 1, ledger_lines)

            created_id = created_lines[0].split(':', 2)[1]
            correction_id = correction_lines[0].split(':', 2)[1]
            self.assertEqual(
                created_id, job_id,
                'sanity: the pre-seeded created: line must carry the raw '
                f'punctuated job id verbatim, got {created_id!r}',
            )
            self.assertEqual(
                correction_id, created_id,
                'WR-01: the correction: line must carry the SAME <id> '
                f'substring as the created: line for the same job -- got '
                f'correction id {correction_id!r} vs created id '
                f'{created_id!r}',
            )

            # The full-history grep itself, through a real ledger file --
            # what an operator auditing this job would actually run.
            full_history = _grep_matching_lines(
                f'^JOB:{job_id}:', Path(jobs_ledger))
            self.assertEqual(
                len(full_history), 2,
                'WR-01: `^JOB:<id>:` must return BOTH the created: and '
                f'correction: lines for a punctuated job id, got '
                f'{full_history!r}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_ordinary_path_stays_gated_after_correction(self):
        """Asserts the ordinary per-tick path remains gated after a
        correction is filed -- a correction must never unblock or
        re-trigger the ordinary `jobs outcome` report. This does NOT assert
        (and must never be read as asserting) that a job id can be reported
        twice through job_outcome_queue -- 42-RESEARCH.md's Pitfall 4 names
        exactly this drift as the regression to avoid."""
        sid, job_id = 'p42c-sid-007', 'p42c-job-007'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(
                sid, job_id, sidecar_lines=[record], seed_outcome_line=True,
            )
        )
        try:
            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '400', '--currency', 'USD',
                '--reason', 'must not unblock the ordinary path',
            ])
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')

            rc, invocations, out = _run_hermes_report(env, jobs_log)
            self.assertEqual(rc, 0, f'hermes-report.sh failed: {out}')
            outcome_invocations = [
                argv for argv in invocations
                if len(argv) >= 2 and argv[0] == 'jobs' and argv[1] == 'outcome'
            ]
            self.assertEqual(
                outcome_invocations, [],
                'EGV-09/D-01: the ordinary path must stay gated by '
                'OUTCOME-01 after a correction -- a correction must never '
                f'cause a further jobs outcome call, got {outcome_invocations!r}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_d04_fail_loud_saves_locally_when_cli_lacks_outcome_update(self):
        sid, job_id = 'p42c-sid-008', 'p42c-job-008'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(
                sid, job_id, sidecar_lines=[record], outcome_update_capable=False,
            )
        )
        try:
            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '400', '--currency', 'USD',
                '--reason', 'older CLI',
            ])
            self.assertNotEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertIn('does not support', err)

            lines = _read_sidecar_lines(sidecar_path)
            self.assertEqual(
                len(lines), 2,
                'D-04: the local correction must be saved even though the '
                f'CLI could not ship it, got {len(lines)} line(s)',
            )
            with open(jobs_ledger) as f:
                ledger_content = f.read()
            self.assertIn(f'JOB:{job_id}:correction:1:', ledger_content)

            invocations = _jobs_log_invocations(jobs_log)
            update_invocations = [
                argv for argv in invocations
                if len(argv) >= 2 and argv[0] == 'jobs' and argv[1] == 'outcome-update'
            ]
            self.assertEqual(
                update_invocations, [],
                'D-04: an unsupported CLI must never actually be invoked '
                f'for outcome-update, got {update_invocations!r}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_d14_refusal_for_absent_sidecar_record(self):
        sid, job_id = 'p42c-sid-009', 'p42c-job-009'
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(sid, job_id, sidecar_lines=None)
        )
        try:
            # _build_correction_tree always pre-seeds a `created` line for
            # the ORDINARY per-tick path's OUTCOME-04 gate -- capture it so
            # the assertion below is "no NEW (correction) line appeared",
            # not "the ledger file must not exist" (it already does).
            ledger_before = Path(jobs_ledger).read_text()

            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '400', '--currency', 'USD',
                '--reason', 'no record exists',
            ])
            self.assertNotEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertIn('D-14', err)
            self.assertFalse(
                os.path.exists(sidecar_path),
                'D-14: no file may be created for an absent record',
            )
            self.assertEqual(
                Path(jobs_ledger).read_text(), ledger_before,
                'D-14: no ledger line may be written for a refused correction',
            )
            invocations = _jobs_log_invocations(jobs_log)
            self.assertEqual(
                invocations, [],
                f'D-14: no CLI invocation at all, got {invocations!r}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_input_validation_rejects_bad_values(self):
        sid, job_id = 'p42c-sid-010', 'p42c-job-010'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(sid, job_id, sidecar_lines=[record])
        )
        try:
            ledger_before = Path(jobs_ledger).read_text()
            cases = {
                'non-numeric': ['--value', 'not-a-number'],
                'negative': ['--value', '-10'],
                'reversed-bounds': [
                    '--value', '500', '--value-low', '600', '--value-high', '700',
                ],
            }
            for label, value_args in cases.items():
                with self.subTest(label):
                    rc, out, err = _run_correct_assessment(env, [
                        '--job-id', job_id, *value_args,
                        '--currency', 'USD', '--reason', f'bad input: {label}',
                    ])
                    self.assertEqual(rc, 2, f'stdout={out!r} stderr={err!r}')
                    self.assertIn('Invalid input', err)

            # No write of any kind occurred across any of the rejected cases.
            lines = _read_sidecar_lines(sidecar_path)
            self.assertEqual(len(lines), 1, 'no correction line may be written on invalid input')
            self.assertEqual(
                Path(jobs_ledger).read_text(), ledger_before,
                'no ledger line may be written on invalid input',
            )
            self.assertEqual(_jobs_log_invocations(jobs_log), [], 'no CLI invocation on invalid input')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_path_traversal_job_id_creates_no_file_outside_assessments_dir(self):
        sid, job_id = 'p42c-sid-011', 'p42c-job-011'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(sid, job_id, sidecar_lines=[record])
        )
        try:
            assessments_dir = os.path.dirname(sidecar_path)
            files_before = set(os.listdir(assessments_dir))
            outside_target = os.path.join(tmpdir, 'evil.jsonl')

            rc, out, err = _run_correct_assessment(env, [
                '--job-id', '../../evil', '--value', '1',
                '--currency', 'USD', '--reason', 'traversal attempt',
            ])
            self.assertNotEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertIn('D-14', err)

            self.assertFalse(
                os.path.exists(outside_target),
                'the filename-safety pass must prevent escaping the '
                'assessments directory via a job id with a path separator '
                'and a parent-directory reference',
            )
            files_after = set(os.listdir(assessments_dir))
            self.assertEqual(
                files_before, files_after,
                f'no new file may appear in the assessments directory: {files_after - files_before}',
            )

            # D-14's refusal (above) makes no escaped file observable at
            # the process level EITHER before or after a broken sanitizer,
            # because this script only ever appends to an EXISTING match --
            # it never creates a brand-new sidecar file. So the mutation
            # this task requires (removing the filename-safety pass) must
            # be caught by exercising the SHIPPED transform directly, not
            # by the file-creation assertions above alone. Extracted
            # verbatim from correct-assessment.sh's own source (not
            # retyped), so a mutation to the real file is what this
            # assertion actually exercises.
            script_text = CORRECT_ASSESSMENT_SH.read_text()
            func_src = script_text[
                script_text.index('def _clean(v):'):
                script_text.index('component = _sidecar_filename_component(raw_job_id)')
            ]
            probe = 'import re\n' + func_src + (
                "\nfor case in ('../../evil', '/etc/passwd', '..', '.', 'a/b/c'):\n"
                "    print(_sidecar_filename_component(case))\n"
            )
            result = subprocess.run(
                ['python3', '-c', probe], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.splitlines(),
                ['.._.._evil', '_etc_passwd', '_', '_', 'a_b_c'],
                'the shipped _sidecar_filename_component transform must '
                'strip every path separator and collapse pure dot-segments '
                '-- this is what actually protects the assessments '
                'directory (the D-14 refusal above cannot demonstrate it '
                'on its own, since this script never creates a brand-new '
                'sidecar file).',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_dry_run_writes_nothing(self):
        sid, job_id = 'p42c-sid-012', 'p42c-job-012'
        record = _tracer_assessment_record(
            job_id, value_low=446.25, value_base=525.0, value_high=603.75,
        )
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(sid, job_id, sidecar_lines=[record])
        )
        try:
            sidecar_bytes_before = Path(sidecar_path).read_bytes()
            ledger_exists_before = os.path.exists(jobs_ledger)
            invocations_before = _jobs_log_invocations(jobs_log)

            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '999', '--currency', 'EUR',
                '--reason', 'dry run preview', '--dry-run',
            ])
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertIn('[dry-run]', out)
            self.assertIn('446.25', out)  # prior value named in the preview
            self.assertIn('999', out)     # new value named in the preview

            self.assertEqual(
                Path(sidecar_path).read_bytes(), sidecar_bytes_before,
                '--dry-run must write nothing to the sidecar file',
            )
            self.assertEqual(
                os.path.exists(jobs_ledger), ledger_exists_before,
                '--dry-run must write nothing to the jobs ledger',
            )
            self.assertEqual(
                _jobs_log_invocations(jobs_log), invocations_before,
                '--dry-run must make no CLI call',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_argv_matches_golden(self):
        sid, job_id = 'p42c-sid-013', 'assess-42-correction-job'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(sid, job_id, sidecar_lines=[record])
        )
        try:
            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '525.0', '--currency', 'USD',
                '--reason', 'correction-golden-reason',
            ])
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')

            invocations = _jobs_log_invocations(jobs_log)
            update_argv = None
            for argv in invocations:
                if len(argv) >= 2 and argv[0] == 'jobs' and argv[1] == 'outcome-update':
                    update_argv = argv
                    break
            self.assertIsNotNone(update_argv, f'expected an outcome-update invocation: {invocations}')
            assert_argv_matches_golden(
                self, update_argv, load_golden('jobs-outcome-update.golden.json'))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_shipped_reason_is_byte_identical_to_the_recorded_reason(self):
        """Greptile P1 (PR #93): the sidecar records _clamp_reason(REASON)
        -- stripped, with '|'/newlines replaced by spaces, truncated to 500
        SERIALIZED bytes -- while the remote `outcome-update --reason` used
        to ship the raw ${REASON}. Any reason the clamp touched therefore
        produced a local audit record that disagreed with the correction
        filed at Revenium, on the one script whose entire purpose is an
        accurate audit trail.

        This reason exercises all three clamp behaviours at once: leading
        and trailing whitespace, an embedded pipe and newline, and a body
        long enough to be truncated."""
        sid, job_id = 'p42c-sid-014', 'assess-42-reason-parity-job'
        record = _tracer_assessment_record(job_id)
        raw_reason = '  billing re-rate | Q3\ntrue-up ' + ('x' * 700) + '  '
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(sid, job_id, sidecar_lines=[record])
        )
        try:
            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '525.0', '--currency', 'USD',
                '--reason', raw_reason,
            ])
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')

            correction = None
            with open(sidecar_path, 'r', encoding='utf-8') as fh:
                for raw_line in fh:
                    if not raw_line.strip():
                        continue
                    parsed = json.loads(raw_line)
                    if parsed.get('kind') == 'correction':
                        correction = parsed
            self.assertIsNotNone(correction, 'expected a correction line in the sidecar')
            recorded = correction['reason']

            update_argv = None
            for argv in _jobs_log_invocations(jobs_log):
                if len(argv) >= 2 and argv[0] == 'jobs' and argv[1] == 'outcome-update':
                    update_argv = argv
                    break
            self.assertIsNotNone(update_argv, 'expected an outcome-update invocation')
            shipped = update_argv[update_argv.index('--reason') + 1]

            # The clamp must actually have done something, or this test would
            # pass vacuously against the raw string.
            self.assertNotEqual(
                recorded, raw_reason,
                'fixture no longer exercises the clamp -- rewrite the reason so '
                'stripping, character replacement and truncation all apply',
            )
            self.assertEqual(
                shipped, recorded,
                'EGV-09: the reason shipped to Revenium must be byte-identical '
                'to the reason recorded in the sidecar -- a divergence makes the '
                'local audit record disagree with the filed correction',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_wr02_toctou_refuses_when_sidecar_deleted_between_check_and_append(self):
        """42-REVIEW.md WR-02: Step 1+2's D-14 check reads the sidecar with
        no lock held. If the file is deleted between that check and Step
        5's append -- plausibly a concurrent, manually-invoked
        prune-markers.sh, since D-13's sidecar pass is mtime-only and both
        scripts are operator-run -- the append must refuse, not silently
        vivify a brand-new sidecar containing only the correction line.

        This test exercises the ACTUAL race, not source text: the shim
        blocks correct-assessment.sh's Step 4 capability probe (the last
        thing the script does before Step 5 opens the sidecar), the test
        deletes the sidecar while the script is paused there, then
        releases it -- a deterministic interleaving landing exactly in the
        window WR-02 describes. A test that deletes the file before the
        script even starts would only exercise the ALREADY-WORKING D-14
        refusal for a record never found in the first place (see
        test_d14_refusal_for_absent_sidecar_record above) -- that is NOT
        what this test proves.
        """
        sid, job_id = 'p42c-sid-015', 'p42c-job-015'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(sid, job_id, sidecar_lines=[record])
        )
        try:
            self.assertTrue(os.path.exists(sidecar_path))
            ledger_before = Path(jobs_ledger).read_text()

            bin_dir = env['PATH'].split(os.pathsep)[0]
            shim = os.path.join(bin_dir, 'revenium')
            entered_file = os.path.join(tmpdir, 'probe-entered')
            release_file = os.path.join(tmpdir, 'probe-release')
            _build_toctou_race_shim(shim, entered_file, release_file)

            proc = subprocess.Popen(
                ['bash', str(CORRECT_ASSESSMENT_SH),
                 '--job-id', job_id, '--value', '400', '--currency', 'USD',
                 '--reason', 'toctou race'],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.time() + 10
                while not os.path.exists(entered_file):
                    self.assertLess(
                        time.time(), deadline,
                        'shim never reached the blocking probe -- the race '
                        'window this test targets was never entered',
                    )
                    time.sleep(0.02)

                # The script is now paused inside Step 4, between Step 1+2's
                # unlocked D-14 check and Step 5's append. Delete the
                # sidecar HERE -- this is the actual race, not a pre-start
                # deletion.
                self.assertTrue(os.path.exists(sidecar_path))
                os.remove(sidecar_path)

                Path(release_file).touch()
                out, err = proc.communicate(timeout=30)
                rc = proc.returncode
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()

            self.assertNotEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertIn('D-14', err)
            self.assertFalse(
                os.path.exists(sidecar_path),
                'WR-02: the append must not silently re-create a sidecar '
                'file containing only the correction line',
            )
            self.assertEqual(
                Path(jobs_ledger).read_text(), ledger_before,
                'WR-02: no ledger line may be written when the '
                're-verified-under-lock existence check refuses',
            )
            self.assertEqual(
                _jobs_log_invocations(jobs_log), [],
                'WR-02: no CLI invocation on a refused correction',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_wr02b_post_write_unlink_refuses_and_ships_nothing(self):
        """Greptile P1 on PR #94: the under-lock st_nlink check closes only
        the open()->flock() window. It does NOT close check->scan->write.
        prune-markers.sh's os.unlink takes no per-file lock (its flock is
        the global prune.lock), so an unlink landing after that check leaves
        the write succeeding against an orphaned inode -- the bytes vanish
        on close -- while the shell still appends the ledger line and ships
        the remote outcome-update, reporting success. Revenium would hold a
        correction the local audit record does not.

        The window is real and wide here because the sequence scan iterates
        an UNBUFFERED FileIO (`os.fdopen(fd, 'r+b', buffering=0)`), so line
        iteration reads a byte at a time. Padding the sidecar with prior
        correction history makes the scan take long enough to unlink inside
        it deterministically: the shim blocks at Step 4, the test releases
        it, waits past the (fast) open and first st_nlink check, then
        unlinks while the (slow) scan is still running.

        The test ASSERTS the refusal rather than tolerating a miss -- if the
        interleaving ever stops landing, this fails loudly instead of
        silently proving nothing."""
        sid, job_id = 'p42c-sid-016', 'p42c-job-016'
        record = _tracer_assessment_record(job_id)
        # Padding history: real `correction` records, so the file stays a
        # legitimate sidecar rather than a synthetic blob.
        padding = []
        for i in range(4000):
            padding.append({
                'kind': 'correction',
                'ts': 1715516100.0 + i,
                'agentic_job_id': job_id,
                'assessment_id': f'{job_id}:{i}',
                'sequence': i,
                'assessment_schema_version': 1,
                'prior_value_low': 400.0, 'prior_value_base': 500.0,
                'prior_value_high': 600.0, 'prior_currency': 'USD',
                'value_low': 400.0, 'value_base': 500.0, 'value_high': 600.0,
                'currency': 'USD',
                'reason': f'padding correction {i} ' + ('p' * 120),
            })
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(sid, job_id, sidecar_lines=[record] + padding)
        )
        try:
            ledger_before = Path(jobs_ledger).read_text()
            bin_dir = env['PATH'].split(os.pathsep)[0]
            shim = os.path.join(bin_dir, 'revenium')
            entered_file = os.path.join(tmpdir, 'probe-entered')
            release_file = os.path.join(tmpdir, 'probe-release')
            _build_toctou_race_shim(shim, entered_file, release_file)

            proc = subprocess.Popen(
                ['bash', str(CORRECT_ASSESSMENT_SH),
                 '--job-id', job_id, '--value', '400', '--currency', 'USD',
                 '--reason', 'post-write unlink race'],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.time() + 30
                while not os.path.exists(entered_file):
                    self.assertLess(
                        time.time(), deadline,
                        'shim never reached the blocking probe',
                    )
                    time.sleep(0.02)

                # Release, then let the open and the FIRST st_nlink check
                # pass (both O(1)) before unlinking -- so the deletion lands
                # inside the slow scan, AFTER the pre-write check, which is
                # the window this test exists for.
                Path(release_file).touch()
                time.sleep(0.15)
                self.assertTrue(
                    os.path.exists(sidecar_path),
                    'sidecar vanished before the test could unlink it',
                )
                os.remove(sidecar_path)

                out, err = proc.communicate(timeout=60)
                rc = proc.returncode
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()

            self.assertNotEqual(
                rc, 0,
                f'post-write unlink must refuse, not report success: '
                f'stdout={out!r} stderr={err!r}',
            )
            self.assertNotIn(
                'Correction shipped to Revenium', out,
                'a correction whose local record was unlinked must NOT be '
                'reported as shipped',
            )
            self.assertEqual(
                Path(jobs_ledger).read_text(), ledger_before,
                'no ledger line may be written when the post-write check '
                'refuses -- the local record does not exist',
            )
            self.assertEqual(
                _jobs_log_invocations(jobs_log), [],
                'no remote outcome-update may be shipped when the local '
                'audit record was lost to a concurrent unlink',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_wr03_team_id_resolution_failure_fails_loud_after_local_save(self):
        """42-REVIEW.md WR-03: `resolve_team_id`'s `revenium config show`
        call is DIFFERENT from the `jobs outcome-update --help` capability
        probe that already succeeded by this point -- its failure must not
        silently kill the script via `set -e` after the local correction
        and ledger line are already durably saved. The operator must be
        told plainly that shipping to Revenium did not happen."""
        sid, job_id = 'p42c-sid-016', 'p42c-job-016'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(
                sid, job_id, sidecar_lines=[record], config_show_fails=True,
            )
        )
        try:
            rc, out, err = _run_correct_assessment(env, [
                '--job-id', job_id, '--value', '400', '--currency', 'USD',
                '--reason', 'team id resolution fails',
            ])
            self.assertNotEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertIn('config show failed', err)
            self.assertIn('NOT shipped to Revenium', err)

            # The local record and ledger line -- Steps 5-6 -- must already
            # be durably saved: they run strictly BEFORE the team-id
            # resolution this test breaks.
            lines = _read_sidecar_lines(sidecar_path)
            self.assertEqual(
                len(lines), 2,
                'WR-03: the local correction must be saved even though '
                f'team-id resolution failed, got {len(lines)} line(s)',
            )
            with open(jobs_ledger) as f:
                ledger_content = f.read()
            self.assertIn(f'JOB:{job_id}:correction:1:', ledger_content)

            invocations = _jobs_log_invocations(jobs_log)
            update_invocations = [
                argv for argv in invocations
                if len(argv) >= 2 and argv[0] == 'jobs' and argv[1] == 'outcome-update'
            ]
            self.assertEqual(
                update_invocations, [],
                'WR-03: outcome-update must never be invoked once team-id '
                f'resolution has already failed, got {update_invocations!r}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Plan 07 (D-13/C-01): the fifth prune pass on the sidecar's OWN mtime clock
# and its OWN retention tunable (REVENIUM_ASSESSMENT_RETENTION_DAYS, default
# 90), wholly independent of REVENIUM_MARKER_RETENTION_DAYS' 30.
#
# Requirements covered:
#   EGV-09 — a correction filed against a sidecar record must not lose the
#            race against a prune keyed on the OWNING SESSION's ledger
#            timestamp; ageing must be the record's own last write instead,
#            so a correction append (which extends the file, never rewrites
#            it) is itself what refreshes the retention window.
# ---------------------------------------------------------------------------


def _build_sidecar_prune_tree():
    """Build a tmp HERMES_HOME tree with only a job-assessments dir and a
    markers dir (no ledger, no state.db) -- enough for prune-markers.sh to
    run standalone against a real subprocess.

    Returns (tmpdir, env, state_dir, assessments_dir, markers_dir).
    """
    tmpdir = tempfile.mkdtemp(prefix='gsd-phase42-sidecar-prune-')
    hermes_home = os.path.join(tmpdir, 'hh')
    state_dir = os.path.join(hermes_home, 'state', 'revenium')
    assessments_dir = os.path.join(state_dir, 'job-assessments')
    markers_dir = os.path.join(state_dir, 'markers')
    os.makedirs(assessments_dir, mode=0o700)
    os.makedirs(markers_dir, mode=0o700)

    env = {
        **os.environ,
        'HERMES_HOME': hermes_home,
        'REVENIUM_STATE_DIR': state_dir,
        'TZ': 'UTC',
    }
    return tmpdir, env, state_dir, assessments_dir, markers_dir


def _write_sidecar_record(assessments_dir, job_id, mtime, extra=None):
    """Write a minimal job_assessment sidecar record for job_id, then
    backdate its mtime (and atime) to `mtime` (a unix timestamp)."""
    record = {
        'kind': 'job_assessment',
        'agentic_job_id': job_id,
        'assessment_id': f'{job_id}:0',
        'value_low': 100.0, 'value_base': 110.0, 'value_high': 120.0,
        'currency': 'USD',
    }
    if extra:
        record.update(extra)
    path = os.path.join(assessments_dir, f'{job_id}.jsonl')
    with open(path, 'w') as f:
        f.write(json.dumps(record, separators=(',', ':')) + '\n')
    os.utime(path, (mtime, mtime))
    return path


def _run_prune_markers(env, *args):
    """Run prune-markers.sh as a REAL subprocess; return
    (returncode, stdout, stderr)."""
    result = subprocess.run(
        ['bash', str(PRUNE_MARKERS_SH), *args],
        env=env, capture_output=True, text=True, timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


def _read_log(state_dir_for_prune):
    """log()'s stderr mirror is TTY-gated (common.sh) -- under a captured
    subprocess it never reaches stdout/stderr, so warn/info assertions must
    read the metering log file directly, matching Phase 32's own helper."""
    log_path = os.path.join(state_dir_for_prune, 'revenium-metering.log')
    if not os.path.exists(log_path):
        return ''
    with open(log_path, encoding='utf-8') as f:
        return f.read()


class SidecarRetentionTests(unittest.TestCase):
    """Plan 07 -- D-13/C-01: the job-assessments sidecar ages from its own
    mtime on its own 90-day REVENIUM_ASSESSMENT_RETENTION_DAYS tunable,
    never from the owning session's ledger timestamp and never from the
    30-day REVENIUM_MARKER_RETENTION_DAYS the four pre-existing passes
    share -- so a file the marker clock would already have deleted still
    survives under the sidecar's own clock, and a correction append (which
    extends the file's mtime) extends the retention window with it."""

    def test_file_older_than_sidecar_cutoff_is_removed(self):
        tmpdir, env, state_dir, assessments_dir, markers_dir = _build_sidecar_prune_tree()
        try:
            old_ts = time.time() - 91 * 86400  # past the 90-day default
            path = _write_sidecar_record(assessments_dir, 'old-job', old_ts)

            rc, out, err = _run_prune_markers(env)
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertFalse(
                os.path.exists(path),
                'a sidecar file past the 90-day default must be removed',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_file_younger_than_sidecar_cutoff_survives(self):
        tmpdir, env, state_dir, assessments_dir, markers_dir = _build_sidecar_prune_tree()
        try:
            fresh_ts = time.time() - 1 * 86400
            path = _write_sidecar_record(assessments_dir, 'fresh-job', fresh_ts)

            rc, out, err = _run_prune_markers(env)
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertTrue(
                os.path.exists(path),
                'a sidecar file younger than the 90-day default must survive',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_older_than_marker_cutoff_but_younger_than_sidecar_cutoff_survives(self):
        """The executable form of D-13's rule: 40 days is stale under the
        30-day MARKER_RETENTION_DAYS the four pre-existing passes share, but
        this file lives in the sidecar's OWN 90-day retention window and
        must survive -- proving the sidecar ages on its own clock, not the
        owning session's."""
        tmpdir, env, state_dir, assessments_dir, markers_dir = _build_sidecar_prune_tree()
        try:
            mid_ts = time.time() - 40 * 86400
            path = _write_sidecar_record(assessments_dir, 'mid-job', mid_ts)

            env = {**env, 'REVENIUM_MARKER_RETENTION_DAYS': '30'}
            rc, out, err = _run_prune_markers(env)
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertTrue(
                os.path.exists(path),
                'D-13: a file older than the 30-day MARKER_RETENTION_DAYS '
                'but younger than the sidecar\'s own 90-day cutoff must '
                'survive -- its own clock, not the session\'s.',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_dry_run_removes_nothing_but_still_reports(self):
        tmpdir, env, state_dir, assessments_dir, markers_dir = _build_sidecar_prune_tree()
        try:
            old_ts = time.time() - 91 * 86400
            path = _write_sidecar_record(assessments_dir, 'old-job-dry', old_ts)

            rc, out, err = _run_prune_markers(env, '--dry-run')
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertTrue(
                os.path.exists(path),
                '--dry-run must not remove a stale sidecar file',
            )
            log_text = _read_log(state_dir)
            self.assertIn(
                'dry-run, would remove', log_text,
                f'--dry-run must still report what it would remove: {log_text!r}',
            )
            self.assertIn('dir=job-assessments', log_text)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_invalid_sidecar_tunable_refuses_to_prune_and_leaves_files_in_place(self):
        tmpdir, env, state_dir, assessments_dir, markers_dir = _build_sidecar_prune_tree()
        try:
            old_ts = time.time() - 91 * 86400
            path = _write_sidecar_record(assessments_dir, 'old-job-invalid', old_ts)

            env = {**env, 'REVENIUM_ASSESSMENT_RETENTION_DAYS': 'not-a-number'}
            rc, out, err = _run_prune_markers(env)
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertTrue(
                os.path.exists(path),
                'an invalid REVENIUM_ASSESSMENT_RETENTION_DAYS must refuse '
                'to prune the sidecar directory, leaving every file in place',
            )
            log_text = _read_log(state_dir)
            self.assertIn('REVENIUM_ASSESSMENT_RETENTION_DAYS', log_text)
            self.assertIn('invalid', log_text.lower())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_invalid_sidecar_tunable_does_not_disable_the_four_existing_passes(self):
        """The other half of the decoupling: an invalid sidecar tunable
        must not gate the marker/flag/spool/ledger passes, which key on the
        wholly separate REVENIUM_MARKER_RETENTION_DAYS."""
        tmpdir, env, state_dir, assessments_dir, markers_dir = _build_sidecar_prune_tree()
        try:
            old_ts = time.time() - 91 * 86400
            marker_path = os.path.join(markers_dir, 'old-sid.jsonl')
            with open(marker_path, 'w') as f:
                f.write(json.dumps({
                    'muid': 'aaa', 'ts': old_ts, 'sid': 'old-sid',
                    'task_type': 'research', 'operation_type': 'CHAT',
                }) + '\n')
            os.utime(marker_path, (old_ts, old_ts))

            env = {**env, 'REVENIUM_ASSESSMENT_RETENTION_DAYS': 'not-a-number'}
            rc, out, err = _run_prune_markers(env)
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertFalse(
                os.path.exists(marker_path),
                'an invalid sidecar tunable must not disable the ordinary '
                'marker pass (no ledger row -> mtime-fallback stale)',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_invalid_marker_tunable_does_not_disable_the_sidecar_pass(self):
        """The mirror of the previous test: an invalid MARKER_RETENTION_DAYS
        must not gate the new sidecar pass, which keys on the wholly
        separate REVENIUM_ASSESSMENT_RETENTION_DAYS."""
        tmpdir, env, state_dir, assessments_dir, markers_dir = _build_sidecar_prune_tree()
        try:
            old_ts = time.time() - 91 * 86400
            path = _write_sidecar_record(assessments_dir, 'old-job-marker-invalid', old_ts)

            env = {**env, 'REVENIUM_MARKER_RETENTION_DAYS': 'not-a-number'}
            rc, out, err = _run_prune_markers(env)
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertFalse(
                os.path.exists(path),
                'an invalid MARKER_RETENTION_DAYS must not disable the '
                'sidecar pass -- its own tunable is unaffected',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_correction_append_refreshes_mtime_so_next_prune_keeps_it(self):
        """C-01's whole point, proven end to end: correct-assessment.sh
        appends a correction line to an about-to-expire sidecar record;
        appending refreshes the file's mtime; the next prune run keeps it
        instead of deleting it. This is the only test that proves the two
        halves (Plan 06's writer, Plan 07's prune pass) compose."""
        tmpdir, env, state_dir, assessments_dir, markers_dir = _build_sidecar_prune_tree()
        try:
            job_id = 'compose-job'
            near_expiry_ts = time.time() - 89 * 86400  # about to cross 90d
            path = _write_sidecar_record(assessments_dir, job_id, near_expiry_ts)

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            shim = os.path.join(bin_dir, 'revenium')
            _build_correction_shim(shim, outcome_update_capable=True)
            correction_env = {
                **env,
                'HOME': shim_home,
                'PATH': bin_dir + os.pathsep + env.get('PATH', ''),
                'JOBS_LOG': os.path.join(tmpdir, 'jobs.log'),
            }

            rc, out, err = _run_correct_assessment(correction_env, [
                '--job-id', job_id, '--value', '90', '--currency', 'USD',
                '--reason', 'compose test -- refresh before expiry',
            ])
            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')

            mtime_after_correction = os.path.getmtime(path)
            self.assertGreater(
                mtime_after_correction, near_expiry_ts + 86400,
                'appending a correction must refresh the sidecar file\'s '
                'mtime',
            )

            rc2, out2, err2 = _run_prune_markers(env)
            self.assertEqual(rc2, 0, f'stdout={out2!r} stderr={err2!r}')
            self.assertTrue(
                os.path.exists(path),
                'C-01: a correction filed against an about-to-expire record '
                'must extend its retention window, so the next prune keeps '
                'it rather than deleting the very file it just appended to',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Follow-up to PR #94 (Greptile P1, accepted): correct-assessment.sh and
# prune-markers.sh now coordinate on ONE per-sidecar lock, held by
# correct-assessment.sh continuously from its D-14 check through its
# remote ship, and taken non-blocking by prune-markers.sh's job-assessments
# pass immediately before it may unlink. These tests exercise both halves
# directly against prune-markers.sh, then prove they compose end to end.
# ---------------------------------------------------------------------------
import fcntl


class SidecarPruneLockCoordinationTests(unittest.TestCase):
    """Prune's job-assessments pass, in isolation: skip (never block) when
    the per-file lock is contended, and decide staleness only AFTER that
    lock is actually held -- never from a value read (or cached) earlier."""

    def test_prune_skips_a_locked_sidecar(self):
        """A stale sidecar currently locked by someone else (a real
        correction, or -- as here -- the test itself holding the SAME
        flock a correction would) must survive a prune run untouched, and
        the skip must be reported, not silently swallowed."""
        tmpdir, env, state_dir, assessments_dir, markers_dir = _build_sidecar_prune_tree()
        try:
            old_ts = time.time() - 91 * 86400  # stale under the 90-day default
            path = _write_sidecar_record(assessments_dir, 'locked-job', old_ts)

            fd = os.open(path, os.O_RDONLY)
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                rc, out, err = _run_prune_markers(env)
                self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
                self.assertTrue(
                    os.path.exists(path),
                    'a sidecar file locked by a concurrent correction must '
                    'survive a prune run regardless of its age -- prune '
                    'must never block waiting for the lock to free up',
                )
                log_text = _read_log(state_dir)
                self.assertIn(
                    'skipped (locked, correction in progress)', log_text,
                    f'prune must report the skip, not silently pass over '
                    f'the file: {log_text!r}',
                )
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_prune_stale_read_is_fstat_on_the_locked_fd_not_a_path_stat(self):
        """STRUCTURAL guard, not a behavioural one -- and deliberately so.

        The behavioural version (prove a value read BEFORE the lock cannot
        win a real race) needs a way to pause prune's process between
        acquiring the lock and reading mtime. This script intentionally
        ships with no such pause point: prune-markers.sh is copied
        verbatim to every end user's `~/.hermes/skills/revenium/`, and an
        env-var-gated sleep loop inside the script that DELETES files is
        surface this product has no business shipping just to make one
        test's timing deterministic.

        With LOCK_NB, a test holding the lock makes prune SKIP rather than
        wait, so there is no window left to hold open and mutate --
        test_prune_skips_a_locked_sidecar above already covers exactly
        that path. What remains provable without a hook is structural: the
        pass reads staleness via `os.fstat(fd).st_mtime` on the fd it just
        locked, and never via a PATH-based stat (`os.path.getmtime` /
        `os.stat` on the filename) that could have been taken earlier --
        for instance during the os.listdir() scan, or cached across
        iterations. With a single stat site, taken on the locked fd, there
        is no earlier read left in the code for a future edit to
        reintroduce a race against.

        The behavioural CONSEQUENCE of this ordering is proven elsewhere,
        end to end: CorrectionSurvivesConcurrentPruneTests below shows a
        correction's append refreshes the sidecar's mtime, and
        SidecarRetentionTests.test_correction_append_refreshes_mtime_so_next_prune_keeps_it
        proves a subsequent prune run then keeps the (now-fresh) record --
        which is only possible if the staleness read genuinely happens
        after the append, under the lock, not from an earlier value.
        """
        src = PRUNE_MARKERS_SH.read_text(encoding='utf-8')
        start = src.index('def prune_assessments_dir(')
        end = src.index('assessment_retention_ok = os.environ.get(', start)
        self.assertGreater(
            end, start,
            'could not locate the job-assessments pass in prune-markers.sh '
            '-- the function may have moved or been renamed',
        )
        function_src = src[start:end]

        self.assertIn(
            'os.fstat(fd).st_mtime', function_src,
            'the job-assessments pass must read staleness from fstat(fd) '
            'on the fd it holds the lock through',
        )
        self.assertNotIn(
            'os.path.getmtime', function_src,
            'the job-assessments pass must never stat the PATH for its '
            'staleness read -- a path-based stat could observe a value '
            'read before the lock was acquired',
        )
        self.assertNotIn(
            'os.stat(fpath', function_src,
            'the job-assessments pass must never stat the PATH for its '
            'staleness read -- a path-based stat could observe a value '
            'read before the lock was acquired',
        )
        # The fstat read must be textually AFTER the flock() acquisition,
        # not just present somewhere in the function -- otherwise a future
        # edit could read mtime up front and still pass the two asserts
        # above by leaving the (now dead) fstat call in place elsewhere.
        flock_idx = function_src.index('fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)')
        fstat_idx = function_src.index('os.fstat(fd).st_mtime')
        self.assertLess(
            flock_idx, fstat_idx,
            'the fstat staleness read must come after the flock() call in '
            'source order, not before it',
        )


class CorrectionSurvivesConcurrentPruneTests(unittest.TestCase):
    """The end-to-end proof that Part A (correct-assessment.sh's
    continuous per-sidecar lock) and Part B (prune-markers.sh's
    lock-and-recheck) compose: whichever of an in-flight correction or a
    concurrent prune gets the lock first, the outcome is always consistent
    -- either the correction completes AND its local record survives, or
    it is refused and nothing is shipped. There is no interleaving that
    ships a remote correction while losing the local record.

    Both orderings are exercised deterministically (via the same
    blocking-checkpoint technique WR-02 already established in this file),
    rather than relying on a bare, schedule-dependent race -- so each
    branch of the "either / or" invariant this task specifies is actually
    proven, not just hoped for."""

    def test_correction_wins_the_lock_first_and_survives_a_concurrent_prune(self):
        sid, job_id = 'p42c-sid-conc-001', 'p42c-job-conc-001'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(sid, job_id, sidecar_lines=[record])
        )
        try:
            # Stale under a tight retention window, so an uncoordinated
            # prune run against this exact file would delete it the moment
            # it got the chance.
            old_ts = time.time() - 2 * 86400
            os.utime(sidecar_path, (old_ts, old_ts))
            prune_env = {**env, 'REVENIUM_ASSESSMENT_RETENTION_DAYS': '1'}

            bin_dir = env['PATH'].split(os.pathsep)[0]
            shim = os.path.join(bin_dir, 'revenium')
            entered_file = os.path.join(tmpdir, 'probe-entered')
            release_file = os.path.join(tmpdir, 'probe-release')
            _build_toctou_race_shim(shim, entered_file, release_file)

            proc = subprocess.Popen(
                ['bash', str(CORRECT_ASSESSMENT_SH),
                 '--job-id', job_id, '--value', '400', '--currency', 'USD',
                 '--reason', 'concurrent prune race -- correction first'],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.time() + 10
                while not os.path.exists(entered_file):
                    self.assertLess(
                        time.time(), deadline,
                        'correct-assessment.sh never reached the blocking '
                        'probe -- it should already hold the per-sidecar '
                        'lock (acquired well before this point) by now',
                    )
                    time.sleep(0.02)

                # correct-assessment.sh holds the fd9 lock now, acquired
                # before its D-14 check (Part A). Run a REAL
                # prune-markers.sh concurrently against the same stale
                # file -- it must skip, not block and not delete.
                rc_prune, out_prune, err_prune = _run_prune_markers(prune_env)
                self.assertEqual(rc_prune, 0, f'stdout={out_prune!r} stderr={err_prune!r}')
                self.assertTrue(
                    os.path.exists(sidecar_path),
                    'a stale sidecar currently locked by an in-flight '
                    'correction must survive a concurrent prune run',
                )
                log_text = _read_log(state_dir)
                self.assertIn(
                    'skipped (locked, correction in progress)', log_text,
                )

                Path(release_file).touch()
                out, err = proc.communicate(timeout=30)
                rc = proc.returncode
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()

            self.assertEqual(rc, 0, f'stdout={out!r} stderr={err!r}')
            self.assertIn('Correction shipped to Revenium', out)

            lines = _read_sidecar_lines(sidecar_path)
            self.assertEqual(
                len(lines), 2,
                'a shipped correction must leave a surviving 2-line local '
                f'record (original + correction), got {len(lines)} line(s)',
            )
            self.assertEqual(json.loads(lines[1]).get('kind'), 'correction')

            with open(jobs_ledger) as f:
                ledger_content = f.read()
            self.assertIn(f'JOB:{job_id}:correction:1:', ledger_content)

            # A SECOND prune, run only after the correction has released
            # the lock, must find the file fresh (the append just
            # refreshed its mtime, per C-01) and keep it under the SAME
            # tight retention window -- proving the earlier survival was
            # specifically the lock at work, not an accident of timing.
            rc_prune2, out_prune2, err_prune2 = _run_prune_markers(prune_env)
            self.assertEqual(rc_prune2, 0, f'stdout={out_prune2!r} stderr={err_prune2!r}')
            self.assertTrue(
                os.path.exists(sidecar_path),
                'the correction append refreshed the mtime -- the record '
                'must still read as fresh under the same retention window',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_prune_wins_the_lock_first_and_correction_refuses_cleanly(self):
        """The other half of the "either / or" invariant. The lock holder
        here is the TEST itself, not a real prune-markers.sh subprocess --
        deliberately: prune-markers.sh ships no pause hook (see the
        docstring on test_prune_stale_read_is_fstat_on_the_locked_fd_not_a_path_stat
        above for why), so this exercises the behavior correct-assessment.sh
        must show against ANY holder of the per-sidecar lock, prune
        included. correct-assessment.sh's own flock(9, LOCK_EX) is
        BLOCKING (unlike prune's LOCK_NB), so holding the lock from the
        test, letting correct-assessment.sh block on it, then deleting the
        file and releasing reproduces exactly what a lock-winning prune
        would leave behind: correct-assessment.sh must acquire the lock
        only once the record is already gone, and must refuse cleanly --
        no ledger line, no CLI invocation, no stdout claim of success."""
        sid, job_id = 'p42c-sid-conc-002', 'p42c-job-conc-002'
        record = _tracer_assessment_record(job_id)
        tmpdir, env, jobs_log, state_dir, sidecar_path, jobs_ledger = (
            _build_correction_tree(sid, job_id, sidecar_lines=[record])
        )
        try:
            fd = os.open(sidecar_path, os.O_RDONLY)
            fcntl.flock(fd, fcntl.LOCK_EX)
            correct_proc = subprocess.Popen(
                ['bash', str(CORRECT_ASSESSMENT_SH),
                 '--job-id', job_id, '--value', '400', '--currency', 'USD',
                 '--reason', 'concurrent prune race -- prune first'],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True,
            )
            try:
                time.sleep(0.3)
                self.assertIsNone(
                    correct_proc.poll(),
                    'correct-assessment.sh must be BLOCKED waiting for '
                    'the lock while the test still holds it, not racing '
                    'ahead and completing independently',
                )

                # Simulate what a lock-winning prune does while it holds
                # the SAME lock: delete the record, then release.
                os.remove(sidecar_path)
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

                correct_out, correct_err = correct_proc.communicate(timeout=30)
                correct_rc = correct_proc.returncode
            finally:
                if correct_proc.poll() is None:
                    correct_proc.kill()
                    correct_proc.communicate()

            self.assertFalse(os.path.exists(sidecar_path))

            self.assertNotEqual(
                correct_rc, 0,
                f'a correction that acquires the lock only after the '
                f'record has been deleted underneath it must refuse, not '
                f'report success: stdout={correct_out!r} stderr={correct_err!r}',
            )
            self.assertIn('D-14', correct_err)
            self.assertNotIn('Correction shipped to Revenium', correct_out)

            with open(jobs_ledger) as f:
                ledger_content = f.read()
            self.assertNotIn(
                f'JOB:{job_id}:correction:', ledger_content,
                'no ledger line may be written when the record was gone '
                'by the time the correction acquired the lock',
            )
            self.assertEqual(
                _jobs_log_invocations(jobs_log), [],
                'no remote outcome-update may be shipped when the local '
                'record was lost to whoever held the lock first',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
