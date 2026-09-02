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


# ---------------------------------------------------------------------------
# Task 2 -- an unrecognised task value ships as aux_unclassified with a
# once-per-distinct-value warn (D-08).
# ---------------------------------------------------------------------------
def _bump_aux_row(state_db, session_id, model, billing_provider='', billing_base_url='',
                   billing_mode='', task='', delta_input=20, delta_output=10, delta_calls=1):
    """Advance a session_model_usage row's CUMULATIVE counters between ticks
    (the schema is UPSERT/cumulative per six-column identity, per Plan 01's
    own D-14 note) so a second tick ships a real new delta rather than the
    no-op every existing test in test_phase55_auxiliary_metering.py drives."""
    conn = sqlite3.connect(state_db)
    conn.execute(
        'UPDATE session_model_usage SET '
        'input_tokens = input_tokens + ?, output_tokens = output_tokens + ?, '
        'api_call_count = api_call_count + ? '
        'WHERE session_id=? AND model=? AND billing_provider=? AND billing_base_url=? '
        'AND billing_mode=? AND task=?',
        (delta_input, delta_output, delta_calls,
         session_id, model, billing_provider, billing_base_url, billing_mode, task),
    )
    conn.commit()
    conn.close()


class _AuxWarnGateTestCase(_AuxMeteringTestCase):
    @staticmethod
    def _log_text(fixture):
        log_path = os.path.join(fixture['state_dir'], 'revenium-metering.log')
        if not os.path.exists(log_path):
            return ''
        with open(log_path) as f:
            return f.read()

    @staticmethod
    def _aux_warn_dir(fixture):
        return os.path.join(fixture['state_dir'], 'markers', '.aux-warn')

    @classmethod
    def _sentinel_names(cls, fixture):
        warn_dir = cls._aux_warn_dir(fixture)
        if not os.path.isdir(warn_dir):
            return []
        return os.listdir(warn_dir)


