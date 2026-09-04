"""Phase 57 Plan 02 (SSE-02): coverage-shape guard for
docs/wire-contract-audit-2.20.0.md.

This module asserts the audit's COVERAGE SHAPE only: that every one of
D-10's eight verbs is present under its own `###` subsection, that every
such subsection carries exactly one of the three D-09 verdict words, that
every *unverifiable* subsection states both a reason and what would be
needed to verify it, that every *compatible* subsection cites a `/v2/api/`
path and a schema name, that CLI-derived evidence in `## Scope` names a
version (guarding Pitfall 4), and that the D-03 marker-path row names all
four `--operation-type` emission sites.

Asserting the audit's CONCLUSIONS -- whether a given verb really is
compatible, or whether the `guardrails budget-rules list` circumstantial
mapping is correct -- is deliberately OUT OF SCOPE for this module. A test
that agreed with the document about what the server accepts would be this
project's own fixture-fidelity failure mode (four test modules, a golden
argv fixture, and a CLI double all agreeing with each other, none of them
able to validate a server-side enum) recurring one level up, against a
document instead of an argv shape. Every assertion below checks that a
claim was MADE with the right shape of evidence; none checks that the claim
is true.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs' / 'wire-contract-audit-2.20.0.md'

# The eight verbs D-10 names, in the exact backtick-wrapped heading form this
# document uses for its per-verb `###` subsections.
D10_VERB_HEADINGS = [
    '`jobs create`',
    '`jobs outcome`',
    '`jobs outcome-update`',
    '`meter completion`',
    '`meter tool-event`',
    '`guardrails enforcement-rules get`',
    '`guardrails budget-rules list`',
    '`guardrails enforcement-events list`',
]

VERDICT_WORDS = ('compatible', 'discrepancy', 'unverifiable')

# The four --operation-type emission sites D-03 must name, at their CURRENT
# (post-Phase-57-Plan-01) line numbers -- the plan's own planning-time
# literals (hermes-report.sh:1246/3254/3420) shifted after Plan 01's comment
# insertions, the same shift Plan 01's own SoleOtherEmitterTests had to
# correct for. This test asserts the numbers that are actually true of the
# tree today, not the plan's stale draft.
D03_EMISSION_SITES = (
    'hermes-report.sh:1248',
    'hermes-report.sh:3256',
    'hermes-report.sh:3422',
    'api-event-report.sh:1457',
)


def _all_subsections(text):
    """Return an ordered list of (heading_text, body) for every `### `
    subsection in text, body running up to (not including) the next `### `
    or `## ` heading.

    Section-scoped rather than whole-file: a verdict word appearing three
    sections away from the row it should describe is not evidence for that
    row (mirrors tests/test_phase55_aux_docs.py's own `_section()` idiom,
    adapted from `## ` to `### ` since this document's per-row content lives
    one heading level deeper).
    """
    lines = text.splitlines()
    out = []
    start = None
    heading = None
    for i, line in enumerate(lines):
        if line.startswith('### '):
            if start is not None:
                out.append((heading, '\n'.join(lines[start:i])))
            start = i
            heading = line[len('### '):].strip()
    if start is not None:
        out.append((heading, '\n'.join(lines[start:])))
    return out


def _section(text, heading_fragment, level='## '):
    """Return the text of the section whose heading (at the given level)
    contains heading_fragment, up to (not including) the next heading at
    that same level.
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith(level) and heading_fragment in line:
            start = i
            break
    assert start is not None, f'no {level!r} heading contains {heading_fragment!r}'
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith(level):
            end = j
            break
    return '\n'.join(lines[start:end])


def _verdict_words_in(body):
    """Return the set of D-09 verdict words present as whole words in body,
    with markdown line-wrap whitespace normalised first so a phrase split
    across a rendered line break is still found."""
    norm = re.sub(r'\s+', ' ', body)
    return {w for w in VERDICT_WORDS if re.search(r'\b' + w + r'\b', norm)}


