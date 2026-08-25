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
        """The kind:"correction" shape plan 42-06 will append -- built here
        directly, since that script does not exist yet, so the reader's
        per-line 8192-byte guard is proven adequate for BOTH line kinds
        before the correction path is built (per this task's own action
        text). Shape per 41-CARRIER-DECISION.md Part 3: job id, timestamp,
        a 500-byte reason, and prior/new bound values -- measured there at
        672 bytes for a much smaller reason; this is the WORST case."""
        mod, _ev = _load_classifier({})
        reason = mod._clamp_assessment_text('r' * 2000, mod.NARRATIVE_CLAMP_BYTES)
        correction = {
            'kind': 'correction',
            'ts': 1756000000.123456,
            'sequence': 999,
            'agentic_job_id': 'x' * 48 + '_a1b2',
            'reason': reason,
            'prior_value_low': 999999.99, 'prior_value_base': 999999.99, 'prior_value_high': 999999.99,
            'new_value_low': 999999.99, 'new_value_base': 999999.99, 'new_value_high': 999999.99,
            'currency': 'USD',
            'operator': 'o' * 80,
        }
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


if __name__ == '__main__':
    unittest.main()
