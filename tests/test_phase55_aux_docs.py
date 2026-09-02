"""Phase 55 Plan 04 (D-03/D-11/D-12): assertions that every disclosure the
migration document must carry is actually present, and that diagnose.sh's
new auxiliary section runs and mutates nothing.

Mirrors tests/test_phase28_operator_doc.py's shape: plain file-content
assertions, each carrying a message naming the decision or requirement it
protects and why it matters, so a future failure is self-explaining rather
than a bare predicate.

Two classes:

- `AuxMigrationDocTests` — content assertions against
  `docs/migration-auxiliary-usage.md`.
- `AuxDiagnoseSectionTests` — drives `diagnose.sh` for real against a temp
  `HERMES_HOME`, in the absent-table and present-table arms, and asserts the
  auxiliary section runs and creates nothing.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs' / 'migration-auxiliary-usage.md'
SKILL = ROOT / 'skills' / 'revenium'

from tests._compat_helpers import build_session_model_usage, build_state_db  # noqa: E402


def _section(text, heading_fragment):
    """Return the text of the '## ...' section whose heading contains
    heading_fragment, up to (not including) the next '## ' heading.

    Section-scoped rather than whole-file: a caveat three sections away from
    the figures it should qualify is not a caveat (Plan 04's own read_first
    instruction).
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith('## ') and heading_fragment in line:
            start = i
            break
    assert start is not None, f'no "## " heading contains {heading_fragment!r}'
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith('## '):
            end = j
            break
    return '\n'.join(lines[start:end])