class WireAuditCoverageShapeTests(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text(encoding='utf-8')
        self.subsections = _all_subsections(self.text)
        self.verb_sections = {
            heading: body
            for heading, body in self.subsections
            if heading in D10_VERB_HEADINGS
        }

    def test_all_eight_audited_verbs_appear(self):
        # Set membership only -- the SSE-02 ordering edge decision states
        # order is documentary, not a test failure (57-02-PLAN.md).
        present = set(self.verb_sections.keys())
        missing = set(D10_VERB_HEADINGS) - present
        self.assertFalse(
            missing,
            f'D-10 names eight verbs; missing ### subsection(s) for: '
            f'{sorted(missing)} -- every audited request must carry a row, '
            f'never be dropped for lacking a schema (D-09)',
        )

    def test_every_verdict_is_one_of_three(self):
        for heading in D10_VERB_HEADINGS:
            body = self.verb_sections[heading]
            found = _verdict_words_in(body)
            self.assertEqual(
                len(found), 1,
                f'### {heading} must carry exactly one of the three D-09 '
                f'verdict words (compatible / discrepancy / unverifiable); '
                f'found {sorted(found)} -- a row with zero or two verdict '
                f'words cannot be read unambiguously',
            )

    def test_every_unverifiable_row_states_a_reason(self):
        unverifiable_headings = [
            h for h in D10_VERB_HEADINGS
            if _verdict_words_in(self.verb_sections[h]) == {'unverifiable'}
        ]
        # RESEARCH.md's own exhaustive path enumeration found the metering
        # ingest surface (meter completion, meter tool-event) absent from
        # all 219 paths, and CONTEXT.md/57-02-PLAN.md's own edge decision
        # scores guardrails budget-rules list unverifiable rather than a
        # bare match on circumstantial evidence -- so at least these three
        # rows must land here. This checks presence, not any OTHER verb's
        # verdict value (which would be a conclusion, not a shape).
        self.assertGreaterEqual(
            len(unverifiable_headings), 3,
            f'expected at least 3 unverifiable rows (meter completion, '
            f'meter tool-event, guardrails budget-rules list per the '
            f'plan\'s own D-09 edge reasoning); found '
            f'{sorted(unverifiable_headings)}',
        )
        for heading in unverifiable_headings:
            norm = re.sub(r'\s+', ' ', self.verb_sections[heading])
            self.assertRegex(
                norm, r'[Rr]eason',
                f'### {heading} is verdict=unverifiable but states no '
                f'reason -- D-09 requires the reason be stated plainly, '
                f'never a bare "unverifiable" with nothing else',
            )
            self.assertRegex(
                norm, r'[Ww]hat would be needed',
                f'### {heading} is verdict=unverifiable but does not state '
                f'what would be needed to verify it -- D-09 requires both '
                f'halves, not just the reason',
            )

    def test_every_compatible_row_cites_a_path_and_schema(self):
        compatible_headings = [
            h for h in D10_VERB_HEADINGS
            if _verdict_words_in(self.verb_sections[h]) == {'compatible'}
        ]
        self.assertTrue(
            compatible_headings,
            'expected at least one compatible row; found none -- either '
            'the audit found nothing compatible (surprising given 6/8 '
            'verbs have a directly-named OAS path) or the verdict words '
            'were not written as expected',
        )
        for heading in compatible_headings:
            body = self.verb_sections[heading]
            self.assertRegex(
                body, r'/v2/api/',
                f'### {heading} is verdict=compatible but cites no '
                f'/v2/api/ path -- D-08 requires the OAS path be named for '
                f'a compatible verdict',
            )
            self.assertRegex(
                body, r'\w+(?:Resource|Payload|_Read)\b',
                f'### {heading} is verdict=compatible but cites no schema '
                f'name (expected something ending in Resource, Payload, or '
                f'_Read) -- D-08 requires the schema be named for a '
                f'compatible verdict',
            )

    def test_cli_derived_evidence_names_a_version(self):
        scope = _section(self.text, 'Scope', level='## ')
        self.assertRegex(
            scope, r'\b\d+\.\d+\.\d+\b',
            'the ## Scope section must name a semantic-version string for '
            'the revenium CLI every --help-derived claim in this document '
            'was captured against -- an unversioned help capture is itself '
            'an unpinned claim (RESEARCH.md Pitfall 4), the same failure '
            'mode this phase exists to correct, one level up',
        )
        self.assertIn(
            '1.5.0', scope,
            'the CLI version named in ## Scope must be 1.5.0 -- the '
            'confirmed-current field version (docs/comprehensive-roi-proof.md'
            ':63,482 records the multiplex VM at the same version); a stale '
            '1.4.0 capture presented as current would misdescribe the '
            'flag set actually in the field',
        )

    def test_marker_path_row_names_all_four_emission_sites(self):
        d03 = None
        for heading, body in self.subsections:
            if heading.startswith('The marker-driven operationType sites'):
                d03 = body
                break
        self.assertIsNotNone(
            d03,
            'expected a "### The marker-driven operationType sites (D-03)" '
            'subsection recording, not guarding, every --operation-type '
            'emission site',
        )
        for site in D03_EMISSION_SITES:
            self.assertIn(
                site, d03,
                f'D-03 section must name emission site {site!r} by file '
                f'and line -- these are the CURRENT (post-Plan-01) line '
                f'numbers; api-event-report.sh:1457 in particular is named '
                f'in neither 57-CONTEXT.md nor 57-RESEARCH.md and was '
                f'found during planning, so its omission here would '
                f'silently lose a call site the phase already knows about',
            )


if __name__ == '__main__':
    unittest.main()
