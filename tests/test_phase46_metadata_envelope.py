"""Phase 46 Plan 01 (EGV-19) — the `--metadata` envelope's byte ceiling and
truncation marker, proven against the REAL forwarder heredoc extracted live
from hermes-report.sh, never a reimplementation of its field selection.

Source-of-truth:
  skills/revenium/scripts/hermes-report.sh — the `outcome_metadata` heredoc
  (D-01/D-02/D-03/D-11): the single emit site enforcing
  `_METADATA_CEILING_BYTES`, and the two mirror sites (marker-row, job-row
  heredocs) whose `failure_reason` clamp Task 2 makes byte-safe.
  skills/revenium/plugins/revenium-classifier/classifier.py — `_validate_job`
  (D-10, the producer-side byte-safe clamp) and `_clamp_assessment_text`
  (the shared byte-safe clamp pattern this plan reuses, never reimplements).

Requirements covered: EGV-19, EGV-20 (probe edge: encoding).

Task 1: the end-to-end transport bound — one over-ceiling path, producer to
wire (MetadataEnvelopeTruncationTests) plus the classifier's own byte-safe
`failure_reason` clamp (FailureReasonClassifierClampTests).
Task 2 appends FailureReasonClampTests for the two reporter mirror sites.
Task 3 appends MetadataEnvelopeBudgetTests, the worst-case measurement
matrix and the ceiling's stated margin.
"""
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys as _sys
import tempfile
import unittest

from tests._compat_helpers import ROOT, SCRIPTS_DIR

PLUGIN_DIR = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'
HERMES_REPORT_SH = SCRIPTS_DIR / 'hermes-report.sh'


# ---------------------------------------------------------------------------
# Forwarder extraction — duplicated (not imported) from
# tests/test_phase38_reporter_path.py::_extract_forwarder_record_keys's
# anchor/extraction shape, per this plan's own instruction: importing that
# module would reopen its documented os.environ-mutation-at-import env-bleed
# trap (setUpModule/_load_classifier). Returns None -- never a partial or
# guessed body -- if either anchor has moved, so a real drift fails the
# caller loudly instead of silently testing a stale shape.
# ---------------------------------------------------------------------------
def _extract_outcome_metadata_heredoc(script_text):
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


def _extract_ceiling_bytes(body):
    """Read `_METADATA_CEILING_BYTES` out of the extracted heredoc source
    rather than retyping 4096 in this test, so the constant has exactly one
    authority (the heredoc itself)."""
    import re
    match = re.search(r'_METADATA_CEILING_BYTES\s*=\s*(\d+)', body)
    if not match:
        return None
    return int(match.group(1))


def _run_forwarder(body, env):
    """Execute the extracted heredoc body as a standalone python3 script
    against an explicit environment, matching the real subshell invocation's
    input contract (OUTCOME_SOURCE / OUTCOME_STATUS / OUTCOME_FAILURE_REASON
    / ASSESSMENT_JSON)."""
    return subprocess.run(
        [_sys.executable, '-'], input=body, env=env,
        capture_output=True, text=True,
    )


def _assessment_env(assessment=None, source='prod', status='SUCCESS', failure_reason=''):
    return {
        'OUTCOME_SOURCE': source,
        'OUTCOME_STATUS': status,
        'OUTCOME_FAILURE_REASON': failure_reason,
        'ASSESSMENT_JSON': json.dumps(assessment) if assessment is not None else '',
    }


# A representative ASCII-typical assessment record -- the shape a resolved,
# reportable naked-LLM estimate takes on the wire.
_TYPICAL_ASSESSMENT = {
    'value_low': 10.5, 'value_base': 20.5, 'value_high': 30.5,
    'bounds_source': 'model_estimate',
    'net_value': 15.25,
    'assumptions': {'estimated_hours_saved': 3.5, 'assumed_loaded_rate': 150.0},
    'evaluator': 'naked-llm-evaluator', 'evaluator_version': 'v1.0.0',
    'model': 'some-model-string-id',
    'evidence_class': 'MODEL_ESTIMATED_DEMO', 'reportability_status': 'reportable',
    'confidence': 0.789, 'economic_mechanism': 'augmentation_capacity_expansion',
}


