"""Phase 28 Plan 01 Task 2 — locks plugin-status.sh's exit-code contract and
status-document shape with automated tests, matching the focused-module
precedent (test_bug4_multiplex_paths.py, test_bug3_multi_profile_cron.py) so
parallel plans in later waves do not serialize on the monolithic test file.

Mirrors tests.test_repository.RepositoryTests.test_hooks_status_sh_three_verdicts's
per-branch tempfile.mkdtemp + try/finally shutil.rmtree + scratch-scripts-tree shape.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'

CONTRACT_KEYS = {'healthy', 'registered', 'liveness', 'lastChecked'}
LIVENESS_VALUES = {'unknown', 'idle', 'firing', 'stalled'}


def setup_skill_tree(hermes_home):
    """Create <hermes_home>/skills/revenium/scripts and copy common.sh +
    plugin-status.sh into it. Returns the scripts directory path."""
    scripts_dir = os.path.join(hermes_home, 'skills', 'revenium', 'scripts')
    os.makedirs(scripts_dir, exist_ok=True)
    for name in ('common.sh', 'plugin-status.sh'):
        shutil.copy(str(SKILL / 'scripts' / name), scripts_dir)
    return scripts_dir


class Phase28PluginStatusTests(unittest.TestCase):
    def test_plugin_status_sh_unregistered_missing_dir(self):
        """Exits 1 when the plugin destination directory is absent, even if
        config.yaml lists the plugin in plugins.enabled."""
        tmp = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-missing-dir-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            status_file = os.path.join(state_dir, 'plugin-status.json')
            os.makedirs(hermes_home, exist_ok=True)
            # config.yaml DOES list the plugin, but no plugins/ dir exists at all.
            with open(os.path.join(hermes_home, 'config.yaml'), 'w') as f:
                f.write('plugins:\n  enabled:\n    - revenium-classifier\n')
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_PLUGIN_STATUS_FILE': status_file,
            }
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(
                result.returncode, 1,
                f'expected exit 1 (missing dir), got {result.returncode}:\n'
                f'{result.stdout}\n{result.stderr}',
            )
            data = json.loads(Path(status_file).read_text())
            self.assertFalse(data['healthy'])
            self.assertFalse(data['registered'])
            self.assertIn('brokenAt', data)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_plugin_status_sh_unregistered_missing_config_entry(self):
        """Exits 1 when the destination directory exists but config.yaml has
        no matching plugins.enabled list item."""
        tmp = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-missing-cfg-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            status_file = os.path.join(state_dir, 'plugin-status.json')
            plugin_dir = os.path.join(hermes_home, 'plugins', 'revenium-classifier')
            os.makedirs(plugin_dir, exist_ok=True)
            # config.yaml exists and has a plugins.enabled block, but it does
            # not list revenium-classifier.
            with open(os.path.join(hermes_home, 'config.yaml'), 'w') as f:
                f.write('plugins:\n  enabled:\n    - some-other-plugin\n')
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_PLUGIN_STATUS_FILE': status_file,
            }
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(
                result.returncode, 1,
                f'expected exit 1 (missing config entry), got {result.returncode}:\n'
                f'{result.stdout}\n{result.stderr}',
            )
            data = json.loads(Path(status_file).read_text())
            self.assertFalse(data['healthy'])
            self.assertFalse(data['registered'])
            self.assertIn('brokenAt', data)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_plugin_status_sh_registered_exits_zero(self):
        """Exits 0 when both the plugin directory and the plugins.enabled
        entry hold; the status document records registered true."""
        tmp = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-registered-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            status_file = os.path.join(state_dir, 'plugin-status.json')
            plugin_dir = os.path.join(hermes_home, 'plugins', 'revenium-classifier')
            os.makedirs(plugin_dir, exist_ok=True)
            with open(os.path.join(hermes_home, 'config.yaml'), 'w') as f:
                f.write('plugins:\n  enabled:\n    - revenium-classifier\n')
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_PLUGIN_STATUS_FILE': status_file,
            }
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(
                result.returncode, 0,
                f'expected exit 0 (registered), got {result.returncode}:\n'
                f'{result.stdout}\n{result.stderr}',
            )
            data = json.loads(Path(status_file).read_text())
            self.assertTrue(data['healthy'])
            self.assertTrue(data['registered'])
            self.assertNotIn('brokenAt', data)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_plugin_status_sh_status_document_shape(self):
        """The status document is valid JSON carrying exactly the contract
        key set on both the exit-1 and exit-0 paths; healthy is a bool and
        liveness is one of the four contract values; brokenAt is present on
        the unhealthy path and absent on the healthy path."""
        # --- Unhealthy (exit-1) branch — its own isolated tempdir ----------
        tmp_unreg = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-shape-unreg-')
        try:
            hermes_home = os.path.join(tmp_unreg, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            status_file = os.path.join(state_dir, 'plugin-status.json')
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_PLUGIN_STATUS_FILE': status_file,
            }
            subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            data = json.loads(Path(status_file).read_text())
            self.assertEqual(set(data.keys()), CONTRACT_KEYS | {'brokenAt'})
            self.assertIsInstance(data['healthy'], bool)
            self.assertFalse(data['healthy'])
            self.assertIn(data['liveness'], LIVENESS_VALUES)
            self.assertIn('brokenAt', data)
        finally:
            shutil.rmtree(tmp_unreg, ignore_errors=True)

        # --- Healthy (exit-0) branch — its own isolated tempdir ------------
        tmp_reg = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-shape-reg-')
        try:
            hermes_home = os.path.join(tmp_reg, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            status_file = os.path.join(state_dir, 'plugin-status.json')
            plugin_dir = os.path.join(hermes_home, 'plugins', 'revenium-classifier')
            os.makedirs(plugin_dir, exist_ok=True)
            with open(os.path.join(hermes_home, 'config.yaml'), 'w') as f:
                f.write('plugins:\n  enabled:\n    - revenium-classifier\n')
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_PLUGIN_STATUS_FILE': status_file,
            }
            subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            data = json.loads(Path(status_file).read_text())
            self.assertEqual(set(data.keys()), CONTRACT_KEYS)
            self.assertIsInstance(data['healthy'], bool)
            self.assertTrue(data['healthy'])
            self.assertIn(data['liveness'], LIVENESS_VALUES)
            self.assertNotIn('brokenAt', data)
        finally:
            shutil.rmtree(tmp_reg, ignore_errors=True)

    def test_plugin_status_sh_never_probes_hermes_cli(self):
        """Source invariant: the script body contains no invocation of, or
        probe for, the Hermes command-line tool. Comment lines are filtered
        out first so a header comment explaining WHY the tool is not probed
        cannot itself trip the assertion."""
        text = (SKILL / 'scripts' / 'plugin-status.sh').read_text()
        code_lines = [
            line for line in text.splitlines()
            if not line.strip().startswith('#')
        ]
        code_text = '\n'.join(code_lines)
        self.assertNotIn('command -v hermes', code_text)
        self.assertNotIn('hermes gateway', code_text)
        self.assertNotIn('hermes plugins', code_text)


if __name__ == '__main__':
    unittest.main()
