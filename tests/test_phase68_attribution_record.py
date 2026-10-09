"""Guards for the tracked Phase 68 record, docs/job-completion-attribution.md.

Three classes. RecordShapeTests pins the skeleton (title, back link, the six
headings in order, three verdict rows) and never the conclusion, so the
verdicts can change as later plans fill them in. PreRegistrationTests derives
every pre-registered number from the harness constant, so the record and the
code that applies the rule cannot drift apart. RecordRedactionTests is
shape-only: the corpus deny-list is never committed, so it cannot be tested
here; it runs against the data-bearing record from plan 06 on.
"""

from __future__ import annotations

import importlib
import json
import re
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD_PATH = ROOT / 'docs' / 'job-completion-attribution.md'
SCRATCH_GATE = (ROOT / '.planning' / 'phases' / '68-job-completion-attribution'
                / 'scratch' / 'prereg-gate.json')

harness = importlib.import_module('tests.job_attribution_harness')

H1 = '# Does a metered completion reach the right job? The Phase 68 measurement'
HEADINGS = (
    '## Verdict, up front — every criterion, in one table',
    '## The 3.2% was a marker count, not an attribution rate',
    '## The legacy reporter now requires positive root evidence',
    '## Pre-registered fix gate',
    '## Judge protocol',
    '## Measurement protocol',
)


