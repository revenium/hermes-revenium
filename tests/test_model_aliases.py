"""REVENIUM_MODEL_ALIASES -- gateway model aliases resolved to the served model.

Hermes behind a gateway such as LiteLLM records the gateway's alias (e.g.
`model-default`) as the session model and the gateway (`custom`) as the
provider, so Revenium receives a model and provider it cannot price. The alias
map rewrites both, on both reporters:

  - hermes-report.sh: `_clean_model_name` (--model) and `_infer_provider`
    (--provider), extracted live and driven as standalone scripts, the way
    tests/test_phase55_aux_edges.py drives `_infer_provider`.
  - api-event-report.sh: `_model_alias`, extracted live from its heredoc and
    exec'd.

The empty default must leave every value exactly as Hermes recorded it.
"""
import os
import subprocess
import tempfile
import unittest

from tests._compat_helpers import SCRIPTS_DIR
from tests.test_phase55_aux_edges import _extract_infer_provider_function

HERMES_REPORT_SH = SCRIPTS_DIR / 'hermes-report.sh'
API_EVENT_REPORT_SH = SCRIPTS_DIR / 'api-event-report.sh'
COMMON_SH = SCRIPTS_DIR / 'common.sh'

ALIASES = 'model-default=anthropic/claude-sonnet-5-5, fast = gemini-3.5-flash'


def _extract_clean_model_name_function(script_text):
    """Same anchor/end-marker shape as _extract_infer_provider_function:
    None, never a partial body, if either anchor has moved."""
    anchor = '_clean_model_name() {'
    start = script_text.find(anchor)
    if start == -1:
        return None
    end_marker = "\nPY\n}\n"
    end = script_text.find(end_marker, start)
    if end == -1:
        return None
    return script_text[start:end + len(end_marker)]


def _run_function(function_body, call, args, aliases):
    script = '#!/usr/bin/env bash\nset -uo pipefail\n' + function_body + \
        '\n' + call + '\n'
    env = dict(os.environ)
    env.pop('REVENIUM_MODEL_ALIASES', None)
    if aliases is not None:
        env['REVENIUM_MODEL_ALIASES'] = aliases
    tmp = tempfile.NamedTemporaryFile('w', suffix='.sh', delete=False)
    try:
        tmp.write(script)
        tmp.close()
        result = subprocess.run(
            ['bash', tmp.name] + list(args),
            capture_output=True, text=True, timeout=10, env=env,
        )
        return result.stdout.strip()
    finally:
        os.unlink(tmp.name)


class HermesReportAliasTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        text = HERMES_REPORT_SH.read_text()
        cls.clean_body = _extract_clean_model_name_function(text)
        cls.infer_body = _extract_infer_provider_function(text)

    def _clean(self, model, aliases):
        return _run_function(self.clean_body, '_clean_model_name "$1"', [model], aliases)

    def _infer(self, model, billing, aliases):
        return _run_function(self.infer_body, '_infer_provider "$1" "$2"', [model, billing], aliases)

    def test_extraction_found_both_functions(self):
        self.assertIsNotNone(self.clean_body, '_clean_model_name extraction failed')
        self.assertIsNotNone(self.infer_body, '_infer_provider extraction failed')

    def test_alias_with_provider_prefix(self):
        self.assertEqual(self._clean('model-default', ALIASES), 'claude-sonnet-5-5')
        self.assertEqual(self._infer('model-default', 'custom', ALIASES), 'anthropic')

    def test_alias_match_is_case_insensitive(self):
        self.assertEqual(self._clean('Model-Default', ALIASES), 'claude-sonnet-5-5')
        self.assertEqual(self._infer('MODEL-DEFAULT', 'custom', ALIASES), 'anthropic')

    def test_bare_target_infers_provider_and_ignores_billing(self):
        # `custom` names the gateway; for an alias it must not win over the
        # provider the target's name implies.
        self.assertEqual(self._clean('fast', ALIASES), 'gemini-3.5-flash')
        self.assertEqual(self._infer('fast', 'custom', ALIASES), 'google')

    def test_unaliased_model_is_unchanged(self):
        self.assertEqual(self._clean('gpt-5.4', ALIASES), 'gpt-5.4')
        self.assertEqual(self._infer('gpt-5.4', 'custom', ALIASES), 'custom')
        self.assertEqual(self._infer('claude-sonnet-5-5', 'anthropic', ALIASES), 'anthropic')

    def test_unset_and_empty_leave_values_as_recorded(self):
        for aliases in (None, ''):
            self.assertEqual(self._clean('model-default', aliases), 'model-default')
            self.assertEqual(self._infer('model-default', 'custom', aliases), 'custom')

    def test_malformed_pairs_are_ignored(self):
        junk = 'nonsense,=anthropic/x,model-default=,,'
        self.assertEqual(self._clean('model-default', junk), 'model-default')
        self.assertEqual(self._infer('model-default', 'custom', junk), 'custom')


class ApiEventReportAliasTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        text = API_EVENT_REPORT_SH.read_text()
        start = text.find('def _model_alias(model):')
        end = text.find('\ndef _resolve_provider(', start)
        cls.source = text[start:end] if start != -1 and end != -1 else None

    def _alias(self, model, aliases):
        self.assertIsNotNone(self.source, '_model_alias extraction failed')
        namespace = {'os': os}
        saved = os.environ.pop('REVENIUM_MODEL_ALIASES', None)
        try:
            if aliases is not None:
                os.environ['REVENIUM_MODEL_ALIASES'] = aliases
            exec(self.source, namespace)
            return namespace['_model_alias'](model)
        finally:
            os.environ.pop('REVENIUM_MODEL_ALIASES', None)
            if saved is not None:
                os.environ['REVENIUM_MODEL_ALIASES'] = saved

    def test_alias_with_provider_prefix(self):
        self.assertEqual(self._alias('model-default', ALIASES), ('anthropic', 'claude-sonnet-5-5'))

    def test_bare_target_has_no_provider(self):
        self.assertEqual(self._alias('FAST', ALIASES), ('', 'gemini-3.5-flash'))

    def test_unaliased_unset_and_malformed_return_none(self):
        self.assertIsNone(self._alias('gpt-5.4', ALIASES))
        self.assertIsNone(self._alias('model-default', None))
        self.assertIsNone(self._alias('model-default', 'model-default='))

    def test_model_source_keeps_the_recorded_provider(self):
        # Only --provider follows the alias; provider_raw (--model-source)
        # must not be reassigned in the row loop.
        text = API_EVENT_REPORT_SH.read_text()
        loop = text[text.find('_aliased = _model_alias(response_model)'):]
        loop = loop[:loop.find('stop_reason = _stop_reason(')]
        self.assertNotIn('provider_raw =', loop)


class CommonDeclarationTests(unittest.TestCase):

    def test_declared_exported_with_empty_default(self):
        self.assertIn(
            'export REVENIUM_MODEL_ALIASES="${REVENIUM_MODEL_ALIASES:-}"',
            COMMON_SH.read_text(),
        )


if __name__ == '__main__':
    unittest.main()
