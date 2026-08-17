"""quick-260817-l6o: both install paths must seed the runtime taxonomy.

The classifier reads ${TAXONOMY_FILE} in the STATE dir; the copy shipped in the
skill dir is never read at runtime. Historically only the repo-clone entry point
(root install.sh) seeded it, so tap installs — `hermes skills install` ->
references/bootstrap.sh -> skills/revenium/scripts/install.sh — left the runtime
file absent and the host classified against an empty vocabulary.

These tests run the seeding block EXTRACTED FROM THE SHIPPED SCRIPT, so they fail
if the real code changes, not merely if a copy in the test drifts.
"""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / 'skills' / 'revenium' / 'scripts' / 'install.sh'
ROOT_INSTALLER = ROOT / 'install.sh'


def _extract_seed_block(path: Path) -> str:
    """Pull the seeding section out of the shipped installer."""
    text = path.read_text()
    m = re.search(r'# 2b\. Seed the runtime taxonomies.*?\n(step "Seeding runtime taxonomies".*?done)\n',
                  text, re.DOTALL)
    return m.group(1) if m else ''


class TaxonomySeedingTests(unittest.TestCase):
    def test_both_installers_seed_the_runtime_taxonomy(self):
        """Trip-wire: the two install paths must not silently diverge again."""
        for installer in (ROOT_INSTALLER, BUNDLED):
            text = installer.read_text()
            self.assertRegex(
                text, r'task-taxonomy\.json',
                f'{installer.relative_to(ROOT)} must seed the runtime task taxonomy')
            self.assertRegex(
                text, r'job-taxonomy\.json',
                f'{installer.relative_to(ROOT)} must seed the runtime job taxonomy')

    def test_both_installers_refuse_to_overwrite_a_grown_taxonomy(self):
        """An existing taxonomy is a vocabulary the host GREW. Overwriting it would
        discard every minted label and re-open the cold-start window."""
        for installer in (ROOT_INSTALLER, BUNDLED):
            text = installer.read_text()
            self.assertTrue(
                re.search(r'\[\[\s*-f\s*"\$\{(TAXONOMY_FILE|TAXONOMY_DEST|seed_dest)\}"\s*\]\]', text)
                or re.search(r'\[\[\s*!\s*-f\s*"\$\{TAXONOMY_DEST\}"\s*\]\]', text),
                f'{installer.relative_to(ROOT)} must guard the seed copy on file existence')

    def test_bundled_seed_block_seeds_a_fresh_install(self):
        """Run the SHIPPED block against an empty state dir: both files appear."""
        block = _extract_seed_block(BUNDLED)
        self.assertTrue(block, 'seeding block not found in the bundled installer')
        with tempfile.TemporaryDirectory() as tmp:
            skill, state = Path(tmp) / 'skill', Path(tmp) / 'state'
            skill.mkdir(); state.mkdir()
            (skill / 'task-taxonomy.json').write_text('{"labels": {"seeded_task": {}}}')
            (skill / 'job-taxonomy.json').write_text('{"labels": {"seeded_job": {}}}')
            script = (f'set -uo pipefail\nstep() {{ :; }}\nwarn() {{ :; }}\n'
                      f'SKILL_DIR="{skill}"\nTAXONOMY_FILE="{state}/task-taxonomy.json"\n'
                      f'JOB_TAXONOMY_FILE="{state}/job-taxonomy.json"\n{block}\n')
            r = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('seeded_task', (state / 'task-taxonomy.json').read_text())
            self.assertIn('seeded_job', (state / 'job-taxonomy.json').read_text())

    def test_bundled_seed_block_never_clobbers_an_existing_taxonomy(self):
        """Run the SHIPPED block against a grown vocabulary: it must survive intact."""
        block = _extract_seed_block(BUNDLED)
        with tempfile.TemporaryDirectory() as tmp:
            skill, state = Path(tmp) / 'skill', Path(tmp) / 'state'
            skill.mkdir(); state.mkdir()
            (skill / 'task-taxonomy.json').write_text('{"labels": {"seeded_task": {}}}')
            (skill / 'job-taxonomy.json').write_text('{"labels": {"seeded_job": {}}}')
            grown = '{"labels": {"weekly_pr_review": {}, "prod_log_triage": {}}}'
            (state / 'task-taxonomy.json').write_text(grown)
            script = (f'set -uo pipefail\nstep() {{ :; }}\nwarn() {{ :; }}\n'
                      f'SKILL_DIR="{skill}"\nTAXONOMY_FILE="{state}/task-taxonomy.json"\n'
                      f'JOB_TAXONOMY_FILE="{state}/job-taxonomy.json"\n{block}\n')
            r = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((state / 'task-taxonomy.json').read_text(), grown,
                             'a grown taxonomy must never be overwritten by the installer')
            # the absent one is still seeded in the same run
            self.assertIn('seeded_job', (state / 'job-taxonomy.json').read_text())

    def test_bundled_seed_block_tolerates_a_missing_seed(self):
        """A skill dir without seeds must warn and continue, not abort the install."""
        block = _extract_seed_block(BUNDLED)
        with tempfile.TemporaryDirectory() as tmp:
            skill, state = Path(tmp) / 'skill', Path(tmp) / 'state'
            skill.mkdir(); state.mkdir()
            script = (f'set -uo pipefail\nstep() {{ :; }}\nwarn() {{ echo "WARN $*"; }}\n'
                      f'SKILL_DIR="{skill}"\nTAXONOMY_FILE="{state}/task-taxonomy.json"\n'
                      f'JOB_TAXONOMY_FILE="{state}/job-taxonomy.json"\n{block}\n')
            r = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse((state / 'task-taxonomy.json').exists())


if __name__ == '__main__':
    unittest.main()
