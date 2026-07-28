"""Phase 28 Plan 02 (Task 1): install-plugin.sh's post-install self-assertion.

D-03: install-plugin.sh must re-verify its own result (plugin placement +
plugins.enabled membership) after its write steps, using the same checks a
fresh reader would use, and exit non-zero if either check fails — rather than
trusting the write steps' own return values and reporting a success it did
not achieve. The assertion must run ONLY on the non-dry-run path.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'


def _setup_skill_tree(hermes_home):
    """Clone the fixture shape from test_repository.py's
    test_install_plugin_sh_happy_path: a scratch skills/revenium tree with
    scripts/ (common.sh + install-plugin.sh) and the real plugin files."""
    scripts_dir = os.path.join(hermes_home, 'skills', 'revenium', 'scripts')
    plugins_src = os.path.join(hermes_home, 'skills', 'revenium', 'plugins',
                                'revenium-classifier')
    os.makedirs(scripts_dir, exist_ok=True)
    os.makedirs(plugins_src, exist_ok=True)
    for name in ('plugin.yaml', '__init__.py', 'classifier.py'):
        shutil.copy(SKILL / 'plugins' / 'revenium-classifier' / name, plugins_src)
    shutil.copy(SKILL / 'scripts' / 'common.sh', scripts_dir)
    shutil.copy(SKILL / 'scripts' / 'install-plugin.sh', scripts_dir)
    return scripts_dir


def _run_install(env, extra_args=None):
    hermes_home = env['HERMES_HOME']
    script = os.path.join(hermes_home, 'skills', 'revenium', 'scripts', 'install-plugin.sh')
    args = ['bash', script] + list(extra_args or [])
    return subprocess.run(args, env=env, capture_output=True, text=True, timeout=15)


class InstallAssertionTests(unittest.TestCase):

    def test_install_plugin_assertion_happy_path(self):
        """A normal --no-restart run against a clean scratch home exits 0,
        and the assertion's success line appears on stdout."""
        tmp = tempfile.mkdtemp(prefix='gsd-assert-happy-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            _setup_skill_tree(hermes_home)
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': os.path.join(hermes_home, 'state', 'revenium'),
            }
            result = _run_install(env, ['--no-restart'])
            self.assertEqual(result.returncode, 0,
                f'expected exit 0: stdout={result.stdout}\nstderr={result.stderr}')
            self.assertIn('Post-install assertion passed', result.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_install_plugin_assertion_dry_run_unchanged(self):
        """--dry-run still exits 0, still prints the pre-existing dry-run
        markers, and still performs zero filesystem mutation — the
        assertion must never execute on this path."""
        tmp = tempfile.mkdtemp(prefix='gsd-assert-dryrun-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            _setup_skill_tree(hermes_home)
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': os.path.join(hermes_home, 'state', 'revenium'),
            }
            result = _run_install(env, ['--dry-run'])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('[dry-run]', result.stdout)
            self.assertIn('dry-run — nothing was changed', result.stdout)
            # The assertion must never run on the dry-run path.
            self.assertNotIn('Post-install assertion', result.stdout)
            self.assertFalse(os.path.exists(os.path.join(hermes_home, 'plugins')),
                              'dry-run must not create the plugin dest dir')
            self.assertFalse(os.path.exists(os.path.join(hermes_home, 'config.yaml')),
                              'dry-run must not create config.yaml')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_install_plugin_assertion_fails_loudly(self):
        """A sabotaged run — config.yaml pre-seeded without the plugin entry
        and made unwritable — exits non-zero with stderr naming what failed.
        The assertion (or the write step it guards) must never downgrade
        this to a warning and continue."""
        tmp = tempfile.mkdtemp(prefix='gsd-assert-sabotage-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            _setup_skill_tree(hermes_home)
            os.makedirs(hermes_home, exist_ok=True)
            config = os.path.join(hermes_home, 'config.yaml')
            with open(config, 'w') as f:
                f.write('approvals:\n  mode: manual\n')
            # Deny write access to the file the patch step must rewrite —
            # the entry is absent, so the "already enabled" fast path cannot
            # short-circuit and the script must attempt (and fail) the write.
            os.chmod(config, 0o444)
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': os.path.join(hermes_home, 'state', 'revenium'),
            }
            try:
                result = _run_install(env, ['--no-restart'])
                self.assertNotEqual(result.returncode, 0,
                    'sabotaged run must not report success')
                self.assertTrue(result.stderr.strip(),
                    'a failed run must emit a diagnostic on stderr')
                self.assertIn(config, result.stderr,
                    'stderr must name the path that failed the check')
            finally:
                os.chmod(config, 0o644)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_install_plugin_assertion_rerun_idempotent(self):
        """A re-run over an already-correct install exits 0 (idempotency
        preserved), and the assertion passes both times."""
        tmp = tempfile.mkdtemp(prefix='gsd-assert-rerun-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            _setup_skill_tree(hermes_home)
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': os.path.join(hermes_home, 'state', 'revenium'),
            }
            first = _run_install(env, ['--no-restart'])
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn('Post-install assertion passed', first.stdout)

            second = _run_install(env, ['--no-restart'])
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn('Post-install assertion passed', second.stdout)

            config = os.path.join(hermes_home, 'config.yaml')
            with open(config) as f:
                content = f.read()
            self.assertEqual(content.count('- revenium-classifier'), 1,
                              're-run must not duplicate the plugins.enabled entry')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
