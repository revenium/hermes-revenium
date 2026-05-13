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
            SKILL / 'references' / 'halt-survivability.md',
            SKILL / 'scripts' / 'common.sh',
            SKILL / 'scripts' / 'install-cron.sh',
            SKILL / 'scripts' / 'uninstall-cron.sh',
            SKILL / 'scripts' / 'cron.sh',
            SKILL / 'scripts' / 'budget-check.sh',
            SKILL / 'scripts' / 'hermes-report.sh',
            SKILL / 'scripts' / 'clear-halt.sh',
            # Python module (excluded from bash -n check by *.sh glob in test_shell_scripts_have_valid_syntax)
            SKILL / 'scripts' / 'split_strategies.py',
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

    def test_marker_file_schema(self):
        """Marker fixture records contain only allow-listed keys and are < 1024 bytes."""
        import json, re
        allow_listed_required = {'muid', 'ts', 'sid', 'task_type', 'operation_type'}
        allow_listed_optional = {'turn_seq', 'agent', 'trace_id', 'model'}
        all_allowed = allow_listed_required | allow_listed_optional
        # Two markers per substantive turn (Pitfall 4): one GUARDRAIL for classification
        # work, one CHAT for the task work. muid is 33-char lowercase hex per MARK-03
        # (recipe: f"{int(time.time_ns()//1_000_000):013x}{secrets.token_hex(10)}").
        fixture_records = [
            {"muid": "01893b8a300abcdef0123456789abcdef", "ts": 1715515200.0, "sid": "test-session",
             "task_type": "code_review", "operation_type": "GUARDRAIL"},
            {"muid": "01893b8a301abcdef0123456789abcde1", "ts": 1715515201.0, "sid": "test-session",
             "task_type": "code_review", "operation_type": "CHAT"},
        ]
        for record in fixture_records:
            # MARK-02 + MARK-05: no free-form fields outside the allow-list
            extra_keys = set(record.keys()) - all_allowed
            self.assertEqual(extra_keys, set(), f'non-allow-listed keys: {extra_keys}')
            # All 5 required keys must be present
            self.assertTrue(allow_listed_required.issubset(set(record.keys())),
                            f'missing required keys: {allow_listed_required - set(record.keys())}')
            # MARK-01: single write line as compact JSONL
            line = json.dumps(record, separators=(',', ':')) + '\n'
            # MARK-02: line budget < 1024 bytes
            self.assertLess(len(line.encode('utf-8')), 1024, 'marker record exceeds 1024 bytes')
            # task_type must be lowercase snake_case matching the taxonomy label regex
            self.assertRegex(record['task_type'], r'^[a-z][a-z0-9_]{1,47}$',
                             f'task_type "{record["task_type"]}" violates label regex')
            # operation_type must be in the documented OpenInference span_kind vocabulary
            self.assertIn(record['operation_type'],
                          {'CHAT', 'GUARDRAIL', 'TOOL', 'AGENT', 'LLM', 'CHAIN',
                           'RETRIEVER', 'EMBEDDING', 'RERANKER', 'EVALUATOR', 'UNKNOWN'},
                          f'operation_type "{record["operation_type"]}" not in span_kind vocabulary')
            # MARK-03: muid must be a 33-char lowercase hex string (ULID-style sortable id)
            self.assertRegex(record['muid'], r'^[0-9a-f]{33}$',
                             f'muid "{record["muid"]}" must be 33-char lowercase hex (MARK-03)')
        # Pitfall 4 invariant: fixture must include exactly one GUARDRAIL and one CHAT
        self.assertEqual({r['operation_type'] for r in fixture_records}, {'GUARDRAIL', 'CHAT'},
                         'fixture must include exactly one GUARDRAIL and one CHAT marker per substantive turn')

    def test_split_strategies_conservation(self):
        """COMPAT-02 / TEST-03 pure-function half: sum of split numeric fields equals input
        delta byte-exact across N in {1, 2, 5, 10} with divisible AND non-divisible deltas."""
        import sys
        from decimal import Decimal
        sys.path.insert(0, str(SKILL / 'scripts'))
        from split_strategies import equal_split, INT_FIELDS, COST_FIELD
        cases = [
            # (delta, n) — RESEARCH.md Example 3 verbatim, plus n=1
            ({"input": 8000, "output": 3000, "cache_read": 100, "cache_write": 50,
              "total": 11000, "cost": "0.123456"}, 1),
            ({"input": 8000, "output": 3000, "cache_read": 100, "cache_write": 50,
              "total": 11000, "cost": "0.123456"}, 2),
            ({"input": 8000, "output": 3000, "cache_read": 100, "cache_write": 50,
              "total": 11000, "cost": "0.123456"}, 5),
            ({"input": 8001, "output": 3001, "cache_read": 101, "cache_write": 51,
              "total": 11003, "cost": "0.987654"}, 10),  # non-divisible by N
        ]
        for delta, n in cases:
            splits = equal_split(delta, n)
            self.assertEqual(len(splits), n, f"expected {n} splits for n={n}")
            for k in INT_FIELDS:
                self.assertEqual(sum(s[k] for s in splits), delta[k],
                                 f"conservation violated for {k} at n={n}")
            # Decimal-exact cost conservation
            self.assertEqual(
                sum(Decimal(s[COST_FIELD]) for s in splits),
                Decimal(delta[COST_FIELD]),
                f"cost conservation violated at n={n}",
            )

    def test_split_strategies_pluggable_shape(self):
        """D-06: the module docstring records the plug-in contract for future S3/S4
        strategies so contributors know the seam is locked-down. Contract-on-docstring
        test (cheap to maintain, hard to silently break)."""
        import sys
        sys.path.insert(0, str(SKILL / 'scripts'))
        import split_strategies
        doc = split_strategies.__doc__ or ''
        self.assertIn('def weighted_split', doc,
                      'docstring must record def weighted_split signature per D-06')
        self.assertIn('def guardrail_estimator_split', doc,
                      'docstring must record def guardrail_estimator_split signature per D-06')

    def test_prompt_ordering_invariant(self):
        """Halt-check anchor appears before the classification anchor in SKILL.md."""
        text = (SKILL / 'SKILL.md').read_text()
        halt_anchor = 'ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)'
        classify_anchor = 'FINAL ACTION — TASK CLASSIFICATION'
        self.assertIn(halt_anchor, text,
                      'halt-check anchor missing from SKILL.md — do not remove or rename it')
        self.assertIn(classify_anchor, text,
                      'classification anchor missing from SKILL.md — Phase 2 deliverable not present')
        self.assertLess(
            text.index(halt_anchor),
            text.index(classify_anchor),
            'halt-check anchor must appear before classification anchor in SKILL.md',
        )

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
