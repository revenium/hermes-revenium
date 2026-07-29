"""install-plugin.sh must not corrupt config.yaml when `plugins.enabled`
already exists in a non-block shape.

Regression for a live incident on 2026-07-28. Two profiles carried
`plugins:\\n  enabled: []` — a complete empty FLOW sequence. The patcher matched
`enabled:` and appended a block item beneath it:

    plugins:
      enabled: []

        - revenium-classifier

which is invalid YAML. Hermes' response to an unparseable config is not to
ignore the plugins key — it discards the ENTIRE config and falls back to
defaults, so every unrelated user override (auxiliary providers, fallback
chain, model settings) silently stops applying. The blast radius of a
one-line plugin edit was the whole profile's configuration.

The pre-existing suite missed it because every fixture started from either no
config at all or a block-form `enabled:` list, both of which the patcher
handles. These tests cover the shapes it did not.

Validated structurally rather than with a YAML parse: PyYAML is not available
in this repo's stdlib-only test environment, and the invalid output is
precisely characterised by "a flow sequence or scalar followed by block items".
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'


def _setup_skill_tree(hermes_home):
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


def _run_install(hermes_home):
    script = os.path.join(hermes_home, 'skills', 'revenium', 'scripts', 'install-plugin.sh')
    env = {
        **os.environ,
        'HERMES_HOME': hermes_home,
        'REVENIUM_STATE_DIR': os.path.join(hermes_home, 'state', 'revenium'),
    }
    return subprocess.run(['bash', script, '--no-restart'], env=env,
                          capture_output=True, text=True, timeout=15)


def _assert_no_dangling_block_items(testcase, text, label):
    """Fail if a `key: <flow-or-scalar>` line is followed by block sequence
    items — the exact invalid shape the incident produced."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r'^(\s*)enabled:(.*)$', line)
        if not m:
            continue
        value = m.group(2).strip()
        if not value or value.startswith('#'):
            continue  # block form opener — legal
        # `enabled:` carries an inline value; no block items may follow it.
        for follower in lines[i + 1:]:
            if not follower.strip():
                continue
            testcase.assertFalse(
                re.match(r'^\s+-\s', follower),
                f'{label}: `enabled: {value}` is followed by block item '
                f'{follower!r} — invalid YAML; Hermes discards the whole '
                f'config and falls back to defaults.\n---\n{text}\n---',
            )
            break


class InstallPluginYamlShapeTests(unittest.TestCase):

    def _run_with_config(self, config_text):
        tmp = tempfile.mkdtemp(prefix='gsd-install-yaml-')
        self.addCleanup(shutil.rmtree, tmp, True)
        hermes_home = os.path.join(tmp, '.hermes')
        _setup_skill_tree(hermes_home)
        cfg = Path(hermes_home) / 'config.yaml'
        cfg.write_text(config_text, encoding='utf-8')
        result = _run_install(hermes_home)
        return result, cfg.read_text(encoding='utf-8')

    def test_empty_flow_sequence_is_converted_not_appended(self):
        """`enabled: []` -> block form containing the plugin.

        The exact production shape that broke two live profiles."""
        result, out = self._run_with_config(
            'timezone: America/New_York\n'
            'plugins:\n'
            '  enabled: []\n'
            'platform_toolsets:\n'
            '  cli:\n'
            '    - clarify\n'
        )
        self.assertEqual(result.returncode, 0,
                         f'exit {result.returncode}: {result.stdout}\n{result.stderr}')
        _assert_no_dangling_block_items(self, out, 'empty flow')
        self.assertNotIn('enabled: []', out,
                         f'empty flow sequence must be rewritten, not kept:\n{out}')
        self.assertRegex(out, r'enabled:\n\s+- revenium-classifier',
                         f'plugin must be a block item under enabled:\n{out}')
        # Unrelated keys must survive untouched — the incident's real damage
        # was to configuration that had nothing to do with plugins.
        self.assertIn('timezone: America/New_York', out)
        self.assertIn('- clarify', out)

    def test_populated_flow_sequence_preserves_existing_entries(self):
        """`enabled: [other]` -> block form with BOTH entries.

        Appending to a populated flow sequence is the same invalid shape, and
        silently dropping the pre-existing plugin would be its own outage."""
        result, out = self._run_with_config(
            'plugins:\n'
            '  enabled: [hermes-achievements]\n'
        )
        self.assertEqual(result.returncode, 0,
                         f'exit {result.returncode}: {result.stdout}\n{result.stderr}')
        _assert_no_dangling_block_items(self, out, 'populated flow')
        self.assertIn('hermes-achievements', out,
                      f'pre-existing plugin must not be dropped:\n{out}')
        self.assertIn('revenium-classifier', out)

    def test_scalar_enabled_is_replaced(self):
        """`enabled: null` is not a list; block items must not be appended."""
        result, out = self._run_with_config(
            'plugins:\n'
            '  enabled: null\n'
        )
        self.assertEqual(result.returncode, 0,
                         f'exit {result.returncode}: {result.stdout}\n{result.stderr}')
        _assert_no_dangling_block_items(self, out, 'scalar')
        self.assertNotIn('enabled: null', out)
        self.assertRegex(out, r'enabled:\n\s+- revenium-classifier')

    def test_block_form_still_appends(self):
        """The pre-existing block-form path must be unchanged."""
        result, out = self._run_with_config(
            'plugins:\n'
            '  enabled:\n'
            '    - hermes-achievements\n'
        )
        self.assertEqual(result.returncode, 0,
                         f'exit {result.returncode}: {result.stdout}\n{result.stderr}')
        _assert_no_dangling_block_items(self, out, 'block form')
        self.assertIn('- hermes-achievements', out)
        self.assertIn('- revenium-classifier', out)

    def test_rerun_on_converted_config_is_idempotent(self):
        """After conversion the file is block form, so a second run takes the
        ordinary append path and must not duplicate the entry."""
        tmp = tempfile.mkdtemp(prefix='gsd-install-yaml-rerun-')
        self.addCleanup(shutil.rmtree, tmp, True)
        hermes_home = os.path.join(tmp, '.hermes')
        _setup_skill_tree(hermes_home)
        cfg = Path(hermes_home) / 'config.yaml'
        cfg.write_text('plugins:\n  enabled: []\n', encoding='utf-8')
        self.assertEqual(_run_install(hermes_home).returncode, 0)
        first = cfg.read_text(encoding='utf-8')
        self.assertEqual(_run_install(hermes_home).returncode, 0)
        second = cfg.read_text(encoding='utf-8')
        self.assertEqual(first, second, 'second run must be a no-op')
        self.assertEqual(second.count('- revenium-classifier'), 1,
                         f'entry duplicated on re-run:\n{second}')


if __name__ == '__main__':
    unittest.main()