class UnrecognisedTaskValueTests(_AuxWarnGateTestCase):
    """Task 2 -- an unrecognised `task` value never drops the row's spend,
    only its label, and costs the operator exactly one actionable warn per
    distinct value per install."""

    def test_unrecognised_value_ships_aux_unclassified_with_spend_intact_and_one_warn(self):
        aux_row = self._one_aux_row(task='title_gen_v2', input_tokens=40, output_tokens=10)
        fixture = self._setup_fixture([self._one_session()], aux_rows=[aux_row])
        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])

        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(len(aux_flags_list), 1, result['meter_invocations'])
        aux_flags = aux_flags_list[0]

        self.assertEqual(aux_flags.get('--task-type'), 'aux_unclassified')
        self.assertEqual(
            aux_flags.get('--input-tokens'), '40',
            'the spend must ship intact even though the label was dropped',
        )
        self.assertEqual(aux_flags.get('--output-tokens'), '10')
        self.assertEqual(aux_flags.get('--total-tokens'), '50')

        log_text = self._log_text(fixture)
        self.assertEqual(
            log_text.count('title_gen_v2'), 1,
            f'expected exactly one warn line naming the unrecognised value, log:\n{log_text}',
        )
        self.assertIn('aux-taxonomy.json', log_text)
        self.assertIn('aux_unclassified', log_text)

        sentinels = self._sentinel_names(fixture)
        self.assertTrue(
            any('title_gen_v2' in name for name in sentinels),
            f'expected a sentinel file naming the unrecognised value, got {sentinels!r}',
        )

    def test_second_tick_over_a_grown_delta_does_not_repeat_the_warn(self):
        aux_row = self._one_aux_row(task='title_gen_v2')
        fixture = self._setup_fixture([self._one_session()], aux_rows=[aux_row])
        self._tick(fixture, 0)

        log_after_tick_1 = self._log_text(fixture)
        self.assertEqual(log_after_tick_1.count('title_gen_v2'), 1)

        _bump_aux_row(
            fixture['state_db'], session_id=aux_row['session_id'], model=aux_row['model'],
            billing_provider=aux_row['billing_provider'],
            billing_base_url=aux_row['billing_base_url'], billing_mode=aux_row['billing_mode'],
            task=aux_row['task'],
        )
        result_2 = self._tick(fixture, 1)
        aux_flags_list = self._find_aux_invocation(result_2['meter_invocations'])
        self.assertEqual(
            len(aux_flags_list), 1,
            'a real new delta must still ship a second aux invocation -- the '
            '"no repeat warn" result below must not be explainable by '
            'nothing having run',
        )

        log_after_tick_2 = self._log_text(fixture)
        self.assertEqual(
            log_after_tick_2.count('title_gen_v2'), 1,
            f'the warn must never repeat for an already-seen value, log:\n{log_after_tick_2}',
        )

    def test_two_distinct_unrecognised_values_each_get_their_own_warn_and_sentinel(self):
        row_a = self._one_aux_row(task='title_gen_v2', model='claude-3-5-haiku')
        row_b = self._one_aux_row(task='weird_upstream_rename', model='claude-3-5-haiku',
                                   billing_base_url='https://distinct-b.example')
        fixture = self._setup_fixture([self._one_session()], aux_rows=[row_a, row_b])
        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])

        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(len(aux_flags_list), 2, result['meter_invocations'])
        for flags in aux_flags_list:
            self.assertEqual(flags.get('--task-type'), 'aux_unclassified')

        log_text = self._log_text(fixture)
        self.assertEqual(log_text.count('title_gen_v2'), 1)
        self.assertEqual(log_text.count('weird_upstream_rename'), 1)

        sentinels = self._sentinel_names(fixture)
        self.assertTrue(any('title_gen_v2' in name for name in sentinels), sentinels)
        self.assertTrue(any('weird_upstream_rename' in name for name in sentinels), sentinels)

    def test_hostile_task_value_sentinel_filename_is_fully_sanitized(self):
        hostile_task = 'weird|task\ncolon:val'
        aux_row = self._one_aux_row(task=hostile_task)
        fixture = self._setup_fixture([self._one_session()], aux_rows=[aux_row])
        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])

        aux_flags_list = self._find_aux_invocation(result['meter_invocations'])
        self.assertEqual(len(aux_flags_list), 1, result['meter_invocations'])
        self.assertEqual(aux_flags_list[0].get('--task-type'), 'aux_unclassified')

        # T-55-07: the hostile value must produce exactly one "unknown-"
        # sentinel. A successful emit also lights the (unrelated,
        # constant-keyed) "notice-step-up" sentinel Task 3 adds -- filter to
        # this test's own concern rather than asserting on the directory's
        # total file count.
        sentinels = [n for n in self._sentinel_names(fixture) if n.startswith('unknown-')]
        self.assertEqual(len(sentinels), 1, sentinels)
        sentinel_name = sentinels[0]
        for forbidden in ('|', '\n', ':'):
            self.assertNotIn(
                forbidden, sentinel_name,
                f'sentinel filename {sentinel_name!r} must not carry a raw {forbidden!r}',
            )

        ledger_path = self._aux_ledger_path(fixture)
        with open(ledger_path) as f:
            lines = [ln.rstrip('\n') for ln in f if ln.strip()]
        self.assertEqual(len(lines), 1, lines)
        parts = lines[0].split('|')
        self.assertEqual(
            len(parts), 8,
            f'ledger line must still split into 8 pipe-delimited parts, got {len(parts)}: {parts!r}',
        )


# ---------------------------------------------------------------------------
# Task 3 -- the once-per-install permanent step-up notice (D-04).
# ---------------------------------------------------------------------------
def _build_failing_completion_shim(shim_path):
    """Same probe/capture shape as _compat_helpers.build_shim (squad-capable,
    jobs-outcome-value-capable), except `revenium meter completion` always
    exits 1 after logging its argv. Drives Task 3's failure arm: the notice
    and the ledger line share the zero-exit precondition, so a failing CLI
    call must produce neither -- proven here by making EVERY completion
    call fail, main-loop and auxiliary alike."""
    body = (
        '#!/usr/bin/env bash\n'
        'case "$1" in\n'
        '  config) exit 0 ;;\n'
        '  guardrails) exit 0 ;;\n'
        '  meter)\n'
        '    if [[ "$3" == "--help" ]]; then\n'
        '      echo "--squad-id string        Squad (root session) identifier"\n'
        '      echo "--squad-name string       Squad (root session) display name"\n'
        '      echo "--squad-role string       Squad role: root or subagent"\n'
        '      echo "--agentic-job-id  Agentic job instance identifier"\n'
        '      exit 0\n'
        '    fi\n'
        '    case "$2" in\n'
        '      completion)\n'
        '        printf "%q " "$@" >> "${METER_LOG:-${INVOCATIONS_LOG:-/dev/null}}"\n'
        '        printf "\\n"      >> "${METER_LOG:-${INVOCATIONS_LOG:-/dev/null}}"\n'
        '        exit 1\n'
        '        ;;\n'
        '      *)\n'
        '        printf "%q " "$@" >> "${INVOCATIONS_LOG:-/dev/null}"\n'
        '        printf "\\n"      >> "${INVOCATIONS_LOG:-/dev/null}"\n'
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
        '    printf "%q " "$@" >> "${JOBS_LOG:-${INVOCATIONS_LOG:-/dev/null}}"\n'
        '    printf "\\n"      >> "${JOBS_LOG:-${INVOCATIONS_LOG:-/dev/null}}"\n'
        '    exit 0\n'
        '    ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n'
    )
    with open(shim_path, 'w') as f:
        f.write(body)
    os.chmod(shim_path, 0o755)


