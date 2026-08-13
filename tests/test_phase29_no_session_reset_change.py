import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Same shipped-suffix set test_no_legacy_branding_left scopes to in
# tests/test_repository.py.
SHIPPED_SUFFIXES = {'.md', '.sh', '.py', '.txt', '.json', '.yml', '.yaml'}


class Phase29NoSessionResetChangeTests(unittest.TestCase):
    def test_no_session_reset_token_in_shipped_files(self):
        # ROADMAP.md Phase 29 success criterion 9 and the "Rejected: setting
        # session_reset.mode to idle/both" paragraph: this phase buys
        # interactive-session attribution by registering hooks Hermes already
        # fires (on_session_finalize, post_llm_call), explicitly INSTEAD OF
        # forcing a session_reset policy change that would make conversations
        # lose context on reset. This test pins that absence-of-change claim
        # with a repository-scoped assertion rather than by inspection: if a
        # later change reintroduces a session_reset policy write anywhere in
        # the shipped tree, this test names the offending file(s) instead of
        # letting it land silently.
        #
        # Scope mirrors test_no_legacy_branding_left in test_repository.py:
        # every shipped-suffix file under the repo root, excluding the
        # .planning/ tree (internal planning state that legitimately quotes
        # "session_reset" while explaining and rejecting it — scanning it
        # would flag those meta-references and defeat the guard's purpose)
        # and excluding this test module's own source, which necessarily
        # contains the literal token to describe what it is checking for.
        offenders = []
        for path in ROOT.rglob('*'):
            if not path.is_file():
                continue
            if path.suffix not in SHIPPED_SUFFIXES:
                continue
            if path.name == 'test_phase29_no_session_reset_change.py':
                continue
            rel = path.relative_to(ROOT)
            if rel.parts and rel.parts[0] == '.planning':
                continue
            text = path.read_text(errors='ignore')
            if re.search(r'\bsession_reset\b', text):
                offenders.append(str(rel))
        self.assertEqual(offenders, [],
                          f'found session_reset token in: {offenders}')


if __name__ == '__main__':
    unittest.main()
