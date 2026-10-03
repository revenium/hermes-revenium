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
  FailOpenMatrixTests -- BEHAVIOURAL. Proves every shape of "no usable
      vocabulary" (DD-1) collapses to the SAME free-form prompt the real
      builder produces for `{}`, captured in this same run.
  BoundaryUnchangedTests -- BEHAVIOURAL, against the real `valuation.py`.
      Proves `_rate_card_valuation_fixture`'s accept/reject verdicts have
      not moved at all.
  OmissionPathTests -- BEHAVIOURAL, against the real `_validate_assessment`.
      Proves an omitted role is NOT a rejected assessment (DD-3/DD-4).
  WithholdingPreservedTests -- BEHAVIOURAL. Proves the `newly_enabled_work`
      branch names neither the field token nor any card role, even with a
      populated card, through the real top-level builder.
  FidelityAndPlumbingTests -- BEHAVIOURAL. Fidelity asserts against the
      real builder's return value; plumbing drives the real
      `_evaluate_outcome_via_llm` with a stubbed `call_llm` and reads the
      prompt back out of the captured call. Both are written so that
      deleting the vocabulary call from the builder turns them red — see
      this module's own red-on-purpose note at the bottom.
  RealisticCardNoSilentOmissionTests -- BEHAVIOURAL, the arm this whole
      reconciliation is about. A card shaped like the measured reference
      card must offer every one of its distinct roles; expected roles are
      DERIVED from the fixture, never hand-listed.
  CollapsePriceNeutralTests -- BEHAVIOURAL. Proves DD-2's collapse is
      exact: agreement collapses to one literal member, any disagreement
      or unusable amount emits the whole group.
  BoundsTruncationTests -- BEHAVIOURAL. Proves DD-7: an over-budget card
      truncates on an entry boundary, preserves card order, and logs
      exactly one warning carrying counts only, never role text.
  RoundTripClampTests -- BEHAVIOURAL. Proves every listed role round-trips
      `_clamp_assessment_text` at the hoisted bound unchanged.

None of these classes is an impossibility proof — each one exercises live
code paths and would need updating, not just re-running, if the underlying
functions changed shape.

Two fixture-fidelity rules this module follows throughout (this repo's
documented repeated defect — a double must model every call production
makes, and a fixture pins what production SENDS, not what the test
produces):
  1. No test builds the vocabulary block itself and asserts it appears;
     every test asserts against the return value of the real top-level
     builder, or against the prompt captured from the stubbed `call_llm`.
  2. The fail-open baseline is captured from the real builder under `{}`
     in the SAME run, never a hand-copied literal.

