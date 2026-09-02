"""Phase 55 Plan 02 (ROI-09/ROI-10) -- the three edges the tracer (Plan 01)
deliberately left open:

  Task 1 (this section): a `billing_provider` of literal "auto" reaching the
  PROVIDER dimension unresolved -- the precise ROI-10 failure, where a rule
  scoped `PROVIDER:IS:anthropic` silently omits rows whose billing_provider
  is "auto" even though the model served was Claude. Proven against the
  REAL `_infer_provider` function extracted live from hermes-report.sh
  (Arm A), driven end to end on both emit paths at once (Arm B), and guarded
  against golden drift (Arm C).

  Task 2 appends the `aux_unclassified` fallback + its once-per-distinct-
  value warn (D-08).

  Task 3 appends the once-per-install permanent-step-up notice (D-04).

Source-of-truth: skills/revenium/scripts/hermes-report.sh -- `_infer_provider`
(the one shared inference function both the main loop and the auxiliary pass
call) and `report_auxiliary_usage` (the post-loop auxiliary pass Plan 01
built).

Harness: `_AuxMeteringTestCase` imported (not duplicated) from
tests/test_phase55_auxiliary_metering.py, per this repo's own convention of
importing a sibling phase-numbered test module's shared fixture-DB/shim
harness rather than re-typing it (see e.g.
tests/test_phase39_outcome_bounding.py importing `_build_flexible_shim` from
tests/test_phase38_reporter_path.py).
"""
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys as _sys
import tempfile
import unittest

from tests._compat_helpers import (
    argv_to_flags,
    load_golden,
    run_script,
    SCRIPTS_DIR,
)
from tests.test_phase55_auxiliary_metering import _AuxMeteringTestCase

HERMES_REPORT_SH = SCRIPTS_DIR / 'hermes-report.sh'


# ---------------------------------------------------------------------------
# Arm A -- the real `_infer_provider` bash function, extracted live and
# driven as a standalone script. Anchor/extraction shape copied from
# tests/test_phase46_metadata_envelope.py::_extract_outcome_metadata_heredoc
# (fail loudly -- return None, never a partial or guessed body -- if either
# anchor has moved, so a future refactor that moves the function turns this
# suite red instead of silently testing nothing).
# ---------------------------------------------------------------------------
def _extract_infer_provider_function(script_text):
    anchor = '_infer_provider() {'
    start = script_text.find(anchor)
    if start == -1:
        return None
    end_marker = "\nPY\n}\n"
    end = script_text.find(end_marker, start)
    if end == -1:
        return None
    end += len(end_marker)
    return script_text[start:end]


