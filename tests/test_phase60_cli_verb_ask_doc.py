"""Phase 60 Plan 01 (SSE-06): coverage-shape guard for
docs/cli-verb-ask.md.

This module asserts the document's coverage SHAPE only: that every one of
the five ask entries D-04 fixes as the ask's scope appears with its own
commitment sub-bullet, that the probed flag spelling and its
never-observed statement appear verbatim and match production source,
that the field shape the `baselines` read verb must return is stated,
that no forward commitment carries a date or a phase number, and that the
document does not quote a credential-shaped or host-shaped string.
Asserting that the ask itself is well-chosen, correctly scoped, or
persuasive is deliberately out of scope -- a test that agreed with the
document about what to ask for would recreate this project's own
fixture-fidelity failure mode one level up. That is precisely what makes
this phase a decision artifact rather than a machine-checked proof.

Task 1 (tracer) method: test_all_five_ask_tokens_appear_in_concrete_ask_section.

Task 2 (gate hardening) methods mechanise D-05/D-06/D-07/D-08 plus the
publication-surface check: test_each_ask_entry_has_exactly_one_commitment,
test_probed_flag_spelling_matches_correction_script,
test_baselines_entry_states_the_field_shape,
test_no_dates_or_phase_numbers_in_commitments,
test_no_credential_or_host_shaped_strings,
test_concrete_ask_section_has_exactly_five_entries.

Task 3 methods assert the two-way cross-reference and the index bullet:
test_ask_docs_cross_reference_each_other, test_readme_links_to_new_doc.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs' / 'cli-verb-ask.md'
SIBLING_DOC = ROOT / 'docs' / 'roi-read-surface-ask.md'
DOCS_README = ROOT / 'docs' / 'README.md'
CORRECT_ASSESSMENT = ROOT / 'skills' / 'revenium' / 'scripts' / 'correct-assessment.sh'
VALUATION_SOURCES = (
    ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'
    / 'valuation_sources.py'
)

# The five ask entries D-04 fixes as this ask's whole scope, verified
# against the installed CLI (`revenium version` -> 1.5.0 (0f5f3a7)) during
# execution of 60-01-PLAN.md. Hardcoded here, with this origin comment, for
# the same reason 58's TABLE_A_VOCAB/TABLE_B_VOCAB constants are
# hardcoded: `.planning/` is gitignored, so the test cannot read the
# locked-decision list the document itself was built from, and this is
# the same reason the document is pinned in the first place.
ASK_TOKENS = (
    'jobs types economics',
    'jobs types baselines',
    'jobs types facts',
    'jobs outcome-update',
    'outcome metrics',
)

# The single bolded lead-in every one of the five ask entries must carry
# exactly once (D-07). Held as a constant, matching the exact string
# written into docs/cli-verb-ask.md by 60-01-PLAN.md Task 1, so a later
# reword of the lead-in is a deliberate edit in two places rather than a
# silent drift between doc and guard.
COMMITMENT_LEAD_IN = '**What changes here the day this ships:**'


def _section(text, fragment, level='## '):
    """Return the text of the section whose heading (at the given level)
    contains fragment, up to (not including) the next heading at that
    same level. Reuses the heading-extraction idiom from
    tests/test_phase58_provenance_mapping_doc.py so an assertion about one
    section cannot be satisfied by a mention somewhere else in the doc.
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith(level) and fragment in line:
            start = i
            break
    assert start is not None, f'no {level!r} heading contains {fragment!r}'
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith(level):
            end = j
            break
    return '\n'.join(lines[start:end])


def _ask_entries(section_text):
    """Split the concrete-ask section into its numbered entries (`1. **...`
    through `5. **...`), each running from its own numbered-item line up
    to (not including) the next one. Anchoring on the numbered-list marker
    means an assertion scoped to "one entry" cannot be satisfied by text
    that merely appears somewhere in the section.
    """
    lines = section_text.splitlines()
    starts = [i for i, line in enumerate(lines) if re.match(r'^\d+\.\s+\*\*', line)]
    entries = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        entries.append('\n'.join(lines[start:end]))
    return entries


