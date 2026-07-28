"""Phase 28 Plan 06 (TRACE-04, D-12/D-13): grep-level invariants locking the
corrected operator reference at
skills/revenium/references/trace-type-uncategorized.md.

Mirrors tests/test_repository.py's test_no_legacy_branding_left file-scan
style: plain file-content assertions, each carrying a message naming the
decision or success criterion it protects, so a future failure is
self-explaining.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'skills' / 'revenium' / 'references' / 'trace-type-uncategorized.md'

# The stale, always-passing diagnostic this plan removed (D-13): a listing of
# the skill bundle's own plugin source directory, which is not a Hermes
# plugin-discovery root and reported healthy throughout the live nine-day
# registration outage. Kept as a single module-level constant so there is
# exactly one place to read the fragment being asserted absent.
STALE_BUNDLE_PATH_FRAGMENT = 'skills/revenium/plugins/revenium-classifier'


class Phase28OperatorDocTests(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text(encoding='utf-8')

    def test_doc_has_no_stale_bundle_listing(self):
        # D-13 / T-28-28: the operator doc must never instruct a health check
        # that passes on a broken install.
        self.assertNotIn(
            STALE_BUNDLE_PATH_FRAGMENT, self.text,
            'the operator doc must never reference the skill-bundle plugin '
            'source path as a health check (D-13)',
        )

    def test_doc_names_registration_check(self):
        # Must-have: the remediation step names plugin-status.sh so an
        # operator can act on its exit code without reading source.
        self.assertGreaterEqual(
            self.text.count('plugin-status.sh'), 2,
            'the operator doc must name plugin-status.sh, the '
            'registration-level check this phase shipped (D-13)',
        )

    def test_doc_lists_all_reason_codes(self):
        # Must-have: the three closed-vocabulary reason literals (D-08,
        # landed in Plans 28-01/28-04) must each be named in the doc.
        for literal in (
            'reason=plugin_unregistered',
            'reason=no_job_classified',
            'reason=marker_lookup_failed',
        ):
            self.assertIn(
                literal, self.text,
                f'the operator doc must document the {literal} reason-code '
                'literal (D-08/D-13)',
            )

    def test_doc_drops_indistinguishable_claim(self):
        # The closing note used to claim telling these cases apart requires
        # source-level investigation, and promised a future release would
        # change that. Both halves are stale as of this phase and must not
        # return (D-13): the marker-file-absent axis is now distinguishable
        # via the reason-code log, and the promise has been kept.
        self.assertNotIn(
            'requires source-level investigation', self.text,
            'the closing note must not claim these cases require '
            'source-level investigation (D-13)',
        )
        self.assertNotIn(
            'future version', self.text,
            'the closing note must not carry a forward-looking promise '
            'this phase already kept (D-13)',
        )

    def test_doc_records_fleet_wrapper_assumption(self):
        # D-12: record (not support) the out-of-tree fleet-wrapper
        # assumption -- per-profile HERMES_HOME repointing -- and the
        # double-reporting hazard of mixing repo-native per-profile cron
        # with such a wrapper.
        self.assertIn(
            'its own Hermes home', self.text,
            'the multi-profile section must record the per-profile '
            'HERMES_HOME repointing pattern a fleet wrapper may use (D-12)',
        )
        self.assertIn(
            'double-report', self.text.lower(),
            'the multi-profile section must record the double-reporting '
            'hazard of mixing fleet-scheduling modes (D-12)',
        )


if __name__ == '__main__':
    unittest.main()
