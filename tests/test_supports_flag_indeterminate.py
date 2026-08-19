"""supports_flag must not report an INDETERMINATE probe as a confirmed absence.

A probe has three outcomes; the function used to collapse them into two:

    non-empty help, flag absent   -> genuinely unsupported
    non-empty help, flag present  -> supported
    command failed / said nothing -> UNKNOWN

The third was silently reported as "unsupported". Every caller fails open, so
the metered row quietly lost --agentic-job-id / --trace-type / --squad-*, and
the result was byte-indistinguishable from a legitimate older-CLI install.

Measured 2026-08-19 over 8 instrumented full-suite runs: of 513 negative probes
per run, 123 were rc=0 with zero bytes and 9 were rc!=0. Those 132 were not
answers.

RESOLUTION is deliberately unchanged (still fail open) — assuming "supported"
would hand an old CLI a flag it rejects, failing the whole meter call instead of
one dimension. Only the SILENCE changes.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / 'skills' / 'revenium' / 'scripts' / 'common.sh'


def _run_probe(stub_body, subcommand='meter completion', flag='--trace-type'):
    """Source common.sh with a fake `revenium` on PATH and run one probe."""
    with tempfile.TemporaryDirectory(prefix='gsd-probe-') as tmp:
        home = os.path.join(tmp, 'home')
        bin_dir = os.path.join(home, '.local', 'bin')
        os.makedirs(bin_dir)
        stub = os.path.join(bin_dir, 'revenium')
        with open(stub, 'w') as f:
            f.write('#!/usr/bin/env bash\n' + stub_body + '\n')
        os.chmod(stub, 0o755)

        state = os.path.join(tmp, 'state')
        script = (
            f'set -uo pipefail\n'
            f'source "{COMMON}"\n'
            f'ensure_path\n'
            f'if supports_flag "{subcommand}" "{flag}"; then echo "RESULT=supported";'
            f' else echo "RESULT=unsupported"; fi\n'
            f'echo "WARNDIR=${{PROBE_WARN_FLAGS_DIR}}"\n'
        )
        env = {
            **os.environ,
            'HOME': home,
            'HERMES_HOME': tmp,
            'REVENIUM_STATE_DIR': state,
            'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
        }
        r = subprocess.run(['bash', '-c', script], env=env,
                           capture_output=True, text=True, timeout=30)
        warn_dir = ''
        for line in r.stdout.splitlines():
            if line.startswith('WARNDIR='):
                warn_dir = line.split('=', 1)[1]
        log = os.path.join(state, 'revenium-metering.log')
        log_text = ''
        if os.path.exists(log):
            with open(log) as fh:
                log_text = fh.read()
        flags = sorted(os.listdir(warn_dir)) if warn_dir and os.path.isdir(warn_dir) else []
        return r.stdout, r.stderr, log_text, flags


HELP_WITH = 'echo "      --trace-type string   Trace type"'
HELP_WITHOUT = 'echo "      --squad-id string   Squad id"'


class SupportsFlagIndeterminateTests(unittest.TestCase):

    def test_flag_present_is_supported(self):
        out, _, log, flags = _run_probe(HELP_WITH)
        self.assertIn('RESULT=supported', out)
        self.assertNotIn('INDETERMINATE', log)
        self.assertEqual([], flags, 'a clean positive must not write a probe-warn flag')

    def test_genuine_absence_is_unsupported_and_silent(self):
        """The one true negative: real help, flag really not in it.

        Must stay SILENT — this is the supported older-CLI configuration, and a
        per-minute cron must not warn about it every tick.
        """
        out, _, log, flags = _run_probe(HELP_WITHOUT)
        self.assertIn('RESULT=unsupported', out)
        self.assertNotIn('INDETERMINATE', log)
        self.assertEqual([], flags, 'a genuine absence must not warn')

    def test_command_failure_is_unsupported_but_warns(self):
        out, _, log, flags = _run_probe('exit 3')
        self.assertIn('RESULT=unsupported', out,
                      'resolution must stay fail-open — behaviour is unchanged')
        self.assertIn('INDETERMINATE', log)
        self.assertIn('exit 3', log)
        self.assertEqual(1, len(flags), f'expected one probe-warn sentinel, got {flags}')

    def test_empty_output_with_success_is_unsupported_but_warns(self):
        """rc=0 and nothing printed — 123 of 513 negatives per suite run."""
        out, _, log, flags = _run_probe('exit 0')
        self.assertIn('RESULT=unsupported', out)
        self.assertIn('INDETERMINATE', log)
        self.assertIn('0 bytes', log)
        self.assertEqual(1, len(flags))

    def test_indeterminate_warn_is_rate_limited(self):
        """Ungated per-tick warns are how the log previously grew unbounded."""
        with tempfile.TemporaryDirectory(prefix='gsd-probe-rl-') as tmp:
            home = os.path.join(tmp, 'home')
            bin_dir = os.path.join(home, '.local', 'bin')
            os.makedirs(bin_dir)
            stub = os.path.join(bin_dir, 'revenium')
            with open(stub, 'w') as f:
                f.write('#!/usr/bin/env bash\nexit 3\n')
            os.chmod(stub, 0o755)
            state = os.path.join(tmp, 'state')
            script = (
                f'set -uo pipefail\n'
                f'source "{COMMON}"\n'
                f'ensure_path\n'
                f'for i in 1 2 3 4 5; do supports_flag "meter completion" "--trace-type" || true; done\n'
            )
            env = {
                **os.environ, 'HOME': home, 'HERMES_HOME': tmp,
                'REVENIUM_STATE_DIR': state,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            }
            subprocess.run(['bash', '-c', script], env=env,
                           capture_output=True, text=True, timeout=30)
            log = os.path.join(state, 'revenium-metering.log')
            text = ''
            if os.path.exists(log):
                with open(log) as fh:
                    text = fh.read()
            self.assertEqual(
                1, text.count('INDETERMINATE'),
                f'five identical indeterminate probes must warn once, not five times:\n{text}')

    def test_distinct_probes_each_get_their_own_warn(self):
        """Rate limiting is per (subcommand, flag), not global — a second
        genuinely different probe must not be muted by the first."""
        with tempfile.TemporaryDirectory(prefix='gsd-probe-2-') as tmp:
            home = os.path.join(tmp, 'home')
            bin_dir = os.path.join(home, '.local', 'bin')
            os.makedirs(bin_dir)
            stub = os.path.join(bin_dir, 'revenium')
            with open(stub, 'w') as f:
                f.write('#!/usr/bin/env bash\nexit 3\n')
            os.chmod(stub, 0o755)
            state = os.path.join(tmp, 'state')
            script = (
                f'set -uo pipefail\n'
                f'source "{COMMON}"\n'
                f'ensure_path\n'
                f'supports_flag "meter completion" "--trace-type" || true\n'
                f'supports_flag "jobs create" "--agentic-job-id" || true\n'
            )
            env = {
                **os.environ, 'HOME': home, 'HERMES_HOME': tmp,
                'REVENIUM_STATE_DIR': state,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            }
            subprocess.run(['bash', '-c', script], env=env,
                           capture_output=True, text=True, timeout=30)
            log = os.path.join(state, 'revenium-metering.log')
            text = ''
            if os.path.exists(log):
                with open(log) as fh:
                    text = fh.read()
            self.assertEqual(2, text.count('INDETERMINATE'), text)


if __name__ == '__main__':
    unittest.main()