def _extract_probed_flag_from_correction_script():
    """Read the flag string `correct-assessment.sh` actually probes for
    optimistic concurrency, straight from production source, so this
    guard checks the document against the thing it describes rather than
    against a copy of itself (D-05, and the project's own recorded
    fixture-fidelity failure mode applied to prose). Anchors on the
    EXPECTED_ENTITY_VERSION_CLI_CAPABLE variable name -- distinct from the
    two earlier `supports_flag "jobs outcome-update" ...` probes in the
    same script (`--reason`, `--metadata`), which gate a different
    variable (OUTCOME_UPDATE_CLI_CAPABLE) entirely.

    Raises AssertionError, rather than falling back to a guessed value, if
    either anchor has moved -- a guard that silently degrades to comparing
    a constant with itself is worse than no guard.
    """
    text = CORRECT_ASSESSMENT.read_text(encoding='utf-8')
    anchor = 'EXPECTED_ENTITY_VERSION_CLI_CAPABLE=false'
    idx = text.find(anchor)
    if idx == -1:
        raise AssertionError(
            f'extraction anchor {anchor!r} not found in '
            f'{CORRECT_ASSESSMENT} -- the probe constant may have moved; '
            f'update this extraction rather than hardcoding a guess',
        )
    window = text[idx:idx + 400]
    match = re.search(r'supports_flag "jobs outcome-update" "(--[a-z0-9-]+)"', window)
    if not match:
        raise AssertionError(
            f'no supports_flag invocation for the version flag found near '
            f'{anchor!r} in {CORRECT_ASSESSMENT} -- the probe call may '
            f'have moved; update this extraction rather than hardcoding a '
            f'guess',
        )
    return match.group(1)


# D-06: the three field names the shipped `_baselines_file_source` returns
# (valuation_sources.py:206-239's docstring). Hardcoded here, with this
# origin comment, rather than parsed from the docstring's inline `{...}`
# literal -- following the precedent module's own convention
# (tests/test_phase58_provenance_mapping_doc.py's TABLE_A_VOCAB /
# TABLE_B_VOCAB) for constants a stable code anchor cannot cheaply supply.
# Verified, not merely asserted: _BASELINES_SOURCE_ANCHOR below is the
# exact substring from that docstring's return-contract sentence, and a
# guard asserts it is still present in valuation_sources.py, so a future
# rename of any of the three fields breaks this test rather than silently
# drifting from the code it describes.
_BASELINES_FIELD_NAMES = ('hourlyRate', 'minutesPerUnit', 'provenance')
# Whitespace-tolerant: the source docstring itself wraps this literal
# across two lines, so a plain substring match on one physical line would
# false-negative on reflow alone.
_BASELINES_SOURCE_ANCHOR_RE = re.compile(
    r'\{"hourlyRate":\s*<float>,\s*"minutesPerUnit":\s*<float>,\s*'
    r'"provenance":\s*<str>,\s*"source":\s*"baselines_file_source"\}'
)

# D-08: applied only to the extracted commitment sub-bullets, never to the
# whole document. The evidence section is REQUIRED to carry a date (the
# probe date) and a version string (`1.5.0 (0f5f3a7)`) -- that dating is
# half of what SSE-06 asks for -- so a whole-file regex would forbid the
# very thing the requirement demands. Only the forward-commitment
# passages are constrained to be mechanical rather than temporal.
_DATE_RE = re.compile(r'\b\d{4}-\d{2}-\d{2}\b')
_PHASE_RE = re.compile(r'\bphase\s*\d+\b', re.IGNORECASE)

# The publication-surface check below is intentionally narrow: an
# IP-address-shaped string, plus the four credential-bearing environment
# variable names this project's own CLI reads (`REVENIUM_API_KEY`,
# `REVENIUM_TEAM_ID`, `REVENIUM_TENANT_ID`, `REVENIUM_API_URL`). It is not
# a general secret scanner.
_IP_RE = re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b')
_CREDENTIAL_ENV_NAMES = (
    'REVENIUM_API_KEY',
    'REVENIUM_TEAM_ID',
    'REVENIUM_TENANT_ID',
    'REVENIUM_API_URL',
)


def _commitment_bullets(entries):
    """Return, for each ask entry, the blank-line-separated paragraph that
    opens with COMMITMENT_LEAD_IN. Raises if an entry has none or more
    than one, since D-07 requires exactly one per entry.
    """
    bullets = []
    for entry in entries:
        paragraphs = [p for p in entry.split('\n\n') if COMMITMENT_LEAD_IN in p]
        bullets.append(paragraphs)
    return bullets


