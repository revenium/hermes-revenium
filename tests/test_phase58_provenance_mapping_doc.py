"""Phase 58 Plan 01 (SSE-03): coverage-shape guard for
docs/provenance-mapping.md.

This module asserts the document's coverage SHAPE only: that every one of
the nine local evidence classes got a row on both server surfaces, that
each row's value cell states exactly one token from that surface's closed
vocabulary (or one of the two non-value tokens, "not applicable" /
"unmappable"), and that the scope line names what it must. Asserting that
the CHOSEN value is the CORRECT value is deliberately out of scope -- a
test that agreed with the document about the right mapping would be this
project's own fixture-fidelity failure mode recurring one level up. That is
precisely what makes this phase a decision artifact rather than a
machine-checked proof.

Task 1 (tracer) methods: test_both_tables_cover_every_evidence_class,
test_every_row_states_exactly_one_value_token,
test_scope_names_the_spec_build_and_the_deferred_consumer.

Task 2 (gate hardening) methods mechanise the three SSE-03 edge predicates
this plan owns (adjacency, encoding, ordering) plus the no-ranking rule
(D-08/EGV-10) and the [ASSUMED] marker's scope:
test_a_tenth_label_would_fail_the_gate,
test_label_match_is_exact_not_substring,
test_coverage_is_set_membership_not_row_order,
test_no_table_row_ranks_one_label_against_another,
test_assumed_marker_scopes_the_three_unevidenced_labels.
"""

import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs' / 'provenance-mapping.md'
PLUGIN = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier'

# The two closed SERVER provenance vocabularies (58-RESEARCH.md Q3, read
# from the vendored 2.20.0-SNAPSHOT OAS this phase's research session) plus
# the two non-value tokens a cell may state instead of a real enum member.
# These are SERVER-value literals, not the LOCAL label set D-15 governs --
# do not mistake this constant for a D-15 violation. Checking these values
# against Phase 57's pinned spec extract was considered and set aside as a
# scope addition (58-CONTEXT.md § Deferred).
TABLE_A_VOCAB = frozenset({'CUSTOMER_DECLARED', 'MEASURED', 'SIGNED_OFF'})
TABLE_B_VOCAB = frozenset({'MEASURED', 'SELF_REPORTED', 'DERIVED', 'ATTESTED'})
NON_VALUE_TOKENS = frozenset({'not applicable', 'unmappable'})

# The three labels with zero code registrant and zero defining prose
# anywhere in the tree (58-CONTEXT.md, 58-RESEARCH.md Q4) -- fixed by
# decision, not derived from EVIDENCE_CLASSES, because this predicate (has
# a registrant vs. does not) is not represented anywhere in code for the
# test to read.
ASSUMED_LABELS = ('OUTPUT_OBSERVED', 'ASSOCIATIONAL', 'EXPERIMENTAL_IMPACT')

# D-08 / EGV-10: these nine labels are a flat, unordered set. A table row
# must never argue its value by ranking one label against another.
_COMPARATIVES = ('stronger', 'weaker', 'outrank', 'ranks above', 'ranks below')


def _load_classifier():
    """Load classifier.py by path, the verified idiom every existing test
    needing it uses (tests/test_phase53_reportable_class_gate.py:32-38) --
    the module lives off the default Python path and is never imported
    with a bare `import classifier`. Minted sys.modules name
    'phase58_classifier', distinct from the sys.modules name Phase 53's own
    loader uses, since unittest discovery runs every module in one
    interpreter.
    """
    spec = importlib.util.spec_from_file_location(
        'phase58_classifier', str(PLUGIN / 'classifier.py'))
    mod = importlib.util.module_from_spec(spec)
    sys.modules['phase58_classifier'] = mod
    spec.loader.exec_module(mod)
    return mod


