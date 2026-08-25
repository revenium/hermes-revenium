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
import unittest.mock

from tests._compat_helpers import build_shim, build_state_db

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
    derivation and adds the remaining EGV-04 fields."""
    record = {
        'kind': 'job_assessment',
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


if __name__ == '__main__':
    unittest.main()