def _run_infer_provider(function_body, model, billing):
    """Write the extracted function into a standalone script that sources
    nothing else, call it with (model, billing) positionally -- matching
    `_infer_provider "${model}" "${billing}"`'s own call shape -- and return
    its stripped stdout."""
    script = '#!/usr/bin/env bash\nset -uo pipefail\n' + function_body + \
        '\n_infer_provider "$1" "$2"\n'
    tmp = tempfile.NamedTemporaryFile('w', suffix='.sh', delete=False)
    try:
        tmp.write(script)
        tmp.close()
        os.chmod(tmp.name, 0o755)
        result = subprocess.run(
            ['bash', tmp.name, model, billing],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip()
    finally:
        os.unlink(tmp.name)


class InferProviderAutoResolutionTests(unittest.TestCase):
    """Task 1 Arm A -- driven against the real, live-extracted function."""

    @classmethod
    def setUpClass(cls):
        cls.script_text = HERMES_REPORT_SH.read_text()
        cls.body = _extract_infer_provider_function(cls.script_text)

    def setUp(self):
        self.assertIsNotNone(
            self.body,
            '_infer_provider extraction failed -- the anchor or the `\\nPY\\n}\\n` '
            'end marker moved in hermes-report.sh; update the extraction in '
            'this test before trusting anything below it',
        )

    def test_extraction_fails_loudly_when_the_function_is_renamed(self):
        """Proves the extraction assertion above is load-bearing, not a
        silent pass: renaming the anchor in a scratch copy of the script
        text must make _extract_infer_provider_function return None."""
        mutated = self.script_text.replace(
            '_infer_provider() {', '_infer_provider_renamed() {'
        )
        self.assertIsNone(
            _extract_infer_provider_function(mutated),
            'extraction must return None once the anchor is gone -- a '
            'renamed function must fail the extraction, not silently match '
            'a stale body',
        )

    def test_auto_billing_with_claude_model_resolves_anthropic(self):
        self.assertEqual(
            _run_infer_provider(self.body, 'claude-3-5-haiku', 'auto'),
            'anthropic',
        )

    def test_auto_billing_with_openai_model_resolves_openai(self):
        self.assertEqual(
            _run_infer_provider(self.body, 'gpt-4o-mini', 'auto'),
            'openai',
        )

    def test_auto_billing_with_google_model_resolves_google(self):
        self.assertEqual(
            _run_infer_provider(self.body, 'gemini-2.5-flash', 'auto'),
            'google',
        )

    def test_auto_billing_with_unrecognised_model_resolves_unknown(self):
        self.assertEqual(
            _run_infer_provider(self.body, 'some-totally-unrecognised-model', 'auto'),
            'unknown',
        )

    # --- Regression guard: every pre-existing branch is unchanged. ---

    def test_regression_anthropic_billing_with_claude_model_still_resolves_anthropic(self):
        self.assertEqual(
            _run_infer_provider(self.body, 'claude-3-5-haiku', 'anthropic'),
            'anthropic',
        )

    def test_regression_openrouter_billing_with_claude_model_still_resolves_anthropic(self):
        self.assertEqual(
            _run_infer_provider(self.body, 'anthropic/claude-3-5-haiku', 'openrouter'),
            'anthropic',
        )

    def test_regression_bedrock_billing_with_claude_model_still_resolves_anthropic(self):
        self.assertEqual(
            _run_infer_provider(self.body, 'anthropic.claude-3-5-haiku', 'bedrock'),
            'anthropic',
        )

    def test_regression_bedrock_billing_with_non_claude_model_still_resolves_aws(self):
        self.assertEqual(
            _run_infer_provider(self.body, 'some-other-model', 'bedrock'),
            'aws',
        )


# ---------------------------------------------------------------------------
# Arm B -- driven end to end, both emit paths at once.
# ---------------------------------------------------------------------------
class AutoProviderEndToEndTests(_AuxMeteringTestCase):
    """Task 1 Arm B -- a `billing_provider` of "auto" on BOTH the main-loop
    session row AND the auxiliary session_model_usage row must resolve
    `--provider anthropic` while `--model-source` keeps the raw "auto"
    literal, proving the fix is genuinely global (one shared function, one
    edit) rather than aux-only."""

    def test_auto_billing_resolves_on_both_emit_paths_at_once(self):
        fixture = self._setup_fixture(
            [self._one_session(
                model='claude-sonnet-4-6', billing_provider='auto',
            )],
            aux_rows=[self._one_aux_row(
                model='claude-3-5-haiku', billing_provider='auto', task='approval',
            )],
        )
        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])

        main_flags_list = self._find_non_aux_invocation(result['meter_invocations'])
        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(len(main_flags_list), 1, result['meter_invocations'])
        self.assertEqual(len(aux_flags_list), 1, result['meter_invocations'])

        main_flags = main_flags_list[0]
        aux_flags = aux_flags_list[0]

        self.assertEqual(
            main_flags.get('--provider'), 'anthropic',
            'main-loop row: billing_provider="auto" must resolve through '
            'model-name inference to "anthropic", not ship literally',
        )
        self.assertEqual(
            main_flags.get('--model-source'), 'auto',
            '--model-source must still carry the raw billing_provider column verbatim',
        )
        self.assertEqual(
            aux_flags.get('--provider'), 'anthropic',
            'auxiliary row: billing_provider="auto" must resolve through the '
            'SAME shared inference function to "anthropic"',
        )
        self.assertEqual(
            aux_flags.get('--model-source'), 'auto',
            '--model-source must still carry the raw billing_provider column '
            'verbatim on the auxiliary path too',
        )


# ---------------------------------------------------------------------------
# Arm C -- the no-drift guard, stated as its own test.
# ---------------------------------------------------------------------------
class NoGoldenDriftGuardTests(unittest.TestCase):
    """Task 1 Arm C -- D-10's own text: if this trips, it will have
    surfaced a main-loop row that was silently shipping "auto" as its
    PROVIDER dimension, which is worth knowing rather than a mystery
    failure. The four immutable goldens
    (tests/fixtures/compat/README.md's own list) are re-run here in-process
    so a regression in this plan's edit is caught by this module directly,
    not only by a separate CI invocation of those four files."""

    def test_meter_completion_golden_still_pins_anthropic_provider(self):
        golden = load_golden('meter-completion.golden.json')
        self.assertEqual(
            golden['exact_match_fields'].get('--provider'), 'anthropic',
            'meter-completion.golden.json must keep pinning --provider '
            'anthropic for its already-real-provider fixture session -- if '
            'this value ever becomes "auto" it means a main-loop row that '
            'declares a real provider started shipping it unresolved',
        )

    def test_four_immutable_goldens_still_pass(self):
        """Runs the four golden-fixture test modules
        (tests/fixtures/compat/README.md's own enumerated four) in-process
        and fails with the D-10 explanation if any of them regress."""
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for module_name in (
            'tests.test_compat_meter_completion',
            'tests.test_compat_jobs_create',
            'tests.test_compat_jobs_outcome',
            'tests.test_compat_meter_tool_event',
        ):
            suite.addTests(loader.loadTestsFromName(module_name))

        result = unittest.TextTestRunner(stream=open(os.devnull, 'w'), verbosity=0).run(suite)
        self.assertTrue(
            result.wasSuccessful(),
            'one of the four immutable golden-fixture test modules regressed '
            'after the `auto` short-circuit-tuple edit in _infer_provider -- '
            'per D-10, this most likely means a main-loop row that declares '
            'a REAL provider (e.g. "anthropic") started resolving through '
            'the model-name inference branch unexpectedly, which would be a '
            'genuine wire-shape regression, not a false alarm: '
            f'failures={result.failures!r} errors={result.errors!r}',
        )


if __name__ == '__main__':
    unittest.main()
