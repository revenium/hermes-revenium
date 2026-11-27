"""`reported_input_tokens` adds the cache read back only for OpenAI-family
calls, matched by provider or by a model family token at the start of the
name or right after a `/`, and leaves an empty input exactly as it was.

Runs under every bash it finds (`bash` on PATH and `/bin/bash`, which is
3.2 on macOS) because the reporter ships to hosts with either.
"""
import os
import shutil
import subprocess
import unittest

from tests._compat_helpers import SCRIPTS_DIR

COMMON_SH = SCRIPTS_DIR / 'common.sh'
INPUT = '1000'
CACHE_READ = '4000'
WITH_READ = '5000'


def _shells():
    found = []
    for candidate in ('bash', '/bin/bash'):
        path = shutil.which(candidate) or (candidate if os.path.exists(candidate) else None)
        if path and os.path.realpath(path) not in [os.path.realpath(p) for p in found]:
            found.append(path)
    return found


def _reported(shell, model, provider, input_tokens, cache_read):
    result = subprocess.run(
        [shell, '-c', 'source "$0"; reported_input_tokens "$@"',
         str(COMMON_SH), model, provider, input_tokens, cache_read],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.rstrip('\n')


class ReportedInputTokensTests(unittest.TestCase):
    def assert_reported(self, model, provider, expected, input_tokens=INPUT):
        for shell in _shells():
            with self.subTest(shell=shell, model=model, provider=provider):
                self.assertEqual(
                    _reported(shell, model, provider, input_tokens, CACHE_READ), expected)

    def test_gpt_inside_another_word_on_a_local_provider_is_unchanged(self):
        self.assert_reported('llama-3-70b-gptq', 'local', INPUT)
        self.assert_reported('my-gpt-wrapper', 'custom', INPUT)

    def test_family_token_after_a_routing_prefix_adds_the_read(self):
        self.assert_reported('openai/gpt-5', 'openrouter', WITH_READ)
        self.assert_reported('azure/gpt-4o', 'litellm', WITH_READ)
        self.assert_reported('openai/o3-mini', 'openrouter', WITH_READ)
        self.assert_reported('x-ai/grok-4', 'openrouter', WITH_READ)

    def test_bare_family_name_adds_the_read(self):
        self.assert_reported('gpt-5.1', 'custom', WITH_READ)
        self.assert_reported('o4-mini', 'custom', WITH_READ)

    def test_openai_family_provider_adds_the_read_for_any_model_name(self):
        self.assert_reported('my-deployment', 'azure-openai', WITH_READ)

    def test_claude_and_gemini_are_unchanged_on_an_openai_family_provider(self):
        self.assert_reported('claude-sonnet-4-6', 'openai', INPUT)
        self.assert_reported('gemini-2.5-pro', 'openai', INPUT)

    def test_empty_input_is_sent_unchanged(self):
        self.assert_reported('gpt-5.1', 'openai', '', input_tokens='')


if __name__ == '__main__':
    unittest.main()