def _over_ceiling_assessment():
    """A full-field assessment record that, combined with a 3,500-byte
    ASCII `failure_reason`, exceeds `_METADATA_CEILING_BYTES` (4096) before
    any drop but fits comfortably after the value-family tier alone is
    popped -- proven empirically against the real forwarder during
    planning: 4,383 bytes before drop, 3,903 after the value-family drop,
    with every provenance field still present. This is a deliberately
    constructed worst case for THIS heredoc in isolation (the ASSESSMENT_JSON
    side alone tops out around ~956 ASCII bytes per 46-RESEARCH.md Q1 --
    failure_reason is the field this plan's D-10 fix bounds upstream in
    production), not a claim about a typical production payload."""
    return {
        'value_low': 10.5, 'value_base': 20.5, 'value_high': 30.5,
        'bounds_source': 'model_estimate',
        'net_value': 15.25,
        'assumptions': {'estimated_hours_saved': 3.5, 'assumed_loaded_rate': 150.0},
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
        'evaluator': 'naked-llm-evaluator-name', 'evaluator_version': 'v1.0.0',
        'model': 'some-model-string-id',
        'evidence_class': 'MODEL_ESTIMATED_DEMO', 'reportability_status': 'reportable',
        'confidence': 0.789, 'economic_mechanism': 'augmentation_capacity_expansion',
        'double_counting_group': 'g' * 64,
    }


_OVER_CEILING_FAILURE_REASON_LEN = 3500
_VALUE_FAMILY_KEYS = (
    'value_low', 'value_base', 'value_high', 'bounds_source',
    'net_value', 'assumptions', 'supplied_costs', 'cost_coverage',
)
_KEPT_PROVENANCE_KEYS = (
    'evaluator', 'evaluator_version', 'model', 'evidence_class', 'reportability_status',
)