class AuxMigrationDocTests(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text(encoding='utf-8')

    def test_doc_lives_under_docs_not_docs_internal(self):
        # docs/internal/ is gitignored -- the whole reason this document
        # exists is to avoid repeating the loss of the sizing measurement
        # (D-03). Asserted from the path itself so a later move fails this.
        rel = DOC.relative_to(ROOT).as_posix()
        self.assertTrue(
            rel.startswith('docs/') and not rel.startswith('docs/internal/'),
            f'migration document must live in tracked docs/, not the '
            f'gitignored docs/internal/ tree; got {rel}',
        )

    def test_off_switch_is_documented(self):
        for token in ('REVENIUM_AUX_METERING', 'auxMetering'):
            self.assertIn(
                token, self.text,
                f'the document must name {token} as part of the off switch '
                f'(D-03) -- an operator must be able to find the exact '
                f'tunable, not a paraphrase of it',
            )
        section = _section(self.text, 'Switching it off')
        self.assertIn(
            'disabled', section,
            'the off switch section must state the literal value that '
            'turns auxiliary metering off',
        )

    def test_step_up_figures_and_outlier_caveat_share_one_section(self):
        section = _section(self.text, 'The step-up')
        for figure in ('0.4598', '3.0634', '2.0723'):
            self.assertIn(
                figure, section,
                f'the step-up section must carry the measured figure '
                f'{figure} (docs/internal/auxiliary-usage-sizing.md, dated '
                f'2026-08-15) -- searching the whole file instead of this '
                f'section would let the figure exist without its caveat',
            )
        self.assertTrue(
            'near-zero denominator' in section or 'near-zero' in section,
            'the two per-profile outliers must carry their near-zero-'
            'denominator caveat IN THE SAME SECTION as the figures, not '
            'three sections away -- an unqualified outlier reads as a '
            'representative range',
        )
        self.assertIn(
            'not representative', section,
            'the section must say plainly that the outliers are not '
            'representative, not merely imply it',
        )

    def test_first_tick_catchup_states_the_mechanism_not_just_the_effect(self):
        section = _section(self.text, 'first tick is a catch-up')
        self.assertIn(
            'cumulative', section,
            'the first-tick section must name the cumulative counters as '
            'part of the mechanism, so a reader learns WHY, not just that '
            'a catch-up happens',
        )
        self.assertIn(
            'empty', section,
            'the first-tick section must name the empty ledger as the '
            'other half of the mechanism (cumulative counters + an empty '
            'ledger is what produces the catch-up)',
        )

    def test_rule_scope_section_names_all_four_dimensions(self):
        section = _section(self.text, 'Which rules count it')
        for dim in ('AGENT:IS:', 'TASK_TYPE', 'MODEL', 'PROVIDER'):
            self.assertIn(
                dim, section,
                f'the rule-scope section must name {dim} -- D-12 requires '
                f'every scoping consequence be stated, not just the '
                f'TASK_TYPE exclusion',
            )

    def test_roi10_limit_names_phase56_and_states_the_gap(self):
        section = _section(self.text, 'The limit on ROI-10')
        self.assertIn(
            'Phase 56', section,
            'the ROI-10 limit must name Phase 56 as where server-side '
            'counting is confirmed live -- omitting it leaves the gap '
            'silent (D-11)',
        )
        self.assertTrue(
            re.search(r'does not observe|not observe the .*counter', section),
            'the ROI-10 section must state plainly that this phase does '
            'NOT observe the server-side counter moving, only that the '
            'row is emitted in scope',
        )

    def test_aux_ledger_named_and_stated_unbounded(self):
        self.assertIn(
            'revenium-aux.ledger', self.text,
            'the document must name revenium-aux.ledger by its actual '
            'filename, not a paraphrase',
        )
        section = _section(self.text, 'ledger growth')
        self.assertTrue(
            'not pruned' in section or 'without bound' in section,
            'the ledger-growth section must state plainly that the '
            'auxiliary ledger is not pruned (D-16), named here so it is '
            'not discovered later as a surprise',
        )

    def test_unverified_filter_operator_never_asserted(self):
        # A1 (carried from RESEARCH.md): STARTS_WITH/CONTAINS could not be
        # verified anywhere in this repo, which documents only IS/IS_NOT.
        self.assertNotIn(
            'STARTS_WITH', self.text,
            'the document must never assert the unverified STARTS_WITH '
            'filter operator as fact -- it is documented nowhere in this '
            'repo and setup-guardrails.sh --help lists only IS, IS_NOT',
        )
        self.assertNotIn('CONTAINS', self.text)

    def test_closing_section_names_the_invalidating_tests(self):
        section = _section(self.text, 'What would invalidate this')
        for test_file in (
            'tests/test_phase55_auxiliary_metering.py',
            'tests/test_compat_v1_4_meta.py',
        ):
            self.assertIn(
                test_file, section,
                f'the closing section must name {test_file} as one of the '
                f'tests that goes red if this document\'s claims stop '
                f'holding',
            )


class AuxDiagnoseSectionTests(unittest.TestCase):
    """Drives the real diagnose.sh against a temp HERMES_HOME in two arms:
    no state.db at all, and a fixture state.db carrying a session_model_usage
    table with one non-empty-task row and one empty-task (mirror) row.

    Both arms must exit 0, print the auxiliary section header, and create no
    auxiliary state -- the diagnostic must never mutate what it reports on
    (T-55-15).
    """

    STUB_REVENIUM = (
        '#!/usr/bin/env bash\n'
        'exit 0\n'
    )

    def _make_home(self, tmp):
        home = os.path.join(tmp, 'home')
        bindir = os.path.join(home, '.local', 'bin')
        hermes_home = os.path.join(home, '.hermes')
        scripts = os.path.join(hermes_home, 'skills', 'revenium', 'scripts')
        os.makedirs(bindir)
        shutil.copytree(SKILL / 'scripts', scripts)
        stub_path = os.path.join(bindir, 'revenium')
        with open(stub_path, 'w') as fh:
            fh.write(self.STUB_REVENIUM)
        os.chmod(stub_path, 0o755)
        state = os.path.join(hermes_home, 'state', 'revenium')
        env = {
            'HOME': home,
            'PATH': f'{bindir}:/usr/bin:/bin:/usr/sbin:/sbin',
            'HERMES_HOME': hermes_home,
            'HERMES_DEFAULT_HOME': hermes_home,
            'REVENIUM_STATE_DIR': state,
        }
        return hermes_home, scripts, state, env

    def _run(self, scripts, env):
        return subprocess.run(
            ['bash', os.path.join(scripts, 'diagnose.sh')],
            env=env, capture_output=True, text=True, timeout=120,
        )

    def _assert_no_aux_state_created(self, state):
        self.assertFalse(
            os.path.exists(os.path.join(state, 'revenium-aux.ledger')),
            'diagnose.sh created revenium-aux.ledger -- a diagnostic must '
            'not mutate the state it is diagnosing',
        )
        self.assertFalse(
            os.path.exists(os.path.join(state, 'markers', '.aux-warn')),
            'diagnose.sh created the .aux-warn sentinel directory -- '
            'section 10 must test for it, never create it',
        )

    def test_absent_table_arm(self):
        tmp = tempfile.mkdtemp(prefix='gsd-aux-diag-')
        try:
            hermes_home, scripts, state, env = self._make_home(tmp)
            # No state.db at all.
            r = self._run(scripts, env)
            self.assertEqual(r.returncode, 0, f'stderr={r.stderr}')
            self.assertIn('AUXILIARY USAGE PASS', r.stdout)
            self.assertIn(
                'no state.db', r.stdout,
                'with no state.db at all, section 10 must say so rather '
                'than silently reporting nothing',
            )
            self._assert_no_aux_state_created(state)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_present_table_arm_shows_both_row_counts(self):
        tmp = tempfile.mkdtemp(prefix='gsd-aux-diag-')
        try:
            hermes_home, scripts, state, env = self._make_home(tmp)
            state_db = os.path.join(hermes_home, 'state.db')
            build_state_db(state_db, [{
                'id': 'sid-doc-test-1', 'model': 'claude-3-opus',
                'source': 'anthropic', 'input_tokens': 10000,
                'output_tokens': 5000, 'cache_read': 0, 'cache_write': 0,
                'reasoning': 0, 'estimated_cost': '5.0', 'api_calls': 5,
                'started_at': 1, 'ended_at': 2, 'billing_provider': 'anthropic',
            }])
            build_session_model_usage(state_db, [
                {
                    'session_id': 'sid-doc-test-1', 'model': 'claude-3-haiku',
                    'billing_provider': 'anthropic',
                    'billing_base_url': 'https://api.anthropic.com',
                    'billing_mode': 'api', 'task': 'approval',
                    'api_call_count': 1, 'input_tokens': 100,
                    'output_tokens': 50, 'estimated_cost_usd': 0.01,
                    'first_seen': 1, 'last_seen': 2,
                },
                {
                    # The empty-task mirror row -- byte-equal to the
                    # sessions row's own totals, per the sizing document's
                    # own worked example.
                    'session_id': 'sid-doc-test-1', 'model': 'claude-3-opus',
                    'billing_provider': 'anthropic',
                    'billing_base_url': 'https://api.anthropic.com',
                    'billing_mode': 'api', 'task': '',
                    'api_call_count': 5, 'input_tokens': 10000,
                    'output_tokens': 5000, 'estimated_cost_usd': 5.0,
                    'first_seen': 1, 'last_seen': 2,
                },
            ])
            r = self._run(scripts, env)
            self.assertEqual(r.returncode, 0, f'stderr={r.stderr}')
            self.assertIn('AUXILIARY USAGE PASS', r.stdout)
            self.assertIn('session_model_usage: present', r.stdout)
            # Both the auxiliary row count and the mirror row count must be
            # visible in the report -- the doubling tell (a near-100% aux
            # share) is only recognisable from the report if both figures
            # are printed side by side, not just implemented internally.
            self.assertIn('aux_rows', r.stdout)
            self.assertIn('mirror_rows', r.stdout)
            self.assertIn('approval', r.stdout)
            self._assert_no_aux_state_created(state)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_taxonomy_line_counts_labels_not_root_keys(self):
        """Greptile P2 on PR #119: the taxonomy line evaluated `len(d)`.

        `aux-taxonomy.json` is `{"labels": {...}}` -- ONE root key -- so a
        healthy install reported `1 labels`, which is precisely backwards
        for a diagnostic an operator reads to confirm the whole vocabulary
        landed: the failure it exists to catch (a truncated taxonomy) and a
        correct install both printed the same number.

        Pinned against the SHIPPED taxonomy rather than a fixture literal,
        so adding a label to `aux-taxonomy.json` cannot silently drift this
        assertion -- the count is read from the same file the script reads.
        """
        expected = len(
            json.loads((SKILL / 'aux-taxonomy.json').read_text())['labels']
        )
        self.assertGreater(
            expected, 1,
            'guard is vacuous if the shipped taxonomy has <=1 label -- with '
            'one label the buggy len(d) and the correct len(d["labels"]) '
            'agree, so this test could not tell them apart',
        )
        tmp = tempfile.mkdtemp(prefix='gsd-aux-diag-tax-')
        try:
            _hermes_home, scripts, state, env = self._make_home(tmp)
            # _make_home copies only scripts/, but AUX_TAXONOMY_FILE resolves
            # to SKILL_DIR/aux-taxonomy.json -- place the REAL shipped file so
            # the assertion above stays pinned to production, not a literal.
            shutil.copy(
                SKILL / 'aux-taxonomy.json',
                os.path.join(os.path.dirname(scripts), 'aux-taxonomy.json'),
            )
            r = self._run(scripts, env)
            self.assertEqual(r.returncode, 0, f'stderr={r.stderr}')
            self.assertIn(
                f'({expected} labels)', r.stdout,
                f'taxonomy line must report {expected} labels (the count '
                f'INSIDE the "labels" object), not the number of root keys',
            )
            self.assertNotIn(
                '(1 labels)', r.stdout,
                'taxonomy line reported "1 labels" -- the root-key count, '
                'the exact regression this pins',
            )
            self._assert_no_aux_state_created(state)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
