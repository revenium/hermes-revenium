import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Same shipped-suffix set test_no_legacy_branding_left scopes to in
# tests/test_repository.py.
SHIPPED_SUFFIXES = {'.md', '.sh', '.py', '.txt', '.json', '.yml', '.yaml'}

# A session_reset POLICY WRITE, not a mention. Two shapes cover it:
#   ^\s*session_reset\s*:   a YAML key at key position (what a config write
#                           emits, whether by heredoc, echo, or yaml.dump)
#   ['"]session_reset['"]   the key as a QUOTED string, in any language
#
# The quoted arm is deliberately not narrowed to a following `=` or `:`. An
# earlier attempt required one and missed `cfg['session_reset'] = {...}` — the
# single most likely Python write shape — because the `]` sits between. Every
# further shape (`cfg["session_reset"]["mode"] = x`, kwargs, setattr) breaks a
# stricter pattern the same way. Quoting the key is itself the signal; PROSE
# that needs to name it should use backticks, which is the house style anyway.
WRITE_PATTERN = re.compile(
    r'''^[ \t]*session_reset[ \t]*:'''
    r'''|['"]session_reset['"]''',
    re.MULTILINE)


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
        #
        # NARROWED 2026-08-19. This guard originally matched the BARE token
        # `\bsession_reset\b` anywhere in a shipped file, which fired on prose
        # that merely EXPLAINS the rejected option. It forced two production
        # docstrings in revenium-classifier/__init__.py to be reworded to
        # "session-reset" — a spelling that is not the real config key — so the
        # design rationale became unfindable by grep for the thing it is about.
        # A guard that makes production docs lie about an identifier costs more
        # than it protects.
        #
        # The claim being pinned is "this skill never WRITES a session_reset
        # policy", so match the WRITE shapes, not the mention:
        #   - a YAML key at key position:      `  session_reset:`
        #   - a quoted key assigned/mapped:    `'session_reset':`  "session_reset" =
        # Prose remains free to name the key, which is the whole point.
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
            if WRITE_PATTERN.search(text):
                offenders.append(str(rel))
        self.assertEqual(offenders, [],
                          f'found session_reset token in: {offenders}')


if __name__ == '__main__':
    unittest.main()
