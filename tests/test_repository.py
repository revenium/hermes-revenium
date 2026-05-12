import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'


class RepositoryTests(unittest.TestCase):
    def test_expected_files_exist(self):
        expected = [
            ROOT / 'README.md',
            ROOT / 'docs' / 'installation.md',
            ROOT / 'examples' / 'setup-local.sh',
            SKILL / 'SKILL.md',
            SKILL / 'references' / 'setup.md',
            SKILL / 'references' / 'troubleshooting.md',
            SKILL / 'scripts' / 'common.sh',
            SKILL / 'scripts' / 'install-cron.sh',
            SKILL / 'scripts' / 'uninstall-cron.sh',
            SKILL / 'scripts' / 'cron.sh',
            SKILL / 'scripts' / 'budget-check.sh',
            SKILL / 'scripts' / 'hermes-report.sh',
            SKILL / 'scripts' / 'clear-halt.sh',
        ]
        for path in expected:
            self.assertTrue(path.exists(), f'missing {path}')

    def test_skill_frontmatter_has_hermes_metadata(self):
        text = (SKILL / 'SKILL.md').read_text()
        self.assertIn('name: revenium', text)
        self.assertIn('metadata:', text)
        self.assertIn('hermes:', text)
        self.assertIn('category: devops', text)

    def test_no_legacy_branding_left(self):
        offenders = []
        for path in ROOT.rglob('*'):
            if not path.is_file():
                continue
            if path.suffix not in {'.md', '.sh', '.py', '.txt', '.json', '.yml', '.yaml'}:
                continue
            if path.name == 'test_repository.py':
                continue
            text = path.read_text(errors='ignore')
            if re.search(r'OpenClaw|openclaw|ClawHub|clawhub', text):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], f'found legacy branding in: {offenders}')

    def test_runtime_paths_are_hermes_native(self):
        text = (SKILL / 'scripts' / 'common.sh').read_text()
        self.assertIn('.hermes', text)
        self.assertIn('state/revenium', text)
        self.assertNotIn('.openclaw', text)
        self.assertIn('task-taxonomy.json', text)
        self.assertIn('TAXONOMY_FILE=', text)
        self.assertRegex(text, r'MARKERS_DIR="\$\{REVENIUM_MARKERS_DIR:-\$\{STATE_DIR\}/markers\}"')
        self.assertIn('markers', text)

    def test_shell_scripts_have_valid_syntax(self):
        scripts = sorted((SKILL / 'scripts').glob('*.sh'))
        self.assertTrue(scripts, 'no shell scripts found')
        for script in scripts:
            result = subprocess.run(
                ['bash', '-n', str(script)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                result.returncode,
                0,
                f'syntax error in {script.name}: {result.stderr}',
            )


if __name__ == '__main__':
    unittest.main()
