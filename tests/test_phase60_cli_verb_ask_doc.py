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