def _section(text, fragment, level='### '):
    """Return the text of the section whose heading (at the given level)
    contains fragment, up to (not including) the next heading at that same
    level OR a shallower level (e.g. a `### ` section ends at the next
    `## ` heading too).
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith(level) and fragment in line:
            start = i
            break
    assert start is not None, f'no {level!r} heading contains {fragment!r}'
    shallower = '#' * (len(level.rstrip()) - 1) + ' '
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith(level) or (
            len(level.rstrip()) > 2 and lines[j].startswith(shallower)
            and not lines[j].startswith(level)
        ):
            end = j
            break
    return '\n'.join(lines[start:end])


def _table_rows(section_text):
    """Return an ordered list of cell-tuples for every markdown table row in
    section_text: split each line that starts with a pipe on the pipe
    character, strip each cell, drop the leading and trailing empties, and
    skip the header row and the dash-only separator row.
    """
    rows = []
    for raw_line in section_text.splitlines():
        line = raw_line.strip()
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.split('|')]
        if cells and cells[0] == '':
            cells = cells[1:]
        if cells and cells[-1] == '':
            cells = cells[:-1]
        if not cells:
            continue
        # Header row: first cell is the literal `evidence_class` key name.
        if cells[0].strip('`').strip() == 'evidence_class':
            continue
        # Dash-only separator row (e.g. `---|---|---|---`).
        if all(set(c) <= {'-', ':', ' '} for c in cells):
            continue
        rows.append(tuple(cells))
    return rows


def _row_labels(rows):
    """Return the set of first cells with surrounding backticks and
    whitespace stripped, compared by EXACT equality -- never a substring
    scan of the document.
    """
    return {row[0].strip().strip('`').strip() for row in rows}


def _row_for_label(rows, label):
    for row in rows:
        if row[0].strip().strip('`').strip() == label:
            return row
    raise AssertionError(f'no row found for {label!r}')


def _coverage_gap(expected_labels, rows):
    """Return (missing, unexpected) label sets: members of expected_labels
    with no row, and row keys that are not members of expected_labels.
    """
    labels = _row_labels(rows)
    return set(expected_labels) - labels, labels - set(expected_labels)


def _tokens_in_cell(cell, vocab):
    """Return the set of vocabulary/non-value tokens found in cell as whole
    words (word-boundary regex, case-sensitive for the enum members, exact
    phrase match for the two non-value tokens).
    """
    found = set()
    for token in vocab | NON_VALUE_TOKENS:
        if re.search(r'\b' + re.escape(token) + r'\b', cell):
            found.add(token)
    return found


def _bolded_entries(section_text):
    """Return each blank-line-separated paragraph in section_text that
    opens with a bolded lead-in phrase (`**...**`), with wrapped lines
    joined into one string per paragraph. This is the shape
    `## Boundary cases` and `docs/evidence-class-precedence.md`'s own
    Boundary cases section both use: bolded lead-in followed by prose, no
    sub-headings -- so "one entry" means "one such paragraph."
    """
    entries = []
    for paragraph in section_text.split('\n\n'):
        joined = ' '.join(line.strip() for line in paragraph.strip().splitlines())
        if joined.startswith('**'):
            entries.append(joined)
    return entries


# Plan 58-03 / D-04: the two-member disposition vocabulary `## Falsification
# conditions`' lead-in defines and every `### Falsifier N` subsection reuses
# verbatim. Held as constants, not re-typed per assertion, so a later reword
# of either sentence is a deliberate edit in two places (the doc and this
# test) rather than a silent drift between them.
_DISPOSITION_FATAL = (
    'Disposition: Fatal to this entry — its premise is gone, so the '
    'row must be re-decided rather than amended.'
)
_DISPOSITION_REVISE = (
    'Disposition: Revise before shipping — not fatal to the entry.'
)


class ProvenanceMappingCoverageShapeTests(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text(encoding='utf-8')
        self.classifier = _load_classifier()
        self.evidence_classes = self.classifier.EVIDENCE_CLASSES
        self.table_a_section = _section(self.text, 'Table A')
        self.table_b_section = _section(self.text, 'Table B')
        self.table_a_rows = _table_rows(self.table_a_section)
        self.table_b_rows = _table_rows(self.table_b_section)

    def test_both_tables_cover_every_evidence_class(self):
        for name, rows in (
            ('Table A', self.table_a_rows),
            ('Table B', self.table_b_rows),
        ):
            missing, unexpected = _coverage_gap(self.evidence_classes, rows)
            self.assertFalse(
                missing,
                f'{name}: EVIDENCE_CLASSES member(s) missing a row: '
                f'{sorted(missing)} -- every local evidence class must '
                f'appear on both surfaces, unmappable or not applicable '
                f'stated with reason rather than omitted (D-16)',
            )
            self.assertFalse(
                unexpected,
                f'{name}: row key(s) not present in EVIDENCE_CLASSES: '
                f'{sorted(unexpected)} -- the coverage gate must never '
                f'tolerate a stale or invented label (D-15)',
            )

    def test_every_row_states_exactly_one_value_token(self):
        """Scans ONLY cell index 1, the value cell -- scanning the whole
        row would break on rows whose lossiness cell (index 3) legitimately
        names a second server value as an alternative considered:
        OUTCOME_OBSERVED's lossiness cell names MEASURED, and
        CUSTOMER_CONFIRMED's names SIGNED_OFF. Cell scoping is load-bearing
        here, not incidental.
        """
        for name, rows, vocab in (
            ('Table A', self.table_a_rows, TABLE_A_VOCAB),
            ('Table B', self.table_b_rows, TABLE_B_VOCAB),
        ):
            for row in rows:
                label = row[0].strip().strip('`').strip()
                value_cell = row[1]
                found = _tokens_in_cell(value_cell, vocab)
                self.assertEqual(
                    len(found), 1,
                    f'{name} row {label!r}: value cell {value_cell!r} '
                    f'states {len(found)} vocabulary token(s) '
                    f'({sorted(found)}), expected exactly one (a server '
                    f'enum member, or "not applicable" / "unmappable")',
                )

    def test_scope_names_the_spec_build_and_the_deferred_consumer(self):
        scope = _section(self.text, 'Scope', level='## ')
        self.assertIn(
            '2.20.0-SNAPSHOT', scope,
            'the Scope section must name the spec build this mapping was '
            'derived against (D-14)',
        )
        self.assertIn(
            'Phase 59', scope,
            'the Scope section must name Phase 59 as the first plausible '
            'consumer (D-17)',
        )
        self.assertIn(
            '1.5.0', scope,
            'the Scope section must name the revenium CLI version whose '
            'absent verbs are why nothing consumes this mapping yet (D-17)',
        )

    # -- Task 2: the three edge predicates, the no-ranking rule, and the
    # [ASSUMED] marker's scope --------------------------------------------

    def test_a_tenth_label_would_fail_the_gate(self):
        """The adjacency edge (SSE-03). A future tenth member added to
        EVIDENCE_CLASSES must fail the build until it is mapped on both
        surfaces -- proven here without editing classifier.py, which
        criterion 4 forbids, by feeding the coverage helper a synthetic
        extra label alongside the real, loaded set.
        """
        synthetic_label = 'ZZZ_SYNTHETIC_NOT_A_REAL_LABEL'
        synthetic_set = set(self.evidence_classes) | {synthetic_label}
        for rows in (self.table_a_rows, self.table_b_rows):
            missing, _ = _coverage_gap(synthetic_set, rows)
            self.assertIn(
                synthetic_label, missing,
                'a synthetic tenth label must be reported missing by the '
                'coverage helper -- the gate must be live for a future '
                'label, not merely for the nine known today (D-15)',
            )

    def test_label_match_is_exact_not_substring(self):
        """The encoding edge (SSE-03). EXPERIMENTAL_IMPACT is a proper
        substring of QUASI_EXPERIMENTAL_IMPACT, so a naive `in` scan over
        the document text would report EXPERIMENTAL_IMPACT covered by the
        quasi row even when no EXPERIMENTAL_IMPACT row exists -- the
        coverage gate would pass with a genuinely missing row. This test
        drives the module's OWN _table_rows/_row_labels helpers against an
        in-test fixture table whose only row is the longer label, proving
        the real parser resolves this correctly rather than a second copy
        of it that proves nothing about the parser the real assertions use.
        """
        fixture = (
            '### Table X -- fixture only\n\n'
            '| `evidence_class` | Server provenance value | '
            'Claim-kind rationale | Lossiness / caveat |\n'
            '|---|---|---|---|\n'
            '| `QUASI_EXPERIMENTAL_IMPACT` | `DERIVED` | x | y |\n'
        )
        section = _section(fixture, 'Table X')
        rows = _table_rows(section)
        labels = _row_labels(rows)
        self.assertIn(
            'QUASI_EXPERIMENTAL_IMPACT', labels,
            'the real label must still be found by exact match',
        )
        self.assertNotIn(
            'EXPERIMENTAL_IMPACT', labels,
            'EXPERIMENTAL_IMPACT is a proper substring of '
            'QUASI_EXPERIMENTAL_IMPACT and must NOT register as covered by '
            'that row -- label matching must be exact equality, never a '
            'substring scan',
        )

    def test_coverage_is_set_membership_not_row_order(self):
        """The ordering edge (SSE-03). D-08 forbids ranking these labels,
        so row sequence must carry no semantic weight: the same fixture
        rows, reversed, must produce the identical coverage verdict.
        """
        forward = _coverage_gap(self.evidence_classes, self.table_b_rows)
        reversed_rows = list(reversed(self.table_b_rows))
        backward = _coverage_gap(self.evidence_classes, reversed_rows)
        self.assertEqual(
            forward, backward,
            'reversing row order must not change the coverage verdict -- '
            'coverage is set membership, never row sequence (D-08)',
        )

    def test_no_table_row_ranks_one_label_against_another(self):
        """The no-ranking rule (D-08/EGV-10), in prose. Scoped to
        pipe-prefixed lines only, NOT the whole document: the surrounding
        prose legitimately needs comparative language when it reproduces
        D-01's own considered-and-rejected reasoning about how a server
        value would read (e.g. "stronger" appearing in a sentence about why
        a value was NOT chosen that way). A whole-file ban would make that
        argument unwritable. Table rows themselves must never carry that
        language, because a row is a verdict, not an argument.
        """
        pipe_lines = [
            line for line in self.text.splitlines()
            if line.strip().startswith('|')
        ]
        offenders = []
        for line in pipe_lines:
            lowered = line.lower()
            for word in _COMPARATIVES:
                if word in lowered:
                    offenders.append((word, line))
        self.assertFalse(
            offenders,
            f'ranking language found in table row(s): {offenders} -- '
            f'EGV-10 forbids ranking these labels and a table row must '
            f'never argue its value that way',
        )

    def test_assumed_marker_scopes_the_three_unevidenced_labels(self):
        """The three labels with zero code registrant and zero defining
        prose anywhere in the tree must carry the [ASSUMED] marker in their
        rationale cell on BOTH tables. CUSTOMER_CONFIGURED is the positive
        control that keeps this non-vacuous: it has a direct on-point
        registrant comment (valuation.py:324-336) and must NOT carry the
        marker.
        """
        rows_by_table = (
            ('Table A', self.table_a_rows),
            ('Table B', self.table_b_rows),
        )
        for label in ASSUMED_LABELS:
            for name, rows in rows_by_table:
                row = _row_for_label(rows, label)
                self.assertIn(
                    '[ASSUMED]', row[2],
                    f'{name} row {label!r} has no code registrant and no '
                    f'defining prose anywhere in the tree, and must carry '
                    f'the [ASSUMED] marker in its rationale cell',
                )
        for name, rows in rows_by_table:
            row = _row_for_label(rows, 'CUSTOMER_CONFIGURED')
            self.assertNotIn(
                '[ASSUMED]', row[2],
                f'{name} row CUSTOMER_CONFIGURED has a direct on-point '
                f'registrant comment and must NOT carry the [ASSUMED] '
                f'marker -- this is the positive control keeping the '
                f'assertion above non-vacuous',
            )

    # -- Plan 58-03: the D-05 gate, the falsifier dispositions, the empty
    # edge, and the named-not-mapped section -------------------------------

    def test_hard_case_cites_the_gate_and_does_not_enumerate_it(self):
        """The D-05 no-restatement guard. `## The hard case` must point at
        Phase 53's reportability gate by file and line rather than copy its
        membership into prose. The expected member set is loaded off the
        SAME classifier module the label set already comes from -- never a
        literal -- so this guard cannot itself drift from the code rule it
        protects, the same D-15 discipline one level over.

        The threshold is "fewer than three distinct members mentioned",
        not zero: the hard case's own rejected-SELF_REPORTED argument
        legitimately names CUSTOMER_CONFIGURED once, as the counter-example
        where a real reporter exists ("the same reading that makes
        SELF_REPORTED the correct value for CUSTOMER_CONFIGURED in Table
        B"). One incidental mention is not a restatement; enumerating the
        gate's membership would be. Note MODEL_ESTIMATED_DEMO is
        deliberately NOT a member of _REPORTABLE_EVIDENCE_CLASSES -- Phase
        53's gate refuses it -- so the section's own heading, which names
        the label, can never itself trip this assertion.
        """
        hard_case = _section(self.text, 'The hard case', level='## ')
        self.assertRegex(
            hard_case, r'classifier\.py:\d+',
            'the hard-case section must cite classifier.py by file and '
            'line rather than restate the reportability gate in prose '
            '(D-05)',
        )
        gate_members = self.classifier._REPORTABLE_EVIDENCE_CLASSES
        mentioned = {
            member for member in gate_members
            if re.search(r'\b' + re.escape(member) + r'\b', hard_case)
        }
        self.assertLess(
            len(mentioned), 3,
            f'the hard-case section mentions {len(mentioned)} distinct '
            f'gate member(s) ({sorted(mentioned)}) -- three or more reads '
            f'as enumerating the gate\'s membership rather than citing it '
            f'by file and line (D-05)',
        )

    def test_every_falsifier_states_one_disposition(self):
        """Each `### Falsifier N` subsection under `## Falsification
        conditions` states exactly one `Disposition:` paragraph, and that
        paragraph opens with one of the two exact sentences the section's
        lead-in defines -- compared against those two sentences as module
        constants so a later reword of either is a deliberate edit made in
        both places, never a silent drift between the doc and this test.
        """
        lines = self.text.splitlines()
        starts = [
            i for i, line in enumerate(lines)
            if line.startswith('### Falsifier')
        ]
        self.assertEqual(
            len(starts), 4,
            f'expected exactly four ### Falsifier subsections, found '
            f'{len(starts)}',
        )
        for idx, start in enumerate(starts):
            end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
            for j in range(start + 1, end):
                if lines[j].startswith('## '):
                    end = j
                    break
            subsection = '\n'.join(lines[start:end])
            paragraphs = [
                ' '.join(line.strip() for line in p.strip().splitlines())
                for p in subsection.split('\n\n')
            ]
            disposition_paragraphs = [
                p for p in paragraphs if p.startswith('Disposition:')
            ]
            self.assertEqual(
                len(disposition_paragraphs), 1,
                f'{lines[start]!r} must state exactly one Disposition: '
                f'paragraph, found {len(disposition_paragraphs)}',
            )
            paragraph = disposition_paragraphs[0]
            self.assertTrue(
                paragraph.startswith(_DISPOSITION_FATAL)
                or paragraph.startswith(_DISPOSITION_REVISE),
                f'{lines[start]!r} disposition paragraph does not open '
                f'with either of the two lead-in-defined sentences: '
                f'{paragraph!r}',
            )

    def test_absent_class_is_one_entry_covering_three_shapes(self):
        """The `empty` edge (D-11). Exactly one `## Boundary cases` entry
        concerns the absent-`evidence_class` case, and its body names all
        three record shapes together -- an abstained assessment, a FAILED
        or CANCELLED arc, and a markerless session -- and states the record
        is not emitted. A second entry separately covering one of the same
        three shapes is exactly what D-11 rules out: this test also asserts
        neither of the other two entries mentions any of the three shape
        markers.
        """
        boundary = _section(self.text, 'Boundary cases', level='## ')
        entries = _bolded_entries(boundary)
        self.assertEqual(
            len(entries), 3,
            f'expected exactly three bolded boundary-case entries, found '
            f'{len(entries)}',
        )
        absent_class_entries = [
            e for e in entries if 'evidence_class' in e.split('**')[1]
        ]
        self.assertEqual(
            len(absent_class_entries), 1,
            'expected exactly one boundary entry whose lead-in concerns '
            'the absent-evidence_class case',
        )
        entry = absent_class_entries[0]
        for shape_marker in ('abstain', 'FAILED', 'CANCELLED', 'markerless'):
            self.assertIn(
                shape_marker, entry,
                f'the absent-class entry must name the {shape_marker!r} '
                f'shape',
            )
        self.assertIn(
            'not emitted', entry,
            'the absent-class entry must state that such a record is not '
            'emitted, rather than emitted with a bare or defaulted '
            'provenance',
        )
        other_entries = [e for e in entries if e is not entry]
        for other in other_entries:
            for shape_marker in ('FAILED', 'CANCELLED', 'markerless'):
                self.assertNotIn(
                    shape_marker, other,
                    f'a second boundary entry names {shape_marker!r} -- '
                    f'D-11 requires the three absent-class shapes covered '
                    f'by ONE entry, not scattered across several',
                )

    def test_adjacent_fields_are_named_and_not_mapped(self):
        """D-12. `## Provenance-adjacent fields: named, not mapped` names
        all five server fields and all three local fields, states a
        not-yet-decided disposition, and -- the real assertion here --
        contains zero lines beginning with a pipe character. Every decided
        mapping on this page is a table row; the absence of a table is the
        structural difference between naming a field and deciding it,
        which is why this test checks for the ABSENCE of a shape rather
        than the presence of one.
        """
        adjacent = _section(self.text, 'Provenance-adjacent fields', level='## ')
        for server_field in (
            'declaredBy', 'evidenceUrl', 'recordedBy', 'source', 'reason',
        ):
            self.assertIn(
                server_field, adjacent,
                f'the adjacent-fields section must name {server_field!r}',
            )
        for local_field in ('evaluator', 'evaluator_version', 'model'):
            self.assertIn(
                local_field, adjacent,
                f'the adjacent-fields section must name {local_field!r} as '
                f'a plausible local source',
            )
        self.assertIn(
            'not', adjacent.lower(),
            'the section must contain a not-yet-decided disposition',
        )
        self.assertIn('Phase 59', adjacent)
        self.assertIn('1.5.0', adjacent)
        pipe_lines = [
            line for line in adjacent.splitlines()
            if line.strip().startswith('|')
        ]
        self.assertFalse(
            pipe_lines,
            f'the adjacent-fields section must contain zero pipe-prefixed '
            f'lines (no table) -- found {pipe_lines!r}. Every decided '
            f'mapping on this page is a table row; a table here would '
            f'read as a decision this section explicitly declines to make '
            f'(D-12)',
        )


if __name__ == '__main__':
    unittest.main()