RED-ON-PURPOSE DEMONSTRATIONS (done by hand, not part of CI, recorded in
the plan's SUMMARY): deleting the vocabulary call from
`_build_outcome_evaluation_prompt` must turn FidelityAndPlumbingTests red;
lowering `_ROLE_VOCABULARY_BUDGET_CHARS` to 2048 must turn
RealisticCardNoSilentOmissionTests red. If the second demonstration does
NOT go red, that arm is not exercising the omission regression.
"""

import asyncio
import importlib.util
import json
import logging
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


def _load_valuation():
    """Fresh valuation.py by file path -- same idiom, mirrored from
    tests/test_phase45_valuation_boundary.py's own `_load_valuation`."""
    spec = importlib.util.spec_from_file_location(
        'ksu_valuation', str(PLUGIN / 'valuation.py'))
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


class _Recorder:
    """Stub call_llm that records kwargs and returns a scripted content.
    Shape copied from tests/test_phase37_llm_evaluator.py's own _Recorder,
    per this plan's instruction to reuse it verbatim."""

    def __init__(self, content='{}', raises=None):
        self.calls = []
        self.content = content
        self.raises = raises

    def __call__(self, **kw):
        self.calls.append(kw)
        if self.raises:
            raise self.raises
        return {'choices': [{'message': {'content': self.content}}]}


class _CapturingHandler(logging.Handler):
    """Collects LogRecords instead of printing them, so a test can assert
    on exactly which warnings fired without depending on unittest's
    assertNoLogs (added in 3.10; this repo pins no Python minimum)."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


_VOCAB_LEAD_IN = (
    "For the two mechanisms above that ask for a human role, choose "
    "exactly one from this approved list, copied verbatim, or omit "
    "the field: "
)
_TRUNCATION_MARKER = " ... [truncated]"


def _extract_vocabulary_raw_segment(prompt):
    """Return the raw vocabulary text (marker included, if truncated)
    between the lead-in and the next blank line, or None if no vocabulary
    block was emitted at all."""
    start = prompt.find(_VOCAB_LEAD_IN)
    if start == -1:
        return None
    start += len(_VOCAB_LEAD_IN)
    end = prompt.find('\n\n', start)
    return prompt[start:end] if end != -1 else prompt[start:]


def _extract_vocabulary_roles(prompt):
    """Return the list of role strings the prompt actually lists, with the
    truncation marker stripped, or None if no vocabulary block exists."""
    raw = _extract_vocabulary_raw_segment(prompt)
    if raw is None:
        return None
    if raw.endswith(_TRUNCATION_MARKER):
        raw = raw[: -len(_TRUNCATION_MARKER)]
    return raw.split(', ') if raw else []


def _build_realistic_rate_card():
    """Synthetic rate card matching the SHAPE of the measured reference
    card (tenant 3By1Ra6, 2026-10-03) WITHOUT reusing its content: 173
    entries over 57 case-folded distinct roles, every case-variant group
    price-identical, longest key 35 characters. Role names and amounts
    below are invented for this test -- this repo's standing redaction
    discipline for reference-host data forbids pasting real operator role
    names or rates into the repository; the shape is what carries the
    regression, not the content.

    Every base role is exactly 35 characters -- the measured card's
    longest-key length, applied to ALL 57 roles rather than varied shorter
    ones. The real card's average key was shorter than its longest, but
    pinning every synthetic key AT the measured maximum is what makes the
    DD-7 budget-regression demonstration (lowering
    `_ROLE_VOCABULARY_BUDGET_CHARS` to 2048) meaningful: at the maximum
    permitted length the 57-role COLLAPSED vocabulary totals ~2.1KB --
    over a shrunken 2048 budget, comfortably under the shipped 4096 one.
    A shorter average (closer to the real card's own) would fit under
    2048 too, and the demonstration would not go red at all.

    Returns (card, canonical_roles): canonical_roles is the 57 "first
    member in card order" representative of each distinct group, DERIVED
    from the construction below -- never a hand-listed copy -- so the arm
    that asserts against it cannot silently agree with a broken
    implementation.
    """
    role_template = "Synthetic Candidate Role Variant {:02d}"
    base_roles = [role_template.format(i) for i in range(1, 58)]
    assert all(len(role) == 35 for role in base_roles)

    def _variants(name, count):
        pool = [name.title(), name.upper(), name.lower(), name.swapcase()]
        return pool[:count]

    card = {}
    canonical_roles = []
    # 173 = 55 groups of 3 case variants + 2 groups of 4 -- the operator
    # hand-maintaining case variants, same shape the measured card showed.
    for idx, base in enumerate(base_roles):
        count = 4 if idx < 2 else 3
        amount = 100.0 + idx  # every variant in the group shares this amount
        variants = _variants(base, count)
        canonical_roles.append(variants[0])
        for variant in variants:
            card[variant] = amount
    return card, canonical_roles


def _build_oversized_card(n=120):
    """A card with no case-folded duplicates, every key well under the
    60-byte clamp, but far over the 4096-char vocabulary budget in total --
    built to force DD-7's truncation path."""
    return {
        f"Synthetic Truncation Candidate Role Number {i:03d} XYZ": 10.0 + i
        for i in range(n)
    }


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


class FailOpenMatrixTests(unittest.TestCase):
    """DD-1 -- every shape of "no usable vocabulary" must fall back to
    today's free-form prompt, BYTE-IDENTICAL. Compared against the real
    builder's own `{}` output captured in this same run, never a
    hand-copied string."""

    def setUp(self):
        self.c = _load_classifier()
        self.job = {'job_type': 'bug_fix', 'job_name': 'x'}
        self.transcript = 'did some work'
        self.baseline = self.c._build_outcome_evaluation_prompt(
            self.job, self.transcript, {})

    def test_fail_open_matrix(self):
        over_long = 'x' * 61
        shapes = {
            'no rateCard key': {},
            'empty dict': {'rateCard': {}},
            'list': {'rateCard': ['a', 'b']},
            'string': {'rateCard': 'not-a-dict'},
            'none': {'rateCard': None},
            'every key fails the filter': {
                'rateCard': {over_long: 10.0, '': 5.0, 123: 7.0},
            },
        }
        for label, config in shapes.items():
            with self.subTest(label=label):
                prompt = self.c._build_outcome_evaluation_prompt(
                    self.job, self.transcript, config)
                self.assertEqual(self.baseline, prompt)
                self.assertNotIn('[truncated]', prompt)
                self.assertIsNone(_extract_vocabulary_raw_segment(prompt))


class BoundaryUnchangedTests(unittest.TestCase):
    """DD-4 -- the valuation boundary is untouched. Proves the REAL
    `_rate_card_valuation_fixture`'s accept/reject verdicts against live
    code, not a reimplementation of its lookup."""

    def setUp(self):
        self.v = _load_valuation()

    def test_role_the_card_does_not_name_still_abstains_and_logs(self):
        assumptions = {
            'estimated_hours_saved': 2.0, 'assumed_loaded_rate': 100.0,
            'currency': 'USD', 'inferred_role': 'Some Unknown Role',
        }
        config = {'rateCard': {'Known Role': 50.0}}
        with self.assertLogs('revenium_classifier.valuation', level='WARNING') as cm:
            result = self.v._rate_card_valuation_fixture(assumptions, config)
        self.assertIsNone(result)
        self.assertTrue(
            any('no configured rate for role' in m for m in cm.output),
            cm.output,
        )

    def test_named_role_still_prices(self):
        assumptions = {
            'estimated_hours_saved': 2.0, 'assumed_loaded_rate': 100.0,
            'currency': 'USD', 'inferred_role': 'Known Role',
        }
        config = {'rateCard': {'Known Role': 50.0}}
        result = self.v._rate_card_valuation_fixture(assumptions, config)
        self.assertEqual({'estimated_value': 50.0, 'currency': 'USD'}, result)


class OmissionPathTests(unittest.TestCase):
    """DD-3/DD-4 -- role-level abstention is OMITTING the field, not
    rejecting the assessment. Proves against the real
    `_validate_assessment` that an omitted role still yields a record."""

    def setUp(self):
        self.c = _load_classifier()

    def _raw(self, **over):
        raw = {
            'economic_mechanism': 'labor_substitution',
            'inferred_role': 'some role',
            'estimated_hours_saved': 2.5,
            'assumed_loaded_rate': 150.0,
            'currency': 'USD',
            'basis': 'time avoided',
            'confidence': 0.5,
        }
        raw.update(over)
        return raw

    def test_omitted_role_abstains_without_rejecting_the_assessment(self):
        raw = self._raw()
        del raw['inferred_role']
        got = self.c._validate_assessment(raw, {})
        self.assertIsNotNone(got, '_validate_assessment must not reject an omitted role')
        self.assertEqual('', got['assumptions']['inferred_role'])


class WithholdingPreservedTests(unittest.TestCase):
    """classifier.py:685's withholding comment -- the `newly_enabled_work`
    branch must name neither the field token nor any card role, even with
    a populated card."""

    def setUp(self):
        self.c = _load_classifier()
        self.card = {'Role One': 10.0, 'Role Two': 20.0}

    def test_mechanism_block_ignores_the_flag_entirely(self):
        constrained = self.c._mechanism_instruction_block(
            'newly_enabled_work', 40, 500, 'USD', role_vocabulary_constrained=True)
        unconstrained = self.c._mechanism_instruction_block(
            'newly_enabled_work', 40, 500, 'USD', role_vocabulary_constrained=False)
        self.assertEqual(unconstrained, constrained)
        self.assertNotIn('inferred_role', constrained)
        for role in self.card:
            self.assertNotIn(role, constrained)

    def test_full_prompt_keeps_newly_enabled_work_role_free_with_a_populated_card(self):
        prompt = self.c._build_outcome_evaluation_prompt(
            {'job_type': 'x', 'job_name': 'y'}, 'transcript', {'rateCard': self.card})
        start = prompt.index('If economic_mechanism is "newly_enabled_work"')
        end = prompt.index(_VOCAB_LEAD_IN)
        fragment = prompt[start:end]
        self.assertNotIn('inferred_role', fragment)
        for role in self.card:
            self.assertNotIn(role, fragment)


class FidelityAndPlumbingTests(unittest.TestCase):
    """Fidelity: asserts against the return value of the real top-level
    builder. Plumbing: drives the real `_evaluate_outcome_via_llm` with a
    recorder stubbed over `call_llm` and reads the prompt back out of the
    captured `messages` -- the claim that `config` carries the card to the
    prompt through the EXISTING argument."""

    def setUp(self):
        self.c = _load_classifier()

    def test_fidelity_against_real_top_level_builder(self):
        config = {
            'enabled': True, 'evaluator': 'llm', 'currency': 'USD',
            'maxHoursSaved': 40, 'maxLoadedRate': 500,
            'rateCard': {'Fidelity Role A': 10.0, 'Fidelity Role B': 20.0},
        }
        prompt = self.c._build_outcome_evaluation_prompt(
            {'job_type': 'x', 'job_name': 'y'}, 'transcript', config)
        self.assertIn('Fidelity Role A', prompt)
        self.assertIn('Fidelity Role B', prompt)

    def test_plumbing_config_reaches_the_prompt_through_evaluate_outcome_via_llm(self):
        rec = _Recorder(content=json.dumps({
            'economic_mechanism': 'labor_substitution',
            'inferred_role': 'Plumbing Role', 'estimated_hours_saved': 2.0,
            'assumed_loaded_rate': 100.0, 'currency': 'USD',
            'basis': 'x', 'confidence': 0.5,
        }))
        self.c.call_llm = rec
        config = {'currency': 'USD', 'rateCard': {'Plumbing Role': 75.0, 'Other Role': 50.0}}
        asyncio.run(self.c._evaluate_outcome_via_llm(
            {'status': 'SUCCESS', 'job_type': 'x', 'job_name': 'y'},
            'transcript', config))
        self.assertEqual(1, len(rec.calls))
        messages = rec.calls[0]['messages']
        user_prompt = next(m['content'] for m in messages if m['role'] == 'user')
        self.assertIn('Plumbing Role', user_prompt)
        self.assertIn('Other Role', user_prompt)


class RealisticCardNoSilentOmissionTests(unittest.TestCase):
    """The arm the whole reconciliation is about. A card shaped like the
    measured reference card must offer every one of its 57 distinct roles
    -- nothing truncated, nothing collapsed that could change a price, no
    warning logged. Expected roles are DERIVED from the fixture itself."""

    def setUp(self):
        self.c = _load_classifier()

    def test_all_57_distinct_roles_offered_nothing_truncated_no_warning(self):
        card, canonical_roles = _build_realistic_rate_card()
        self.assertEqual(173, len(card))
        self.assertEqual(57, len(canonical_roles))
        self.assertEqual(35, max(len(k) for k in card))

        handler = _CapturingHandler()
        target_logger = logging.getLogger('revenium_classifier')
        target_logger.addHandler(handler)
        try:
            prompt = self.c._build_outcome_evaluation_prompt(
                {'job_type': 'x', 'job_name': 'y'}, 'transcript', {'rateCard': card})
        finally:
            target_logger.removeHandler(handler)

        self.assertNotIn('[truncated]', prompt)
        listed = _extract_vocabulary_roles(prompt)
        self.assertEqual(57, len(listed))
        for role in canonical_roles:
            self.assertEqual(1, prompt.count(role), f'{role!r} must appear exactly once')
        self.assertEqual(
            [], handler.records,
            'no warning may be logged when nothing was truncated',
        )


class CollapsePriceNeutralTests(unittest.TestCase):
    """DD-2 -- a collapse may never change which price is reachable: it
    happens ONLY when every member of a case-folded group has a usable,
    positive, and EQUAL amount; otherwise every member is shown."""

    def setUp(self):
        self.c = _load_classifier()

    def _prompt(self, card):
        return self.c._build_outcome_evaluation_prompt(
            {'job_type': 'x', 'job_name': 'y'}, 'transcript', {'rateCard': card})

    def test_agreeing_group_collapses_to_first_member(self):
        card = {'Agree Role': 50.0, 'AGREE ROLE': 50.0, 'agree role': 50.0}
        prompt = self._prompt(card)
        self.assertEqual(1, prompt.count('Agree Role'))
        self.assertNotIn('AGREE ROLE', prompt)
        self.assertNotIn('agree role', prompt)

    def test_disagreeing_group_emits_every_member(self):
        card = {'Disagree Role': 50.0, 'DISAGREE ROLE': 75.0}
        prompt = self._prompt(card)
        self.assertIn('Disagree Role', prompt)
        self.assertIn('DISAGREE ROLE', prompt)

    def test_unusable_amount_in_group_emits_every_member(self):
        card = {'Unusable Role': 50.0, 'UNUSABLE ROLE': 'not-a-number'}
        prompt = self._prompt(card)
        self.assertIn('Unusable Role', prompt)
        self.assertEqual(1, prompt.count('UNUSABLE ROLE'))

    def test_every_emitted_string_is_a_literal_card_key(self):
        card = {'Lit Role': 1.0, 'LIT ROLE': 2.0, 'Other Role': 3.0}
        prompt = self._prompt(card)
        listed = _extract_vocabulary_roles(prompt)
        for role in listed:
            self.assertIn(role, card)


class BoundsTruncationTests(unittest.TestCase):
    """DD-7 -- an over-budget card truncates on an ENTRY boundary, never
    mid-role-name, preserves card order, and logs exactly one warning
    carrying offered/omitted COUNTS ONLY, never a role name."""

    def setUp(self):
        self.c = _load_classifier()

    def test_oversized_card_truncates_on_entry_boundary_with_one_counts_only_warning(self):
        card = _build_oversized_card()
        handler = _CapturingHandler()
        target_logger = logging.getLogger('revenium_classifier')
        target_logger.addHandler(handler)
        try:
            prompt = self.c._build_outcome_evaluation_prompt(
                {'job_type': 'x', 'job_name': 'y'}, 'transcript', {'rateCard': card})
        finally:
            target_logger.removeHandler(handler)

        raw_segment = _extract_vocabulary_raw_segment(prompt)
        self.assertIsNotNone(raw_segment)
        self.assertTrue(raw_segment.endswith(_TRUNCATION_MARKER))

        listed = _extract_vocabulary_roles(prompt)
        self.assertGreater(len(listed), 0)
        self.assertLess(len(listed), len(card))
        card_keys = list(card.keys())
        self.assertEqual(
            listed, card_keys[:len(listed)],
            'truncation must preserve card order and land on a whole-entry boundary',
        )
        for role in listed:
            self.assertIn(role, card)

        truncation_warnings = [
            r for r in handler.records
            if 'vocabulary truncated' in r.getMessage()
        ]
        self.assertEqual(1, len(truncation_warnings))
        msg = truncation_warnings[0].getMessage()
        self.assertIn('offered=', msg)
        self.assertIn('omitted=', msg)
        for role in card:
            self.assertNotIn(role, msg)


class RoundTripClampTests(unittest.TestCase):
    """Every role the prompt lists survives `_clamp_assessment_text` at the
    hoisted `_INFERRED_ROLE_CLAMP` bound unchanged -- asserted over a card
    mixing eligible and ineligible keys, including keys carrying a pipe and
    a newline."""

    def setUp(self):
        self.c = _load_classifier()

    def test_every_listed_role_round_trips_the_clamp_unchanged(self):
        over_long = 'x' * 61
        pipe_key = 'Role | Injected'
        newline_key = 'Role\nInjected'
        card = {
            'Eligible Role': 10.0,
            over_long: 20.0,
            pipe_key: 30.0,
            newline_key: 40.0,
        }
        prompt = self.c._build_outcome_evaluation_prompt(
            {'job_type': 'x', 'job_name': 'y'}, 'transcript', {'rateCard': card})
        listed = _extract_vocabulary_roles(prompt)
        self.assertEqual(['Eligible Role'], listed)
        self.assertNotIn(over_long, prompt)
        self.assertNotIn(pipe_key, prompt)
        self.assertNotIn('Role\nInjected', prompt)
        for role in listed:
            self.assertEqual(
                role,
                self.c._clamp_assessment_text(role, self.c._INFERRED_ROLE_CLAMP),
            )


if __name__ == '__main__':
    unittest.main()
