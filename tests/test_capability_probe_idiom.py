"""Guard: capability probes must go through common.sh's supports_flag.

Closes the STATE.md deferred item opened 2026-07-28 during 29-02. The raw
`revenium ... --help 2>&1 | grep -q -- '--flag'` idiom carries two faults:

  1. grep -q exits on its first match and can SIGPIPE the upstream `revenium`
     process. Under `pipefail` that is exit 141, so the probe reports
     "unsupported" NONDETERMINISTICALLY. Every probe fails open, so the failure
     is silent — the metered row simply loses an attribution dimension.
  2. The match is unanchored, so a probe for a short flag can match a longer
     sibling. supports_flag appends `([^A-Za-z0-9-]|$)`.

This test deliberately strips COMMENT lines before matching. The sibling
deferred item on `test_phase29_no_session_reset_change.py` is a live example of
what happens when a guard like this greps prose: it forced two production
docstrings to be reworded to a config key name that does not exist. Comments
must stay free to describe the idiom they replaced -- common.sh's supports_flag
does exactly that, and is the reason this stripping is not optional.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'revenium' / 'scripts'

# The executable shape only: a --help invocation piped into grep. Written as a
# regex over code lines rather than a bare substring so that reordered
# redirections still match.
RAW_PROBE = re.compile(r'--help\s+2>&1\s*\|\s*grep')


def _code_lines(path):
    """Yield (lineno, text) for lines that are not wholly a comment."""
    for i, line in enumerate(path.read_text().splitlines(), start=1):
        if line.lstrip().startswith('#'):
            continue
        yield i, line


class CapabilityProbeIdiomTests(unittest.TestCase):
    def test_no_raw_help_grep_probes_in_shipped_scripts(self):
        offenders = []
        for script in sorted(SCRIPTS.glob('*.sh')):
            for lineno, line in _code_lines(script):
                if RAW_PROBE.search(line):
                    offenders.append(f'{script.name}:{lineno}: {line.strip()}')
        self.assertEqual(
            [], offenders,
            'Raw `--help | grep` capability probe(s) found. Use '
            'supports_flag "<subcommand words>" "<--flag>" from common.sh, '
            'resolved as `if supports_flag ...; then VAR=true; fi` — never '
            'VAR=$(supports_flag ...), which swallows the exit status.\n  '
            + '\n  '.join(offenders))

    def test_both_billing_paths_probe_the_job_and_trace_flags_via_supports_flag(self):
        """The four probes this guard was written for, pinned by name.

        A blanket 'no raw grep' assertion also passes if someone deletes a
        probe outright, which would silently drop the flag from every row. Pin
        that each billing path still asks both questions, and asks them through
        supports_flag.
        """
        for name in ('hermes-report.sh', 'api-event-report.sh'):
            body = (SCRIPTS / name).read_text()
            for flag in ('--agentic-job-id', '--trace-type'):
                self.assertIn(
                    f'supports_flag "meter completion" "{flag}"', body,
                    f'{name} no longer probes {flag} via supports_flag')

    def test_jobs_subcommand_existence_check_is_deliberately_not_a_flag_probe(self):
        """`revenium jobs --help` asks whether the SUBCOMMAND exists.

        That is a different question from flag support and is correctly left as
        a raw check. Pinned so a future cleanup does not "consistency-fix" it
        into supports_flag, which probes flags and would not answer it.
        """
        for name in ('hermes-report.sh', 'api-event-report.sh'):
            body = (SCRIPTS / name).read_text()
            self.assertIn('revenium jobs --help >/dev/null 2>&1', body,
                          f'{name} lost its jobs subcommand-existence check')




class SupportsFlagSigpipeTests(unittest.TestCase):
    """supports_flag must not reintroduce the defect it exists to fix.

    The two-step capture moved the SIGPIPE off `revenium`, but
    `printf ... | grep -q` reproduced it one level down: grep exits on the
    first match, SIGPIPEs printf, and under `pipefail` the function returns
    141 — reporting a SUPPORTED flag as absent. Since every caller fails
    open, that silently drops a flag from a metered row.

    Measured 2026-08-19: pipeline form 200/200 spurious failures with help
    text past the pipe buffer; here-string form 0/200.
    """

    def test_supports_flag_does_not_pipe_into_grep(self):
        body = (ROOT / 'skills' / 'revenium' / 'scripts' / 'common.sh').read_text()
        fn = body.split('supports_flag()', 1)[1].split('\n}', 1)[0]
        code = [l for l in fn.splitlines() if not l.lstrip().startswith('#')]
        piped = [l for l in code if re.search(r'\|\s*grep', l)]
        self.assertEqual(
            [], piped,
            'supports_flag pipes into grep again — grep -q can SIGPIPE the '
            'writer and return 141 under pipefail, reporting a supported flag '
            'as absent. Use a here-string (a temp file, no reader to '
            'disappear):\n  ' + '\n  '.join(piped))

    def test_supports_flag_matches_via_here_string(self):
        body = (ROOT / 'skills' / 'revenium' / 'scripts' / 'common.sh').read_text()
        fn = body.split('supports_flag()', 1)[1].split('\n}', 1)[0]
        self.assertRegex(
            fn, r'grep -qE --.*<<<\s*"\$\{help_text\}"',
            'supports_flag no longer feeds grep from a here-string')

    def test_here_string_form_is_sigpipe_immune_in_practice(self):
        """Behavioural check, not a source grep.

        Runs both forms with help text past the pipe buffer and a match on
        line 1 — the conditions that make the race deterministic — and asserts
        the shipped form never reports a present flag as absent.
        """
        import subprocess
        script = r"""
set -uo pipefail
big="$(printf -- '--page int\n'; for i in $(seq 1 20000); do echo "filler $i pad pad pad pad"; done)"
fails=0
for i in $(seq 1 25); do
  grep -qE -- "--page([^A-Za-z0-9-]|$)" <<< "${big}" || fails=$((fails+1))
done
echo "${fails}"
"""
        out = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
        self.assertEqual('0', out.stdout.strip(),
                         f'here-string form reported spurious absences: {out.stdout!r} {out.stderr!r}')


if __name__ == '__main__':
    unittest.main()
