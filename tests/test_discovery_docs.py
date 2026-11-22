"""Discovery docs contracts; no installation, credentials or hosted API calls."""
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DiscoveryDocsTests(unittest.TestCase):
    def test_install_first_and_disclosure(self):
        text = (ROOT / "README.md").read_text()
        self.assertIn("Langfuse traces your agent. Revenium governs it", text)
        self.assertLess(text.index("hermes skills install"), text.index("## What you get"))
        self.assertIn("TODO(John)", text)
        self.assertIn("A blanket “model free-text is never sent” claim would be false", text)
        self.assertIn("candidate_downstream_outcome", text)
        self.assertIn("docs/demo.gif", text)

    def test_evaluator_budget_matches_code(self):
        code = ROOT / "skills/revenium/plugins/revenium-classifier/classifier.py"
        tree = ast.parse(code.read_text())
        values = [node.value.value for node in tree.body
                  if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                  and any(isinstance(t, ast.Name) and t.id == "_EVAL_MAX_TOKENS"
                          for t in node.targets)]
        self.assertEqual(len(values), 1)
        doc = (ROOT / "docs/value-and-roi.md").read_text()
        self.assertIn(f"| Max response tokens | {values[0]} | `_EVAL_MAX_TOKENS` |", doc)
        self.assertIn(f"{values[0]} max tokens", doc)

    def test_exact_readme_verification_snippet_in_isolated_home(self):
        text = (ROOT / "README.md").read_text()
        blocks = re.findall(r"```bash\n(.*?)```", text, re.S)
        snippet = next(b for b in blocks if 'scripts/plugin-status.sh' in b)
        self.assertEqual(len(snippet.strip().splitlines()), 3)
        # The two status scripts are doubles: this exercises the published shell
        # snippet and real JSON assertion, not classifier/hook health themselves.
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            scripts = home / "skills/revenium/scripts"
            scripts.mkdir(parents=True)
            for name in ("plugin-status.sh", "hooks-status.sh"):
                (scripts / name).write_text("#!/bin/bash\nprintf 'fixture status OK\\n'\n")
            state = home / "state/revenium"
            state.mkdir(parents=True)
            status = state / "guardrail-status.json"
            status.write_text(json.dumps({"lastChecked": "fixture", "rules": [{}], "halted": False}))
            env = {**os.environ, "HERMES_HOME": td}
            result = subprocess.run(["bash", "-e", "-c", snippet], env=env,
                                    text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Guardrail snapshot: fixture halted: False", result.stdout)
            status.write_text(json.dumps({"lastChecked": "fixture", "rules": []}))
            result = subprocess.run(["bash", "-e", "-c", snippet], env=env,
                                    text=True, capture_output=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("No populated guardrail snapshot yet", result.stderr)

    def test_community_files_exist(self):
        for name in ("LICENSE", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md",
                     "docs/demo-script.md", "docs/release-notes-v0.1.0.md"):
            self.assertTrue((ROOT / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
