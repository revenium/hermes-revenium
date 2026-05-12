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
            SKILL / 'task-taxonomy.json',
            SKILL / 'references' / 'task-taxonomy.md',
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

    def test_taxonomy_file_schema(self):
        """Seed task-taxonomy.json has correct schema and all labels match the regex."""
        import json, re
        taxonomy_path = SKILL / 'task-taxonomy.json'
        self.assertTrue(taxonomy_path.exists(), 'task-taxonomy.json missing from skill root')
        data = json.loads(taxonomy_path.read_text())
        self.assertIn('labels', data, 'taxonomy missing top-level "labels" key')
        labels = data['labels']
        self.assertIsInstance(labels, dict, '"labels" must be a dict')
        label_regex = re.compile(r'^[a-z][a-z0-9_]{1,47}$')
        forbidden = {'ack', 'acknowledgment', 'greeting', 'confirmation', 'hello', 'thanks'}
        expected_labels = ['research', 'analysis', 'generation', 'review',
                           'code_review', 'refactor', 'planning', 'debugging']
        self.assertEqual(list(labels.keys()), expected_labels,
                         'seed taxonomy labels must match D-06 order exactly')
        for label, schema in labels.items():
            self.assertRegex(label, label_regex, f'label "{label}" fails regex')
            self.assertNotIn(label, forbidden, f'forbidden label "{label}" in seed taxonomy')
            self.assertIn('description', schema, f'label "{label}" missing description')
            self.assertIn('examples', schema, f'label "{label}" missing examples')
            self.assertIsInstance(schema['description'], str, f'label "{label}" description must be str')
            self.assertIsInstance(schema['examples'], list, f'label "{label}" examples must be list')

    # Single-writer round-trip per Phase 2 SC5; concurrent multi-writer fixture deferred to Phase 3 (RESEARCH.md note: v1 has single-writer-per-session).
    def test_taxonomy_atomic_write_pattern(self):
        """Atomic write pattern (flock + write-to-tmp + os.rename) never produces partial reads (Phase 2 SC5)."""
        import json, os, shutil, subprocess, sys, tempfile

        reader_src = (
            "import json, sys\n"
            "path = sys.argv[1]\n"
            "try:\n"
            "    with open(path, 'rb') as f:\n"
            "        data = f.read()\n"
            "    parsed = json.loads(data)\n"
            "    n = len(parsed.get('labels', {}))\n"
            "    print(f'OK:{n}')\n"
            "    sys.exit(0)\n"
            "except Exception as e:\n"
            "    print(f'PARTIAL:{e}')\n"
            "    sys.exit(1)\n"
        )

        tmpdir = tempfile.mkdtemp(prefix="gsd-atomic-")
        try:
            target = os.path.join(tmpdir, "task-taxonomy.json")

            # Seed: write initial state via atomic pattern
            pre_state = {"labels": {"seed": {"description": "seed", "examples": ["a", "b"]}}}
            with tempfile.NamedTemporaryFile("w", dir=tmpdir, delete=False, suffix=".tmp") as tmp:
                json.dump(pre_state, tmp, indent=2, ensure_ascii=True)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmpname = tmp.name
            os.rename(tmpname, target)

            # Reader must see complete pre-state (1 label)
            result = subprocess.run(
                [sys.executable, "-c", reader_src, target],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0,
                             f"reader failed on pre-state: {result.stdout} {result.stderr}")
            self.assertTrue(result.stdout.startswith("OK:1"),
                            f"expected OK:1, got: {result.stdout!r}")
            self.assertNotIn("PARTIAL:", result.stdout)

            # Second atomic write: add a second label
            import fcntl
            post_state = {
                "labels": {
                    "seed": {"description": "seed", "examples": ["a", "b"]},
                    "minted": {"description": "minted", "examples": ["c", "d"]},
                }
            }
            with open(target, "r+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                with tempfile.NamedTemporaryFile("w", dir=tmpdir, delete=False, suffix=".tmp") as tmp:
                    json.dump(post_state, tmp, indent=2, ensure_ascii=True)
                    tmp.flush()
                    os.fsync(tmp.fileno())
                    tmpname = tmp.name
                os.rename(tmpname, target)

            # Reader must see complete post-state (2 labels)
            result = subprocess.run(
                [sys.executable, "-c", reader_src, target],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0,
                             f"reader failed on post-state: {result.stdout} {result.stderr}")
            self.assertTrue(result.stdout.startswith("OK:2"),
                            f"expected OK:2, got: {result.stdout!r}")
            self.assertNotIn("PARTIAL:", result.stdout)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

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