class CliVerbAskCoverageShapeTests(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text(encoding='utf-8')
        self.ask_section = _section(self.text, 'The concrete ask')
        self.entries = _ask_entries(self.ask_section)

    def test_all_five_ask_tokens_appear_in_concrete_ask_section(self):
        missing = [token for token in ASK_TOKENS if token not in self.ask_section]
        self.assertEqual(
            missing, [],
            f'ask token(s) missing from the concrete-ask section: {missing} '
            f'-- every one of the five D-04 asks must name its exact '
            f'verb/flag string in this section',
        )

    def test_concrete_ask_section_has_exactly_five_entries(self):
        self.assertEqual(
            len(self.entries), 5,
            f'expected exactly 5 ask entries, found {len(self.entries)} -- '
            f'more means something was added that D-04 excluded; fewer '
            f'means one was dropped',
        )

    def test_each_ask_entry_has_exactly_one_commitment(self):
        bullets_per_entry = _commitment_bullets(self.entries)
        for i, bullets in enumerate(bullets_per_entry, start=1):
            self.assertEqual(
                len(bullets), 1,
                f'ask entry {i} has {len(bullets)} occurrence(s) of the '
                f'commitment lead-in {COMMITMENT_LEAD_IN!r}, expected '
                f'exactly 1 -- anchoring per entry (not counting 5 over '
                f'the whole section) is the point: an entry with two '
                f'lead-ins and another with none would pass a naive count',
            )

    def test_probed_flag_spelling_matches_correction_script(self):
        probed = _extract_probed_flag_from_correction_script()
        self.assertIn(
            probed, self.text,
            f'probed flag spelling {probed!r} (extracted from '
            f'{CORRECT_ASSESSMENT}) does not appear verbatim in '
            f'{DOC} -- the document has drifted from the probe it '
            f'describes',
        )
        guessed_section = _section(self.text, 'The one string we are guessing')
        self.assertIn(
            probed, guessed_section,
            f'probed flag spelling {probed!r} does not appear in the '
            f'"The one string we are guessing" section',
        )
        self.assertIn(
            'never been observed',
            guessed_section,
            'the "never observed on a real --help" statement is missing '
            'from the same section as the probed flag spelling',
        )

    def test_baselines_entry_states_the_field_shape(self):
        source_text = VALUATION_SOURCES.read_text(encoding='utf-8')
        self.assertRegex(
            source_text, _BASELINES_SOURCE_ANCHOR_RE,
            f'extraction anchor for the baselines field shape not found in '
            f'{VALUATION_SOURCES} -- the return-contract docstring may '
            f'have moved; update _BASELINES_FIELD_NAMES rather than '
            f'trusting a stale hardcode',
        )
        baselines_entry = next(
            (e for e in self.entries if 'jobs types baselines' in e), None,
        )
        self.assertIsNotNone(
            baselines_entry, 'no ask entry names `jobs types baselines`',
        )
        missing = [
            name for name in _BASELINES_FIELD_NAMES
            if name not in baselines_entry
        ]
        self.assertEqual(
            missing, [],
            f'field name(s) missing from the `baselines` ask entry: '
            f'{missing} -- D-06 requires the shipped source\'s exact '
            f'return-contract field names to appear so the seam can '
            f'consume whatever ships without a code change',
        )

    def test_no_dates_or_phase_numbers_in_commitments(self):
        bullets_per_entry = _commitment_bullets(self.entries)
        for i, bullets in enumerate(bullets_per_entry, start=1):
            for bullet in bullets:
                date_hits = _DATE_RE.findall(bullet)
                phase_hits = _PHASE_RE.findall(bullet)
                self.assertEqual(
                    date_hits, [],
                    f'ask entry {i}\'s commitment sub-bullet contains a '
                    f'date-shaped string {date_hits} -- D-08 forbids '
                    f'dates in forward commitments (the evidence section '
                    f'is exempt and is checked separately)',
                )
                self.assertEqual(
                    phase_hits, [],
                    f'ask entry {i}\'s commitment sub-bullet contains a '
                    f'phase-number-shaped string {phase_hits} -- D-08 '
                    f'forbids phase numbers in forward commitments',
                )

    def test_no_credential_or_host_shaped_strings(self):
        ip_hits = _IP_RE.findall(self.text)
        self.assertEqual(
            ip_hits, [],
            f'found IP-address-shaped string(s) in {DOC}: {ip_hits} -- '
            f'this document is written to be read outside this '
            f'repository and must not quote a host address',
        )
        env_hits = [name for name in _CREDENTIAL_ENV_NAMES if name in self.text]
        self.assertEqual(
            env_hits, [],
            f'found credential-bearing environment variable name(s) in '
            f'{DOC}: {env_hits}',
        )