class StepUpNoticeTests(_AuxWarnGateTestCase):
    """Task 3 -- the permanent step-up and its one-time historical catch-up
    are announced exactly once per install, only after a real successful
    emit, naming the off switch and the migration document."""

    def test_first_successful_emit_fires_the_notice_exactly_once(self):
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])
        self.assertEqual(len(self._find_aux_invocation(result['meter_invocations'])), 1)

        log_text = self._log_text(fixture)
        self.assertEqual(
            log_text.count('permanently raises reported spend'), 1,
            f'expected exactly one step-up notice line, log:\n{log_text}',
        )
        self.assertIn(
            'REVENIUM_AUX_METERING', log_text,
            'the notice must name the off-switch variable by name',
        )
        self.assertIn(
            'docs/migration-auxiliary-usage.md', log_text,
            'the notice must name the migration document',
        )

        sentinels = self._sentinel_names(fixture)
        self.assertIn('notice-step-up.flag', sentinels, sentinels)

    def test_second_run_ships_a_real_aux_row_but_never_repeats_the_notice(self):
        aux_row = self._one_aux_row()
        fixture = self._setup_fixture([self._one_session()], aux_rows=[aux_row])
        self._tick(fixture, 0)

        log_after_tick_1 = self._log_text(fixture)
        self.assertEqual(log_after_tick_1.count('permanently raises reported spend'), 1)

        _bump_aux_row(
            fixture['state_db'], session_id=aux_row['session_id'], model=aux_row['model'],
            billing_provider=aux_row['billing_provider'],
            billing_base_url=aux_row['billing_base_url'], billing_mode=aux_row['billing_mode'],
            task=aux_row['task'],
        )
        result_2 = self._tick(fixture, 1)
        aux_flags_list = self._find_aux_invocation(result_2['meter_invocations'])
        self.assertEqual(
            len(aux_flags_list), 1,
            'a real second aux invocation must ship -- the "no repeat notice" '
            'result below must not be explainable by nothing having run',
        )

        log_after_tick_2 = self._log_text(fixture)
        self.assertEqual(
            log_after_tick_2.count('permanently raises reported spend'), 1,
            f'the step-up notice must never repeat, log:\n{log_after_tick_2}',
        )

    def test_failing_cli_call_produces_none_of_notice_sentinel_or_ledger_line(self):
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        _build_failing_completion_shim(os.path.join(fixture['bin_dir'], 'revenium'))

        result = self._tick(fixture, 0)
        self.assertEqual(result['rc'], 0, result['output'])

        log_text = self._log_text(fixture)
        self.assertNotIn(
            'permanently raises reported spend', log_text,
            'a failing CLI call must never produce the step-up notice',
        )

        sentinels = self._sentinel_names(fixture)
        self.assertNotIn('notice-step-up.flag', sentinels, sentinels)

        ledger_path = self._aux_ledger_path(fixture)
        self.assertFalse(
            os.path.exists(ledger_path),
            'a failing CLI call must never append an aux ledger line',
        )

    def test_off_switch_never_produces_the_notice(self):
        fixture = self._setup_fixture(
            [self._one_session()], aux_rows=[self._one_aux_row()],
        )
        result = self._tick(fixture, 0, extra_env={'REVENIUM_AUX_METERING': 'disabled'})
        self.assertEqual(result['rc'], 0, result['output'])

        self.assertEqual(len(self._find_aux_invocation(result['meter_invocations'])), 0)

        log_text = self._log_text(fixture)
        self.assertNotIn('permanently raises reported spend', log_text)

        sentinels = self._sentinel_names(fixture)
        self.assertNotIn('notice-step-up.flag', sentinels, sentinels)


if __name__ == '__main__':
    unittest.main()