class MetadataEnvelopeTruncationTests(unittest.TestCase):
    """Task 1 behaviors 1-4: the forwarder heredoc extracted live, executed
    as a standalone script, driven end to end from producer-shaped
    environment variables to the wire JSON line."""

    def setUp(self):
        self.script_text = HERMES_REPORT_SH.read_text()
        self.body = _extract_outcome_metadata_heredoc(self.script_text)
        self.assertIsNotNone(
            self.body,
            'outcome_metadata=$( ... <<\'PY\' ... \\nPY\\n anchor moved in '
            'hermes-report.sh -- update the extraction before trusting this test',
        )
        self.ceiling = _extract_ceiling_bytes(self.body)
        self.assertIsNotNone(
            self.ceiling,
            '_METADATA_CEILING_BYTES not found in the extracted heredoc body',
        )

    def test_extraction_executes_as_standalone_script(self):
        """Behavior 1: the extracted body runs as a real python3 script and
        produces a single JSON line on stdout for an ordinary input."""
        env = _assessment_env(assessment={'source': 'prod'}, source='prod')
        result = _run_forwarder(self.body, env)
        self.assertEqual(
            result.returncode, 0,
            f'forwarder subprocess failed: stdout={result.stdout!r} stderr={result.stderr!r}',
        )
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        self.assertEqual(len(lines), 1, f'expected exactly one JSON line, got: {lines!r}')
        json.loads(lines[0])  # must parse

    def test_ascii_typical_record_under_ceiling_no_truncation_marker(self):
        """Behavior 2: an ASCII-typical assessment stays under the ceiling
        and carries no metadata_truncated key."""
        env = _assessment_env(assessment=_TYPICAL_ASSESSMENT, source='prod')
        result = _run_forwarder(self.body, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout.strip()
        self.assertLessEqual(
            len(out.encode('utf-8')), self.ceiling,
            f'ASCII-typical payload is {len(out.encode("utf-8"))} bytes, over the {self.ceiling}-byte ceiling',
        )
        meta = json.loads(out)
        self.assertNotIn('metadata_truncated', meta)

    def test_over_ceiling_record_truncates_value_family_and_marks_truncated(self):
        """Behavior 3: a deliberately over-ceiling record (a large
        failure_reason atop a full-field assessment) truncates to at-or-under
        the ceiling, marks metadata_truncated, drops every value-family key,
        and still carries the base + provenance keys."""
        reason = 'r' * _OVER_CEILING_FAILURE_REASON_LEN
        env = _assessment_env(
            assessment=_over_ceiling_assessment(), source='prod',
            status='FAILED', failure_reason=reason,
        )
        result = _run_forwarder(self.body, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout.strip()
        total = len(out.encode('utf-8'))
        self.assertLessEqual(
            total, self.ceiling,
            f'over-ceiling record still ships at {total} bytes, over the {self.ceiling}-byte ceiling',
        )
        meta = json.loads(out)
        self.assertIs(meta.get('metadata_truncated'), True)
        for key in _VALUE_FAMILY_KEYS:
            self.assertNotIn(key, meta, f'{key} (value family) survived truncation')
        for key in _KEPT_PROVENANCE_KEYS:
            self.assertIn(key, meta, f'{key} (provenance) was dropped when only the value family should yield')
        self.assertIn('source', meta)
        self.assertIn('failure_reason', meta)

    def test_over_ceiling_record_is_deterministic_across_runs(self):
        """Behavior 4: running the same over-ceiling input twice produces
        byte-identical stdout -- the concurrency edge (EGV-19)."""
        reason = 'r' * _OVER_CEILING_FAILURE_REASON_LEN
        env = _assessment_env(
            assessment=_over_ceiling_assessment(), source='prod',
            status='FAILED', failure_reason=reason,
        )
        first = _run_forwarder(self.body, env)
        second = _run_forwarder(self.body, env)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first.stdout, second.stdout)

    def test_over_ceiling_source_alone_never_marks_truncated_at_this_heredoc(self):
        """Behavior 5 (CR-01, 46-REVIEW.md): this heredoc, in isolation,
        does not and must not bound `source` -- D-02's 'base metering never
        yields' means neither drop tier ever pops it, and production bounds
        it upstream instead (see SourceClampTests above, which proves the
        job-row/precheck-heredoc producers clamp it to 64 bytes before this
        heredoc ever runs). Feeding a raw, unclamped 400-emoji source
        directly into OUTCOME_SOURCE (bypassing that upstream clamp, the
        same way a hand-edited environment or a future producer regression
        would) reproduces the exact CR-01 defect #2 at this emit site: the
        payload ships over the ceiling with NOTHING in either drop family
        present, so both tier loops pop zero keys -- and metadata_truncated
        must stay ABSENT, not fire unconditionally the way the pre-fix
        code did. Asserting the marker's absence here, at the one emit
        site that decides it, is what makes CR-01 defect #2 (a false
        'something was withheld' signal on a record that withheld nothing)
        a regression a future edit cannot silently reintroduce."""
        huge_source = '\U0001F600' * 400
        env = _assessment_env(assessment=None, source=huge_source)
        result = _run_forwarder(self.body, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout.strip()
        self.assertGreater(
            len(out.encode('utf-8')), self.ceiling,
            'test setup invalid: a 400-emoji source no longer exceeds the '
            'ceiling on its own -- retune the emoji count above',
        )
        meta = json.loads(out)
        self.assertNotIn(
            'metadata_truncated', meta,
            'metadata_truncated was set even though neither drop tier '
            'removed a key -- CR-01 defect #2 regressed',
        )
        self.assertIn('source', meta)


# ---------------------------------------------------------------------------
# Behavior 5 — the classifier's own byte-safe failure_reason clamp
# (D-10). Isolated-import idiom copied from
# tests/test_phase38_reporter_path.py:1678-1719 -- a UNIQUE module name per
# call (the classifier binds its path constants at import time and Python
# caches submodules by name), restored per-test via tearDown, not just at
# module teardown, in case a later class in this same run inherits a
# dangling env var.
# ---------------------------------------------------------------------------
_LOAD_SEQ = [0]
_ENV_TOUCHED = set()
_ENV_SAVED = {}


def setUpModule():
    for k in ('REVENIUM_STATE_DIR', 'REVENIUM_MARKERS_DIR', 'REVENIUM_CONFIG_FILE',
              'REVENIUM_TAXONOMY_FILE', 'REVENIUM_JOB_TAXONOMY_FILE',
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
    for cached in [k for k in list(_sys.modules) if k.startswith('p46env_pkg')]:
        del _sys.modules[cached]


def _load_classifier(env=None):
    """Import the revenium-classifier plugin fresh; return (classifier, evaluators)."""
    for k, v in (env or {}).items():
        os.environ[k] = v
        _ENV_TOUCHED.add(k)
    _LOAD_SEQ[0] += 1
    name = f'p46env_pkg_{_LOAD_SEQ[0]}'
    for cached in [k for k in _sys.modules if k.startswith('p46env_pkg')]:
        del _sys.modules[cached]
    spec = importlib.util.spec_from_file_location(
        name, str(PLUGIN_DIR / '__init__.py'), submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    _sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return _sys.modules[f'{name}.classifier'], _sys.modules[f'{name}.evaluators']


# ---------------------------------------------------------------------------
# Task 2 — the two reporter mirror sites (marker-row, job-row heredocs).
# Each extracted by its OWN distinct anchor per the plan's instruction, not
# shared with _extract_outcome_metadata_heredoc above. `job_rows=$(` is
# deliberately anchored with a leading newline + fixed indent so it does not
# false-match the `precheck_job_rows=$(` anchor, which contains the same
# substring.
# ---------------------------------------------------------------------------
def _extract_marker_row_heredoc(script_text):
    anchor = 'precheck_job_rows=$('
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


def _extract_job_row_heredoc(script_text):
    anchor = '\n      job_rows=$('
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


class FailureReasonClampTests(unittest.TestCase):
    """Task 2 behaviors 1-4: the two reporter mirror sites -- the marker-row
    heredoc (reads markers/<sid>.jsonl, an operator-writable file per this
    plan's T-46-02 threat register entry) and the job-row heredoc (reads the
    JOBS_JSON env var) -- both clamp failure_reason by SERIALIZED BYTES, not
    characters (D-10), independent of the classifier's own producer-side
    clamp (FailureReasonClassifierClampTests above)."""

    def setUp(self):
        script_text = HERMES_REPORT_SH.read_text()
        self.marker_body = _extract_marker_row_heredoc(script_text)
        self.assertIsNotNone(
            self.marker_body,
            "precheck_job_rows=$( ... <<'PY' ... \\nPY\\n anchor moved in "
            'hermes-report.sh -- update the extraction before trusting this test',
        )
        self.job_body = _extract_job_row_heredoc(script_text)
        self.assertIsNotNone(
            self.job_body,
            "job_rows=$( ... <<'PY' ... \\nPY\\n anchor moved in "
            'hermes-report.sh -- update the extraction before trusting this test',
        )
        self._tmpdir = tempfile.mkdtemp(prefix='p46-marker-row-')
        self.addCleanup(shutil.rmtree, self._tmpdir, True)

    def _run_marker_row(self, failure_reason, status='FAILED', source='prod'):
        """Write a hand-crafted markers/<sid>.jsonl line directly -- NOT
        through the classifier's own writer/clamp -- so this test proves the
        reporter's OWN byte-safe clamp defends independently (defense in
        depth for an operator-writable file, per T-46-02). Encoded with
        ensure_ascii=False so the on-disk line stays comfortably under the
        pre-existing large-CHARACTER line-length reader gate (T-03-04,
        unrelated to and unmodified by this plan) even for a long emoji
        failure_reason -- that gate operates on raw line length before this
        clamp is ever reached, so it must not be the thing under test here.

        `source` maps to the SOURCE env var this heredoc invocation receives
        from the bash caller (CR-01, 46-REVIEW.md) -- mirrors `_run_job_row`
        below so both mirror sites are exercised the same way.
        """
        sid = 'p46-clamp-sid'
        marker_path = pathlib.Path(self._tmpdir) / f'{sid}.jsonl'
        record = {
            'kind': 'job', 'agentic_job_id': 'p46-clamp-job',
            'job_type': 'bug_fix', 'status': status,
            'failure_reason': failure_reason,
        }
        marker_path.write_text(json.dumps(record, ensure_ascii=False) + '\n', encoding='utf-8')
        env = {'MARKERS_DIR': self._tmpdir, 'SID': sid, 'SOURCE': source}
        return _run_forwarder(self.marker_body, env)

    def _run_job_row(self, failure_reason, status='FAILED', source='prod'):
        jobs = [{
            'agentic_job_id': 'p46-clamp-job', 'job_type': 'bug_fix',
            'status': status, 'failure_reason': failure_reason,
        }]
        env = {'JOBS_JSON': json.dumps(jobs), 'SOURCE': source}
        return _run_forwarder(self.job_body, env)

    def test_marker_row_500_emoji_failure_reason_clamped_to_500_bytes(self):
        """Behavior 1. CR-01 (46-REVIEW.md): 7 fields now, not 6 -- the
        precheck/marker-row heredoc grew a clamped `source` 4th field,
        mirroring the job-row heredoc's existing layout exactly (see
        SourceClampTests below), so failure_reason shifted from index 5 to
        index 6 in lockstep with the job-row heredoc's own field 6."""
        reason = '\U0001F600' * 500
        result = self._run_marker_row(reason)
        self.assertEqual(result.returncode, 0, result.stderr)
        line = result.stdout.strip()
        self.assertTrue(line, f'expected one pipe row, got empty stdout (stderr={result.stderr!r})')
        fields = line.split('|')
        self.assertEqual(len(fields), 7, f'expected 7 pipe fields, got {len(fields)}: {fields!r}')
        emitted = fields[6]
        serialized = len(json.dumps(emitted, ensure_ascii=True).encode('utf-8')) - 2
        self.assertLessEqual(
            serialized, 500,
            f'marker-row failure_reason is {serialized} serialized bytes, over the 500-byte budget',
        )

    def test_job_row_500_emoji_failure_reason_clamped_to_500_bytes(self):
        """Behavior 2: the same input through the job-row heredoc gives the
        same bound."""
        reason = '\U0001F600' * 500
        result = self._run_job_row(reason)
        self.assertEqual(result.returncode, 0, result.stderr)
        line = result.stdout.strip()
        self.assertTrue(line, f'expected one pipe row, got empty stdout (stderr={result.stderr!r})')
        fields = line.split('|')
        self.assertEqual(len(fields), 7, f'expected 7 pipe fields, got {len(fields)}: {fields!r}')
        emitted = fields[6]
        serialized = len(json.dumps(emitted, ensure_ascii=True).encode('utf-8')) - 2
        self.assertLessEqual(
            serialized, 500,
            f'job-row failure_reason is {serialized} serialized bytes, over the 500-byte budget',
        )

    def test_ascii_failure_reason_under_budget_passes_through_unchanged(self):
        """Behavior 3: no drift on the ordinary path."""
        reason = 'ordinary ascii failure reason well under the byte budget'
        marker_result = self._run_marker_row(reason)
        job_result = self._run_job_row(reason)
        self.assertEqual(marker_result.returncode, 0, marker_result.stderr)
        self.assertEqual(job_result.returncode, 0, job_result.stderr)
        self.assertEqual(marker_result.stdout.strip().split('|')[6], reason)
        self.assertEqual(job_result.stdout.strip().split('|')[6], reason)

    def test_pipe_newline_cr_failure_reason_emits_one_row_with_expected_field_count(self):
        """Behavior 4."""
        reason = 'a|b\nc\rd'
        marker_result = self._run_marker_row(reason)
        job_result = self._run_job_row(reason)
        self.assertEqual(marker_result.returncode, 0, marker_result.stderr)
        self.assertEqual(job_result.returncode, 0, job_result.stderr)
        marker_lines = [l for l in marker_result.stdout.splitlines() if l.strip()]
        job_lines = [l for l in job_result.stdout.splitlines() if l.strip()]
        self.assertEqual(len(marker_lines), 1, f'marker-row: expected 1 line, got {marker_lines!r}')
        self.assertEqual(len(job_lines), 1, f'job-row: expected 1 line, got {job_lines!r}')
        self.assertEqual(len(marker_lines[0].split('|')), 7)
        self.assertEqual(len(job_lines[0].split('|')), 7)


class SourceClampTests(unittest.TestCase):
    """CR-01 (46-REVIEW.md): `source` is the one base-metering key the
    `--metadata` two-tier drop NEVER pops (D-02: 'base metering never
    yields') -- so unlike every value/provenance field, it must be bounded
    at the PRODUCER, before it ever reaches the outcome_metadata heredoc.
    This class proves that bound exists at both mirror sites, the same way
    FailureReasonClampTests above proves failure_reason's -- extraction
    idiom, tmpdir fixture, and both `_run_marker_row`/`_run_job_row` helpers
    reused verbatim rather than reimplemented, per this module's own
    docstring instruction ('never a reimplementation of its field
    selection'). WR-05's own gap was that no existing sweep varied
    `source`'s length; the CR-01 required-fix explicitly asks for this."""

    def setUp(self):
        script_text = HERMES_REPORT_SH.read_text()
        self.marker_body = _extract_marker_row_heredoc(script_text)
        self.assertIsNotNone(
            self.marker_body,
            "precheck_job_rows=$( ... <<'PY' ... \\nPY\\n anchor moved in "
            'hermes-report.sh -- update the extraction before trusting this test',
        )
        self.job_body = _extract_job_row_heredoc(script_text)
        self.assertIsNotNone(
            self.job_body,
            "job_rows=$( ... <<'PY' ... \\nPY\\n anchor moved in "
            'hermes-report.sh -- update the extraction before trusting this test',
        )
        self._tmpdir = tempfile.mkdtemp(prefix='p46-source-clamp-')
        self.addCleanup(shutil.rmtree, self._tmpdir, True)

    # Reuses FailureReasonClampTests' own helpers -- same tmpdir/marker-file
    # shape, same JOBS_JSON shape -- rather than a third copy of either.
    _run_marker_row = FailureReasonClampTests._run_marker_row
    _run_job_row = FailureReasonClampTests._run_job_row

    @staticmethod
    def _serialized_source_bytes(field):
        """Measure a pipe field the same way hermes-report.sh's own
        _clamp_bytes does: json.dumps(..., ensure_ascii=True) minus the two
        quote bytes -- so this assertion assumes nothing about UTF-8 byte
        counting that the production clamp doesn't also assume."""
        return len(json.dumps(field, ensure_ascii=True).encode('utf-8')) - 2

    def test_marker_row_long_emoji_source_clamped_to_64_bytes(self):
        """A source long enough to have triggered CR-01 (the pre-fix
        golden's 61-emoji SOURCE_CHARS, ~732 serialized bytes on its own)
        must come out at or under the 64-byte producer budget through the
        precheck/marker-row heredoc."""
        huge_source = '\U0001F600' * 61
        result = self._run_marker_row('', status='SUCCESS', source=huge_source)
        self.assertEqual(result.returncode, 0, result.stderr)
        fields = result.stdout.strip().split('|')
        self.assertEqual(len(fields), 7, f'expected 7 pipe fields, got {len(fields)}: {fields!r}')
        emitted_source = fields[3]
        serialized = self._serialized_source_bytes(emitted_source)
        self.assertLessEqual(
            serialized, 64,
            f'marker-row source is {serialized} serialized bytes, over the 64-byte budget',
        )

    def test_job_row_long_emoji_source_clamped_to_64_bytes(self):
        """Same input, same bound, through the job-row heredoc -- the two
        mirror sites must agree (WR-01's own concern: divergent copies of a
        small heredoc helper)."""
        huge_source = '\U0001F600' * 61
        result = self._run_job_row('', status='SUCCESS', source=huge_source)
        self.assertEqual(result.returncode, 0, result.stderr)
        fields = result.stdout.strip().split('|')
        self.assertEqual(len(fields), 7, f'expected 7 pipe fields, got {len(fields)}: {fields!r}')
        emitted_source = fields[3]
        serialized = self._serialized_source_bytes(emitted_source)
        self.assertLessEqual(
            serialized, 64,
            f'job-row source is {serialized} serialized bytes, over the 64-byte budget',
        )

    def test_ascii_source_under_budget_passes_through_unchanged(self):
        """No drift on the ordinary path -- a realistic deployment-source
        label (well under 64 bytes) survives both mirror sites byte for
        byte, matching FailureReasonClampTests' own ordinary-path
        assertion."""
        source = 'production-us-east-1'
        marker_result = self._run_marker_row('', status='SUCCESS', source=source)
        job_result = self._run_job_row('', status='SUCCESS', source=source)
        self.assertEqual(marker_result.returncode, 0, marker_result.stderr)
        self.assertEqual(job_result.returncode, 0, job_result.stderr)
        self.assertEqual(marker_result.stdout.strip().split('|')[3], source)
        self.assertEqual(job_result.stdout.strip().split('|')[3], source)

    def test_pipe_newline_cr_source_sanitized(self):
        """A source carrying pipe/newline/CR must not desync the 7-field
        row -- mirrors failure_reason's own delimiter-safety test above."""
        source = 'a|b\nc\rd'
        marker_result = self._run_marker_row('', status='SUCCESS', source=source)
        job_result = self._run_job_row('', status='SUCCESS', source=source)
        self.assertEqual(marker_result.returncode, 0, marker_result.stderr)
        self.assertEqual(job_result.returncode, 0, job_result.stderr)
        marker_lines = [l for l in marker_result.stdout.splitlines() if l.strip()]
        job_lines = [l for l in job_result.stdout.splitlines() if l.strip()]
        self.assertEqual(len(marker_lines), 1, f'marker-row: expected 1 line, got {marker_lines!r}')
        self.assertEqual(len(job_lines), 1, f'job-row: expected 1 line, got {job_lines!r}')
        self.assertEqual(len(marker_lines[0].split('|')), 7)
        self.assertEqual(len(job_lines[0].split('|')), 7)


class FailureReasonClassifierClampTests(unittest.TestCase):
    """Task 1 behavior 5: `_validate_job`'s failure_reason clamp is byte-safe,
    not character-safe (D-10)."""

    def tearDown(self):
        _restore_env()

    def test_500_emoji_failure_reason_clamped_to_500_serialized_bytes(self):
        mod, _ev = _load_classifier({})
        job = {
            'agentic_job_id': 'p46-clamp-job',
            'job_type': 'bug_fix',
            'status': 'FAILED',
            'failure_reason': '\U0001F600' * 500,
        }
        valid = mod._validate_job(job)
        self.assertIsNotNone(valid)
        reason = valid['failure_reason']
        serialized = len(json.dumps(reason, ensure_ascii=True).encode('utf-8')) - 2
        self.assertLessEqual(
            serialized, mod.FAILURE_REASON_CLAMP_BYTES,
            f'failure_reason clamped to {serialized} serialized bytes, over the '
            f'{mod.FAILURE_REASON_CLAMP_BYTES}-byte budget',
        )


# ---------------------------------------------------------------------------
# Task 3 — the worst-case measurement matrix and the ceiling's stated
# margin. Mirrors tests.test_phase42_assessment_contract.SidecarBudgetTests'
# measurement discipline method for method (compute the worst case
# PROGRAMMATICALLY, call the REAL constructor, assert acceptance before
# measuring, serialize exactly as the writer does, assert under budget AND
# a stated minimum margin, sweep non-ASCII input) but against
# _METADATA_CEILING_BYTES and the REAL forwarder heredoc, not
# SIDECAR_LINE_MAX_BYTES and the sidecar writer.
# ---------------------------------------------------------------------------
def _extract_value_omit_family(script_text):
    """Extract `_VALUE_OMIT_FAMILY`'s member list from the live script text
    rather than retyping it, so a future edit to that tuple cannot silently
    desync from this negative-inventory assertion (AMEND-D-02)."""
    import re
    match = re.search(r'_VALUE_OMIT_FAMILY\s*=\s*\(([^)]*)\)', script_text, re.DOTALL)
    if not match:
        return None
    return re.findall(r"'([^']*)'", match.group(1))


class MetadataEnvelopeBudgetTests(unittest.TestCase):
    """Task 3 behaviors 1-5."""

    # 25% of _METADATA_CEILING_BYTES -- the same proportional-margin
    # discipline SidecarBudgetTests uses (its 1024-byte MARGIN_BYTES is
    # ~12.5% of SIDECAR_LINE_MAX_BYTES' 8192); a failure here means a real
    # regression, not a tight fit.
    MARGIN_BYTES = 1024

    def setUp(self):
        self.script_text = HERMES_REPORT_SH.read_text()
        self.body = _extract_outcome_metadata_heredoc(self.script_text)
        self.assertIsNotNone(
            self.body,
            "outcome_metadata=$( ... <<'PY' ... \\nPY\\n anchor moved in "
            'hermes-report.sh -- update the extraction before trusting this test',
        )
        self.ceiling = _extract_ceiling_bytes(self.body)
        self.assertIsNotNone(
            self.ceiling,
            '_METADATA_CEILING_BYTES not found in the extracted heredoc body',
        )

    def tearDown(self):
        _restore_env()

    # -- worst-case JobAssessment construction, mirroring SidecarBudgetTests
    # method for method against THIS module's own isolated-import idiom --

    def _worst_case_valid(self, job_id):
        return {
            'agentic_job_id': job_id,
            'job_type': 'a' + 'b' * 46 + 'c',
            'status': 'FAILED',
        }

    def _worst_case_raw(self, narrative_char='n'):
        return {
            'economic_mechanism': 'augmentation_capacity_expansion',
            'inferred_role': narrative_char * 60,
            'estimated_hours_saved': 40.0,
            'assumed_loaded_rate': 500.0,
            'currency': 'USD',
            'basis': narrative_char * 1000,
            'confidence': 0.999999,
            'candidate_downstream_outcome': narrative_char * 1000,
            'counterfactual_assumption': narrative_char * 1000,
        }

    def _worst_case_record(self, mod, job_id, narrative_char='n'):
        raw = self._worst_case_raw(narrative_char)
        # Overlong on purpose -- _build_job_assessment's own internal
        # clamps (32/16/64/64 bytes respectively) are the real ceilings;
        # passing something longer proves those internal clamps, not a
        # value this test guessed, are what bounds the record.
        evaluator = 'e' * 100
        evaluator_version = 'v' * 100
        model = 'm' * 100
        assessment = mod._validate_assessment(raw, {}, evaluator, evaluator_version)
        self.assertIsNotNone(assessment, 'max-bound inputs must be accepted, not rejected')
        valid = self._worst_case_valid(job_id)
        # Every cost category as a literal 0 -- lands in BOTH "included" and
        # "known_zero" simultaneously, which costs MORE serialized bytes
        # than a large nonzero value would (SidecarBudgetTests' own D-10
        # finding, reused here for the same reason).
        cfg = {'costs': {valid['job_type']: {cat: 0 for cat in mod.COST_CATEGORIES}}}
        rec = mod._build_job_assessment(
            valid, assessment, raw, cfg, evaluator, evaluator_version,
            double_counting_group='g' * 100, model=model)
        self.assertIsNotNone(rec, 'worst-case record construction must succeed')
        return rec

    def _measure(self, mod, narrative_char):
        rec = self._worst_case_record(mod, job_id=f'p46-budget-{narrative_char!r}', narrative_char=narrative_char)
        failure_reason = mod._clamp_assessment_text(narrative_char * 1000, mod.FAILURE_REASON_CLAMP_BYTES)
        env = _assessment_env(assessment=rec, source='prod', status='FAILED', failure_reason=failure_reason)
        result = _run_forwarder(self.body, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout.strip()
        json.loads(out)  # must parse
        return len(out.encode('utf-8'))

    _ENCODINGS = (('ascii', 'n'), ('accented', 'é'), ('cjk', '漢'), ('emoji', '😀'), ('mixed', 'a😀é漢'))

    def test_worst_case_swept_across_encodings_stays_under_ceiling(self):
        """Behavior 1."""
        mod, _ev = _load_classifier({})
        for label, ch in self._ENCODINGS:
            with self.subTest(label):
                measured = self._measure(mod, ch)
                self.assertLessEqual(
                    measured, self.ceiling,
                    f'{label} worst case is {measured} bytes, over the {self.ceiling}-byte ceiling',
                )
                print(f'[46-01 MetadataEnvelopeBudgetTests] {label} worst-case envelope: {measured} bytes')

    def test_margin_asserted_not_assumed(self):
        """Behavior 2: the largest measured worst case plus MARGIN_BYTES is
        still at or under the ceiling -- the headroom is asserted, not
        assumed."""
        mod, _ev = _load_classifier({})
        largest = max(self._measure(mod, ch) for _label, ch in self._ENCODINGS)
        self.assertLessEqual(
            largest + self.MARGIN_BYTES, self.ceiling,
            f'largest measured worst case ({largest} bytes) + {self.MARGIN_BYTES}-byte margin '
            f'exceeds the {self.ceiling}-byte ceiling -- re-derive the ceiling or the clamps',
        )
        print(f'[46-01 MetadataEnvelopeBudgetTests] largest worst-case envelope: {largest} bytes, '
              f'margin {self.ceiling - largest}')

    def test_correction_record_carries_correction_fields_and_stays_far_under_ceiling(self):
        """Behavior 3: a kind:"correction" record (the shape
        correct-assessment.sh writes, duplicated here rather than imported
        per this repo's no-shared-code-between-producer-and-test-fixture
        convention -- see test_phase42_assessment_contract.py's own
        docstring on the same point) still carries `corrected` and
        `correction_sequence`, and stays far under the ceiling."""
        record = {
            'kind': 'correction',
            'ts': 1715516010.0,
            'agentic_job_id': 'p46-correction-job',
            'assessment_id': 'p46-correction-job:2',
            'sequence': 2,
            'assessment_schema_version': 1,
            'prior_value_low': 446.25,
            'prior_value_base': 525.0,
            'prior_value_high': 603.75,
            'prior_currency': 'USD',
            'value_low': 100.0,
            'value_base': 110.0,
            'value_high': 120.0,
            'currency': 'USD',
            'reason': 'operator correction',
        }
        env = _assessment_env(assessment=record, source='prod', status='SUCCESS')
        result = _run_forwarder(self.body, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout.strip()
        meta = json.loads(out)
        self.assertIs(meta.get('corrected'), True)
        self.assertEqual(meta.get('correction_sequence'), 2)
        total = len(out.encode('utf-8'))
        self.assertLess(
            total, self.ceiling // 2,
            f'correction record is {total} bytes -- expected far under the {self.ceiling}-byte ceiling',
        )

    def test_metadata_truncated_absent_from_sidecar_declared_keys(self):
        """Behavior 4: `metadata_truncated` belongs to the transport, not
        the sidecar (AMEND-D-02)."""
        from tests.test_phase42_assessment_contract import RecordShapeTests
        self.assertNotIn(
            'metadata_truncated', RecordShapeTests.DECLARED_KEYS,
            'AMEND-D-02: metadata_truncated is a --metadata TRANSPORT key, '
            "computed in hermes-report.sh's outcome_metadata heredoc -- a "
            "different Python subprocess connected to the sidecar's "
            "DECLARED_KEYS contract only through shell variables. It must "
            'never join the sidecar contract.',
        )

    def test_metadata_truncated_absent_from_value_omit_family(self):
        """Behavior 5: `metadata_truncated` is absent from
        `_VALUE_OMIT_FAMILY` in hermes-report.sh -- that tuple governs an
        earlier pipeline stage (the sidecar re-read) that can never see a
        marker computed downstream at the transport emit site (AMEND-D-02)."""
        family = _extract_value_omit_family(self.script_text)
        self.assertIsNotNone(
            family,
            '_VALUE_OMIT_FAMILY anchor moved in hermes-report.sh -- update '
            'the extraction before trusting this test',
        )
        self.assertNotIn('metadata_truncated', family)


if __name__ == '__main__':
    unittest.main()