def _section(text, heading, level='## '):
    """The text under `heading`, up to the next heading at the same or a
    shallower level. Copied by value from the Phase 67 contract test."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i
            break
    assert start is not None, f'no heading {heading!r}'
    depth = len(level.rstrip())
    end = len(lines)
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if (line.startswith('#')
                and len(line) - len(line.lstrip('#')) <= depth
                and line.lstrip('#').startswith(' ')):
            end = j
            break
    return '\n'.join(lines[start:end])


def _flat(text):
    return ' '.join(text.split())


class RecordShapeTests(unittest.TestCase):
    """The record exists and keeps its skeleton. Shape only."""

    @classmethod
    def setUpClass(cls):
        cls.text = RECORD_PATH.read_text(encoding='utf-8')
        cls.lines = cls.text.splitlines()

    def test_opens_with_the_title_and_a_back_link(self):
        self.assertEqual(self.lines[0], H1)
        self.assertIn('[← Back to the docs index](README.md)', self.lines[:5])

    def test_the_six_headings_exist_in_order(self):
        positions = []
        for heading in HEADINGS:
            self.assertIn(heading, self.lines)
            positions.append(self.lines.index(heading))
        self.assertEqual(positions, sorted(positions))

    def test_verdict_table_has_exactly_three_sourced_rows(self):
        rows = _section(self.text, HEADINGS[0]).splitlines()
        sources = []
        for line in rows:
            m = re.match(
                r'^\|\s*\d+\s*\|.*\|\s*([^|]+?)\s*\|[^|]*\|\s*$', line)
            if m:
                sources.append(m.group(1))
        self.assertEqual(sources, [
            'ROADMAP criterion 1, restated',
            'ROADMAP criterion 2',
            'ROADMAP criterion 3',
        ])

    def test_the_denominator_correction_is_stated(self):
        body = _flat(_section(self.text, HEADINGS[1]))
        for needle in ('78 of 2,424', 'agentic_job_id', 'owning_job_id',
                       '97.14%', '$285.80 of $294.22', '40e008a'):
            self.assertIn(needle, body)

    def test_the_root_gate_section_cites_the_plan_commit(self):
        body = _flat(_section(self.text, HEADINGS[2]))
        self.assertIn('ab0b02d', body)
        self.assertIn('withhold the dimension, never the event', body)


class PreRegistrationTests(unittest.TestCase):
    """Every pre-registered number is derived from a harness constant."""

    @classmethod
    def setUpClass(cls):
        cls.text = RECORD_PATH.read_text(encoding='utf-8')
        cls.gate = _section(cls.text, '## Pre-registered fix gate')
        cls.judge = _section(cls.text, '## Judge protocol')
        cls.measure = _section(cls.text, '## Measurement protocol')

    def test_the_gate_threshold_is_a_fraction(self):
        self.assertIsInstance(harness.GATE_THRESHOLD, Fraction)

    def test_the_gate_threshold_is_one_hundredth(self):
        self.assertEqual(harness.GATE_THRESHOLD, Fraction(1, 100))

    @unittest.skipUnless(SCRATCH_GATE.exists(),
                         'the gitignored pre-registration file is not here')
    def test_the_gate_threshold_equals_the_preregistration_file(self):
        recorded = json.loads(SCRATCH_GATE.read_text())
        self.assertEqual(harness.GATE_THRESHOLD,
                         Fraction(str(recorded['threshold'])))
        self.assertEqual(recorded['comparator'], '>=')

    def test_the_threshold_is_stated_as_a_fraction_and_as_a_percent(self):
        flat = _flat(self.gate)
        threshold = harness.GATE_THRESHOLD
        self.assertIn(f'{threshold.numerator}/{threshold.denominator}', flat)
        self.assertIn(harness.display_pct(threshold), flat)

    def test_the_comparator_is_stated_in_words(self):
        self.assertIn('greater than or equal to', _flat(self.gate))

    def test_the_section_says_it_precedes_every_datum(self):
        opening = _flat(self.gate.split('###')[0])
        self.assertIn('committed before any data in this phase was read',
                      opening)
        self.assertIn('nothing in it changes after a result is seen', opening)

    def test_the_gate_names_its_quantity_and_denominator(self):
        flat = _flat(self.gate)
        for needle in ('exact fractions', 'half-even',
                       'named-cause', 'lower bound', 'same pull'):
            self.assertIn(needle, flat)

    def test_both_judge_slugs_are_stated(self):
        for slug in (harness.JUDGE_A_MODEL, harness.JUDGE_B_MODEL):
            self.assertIn(slug, self.judge)

    def test_the_full_prompt_template_is_verbatim(self):
        self.assertIn(harness.JUDGE_PROMPT_TEMPLATE, self.judge)

    def test_the_caps_are_stated(self):
        flat = _flat(self.judge)
        self.assertIn(f'{harness.MESSAGE_CHAR_CAP} characters', flat)
        self.assertIn(f'${harness.SPEND_CAP_USD}', flat)
        self.assertIn(f'{harness.MAX_CALLS} calls', flat)

    def test_the_judge_protocol_names_every_bucket(self):
        flat = _flat(self.judge)
        for needle in ('agreed', 'disagree', 'unstable', 'invalid',
                       'served-model-mismatch', 'forward', 'reversed',
                       'kappa', 'lower bound', 'upper bound'):
            self.assertIn(needle, flat)

    def test_the_measurement_protocol_names_every_template(self):
        for name in harness.REMOTE_COMMAND_TEMPLATES:
            self.assertIn(f'`{name}`', self.measure)


class RecordRedactionTests(unittest.TestCase):
    """Shape-only redaction. The deny-list of operator-named tokens is
    derived from pulled data and is never committed, so name-awareness is
    enforced by the harness `audit` verb against the data-bearing record."""

    @classmethod
    def setUpClass(cls):
        cls.text = RECORD_PATH.read_text(encoding='utf-8')

    def _hits(self, pattern, flags=0):
        return re.findall(pattern, self.text, flags)

    def test_no_muid_or_uuid_shaped_token(self):
        self.assertEqual(
            self._hits(r'(?<![0-9A-Za-z])[0-9a-f]{32,33}(?![0-9A-Za-z])'), [])

    def test_no_session_id(self):
        self.assertEqual(self._hits(r'\d{8}_\d{6}_[0-9a-f]+'), [])

    def test_no_job_id_suffix(self):
        self.assertEqual(self._hits(
            r'(?<![A-Za-z0-9_])[a-z0-9]+(?:_[a-z0-9]+)*_[0-9a-f]{4}'
            r'(?![A-Za-z0-9_])'), [])

    def test_no_ip_address_email_or_key_file(self):
        self.assertEqual(
            self._hits(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])'), [])
        self.assertEqual(self._hits(r'[\w.+-]+@[\w-]+\.[\w.]+'), [])
        self.assertEqual(self._hits(r'\.pem'), [])

    def test_no_login_name_or_ssh_path(self):
        self.assertEqual(self._hits(r'ubuntu', re.IGNORECASE), [])
        self.assertNotIn('~/.ssh', self.text)

    def test_no_tenant_id_and_no_shared_tenant_agent(self):
        self.assertEqual(self._hits(r'3By1Ra6|aL7ZRO2'), [])
        self.assertNotIn('Hermes-ent', self.text)

    def test_the_slice_agent_appears_only_in_its_literal(self):
        stripped = self.text.replace('`agent == Jupiter`', '')
        self.assertNotIn('Jupiter', stripped)


if __name__ == '__main__':
    unittest.main()
