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

Task 2 (this module's own follow-up commit) hardens the gate further with
the SSE-03 edge predicates and the no-ranking rule -- see that commit's
methods for the adjacency, encoding, and ordering proofs.
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


def _row_for_label(rows, label):
    for row in rows:
        if row[0].strip().strip('`').strip() == label:
            return row
    raise AssertionError(f'no row found for {label!r}')


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


if __name__ == '__main__':
    unittest.main()
