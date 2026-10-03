"""quick-261003-ksu — constrain the outcome evaluator's `inferred_role` to
the operator's own rate-card vocabulary, so a role miss stops being a
silent, unfixable abstention.

Every test here runs OFFLINE: no provider, no network, no subprocess other
than the one-time `git show` this module uses to fetch the pre-change
`classifier.py` for the byte-identity baseline (matching
tests/test_phase45_valuation_boundary.py's own OFFLINE convention for
everything else).

Guarantee-class honesty (tests/test_phase44_economic_mechanisms.py's own
docstring convention):

  ClosedVocabularyPromptTests  -- BEHAVIOURAL, against the real top-level
      `_build_outcome_evaluation_prompt`. Proves a populated card's keys
      reach the prompt verbatim, that an unusable card is byte-identical to
      the pre-change prompt (measured from git, not hand-written), and that
      an over-long key is excluded while its siblings survive.

Task 2 (the negative arms -- fail-open, fidelity, plumbing, the realistic
no-silent-omission card, the collapse rule, the truncation budget, and the
round-trip clamp) extends this module; see its own commit for the rest of
the guarantee-class list.

Two fixture-fidelity rules this module follows throughout (this repo's
documented repeated defect — a double must model every call production
makes, and a fixture pins what production SENDS, not what the test
produces):
  1. No test builds the vocabulary block itself and asserts it appears;
     every test asserts against the return value of the real top-level
     builder, or against the prompt captured from the stubbed `call_llm`.
  2. The fail-open baseline is captured from the real builder under `{}`
     in the SAME run, never a hand-copied literal.
"""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'


def _load_classifier():
    """Fresh classifier.py by file path, no package parent, no sys.modules
    registration -- the idiom tests/test_phase44_economic_mechanisms.py's
    and tests/test_phase45_valuation_boundary.py's own `_load_classifier`
    copies both use for the pure-function resolver/prompt tests that need
    no evaluator registration. A fresh module object per call means no
    cross-test state leakage, and classifier.py has no relative imports of
    its own, so no package context is required."""
    spec = importlib.util.spec_from_file_location(
        'ksu_classifier', str(PLUGIN / 'classifier.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_BASELINE_CACHE = {}


def _baseline_classifier():
    """Load classifier.py AS IT WAS at the commit this quick task branched
    from -- the real pre-change module, not a hand-written reimplementation
    of its output (the task's own hard requirement: "do not hand-write the
    expected string"). Resolved via `git merge-base HEAD origin/main`
    rather than a hardcoded sha, so this baseline stays correct even if
    origin/main advances, as long as this branch was forked from it and not
    rebased. Memoized per test process -- the git calls are the only
    subprocess work in this module and need run once.
    """
    if 'mod' in _BASELINE_CACHE:
        return _BASELINE_CACHE['mod']
    base_sha = subprocess.run(
        ['git', 'merge-base', 'HEAD', 'origin/main'],
        cwd=str(ROOT), capture_output=True, text=True, check=True,
    ).stdout.strip()
    source = subprocess.run(
        ['git', 'show', f'{base_sha}:skills/revenium/plugins/revenium-classifier/classifier.py'],
        cwd=str(ROOT), capture_output=True, text=True, check=True,
    ).stdout
    spec = importlib.util.spec_from_loader('ksu_baseline_classifier', loader=None)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['ksu_baseline_classifier'] = mod
    try:
        exec(compile(source, 'baseline_classifier.py', 'exec'), mod.__dict__)
    finally:
        del sys.modules['ksu_baseline_classifier']
    _BASELINE_CACHE['mod'] = mod
    return mod


class ClosedVocabularyPromptTests(unittest.TestCase):
    """Task 1's three founding arms, against the real top-level builder."""

    def setUp(self):
        self.c = _load_classifier()

    def test_populated_card_lists_literal_keys_once_with_verbatim_instruction(self):
        config = {
            'rateCard': {'Alpha Role': 100.0, 'Beta Role': 50.0, 'Gamma Role': 75.0},
            'currency': 'USD', 'maxHoursSaved': 40, 'maxLoadedRate': 500,
        }
        prompt = self.c._build_outcome_evaluation_prompt(
            {'job_type': 'bug_fix', 'job_name': 'x'}, 'transcript', config)
        for role in ('Alpha Role', 'Beta Role', 'Gamma Role'):
            self.assertEqual(1, prompt.count(role), f'{role!r} must appear exactly once')
        self.assertIn('copied verbatim', prompt)
        self.assertIn('omit', prompt.lower())

    def test_empty_config_is_byte_identical_to_pre_change_baseline(self):
        baseline = _baseline_classifier()
        job = {'job_type': 'bug_fix', 'job_name': 'x'}
        transcript = 'did some work'
        expected = baseline._build_outcome_evaluation_prompt(job, transcript, {})
        actual = self.c._build_outcome_evaluation_prompt(job, transcript, {})
        self.assertEqual(expected, actual)

    def test_overlong_key_absent_while_shorter_siblings_present(self):
        over_long = 'x' * 61  # over _INFERRED_ROLE_CLAMP's 60-byte bound
        config = {'rateCard': {over_long: 10.0, 'Short Role': 20.0}}
        prompt = self.c._build_outcome_evaluation_prompt(
            {'job_type': 'bug_fix', 'job_name': 'x'}, 'transcript', config)
        self.assertNotIn(over_long, prompt)
        self.assertIn('Short Role', prompt)


if __name__ == '__main__':
    unittest.main()
