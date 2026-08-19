import ast
import io
import re
import tokenize
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Suffixes that can CONTAIN CODE. Prose-only formats (.md, .txt) are excluded
# entirely — a markdown file cannot write a config policy, and the whole point
# of this guard's 2026-08-19 revision is that documentation must stay free to
# name the key it is documenting.
CODE_SUFFIXES = {'.sh', '.py', '.json', '.yml', '.yaml'}

TOKEN = re.compile(r'\bsession_reset\b')


def _strip_hash_comments(text):
    out = []
    for line in text.splitlines():
        # Naive but sufficient: this guard only needs to stop a COMMENT from
        # tripping it. A '#' inside a string on a code line leaves the code
        # portion intact, which still gets scanned.
        stripped = line.split('#', 1)[0] if line.lstrip().startswith('#') else line
        out.append(stripped)
    return '\n'.join(out)


def _strip_python_prose(text):
    """Remove comments and DOCSTRINGS from Python source — nothing else.

    Deliberately not "strip every triple-quoted string": a triple-quoted YAML
    template assigned to a variable is a plausible way to WRITE a policy, and
    must stay in scope. Only expression-statement strings (module, class and
    function docstrings) are prose, and only those are removed.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text

    prose_lines = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, 'body', None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            prose_lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))

    lines = text.splitlines()
    kept = [('' if i + 1 in prose_lines else l) for i, l in enumerate(lines)]
    text = '\n'.join(kept)

    try:
        out = []
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type != tokenize.COMMENT:
                out.append(tok.string)
        return ' '.join(out)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return text


class Phase29NoSessionResetChangeTests(unittest.TestCase):
    def test_no_session_reset_token_in_shipped_code(self):
        # ROADMAP.md Phase 29 success criterion 9 and the "Rejected: setting
        # session_reset.mode to idle/both" paragraph: this phase buys
        # interactive-session attribution by registering hooks Hermes already
        # fires (on_session_finalize, post_llm_call), explicitly INSTEAD OF
        # forcing a session_reset policy change that would make conversations
        # lose context on reset. This test pins that absence-of-change claim
        # with a repository-scoped assertion rather than by inspection.
        #
        # REVISED 2026-08-19 (PR #62), twice.
        #
        # v1 matched the bare token in every shipped file, so it fired on prose
        # that merely EXPLAINS the rejected option. It forced two production
        # docstrings to be reworded to "session-reset" — not the real config
        # key — making the rationale unfindable by grep for the thing it is
        # about. A guard that makes production docs lie costs more than it
        # protects.
        #
        # v2 tried to match WRITE SHAPES (`^session_reset:` / quoted key).
        # Review killed it, correctly, on both sides at once: it MISSED inline
        # YAML (`{session_reset: {mode: both}}`, and any mid-line key) while
        # still FLAGGING ordinary reads (`cfg.get('session_reset')`,
        # `cfg['session_reset'] == x`) — recreating the very pressure to
        # obscure the identifier that v1 caused.
        #
        # v3 stops trying to infer write-versus-read from syntax, which is not
        # reliably possible. The rule is now positional: the token must not
        # appear in shipped CODE at all; comments, Python docstrings, and
        # prose-only files are free to name it.
        #
        # Reads are IN SCOPE on purpose. This skill touches session_reset
        # nowhere today, so any code reference — read or write — is a
        # deliberate change in its relationship to that key and should force a
        # conversation. That is what a guard is for. The pressure v1 created is
        # gone because prose is now exempt, not because reads were carved out.
        offenders = []
        for path in ROOT.rglob('*'):
            if not path.is_file() or path.suffix not in CODE_SUFFIXES:
                continue
            if path.name == 'test_phase29_no_session_reset_change.py':
                continue
            rel = path.relative_to(ROOT)
            # .planning/ is internal planning state that legitimately quotes
            # the key while explaining and rejecting it.
            if rel.parts and rel.parts[0] == '.planning':
                continue
            text = path.read_text(errors='ignore')
            text = (_strip_python_prose(text) if path.suffix == '.py'
                    else _strip_hash_comments(text))
            if TOKEN.search(text):
                offenders.append(str(rel))
        self.assertEqual(offenders, [],
                         f'session_reset appears in shipped code: {offenders}. '
                         'Prose (comments, docstrings, .md/.txt) may name it '
                         'freely; code may not touch it at all.')


if __name__ == '__main__':
    unittest.main()
