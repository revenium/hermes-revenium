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
import subprocess
import sys as _sys
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


if __name__ == '__main__':
    unittest.main()
